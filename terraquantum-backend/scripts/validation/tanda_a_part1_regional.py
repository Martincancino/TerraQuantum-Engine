"""
TANDA A — PARTE 1: ¿la remoción regional cura el sink de profundidad de LdM?
=============================================================================

MEDIR, sin cambiar ningún default. Tres casos, cada uno OFF (remove_regional=False,
= comportamiento de producción actual) vs ON (remove_regional=True, order=2):

  1. LdM real (Bouguer Miller, LdM_ENRICHED_GOOD.csv) por el FLUJO DE PRODUCCIÓN
     (run_geophysics_inversion, espejo de /load-package). Mide la profundidad del
     cuerpo de BAJA densidad recuperado.
       PRE-REGISTRO: ÉXITO = el centroide de baja densidad sube de ~4.8 km hacia
       ~1.5–2.5 km (≈ los ~2 km publicados / ~1.9 km de la corrida hand-tuned).
       Si NO sube → hipótesis refutada; PARAR, no tunear.

  2. DO-27 (gravimetría) — CONTROL DE DAÑO. Aplica la MISMA remoción regional al
     g_obs (m/s²) del harness y mide el targeting horizontal vs ground truth.
       Sin regional dominante → debería ser ~neutral. Si lo DAÑA → no se puede
       auto-activar a ciegas.

  3. Raglan (magnetometría) — CONTROL DE DAÑO. NOTA HONESTA: en producción
     `remove_regional` vive SÓLO en el path gravimétrico (build_sensor_arrays); el
     path magnético NO lo toca → Raglan es estructuralmente byte-idéntico al flag.
     Aquí se corre el ANÁLOGO (poly-trend sobre el TMI) como chequeo de
     sensibilidad: ¿dañaría un benchmark magnético si se extendiera el feature?

NO se tunea nada. Mismos datos/malla/σ; lo único que cambia es la columna OFF/ON.
Backend-only. No toca el motor ni defaults (este script sólo MIDE).

USO:
  cd terraquantum-backend
  python scripts/validation/tanda_a_part1_regional.py
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent  # raíz del monorepo (donde están los CSV de LdM)


# ══════════════════════════════════════════════════════════════════════════════
#  CASO 1 — LdM real por el flujo de producción
# ══════════════════════════════════════════════════════════════════════════════
LDM_CSV = REPO / "terraquantum-backend" / "tests" / "fixtures" / "csv_reales" / "LdM_ENRICHED_GOOD.csv"


def _build_ldm_input(remove_regional: bool, regional_order: int = 2):
    """Reconstruye el GeophysicsInvertInput EXACTAMENTE como /load-package, salvo el
    flag remove_regional (que load-package no propaga → siempre False en producción).
    """
    import math

    from services.csv_package_service import parse_package_text
    from services.gravity_import_service import import_gravity_csv_v1
    from schemas.geophysics_schema import GeophysicsInvertInput

    parsed = parse_package_text(LDM_CSV.read_text(encoding="utf-8"))
    cfg = parsed.config

    tmp = Path(ROOT) / "tmp" / f"_tanda_a_{uuid.uuid4().hex[:8]}.csv"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(parsed.body_csv, encoding="utf-8")
    try:
        import_result = import_gravity_csv_v1(
            tmp,
            strict=bool(cfg.get("strict", True)),
            allow_g_raw=bool(cfg.get("allow_g_raw", False)),
            data_kind="gravity",
        )
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass

    if import_result.status != "ok":
        raise RuntimeError(f"Import LdM falló: {import_result.errors}")

    observations = list(import_result.observations or [])
    auto_grid = import_result.auto_grid
    if auto_grid is None and import_result.csv_analysis:
        auto_grid = import_result.csv_analysis.auto_grid

    def _eff_dim(v, av):
        v = int(v or 0)
        return v if (0 < v <= 80) else int(av)

    eff_nx = _eff_dim(cfg.get("nx", 0), auto_grid.nx)
    eff_ny = _eff_dim(cfg.get("ny", 0), auto_grid.ny)
    eff_nz = _eff_dim(cfg.get("nz", 0), auto_grid.nz)
    _bs = float(cfg.get("block_size", 0) or 0)
    eff_block = int(math.ceil(_bs)) if _bs > 0 else int(math.ceil(auto_grid.block_size_m))
    _dp = float(cfg.get("depth", 0) or 0)
    eff_depth = int(math.ceil(_dp)) if _dp > 0 else int(math.ceil(auto_grid.depth_m))
    _cr = float(cfg.get("cutoff_radius", 0) or 0)
    eff_cutoff = _cr if _cr > 0 else float(auto_grid.cutoff_radius_m)

    # Sigma por estación (mediana de uncertainty) + topografía — espejo de load_package.
    noise_floor = None
    _unc = import_result.station_uncertainties
    if _unc:
        _fin = sorted(u for u in _unc if u == u and u > 0.0)
        if len(_fin) >= max(3, len(_unc) // 2):
            noise_floor = float(_fin[len(_fin) // 2])
    sensor_elevs = None
    _se = import_result.station_elevations
    if _se and len(_se) == len(observations):
        _se_fin = [v for v in _se if v == v]
        if len(_se_fin) == len(_se) and (max(_se_fin) - min(_se_fin)) >= 10.0:
            sensor_elevs = [float(v) for v in _se]

    inp = GeophysicsInvertInput(
        project_id=f"tanda_a_ldm_{'on' if remove_regional else 'off'}",
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        depth=eff_depth, nir=int(cfg.get("nir", 83)), fe=int(cfg.get("fe", 79)),
        region=str(cfg.get("region", "norte_chile")),
        lat=cfg.get("lat"), lon=cfg.get("lon"),
        nx=eff_nx, ny=eff_ny, nz=eff_nz,
        block_size=eff_block, cutoff_radius=eff_cutoff,
        lambda_mag=float(cfg.get("lambda_mag", 0.0)),
        alpha_spatial=float(cfg.get("alpha_spatial", 1.0)),
        observations=observations,
        enable_focusing=True,
        density_min=float(cfg.get("density_min", 0.0)),
        density_max=float(cfg.get("density_max", 5.5)),
        sensor_elevations_masl=sensor_elevs,
        noise_floor_mgal=noise_floor,
        gravimeter_type=str(cfg.get("gravimeter_type", "unknown")),
        inclination_deg=float(cfg.get("inclination_deg", -30.0)),
        declination_deg=float(cfg.get("declination_deg", 2.0)),
        field_intensity_nt=float(cfg.get("field_intensity_nt", 23500.0)),
        susc_min=float(cfg.get("susc_min", 0.0)),
        susc_max=float(cfg.get("susc_max", 1.0)),
        padding_kappa=float(cfg.get("padding_kappa", 1e5)),
        anchor_kappa=float(cfg.get("anchor_kappa", 1e4)),
        auto_kappa=bool(cfg.get("auto_kappa", True)),
        remove_regional=remove_regional,
        regional_order=regional_order,
    )
    return inp


def _deep_find(obj, key):
    """Busca recursivamente la primera ocurrencia de `key` en dicts/lists anidados."""
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


def _measure_low_density_depth(voxels) -> dict:
    """Profundidad del cuerpo de BAJA densidad recuperado + centroide global.

    Apples-to-apples off vs on:
      base = mediana de densidad de celdas activas (fondo robusto).
      low_contrast = max(0, base - density)  (sólo celdas MENOS densas que el fondo).
      depth_low = centroide-y ponderado de las celdas con low_contrast > 0.5·máx.
    También centroide-y global (|density-base| sobre todas las activas) para comparar
    contra el ~4.766 m global de memoria.
    """
    ys = np.array([float(v["y"]) for v in voxels if v.get("density") is not None], dtype=float)
    ds = np.array([float(v["density"]) for v in voxels if v.get("density") is not None], dtype=float)
    if ds.size == 0:
        return {"n_active": 0}
    base = float(np.median(ds))

    out = {"n_active": int(ds.size), "base_density_median": round(base, 4),
           "density_min": round(float(ds.min()), 4), "density_max": round(float(ds.max()), 4)}

    # Centroide global (|contraste|)
    gc = np.abs(ds - base)
    if gc.max() > 0:
        strong_g = gc > 0.5 * gc.max()
        out["global_centroid_depth_m"] = round(float(np.average(ys[strong_g], weights=gc[strong_g])), 1)
        out["n_strong_global"] = int(strong_g.sum())

    # Centroide de BAJA densidad
    low = np.maximum(0.0, base - ds)
    if low.max() > 0:
        strong_l = low > 0.5 * low.max()
        out["low_density_centroid_depth_m"] = round(float(np.average(ys[strong_l], weights=low[strong_l])), 1)
        out["n_strong_low"] = int(strong_l.sum())
        ip = int(np.argmax(low))
        out["low_density_peak_depth_m"] = round(float(ys[ip]), 1)
        out["low_density_peak_value"] = round(float(ds[ip]), 4)
    else:
        out["low_density_centroid_depth_m"] = None
        out["note_low"] = "no hay celdas por debajo del fondo (sin cuerpo de baja densidad)"
    return out


def run_ldm() -> dict:
    from services.geophysics_service import run_geophysics_inversion

    res = {}
    for tag, rr in (("off", False), ("on", True)):
        print(f"\n[LdM] remove_regional={rr} ...")
        t0 = time.time()
        inp = _build_ldm_input(remove_regional=rr)
        out = run_geophysics_inversion(inp)
        voxels = out.get("voxels", []) if isinstance(out, dict) else []
        m = _measure_low_density_depth(voxels)
        m["misfit_pct"] = out.get("misfit_pct") if isinstance(out, dict) else None
        rep = out.get("report", {}) if isinstance(out, dict) else {}
        m["chi_squared"] = _deep_find(rep, "chi_squared_final") or _deep_find(rep, "chi_squared")
        m["lambda_selected"] = _deep_find(rep, "selected_lambda") or _deep_find(rep, "lambda_mag")
        m["elapsed_s"] = round(time.time() - t0, 1)
        res[tag] = m
        print(f"   low-density centroid prof = {m.get('low_density_centroid_depth_m')} m | "
              f"global centroid = {m.get('global_centroid_depth_m')} m | "
              f"chi2={m.get('chi_squared')} | {m['elapsed_s']}s")
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  CASO 2 — DO-27 gravimetría (control de daño)
# ══════════════════════════════════════════════════════════════════════════════
def run_do27() -> dict:
    import scripts.validation.do27_harness as H
    from services.gravity_preprocessing_service import separate_regional_residual

    grav = H.load_gravity()
    mag = H.load_magnetic()
    gt_g, _gt_m, _raw = H.load_ground_truth()
    fr = H.build_local_frame(grav, mag)
    geo = H._prepare(grav, mag, fr)

    res = {}
    for tag, rr in (("off", False), ("on", True)):
        print(f"\n[DO-27 grav] remove_regional={rr} ...")
        t0 = time.time()
        g_use = geo.g_obs.copy()
        regional_meta = None
        if rr:
            g_use, regional_meta = separate_regional_residual(geo.sensors_g, geo.g_obs, order=2)
            # σ adaptativo recomputado sobre el residual (espejo de build_sensor_arrays +
            # cómputo de σ downstream): 0.02·std, igual fórmula que _prepare.
            geo2 = H._Geometry(
                sensors_g=geo.sensors_g, g_obs=np.asarray(g_use, dtype=np.float64),
                sigma_g=max(0.02 * float(np.std(g_use)), 1e-9),
                sensors_m=geo.sensors_m, d_obs=geo.d_obs, sigma_m=geo.sigma_m,
                x_c=geo.x_c, y_c=geo.y_c, z_c=geo.z_c, igrf=geo.igrf,
            )
        else:
            geo2 = geo
        rho, mf_g, _meta, _ = H.invert_gravity(geo2)
        geom = H.measure_geometry(rho, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, H.BASE_DENSITY)
        res[tag] = {
            "horizontal_error_m": geom.get("horizontal_error_m"),
            "centroid_depth_error_m": geom.get("centroid_depth_error_m"),
            "top_depth_error_m": geom.get("top_depth_error_m"),
            "misfit_percent": round(float(mf_g), 3),
            "n_strong": geom.get("n_strong"),
            "regional_meta": ({
                "residual_std": regional_meta["residual_std"],
                "regional_min": regional_meta["regional_min"],
                "regional_max": regional_meta["regional_max"],
            } if regional_meta else None),
            "elapsed_s": round(time.time() - t0, 1),
        }
        print(f"   horiz err = {res[tag]['horizontal_error_m']} m | "
              f"misfit={res[tag]['misfit_percent']}% | {res[tag]['elapsed_s']}s")
    res["targeting_tol_m"] = H.TARGETING_TOL_M
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  CASO 3 — Raglan magnetometría (control de daño — ANÁLOGO, no producción)
# ══════════════════════════════════════════════════════════════════════════════
def run_raglan() -> dict:
    import scripts.validation.raglan_harness as R
    from exploration.preprocessing import remove_regional_trend

    survey = R.load_raglan_magnetic()
    ref = R.load_raglan_reference(survey=survey)
    fr = R.build_raglan_frame(survey)

    res = {"note": ("remove_regional es GRAVITY-ONLY en producción (build_sensor_arrays); "
                    "el path magnético NO lo toca. 'on' aquí es un ANÁLOGO de sensibilidad: "
                    "poly-trend de grado 2 restado al TMI antes de invertir.")}

    # baseline OFF (TMI intacto) y ON (TMI con trend removido), ambos CON padding.
    survey_off = survey
    for tag, rr in (("off", False), ("on", True)):
        print(f"\n[Raglan mag] regional(análogo)={rr} ...")
        t0 = time.time()
        if rr:
            # Restar poly-2 sobre (este, norte) del TMI completo (antes de submuestrear).
            resid, regional, _coef = remove_regional_trend(
                survey.east, survey.north, survey.tmi_nt, order=2)
            survey_use = R.RaglanMagneticSurvey(
                east=survey.east, north=survey.north, elevation=survey.elevation,
                tmi_nt=np.asarray(resid, dtype=np.float64), sigma_nt=survey.sigma_nt,
                inclination_deg=survey.inclination_deg, declination_deg=survey.declination_deg,
                field_intensity_nt=survey.field_intensity_nt,
                n_dropped_nan=survey.n_dropped_nan,
            )
            reg_span = [round(float(regional.min()), 1), round(float(regional.max()), 1)]
        else:
            survey_use = survey_off
            reg_span = None
        chi, misfit, x_c, y_c, z_c, n_sensors, sigma_floor, _meta = R.invert_magnetic(
            survey_use, fr, use_padding=True)
        geom = R.measure(chi, x_c, y_c, z_c, ref, fr)
        res[tag] = {
            "horiz_err_interior_peak_vs_ref_m": geom.get("horiz_err_interior_peak_vs_ref_m"),
            "horiz_err_peak_vs_ref_peak_m": geom.get("horiz_err_peak_vs_ref_peak_m"),
            "n_saturated_cells": geom.get("n_saturated_cells"),
            "misfit_percent": None if (misfit is None or not np.isfinite(misfit)) else round(misfit, 3),
            "regional_span_nt": reg_span,
            "elapsed_s": round(time.time() - t0, 1),
        }
        print(f"   interior-peak err = {res[tag]['horiz_err_interior_peak_vs_ref_m']} m | "
              f"misfit={res[tag]['misfit_percent']}% | {res[tag]['elapsed_s']}s")
    res["targeting_tol_m"] = R.TARGETING_TOL_M
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  Orquestación
# ══════════════════════════════════════════════════════════════════════════════
def _render_table(report: dict) -> str:
    ldm, do27, rag = report["ldm"], report["do27"], report["raglan"]
    lines = [
        "| Caso | Métrica | OFF (regional=False) | ON (regional=True) |",
        "|------|---------|----------------------|--------------------|",
        f"| LdM (prod.) | prof. cuerpo baja densidad (m) | "
        f"{ldm['off'].get('low_density_centroid_depth_m')} | {ldm['on'].get('low_density_centroid_depth_m')} |",
        f"| LdM (prod.) | centroide global (m) | "
        f"{ldm['off'].get('global_centroid_depth_m')} | {ldm['on'].get('global_centroid_depth_m')} |",
        f"| LdM (prod.) | chi² / misfit% | "
        f"{ldm['off'].get('chi_squared')} / {ldm['off'].get('misfit_pct')} | "
        f"{ldm['on'].get('chi_squared')} / {ldm['on'].get('misfit_pct')} |",
        f"| DO-27 (grav) | err horizontal targeting (m) | "
        f"{do27['off'].get('horizontal_error_m')} | {do27['on'].get('horizontal_error_m')} |",
        f"| DO-27 (grav) | misfit% | "
        f"{do27['off'].get('misfit_percent')} | {do27['on'].get('misfit_percent')} |",
        f"| Raglan (mag·análogo) | err interior-peak vs ref (m) | "
        f"{rag['off'].get('horiz_err_interior_peak_vs_ref_m')} | {rag['on'].get('horiz_err_interior_peak_vs_ref_m')} |",
        f"| Raglan (mag·análogo) | misfit% | "
        f"{rag['off'].get('misfit_percent')} | {rag['on'].get('misfit_percent')} |",
    ]
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    t0 = time.time()
    print("=" * 80)
    print("TANDA A — PARTE 1: ¿la remoción regional cura el sink de LdM? (MEDIR, sin tunear)")
    print("=" * 80)

    report = {"case": "TANDA A PARTE 1 — remoción regional off→on"}
    report["ldm"] = run_ldm()
    report["do27"] = run_do27()
    report["raglan"] = run_raglan()

    # Veredicto LdM pre-registrado
    off_d = report["ldm"]["off"].get("low_density_centroid_depth_m")
    on_d = report["ldm"]["on"].get("low_density_centroid_depth_m")
    ldm_cured = (off_d is not None and on_d is not None
                 and on_d < off_d and 1500.0 <= on_d <= 2500.0)
    report["ldm_verdict"] = {
        "off_depth_m": off_d, "on_depth_m": on_d,
        "success_window_m": [1500.0, 2500.0],
        "cured": bool(ldm_cured),
        "note": ("ÉXITO: el cuerpo subió a la ventana publicada ~1.5–2.5 km"
                 if ldm_cured else
                 "NO cura dentro de la ventana — revisar hipótesis (no tunear)"),
    }
    report["elapsed_s"] = round(time.time() - t0, 1)
    report["table_markdown"] = _render_table(report)

    print("\n" + "=" * 80)
    print("TABLA PARTE 1 (la evidencia que decide la PARTE 2)")
    print("=" * 80)
    print("\n" + report["table_markdown"])
    print(f"\nVeredicto LdM: {report['ldm_verdict']['note']} "
          f"(off={off_d} m → on={on_d} m)")
    print(f"\nTiempo total: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "tanda_a_part1_regional_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
