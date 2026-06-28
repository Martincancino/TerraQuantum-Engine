"""
FASE 8.2c (Live Update local — RE-SOLVE POR SUB-OCTREE) — live_update_suboctree.

Refina SOLO una sub-región local del modelo con el fondo congelado. Verifica:
 - PROPIEDAD CLAVE del sub-octree: las celdas FUERA de la sub-región quedan
   byte-idénticas a m0;
 - re-solve con dato nuevo local reduce el misfit del dato (exist.+nuevo);
 - región por mask ≡ región por centro+radio;
 - respeta bounds; determinista; preserva aire; valida entradas.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import GravimetryForward, GravimetryInversion


NX, NY, NZ, BLOCK = 8, 4, 8, 10.0


def _synthetic_setup():
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F").astype(np.float64) * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F").astype(np.float64) * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F").astype(np.float64) * BLOCK + BLOCK / 2
    sx, sz = np.meshgrid(
        np.arange(NX) * BLOCK + BLOCK / 2,
        np.arange(NZ) * BLOCK + BLOCK / 2,
        indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()]).astype(np.float64)
    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=200.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(len(x_c))
    mask = ((x_c - 40.0) ** 2 + (y_c - 20.0) ** 2 + (z_c - 40.0) ** 2) < 22.0 ** 2
    true[mask] = 0.8
    g_obs = kernel @ true
    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    return inv, forward, sensors, x_c, y_c, z_c, g_obs, true


CENTER = (40.0, 20.0, 40.0)
RADIUS = 18.0


def test_outside_region_is_frozen_byte_identical():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    m0 = true.copy()
    out = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        new_sensor_coords=np.array([[40.0, -5.0, 40.0]]),
        new_g_observed=np.array([g_obs.max() * 1.5]),
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    in_S = ((x_c - CENTER[0]) ** 2 + (y_c - CENTER[1]) ** 2 + (z_c - CENTER[2]) ** 2) <= RADIUS ** 2
    # Fuera de S: idéntico bit a bit a m0.
    np.testing.assert_array_equal(out["model"][~in_S], m0[~in_S])
    # Dentro de S: algo cambió.
    assert out["update_norm"] > 0.0
    assert out["region_size"] == int(np.sum(in_S))


def test_resolve_reduces_data_misfit():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    # m0 subestima el cuerpo (mitad de densidad) → re-solve local debe mejorar el ajuste.
    m0 = true * 0.5
    out = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1,
    )
    assert out["region_misfit_after"] < out["region_misfit_before"], (
        f"{out['region_misfit_before']:.3g} → {out['region_misfit_after']:.3g}"
    )


def test_mask_equals_center_radius():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    m0 = true * 0.5
    in_S = ((x_c - CENTER[0]) ** 2 + (y_c - CENTER[1]) ** 2 + (z_c - CENTER[2]) ** 2) <= RADIUS ** 2
    kw = dict(lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1)
    a = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS, **kw,
    )
    b = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_mask=in_S, **kw,
    )
    np.testing.assert_allclose(a["model"], b["model"])


def test_respects_bounds():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    m0 = true * 0.5
    out = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        new_sensor_coords=np.array([[40.0, -5.0, 40.0]]),
        new_g_observed=np.array([g_obs.max() * 5.0]),
        lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.05,
        density_min=0.0, density_max=1.0,
    )
    vals = out["model"][np.isfinite(out["model"])]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 1.0 + 1e-9


def test_deterministic():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    m0 = true * 0.5
    kw = dict(region_center=CENTER, region_radius=RADIUS,
              lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1)
    a = inv.live_update_suboctree(m0, g_obs, y_c, forward, sensors, x_c, z_c, **kw)
    b = inv.live_update_suboctree(m0, g_obs, y_c, forward, sensors, x_c, z_c, **kw)
    np.testing.assert_array_equal(a["model"], b["model"])


def test_air_cells_preserved():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    topo = np.full(inv.total_voxels, BLOCK)   # primera capa = aire
    m0 = true.copy()
    voxel_top = y_c - BLOCK / 2.0
    air = voxel_top < topo
    m0[air] = np.nan
    out = inv.live_update_suboctree(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        topography_elevations=topo, lambda_mag=1e-3, alpha_spatial=0.5,
    )
    assert np.isnan(out["model"][air]).all()
    assert np.isfinite(out["model"][~air]).all()


def test_validation_errors():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    m0 = true.copy()
    # Falta definir la región.
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(m0, g_obs, y_c, forward, sensors, x_c, z_c)
    # m0 mal dimensionado.
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(
            m0[:-1], g_obs, y_c, forward, sensors, x_c, z_c,
            region_center=CENTER, region_radius=RADIUS,
        )
    # Región vacía (radio 0 en un punto sin celda exacta) → error.
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(
            m0, g_obs, y_c, forward, sensors, x_c, z_c,
            region_center=(9999.0, 9999.0, 9999.0), region_radius=1.0,
        )
