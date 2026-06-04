"""
Fase 6 — Tests de validación de entrada geofísica.

Verifica que validate_geophysics_input() rechaza inputs inválidos con Exception
y acepta inputs válidos sin error.  14 casos inválidos + 1 caso válido.
"""
import pytest
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import validate_geophysics_input


# ── Helpers ──────────────────────────────────────────────────────────────────

def _obs(n: int = 12):
    return [
        GravityObservation(x_m=float(i * 10), y_m=float(i * 10), z_m=0.0, g=9.8)
        for i in range(n)
    ]


def _base():
    return {
        "project_id": "test-proj",
        "run_id": "test-run",
        "depth": 100,
        "nir": 50,
        "fe": 50,
        "region": "andes",
        "lat": "-33.0",
        "lon": "-70.0",
        "nx": 10,
        "ny": 10,
        "nz": 10,
        "block_size": 20,
        "cutoff_radius": 50.0,
        "lambda_mag": 0.1,
        "alpha_spatial": 1.0,
        "observations": _obs(),
    }


def _expect_error(overrides: dict):
    payload = _base()
    payload.update(overrides)
    with pytest.raises(Exception):
        model = GeophysicsInvertInput(**payload)
        validate_geophysics_input(model)


# ── Tests de casos inválidos ──────────────────────────────────────────────────

@pytest.mark.unit
def test_observations_empty():
    _expect_error({"observations": []})


@pytest.mark.unit
def test_too_few_observations():
    _expect_error({"observations": _obs(5)})


@pytest.mark.unit
def test_g_not_finite():
    _expect_error({"observations": [
        GravityObservation(x_m=float(i), y_m=float(i), z_m=0.0, g=float("nan"))
        for i in range(12)
    ]})


@pytest.mark.unit
def test_duplicate_coordinates():
    _expect_error({"observations": [
        GravityObservation(x_m=10.0, y_m=10.0, z_m=0.0, g=9.8)
    ] * 12})


@pytest.mark.unit
def test_nx_too_small():
    _expect_error({"nx": 3})


@pytest.mark.unit
def test_grid_too_large():
    _expect_error({"nx": 70, "ny": 70, "nz": 70})


@pytest.mark.unit
def test_block_size_zero():
    _expect_error({"block_size": 0})


@pytest.mark.unit
def test_depth_zero():
    _expect_error({"depth": 0})


@pytest.mark.unit
def test_lat_out_of_range():
    _expect_error({"lat": "-100"})


@pytest.mark.unit
def test_lon_out_of_range():
    _expect_error({"lon": "200"})


@pytest.mark.unit
def test_nir_out_of_range():
    _expect_error({"nir": 150})


@pytest.mark.unit
def test_fe_negative():
    _expect_error({"fe": -10})


@pytest.mark.unit
def test_lambda_mag_negative():
    _expect_error({"lambda_mag": -0.5})


@pytest.mark.unit
def test_alpha_spatial_negative():
    _expect_error({"alpha_spatial": -1.0})


# ── Test de caso válido ───────────────────────────────────────────────────────

@pytest.mark.unit
def test_valid_input_passes():
    model = GeophysicsInvertInput(**_base())
    validate_geophysics_input(model)
