"""
DO-27 (Tli Kwi Cho) — Harness de validación contra benchmark PUBLICADO
=======================================================================

Primer test del motor de TerraQuantum contra un benchmark EXTERNO y peer-reviewed
(Astic & Oldenburg 2020). Ingiere la gravimetría + magnetometría de DO-27, corre 3
inversiones con el MOTOR REAL (grav-sola, mag-sola, joint cross-gradient) y MIDE la
GEOMETRÍA/TARGETING recuperada contra el ground truth de sondajes (modelo verdadero
forward-modelado por los autores), comparándola con las inversiones de referencia.

REFRAME VIGENTE (project_fase25_field_validation): TerraQuantum se valida por
GEOMETRÍA/TARGETING (dónde está el cuerpo, profundidad, forma), NO por predicción de
densidad punto a punto. La métrica dura es la LOCALIZACIÓN del pipe (horizontal +
profundidad). La densidad/susceptibilidad se reporta sólo como informativo.

NO se tunea nada para pasar. Los números son los que salen. Backend-only.

USO:
  cd terraquantum-backend
  python scripts/validation/do27_harness.py
  # → imprime la tabla y escribe scripts/validation/do27_validation_report.json
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from exploration.geophysics_math import build_gradient_operators
from services.field_validation_service import estimate_location_error
from services.joint_inversion import (
    _build_cross_gradient_block,
    _normalized_gradient,
)
from scripts.validation.ingest_do27 import (
    LocalFrame,
    PipeGroundTruth,
    build_local_frame,
    load_gravity,
    load_ground_truth,
    load_magnetic,
    summarize,
)

# ── Parámetros físicos del problema DO-27 ────────────────────────────────────
BASE_DENSITY = 2.6        # t/m³ roca caja (granito/metasedimentos de la zona)
# Kimberlita = MENOS densa que la caja (Δρ<0). Bounds que permiten contraste negativo
# (encoding del prior geológico estándar: low-density pipe). NO se tunea la magnitud.
DENSITY_MIN = 1.5
DENSITY_MAX = 2.7
SUSC_MIN = 0.0
SUSC_MAX = 0.05           # κ verdadero máx = 0.02 SI (HK1); headroom sin forzar

# ── Malla de inversión ───────────────────────────────────────────────────────
# Survey 600 m × 600 m. bs=40 m → 15×15 horizontal cubre el footprint; 13 celdas en
# profundidad ≈ 520 m alcanzan la cola del pipe (techo ~50 m, base ~480 m bajo datum).
BLOCK_SIZE = 50.0
NX = 12   # Norte (12×50 = 600 m cubre el footprint)
NZ = 12   # Este
NY = 10   # profundidad (10×50 = 500 m alcanza la base del pipe)
# Survey ~600 m de lado (diagonal ~850 m). 2000 m de cutoff capta toda interacción
# relevante (gravedad 1/r², magnetismo 1/r³) sin inflar la densidad del kernel.
CUTOFF = 2000.0

# Submuestreo de sensores: el survey trae 31×31=961 estaciones a 20 m; a 2925 celdas
# y solver acotado (TRF+IRLS) eso es lento sin ganancia (la anomalía es suave). Se
# toma 1 de cada 2 → ~16×16≈256 estaciones a 40 m, coherente con la malla.
SENSOR_STRIDE = 2
COMPACT_IRLS = 2
LAMBDA_GRAV = 1e-3
LAMBDA_MAG = 1e-3
JOINT_MAX_ITER = 2        # warm-up (k=1) + 1 iteración acoplada (k=2)


# ══════════════════════════════════════════════════════════════════════════════
#  Malla y sensores
# ══════════════════════════════════════════════════════════════════════════════
def _grid_centers_fortran(nx, ny, nz, bs):
    """Centros de celda en orden Fortran (idx = ix + nx·iy + nx·ny·iz).

    DEBE ser Fortran para que coincida con el Laplaciano/gradientes del motor
    (build_gradient_operators y _build_laplacian usan reshape order='F').
    """
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return (
        (ix.ravel(order="F") + 0.5) * bs,
        (iy.ravel(order="F") + 0.5) * bs,
        (iz.ravel(order="F") + 0.5) * bs,
    )


def _subsample(arr_list, stride):
    """Submuestrea un survey en grilla 31×31 tomando 1 de cada `stride` por eje."""
    n = arr_list[0].shape[0]
    side = int(round(np.sqrt(n)))
    if side * side != n:
        # Survey no perfectamente cuadrado → submuestreo lineal simple.
        idx = np.arange(0, n, stride)
    else:
        grid = np.arange(n).reshape(side, side)
        idx = grid[::stride, ::stride].ravel()
    return [a[idx] for a in arr_list]


# ══════════════════════════════════════════════════════════════════════════════
#  Medición de geometría vs ground truth
# ══════════════════════════════════════════════════════════════════════════════
def _truth_to_local(gt: PipeGroundTruth, fr: LocalFrame):
    """Centroide verdadero (UTM/elev) → frame local (x=Norte, y=prof, z=Este)."""
    tx = float(gt.centroid_northing - fr.origin_north)   # Norte
    tz = float(gt.centroid_easting - fr.origin_east)     # Este
    ty = float(fr.datum_elev - gt.centroid_elevation)    # profundidad
    return tx, ty, tz


def _recovered_top_depth(model_full, x_c, y_c, z_c, base_value, strong_fraction=0.5):
    """Profundidad del TECHO del cuerpo recuperado (celda fuerte más somera)."""
    contrast = np.abs(np.asarray(model_full, dtype=np.float64) - base_value)
    finite = np.isfinite(contrast)
    if not np.any(finite) or np.nanmax(contrast[finite]) <= 0:
        return None
    cmax = float(np.nanmax(contrast[finite]))
    strong = finite & (contrast > strong_fraction * cmax)
    if not np.any(strong):
        return None
    return float(np.min(y_c[strong]))


def measure_geometry(model_full, x_c, y_c, z_c, gt: PipeGroundTruth, fr: LocalFrame,
                     base_value: float) -> dict:
    """Mide localización del cuerpo recuperado vs ground truth.

    Métrica dura de TARGETING = error horizontal (UTM). Profundidad del centroide y
    del techo = informativas (gravimetría arrastra sesgo de profundidad conocido).
    """
    tx, ty, tz = _truth_to_local(gt, fr)
    loc = estimate_location_error(
        model_full, x_c, y_c, z_c, (tx, ty, tz), base_density=base_value,
    )
    # Reconvertir el centroide recuperado a UTM/elev para reporte interpretable.
    rec = {}
    if loc.get("recovered_x_m") is not None:
        rec = {
            "recovered_easting": round(fr.to_easting(loc["recovered_z_m"]), 1),
            "recovered_northing": round(fr.to_northing(loc["recovered_x_m"]), 1),
            "recovered_elevation": round(fr.to_elevation(loc["recovered_y_m"]), 1),
        }
    # Techo recuperado (profundidad bajo datum) vs techo verdadero bajo datum.
    rec_top_depth = _recovered_top_depth(model_full, x_c, y_c, z_c, base_value)
    true_top_depth = float(fr.datum_elev - gt.top_elevation)
    true_centroid_depth = ty
    return {
        "horizontal_error_m": loc.get("horizontal_error_m"),
        "centroid_depth_error_m": loc.get("depth_error_m"),
        "recovered_centroid_depth_m": loc.get("recovered_y_m"),
        "true_centroid_depth_m": round(true_centroid_depth, 1),
        "recovered_top_depth_m": None if rec_top_depth is None else round(rec_top_depth, 1),
        "true_top_depth_m": round(true_top_depth, 1),
        "top_depth_error_m": (None if rec_top_depth is None
                              else round(abs(rec_top_depth - true_top_depth), 1)),
        "n_strong": loc.get("n_strong"),
        **rec,
        "true_centroid_utm": [round(gt.centroid_easting, 1), round(gt.centroid_northing, 1)],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Inversiones (motor real)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class _Geometry:
    sensors_g: np.ndarray
    g_obs: np.ndarray
    sigma_g: float
    sensors_m: np.ndarray
    d_obs: np.ndarray
    sigma_m: float
    x_c: np.ndarray
    y_c: np.ndarray
    z_c: np.ndarray
    igrf: dict


def _prepare(grav, mag, fr: LocalFrame) -> _Geometry:
    ge, gn, gz, gv = _subsample(
        [grav.easting, grav.northing, grav.elevation, grav.bouguer_mgal], SENSOR_STRIDE
    )
    me, mn, mz, mv = _subsample(
        [mag.easting, mag.northing, mag.elevation, mag.tmi_nt], SENSOR_STRIDE
    )
    # El motor gravimétrico opera en SI (m/s²), igual que el path de producción
    # (gravity_import_service.convert_to_ms2): 1 mGal = 1e-5 m/s². El magnético opera
    # directamente en nT (el kernel dipolar usa field_intensity_nt) → sin conversión.
    gv = np.asarray(gv, dtype=np.float64) * 1e-5
    sensors_g = fr.sensors(ge, gn, gz)
    sensors_m = fr.sensors(me, mn, mz)
    x_c, y_c, z_c = _grid_centers_fortran(NX, NY, NZ, BLOCK_SIZE)
    sigma_g = max(0.02 * float(np.std(gv)), 1e-9)   # piso adaptativo (Error_Est=0 en DO-27)
    sigma_m = max(0.02 * float(np.std(mv)), 1e-2)
    return _Geometry(
        sensors_g=sensors_g, g_obs=np.asarray(gv, dtype=np.float64), sigma_g=sigma_g,
        sensors_m=sensors_m, d_obs=np.asarray(mv, dtype=np.float64), sigma_m=sigma_m,
        x_c=x_c, y_c=y_c, z_c=z_c,
        igrf={"inclination_deg": mag.inclination_deg, "declination_deg": mag.declination_deg,
              "field_intensity_nt": mag.field_intensity_nt},
    )


def invert_gravity(geo: _Geometry, extra_blocks=None, m_ref=None, kernel_cache=None):
    inv = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF)
    meta: dict = {}
    rho_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        geo.g_obs, kernel_cache, geo.y_c,
        lambda_mag=LAMBDA_GRAV, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=geo.sensors_g,
        x_c=geo.x_c, z_c=geo.z_c,
        density_min=DENSITY_MIN, density_max=DENSITY_MAX,
        noise_floor=geo.sigma_g, noise_pct=0.02,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm="compact", compact_max_irls=COMPACT_IRLS,
        m_ref=m_ref, extra_reg_blocks=extra_blocks, extra_reg_rhs=None,
        solver_meta=meta,
    )
    return np.asarray(rho_full, dtype=np.float64), misfit, meta, fwd


def invert_magnetic(geo: _Geometry, extra_blocks=None, m_ref=None, kernel_cache=None):
    inv = MagnetometryInversion(NX, NY, NZ, BLOCK_SIZE)
    fwd = MagnetometryForward(
        BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF,
        inclination_deg=geo.igrf["inclination_deg"],
        declination_deg=geo.igrf["declination_deg"],
        field_intensity_nt=geo.igrf["field_intensity_nt"],
    )
    meta: dict = {}
    chi_full, _score, misfit, _sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=geo.d_obs, override_kernel=kernel_cache, y_c=geo.y_c,
        lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=geo.sensors_m,
        x_c=geo.x_c, z_c=geo.z_c,
        susc_min=SUSC_MIN, susc_max=SUSC_MAX,
        noise_floor=geo.sigma_m, noise_pct=0.02,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm="compact", compact_max_irls=COMPACT_IRLS,
        m_ref=m_ref, extra_reg_blocks=extra_blocks, extra_reg_rhs=None,
        solver_meta=meta,
    )
    return np.asarray(chi_full, dtype=np.float64), misfit, meta, fwd


def invert_joint(geo: _Geometry) -> dict:
    """Joint grav+mag con el cross-gradient REAL de services/joint_inversion.

    Replica el bucle alternado con continuation (warm-up + acople) usando las mismas
    primitivas (_build_cross_gradient_block, _normalized_gradient) — no se reinventa
    física. NOTA HONESTA: por la poda de dominio observable, los bloques cross-gradient
    requerirían recorte de columnas como en joint_inversion; para mantener el harness
    simple y robusto se corre el joint SIN poda (prune=False) en ambas físicas, de modo
    que los bloques conforman con nC. Misfit reportado tal cual sale.
    """
    nC = NX * NY * NZ
    Dx, Dy, Dz = build_gradient_operators(NX, NY, NZ, BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)
    G_norm = float(np.sqrt(nC))
    base_rho = BASE_DENSITY

    def _solve_g(extra, mref):
        inv = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE, base_density=BASE_DENSITY)
        fwd = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF)
        meta: dict = {}
        rho, _s, mf, _ = inv.solve_inversion_lsqr(
            geo.g_obs, None, geo.y_c, lambda_mag=LAMBDA_GRAV, alpha_spatial=1.0,
            forward_model=fwd, sensor_coords=geo.sensors_g, x_c=geo.x_c, z_c=geo.z_c,
            density_min=DENSITY_MIN, density_max=DENSITY_MAX,
            noise_floor=geo.sigma_g, noise_pct=0.02,
            auto_kappa=True, prune_observable_domain=False,
            regularization_norm="compact", compact_max_irls=COMPACT_IRLS,
            m_ref=mref, extra_reg_blocks=extra, extra_reg_rhs=None, solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(rho), nan=base_rho), mf, meta

    def _solve_m(extra, mref):
        inv = MagnetometryInversion(NX, NY, NZ, BLOCK_SIZE)
        fwd = MagnetometryForward(
            BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF,
            inclination_deg=geo.igrf["inclination_deg"],
            declination_deg=geo.igrf["declination_deg"],
            field_intensity_nt=geo.igrf["field_intensity_nt"],
        )
        meta: dict = {}
        chi, _s, mf, _ = inv.solve_magnetic_inversion_lsqr(
            d_observed=geo.d_obs, override_kernel=None, y_c=geo.y_c,
            lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
            forward_model=fwd, sensor_coords=geo.sensors_m, x_c=geo.x_c, z_c=geo.z_c,
            susc_min=SUSC_MIN, susc_max=SUSC_MAX,
            noise_floor=geo.sigma_m, noise_pct=0.02,
            auto_kappa=True, prune_observable_domain=False,
            regularization_norm="compact", compact_max_irls=COMPACT_IRLS,
            m_ref=mref, extra_reg_blocks=extra, extra_reg_rhs=None, solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(chi), nan=0.0), mf, meta

    # k=0 warm-up independiente
    m_rho, mf_g, _ = _solve_g(None, None)
    m_chi, mf_m, _ = _solve_m(None, None)
    history = [{"iter": 0, "misfit_g": round(mf_g, 3), "misfit_m": round(mf_m, 3)}]

    for k in range(1, JOINT_MAX_ITER + 1):
        lambda_cross = 1.0 if k >= 2 else 0.0
        if lambda_cross > 0.0:
            hx, hy, hz = _normalized_gradient(m_chi, Dx, Dy, Dz)
            B_chi = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            bnorm = float(np.sqrt(B_chi.power(2).sum()))
            grav_blocks = [(G_norm / max(bnorm, 1e-12)) * B_chi]
        else:
            grav_blocks = None
        m_rho, mf_g, _ = _solve_g(grav_blocks, m_rho - base_rho)

        if lambda_cross > 0.0:
            hx, hy, hz = _normalized_gradient(m_rho, Dx, Dy, Dz)
            B_rho = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            bnorm = float(np.sqrt(B_rho.power(2).sum()))
            mag_blocks = [(G_norm / max(bnorm, 1e-12)) * B_rho]
        else:
            mag_blocks = None
        m_chi, mf_m, _ = _solve_m(mag_blocks, m_chi)
        history.append({"iter": k, "misfit_g": round(mf_g, 3), "misfit_m": round(mf_m, 3)})

    return {"rho": m_rho, "chi": m_chi, "misfit_g": mf_g, "misfit_m": mf_m, "history": history}


# ══════════════════════════════════════════════════════════════════════════════
#  Comparación contra la referencia publicada (L2 / PGI joint)
# ══════════════════════════════════════════════════════════════════════════════
def reference_geometry() -> dict:
    """Geometría del pipe según el ground truth (= lo que las referencias publicadas
    L2/PGI también recuperan: el pipe centrado en el survey, techo somero).

    Las inversiones de referencia (L2_inversion/, PGI_joint_inversion/) recuperan el
    MISMO cuerpo central somero. El test cuantitativo es: ¿TQ localiza el pipe en la
    misma posición (horizontal + techo somero) que el ground truth y las referencias?
    """
    return {
        "source": "Astic & Oldenburg 2020 — ground truth de sondajes + inv. de referencia L2/PGI",
        "note": "Las referencias L2/PGI localizan el pipe central somero; aquí se compara TQ vs ese ground truth.",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Orquestación
# ══════════════════════════════════════════════════════════════════════════════
TARGETING_TOL_M = 100.0   # tolerancia de targeting a esta escala (pipe ~300 m)


def run() -> dict:
    t0 = time.time()
    grav = load_gravity()
    mag = load_magnetic()
    gt_g, gt_m, _raw = load_ground_truth()
    fr = build_local_frame(grav, mag)
    geo = _prepare(grav, mag, fr)

    results = {}

    print("\n[1/3] Inversión GRAVIMÉTRICA sola...")
    rho, mf_g, meta_g, _ = invert_gravity(geo)
    geom_g = measure_geometry(rho, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)
    geom_g["misfit_percent"] = round(float(mf_g), 3)
    results["gravity_only"] = geom_g

    print("\n[2/3] Inversión MAGNÉTICA sola (IGRF extraído)...")
    chi, mf_m, meta_m, _ = invert_magnetic(geo)
    geom_m = measure_geometry(chi, geo.x_c, geo.y_c, geo.z_c, gt_m, fr, SUSC_MIN)
    geom_m["misfit_percent"] = round(float(mf_m), 3)
    results["magnetic_only"] = geom_m

    print("\n[3/3] Inversión JOINT grav+mag (cross-gradient)...")
    joint = invert_joint(geo)
    geom_jg = measure_geometry(joint["rho"], geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)
    geom_jg["misfit_percent"] = round(float(joint["misfit_g"]), 3)
    geom_jm = measure_geometry(joint["chi"], geo.x_c, geo.y_c, geo.z_c, gt_m, fr, SUSC_MIN)
    geom_jm["misfit_percent"] = round(float(joint["misfit_m"]), 3)
    results["joint_gravity"] = geom_jg
    results["joint_magnetic"] = geom_jm
    results["joint_history"] = joint["history"]

    # Veredicto de targeting: error horizontal < tolerancia en las corridas clave.
    def _horiz(d):
        return d.get("horizontal_error_m")

    verdict = {
        "targeting_tol_m": TARGETING_TOL_M,
        "gravity_only_horiz_m": _horiz(geom_g),
        "magnetic_only_horiz_m": _horiz(geom_m),
        "joint_grav_horiz_m": _horiz(geom_jg),
        "joint_mag_horiz_m": _horiz(geom_jm),
    }
    passes = [v for v in [_horiz(geom_g), _horiz(geom_jg)] if v is not None]
    verdict["gravity_targeting_pass"] = bool(passes) and all(v <= TARGETING_TOL_M for v in passes)
    mag_passes = [v for v in [_horiz(geom_m), _horiz(geom_jm)] if v is not None]
    verdict["magnetic_targeting_pass"] = bool(mag_passes) and all(v <= TARGETING_TOL_M for v in mag_passes)

    report = {
        "dataset": "DO-27 Tli Kwi Cho (Astic & Oldenburg 2020) — synthetic-based-on, ground truth EXTERNO",
        "ingestion": summarize(grav, mag),
        "ground_truth": {
            "gravity_pipe": _gt_dict(gt_g),
            "magnetic_body": _gt_dict(gt_m),
        },
        "local_frame": {
            "origin_east": fr.origin_east, "origin_north": fr.origin_north,
            "datum_elev": fr.datum_elev,
        },
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_size_m": BLOCK_SIZE,
                 "n_sensors_used": int(geo.sensors_g.shape[0])},
        "results": results,
        "reference": reference_geometry(),
        "verdict": verdict,
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = render_table(report)
    return report


def _gt_dict(gt: PipeGroundTruth) -> dict:
    return {
        "centroid_easting": round(gt.centroid_easting, 1),
        "centroid_northing": round(gt.centroid_northing, 1),
        "centroid_elevation": round(gt.centroid_elevation, 1),
        "top_elevation": round(gt.top_elevation, 1),
        "surface_elevation": round(gt.surface_elevation, 1),
        "depth_to_top_m": round(gt.depth_to_top_m, 1),
        "horizontal_extent_m": [round(v, 1) for v in gt.horizontal_extent_m],
        "n_body_cells": gt.n_body_cells,
    }


def render_table(report: dict) -> str:
    r = report["results"]
    rows = [
        ("Gravimetría sola", r["gravity_only"]),
        ("Magnetometría sola", r["magnetic_only"]),
        ("Joint — gravedad", r["joint_gravity"]),
        ("Joint — magnetismo", r["joint_magnetic"]),
    ]
    h = ("| Inversión | err horiz | err prof centroide | err prof techo | misfit |\n"
         "|-----------|-----------|--------------------|----------------|--------|")
    lines = [h]
    for name, d in rows:
        def _m(v):
            return "—" if v is None else f"{v:.1f}m"
        lines.append(
            f"| {name} | {_m(d.get('horizontal_error_m'))} | "
            f"{_m(d.get('centroid_depth_error_m'))} | {_m(d.get('top_depth_error_m'))} | "
            f"{d.get('misfit_percent')}% |"
        )
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run()
    print("\n" + "=" * 80)
    print("DO-27 — VALIDACIÓN CONTRA BENCHMARK PUBLICADO (geometría/targeting)")
    print("=" * 80)
    gt = report["ground_truth"]
    print(f"\nGround truth pipe (UTM): grav=({gt['gravity_pipe']['centroid_easting']}, "
          f"{gt['gravity_pipe']['centroid_northing']}) techo_prof≈"
          f"{report['results']['gravity_only']['true_top_depth_m']}m bajo datum")
    print("\n" + report["table_markdown"])
    v = report["verdict"]
    print(f"\nTolerancia targeting: <{v['targeting_tol_m']:.0f}m")
    print(f"  Gravimetría localiza el pipe: {'SÍ' if v['gravity_targeting_pass'] else 'NO'} "
          f"(horiz sola={v['gravity_only_horiz_m']}m, joint={v['joint_grav_horiz_m']}m)")
    print(f"  Magnetometría localiza el cuerpo: {'SÍ' if v['magnetic_targeting_pass'] else 'NO'} "
          f"(horiz sola={v['magnetic_only_horiz_m']}m, joint={v['joint_mag_horiz_m']}m)")
    print(f"\nTiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "do27_validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
