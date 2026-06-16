"""Fase 9: LOD (Level of Detail) octree sampling tests."""
import pytest
from services.block_model_service import _compute_octree_lod_levels


def _make_grid(nx, ny, nz, spacing=1.0):
    """Synthetic voxel grid for testing."""
    return [
        {
            "cx": float(x) * spacing,
            "cy": float(y) * spacing,
            "cz": float(z) * spacing,
            "density": 0.5 + 0.001 * (x + y + z),
            "doi_index": 0.5 + 0.001 * (x + y + z),
        }
        for x in range(nx)
        for y in range(ny)
        for z in range(nz)
    ]


def test_lod_full_count():
    """lod_0_full must equal the input list."""
    voxels = _make_grid(10, 10, 10)
    result = _compute_octree_lod_levels(voxels, spacing_m=1.0)
    assert len(result["lod_0_full"]) == 1000


def test_lod_medium_reduces():
    """lod_1_medium must be fewer voxels than the full grid."""
    voxels = _make_grid(20, 20, 20)  # 8 000 voxels
    result = _compute_octree_lod_levels(voxels, spacing_m=1.0)
    assert len(result["lod_1_medium"]) < len(result["lod_0_full"])
    assert len(result["lod_1_medium"]) > 0


def test_lod_far_fewer_than_medium():
    """lod_2_far must have fewer (or equal) voxels than lod_1_medium."""
    voxels = _make_grid(20, 20, 20)
    result = _compute_octree_lod_levels(voxels, spacing_m=1.0)
    assert len(result["lod_2_far"]) <= len(result["lod_1_medium"])
    assert len(result["lod_2_far"]) > 0


def test_lod_subsets_are_from_original():
    """All LOD voxels must be taken from the original list (no fabrication)."""
    voxels = _make_grid(10, 10, 10)
    result = _compute_octree_lod_levels(voxels, spacing_m=1.0)
    original_coords = {(v["cx"], v["cy"], v["cz"]) for v in voxels}
    for lvl in ("lod_1_medium", "lod_2_far"):
        for v in result[lvl]:
            assert (v["cx"], v["cy"], v["cz"]) in original_coords, (
                f"{lvl}: fabricated voxel at ({v['cx']},{v['cy']},{v['cz']})"
            )


def test_lod_preserves_high_doi():
    """Within each spatial bin, the voxel with the highest doi_index is selected."""
    voxels = [
        {"cx": 0.0, "cy": 0.0, "cz": 0.0, "doi_index": 0.3, "density": 0.5},
        {"cx": 0.1, "cy": 0.0, "cz": 0.0, "doi_index": 0.9, "density": 0.5},  # highest
        {"cx": 0.2, "cy": 0.0, "cz": 0.0, "doi_index": 0.1, "density": 0.5},
    ]
    result = _compute_octree_lod_levels(voxels, spacing_m=0.5)
    medium = result["lod_1_medium"]
    # All three fall in the same bin (spacing_m*2.154 = 1.077 > 0.2 span)
    assert len(medium) == 1
    assert medium[0]["doi_index"] == pytest.approx(0.9)


def test_lod_empty_input():
    """Empty input returns empty output for all levels."""
    result = _compute_octree_lod_levels([], spacing_m=100.0)
    assert result["lod_0_full"] == []
    assert result["lod_1_medium"] == []
    assert result["lod_2_far"] == []


def test_lod_single_voxel():
    """Single voxel passes through all LOD levels."""
    voxels = [{"cx": 0.0, "cy": 0.0, "cz": 0.0, "doi_index": 0.8, "density": 0.5}]
    result = _compute_octree_lod_levels(voxels, spacing_m=100.0)
    assert len(result["lod_0_full"]) == 1
    assert len(result["lod_1_medium"]) == 1
    assert len(result["lod_2_far"]) == 1
