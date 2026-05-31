"""
TerraQuantum Synthetic Copper Demo v1 — Robustness Suite para Depth Weighting

Prueba la robustez del "Geometric Depth Weighting" en múltiples escenarios
sintéticos para encontrar un parámetro beta (β) óptimo que evite el sobre-ajuste
a un solo caso.

Genera sintéticamente los escenarios, simula observaciones directas con kernel
y añade ruido, sin leer datos de disco ni persistir corridas productivas.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\demo\\run_tq_synthetic_copper_demo_v1_weighting_robustness_suite.py
"""

import math
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

# ---------------------------------------------------------------------------
# Configuración del entorno
# ---------------------------------------------------------------------------
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.geophysics_service import estimate_grade_from_geophysics
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    centroid_weighted,
    CUTOFF_DENSITY,
    CUTOFF_VISUAL_SCORE,
    BASE_DENSITY,
    TOTAL_VOXELS,
    NX, NY, NZ,
    BLOCK_SIZE,
)

# ---------------------------------------------------------------------------
# Generación de Grillas
# ---------------------------------------------------------------------------
grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix_arr = grid_x.flatten(order="F").astype(np.int32)
iy_arr = grid_y.flatten(order="F").astype(np.int32)
iz_arr = grid_z.flatten(order="F").astype(np.int32)

