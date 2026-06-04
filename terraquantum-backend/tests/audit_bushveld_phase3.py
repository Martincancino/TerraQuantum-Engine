"""
AUDIT FASE 3 — Calibración H-A3: sweep λ × α_spatial en datos reales Bushveld.
================================================================================
Objetivo: encontrar la combinación (λ, α_spatial) que, con los datos reales de
real_bushveld_gravity.csv, produzca un cuerpo con:
    - profundidad ∈ [5, 12] km
    - horiz_offset < 15 km al pico de anomalía
    - misfit < 35 %
    - Δρmax ∈ [0.2, 1.0] t/m³

El sweep es:
    lambda_vals        = [1.0, 3.0, 5.0]
    alpha_spatial_vals = [1, 5, 10, 25, 50]   →  15 inversiones

Los datos de real_bushveld_gravity.csv ya vienen proyectados a metros (x_m, z_m).
No se llama project_geographic_to_local; sí se aplica remove_regional_trend(order=2).

Resultados → tests/audit_bushveld_phase3_results.json
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import sys

import numpy as np

# ── Resolución de imports (funciona como script directo o desde pytest) ─────
try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid
    from exploration.preprocessing import remove_regional_trend
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid
    from exploration.preprocessing import remove_regional_trend

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("audit.phase3")

# ── Paths ────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_CSV = os.path.join(_HERE, "data", "real_bushveld_gravity.csv")
OUT_JSON = os.path.join(_HERE, "audit_bushveld_phase3_results.json")

# ── Parámetros de malla ───────────────────────────────────────────────────────
BLOCK = 4000.0      # 4 km por celda
NZ_DEPTH = 5        # 5 capas → 20 km de profundidad
REG_ORDER = 2       # Poly-2 para remoción de regional

# ── Sweep ────────────────────────────────────────────────────────────────────
LAMBDA_VALS = [1.0, 3.0, 5.0]
ALPHA_SPATIAL_VALS = [1.0, 5.0, 10.0, 25.0, 50.0]
DEPTH_BETA = 2.0  # Li & Oldenburg 1998 standard

# ── Umbrales de sanidad ───────────────────────────────────────────────────────
DEPTH_MIN_KM   = 5.0
DEPTH_MAX_KM   = 12.0
HORIZ_OFF_MAX  = 15.0    # km
MISFIT_MAX_PCT = 35.0    # %
DRHO_MIN       = 0.2     # t/m³
DRHO_MAX       = 1.0     # t/m³


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_data():
    """Lee real_bushveld_gravity.csv → (x_m, z_m, g_mGal)."""
    a = np.genfromtxt(DATA_CSV, delimiter=",", skip_header=1, usecols=(1, 3, 4))
    x, z, g = a[:, 0], a[:, 1], a[:, 2]
    log.info("CSV cargado: %d estaciones | x [%.1f, %.1f] km | z [%.1f, %.1f] km",
             len(x), x.min() / 1e3, x.max() / 1e3, z.min() / 1e3, z.max() / 1e3)
    log.info("g raw (mGal): min=%.2f  max=%.2f  std=%.2f", g.min(), g.max(), g.std())
    return x, z, g


# ── Métricas del cuerpo recuperado ───────────────────────────────────────────

def body_metrics(contrast, x_c, y_c, z_c, x_pk, z_pk):
    """
    Extrae métricas del cuerpo: celdas con Δρ > 0.5·Δρmax.
    Devuelve depth_km (CoM vertical), horiz_offset_km (al pico), delta_rho_max.
    """
    c_finite = np.nan_to_num(contrast, nan=0.0)
    dmax = float(np.nanmax(c_finite))
    if dmax <= 0:
        return dict(depth_km=np.nan, horiz_offset_km=np.nan, delta_rho_max=0.0, n_body=0)

    body = c_finite > 0.5 * dmax
    if not body.any():
        return dict(depth_km=np.nan, horiz_offset_km=np.nan, delta_rho_max=dmax, n_body=0)

    w = c_finite[body]
    tot = w.sum()
    cmx = (w * x_c[body]).sum() / tot
    cmy = (w * y_c[body]).sum() / tot   # profundidad (metros, positivo ↓)
    cmz = (w * z_c[body]).sum() / tot
    off_km = float(np.hypot(cmx - x_pk, cmz - z_pk) / 1000.0)
    return dict(
        depth_km=float(cmy / 1000.0),
        horiz_offset_km=off_km,
        delta_rho_max=float(dmax),
        n_body=int(body.sum()),
    )


def sanity_notes(depth_km, horiz_offset_km, misfit_pct, delta_rho_max):
    """Devuelve lista de problemas (vacía = PASS)."""
    issues = []
    if np.isnan(depth_km):
        issues.append("depth=NaN (cuerpo vacío)")
        return issues
    if depth_km < DEPTH_MIN_KM:
        issues.append(f"depth {depth_km:.1f}km < {DEPTH_MIN_KM}km (demasiado shallow)")
    if depth_km > DEPTH_MAX_KM:
        issues.append(f"depth {depth_km:.1f}km > {DEPTH_MAX_KM}km (demasiado profundo)")
    if horiz_offset_km >= HORIZ_OFF_MAX:
        issues.append(f"horiz_offset {horiz_offset_km:.1f}km ≥ {HORIZ_OFF_MAX}km")
    if misfit_pct >= MISFIT_MAX_PCT:
        issues.append(f"misfit {misfit_pct:.1f}% ≥ {MISFIT_MAX_PCT}%")
    if delta_rho_max < DRHO_MIN:
        issues.append(f"Δρmax {delta_rho_max:.2f} < {DRHO_MIN} t/m³")
    if delta_rho_max > DRHO_MAX:
        issues.append(f"Δρmax {delta_rho_max:.2f} > {DRHO_MAX} t/m³")
    return issues


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Cargar datos
    x, z, g_raw = load_data()

    # 2. Remoción de regional (poly-2)
    residual, _, _ = remove_regional_trend(x, z, g_raw, order=REG_ORDER)
    g_target = residual          # media ≈ 0; NO aplicar shift DC
    g_si = g_target * 1e-5      # mGal → SI (m/s²)

    log.info("Residual poly-%d: min=%.2f  max=%.2f  std=%.2f  mean=%.3f mGal",
             REG_ORDER, residual.min(), residual.max(), residual.std(), residual.mean())

    # Pico de anomalía densa (referencia para offset horizontal)
    pk = int(np.argmax(g_target))
    x_pk, z_pk = float(x[pk]), float(z[pk])
    log.info("Pico anomalía densa: x=%.1f km  z=%.1f km  g=%.2f mGal",
             x_pk / 1e3, z_pk / 1e3, float(g_target[pk]))

    # 3. Construir malla
    nx = int(np.ceil(x.max() / BLOCK)) + 1
    nz = int(np.ceil(z.max() / BLOCK)) + 1
    ny = NZ_DEPTH
    log.info("Malla: %dx%dx%d = %d celdas | %.0f km/celda | prof %.0f km",
             nx, ny, nz, nx * ny * nz, BLOCK / 1e3, ny * BLOCK / 1e3)

    _, _, _, x_c, y_c, z_c = build_voxel_grid(nx, ny, nz, BLOCK)

    # Sensores en superficie (y=0)
    sensors = np.column_stack([x, np.zeros_like(x), z]).astype(np.float64)

    # Objetos fijos de forward/inversion
    fwd = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=2e6)
    inv = GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=BLOCK)

    # Nivel de ruido para data-weighting
    noise = 0.02 * float(np.sqrt(np.mean(g_si ** 2)))

    # 4. Barrido λ × α
    log.info("=" * 72)
    log.info("SWEEP: lambda_vals=%s  alpha_spatial_vals=%s", LAMBDA_VALS, ALPHA_SPATIAL_VALS)
    log.info("SANITY: depth [%g,%g] km | off<%g km | misfit<%g%% | Δρ [%g,%g] t/m³",
             DEPTH_MIN_KM, DEPTH_MAX_KM, HORIZ_OFF_MAX, MISFIT_MAX_PCT, DRHO_MIN, DRHO_MAX)
    log.info("=" * 72)
    hdr = f"{'λ':>6} {'α':>6} | {'misfit%':>8} | {'depth km':>9} {'off km':>7} {'Δρmax':>7} | {'PASS':>5} | ISSUES"
    log.info(hdr)
    log.info("-" * 72)

    results = []
    for lm in LAMBDA_VALS:
        for asp in ALPHA_SPATIAL_VALS:
            with contextlib.redirect_stdout(io.StringIO()):
                ed, _, mis, _ = inv.solve_inversion_lsqr(
                    g_observed=g_si,
                    kernel_sparse=None,
                    y_c=y_c,
                    lambda_mag=lm,
                    alpha_spatial=asp,
                    forward_model=fwd,
                    sensor_coords=sensors,
                    x_c=x_c,
                    z_c=z_c,
                    noise_floor=noise,
                    noise_pct=0.0,
                    depth_beta=DEPTH_BETA,
                )

            contrast = np.nan_to_num(ed - inv.base_density, nan=0.0)
            mt = body_metrics(contrast, x_c, y_c, z_c, x_pk, z_pk)
            issues = sanity_notes(mt["depth_km"], mt["horiz_offset_km"], float(mis), mt["delta_rho_max"])
            passed = len(issues) == 0
            notes = "PASS: all sanity checks" if passed else " | ".join(issues)

            row = {
                "lambda": float(lm),
                "alpha_spatial": float(asp),
                "depth_km": round(mt["depth_km"], 2) if not np.isnan(mt["depth_km"]) else None,
                "horiz_offset_km": round(mt["horiz_offset_km"], 2) if not np.isnan(mt["horiz_offset_km"]) else None,
                "misfit_pct": round(float(mis), 2),
                "delta_rho_max": round(mt["delta_rho_max"], 3),
                "n_body": mt["n_body"],
                "pass_sanity": bool(passed),
                "notes": notes,
            }
            results.append(row)

            flag = " <== PASS" if passed else ""
            log.info(
                f"{lm:>6.1f} {asp:>6.0f} | {mis:>8.1f} | {mt['depth_km']:>9.2f} "
                f"{mt['horiz_offset_km']:>7.1f} {mt['delta_rho_max']:>7.3f} | "
                f"{'YES' if passed else 'NO':>5}{flag}"
            )

    log.info("=" * 72)

    # 5. Estadísticas finales
    n_pass = sum(r["pass_sanity"] for r in results)
    log.info("Configs PASS: %d / %d", n_pass, len(results))

    lambda3_results = [r for r in results if r["lambda"] == 3.0]
    lambda3_pass = [r for r in lambda3_results if r["pass_sanity"]]

    if lambda3_pass:
        # Best λ=3 con sanity OK: menor misfit
        best_l3 = min(lambda3_pass, key=lambda r: r["misfit_pct"])
        log.info("Best λ=3.0 PASS: α=%.0f  depth=%.2f km  misfit=%.1f%%",
                 best_l3["alpha_spatial"], best_l3["depth_km"], best_l3["misfit_pct"])
    else:
        # Ninguna config λ=3 pasa — reportar la más cercana al rango
        def depth_distance(r):
            d = r["depth_km"]
            if d is None:
                return 9999.0
            if d < DEPTH_MIN_KM:
                return DEPTH_MIN_KM - d
            if d > DEPTH_MAX_KM:
                return d - DEPTH_MAX_KM
            return 0.0

        best_l3 = min(lambda3_results, key=depth_distance)
        log.warning(
            "depth-weighting issue persists at this scale: ningún α produce depth>%.0f km "
            "con λ=3.0. Mejor aproximación: α=%.0f depth=%.2f km misfit=%.1f%%",
            DEPTH_MIN_KM, best_l3["alpha_spatial"],
            best_l3["depth_km"] if best_l3["depth_km"] is not None else float("nan"),
            best_l3["misfit_pct"],
        )

    # 6. Guardar JSON
    output = {
        "sweep": {
            "lambda_vals": LAMBDA_VALS,
            "alpha_spatial_vals": ALPHA_SPATIAL_VALS,
            "grid": {"block_km": BLOCK / 1e3, "nz_depth": NZ_DEPTH, "total_depth_km": NZ_DEPTH * BLOCK / 1e3},
            "reg_order": REG_ORDER,
            "n_stations": len(x),
        },
        "sanity_thresholds": {
            "depth_km": [DEPTH_MIN_KM, DEPTH_MAX_KM],
            "horiz_offset_max_km": HORIZ_OFF_MAX,
            "misfit_max_pct": MISFIT_MAX_PCT,
            "delta_rho_range_t_m3": [DRHO_MIN, DRHO_MAX],
        },
        "summary": {
            "n_total": len(results),
            "n_pass": n_pass,
            "lambda3_any_pass": bool(lambda3_pass),
        },
        "results": results,
        "best_with_lambda_3": best_l3,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info("Resultados guardados → %s", OUT_JSON)

    if not lambda3_pass:
        log.warning(
            "CONCLUSIÓN: depth-weighting issue persists at this scale con λ=3.0. "
            "Ninguna α ∈ %s produce depth>%.0fkm. Considerar depth_beta recalibración (H-A4).",
            ALPHA_SPATIAL_VALS, DEPTH_MIN_KM,
        )


if __name__ == "__main__":
    main()
