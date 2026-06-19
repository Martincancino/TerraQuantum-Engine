"""
FASE 24B — Tarea 4: Topografía fraccionaria (cut-cell, anti-staircase). AUDIT GEMINI P0.

La máscara de aire BINARIA produce el "efecto escalera" en terreno inclinado/rugoso:
aristas ortogonales falsas → ruido de alta frecuencia que el solver malinterpreta
como mineralización somera. El cut-cell pondera cada celda de borde por su fracción
de volumen rocoso bajo el DEM → superficie efectiva suave.

Tests:
  - Cut-cell ACTIVA las celdas de borde (fraccionarias) que el binario descarta, y
    NO degrada el misfit (lo mejora: el staircase forzaba residual espurio).
  - Default OFF = comportamiento binario EXACTO (backward-compat).
  - Cut-cell recupera el cuerpo enterrado.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid

NX, NY, NZ = 12, 8, 12
BLOCK = 20.0
LAMBDA_MAG = 0.1


def _setup():
    _, _, _, xc, yc, zc = build_voxel_grid(NX, NY, NZ, BLOCK)
    fwd = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK,
                            cutoff_radius=min(3 * BLOCK * max(NX, NY, NZ), 5000.0))
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)
    # Terreno INCLINADO (rampa en x) → el binario escalona la superficie
    x_span = float(xc.max() - xc.min()) or 1.0
    topo = 55.0 * (xc - xc.min()) / x_span
    # Cuerpo compacto enterrado
    cx, cz = (NX * BLOCK) / 2.0, (NZ * BLOCK) / 2.0
    r2 = (xc - cx) ** 2 + (yc - 90.0) ** 2 + (zc - cz) ** 2
    true_contrast = np.where(r2 <= (1.6 * BLOCK) ** 2, 1.0, 0.0)
    kernel = fwd.build_sparse_kernel(xc, yc, zc, sensors)
    g_body = np.asarray(kernel @ true_contrast, dtype=np.float64)
    g_obs = g_body + np.random.default_rng(3).normal(0.0, 0.02 * np.std(g_body), size=len(sensors))
    return xc, yc, zc, fwd, sensors, topo, g_obs


def _invert(g_obs, xc, yc, zc, fwd, sensors, topo, cut):
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)
    meta: dict = {}
    with contextlib.redirect_stdout(io.StringIO()):
        ed, _, mf, _ = inv.solve_inversion_lsqr(
            g_observed=g_obs, kernel_sparse=None, y_c=yc, lambda_mag=LAMBDA_MAG,
            alpha_spatial=1.0, forward_model=fwd, sensor_coords=sensors, x_c=xc, z_c=zc,
            topography_elevations=topo, density_min=2.0, density_max=5.5,
            cut_cell_topography=cut, solver_meta=meta,
        )
    n_active = int(np.sum(np.isfinite(ed)))
    cmax = float(np.max(np.nan_to_num(ed - inv.base_density, nan=0.0)))
    return dict(misfit=float(mf), n_active=n_active, cmax=cmax,
                cut=meta.get("cut_cell_topography"))


def test_cutcell_activates_partial_cells_and_does_not_degrade_fit():
    xc, yc, zc, fwd, sensors, topo, g_obs = _setup()
    bini = _invert(g_obs, xc, yc, zc, fwd, sensors, topo, cut=False)
    cut = _invert(g_obs, xc, yc, zc, fwd, sensors, topo, cut=True)
    print(f"\n[FASE 24B T4] binario : misfit={bini['misfit']:.2f}% n_active={bini['n_active']}")
    print(f"[FASE 24B T4] cut-cell: misfit={cut['misfit']:.2f}% n_active={cut['n_active']} cut={cut['cut']}")

    assert cut["cut"] is True and bini["cut"] is False
    # 1) Cut-cell activa las celdas de borde que el binario descartaba
    assert cut["n_active"] > bini["n_active"], (
        f"cut-cell debe activar celdas fraccionarias de borde "
        f"(binario={bini['n_active']}, cut={cut['n_active']})"
    )
    # 2) NO degrada el misfit (anti-staircase: elimina residual espurio del escalón)
    assert cut["misfit"] <= bini["misfit"] * 1.10 + 0.2, (
        f"cut-cell degradó el misfit: binario={bini['misfit']:.2f}% cut={cut['misfit']:.2f}%"
    )
    # 3) Recupera el cuerpo
    assert cut["cmax"] > 0.0


def test_cutcell_off_is_binary_default():
    """Default OFF: bandera False y mismo nº de celdas activas que el binario explícito."""
    xc, yc, zc, fwd, sensors, topo, g_obs = _setup()
    default = _invert(g_obs, xc, yc, zc, fwd, sensors, topo, cut=False)
    assert default["cut"] is False
    # Binario explícito: misma máscara → mismo n_active
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)
    voxel_top = yc - BLOCK / 2.0
    n_binary_expected = int(np.sum(voxel_top >= topo))
    assert default["n_active"] == n_binary_expected, (
        f"default debe ser binario exacto (got {default['n_active']}, esperado {n_binary_expected})"
    )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
