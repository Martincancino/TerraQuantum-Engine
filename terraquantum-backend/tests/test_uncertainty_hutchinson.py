"""
Track 3 / T3.1 — Incertidumbre posterior por vóxel (estimador de Hutchinson).

Dos niveles de validación:
 1. El kernel numérico hutchinson_diag_inv contra diag(A^{-1}) exacto (denso).
 2. El método estimate_posterior_std: forma, finitud, signo y la propiedad física
    de que la σ posterior CRECE con la profundidad (la gravimetría pierde
    resolución en profundidad → mayor varianza).
"""
import numpy as np
import pytest
import scipy.sparse as sp

from exploration.gravimetry import (
    GravimetryForward,
    GravimetryInversion,
    hutchinson_diag_inv,
)


def test_hutchinson_diag_inv_matches_exact_dense():
    """Insesgado: con suficientes sondas, diag(A^{-1}) ≈ exacto."""
    rng = np.random.default_rng(0)
    n = 40
    B = rng.standard_normal((n, n))
    A_dense = B @ B.T + np.eye(n) * 2.0     # SPD, bien condicionada
    A = sp.csr_matrix(A_dense)

    exact = np.diag(np.linalg.inv(A_dense))
    est = hutchinson_diag_inv(A, n_probes=4000, cg_rtol=1e-9, seed=1)

    # Estocástico pero sembrado → determinista. Debe correlacionar fuerte y
    # tener error relativo mediano bajo.
    corr = np.corrcoef(exact, est)[0, 1]
    rel_err = np.abs(est - exact) / np.abs(exact)
    assert corr > 0.95, f"correlación demasiado baja: {corr}"
    assert np.median(rel_err) < 0.15, f"error relativo mediano alto: {np.median(rel_err)}"
    assert np.all(est >= 0.0)


def test_hutchinson_rejects_non_square():
    with np.testing.assert_raises(ValueError):
        hutchinson_diag_inv(sp.csr_matrix(np.ones((3, 4))))


def _synthetic_setup():
    """Survey razonablemente cubierto (malla densa de sensores en superficie),
    para que la covarianza posterior lineal esté bien condicionada y sea estable.
    Un caso con muy pocos sensores deja el problema casi singular y la σ posterior
    se dispara (correcto, pero inadecuado para validar la implementación)."""
    NX, NY, NZ, BLOCK = 8, 4, 8, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = gx.flatten(order="F").astype(np.int32)
    iy = gy.flatten(order="F").astype(np.int32)
    iz = gz.flatten(order="F").astype(np.int32)
    x_c = ix * BLOCK + BLOCK / 2
    y_c = iy * BLOCK + BLOCK / 2
    z_c = iz * BLOCK + BLOCK / 2
    # Malla densa de sensores en superficie (y=0): un sensor sobre cada columna (x,z).
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
    return inv, forward, sensors, x_c, y_c, z_c, g_obs


def test_estimate_posterior_std_shape_sign_and_air_mask():
    inv, forward, sensors, x_c, y_c, z_c, g_obs = _synthetic_setup()
    std_full = inv.estimate_posterior_std(
        g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_probes=64, seed=0,
    )
    assert std_full.shape[0] == inv.total_voxels
    finite = np.isfinite(std_full)
    # Sin topografía todas las celdas están activas → todas finitas y positivas.
    assert finite.all()
    assert np.median(std_full[finite]) > 0.0
    assert np.all(std_full[finite] >= 0.0)


def test_posterior_std_increases_with_depth():
    """Propiedad física: la incertidumbre posterior crece con la profundidad
    (la gravimetría pierde resolución en profundidad). Se comparan los promedios
    de la mitad somera vs. la mitad profunda del modelo."""
    inv, forward, sensors, x_c, y_c, z_c, g_obs = _synthetic_setup()
    std_full = inv.estimate_posterior_std(
        g_obs, y_c, forward, sensors, x_c, z_c,
        lambda_mag=1e-2, alpha_spatial=1.5, n_probes=80, seed=0,
    )
    depth_median = np.median(y_c)
    shallow = std_full[y_c <= depth_median]
    deep = std_full[y_c > depth_median]
    assert np.nanmean(deep) > np.nanmean(shallow), (
        f"σ profunda ({np.nanmean(deep):.3g}) debe superar la somera "
        f"({np.nanmean(shallow):.3g})"
    )


def test_posterior_std_is_deterministic_with_seed():
    inv, forward, sensors, x_c, y_c, z_c, g_obs = _synthetic_setup()
    a = inv.estimate_posterior_std(g_obs, y_c, forward, sensors, x_c, z_c,
                                   lambda_mag=5e-5, alpha_spatial=1.5, n_probes=12, seed=7)
    b = inv.estimate_posterior_std(g_obs, y_c, forward, sensors, x_c, z_c,
                                   lambda_mag=5e-5, alpha_spatial=1.5, n_probes=12, seed=7)
    np.testing.assert_array_equal(a, b)


def _obs10():
    return [
        {"x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000080},
        {"x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000090},
        {"x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000110},
        {"x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000150},
        {"x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000110},
        {"x_m": 5, "y_m": 0, "z_m": 25, "g": 0.00000085},
        {"x_m": 15, "y_m": 0, "z_m": 25, "g": 0.00000095},
        {"x_m": 25, "y_m": 0, "z_m": 25, "g": 0.00000130},
        {"x_m": 35, "y_m": 0, "z_m": 25, "g": 0.00000100},
        {"x_m": 45, "y_m": 0, "z_m": 25, "g": 0.00000090},
    ]


@pytest.mark.integration
def test_run_inversion_with_uncertainty_populates_report(test_project_id, test_run_id):
    """End-to-end: compute_uncertainty=True llena report['uncertaintyPosterior']."""
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id, run_id=test_run_id,
        depth=30, nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=6, ny=6, nz=6, block_size=10, cutoff_radius=400,
        lambda_mag=0.01, alpha_spatial=1.5,
        observations=_obs10(), compute_uncertainty=True,
    )
    result = run_geophysics_inversion(params)
    assert "error" not in result, result.get("error")
    up = result["report"].get("uncertaintyPosterior")
    assert up is not None
    assert up.get("computed") is True
    assert up.get("is_statistical_posterior") is True
    assert up.get("p95") is not None and up["p95"] >= 0.0
    # T2: 'status' machine-readable + 'reason' ES (por qué está o no la σ).
    assert up.get("status") in ("computed", "ill_conditioned")
    assert isinstance(up.get("reason"), str) and up["reason"]


@pytest.mark.integration
def test_run_inversion_without_uncertainty_is_off_by_default(test_project_id, test_run_id):
    """Por defecto (sin flag) la UQ posterior NO se calcula → computed=False."""
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    params = GeophysicsInvertInput(
        project_id=test_project_id, run_id=test_run_id,
        depth=30, nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=6, ny=6, nz=6, block_size=10, cutoff_radius=400,
        lambda_mag=0.01, alpha_spatial=1.5,
        observations=_obs10(),
    )
    result = run_geophysics_inversion(params)
    assert "error" not in result, result.get("error")
    up = result["report"].get("uncertaintyPosterior")
    assert up is not None and up.get("computed") is False
    # T2: default apagado explícito y con razón (para el EmptyState del frontend).
    assert up.get("status") == "disabled_by_default"
    assert isinstance(up.get("reason"), str) and up["reason"]
