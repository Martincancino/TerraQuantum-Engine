"""
TerraQuantum Synthetic Copper Demo v1 — Experimento de Weighting

Prueba diferentes estrategias de depth/sensitivity weighting
para corregir el sesgo somero de la inversión gravimétrica.

Casos:
A. baseline_unweighted
B. geometric_depth_weight_beta1
C. geometric_depth_weight_beta2
D. sensitivity_weighting

No modifica el solver productivo. Todo se ejecuta de manera local en el script.
"""

import math
import os
import sys
import time

import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

# ---------------------------------------------------------------------------
# Configuración del entorno
# ---------------------------------------------------------------------------
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from services.gravity_import_service import import_gravity_csv_v1
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.geophysics_service import estimate_grade_from_geophysics
from schemas.geophysics_schema import GravityObservation

from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    build_true_contrast_on_inversion_grid,
    centroid_weighted,
    CUTOFF_DENSITY,
    CUTOFF_VISUAL_SCORE,
    BASE_DENSITY,
    TOTAL_VOXELS,
    NX, NY, NZ,
    BLOCK_SIZE,
)

CSV_RELPATH = os.path.join("scripts", "demo_data", "tq_synthetic_copper_demo_v1_bouguer_mgal.csv")

# Ground Truth analítico calculado una vez
contrast_true, x_c, y_c, z_c, ix_arr, iy_arr, iz_arr = build_true_contrast_on_inversion_grid()
mask_true_active = contrast_true > 0
cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)


def solve_experimental(kernel_sparse, g_observed, x_c, y_c, z_c, mode: str):
    """
    Réplica aislada del solver productivo (LSQR + Laplaciano) modificada
    para soportar depth weighting experimental.
    
    Formulación con Weighting:
    Sea m = W_inv * m_tilde, donde W_inv es una matriz diagonal de pesos.
    Resolvemos m_tilde para minimizar:
    || G_norm * W_inv * m_tilde - d_norm ||^2 + lambda_s^2 || W_spatial_norm * W_inv * m_tilde ||^2
    Luego reconstruimos m = W_inv * m_tilde.
    
    Para geometric depth weighting, W_inv_diag[i] = y_c[i] ** (beta / 2).
    Esto amplifica la "influencia" de celdas profundas, logrando que el solver
    penalice menos el depositar masa en ellas.
    """
    t0 = time.perf_counter()
    n_sensors, n_voxels = kernel_sparse.shape

    scale_G = float(np.max(np.abs(kernel_sparse.data)))
    G_norm = kernel_sparse / scale_G
    g_obs_norm = g_observed / scale_G

    # 1. Definir la matriz de pesos (W_inv_diag)
    if mode == "baseline_unweighted":
        W_inv_diag = np.ones(n_voxels, dtype=np.float64)
    elif mode == "geometric_depth_weight_beta1":
        # w_inv = y^(1/2)
        W_inv_diag = np.power(y_c, 0.5)
    elif mode == "geometric_depth_weight_beta2":
        # w_inv = y^(1)
        W_inv_diag = y_c.copy()
    elif mode == "sensitivity_weighting":
        # w_inv = 1 / (norma_L2_columna + epsilon)
        G_csc = G_norm.tocsc()
        col_norms = np.array(np.sqrt(G_csc.power(2).sum(axis=0))).ravel()
        max_norm = np.max(col_norms) if np.max(col_norms) > 0 else 1.0
        s_norm = col_norms / max_norm
        epsilon = 1e-4
        W_inv_diag = 1.0 / (s_norm + epsilon)
    else:
        raise ValueError(f"Modo desconocido: {mode}")

    # Normalizar W_inv_diag para no alterar radicalmente el balance del lambda
    W_inv_diag /= np.mean(W_inv_diag)
    
    W_inv_mat = sp.diags(W_inv_diag, 0, format="csr")

    # 2. Transformar operadores
    G_tilde = G_norm.dot(W_inv_mat)

    dummy_inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    W_spatial = dummy_inv._build_spatial_regularizer()
    W_spatial_norm = W_spatial / 6.0
    W_spatial_tilde = W_spatial_norm.dot(W_inv_mat)

    # 3. Ensamblar sistema aumentado
    lambda_mag = 0.00005
    alpha_spatial = 1.0
    lambda_spatial = float(alpha_spatial) * (n_sensors / n_voxels)

    G_aug = sp.vstack([G_tilde, lambda_spatial * W_spatial_tilde], format="csr")
    d_aug = np.concatenate([g_obs_norm, np.zeros(n_voxels, dtype=np.float64)])

    # 4. Resolver
    result = lsqr(G_aug, d_aug, damp=lambda_mag, iter_lim=250, show=False)
    m_tilde = result[0]
    
    # 5. Mapear de vuelta a contraste físico
    m = m_tilde * W_inv_diag

    # 6. Calcular post-procesamiento idéntico al productivo
    g_model = kernel_sparse @ m
    residual_sensor = g_observed - g_model
    residual_l2 = float(np.linalg.norm(residual_sensor))
    
    voxel_error = np.abs(kernel_sparse.T @ residual_sensor)
    max_voxel_error = float(np.max(voxel_error)) if len(voxel_error) > 0 else 0.0
    probability = np.ones(n_voxels, dtype=np.float64)
    if max_voxel_error > 0:
        probability = np.clip(1.0 - (voxel_error / max_voxel_error), 0.0, 1.0)
        
    estimated_density = np.clip(BASE_DENSITY + m, 2.6, 4.2)
    density_score = np.clip((estimated_density - 2.6) / 1.6, 0.0, 1.0)
    visual_score = probability * density_score
    
    t_end = time.perf_counter()
    return estimated_density, visual_score, probability, residual_l2, t_end - t0


