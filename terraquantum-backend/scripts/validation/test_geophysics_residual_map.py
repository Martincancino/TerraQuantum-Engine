"""
test_geophysics_residual_map.py
Fase 4.4 - Residual Map / Mapa de residuales por sensor.

Prueba build_fit_diagnostics con sensor_coords.
No ejecuta inversión completa.
"""
import sys
import numpy as np
import scipy.sparse as sp
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from services.geophysics_service import build_fit_diagnostics

BASE_DENSITY = 2.6


def make_kernel(n_sensors: int, n_voxels: int, seed: int = 7) -> sp.csr_matrix:
    """Kernel sintético disperso determinista."""
    rng = np.random.default_rng(seed)
    data = rng.standard_normal((n_sensors, n_voxels)) * 1e-9
    mask = rng.random((n_sensors, n_voxels)) > 0.7  # ~30 % no cero
    data[mask] = 0.0
    return sp.csr_matrix(data)


def make_coords(n: int) -> np.ndarray:
    """Grilla de sensores determinista (n × 3)."""
    xs = np.linspace(0, 500, n)
    return np.column_stack([xs, np.zeros(n), np.zeros(n)])


def run_tests():
    all_passed = True
    print("Running Residual Map Tests...\n")

    n_voxels = 200
    true_contrast = np.zeros(n_voxels)
    true_contrast[30:60] = 0.6  # anomalía determinista

    # ─────────────────────────────────────────────────────────────────────────
    # 1. residualMap existe al pasar sensor_coords
    # ─────────────────────────────────────────────────────────────────────────
    n_s = 30
    K = make_kernel(n_s, n_voxels)
    coords = make_coords(n_s)
    g_obs = np.asarray(K @ true_contrast, dtype=np.float64)
    est_density = BASE_DENSITY + true_contrast * 0.8  # modelo aproximado

    r1 = build_fit_diagnostics(g_obs, K, est_density, base_density=BASE_DENSITY, sensor_coords=coords)

    ok1 = (
        r1.get("residualMap") is not None
        and isinstance(r1["residualMap"], list)
        and len(r1["residualMap"]) == n_s
    )
    if ok1:
        print(f"PASS: 1. residualMap existe  (n={len(r1['residualMap'])})")
    else:
        print(f"FAIL: 1. residualMap={r1.get('residualMap')}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Cada punto tiene x_m, y_m, z_m
    # ─────────────────────────────────────────────────────────────────────────
    required_spatial = {"sensor_index", "x_m", "y_m", "z_m", "observed", "modeled",
                        "residual", "abs_residual", "normalized_residual", "residual_level"}
    ok2 = all(required_spatial.issubset(p.keys()) for p in r1["residualMap"])
    if ok2:
        print("PASS: 2. Claves espaciales presentes en cada punto")
    else:
        missing = [k for p in r1["residualMap"] for k in required_spatial if k not in p]
        print(f"FAIL: 2. Claves faltantes: {set(missing)}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 3. residual_level ∈ {LOW, MEDIUM, HIGH} y valores finitos
    # ─────────────────────────────────────────────────────────────────────────
    valid_levels = {"LOW", "MEDIUM", "HIGH"}
    ok3_levels = all(p["residual_level"] in valid_levels for p in r1["residualMap"])
    ok3_finite = all(
        np.isfinite(p["normalized_residual"])
        and np.isfinite(p["abs_residual"])
        for p in r1["residualMap"]
    )
    # Crear un caso con residuales claramente distribuidos para forzar las tres clases
    # Kernel identidad → residual = g_obs - K @ contraste_errado, con contraste muy distinto
    n_s3 = 12
    I_K = sp.eye(n_s3, n_voxels, format="csr") * 1e-9  # kernel mínimo
    g3 = np.linspace(1e-9, 10e-9, n_s3)
    # Modelo que sobreestima mucho en algunos sensores, sub en otros
    est3 = BASE_DENSITY + np.concatenate([
        np.zeros(n_voxels // 2),
        np.full(n_voxels // 2, 2.0)
    ])
    coords3 = make_coords(n_s3)
    r3 = build_fit_diagnostics(g3, I_K, est3, base_density=BASE_DENSITY, sensor_coords=coords3)
    all_levels = {p["residual_level"] for p in r3["residualMap"]}
    ok3 = ok3_levels and ok3_finite

    if ok3:
        print(f"PASS: 3. residual_level válido; niveles observados: {all_levels}")
    else:
        print(f"FAIL: 3. levels_ok={ok3_levels}, finite_ok={ok3_finite}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Límite de 500 puntos con >500 sensores
    # ─────────────────────────────────────────────────────────────────────────
    n_big = 800
    K_big = make_kernel(n_big, n_voxels, seed=13)
    coords_big = make_coords(n_big)
    g_big = np.asarray(K_big @ true_contrast, dtype=np.float64)
    est_big = BASE_DENSITY + true_contrast

    r4 = build_fit_diagnostics(g_big, K_big, est_big, base_density=BASE_DENSITY, sensor_coords=coords_big)

    ok4 = (
        r4["residualMap"] is not None
        and len(r4["residualMap"]) <= 500
        and len(r4["residualSamples"]) <= 50
    )
    if ok4:
        print(f"PASS: 4. Límite 500 puntos  (residualMap={len(r4['residualMap'])}, samples={len(r4['residualSamples'])})")
    else:
        print(f"FAIL: 4. residualMap={len(r4.get('residualMap', []))}")
        all_passed = False

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Compatibilidad: sin sensor_coords → no falla, residualMap es None,
    #    residualSamples sigue existiendo
    # ─────────────────────────────────────────────────────────────────────────
    K5 = make_kernel(20, n_voxels, seed=3)
    g5 = np.asarray(K5 @ true_contrast, dtype=np.float64)
    est5 = BASE_DENSITY + true_contrast

    try:
        r5 = build_fit_diagnostics(g5, K5, est5, base_density=BASE_DENSITY)
        ok5 = (
            r5["residualMap"] is None
            and isinstance(r5["residualSamples"], list)
            and len(r5["residualSamples"]) <= 50
        )
        if ok5:
            print("PASS: 5. Compatibilidad sin sensor_coords")
        else:
            print(f"FAIL: 5. residualMap={r5['residualMap']}, samples={len(r5['residualSamples'])}")
            all_passed = False
    except Exception as exc:
        print(f"FAIL: 5. Excepción inesperada: {exc}")
        all_passed = False

    print("\nRESULT:")
    if all_passed:
        print("PASS")
    else:
        print("FAIL")


if __name__ == "__main__":
    run_tests()
