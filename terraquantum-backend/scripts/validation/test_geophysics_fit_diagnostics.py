"""
test_geophysics_fit_diagnostics.py
Fase 4.3 - Observed vs Modeled diagnostics.

Prueba build_fit_diagnostics directamente con kernels sintéticos simples.
No ejecuta la inversión completa (no usa GravimetryInversion ni GravimetryForward).
"""
import sys
import numpy as np
import scipy.sparse as sp
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from services.geophysics_service import build_fit_diagnostics

BASE_DENSITY = 2.6


def make_simple_kernel(n_sensors: int, n_voxels: int, seed: int = 42) -> sp.csr_matrix:
    """Kernel sintético disperso determinista."""
    rng = np.random.default_rng(seed)
    density = 0.3
    mask = rng.random((n_sensors, n_voxels)) < density
    data = rng.standard_normal((n_sensors, n_voxels)) * 1e-9
    data[~mask] = 0.0
    return sp.csr_matrix(data)


def run_tests():
    all_passed = True
    print("Running Fit Diagnostics Tests...\n")

    n_sensors = 20
    n_voxels = 200
    K = make_simple_kernel(n_sensors, n_voxels)

    # Contraste verdadero para construir observaciones sintéticas
    true_contrast = np.zeros(n_voxels)
    true_contrast[50:70] = 0.5  # anomalía sintética

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Ajuste perfecto: est_density reproduce exactamente el contraste
    # ─────────────────────────────────────────────────────────────────────────
    g_obs_perfect = np.array(K @ true_contrast, dtype=np.float64)
    est_density_perfect = BASE_DENSITY + true_contrast  # densidad absoluta

    r1 = build_fit_diagnostics(g_obs_perfect, K, est_density_perfect, base_density=BASE_DENSITY)

    ok1 = (
        r1["residual_rmse"] < 1e-10
        and r1["fit_level"] == "GOOD"
        and isinstance(r1["residualSamples"], list)
        and len(r1["residualSamples"]) <= 50
    )
    if ok1:
        print(f"PASS: 1. Ajuste perfecto  (rmse={r1['residual_rmse']:.2e}, fit={r1['fit_level']})")
    else:
        print(f"FAIL: 1. Ajuste perfecto  rmse={r1['residual_rmse']:.2e}, fit={r1['fit_level']}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Ajuste moderado: modelo suavizado (contraste parcial)
    # ─────────────────────────────────────────────────────────────────────────
    partial_contrast = true_contrast * 0.7
    est_density_partial = BASE_DENSITY + partial_contrast
    g_obs_partial = np.array(K @ true_contrast, dtype=np.float64)

    r2 = build_fit_diagnostics(g_obs_partial, K, est_density_partial, base_density=BASE_DENSITY)

    ok2 = (
        np.isfinite(r2["residual_rmse"])
        and r2["fit_level"] in ("GOOD", "MEDIUM")
        and len(r2["residualSamples"]) <= 50
        and all(
            {"sensor_index", "observed", "modeled", "residual"}.issubset(s.keys())
            for s in r2["residualSamples"]
        )
    )
    if ok2:
        print(f"PASS: 2. Ajuste moderado  (rmse={r2['residual_rmse']:.2e}, fit={r2['fit_level']})")
    else:
        print(f"FAIL: 2. Ajuste moderado  rmse={r2['residual_rmse']:.2e}, fit={r2['fit_level']}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Ajuste malo: modelo muy alejado (contraste incorrecto)
    # ─────────────────────────────────────────────────────────────────────────
    wrong_contrast = np.zeros(n_voxels)
    wrong_contrast[100:120] = 2.0  # zona y magnitud muy distinta
    est_density_wrong = BASE_DENSITY + wrong_contrast
    g_obs_wrong = np.array(K @ true_contrast, dtype=np.float64)

    r3 = build_fit_diagnostics(g_obs_wrong, K, est_density_wrong, base_density=BASE_DENSITY)

    ok3 = (
        np.isfinite(r3["residual_rmse"])
        and np.isfinite(r3["normalized_rmse"])
        and r3["residual_rmse"] >= 0.0
    )
    if ok3:
        print(f"PASS: 3. Ajuste malo      (rmse={r3['residual_rmse']:.2e}, fit={r3['fit_level']}, nrmse={r3['normalized_rmse']:.4f})")
    else:
        print(f"FAIL: 3. Ajuste malo - valores no finitos o negativos")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 4. residualSamples: estructura, límite de 50, keys correctas
    # ─────────────────────────────────────────────────────────────────────────
    # Kernel grande para forzar el límite de 50 muestras
    K_big = make_simple_kernel(120, n_voxels, seed=99)
    g_obs_big = np.array(K_big @ true_contrast, dtype=np.float64)
    est_density_big = BASE_DENSITY + true_contrast

    r4 = build_fit_diagnostics(g_obs_big, K_big, est_density_big, base_density=BASE_DENSITY)

    required_keys = {"sensor_index", "observed", "modeled", "residual"}
    ok4 = (
        isinstance(r4["residualSamples"], list)
        and len(r4["residualSamples"]) <= 50
        and len(r4["residualSamples"]) > 0
        and all(required_keys.issubset(s.keys()) for s in r4["residualSamples"])
    )
    if ok4:
        print(f"PASS: 4. residualSamples  (n={len(r4['residualSamples'])}, keys OK)")
    else:
        print(f"FAIL: 4. residualSamples  n={len(r4['residualSamples'])}")
        all_passed = False

    print("\nRESULT:")
    if all_passed:
        print("PASS")
    else:
        print("FAIL")


if __name__ == "__main__":
    run_tests()
