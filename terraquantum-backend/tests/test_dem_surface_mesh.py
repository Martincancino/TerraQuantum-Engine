"""
FASE 24B — Tarea 3: Superficie de malla suave (anti-staircase).

Verifica interpolate_surface_depths (core/geo_utils):
  - Terreno ONDULADO: la interpolación lineal reconstruye la superficie real entre
    sensores con MENOS error que nearest-neighbor (que escalona en bloques).
  - Terreno PLANO: lineal y nearest coinciden (sin regresión).
  - Geometría degenerada (<3 sensores / colineales): fallback robusto a nearest.
  - Columnas fuera del convex hull (extrapolación): fallback nearest (no NaN).
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.geo_utils import interpolate_surface_depths


def _true_relief(x, z):
    """Superficie de profundidad 'real' con relieve suave (quebrada/loma)."""
    return 30.0 * np.sin(x / 120.0) + 18.0 * np.cos(z / 90.0)


def test_linear_beats_nearest_on_rough_terrain():
    rng = np.random.default_rng(3)
    # Sensores dispersos en un dominio 400×400 m
    sx = rng.uniform(20, 380, size=36)
    sz = rng.uniform(20, 380, size=36)
    sensor_xz = np.column_stack([sx, sz])
    surface_depths = _true_relief(sx, sz)

    # Columnas de grilla densas DENTRO del hull de sensores (terreno entre estaciones)
    gx, gz = np.meshgrid(np.linspace(60, 340, 24), np.linspace(60, 340, 24))
    grid_xz = np.column_stack([gx.ravel(), gz.ravel()])
    truth = _true_relief(grid_xz[:, 0], grid_xz[:, 1])

    depths_lin, mode = interpolate_surface_depths(sensor_xz, surface_depths, grid_xz)
    assert mode == "linear+nearest_fallback"

    # nearest de referencia (mismo helper con 1 sensor por columna no aplica; lo
    # calculamos directo para comparar)
    from scipy.spatial import cKDTree
    _, nidx = cKDTree(sensor_xz).query(grid_xz)
    depths_near = surface_depths[nidx]

    err_lin = float(np.sqrt(np.mean((depths_lin - truth) ** 2)))
    err_near = float(np.sqrt(np.mean((depths_near - truth) ** 2)))
    print(f"\n[FASE 24B T3] RMS superficie: nearest={err_near:.1f}m linear={err_lin:.1f}m")

    assert err_lin < err_near, (
        f"lineal debe reducir el error de superficie vs nearest "
        f"(linear={err_lin:.1f}m, nearest={err_near:.1f}m)"
    )
    # Mejora sustancial (anti-staircase real, no marginal)
    assert err_lin <= 0.8 * err_near


def test_flat_terrain_no_regression():
    """Terreno plano: lineal == nearest == constante (sin regresión)."""
    sensor_xz = np.array([[0, 0], [100, 0], [0, 100], [100, 100], [50, 50]], float)
    surface_depths = np.full(5, 12.5)
    grid_xz = np.column_stack([
        np.repeat(np.linspace(10, 90, 9), 9),
        np.tile(np.linspace(10, 90, 9), 9),
    ])
    depths, mode = interpolate_surface_depths(sensor_xz, surface_depths, grid_xz)
    assert np.allclose(depths, 12.5), "terreno plano debe dar profundidad constante"


def test_degenerate_geometry_falls_back_to_nearest():
    """<3 sensores → nearest puro (no crash)."""
    sensor_xz = np.array([[0, 0], [100, 100]], float)
    surface_depths = np.array([5.0, 25.0])
    grid_xz = np.array([[10, 10], [90, 90], [50, 50]], float)
    depths, mode = interpolate_surface_depths(sensor_xz, surface_depths, grid_xz)
    assert mode == "nearest"
    assert np.all(np.isfinite(depths))
    # cada columna recibe la profundidad del sensor más cercano
    assert depths[0] == 5.0 and depths[1] == 25.0


def test_outside_hull_uses_nearest_fallback_no_nan():
    """Columnas fuera del convex hull → fallback nearest, nunca NaN."""
    sensor_xz = np.array([[100, 100], [200, 100], [100, 200], [200, 200]], float)
    surface_depths = np.array([10.0, 20.0, 30.0, 40.0])
    # Algunas columnas dentro, otras MUY fuera del hull
    grid_xz = np.array([[150, 150], [0, 0], [500, 500], [150, 50]], float)
    depths, mode = interpolate_surface_depths(sensor_xz, surface_depths, grid_xz)
    assert np.all(np.isfinite(depths)), "no debe haber NaN fuera del hull"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
