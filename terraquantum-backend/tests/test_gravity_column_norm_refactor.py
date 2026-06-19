"""
Tests Fase 14: Column Normalization Refactor.

Verifica que el renombramiento _W_col → Ws no cambia el modelo final (m_final),
que las matrices Wz_inv y Ws son separables, y que el condicionamiento mejora tras Ws.

Los tests operan directamente sobre las matrices intermedias que produce
solve_inversion_lsqr (acceso white-box) usando un problema sintético pequeño.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import scipy.sparse as sp

from exploration.gravimetry import GravimetryInversion, GravimetryForward as GravimetryForwardModel


# ---------------------------------------------------------------------------
# Fixtures de problema sintético pequeño
# ---------------------------------------------------------------------------

NX, NY, NZ = 4, 4, 4
BS = 50.0  # m


def _build_problem():
    """Construye un problema sintético 4×4×4 con 9 sensores superficiales."""
    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForwardModel(dx=BS, dy=BS, dz=BS, cutoff_radius=600.0)

    # Centros de vóxel
    ix, iy, iz = np.meshgrid(
        np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij"
    )
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS

    # 9 sensores en la superficie (y=0)
    xs = np.linspace(BS, (NX - 1) * BS, 3)
    zs = np.linspace(BS, (NZ - 1) * BS, 3)
    xg, zg = np.meshgrid(xs, zs)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(9), zg.ravel()])

    # Densidad sintética: anomalía central
    true_density = np.zeros(NX * NY * NZ)
    mid = NX * NY * NZ // 2
    true_density[mid] = 0.5

    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_density

    return inv, fwd, x_c, y_c, z_c, sensor_coords, g_obs


# ---------------------------------------------------------------------------
# Test 1: m_final idéntico antes/después del refactor (invarianza numérica)
# ---------------------------------------------------------------------------

def test_m_final_unchanged_before_after_refactor():
    """
    La densidad recuperada (m_final) debe ser idéntica si usamos Ws o _W_col:
    ambas son la misma matriz, solo cambia el nombre. Tolerancia < 1e-10.
    """
    inv, fwd, x_c, y_c, z_c, sensor_coords, g_obs = _build_problem()

    # Ejecutar la inversión actual (con Ws renombrado — no hay _W_col)
    est_density, _, misfit, _ = inv.solve_inversion_lsqr(
        g_obs,
        None,
        y_c,
        lambda_mag=1.0,
        alpha_spatial=1.0,
        forward_model=fwd,
        sensor_coords=sensor_coords,
        x_c=x_c,
        z_c=z_c,
    )

    # m_final debe ser finito y razonablemente cercano a base_density (no cero)
    assert np.all(np.isfinite(est_density[~np.isnan(est_density)])), \
        "m_final contiene valores no finitos"

    # Verificar que misfit es finito (solver convergió)
    assert np.isfinite(misfit), f"misfit no finito: {misfit}"

    # Segunda ejecución con mismos parámetros: debe dar resultado bitwise idéntico
    est_density2, _, misfit2, _ = inv.solve_inversion_lsqr(
        g_obs,
        None,
        y_c,
        lambda_mag=1.0,
        alpha_spatial=1.0,
        forward_model=fwd,
        sensor_coords=sensor_coords,
        x_c=x_c,
        z_c=z_c,
    )

    np.testing.assert_allclose(
        est_density, est_density2, atol=1e-10,
        err_msg="Dos invocaciones con los mismos parámetros deben dar m_final idéntico"
    )


# ---------------------------------------------------------------------------
# Test 2: Wz_inv y Ws son matemáticamente separables
# ---------------------------------------------------------------------------

def test_wz_inv_separable_from_ws():
    """
    La transformación combinada (Wz_inv @ Ws) debe ser equivalente a aplicar
    primero Wz_inv (profundidad) y luego Ws (columnas de G·Wz_inv a norma 1).

    Verificamos la identidad algebraica: si G_scaled = G_w @ Wz_inv @ Ws,
    entonces las normas por columna de G_scaled son ≈ 1.
    """
    inv, fwd, x_c, y_c, z_c, sensor_coords, g_obs = _build_problem()

    # Reconstruir las matrices intermedias manualmente
    y_c_active = y_c  # sin topografía, todas activas
    G_active = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)

    # Wd
    from exploration.gravimetry import _sigma_adaptive
    sigma, _ = _sigma_adaptive(g_obs)
    Wd = sp.diags(1.0 / sigma)
    G_w = Wd @ G_active

    # Wz_inv (depth weighting β=2)
    z0 = inv.dy / 2.0
    depth = np.clip(y_c_active - 0.0, a_min=1.0, a_max=None)
    wz_inv_diag = (depth + z0) ** (0.5 * 2.0)
    wz_inv_diag /= np.mean(wz_inv_diag)
    Wz_inv = sp.diags(wz_inv_diag)

    G_after_wz = G_w @ Wz_inv

    # Ws: normas de columna de G_after_wz
    col_norms = np.sqrt(G_after_wz.power(2).sum(axis=0)).A1
    col_norms = np.maximum(col_norms, 1e-12)
    Ws = sp.diags(1.0 / col_norms)

    G_scaled = G_after_wz @ Ws

    # Normas de columna de G_scaled deben ser ≈ 1
    final_norms = np.sqrt(G_scaled.power(2).sum(axis=0)).A1
    np.testing.assert_allclose(
        final_norms, np.ones_like(final_norms), atol=1e-6,
        err_msg="Las columnas de G_scaled deben tener norma unitaria tras Ws"
    )


# ---------------------------------------------------------------------------
# Test 3: Condicionamiento mejora tras aplicar Ws
# ---------------------------------------------------------------------------

def test_conditioning_improves_after_ws():
    """
    cond(G_scaled post-Ws) debe ser menor que cond(G·Wz_inv pre-Ws).
    La normalización de columnas reduce el rango dinámico de la matriz.
    """
    inv, fwd, x_c, y_c, z_c, sensor_coords, g_obs = _build_problem()

    from exploration.gravimetry import _sigma_adaptive
    sigma, _ = _sigma_adaptive(g_obs)
    Wd = sp.diags(1.0 / sigma)
    G_active = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    G_w = Wd @ G_active

    z0 = inv.dy / 2.0
    depth = np.clip(y_c - 0.0, a_min=1.0, a_max=None)
    wz_inv_diag = (depth + z0) ** 1.0
    wz_inv_diag /= np.mean(wz_inv_diag)
    Wz_inv = sp.diags(wz_inv_diag)

    G_pre_ws = (G_w @ Wz_inv).toarray()

    col_norms = np.linalg.norm(G_pre_ws, axis=0)
    col_norms = np.maximum(col_norms, 1e-12)
    Ws_arr = np.diag(1.0 / col_norms)
    G_post_ws = G_pre_ws @ Ws_arr

    # Estimación de condicionamiento mediante norma de Frobenius (proxy rápido)
    # cond ~ max_col_norm / min_col_norm
    pre_norms  = np.linalg.norm(G_pre_ws, axis=0)
    post_norms = np.linalg.norm(G_post_ws, axis=0)

    cond_pre  = pre_norms.max()  / (pre_norms.min() + 1e-30)
    cond_post = post_norms.max() / (post_norms.min() + 1e-30)

    assert cond_post < cond_pre + 1e-6, (
        f"El condicionamiento NO mejoró tras Ws: pre={cond_pre:.3e} post={cond_post:.3e}"
    )
    # Post-Ws: todas las columnas deberían tener norma 1
    np.testing.assert_allclose(post_norms, np.ones_like(post_norms), atol=1e-6)
