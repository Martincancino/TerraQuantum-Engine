"""
TANDA A — PARTE 0: clavar el número OFF-ANCHOR del sintético de ambigüedad-z.
=============================================================================

El reporte synthetic_depth_ambiguity_report.json mostró que la config C ("+1 ancla
dura") "cura" la profundidad: z-error 2675 m → 75 m, prof recuperada 325 m → 2925 m.
PERO n_strong=3 = n_anchored=3: el "estimate_location_error" sólo cuenta como cuerpo a
las 3 celdas ancladas (su contraste 0.5 domina; el resto cae bajo el umbral 0.5·máx).
La "cura" podría ser TAUTOLÓGICA: el ancla SÓLO empuja densidad en sus 3 celdas y la
gravedad NO construyó nada profundo a su alrededor.

Pre-registro (escrito ANTES de correr):
    El centroide de profundidad EXCLUYENDO las 3 celdas ancladas sigue apilado SOMERO
    (~325 m, igual que A/B), confirmando que la gravedad no construyó profundidad: la
    "cura" de la config C la aportan exclusivamente las celdas ancladas.

El modelo NO está guardado en el reporte → se re-corre SÓLO la config C (compacto, malla
capada ny=8, ancla dura) con MISMA semilla/datos/ruido, se vuelca el modelo y se mide el
centroide off-anchor. Backend-only, no toca nada del motor ni defaults.

USO:
  cd terraquantum-backend
  python scripts/validation/tanda_a_part0_offanchor.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.validation.synthetic_depth_ambiguity import (  # noqa: E402
    BASE_DENSITY,
    BLOCK,
    BODY_DEPTH,
    BODY_RADIUS,
    BODY_X,
    BODY_Z,
    DELTA_RHO,
    NX,
    NY_CAP,
    NZ,
    build_anchor,
    build_survey,
    invert,
)
from scripts.validation.do27_harness import _grid_centers_fortran  # noqa: E402
from services.field_validation_service import estimate_location_error  # noqa: E402

SEED = 20260628  # idéntico a synthetic_depth_ambiguity.SEED


def _weighted_depth_centroid(contrast, y_c, mask, strong_fraction=0.5):
    """Centroide de profundidad ponderado por contraste, sobre `mask`, usando el mismo
    criterio de `estimate_location_error` (celdas > strong_fraction·máx dentro de mask)."""
    c = np.where(mask, contrast, 0.0)
    finite = np.isfinite(c) & mask
    if not np.any(finite) or np.nanmax(c[finite]) <= 0:
        return None, 0, None
    cmax = float(np.nanmax(c[finite]))
    strong = finite & (c > strong_fraction * cmax)
    if not np.any(strong):
        strong = finite & (c > 0)
    w = c[strong]
    yr = float(np.average(y_c[strong], weights=w))
    return round(yr, 1), int(np.count_nonzero(strong)), round(cmax, 4)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    t0 = time.time()
    rng = np.random.default_rng(SEED)
    sensors, g_obs, sigma_g = build_survey(rng)
    anchor = build_anchor()

    print("=" * 80)
    print("TANDA A — PARTE 0: centroide OFF-ANCHOR de la config C del sintético")
    print("=" * 80)
    print("\n[C] Re-corriendo config C (compacto · malla capada ny=8 · ancla dura)...")
    rho_c, mf_c, (x_c, y_c, z_c), meta_c = invert(
        sensors, g_obs, sigma_g, ny=NY_CAP, regularization_norm="compact",
        boreholes=anchor, anchor_mode="hard",
    )
    rho_c = np.asarray(rho_c, dtype=np.float64)
    contrast = np.abs(rho_c - BASE_DENSITY)

    # ── Identificar las celdas ancladas: columna más cercana a (BODY_X, BODY_Z),
    #    profundidad dentro del intervalo del sondaje [y_top, y_bot]. ───────────
    y_top = BODY_DEPTH - BODY_RADIUS   # 2200 m
    y_bot = BODY_DEPTH + BODY_RADIUS   # 3800 m
    # tolerancia de media celda para "misma columna"
    same_col = (np.abs(x_c - BODY_X) <= 0.5 * BLOCK) & (np.abs(z_c - BODY_Z) <= 0.5 * BLOCK)
    in_interval = (y_c >= y_top - 1e-6) & (y_c <= y_bot + 1e-6)
    anchored = same_col & in_interval
    n_anchored = int(np.count_nonzero(anchored))
    off = ~anchored

    # Densidad de las celdas ancladas (deberían ≈ 3.17, la verdad inyectada).
    anchored_rho = sorted(round(float(v), 3) for v in rho_c[anchored])
    anchored_depths = sorted(round(float(v), 1) for v in y_c[anchored])

    # ── Centroide de profundidad CON ancla (réplica del reporte) ───────────────
    loc_all = estimate_location_error(
        rho_c, x_c, y_c, z_c, (BODY_X, BODY_DEPTH, BODY_Z), base_density=BASE_DENSITY,
    )
    # ── Centroide de profundidad EXCLUYENDO las celdas ancladas ────────────────
    off_depth, off_nstrong, off_cmax = _weighted_depth_centroid(contrast, y_c, off)

    # Pico off-anchor (celda de máximo contraste fuera del ancla) para contexto.
    off_contrast = np.where(off, contrast, -np.inf)
    ip = int(np.argmax(off_contrast))
    peak_off_depth = round(float(y_c[ip]), 1)
    peak_off_contrast = round(float(contrast[ip]), 4)

    shallow_threshold = 1.5 * BLOCK   # ~975 m: "somero" = primeras ~1.5 celdas
    off_is_shallow = off_depth is not None and off_depth <= shallow_threshold

    report = {
        "case": "PARTE 0 — centroide off-anchor (config C del sintético ambigüedad-z)",
        "prereg": (
            "El centroide de profundidad EXCLUYENDO las 3 celdas ancladas sigue SOMERO "
            f"(~325 m, ≤ {shallow_threshold:.0f} m). Si se confirma, la 'cura' de la "
            "config C es tautológica: sólo las celdas ancladas tienen densidad profunda."
        ),
        "ground_truth": {
            "centroid_depth_m": BODY_DEPTH, "radius_m": BODY_RADIUS,
            "anchor_interval_m": [y_top, y_bot],
            "true_density_t_m3": round(BASE_DENSITY + DELTA_RHO, 3),
        },
        "config_C": {
            "misfit_percent": round(float(mf_c), 3),
            "n_anchored_cells": n_anchored,
            "n_anchored_voxels_meta": meta_c.get("n_anchored_voxels"),
            "anchored_cell_depths_m": anchored_depths,
            "anchored_cell_density_t_m3": anchored_rho,
        },
        "with_anchor_centroid": {
            "recovered_depth_m": loc_all.get("recovered_y_m"),
            "z_error_m": loc_all.get("depth_error_m"),
            "n_strong": loc_all.get("n_strong"),
        },
        "OFF_ANCHOR_centroid": {
            "recovered_depth_m": off_depth,
            "n_strong_off": off_nstrong,
            "max_contrast_off": off_cmax,
            "peak_off_anchor_depth_m": peak_off_depth,
            "peak_off_anchor_contrast": peak_off_contrast,
            "shallow_threshold_m": shallow_threshold,
            "off_anchor_is_shallow": bool(off_is_shallow),
        },
        "verdict": (
            "TAUTOLÓGICA CONFIRMADA — la gravedad no construyó profundidad off-anchor"
            if off_is_shallow else
            "NO tautológica — la profundidad off-anchor también subió (revisar hipótesis)"
        ),
        "elapsed_s": round(time.time() - t0, 1),
    }

    print("\n" + "-" * 80)
    print(f"Celdas ancladas (n={n_anchored}): prof={anchored_depths} m, "
          f"densidad={anchored_rho} t/m³")
    print(f"Centroide CON ancla:  prof={loc_all.get('recovered_y_m')} m "
          f"(n_strong={loc_all.get('n_strong')}) ← réplica del reporte (~2925 m)")
    print(f"Centroide OFF-ANCHOR: prof={off_depth} m "
          f"(n_strong_off={off_nstrong}, máx contraste off={off_cmax})")
    print(f"Pico off-anchor: prof={peak_off_depth} m (contraste {peak_off_contrast})")
    print(f"\nVeredicto: {report['verdict']}")
    print(f"Tiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "tanda_a_part0_offanchor_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
