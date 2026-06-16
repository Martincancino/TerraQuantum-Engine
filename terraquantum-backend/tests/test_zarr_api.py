"""
Fase 10 (v0.4.0) — Zarr API endpoint tests.

Tests GET /block-model-zarr/{project_id}/{run_id} metadata and chunk responses.
"""
import os
import tempfile

import pytest

from services.block_model_service import create_zarr_block_model


@pytest.fixture()
def zarr_store_fixture(tmp_path):
    """Pre-built Zarr store with 200 voxels for API tests."""
    voxels = [
        {
            "cx": float(i), "cy": float(i * 2), "cz": float(i * 3),
            "density": 2.6 + i * 0.001,
            "susceptibility": 0.001 * i,
            "doi_index": max(0.0, 1.0 - i * 0.005),
        }
        for i in range(200)
    ]
    run_dir = str(tmp_path)
    info = create_zarr_block_model(voxels, "proj_test", "run_test", run_dir)
    return info, run_dir, voxels


def test_zarr_store_created(zarr_store_fixture):
    """Zarr store directory must exist after create_zarr_block_model()."""
    info, run_dir, _ = zarr_store_fixture
    assert os.path.exists(info["zarr_path"]), "Zarr store path missing"
    assert info["total_voxels"] == 200
    assert info["chunk_count"] >= 1


def test_zarr_metadata_attrs(zarr_store_fixture):
    """Root attrs must contain expected keys with correct values."""
    import zarr

    info, _, _ = zarr_store_fixture
    root = zarr.open_group(info["zarr_path"], mode="r")

    assert root.attrs["total_voxels"] == 200
    assert root.attrs["project_id"] == "proj_test"
    assert root.attrs["run_id"] == "run_test"
    assert "bounds" in root.attrs
    bounds = root.attrs["bounds"]
    for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
        assert key in bounds, f"Missing bound key: {key}"


def test_zarr_chunk0_data(zarr_store_fixture):
    """Chunk 0 must return correct first voxel values."""
    import zarr

    info, _, voxels = zarr_store_fixture
    root = zarr.open_group(info["zarr_path"], mode="r")

    chunk_size = info["chunk_size_voxels"]
    cx_chunk = root["cx"][0:min(chunk_size, 200)]
    den_chunk = root["density"][0:min(chunk_size, 200)]

    assert abs(float(cx_chunk[0]) - voxels[0]["cx"]) < 1e-4
    assert abs(float(den_chunk[0]) - voxels[0]["density"]) < 1e-4


def test_zarr_all_fields_present(zarr_store_fixture):
    """All six expected fields must be present in the Zarr store."""
    import zarr

    info, _, _ = zarr_store_fixture
    root = zarr.open_group(info["zarr_path"], mode="r")

    for field in ("cx", "cy", "cz", "density", "susceptibility", "doi_index"):
        assert field in root, f"Missing Zarr dataset: {field}"
        assert root[field].size == 200  # zarr v3: .size not len()


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        voxels = [
            {"cx": float(i), "cy": float(i * 2), "cz": float(i * 3),
             "density": 2.6 + i * 0.001, "susceptibility": 0.001 * i,
             "doi_index": max(0.0, 1.0 - i * 0.005)}
            for i in range(200)
        ]
        info = create_zarr_block_model(voxels, "proj_test", "run_test", tmpdir)
        fixture = (info, tmpdir, voxels)
        test_zarr_store_created(fixture)
        test_zarr_metadata_attrs(fixture)
        test_zarr_chunk0_data(fixture)
        test_zarr_all_fields_present(fixture)
    print("\n[ALL] test_zarr_api.py — 4/4 PASS")
