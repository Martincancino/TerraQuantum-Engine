"""PILAR 1 (KEYSTONE) — Tests de ingesta robusta + MAPEO MANUAL de columnas.

Cubren:
  • normalize_token (acentos/mayúsculas/separadores).
  • Auto-detección fuzzy: encabezados con acentos/espacios se reconocen igual.
  • build_column_mapping_plan: needs_mapping cuando faltan roles; resolución con override.
  • import_gravity_csv_v1 con column_map: un CSV de columnas arbitrarias
    ('Anomalia_Bouguer_mGal','X','Y','Z') ingiere OK con mapeo manual.
  • Sin regresión: un CSV estándar sigue ingiriendo sin column_map.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.column_mapping_service import (
    normalize_token,
    build_column_mapping_plan,
    resolve_mapped_column,
)
from services.gravity_import_service import (
    import_gravity_csv_v1,
    read_csv_headers,
    choose_gravity_column,
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 1. normalize_token ────────────────────────────────────────────────────────
def test_normalize_token_strips_accents_case_separators():
    assert normalize_token("Anomalía Bouguer (mGal)") == "anomaliabouguermgal"
    assert normalize_token("UTM-X") == "utmx"
    assert normalize_token("  X  ") == "x"
    assert normalize_token("Elevación_m") == "elevacionm"
    assert normalize_token(None) == ""


def test_resolve_mapped_column_fuzzy():
    headers = ["Easting", "Northing", "Bouguer (mGal)"]
    assert resolve_mapped_column("easting", headers) == "Easting"
    assert resolve_mapped_column("BOUGUER_MGAL", headers) == "Bouguer (mGal)"
    assert resolve_mapped_column("nope", headers) is None


# ── 2. Auto-detección fuzzy ───────────────────────────────────────────────────
def test_choose_gravity_column_fuzzy_accent():
    # "Bouguer Anomaly" normaliza a "bougueranomaly" == alias "bouguer_anomaly".
    assert choose_gravity_column(["X", "Z", "Bouguer Anomaly"]) == "Bouguer Anomaly"


def test_plan_autodetect_standard_no_mapping_needed():
    headers = ["station_id", "lat", "lon", "elevation_m", "gravity_anomaly", "unit"]
    plan = build_column_mapping_plan(headers, data_kind="gravity")
    assert plan["needs_mapping"] is False
    assert plan["confidence"] == "high"
    assert plan["roles"]["x"] == "lon"
    assert plan["roles"]["y"] == "lat"
    assert plan["roles"]["gravity_value"] == "gravity_anomaly"


# ── 3. needs_mapping con columnas arbitrarias ─────────────────────────────────
def test_plan_arbitrary_columns_needs_mapping():
    headers = ["Anomalia_Bouguer_mGal", "X", "Y", "Z"]
    plan = build_column_mapping_plan(headers, data_kind="gravity")
    # X/Y se auto-detectan como local (alias x/y), pero el valor gravimétrico no.
    assert plan["needs_mapping"] is True
    assert "gravity_value" in plan["missing_required"]
    assert plan["raw_columns"] == headers


def test_plan_with_override_resolves():
    headers = ["Anomalia_Bouguer_mGal", "Xcoord", "Ycoord", "Z"]
    column_map = {
        "x": "Xcoord", "y": "Ycoord", "gravity_value": "Anomalia_Bouguer_mGal",
    }
    plan = build_column_mapping_plan(headers, data_kind="gravity", column_map=column_map)
    assert plan["needs_mapping"] is False
    assert plan["roles"]["gravity_value"] == "Anomalia_Bouguer_mGal"
    assert plan["overridden"]["x"] == "Xcoord"


def test_plan_flags_invalid_override():
    headers = ["A", "B", "C"]
    plan = build_column_mapping_plan(
        headers, data_kind="gravity",
        column_map={"x": "A", "y": "B", "gravity_value": "DOES_NOT_EXIST"},
    )
    assert "gravity_value" in plan["invalid_overrides"]
    assert plan["needs_mapping"] is True


# ── 4. import_gravity_csv_v1 con column_map (ingesta real) ─────────────────────
def _arbitrary_csv(n=12):
    rows = ["Anomalia_Bouguer_mGal,X,Y,Z"]
    for i in range(n):
        # X/Y locales métricos, Z elevación; valor con variación para pasar QC.
        rows.append(f"{1.0 + 0.1 * i},{i * 100.0},{i * 50.0},{100.0 + i}")
    return "\n".join(rows) + "\n"


def test_import_arbitrary_columns_with_manual_map(tmp_path):
    path = _write(tmp_path, "weird.csv", _arbitrary_csv())
    column_map = {
        "x": "X", "y": "Y", "elevation": "Z",
        "gravity_value": "Anomalia_Bouguer_mGal",
        "unit": "mGal", "coordinate_system": "local",
    }
    res = import_gravity_csv_v1(
        path, strict=False, allow_g_raw=True,
        data_kind="gravity", column_map=column_map,
    )
    assert res.status == "ok", res.errors
    assert len(res.observations) == 12
    assert res.import_metadata.gravity_column_used == "Anomalia_Bouguer_mGal"


def test_import_arbitrary_columns_without_map_fails_clearly(tmp_path):
    path = _write(tmp_path, "weird.csv", _arbitrary_csv())
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    # Sin mapeo ni columna de unidad/valor reconocible → error claro, no crash.
    assert res.status == "error"
    assert res.errors


def test_read_csv_headers(tmp_path):
    path = _write(tmp_path, "weird.csv", _arbitrary_csv())
    assert read_csv_headers(path) == ["Anomalia_Bouguer_mGal", "X", "Y", "Z"]


# ── 5. Sin regresión: CSV estándar sin column_map ─────────────────────────────
def _standard_csv(n=12):
    rows = ["station_id,x_m,z_m,gravity_anomaly,unit,gravity_type"]
    for i in range(n):
        rows.append(f"ST{i},{i * 100.0},{i * 50.0},{1.0 + 0.1 * i},mGal,bouguer_anomaly")
    return "\n".join(rows) + "\n"


def test_standard_csv_still_imports_without_map(tmp_path):
    path = _write(tmp_path, "std.csv", _standard_csv())
    res = import_gravity_csv_v1(path, strict=True, allow_g_raw=False, data_kind="gravity")
    assert res.status == "ok", res.errors
    assert len(res.observations) == 12


# ── 6. Magnetometría con mapeo manual ─────────────────────────────────────────
def test_import_magnetic_with_manual_map(tmp_path):
    rows = ["Campo_Total,Este,Norte"]
    for i in range(12):
        rows.append(f"{50000.0 + i * 3.0},{i * 100.0},{i * 80.0}")
    path = _write(tmp_path, "mag.csv", "\n".join(rows) + "\n")
    column_map = {"x": "Este", "y": "Norte", "magnetic_value": "Campo_Total"}
    res = import_gravity_csv_v1(
        path, strict=False, allow_g_raw=True,
        data_kind="magnetic", column_map=column_map,
    )
    assert res.status == "ok", res.errors
    assert len(res.observations) == 12
