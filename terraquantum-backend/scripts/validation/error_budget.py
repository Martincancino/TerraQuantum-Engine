# -*- coding: utf-8 -*-
"""PARTE A — Presupuesto de error: ¿cuánto nos equivocamos HOY, y DÓNDE?

Barre regímenes (profundidad · cobertura · contraste · SNR · extensión del survey)
con VERDAD ANALÍTICA conocida (gravedad de forma cerrada de una esfera enterrada =
anti-inverse-crime: el dato NO se genera con el operador de la inversión) e invierte con
el MOTOR REAL. Mide, por caso: error de targeting HORIZONTAL, error de PROFUNDIDAD
(centroide y techo) y recuperación de DENSIDAD, contra la verdad.

Salida: tabla honesta `error × régimen` → dónde el producto sirve (targeting) y dónde
NO (profundidad en régimen profundo/disperso). Reproducible (semilla fija). Backend-only,
no toca el motor. Corre a demanda:

    python scripts/validation/error_budget.py            # smoke (baseline + 1 por eje)
    python scripts/validation/error_budget.py --full     # barrido completo
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.field_validation_service import estimate_location_error

BASE_DENSITY = 2.67   # t/m³ roca caja

# ── Malla FIJA (para que las diferencias de error vengan del RÉGIMEN, no de la malla) ──
BLOCK = 125.0
NX = NZ = 18          # 2250 m de lado
NY = 14               # 1750 m de profundidad (contiene el cuerpo más profundo con margen)
CUTOFF = 2600.0
MESH_CENTER = NX * BLOCK / 2.0   # 1125 m (centro horizontal del survey y del cuerpo)

DENSITY_MAX = BASE_DENSITY + 2.0
# Config IDÉNTICA al harness DO-27 validado (que dio horiz 53.7 m en F9): λ=1e-3, IRLS=2.
# (El operating point de campo 0.1 escala con √n → sobre-regulariza mallas grandes; se descartó.)
LAMBDA_GRAV = 1e-3
COMPACT_IRLS = 2


@dataclass
class Case:
    name: str
    axis: str                 # eje que se está variando
    depth_m: float = 400.0     # profundidad del centroide
    radius_m: float = 150.0
    delta_rho: float = 0.6     # contraste (t/m³)
    span_m: float = 1500.0     # extensión del survey (lado)
    n_side: int = 12           # estaciones por lado
    noise_mgal: float = 0.02
    seed: int = 20260723
    notes: str = ""


def _grid_centers_fortran(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _sphere_gy_ms2(sensors, x0, y0, z0, radius, delta_rho):
    """Componente vertical (profundidad↓) de la gravedad de una esfera (forma cerrada, sin malla)."""
    G = 6.67430e-11
    mass_kg = (delta_rho * 1000.0) * (4.0 / 3.0) * np.pi * radius ** 3
    dy = sensors[:, 1] - y0
    r3 = ((sensors[:, 0] - x0) ** 2 + dy ** 2 + (sensors[:, 2] - z0) ** 2) ** 1.5
    return -G * mass_kg * dy / r3


def run_case(c: Case) -> dict:
    rng = np.random.default_rng(c.seed)
    cx = cz = MESH_CENTER
    by = c.depth_m
    # Survey centrado sobre el cuerpo.
    half = c.span_m / 2.0
    axis = np.linspace(cx - half, cx + half, c.n_side)
    gx, gz = np.meshgrid(axis, axis, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    spacing = c.span_m / max(c.n_side - 1, 1)

    g_clean = _sphere_gy_ms2(sensors, cx, by, cz, c.radius_m, c.delta_rho)
    noise = c.noise_mgal * 1e-5
    g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
    sigma = max(noise, 1e-12)
    peak_mgal = float(np.max(np.abs(g_clean))) / 1e-5
    snr = peak_mgal / max(c.noise_mgal, 1e-9)

    x_c, y_c, z_c = _grid_centers_fortran(NX, NY, NZ, BLOCK)
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    meta: dict = {}
    rho, _score, misfit, _s = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=LAMBDA_GRAV, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        density_min=BASE_DENSITY, density_max=DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True,
        prune_observable_domain=True, regularization_norm="compact",
        compact_max_irls=COMPACT_IRLS, solver_meta=meta,
    )
    rho = np.asarray(rho, dtype=np.float64)

    loc = estimate_location_error(rho, x_c, y_c, z_c, (cx, by, cz), base_density=BASE_DENSITY)
    # Techo recuperado (celda fuerte más somera) vs techo verdadero.
    contrast = np.abs(rho - BASE_DENSITY)
    finite = np.isfinite(contrast)
    rec_top = None
    peak_depth = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        cmax = float(np.nanmax(contrast[finite]))
        strong = finite & (contrast > 0.5 * cmax)
        if np.any(strong):
            rec_top = float(np.min(y_c[strong]))
        # Profundidad del PICO (celda de máximo contraste) — más confiable que el centroide.
        ipk = int(np.nanargmax(np.where(finite, contrast, -np.inf)))
        peak_depth = float(y_c[ipk])
    true_top = by - c.radius_m
    # Recuperación de densidad: pico de contraste recuperado vs verdadero.
    rec_peak_contrast = float(np.nanmax(rho[finite] - BASE_DENSITY)) if np.any(finite) else 0.0

    return {
        "name": c.name, "axis": c.axis, "notes": c.notes,
        "regime": {
            "depth_m": c.depth_m, "radius_m": c.radius_m, "delta_rho": c.delta_rho,
            "span_m": c.span_m, "n_side": c.n_side, "n_stations": int(sensors.shape[0]),
            "spacing_m": round(spacing, 1), "noise_mgal": c.noise_mgal,
            "extent_over_depth": round(c.span_m / max(c.depth_m, 1.0), 2),
            "spacing_over_depth": round(spacing / max(c.depth_m, 1.0), 2),
            "peak_anomaly_mgal": round(peak_mgal, 3), "snr_peak": round(snr, 1),
        },
        "error": {
            "horizontal_m": loc.get("horizontal_error_m"),
            "depth_centroid_m": loc.get("depth_error_m"),
            "depth_peak_m": (None if peak_depth is None else round(abs(peak_depth - by), 1)),
            "top_depth_m": (None if rec_top is None else round(abs(rec_top - true_top), 1)),
            "recovered_depth_m": loc.get("recovered_y_m"),
            "recovered_peak_depth_m": (None if peak_depth is None else round(peak_depth, 1)),
            "true_depth_m": round(by, 1),
            "n_strong": loc.get("n_strong"),
            "density_recovered_t_m3": round(rec_peak_contrast, 3),
            "density_true_t_m3": c.delta_rho,
            "density_recovery_frac": round(rec_peak_contrast / max(c.delta_rho, 1e-9), 3),
            "misfit_pct": round(float(misfit), 3),
        },
    }


# ── Diseño del barrido (baseline + un eje a la vez) ─────────────────────────────
def build_cases(full: bool) -> List[Case]:
    base = Case("baseline", "baseline", notes="somero, buena cobertura, fuerte, limpio")
    cases = [base]
    # Profundidad (el límite clave).
    depths = [250, 400, 600, 900] if full else [600, 900]
    cases += [Case(f"depth_{d}m", "profundidad", depth_m=d,
                   notes=f"extent/depth={round(1500/d,2)}") for d in depths]
    # Cobertura (densidad de estaciones).
    sides = [(14, "densa"), (9, "media"), (6, "dispersa")] if full else [(6, "dispersa")]
    cases += [Case(f"coverage_{n}", "cobertura", n_side=n, notes=f"cobertura {lbl}") for n, lbl in sides]
    # Contraste.
    contrasts = [0.4, 0.2] if full else [0.2]
    cases += [Case(f"contrast_{c}", "contraste", delta_rho=c, notes=f"Δρ débil {c}") for c in contrasts]
    # SNR.
    noises = [0.05, 0.15] if full else [0.15]
    cases += [Case(f"noise_{n}", "SNR", noise_mgal=n, notes=f"ruido {n} mGal") for n in noises]
    # Extensión del survey (regla: extent ≥ 2× profundidad).
    spans = [1200, 800] if full else [800]
    cases += [Case(f"span_{s}m", "extensión", span_m=s, depth_m=400,
                   notes=f"extent/depth={round(s/400,2)}") for s in spans]
    # Compuesto peor-caso (régimen LdM: profundo + disperso + ruidoso).
    cases.append(Case("worst_ldm_like", "compuesto", depth_m=900, n_side=6, noise_mgal=0.05,
                      notes="profundo + disperso + ruidoso (régimen LdM)"))
    return cases


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    full = "--full" in sys.argv
    cases = build_cases(full)
    print(f"PRESUPUESTO DE ERROR — {'COMPLETO' if full else 'smoke'} — {len(cases)} casos "
          f"(malla fija {NX}×{NY}×{NZ}@{BLOCK:.0f}m)")
    results = []
    t0 = time.time()
    for i, c in enumerate(cases, 1):
        tc = time.time()
        r = run_case(c)
        r["elapsed_s"] = round(time.time() - tc, 1)
        results.append(r)
        e, rg = r["error"], r["regime"]
        print(f"[{i:>2}/{len(cases)}] {c.name:16s} ({c.axis:11s}) "
              f"horiz={e['horizontal_m']}m prof={e['depth_centroid_m']}m "
              f"techo={e['top_depth_m']}m ρ={e['density_recovery_frac']} "
              f"| depth={rg['depth_m']:.0f} spc/dep={rg['spacing_over_depth']} SNR={rg['snr_peak']} "
              f"({r['elapsed_s']}s)", flush=True)

    report = {
        "kind": "error_budget_partA", "full": full,
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_m": BLOCK, "cutoff_m": CUTOFF},
        "base_density": BASE_DENSITY, "n_cases": len(cases),
        "elapsed_s": round(time.time() - t0, 1), "cases": results,
    }
    out = Path(__file__).resolve().parent / "error_budget_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}  ({report['elapsed_s']}s)")
    return report


if __name__ == "__main__":
    main()
