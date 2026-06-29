"""BUG decimal-coma (corrupción silenciosa) — ingesta de CSV crudo real chileno.

Los tests previos de ingesta usaban CSV LIMPIOS (punto decimal, headers en inglés) y
por eso NO detectaban este bug: un CSV ';'-delimitado con coma decimal (Excel-ES,
"362472,4;6008599,5;...") se partía con regex [,;] → cada decimal en 2 columnas → fila
basura (E≈531, g=0) sellada "Calidad GOOD".

INVARIANTE: la ingesta entrega dato LIMPIO, o un ERROR CLARO, pero JAMÁS un número
silenciosamente equivocado. Aquí se fija el parseo correcto + la byte-identidad de los
caminos históricos + el error accionable de los casos no resueltos (miles, texto).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gravity_import_service import (  # noqa: E402
    AmbiguousDelimiterError,
    _read_csv_dataframe,
    _resolve_sep_decimal,
    import_gravity_csv_v1,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
LDM_FIXTURE = os.path.join(FIXTURES, "ldm_semicolon_comma_decimal.csv")


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return str(p)


# ── (a) ';'-delim + coma decimal + ES → columnas y valores CORRECTOS ──────────
def test_ldm_semicolon_comma_decimal_parses_correctly():
    sep, decimal = _resolve_sep_decimal(LDM_FIXTURE, "utf-8-sig")
    assert (sep, decimal) == (";", ","), "debe detectar ';'-delim + coma decimal"

    df, _ = _read_csv_dataframe(LDM_FIXTURE)
    # 6 columnas reales (no colapso a 1 ni fragmentación a 11+)
    assert len(df.columns) == 6, list(df.columns)
    # El Este de LDM-000 es 362472.4, NO 531 ni 362472 fragmentado.
    este0 = float(df["Este_UTM"].iloc[0])
    assert abs(este0 - 362472.4) < 1e-3, este0
    # Bouguer ya negativa preservada como número (no string roto).
    boug0 = float(df["Anom_Bouguer_mGal"].iloc[0])
    assert abs(boug0 - (-11.5534)) < 1e-3, boug0


def test_ldm_european_decimal_without_leading_zero():
    """Decimales europeos sin cero inicial (',05', '-,1396') deben parsear bien."""
    df, _ = _read_csv_dataframe(LDM_FIXTURE)
    # LDM-005 (índice 5): Anom_Bouguer = -,1396 ; Error = ,05
    assert abs(float(df["Anom_Bouguer_mGal"].iloc[5]) - (-0.1396)) < 1e-4
    assert abs(float(df["Error_mGal"].iloc[5]) - 0.05) < 1e-4


def test_ldm_import_end_to_end_with_column_map(tmp_path):
    """Vía import completo con mapeo ES→roles: coords correctas, no basura."""
    res = import_gravity_csv_v1(
        LDM_FIXTURE,
        strict=False,
        allow_g_raw=True,
        data_kind="gravity",
        column_map={
            "x": "Este_UTM",
            "y": "Norte_UTM",
            "elevation": "Cota_msnm",
            "gravity_value": "Anom_Bouguer_mGal",
            "station_id": "Estacion",
            "unit": "mGal",
            "gravity_type": "bouguer_anomaly",
        },
    )
    assert res.status == "ok", res.errors
    assert len(res.observations) >= 10
    # Las coords UTM se re-basan a un origen local; lo que importa es que el SPAN
    # del survey sea el real (~8.7 km), no fragmentos (la corrupción daba E≈531 →
    # spans absurdos). El valor absoluto 362472.4 ya se fija a nivel dataframe.
    xs = [o.x_m for o in res.observations]
    ys = [o.z_m for o in res.observations]
    assert 5_000 < (max(xs) - min(xs)) < 15_000, (min(xs), max(xs))
    assert 5_000 < (max(ys) - min(ys)) < 15_000, (min(ys), max(ys))


# ── (b) coma-delim inglés → byte-idéntico (camino histórico [,;] decimal '.') ──
def test_english_comma_delim_unchanged(tmp_path):
    rows = ["x_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(14):
        rows.append(f"{i*100.0},{(i%5)*90.0},{1.0+0.13*i},mGal,bouguer_anomaly")
    path = _write(tmp_path, "eng.csv", "\n".join(rows) + "\n")
    sep, decimal = _resolve_sep_decimal(path, "utf-8-sig")
    assert (sep, decimal) == (r"[,;]", "."), "inglés coma-delim debe seguir histórico"
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "ok", res.errors
    assert len(res.observations) == 14


# ── (c) ';'-delim punto-decimal → byte-idéntico (histórico [,;] decimal '.') ───
def test_semicolon_delim_point_decimal_unchanged(tmp_path):
    rows = ["x_m;z_m;bouguer_anomaly;unit;gravity_type"]
    for i in range(14):
        rows.append(f"{i*100.0};{(i%5)*90.0};{1.0+0.13*i};mGal;bouguer_anomaly")
    path = _write(tmp_path, "semic.csv", "\n".join(rows) + "\n")
    sep, decimal = _resolve_sep_decimal(path, "utf-8-sig")
    assert (sep, decimal) == (r"[,;]", "."), "';'-delim punto-decimal debe seguir histórico"
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "ok", res.errors
    assert len(res.observations) == 14


# ── (d) casos AMBIGUOS → error CLARO, jamás basura silenciosa ──────────────────
def test_thousands_separator_is_ambiguous_error(tmp_path):
    """Separador de miles (1,234,567) en ';'-delim → NO se adivina: error claro."""
    rows = ["Estacion;Este;Norte;Bouguer"]
    for i in range(14):
        rows.append(f"P{i};1,234,{500+i};6,008,{599+i};-11,55")
    path = _write(tmp_path, "miles.csv", "\n".join(rows) + "\n")
    with pytest.raises(AmbiguousDelimiterError):
        _resolve_sep_decimal(path, "utf-8-sig")
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "error"
    assert any("decimal" in e.lower() or "punto" in e.lower() for e in res.errors)


def test_text_comma_in_semicolon_field_is_ambiguous(tmp_path):
    """Coma de texto ('Sitio, norte') mezclada con decimales → error claro."""
    rows = ["Sitio;Este_UTM;Norte_UTM;Bouguer"]
    for i in range(14):
        rows.append(f"Estacion, norte {i};362472,4;6008599,5;-11,5534")
    path = _write(tmp_path, "texto.csv", "\n".join(rows) + "\n")
    with pytest.raises(AmbiguousDelimiterError):
        _resolve_sep_decimal(path, "utf-8-sig")


def test_ambiguous_error_message_is_actionable(tmp_path):
    rows = ["a;b;c"]
    for i in range(14):
        rows.append(f"x, y {i};1,2;3,4,5")
    path = _write(tmp_path, "amb.csv", "\n".join(rows) + "\n")
    with pytest.raises(AmbiguousDelimiterError) as ei:
        _resolve_sep_decimal(path, "utf-8-sig")
    msg = str(ei.value).lower()
    assert "punto decimal" in msg or "declara el formato" in msg
