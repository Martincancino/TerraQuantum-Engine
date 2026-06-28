"""
FASE 8.2 (Live Update local) — actualización de Woodbury rango-k.

Valida en dos niveles:
 1. El helper woodbury_low_rank_update (álgebra pura, EXACTA): la actualización de
    rango-k reproduce, hasta tolerancia, la solución del sistema de información
    aumentado A1 = A + UᵀU, b1 = b0 + Uᵀ d_new resuelto densamente desde cero. Más la
    propiedad no-op: si el dato nuevo ya coincide con la predicción actual, m1 = m0.
 2. El método de motor live_update_add_data: al incorporar una observación nueva el
    misfit del dato nuevo BAJA; con un dato consistente con el modelo no cambia nada;
    respeta bounds; es determinista; preserva la máscara de aire.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import (
    GravimetryForward,
    GravimetryInversion,
    woodbury_low_rank_update,
)


# ───────────────────────── Nivel 1: el helper ──────────────────────────────


def _spd(n, seed):
    rng = np.random.default_rng(seed)
    B = rng.standard_normal((n, n))
    return B @ B.T + np.eye(n) * (n * 0.5)   # bien condicionada, SPD


def test_woodbury_matches_dense_solve():
    """La actualización rango-k == resolver el sistema aumentado desde cero."""
    import scipy.sparse as sp

    n, k = 40, 4
    A = _spd(n, 0)
    rng = np.random.default_rng(1)
    m0 = rng.standard_normal(n)
    b0 = A @ m0                         # ⇒ m0 = A⁻¹ b0 por construcción
    U = rng.standard_normal((k, n))
    d_new = rng.standard_normal(k)

    m1, info = woodbury_low_rank_update(sp.csr_matrix(A), m0, U, d_new, cg_rtol=1e-12)

    A1 = A + U.T @ U
    b1 = b0 + U.T @ d_new
    m1_dense = np.linalg.solve(A1, b1)

    np.testing.assert_allclose(m1, m1_dense, rtol=1e-5, atol=1e-7)
    assert info["n_new"] == k
    assert info["update_norm"] > 0.0


def test_woodbury_rank1():
    import scipy.sparse as sp

    n = 30
    A = _spd(n, 5)
    rng = np.random.default_rng(6)
    m0 = rng.standard_normal(n)
    b0 = A @ m0
    u = rng.standard_normal(n)
    d = 2.5

    m1, _ = woodbury_low_rank_update(sp.csr_matrix(A), m0, u, d, cg_rtol=1e-12)
    m1_dense = np.linalg.solve(A + np.outer(u, u), b0 + u * d)
    np.testing.assert_allclose(m1, m1_dense, rtol=1e-5, atol=1e-7)


def test_woodbury_noop_when_data_already_fit():
    """Si el dato nuevo ya coincide con la predicción actual (d_new = U·m0),
    la actualización es exactamente m1 = m0 (no hay información nueva)."""
    import scipy.sparse as sp

    n, k = 35, 3
    A = _spd(n, 2)
    rng = np.random.default_rng(3)
    m0 = rng.standard_normal(n)
    U = rng.standard_normal((k, n))
    d_new = U @ m0                       # consistente con m0

    m1, info = woodbury_low_rank_update(sp.csr_matrix(A), m0, U, d_new, cg_rtol=1e-12)
    np.testing.assert_allclose(m1, m0, rtol=1e-6, atol=1e-8)
    assert info["update_norm"] < 1e-6


def test_woodbury_empty_update_returns_m0():
    import scipy.sparse as sp

    n = 20
    A = _spd(n, 7)
    m0 = np.arange(n, dtype=np.float64)
    m1, info = woodbury_low_rank_update(
        sp.csr_matrix(A), m0, np.zeros((0, n)), np.zeros(0)
    )
    np.testing.assert_array_equal(m1, m0)
    assert info["n_new"] == 0


def test_woodbury_shape_validation():
    import scipy.sparse as sp

    n = 10
    A = sp.csr_matrix(_spd(n, 8))
    m0 = np.zeros(n)
    with np.testing.assert_raises(ValueError):
        woodbury_low_rank_update(A, m0, np.zeros((2, n + 1)), np.zeros(2))   # U mal
    with np.testing.assert_raises(ValueError):
        woodbury_low_rank_update(A, m0, np.zeros((2, n)), np.zeros(3))       # d_new mal


def test_woodbury_deterministic():
    import scipy.sparse as sp

    n, k = 25, 2
    A = sp.csr_matrix(_spd(n, 9))
    rng = np.random.default_rng(10)
    m0 = rng.standard_normal(n)
    U = rng.standard_normal((k, n))
    d = rng.standard_normal(k)
    a, _ = woodbury_low_rank_update(A, m0, U, d)
    b, _ = woodbury_low_rank_update(A, m0, U, d)
    np.testing.assert_array_equal(a, b)


# ───────────────────── Nivel 2: el método de motor ─────────────────────────


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
    mask = ((x_c - 40.0) ** 2 + (y_c - 20.0) ** 2 + (z_c - 40.0) ** 2) < 25.0 ** 2
    true[mask] = 0.8
    g_obs = kernel @ true
    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    return inv, forward, sensors, x_c, y_c, z_c, g_obs, true


def _new_sensor():
    # Un sensor nuevo sobre el cuerpo, a media altura entre la malla existente.
    return np.array([[45.0, -5.0, 45.0]], dtype=np.float64)


def test_live_update_reduces_new_data_misfit():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    # Predicción actual del modelo en el sensor nuevo, y un dato nuevo que NO encaja
    # (1.6×) → el modelo lo subestima; el update debe acercarlo.
    G_new = forward.build_sparse_kernel(x_c, y_c, z_c, new_xyz)
    pred0 = float((G_new @ true)[0])
    new_g = np.array([pred0 * 1.6])

    out = inv.live_update_add_data(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_g_observed=new_g,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    assert out["n_new"] == 1
    assert out["model"].shape == (inv.total_voxels,)
    assert out["new_data_misfit_after"] < out["new_data_misfit_before"], (
        f"el update debe reducir el misfit del dato nuevo: "
        f"{out['new_data_misfit_before']:.3g} → {out['new_data_misfit_after']:.3g}"
    )
    assert np.isfinite(out["capacitance_cond"]) and out["capacitance_cond"] >= 1.0


def test_live_update_noop_when_consistent():
    """Dato nuevo = predicción actual del modelo ⇒ no hay información nueva ⇒
    el modelo no cambia (propiedad no-op del Woodbury, end-to-end en el motor)."""
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    G_new = forward.build_sparse_kernel(x_c, y_c, z_c, new_xyz)
    consistent = np.array([float((G_new @ true)[0])])   # = predicción de `true`

    out = inv.live_update_add_data(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_g_observed=consistent,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    np.testing.assert_allclose(out["model"], true, atol=1e-4)
    assert out["update_norm"] < 1e-3


def test_live_update_respects_bounds():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    G_new = forward.build_sparse_kernel(x_c, y_c, z_c, new_xyz)
    pred0 = float((G_new @ true)[0])
    new_g = np.array([pred0 * 5.0])   # empuja fuerte hacia arriba

    out = inv.live_update_add_data(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_g_observed=new_g,
        lambda_mag=1e-3, alpha_spatial=1.0,
        density_min=0.0, density_max=1.0,
    )
    vals = out["model"][np.isfinite(out["model"])]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 1.0 + 1e-9


def test_live_update_deterministic():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    new_g = np.array([1.0e-6])
    kw = dict(
        new_sensor_coords=new_xyz, new_g_observed=new_g,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    a = inv.live_update_add_data(true, g_obs, y_c, forward, sensors, x_c, z_c, **kw)
    b = inv.live_update_add_data(true, g_obs, y_c, forward, sensors, x_c, z_c, **kw)
    np.testing.assert_array_equal(a["model"], b["model"])


def test_live_update_air_cells_preserved():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    topo = np.full(inv.total_voxels, BLOCK)   # primera capa = aire
    m0 = true.copy()
    voxel_top = y_c - BLOCK / 2.0
    air = voxel_top < topo
    m0[air] = np.nan
    new_xyz = _new_sensor()
    out = inv.live_update_add_data(
        m0, g_obs, y_c, forward, sensors, x_c, z_c,
        new_sensor_coords=new_xyz, new_g_observed=np.array([1e-6]),
        topography_elevations=topo, lambda_mag=1e-3, alpha_spatial=1.0,
    )
    assert np.isnan(out["model"][air]).all(), "celdas de aire deben seguir NaN"
    assert np.isfinite(out["model"][~air]).all()


def test_live_update_rejects_wrong_sizes():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    new_xyz = _new_sensor()
    with np.testing.assert_raises(ValueError):
        inv.live_update_add_data(
            true[:-1], g_obs, y_c, forward, sensors, x_c, z_c,
            new_sensor_coords=new_xyz, new_g_observed=np.array([1.0]),
        )
    with np.testing.assert_raises(ValueError):
        inv.live_update_add_data(
            true, g_obs, y_c, forward, sensors, x_c, z_c,
            new_sensor_coords=new_xyz, new_g_observed=np.array([1.0, 2.0]),  # k≠sensores
        )
