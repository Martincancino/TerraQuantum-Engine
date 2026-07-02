"""
TANDA A — PARTE 1B: ¿es ROBUSTO el cuerpo SOMERO de LdM, o lo profundo es null-space?
====================================================================================

La pregunta CORRECTA (no "¿λ cura el centroide global?"). Re-corre LdM por el flujo de
producción separando DOS métricas que veníamos mezclando:

  • SOMERO (<2.5 km): centroide del cuerpo de baja densidad restringido a celdas con
    profundidad < 2500 m  ← lo que se vende (targeting de la anomalía resoluble).
  • GLOBAL: centroide de TODA la baja densidad  ← contaminado por el smear de fondo.

…a través de las perillas REALES de producción (las que el schema expone):
  λ:      auto (Morozov) ↔ hand-tuned 0.1
  bounds: loose (dmin=0, dmax=5.5 = default que satura) ↔ físicos (dmin=2.0, dmax=3.0)

NOTA HONESTA: depth_beta NO es campo del schema (se lee por getattr → fijo 2.0 en
producción); variarlo exigiría bypassear el flujo. Por eso el barrido cubre las DOS
perillas que SÍ son production-reachable y que deciden las hipótesis pre-registradas.

PRE-REGISTRO (escrito ANTES de correr):
  A) Si el cuerpo SOMERO queda estable en ~1.8 km pase lo que pase con las perillas →
     el motor está bien; el problema es 100% de REPORTE (suprimir el artefacto del piso)
     → se cierra la física y se pivotea a reporte honesto (B).
  B) Si λ=0.1 ELIMINA el smear y baja el centroide global a ~1.9 km → el operating-point
     auto ES el culpable arreglable → se corrige el default.

NO se tunea para pasar. Mismos datos/malla/auto-grid; sólo cambian λ y bounds. Backend-
only, sin tocar producción (este script sólo MIDE).

USO:
  cd terraquantum-backend
  python scripts/validation/tanda_a_part1b_shallow_vs_smear.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
LDM_CSV = REPO / "terraquantum-backend" / "tests" / "fixtures" / "csv_reales" / "LdM_ENRICHED_GOOD.csv"

SHALLOW_CUTOFF_M = 2500.0   # umbral somero/profundo (< 2.5 km = componente resoluble)
BASE_DENSITY = 2.6          # host: getattr(params,"base_density",2.6) en producción


def _build_ldm_input(*, lambda_mag, auto_lambda, density_min, density_max, tag):
    """Reconstruye el payload de /load-package; sólo λ y bounds varían entre runs."""
    from services.csv_package_service import parse_package_text
    from services.gravity_import_service import import_gravity_csv_v1
    from schemas.geophysics_schema import GeophysicsInvertInput

    parsed = parse_package_text(LDM_CSV.read_text(encoding="utf-8"))
    cfg = parsed.config

    tmp = Path(ROOT) / "tmp" / f"_tanda_b_{uuid.uuid4().hex[:8]}.csv"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(parsed.body_csv, encoding="utf-8")
    try:
        ir = import_gravity_csv_v1(
            tmp, strict=bool(cfg.get("strict", True)),
            allow_g_raw=bool(cfg.get("allow_g_raw", False)), data_kind="gravity",
        )
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    if ir.status != "ok":
        raise RuntimeError(f"Import LdM falló: {ir.errors}")

    observations = list(ir.observations or [])
    ag = ir.auto_grid or (ir.csv_analysis.auto_grid if ir.csv_analysis else None)

    def _eff(v, av):
        v = int(v or 0)
        return v if (0 < v <= 80) else int(av)

    noise_floor = None
    _unc = ir.station_uncertainties
    if _unc:
        _fin = sorted(u for u in _unc if u == u and u > 0.0)
        if len(_fin) >= max(3, len(_unc) // 2):
            noise_floor = float(_fin[len(_fin) // 2])
    sensor_elevs = None
    _se = ir.station_elevations
    if _se and len(_se) == len(observations):
        _f = [v for v in _se if v == v]
        if len(_f) == len(_se) and (max(_f) - min(_f)) >= 10.0:
            sensor_elevs = [float(v) for v in _se]

    return GeophysicsInvertInput(
        project_id=f"tanda_b_ldm_{tag}", run_id=f"run_{uuid.uuid4().hex[:12]}",
        depth=int(math.ceil(ag.depth_m)), nir=int(cfg.get("nir", 83)), fe=int(cfg.get("fe", 79)),
        region=str(cfg.get("region", "norte_chile")), lat=cfg.get("lat"), lon=cfg.get("lon"),
        nx=_eff(cfg.get("nx", 0), ag.nx), ny=_eff(cfg.get("ny", 0), ag.ny), nz=_eff(cfg.get("nz", 0), ag.nz),
        block_size=int(math.ceil(ag.block_size_m)), cutoff_radius=float(ag.cutoff_radius_m),
        lambda_mag=float(lambda_mag), auto_lambda=bool(auto_lambda),
        alpha_spatial=float(cfg.get("alpha_spatial", 1.0)),
        observations=observations, enable_focusing=True,
        density_min=float(density_min), density_max=float(density_max),
        sensor_elevations_masl=sensor_elevs, noise_floor_mgal=noise_floor,
        gravimeter_type=str(cfg.get("gravimeter_type", "unknown")),
        inclination_deg=float(cfg.get("inclination_deg", -30.0)),
        declination_deg=float(cfg.get("declination_deg", 2.0)),
        field_intensity_nt=float(cfg.get("field_intensity_nt", 23500.0)),
        susc_min=float(cfg.get("susc_min", 0.0)), susc_max=float(cfg.get("susc_max", 1.0)),
        padding_kappa=float(cfg.get("padding_kappa", 1e5)),
        anchor_kappa=float(cfg.get("anchor_kappa", 1e4)),
        auto_kappa=bool(cfg.get("auto_kappa", True)),
    )


def _deep_find(obj, key):
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            return obj[key]
        for v in obj.values():
            r = _deep_find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _deep_find(v, key)
            if r is not None:
                return r
    return None


def _measure(voxels) -> dict:
    """Separa SOMERO (<2.5km) vs GLOBAL para el cuerpo de BAJA densidad (density < host).

    low_contrast = max(0, BASE_DENSITY - density). El cuerpo somero se pondera por ese
    contraste; se reporta su centroide (prof + horizontal local x,z) y la FRACCIÓN de la
    'masa' de baja densidad que cae profunda (>2.5km) = magnitud del smear/null-space.
    """
    xs, ys, zs, ds = [], [], [], []
    for v in voxels:
        d = v.get("density")
        if d is None:
            continue
        ds.append(float(d)); xs.append(float(v["x"])); ys.append(float(v["y"])); zs.append(float(v["z"]))
    if not ds:
        return {"n_active": 0}
    xs, ys, zs, ds = map(lambda a: np.asarray(a, float), (xs, ys, zs, ds))

    # Fondo = MEDIANA del campo recuperado (robusto al blob de alta densidad saturado).
    # El "cuerpo de baja densidad" = celdas notablemente MENOS densas que ese fondo.
    # (Producción nunca recupera densidad < host 2.6: el campo vive en ~3.0-5.5; la
    #  anomalía LdM es una BAJA RELATIVA, igual que la midió la PARTE 1.)
    bg = float(np.median(ds))
    low = np.maximum(0.0, bg - ds)
    out = {"n_active": int(ds.size), "density_min": round(float(ds.min()), 4),
           "density_max": round(float(ds.max()), 4), "background_median": round(bg, 4),
           "total_low_mass": round(float(low.sum()), 4)}
    if low.sum() <= 0:
        out["note"] = "no hay cuerpo de baja densidad (todas las celdas ≥ host 2.6)"
        return out

    # GLOBAL: centroide de toda la baja densidad (umbral 0.5·máx, como estimate_location_error)
    def _centroid(mask):
        w = low[mask]
        if w.sum() <= 0:
            return None, None, None, 0
        strong = mask & (low > 0.5 * low[mask].max())
        if low[strong].sum() <= 0:
            strong = mask & (low > 0)
        ws = low[strong]
        return (round(float(np.average(ys[strong], weights=ws)), 1),
                round(float(np.average(xs[strong], weights=ws)), 1),
                round(float(np.average(zs[strong], weights=ws)), 1),
                int(strong.sum()))

    g_depth, g_x, g_z, g_n = _centroid(low > 0)
    out.update(global_centroid_depth_m=g_depth, global_centroid_x_m=g_x,
               global_centroid_z_m=g_z, global_n_strong=g_n)

    # SOMERO: restringido a celdas < 2.5 km
    shallow_mask = (low > 0) & (ys < SHALLOW_CUTOFF_M)
    if np.any(shallow_mask):
        s_depth, s_x, s_z, s_n = _centroid(shallow_mask)
        out.update(shallow_centroid_depth_m=s_depth, shallow_centroid_x_m=s_x,
                   shallow_centroid_z_m=s_z, shallow_n_strong=s_n)
        # pico somero
        sl = np.where(shallow_mask, low, -np.inf)
        ip = int(np.argmax(sl))
        out["shallow_peak_depth_m"] = round(float(ys[ip]), 1)
        out["shallow_peak_density"] = round(float(ds[ip]), 4)
    else:
        out["shallow_centroid_depth_m"] = None
        out["note_shallow"] = "no hay baja densidad < 2.5 km"

    # Magnitud del smear: fracción de la masa de baja densidad que es profunda (>2.5km)
    deep_mass = float(low[ys >= SHALLOW_CUTOFF_M].sum())
    out["deep_low_mass_fraction"] = round(deep_mass / float(low.sum()), 3)
    return out


SETTINGS = [
    # tag,            lambda_mag, auto_lambda, dmin, dmax
    ("auto_loose",    0.0,        True,        0.0,  5.5),   # = producción actual (el sink)
    ("l0p1_loose",    0.1,        False,       0.0,  5.5),   # hand-tuned λ, bounds default
    ("auto_phys",     0.0,        True,        2.0,  3.0),   # bounds físicos (no saturan)
    ("l0p1_phys",     0.1,        False,       2.0,  3.0),   # ambos arreglos
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from services.geophysics_service import run_geophysics_inversion

    t0 = time.time()
    print("=" * 80)
    print("TANDA A — PARTE 1B: cuerpo SOMERO robusto vs smear profundo (null-space)")
    print("=" * 80)

    results = {}
    for tag, lam, auto, dmin, dmax in SETTINGS:
        print(f"\n[{tag}] λ={'auto' if auto else lam} | bounds=[{dmin},{dmax}] ...")
        ti = time.time()
        inp = _build_ldm_input(lambda_mag=lam, auto_lambda=auto,
                               density_min=dmin, density_max=dmax, tag=tag)
        out = run_geophysics_inversion(inp)
        vox = out.get("voxels", []) if isinstance(out, dict) else []
        m = _measure(vox)
        rep = out.get("report", {}) if isinstance(out, dict) else {}
        m["chi_squared"] = _deep_find(rep, "chi_squared_final") or _deep_find(rep, "chi_squared")
        m["lambda_selected"] = _deep_find(rep, "selected_lambda") or (None if auto else lam)
        m["misfit_pct"] = out.get("misfit_pct") if isinstance(out, dict) else None
        m["elapsed_s"] = round(time.time() - ti, 1)
        m["setting"] = {"lambda_mag": lam, "auto_lambda": auto, "dmin": dmin, "dmax": dmax}
        results[tag] = m
        print(f"   SOMERO prof={m.get('shallow_centroid_depth_m')} m "
              f"(x={m.get('shallow_centroid_x_m')}, z={m.get('shallow_centroid_z_m')}) | "
              f"GLOBAL prof={m.get('global_centroid_depth_m')} m | "
              f"smear deep-frac={m.get('deep_low_mass_fraction')} | "
              f"chi2={m.get('chi_squared')} | {m['elapsed_s']}s")

    # ── Análisis de robustez del cuerpo somero ────────────────────────────────
    s_depths = [results[t].get("shallow_centroid_depth_m") for t in results
                if results[t].get("shallow_centroid_depth_m") is not None]
    s_xs = [results[t].get("shallow_centroid_x_m") for t in results
            if results[t].get("shallow_centroid_x_m") is not None]
    s_zs = [results[t].get("shallow_centroid_z_m") for t in results
            if results[t].get("shallow_centroid_z_m") is not None]
    g_depths = {t: results[t].get("global_centroid_depth_m") for t in results}

    robustness = {
        "shallow_depth_range_m": ([round(min(s_depths), 1), round(max(s_depths), 1)] if s_depths else None),
        "shallow_depth_spread_m": (round(max(s_depths) - min(s_depths), 1) if len(s_depths) > 1 else None),
        "shallow_xz_spread_m": (
            [round(max(s_xs) - min(s_xs), 1), round(max(s_zs) - min(s_zs), 1)]
            if (len(s_xs) > 1 and len(s_zs) > 1) else None),
        "global_depth_by_setting_m": g_depths,
        "lambda_fixes_smear": None,   # se decide abajo
    }
    # ¿λ=0.1 baja el global hacia ~1.9 km respecto a auto (mismos bounds)?
    def _g(t):
        return g_depths.get(t)
    lambda_effect_loose = (_g("auto_loose"), _g("l0p1_loose"))
    lambda_effect_phys = (_g("auto_phys"), _g("l0p1_phys"))
    robustness["lambda_effect_global_loose_auto_to_0p1"] = lambda_effect_loose
    robustness["lambda_effect_global_phys_auto_to_0p1"] = lambda_effect_phys

    # Veredicto pre-registrado
    shallow_stable = (robustness["shallow_depth_spread_m"] is not None
                      and robustness["shallow_depth_spread_m"] <= 600.0)  # < ~1 celda de spread
    lambda_cured_global = False
    for a, b in (lambda_effect_loose, lambda_effect_phys):
        if a is not None and b is not None and b < a - 1000.0 and 1500.0 <= b <= 2500.0:
            lambda_cured_global = True
    if shallow_stable and not lambda_cured_global:
        verdict = ("A — CUERPO SOMERO ROBUSTO: el motor está bien; el sink es null-space. "
                   "Cierra la física → pivotear a REPORTE honesto (suprimir artefacto del piso, "
                   "reportar a profundidad resoluble, incertidumbre por-eje).")
    elif lambda_cured_global:
        verdict = ("B — λ=0.1 ELIMINA el smear (global baja a la ventana ~1.9 km): el "
                   "operating-point auto es el culpable arreglable → corregir el default de λ.")
    else:
        verdict = ("AMBIGUO — ni el somero es estable ni λ cura el global; revisar (no tunear).")
    robustness["shallow_stable"] = bool(shallow_stable)
    robustness["lambda_cured_global"] = bool(lambda_cured_global)
    robustness["verdict"] = verdict

    report = {"case": "TANDA A 1B — somero robusto vs smear", "shallow_cutoff_m": SHALLOW_CUTOFF_M,
              "base_density": BASE_DENSITY, "results": results, "robustness": robustness,
              "elapsed_s": round(time.time() - t0, 1)}

    # Tabla
    lines = [
        "| Setting | λ | bounds | SOMERO prof (m) | SOMERO (x,z) | GLOBAL prof (m) | smear deep-frac | chi² |",
        "|---------|---|--------|-----------------|--------------|-----------------|-----------------|------|",
    ]
    for tag, lam, auto, dmin, dmax in SETTINGS:
        r = results[tag]
        lines.append(
            f"| {tag} | {'auto' if auto else lam} | [{dmin},{dmax}] | "
            f"{r.get('shallow_centroid_depth_m')} | "
            f"({r.get('shallow_centroid_x_m')},{r.get('shallow_centroid_z_m')}) | "
            f"{r.get('global_centroid_depth_m')} | {r.get('deep_low_mass_fraction')} | "
            f"{r.get('chi_squared')} |")
    report["table_markdown"] = "\n".join(lines)

    print("\n" + "=" * 80)
    print("TABLA 1B — cuerpo SOMERO (lo que vendes) vs GLOBAL (artefacto)")
    print("=" * 80)
    print("\n" + report["table_markdown"])
    print(f"\nSomero: rango prof={robustness['shallow_depth_range_m']} m, "
          f"spread={robustness['shallow_depth_spread_m']} m, "
          f"xz-spread={robustness['shallow_xz_spread_m']} m")
    print(f"λ efecto global (loose auto→0.1): {lambda_effect_loose} m")
    print(f"λ efecto global (phys  auto→0.1): {lambda_effect_phys} m")
    print(f"\nVEREDICTO: {verdict}")
    print(f"\nTiempo total: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "tanda_a_part1b_shallow_vs_smear_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
