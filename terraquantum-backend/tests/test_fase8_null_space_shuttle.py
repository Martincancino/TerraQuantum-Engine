"""
FASE 8.1 (peldaño 1 de la escalera de UQ) — "null-space shuttle".

Valida en dos niveles:
 1. El kernel null_space_shuttle_directions: que las direcciones δ devueltas viven
    (aprox.) en el espacio nulo de datos (G·δ ≈ 0) → cada alternativa preserva el
    ajuste del dato. Con un G de rango deficiente, EXISTE espacio nulo no trivial y
    el shuttle lo encuentra (‖Gδ‖/‖Gs‖ pequeño). Con un G de rango completo bien
    condicionado NO hay espacio nulo → δ → 0.
 2. El método null_space_shuttle_ensemble: forma, máscara de aire, determinismo por
    semilla, respeto de bounds y la propiedad física de que el abanico de modelos se
    abre con la profundidad (donde la gravimetría pierde resolución, la no-unicidad
    crece).
"""
import numpy as np
import pytest
import scipy.sparse as sp

from exploration.gravimetry import (
    GravimetryForward,
    GravimetryInversion,
    null_space_shuttle_directions,
)


# ───────────────────────── Nivel 1: el kernel ──────────────────────────────


def test_directions_live_in_data_null_space_when_rank_deficient():
    """G con menos filas que columnas ⇒ null(G) no trivial. El shuttle debe
    devolver direcciones con G·δ ≈ 0 (preserved ≪ 1)."""
    rng = np.random.default_rng(0)
    n_data, n = 6, 30          # rango ≤ 6 ⇒ espacio nulo de dim ≥ 24
    G = sp.csr_matrix(rng.standard_normal((n_data, n)))

    directions, preserved, null_fraction = null_space_shuttle_directions(
        G, n_shuttles=8, mu=1e-4, cg_rtol=1e-10, cg_maxiter=2000, seed=1
    )
    assert directions.shape == (8, n)
    # Norma unitaria por construcción.
    np.testing.assert_allclose(np.linalg.norm(directions, axis=1), 1.0, atol=1e-8)
    # Direcciones casi en el núcleo: ‖Gδ‖ ≪ ‖Gs‖.
    assert np.max(preserved) < 0.05, f"preserved demasiado alto: {preserved}"
    # Existe núcleo amplio: gran parte de s sobrevive a la proyección.
    assert np.min(null_fraction) > 0.5, f"null_fraction baja: {null_fraction}"
    # Verificación directa: G·δ ≈ 0.
    residual = np.linalg.norm(G @ directions.T, axis=0)
    assert np.max(residual) < 0.05


def test_full_rank_well_conditioned_has_no_null_space():
    """G cuadrada SPD-ish bien condicionada ⇒ sin espacio nulo ⇒ δ → 0
    (toda dirección la 've' el dato, no hay shuttle posible)."""
    rng = np.random.default_rng(2)
    n = 25
    B = rng.standard_normal((n, n))
    G = sp.csr_matrix(B @ B.T + np.eye(n) * 3.0)   # bien condicionada, rango completo

    directions, preserved, null_fraction = null_space_shuttle_directions(
        G, n_shuttles=6, mu=1e-6, cg_rtol=1e-10, cg_maxiter=2000, seed=3
    )
    # Sin núcleo: la proyección aniquila s ⇒ ‖δ_cruda‖/‖s‖ ≈ 0. No hay shuttle real
    # (toda dirección la 've' el dato). preserved es ≈0 en AMBOS casos y no sirve
    # para distinguir; null_fraction sí.
    assert np.max(null_fraction) < 1e-3, f"esperaba sin núcleo, null_fraction={null_fraction}"


def test_directions_rejects_nonpositive_mu():
    rng = np.random.default_rng(0)
    G = sp.csr_matrix(rng.standard_normal((4, 10)))
    with np.testing.assert_raises(ValueError):
        null_space_shuttle_directions(G, mu=0.0)


def test_directions_deterministic_with_seed():
    rng = np.random.default_rng(0)
    G = sp.csr_matrix(rng.standard_normal((5, 20)))
    a, pa, na = null_space_shuttle_directions(G, n_shuttles=4, seed=7)
    b, pb, nb = null_space_shuttle_directions(G, n_shuttles=4, seed=7)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(pa, pb)
    np.testing.assert_array_equal(na, nb)


