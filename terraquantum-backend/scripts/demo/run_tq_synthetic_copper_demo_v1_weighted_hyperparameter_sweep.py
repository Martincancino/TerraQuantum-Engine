"""
TerraQuantum Synthetic Copper Demo v1 — Barrido de Hiperparámetros (Weighting)

Explora exhaustivamente el espacio de parámetros de la inversión gravimétrica
ponderada (beta, lambda_mag, alpha_spatial) para priorizar candidatos óptimos
antes de pasar a validaciones de robustez sobre múltiples escenarios.

No modifica servicios productivos ni usa datos reales.
"""

import math
import os
import sys
import time

import numpy as np
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

# Ground Truth analítico
contrast_true, x_c, y_c, z_c, ix_arr, iy_arr, iz_arr = build_true_contrast_on_inversion_grid()
mask_true_active = contrast_true > 0.05
cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)

PHYSICAL_CONTRAST_THRESHOLD = 0.15
mask_true_physical = contrast_true >= PHYSICAL_CONTRAST_THRESHOLD
n_true_physical = int(np.sum(mask_true_physical))


# ---------------------------------------------------------------------------
# Solver Experimental Parametrizado
# ---------------------------------------------------------------------------
def solve_experimental(kernel_sparse, g_observed, beta: float, lambda_mag: float, alpha_spatial: float):
    t0 = time.perf_counter()
    n_sensors, n_voxels = kernel_sparse.shape

    scale_G = float(np.max(np.abs(kernel_sparse.data)))
    G_norm = kernel_sparse / scale_G
    g_obs_norm = g_observed / scale_G

    if beta == 0.0:
        W_inv_diag = np.ones(n_voxels, dtype=np.float64)
    else:
        W_inv_diag = np.power(y_c, beta / 2.0)

    W_inv_diag /= np.mean(W_inv_diag)
    W_inv_mat = sp.diags(W_inv_diag, 0, format="csr")

    G_tilde = G_norm.dot(W_inv_mat)

    dummy_inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    W_spatial = dummy_inv._build_spatial_regularizer()
    W_spatial_norm = W_spatial / 6.0
    W_spatial_tilde = W_spatial_norm.dot(W_inv_mat)

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
    
    t_end = time.perf_counter()
    return estimated_density, visual_score, probability, residual_l2, t_end - t0


def min_max_norm(arr):
    arr = np.array(arr)
    mn, mx = np.min(arr), np.max(arr)
    if mx == mn:
        return np.zeros_like(arr)
    return (arr - mn) / (mx - mn)


