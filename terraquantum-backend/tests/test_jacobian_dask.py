"""
Sprint 2 — Dask + Out-of-Core Jacobian
=======================================
Validates that compute_jacobian_dask() produces a Jacobian matrix that is
element-wise identical to the serial sparse-kernel reference, and that the
result is correctly persisted as a Zarr store.

Run:
    cd terraquantum-backend
    python tests/test_jacobian_dask.py
    # or
    python -m pytest tests/test_jacobian_dask.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

# ── Import resolution: supports execution from repo root or tests/ dir ────────
try:
    from exploration.gravimetry import GravimetryForward, compute_jacobian_dask
    from exploration.storage import save_jacobian_zarr
    import zarr
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, compute_jacobian_dask
    from exploration.storage import save_jacobian_zarr
    import zarr


def _make_small_geometry(
    n_sensors: int = 12,
    nx: int = 4,
    ny: int = 3,
    nz: int = 4,
    block_size: float = 50.0,
):
    """Build a tiny sensor + voxel geometry for unit testing."""
    rng = np.random.default_rng(42)
    domain = np.array([nx, ny, nz], dtype=float) * block_size
    sensor_coords = rng.uniform(
        low=[0.0, 0.0, 0.0],
        high=domain,
        size=(n_sensors, 3),
    )

    ix, iy, iz = np.mgrid[0:nx, 0:ny, 0:nz]
    x_c = (ix.ravel(order="F") + 0.5) * block_size
    y_c = (iy.ravel(order="F") + 0.5) * block_size
    z_c = (iz.ravel(order="F") + 0.5) * block_size
    voxel_centers = np.column_stack([x_c, y_c, z_c])

    return sensor_coords, voxel_centers


class TestJacobianDaskVsSerial(unittest.TestCase):
    """Core correctness: Dask Jacobian == serial Jacobian element-wise."""

    def setUp(self):
        self.sensor_coords, self.voxel_centers = _make_small_geometry()
        self.forward = GravimetryForward(
            dx=50.0, dy=50.0, dz=50.0, cutoff_radius=800.0
        )

    def test_jacobian_dask_vs_serial(self):
        """J_dask must be np.allclose to J_serial (rtol=1e-14)."""
        # Serial reference
        x_c = self.voxel_centers[:, 0]
        y_c = self.voxel_centers[:, 1]
        z_c = self.voxel_centers[:, 2]
        G_serial = self.forward._build_sparse_kernel(
            x_c, y_c, z_c, self.sensor_coords
        )
        J_serial = G_serial.toarray()

        # Dask path
        zarr_path, shape = compute_jacobian_dask(
            self.sensor_coords,
            self.voxel_centers,
            self.forward,
            batch_size=5,
        )

        J_dask = zarr.open(zarr_path)[:]

        self.assertEqual(shape, J_serial.shape, "Shape mismatch between Dask and serial Jacobians.")
        self.assertTrue(
            np.allclose(J_serial, J_dask, rtol=1e-14, atol=0.0),
            f"Jacobians differ. Max abs diff: {np.max(np.abs(J_serial - J_dask)):.3e}",
        )

    def test_zarr_file_created(self):
        """compute_jacobian_dask must create a .zarr store on disk."""
        zarr_path, _ = compute_jacobian_dask(
            self.sensor_coords,
            self.voxel_centers,
            self.forward,
            batch_size=6,
        )
        self.assertTrue(os.path.exists(zarr_path), f"Zarr file not found: {zarr_path}")

    def test_zarr_shape_matches(self):
        """Returned shape tuple must match the actual Zarr array shape."""
        zarr_path, shape = compute_jacobian_dask(
            self.sensor_coords,
            self.voxel_centers,
            self.forward,
            batch_size=4,
        )
        z = zarr.open(zarr_path)
        self.assertEqual(shape, z.shape)

    def test_batch_invariance(self):
        """
        Jacobian result must be identical regardless of batch_size.

        This is the core property of the out-of-core approach: slicing sensors
        into different batch sizes must produce numerically identical output.
        Indirectly validates that no sensor row is dropped or duplicated.
        """
        n = self.sensor_coords.shape[0]
        batch_sizes = [1, n // 3 or 1, n]  # small / mid / single-batch

        zarr_path_ref, _ = compute_jacobian_dask(
            self.sensor_coords, self.voxel_centers, self.forward,
            batch_size=batch_sizes[0],
        )
        J_ref = zarr.open(zarr_path_ref)[:]

        for bs in batch_sizes[1:]:
            zarr_path, _ = compute_jacobian_dask(
                self.sensor_coords, self.voxel_centers, self.forward,
                batch_size=bs,
            )
            J_bs = zarr.open(zarr_path)[:]
            self.assertTrue(
                np.allclose(J_ref, J_bs, rtol=1e-14, atol=0.0),
                f"batch_size={bs} differs from batch_size={batch_sizes[0]}. "
                f"Max abs diff: {np.max(np.abs(J_ref - J_bs)):.3e}",
            )


class TestSaveJacobianZarr(unittest.TestCase):
    """Unit tests for the save_jacobian_zarr storage utility."""

    def test_roundtrip(self):
        """Saving and loading a random matrix must be lossless."""
        rng = np.random.default_rng(7)
        J = rng.standard_normal((20, 48)).astype(np.float64)
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "tq_test_jacobian_rtrip.zarr")
        save_jacobian_zarr(J, path, chunk_size=10)
        J_loaded = zarr.open(path)[:]
        np.testing.assert_array_equal(J, J_loaded)

    def test_chunks_are_sensor_batches(self):
        """Zarr chunks must follow (chunk_size, n_voxels)."""
        import tempfile
        J = np.ones((30, 50), dtype=np.float64)
        path = os.path.join(tempfile.gettempdir(), "tq_test_jacobian_chunks.zarr")
        save_jacobian_zarr(J, path, chunk_size=10)
        z = zarr.open(path)
        self.assertEqual(z.chunks, (10, 50))

    def test_rejects_non_2d(self):
        """save_jacobian_zarr must raise for non-2D input."""
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "tq_test_jac_1d.zarr")
        with self.assertRaises(ValueError):
            save_jacobian_zarr(np.ones(10), path)


if __name__ == "__main__":
    # Stand-alone execution: run tests and print a summary.
    print("=" * 60)
    print("Sprint 2 — Jacobian Dask Validation")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
