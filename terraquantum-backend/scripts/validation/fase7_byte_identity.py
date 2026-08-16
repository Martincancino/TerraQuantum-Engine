# -*- coding: utf-8 -*-
"""FASE 7 — arnés de BYTE-IDENTIDAD para la extracción del núcleo compartido.

La Fase 7 mueve código que está dentro de los dos motores validados. Su criterio
de aceptación (b) dice, literalmente: *«Byte-identidad obligatoria en los 4
benchmarks + la suite de magnetometría. Un solo bit de diferencia ⇒ revertir.»*

Este arnés es el instrumento de esa exigencia. Congela la salida EXACTA (bits de
float64, vía SHA-256 sobre el buffer crudo) de una matriz de configuraciones que
recorre todas las ramas que la extracción toca, en los DOS motores:

  * `solve_inversion_lsqr`            (gravimetría, grilla regular)
  * `solve_magnetic_inversion_lsqr`   (magnetometría, rutas A y B del funcional)
  * `estimate_posterior_std`          (los dos)
  * `null_space_shuttle_ensemble`     (los dos)
  * `live_update_add_data`            (los dos)
  * `live_update_suboctree`           (los dos)
  * `select_lambda_chi2_target` / `select_lambda_lcurve` (gravimetría)

Por qué SHA-256 del buffer y no `allclose`: una tolerancia esconde exactamente la
clase de error que esta fase puede introducir (reordenar una multiplicación de
matrices cambia el último bit y no el tercer decimal). Un hash no negocia.

Las perillas de `core.config` que eligen el solver interno se FIJAN aquí: sin eso
el arnés compara el SOLVER en vez del FUNCIONAL, y es orden-dependiente — la
lección medida en la Fase 4 (`tests/test_fase4_depth_weighting.py::_pinned_solver_path`).

Uso:
    python scripts/validation/fase7_byte_identity.py --freeze   # ANTES de tocar
    python scripts/validation/fase7_byte_identity.py --check    # DESPUÉS
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BASELINE = Path(__file__).resolve().parent / "fase7_byte_identity_baseline.json"

NX = NZ = 8
NY = 6
BLOCK = 100.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 1.5
CUTOFF = 3000.0
ALPHA_SPATIAL = 1.0
LAMBDA_G = 0.31623
LAMBDA_M = 1e-3


# ── utilidades ───────────────────────────────────────────────────────────────

def _huella(*arrays) -> str:
    """SHA-256 sobre los BITS de cada array (float64 en C-order, NaN incluidos)."""
    h = hashlib.sha256()
    for a in arrays:
        arr = np.ascontiguousarray(np.asarray(a, dtype=np.float64))
        h.update(str(arr.shape).encode("utf-8"))
        h.update(arr.tobytes())
    return h.hexdigest()


@contextlib.contextmanager
def _perillas_fijas():
    """Fija las perillas de solver de `core.config` y las restaura.

    Se resuelve el módulo VIVO por `importlib` en cada uso: otros tests hacen
    `sys.modules.pop("core.config")`, lo que deja huérfana cualquier referencia
    tomada en el import inicial (medido en la Fase 4).
    """
    cfg = importlib.import_module("core.config")
    prev = (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE)
    cfg.USE_BOUNDED_SOLVER = False
    cfg.USE_PROJECTED_SOLVER = True
    cfg.USE_LSMR_LARGE = False
    try:
        yield
    finally:
        (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE) = prev


def _centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _escenario(amplitud_contraste: float, seed: int):
    """Geometría + survey + dato sintético con ruido reproducible."""
    rng = np.random.default_rng(seed)
    x_c, y_c, z_c = _centers(NX, NY, NZ, BLOCK)
    cx = cz = NX * BLOCK / 2.0
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 7)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    cuerpo = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
              & (y_c >= 2 * BLOCK) & (y_c <= 3 * BLOCK))
    contraste = np.zeros(x_c.size, dtype=np.float64)
    contraste[cuerpo] = amplitud_contraste
    return x_c, y_c, z_c, sensors, contraste, cuerpo, rng


def _mascara_padding(x_c, z_c):
    """Anillo exterior = padding (una capa por lado). Enciende la RUTA B magnética."""
    cx = cz = NX * BLOCK / 2.0
    lim = (NX / 2.0 - 1.0) * BLOCK
    return (np.abs(x_c - cx) > lim) | (np.abs(z_c - cz) > lim)


def _boreholes_grav(x_c, y_c, z_c, contraste):
    cx = cz = NX * BLOCK / 2.0
    return np.array([[cx + BLOCK / 2, cz + BLOCK / 2, 2 * BLOCK, 3 * BLOCK,
                      BASE_DENSITY + 0.8]], dtype=np.float64)


def _boreholes_mag():
    cx = cz = NX * BLOCK / 2.0
    return np.array([[cx + BLOCK / 2, cz + BLOCK / 2, 2 * BLOCK, 3 * BLOCK, 0.05]],
                    dtype=np.float64)


# ── casos ────────────────────────────────────────────────────────────────────

def _casos_gravimetria() -> list[tuple[str, callable]]:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

    x_c, y_c, z_c, sensors, contraste, cuerpo, rng = _escenario(0.8, 20260815)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensors) @ contraste).ravel()
    nf = 0.02 * float(np.max(np.abs(g)))
    g = g + nf * rng.standard_normal(g.size)
    pad = _mascara_padding(x_c, z_c)
    bh = _boreholes_grav(x_c, y_c, z_c, contraste)
    m0 = BASE_DENSITY + contraste

    def _inv():
        return GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)

    def _f(**kw):
        base = dict(
            lambda_mag=LAMBDA_G, alpha_spatial=ALPHA_SPATIAL, forward_model=fwd,
            sensor_coords=sensors, x_c=x_c, z_c=z_c,
            density_min=BASE_DENSITY, density_max=DENSITY_MAX,
            noise_floor=nf, noise_pct=0.02, prune_observable_domain=True,
            detect_outliers=False,
        )
        base.update(kw)

        def _run():
            meta: dict = {}
            rho, sens, mis, err = _inv().solve_inversion_lsqr(
                g, None, y_c, solver_meta=meta, **base)
            return _huella(rho, sens, np.array([mis]), err)
        return _run

    casos: list[tuple[str, callable]] = [
        ("grav/solve/L2", _f(regularization_norm="L2")),
        ("grav/solve/L2+padding", _f(regularization_norm="L2", padding_mask=pad)),
        ("grav/solve/L2+anclas_soft", _f(regularization_norm="L2", boreholes=bh)),
        ("grav/solve/L2+anclas_hard", _f(regularization_norm="L2", boreholes=bh,
                                         anchor_mode="hard")),
        ("grav/solve/L2+padding+anclas", _f(regularization_norm="L2", padding_mask=pad,
                                            boreholes=bh)),
        ("grav/solve/compact", _f(regularization_norm="compact", compact_max_irls=4)),
        ("grav/solve/compact+padding", _f(regularization_norm="compact",
                                          compact_max_irls=4, padding_mask=pad)),
        ("grav/solve/mixed", _f(regularization_norm="mixed", compact_max_irls=3)),
        ("grav/solve/sin_poda", _f(regularization_norm="L2",
                                   prune_observable_domain=False)),
        ("grav/solve/sigma_adaptivo", _f(regularization_norm="L2", noise_floor=0.02,
                                         noise_pct=0.02, detect_outliers=True)),
    ]

    def _posterior():
        out = _inv().estimate_posterior_std(
            g, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_G, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02)
        return _huella(out)
    casos.append(("grav/posterior_std", _posterior))

    def _shuttle():
        out = _inv().null_space_shuttle_ensemble(
            m0, g, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            n_shuttles=3, noise_floor=nf, noise_pct=0.02, seed=7,
            density_min=BASE_DENSITY, density_max=DENSITY_MAX)
        return _huella(out["ensemble"], out["ensemble_std"], out["ensemble_mean"],
                       np.array([out["data_fit_preserved"]]))
    casos.append(("grav/null_space_shuttle", _shuttle))

    def _live_add():
        new_s = np.array([[350.0, 0.0, 350.0], [450.0, 0.0, 450.0]], dtype=np.float64)
        new_g = np.asarray(
            fwd._build_sparse_kernel(x_c, y_c, z_c, new_s) @ contraste).ravel()
        out = _inv().live_update_add_data(
            m0, g, y_c, new_sensor_coords=new_s, new_g_observed=new_g,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_G, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02, density_min=BASE_DENSITY, density_max=DENSITY_MAX)
        return _huella(out["model"], np.array([out["update_norm"],
                                               out["new_data_misfit_after"]]))
    casos.append(("grav/live_update_add_data", _live_add))

    def _live_sub():
        out = _inv().live_update_suboctree(
            m0, g, y_c, region_center=(400.0, 250.0, 400.0), region_radius=250.0,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_G, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02, density_min=BASE_DENSITY, density_max=DENSITY_MAX)
        return _huella(out["model"], np.array([out["update_norm"],
                                               out["region_misfit_after"]]))
    casos.append(("grav/live_update_suboctree", _live_sub))

    def _chi2_scan():
        out = _inv().select_lambda_chi2_target(
            g_observed=g, y_c=y_c, forward_model=fwd, sensor_coords=sensors,
            x_c=x_c, z_c=z_c, lambda_candidates=[1e-2, 1e-1, 1.0],
            chi2_target=1.0, alpha_spatial=ALPHA_SPATIAL)
        return _huella(np.array([out["lambda_selected"], out["chi2_achieved"]]),
                       np.array([t["chi2_final"] for t in out["trials"]]))
    casos.append(("grav/select_lambda_chi2_target", _chi2_scan))

    # ── Solver Octree: el TERCER sitio donde se construye un peso de modelo ────
    # Producción conmuta a él sola con >50.000 celdas o >50 km de survey
    # (`should_auto_use_treemesh`), y la Fase 4 midió que ahí `depth_beta` SÍ está
    # vivo (8.125×). Entra en el arnés porque la Fase 7 también lo recablea.
    def _treemesh(beta):
        from exploration.gravimetry import solve_inversion_treemesh
        from exploration.treemesh import TreeMesh
        mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)
        dens, _p, _m = solve_inversion_treemesh(
            mesh=mesh, g_observed=g, sensor_coords=sensors, forward_model=fwd,
            lambda_mag=LAMBDA_G, alpha_spatial=ALPHA_SPATIAL, depth_beta=beta,
            base_density=BASE_DENSITY, density_min=BASE_DENSITY,
            density_max=DENSITY_MAX, noise_floor=nf, noise_pct=0.02)
        return _huella(dens)
    for _b in (0.0, 2.0, 4.0):
        casos.append((f"grav/treemesh/beta{_b}", (lambda b: (lambda: _treemesh(b)))(_b)))

    def _lcurve():
        out = _inv().select_lambda_lcurve(
            g_observed=g, y_c=y_c, forward_model=fwd, sensor_coords=sensors,
            x_c=x_c, z_c=z_c, n_trials=5, lambda_min=1e-2, lambda_max=1e1,
            alpha_spatial=ALPHA_SPATIAL, noise_floor=nf, noise_pct=0.02)
        return _huella(np.array([out["lambda_selected"]]),
                       np.array([t["misfit_norm"] for t in out["trials"]]),
                       np.array([t["roughness_norm"] for t in out["trials"]]))
    casos.append(("grav/select_lambda_lcurve", _lcurve))

    return casos


def _casos_magnetometria() -> list[tuple[str, callable]]:
    from exploration.magnetometry import MagnetometryForward, MagnetometryInversion

    x_c, y_c, z_c, sensors, contraste, cuerpo, rng = _escenario(0.05, 20260816)
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    d = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensors) @ contraste).ravel()
    nf = 0.02 * float(np.max(np.abs(d)))
    d = d + nf * rng.standard_normal(d.size)
    pad = _mascara_padding(x_c, z_c)
    bh = _boreholes_mag()
    m0 = contraste.copy()

    def _inv():
        return MagnetometryInversion(NX, NY, NZ, BLOCK)

    def _f(**kw):
        base = dict(
            lambda_mag=LAMBDA_M, alpha_spatial=ALPHA_SPATIAL, forward_model=fwd,
            sensor_coords=sensors, x_c=x_c, z_c=z_c, susc_min=0.0, susc_max=1.0,
            noise_floor=nf, noise_pct=0.02, detect_outliers=False,
        )
        base.update(kw)

        def _run():
            meta: dict = {}
            susc, sens, mis, err = _inv().solve_magnetic_inversion_lsqr(
                d, y_c, solver_meta=meta, **base)
            return _huella(susc, sens, np.array([mis]), err)
        return _run

    casos: list[tuple[str, callable]] = [
        # RUTA A del funcional (H-33): sin padding ni anclas ni IRLS → depth weighting ACTIVO
        ("mag/solve/rutaA_L2_b1.5", _f(regularization_norm="L2", depth_beta=1.5)),
        ("mag/solve/rutaA_L2_b0.0", _f(regularization_norm="L2", depth_beta=0.0)),
        ("mag/solve/rutaA_L2_b3.0", _f(regularization_norm="L2", depth_beta=3.0)),
        # RUTA B (producción): con padding → cambio de variable puro → INERTE
        ("mag/solve/rutaB_padding_b1.5", _f(regularization_norm="L2", padding_mask=pad,
                                            depth_beta=1.5)),
        ("mag/solve/rutaB_padding_b0.0", _f(regularization_norm="L2", padding_mask=pad,
                                            depth_beta=0.0)),
        ("mag/solve/rutaB_anclas", _f(regularization_norm="L2", boreholes=bh)),
        ("mag/solve/rutaB_anclas_hard", _f(regularization_norm="L2", boreholes=bh,
                                           anchor_mode="hard")),
        ("mag/solve/rutaB_compact", _f(regularization_norm="compact",
                                       compact_max_irls=4)),
        ("mag/solve/rutaB_compact_padding", _f(regularization_norm="compact",
                                               compact_max_irls=4, padding_mask=pad)),
        ("mag/solve/poda_observable", _f(regularization_norm="L2",
                                         prune_observable_domain=True)),
        ("mag/solve/sigma_adaptivo", _f(regularization_norm="L2", noise_floor=0.02,
                                        noise_pct=0.02, detect_outliers=True)),
    ]

    def _posterior():
        out = _inv().estimate_posterior_std(
            d, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_M, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02)
        return _huella(out)
    casos.append(("mag/posterior_std", _posterior))

    def _shuttle():
        out = _inv().null_space_shuttle_ensemble(
            m0, d, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            n_shuttles=3, noise_floor=nf, noise_pct=0.02, seed=7,
            susceptibility_min=0.0, susceptibility_max=1.0)
        return _huella(out["ensemble"], out["ensemble_std"], out["ensemble_mean"],
                       np.array([out["data_fit_preserved"]]))
    casos.append(("mag/null_space_shuttle", _shuttle))

    def _live_add():
        new_s = np.array([[350.0, 0.0, 350.0], [450.0, 0.0, 450.0]], dtype=np.float64)
        new_d = np.asarray(
            fwd._build_sparse_kernel(x_c, y_c, z_c, new_s) @ contraste).ravel()
        out = _inv().live_update_add_data(
            m0, d, y_c, new_sensor_coords=new_s, new_d_observed=new_d,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_M, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02, susceptibility_min=0.0, susceptibility_max=1.0)
        return _huella(out["model"], np.array([out["update_norm"],
                                               out["new_data_misfit_after"]]))
    casos.append(("mag/live_update_add_data", _live_add))

    def _live_sub():
        out = _inv().live_update_suboctree(
            m0, d, y_c, region_center=(400.0, 250.0, 400.0), region_radius=250.0,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            lambda_mag=LAMBDA_M, alpha_spatial=ALPHA_SPATIAL, noise_floor=nf,
            noise_pct=0.02, susceptibility_min=0.0, susceptibility_max=1.0)
        return _huella(out["model"], np.array([out["update_norm"],
                                               out["region_misfit_after"]]))
    casos.append(("mag/live_update_suboctree", _live_sub))

    return casos


def medir() -> dict[str, str]:
    salida: dict[str, str] = {}
    with _perillas_fijas():
        for nombre, fn in _casos_gravimetria() + _casos_magnetometria():
            try:
                salida[nombre] = fn()
            except Exception as exc:      # el fallo también es una salida a congelar
                salida[nombre] = f"ERROR::{type(exc).__name__}::{exc}"
                print(f"  [!] {nombre}: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc(limit=3, file=sys.stderr)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", action="store_true", help="congela la linea base")
    ap.add_argument("--check", action="store_true", help="compara contra la linea base")
    args = ap.parse_args()

    medido = medir()
    n_err = sum(1 for v in medido.values() if v.startswith("ERROR::"))
    print(f"\n{len(medido)} casos medidos ({n_err} con ERROR congelado).")

    if args.freeze:
        BASELINE.write_text(json.dumps(medido, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"Linea base escrita en {BASELINE}")
        for k in sorted(medido):
            print(f"  {medido[k][:16]}  {k}")
        return 0

    if args.check:
        if not BASELINE.is_file():
            print(f"FALTA {BASELINE} (corre --freeze antes de tocar el motor)",
                  file=sys.stderr)
            return 1
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        faltan = sorted(set(base) - set(medido))
        nuevos = sorted(set(medido) - set(base))
        difs = sorted(k for k in set(base) & set(medido) if base[k] != medido[k])
        for k in faltan:
            print(f"  AUSENTE  {k}", file=sys.stderr)
        for k in nuevos:
            print(f"  NUEVO    {k}  {medido[k][:16]}")
        for k in difs:
            print(f"  DISTINTO {k}\n           base={base[k][:32]}\n"
                  f"           ahora={medido[k][:32]}", file=sys.stderr)
        if difs or faltan:
            print(f"\nBYTE-IDENTIDAD ROTA: {len(difs)} distinto(s), "
                  f"{len(faltan)} ausente(s).", file=sys.stderr)
            return 1
        print(f"\nBYTE-IDENTIDAD OK: {len(base)} casos identicos bit a bit.")
        return 0

    for k in sorted(medido):
        print(f"  {medido[k][:16]}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
