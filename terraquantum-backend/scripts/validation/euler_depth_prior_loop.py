# -*- coding: utf-8 -*-
"""PARTE B — Cadena COMPLETA con componentes de producción:
   datos → Euler REAL (F2B) → profundidad independiente → prior → gravedad mejor.

Cierra el círculo del experimento de prior: en vez de darle a mano el horizonte de
profundidad, se lo pedimos al servicio Euler de F2B (`euler_deconvolution`) sobre los
MISMOS datos gravimétricos sintéticos, y se usa esa profundidad como prior. Demuestra
que la mejora es REAL end-to-end, no un número inventado.

    python scripts/validation/euler_depth_prior_loop.py
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
from services.euler_spectral_service import euler_deconvolution


def _grid_from_survey(g_obs):
    """El survey 12×12 YA es una grilla regular → ScatteredGrid directo (gravedad en mGal)."""
    n = int(round(np.sqrt(g_obs.size)))
    vals = (g_obs / 1e-5).reshape(n, n)          # m/s² → mGal (Euler es escala-invariante igual)
    half = MP.SPAN / 2.0
    dx = MP.SPAN / (n - 1)
    x0 = MP.CENTER - half
    return ScatteredGrid(values=vals, x0=x0, y0=x0, dx=dx, dy=dx, nx=n, ny=n,
                         inside_hull=np.ones((n, n), dtype=bool))


def run():
    # Euler necesita una grilla más DENSA que la que basta para invertir → survey fino (24×24).
    MP.N_SIDE = 24
    sensors, g_obs, tmi, sig_g, sig_m, pm, pn = MP._make_data()
    print(f"Cuerpo verdadero: profundidad centro {MP.BODY_DEPTH:.0f} m, techo {MP.BODY_DEPTH-MP.BODY_RADIUS:.0f} m "
          f"· survey {MP.N_SIDE}×{MP.N_SIDE}\n")

    def _euler_depth(field_vals, si, label):
        sg = _grid_from_survey(field_vals)
        er = euler_deconvolution(sg, structural_index=si, window_cells=8, step_cells=1,
                                 max_depth_m=1200.0, max_rel_uncertainty=0.5, min_signal_percentile=50.0)
        ds = [s.depth_m for s in er.solutions]
        if ds:
            zmed = float(np.median(ds))
            print(f"[EULER {label} SI={si}] {er.n_accepted}/{er.n_windows} aceptadas · "
                  f"z_mediana = {zmed:.0f} m (verdad 500 m) · rango [{min(ds):.0f}, {max(ds):.0f}]")
            return zmed
        print(f"[EULER {label} SI={si}] sin soluciones ({er.n_windows} ventanas)")
        return None

    # 1) Euler sobre GRAVEDAD (SI=2) y sobre MAGNETOMETRÍA (SI=3, dipolo) — comparar fuentes.
    z_grav = _euler_depth(g_obs, 2.0, "GRAV")
    z_mag = _euler_depth(tmi, 3.0, "MAG")
    euler_depth = z_mag if z_mag is not None else z_grav   # el mag es la fuente físicamente correcta

    # 2) Prior derivado de Euler: horizonte = fracción de la profundidad de Euler (techo estimado).
    res = {"euler_depth_m": euler_depth, "true_depth_m": MP.BODY_DEPTH, "cases": {}}
    base = solve_grav_prior(g_obs, sensors, sig_g, depth_floor=None)
    res["cases"]["baseline"] = base
    print(f"\n{'baseline (sin prior)':40s} err_prof={base['depth_centroid_m']}m horiz={base['horizontal_m']}m")

    if euler_depth is not None:
        for frac in (0.7, 1.0):
            floor = round(frac * euler_depth, 1)
            t = time.time()
            m = solve_grav_prior(g_obs, sensors, sig_g, depth_floor=floor)
            m["s"] = round(time.time() - t, 1)
            res["cases"][f"euler_floor_{frac}"] = {**m, "floor_m": floor}
            print(f"{'prior Euler (piso '+str(floor)+' m = '+str(frac)+'×z_euler)':40s} "
                  f"err_prof={m['depth_centroid_m']}m horiz={m['horizontal_m']}m")

    out = Path(__file__).resolve().parent / "euler_depth_prior_loop_report.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}")
    return res


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
