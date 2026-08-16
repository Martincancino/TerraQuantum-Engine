# -*- coding: utf-8 -*-
"""FASE 7 — ¿el χ² que el escáner de λ promete es el χ² que el solve consigue?

La auditoría 06 §9D.2 dejó esta medición escrita como pendiente y la llamó
«verificación decisiva y barata (una tarde)»:

  «instrumentar una corrida para registrar el χ² que el escáner predice para el λ
   elegido y el χ² que el solve consigue con ese mismo λ. Si divergen, está
   confirmado.»

Nadie la corrió. Este script la corre.

Contexto que hay que tener presente para no re-litigar lo ya resuelto: la propia
auditoría RECTIFICÓ el hallazgo H-25 al comprobar que **producción no usa**
`select_lambda_chi2_target` — el Morozov de producción escanea con el solver real
(`geophysics_service._solve_full_grid`) y adopta su solución, que es la forma
correcta. Lo que queda vivo es el selector como **instrumento de diagnóstico**, y
un instrumento que mide con el operador equivocado es una trampa, no un
instrumento. Esta sonda pone el número a esa trampa.

Qué comparaba, y qué encontró (medición del 2026-08-15, ANTES del arreglo):

  ESCÁNER  A = [Wd·G·Ws ; λ_sp·diag(w_reg)·L·Ws ; diag(λ·w_reg)·Ws]   σ adaptativo cableado
  SOLVER   A = [Wd·G·Ws ; λ_sp·L·Ws             ; diag(λ_eff)     ]   σ del llamador

Cuatro diferencias, no una: (1) el escáner pesaba el Laplaciano por `w_reg` y el
solver no; (2) su smallness era `diag(λ·w_reg)·Ws` —espacio FÍSICO, relajada con
la profundidad— y la del solver es identidad en `m̃`; (3) usaba λ crudo y el solver
`λ·√(n_active/256)`; (4) calculaba su χ² con un σ distinto del que usa el solve, y
χ² es literalmente `Σ(r/σ)²/n`.

    prof     χ² prometido   χ² real del solve      ratio     ¿acertó el λ?
    150 m       2,084             48,53             23×           NO
    350 m       0,444            128,5             289×           NO
    550 m       0,0724           165,7           2.290×           NO
    750 m       0,0161           204,5          12.700×           NO

El error CRECE con la profundidad —justo donde los dos funcionales más difieren—,
que es el mecanismo que §9D.2 dejó planteado como hipótesis no descartada.

DESPUÉS del arreglo de la Fase 7 (los cuatro puntos corregidos): ratio 1,12–1,70 y
**4/4** en la elección de λ. Y con el box petrofísico ABIERTO —el brazo de control
que aísla la única diferencia que queda, porque el escáner no modela bounds— el
ratio es **1,0000 a las cuatro profundidades**: la identidad es exacta, y lo que
resta es el bound, no el funcional.

Uso:
    python scripts/validation/fase7_lambda_identity_probe.py
    python scripts/validation/fase7_lambda_identity_probe.py --json salida.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion  # noqa: E402

NX = NZ = 10
NY = 10
BLOCK = 100.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 1.5
ALPHA_SPATIAL = 1.0
CUTOFF = 4000.0
NOISE_PCT = 0.02


def _centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _case(depth_m: float, seed: int = 20260815):
    """Cuerpo cúbico a `depth_m` de profundidad + survey en superficie."""
    rng = np.random.default_rng(seed)
    x_c, y_c, z_c = _centers(NX, NY, NZ, BLOCK)
    cx = cz = NX * BLOCK / 2.0
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 9)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)

    contrast = np.zeros(x_c.size, dtype=np.float64)
    body = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
            & (np.abs(y_c - depth_m) <= BLOCK))
    contrast[body] = 0.8
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast).ravel()
    amp = float(np.max(np.abs(g)))
    noise_floor = NOISE_PCT * amp
    g = g + noise_floor * rng.standard_normal(g.size)
    return x_c, y_c, z_c, sensors, g, noise_floor, int(np.sum(body))


def _run_depth(depth_m: float) -> dict:
    x_c, y_c, z_c, sensors, g_obs, nf, n_body = _case(depth_m)
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)

    candidatos = [1e-2, 3.16e-2, 1e-1, 3.16e-1, 1.0, 3.16, 10.0]
    escaner = inv.select_lambda_chi2_target(
        g_observed=g_obs, y_c=y_c, forward_model=fwd, sensor_coords=sensors,
        x_c=x_c, z_c=z_c, lambda_candidates=candidatos, chi2_target=1.0,
        alpha_spatial=ALPHA_SPATIAL,
        # El MISMO sigma que el solve: chi² es Σ(r/σ)²/n, así que comparar dos chi²
        # calculados con sigmas distintos no mide el funcional, mide el sigma.
        noise_floor=nf, noise_pct=NOISE_PCT,
    )
    lam = float(escaner["lambda_selected"])
    chi2_prometido = float(escaner["chi2_achieved"])

    def _solve_chi2(_lam, dmin, dmax):
        meta: dict = {}
        inv.solve_inversion_lsqr(
            g_obs, None, y_c, lambda_mag=_lam, alpha_spatial=ALPHA_SPATIAL,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            density_min=dmin, density_max=dmax,
            noise_floor=nf, noise_pct=NOISE_PCT, solver_meta=meta,
            prune_observable_domain=True, regularization_norm="L2",
            detect_outliers=False,
        )
        return float(meta.get("chi2_final", float("nan")))

    chi2_real = _solve_chi2(lam, BASE_DENSITY, DENSITY_MAX)
    # Brazo de control: el MISMO solve con el box petrofísico abierto. El escáner no
    # modela bounds, así que ésta es la única diferencia que le queda al funcional;
    # si el ratio de este brazo no da 1, la divergencia NO es el bound y hay otra
    # causa que buscar. (Medido 2026-08-15: da 1,0000 a las cuatro profundidades.)
    chi2_real_sin_box = _solve_chi2(lam, -1e6, 1e6)

    # Y el χ² que el solve consigue con CADA candidato: dice si el λ elegido por el
    # escáner es siquiera el mejor del conjunto para el solver real.
    barrido = []
    for c in candidatos:
        m2: dict = {}
        inv.solve_inversion_lsqr(
            g_obs, None, y_c, lambda_mag=c, alpha_spatial=ALPHA_SPATIAL,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            density_min=BASE_DENSITY, density_max=DENSITY_MAX,
            noise_floor=nf, noise_pct=NOISE_PCT, solver_meta=m2,
            prune_observable_domain=True, regularization_norm="L2",
            detect_outliers=False,
        )
        barrido.append({"lambda": float(c), "chi2_solver": float(m2.get("chi2_final", float("nan")))})

    mejor_real = min(barrido, key=lambda t: abs(np.log10(max(t["chi2_solver"], 1e-30))))
    ratio = (chi2_real / chi2_prometido) if chi2_prometido > 0 else float("nan")
    ratio_sin_box = ((chi2_real_sin_box / chi2_prometido)
                     if chi2_prometido > 0 else float("nan"))
    return {
        "depth_m": depth_m,
        "n_body_cells": n_body,
        "lambda_escaner": lam,
        "chi2_prometido_por_escaner": chi2_prometido,
        "chi2_real_del_solve": chi2_real,
        "ratio_real_sobre_prometido": ratio,
        "chi2_real_sin_box": chi2_real_sin_box,
        "ratio_sin_box": ratio_sin_box,
        "lambda_optimo_del_solver_real": mejor_real["lambda"],
        "chi2_en_ese_lambda": mejor_real["chi2_solver"],
        "el_escaner_acerto_el_lambda": bool(
            abs(np.log10(lam / mejor_real["lambda"])) < 1e-9
        ),
        "barrido_solver": barrido,
        "trials_escaner": [
            {"lambda": t["lambda"], "chi2_escaner": t["chi2_final"]}
            for t in escaner["trials"]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=str, default=None, help="ruta del informe JSON")
    ap.add_argument("--depths", type=float, nargs="*", default=[150.0, 350.0, 550.0, 750.0])
    args = ap.parse_args()

    # Aquí había un `os.environ.setdefault("TQ_LOG_LEVEL", "WARNING")`. El gate de
    # superficie de configuración de la Fase 5 lo cazó: **ningún otro sitio del
    # backend lee esa variable**, así que era una perilla que prometía un control
    # inexistente — exactamente el patrón que esa fase fue a buscar. Se borra en vez
    # de declararse: si no vale la pena declararla, tampoco vale la pena leerla.
    filas = [_run_depth(d) for d in args.depths]

    # ASCII a proposito: la consola de Windows (cp1252) no imprime lambda ni chi.
    print("\n" + "=" * 96)
    print("FASE 7 - identidad chi2 escaner(select_lambda_chi2_target) vs solve_inversion_lsqr")
    print("=" * 96)
    print(f"{'prof (m)':>9} {'lam escan':>11} {'chi2 prom':>11} {'chi2 real':>11} "
          f"{'ratio':>10} {'ratio s/box':>12} {'lam optimo':>14} {'acerto?':>9}")
    for f in filas:
        print(f"{f['depth_m']:9.0f} {f['lambda_escaner']:11.3e} "
              f"{f['chi2_prometido_por_escaner']:11.4g} {f['chi2_real_del_solve']:11.4g} "
              f"{f['ratio_real_sobre_prometido']:10.3g} "
              f"{f['ratio_sin_box']:12.4f} "
              f"{f['lambda_optimo_del_solver_real']:14.3e} "
              f"{('si' if f['el_escaner_acerto_el_lambda'] else 'NO'):>9}")
    ratios = [f["ratio_real_sobre_prometido"] for f in filas
              if np.isfinite(f["ratio_real_sobre_prometido"])]
    if ratios:
        print(f"\nratio chi2_real/chi2_prometido: min={min(ratios):.3g} max={max(ratios):.3g}")
    aciertos = sum(1 for f in filas if f["el_escaner_acerto_el_lambda"])
    print(f"el escaner eligio el lambda que el solver real habria elegido: "
          f"{aciertos}/{len(filas)}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"filas": filas}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nInforme JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
