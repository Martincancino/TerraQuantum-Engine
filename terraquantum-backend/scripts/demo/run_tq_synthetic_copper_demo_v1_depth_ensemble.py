"""
TerraQuantum Synthetic Copper Demo v1 — Ensemble de Profundidad e Incertidumbre

Combina varias inversiones con distintos beta de depth weighting para cuantificar
incertidumbre de profundidad, estabilidad espacial de las anomalías y el grado
de consenso entre los distintos modelos posibles.

No elige todavía un único beta, sino que clasifica el volumen en un "stable core"
(donde todos los modelos están de acuerdo) y un "uncertain shell" (donde depende
del peso de profundidad asumido).

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

# ---------------------------------------------------------------------------
# Funciones base
# ---------------------------------------------------------------------------
def solve_experimental(kernel_sparse, g_observed, y_c, beta: float):
    """Resuelve la inversión con Geometric Depth Weighting (beta)."""
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
    
    t_end = time.perf_counter()
    return estimated_density, visual_score, probability, residual_l2, t_end - t0


def run_ensemble():
    print("=" * 120)
    print("TerraQuantum — Ensemble de Profundidad e Incertidumbre Vertical")
    print("=" * 120)

    # 1. Cargar datos
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

    # 2. Ground truth
    contrast_true, x_c, y_c, z_c, ix_arr, iy_arr, iz_arr = build_true_contrast_on_inversion_grid()
    mask_true_active = contrast_true > 0
    cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)

    # 3. Construir kernel único
    print("\n[2] Construyendo kernel gravimétrico base (cutoff=600 m)...")
    t0_k = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Kernel completado en {time.perf_counter() - t0_k:.1f} s. NNZ={kernel.nnz:,}")

    betas_to_test = [0.0, 0.25, 0.50, 0.75, 1.00]
    
    ensemble_contrasts = []
    ensemble_masks = []
    
    results = []
    
    print("\n[3] Ejecutando miembros del Ensemble...")
    for beta in betas_to_test:
        print(f"    -> Resolviendo para beta={beta:.2f}")
        est_density, visual_score, probability, res_l2, t_inv = solve_experimental(
            kernel, g_obs, y_c, beta
        )
        
        contrast_rec = est_density - BASE_DENSITY
        ensemble_contrasts.append(contrast_rec)
        
        grade = estimate_grade_from_geophysics(est_density, probability, 83, 79, "norte_chile")
        mask_physical = (est_density >= CUTOFF_DENSITY) | (visual_score >= CUTOFF_VISUAL_SCORE)
        ensemble_masks.append(mask_physical)
        
        n_rec = int(np.sum(mask_physical))
        ranking_score = np.where(
            mask_physical,
            probability * np.maximum(est_density - 2.6, 0.0) * np.maximum(grade, 0.01),
            -1.0
        )
        best_idx = int(np.argmax(ranking_score)) if n_rec > 0 else -1
        bt_y = float(y_c[best_idx]) if best_idx >= 0 else float("nan")
        
        corr = float(np.corrcoef(contrast_true, contrast_rec)[0, 1]) if np.std(contrast_rec) > 0 else 0.0
        
        mt = mask_true_active
        mr = mask_physical
        intersection = int(np.sum(mt & mr))
        union_count  = int(np.sum(mt | mr))
        iou = intersection / max(union_count, 1)
        
        cr_pos = np.maximum(contrast_rec, 0.0)
        cw_rec = centroid_weighted(x_c, y_c, z_c, cr_pos)
        y_err = cw_rec[1] - cw_true[1] if math.isfinite(cw_rec[1]) else float("nan")
        
        shallow_mask = iy_arr <= 3
        sh_mass = float(np.sum(cr_pos[shallow_mask]))
        sh_mass_pct = 100.0 * sh_mass / max(float(np.sum(cr_pos)), 1e-15)
        
        results.append({
            "beta": beta,
            "corr": corr,
            "iou": iou,
            "cw_y": cw_rec[1],
            "y_err": y_err,
            "sh_mass_pct": sh_mass_pct,
            "bt_y": bt_y,
        })

    # ===================================================================
    # ANÁLISIS DEL ENSEMBLE
    # ===================================================================
    print("\n[4] Calculando métricas del Ensemble...")
    
    contrasts_mat = np.vstack(ensemble_contrasts) # shape: (5, TOTAL_VOXELS)
    masks_mat = np.vstack(ensemble_masks)         # shape: (5, TOTAL_VOXELS)
    
    median_contrast = np.median(contrasts_mat, axis=0)
    std_contrast = np.std(contrasts_mat, axis=0)
    
    anomaly_vote_fraction = np.mean(masks_mat, axis=0)
    
    stable_core = anomaly_vote_fraction >= 0.80
    uncertain_shell = (anomaly_vote_fraction >= 0.20) & (anomaly_vote_fraction < 0.80)
    background = anomaly_vote_fraction < 0.20
    
    n_core = int(np.sum(stable_core))
    n_shell = int(np.sum(uncertain_shell))
    n_back = int(np.sum(background))
    
    cw_median = centroid_weighted(x_c, y_c, z_c, np.maximum(median_contrast, 0.0))
    
    all_cw_y = [r["cw_y"] for r in results if math.isfinite(r["cw_y"])]
    all_bt_y = [r["bt_y"] for r in results if math.isfinite(r["bt_y"])]
    
    cw_y_min, cw_y_max = min(all_cw_y), max(all_cw_y)
    bt_y_min, bt_y_max = min(all_bt_y), max(all_bt_y)
    
    # ─── Métricas de cobertura: Full-Body (contrast_true > 0.05) ────────
    intersection_core = int(np.sum(mask_true_active & stable_core))
    union_core = int(np.sum(mask_true_active | stable_core))
    iou_core = intersection_core / max(union_core, 1)
    recall_core = intersection_core / max(int(np.sum(mask_true_active)), 1)
    prec_core = intersection_core / max(n_core, 1)
    
    mask_core_shell = stable_core | uncertain_shell
    intersection_cs = int(np.sum(mask_true_active & mask_core_shell))
    union_cs = int(np.sum(mask_true_active | mask_core_shell))
    iou_cs = intersection_cs / max(union_cs, 1)
    
    true_in_core = int(np.sum(mask_true_active & stable_core)) / max(int(np.sum(mask_true_active)), 1)
    true_in_shell = int(np.sum(mask_true_active & uncertain_shell)) / max(int(np.sum(mask_true_active)), 1)
    true_in_back = int(np.sum(mask_true_active & background)) / max(int(np.sum(mask_true_active)), 1)

    # ─── Métricas de cobertura: Physical-Core (contrast_true >= 0.15) ─
    # Esto genera una comparación justa: el umbral de anomalía recuperada
    # (density >= 2.75, es decir contrast >= 0.15) debe compararse contra
    # un ground truth con el mismo umbral de contraste.
    PHYSICAL_CONTRAST_THRESHOLD = 0.15  # = CUTOFF_DENSITY - BASE_DENSITY
    mask_true_physical = contrast_true >= PHYSICAL_CONTRAST_THRESHOLD
    n_true_physical = int(np.sum(mask_true_physical))

    intersection_core_phys = int(np.sum(mask_true_physical & stable_core))
    union_core_phys = int(np.sum(mask_true_physical | stable_core))
    iou_core_phys = intersection_core_phys / max(union_core_phys, 1)
    recall_core_phys = intersection_core_phys / max(n_true_physical, 1)
    prec_core_phys = intersection_core_phys / max(n_core, 1)

    intersection_cs_phys = int(np.sum(mask_true_physical & mask_core_shell))
    union_cs_phys = int(np.sum(mask_true_physical | mask_core_shell))
    iou_cs_phys = intersection_cs_phys / max(union_cs_phys, 1)

    true_phys_in_core = int(np.sum(mask_true_physical & stable_core)) / max(n_true_physical, 1)
    true_phys_in_shell = int(np.sum(mask_true_physical & uncertain_shell)) / max(n_true_physical, 1)
    true_phys_in_back = int(np.sum(mask_true_physical & background)) / max(n_true_physical, 1)

    # ─── Identificar mejores betas por métrica (datos reales, no hardcoded) ─
    best_beta_y_err = min(results, key=lambda r: abs(r["y_err"]) if math.isfinite(r["y_err"]) else 999)
    best_beta_corr = max(results, key=lambda r: r["corr"])
    best_beta_iou = max(results, key=lambda r: r["iou"])

    # ===================================================================
    # REPORTE TABULAR
    # ===================================================================
    print("\n" + "=" * 100)
    print("TABLA POR BETA")
    print("-" * 100)
    print(f"{'Beta':<6} | {'Corr':>7} | {'IoU':>7} | {'cw_y(m)':>8} | {'y_err(m)':>9} | {'sh_mass%':>9} | {'bt_y(m)':>8}")
    print("-" * 100)
    for r in results:
        print(f"{r['beta']:<6.2f} | {r['corr']:>7.4f} | {r['iou']:>7.4f} | {r['cw_y']:>8.1f} | {r['y_err']:>+9.1f} | {r['sh_mass_pct']:>8.1f}% | {r['bt_y']:>8.1f}")
    print("=" * 100)

    print("\n" + "=" * 100)
    print("RESUMEN DEL ENSEMBLE")
    print("-" * 100)
    print(f"  Volumen Stable Core        : {n_core:,} vóxeles (votos >= 80%)")
    print(f"  Volumen Uncertain Shell    : {n_shell:,} vóxeles (votos 20% - 79%)")
    print(f"  Volumen Background         : {n_back:,} vóxeles (votos < 20%)")
    print(f"")
    print(f"  Centroide Y (Median Model) : {cw_median[1]:.1f} m")
    print(f"  Rango Incertidumbre CW Y   : [{cw_y_min:.1f} m, {cw_y_max:.1f} m] (Ancho: {cw_y_max - cw_y_min:.1f} m)")
    print(f"  Rango Incertidumbre BT Y   : [{bt_y_min:.1f} m, {bt_y_max:.1f} m] (Ancho: {bt_y_max - bt_y_min:.1f} m)")
    print(f"")
    print(f"  Cobertura vs Full-Body (contrast > 0.05):")
    print(f"    - Cuerpo verdadero en Core : {true_in_core:.1%}")
    print(f"    - Cuerpo verdadero en Shell: {true_in_shell:.1%}")
    print(f"    - Cuerpo verdadero fuera   : {true_in_back:.1%}")
    print(f"    - Precisión del Core       : {prec_core:.1%}")
    print(f"    - IoU Core                 : {iou_core:.4f}")
    print(f"    - IoU Core+Shell           : {iou_cs:.4f}")
    print(f"")
    print(f"  Cobertura vs Physical-Core (contrast >= 0.15, comparación justa):")
    print(f"    - true_physical vóxeles    : {n_true_physical:,}")
    print(f"    - Phys en Core             : {true_phys_in_core:.1%}")
    print(f"    - Phys en Shell            : {true_phys_in_shell:.1%}")
    print(f"    - Phys fuera               : {true_phys_in_back:.1%}")
    print(f"    - Core IoU vs true_phys    : {iou_core_phys:.4f}")
    print(f"    - Core Recall vs true_phys : {recall_core_phys:.4f}")
    print(f"    - Core Precision vs t_phys : {prec_core_phys:.4f}")
    print(f"    - Core+Shell IoU vs t_phys : {iou_cs_phys:.4f}")
    print("=" * 100)

    # ===================================================================
    # MEJORES BETAS POR MÉTRICA (data-driven)
    # ===================================================================
    print("\nMEJORES BETAS POR MÉTRICA (según tabla):")
    print(f"  • Menor |y_err| : beta={best_beta_y_err['beta']:.2f}  (y_err={best_beta_y_err['y_err']:+.1f} m)")
    print(f"  • Mayor Corr    : beta={best_beta_corr['beta']:.2f}  (corr={best_beta_corr['corr']:.4f})")
    print(f"  • Mayor IoU     : beta={best_beta_iou['beta']:.2f}  (IoU={best_beta_iou['iou']:.4f})")
    if best_beta_y_err["beta"] == best_beta_corr["beta"] == best_beta_iou["beta"]:
        print(f"  ✅ Un único beta={best_beta_y_err['beta']:.2f} domina en todas las métricas.")
    else:
        print("  ⚠  Existe tradeoff entre métricas. No hay un beta dominante único.")

    # ===================================================================
    # DIAGNÓSTICO FINAL AUTOMÁTICO
    # ===================================================================
    print("\nDIAGNÓSTICO AUTOMÁTICO:")

    # Evaluación del Core: consistencia interna
    if n_core > 0 and prec_core_phys > 0.5:
        print("  ✅ Existe un núcleo estable (Stable Core) de alta confianza que no depende del parámetro beta.")
        print("     El centro de gravedad XZ y la existencia de la anomalía son hechos duros inferibles de los datos.")
    elif n_core > 0 and prec_core_phys > 0.3:
        print("  ⚠  Existe un núcleo estable, pero su precisión contra el ground truth físico es moderada.")
        print("     El Core contiene falsos positivos; la interpretación debe ser cautelosa.")
    else:
        print("  ⚠  No existe un núcleo estable claro, o su precisión contra el ground truth físico es baja.")
        print("     El modelo es muy sensible a la parametrización previa.")

    uncert_cw = cw_y_max - cw_y_min
    if uncert_cw > BLOCK_SIZE * 3:
        print(f"  ⚠  La profundidad volumétrica es altamente incierta (ancho de banda {uncert_cw:.1f} m).")
    else:
        print(f"  ✅ La profundidad volumétrica está acotada (ancho de banda {uncert_cw:.1f} m).")
        if prec_core_phys < 0.5:
            print("     Sin embargo, el núcleo no es todavía suficientemente confiable si la precisión es baja.")

    uncert_bt = bt_y_max - bt_y_min
    if uncert_bt > BLOCK_SIZE * 2:
        print(f"  ⚠  El Best Target Y es inestable según el beta (ancho {uncert_bt:.1f} m).")
        print("     La heurística de targeting es vulnerable a la forma de la regularización.")
        print("     best_target_y sigue siendo un problema separado de ranking, no de recuperación volumétrica.")
    elif bt_y_min < cw_median[1] * 0.7:
        print(f"  ⚠  El Best Target Y es estable (ancho {uncert_bt:.1f} m), pero SISTEMÁTICAMENTE SESGADO somero.")
        print("     best_target_y sigue siendo un problema separado de ranking.")
    else:
        print(f"  ✅ El Best Target Y es consistente con la masa recuperada.")

    # Recomendación técnica: condicionada a los datos, no hardcoded
    print("\nRECOMENDACIÓN TÉCNICA:")

    bt_sesgado = bt_y_min < cw_median[1] * 0.7
    core_debil = prec_core_phys < 0.50 or recall_core_phys < 0.30

    if core_debil or bt_sesgado:
        print("  -> El sistema productivo debería mostrar MODELO RECOMENDADO + BANDA DE INCERTIDUMBRE,")
        print("     NO una solución única pura.")
        if core_debil:
            print(f"     Razón: Precisión del Core vs Physical={prec_core_phys:.1%}, Recall={recall_core_phys:.1%}.")
        if bt_sesgado:
            print("     Razón: El best_target_y está sistemáticamente sesgado respecto al centroide volumétrico.")
    elif n_shell > n_core * 2:
        print("  -> El Uncertain Shell es masivo frente al Core.")
        print("  -> El sistema productivo debería mostrar SOLUCIÓN PROBABILÍSTICA (Banda de Incertidumbre).")
    else:
        print("  -> El modelo es lo bastante compacto para presentar una solución determinista,")
        print("     informando al usuario un margen de error +/- en profundidad.")

    print(f"\n  Beta recomendado por profundidad : {best_beta_y_err['beta']:.2f}")
    print(f"  Beta recomendado por correlación : {best_beta_corr['beta']:.2f}")
    print(f"  Beta recomendado por IoU         : {best_beta_iou['beta']:.2f}")

    print("\nFin del experimento no productivo.\n")


if __name__ == "__main__":
    run_ensemble()
