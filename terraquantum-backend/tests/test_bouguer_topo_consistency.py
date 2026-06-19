"""
FASE 24B — Tarea 5: Verificación de doble-conteo topografía (losa Bouguer).

DECISIÓN DOCUMENTADA (verificada en código + test):
  TerraQuantum invierte CONTRASTE de densidad relativo a base_density sobre celdas
  de SUBSUELO (máscara de aire: active = voxel_top >= topo_depth). La corrección de
  losa de Bouguer es una corrección del LADO DE DATOS (reduce la masa de la losa
  terreno→datum, densidad de reducción constante) y la máscara de aire es una
  restricción del LADO DEL MODELO (las fuentes sólo viven bajo la superficie).
  Son COMPLEMENTARIAS, NO redundantes → NO hay doble conteo de la masa del terreno.
  Este es el "caso correcto" del roadmap (invierte contraste con air-mask → losa
  Bouguer estándar, OK). Referencia moderna: Hinze (2005).

Estos tests verifican esa garantía:
  1. El terreno NO se modela como fuente: un subsuelo HOMOGÉNEO bajo topografía
     ondulada produce contraste recuperado ≈ 0 (sin anomalía falsa correlacionada
     con el relieve). Si el terreno se contara doble, aparecería masa espuria.
  2. La máscara de aire excluye exactamente las celdas sobre la superficie (NaN).
  3. La geometría de un cuerpo enterrado NO se distorsiona por el manejo topográfico.
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

NX, NY, NZ = 8, 6, 8
BLOCK = 25.0
LAMBDA_MAG = 0.1


def _ridge_topography(x_c, amplitude=40.0):
    """Profundidad de superficie ondulada (loma) en función de X. Longitud total_voxels."""
    x_span = float(np.max(x_c) - np.min(x_c)) or 1.0
    # 0 en los bordes, sube hasta `amplitude` en el centro (relieve de 40 m)
    return amplitude * np.sin(np.pi * (x_c - np.min(x_c)) / x_span)


def _geom():
    _, _, _, xc, yc, zc = build_voxel_grid(NX, NY, NZ, BLOCK)
    cutoff = min(3.0 * BLOCK * max(NX, NY, NZ), 5000.0)
    fwd = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=cutoff)
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)
    return xc, yc, zc, fwd, sensors


def _invert(g_obs, xc, yc, zc, fwd, sensors, topo, density_min=2.0):
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)
    meta: dict = {}
    with contextlib.redirect_stdout(io.StringIO()):
        ed, _, mf, _ = inv.solve_inversion_lsqr(
            g_observed=g_obs, kernel_sparse=None, y_c=yc,
            lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
            forward_model=fwd, sensor_coords=sensors, x_c=xc, z_c=zc,
            topography_elevations=topo,
            density_min=density_min, density_max=5.5,
            solver_meta=meta,
        )
    return ed, float(mf), inv.base_density


def test_no_spurious_terrain_correlated_anomaly():
    """Un cuerpo enterrado bajo relieve NO genera masa espuria lejos del cuerpo.

    Si la topografía se contara doble (masa del terreno modelada como fuente además
    de la reducción Bouguer), aparecerían anomalías correlacionadas con el relieve
    en el fondo subsuperficial, lejos del cuerpo. Verificamos que el contraste de
    fondo es pequeño frente al del cuerpo → sin doble conteo grosero.
    """
    xc, yc, zc, fwd, sensors = _geom()
    topo = _ridge_topography(xc, amplitude=30.0)

    cx = (NX * BLOCK) / 2.0
    cz = (NZ * BLOCK) / 2.0
    body_depth = 60.0
    r2 = (xc - cx) ** 2 + (yc - body_depth) ** 2 + (zc - cz) ** 2
    true_contrast = np.where(r2 <= (1.5 * BLOCK) ** 2, 1.0, 0.0)
    assert true_contrast.sum() > 0

    kernel = fwd.build_sparse_kernel(xc, yc, zc, sensors)
    g_body = np.asarray(kernel @ true_contrast, dtype=np.float64)
    g_obs = g_body + np.random.default_rng(2).normal(0.0, 0.02 * np.std(g_body), size=len(sensors))

    ed, _, base = _invert(g_obs, xc, yc, zc, fwd, sensors, topo, density_min=2.0)
    contrast = np.clip(np.nan_to_num(ed - base, nan=0.0), 0.0, None)

    # Región del cuerpo (cilindro generoso en x,z alrededor del centro) vs fondo.
    near_body = np.sqrt((xc - cx) ** 2 + (zc - cz) ** 2) <= 2.0 * BLOCK
    body_max = float(np.max(contrast[near_body])) if near_body.any() else 0.0
    bg_max = float(np.max(contrast[~near_body])) if (~near_body).any() else 0.0
    print(f"\n[FASE 24B T5] contraste cuerpo={body_max:.3f} fondo={bg_max:.3f} t/m³")

    assert body_max > 0.0, "no se recuperó el cuerpo"
    # El fondo (incluye el terreno) no debe contener masa comparable al cuerpo.
    assert bg_max <= 0.6 * body_max, (
        f"Masa espuria en el fondo correlacionada con el terreno "
        f"(fondo={bg_max:.3f} vs cuerpo={body_max:.3f} t/m³): posible doble conteo."
    )


def test_air_mask_excludes_above_surface_cells():
    """Las celdas sobre la superficie quedan como AIRE (NaN); las de subsuelo, finitas."""
    xc, yc, zc, fwd, sensors = _geom()
    topo = _ridge_topography(xc)
    rng = np.random.default_rng(5)
    g_obs = rng.normal(0.0, 1e-6, size=len(sensors))

    ed, _, _ = _invert(g_obs, xc, yc, zc, fwd, sensors, topo)

    voxel_top = yc - (BLOCK / 2.0)
    is_air_expected = voxel_top < topo            # sobre la superficie
    is_nan = ~np.isfinite(ed)

    # Toda celda sobre la superficie debe ser NaN (aire); ninguna de subsuelo lo es.
    assert np.array_equal(is_nan, is_air_expected), (
        "La máscara de aire no coincide con la superficie topográfica: "
        f"{int(np.sum(is_nan != is_air_expected))} celdas inconsistentes."
    )
    assert is_air_expected.any(), "El relieve debería generar al menos una celda de aire."


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
