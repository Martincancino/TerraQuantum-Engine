# -*- coding: utf-8 -*-
"""PUNTO 4 — trade-off PROFUNDIDAD ↔ χ² (agregado 3) y ¿el depth-weight agrega valor?

La sonda de palancas midió: la profundidad la gobierna la MAGNITUD del smallness
(lambda_mag); la suavidad no. Forzar masa profunda (λ alto) cuesta ajuste. Aquí se
mide la curva completa y se responde la pregunta decisiva con la disciplina del χ²:

  (1) CURVA: para un barrido de λ, ¿hay ALGÚN λ que dé buena profundidad Y χ²≈1?
      (χ² < 1 = sobreajuste; χ² ≫ 1 = subajuste). Si no existe → la profundidad es
      null-space (LEY), no un bug tuneable.
  (2) VALOR DEL FIX: a un λ donde el smallness SÍ pesa (bloque activo), ¿el
      depth-weight (smallness_depth_beta) mejora la profundidad A χ² IGUALADO frente
      a solo subir λ? Si no mejora a χ² igualado → el fix no agrega nada sobre λ.

Esfera analítica a 600 m (anti-inverse-crime), motor real. Nada ajustado.

    python scripts/validation/wz_tradeoff.py
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

DEPTH_M = 600.0
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02


def _solve(sensors, g_obs, sigma, by, *, lambda_mag, sdb=0.0):
    x_c, y_c, z_c = EB._grid_centers_fortran(EB.NX, EB.NY, EB.NZ, EB.BLOCK)
    inv = GravimetryInversion(EB.NX, EB.NY, EB.NZ, EB.BLOCK, base_density=EB.BASE_DENSITY)
    fwd = GravimetryForward(EB.BLOCK, EB.BLOCK, EB.BLOCK, cutoff_radius=EB.CUTOFF)
    meta: dict = {}
    cx = cz = EB.MESH_CENTER
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=lambda_mag, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        density_min=EB.BASE_DENSITY, density_max=EB.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=EB.COMPACT_IRLS, smallness_depth_beta=sdb, solver_meta=meta)
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
        "peak_err_m": None if peak_depth is None else round(abs(peak_depth - by), 1),
        "centroid_m": loc.get("recovered_y_m"),
        "centroid_err_m": loc.get("depth_error_m"),
        "horizontal_m": loc.get("horizontal_error_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2": None if meta.get("chi2_final") is None else round(meta["chi2_final"], 4),
        "s_over_s": None if meta.get("smallness_over_smoothness") is None
                    else round(meta["smallness_over_smoothness"], 3),
    }


LAMBDAS = [1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1, 1.0]
# λ donde el smallness ya pesa (s/s≈6.8) pero el ajuste aún no está destruido:
LAMBDA_ACTIVE = 1e-1
SDBS = [0.0, -2.0, -4.0, 2.0]   # depth-weight a λ activo (a χ² comparable)


def run():
    rng = np.random.default_rng(20260725)
    cx = cz = EB.MESH_CENTER
    by = DEPTH_M
    half = SPAN_M / 2.0
    axis = np.linspace(cx - half, cx + half, N_SIDE)
    gx, gz = np.meshgrid(axis, axis, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g_clean = EB._sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
    noise = NOISE_MGAL * 1e-5
    g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
    sigma = max(noise, 1e-12)

    print(f"Esfera a {by:.0f} m (techo {by-RADIUS_M:.0f} m). χ²<1 = sobreajuste; χ²≈1 = correcto.\n")
    print("── (1) CURVA λ → profundidad ↔ χ² ─────────────────────────────────", flush=True)
    curve = []
    for lam in LAMBDAS:
        t = time.time()
        r = _solve(sensors, g_obs, sigma, by, lambda_mag=lam)
        r["lambda"] = lam
        r["s"] = round(time.time() - t, 1)
        curve.append(r)
        print(f"λ={lam:<7.0e} pico={r['peak_depth_m']}m (err {r['peak_err_m']}m) "
              f"cent={r['centroid_m']}m (err {r['centroid_err_m']}m) "
              f"horiz={r['horizontal_m']}m misfit={r['misfit_pct']}% χ²={r['chi2']} "
              f"s/s={r['s_over_s']} ({r['s']}s)", flush=True)

    print(f"\n── (2) depth-weight a λ={LAMBDA_ACTIVE:.0e} (smallness activo) — ¿mejora a χ² igual? ──", flush=True)
    dw = []
    for sdb in SDBS:
        t = time.time()
        r = _solve(sensors, g_obs, sigma, by, lambda_mag=LAMBDA_ACTIVE, sdb=sdb)
        r["smallness_depth_beta"] = sdb
        r["s"] = round(time.time() - t, 1)
        dw.append(r)
        print(f"sdb={sdb:+.1f} pico={r['peak_depth_m']}m (err {r['peak_err_m']}m) "
              f"cent={r['centroid_m']}m (err {r['centroid_err_m']}m) "
              f"misfit={r['misfit_pct']}% χ²={r['chi2']} ({r['s']}s)", flush=True)

    # Veredictos medidos
    good = [c for c in curve if c["chi2"] is not None and 0.7 <= c["chi2"] <= 1.3]
    best_good = min(good, key=lambda c: c["peak_err_m"]) if good else None
    base_dw = next(r for r in dw if r["smallness_depth_beta"] == 0.0)
    improved_dw = [r for r in dw if r["smallness_depth_beta"] != 0.0
                   and r["peak_err_m"] is not None and base_dw["peak_err_m"] is not None
                   and r["peak_err_m"] < base_dw["peak_err_m"] - 20
                   and r["chi2"] is not None and r["chi2"] <= base_dw["chi2"] * 1.15]

    print("\n" + "=" * 70)
    if best_good:
        print(f"(1) Mejor profundidad con χ²∈[0.7,1.3]: λ={best_good['lambda']:.0e} → "
              f"pico err {best_good['peak_err_m']}m, χ²={best_good['chi2']}")
    else:
        print("(1) NINGÚN λ da χ²∈[0.7,1.3] en este caso (todos sobre/subajustan).")
    print(f"(2) depth-weight mejora profundidad a χ² igualado: "
          f"{'SÍ' if improved_dw else 'NO'} "
          f"(base sdb=0: err {base_dw['peak_err_m']}m χ²={base_dw['chi2']})")
    print("=" * 70)

    out = Path(__file__).resolve().parent / "wz_tradeoff_report.json"
    out.write_text(json.dumps({"true_depth_m": by, "curve": curve, "depth_weight_at_active_lambda": dw},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
