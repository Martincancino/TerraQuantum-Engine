"""
Test end-to-end del flujo project_run: inversión geofísica → persistencia → pit design.
"""
import pytest


def _observations_grid_10x10():
    """24 observaciones que cubren un grid 10x10x10 (100m x 100m x 100m)."""
    obs = []
    for x in [5, 25, 50, 75, 95]:
        for z in [5, 50, 95, 120]:
            obs.append({"x_m": float(x), "y_m": 0.0, "z_m": float(z), "g": 0.00000090})
    # Anomalía central más fuerte
    obs[5]["g"] = 0.00000160
    obs[6]["g"] = 0.00000140
    return obs[:24]


@pytest.mark.integration
def test_geophysics_flow_crea_archivos(test_project_id, test_run_id, backend_root):
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=100,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=10,
        ny=10,
        nz=10,
        block_size=10,
        cutoff_radius=800,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        observations=_observations_grid_10x10(),
    )

    result = run_geophysics_inversion(params)

    assert "error" not in result, f"Inversión falló: {result.get('error')}"
    assert result.get("report", {}).get("storageMode") == "project_run"

    run_dir = backend_root / "data" / "projects" / test_project_id / "runs" / test_run_id
    assert (run_dir / "block_model.parquet").exists()
    assert (run_dir / "inputs.json").exists()
    assert (run_dir / "observations.json").exists()
    assert (run_dir / "report.json").exists()

    report = result.get("report", {})
    assert report.get("projectId") == test_project_id
    assert report.get("runId") == test_run_id
    assert report.get("storageMode") == "project_run"


@pytest.mark.integration
def test_block_model_response_con_project_run(test_project_id, test_run_id):
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.block_model_service import build_block_model_response
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=100,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=10,
        ny=10,
        nz=10,
        block_size=10,
        cutoff_radius=800,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        observations=_observations_grid_10x10(),
    )

    run_geophysics_inversion(params)

    block_model = build_block_model_response(
        mode="exploration",
        limit=2000,
        project_id=test_project_id,
        run_id=test_run_id,
    )

    assert "error" not in block_model, f"block_model_response error: {block_model.get('error')}"
    assert block_model.get("returnedCells", 0) > 0
    assert block_model.get("storageMode") == "project_run"


@pytest.mark.integration
def test_pit_design_after_inversion(test_project_id, test_run_id):
    from schemas.geophysics_schema import GeophysicsInvertInput
    from schemas.pit_design_schema import PitRequest
    from services.geophysics_service import run_geophysics_inversion
    from services.pit_design_service import generate_pit_design

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=100,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=10,
        ny=10,
        nz=10,
        block_size=10,
        cutoff_radius=800,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        observations=_observations_grid_10x10(),
    )

    run_geophysics_inversion(params)

    pit_req = PitRequest(
        project_id=test_project_id,
        run_id=test_run_id,
        price=8500,
        recovery=0.88,
        mining_cost=2.2,
        processing_cost=24.0,
        pit_angle=45,
        bench_height=10,
        berm_width=8,
        haulage_cost_per_m=0.002,
        ramp_gradient=0.10,
        block_size_x=10,
        block_size_y=10,
        block_size_z=10,
        exclude_inferred=False,
        p_cap=80_000_000,
        discount_rate=0.10,
        fleet_size=20,
    )

    result = generate_pit_design(pit_req)

    assert result.get("status") == "done", (
        f"pit design status esperado 'done', recibido: {result.get('status')} — "
        f"detail: {result.get('detail', '')}"
    )
    assert bool(result.get("modelUrl"))
    assert "npv" in result.get("metrics", {})
