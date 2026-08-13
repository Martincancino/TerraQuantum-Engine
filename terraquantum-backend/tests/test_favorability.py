import numpy as np
import polars as pl
import pytest

from services.block_model_store import get_run_favorability_path
from services.favorability_service import (
    _depth_score,
    _factor_anomaly_intensity,
    _factor_core_coherence,
    _factor_msx_support,
    compute_favorability_score,
)


def _report(overall_level="GOOD", uncertainty_score=0.1):
    return {
        "technicalSummary": {"overall_level": overall_level},
        "uncertaintyDiagnostics": {"uncertainty_score": uncertainty_score},
    }


def _grid_df(nx=4, ny=4, nz=4, block_size=10.0, high_indices=None):
    rows = []
    high = set(high_indices or [])

    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                rows.append(
                    {
                        "ix": ix,
                        "iy": iy,
                        "iz": iz,
                        "x": (ix * block_size) + (block_size / 2.0),
                        "y": (iy * block_size) + (block_size / 2.0),
                        "z": (iz * block_size) + (block_size / 2.0),
                        "density": 4.0 if (ix, iy, iz) in high else 2.6,
                        "probability": 0.8 if (ix, iy, iz) in high else 0.2,
                        "visual_score": 0.8 if (ix, iy, iz) in high else 0.0,
                    }
                )

    return pl.DataFrame(rows)


def _observations_with_anomaly():
    return [
        {"x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000080},
        {"x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000090},
        {"x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000140},
        {"x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000090},
        {"x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000080},
        {"x_m": 5, "y_m": 0, "z_m": 25, "g": 0.00000082},
        {"x_m": 15, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 25, "y_m": 0, "z_m": 25, "g": 0.00000120},
        {"x_m": 35, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 45, "y_m": 0, "z_m": 25, "g": 0.00000082},
    ]


def test_factor_anomaly_intensity_strong_signal():
    density = np.array([2.6] * 90 + [4.2] * 10, dtype=float)

    factor = _factor_anomaly_intensity(density)

    assert factor["status"] == "evaluated"
    assert factor["value"] > 0.9


def test_factor_anomaly_intensity_flat_field():
    density = np.full(100, 2.6, dtype=float)

    factor = _factor_anomaly_intensity(density)

    assert factor["value"] == 0.0


def test_factor_depth_table():
    assert _depth_score(50) == 0.65
    assert _depth_score(500) == 1.00
    assert _depth_score(1200) == 0.85
    assert _depth_score(2500) == 0.55
    assert _depth_score(4000) == 0.25
    assert _depth_score(4000.1) == 0.05


def test_factor_core_coherence_single_blob():
    density_3d = np.zeros((4, 4, 4), dtype=float)
    density_3d[1:3, 1:3, 1:3] = 10.0

    factor = _factor_core_coherence(density_3d, density_3d.ravel())

    assert factor["value"] == pytest.approx(1.0)


def test_factor_core_coherence_scattered():
    density_3d = np.zeros((4, 4, 4), dtype=float)
    for idx in [
        (0, 0, 0),
        (0, 0, 3),
        (0, 3, 0),
        (0, 3, 3),
        (3, 0, 0),
        (3, 0, 3),
        (3, 3, 0),
        (3, 3, 3),
    ]:
        density_3d[idx] = 10.0

    factor = _factor_core_coherence(density_3d, density_3d.ravel())

    assert factor["value"] < 0.2


def test_msx_not_evaluated_when_no_parquet(test_project_id, test_run_id):
    density_3d = np.ones((4, 4, 4), dtype=float)
    density_1d = density_3d.ravel()

    factor = _factor_msx_support(
        test_project_id,
        test_run_id,
        density_3d,
        density_1d,
        4,
        4,
        4,
    )

    assert factor["status"] == "not_evaluated"
    assert factor["value"] is None


def test_quality_gate_low_plus_high_uncertainty_is_mala(test_project_id, test_run_id):
    high_blob = [(ix, iy, iz) for ix in (1, 2) for iy in (1, 2) for iz in (1, 2)]
    df = _grid_df(high_indices=high_blob)

    result = compute_favorability_score(
        project_id=test_project_id,
        run_id=test_run_id,
        df_full=df,
        report_payload=_report(overall_level="LOW", uncertainty_score=0.8),
        nx=4,
        ny=4,
        nz=4,
        block_size=10.0,
    )

    assert result["gates"]["quality_gate"]["label"] == "MALA"
    assert result["gates"]["quality_gate"]["cap"] == 40.0
    assert result["score"] <= 40.0


def test_score_not_mineral_confirmation_always_true(test_project_id, test_run_id):
    df = _grid_df(high_indices=[(1, 1, 1), (1, 1, 2), (1, 2, 1), (1, 2, 2)])

    result = compute_favorability_score(
        project_id=test_project_id,
        run_id=test_run_id,
        df_full=df,
        report_payload=_report(),
        nx=4,
        ny=4,
        nz=4,
        block_size=10.0,
    )

    assert result["not_mineral_confirmation"] is True


def test_full_pipeline_integration(test_project_id, test_run_id):
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
        enable_focusing=False,
        observations=_observations_with_anomaly(),
    )

    result = run_geophysics_inversion(params)
    favorability_path = get_run_favorability_path(test_project_id, test_run_id)

    assert favorability_path.exists()
    assert result["report"]["favorability"]["not_mineral_confirmation"] is True
    assert result["report"]["favorability"]["factors"][-1]["status"] == "not_evaluated"
