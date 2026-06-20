"""
FASE 20B Tarea 2 — Incertidumbre posterior por vóxel (Hutchinson) del motor MAGNÉTICO.

Verifica paridad con gravimetry.estimate_posterior_std:
  - σ posterior por vóxel de susceptibilidad, dimensiones correctas (total_voxels).
  - σ ≥ 0 y finito en celdas activas; NaN en celdas de aire (bajo topografía).
  - Determinismo (misma seed → mismo resultado).
  - σ crece con la profundidad (menos resolución abajo) — sanidad física.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ = 6, 6, 6
BS = 30.0


def _setup():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    xs = np.linspace(BS, (NX - 1) * BS, 5)
    zs = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs, zs)
    sensors = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[2 * NY * NZ + 2 * NZ + 2] = 0.2
    d_obs = G @ true
    return inv, fwd, sensors, x_c, y_c, z_c, d_obs


def test_posterior_std_shape_and_positive():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs = _setup()
    std = inv.estimate_posterior_std(
        d_observed=d_obs, y_c=y_c, forward_model=fwd,
        sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0, n_probes=16,
    )
    assert std.shape == (NX * NY * NZ,)
    finite = std[np.isfinite(std)]
    assert finite.size == NX * NY * NZ      # topo plana → todas activas
    assert (finite >= 0.0).all()
    assert finite.max() > 0.0


def test_posterior_std_air_cells_nan():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs = _setup()
    # Topografía: enmascara la primera capa (y<30 = aire) → esos vóxeles deben ser NaN.
    topo = np.full(NX * NY * NZ, BS)   # superficie a y=30 m
    std = inv.estimate_posterior_std(
        d_observed=d_obs, y_c=y_c, forward_model=fwd,
        sensor_coords=sensors, x_c=x_c, z_c=z_c,
        topography_elevations=topo,
        lambda_mag=1e-3, alpha_spatial=1.0, n_probes=16,
    )
    voxel_top = y_c - BS / 2.0
    air = voxel_top < topo
    assert np.isnan(std[air]).all(), "Celdas de aire deben ser NaN."
    assert np.isfinite(std[~air]).all(), "Celdas activas deben ser finitas."


def test_posterior_std_deterministic():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs = _setup()
    kw = dict(d_observed=d_obs, y_c=y_c, forward_model=fwd,
              sensor_coords=sensors, x_c=x_c, z_c=z_c,
              lambda_mag=1e-3, alpha_spatial=1.0, n_probes=16, seed=42)
    a = inv.estimate_posterior_std(**kw)
    b = inv.estimate_posterior_std(**kw)
    np.testing.assert_allclose(np.nan_to_num(a), np.nan_to_num(b))


def test_posterior_std_grows_with_depth():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs = _setup()
    std = inv.estimate_posterior_std(
        d_observed=d_obs, y_c=y_c, forward_model=fwd,
        sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0, n_probes=24,
    )
    # σ media por capa de profundidad: debe ser monótona creciente (menos resolución).
    layer_means = []
    for iy in range(NY):
        mask = np.isclose(y_c, (iy + 0.5) * BS)
        layer_means.append(float(np.nanmean(std[mask])))
    assert layer_means[-1] > layer_means[0], (
        f"σ posterior debería crecer con la profundidad: {layer_means}"
    )
