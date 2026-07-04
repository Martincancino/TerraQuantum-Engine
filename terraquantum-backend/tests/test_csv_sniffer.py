"""F2 — Sniffer universal de capa física (csv_sniffer_service).

Fija el contrato del SniffReport: cada dimensión (encoding / separador /
decimal / preámbulo / filas rotas) se detecta CON EVIDENCIA y confianza, nunca
en silencio. Incluye el caso real del corpus: LdM crudo Excel-ES con preámbulo
de proyecto, ';' + coma decimal (el archivo del usuario que motivó F2).

También fija la INTEGRACIÓN: import_gravity_csv_v1 sobre el CSV crudo CON
preámbulo (antes: el preámbulo se convertía en encabezado basura y el import
moría; ahora: se salta con aviso y el dato parsea correcto).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.csv_sniffer_service import (  # noqa: E402
    AmbiguousDelimiterError,
    decimal_verdict_for_lines,
    detect_encoding,
    detect_separator,
    sniff_csv,
)
from services.gravity_import_service import (  # noqa: E402
    _read_csv_dataframe,
    import_gravity_csv_v1,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CORPUS = os.path.join(FIXTURES, "csv_reales")
LDM_CRUDO = os.path.join(CORPUS, "LdM_gravimetria_CRUDO_usuario.csv")

_LDM_COLUMN_MAP = {
    "x": "Este_UTM",
    "y": "Norte_UTM",
    "elevation": "Cota_msnm",
    "gravity_value": "Anom_Bouguer_mGal",
    "station_id": "Estacion",
    "unit": "mGal",
    "gravity_type": "bouguer_anomaly",
}


def _write(tmp_path, name, payload, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(payload.encode(encoding) if isinstance(payload, str) else payload)
    return str(p)


def _clean_rows(n=14, sep=",", decimal="."):
    def num(x):
        return f"{x:.1f}".replace(".", decimal)
    rows = [sep.join(["x_m", "z_m", "bouguer_anomaly", "unit", "gravity_type"])]
    for i in range(n):
        rows.append(sep.join([
            num(i * 100.0), num((i % 5) * 90.0), num(1.0 + 0.13 * i),
            "mGal", "bouguer_anomaly",
        ]))
    return "\n".join(rows) + "\n"


# ── 1. Encoding: UTF-8 / BOM / UTF-16 / cp1252 / latin-1 ─────────────────────
def test_encoding_utf8_plain():
    det = detect_encoding("x,y\n1,2\n".encode("utf-8"))
    assert det.value == "utf-8-sig" and det.confidence == "high"


def test_encoding_utf8_bom():
    det = detect_encoding(b"\xef\xbb\xbf" + "x,y\n1,2\n".encode("utf-8"))
    assert det.value == "utf-8-sig" and det.confidence == "high"
    assert "BOM" in det.evidence


def test_encoding_utf16_bom():
    det = detect_encoding("x,y\nñandú,2\n".encode("utf-16"))
    assert det.value == "utf-16" and det.confidence == "high"


def test_encoding_cp1252():
    # 'ñ'=0xF1 y '”'=0x94: 0x94 es cp1252 (no definido igual en utf-8) →
    # utf-8 falla, cp1252 decodifica.
    det = detect_encoding("Estación,cañón”\n1,2\n".encode("cp1252"))
    assert det.value in ("cp1252", "latin-1")
    assert det.value == "cp1252", det.evidence
    assert any(d["value"] == "utf-8" for d in det.discarded)


def test_encoding_never_fails():
    det = detect_encoding(bytes(range(256)))
    assert det.value in ("utf-8-sig", "utf-16", "cp1252", "latin-1")


# ── 2. Separador por consistencia modal ──────────────────────────────────────
@pytest.mark.parametrize("sep,expected", [(",", ","), (";", ";"), ("\t", "\t"), ("|", "|")])
def test_separator_detection(sep, expected):
    lines = _clean_rows(sep=sep).splitlines()
    det, eff = detect_separator(lines)
    assert eff == expected
    assert det.confidence in ("high", "medium")


def test_separator_semicolon_beats_decimal_comma():
    """Excel-ES: ';' separador + ',' decimal — ambos consistentes, gana ';'."""
    lines = _clean_rows(sep=";", decimal=",").splitlines()
    det, eff = detect_separator(lines)
    assert eff == ";"


def test_separator_single_column():
    det, eff = detect_separator(["gravedad", "1.5", "2.5", "3.5"])
    assert eff is None and det.confidence == "low"


# ── 3. Decimal generalizado (bug e7d2858) ────────────────────────────────────
def test_decimal_comma_all_decimal():
    lines = ["a;b", "362472,4;6008599,5", "-,1396;,05"]
    assert decimal_verdict_for_lines(lines, ";") == "comma"


def test_decimal_thousands_is_ambiguous():
    assert decimal_verdict_for_lines(["a;b", "1,234,567;2"], ";") == "ambiguous"


def test_decimal_comma_sep_always_point():
    assert decimal_verdict_for_lines(["a,b", "1.5,2.5"], ",") == "point"


def test_decimal_tab_with_comma_decimal():
    """La generalización cubre tab (antes solo ';')."""
    assert decimal_verdict_for_lines(["a\tb", "1,5\t2,5"], "\t") == "comma"


# ── 4. Preámbulo + filas rotas (el caso REAL del corpus) ─────────────────────
def test_sniff_ldm_crudo_usuario_full_report():
    """El CSV crudo del usuario de LdM: 2 líneas de preámbulo, ';', coma decimal."""
    rep = sniff_csv(LDM_CRUDO)
    assert rep.encoding.value == "utf-8-sig"
    assert rep.separator.value == ";"
    assert rep.decimal.value == ","
    assert rep.preamble_count == 2, rep.preamble_lines
    assert rep.preamble_lines[0]["line_number"] == 1
    assert "Proyecto" in rep.preamble_lines[0]["text"]
    assert rep.header_line_number == 3
    assert rep.header_columns[:3] == ["Estacion", "Este_UTM", "Norte_UTM"]
    assert rep.broken_row_count == 0
    d = rep.to_dict()
    assert d["version"] == "csv_sniff_v1" and d["preamble_count"] == 2


def test_sniff_clean_csv_no_preamble(tmp_path):
    rep = sniff_csv(_write(tmp_path, "clean.csv", _clean_rows()))
    assert rep.preamble_count == 0
    assert rep.header_line_number == 1
    assert rep.broken_row_count == 0


def test_sniff_tqpkg_hash_lines_are_preamble(tmp_path):
    text = (
        "#TQPKG/1\n"
        '#CONFIG {"data_type":"gravity","lat":null,"nx":0,"ny":0}\n'
        "#BOREHOLES []\n"
        + _clean_rows()
    )
    rep = sniff_csv(_write(tmp_path, "pkg.tqpkg.csv", text))
    assert rep.preamble_count == 3
    assert all(p["reason"] == "directiva '#'" for p in rep.preamble_lines)
    assert rep.header_line_number == 4


def test_sniff_broken_rows_reported_with_line_numbers(tmp_path):
    rows = _clean_rows(n=14).splitlines()
    rows.insert(5, "esta,fila,esta")           # 3 campos vs 5 → rota
    rows.insert(9, "a,b,c,d,e,f,g")            # 7 campos vs 5 → rota
    rep = sniff_csv(_write(tmp_path, "broken.csv", "\n".join(rows) + "\n"))
    assert rep.broken_row_count == 2
    lines_reported = {b["line_number"] for b in rep.broken_rows}
    assert lines_reported == {6, 10}
    assert rep.broken_rows[0]["expected_fields"] == 5


def test_sniff_never_raises_on_garbage(tmp_path):
    p = tmp_path / "garbage.bin"
    p.write_bytes(bytes(range(256)) * 10)
    rep = sniff_csv(str(p))          # no debe lanzar
    assert rep.encoding.value in ("utf-8-sig", "utf-16", "cp1252", "latin-1")

    rep2 = sniff_csv(str(tmp_path / "no_existe.csv"))
    assert rep2.warnings, "archivo inexistente → warning, no excepción"


# ── 5. Integración: _read_csv_dataframe salta el preámbulo ───────────────────
def test_read_dataframe_ldm_crudo_with_preamble():
    """ANTES: el preámbulo era el encabezado → columnas basura. AHORA: datos."""
    df, warns = _read_csv_dataframe(LDM_CRUDO)
    assert "Este_UTM" in df.columns, list(df.columns)
    assert abs(float(df["Este_UTM"].iloc[0]) - 362472.4) < 1e-3
    assert abs(float(df["Anom_Bouguer_mGal"].iloc[0]) - (-11.5534)) < 1e-3
    assert any("preámbulo" in w for w in warns), warns


def test_read_dataframe_utf16_excel_unicode(tmp_path):
    """Export 'Texto Unicode' de Excel (UTF-16 + tab): antes mojibake latin-1."""
    path = _write(tmp_path, "u16.csv", _clean_rows(sep="\t"), encoding="utf-16")
    df, warns = _read_csv_dataframe(path)
    assert "x_m" in df.columns and len(df) == 14
    assert any("utf-16" in w.lower() for w in warns), warns


def test_read_dataframe_preamble_ambiguous_decimal_still_raises(tmp_path):
    """Preámbulo + comas de miles → sigue siendo error claro, jamás basura."""
    rows = ["Proyecto: X;;;", "Estacion;Este;Norte;Bouguer"]
    for i in range(14):
        rows.append(f"P{i};1,234,{500 + i};6,008,{599 + i};-11,55")
    path = _write(tmp_path, "amb.csv", "\n".join(rows) + "\n")
    with pytest.raises(AmbiguousDelimiterError):
        _read_csv_dataframe(path)


# ── 6. Integración E2E: import del CSV crudo REAL con preámbulo ──────────────
def test_import_ldm_crudo_usuario_end_to_end():
    """El archivo que motivó F2: preámbulo + ';' + coma decimal + headers ES.

    Con column_map manual (el auto-mapeo ES es F2.2) el import completo debe
    dar dato LIMPIO: spans ~8.7 km, no fragmentos (la corrupción histórica
    daba E≈531).
    """
    res = import_gravity_csv_v1(
        LDM_CRUDO, strict=False, allow_g_raw=True,
        data_kind="gravity", column_map=dict(_LDM_COLUMN_MAP),
    )
    assert res.status == "ok", res.errors
    assert len(res.observations) >= 100
    # Survey completo de LdM: ~13.9 km E × ~15.1 km N (la corrupción histórica
    # daba E≈531 → spans de metros; el guardián es el ORDEN de magnitud).
    xs = [o.x_m for o in res.observations]
    zs = [o.z_m for o in res.observations]
    assert 5_000 < (max(xs) - min(xs)) < 25_000
    assert 5_000 < (max(zs) - min(zs)) < 25_000
    # El sniff viaja en el resultado (contrato F2: siempre avisar).
    assert res.sniff_report is not None
    assert res.sniff_report["preamble_count"] == 2
    assert res.sniff_report["separator"]["value"] == ";"
    assert any("preámbulo" in w for w in res.warnings)


def test_import_clean_csv_sniff_attached_without_new_warnings(tmp_path):
    """CSV limpio: sniff adjunto pero SIN avisos nuevos (byte-idéntico)."""
    path = _write(tmp_path, "clean.csv", _clean_rows())
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "ok", res.errors
    assert res.sniff_report is not None
    assert res.sniff_report["preamble_count"] == 0
    assert not any("preámbulo" in w for w in res.warnings)
