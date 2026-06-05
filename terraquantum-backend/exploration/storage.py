"""
Zarr + Parquet storage utilities for TerraQuantum inversion results.
Foundation for Dask + streaming (Sprint 1 — Tier-1 architecture).

Writes:
  <output_dir>/<prefix>_density.zarr    — 3D density grid (nx, ny, nz)
  <output_dir>/<prefix>_susc.zarr       — 3D susceptibility grid (if provided)
  <output_dir>/<prefix>_metadata.parquet — misfit, chi2, lambda, shape, stats
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd
import zarr


def save_inversion_results_parquet(
    density_grid: np.ndarray,
    susceptibility_grid: Optional[np.ndarray],
    misfit: float,
    chi2: float,
    lambda_used: float,
    params_dict: dict,
    output_dir: str,
    run_id: str = "",
) -> dict:
    """
    Save inversion results to Parquet (metadata) + Zarr (3D grids).

    Parameters
    ----------
    density_grid : 1D (nx*ny*nz,) or 3D (nx,ny,nz) float64 array.
        Assumes Fortran (column-major) order when reshaping from 1D.
    susceptibility_grid : optional array, same size as density_grid.
    misfit : data misfit percentage.
    chi2 : reduced chi-squared.
    lambda_used : Tikhonov regularization parameter.
    params_dict : must contain 'nx', 'ny', 'nz'; any extra scalar key is
        persisted verbatim in the Parquet row.
    output_dir : directory where files are written (created if absent).
    run_id : optional identifier appended to file names.

    Returns
    -------
    dict with keys:
        zarr_density        — path to density .zarr
        zarr_susceptibility — path to susceptibility .zarr (or None)
        parquet_metadata    — path to .parquet metadata file
    """
    os.makedirs(output_dir, exist_ok=True)

    prefix = f"inv_{run_id}" if run_id else "inv_results"
    zarr_density_path = os.path.join(output_dir, f"{prefix}_density.zarr")
    parquet_path = os.path.join(output_dir, f"{prefix}_metadata.parquet")

    nx = int(params_dict.get("nx", 1))
    ny = int(params_dict.get("ny", 1))
    nz = int(params_dict.get("nz", 1))
    expected_n = nx * ny * nz

    # ── Reshape density to (nx, ny, nz) ──────────────────────────────────────
    density_flat = np.asarray(density_grid, dtype=np.float64).ravel()
    if density_flat.size == expected_n:
        density_3d = density_flat.reshape((nx, ny, nz), order="F")
    else:
        # Fallback: treat as flat — shape will not match (nx,ny,nz) but still stored
        density_3d = density_flat.reshape((-1, 1, 1))

    # ── Write density Zarr ────────────────────────────────────────────────────
    zd = zarr.open_array(
        zarr_density_path,
        mode="w",
        shape=density_3d.shape,
        dtype="float64",
        chunks=density_3d.shape,
    )
    zd[:] = density_3d

    # ── Write susceptibility Zarr (optional) ──────────────────────────────────
    zarr_susc_path = None
    if susceptibility_grid is not None:
        zarr_susc_path = os.path.join(output_dir, f"{prefix}_susc.zarr")
        susc_flat = np.asarray(susceptibility_grid, dtype=np.float64).ravel()
        if susc_flat.size == expected_n:
            susc_3d = susc_flat.reshape((nx, ny, nz), order="F")
        else:
            susc_3d = susc_flat.reshape((-1, 1, 1))
        zs = zarr.open_array(
            zarr_susc_path,
            mode="w",
            shape=susc_3d.shape,
            dtype="float64",
            chunks=susc_3d.shape,
        )
        zs[:] = susc_3d

    # ── Write metadata Parquet ────────────────────────────────────────────────
    meta: dict = {
        "misfit_pct":     [float(misfit)],
        "chi2_reduced":   [float(chi2)],
        "lambda":         [float(lambda_used)],
        "grid_nx":        [nx],
        "grid_ny":        [ny],
        "grid_nz":        [nz],
        "n_voxels":       [expected_n],
        "density_min":    [float(np.nanmin(density_flat))],
        "density_max":    [float(np.nanmax(density_flat))],
        "density_mean":   [float(np.nanmean(density_flat))],
        "density_std":    [float(np.nanstd(density_flat))],
    }
    for k, v in params_dict.items():
        if k not in meta and isinstance(v, (int, float, str, bool)):
            meta[k] = [v]

    pd.DataFrame(meta).to_parquet(parquet_path, index=False)

    return {
        "zarr_density":        zarr_density_path,
        "zarr_susceptibility": zarr_susc_path,
        "parquet_metadata":    parquet_path,
    }


def save_jacobian_zarr(
    jacobian_dense: np.ndarray,
    output_path: str,
    chunk_size: int = 1000,
) -> str:
    """
    Save Jacobian matrix (n_sensors, n_voxels) to Zarr with sensor-batch chunking.

    Chunks rows (sensors) in groups of chunk_size so downstream code can stream
    sensor batches without loading the full matrix into RAM.

    Returns: absolute path to the written .zarr store.
    """
    j = np.asarray(jacobian_dense, dtype=np.float64)
    if j.ndim != 2:
        raise ValueError(f"jacobian_dense must be 2-D, got shape {j.shape}")
    n_sensors, n_voxels = j.shape
    chunks = (min(chunk_size, n_sensors), n_voxels)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    z = zarr.open_array(
        output_path,
        mode="w",
        shape=(n_sensors, n_voxels),
        dtype="float64",
        chunks=chunks,
    )
    z[:] = j
    return output_path
