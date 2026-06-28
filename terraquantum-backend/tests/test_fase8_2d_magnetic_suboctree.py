"""
FASE 8.2d (Live Update local — RE-SOLVE POR SUB-OCTREE, PARIDAD MAGNÉTICA).

Espejo del test de gravimetría (test_fase8_2c_suboctree_resolve.py) para el motor
MAGNÉTICO: MagnetometryInversion.live_update_suboctree (scaling Wz_inv, sin Ws, SI).

Verifica: celdas FUERA de la sub-región byte-idénticas a m0; re-solve baja el misfit;
mask ≡ centro+radio; bounds; determinismo; aire preservado; validaciones.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ, BS = 8, 4, 8, 30.0
CENTER = (120.0, 60.0, 120.0)
RADIUS = 55.0


def _synthetic_setup():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    xs = np.linspace(BS, (NX - 1) * BS, 6)
    zs = np.linspace(BS, (NZ - 1) * BS, 6)
    xg, zg = np.meshgrid(xs, zs)
    sensors = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()]).astype(np.float64)
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    mask = ((x_c - CENTER[0]) ** 2 + (y_c - CENTER[1]) ** 2 + (z_c - CENTER[2]) ** 2) < 50.0 ** 2
    true[mask] = 0.2
    d_obs = G @ true
    return inv, fwd, sensors, x_c, y_c, z_c, d_obs, true


def test_outside_region_is_frozen_byte_identical():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true.copy()
    out = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        new_sensor_coords=np.array([[120.0, -15.0, 120.0]]),
        new_d_observed=np.array([d_obs.max() * 1.5]),
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    in_S = ((x_c - CENTER[0]) ** 2 + (y_c - CENTER[1]) ** 2 + (z_c - CENTER[2]) ** 2) <= RADIUS ** 2
    np.testing.assert_array_equal(out["model"][~in_S], m0[~in_S])
    assert out["update_norm"] > 0.0
    assert out["region_size"] == int(np.sum(in_S))


def test_resolve_reduces_data_misfit():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true * 0.5
    out = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1,
    )
    assert out["region_misfit_after"] < out["region_misfit_before"], (
        f"{out['region_misfit_before']:.3g} → {out['region_misfit_after']:.3g}"
    )


def test_mask_equals_center_radius():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true * 0.5
    in_S = ((x_c - CENTER[0]) ** 2 + (y_c - CENTER[1]) ** 2 + (z_c - CENTER[2]) ** 2) <= RADIUS ** 2
    kw = dict(lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1)
    a = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS, **kw,
    )
    b = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c, region_mask=in_S, **kw,
    )
    np.testing.assert_allclose(a["model"], b["model"])


def test_respects_bounds():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true * 0.5
    out = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        new_sensor_coords=np.array([[120.0, -15.0, 120.0]]),
        new_d_observed=np.array([d_obs.max() * 5.0]),
        lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.05,
        susceptibility_min=0.0, susceptibility_max=0.25,
    )
    vals = out["model"][np.isfinite(out["model"])]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 0.25 + 1e-9


def test_deterministic():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true * 0.5
    kw = dict(region_center=CENTER, region_radius=RADIUS,
              lambda_mag=1e-3, alpha_spatial=0.5, anchor_strength=0.1)
    a = inv.live_update_suboctree(m0, d_obs, y_c, fwd, sensors, x_c, z_c, **kw)
    b = inv.live_update_suboctree(m0, d_obs, y_c, fwd, sensors, x_c, z_c, **kw)
    np.testing.assert_array_equal(a["model"], b["model"])


def test_air_cells_preserved():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    topo = np.full(inv.total_voxels, BS)
    m0 = true.copy()
    voxel_top = y_c - BS / 2.0
    air = voxel_top < topo
    m0[air] = np.nan
    out = inv.live_update_suboctree(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        region_center=CENTER, region_radius=RADIUS,
        topography_elevations=topo, lambda_mag=1e-3, alpha_spatial=0.5,
    )
    assert np.isnan(out["model"][air]).all()
    assert np.isfinite(out["model"][~air]).all()


def test_validation_errors():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    m0 = true.copy()
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(m0, d_obs, y_c, fwd, sensors, x_c, z_c)
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(
            m0[:-1], d_obs, y_c, fwd, sensors, x_c, z_c,
            region_center=CENTER, region_radius=RADIUS,
        )
    with np.testing.assert_raises(ValueError):
        inv.live_update_suboctree(
            m0, d_obs, y_c, fwd, sensors, x_c, z_c,
            region_center=(9999.0, 9999.0, 9999.0), region_radius=1.0,
        )
