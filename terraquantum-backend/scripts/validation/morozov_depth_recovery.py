# -*- coding: utf-8 -*-
"""PUNTO 4 — ¿la profundidad NO se recupera (LEY), o es un ARTEFACTO del λ fijo?

La Parte A midió "profundidad no se recupera" con λ FIJO=1e-3 (config DO-27 somero).
Pero PRODUCCIÓN, cuando σ es explícito, elige λ por DISCREPANCIA DE MOROZOV sobre el
solver real, con candidatos [0.01, 0.056, 0.316, 1.78, 10.0] (¡hasta λ=10!). El barrido
de trade-off mostró que a χ²≈1 (λ alto) la profundidad SÍ se recupera (err 37.5 m a 600 m)
mientras que a λ=1e-3 se apila somero (χ²=0.098 = SOBREAJUSTE).

Este harness replica FIELMENTE la selección de Morozov de producción
(services/geophysics_service.py: mismos candidatos + bisección + |log10 χ²| mínimo) sobre
la esfera analítica (anti-inverse-crime) a varias profundidades + un CONTROL somero (150 m,
tipo DO-27), y compara contra el λ fijo=1e-3. Pregunta:

    ¿La profundidad se recupera cuando λ se elige como en producción (Morozov)?
    Y en el somero, ¿Morozov elige un λ bajo y NO lo rompe?

Sin ajustar nada; se reporta lo que salga (depth err, horizontal, λ elegido, χ²).

    python scripts/validation/morozov_depth_recovery.py
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

# Candidatos EXACTOS de producción (geophysics_service.py ~2890).
MOROZOV_CANDIDATES = [0.01, 0.05623, 0.31623, 1.77828, 10.0]
DEPTHS = [150.0, 300.0, 600.0, 900.0]   # 150 = control somero tipo DO-27
SEEDS = [20260725, 424242]
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
    chi2 = meta.get("chi2_final")
    return {
        "lambda": lam,
        "peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "peak_err_m": None if peak_depth is None else round(abs(peak_depth - by), 1),
        "centroid_err_m": loc.get("depth_error_m"),
        "horizontal_m": loc.get("horizontal_error_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2": None if chi2 is None else round(float(chi2), 4),
    }


def _morozov_select(sensors, g_obs, sigma, by):
    """Réplica fiel de la selección de producción: scan candidatos + bisección del
    bracket de χ²=1, elige |log10(χ²)| mínimo."""
    trials = {}
    def _try(lam):
        if lam not in trials:
            trials[lam] = _solve(sensors, g_obs, sigma, by, lam)
        return trials[lam]["chi2"]
    scan = [_try(l) for l in MOROZOV_CANDIDATES]
    # Bisección geométrica del primer bracket que cruza χ²=1 (χ² crece con λ).
    for i in range(len(MOROZOV_CANDIDATES) - 1):
        c1, c2 = scan[i], scan[i + 1]
        if c1 is not None and c2 is not None and (c1 - 1.0) * (c2 - 1.0) < 0:
            _try(float(np.sqrt(MOROZOV_CANDIDATES[i] * MOROZOV_CANDIDATES[i + 1])))
            break
    def _score(r):
        c = r["chi2"]
        return abs(np.log10(c)) if (c is not None and c > 0) else float("inf")
    best = min(trials.values(), key=_score)
    return best, list(trials.values())


def run():
    rows = []
    for by in DEPTHS:
        for seed in SEEDS:
            rng = np.random.default_rng(seed)
            cx = cz = EB.MESH_CENTER
            half = SPAN_M / 2.0
            axis = np.linspace(cx - half, cx + half, N_SIDE)
            gx, gz = np.meshgrid(axis, axis, indexing="ij")
            sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
            g_clean = EB._sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
            noise = NOISE_MGAL * 1e-5
            g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
            sigma = max(noise, 1e-12)

            t = time.time()
            fixed = _solve(sensors, g_obs, sigma, by, 1e-3)   # config Parte A (λ fijo)
            best, scan = _morozov_select(sensors, g_obs, sigma, by)
            dt = round(time.time() - t, 1)
            row = {"true_depth_m": by, "seed": seed,
                   "fixed_lambda_1e-3": fixed, "morozov_selected": best,
                   "morozov_scan": scan, "s": dt}
            rows.append(row)
            print(f"prof={by:>4.0f} seed={seed} | FIJO λ=1e-3: pico_err={fixed['peak_err_m']}m "
                  f"horiz={fixed['horizontal_m']}m χ²={fixed['chi2']} || "
                  f"MOROZOV λ={best['lambda']:.4g}: pico_err={best['peak_err_m']}m "
                  f"horiz={best['horizontal_m']}m χ²={best['chi2']} ({dt}s)", flush=True)

    print("\n" + "=" * 74)
    print("RESUMEN — ¿Morozov recupera la profundidad donde el λ fijo=1e-3 falla?")
    for by in DEPTHS:
        sub = [r for r in rows if r["true_depth_m"] == by]
        f_err = np.mean([r["fixed_lambda_1e-3"]["peak_err_m"] for r in sub])
        m_err = np.mean([r["morozov_selected"]["peak_err_m"] for r in sub])
        m_lam = [round(r["morozov_selected"]["lambda"], 4) for r in sub]
        print(f"  prof={by:>4.0f}m: pico_err FIJO={f_err:6.0f}m → MOROZOV={m_err:6.0f}m "
              f"(λ elegido {m_lam})")
    print("=" * 74)

    out = Path(__file__).resolve().parent / "morozov_depth_recovery_report.json"
    out.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
