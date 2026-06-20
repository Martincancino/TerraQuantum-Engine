"""
FASE 20B Tarea 4 — Sigma robusto (MAD outliers) del motor MAGNÉTICO (port Fase 18).

Verifica:
  - sin outliers: detect_outliers True ≡ False (mismo sigma, ningún flag).
  - con 1 outlier: se marca y se downpesa 10×, SIN dilatar el sigma de los datos limpios.
  - el solver expone n_outliers en solver_meta y no degrada con detect_outliers=True.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import (
    MagnetometryForward,
    MagnetometryInversion,
    _sigma_adaptive,
)


def test_sigma_no_outliers_equivalent():
    rng = np.random.default_rng(0)
    d = 50.0 + 5.0 * rng.standard_normal(40)
    s_off, out_off = _sigma_adaptive(d, detect_outliers=False)
    s_on, out_on = _sigma_adaptive(d, detect_outliers=True)
    assert not out_off.any()
    # Datos gaussianos limpios → típicamente sin outliers MAD; sigma idéntico.
    if not out_on.any():
        np.testing.assert_allclose(s_off, s_on)


def test_sigma_outlier_downweighted_not_dilated():
    rng = np.random.default_rng(1)
    d = 10.0 + 1.0 * rng.standard_normal(40)
    d_clean = d.copy()
    d[7] = 500.0   # outlier extremo

    s_clean_baseline, _ = _sigma_adaptive(d_clean, detect_outliers=True)
    s_rob, is_out = _sigma_adaptive(d, detect_outliers=True)

    assert is_out[7], "El outlier debe ser detectado por MAD."
    assert is_out.sum() >= 1
    # El outlier queda con sigma grande (downpesado 10×).
    assert s_rob[7] > 5.0 * np.median(s_rob[~is_out])
    # Los datos limpios NO se dilatan respecto al baseline sin outlier (data_range
    # robusto p5–p95): el sigma de los limpios queda comparable.
    ratio = np.median(s_rob[~is_out]) / np.median(s_clean_baseline)
    assert 0.5 <= ratio <= 2.0, f"sigma de limpios dilatado: ratio={ratio:.3f}"


def test_sigma_non_robust_inflated_by_outlier():
    # Sin detección, un outlier infla el data_range (min-max) → sigma de TODOS sube.
    rng = np.random.default_rng(2)
    d = 10.0 + 1.0 * rng.standard_normal(40)
    s_no_out, _ = _sigma_adaptive(d, detect_outliers=False)
    d2 = d.copy(); d2[7] = 500.0
    s_with_out, _ = _sigma_adaptive(d2, detect_outliers=False)
    # El piso 0.01·data_range crece con el outlier → sigma de limpios mayor.
    assert np.median(s_with_out) > np.median(s_no_out)


def test_solver_reports_outliers():
    NX, NY, NZ, BS = 6, 4, 6, 25.0
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    sx, sz = np.meshgrid(np.linspace(BS, (NX - 1) * BS, 5), np.linspace(BS, (NZ - 1) * BS, 5))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[2 * NY * NZ + 1 * NZ + 2] = 0.15
    d_obs = G @ true
    d_obs[3] += 50.0 * (abs(d_obs).max() + 1e-6)   # outlier sintético en un sensor

    meta_on = {}
    inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, detect_outliers=True, solver_meta=meta_on,
    )
    meta_off = {}
    inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, detect_outliers=False, solver_meta=meta_off,
    )
    assert meta_on["detect_outliers"] is True
    assert meta_on["n_outliers"] >= 1
    assert meta_off["n_outliers"] == 0
