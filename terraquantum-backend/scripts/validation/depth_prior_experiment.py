# -*- coding: utf-8 -*-
"""PARTE B — ¿Un prior de profundidad (mag/Euler) arregla la profundidad de la gravedad?

Hipótesis: la gravedad es ambigua en profundidad y elige la solución SOMERA. Si una física
independiente (deconvolución de Euler, magnetometría) dice "el cuerpo NO está somero, está
a ~Z", se puede RESTRINGIR la inversión gravimétrica a poner masa por debajo de ese
horizonte → la masa va a donde el dato la soporta, más profundo.

Mecanismo (usa hooks EXISTENTES del motor, no reescribe física): anclar a densidad-base
(contraste 0) todas las celdas por ENCIMA del horizonte estimado (ancla dura). Así el
solver no puede apilar masa somera.

Mide, sobre el mismo cuerpo del banco multi-física (500 m):
  - grav-sola (baseline, sin prior)
  - + prior PERFECTO (Euler-exacto: horizonte 350 m = techo verdadero)
  - + prior CONSERVADOR (Euler a 300 m)
  - + prior IMPERFECTO del mag (mag recuperó ~218 m → horizonte 200 m)
  - + prior MALO (horizonte 100 m, casi sin restricción) — control

NO se ajusta nada. Si el prior perfecto NO baja el error de profundidad, la hipótesis
está refutada y se documenta. Regla de oro: medir antes de creer.

    python scripts/validation/depth_prior_experiment.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.multiphysics_gain as MP
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.field_validation_service import estimate_location_error


def _shallow_floor_anchor(depth_floor: float) -> np.ndarray:
    """Ancla dura a densidad-base (contraste 0) todas las celdas por ENCIMA de depth_floor,
    en cada columna (x,z) de la malla. Es el prior 'no hay masa somera'."""
    x_c, y_c, z_c = MP._centers(MP.NX, MP.NY, MP.NZ, MP.BLOCK)
    cols = np.unique(np.column_stack([x_c, z_c]), axis=0)
    rows = [[float(x), float(z), 0.0, float(depth_floor), MP.BASE_DENSITY] for x, z in cols]
    return np.asarray(rows, dtype=np.float64)


def solve_grav_prior(g_obs, sensors, sigma, depth_floor=None):
    x_c, y_c, z_c = MP._centers(MP.NX, MP.NY, MP.NZ, MP.BLOCK)
    inv = GravimetryInversion(MP.NX, MP.NY, MP.NZ, MP.BLOCK, base_density=MP.BASE_DENSITY)
    fwd = GravimetryForward(MP.BLOCK, MP.BLOCK, MP.BLOCK, cutoff_radius=MP.CUTOFF)
    boreholes = None if depth_floor is None else _shallow_floor_anchor(depth_floor)
    meta: dict = {}
    rho, _s, mf, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=MP.LAMBDA_G, alpha_spatial=1.0, forward_model=fwd,
        sensor_coords=sensors, x_c=x_c, z_c=z_c, density_min=MP.BASE_DENSITY, density_max=MP.DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True, prune_observable_domain=True,
        regularization_norm="compact", compact_max_irls=MP.IRLS,
        boreholes=boreholes, anchor_mode=("hard" if boreholes is not None else "soft"),
        solver_meta=meta)
    rho = np.nan_to_num(np.asarray(rho), nan=MP.BASE_DENSITY)
    loc = estimate_location_error(rho, x_c, y_c, z_c, (MP.CENTER, MP.BODY_DEPTH, MP.CENTER),
                                  base_density=MP.BASE_DENSITY)
    contrast = np.abs(rho - MP.BASE_DENSITY)
    finite = np.isfinite(contrast)
    peak = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        peak = float(y_c[int(np.nanargmax(np.where(finite, contrast, -np.inf)))])
    return {
        "horizontal_m": loc.get("horizontal_error_m"),
        "depth_centroid_m": loc.get("depth_error_m"),
        "recovered_depth_m": loc.get("recovered_y_m"),
        "depth_peak_m": None if peak is None else round(abs(peak - MP.BODY_DEPTH), 1),
        "n_anchored": meta.get("n_anchored_voxels"),
        "misfit_pct": round(float(mf), 2),
    }


CASES = [
    ("baseline (sin prior)", None),
    ("prior EULER-perfecto (piso 350 m = techo real)", 350.0),
    ("prior EULER-conservador (piso 300 m)", 300.0),
    ("prior MAG-imperfecto (piso 200 m)", 200.0),
    ("prior MALO (piso 100 m, control)", 100.0),
]


def run():
    sensors, g_obs, tmi, sig_g, sig_m, pm, pn = MP._make_data()
    print(f"Cuerpo a {MP.BODY_DEPTH:.0f} m (techo real {MP.BODY_DEPTH-MP.BODY_RADIUS:.0f} m) · "
          f"grav-sola sesga somero → veamos si el prior lo baja\n", flush=True)
    res = {}
    for label, floor in CASES:
        t = time.time()
        m = solve_grav_prior(g_obs, sensors, sig_g, depth_floor=floor)
        m["s"] = round(time.time() - t, 1)
        res[label] = m
        print(f"{label:48s} horiz={m['horizontal_m']:>6}m  err_prof={m['depth_centroid_m']:>6}m  "
              f"rec_prof={m['recovered_depth_m']:>6}m  ancladas={m['n_anchored']}  ({m['s']}s)", flush=True)

    out = Path(__file__).resolve().parent / "depth_prior_report.json"
    out.write_text(json.dumps({"body_depth_m": MP.BODY_DEPTH, "results": res}, indent=2,
                              ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)
    return res


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
