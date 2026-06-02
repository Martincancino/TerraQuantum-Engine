import pytest
from pydantic import ValidationError

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.grid_calculator_service import R10_LIMIT, compute_auto_grid


def _invert_input(depth):
    return GeophysicsInvertInput(
        depth=depth,
        nir=50,
        fe=50,
        region="QA",
        lat="-22.2",
        lon="-68.8",
        nx=4,
        ny=4,
        nz=4,
        block_size=1000,
        cutoff_radius=100.0,
        lambda_mag=0.00005,
        alpha_spatial=2.0,
        observations=[
            GravityObservation(x_m=float(i), y_m=0.0, z_m=float(i), g=1e-5)
            for i in range(10)
        ],
    )


def test_geophysics_invert_input_accepts_regional_auto_grid_depth():
    params = _invert_input(30_000)

    assert params.depth == 30_000


def test_geophysics_invert_input_accepts_regional_depth():
    # HITO 5 Fase 1.5: el cap de 100km se elevó a 1000km para soportar inversión regional.
    # depth=250000m (250km, escala Bushveld) debe pasar sin ValidationError.
    params = _invert_input(250_000)
    assert params.depth == 250_000


def test_hvc_like_grid_matches_expected_scale():
    grid = compute_auto_grid(
        x_extent_m=50_000.0,
        z_extent_m=50_000.0,
        observation_count=251,
        quality_label="MEDIA",
    )

    # HITO 5 — Scale-aware meshing: depth = L_max / 3 (no 0.6·L_max).
    # Para L_max=50km → depth≈16.7km → ny≈11 (antes 0.6·50km=30km → ny≈20).
    assert 1400.0 <= grid.block_size_m <= 1700.0
    assert 30 <= grid.nx <= 34
    assert 9 <= grid.ny <= 13
    assert 30 <= grid.nz <= 34
    assert grid.voxel_count <= R10_LIMIT
    assert 9_000 <= grid.voxel_count <= 14_000
    assert 16_000.0 <= grid.depth_m <= 17_000.0


def test_voxel_count_always_respects_r10_for_large_dataset():
    grid = compute_auto_grid(
        x_extent_m=250_000.0,
        z_extent_m=180_000.0,
        observation_count=500,
        quality_label="MEDIA",
    )

    assert grid.voxel_count <= R10_LIMIT


def test_small_dataset_uses_reasonable_grid_and_quality_warning():
    grid = compute_auto_grid(
        x_extent_m=900.0,
        z_extent_m=900.0,
        observation_count=10,
        quality_label="BAJA",
    )

    assert grid.nx >= 4
    assert grid.ny >= 4
    assert grid.nz >= 4
    assert grid.block_size_m >= 25.0
    assert grid.voxel_count <= R10_LIMIT
    assert any("quality_label=BAJA" in warning for warning in grid.warnings)


def test_dense_dataset_respects_r10():
    grid = compute_auto_grid(
        x_extent_m=10_000.0,
        z_extent_m=10_000.0,
        observation_count=10_000,
        quality_label="ALTA",
    )

    assert grid.voxel_count <= R10_LIMIT
    assert grid.adjusted_for_r10 is True


def test_r10_stress_adjusts_block_size_and_warns():
    grid = compute_auto_grid(
        x_extent_m=1_000_000.0,
        z_extent_m=1_000_000.0,
        observation_count=100_000,
        quality_label="MEDIA",
    )

    assert grid.adjusted_for_r10 is True
    assert grid.r10_iterations > 0
    assert grid.voxel_count <= R10_LIMIT
    assert any("R-10" in warning for warning in grid.warnings)


def test_zero_extent_or_observation_count_uses_safe_fallback():
    grid = compute_auto_grid(
        x_extent_m=0.0,
        z_extent_m=0.0,
        observation_count=0,
        quality_label="INSUFICIENTE",
    )

    assert grid.nx >= 4
    assert grid.ny >= 4
    assert grid.nz >= 4
    assert grid.voxel_count <= R10_LIMIT
    assert grid.block_size_m >= 25.0
    assert grid.warnings
