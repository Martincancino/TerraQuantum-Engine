"""
TerraQuantum Synthetic Copper Demo v1 — Benchmark Volumétrico

Compara el modelo invertido del demo grande contra el ground truth
sintético real, evaluado sobre la MISMA grilla de inversión 32×20×32.

No modifica datos ni código productivo.
No recalcula la inversión.
No usa datos reales.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\demo\\benchmark_tq_synthetic_copper_demo_v1_recovery.py
"""

import math
import os
import sys

import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Ruta del backend
# ---------------------------------------------------------------------------
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from core.block_model_store import get_run_anomaly_reference

# ---------------------------------------------------------------------------
# Constantes del modelo
# ---------------------------------------------------------------------------
PROJECT_ID = "tq_synthetic_copper_demo_v1"
RUN_ID     = "smoke_demo_v1"

RUN_DIR          = os.path.join(BACKEND_ROOT, "data", "projects", PROJECT_ID, "runs", RUN_ID)
BLOCK_MODEL_PATH = os.path.join(RUN_DIR, "block_model.parquet")

# Parámetros de la grilla de inversión
NX, NY, NZ = 32, 20, 32
BLOCK_SIZE  = 25  # m
TOTAL_VOXELS = NX * NY * NZ

# Ground truth sintético (parámetros del generador)
CX, CY, CZ = 420.0, 230.0, 390.0
RX, RY, RZ = 180.0, 140.0, 170.0
MAX_CONTRAST = 0.55  # t/m³
DENSITY_CUTOFF_CONTRAST = 0.05  # t/m³
BASE_DENSITY = 2.6

# Umbrales físicos (post Fase 1.7C.2)
CUTOFF_DENSITY      = 2.75
CUTOFF_VISUAL_SCORE = 0.35


def separator(label: str = ""):
    width = 70
    if label:
        print(f"\n{'─' * 4} {label} {'─' * max(0, width - len(label) - 6)}")
    else:
        print("─" * width)


