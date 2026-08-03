# -*- coding: utf-8 -*-
"""PUNTO 4 — sonda de PALANCAS: ¿qué mueve la profundidad recuperada (los 62.5 m clavados)?

La perilla del smallness resultó inerte (smallness = 7% del objetivo; la suavidad domina).
Antes de reubicar el fix a ciegas, se MIDE qué término controla realmente la profundidad
en el régimen profundo (esfera a 600 m). Se barre:
  - lambda_mag (peso del smallness): ¿boostear el smallness mueve la masa en profundidad?
  - alpha_spatial (peso de la suavidad): ¿la suavidad controla la profundidad?
  - regularization_norm (L2 vs compact): ¿la norma cambia la profundidad?

Sin ajustar nada; se reporta la profundidad de pico recuperada y el χ² de cada corrida.

    python scripts/validation/wz_lever_probe.py
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


def _solve(sensors, g_obs, sigma, by, *, lambda_mag, alpha_spatial, reg_norm, depth_beta=2.0):
    x_c, y_c, z_c = EB._grid_centers_fortran(EB.NX, EB.NY, EB.NZ, EB.BLOCK)
    inv = GravimetryInversion(EB.NX, EB.NY, EB.NZ, EB.BLOCK, base_density=EB.BASE_DENSITY)
    fwd = GravimetryForward(EB.BLOCK, EB.BLOCK, EB.BLOCK, cutoff_radius=EB.CUTOFF)
    meta: dict = {}
    cx = cz = EB.MESH_CENTER
    kw = dict(
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        density_min=EB.BASE_DENSITY, density_max=EB.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True,
        prune_observable_domain=True, regularization_norm=reg_norm,
        depth_beta=depth_beta, solver_meta=meta,
    )
    if reg_norm != "l2":
        kw["compact_max_irls"] = EB.COMPACT_IRLS
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=lambda_mag, alpha_spatial=alpha_spatial, **kw)
    rho = np.asarray(rho, dtype=np.float64)
    loc = estimate_location_error(rho, x_c, y_c, z_c, (cx, by, cz), base_density=EB.BASE_DENSITY)
    contrast = np.abs(rho - EB.BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(y_c[ipk])
    return {
        "recovered_peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "recovered_centroid_m": loc.get("recovered_y_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2_final": None if meta.get("chi2_final") is None else round(meta["chi2_final"], 4),
        "smallness_over_smoothness": (None if meta.get("smallness_over_smoothness") is None
                                      else round(meta["smallness_over_smoothness"], 4)),
    }


CONFIGS = [
    ("baseline (lam=1e-3, alpha=1, compact)", dict(lambda_mag=1e-3, alpha_spatial=1.0, reg_norm="compact")),
    ("smallness x100 (lam=1e-1)",             dict(lambda_mag=1e-1, alpha_spatial=1.0, reg_norm="compact")),
    ("smallness x1000 (lam=1.0)",             dict(lambda_mag=1.0,  alpha_spatial=1.0, reg_norm="compact")),
    ("smoothness /10 (alpha=0.1)",            dict(lambda_mag=1e-3, alpha_spatial=0.1, reg_norm="compact")),
    ("smoothness x10 (alpha=10)",             dict(lambda_mag=1e-3, alpha_spatial=10.0, reg_norm="compact")),
    ("norma L2 (lam=1e-3, alpha=1)",          dict(lambda_mag=1e-3, alpha_spatial=1.0, reg_norm="l2")),
]


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

    print(f"Esfera a {by:.0f} m (techo {by-RADIUS_M:.0f} m) · ¿qué palanca mueve la profundidad?\n", flush=True)
    rows = []
    for label, cfg in CONFIGS:
        t = time.time()
        r = _solve(sensors, g_obs, sigma, by, **cfg)
        r["label"] = label
        r["s"] = round(time.time() - t, 1)
        rows.append(r)
        print(f"{label:42s} prof_pico={r['recovered_peak_depth_m']} m  "
              f"centroide={r['recovered_centroid_m']} m  misfit={r['misfit_pct']}%  "
              f"chi2={r['chi2_final']}  s/s={r['smallness_over_smoothness']}  ({r['s']}s)", flush=True)

    depths = {r["label"]: r["recovered_peak_depth_m"] for r in rows}
    moved = any(d is not None and abs(d - 62.5) > 30 for d in depths.values())
    print("\n" + "=" * 66)
    print(f"¿Alguna palanca mueve la profundidad >30 m del piso somero? {'SÍ' if moved else 'NO'}")
    print("=" * 66)

    out = Path(__file__).resolve().parent / "wz_lever_probe_report.json"
    out.write_text(json.dumps({"true_depth_m": by, "rows": rows, "any_lever_moves": bool(moved)},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)
    return rows


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
