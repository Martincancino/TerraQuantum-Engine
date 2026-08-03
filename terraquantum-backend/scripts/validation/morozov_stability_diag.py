# -*- coding: utf-8 -*-
"""PUNTO 4 — DIAGNÓSTICO de la inestabilidad de Morozov (paso #1, antes de todo).

Observado: a 600 m Morozov salta entre semillas (pico 538 ↔ 38 m), a 900 m falla y
destroza el horizontal, y un solve tardó 2.2 h. Antes de reencuadrar nada hay que saber
QUÉ es esa inestabilidad. Dos hipótesis:

  (H1) PATOLOGÍA NUMÉRICA: cond(A) explota a ciertos λ → el solve es basura a veces.
  (H2) NULL-SPACE en la selección de λ: el dato NO restringe la profundidad en profundo,
       así que χ²(λ) es PLANA cerca de χ²=1 → el λ que "recupera" no es único →
       ruido de semilla mueve el λ elegido y con él la profundidad. En ese caso la
       fragilidad de Morozov y la LEY del null-space son el MISMO fenómeno, y la
       conclusión honesta es: Morozov rescata lo MODERADO, no lo profundo.

Discriminante clave: a un λ FIJO cerca del punto de Morozov, ¿la profundidad varía entre
semillas (→ null-space) o es estable (→ solo la selección salta)? Y ¿cond(A) explota?

Este es el MECANISMO (malla chica rápida, IRLS=2) — los NÚMEROS finales van con config
de producción (IRLS=8/padding) en un paso posterior. Nada ajustado.

    python scripts/validation/morozov_stability_diag.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.error_budget as EB
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.field_validation_service import estimate_location_error

DEPTHS = [300.0, 600.0, 900.0]          # 300 control estable · 600 salta · 900 falla
SEEDS = [11, 101, 20260725, 424242, 7]  # 5 semillas
LAMBDAS = [0.0316, 0.1, 0.316, 0.562, 1.0, 1.78, 3.16]  # rango donde Morozov aterriza
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02


def _solve(sensors, g_obs, sigma, by, lam):
    x_c, y_c, z_c = EB._grid_centers_fortran(EB.NX, EB.NY, EB.NZ, EB.BLOCK)
    inv = GravimetryInversion(EB.NX, EB.NY, EB.NZ, EB.BLOCK, base_density=EB.BASE_DENSITY)
    fwd = GravimetryForward(EB.BLOCK, EB.BLOCK, EB.BLOCK, cutoff_radius=EB.CUTOFF)
    meta: dict = {}
    cx = cz = EB.MESH_CENTER
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=lam, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        density_min=EB.BASE_DENSITY, density_max=EB.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.0, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=EB.COMPACT_IRLS, solver_meta=meta)
    rho = np.asarray(rho, dtype=np.float64)
    loc = estimate_location_error(rho, x_c, y_c, z_c, (cx, by, cz), base_density=EB.BASE_DENSITY)
    contrast = np.abs(rho - EB.BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(y_c[ipk])
    return {
        "peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "horizontal_m": loc.get("horizontal_error_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2": None if meta.get("chi2_final") is None else round(float(meta["chi2_final"]), 4),
        "cond_a": None if meta.get("cond_a_estimated") is None else float(meta["cond_a_estimated"]),
    }


def _mk_data(by, seed):
    rng = np.random.default_rng(seed)
    cx = cz = EB.MESH_CENTER
    half = SPAN_M / 2.0
    axis = np.linspace(cx - half, cx + half, N_SIDE)
    gx, gz = np.meshgrid(axis, axis, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g_clean = EB._sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
    noise = NOISE_MGAL * 1e-5
    g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
    return sensors, g_obs, max(noise, 1e-12)


def run():
    grid = {}   # (depth) -> lambda -> list per seed
    t_all = time.time()
    for by in DEPTHS:
        grid[by] = {lam: [] for lam in LAMBDAS}
        for seed in SEEDS:
            sensors, g_obs, sigma = _mk_data(by, seed)
            for lam in LAMBDAS:
                t = time.time()
                r = _solve(sensors, g_obs, sigma, by, lam)
                r["seed"] = seed
                r["s"] = round(time.time() - t, 1)
                grid[by][lam].append(r)
                print(f"prof={by:>4.0f} seed={seed:>9} λ={lam:<6.3g} "
                      f"pico={r['peak_depth_m']}m χ²={r['chi2']} cond={r['cond_a']:.2e} "
                      f"horiz={r['horizontal_m']}m ({r['s']}s)", flush=True)

    # ── Análisis por profundidad ──────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("ANÁLISIS — χ²(λ), cond(λ) y dispersión de profundidad entre semillas")
    print("=" * 78)
    summary = {}
    for by in DEPTHS:
        print(f"\n▼ Profundidad real = {by:.0f} m")
        print(f"  {'λ':>7} | {'χ² medio':>9} {'χ² rango':>16} | {'cond medio':>11} | "
              f"{'pico medio':>10} {'pico σ':>8} {'picos únicos':>14}")
        rows_by = []
        for lam in LAMBDAS:
            rs = grid[by][lam]
            chi2s = [x["chi2"] for x in rs if x["chi2"] is not None]
            conds = [x["cond_a"] for x in rs if x["cond_a"] is not None]
            picos = [x["peak_depth_m"] for x in rs if x["peak_depth_m"] is not None]
            chi2_mean = float(np.mean(chi2s)) if chi2s else None
            cond_mean = float(np.mean(conds)) if conds else None
            pico_mean = float(np.mean(picos)) if picos else None
            pico_std = float(np.std(picos)) if picos else None
            uniq = sorted(set(picos))
            print(f"  {lam:>7.3g} | {chi2_mean:>9.4f} [{min(chi2s):>6.3f},{max(chi2s):>6.3f}] | "
                  f"{cond_mean:>11.2e} | {pico_mean:>9.0f}m {pico_std:>7.0f}m  {str([int(u) for u in uniq]):>14}")
            rows_by.append({"lambda": lam, "chi2_mean": chi2_mean,
                            "chi2_min": min(chi2s) if chi2s else None,
                            "chi2_max": max(chi2s) if chi2s else None,
                            "cond_mean": cond_mean, "peak_mean": pico_mean,
                            "peak_std": pico_std, "peaks_unique": uniq})
        # Pendiente local de χ² vs log10(λ) cerca de χ²=1 (planitud = null-space en la selección).
        ll = np.log10(LAMBDAS)
        cc = np.array([r["chi2_mean"] for r in rows_by], dtype=float)
        # cruce de χ²=1
        slope_at_1 = None
        for i in range(len(LAMBDAS) - 1):
            if (cc[i] - 1.0) * (cc[i + 1] - 1.0) <= 0 and cc[i] != cc[i + 1]:
                slope_at_1 = float((cc[i + 1] - cc[i]) / (ll[i + 1] - ll[i]))
                break
        print(f"  → pendiente dχ²/dlog₁₀λ en el cruce χ²=1: "
              f"{'n/a (no cruza)' if slope_at_1 is None else f'{slope_at_1:.3f}'}  "
              f"(plana = pequeña → selección de λ no-única = null-space)")
        summary[by] = {"rows": rows_by, "chi2_slope_at_1": slope_at_1}

    out = Path(__file__).resolve().parent / "morozov_stability_diag_report.json"
    out.write_text(json.dumps({
        "depths": DEPTHS, "seeds": SEEDS, "lambdas": LAMBDAS,
        "grid": {str(k): {str(l): v for l, v in d.items()} for k, d in grid.items()},
        "summary": {str(k): v for k, v in summary.items()},
        "elapsed_s": round(time.time() - t_all, 1),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}  ({round(time.time()-t_all,1)}s)", flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
