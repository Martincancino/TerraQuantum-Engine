# -*- coding: utf-8 -*-
"""PARTE B · Punto 1 — ¿Qué método da una profundidad CONFIABLE para el régimen profundo?

Euler (ventana móvil) falló en profundo con la config anterior (ventana chica + umbral de
señal permisivo → profundidades espurias someras). Aquí se comparan, sobre el MISMO cuerpo
sintético a varias profundidades verdaderas, estimadores INDEPENDIENTES de la inversión:

  - Euler-grav (SI=2) / Euler-mag (SI=3) AFINADO: ventana grande (≈ la longitud de onda de
    la anomalía) + umbral de señal ESTRICTO (solo el pico, no el ruido de campo lejano).
  - Espectro radial de potencia (F2B): profundidad de ensamble profundo.

Dato generado ANALÍTICAMENTE (gravedad = esfera de forma cerrada; magnetismo = dipolo de
forma cerrada) → exacto, sin malla, sin memoria, anti-inverse-crime total. Sólo importa la
FORMA de la anomalía (Euler/espectro son escala-invariantes). Rápido.

    python scripts/validation/depth_source_comparison.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.potential_field_grid_service import ScatteredGrid
from services.euler_spectral_service import euler_deconvolution, radial_power_spectrum

DEPTHS = [300.0, 500.0, 700.0]
SPAN = 2000.0
N_SIDE = 40                 # survey denso (Euler/espectro necesitan buen muestreo)
RADIUS = 150.0
INCL, DECL = -55.0, 3.0
NOISE_FRAC = 0.02           # ruido = 2% del pico


def _survey():
    a = np.linspace(-SPAN / 2, SPAN / 2, N_SIDE)
    gx, gz = np.meshgrid(a, a, indexing="ij")   # x=Este, z=Norte; cuerpo en (0,depth,0)
    return gx, gz


def _grav_sphere(gx, gz, depth):
    """g_y (vertical) de una esfera, forma cerrada. Unidades arbitrarias (escala-invariante)."""
    r2 = gx ** 2 + depth ** 2 + gz ** 2
    return depth / r2 ** 1.5     # ∝ G·M·Δy/r³, con Δy = depth


def _mag_dipole(gx, gz, depth):
    """TMI de una esfera magnetizada por inducción (dipolo), forma cerrada. b̂ del campo."""
    I, D = np.radians(INCL), np.radians(DECL)
    b = np.array([np.cos(I) * np.cos(D), np.sin(I), np.cos(I) * np.sin(D)])  # (N, down, E)
    Rx, Ry, Rz = gx, -depth * np.ones_like(gx), gz     # sensor(y=0) − cuerpo(y=depth)
    r = np.sqrt(Rx ** 2 + Ry ** 2 + Rz ** 2)
    cospsi = (Rx * b[0] + Ry * b[1] + Rz * b[2]) / r
    return (3.0 * cospsi ** 2 - 1.0) / r ** 3          # ∝ ΔT (forma correcta)


def _grid(vals):
    n = vals.shape[0]
    dx = SPAN / (n - 1)
    v = vals.copy()
    rng = np.random.default_rng(7)
    v = v + NOISE_FRAC * float(np.max(np.abs(v))) * rng.standard_normal(v.shape)
    return ScatteredGrid(values=v, x0=-SPAN / 2, y0=-SPAN / 2, dx=dx, dy=dx,
                         nx=n, ny=n, inside_hull=np.ones((n, n), dtype=bool))


def _euler(vals, si):
    sg = _grid(vals)
    try:
        er = euler_deconvolution(sg, structural_index=si, window_cells=20, step_cells=2,
                                 max_depth_m=1500.0, max_rel_uncertainty=0.30,
                                 min_signal_percentile=88.0)
    except Exception as e:
        return None, f"error:{str(e)[:40]}"
    ds = [s.depth_m for s in er.solutions]
    if not ds:
        return None, f"0/{er.n_windows}"
    return float(np.median(ds)), f"{er.n_accepted}acc p50={np.median(ds):.0f} [{min(ds):.0f},{max(ds):.0f}]"


def _spectral_deep(vals):
    try:
        r = radial_power_spectrum(_grid(vals))
    except Exception:
        return None
    return r.get("ensemble_depth_deep_m")


def run():
    gx, gz = _survey()
    rows = []
    for d in DEPTHS:
        g = _grav_sphere(gx, gz, d)
        m = _mag_dipole(gx, gz, d)
        eg, dg = _euler(g, 2.0)
        em, dm = _euler(m, 3.0)
        sg = _spectral_deep(g)
        sm = _spectral_deep(m)
        row = {"true_depth_m": d,
               "euler_grav": None if eg is None else round(eg, 0),
               "euler_mag": None if em is None else round(em, 0),
               "spectral_grav": None if sg is None else round(sg, 0),
               "spectral_mag": None if sm is None else round(sm, 0)}
        rows.append(row)
        print(f"verdad {d:>4.0f} m | Euler-grav={row['euler_grav']} ({dg}) | "
              f"Euler-mag={row['euler_mag']} ({dm}) | esp-grav={row['spectral_grav']} | "
              f"esp-mag={row['spectral_mag']}", flush=True)

    out = Path(__file__).resolve().parent / "depth_source_comparison_report.json"
    out.write_text(json.dumps({"rows": rows, "config": {"span_m": SPAN, "n_side": N_SIDE,
                   "radius_m": RADIUS, "incl": INCL}}, indent=2, ensure_ascii=False), encoding="utf-8")
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
