"""
TerraQuantum Synthetic Copper Demo v1 — Diagnóstico Post-Inversión

Script de solo lectura que analiza el resultado del smoke test
para entender por qué se reportaron tantas anomalías y por qué
el best target puede haber quedado desplazado respecto al centro
sintético conocido.

No modifica datos ni código productivo.
No recalcula la inversión.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\demo\\analyze_tq_synthetic_copper_demo_v1_run.py
"""

import json
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

PROJECT_ID = "tq_synthetic_copper_demo_v1"
RUN_ID     = "smoke_demo_v1"

RUN_DIR          = os.path.join(BACKEND_ROOT, "data", "projects", PROJECT_ID, "runs", RUN_ID)
BLOCK_MODEL_PATH = os.path.join(RUN_DIR, "block_model.parquet")
# La ruta real de anomalías la resuelve el mismo helper que usa el backend.
ANOMALIES_PATH   = str(get_run_anomaly_reference(PROJECT_ID, RUN_ID).path)
REPORT_PATH      = os.path.join(RUN_DIR, "report.json")

# Centro real del cuerpo sintético (del generador)
TRUE_CENTER = (420.0, 230.0, 390.0)

# Umbrales usados en build_anomaly_dataframe (geophysics_service.py)
CUTOFF_DENSITY      = 2.75
CUTOFF_VISUAL_SCORE = 0.35
CUTOFF_GRADE        = 0.30


def separator(label: str = ""):
    width = 60
    if label:
        print(f"\n{'─' * 4} {label} {'─' * max(0, width - len(label) - 6)}")
    else:
        print("─" * width)


def print_percentiles(name: str, arr: np.ndarray):
    """Imprime min, p10, p25, p50, p75, p90, max de un array."""
    pcts = [0, 10, 25, 50, 75, 90, 100]
    vals = np.percentile(arr, pcts)
    line = "  ".join(f"p{p:>3d}={v:>8.4f}" for p, v in zip(pcts, vals))
    print(f"  {name:15s}: {line}")