def build_true_contrast_on_inversion_grid() -> np.ndarray:
    """Evalúa el ground truth analítico sobre la grilla 32×20×32 con orden F."""
    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)

    x_c = (ix * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
    y_c = (iy * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
    z_c = (iz * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

    r2_norm = (
        ((x_c - CX) / RX) ** 2
        + ((y_c - CY) / RY) ** 2
        + ((z_c - CZ) / RZ) ** 2
    )
    contrast = MAX_CONTRAST * np.exp(-r2_norm)
    contrast[contrast < DENSITY_CUTOFF_CONTRAST] = 0.0

    return contrast, x_c, y_c, z_c, ix, iy, iz


def centroid_geometric(x: np.ndarray, y: np.ndarray, z: np.ndarray, mask: np.ndarray):
    """Centroide geométrico de los vóxeles en mask."""
    n = int(np.sum(mask))
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    return (
        float(np.mean(x[mask])),
        float(np.mean(y[mask])),
        float(np.mean(z[mask])),
    )


def centroid_weighted(x: np.ndarray, y: np.ndarray, z: np.ndarray, w: np.ndarray):
    """Centroide ponderado por w (solo donde w > 0)."""
    mask = w > 0
    total_w = float(np.sum(w[mask]))
    if total_w < 1e-15:
        return float("nan"), float("nan"), float("nan")
    return (
        float(np.sum(x[mask] * w[mask]) / total_w),
        float(np.sum(y[mask] * w[mask]) / total_w),
        float(np.sum(z[mask] * w[mask]) / total_w),
    )


def euclidean(a: tuple, b: tuple) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def run_benchmark():
    print("=" * 70)
    print("TerraQuantum — Benchmark Volumétrico Demo Copper v1")
    print("=" * 70)

    # ─── Verificar archivos ──────────────────────────────────────────────
    if not os.path.exists(BLOCK_MODEL_PATH):
        print(f"\n❌  block_model.parquet no encontrado: {BLOCK_MODEL_PATH}")
        print("    Ejecuta primero el smoke test.")
        sys.exit(1)

    # ===================================================================
    # 1. GROUND TRUTH SOBRE GRILLA DE INVERSIÓN
    # ===================================================================
    separator("1. GROUND TRUTH ANALÍTICO (grilla 32×20×32)")

    contrast_true, x_c, y_c, z_c, ix_arr, iy_arr, iz_arr = build_true_contrast_on_inversion_grid()
    density_true = BASE_DENSITY + contrast_true
    mask_true_active = contrast_true > 0
    n_true_active = int(np.sum(mask_true_active))

    print(f"  Total vóxeles       : {TOTAL_VOXELS:,}")
    print(f"  Vóxeles verdaderos  : {n_true_active:,} ({100.0 * n_true_active / TOTAL_VOXELS:.1f}%)")
    print(f"  Contraste verdadero : min={float(np.min(contrast_true)):.4f}  max={float(np.max(contrast_true)):.4f}")
    print(f"  Densidad verdadera  : min={float(np.min(density_true)):.4f}  max={float(np.max(density_true)):.4f}")

    # ===================================================================
    # 2. MODELO RECUPERADO
    # ===================================================================
    separator("2. MODELO RECUPERADO (block_model.parquet)")

    df = pl.read_parquet(BLOCK_MODEL_PATH)
    n_loaded = len(df)

    if n_loaded != TOTAL_VOXELS:
        print(f"  ⚠  block_model tiene {n_loaded:,} vóxeles, se esperaban {TOTAL_VOXELS:,}")

    density_rec = df["density"].to_numpy().astype(np.float64)
    contrast_rec = density_rec - BASE_DENSITY
    vs_arr = df["visual_score"].to_numpy().astype(np.float64) if "visual_score" in df.columns else np.zeros(n_loaded)

    mask_rec_physical = (density_rec >= CUTOFF_DENSITY) | (vs_arr >= CUTOFF_VISUAL_SCORE)
    n_rec_physical = int(np.sum(mask_rec_physical))

    print(f"  Vóxeles cargados         : {n_loaded:,}")
    print(f"  Anomalías físicas rec.   : {n_rec_physical:,} ({100.0 * n_rec_physical / max(n_loaded, 1):.1f}%)")
    print(f"  Contraste recuperado     : min={float(np.min(contrast_rec)):.4f}  max={float(np.max(contrast_rec)):.4f}")
    print(f"  Densidad recuperada      : min={float(np.min(density_rec)):.4f}  max={float(np.max(density_rec)):.4f}")

    # ===================================================================
    # 3. MÉTRICAS GLOBALES
    # ===================================================================
    separator("3. MÉTRICAS GLOBALES")

    # Usar solo los primeros TOTAL_VOXELS para la comparación
    n_compare = min(n_loaded, TOTAL_VOXELS)
    ct = contrast_true[:n_compare]
    cr = contrast_rec[:n_compare]

    corr = float(np.corrcoef(ct, cr)[0, 1]) if np.std(ct) > 0 and np.std(cr) > 0 else 0.0
    rmse = float(np.sqrt(np.mean((ct - cr) ** 2)))
    mae  = float(np.mean(np.abs(ct - cr)))
    max_err = float(np.max(np.abs(ct - cr)))

    print(f"  Pearson correlation   : {corr:.6f}")
    print(f"  RMSE contraste        : {rmse:.6f} t/m³")
    print(f"  MAE contraste         : {mae:.6f} t/m³")
    print(f"  Max |error| contraste : {max_err:.6f} t/m³")

    # ===================================================================
    # 4. CENTROIDES
    # ===================================================================
    separator("4. CENTROIDES")

    x_rec = df["x"].to_numpy().astype(np.float64)[:n_compare]
    y_rec = df["y"].to_numpy().astype(np.float64)[:n_compare]
    z_rec = df["z"].to_numpy().astype(np.float64)[:n_compare]

    # A. Centroide geométrico verdadero
    cg_true = centroid_geometric(x_c[:n_compare], y_c[:n_compare], z_c[:n_compare], mask_true_active[:n_compare])
    # B. Centroide ponderado verdadero
    cw_true = centroid_weighted(x_c[:n_compare], y_c[:n_compare], z_c[:n_compare], ct)
    # C. Centroide geométrico recuperado (máscara física)
    cg_rec = centroid_geometric(x_rec, y_rec, z_rec, mask_rec_physical[:n_compare])
    # D. Centroide ponderado recuperado (por contraste positivo)
    cr_positive = np.maximum(cr, 0.0)
    cw_rec = centroid_weighted(x_rec, y_rec, z_rec, cr_positive)

    labels = [
        ("A. Geom. verdadero", cg_true),
        ("B. Pond. verdadero", cw_true),
        ("C. Geom. recuperado", cg_rec),
        ("D. Pond. recuperado", cw_rec),
    ]
    print(f"  {'Centroide':<25s}  {'x':>8s}  {'y(prof)':>8s}  {'z':>8s}")
    for label, c in labels:
        if math.isfinite(c[0]):
            print(f"  {label:<25s}  {c[0]:>8.1f}  {c[1]:>8.1f}  {c[2]:>8.1f}")
        else:
            print(f"  {label:<25s}  (sin datos)")

    # ===================================================================
    # 5. ERRORES DE CENTROIDE
    # ===================================================================
    separator("5. ERRORES DE CENTROIDE")

    for name, c_true, c_rec in [
        ("Geométrico", cg_true, cg_rec),
        ("Ponderado", cw_true, cw_rec),
    ]:
        if math.isfinite(c_true[0]) and math.isfinite(c_rec[0]):
            d = euclidean(c_true, c_rec)
            dy_err = c_rec[1] - c_true[1]
            print(f"  {name}:")
            print(f"    Δx={c_rec[0] - c_true[0]:+.1f}  Δy={dy_err:+.1f}  Δz={c_rec[2] - c_true[2]:+.1f}")
            print(f"    Distancia euclídea : {d:.1f} m")
            print(f"    Error profundidad y: {dy_err:+.1f} m ({'somero' if dy_err < 0 else 'profundo'})")
        else:
            print(f"  {name}: sin datos suficientes")

    # ===================================================================
    # 6. SOLAPAMIENTO VOLUMÉTRICO
    # ===================================================================
    separator("6. SOLAPAMIENTO VOLUMÉTRICO")

    mt = mask_true_active[:n_compare]
    mr = mask_rec_physical[:n_compare]

    intersection = int(np.sum(mt & mr))
    union_count  = int(np.sum(mt | mr))
    iou = intersection / max(union_count, 1)
    recall    = intersection / max(int(np.sum(mt)), 1)
    precision = intersection / max(int(np.sum(mr)), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-15)

    print(f"  Verdaderos activos     : {int(np.sum(mt)):,}")
    print(f"  Recuperados físicos    : {int(np.sum(mr)):,}")
    print(f"  Intersección           : {intersection:,}")
    print(f"  Unión                  : {union_count:,}")
    print(f"  IoU                    : {iou:.4f}")
    print(f"  Recall (sensibilidad)  : {recall:.4f}")
    print(f"  Precision              : {precision:.4f}")
    print(f"  F1                     : {f1:.4f}")

    # Top-k overlap
    print()
    k_pct = 0.05
    k_n = max(1, int(k_pct * n_compare))
    top_true_idx = set(np.argsort(ct)[::-1][:k_n].tolist())
    top_rec_idx  = set(np.argsort(cr)[::-1][:k_n].tolist())
    top_overlap = len(top_true_idx & top_rec_idx) / k_n
    print(f"  Top {k_pct*100:.0f}% overlap     : {top_overlap:.4f} ({len(top_true_idx & top_rec_idx)} / {k_n})")

    k_body = max(1, n_true_active)
    top_true_body = set(np.argsort(ct)[::-1][:k_body].tolist())
    top_rec_body  = set(np.argsort(cr)[::-1][:k_body].tolist())
    body_overlap = len(top_true_body & top_rec_body) / k_body
    print(f"  Top-N={k_body} body overlap: {body_overlap:.4f} ({len(top_true_body & top_rec_body)} / {k_body})")

    # ===================================================================
    # 7. PERFIL VERTICAL POR iy
    # ===================================================================
    separator("7. PERFIL VERTICAL POR CAPA iy")

    iy_true = iy_arr[:n_compare]
    iy_rec  = df["iy"].to_numpy().astype(int)[:n_compare] if "iy" in df.columns else iy_true

    iy_unique = sorted(set(iy_true.tolist()))

    print(f"  {'iy':>4s}  {'true_act':>9s}  {'rec_act':>9s}  {'true_mc':>9s}  {'rec_mc+':>9s}  {'true_mass':>10s}  {'rec_mass':>10s}")

    mass_true_by_iy = {}
    mass_rec_by_iy = {}

    for iy_val in iy_unique:
        m_iy = iy_true == iy_val
        ta = int(np.sum(m_iy & mt))
        ra = int(np.sum(m_iy & mr))
        true_mc = float(np.mean(ct[m_iy & mt])) if ta > 0 else 0.0
        rec_pos = np.maximum(cr[m_iy], 0.0)
        rec_mc = float(np.mean(rec_pos[rec_pos > 0])) if np.sum(rec_pos > 0) > 0 else 0.0
        true_mass = float(np.sum(ct[m_iy]))
        rec_mass = float(np.sum(rec_pos))
        mass_true_by_iy[iy_val] = true_mass
        mass_rec_by_iy[iy_val] = rec_mass
        print(f"  {iy_val:>4d}  {ta:>9d}  {ra:>9d}  {true_mc:>9.4f}  {rec_mc:>9.4f}  {true_mass:>10.3f}  {rec_mass:>10.3f}")

    # ===================================================================
    # 8. DISTRIBUCIÓN DE MASA POR PROFUNDIDAD
    # ===================================================================
    separator("8. DISTRIBUCIÓN DE MASA")

    total_true_mass = sum(mass_true_by_iy.values())
    total_rec_mass  = sum(mass_rec_by_iy.values())

    shallow_true = sum(v for k, v in mass_true_by_iy.items() if k <= 3)
    shallow_rec  = sum(v for k, v in mass_rec_by_iy.items() if k <= 3)

    pct_shallow_true = 100.0 * shallow_true / max(total_true_mass, 1e-15)
    pct_shallow_rec  = 100.0 * shallow_rec  / max(total_rec_mass, 1e-15)

    print(f"  Masa total verdadera     : {total_true_mass:.3f}")
    print(f"  Masa total recuperada (+): {total_rec_mass:.3f}")
    print(f"  Masa verdadera iy<=3     : {shallow_true:.3f} ({pct_shallow_true:.1f}%)")
    print(f"  Masa recuperada iy<=3    : {shallow_rec:.3f} ({pct_shallow_rec:.1f}%)")
    print(f"  Sesgo somero de masa     : {pct_shallow_rec - pct_shallow_true:+.1f} pp")

    # ===================================================================
    # 9. BEST TARGET (REFERENCIA PUNTUAL)
    # ===================================================================
    separator("9. BEST TARGET (referencia puntual, no volumétrica)")

    grade_arr = df["grade"].to_numpy().astype(np.float64)[:n_compare] if "grade" in df.columns else np.ones(n_compare) * 0.01
    prob_arr = df["probability"].to_numpy().astype(np.float64)[:n_compare] if "probability" in df.columns else np.zeros(n_compare)

    ranking_score = np.where(
        mr,
        prob_arr * np.maximum(density_rec[:n_compare] - 2.6, 0.0) * np.maximum(grade_arr, 0.01),
        -1.0,
    )

    if int(np.sum(mr)) > 0:
        best_idx = int(np.argmax(ranking_score))
        best_row = df.row(best_idx, named=True)
        bx, by, bz = float(best_row["x"]), float(best_row["y"]), float(best_row["z"])
        dist_bt = euclidean((bx, by, bz), (CX, CY, CZ))
        print(f"  Best target  : ({bx:.1f}, {by:.1f}, {bz:.1f})")
        print(f"  Centro real  : ({CX:.1f}, {CY:.1f}, {CZ:.1f})")
        print(f"  Distancia    : {dist_bt:.1f} m")
        print(f"  Densidad     : {float(best_row['density']):.4f}")
        print(f"  Probabilidad : {float(best_row['probability']):.4f}")
        print(f"  ⚠  Esta es una métrica puntual; ver centroides y IoU para evaluación volumétrica.")
    else:
        print("  Sin anomalías físicas.")

    # ===================================================================
    # 10. DIAGNÓSTICO TEXTUAL
    # ===================================================================
    separator("10. DIAGNÓSTICO FINAL")

    diag = []

    # Correlación
    if corr > 0.7:
        diag.append(f"✅  Correlación global buena ({corr:.4f}). El patrón general del contraste fue recuperado.")
    elif corr > 0.4:
        diag.append(f"⚠  Correlación moderada ({corr:.4f}). Recuperación parcial del patrón.")
    else:
        diag.append(f"❌  Correlación baja ({corr:.4f}). El patrón no fue adecuadamente recuperado.")

    # IoU
    if iou > 0.5:
        diag.append(f"✅  IoU buena ({iou:.4f}). Buen solapamiento entre cuerpo verdadero y recuperado.")
    elif iou > 0.2:
        diag.append(f"⚠  IoU moderada ({iou:.4f}). Solapamiento parcial.")
    else:
        diag.append(f"❌  IoU baja ({iou:.4f}). El cuerpo recuperado no coincide bien con el verdadero.")

    # Sesgo en profundidad
    mass_bias = pct_shallow_rec - pct_shallow_true
    if abs(mass_bias) < 5:
        diag.append(f"✅  Distribución vertical de masa consistente (sesgo somero: {mass_bias:+.1f} pp).")
    elif mass_bias > 0:
        diag.append(
            f"⚠  Sesgo somero detectado: masa recuperada {mass_bias:+.1f} pp más superficial que la verdadera. "
            f"Esto es un efecto esperado en inversión gravimétrica sin depth weighting."
        )
    else:
        diag.append(f"⚠  Sesgo profundo detectado: {mass_bias:+.1f} pp (inusual).")

    # Error de centroide ponderado en profundidad
    if math.isfinite(cw_true[1]) and math.isfinite(cw_rec[1]):
        dy_err_w = cw_rec[1] - cw_true[1]
        if abs(dy_err_w) < 25:
            diag.append(f"✅  Error de profundidad del centroide ponderado: {dy_err_w:+.1f} m (< 1 bloque).")
        elif abs(dy_err_w) < 75:
            diag.append(f"⚠  Error de profundidad del centroide ponderado: {dy_err_w:+.1f} m (2–3 bloques).")
        else:
            diag.append(
                f"❌  Error de profundidad del centroide ponderado: {dy_err_w:+.1f} m ({abs(dy_err_w)/BLOCK_SIZE:.0f} bloques). "
                f"El volumen recuperado está significativamente desplazado en y."
            )

    # Conclusión global
    diag.append("")
    if corr > 0.5 and iou > 0.3 and abs(mass_bias) < 15:
        diag.append("CONCLUSIÓN: Recuperación volumétrica aceptable. Sesgo somero dentro de lo esperado para LSQR sin depth weighting.")
    elif corr > 0.3:
        diag.append("CONCLUSIÓN: Recuperación parcial. Se recomienda depth weighting para mejorar la resolución vertical.")
    else:
        diag.append("CONCLUSIÓN: Recuperación insuficiente. Revisar parámetros de inversión antes de usar para targeting.")

    print()
    for i, line in enumerate(diag, 1):
        if line:
            print(f"  {i}. {line}")
        else:
            print()

    print()
    separator()
    print("Fin del benchmark. No se modificó ningún dato ni servicio.\n")


if __name__ == "__main__":
    run_benchmark()
