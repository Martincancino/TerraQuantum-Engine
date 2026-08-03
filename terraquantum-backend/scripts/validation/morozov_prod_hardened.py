# -*- coding: utf-8 -*-
"""PUNTO 4 — Morozov ENDURECIDO en CONFIG DE PRODUCCIÓN (paso 2 del hardening).

El diagnóstico de mecanismo (malla chica, IRLS=2) demostró: la fragilidad de Morozov en
profundo ES el null-space (χ²(λ) se aplana 4.06→1.27→0.56 con la profundidad; cond≈1 = no
numérico). Falta el número TRASLADABLE: config de producción real y los 3 modos de λ que
recibe cada tipo de cliente.

Config de producción REPLICADA fielmente (verificado en geophysics_service.py:2534):
  - Malla con padding: build_padded_tensor_grid(n_pad=5, pad_factor=1.3) — la misma BC física.
  - forward = GravimetryForward(dx, dx, dx) — celdas uniformes (el padding sólo pesa el Laplaciano).
  - padding_mask=~is_core, padding_kappa=1e5 (default prod), IRLS=8 (default prod), auto_kappa.
  - σ explícito → noise_pct=0 (path Morozov de prod).

Tres modos = tres tipos de cliente:
  - FIJO 1e-3   : la config del harness de Parte A (referencia; probablemente no representa a nadie).
  - OPERATING 0.1: PRECONDITIONED_OPERATING_LAMBDA — lo que recibe el cliente que NO declara σ.
  - MOROZOV     : scan [0.01,0.056,0.316,1.78,10]+bisección, |log10 χ²| mín — cliente que SÍ declara σ.

Mide, por (profundidad × semilla × modo): error de profundidad (pico+centroide), horizontal,
χ², λ elegido. Verdad conocida (esfera analítica anti-inverse-crime). Nada ajustado.

    python scripts/validation/morozov_prod_hardened.py --smoke   # 1 prof, 1 semilla (verificación)
    python scripts/validation/morozov_prod_hardened.py           # sweep completo
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.inversion_kernel_service import build_padded_tensor_grid
from services.field_validation_service import estimate_location_error

# ── Config de malla (core) — misma escala que error_budget/Parte A ────────────
NX = NZ = 18
NY = 14
BLOCK = 125.0
N_PAD = 5
PAD_FACTOR = 1.3
CUTOFF = 2600.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 2.0
PADDING_KAPPA = 1e5
IRLS = 8                      # default de producción (vs 2 del diagnóstico)
MESH_CENTER = NX * BLOCK / 2.0   # 1125 m (centro del core)

# ── Cuerpo / survey ───────────────────────────────────────────────────────────
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02

DEPTHS = [150.0, 300.0, 600.0, 900.0]
SEEDS = [11, 101, 20260725, 424242, 7]
MOROZOV_CANDIDATES = [0.01, 0.05623, 0.31623, 1.77828, 10.0]

# Malla con padding construida UNA vez (geometría fija).
_MESH = build_padded_tensor_grid(NX, NY, NZ, BLOCK, n_pad=N_PAD, pad_factor=PAD_FACTOR)
X_C = _MESH["x_c"]; Y_C = _MESH["y_c"]; Z_C = _MESH["z_c"]
HX = _MESH["hx"]; HY = _MESH["hy"]; HZ = _MESH["hz"]
IS_CORE = _MESH["is_core"]
PADDING_MASK = ~IS_CORE
NX_T = _MESH["nx_total"]; NY_T = _MESH["ny_total"]; NZ_T = _MESH["nz_total"]
XC_CORE = _MESH["x_c_core"]; YC_CORE = _MESH["y_c_core"]; ZC_CORE = _MESH["z_c_core"]


def _sphere_gy_ms2(sensors, x0, y0, z0, radius, delta_rho):
    G = 6.67430e-11
    mass = (delta_rho * 1000.0) * (4.0 / 3.0) * np.pi * radius ** 3
    dy = sensors[:, 1] - y0
    r3 = ((sensors[:, 0] - x0) ** 2 + dy ** 2 + (sensors[:, 2] - z0) ** 2) ** 1.5
    return -G * mass * dy / r3


def _make_data(by, seed):
    rng = np.random.default_rng(seed)
    cx = cz = MESH_CENTER
    half = SPAN_M / 2.0
    axis = np.linspace(cx - half, cx + half, N_SIDE)
    gx, gz = np.meshgrid(axis, axis, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g_clean = _sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
    noise = NOISE_MGAL * 1e-5
    g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
    return sensors, g_obs, max(noise, 1e-12)


def _solve(sensors, g_obs, sigma, by, lam):
    inv = GravimetryInversion(NX_T, NY_T, NZ_T, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    meta: dict = {}
    cx = cz = MESH_CENTER
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, Y_C, lambda_mag=lam, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=X_C, z_c=Z_C,
        hx=HX, hy=HY, hz=HZ, padding_mask=PADDING_MASK, padding_kappa=PADDING_KAPPA,
        density_min=BASE_DENSITY, density_max=DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.0, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=IRLS, solver_meta=meta)
    rho = np.asarray(rho, dtype=np.float64)
    rho_core = rho[IS_CORE]
    loc = estimate_location_error(rho_core, XC_CORE, YC_CORE, ZC_CORE, (cx, by, cz),
                                  base_density=BASE_DENSITY)
    contrast = np.abs(rho_core - BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(YC_CORE[ipk])
    return {
        "lambda": lam,
        "peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "peak_err_m": None if peak_depth is None else round(abs(peak_depth - by), 1),
        "centroid_err_m": loc.get("depth_error_m"),
        "horizontal_m": loc.get("horizontal_error_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2": None if meta.get("chi2_final") is None else round(float(meta["chi2_final"]), 4),
    }


def _morozov(sensors, g_obs, sigma, by):
    trials = {}
    def _try(lam):
        if lam not in trials:
            trials[lam] = _solve(sensors, g_obs, sigma, by, lam)
        return trials[lam]["chi2"]
    scan = [_try(l) for l in MOROZOV_CANDIDATES]
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


def run(smoke=False):
    depths = [600.0] if smoke else DEPTHS
    seeds = [11] if smoke else SEEDS
    print(f"MOROZOV ENDURECIDO — config PROD (malla {NX_T}x{NY_T}x{NZ_T} padded, IRLS={IRLS}, "
          f"kappa={PADDING_KAPPA:.0e}) — {'SMOKE' if smoke else 'FULL'}\n", flush=True)
    rows = []
    t_all = time.time()
    for by in depths:
        for seed in seeds:
            sensors, g_obs, sigma = _make_data(by, seed)
            t = time.time()
            fijo = _solve(sensors, g_obs, sigma, by, 1e-3)
            oper = _solve(sensors, g_obs, sigma, by, 0.1)
            moro, moro_scan = _morozov(sensors, g_obs, sigma, by)
            dt = round(time.time() - t, 1)
            row = {"true_depth_m": by, "seed": seed,
                   "fijo_1e-3": fijo, "operating_0.1": oper,
                   "morozov": moro, "morozov_scan": moro_scan, "s": dt}
            rows.append(row)
            print(f"prof={by:>4.0f} seed={seed:>9} | "
                  f"FIJO1e-3 pico_err={fijo['peak_err_m']}m horiz={fijo['horizontal_m']}m χ²={fijo['chi2']} | "
                  f"OPER0.1 pico_err={oper['peak_err_m']}m horiz={oper['horizontal_m']}m χ²={oper['chi2']} | "
                  f"MOROZOV λ={moro['lambda']:.3g} pico_err={moro['peak_err_m']}m "
                  f"horiz={moro['horizontal_m']}m χ²={moro['chi2']} ({dt}s)", flush=True)

    if not smoke:
        print("\n" + "=" * 78)
        print("RESUMEN — error de profundidad (pico) por modo, media±σ entre semillas")
        for by in depths:
            sub = [r for r in rows if r["true_depth_m"] == by]
            for mode in ("fijo_1e-3", "operating_0.1", "morozov"):
                errs = [r[mode]["peak_err_m"] for r in sub if r[mode]["peak_err_m"] is not None]
                hors = [r[mode]["horizontal_m"] for r in sub if r[mode]["horizontal_m"] is not None]
                print(f"  prof={by:>4.0f} {mode:14s}: pico_err {np.mean(errs):6.0f}±{np.std(errs):4.0f} m | "
                      f"horiz {np.mean(hors):6.0f}±{np.std(hors):4.0f} m")
        print("=" * 78)

    out = Path(__file__).resolve().parent / (
        "morozov_prod_hardened_smoke.json" if smoke else "morozov_prod_hardened_report.json")
    out.write_text(json.dumps({"config": {"nx_total": NX_T, "ny_total": NY_T, "nz_total": NZ_T,
                                          "irls": IRLS, "n_pad": N_PAD, "padding_kappa": PADDING_KAPPA},
                               "rows": rows, "elapsed_s": round(time.time() - t_all, 1)},
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
