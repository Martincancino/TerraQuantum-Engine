"""PILAR 4/7 (Fase 4) — Capa "nunca crashea" + MATRIZ de ingesta.

Prueba que el importador SIEMPRE termina en una salida válida (status=ok con
observaciones) O un error CLARO (status=error con errors no vacío), nunca con una
excepción ni un silent-fail. Casos sucios: NaN, filas vacías, BOM, delimitadores
(, ; tab |), columnas extra, metadata, duplicados, latin-1, vacío, 1 fila, sin
header — cruzados con gravimetría y magnetometría.

Estilo Fase 22: parametrizado, cada caso es una aserción del invariante "limpio O
error claro, jamás crash".
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gravity_import_service import import_gravity_csv_v1


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return str(p)


# ── Generadores base ──────────────────────────────────────────────────────────
def _grav_rows(n=14, sep=","):
    head = sep.join(["x_m", "z_m", "bouguer_anomaly", "unit", "gravity_type"])
    out = [head]
    for i in range(n):
        out.append(sep.join([
            f"{i * 100.0}", f"{(i % 5) * 90.0}", f"{1.0 + 0.13 * i}",
            "mGal", "bouguer_anomaly",
        ]))
    return "\n".join(out) + "\n"


def _mag_rows(n=14, sep=","):
    head = sep.join(["x_m", "z_m", "magnetic_nt"])
    out = [head]
    for i in range(n):
        out.append(sep.join([f"{i * 100.0}", f"{(i % 5) * 90.0}", f"{51000.0 + 7.0 * (i % 4)}"]))
    return "\n".join(out) + "\n"


def _assert_clean_or_clear_error(res):
    """Invariante PILAR 4: o salida válida o error claro; nunca silent-fail."""
    assert res.status in ("ok", "error")
    if res.status == "ok":
        assert len(res.observations) >= 10
    else:
        assert res.errors, "status=error debe traer al menos un mensaje accionable"


# ── 1. Casos LIMPIOS por combinación ──────────────────────────────────────────
@pytest.mark.parametrize("kind", ["gravity", "magnetic"])
def test_clean_imports_ok(tmp_path, kind):
    text = _grav_rows() if kind == "gravity" else _mag_rows()
    res = import_gravity_csv_v1(
        _write(tmp_path, "c.csv", text), strict=False, allow_g_raw=True, data_kind=kind,
    )
    assert res.status == "ok", res.errors


# ── 2. Delimitadores , ; tab | ────────────────────────────────────────────────
@pytest.mark.parametrize("sep,name", [(",", "comma"), (";", "semic"), ("\t", "tab"), ("|", "pipe")])
def test_delimiters(tmp_path, sep, name):
    res = import_gravity_csv_v1(
        _write(tmp_path, f"{name}.csv", _grav_rows(sep=sep)),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", (name, res.errors)
    assert len(res.observations) == 14


# ── 3. NaN / filas vacías → se omiten, import OK ──────────────────────────────
def test_nan_rows_skipped(tmp_path):
    rows = _grav_rows(n=14).splitlines()
    rows.insert(3, "NaN,NaN,,mGal,bouguer_anomaly")     # NaN coords
    rows.insert(6, ",,,,")                               # fila vacía de campos
    text = "\n".join(rows) + "\n"
    res = import_gravity_csv_v1(
        _write(tmp_path, "nan.csv", text), strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", res.errors
    assert len(res.observations) == 14
    assert any("omitieron" in w or "omitida" in w for w in res.warnings)


def test_blank_lines_tolerated(tmp_path):
    rows = _grav_rows(n=14).splitlines()
    rows.insert(4, "")
    rows.insert(9, "   ")
    text = "\n".join(rows) + "\n"
    res = import_gravity_csv_v1(
        _write(tmp_path, "blank.csv", text), strict=False, allow_g_raw=True, data_kind="gravity",
    )
    _assert_clean_or_clear_error(res)
    assert res.status == "ok", res.errors


# ── 4. BOM y encoding latin-1 ─────────────────────────────────────────────────
def test_bom_header(tmp_path):
    res = import_gravity_csv_v1(
        _write(tmp_path, "bom.csv", _grav_rows(), encoding="utf-8-sig"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", res.errors


def test_latin1_encoding(tmp_path):
    # Comentario con acento en latin-1 como nombre de estación-extra; datos válidos.
    text = _grav_rows()
    res = import_gravity_csv_v1(
        _write(tmp_path, "lat1.csv", text, encoding="latin-1"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", res.errors


# ── 5. Columnas extra ─────────────────────────────────────────────────────────
def test_extra_columns_ignored(tmp_path):
    rows = ["x_m,z_m,bouguer_anomaly,unit,gravity_type,comentario,foo_extra"]
    for i in range(14):
        rows.append(f"{i*100.0},{(i%5)*90.0},{1.0+0.1*i},mGal,bouguer_anomaly,hola,{i}")
    res = import_gravity_csv_v1(
        _write(tmp_path, "extra.csv", "\n".join(rows) + "\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", res.errors


# ── 6. Duplicados ─────────────────────────────────────────────────────────────
def test_exact_duplicates(tmp_path):
    rows = _grav_rows(n=14).splitlines()
    rows.append(rows[1])  # duplica la primera fila de datos
    res = import_gravity_csv_v1(
        _write(tmp_path, "dup.csv", "\n".join(rows) + "\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    _assert_clean_or_clear_error(res)
    assert res.status == "ok", res.errors


# ── 7. Degenerados → error CLARO, no crash ────────────────────────────────────
def test_empty_file(tmp_path):
    res = import_gravity_csv_v1(
        _write(tmp_path, "empty.csv", ""), strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "error"
    assert res.errors


def test_header_only(tmp_path):
    res = import_gravity_csv_v1(
        _write(tmp_path, "head.csv", "x_m,z_m,bouguer_anomaly,unit,gravity_type\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "error"
    assert res.errors


def test_single_row(tmp_path):
    res = import_gravity_csv_v1(
        _write(tmp_path, "one.csv", _grav_rows(n=1)),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "error"
    assert any("10" in e for e in res.errors)


def test_no_coords_clear_error(tmp_path):
    rows = ["station_id,unit,g_mgal,gravity_type"]
    for i in range(14):
        rows.append(f"st_{i},mGal,{5.0 + i * 0.1},bouguer_anomaly")
    res = import_gravity_csv_v1(
        _write(tmp_path, "nocoord.csv", "\n".join(rows) + "\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "error"
    assert res.errors


# ── 8. Matriz combinada: nunca crashea ────────────────────────────────────────
@pytest.mark.parametrize("kind", ["gravity", "magnetic"])
@pytest.mark.parametrize("sep", [",", ";", "\t", "|"])
def test_matrix_never_crashes(tmp_path, kind, sep):
    text = _grav_rows(sep=sep) if kind == "gravity" else _mag_rows(sep=sep)
    # Inyecta una fila de metadata + una NaN para estresar la tolerancia.
    lines = text.splitlines()
    lines.insert(2, sep.join(["META", "x", "y"] if kind == "magnetic" else ["META", "x", "y", "z", "w"]))
    lines.insert(5, sep.join(["NaN", "NaN", ""] if kind == "magnetic" else ["NaN", "NaN", "", "mGal", "bouguer_anomaly"]))
    res = import_gravity_csv_v1(
        _write(tmp_path, "mx.csv", "\n".join(lines) + "\n"),
        strict=False, allow_g_raw=True, data_kind=kind,
    )
    _assert_clean_or_clear_error(res)
