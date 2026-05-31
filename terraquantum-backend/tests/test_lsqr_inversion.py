"""
Test camino feliz de inversión LSQR gravimétrica.

Verifica que run_geophysics_inversion con datos sintéticos mínimos:
- No lanza excepción
- Retorna dict con estructura esperada
- Persiste archivos en data/projects/{project_id}/runs/{run_id}/
"""
import pytest


def _minimal_observations():
    return [
        {"x_m": 5,  "y_m": 0, "z_m": 5,  "g": 0.00000080},
        {"x_m": 15, "y_m": 0, "z_m": 5,  "g": 0.00000090},
        {"x_m": 25, "y_m": 0, "z_m": 5,  "g": 0.00000110},
        {"x_m": 35, "y_m": 0, "z_m": 5,  "g": 0.00000150},
        {"x_m": 45, "y_m": 0, "z_m": 5,  "g": 0.00000110},
        {"x_m": 5,  "y_m": 0, "z_m": 25, "g": 0.00000085},
        {"x_m": 15, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 25, "y_m": 0, "z_m": 25, "g": 0.00000130},
        {"x_m": 35, "y_m": 0, "z_m": 25, "g": 0.00000100},
        {"x_m": 45, "y_m": 0, "z_m": 25, "g": 0.00000090},
    ]


@pytest.mark.integration
def test_lsqr_inversion_retorna_estructura_esperada(test_project_id, test_run_id):
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
        observations=_minimal_observations(),
    )

    result = run_geophysics_inversion(params)

    assert isinstance(result, dict), "El resultado debe ser un dict"
    assert "error" not in result, f"El resultado no debe tener 'error': {result.get('error')}"
    assert "report" in result, "El resultado debe tener 'report'"

    report = result["report"]
    assert report.get("storageMode") == "project_run", (
        f"storageMode esperado 'project_run', recibido: {report.get('storageMode')}"
    )
    assert report.get("projectId") == test_project_id
    assert report.get("runId") == test_run_id
    assert report.get("storageMode") == "project_run"
    # La migración de compliance JORC reemplazó la clave accionable 'recommendation'
    # por la señal técnica no accionable 'preliminary_signal' (+ 'drill_recommendation'),
    # ambas siempre presentes ("OBSERVE" / "DRILL_CANDIDATE"). Ver build_geophysics_report.
    assert bool(report.get("preliminary_signal")), "El report debe tener 'preliminary_signal'"


@pytest.mark.integration
def test_lsqr_inversion_persiste_archivos(test_project_id, test_run_id, backend_root):
    from pathlib import Path

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
        observations=_minimal_observations(),
    )

    run_geophysics_inversion(params)

    run_dir = backend_root / "data" / "projects" / test_project_id / "runs" / test_run_id
    assert run_dir.exists(), f"Run directory no existe: {run_dir}"
    assert (run_dir / "block_model.parquet").exists(), "block_model.parquet no creado"
    assert (run_dir / "inputs.json").exists(), "inputs.json no creado"
    assert (run_dir / "report.json").exists(), "report.json no creado"
