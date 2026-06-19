"""
FASE 25 — Validación de Campo (Field Validation)

Capa de servicio que convierte un resultado de inversión en MÉTRICAS de validación
publicables contra sondajes reales, y arma las fichas de caso (case studies) que
exige el roadmap Fase 25:

  - error medio de densidad vs sondaje (MAE), RMSE
  - % de intervalos dentro de 0.2 / 0.3 / 0.5 t/m³
  - error de profundidad del cuerpo recuperado vs profundidad conocida
  - ficha de caso por proyecto + tabla resumen + veredicto GO/NO-GO

NO duplica física: el mapeo profundidad→vóxel se reutiliza de borehole_service
(misma regla que el solver), y el ruteo/confianza viene de multimodal_fusion_service.
Aquí sólo se calcula estadística de validación y se ensambla el reporte.

Convención de ejes del backend: x, z horizontales; y = profundidad (+ hacia abajo).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

import numpy as np

from services.borehole_service import map_interval_to_voxels

# Umbrales de acuerdo densidad modelo↔sondaje (t/m³), del roadmap Fase 25.
THRESHOLDS_T_M3 = (0.2, 0.3, 0.5)

# GO/NO-GO Fase 25: error <0.3 t/m³ en ≥75% de los intervalos de sondaje.
GATE_THRESHOLD_T_M3 = 0.3
GATE_MIN_FRACTION = 0.75


# ══════════════════════════════════════════════════════════════════════════════
#  Métricas de validación contra sondajes
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class BoreholeValidationMetrics:
    """Estadística de error de densidad modelo↔sondaje para un proyecto."""

    n_evaluated: int                 # intervalos con densidad medida Y predicción
    n_total: int                     # intervalos con densidad medida (incluye fuera de grilla)
    mae_t_m3: Optional[float]        # error absoluto medio
    rmse_t_m3: Optional[float]       # raíz del error cuadrático medio
    max_abs_diff_t_m3: Optional[float]
    bias_t_m3: Optional[float]       # sesgo medio (modelo − sondaje)
    pct_within: dict                 # {0.2: frac, 0.3: frac, 0.5: frac}
    residuals: List[dict] = field(default_factory=list)

    def passes_gate(self) -> bool:
        """True si ≥GATE_MIN_FRACTION de los intervalos quedan dentro del umbral GO/NO-GO."""
        frac = self.pct_within.get(GATE_THRESHOLD_T_M3)
        return bool(self.n_evaluated > 0 and frac is not None and frac >= GATE_MIN_FRACTION)

    def to_dict(self) -> dict:
        def _r(v, n=4):
            return None if v is None else round(float(v), n)
        return {
            "n_evaluated": self.n_evaluated,
            "n_total": self.n_total,
            "mae_t_m3": _r(self.mae_t_m3),
            "rmse_t_m3": _r(self.rmse_t_m3),
            "max_abs_diff_t_m3": _r(self.max_abs_diff_t_m3),
            "bias_t_m3": _r(self.bias_t_m3),
            "pct_within": {str(k): _r(v, 4) for k, v in self.pct_within.items()},
            "passes_gate": self.passes_gate(),
            "gate": {"threshold_t_m3": GATE_THRESHOLD_T_M3, "min_fraction": GATE_MIN_FRACTION},
            "residuals": self.residuals,
        }


def validate_against_boreholes(
    intervals: Iterable,
    density_full: np.ndarray,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    dx: float,
    *,
    thresholds_t_m3: Sequence[float] = THRESHOLDS_T_M3,
) -> BoreholeValidationMetrics:
    """Compara densidad recuperada vs medida en sondaje y calcula MAE/RMSE/%dentro.

    A diferencia de `borehole_service.detect_borehole_conflicts` (veredicto binario
    OK/CONFLICT por intervalo), esto produce la ESTADÍSTICA agregada que pide la
    validación de campo: error medio, dispersión y fracciones dentro de umbral.

    Args:
        intervals: objetos con x_m, z_m, y_from_m, y_to_m, density_t_m3 (los que no
                   traen densidad se ignoran). hole_id es opcional (trazabilidad).
        density_full: densidad recuperada por vóxel (t/m³), grilla COMPLETA, NaN en aire.
        x_c, y_c, z_c, dx: geometría de la grilla COMPLETA.
        thresholds_t_m3: umbrales para las fracciones "% dentro de".

    Returns:
        BoreholeValidationMetrics. n_total cuenta intervalos con densidad medida;
        n_evaluated los que además cayeron en vóxeles con densidad (no aire / no fuera).
    """
    density_full = np.asarray(density_full, dtype=np.float64)
    residuals: List[dict] = []
    abs_errs: List[float] = []
    signed_errs: List[float] = []
    n_total = 0

    for it in intervals:
        rho_meas = getattr(it, "density_t_m3", None)
        if rho_meas is None:
            continue
        n_total += 1
        rho_meas = float(rho_meas)
        vox = map_interval_to_voxels(
            getattr(it, "x_m"), getattr(it, "z_m"),
            getattr(it, "y_from_m"), getattr(it, "y_to_m"),
            x_c, y_c, z_c, dx,
        )
        rho_pred: Optional[float] = None
        status = "OUT_OF_GRID"
        if vox.size > 0:
            vals = density_full[vox]
            vals = vals[np.isfinite(vals)]
            if vals.size > 0:
                rho_pred = float(np.mean(vals))
                status = "EVALUATED"
            else:
                status = "AIR_VOXEL"

        residual = None
        if rho_pred is not None:
            residual = rho_pred - rho_meas
            abs_errs.append(abs(residual))
            signed_errs.append(residual)

        residuals.append({
            "hole_id": getattr(it, "hole_id", None),
            "depth_from_m": float(getattr(it, "y_from_m")),
            "depth_to_m": float(getattr(it, "y_to_m")),
            "density_measured_t_m3": rho_meas,
            "density_predicted_t_m3": rho_pred,
            "residual_t_m3": residual,
            "status": status,
        })

    n_eval = len(abs_errs)
    if n_eval == 0:
        pct = {float(t): None for t in thresholds_t_m3}
        return BoreholeValidationMetrics(
            n_evaluated=0, n_total=n_total, mae_t_m3=None, rmse_t_m3=None,
            max_abs_diff_t_m3=None, bias_t_m3=None, pct_within=pct, residuals=residuals,
        )

    abs_arr = np.asarray(abs_errs, dtype=np.float64)
    mae = float(np.mean(abs_arr))
    rmse = float(np.sqrt(np.mean(abs_arr ** 2)))
    max_abs = float(np.max(abs_arr))
    bias = float(np.mean(signed_errs))
    pct = {float(t): float(np.mean(abs_arr <= float(t))) for t in thresholds_t_m3}

    return BoreholeValidationMetrics(
        n_evaluated=n_eval, n_total=n_total, mae_t_m3=mae, rmse_t_m3=rmse,
        max_abs_diff_t_m3=max_abs, bias_t_m3=bias, pct_within=pct, residuals=residuals,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Error de profundidad del cuerpo recuperado
# ══════════════════════════════════════════════════════════════════════════════
def estimate_depth_error(
    density_full: np.ndarray,
    y_c: np.ndarray,
    depth_true_m: float,
    *,
    contrast_quantile: float = 0.95,
    base_density: Optional[float] = None,
) -> dict:
    """Error de profundidad: profundidad del cuerpo recuperado vs profundidad real.

    Mide la profundidad del centroide del cuerpo anómalo (ponderado por el contraste
    de densidad por encima del cuantil dado) y la compara con la profundidad conocida
    del cuerpo (de sondaje o ground-truth sintético).

    Args:
        density_full: densidad (o contraste) recuperada por vóxel, grilla completa.
        y_c: profundidad del centro de cada vóxel (m), grilla completa.
        depth_true_m: profundidad conocida del cuerpo (m).
        contrast_quantile: usa sólo los vóxeles cuyo |contraste| supera este cuantil
                           (aísla el cuerpo del fondo difuso).
        base_density: si density_full es densidad ABSOLUTA, restar este fondo para
                      obtener contraste; si None se asume que ya es contraste/anomalía.

    Returns:
        dict con depth_recovered_m, depth_true_m, depth_error_m (|recuperada−real|),
        depth_error_pct y peak_depth_m (profundidad del vóxel de máximo contraste).
    """
    density_full = np.asarray(density_full, dtype=np.float64)
    y_c = np.asarray(y_c, dtype=np.float64)
    finite = np.isfinite(density_full) & np.isfinite(y_c)
    d = density_full[finite]
    y = y_c[finite]
    if d.size == 0:
        return {
            "depth_recovered_m": None, "depth_true_m": float(depth_true_m),
            "depth_error_m": None, "depth_error_pct": None, "peak_depth_m": None,
            "n_anomalous_voxels": 0,
        }

    contrast = np.abs(d - base_density) if base_density is not None else np.abs(d)
    pos = contrast > 0
    if not np.any(pos):
        return {
            "depth_recovered_m": None, "depth_true_m": float(depth_true_m),
            "depth_error_m": None, "depth_error_pct": None, "peak_depth_m": None,
            "n_anomalous_voxels": 0,
        }

    thr = float(np.quantile(contrast[pos], contrast_quantile))
    mask = contrast >= thr
    if not np.any(mask):
        mask = pos
    w = contrast[mask]
    depth_recovered = float(np.sum(y[mask] * w) / np.sum(w))
    peak_depth = float(y[int(np.argmax(contrast))])
    depth_error = abs(depth_recovered - float(depth_true_m))
    depth_error_pct = (
        100.0 * depth_error / abs(depth_true_m) if depth_true_m else None
    )
    return {
        "depth_recovered_m": round(depth_recovered, 1),
        "depth_true_m": float(depth_true_m),
        "depth_error_m": round(depth_error, 1),
        "depth_error_pct": round(depth_error_pct, 1) if depth_error_pct is not None else None,
        "peak_depth_m": round(peak_depth, 1),
        "n_anomalous_voxels": int(np.count_nonzero(mask)),
    }


def estimate_location_error(
    density_full: np.ndarray,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    true_xyz: Sequence[float],
    *,
    base_density: Optional[float] = None,
    strong_fraction: float = 0.5,
) -> dict:
    """Error de LOCALIZACIÓN (horizontal + profundidad) del cuerpo recuperado.

    Usa la convención de los tests de validación analítica del motor: el cuerpo es
    el conjunto de vóxeles cuyo contraste supera `strong_fraction`·máx (por defecto
    50%), y su centro de masa se compara con la posición real (true_xyz = x,y,z).

    La localización HORIZONTAL es el observable robusto de la gravimetría; la
    PROFUNDIDAD arrastra el sesgo conocido por no-unicidad (~40%) y se reporta como
    diagnóstico, no como métrica dura.

    Returns dict con horizontal_error_m, depth_error_m, recovered (x,y,z) y n_strong.
    """
    density_full = np.asarray(density_full, dtype=np.float64)
    x_c = np.asarray(x_c, dtype=np.float64)
    y_c = np.asarray(y_c, dtype=np.float64)
    z_c = np.asarray(z_c, dtype=np.float64)
    tx, ty, tz = (float(true_xyz[0]), float(true_xyz[1]), float(true_xyz[2]))

    contrast = np.abs(density_full - base_density) if base_density is not None else np.abs(density_full)
    finite = np.isfinite(contrast)
    if not np.any(finite) or np.nanmax(contrast[finite]) <= 0:
        return {
            "horizontal_error_m": None, "depth_error_m": None,
            "recovered_x_m": None, "recovered_y_m": None, "recovered_z_m": None,
            "true_xyz_m": [tx, ty, tz], "n_strong": 0,
        }
    cmax = float(np.nanmax(contrast[finite]))
    strong = finite & (contrast > strong_fraction * cmax)
    if not np.any(strong):
        strong = finite & (contrast > 0)
    w = contrast[strong]
    xr = float(np.average(x_c[strong], weights=w))
    yr = float(np.average(y_c[strong], weights=w))
    zr = float(np.average(z_c[strong], weights=w))
    horiz = math.hypot(xr - tx, zr - tz)
    return {
        "horizontal_error_m": round(horiz, 1),
        "depth_error_m": round(abs(yr - ty), 1),
        "recovered_x_m": round(xr, 1),
        "recovered_y_m": round(yr, 1),
        "recovered_z_m": round(zr, 1),
        "true_xyz_m": [tx, ty, tz],
        "n_strong": int(np.count_nonzero(strong)),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Ficha de caso (case study) + agregación + tabla
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class CaseStudy:
    """Una fila del informe de validación de campo (un proyecto)."""

    project: str
    route: str
    n_sensors_gravity: int = 0
    n_sensors_magnetic: int = 0
    n_boreholes: int = 0
    depth_range_m: Optional[tuple] = None
    data_quality_score: Optional[float] = None
    confidence: Optional[float] = None            # 0–1
    metrics: Optional[BoreholeValidationMetrics] = None
    depth_error: Optional[dict] = None
    location_error: Optional[dict] = None
    chi2_reduced: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """✅ OK / ⚠️ OK / ❌ FAIL / — sin sondaje, según el gate de densidad."""
        if self.metrics is None or self.metrics.n_evaluated == 0:
            return "NO_BOREHOLE"
        if self.metrics.passes_gate():
            frac02 = self.metrics.pct_within.get(0.2) or 0.0
            return "OK" if frac02 >= 0.8 else "OK_MARGINAL"
        return "FAIL"

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "route": self.route,
            "n_sensors_gravity": self.n_sensors_gravity,
            "n_sensors_magnetic": self.n_sensors_magnetic,
            "n_boreholes": self.n_boreholes,
            "depth_range_m": list(self.depth_range_m) if self.depth_range_m else None,
            "data_quality_score": self.data_quality_score,
            "confidence": None if self.confidence is None else round(self.confidence, 3),
            "confidence_pct": None if self.confidence is None else round(self.confidence * 100, 1),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "depth_error": self.depth_error,
            "location_error": self.location_error,
            "chi2_reduced": self.chi2_reduced,
            "status": self.status,
            "notes": list(self.notes),
        }


def aggregate_case_studies(cases: Sequence[CaseStudy]) -> dict:
    """Veredicto GO/NO-GO de la campaña de validación (roadmap Fase 25).

    Criterios:
      - ≥75% de los intervalos dentro de 0.3 t/m³ en los proyectos con sondaje.
      - Confianza predictiva: correlación (confianza ↔ fracción dentro de umbral) > 0.
    """
    with_bh = [c for c in cases if c.metrics is not None and c.metrics.n_evaluated > 0]
    n_projects = len(cases)
    n_with_bh = len(with_bh)
    n_pass = sum(1 for c in with_bh if c.metrics.passes_gate())

    # Métricas globales ponderadas por nº de intervalos evaluados.
    total_eval = sum(c.metrics.n_evaluated for c in with_bh)
    global_mae = (
        sum((c.metrics.mae_t_m3 or 0.0) * c.metrics.n_evaluated for c in with_bh) / total_eval
        if total_eval > 0 else None
    )
    global_frac03 = (
        sum((c.metrics.pct_within.get(0.3) or 0.0) * c.metrics.n_evaluated for c in with_bh)
        / total_eval if total_eval > 0 else None
    )

    # ¿La confianza es predictiva del error? Correlación de Pearson conf ↔ frac(0.3).
    conf = [c.confidence for c in with_bh if c.confidence is not None]
    frac = [c.metrics.pct_within.get(0.3) for c in with_bh
            if c.confidence is not None and c.metrics.pct_within.get(0.3) is not None]
    confidence_predictive = None
    corr = None
    if len(conf) >= 2 and len(conf) == len(frac) and np.std(conf) > 1e-9 and np.std(frac) > 1e-9:
        corr = float(np.corrcoef(conf, frac)[0, 1])
        confidence_predictive = bool(corr > 0.0)

    gate_pass = (
        n_with_bh > 0
        and n_pass / n_with_bh >= GATE_MIN_FRACTION
        and (confidence_predictive is not False)
    )

    return {
        "n_projects": n_projects,
        "n_projects_with_borehole": n_with_bh,
        "n_projects_passing_gate": n_pass,
        "global_mae_t_m3": round(global_mae, 4) if global_mae is not None else None,
        "global_pct_within_0_3": round(global_frac03, 4) if global_frac03 is not None else None,
        "confidence_corr": round(corr, 3) if corr is not None else None,
        "confidence_predictive": confidence_predictive,
        "gate_threshold_t_m3": GATE_THRESHOLD_T_M3,
        "gate_min_fraction": GATE_MIN_FRACTION,
        "go_no_go": "GO" if gate_pass else "NO_GO",
    }


_STATUS_ICON = {
    "OK": "✅ OK",
    "OK_MARGINAL": "⚠️ OK",
    "FAIL": "❌ FAIL",
    "NO_BOREHOLE": "— s/sondaje",
}


def render_case_study_table(cases: Sequence[CaseStudy]) -> str:
    """Tabla Markdown resumen (formato del roadmap Fase 25)."""
    header = (
        "| Project | n_sens | n_bh | Depth | DQ% | Conf | MAE | %<0.2 | Status |\n"
        "|---------|--------|------|-------|-----|------|-----|-------|--------|"
    )
    lines = [header]
    for c in cases:
        n_sens = c.n_sensors_gravity + c.n_sensors_magnetic
        if c.depth_range_m:
            depth = f"{c.depth_range_m[1] / 1000.0:.1f}km" if c.depth_range_m[1] >= 1000 \
                else f"{c.depth_range_m[1]:.0f}m"
        else:
            depth = "—"
        dq = f"{c.data_quality_score:.0f}" if c.data_quality_score is not None else "—"
        conf = f"{c.confidence * 100:.0f}%" if c.confidence is not None else "—"
        if c.metrics and c.metrics.mae_t_m3 is not None:
            mae = f"{c.metrics.mae_t_m3:.2f}"
            frac02 = c.metrics.pct_within.get(0.2)
            pct02 = f"{frac02 * 100:.0f}%" if frac02 is not None else "—"
        else:
            mae, pct02 = "—", "—"
        status = _STATUS_ICON.get(c.status, c.status)
        lines.append(
            f"| {c.project} | {n_sens} | {c.n_boreholes} | {depth} | {dq} | "
            f"{conf} | {mae} | {pct02} | {status} |"
        )
    return "\n".join(lines)
