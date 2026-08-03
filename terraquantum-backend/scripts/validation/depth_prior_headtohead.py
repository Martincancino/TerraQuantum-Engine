# -*- coding: utf-8 -*-
"""PUNTO 1 REFORMULADO — Head-to-head del PRIOR de profundidad en CONFIG DE PRODUCCIÓN.

El sweep endurecido mostró: Morozov (σ declarado) recupera el MODERADO (≤300m) robusto,
falla en profundo (600m frágil, 900m falla = null-space). El prior de profundidad
(espectro radial → piso → ancla dura sobre el piso) prometía 7-18×, pero ESO se midió
contra un baseline λ=1e-3 sobreajustado. La pregunta honesta AHORA:

  ¿El prior aporta valor SOBRE Morozov, especialmente a 600-900m donde Morozov falla?
  Y — el nudo — ¿el ESPECTRO da un piso usable en profundo, o falla justo donde se lo necesita?

4 brazos × {300,600,900}m × 5 semillas, config de producción (padded, IRLS=8):
  - Morozov (sin prior)          — el mejor actual (σ declarado)
  - Morozov + prior              — ¿mejora al mejor?
  - Operating-0.1 (sin prior)    — el cliente común (sin-σ)
  - Operating-0.1 + prior        — ¿lo rescata?

El prior: piso del ESPECTRO RADIAL (grilla densa 32×32, FFT barata) → ancla dura a
densidad-base todas las celdas del core POR ENCIMA del piso (hook `boreholes`, variable
elimination = rápido). Reporta el piso estimado vs la verdad. Nada ajustado.

    python scripts/validation/depth_prior_headtohead.py --smoke
    python scripts/validation/depth_prior_headtohead.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.morozov_prod_hardened as MPH
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.field_validation_service import estimate_location_error
from services.potential_field_grid_service import ScatteredGrid
from services.euler_spectral_service import radial_power_spectrum
from services.depth_prior_service import recommend_depth_floor

DEPTHS = [300.0, 600.0, 900.0]
# Piso ORÁCULO (como si el espectro fuera perfecto): 0.7×profundidad real → separa
# "el mecanismo no transfiere en config prod" de "la fuente (espectro) falla en profundo".
SEEDS = MPH.SEEDS
SPEC_N = 32   # grilla densa para el espectro (FFT barata, no se invierte)


def _spectrum_floor(by, seed):
    """Piso de profundidad del ESPECTRO RADIAL sobre una grilla densa analítica + ruido."""
    rng = np.random.default_rng(seed + 999)
    cx = cz = MPH.MESH_CENTER
    half = MPH.SPAN_M / 2.0
    a = np.linspace(cx - half, cx + half, SPEC_N)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g = MPH._sphere_gy_ms2(sensors, cx, by, cz, MPH.RADIUS_M, MPH.DELTA_RHO)
    noise = MPH.NOISE_MGAL * 1e-5
    g = g + noise * rng.standard_normal(g.size)
    vals = (g / 1e-5).reshape(SPEC_N, SPEC_N)
    dx = MPH.SPAN_M / (SPEC_N - 1)
    sg = ScatteredGrid(values=vals, x0=cx - half, y0=cz - half, dx=dx, dy=dx,
                       nx=SPEC_N, ny=SPEC_N, inside_hull=np.ones((SPEC_N, SPEC_N), dtype=bool))
    try:
        z = radial_power_spectrum(sg).get("ensemble_depth_deep_m")
    except Exception:
        z = None
    floor = None if z is None else recommend_depth_floor(1.15 * float(z), safety_fraction=0.7)
    return (None if z is None else round(float(z), 1),
            None if floor is None else round(float(floor), 1))


def _core_columns_prior(floor):
    """Ancla dura a densidad-base todas las celdas del core por ENCIMA de `floor`.
    boreholes: filas [x, z, y_from, y_to, density]. Una por columna (x,z) del core."""
    cols = np.unique(np.column_stack([MPH.XC_CORE, MPH.ZC_CORE]), axis=0)
    rows = [[float(x), float(z), 0.0, float(floor), MPH.BASE_DENSITY] for x, z in cols]
    return np.asarray(rows, dtype=np.float64)


def _solve(sensors, g_obs, sigma, by, lam, boreholes=None):
    inv = GravimetryInversion(MPH.NX_T, MPH.NY_T, MPH.NZ_T, MPH.BLOCK, base_density=MPH.BASE_DENSITY)
    fwd = GravimetryForward(MPH.BLOCK, MPH.BLOCK, MPH.BLOCK, cutoff_radius=MPH.CUTOFF)
    meta: dict = {}
    cx = cz = MPH.MESH_CENTER
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, MPH.Y_C, lambda_mag=lam, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=MPH.X_C, z_c=MPH.Z_C,
        hx=MPH.HX, hy=MPH.HY, hz=MPH.HZ, padding_mask=MPH.PADDING_MASK, padding_kappa=MPH.PADDING_KAPPA,
        boreholes=boreholes, anchor_mode=("hard" if boreholes is not None else "soft"),
        density_min=MPH.BASE_DENSITY, density_max=MPH.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.0, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=MPH.IRLS, solver_meta=meta)
    rho = np.asarray(rho, dtype=np.float64)
    rho_core = rho[MPH.IS_CORE]
    loc = estimate_location_error(rho_core, MPH.XC_CORE, MPH.YC_CORE, MPH.ZC_CORE, (cx, by, cz),
                                  base_density=MPH.BASE_DENSITY)
    contrast = np.abs(rho_core - MPH.BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(MPH.YC_CORE[ipk])
    return {
        "lambda": lam,
        "peak_err_m": None if peak_depth is None else round(abs(peak_depth - by), 1),
        "horizontal_m": loc.get("horizontal_error_m"),
        "chi2": None if meta.get("chi2_final") is None else round(float(meta["chi2_final"]), 4),
    }


def _morozov(sensors, g_obs, sigma, by, boreholes=None):
    trials = {}
    def _try(lam):
        if lam not in trials:
            trials[lam] = _solve(sensors, g_obs, sigma, by, lam, boreholes=boreholes)
        return trials[lam]["chi2"]
    scan = [_try(l) for l in MPH.MOROZOV_CANDIDATES]
    for i in range(len(MPH.MOROZOV_CANDIDATES) - 1):
        c1, c2 = scan[i], scan[i + 1]
        if c1 is not None and c2 is not None and (c1 - 1.0) * (c2 - 1.0) < 0:
            _try(float(np.sqrt(MPH.MOROZOV_CANDIDATES[i] * MPH.MOROZOV_CANDIDATES[i + 1])))
            break
    def _score(r):
        c = r["chi2"]
        return abs(np.log10(c)) if (c is not None and c > 0) else float("inf")
    return min(trials.values(), key=_score)


def run(smoke=False):
    depths = [600.0] if smoke else DEPTHS
    seeds = [11] if smoke else SEEDS
    print(f"HEAD-TO-HEAD PRIOR — config PROD (padded {MPH.NX_T}x{MPH.NY_T}x{MPH.NZ_T}, IRLS={MPH.IRLS}) "
          f"— {'SMOKE' if smoke else 'FULL'}\n", flush=True)
    rows = []
    t_all = time.time()
    for by in depths:
        for seed in seeds:
            sensors, g_obs, sigma = MPH._make_data(by, seed)
            z_spec, floor = _spectrum_floor(by, seed)
            bh = None if floor is None else _core_columns_prior(floor)
            oracle_floor = round(float(recommend_depth_floor(by, safety_fraction=0.7)), 1)
            bh_oracle = _core_columns_prior(oracle_floor)
            t = time.time()
            mor = _morozov(sensors, g_obs, sigma, by)
            mor_p = _morozov(sensors, g_obs, sigma, by, boreholes=bh) if bh is not None else None
            mor_orac = _morozov(sensors, g_obs, sigma, by, boreholes=bh_oracle)
            opr = _solve(sensors, g_obs, sigma, by, 0.1)
            opr_p = _solve(sensors, g_obs, sigma, by, 0.1, boreholes=bh) if bh is not None else None
            dt = round(time.time() - t, 1)
            row = {"true_depth_m": by, "seed": seed, "z_spectrum_m": z_spec, "floor_m": floor,
                   "floor_err_m": None if floor is None else round(floor - by, 1),
                   "oracle_floor_m": oracle_floor,
                   "morozov": mor, "morozov_prior": mor_p, "morozov_oracle": mor_orac,
                   "operating": opr, "operating_prior": opr_p, "s": dt}
            rows.append(row)
            def _f(d): return "—" if d is None else f"{d['peak_err_m']}m/h{d['horizontal_m']}m/χ²{d['chi2']}"
            print(f"prof={by:>4.0f} seed={seed:>9} | espectro z={z_spec} piso={floor}(err {row['floor_err_m']}) "
                  f"oráculo={oracle_floor} | MOR {_f(mor)} | MOR+prior {_f(mor_p)} | "
                  f"MOR+oráculo {_f(mor_orac)} | OPER {_f(opr)} | OPER+prior {_f(opr_p)} ({dt}s)",
                  flush=True)

    if not smoke:
        print("\n" + "=" * 80)
        print("RESUMEN — error de profundidad (pico) media±σ entre semillas, por brazo")
        for by in depths:
            sub = [r for r in rows if r["true_depth_m"] == by]
            fl = [r["floor_err_m"] for r in sub if r["floor_err_m"] is not None]
            print(f"\n  prof={by:.0f}m  (piso espectro err medio {np.mean(fl):+.0f}±{np.std(fl):.0f} m)")
            for arm in ("morozov", "morozov_prior", "morozov_oracle", "operating", "operating_prior"):
                errs = [r[arm]["peak_err_m"] for r in sub if r[arm] and r[arm]["peak_err_m"] is not None]
                hors = [r[arm]["horizontal_m"] for r in sub if r[arm] and r[arm]["horizontal_m"] is not None]
                if errs:
                    print(f"    {arm:16s}: pico_err {np.mean(errs):6.0f}±{np.std(errs):4.0f} m | "
                          f"horiz {np.mean(hors):6.0f}±{np.std(hors):4.0f} m")
        print("=" * 80)

    out = Path(__file__).resolve().parent / (
        "depth_prior_headtohead_smoke.json" if smoke else "depth_prior_headtohead_report.json")
    out.write_text(json.dumps({"rows": rows, "elapsed_s": round(time.time() - t_all, 1)},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}  ({round(time.time()-t_all,1)}s)", flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run(smoke="--smoke" in sys.argv)


if __name__ == "__main__":
    main()