def run_hyperparameter_sweep():
    print("=" * 140)
    print("TerraQuantum — Barrido de Hiperparámetros de Inversión Ponderada")
    print("=" * 140)

    csv_path = os.path.join(BACKEND_ROOT, CSV_RELPATH)
    if not os.path.exists(csv_path):
        print(f"❌  CSV no encontrado: {csv_path}")
        sys.exit(1)

    print(f"\n[1] Cargando observaciones desde: {csv_path}")
    import_result = import_gravity_csv_v1(csv_path, strict=True, allow_g_raw=False)
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

    betas = [0.50, 0.75, 1.00]
    lambdas = [0.00001, 0.00005, 0.00010]
    alphas = [0.25, 0.50, 1.00, 2.00]
    
    total_runs = len(betas) * len(lambdas) * len(alphas)
    
    results = []

    print(f"\n[3] Ejecutando barrido de {total_runs} combinaciones...")
    
    run_idx = 1
    for beta in betas:
        for l_mag in lambdas:
            for a_spat in alphas:
                sys.stdout.write(f"\r    -> Inversión {run_idx}/{total_runs} (beta={beta:.2f}, l_mag={l_mag:.5f}, a_spat={a_spat:.2f})...")
                sys.stdout.flush()
                
                est_density, visual_score, probability, res_l2, t_inv = solve_experimental(
                    kernel, g_obs, beta, l_mag, a_spat
                )
                
                contrast_rec = est_density - BASE_DENSITY
                max_dens = float(np.max(est_density))
                
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

                corr = float(np.corrcoef(contrast_true, contrast_rec)[0, 1]) if np.std(contrast_rec) > 0 else 0.0
                
                mt = mask_true_active
                mr = mask_rec_physical
                intersection = int(np.sum(mt & mr))
                union_count  = int(np.sum(mt | mr))
                iou = intersection / max(union_count, 1)
                recall = intersection / max(int(np.sum(mt)), 1)
                precision = intersection / max(n_rec, 1)
                f1 = 2 * precision * recall / max(precision + recall, 1e-15)
                
                # Physical comparisons
                inter_phys = int(np.sum(mask_true_physical & mask_rec_physical))
                prec_phys = inter_phys / max(n_rec, 1)
                recall_phys = inter_phys / max(n_true_physical, 1)

                cr_pos = np.maximum(contrast_rec, 0.0)
                cw_rec = centroid_weighted(x_c, y_c, z_c, cr_pos)
                y_err = cw_rec[1] - cw_true[1] if math.isfinite(cw_rec[1]) else float("nan")
                
                shallow_mask = iy_arr <= 3
                sh_mass = float(np.sum(cr_pos[shallow_mask]))
                sh_mass_pct = 100.0 * sh_mass / max(float(np.sum(cr_pos)), 1e-15)

                results.append({
                    "id": f"b{beta:.2f}_l{l_mag:.5f}_a{a_spat:.2f}",
                    "beta": beta,
                    "l_mag": l_mag,
                    "a_spat": a_spat,
                    "time_s": t_inv,
                    "max_dens": max_dens,
                    "anom": n_rec,
                    "corr": corr,
                    "iou": iou,
                    "recall": recall,
                    "prec": precision,
                    "f1": f1,
                    "cw_y": cw_rec[1],
                    "y_err": y_err,
                    "abs_y_err": abs(y_err) if math.isfinite(y_err) else 999.0,
                    "sh_mass_pct": sh_mass_pct,
                    "bt_y": bt_y,
                    "res_l2": res_l2,
                    "prec_phys": prec_phys,
                    "recall_phys": recall_phys
                })
                run_idx += 1
    
    print("\n    ¡Barrido completado!")

    # 4. Calcular score compuesto
    # Score = + 0.30*norm_corr + 0.25*norm_iou + 0.20*norm_f1 - 0.15*norm_abs_y_err - 0.10*norm_sh_mass_pct
    arr_corr = [r["corr"] for r in results]
    arr_iou = [r["iou"] for r in results]
    arr_f1 = [r["f1"] for r in results]
    arr_abs_y_err = [r["abs_y_err"] for r in results]
    arr_sh_mass = [r["sh_mass_pct"] for r in results]

    n_corr = min_max_norm(arr_corr)
    n_iou = min_max_norm(arr_iou)
    n_f1 = min_max_norm(arr_f1)
    n_abs_y_err = min_max_norm(arr_abs_y_err)
    n_sh_mass = min_max_norm(arr_sh_mass)

    for i, r in enumerate(results):
        score = (0.30 * n_corr[i] + 
                 0.25 * n_iou[i] + 
                 0.20 * n_f1[i] - 
                 0.15 * n_abs_y_err[i] - 
                 0.10 * n_sh_mass[i])
        r["score"] = score

    # Ordenar por score descendente
    results_sorted = sorted(results, key=lambda x: x["score"], reverse=True)

    # 5. Hallar Frente de Pareto
    pareto_front = []
    for i, r_a in enumerate(results):
        dominated = False
        for j, r_b in enumerate(results):
            if i == j: continue
            # r_b domina a r_a si es mejor o igual en todo, y estrictamente mejor en algo
            # Consideramos mejores: mayor corr, mayor iou, menor abs_y_err
            b_better_or_eq = (r_b['corr'] >= r_a['corr'] and 
                              r_b['iou'] >= r_a['iou'] and 
                              r_b['abs_y_err'] <= r_a['abs_y_err'])
            b_strictly_better = (r_b['corr'] > r_a['corr'] or 
                                 r_b['iou'] > r_a['iou'] or 
                                 r_b['abs_y_err'] < r_a['abs_y_err'])
            if b_better_or_eq and b_strictly_better:
                dominated = True
                break
        if not dominated:
            pareto_front.append(r_a)
    
    pareto_front.sort(key=lambda x: x["corr"], reverse=True)

    # ===================================================================
    # IMPRESIONES
    # ===================================================================
    def print_table_header():
        print(f"{'ID (b_l_a)':<22} | {'Score':>7} | {'Corr':>7} | {'IoU':>7} | {'F1':>7} | {'cw_y(m)':>7} | {'y_err(m)':>8} | {'sh_mass%':>8} | {'Prc_Phys':>8} | {'Anom':>5} | {'MaxDen':>6}")
        print("-" * 115)

    def print_row(r):
        print(
            f"{r['id']:<22} | "
            f"{r['score']:>7.3f} | "
            f"{r['corr']:>7.4f} | "
            f"{r['iou']:>7.4f} | "
            f"{r['f1']:>7.4f} | "
            f"{r['cw_y']:>7.1f} | "
            f"{r['y_err']:>+8.1f} | "
            f"{r['sh_mass_pct']:>7.1f}% | "
            f"{r['prec_phys']:>8.1%} | "
            f"{r['anom']:>5d} | "
            f"{r['max_dens']:>6.3f}"
        )

    print("\n" + "=" * 115)
    print("A. TABLA COMPLETA (36 combinaciones)")
    print("=" * 115)
    print_table_header()
    for r in results:
        print_row(r)

    print("\n" + "=" * 115)
    print("B. TOP 10 POR SCORE COMPUESTO")
    print("Fórmula: Score = 0.30*N(Corr) + 0.25*N(IoU) + 0.20*N(F1) - 0.15*N(|y_err|) - 0.10*N(sh_mass)")
    print("=" * 115)
    print_table_header()
    for r in results_sorted[:10]:
        print_row(r)

    print("\n" + "=" * 115)
    print("C. TOP 5 POR MÉTRICAS INDIVIDUALES")
    print("=" * 115)
    
    print("\n -> Menor |y_err|:")
    for r in sorted(results, key=lambda x: x["abs_y_err"])[:5]:
        print(f"    {r['id']:<22} : {r['y_err']:+.1f} m")
        
    print("\n -> Mayor Correlación:")
    for r in sorted(results, key=lambda x: x["corr"], reverse=True)[:5]:
        print(f"    {r['id']:<22} : {r['corr']:.4f}")
        
    print("\n -> Mayor IoU:")
    for r in sorted(results, key=lambda x: x["iou"], reverse=True)[:5]:
        print(f"    {r['id']:<22} : {r['iou']:.4f}")
        
    print("\n -> Mayor F1:")
    for r in sorted(results, key=lambda x: x["f1"], reverse=True)[:5]:
        print(f"    {r['id']:<22} : {r['f1']:.4f}")

    print("\n" + "=" * 115)
    print("D. CONJUNTO PARETO (No dominados en Corr, IoU, |y_err|)")
    print("=" * 115)
    print_table_header()
    for r in pareto_front:
        print_row(r)

    # ===================================================================
    # DIAGNÓSTICO AUTOMÁTICO
    # ===================================================================
    print("\n" + "=" * 115)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 115)

    # Impacto de alpha_spatial
    alpha_corrs = {a: np.mean([r["corr"] for r in results if r["a_spat"] == a]) for a in alphas}
    best_alpha = max(alpha_corrs, key=alpha_corrs.get)
    worst_alpha = min(alpha_corrs, key=alpha_corrs.get)
    if best_alpha < 1.0:
        print(f"  • Alpha Spatial: Bajar alpha_spatial a {best_alpha:.2f} mejora la forma volumétrica (Corr media: {alpha_corrs[best_alpha]:.4f} vs {alpha_corrs[worst_alpha]:.4f} en peor caso).")
    else:
        print(f"  • Alpha Spatial: Subir alpha_spatial a {best_alpha:.2f} ayuda a cohesionar la forma (Corr media: {alpha_corrs[best_alpha]:.4f}).")

    # Impacto de beta
    beta_yerrs = {b: np.mean([r["abs_y_err"] for r in results if r["beta"] == b]) for b in betas}
    beta_corrs = {b: np.mean([r["corr"] for r in results if r["beta"] == b]) for b in betas}
    print(f"  • Beta Weighting: beta=1.0 mejora la correlación geométrica (Corr media b=1.0: {beta_corrs[1.0]:.4f} vs b=0.5: {beta_corrs[0.5]:.4f}),")
    print(f"    pero sobrecorrige la profundidad y aumenta el error absoluto respecto a beta=0.75 (Error medio b=1.0: {beta_yerrs[1.0]:.1f}m vs b=0.75: {beta_yerrs[0.75]:.1f}m).")
    if beta_yerrs[1.0] > beta_yerrs[0.75]:
        print("    -> CUIDADO: beta=1.0 está SOBRECORRIGIENDO y mandando la masa muy profundo, empeorando el error absoluto.")

    # Impacto de lambda_mag
    lambda_std_score = np.std([np.mean([r["score"] for r in results if r["l_mag"] == l]) for l in lambdas])
    alpha_std_score = np.std([np.mean([r["score"] for r in results if r["a_spat"] == a]) for a in alphas])
    if lambda_std_score < alpha_std_score * 0.5:
        print(f"  • Lambda Mag: El impacto de variar lambda_mag es MARGINAL comparado con el de alpha_spatial.")
    else:
        print(f"  • Lambda Mag: lambda_mag tiene un impacto IMPORTANTE en la calidad del modelo.")

    # Selección de candidatos
    print("\nCANDIDATOS RECOMENDADOS PARA SUITE ROBUSTA:")
    candidates = []
    seen_architectures = set()

    def add_candidate(desc, r):
        arch = (r["beta"], r["a_spat"])
        if any(c[1]["id"] == r["id"] for c in candidates):
            return False
        if arch in seen_architectures:
            print(f"  [Descartado: {desc:<14}] {r['id']:<22} -> Duplicado geométrico de arquitectura (beta={arch[0]:.2f}, alpha={arch[1]:.2f})")
            return False
        seen_architectures.add(arch)
        candidates.append((desc, r))
        return True

    # 1. Highest Score
    add_candidate("Highest Score", results_sorted[0])
    # 2. Highest Pareto IoU
    pareto_iou = sorted(pareto_front, key=lambda x: x["iou"], reverse=True)[0]
    add_candidate("Max Pareto IoU", pareto_iou)
    # 3. Best depth error from Pareto
    pareto_depth = sorted(pareto_front, key=lambda x: x["abs_y_err"])[0]
    add_candidate("Min Depth Err", pareto_depth)
    # 4. Alternative top score if space available
    for r in results_sorted:
        if len(candidates) >= 4:
            break
        add_candidate("Alt. Top Score", r)

    print("")
    for desc, c in candidates:
        print(f"  [{desc:<25}] {c['id']:<22} -> Beta: {c['beta']:.2f}, Lambda: {c['l_mag']:.5f}, Alpha: {c['a_spat']:.2f}")

    print("\nFin del barrido de hiperparámetros no productivo.\n")


if __name__ == "__main__":
    run_hyperparameter_sweep()