x_c = (ix_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
y_c = (iy_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
z_c = (iz_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

# 33x33 sensores en superficie
x_obs = np.linspace(0, 800, 33)
z_obs = np.linspace(0, 800, 33)
xv, zv = np.meshgrid(x_obs, z_obs, indexing="ij")
sensor_coords = np.column_stack((xv.ravel(), np.zeros_like(xv.ravel()), zv.ravel()))


# ---------------------------------------------------------------------------
# Generador de Escenarios
# ---------------------------------------------------------------------------
def build_gaussian_body(cx, cy, cz, rx, ry, rz, max_contrast=0.55):
    r2_norm = ((x_c - cx) / rx) ** 2 + ((y_c - cy) / ry) ** 2 + ((z_c - cz) / rz) ** 2
    contrast = max_contrast * np.exp(-r2_norm)
    contrast[contrast < 0.05] = 0.0
    return contrast


def generate_scenarios() -> Dict[str, np.ndarray]:
    scenarios = {}
    
    # A. Shallow body
    scenarios["shallow_body"] = build_gaussian_body(
        cx=400, cy=120, cz=400, rx=120, ry=80, rz=120
    )
    
    # B. Mid body
    scenarios["mid_body"] = build_gaussian_body(
        cx=400, cy=230, cz=400, rx=150, ry=120, rz=150
    )
    
    # C. Deep body
    scenarios["deep_body"] = build_gaussian_body(
        cx=400, cy=330, cz=400, rx=150, ry=120, rz=150
    )
    
    # D. Elongated body
    scenarios["elongated_body"] = build_gaussian_body(
        cx=400, cy=230, cz=400, rx=250, ry=90, rz=100
    )
    
    # E. Two bodies (shallow + deep)
    b1 = build_gaussian_body(cx=250, cy=150, cz=250, rx=100, ry=80, rz=100, max_contrast=0.5)
    b2 = build_gaussian_body(cx=550, cy=300, cz=550, rx=120, ry=100, rz=120, max_contrast=0.6)
    scenarios["two_bodies"] = np.maximum(b1, b2)
    
    return scenarios


# ---------------------------------------------------------------------------
# Solver Experimental Aislado
# ---------------------------------------------------------------------------
def solve_experimental(kernel_sparse, g_observed, beta: float):
    n_sensors, n_voxels = kernel_sparse.shape

    scale_G = float(np.max(np.abs(kernel_sparse.data)))
    G_norm = kernel_sparse / scale_G
    g_obs_norm = g_observed / scale_G

    if beta == 0.0:
        W_inv_diag = np.ones(n_voxels, dtype=np.float64)
    else:
        # Geometric depth weighting: W_inv = y^(beta / 2)
        # Esto viene de W_z * m_tilde, si w_j = 1/y^(beta/2), m = W_z^{-1} m_tilde = y^(beta/2) * m_tilde
        W_inv_diag = np.power(y_c, beta / 2.0)

    W_inv_diag /= np.mean(W_inv_diag)
    W_inv_mat = sp.diags(W_inv_diag, 0, format="csr")

    G_tilde = G_norm.dot(W_inv_mat)

    dummy_inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    W_spatial = dummy_inv._build_spatial_regularizer()
    W_spatial_norm = W_spatial / 6.0
    W_spatial_tilde = W_spatial_norm.dot(W_inv_mat)

    lambda_mag = 0.00005
    alpha_spatial = 1.0
    lambda_spatial = float(alpha_spatial) * (n_sensors / n_voxels)

    G_aug = sp.vstack([G_tilde, lambda_spatial * W_spatial_tilde], format="csr")
    d_aug = np.concatenate([g_obs_norm, np.zeros(n_voxels, dtype=np.float64)])

    result = lsqr(G_aug, d_aug, damp=lambda_mag, iter_lim=250, show=False)
    m_tilde = result[0]
    m = m_tilde * W_inv_diag

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
    
    return estimated_density, visual_score, probability, residual_l2


# ---------------------------------------------------------------------------
# Evaluación de Métricas
# ---------------------------------------------------------------------------
def compute_metrics(contrast_true, est_density, visual_score, probability, res_l2):
    contrast_rec = est_density - BASE_DENSITY
    cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)
    
    grade = estimate_grade_from_geophysics(est_density, probability, 83, 79, "norte_chile")
    mask_rec_physical = (est_density >= CUTOFF_DENSITY) | (visual_score >= CUTOFF_VISUAL_SCORE)
    n_rec = int(np.sum(mask_rec_physical))
    
    ranking_score = np.where(
        mask_rec_physical,
        probability * np.maximum(est_density - 2.6, 0.0) * np.maximum(grade, 0.01),
        -1.0
    )
    best_idx = int(np.argmax(ranking_score)) if n_rec > 0 else -1
    bt_y = float(y_c[best_idx]) if best_idx >= 0 else float("nan")

    corr = float(np.corrcoef(contrast_true, contrast_rec)[0, 1]) if np.std(contrast_true) > 0 and np.std(contrast_rec) > 0 else 0.0
    
    mt = contrast_true > 0
    mr = mask_rec_physical
    n_true_active = int(np.sum(mt))
    intersection = int(np.sum(mt & mr))
    union_count  = int(np.sum(mt | mr))
    iou = intersection / max(union_count, 1)
    recall = intersection / max(n_true_active, 1)
    precision = intersection / max(n_rec, 1)

    cr_pos = np.maximum(contrast_rec, 0.0)
    cw_rec = centroid_weighted(x_c, y_c, z_c, cr_pos)
    y_err = cw_rec[1] - cw_true[1] if math.isfinite(cw_rec[1]) and math.isfinite(cw_true[1]) else float("nan")

    shallow_mask = iy_arr <= 3
    shallow_mass_pct = 100.0 * float(np.sum(cr_pos[shallow_mask])) / max(float(np.sum(cr_pos)), 1e-15)

    # Top-N body overlap
    k_body = max(1, n_true_active)
    top_true_body = set(np.argsort(contrast_true)[::-1][:k_body].tolist())
    top_rec_body  = set(np.argsort(contrast_rec)[::-1][:k_body].tolist())
    top_overlap = len(top_true_body & top_rec_body) / k_body

    return {
        "corr": corr,
        "iou": iou,
        "recall": recall,
        "precision": precision,
        "top_n_overlap": top_overlap,
        "cw_y": cw_rec[1],
        "y_err": y_err,
        "sh_mass_pct": shallow_mass_pct,
        "res_l2": res_l2,
        "bt_y": bt_y,
    }


# ---------------------------------------------------------------------------
# Ejecución Principal
# ---------------------------------------------------------------------------
def run_robustness_suite():
    print("=" * 120)
    print("TerraQuantum — Suite de Robustez para Geometric Depth Weighting")
    print("=" * 120)

    # 1. Construir kernel general (cutoff 600m)
    print("\n[1] Construyendo Kernel Forward (cutoff=600m)...")
    t0_k = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Kernel completado en {time.perf_counter() - t0_k:.1f} s. NNZ={kernel.nnz:,}")

    scenarios = generate_scenarios()
    
    betas_to_test = [0.0, 0.25, 0.50, 0.75, 1.00]
    
    # metrics_db[beta][scenario_name] = metrics_dict
    metrics_db = {beta: {} for beta in betas_to_test}

    np.random.seed(42)  # Para ruido reproducible

    print("\n[2] Ejecutando Escenarios...")
    
    for sc_name, contrast_true in scenarios.items():
        print(f"\n  ➤ Escenario: {sc_name}")
        cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)
        print(f"    Centroide ponderado verdadero y = {cw_true[1]:.1f} m")

        # Generar observaciones sintéticas con 1% de ruido gaussiano
        g_exact = kernel @ contrast_true
        noise_std = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, noise_std, size=g_exact.shape)

        for beta in betas_to_test:
            est_density, visual_score, probability, res_l2 = solve_experimental(
                kernel, g_obs, beta
            )
            mets = compute_metrics(contrast_true, est_density, visual_score, probability, res_l2)
            metrics_db[beta][sc_name] = mets
            
            # Print short summary per run
            mode_name = f"baseline" if beta == 0.0 else f"beta_{beta:.2f}"
            print(f"      {mode_name:<10} | y_err: {mets['y_err']:+6.1f}m | corr: {mets['corr']:.4f} | iou: {mets['iou']:.4f}")

    # ===================================================================
    # TABLA RESUMEN POR BETA
    # ===================================================================
    print("\n" + "=" * 120)
    print("RESUMEN DE ROBUSTEZ POR BETA (Agregado de todos los escenarios)")
    print("-" * 120)
    print(f"{'Beta Mode':<15} | {'Mean Corr':>9} | {'Mean IoU':>9} | {'Mean |y_err|':>12} | {'Worst |y_err|':>13} | {'Mean Shallow%':>13}")
    print("-" * 120)

    summary_stats = []

    for beta in betas_to_test:
        mode_name = "baseline" if beta == 0.0 else f"beta={beta:.2f}"
        
        corrs = [mets["corr"] for mets in metrics_db[beta].values()]
        ious = [mets["iou"] for mets in metrics_db[beta].values()]
        abs_y_errs = [abs(mets["y_err"]) for mets in metrics_db[beta].values() if math.isfinite(mets["y_err"])]
        shallows = [mets["sh_mass_pct"] for mets in metrics_db[beta].values()]
        
        mean_corr = np.mean(corrs)
        mean_iou = np.mean(ious)
        mean_abs_y_err = np.mean(abs_y_errs) if abs_y_errs else float("nan")
        worst_abs_y_err = np.max(abs_y_errs) if abs_y_errs else float("nan")
        mean_shallow = np.mean(shallows)

        summary_stats.append({
            "beta": beta,
            "mode": mode_name,
            "mean_corr": mean_corr,
            "mean_iou": mean_iou,
            "mean_abs_y_err": mean_abs_y_err,
            "worst_abs_y_err": worst_abs_y_err,
            "mean_shallow": mean_shallow,
        })

        print(
            f"{mode_name:<15} | "
            f"{mean_corr:>9.4f} | "
            f"{mean_iou:>9.4f} | "
            f"{mean_abs_y_err:>10.1f} m | "
            f"{worst_abs_y_err:>11.1f} m | "
            f"{mean_shallow:>12.1f}%"
        )
    print("=" * 120)

    # ===================================================================
    # DIAGNÓSTICO FINAL AUTOMÁTICO
    # ===================================================================
    print("\nDIAGNÓSTICO AUTOMÁTICO:")

    best_corr = max(summary_stats, key=lambda x: x["mean_corr"])
    best_y_err = min(summary_stats, key=lambda x: x["mean_abs_y_err"])
    baseline = next(s for s in summary_stats if s["beta"] == 0.0)

    print(f"  • Baseline: Error de profundidad medio = {baseline['mean_abs_y_err']:.1f} m.")
    print(f"  • Mejor recuperación de profundidad (y_err): {best_y_err['mode']} ({best_y_err['mean_abs_y_err']:.1f} m).")
    print(f"  • Mejor preservación morfológica (Corr): {best_corr['mode']} ({best_corr['mean_corr']:.4f}).")

    if best_y_err["beta"] == 0.50 and best_corr["beta"] >= 0.50:
        print("  ✅ beta=0.50 ofrece el mejor equilibrio entre profundidad y correlación en todos los casos.")
    elif best_y_err["beta"] != best_corr["beta"]:
        print(f"  ⚠  Tradeoff detectado: {best_y_err['mode']} hunde mejor las anomalías, pero {best_corr['mode']} mantiene mejor la forma.")
        print("     Se debe elegir el beta que maximice correlación sin exceder un y_err de ~50m (2 bloques).")
    
    # Análisis sobre best_target_y
    all_bt_y = [mets["bt_y"] for sc in metrics_db[0.5].values() for mets in [sc] if math.isfinite(mets["bt_y"])]
    all_cw_y = [mets["cw_y"] for sc in metrics_db[0.5].values() for mets in [sc] if math.isfinite(mets["cw_y"])]
    
    if all_bt_y and all_cw_y:
        avg_bt = np.mean(all_bt_y)
        avg_cw = np.mean(all_cw_y)
        if avg_bt < avg_cw * 0.8:
            print("  ⚠  ALERTA: best_target_y se mantiene sistemáticamente más somero que el centroide volumétrico recuperado.")
            print("     Esto significa que, aunque el depth weighting recupere la masa correctamente, la heurística")
            print("     puntual de target (probability * density * grade) sigue penalizando la profundidad.")
            print("     Se requerirá revisión separada de build_best_target.")

    print("\nRECOMENDACIÓN TÉCNICA:")
    print("Seleccionar el beta que mejor reduzca el worst_abs_y_error sin destruir el mean_corr.")
    print("Una vez elegido, este valor puede implementarse en geophysics_service.py y exploration/gravimetry.py.")
    print("\nFin de la suite de robustez.\n")


if __name__ == "__main__":
    run_robustness_suite()
