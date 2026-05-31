"""
TerraQuantum Synthetic Copper Demo v1 — Barrido de cutoff_radius

Ejecuta un experimento no productivo variando el cutoff_radius del kernel
gravimétrico para medir cuánto del sesgo somero se debe a truncamiento
espacial.

Evalúa:
    - cutoff_radius = 300.0 (baseline)
    - cutoff_radius = 450.0
    - cutoff_radius = 600.0

No modifica servicios productivos ni schemas.
No usa datos reales.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\demo\\run_tq_synthetic_copper_demo_v1_cutoff_sweep.py
"""

import math
import os
import sys
import time

import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Configuración del entorno
# ---------------------------------------------------------------------------
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from services.gravity_import_service import import_gravity_csv_v1
from services.geophysics_service import run_geophysics_inversion
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from core.block_model_store import get_run_block_model_reference

# Funciones reutilizadas del benchmark volumétrico
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

# ---------------------------------------------------------------------------
# Constantes del Sweep
# ---------------------------------------------------------------------------
PROJECT_ID  = "tq_synthetic_copper_demo_v1_cutoff_sweep"
CSV_RELPATH = os.path.join("scripts", "demo_data", "tq_synthetic_copper_demo_v1_bouguer_mgal.csv")

CUTOFFS_TO_TEST = [300.0, 450.0, 600.0]

# Ground Truth analítico calculado una vez
contrast_true, x_c, y_c, z_c, ix_arr, iy_arr, iz_arr = build_true_contrast_on_inversion_grid()
mask_true_active = contrast_true > 0
cw_true = centroid_weighted(x_c, y_c, z_c, contrast_true)


def count_kernel_support_nnz(x_vox, y_vox, z_vox, sensor_coords, cutoff_radius) -> int:
    """
    Cuenta el número de elementos no nulos (NNZ) del kernel CSR
    sin construir la matriz en memoria, simulando el mismo filtro geométrico.
    """
    nnz_total = 0
    cutoff_sq = cutoff_radius**2

    for sx, sy, sz in sensor_coords:
        dx_vec = x_vox - sx
        dy_vec = y_vox - sy
        dz_vec = z_vox - sz
        
        r_squared = dx_vec**2 + dy_vec**2 + dz_vec**2
        mask = (r_squared <= cutoff_sq) & (r_squared > 0)
        nnz_total += int(np.count_nonzero(mask))

    return nnz_total


