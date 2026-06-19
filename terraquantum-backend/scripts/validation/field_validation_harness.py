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
def run_project(p: FieldProject) -> CaseStudy:
    rng = np.random.default_rng(p.seed)
    sensors = _surface_sensors(p)
    n_sensors = sensors.shape[0]

    # ── Señal sintética: malla forward FINA (anti-inverse-crime) ─────────────
    (xf, yf, zf), bf = _forward_grid(p)
    fwd_fine = GravimetryForward(bf, bf, bf, cutoff_radius=8000.0)
    contrast_fine = _sphere_contrast(
        xf, yf, zf, p.body_center_xyz, p.body_radius_m, p.body_contrast
    )
    g_clean = fwd_fine.build_sparse_kernel(xf, yf, zf, sensors) @ contrast_fine
    sig = float(np.std(g_clean))
    sigma_noise = p.noise_pct * sig if sig > 0 else 1e-12
    g_obs = g_clean + sigma_noise * rng.standard_normal(n_sensors)

    # ── Inversión en malla DISTINTA (coarse) ─────────────────────────────────
    x_c, y_c, z_c = _grid_centers(p.nx, p.ny, p.nz, p.block_size)
    inv = GravimetryInversion(p.nx, p.ny, p.nz, p.block_size, base_density=BASE_DENSITY)
    fwd_inv = GravimetryForward(
        p.block_size, p.block_size, p.block_size, cutoff_radius=8000.0
    )
    boreholes = p.boreholes or _auto_boreholes(p)

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
        solver_meta=meta,
    )

    plan = plan_multimodal(
        has_gravity=True, has_magnetic=False, has_borehole=bool(boreholes),
        n_sensors=n_sensors, data_quality=p.data_quality_score, coverage_pct=1.0,
    )

    metrics = validate_against_boreholes(boreholes, dens_full, x_c, y_c, z_c, p.block_size)
    depth_err = estimate_depth_error(
        dens_full, y_c, depth_true_m=p.body_center_xyz[1], base_density=BASE_DENSITY,
    )
    loc_err = estimate_location_error(
        dens_full, x_c, y_c, z_c, p.body_center_xyz, base_density=BASE_DENSITY,
    )

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
        notes=[
            f"misfit={misfit:.3%}",
            f"horiz_err={loc_err['horizontal_error_m']}m",
            f"depth_err={loc_err['depth_error_m']}m",
        ],
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


def main():
    try:  # consola Windows (cp1252) no imprime los iconos de estado por defecto
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run_campaign()
    print("\n" + report["table_markdown"] + "\n")
    print("Localización del cuerpo (horizontal = observable robusto; profundidad = sesgo conocido):")
    for c in report["cases"]:
        le = c.get("location_error") or {}
        print(f"  {c['project']:18s} horiz_err={le.get('horizontal_error_m')}m  "
              f"depth_err={le.get('depth_error_m')}m  (true y={le.get('true_xyz_m', [None]*3)[1]}m)")
    s = report["summary"]
    print(f"\nGate densidad GO/NO-GO: {s['go_no_go']}  "
          f"({s['n_projects_passing_gate']}/{s['n_projects_with_borehole']} pasan gate, "
          f"MAE global={s['global_mae_t_m3']} t/m³, "
          f"%<0.3={s['global_pct_within_0_3']}, "
          f"conf_predictiva={s['confidence_predictive']})")
    out = Path(__file__).resolve().parent / "field_validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte escrito en {out}")


if __name__ == "__main__":
    main()
