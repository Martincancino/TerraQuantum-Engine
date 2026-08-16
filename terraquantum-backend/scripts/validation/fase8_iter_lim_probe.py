# -*- coding: utf-8 -*-
"""FASE 8 — el deber medido que dejó la Fase 7: ¿hay que subir `iter_lim=500`?

Lo que dejó dicho la Fase 7 (registro de su cierre)
---------------------------------------------------
> «`iter_lim=500` no se subió. El Hallazgo 2 dice que el LSQR magnético no
> converge en 500 iteraciones en la malla de prueba. Subirlo cambia resultados en
> producción; medirlo y decidirlo es trabajo propio, no un efecto colateral de una
> fase de extracción. **Queda como deber medido para la Fase 8.**»

Y midió también la consecuencia: con el LSQR parando por límite (`istop=7`,
500/500), un parámetro que el álgebra declara INERTE movía el resultado hasta un
86 %. O sea: el número que sale no es «la solución del funcional», es «dónde
estaba el LSQR cuando se le acabó el presupuesto».

Qué mide esta sonda
-------------------
Para cada motor (gravimetría y magnetometría) y varias configuraciones, resuelve
con `iter_lim` ∈ {500, 1000, 2000, 5000, 20000} y anota:

* `istop` / `itn` — POR QUÉ paró. `istop=7` = se acabaron las iteraciones.
* `chi2`, `misfit_pct` — si el ajuste mejora al dejarlo correr.
* `delta_vs_500` — ‖m(iter_lim) − m(500)‖ / ‖m(500)‖ sobre el modelo FINAL de
  producción (después de FISTA proyectado, que es lo que el usuario recibe).
* `delta_pre_fista` — el mismo cociente sobre `m_tilde` crudo, para separar
  «el LSQR cambió» de «el resultado cambió».
* `segundos` — el precio.

Cómo se varía sin tocar producción: `iter_lim` está cableado en la llamada a
`lsqr`, así que la sonda envuelve el símbolo `lsqr` DEL MÓDULO (no de scipy) y le
impone el límite. Producción no se modifica para medirla — la Fase 8 es de
byte-identidad.

Uso:
    python scripts/validation/fase8_iter_lim_probe.py
    python scripts/validation/fase8_iter_lim_probe.py --rapido   # sin 20000
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

REPORTE = Path(__file__).resolve().parent / "fase8_iter_lim_report.json"

NX = NZ = 8
NY = 6
BLOCK = 100.0
BASE_DENSITY = 2.67
CUTOFF = 3000.0
ALPHA = 1.0
LIMITES = (500, 1000, 2000, 5000, 20000)


@contextlib.contextmanager
def _perillas_fijas():
    """Mismo pinneo que el arnés de la Fase 7: se mide el FUNCIONAL, no el despacho."""
    cfg = importlib.import_module("core.config")
    prev = (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE)
    cfg.USE_BOUNDED_SOLVER = False      # fuerza el camino LSQR (el que tiene iter_lim)
    cfg.USE_PROJECTED_SOLVER = True     # FISTA como en producción
    cfg.USE_LSMR_LARGE = False
    try:
        yield
    finally:
        (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE) = prev


@contextlib.contextmanager
def _sin_fista():
    cfg = importlib.import_module("core.config")
    prev = cfg.USE_PROJECTED_SOLVER
    cfg.USE_PROJECTED_SOLVER = False
    try:
        yield
    finally:
        cfg.USE_PROJECTED_SOLVER = prev


@contextlib.contextmanager
def _iter_lim(modulo, limite: int):
    """Impone `iter_lim` sobre el `lsqr` que ve el módulo del motor."""
    original = modulo.lsqr

    def _envuelto(*a, **kw):
        kw["iter_lim"] = limite
        return original(*a, **kw)

    modulo.lsqr = _envuelto
    try:
        yield
    finally:
        modulo.lsqr = original


def _centros(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _escenario(seed: int = 20260815):
    rng = np.random.default_rng(seed)
    x_c, y_c, z_c = _centros(NX, NY, NZ, BLOCK)
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 7)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensores = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    cx = cz = NX * BLOCK / 2.0
    cuerpo = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
              & (y_c >= 2 * BLOCK) & (y_c <= 3 * BLOCK))
    pad = (np.abs(x_c - cx) > (NX / 2.0 - 1.0) * BLOCK) | (np.abs(z_c - cz) > (NX / 2.0 - 1.0) * BLOCK)
    return x_c, y_c, z_c, sensores, cuerpo, pad, rng


def _casos_grav():
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    x_c, y_c, z_c, sensores, cuerpo, pad, rng = _escenario()
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    contraste = np.where(cuerpo, 0.8, 0.0)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ contraste).ravel()
    nf = 0.02 * float(np.max(np.abs(g)))
    g = g + nf * rng.standard_normal(g.size)

    def _run(lam, padding, limite, con_fista):
        inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
        meta: dict = {}
        import exploration.gravimetry as G
        ctx = contextlib.nullcontext() if con_fista else _sin_fista()
        t0 = time.perf_counter()
        with ctx, _iter_lim(G, limite):
            rho, _sc, mis, _sens = inv.solve_inversion_lsqr(
                g, None, y_c, lambda_mag=lam, alpha_spatial=ALPHA,
                forward_model=fwd, sensor_coords=sensores, x_c=x_c, z_c=z_c,
                density_min=BASE_DENSITY, density_max=BASE_DENSITY + 1.5,
                noise_floor=nf, noise_pct=0.02, prune_observable_domain=True,
                detect_outliers=False, solver_meta=meta,
                padding_mask=(pad if padding else None),
            )
        return {
            "modelo": np.nan_to_num(rho, nan=0.0),
            "istop": meta.get("lsqr_istop"), "itn": meta.get("lsqr_iters"),
            "convergio": meta.get("lsqr_converged"),
            "chi2": meta.get("chi2_final"), "misfit_pct": float(mis),
            "segundos": round(time.perf_counter() - t0, 3),
        }

    return [
        ("grav/lambda_0.316", lambda lim, cf: _run(0.31623, False, lim, cf)),
        ("grav/lambda_0.316+padding", lambda lim, cf: _run(0.31623, True, lim, cf)),
        ("grav/lambda_0.01", lambda lim, cf: _run(0.01, False, lim, cf)),
    ]


def _casos_mag():
    from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
    x_c, y_c, z_c, sensores, cuerpo, pad, rng = _escenario(20260816)
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF,
                              inclination_deg=-30.0, declination_deg=2.0,
                              field_intensity_nt=23500.0)
    susc = np.where(cuerpo, 0.05, 0.0)
    d = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ susc).ravel()
    nf = 0.02 * float(np.max(np.abs(d)))
    d = d + nf * rng.standard_normal(d.size)

    def _run(lam, padding, limite, con_fista):
        inv = MagnetometryInversion(NX, NY, NZ, BLOCK)
        meta: dict = {}
        import exploration.magnetometry as M
        ctx = contextlib.nullcontext() if con_fista else _sin_fista()
        t0 = time.perf_counter()
        with ctx, _iter_lim(M, limite):
            # OJO: la firma magnética NO lleva `kernel_sparse` en 3ª posición
            # (a diferencia de la gravimétrica); es (d_observed, y_c, lambda_mag…).
            chi, _sc, mis, _sens = inv.solve_magnetic_inversion_lsqr(
                d, y_c, lambda_mag=lam, alpha_spatial=ALPHA,
                forward_model=fwd, sensor_coords=sensores, x_c=x_c, z_c=z_c,
                susc_min=0.0, susc_max=1.0,
                noise_floor=nf, noise_pct=0.02, prune_observable_domain=True,
                detect_outliers=False, solver_meta=meta,
                padding_mask=(pad if padding else None),
            )
        return {
            "modelo": np.nan_to_num(chi, nan=0.0),
            "istop": meta.get("lsqr_istop"), "itn": meta.get("lsqr_iters"),
            "convergio": meta.get("lsqr_converged"),
            "chi2": meta.get("chi2_final"), "misfit_pct": float(mis),
            "segundos": round(time.perf_counter() - t0, 3),
        }

    return [
        ("mag/lambda_1e-3", lambda lim, cf: _run(1e-3, False, lim, cf)),
        ("mag/lambda_1e-3+padding", lambda lim, cf: _run(1e-3, True, lim, cf)),
        ("mag/lambda_1e-2", lambda lim, cf: _run(1e-2, False, lim, cf)),
    ]


def _rel(a, b) -> float:
    den = float(np.linalg.norm(b))
    return float(np.linalg.norm(a - b) / den) if den > 0 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rapido", action="store_true", help="omite iter_lim=20000")
    args = ap.parse_args()
    limites = [x for x in LIMITES if not (args.rapido and x > 5000)]

    salida: dict = {"limites": limites, "casos": {}}
    with _perillas_fijas():
        for nombre, fn in _casos_grav() + _casos_mag():
            filas = {}
            ref_prod = ref_crudo = None
            for lim in limites:
                prod = fn(lim, True)
                crudo = fn(lim, False)
                if ref_prod is None:
                    ref_prod, ref_crudo = prod["modelo"], crudo["modelo"]
                filas[str(lim)] = {
                    "istop": prod["istop"], "itn": prod["itn"],
                    "convergio": prod["convergio"],
                    "chi2": prod["chi2"], "misfit_pct": round(prod["misfit_pct"], 6),
                    "delta_vs_500": round(_rel(prod["modelo"], ref_prod), 8),
                    "delta_pre_fista": round(_rel(crudo["modelo"], ref_crudo), 8),
                    "segundos": prod["segundos"],
                }
                print(f"  {nombre:28s} iter_lim={lim:<6d} istop={prod['istop']} "
                      f"itn={prod['itn']} chi2={prod['chi2']} "
                      f"delta={filas[str(lim)]['delta_vs_500']:.3e} "
                      f"({prod['segundos']}s)", flush=True)
            salida["casos"][nombre] = filas

    REPORTE.write_text(json.dumps(salida, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"\nreporte: {REPORTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