# ───────────────────── Nivel 2: el método de motor ─────────────────────────


def _synthetic_setup():
    """Survey denso en superficie + un cuerpo esférico (reusa el patrón del test
    de Hutchinson para que la covarianza/null-space estén bien definidos)."""
    NX, NY, NZ, BLOCK = 8, 4, 8, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = gx.flatten(order="F").astype(np.int32)
    iy = gy.flatten(order="F").astype(np.int32)
    iz = gz.flatten(order="F").astype(np.int32)
    x_c = ix * BLOCK + BLOCK / 2
    y_c = iy * BLOCK + BLOCK / 2
    z_c = iz * BLOCK + BLOCK / 2
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


def test_ensemble_shape_air_mask_and_data_fit():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_shuttles=10, seed=0,
    )
    assert out["ensemble"].shape == (10, inv.total_voxels)
    assert out["ensemble_std"].shape[0] == inv.total_voxels
    # Sin topografía todas las celdas están activas → todo finito.
    assert np.isfinite(out["ensemble_std"]).all()
    assert np.isfinite(out["ensemble"]).all()
    assert np.all(out["ensemble_std"] >= 0.0)
    # El abanico tiene spread (no degenerado a un solo modelo).
    assert np.median(out["ensemble_std"]) > 0.0
    # Honestidad: las alternativas preservan razonablemente el dato.
    assert out["data_fit_preserved"] < 0.25, out["data_fit_preserved"]


def test_ensemble_members_actually_fit_the_data():
    """Cada modelo alternativo debe reproducir el dato casi tan bien como la
    solución de referencia (esa es la promesa del null-space shuttle)."""
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_shuttles=8,
        shuttle_scale=0.5, smooth_strength=5.0, seed=0,
    )
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    d_ref = kernel @ true
    base_misfit = np.linalg.norm(d_ref - g_obs) / np.linalg.norm(g_obs)
    for k in range(out["n_shuttles"]):
        member = out["ensemble"][k]
        d_k = kernel @ np.nan_to_num(member)
        misfit = np.linalg.norm(d_k - g_obs) / np.linalg.norm(g_obs)
        # El dato apenas cambia: el shuttle viaja por el espacio nulo.
        assert misfit < base_misfit + 0.15, (
            f"shuttle {k} degrada el ajuste: {misfit:.3g} vs base {base_misfit:.3g}"
        )


def test_ensemble_respects_bounds():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_shuttles=8,
        shuttle_scale=2.0, density_min=0.0, density_max=1.0, seed=0,
    )
    finite = np.isfinite(out["ensemble"])
    vals = out["ensemble"][finite]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 1.0 + 1e-9


def test_ensemble_spread_grows_with_depth():
    """No-unicidad física: el abanico de modelos se ABRE en profundidad (la
    gravimetría no resuelve la densidad profunda → más alternativas posibles)."""
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_shuttles=24,
        shuttle_scale=0.5, smooth_strength=5.0, seed=0,
    )
    std = out["ensemble_std"]
    depth_median = np.median(y_c)
    shallow = std[y_c <= depth_median]
    deep = std[y_c > depth_median]
    assert np.nanmean(deep) > np.nanmean(shallow), (
        f"spread profundo ({np.nanmean(deep):.3g}) debe superar el somero "
        f"({np.nanmean(shallow):.3g})"
    )


def test_ensemble_deterministic_with_seed():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    a = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=5e-3, alpha_spatial=1.5, n_shuttles=6, seed=11,
    )
    b = inv.null_space_shuttle_ensemble(
        true, g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=5e-3, alpha_spatial=1.5, n_shuttles=6, seed=11,
    )
    np.testing.assert_array_equal(a["ensemble"], b["ensemble"])
    np.testing.assert_array_equal(a["ensemble_std"], b["ensemble_std"])


def test_rejects_wrong_m0_size():
    inv, forward, sensors, x_c, y_c, z_c, g_obs, true = _synthetic_setup()
    with np.testing.assert_raises(ValueError):
        inv.null_space_shuttle_ensemble(
            true[:-1], g_obs, y_c, forward, sensors, x_c, z_c,
        )
