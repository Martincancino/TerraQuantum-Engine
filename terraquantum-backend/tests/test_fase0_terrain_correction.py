"""
FASE 0 Tarea 0.4 — Corrección de terreno: renombrar (no es prisma).

compute_terrain_correction_prism implementaba SOLO masa-puntual
(G·ρ·área·|dh|/r²) pero el nombre/comentarios prometían "exact prism formula".
Se renombró a compute_terrain_correction_pointmass (alias viejo deprecado).

Verifica:
  - alias deprecado apunta a la misma función;
  - TC >= 0 siempre (propiedad matemática);
  - el valor coincide con la suma analítica de masa-puntual (lejos del campo
    cercano), confirmando que ES masa-puntual y no un prisma exacto.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from services.gravity_corrections_service import (
    _G_NEWTON,
    compute_terrain_correction_pointmass,
    compute_terrain_correction_prism,
)


def test_deprecated_alias_is_same_function():
    assert compute_terrain_correction_prism is compute_terrain_correction_pointmass


def _dem_with_hill():
    cell = 50.0
    xs = np.arange(0.0, 2000.0, cell)
    zs = np.arange(0.0, 2000.0, cell)
    elev = np.zeros((zs.size, xs.size))
    # Colina suave centrada.
    xx, zz = np.meshgrid(xs, zs)
    elev += 80.0 * np.exp(-(((xx - 1000.0) ** 2 + (zz - 1000.0) ** 2) / (2 * 300.0 ** 2)))
    return xs, zs, elev, cell


def test_tc_non_negative_always():
    xs, zs, elev, cell = _dem_with_hill()
    stations_x = np.array([500.0, 1000.0, 1500.0])
    stations_z = np.array([500.0, 1000.0, 1500.0])
    stations_e = np.array([0.0, 80.0, 0.0])
    tc = compute_terrain_correction_pointmass(
        stations_x, stations_z, stations_e, xs, zs, elev, cell,
        reduction_density_gcc=2.67, max_radius_m=22000.0,
    )
    assert np.all(tc >= 0.0), f"TC negativa: {tc}"
    assert np.all(np.isfinite(tc))


def test_tc_matches_pointmass_formula():
    # DEM con UNA sola celda elevada lejos de la estación → suma de masa puntual
    # analítica exacta (sin campo cercano, sin prisma).
    cell = 50.0
    xs = np.array([0.0, 1000.0])
    zs = np.array([0.0])
    elev = np.array([[0.0, 30.0]])  # (nz=1, nx=2): celda lejana elevada 30 m
    sx = np.array([0.0]); sz = np.array([0.0]); se = np.array([0.0])

    tc = compute_terrain_correction_pointmass(
        sx, sz, se, xs, zs, elev, cell,
        reduction_density_gcc=2.67, max_radius_m=22000.0,
    )
    rho = 2.67 * 1000.0
    r = 1000.0
    expected_mgal = _G_NEWTON * rho * (cell ** 2) * 30.0 / r ** 2 * 1e5
    np.testing.assert_allclose(tc[0], expected_mgal, rtol=1e-9)
