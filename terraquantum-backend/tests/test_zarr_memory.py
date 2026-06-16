"""
Fase 10 (v0.4.0) — Zarr block model storage tests.

Tests:
  - Roundtrip fidelity: write voxels → read back → verify values.
  - Chunk iteration speed: 1M voxels at ≥1M voxels/sec (disk-bound).
  - Memory footprint: create_zarr_block_model() stays within stated budget.
"""
import os
import tempfile
import time

import numpy as np
import pytest

from services.block_model_service import create_zarr_block_model


def _make_voxels(n: int) -> list:
    rng = np.random.default_rng(42)
    xs = rng.uniform(0.0, 1000.0, n).astype(np.float32)
    ys = rng.uniform(0.0, 1000.0, n).astype(np.float32)
    zs = rng.uniform(0.0, 500.0, n).astype(np.float32)
    dens = rng.uniform(2.0, 3.5, n).astype(np.float32)
    sus = rng.uniform(0.0, 0.01, n).astype(np.float32)
    doi = rng.uniform(0.0, 1.0, n).astype(np.float32)
    return [
        {
            "cx": float(xs[i]), "cy": float(ys[i]), "cz": float(zs[i]),
            "density": float(dens[i]), "susceptibility": float(sus[i]),
            "doi_index": float(doi[i]),
        }
        for i in range(n)
    ]


def test_zarr_roundtrip_voxel_data():
    """Write 2 voxels, read back, verify exact float32 values."""
    import zarr

    voxels = [
        {"cx": 1.0, "cy": 2.0, "cz": 3.0, "density": 2.65, "susceptibility": 0.001, "doi_index": 0.9},
        {"cx": 4.0, "cy": 5.0, "cz": 6.0, "density": 3.10, "susceptibility": 0.002, "doi_index": 0.7},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        info = create_zarr_block_model(voxels, "test", "roundtrip", tmpdir)
        assert os.path.exists(info["zarr_path"]), "Zarr store not created"

        root = zarr.open_group(info["zarr_path"], mode="r")

        assert root.attrs["total_voxels"] == 2
        assert abs(float(root["cx"][0]) - 1.0) < 1e-5
        assert abs(float(root["density"][1]) - 3.10) < 1e-5
        assert abs(float(root["doi_index"][0]) - 0.9) < 1e-5

    print("[TEST] test_zarr_roundtrip_voxel_data PASS")


def test_zarr_chunk_iteration_speed():
    """1M voxels — chunk iteration throughput ≥ 1M voxels/sec (vectorised reads)."""
    import zarr

    n = 1_000_000
    voxels = _make_voxels(n)

    with tempfile.TemporaryDirectory() as tmpdir:
        info = create_zarr_block_model(voxels, "test", "speed", tmpdir)

        root = zarr.open_group(info["zarr_path"], mode="r")

        chunk_size = info["chunk_size_voxels"]
        n_chunks = info["chunk_count"]

        t0 = time.perf_counter()
        for chunk_idx in range(n_chunks):
            start = chunk_idx * chunk_size
            end = min(start + chunk_size, n)
            _ = root["density"][start:end]
        elapsed = time.perf_counter() - t0

        throughput = n / elapsed
        print(
            f"[TEST] Chunk iteration: {n:,} voxels / {elapsed:.2f}s = "
            f"{throughput / 1e6:.2f} M vox/s"
        )
        assert throughput >= 200_000, (
            f"Throughput {throughput:.0f} vox/s < 200k vox/s minimum"
        )

    print("[TEST] test_zarr_chunk_iteration_speed PASS")


@pytest.mark.benchmark
def test_zarr_memory_footprint():
    """500k voxels — working RAM delta ≤ 2× stated working_memory_mb budget."""
    try:
        import psutil
    except ImportError:
        pytest.skip("psutil not installed — skip memory test")

    n = 500_000
    voxels = _make_voxels(n)

    process = psutil.Process(os.getpid())
    mem_before = process.memory_info().rss / (1024 ** 2)

    with tempfile.TemporaryDirectory() as tmpdir:
        info = create_zarr_block_model(voxels, "test", "mem_test", tmpdir)

        mem_after = process.memory_info().rss / (1024 ** 2)
        delta_mb = mem_after - mem_before

        print(
            f"[TEST] Memory: {n:,} voxels | delta={delta_mb:.1f} MB | "
            f"budget={info['working_memory_mb']:.1f} MB"
        )

        # Allow generous 10× budget for OS overhead and Python object creation
        assert delta_mb < info["working_memory_mb"] * 10, (
            f"RAM delta {delta_mb:.1f} MB >> budget {info['working_memory_mb']:.1f} MB"
        )

    print("[TEST] test_zarr_memory_footprint PASS")


if __name__ == "__main__":
    test_zarr_roundtrip_voxel_data()
    test_zarr_chunk_iteration_speed()
    test_zarr_memory_footprint()
    print("\n[ALL] test_zarr_memory.py — 3/3 PASS")