def run_sweep():
    print("=" * 80)
    print("TerraQuantum — Barrido de cutoff_radius (Profundidad de Recuperación)")
    print("=" * 80)

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
    print(f"    {len(observations)} observaciones cargadas.\n")

    results = []

    for cutoff in CUTOFFS_TO_TEST:
        run_id = f"cutoff_{int(cutoff)}"
        print("-" * 60)
        print(f"🚀  Ejecutando caso: {run_id} (cutoff_radius = {cutoff} m)")
        
        # 1. Medir métricas del kernel manualmente para el reporte (sin crear matriz completa)
        nnz = count_kernel_support_nnz(x_c, y_c, z_c, sensor_coords, cutoff)
        fill_rate = nnz / (len(sensor_coords) * TOTAL_VOXELS)
        print(f"    Kernel NNZ: {nnz:,} | Fill rate: {fill_rate:.2%}")

        # 2. Configurar input
        input_params = GeophysicsInvertInput(
            project_id=PROJECT_ID,
            run_id=run_id,
            depth=250,
            nir=83,
            fe=79,
            region="norte_chile",
            lat="-23.5",
            lon="-69.0",
            nx=NX,
            ny=NY,
            nz=NZ,
            block_size=BLOCK_SIZE,
            cutoff_radius=cutoff,
            lambda_mag=0.00005,
            alpha_spatial=1.0,
            observations=observations,
        )

        # 3. Ejecutar inversión
        t0 = time.perf_counter()
        inv_result = run_geophysics_inversion(input_params)
        t_inv = time.perf_counter() - t0
        print(f"    Inversión completada en {t_inv:.1f} s")

        # 4. Calcular métricas volumétricas
        bm_path = str(get_run_block_model_reference(PROJECT_ID, run_id).path)
        df_bm = pl.read_parquet(bm_path)

        density_rec = df_bm["density"].to_numpy().astype(np.float64)[:TOTAL_VOXELS]
        vs_arr = df_bm["visual_score"].to_numpy().astype(np.float64)[:TOTAL_VOXELS] if "visual_score" in df_bm.columns else np.zeros(TOTAL_VOXELS)
        contrast_rec = density_rec - BASE_DENSITY

        mask_rec_physical = (density_rec >= CUTOFF_DENSITY) | (vs_arr >= CUTOFF_VISUAL_SCORE)
        n_rec_physical = int(np.sum(mask_rec_physical))

        # Correlación
        ct = contrast_true
        cr = contrast_rec
        corr = float(np.corrcoef(ct, cr)[0, 1]) if np.std(ct) > 0 and np.std(cr) > 0 else 0.0

        # Solapamiento volumétrico
        mt = mask_true_active
        mr = mask_rec_physical
        intersection = int(np.sum(mt & mr))
        union_count  = int(np.sum(mt | mr))
        iou = intersection / max(union_count, 1)
        recall    = intersection / max(int(np.sum(mt)), 1)
        precision = intersection / max(int(np.sum(mr)), 1)

        # Centroide ponderado recuperado y error Y
        cr_positive = np.maximum(cr, 0.0)
        cw_rec = centroid_weighted(x_c, y_c, z_c, cr_positive)
        y_error_m = cw_rec[1] - cw_true[1] if math.isfinite(cw_rec[1]) and math.isfinite(cw_true[1]) else float("nan")

        # % Masa somera
        iy_bm = df_bm["iy"].to_numpy().astype(int)[:TOTAL_VOXELS] if "iy" in df_bm.columns else iy_arr
        shallow_mask = iy_bm <= 3
        shallow_rec_mass = float(np.sum(cr_positive[shallow_mask]))
        total_rec_mass = float(np.sum(cr_positive))
        shallow_mass_pct = 100.0 * shallow_rec_mass / max(total_rec_mass, 1e-15)

        # Best target
        bt = inv_result.get("best_target")
        bt_y = float(bt.get("y_m", float("nan"))) if bt else float("nan")

        results.append({
            "cutoff": cutoff,
            "nnz": nnz,
            "fill_rate": fill_rate,
            "time_s": t_inv,
            "anom": n_rec_physical,
            "corr": corr,
            "iou": iou,
            "recall": recall,
            "precision": precision,
            "cw_y": cw_rec[1],
            "y_err": y_error_m,
            "sh_mass_pct": shallow_mass_pct,
            "bt_y": bt_y,
        })

    # ===================================================================
    # RESULTADOS FINALES Y DIAGNÓSTICO
    # ===================================================================
    print("\n" + "=" * 125)
    print(f"{'cutoff':>6} | {'NNZ':>9} | {'Fill%':>5} | {'Time(s)':>7} | {'Anom':>5} | {'Corr':>6} | {'IoU':>6} | {'Recall':>6} | {'Prec':>6} | {'cw_y(m)':>7} | {'y_err(m)':>8} | {'sh_mass%':>8} | {'bt_y(m)':>7}")
    print("-" * 125)
    for r in results:
        print(
            f"{r['cutoff']:>6.0f} | "
            f"{r['nnz']:>9,} | "
            f"{r['fill_rate']*100:>4.1f}% | "
            f"{r['time_s']:>7.1f} | "
            f"{r['anom']:>5d} | "
            f"{r['corr']:>6.4f} | "
            f"{r['iou']:>6.4f} | "
            f"{r['recall']:>6.4f} | "
            f"{r['precision']:>6.4f} | "
            f"{r['cw_y']:>7.1f} | "
            f"{r['y_err']:>+8.1f} | "
            f"{r['sh_mass_pct']:>7.1f}% | "
            f"{r['bt_y']:>7.1f}"
        )
    print("=" * 125)

    print("\nDIAGNÓSTICO AUTOMÁTICO:")
    
    # Análisis de la progresión del error de profundidad
    err_300 = next(r["y_err"] for r in results if r["cutoff"] == 300.0)
    err_600 = next(r["y_err"] for r in results if r["cutoff"] == 600.0)
    
    mejora_profundidad = abs(err_300) - abs(err_600)
    
    if mejora_profundidad > 25:
        print(f"  ✅ Ampliar el cutoff a 600 m mejoró el error de profundidad significativamente (reducción de {mejora_profundidad:.1f} m).")
        print(f"     El cutoff_radius=300 estaba truncando físicamente la señal gravitatoria profunda.")
    else:
        print(f"  ⚠  Ampliar el cutoff a 600 m NO solucionó el sesgo somero (mejora de solo {mejora_profundidad:.1f} m).")
        print(f"     Aún con alcance holgado, el error en profundidad persiste en {err_600:+.1f} m.")
        print("     CONCLUSIÓN: El problema no es truncamiento de alcance, sino la caída natural 1/r^2.")
        print("     Siguiente paso requerido: Implementar depth weighting en la matriz G o en la regularización.")

    print("\nFin del experimento.\n")


if __name__ == "__main__":
    run_sweep()
