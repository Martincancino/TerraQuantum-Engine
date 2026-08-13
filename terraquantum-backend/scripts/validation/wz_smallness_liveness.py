# -*- coding: utf-8 -*-
"""PUNTO 4 (docs/05 Parte B) — AGREGADO 1: ¿la perilla del W_z-fix está VIVA?

El `depth_beta` histórico es INERTE (la normalización de columnas Ws lo cancela;
medido en F9). El fix (opt-in `smallness_depth_beta`) pesa el BLOQUE SMALLNESS `_ws`,
que Ws NO reabsorbe. ANTES de medir ganancia hay que confirmar dos cosas, o el fix
cae en la misma trampa:

  (A) PERILLA VIVA: el mismo sintético profundo con exponente 0 vs 2 debe dar una
      profundidad recuperada DISTINTA. Si sale byte-idéntico → el fix está en el
      lugar equivocado; se reubica, no se sigue.
  (B) BLOQUE ACTIVO: si el smallness es despreciable frente a la suavidad
      (Laplaciano), reponderarlo no hace nada. Se reporta `smallness/smoothness`.

Esfera analítica enterrada (forma cerrada = anti-inverse-crime) invertida con el
MOTOR REAL. NO se ajusta nada; se reporta lo que salga.

    python scripts/validation/wz_smallness_liveness.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.error_budget as EB  # reutiliza malla/esfera/config validada
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.field_validation_service import estimate_location_error

# Caso PROFUNDO donde el sesgo somero es fuerte (error_budget: depth_600 apila a ~62 m).
DEPTH_M = 600.0
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02
BETAS = [0.0, 2.0, -2.0]   # 0 = OFF; ±2 = perilla en ambos signos


def _solve(sensors, g_obs, sigma, sdb, by):
    x_c, y_c, z_c = EB._grid_centers_fortran(EB.NX, EB.NY, EB.NZ, EB.BLOCK)
    inv = GravimetryInversion(EB.NX, EB.NY, EB.NZ, EB.BLOCK, base_density=EB.BASE_DENSITY)
    fwd = GravimetryForward(EB.BLOCK, EB.BLOCK, EB.BLOCK, cutoff_radius=EB.CUTOFF)
    meta: dict = {}
    cx = cz = EB.MESH_CENTER
    rho, _s, misfit, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=EB.LAMBDA_GRAV, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        density_min=EB.BASE_DENSITY, density_max=EB.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=EB.COMPACT_IRLS, smallness_depth_beta=sdb,
        solver_meta=meta,
    )
    rho = np.asarray(rho, dtype=np.float64)
    loc = estimate_location_error(rho, x_c, y_c, z_c, (cx, by, cz), base_density=EB.BASE_DENSITY)
    contrast = np.abs(rho - EB.BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(y_c[ipk])
    return {
        "beta": sdb,
        "recovered_peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "recovered_centroid_m": loc.get("recovered_y_m"),
        "depth_err_centroid_m": loc.get("depth_error_m"),
        "depth_err_peak_m": None if peak_depth is None else round(abs(peak_depth - by), 1),
        "horizontal_m": loc.get("horizontal_error_m"),
        "misfit_pct": round(float(misfit), 3),
        "chi2_final": meta.get("chi2_final"),
        "smallness_over_smoothness": meta.get("smallness_over_smoothness"),
        "smallness_block_fro": meta.get("smallness_block_fro"),
        "smoothness_block_fro": meta.get("smoothness_block_fro"),
    }


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

    print(f"Esfera a {by:.0f} m (techo real {by-RADIUS_M:.0f} m) · malla {EB.NX}x{EB.NY}x{EB.NZ}"
          f"@{EB.BLOCK:.0f} m · {sensors.shape[0]} estaciones\n", flush=True)
    rows = []
    for sdb in BETAS:
        t = time.time()
        r = _solve(sensors, g_obs, sigma, sdb, by)
        r["s"] = round(time.time() - t, 1)
        rows.append(r)
        sos = r["smallness_over_smoothness"]
        sos_s = "n/a" if sos is None else f"{sos:.3e}"
        print(f"beta={sdb:+.1f} | prof_pico={r['recovered_peak_depth_m']} m "
              f"(err {r['depth_err_peak_m']} m) | horiz={r['horizontal_m']} m | "
              f"misfit={r['misfit_pct']}% chi2={r['chi2_final']} | "
              f"smallness/smoothness={sos_s} ({r['s']}s)", flush=True)

    # ── Veredicto de PERILLA VIVA ────────────────────────────────────────────
    d0 = next(r for r in rows if r["beta"] == 0.0)["recovered_peak_depth_m"]
    d2 = next(r for r in rows if r["beta"] == 2.0)["recovered_peak_depth_m"]
    dm = next(r for r in rows if r["beta"] == -2.0)["recovered_peak_depth_m"]
    diff2 = None if (d0 is None or d2 is None) else round(abs(d2 - d0), 2)
    diffm = None if (d0 is None or dm is None) else round(abs(dm - d0), 2)
    alive = (diff2 is not None and diff2 > 1.0) or (diffm is not None and diffm > 1.0)

    print("\n" + "=" * 66)
    print(f"PERILLA VIVA: {'SÍ' if alive else 'NO'}  "
          f"(Δprof beta0→beta+2 = {diff2} m; beta0→beta-2 = {diffm} m)")
    sos0 = next(r for r in rows if r["beta"] == 0.0)["smallness_over_smoothness"]
    print(f"BLOQUE SMALLNESS ACTIVO: smallness/smoothness (beta0) = "
          f"{'n/a' if sos0 is None else f'{sos0:.3e}'}")
    if not alive:
        print("  ⚠ El fix es INERTE en esta config (misma trampa que depth_beta). "
              "REUBICAR, no seguir.")
    print("=" * 66)

    out = Path(__file__).resolve().parent / "wz_smallness_liveness_report.json"
    out.write_text(json.dumps({
        "case": {"depth_m": by, "radius_m": RADIUS_M, "delta_rho": DELTA_RHO,
                 "span_m": SPAN_M, "n_side": N_SIDE, "noise_mgal": NOISE_MGAL},
        "rows": rows, "knob_alive": bool(alive),
        "delta_depth_beta_pos_m": diff2, "delta_depth_beta_neg_m": diffm,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
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
