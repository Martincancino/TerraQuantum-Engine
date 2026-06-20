"""
FASE 25 — Harness de Validación de Campo (reproducible)
=======================================================

Orquesta el flujo de validación de campo de extremo a extremo y produce las
fichas de caso (case studies) + tabla resumen + veredicto GO/NO-GO que exige el
roadmap Fase 25:

  proyecto (gravimetría [+ sondajes]) → ruteo multimodal (confianza/error esperado)
  → inversión (motor real) → validación vs sondaje (MAE/RMSE/%dentro/error profundidad)
  → ficha de caso → tabla resumen → JSON.

DEMOSTRACIÓN: se ejecuta sobre proyectos SINTÉTICOS con ground-truth conocido
(esferas/cuerpos compactos a profundidad fija + sondajes perforados en el cuerpo).
Esto valida el harness de forma reproducible y sin red, midiendo el error REAL del
motor contra una verdad conocida. Para validar un proyecto REAL chileno basta con
construir un `FieldProject` desde su CSV (gravimetría + sondaje) y llamar `run_project`.

Las firmas/coordenadas las hereda del motor existente (no se inventa física):
  x, z horizontales; y = profundidad (+ hacia abajo). density absoluta = base + contraste.

USO:
  cd terraquantum-backend
  python scripts/validation/field_validation_harness.py
  # → imprime la tabla y escribe scripts/validation/field_validation_report.json
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from schemas.geophysics_schema import BoreholeInterval
from services.multimodal_fusion_service import plan_multimodal
from services.field_validation_service import (
    CaseStudy,
    aggregate_case_studies,
    estimate_depth_error,
    estimate_location_error,
    render_case_study_table,
    validate_against_boreholes,
)

BASE_DENSITY = 2.6   # t/m³, roca caja (coincide con GravimetryInversion por defecto)


# ══════════════════════════════════════════════════════════════════════════════
#  Definición de un proyecto de validación
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class FieldProject:
    """Proyecto de validación: malla de INVERSIÓN + cuerpo sintético (ground-truth).

    La señal g_obs se genera con una malla FORWARD distinta (más fina) → protocolo
    anti-inverse-crime (la verdad no vive en la base del modelo de inversión). El
    cuerpo y los sensores se definen en coordenadas geográficas (m) del survey.
    """

    name: str
    nx: int                     # malla de inversión
    ny: int
    nz: int
    block_size: float           # tamaño de celda de inversión (m)
    body_center_xyz: tuple      # (x, y=prof, z) del centro del cuerpo, en m
    body_radius_m: float
    body_contrast: float        # Δρ del cuerpo (t/m³)
    forward_block: float = 10.0 # celda de la malla forward (fina) → anti-inverse-crime
    sensor_half_span_m: float = 250.0  # medio-ancho de la malla de sensores sobre el cuerpo
    n_sensors_side: int = 10
    noise_pct: float = 0.02
    data_quality_score: float = 85.0
    lambda_mag: float = 1e-3
    regularization_norm: str = "compact"   # Fase 24B: validar con el MEJOR motor
    compact_max_irls: int = 5
    seed: int = 20260619
    boreholes: List[BoreholeInterval] = field(default_factory=list)


def _grid_centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return (
        (ix.ravel() + 0.5) * bs,
        (iy.ravel() + 0.5) * bs,
        (iz.ravel() + 0.5) * bs,
    )


def _forward_grid(p: FieldProject):
    """Malla forward fina que cubre el mismo volumen que la malla de inversión."""
    ext_x, ext_y, ext_z = p.nx * p.block_size, p.ny * p.block_size, p.nz * p.block_size
    bf = p.forward_block
    nxf, nyf, nzf = int(ext_x / bf), int(ext_y / bf), int(ext_z / bf)
    return _grid_centers(nxf, nyf, nzf, bf), bf


def _sphere_contrast(x_c, y_c, z_c, center, radius, contrast):
    cx, cy, cz = center
    r = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    out = np.zeros_like(x_c)
    out[r <= radius] = contrast
    return out


def _surface_sensors(p: FieldProject):
    """Survey denso CENTRADO sobre el cuerpo (sensores en superficie, y=0)."""
    cx, _cy, cz = p.body_center_xyz
    s = p.sensor_half_span_m
    xs = np.linspace(cx - s, cx + s, p.n_sensors_side)
    zs = np.linspace(cz - s, cz + s, p.n_sensors_side)
    gx, gz = np.meshgrid(xs, zs)
    n = gx.size
    return np.column_stack([gx.ravel(), np.zeros(n), gz.ravel()])


def _auto_boreholes(p: FieldProject) -> List[BoreholeInterval]:
    """Sondajes sintéticos: uno en el cuerpo (mide base+contraste) + uno en roca caja.

    El sondaje de roca caja se ubica DENTRO de la grilla, suficientemente lejos del
    cuerpo (>2·radio) para muestrear fondo, sin caer fuera del dominio de inversión.
    """
    cx, cy, cz = p.body_center_xyz
    rho_body = BASE_DENSITY + p.body_contrast
    half = p.body_radius_m
    grid_max = p.nx * p.block_size
    margin = p.block_size  # al menos media celda dentro del borde
    # candidatos a ambos lados del cuerpo; elegir el que quede holgado dentro de grilla
    right = cx + 3 * half
    left = cx - 3 * half
    host_x = right if right <= grid_max - margin else left
    host_x = float(min(max(host_x, margin), grid_max - margin))
    return [
        BoreholeInterval(  # cruza el centro del cuerpo
            x_m=cx, z_m=cz, y_from_m=cy - half, y_to_m=cy + half,
            density_t_m3=round(rho_body, 3),
        ),
        BoreholeInterval(  # roca caja (fondo), dentro de la grilla
            x_m=host_x, z_m=cz, y_from_m=cy - half, y_to_m=cy + half,
            density_t_m3=BASE_DENSITY,
        ),
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  Ejecución de un proyecto
# ══════════════════════════════════════════════════════════════════════════════
def _boreholes_to_anchor_array(intervals: List[BoreholeInterval]) -> Optional[np.ndarray]:
    """Convierte intervalos de sondaje a la matriz (n,5) que consume el solver.

    Sólo entran intervalos CON densidad medida (los demás no anclan). Formato del
    contrato del motor: [x_m, z_m, y_from_m, y_to_m, density_t_m3].
    """
    rows = [
        [b.x_m, b.z_m, b.y_from_m, b.y_to_m, float(b.density_t_m3)]
        for b in intervals
        if getattr(b, "density_t_m3", None) is not None
    ]
    if not rows:
        return None
    return np.asarray(rows, dtype=np.float64)


def _simulate_observations(p: FieldProject):
    """Genera la señal gravimétrica sintética (malla forward fina, anti-inverse-crime).

    Devuelve (sensors, g_obs, sigma_noise). Aislado de la inversión para que el modo
    leave-one-out invierta MUCHAS veces sobre EXACTAMENTE el mismo dato observado.
    """
    rng = np.random.default_rng(p.seed)
    sensors = _surface_sensors(p)
    n_sensors = sensors.shape[0]

    (xf, yf, zf), bf = _forward_grid(p)
    fwd_fine = GravimetryForward(bf, bf, bf, cutoff_radius=8000.0)
    contrast_fine = _sphere_contrast(
        xf, yf, zf, p.body_center_xyz, p.body_radius_m, p.body_contrast
    )
    g_clean = fwd_fine.build_sparse_kernel(xf, yf, zf, sensors) @ contrast_fine
    sig = float(np.std(g_clean))
    sigma_noise = p.noise_pct * sig if sig > 0 else 1e-12
    g_obs = g_clean + sigma_noise * rng.standard_normal(n_sensors)
    return sensors, g_obs, sigma_noise


def _invert(p: FieldProject, sensors, g_obs, sigma_noise, anchor_arr):
    """Invierte en la malla coarse con el conjunto de anclajes dado (o None).

    Devuelve (dens_full, x_c, y_c, z_c, meta, misfit). Es el núcleo reutilizado por
    `run_project` (grav-sola / combo) y por `run_leave_one_out` (anclar N−1).
    """
    x_c, y_c, z_c = _grid_centers(p.nx, p.ny, p.nz, p.block_size)
    inv = GravimetryInversion(p.nx, p.ny, p.nz, p.block_size, base_density=BASE_DENSITY)
    fwd_inv = GravimetryForward(
        p.block_size, p.block_size, p.block_size, cutoff_radius=8000.0
    )
    meta: dict = {}
    dens_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=p.lambda_mag, alpha_spatial=1.0,
        forward_model=fwd_inv, sensor_coords=sensors,
        x_c=x_c, z_c=z_c,
        density_min=BASE_DENSITY, density_max=5.5,
        noise_floor=max(sigma_noise, 1e-12), noise_pct=p.noise_pct,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm=p.regularization_norm,
        compact_max_irls=p.compact_max_irls,
        boreholes=anchor_arr,            # None = grav-sola; (n,5) = combo grav+sondajes
        solver_meta=meta,
    )
    return dens_full, x_c, y_c, z_c, meta, misfit


def run_project(p: FieldProject, *, anchor_boreholes: bool = False) -> CaseStudy:
    """Invierte un proyecto sintético y lo valida vs sondaje.

    Args:
        anchor_boreholes: si False, GRAVIMETRÍA SOLA (los sondajes sólo validan, no
            restringen). Si True, COMBO grav+sondajes: los intervalos con densidad
            medida se inyectan como anclaje fuerte (Fase 8/20) en `solve_inversion_lsqr`.
    """
    sensors, g_obs, sigma_noise = _simulate_observations(p)
    n_sensors = sensors.shape[0]

    boreholes = p.boreholes or _auto_boreholes(p)
    anchor_arr = _boreholes_to_anchor_array(boreholes) if anchor_boreholes else None
    dens_full, x_c, y_c, z_c, meta, misfit = _invert(
        p, sensors, g_obs, sigma_noise, anchor_arr
    )

    plan = plan_multimodal(
        has_gravity=True, has_magnetic=False, has_borehole=anchor_boreholes,
        n_sensors=n_sensors, data_quality=p.data_quality_score, coverage_pct=1.0,
    )

    metrics = validate_against_boreholes(boreholes, dens_full, x_c, y_c, z_c, p.block_size)
    depth_err = estimate_depth_error(
        dens_full, y_c, depth_true_m=p.body_center_xyz[1], base_density=BASE_DENSITY,
    )
    loc_err = estimate_location_error(
        dens_full, x_c, y_c, z_c, p.body_center_xyz, base_density=BASE_DENSITY,
    )

    mode = "grav+sondajes" if anchor_boreholes else "grav-sola"
    notes = [
        f"mode={mode}",
        f"misfit={misfit:.3%}",
        f"horiz_err={loc_err['horizontal_error_m']}m",
        f"depth_err={loc_err['depth_error_m']}m",
    ]
    if anchor_boreholes:
        # HONESTIDAD: los intervalos anclados son IN-SAMPLE para el gate de densidad
        # (el sondaje fija su propia densidad in-situ). El error de PROFUNDIDAD, en
        # cambio, NO se ancla directamente → es la evidencia independiente de la tesis.
        notes.append(f"n_anchored_vox={meta.get('n_anchored_voxels')}")
        notes.append("density_gate_in_sample=True")

    return CaseStudy(
        project=p.name,
        route=plan.route,
        n_sensors_gravity=n_sensors,
        n_sensors_magnetic=0,
        n_boreholes=len({(b.x_m, b.z_m) for b in boreholes}),
        depth_range_m=(0.0, float(p.ny * p.block_size)),
        data_quality_score=p.data_quality_score,
        confidence=plan.confidence,
        metrics=metrics,
        depth_error=depth_err,
        location_error=loc_err,
        chi2_reduced=meta.get("chi2_final"),
        notes=notes,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Campaña de validación (varios proyectos sintéticos con ground-truth)
# ══════════════════════════════════════════════════════════════════════════════
def default_projects() -> List[FieldProject]:
    """Proyectos sintéticos análogos a depósitos chilenos someros (<1.5 km)."""
    # Malla de inversión 12×12×12 @ 25 m = 300 m de lado (proporciones del test de
    # validación analítica del motor). Cuerpo a ~50-65% de la profundidad, survey denso
    # centrado. forward_block=12.5 m ≠ 25 m → anti-inverse-crime. compact_max_irls
    # moderado para que la campaña (3 inversiones acotadas) corra en pocos minutos.
    # (Para una corrida de mayor resolución, subir nx/ny/nz a 16-20: más lento.)
    bs = 25.0
    return [
        FieldProject(
            name="Synthetic-Shallow", nx=12, ny=12, nz=12, block_size=bs,
            body_center_xyz=(150.0, 150.0, 150.0), body_radius_m=40.0,
            body_contrast=0.8, forward_block=12.5, sensor_half_span_m=130.0,
            compact_max_irls=3, data_quality_score=88.0,
        ),
        FieldProject(
            name="Synthetic-Deep", nx=12, ny=12, nz=12, block_size=bs,
            body_center_xyz=(150.0, 200.0, 150.0), body_radius_m=45.0,
            body_contrast=0.8, forward_block=12.5, sensor_half_span_m=130.0,
            compact_max_irls=3, data_quality_score=82.0, seed=20260620,
        ),
        FieldProject(
            name="Synthetic-Noisy", nx=12, ny=12, nz=12, block_size=bs,
            body_center_xyz=(150.0, 150.0, 150.0), body_radius_m=40.0,
            body_contrast=0.8, forward_block=12.5, sensor_half_span_m=130.0,
            compact_max_irls=3, noise_pct=0.05, data_quality_score=70.0, seed=20260621,
        ),
    ]


def run_campaign(projects: Optional[List[FieldProject]] = None) -> dict:
    projects = projects or default_projects()
    cases = [run_project(p) for p in projects]
    summary = aggregate_case_studies(cases)
    table = render_case_study_table(cases)
    return {
        "cases": [c.to_dict() for c in cases],
        "summary": summary,
        "table_markdown": table,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 2 — Demostración de la TESIS CENTRAL: grav+sondajes vs grav-sola
# ══════════════════════════════════════════════════════════════════════════════
def _frac03(case: CaseStudy) -> Optional[float]:
    if case.metrics is None:
        return None
    return case.metrics.pct_within.get(0.3)


def _depth_err(case: CaseStudy) -> Optional[float]:
    le = case.location_error or {}
    return le.get("depth_error_m")


def run_combo_comparison(projects: Optional[List[FieldProject]] = None) -> dict:
    """Corre CADA proyecto en los dos modos (grav-sola y grav+sondajes) y compara.

    Mide, por proyecto: error de profundidad (m) y % de densidad dentro de 0.3 t/m³.
    Reporta la VERDAD medida — sin tunear nada para que pase. La tesis central
    ("grav+sondajes baja la profundidad a <10–15m y sube el gate de densidad a
    >75%") se declara GO sólo si los números medidos la cumplen.
    """
    projects = projects or default_projects()
    rows = []
    cases_solo, cases_combo = [], []
    for p in projects:
        c_solo = run_project(p, anchor_boreholes=False)
        c_combo = run_project(p, anchor_boreholes=True)
        cases_solo.append(c_solo)
        cases_combo.append(c_combo)

        d_solo, d_combo = _depth_err(c_solo), _depth_err(c_combo)
        f_solo, f_combo = _frac03(c_solo), _frac03(c_combo)
        rows.append({
            "project": p.name,
            "true_depth_m": p.body_center_xyz[1],
            "depth_err_solo_m": d_solo,
            "depth_err_combo_m": d_combo,
            "depth_improvement_m": (None if d_solo is None or d_combo is None
                                    else round(d_solo - d_combo, 1)),
            "pct_within_0_3_solo": f_solo,
            "pct_within_0_3_combo": f_combo,
            "n_anchored_vox": next((n.split("=")[1] for n in c_combo.notes
                                    if n.startswith("n_anchored_vox=")), None),
        })

    return {
        "rows": rows,
        "thesis": evaluate_thesis(rows),
        "comparison_table_markdown": _render_combo_table(rows),
        "cases_solo": [c.to_dict() for c in cases_solo],
        "cases_combo": [c.to_dict() for c in cases_combo],
    }


# Umbrales de la tesis (roadmap Fase 25/21): profundidad <15m, gate densidad >75%.
DEPTH_TARGET_M = 15.0
GATE_FRAC = 0.75


def evaluate_thesis(rows: List[dict]) -> dict:
    """Veredicto GO/NO-GO de la tesis grav+sondajes a partir de las filas comparativas.

    Función PURA (sin inversión) para que el veredicto sea testeable de forma
    determinista. GO sólo si el combo cumple AMBOS: profundidad ≤ objetivo en todos
    los proyectos medidos, y ≥75% de los proyectos pasan el gate de densidad >75%.
    """
    combo_depths = [r["depth_err_combo_m"] for r in rows if r["depth_err_combo_m"] is not None]
    combo_fracs = [r["pct_within_0_3_combo"] for r in rows if r["pct_within_0_3_combo"] is not None]
    solo_depths = [r["depth_err_solo_m"] for r in rows if r["depth_err_solo_m"] is not None]
    depth_ok = bool(combo_depths) and all(d <= DEPTH_TARGET_M for d in combo_depths)
    gate_ok = bool(combo_fracs) and (sum(1 for f in combo_fracs if f >= GATE_FRAC)
                                     / len(combo_fracs)) >= GATE_FRAC
    return {
        "depth_target_m": DEPTH_TARGET_M,
        "gate_fraction_target": GATE_FRAC,
        "median_depth_err_combo_m": (round(float(np.median(combo_depths)), 1)
                                     if combo_depths else None),
        "median_depth_err_solo_m": (round(float(np.median(solo_depths)), 1)
                                    if solo_depths else None),
        "depth_thesis_met": depth_ok,
        "density_gate_thesis_met": gate_ok,
        "verdict": "GO" if (depth_ok and gate_ok) else "NO_GO",
    }


def _render_combo_table(rows: List[dict]) -> str:
    header = (
        "| Proyecto | y_real | prof_err SOLA | prof_err COMBO | Δprof | %<0.3 SOLA | %<0.3 COMBO |\n"
        "|----------|--------|---------------|----------------|-------|------------|-------------|"
    )

    def _m(v):
        return "—" if v is None else f"{v:.1f}m"

    def _p(v):
        return "—" if v is None else f"{v * 100:.0f}%"

    lines = [header]
    for r in rows:
        lines.append(
            f"| {r['project']} | {r['true_depth_m']:.0f}m | {_m(r['depth_err_solo_m'])} | "
            f"{_m(r['depth_err_combo_m'])} | {_m(r['depth_improvement_m'])} | "
            f"{_p(r['pct_within_0_3_solo'])} | {_p(r['pct_within_0_3_combo'])} |"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 3 — VALIDACIÓN CRUZADA LEAVE-ONE-OUT (mata la circularidad)
# ══════════════════════════════════════════════════════════════════════════════
# El gate de densidad de la Fase 25 mide la densidad EN los intervalos de sondaje,
# que en el combo son justo las celdas ANCLADAS. Validar ahí es tautológico: el
# anclaje fija su propia densidad in-situ, así que el gate pasa POR CONSTRUCCIÓN.
# Leave-one-out rompe esa circularidad: se ancla con N−1 sondajes y se valida la
# densidad/profundidad predicha en el sondaje OCULTO N (que la inversión NUNCA vio).
# Sólo esto cuenta como PODER PREDICTIVO real y sobrevive a un revisor.

# Umbral de densidad para el gate leave-one-out (mismo que el roadmap Fase 25).
LOO_DENSITY_TOL_T_M3 = 0.3
LOO_GATE_FRACTION = 0.75


def _loo_boreholes(p: FieldProject) -> List[dict]:
    """Conjunto rico de sondajes sintéticos (≥3) para leave-one-out, con etiqueta.

    Cada sondaje es un intervalo DELGADO (más corto que la celda) que mapea a UN
    vóxel: varios cruzan el cuerpo (densidad base+contraste) en distintas columnas,
    otros muestrean roca caja (base). Las posiciones se eligen sobre CENTROS de celda
    para que el mapeo sea inequívoco. El ground-truth de cada sondaje es consistente
    con la malla forward fina (la esfera evaluada en ese punto).

    Devuelve dicts {interval, label, kind} para poder reportar por tipo de sondaje;
    `kind` ∈ {"body","host"}.
    """
    cx, cy, cz = p.body_center_xyz
    rho_body = round(BASE_DENSITY + p.body_contrast, 3)
    d = p.block_size
    grid_max = p.nx * p.block_size
    margin = p.block_size

    def _thin(x, z, rho):
        return BoreholeInterval(
            x_m=float(x), z_m=float(z),
            y_from_m=float(cy - 1.0), y_to_m=float(cy + 1.0),
            density_t_m3=float(rho),
        )

    items: List[dict] = []
    # Sondajes que cruzan el CUERPO en distintas columnas (offset ±1 celda, dentro
    # del radio → el vóxel a profundidad cy está dentro de la esfera).
    body_offsets = [(0, 0, "C"), (d, 0, "E"), (-d, 0, "W"), (0, d, "N"), (0, -d, "S")]
    for ox, oz, tag in body_offsets:
        bx, bz = cx + ox, cz + oz
        if not (margin <= bx <= grid_max - margin and margin <= bz <= grid_max - margin):
            continue
        # Sólo si el punto está realmente dentro del cuerpo (consistencia ground-truth).
        if (bx - cx) ** 2 + (bz - cz) ** 2 <= p.body_radius_m ** 2:
            items.append({"interval": _thin(bx, bz, rho_body), "label": f"BODY-{tag}", "kind": "body"})

    # Sondajes en ROCA CAJA (fondo), lejos del cuerpo y dentro de la grilla.
    for ox, tag in [(5 * d, "E"), (-5 * d, "W")]:
        hx = float(min(max(cx + ox, margin), grid_max - margin))
        if (hx - cx) ** 2 > p.body_radius_m ** 2:   # asegurar que es fondo
            items.append({"interval": _thin(hx, cz, BASE_DENSITY), "label": f"HOST-{tag}", "kind": "host"})

    return items


def run_leave_one_out(p: FieldProject, bh_items: Optional[List[dict]] = None) -> dict:
    """Validación cruzada leave-one-out sobre los sondajes de un proyecto.

    Para cada sondaje i: ancla con TODOS los demás (N−1), invierte, y mide la densidad
    y la profundidad del cuerpo PREDICHAS en el sondaje OCULTO i. El dato observado
    g_obs es idéntico en todos los folds (se simula una sola vez).
    """
    bh_items = bh_items or _loo_boreholes(p)
    if len(bh_items) < 3:
        raise ValueError(
            f"leave-one-out requiere ≥3 sondajes para ser significativo; "
            f"el proyecto '{p.name}' generó {len(bh_items)}."
        )

    sensors, g_obs, sigma_noise = _simulate_observations(p)
    folds: List[dict] = []
    for i, held in enumerate(bh_items):
        train = [it["interval"] for j, it in enumerate(bh_items) if j != i]
        anchor_arr = _boreholes_to_anchor_array(train)
        dens_full, x_c, y_c, z_c, meta, misfit = _invert(
            p, sensors, g_obs, sigma_noise, anchor_arr
        )
        held_iv = held["interval"]
        m = validate_against_boreholes(
            [held_iv], dens_full, x_c, y_c, z_c, p.block_size
        )
        res = m.residuals[0] if m.residuals else {}
        loc = estimate_location_error(
            dens_full, x_c, y_c, z_c, p.body_center_xyz, base_density=BASE_DENSITY,
        )
        abs_err = res.get("residual_t_m3")
        abs_err = None if abs_err is None else abs(abs_err)
        folds.append({
            "held_out_label": held["label"],
            "kind": held["kind"],
            "held_out_xz_m": [held_iv.x_m, held_iv.z_m],
            "held_out_depth_m": round(0.5 * (held_iv.y_from_m + held_iv.y_to_m), 1),
            "density_measured_t_m3": res.get("density_measured_t_m3"),
            "density_predicted_t_m3": (None if res.get("density_predicted_t_m3") is None
                                       else round(res["density_predicted_t_m3"], 4)),
            "density_abs_err_t_m3": None if abs_err is None else round(abs_err, 4),
            "within_0_3": (None if abs_err is None else bool(abs_err <= LOO_DENSITY_TOL_T_M3)),
            "status": res.get("status"),
            "body_depth_err_m": loc.get("depth_error_m"),
            "n_anchored_vox": meta.get("n_anchored_voxels"),
            "misfit": round(float(misfit), 5),
        })

    return {
        "project": p.name,
        "n_folds": len(folds),
        "folds": folds,
        "summary": _summarize_loo(p, folds),
        "table_markdown": _render_loo_table(p.name, folds),
    }


def _summarize_loo(p: FieldProject, folds: List[dict]) -> dict:
    """Agrega los folds. El veredicto se centra en los sondajes de CUERPO (el caso
    informativo): la roca caja se predice trivialmente y no debe inflar el gate."""
    body = [f for f in folds if f["kind"] == "body" and f["density_abs_err_t_m3"] is not None]
    host = [f for f in folds if f["kind"] == "host" and f["density_abs_err_t_m3"] is not None]
    eval_all = [f for f in folds if f["density_abs_err_t_m3"] is not None]

    def _frac_within(items):
        return (None if not items
                else round(sum(1 for f in items if f["within_0_3"]) / len(items), 3))

    def _median(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else round(float(np.median(vals)), 3)

    body_depth_errs = [f["body_depth_err_m"] for f in folds if f["body_depth_err_m"] is not None]

    density_frac_body = _frac_within(body)
    depth_median = _median(body_depth_errs)
    density_ok = density_frac_body is not None and density_frac_body >= LOO_GATE_FRACTION
    depth_ok = depth_median is not None and depth_median <= DEPTH_TARGET_M

    return {
        "n_body_folds": len(body),
        "n_host_folds": len(host),
        "median_density_abs_err_body_t_m3": _median([f["density_abs_err_t_m3"] for f in body]),
        "median_density_abs_err_all_t_m3": _median([f["density_abs_err_t_m3"] for f in eval_all]),
        "frac_within_0_3_body": density_frac_body,
        "frac_within_0_3_all": _frac_within(eval_all),
        "median_body_depth_err_m": depth_median,
        "density_tol_t_m3": LOO_DENSITY_TOL_T_M3,
        "gate_fraction": LOO_GATE_FRACTION,
        "depth_target_m": DEPTH_TARGET_M,
        "density_thesis_met": density_ok,
        "depth_thesis_met": depth_ok,
        "verdict": "GO" if (density_ok and depth_ok) else "NO_GO",
    }


def _render_loo_table(name: str, folds: List[dict]) -> str:
    header = (
        f"### Leave-one-out — {name}\n\n"
        "| Sondaje OCULTO | tipo | prof | ρ medida | ρ predicha | |Δρ| | <0.3 | prof_cuerpo_err |\n"
        "|----------------|------|------|----------|------------|------|------|-----------------|"
    )
    lines = [header]
    for f in folds:
        def _n(v, s="{:.3f}"):
            return "—" if v is None else s.format(v)
        ok = "—" if f["within_0_3"] is None else ("✓" if f["within_0_3"] else "✗")
        lines.append(
            f"| {f['held_out_label']} | {f['kind']} | {f['held_out_depth_m']:.0f}m | "
            f"{_n(f['density_measured_t_m3'])} | {_n(f['density_predicted_t_m3'])} | "
            f"{_n(f['density_abs_err_t_m3'])} | {ok} | "
            f"{_n(f['body_depth_err_m'], '{:.1f}m')} |"
        )
    return "\n".join(lines)


def default_loo_projects() -> List[FieldProject]:
    """Proyectos para leave-one-out: cuerpo en CENTRO de celda (mapeo inequívoco) y
    radio amplio para alojar varios sondajes de cuerpo en columnas distintas."""
    bs = 25.0
    # Centro en (137.5,137.5,137.5) = centro de la celda (5,5,5) con bs=25.
    return [
        FieldProject(
            name="LOO-Shallow", nx=12, ny=12, nz=12, block_size=bs,
            body_center_xyz=(137.5, 137.5, 137.5), body_radius_m=55.0,
            body_contrast=0.8, forward_block=12.5, sensor_half_span_m=130.0,
            compact_max_irls=3, data_quality_score=88.0,
        ),
        FieldProject(
            name="LOO-Deep", nx=12, ny=12, nz=12, block_size=bs,
            body_center_xyz=(137.5, 187.5, 137.5), body_radius_m=55.0,
            body_contrast=0.8, forward_block=12.5, sensor_half_span_m=130.0,
            compact_max_irls=3, data_quality_score=82.0, seed=20260620,
        ),
    ]


def run_leave_one_out_campaign(projects: Optional[List[FieldProject]] = None) -> dict:
    projects = projects or default_loo_projects()
    per_project = [run_leave_one_out(p) for p in projects]
    # Veredicto global: GO sólo si TODOS los proyectos cumplen densidad+profundidad
    # en el sondaje oculto de CUERPO.
    verdicts = [pp["summary"]["verdict"] for pp in per_project]
    global_verdict = "GO" if verdicts and all(v == "GO" for v in verdicts) else "NO_GO"
    return {
        "projects": per_project,
        "global_verdict": global_verdict,
    }


def main():
    try:  # consola Windows (cp1252) no imprime los iconos de estado por defecto
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # ── Campaña base (grav-sola) ──────────────────────────────────────────────
    report = run_campaign()
    print("\n" + report["table_markdown"] + "\n")
    print("Localización del cuerpo (horizontal = observable robusto; profundidad = sesgo conocido):")
    for c in report["cases"]:
        le = c.get("location_error") or {}
        print(f"  {c['project']:18s} horiz_err={le.get('horizontal_error_m')}m  "
              f"depth_err={le.get('depth_error_m')}m  (true y={le.get('true_xyz_m', [None]*3)[1]}m)")
    s = report["summary"]
    print(f"\nGate densidad GO/NO-GO (grav-sola): {s['go_no_go']}  "
          f"({s['n_projects_passing_gate']}/{s['n_projects_with_borehole']} pasan gate, "
          f"MAE global={s['global_mae_t_m3']} t/m³, "
          f"%<0.3={s['global_pct_within_0_3']}, "
          f"conf_predictiva={s['confidence_predictive']})")

    # ── PASO 2: TESIS CENTRAL — grav-sola vs grav+sondajes ───────────────────
    combo = run_combo_comparison()
    print("\n" + "=" * 78)
    print("TESIS CENTRAL — grav-sola vs grav+sondajes (profundidad + gate densidad)")
    print("=" * 78)
    print("\n" + combo["comparison_table_markdown"] + "\n")
    t = combo["thesis"]
    print(f"Mediana prof_err: SOLA={t['median_depth_err_solo_m']}m → COMBO={t['median_depth_err_combo_m']}m "
          f"(objetivo <{t['depth_target_m']:.0f}m → {'CUMPLE' if t['depth_thesis_met'] else 'NO cumple'})")
    print(f"Gate densidad combo (>{t['gate_fraction_target'] * 100:.0f}% intervalos <0.3 t/m³): "
          f"{'CUMPLE' if t['density_gate_thesis_met'] else 'NO cumple'}")
    print(f"VEREDICTO TESIS grav+sondajes: {t['verdict']}")
    report["combo_comparison"] = combo

    # ── PASO 3: LEAVE-ONE-OUT — poder predictivo en sondaje OCULTO ───────────
    loo = run_leave_one_out_campaign()
    print("\n" + "=" * 78)
    print("LEAVE-ONE-OUT — densidad/profundidad en el sondaje OCULTO (no circular)")
    print("=" * 78)
    for pp in loo["projects"]:
        print("\n" + pp["table_markdown"])
        s = pp["summary"]
        print(
            f"\n  {pp['project']}: ρ oculta CUERPO mediana |Δρ|="
            f"{s['median_density_abs_err_body_t_m3']} t/m³  "
            f"(<0.3 en {s['frac_within_0_3_body']} de folds cuerpo) | "
            f"prof_cuerpo mediana={s['median_body_depth_err_m']}m | "
            f"VEREDICTO={s['verdict']}"
        )
    print(f"\nVEREDICTO GLOBAL leave-one-out: {loo['global_verdict']}")
    report["leave_one_out"] = loo

    out = Path(__file__).resolve().parent / "field_validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte escrito en {out}")


if __name__ == "__main__":
    main()
