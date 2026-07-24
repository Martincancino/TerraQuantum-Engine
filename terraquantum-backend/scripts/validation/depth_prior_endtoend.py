# -*- coding: utf-8 -*-
"""PARTE B · Punto 2 — Cadena COMPLETA con componentes de producción, sobre verdad conocida:
   datos → ESPECTRO radial (fuente de profundidad, F2B) → prior → gravedad mejor.

Cierra la cadena que Euler no pudo: el espectro radial SÍ da una profundidad profunda usable
(Punto 1). Aquí, sobre cuerpos sintéticos a profundidad CONOCIDA (300/500/700 m), se:
  1) genera la gravedad (esfera analítica, sin malla → sin memoria),
  2) se estima la profundidad con el servicio ESPECTRAL REAL,
  3) se deriva un piso conservador (recommend_depth_floor) y se arma el prior (depth_prior_service),
  4) se invierte con el MOTOR con y sin prior, y se mide el error de profundidad vs la verdad.

Todo con componentes de producción (espectro F2B + depth_prior_service + motor). NO se ajusta.

    python scripts/validation/depth_prior_endtoend.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.multiphysics_gain as MP
from scripts.validation.depth_prior_experiment import solve_grav_prior
from services.potential_field_grid_service import ScatteredGrid
from services.euler_spectral_service import radial_power_spectrum
from services.depth_prior_service import build_depth_floor_prior, recommend_depth_floor

SPAN = 2000.0
N_SIDE = 24
DEPTHS = [300.0, 500.0, 700.0]
G = 6.67430e-11


def _analytic_grav(sensors, depth):
    M = (MP.DELTA_RHO * 1000.0) * (4.0 / 3.0) * np.pi * MP.BODY_RADIUS ** 3
    dx = sensors[:, 0] - MP.CENTER
    dy = sensors[:, 1] - depth
    dz = sensors[:, 2] - MP.CENTER
    r3 = (dx * dx + dy * dy + dz * dz) ** 1.5
    return -G * M * dy / r3          # m/s² (dy<0 → positivo)


def _survey():
    half = SPAN / 2.0
    a = np.linspace(MP.CENTER - half, MP.CENTER + half, N_SIDE)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    return np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)


def _spectral_depth(g_obs):
    n = int(round(np.sqrt(g_obs.size)))
    vals = (g_obs / 1e-5).reshape(n, n)
    dx = SPAN / (n - 1)
    sg = ScatteredGrid(values=vals, x0=MP.CENTER - SPAN / 2, y0=MP.CENTER - SPAN / 2,
                       dx=dx, dy=dx, nx=n, ny=n, inside_hull=np.ones((n, n), dtype=bool))
    try:
        return radial_power_spectrum(sg).get("ensemble_depth_deep_m")
    except Exception:
        return None


def run():
    sensors = _survey()
    rng = np.random.default_rng(11)
    rows = []
    for d in DEPTHS:
        MP.BODY_DEPTH = d
        g_clean = _analytic_grav(sensors, d)
        sig = 0.02 * float(np.std(g_clean))
        g_obs = g_clean + sig * rng.standard_normal(g_clean.size)

        z_spec = _spectral_depth(g_obs)
        # Piso conservador: el espectro subestima ~15%, así que corregimos ×1.15 y luego 0.7 de margen.
        floor = None if z_spec is None else recommend_depth_floor(1.15 * z_spec, safety_fraction=0.7)

        t = time.time()
        base = solve_grav_prior(g_obs, sensors, max(sig, 1e-12), depth_floor=None)
        primed = solve_grav_prior(g_obs, sensors, max(sig, 1e-12), depth_floor=floor)
        prior = build_depth_floor_prior(*_cols(), MP.BASE_DENSITY, floor, source="espectro") if floor else None

        row = {
            "true_depth_m": d,
            "spectral_depth_m": None if z_spec is None else round(z_spec, 0),
            "floor_m": None if floor is None else round(floor, 0),
            "err_prof_baseline_m": base["depth_centroid_m"],
            "err_prof_con_prior_m": primed["depth_centroid_m"],
            "horiz_baseline_m": base["horizontal_m"],
            "horiz_con_prior_m": primed["horizontal_m"],
            "n_columnas_ancladas": None if prior is None else prior.n_columns,
            "s": round(time.time() - t, 1),
        }
        rows.append(row)
        print(f"verdad {d:>4.0f} m | espectro={row['spectral_depth_m']} → piso={row['floor_m']} | "
              f"err_prof {row['err_prof_baseline_m']}→{row['err_prof_con_prior_m']} m | "
              f"horiz {row['horiz_baseline_m']}→{row['horiz_con_prior_m']} m  ({row['s']}s)", flush=True)

    out = Path(__file__).resolve().parent / "depth_prior_endtoend_report.json"
    out.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)
    return rows


def _cols():
    x_c, y_c, z_c = MP._centers(MP.NX, MP.NY, MP.NZ, MP.BLOCK)
    return x_c, z_c


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