def run_experiment():
    print("=" * 110)
    print("TerraQuantum — Experimento de Weighting (Depth & Sensitivity)")
    print("=" * 110)

    csv_path = os.path.join(BACKEND_ROOT, CSV_RELPATH)
    if not os.path.exists(csv_path):
        print(f"❌  CSV no encontrado: {csv_path}")
        sys.exit(1)

    print(f"\n[1] Cargando observaciones desde: {csv_path}")
    import_result = import_gravity_csv_v1(csv_path, strict=True, allow_g_raw=False)
    if import_result.status != "ok":
        print(f"❌  Error importando CSV: {import_result.errors}")
        sys.exit(1)

    observations = [
        GravityObservation(x_m=obs.x_m, y_m=obs.y_m, z_m=obs.z_m, g=obs.g)
        for obs in import_result.observations
    ]
    sensor_coords = np.array([[obs.x_m, obs.y_m, obs.z_m] for obs in observations])
    g_obs = np.array([obs.g for obs in import_result.observations])
    print(f"    {len(observations)} observaciones cargadas.")

    print(f"\n[2] Construyendo kernel gravimétrico base (cutoff=600 m)...")
    t0_k = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Kernel completado en {time.perf_counter() - t0_k:.1f} s. NNZ={kernel.nnz:,}")

    MODES = [
        "baseline_unweighted",
        "geometric_depth_weight_beta1",
        "geometric_depth_weight_beta2",
        "sensitivity_weighting"
    ]

    results = []

    print("\n[3] Ejecutando solvers experimentales...")
    for mode in MODES:
        print(f"    -> {mode}")
        
        est_density, visual_score, probability, res_l2, t_inv = solve_experimental(
            kernel, g_obs, x_c, y_c, z_c, mode
        )

        grade = estimate_grade_from_geophysics(est_density, probability, 83, 79, "norte_chile")
        mask_rec_physical = (est_density >= CUTOFF_DENSITY) | (visual_score >= CUTOFF_VISUAL_SCORE)
        n_rec = int(np.sum(mask_rec_physical))
        
        ranking_score = np.where(
            mask_rec_physical,
            probability * np.maximum(est_density - 2.6, 0.0) * np.maximum(grade, 0.01),
            -1.0
        )
        best_idx = int(np.argmax(ranking_score))
        bt_y = float(y_c[best_idx]) if n_rec > 0 else float("nan")

        contrast_rec = est_density - BASE_DENSITY
        corr = float(np.corrcoef(contrast_true, contrast_rec)[0, 1]) if np.std(contrast_true) > 0 and np.std(contrast_rec) > 0 else 0.0
        
        mt = mask_true_active
        mr = mask_rec_physical
        intersection = int(np.sum(mt & mr))
        union_count  = int(np.sum(mt | mr))
        iou = intersection / max(union_count, 1)
        recall = intersection / max(int(np.sum(mt)), 1)
        precision = intersection / max(n_rec, 1)

        cr_pos = np.maximum(contrast_rec, 0.0)
        cw_rec = centroid_weighted(x_c, y_c, z_c, cr_pos)
        y_err = cw_rec[1] - cw_true[1] if math.isfinite(cw_rec[1]) and math.isfinite(cw_true[1]) else float("nan")

        shallow_mask = iy_arr <= 3
        shallow_mass = float(np.sum(cr_pos[shallow_mask]))
        total_mass = float(np.sum(cr_pos))
        shallow_mass_pct = 100.0 * shallow_mass / max(total_mass, 1e-15)

        results.append({
            "mode": mode,
            "time_s": t_inv,
            "max_dens": float(np.max(est_density)),
            "anom": n_rec,
            "corr": corr,
            "iou": iou,
            "recall": recall,
            "precision": precision,
            "cw_y": cw_rec[1],
            "y_err": y_err,
            "sh_mass_pct": shallow_mass_pct,
            "bt_y": bt_y,
            "res_l2": res_l2,
        })

    # ===================================================================
    # TABLA COMPARATIVA
    # ===================================================================
    print("\n" + "=" * 140)
    print(f"{'Mode':<30} | {'Time(s)':>7} | {'MaxDen':>6} | {'Anom':>5} | {'Corr':>6} | {'IoU':>6} | {'Recall':>6} | {'Prec':>6} | {'cw_y(m)':>7} | {'y_err(m)':>8} | {'sh_mass%':>8} | {'bt_y(m)':>7} | {'Res_L2':>8}")
    print("-" * 140)
    for r in results:
        print(
            f"{r['mode']:<30} | "
            f"{r['time_s']:>7.1f} | "
            f"{r['max_dens']:>6.3f} | "
            f"{r['anom']:>5d} | "
            f"{r['corr']:>6.4f} | "
            f"{r['iou']:>6.4f} | "
            f"{r['recall']:>6.4f} | "
            f"{r['precision']:>6.4f} | "
            f"{r['cw_y']:>7.1f} | "
            f"{r['y_err']:>+8.1f} | "
            f"{r['sh_mass_pct']:>7.1f}% | "
            f"{r['bt_y']:>7.1f} | "
            f"{r['res_l2']:>8.4f}"
        )
    print("=" * 140)

    # ===================================================================
    # DIAGNÓSTICO
    # ===================================================================
    print("\nDIAGNÓSTICO AUTOMÁTICO:")

    base = next(r for r in results if r["mode"] == "baseline_unweighted")
    best_y = min(results, key=lambda x: abs(x["y_err"]))
    best_corr = max(results, key=lambda x: x["corr"])
    best_iou = max(results, key=lambda x: x["iou"])

    print(f"  • El método que más redujo el error de profundidad fue: '{best_y['mode']}'")
    print(f"    (y_err pasó de {base['y_err']:+.1f} m a {best_y['y_err']:+.1f} m)")
    print(f"  • El método con mejor correlación geométrica fue: '{best_corr['mode']}' (Corr={best_corr['corr']:.4f})")
    print(f"  • El método con mejor IoU física fue: '{best_iou['mode']}' (IoU={best_iou['iou']:.4f})")

    print("\nCONCLUSIÓN Y RECOMENDACIÓN TÉCNICA:")
    if best_y["mode"] != "baseline_unweighted":
        if best_y["corr"] < base["corr"] * 0.8:
            print("  ⚠  El weighting mejoró la profundidad, pero destruyó significativamente la correlación global.")
            print("     Existe un claro tradeoff. Es necesario afinar Beta o implementar un esquema de regularización acoplado.")
        elif best_y["corr"] >= base["corr"]:
            print("  ✅ El weighting mejoró la profundidad y a la vez preservó o mejoró la correlación.")
            print(f"     Se recomienda implementar '{best_y['mode']}' productivamente en la matriz G.")
        else:
            print("  ✅ El weighting hundió la masa con un sacrificio mínimo de forma.")
            print(f"     '{best_y['mode']}' es el candidato principal para el solver productivo.")
    else:
        print("  ❌ Ningún weighting mejoró sustancialmente la posición del baseline.")
        print("     Revisar los umbrales físicos o las matrices de transformación del solver.")

    print("\nFin del experimento no productivo.\n")


if __name__ == "__main__":
    run_experiment()