def run_analysis():
    print("=" * 60)
    print("TerraQuantum — Diagnóstico Post-Inversión Demo v1")
    print("=" * 60)

    # ─── Verificar existencia de archivos ────────────────────────────────
    for label, path in [("block_model", BLOCK_MODEL_PATH), ("report", REPORT_PATH)]:
        if not os.path.exists(path):
            print(f"\n❌  {label} no encontrado: {path}")
            print("    Ejecuta primero el smoke test:")
            print("    python scripts\\demo\\run_tq_synthetic_copper_demo_v1_smoke.py")
            sys.exit(1)

    # ─── Cargar datos ────────────────────────────────────────────────────
    df = pl.read_parquet(BLOCK_MODEL_PATH)

    report = {}
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            report = json.load(f)

    total_voxels = len(df)

    # ===================================================================
    # 1. RESUMEN GENERAL
    # ===================================================================
    separator("1. RESUMEN GENERAL")
    print(f"  Total vóxeles en block_model: {total_voxels:,}")
    print(f"  Columnas: {df.columns}")

    # ===================================================================
    # 2. PERCENTILES DE VARIABLES CLAVE
    # ===================================================================
    separator("2. PERCENTILES")

    for col in ["density", "probability", "grade", "visual_score"]:
        if col in df.columns:
            arr = df[col].to_numpy().astype(np.float64)
            print_percentiles(col, arr)
        else:
            print(f"  {col:15s}: (columna no encontrada)")

    # ===================================================================
    # 3. CONTEOS POR CRITERIO DE ANOMALÍA
    # ===================================================================
    separator("3. CONTEOS POR CRITERIO DE ANOMÍA")

    density_arr = df["density"].to_numpy().astype(np.float64) if "density" in df.columns else np.array([])
    vs_arr = df["visual_score"].to_numpy().astype(np.float64) if "visual_score" in df.columns else np.array([])
    grade_arr = df["grade"].to_numpy().astype(np.float64) if "grade" in df.columns else np.array([])

    mask_density = density_arr >= CUTOFF_DENSITY
    mask_vs      = vs_arr >= CUTOFF_VISUAL_SCORE
    mask_grade   = grade_arr >= CUTOFF_GRADE

    # Máscara física actual (build_anomaly_dataframe tras Fase 1.7C.2)
    mask_physical = mask_density | mask_vs
    # Máscara legacy con grade (usada antes de Fase 1.7C.2 — referencia comparativa)
    mask_legacy_grade_inflated = mask_density | mask_vs | mask_grade

    n_density = int(np.sum(mask_density))
    n_vs      = int(np.sum(mask_vs))
    n_grade   = int(np.sum(mask_grade))
    n_physical = int(np.sum(mask_physical))
    n_legacy   = int(np.sum(mask_legacy_grade_inflated))

    def pct(n: int) -> str:
        return f"{100.0 * n / max(total_voxels, 1):.1f}%"

    print(f"  density >= {CUTOFF_DENSITY}              : {n_density:>6,}  ({pct(n_density)})")
    print(f"  visual_score >= {CUTOFF_VISUAL_SCORE}       : {n_vs:>6,}  ({pct(n_vs)})")
    print(f"  grade >= {CUTOFF_GRADE}  (interpretativo) : {n_grade:>6,}  ({pct(n_grade)})")
    print()
    print(f"  Máscara física ACTUAL (density|vs)   : {n_physical:>6,}  ({pct(n_physical)})")
    print(f"  Máscara LEGACY con grade (referencia): {n_legacy:>6,}  ({pct(n_legacy)})")
    print(f"  Vóxeles extra por grade (inflación)  : {n_legacy - n_physical:>6,}")
    print()

    # Desglose de solapamientos
    only_density = int(np.sum(mask_density & ~mask_vs & ~mask_grade))
    only_vs      = int(np.sum(mask_vs & ~mask_density & ~mask_grade))
    only_grade   = int(np.sum(mask_grade & ~mask_density & ~mask_vs))
    all_three    = int(np.sum(mask_density & mask_vs & mask_grade))

    print(f"  Solo density (físico)   : {only_density:>6,}")
    print(f"  Solo visual_score       : {only_vs:>6,}")
    print(f"  Solo grade (excluido)   : {only_grade:>6,}")
    print(f"  Los tres a la vez       : {all_three:>6,}")

    # ─── anomalies.parquet persistido ───────────────────────────────────
    print()
    print(f"  Ruta anomaly parquet : {ANOMALIES_PATH}")
    if os.path.exists(ANOMALIES_PATH):
        df_saved_anom = pl.read_parquet(ANOMALIES_PATH)
        n_saved_anom = len(df_saved_anom)
        print(f"  anomaly parquet persistido : {n_saved_anom:,} vóxeles")
        match_str = "✅ coincide" if n_saved_anom == n_physical else f"⚠  difiere (mask_physical={n_physical:,}; el parquet fue guardado con la máscara en vigor en ese momento)"
        print(f"  vs. mask_physical actual   : {match_str}")
    else:
        print(f"  anomaly parquet: no encontrado en {ANOMALIES_PATH}")

    # ===================================================================
    # 4. DISTRIBUCIÓN POR PROFUNDIDAD (iy)
    # ===================================================================
    separator("4. DISTRIBUCIÓN POR PROFUNDIDAD (iy)")

    if "iy" in df.columns:
        iy_arr = df["iy"].to_numpy().astype(int)
        iy_unique = sorted(set(iy_arr.tolist()))

        print(f"  {'iy':>4s}  {'total':>6s}  {'físico':>7s}  {'%':>6s}  {'legacy':>7s}  {'%leg':>6s}  {'avg_dens':>10s}")

        for iy_val in iy_unique:
            iy_mask = iy_arr == iy_val
            n_total_layer   = int(np.sum(iy_mask))
            n_phys_layer    = int(np.sum(iy_mask & mask_physical))
            n_legacy_layer  = int(np.sum(iy_mask & mask_legacy_grade_inflated))
            pct_phys   = 100.0 * n_phys_layer / max(n_total_layer, 1)
            pct_legacy = 100.0 * n_legacy_layer / max(n_total_layer, 1)
            avg_d = float(np.mean(density_arr[iy_mask])) if n_total_layer > 0 else 0.0
            print(f"  {iy_val:>4d}  {n_total_layer:>6d}  {n_phys_layer:>7d}  {pct_phys:>5.1f}%  {n_legacy_layer:>7d}  {pct_legacy:>5.1f}%  {avg_d:>10.4f}")

    # ===================================================================
    # 5. BEST TARGET RECONSTRUIDO VS CENTRO REAL
    # ===================================================================
    separator("5. BEST TARGET VS CENTRO SINTÉTICO")

    # report.json persiste report_payload pero NO best_target (se devuelve solo en memoria).
    # Lo reconstruimos localmente replicando el mismo ranking que build_best_target():
    #   score = probability * max(density - 2.6, 0) * max(grade, 0.01)
    # Se aplica solo sobre mask_physical (la máscara física actual del backend).

    prob_arr = df["probability"].to_numpy().astype(np.float64)

    ranking_score_anom = np.where(
        mask_physical,
        prob_arr * np.maximum(density_arr - 2.6, 0.0) * np.maximum(grade_arr, 0.01),
        -1.0,  # vóxeles fuera de la máscara física quedan excluidos
    )

    best_idx: int | None = None
    reconstructed_best_target: dict | None = None
    dist: float = float("nan")

    if int(np.sum(mask_physical)) > 0:
        best_idx = int(np.argmax(ranking_score_anom))
        best_row = df.row(best_idx, named=True)

        bx = float(best_row["x"])
        by = float(best_row["y"])
        bz = float(best_row["z"])

        dx_t = bx - TRUE_CENTER[0]
        dy_t = by - TRUE_CENTER[1]
        dz_t = bz - TRUE_CENTER[2]
        dist = math.sqrt(dx_t**2 + dy_t**2 + dz_t**2)

        reconstructed_best_target = {
            "x_m":        bx,
            "y_m":        by,
            "z_m":        bz,
            "density":    float(best_row["density"]),
            "grade":      float(best_row["grade"]),
            "probability":float(best_row["probability"]),
            "visual_score":float(best_row["visual_score"]),
            "score":      float(ranking_score_anom[best_idx]),
        }

        print(f"  Best target rec. (máscara física): ({bx:.1f}, {by:.1f}, {bz:.1f})")
        print(f"  Centro sintético                  : ({TRUE_CENTER[0]:.1f}, {TRUE_CENTER[1]:.1f}, {TRUE_CENTER[2]:.1f})")
        print(f"  Δx={dx_t:+.1f}  Δy={dy_t:+.1f}  Δz={dz_t:+.1f}")
        print(f"  Distancia euclídea: {dist:.1f} m")
        print(f"  Densidad          : {reconstructed_best_target['density']:.4f} t/m³")
        print(f"  Grade (informativo): {reconstructed_best_target['grade']:.4f}")
        print(f"  Probabilidad      : {reconstructed_best_target['probability']:.4f}")
        print(f"  Visual score      : {reconstructed_best_target['visual_score']:.4f}")
        print(f"  Score ranking     : {reconstructed_best_target['score']:.8f}")
    else:
        print("  ⚠  No hay vóxeles anómalos en máscara física: no se puede reconstruir el best target.")

    # ===================================================================
    # 6. TOP 10 VÓXELES POR DIFERENTES RANKINGS
    # ===================================================================
    separator("6. TOP 10 VÓXELES")

    # 6a. Ranking usado por build_best_target:
    #     probability * max(density - 2.6, 0) * max(grade, 0.01)
    print("\n  [A] Ranking build_best_target: prob * (dens-2.6) * max(grade,0.01)")

    ranking_score = (
        np.clip(df["probability"].to_numpy().astype(np.float64), 0, None)
        * np.maximum(density_arr - 2.6, 0.0)
        * np.maximum(grade_arr, 0.01)
    )
    top_idx_rank = np.argsort(ranking_score)[::-1][:10]

    print(f"  {'#':>2s}  {'ix':>3s} {'iy':>3s} {'iz':>3s}  {'x':>7s} {'y':>7s} {'z':>7s}  {'dens':>7s} {'grade':>7s} {'prob':>7s} {'vs':>7s}  {'score':>10s}")
    for rank, idx in enumerate(top_idx_rank, 1):
        row = df.row(int(idx), named=True)
        print(
            f"  {rank:>2d}  {row['ix']:>3d} {row['iy']:>3d} {row['iz']:>3d}"
            f"  {row['x']:>7.1f} {row['y']:>7.1f} {row['z']:>7.1f}"
            f"  {row['density']:>7.4f} {row['grade']:>7.4f} {row['probability']:>7.4f} {row['visual_score']:>7.4f}"
            f"  {ranking_score[idx]:>10.6f}"
        )

    # 6b. Top por density
    print("\n  [B] Top 10 por density")
    top_idx_dens = np.argsort(density_arr)[::-1][:10]
    print(f"  {'#':>2s}  {'ix':>3s} {'iy':>3s} {'iz':>3s}  {'x':>7s} {'y':>7s} {'z':>7s}  {'dens':>7s} {'grade':>7s} {'prob':>7s} {'vs':>7s}")
    for rank, idx in enumerate(top_idx_dens, 1):
        row = df.row(int(idx), named=True)
        print(
            f"  {rank:>2d}  {row['ix']:>3d} {row['iy']:>3d} {row['iz']:>3d}"
            f"  {row['x']:>7.1f} {row['y']:>7.1f} {row['z']:>7.1f}"
            f"  {row['density']:>7.4f} {row['grade']:>7.4f} {row['probability']:>7.4f} {row['visual_score']:>7.4f}"
        )

    # 6c. Top por visual_score
    print("\n  [C] Top 10 por visual_score")
    top_idx_vs = np.argsort(vs_arr)[::-1][:10]
    print(f"  {'#':>2s}  {'ix':>3s} {'iy':>3s} {'iz':>3s}  {'x':>7s} {'y':>7s} {'z':>7s}  {'dens':>7s} {'grade':>7s} {'prob':>7s} {'vs':>7s}")
    for rank, idx in enumerate(top_idx_vs, 1):
        row = df.row(int(idx), named=True)
        print(
            f"  {rank:>2d}  {row['ix']:>3d} {row['iy']:>3d} {row['iz']:>3d}"
            f"  {row['x']:>7.1f} {row['y']:>7.1f} {row['z']:>7.1f}"
            f"  {row['density']:>7.4f} {row['grade']:>7.4f} {row['probability']:>7.4f} {row['visual_score']:>7.4f}"
        )

    # ===================================================================
    # 7. DIAGNÓSTICO TEXTUAL
    # ===================================================================
    separator("7. DIAGNÓSTICO TEXTUAL PRELIMINAR")

    diag_lines = []

    # A) Máscara física actual vs legacy inflada por grade
    physical_ratio = 100.0 * n_physical / max(total_voxels, 1)
    legacy_ratio   = 100.0 * n_legacy   / max(total_voxels, 1)
    diag_lines.append(
        f"Máscara física actual (density|vs): {n_physical:,} vóxeles ({physical_ratio:.1f}%). "
        f"La máscara legacy con grade había marcado {n_legacy:,} vóxeles ({legacy_ratio:.1f}%)."
    )
    extra = n_legacy - n_physical
    if extra > 0:
        diag_lines.append(
            f"Separación correcta: {extra:,} vóxeles ya no son falsamente anómalos tras eliminar "
            f"grade del filtro físico (Fase 1.7C.2)."
        )

    if physical_ratio > 80:
        diag_lines.append(
            "⚠  La proporción de anomalías físicas sigue alta (>80%). "
            "Revisar cutoff_density o visual_score threshold."
        )
    elif physical_ratio < 5:
        diag_lines.append(
            "La máscara física es selectiva (<5%). útil para pit design."
        )

    # B) ¿Las anomalías físicas están concentradas en capas someras?
    if "iy" in df.columns:
        iy_arr_local = df["iy"].to_numpy().astype(int)
        shallow_mask = iy_arr_local <= 3  # primeras 4 capas (iy 0..3)
        n_shallow_phys = int(np.sum(shallow_mask & mask_physical))
        if n_physical > 0:
            shallow_pct = 100.0 * n_shallow_phys / n_physical
            diag_lines.append(
                f"Anomalías físicas someras (iy<=3): {n_shallow_phys:,} ({shallow_pct:.1f}% del total físico)."
            )
            if shallow_pct > 50:
                diag_lines.append(
                    "⚠  Más de la mitad de las anomalías físicas están en capas superficiales. "
                    "Puede indicar que la inversión no resolvió bien la profundidad."
                )

    # C) ¿El best target está lejos del centro sintético?
    if reconstructed_best_target is not None and math.isfinite(dist):
        if dist > 100:
            diag_lines.append(
                f"⚠  Best target reconstruido a {dist:.0f} m del centro sintético real. "
                "La inversión + heurística de ranking no ubicó el núcleo del cuerpo correctamente."
            )
        elif dist > 50:
            diag_lines.append(
                f"Best target reconstruido a {dist:.0f} m del centro sintético. Desplazamiento moderado."
            )
        else:
            diag_lines.append(
                f"✅  Best target reconstruido a solo {dist:.0f} m del centro sintético. Buena recuperación espacial."
            )
    else:
        diag_lines.append(
            "⚠  No se pudo reconstruir el best target: sin vóxeles anómalos disponibles."
        )

    # D) Estado del grade como campo interpretativo (referencia)
    if len(grade_arr) > 0:
        grade_min = float(np.min(grade_arr))
        diag_lines.append(
            f"Grade informativo (NO usado para selección física): min={grade_min:.4f}. "
            f"Con cutoff 0.30 habría marcado {n_grade:,} vóxeles ({100.0 * n_grade / max(total_voxels, 1):.1f}%)."
        )

    print()
    for i, line in enumerate(diag_lines, 1):
        print(f"  {i}. {line}")

    print()
    separator()
    print("Fin del diagnóstico. No se modificó ningún dato ni servicio.\n")


if __name__ == "__main__":
    run_analysis()
