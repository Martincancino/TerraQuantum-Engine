"""
TAREA B — Unidad de la columna de elevación (m/ft) en la ingesta de CSV.

ROLE_ELEVATION asumía SIEMPRE metros. Una columna de elevación en pies se ingería
como metros → error de ~3.28× (1/0.3048) en la superficie de malla (station_elevations)
y en la corrección de Bouguer (raw_latlon_elev_list.elev_m). Ahora `column_map` admite
la clave literal "elevation_unit" ∈ {"m","ft"} (alias tolerantes), default "m".

GUARDRAIL verificado: sin la clave → byte-idéntico al histórico (factor 1.0).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.column_mapping_service import (
    LITERAL_KEYS,
    resolve_elevation_unit_factor,
)
from services.gravity_import_service import import_gravity_csv_v1

_FT_TO_M = 0.3048
# Elevaciones crudas (en la unidad declarada por la columna). ≥10 estaciones porque
# la ingesta exige un mínimo de observaciones válidas.
_N_STATIONS = 12
_RAW_ELEVS = [1000.0 + 100.0 * i for i in range(_N_STATIONS)]


def _write_latlon_csv(path: Path) -> None:
    """CSV lat/lon con columna de elevación: alimenta tanto station_elevations
    (superficie de malla) como raw_latlon_elev_list.elev_m (Bouguer)."""
    headers = ["station_id", "lat", "lon", "elevation", "unit", "gravity_anomaly", "gravity_type"]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers) + "\n")
        for i in range(_N_STATIONS):
            lat = -33.10 - 0.01 * i
            lon = -70.20 - 0.01 * i
            f.write(
                f"S{i+1},{lat:.5f},{lon:.5f},{_RAW_ELEVS[i]},mGal,"
                f"{5.0 + 0.1 * i:.2f},bouguer_anomaly\n"
            )


def _station_elevs(result):
    se = result.station_elevations
    assert se is not None, "El CSV de prueba debe producir station_elevations."
    return [float(v) for v in se]


# ── Resolver de unidad (helper puro) ─────────────────────────────────────────

def test_resolve_factor_defaults_to_meters():
    assert resolve_elevation_unit_factor(None) == 1.0
    assert resolve_elevation_unit_factor("") == 1.0
    assert resolve_elevation_unit_factor("m") == 1.0
    assert resolve_elevation_unit_factor("metros") == 1.0


def test_resolve_factor_feet_aliases():
    for alias in ("ft", "feet", "pies", "FT", "Pies"):
        assert resolve_elevation_unit_factor(alias) == pytest.approx(_FT_TO_M)


def test_resolve_factor_unknown_is_meters_not_crash():
    # Unidad desconocida → no se inventa nada: cae a metros (guardrail).
    assert resolve_elevation_unit_factor("furlongs") == 1.0


def test_elevation_unit_is_a_literal_key():
    assert "elevation_unit" in LITERAL_KEYS


# ── Ingesta end-to-end: m vs ft ──────────────────────────────────────────────

def test_default_no_key_is_byte_identical_to_meters(tmp_path):
    csv = tmp_path / "elev.csv"
    _write_latlon_csv(csv)
    no_map = _station_elevs(import_gravity_csv_v1(csv, strict=True))
    explicit_m = _station_elevs(
        import_gravity_csv_v1(csv, strict=True, column_map={"elevation_unit": "m"})
    )
    # Sin clave == declarar metros == valores crudos.
    assert no_map == pytest.approx(_RAW_ELEVS)
    assert explicit_m == pytest.approx(no_map)


def test_feet_elevation_converted_to_meters(tmp_path):
    csv = tmp_path / "elev.csv"
    _write_latlon_csv(csv)
    as_meters = _station_elevs(import_gravity_csv_v1(csv, strict=True))
    as_feet = _station_elevs(
        import_gravity_csv_v1(csv, strict=True, column_map={"elevation_unit": "ft"})
    )
    # La MISMA columna interpretada como pies → metros = crudo × 0.3048.
    assert as_feet == pytest.approx([v * _FT_TO_M for v in _RAW_ELEVS])
    # Y por tanto difiere del default por el factor 0.3048 (no idéntico).
    for f_val, m_val in zip(as_feet, as_meters):
        assert f_val == pytest.approx(m_val * _FT_TO_M)
        assert f_val != pytest.approx(m_val)


def test_feet_alias_pies_matches_ft(tmp_path):
    csv = tmp_path / "elev.csv"
    _write_latlon_csv(csv)
    via_ft = _station_elevs(
        import_gravity_csv_v1(csv, strict=True, column_map={"elevation_unit": "ft"})
    )
    via_pies = _station_elevs(
        import_gravity_csv_v1(csv, strict=True, column_map={"elevation_unit": "pies"})
    )
    assert via_pies == pytest.approx(via_ft)
