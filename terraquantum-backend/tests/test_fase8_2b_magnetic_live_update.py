"""
FASE 8.2b (Live Update local — PARIDAD MAGNÉTICA) — actualización de Woodbury rango-k.

Espejo del test de gravimetría (test_fase8_2_live_update_woodbury.py, Nivel 2) para el
motor MAGNÉTICO: MagnetometryInversion.live_update_add_data. El helper standalone
woodbury_low_rank_update es COMPARTIDO (vive en gravimetry.py) y ya está cubierto
airtight por el Nivel 1 de ese test; aquí solo se valida el método de motor con el
scaling magnético (Wz_inv depth-weighting, sin Ws, unidades SI).

Verifica: misfit del dato TMI nuevo BAJA; no-op con dato consistente; respeta bounds;
determinismo; preserva máscara de aire; rechaza tamaños inválidos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ, BS = 8, 4, 8, 30.0


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
    mask = ((x_c - 120.0) ** 2 + (y_c - 60.0) ** 2 + (z_c - 120.0) ** 2) < 60.0 ** 2
    true[mask] = 0.2
    d_obs = G @ true
    return inv, fwd, sensors, x_c, y_c, z_c, d_obs, true


def _new_sensor():
    return np.array([[135.0, -15.0, 135.0]], dtype=np.float64)


def _kernel_new(fwd, x_c, y_c, z_c, new_xyz):
    return fwd._build_sparse_kernel(x_c, y_c, z_c, new_xyz)


def test_live_update_reduces_new_data_misfit():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    pred0 = float((_kernel_new(fwd, x_c, y_c, z_c, new_xyz) @ true)[0])
    new_d = np.array([pred0 * 1.6])

    out = inv.live_update_add_data(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_d_observed=new_d,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    assert out["n_new"] == 1
    assert out["model"].shape == (inv.total_voxels,)
    assert out["new_data_misfit_after"] < out["new_data_misfit_before"], (
        f"{out['new_data_misfit_before']:.3g} → {out['new_data_misfit_after']:.3g}"
    )
    assert np.isfinite(out["capacitance_cond"]) and out["capacitance_cond"] >= 1.0


def test_live_update_noop_when_consistent():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    consistent = np.array([float((_kernel_new(fwd, x_c, y_c, z_c, new_xyz) @ true)[0])])

    out = inv.live_update_add_data(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_d_observed=consistent,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    np.testing.assert_allclose(out["model"], true, atol=1e-5)
    assert out["update_norm"] < 1e-3


def test_live_update_respects_bounds():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    pred0 = float((_kernel_new(fwd, x_c, y_c, z_c, new_xyz) @ true)[0])
    new_d = np.array([pred0 * 5.0])

    out = inv.live_update_add_data(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_d_observed=new_d,
        lambda_mag=1e-3, alpha_spatial=1.0,
        susceptibility_min=0.0, susceptibility_max=0.25,
    )
    vals = out["model"][np.isfinite(out["model"])]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 0.25 + 1e-9


def test_live_update_deterministic():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    kw = dict(
        new_sensor_coords=new_xyz, new_d_observed=np.array([1.0]),
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    a = inv.live_update_add_data(true, d_obs, y_c, fwd, sensors, x_c, z_c, **kw)
    b = inv.live_update_add_data(true, d_obs, y_c, fwd, sensors, x_c, z_c, **kw)
    np.testing.assert_array_equal(a["model"], b["model"])


def test_live_update_air_cells_preserved():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    topo = np.full(inv.total_voxels, BS)   # primera capa = aire
    m0 = true.copy()
    voxel_top = y_c - BS / 2.0
    air = voxel_top < topo
    m0[air] = np.nan
    new_xyz = _new_sensor()
    out = inv.live_update_add_data(
        m0, d_obs, y_c, fwd, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_d_observed=np.array([1.0]),
        topography_elevations=topo, lambda_mag=1e-3, alpha_spatial=1.0,
    )
    assert np.isnan(out["model"][air]).all()
    assert np.isfinite(out["model"][~air]).all()


def test_live_update_rejects_wrong_sizes():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    with np.testing.assert_raises(ValueError):
        inv.live_update_add_data(
            true[:-1], d_obs, y_c, fwd, sensors, x_c, z_c,
            new_sensor_coords=new_xyz, new_d_observed=np.array([1.0]),
        )
    with np.testing.assert_raises(ValueError):
        inv.live_update_add_data(
            true, d_obs, y_c, fwd, sensors, x_c, z_c,
            new_sensor_coords=new_xyz, new_d_observed=np.array([1.0, 2.0]),
        )
