"""
Test camino feliz de MS-x focusing (IRLS — Minimum Support).

Verifica que con enable_focusing=True:
- La inversión no lanza excepción
- El resultado incluye información de focusing (scale_status)
"""
import pytest


def _observations_with_anomaly():
    return [
        {"x_m": 5,  "y_m": 0, "z_m": 5,  "g": 0.00000080},
        {"x_m": 15, "y_m": 0, "z_m": 5,  "g": 0.00000090},
        {"x_m": 25, "y_m": 0, "z_m": 5,  "g": 0.00000140},
        {"x_m": 35, "y_m": 0, "z_m": 5,  "g": 0.00000090},
        {"x_m": 45, "y_m": 0, "z_m": 5,  "g": 0.00000080},
        {"x_m": 5,  "y_m": 0, "z_m": 25, "g": 0.00000082},
        {"x_m": 15, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 25, "y_m": 0, "z_m": 25, "g": 0.00000120},
        {"x_m": 35, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 45, "y_m": 0, "z_m": 25, "g": 0.00000082},
    ]


@pytest.mark.integration
def test_msx_focusing_no_lanza_excepcion(test_project_id, test_run_id):
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=30,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=6,
        ny=6,
        nz=6,
        block_size=10,
        cutoff_radius=400,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        enable_focusing=True,
        observations=_observations_with_anomaly(),
    )

    result = run_geophysics_inversion(params)

    assert isinstance(result, dict), "El resultado debe ser un dict"
    assert "error" not in result, f"El resultado no debe tener 'error': {result.get('error')}"
    assert result.get("report", {}).get("storageMode") == "project_run"


@pytest.mark.integration
def test_msx_focusing_incluye_scale_status(test_project_id, test_run_id):
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=30,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=6,
        ny=6,
        nz=6,
        block_size=10,
        cutoff_radius=400,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        enable_focusing=True,
        observations=_observations_with_anomaly(),
    )

    result = run_geophysics_inversion(params)

    report = result.get("report", {})
    # scale_status puede estar en report directamente o en report["focusing"]
    focusing_info = report.get("focusing") or result.get("focusing") or {}
    scale_status = report.get("scale_status") or focusing_info.get("scale_status")

    assert scale_status is not None, (
        "Con enable_focusing=True, el resultado debe incluir 'scale_status'. "
        f"Claves disponibles en report: {list(report.keys())}, "
        f"en result: {list(result.keys())}"
    )
