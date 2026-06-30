import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from enum import Enum

import numpy as np
import polars as pl

from core.block_model_store import (
    RUN_MAGNETIC_BLOCK_MODEL_FILENAME,
    RUN_SOURCE_GRAVITY_FILENAME,
    get_run_anomaly_reference,
    get_run_block_model_reference,
    get_run_favorability_path,
    get_run_focusing_reference,
    get_run_inputs_path,
    get_run_observations_path,
    get_run_report_path,
    sha256_file,
    update_run_status,
    validate_parquet_schema,
    write_run_manifest,
)
from core.config import DEFAULT_BLOCK_MODEL_PATH, ensure_runtime_dirs
from exploration.focusing import run_focusing
from exploration.gravimetry import (
    GravimetryForward,
    GravimetryInversion,
    TargetingEngine,
)
from core.logging import get_logger
from fastapi import HTTPException
from schemas.geophysics_schema import GeophysicsInvertInput
from services.favorability_service import compute_favorability_score
from services.export_service import export_core_to_vtr

# ── Fase 2 §2.1: módulos aislados (re-exportados para compatibilidad) ─────────
from services.inversion_kernel_service import (
    build_voxel_grid,
    build_tensor_mesh_with_padding,
    build_sensor_arrays,
    build_observation_qaqc_report,
)
from services.inversion_solver_service import _run_lsqr_with_heartbeat
from services.inversion_postprocess_service import (
    estimate_grade_from_geophysics,
    build_full_block_model_dataframe,
    build_anomaly_dataframe,
)
from services.block_model_service import create_zarr_block_model

_log = get_logger(__name__)


# ── FASE 4 (causa J): Operating point fijo de lambda_mag ──────────────────────
# La inversión gravimétrica es severamente SUB-DETERMINADA (n_modelo ≫ n_datos).
# Con el solver W_z formal (H-A0: cambio de variable m = Wz_inv @ m_tilde con
# normalización de columnas) el espacio del parámetro es diferente al sistema
# antiguo (column-scaling Ws):
#   - Con W_z formal, columnas de G_scaled son unitarias DESPUÉS de Wz_inv @ W_col
#   - El lambda óptimo para el benchmark (8×4×8, 49 sensores, n_active=256) es 0.1
#   - Sweep empírico (H-A1): lambda sweep [0.01–3.0] → Pearson máximo en lambda=0.1 (r=0.73)
#   - A lambda=3.0 el chi²=33 (sobre-regularización severa)
#
# ADVERTENCIA: calibrado en n_active=256 (benchmark sintético 8×4×8). El scaling
# lambda_eff = lambda * sqrt(n_active / 256) ajusta a otros tamaños de problema.
# No verificado a escala regional real. Ver memoria project_fase4_h2_depth_smallness.
PRECONDITIONED_OPERATING_LAMBDA = 0.1


class PriorityClass(str, Enum):
    HIGH_RELATIVE_PRIORITY   = "HIGH_RELATIVE_PRIORITY"
    MEDIUM_RELATIVE_PRIORITY = "MEDIUM_RELATIVE_PRIORITY"
    LOW_RELATIVE_PRIORITY    = "LOW_RELATIVE_PRIORITY"
    UNCLASSIFIED             = "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE"


MSX_POLICY = {
    "enabled": True,
    "source": "backend_policy",
    "user_toggle_allowed": False,
    "disclaimer": "MS-x focusing is exploratory support; it is not a mineral resource estimate.",
}

_PRIORITY_RANK: dict[str, int] = {
    "NONE": 0,
    "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE": 1,
    "LOW_RELATIVE_PRIORITY": 2,
    "MEDIUM_RELATIVE_PRIORITY": 3,
    "HIGH_RELATIVE_PRIORITY": 4,
}


def build_report_auto_params(params: GeophysicsInvertInput):
    auto_params = dict(params.auto_params_metadata or {})
    auto_params.setdefault("version", "auto_params_v0_1")
    auto_params["msx_policy"] = dict(MSX_POLICY)
    return auto_params


def _spatial_cap_score_level(score: float) -> str:
    """Map a capped score to a favorability level string (mirrors favorability_service logic)."""
    if score < 25:
        return "MUY BAJO"
    if score < 50:
        return "BAJO"
    if score < 65:
        return "MODERADO"
    if score < 80:
        return "ALTO"
    return "MUY ALTO"


def _apply_spatial_readiness_caps(
    report_payload: dict,
    spatial_readiness: dict | None,
) -> dict:
    """
    R3.5-E — Cap favorability score and priority_class to the limits allowed
    by the input's spatial readiness level.

    Modifies report_payload in-place and returns it.
    Safe to call with None or malformed spatial_readiness — never raises.
    """
    if not spatial_readiness or not isinstance(spatial_readiness, dict):
        return report_payload

    sr_level = spatial_readiness.get("level", "")

    try:
        max_fav = float(spatial_readiness.get("max_favorability_score_allowed", 100.0))
    except (TypeError, ValueError):
        return report_payload

    max_prio = spatial_readiness.get("max_priority_class_allowed", "HIGH_RELATIVE_PRIORITY")
    if not isinstance(max_prio, str):
        max_prio = "HIGH_RELATIVE_PRIORITY"

    cap_warnings: list[str] = []

    # ── Favorability score cap ────────────────────────────────────────────────
    favorability = report_payload.get("favorability")
    if isinstance(favorability, dict):
        try:
            current_score = float(favorability.get("score", 0.0))
        except (TypeError, ValueError):
            current_score = 0.0

        if current_score > max_fav:
            original_score = current_score
            favorability["score"] = max_fav
            favorability["level"] = _spatial_cap_score_level(max_fav)
            w = (
                "Favorabilidad/prioridad limitada por SpatialReadiness: "
                "el input no tiene suficiencia espacial para clasificación superior."
            )
            cap_warnings.append(w)
            fav_warns = favorability.get("warnings")
            if isinstance(fav_warns, list):
                fav_warns.append(w)
            favorability["spatial_readiness_cap"] = {
                "applied": True,
                "level": sr_level,
                "original_favorability_score": round(original_score, 1),
                "capped_favorability_score": max_fav,
                "max_favorability_score_allowed": max_fav,
                "max_priority_class_allowed": max_prio,
                "reason": "La suficiencia espacial del input no permite una clasificación superior.",
                "warnings": cap_warnings[:],
            }
        else:
            favorability["spatial_readiness_cap"] = {
                "applied": False,
                "level": sr_level,
                "original_favorability_score": current_score,
                "capped_favorability_score": current_score,
                "max_favorability_score_allowed": max_fav,
                "max_priority_class_allowed": max_prio,
                "reason": None,
                "warnings": [],
            }

    # ── Priority class cap ────────────────────────────────────────────────────
    current_prio = report_payload.get("priority_class", "")
    if not isinstance(current_prio, str):
        current_prio = ""

    current_rank = _PRIORITY_RANK.get(current_prio, -1)
    max_rank = _PRIORITY_RANK.get(max_prio, 4)

    if max_prio == "NONE":
        if current_prio != PriorityClass.UNCLASSIFIED.value:
            report_payload["priority_class"] = PriorityClass.UNCLASSIFIED.value
            w = (
                "Clase de prioridad degradada a UNCLASSIFIED: "
                "nivel espacial NO_SPATIAL_DATA no permite clasificación."
            )
            if w not in cap_warnings:
                cap_warnings.append(w)
    elif current_rank > max_rank and current_rank >= 0:
        report_payload["priority_class"] = max_prio
        w = (
            "Favorabilidad/prioridad limitada por SpatialReadiness: "
            "el input no tiene suficiencia espacial para clasificación superior."
        )
        if w not in cap_warnings:
            cap_warnings.append(w)

    # ── Propagate cap warnings ────────────────────────────────────────────────
    if cap_warnings:
        existing = report_payload.get("priority_class_warnings")
        if not isinstance(existing, list):
            existing = []
        for w in cap_warnings:
            if w not in existing:
                existing.append(w)
        report_payload["priority_class_warnings"] = existing

    return report_payload


def validate_geophysics_input(params: GeophysicsInvertInput):
    import math

    # 4. coordenadas geográficas (opcionales — datos reales del gravímetro no las tienen)
    if params.lat is not None and params.lon is not None:
        try:
            lat = float(params.lat)
            lon = float(params.lon)
        except (ValueError, TypeError):
            raise ValueError("lat y lon deben ser valores numéricos (o null si no disponibles).")

        if lat < -90 or lat > 90:
            raise ValueError("lat debe estar entre -90 y 90.")

        if lon < -180 or lon > 180:
            raise ValueError("lon debe estar entre -180 y 180.")
    else:
        # Datos crudos del gravímetro sin georeferencia — usar "0, 0" como placeholder
        lat = 0.0
        lon = 0.0

    # observaciones: valores finitos y sin duplicados (mínimo 10 validado por Pydantic)
    seen_coords = set()
    for i, obs in enumerate(params.observations):
        if not (math.isfinite(obs.x_m) and math.isfinite(obs.y_m) and math.isfinite(obs.z_m) and math.isfinite(obs.g)):
            raise ValueError(f"La observación en el índice {i} contiene valores no finitos (NaN o Inf).")
        
        coord = (obs.x_m, obs.y_m, obs.z_m)
        if coord in seen_coords:
            raise ValueError(f"Observación duplicada detectada en las coordenadas exactas: {coord}")
        seen_coords.add(coord)

    # grilla: límite total de voxels (cross-field; rango individual validado por Pydantic)
    # Grids >500k usan almacenamiento Zarr out-of-core (Fase 10 v0.4.0).
    total_voxels = params.nx * params.ny * params.nz
    if total_voxels > 10_000_000:
        raise ValueError(f"Modelo demasiado grande (nx*ny*nz > 10 000 000): {total_voxels} voxels.")

    # profundidad: límite físico contra la grilla (cross-field; rango validado por Pydantic)
    max_model_depth = params.ny * params.block_size
    if params.depth > max_model_depth:
        raise ValueError(
            f"El target de exploración depth={params.depth} m queda fuera de la matriz. "
            f"Profundidad máxima física: {max_model_depth} m."
        )

    # cutoff_radius debe ser >= block_size (cross-field; rango y signo validados por Pydantic)
    if params.cutoff_radius < params.block_size:
        raise ValueError("cutoff_radius no puede ser menor que block_size.")

    # Discretización vertical gruesa: depth físico mucho mayor que la malla
    # vertical (ny celdas de block_size). No es error — es decisión del usuario
    # a escala regional — pero se advierte porque degrada la resolución.
    _mesh_depth = params.ny * params.block_size
    if params.depth > 10 * _mesh_depth:
        _log.warning(
            "depth_discretization_coarse",
            depth_m=params.depth,
            mesh_vertical_m=_mesh_depth,
            note="depth >> ny*block_size: la malla vertical no resuelve la "
                 "profundidad declarada; aumentar ny o block_size.",
        )


def build_fit_diagnostics(
    g_observed: np.ndarray,
    kernel_sparse,
    est_density: np.ndarray,
    base_density: float = 2.6,
    sensor_coords: np.ndarray = None,
    noise_floor: float = 0.02,
    noise_pct: float = 0.02,
    g_modeled_precomputed: np.ndarray = None,  # R-01: G_pad @ m_pad del solver
) -> dict:
    """
    Calcula métricas de ajuste observed vs modeled.

    est_density es densidad absoluta (base_density + contraste), tal como lo devuelve
    GravimetryInversion.solve_inversion_lsqr (ver gravimetry.py línea 299).
    Para reconstruir g_modeled se usa el mismo contraste que usó LSQR internamente.

    sensor_coords: array (n_sensors, 3) con columnas [x_m, y_m, z_m]. Opcional.
    Si se provee, se agrega residualMap con ubicación espacial de cada residual.
    """
    g_observed = np.asarray(g_observed, dtype=np.float64)
    est_density = np.asarray(est_density, dtype=np.float64)

    density_contrast = est_density - base_density
    density_contrast_clean = np.nan_to_num(density_contrast, nan=0.0)
    if g_modeled_precomputed is not None:
        # R-01: forward consistente del solver (G_pad @ m_pad, no G_core @ m_core)
        # Evita discrepancia cuando hay masa en celdas de padding.
        g_modeled = np.asarray(g_modeled_precomputed, dtype=np.float64)
    else:
        g_modeled = np.asarray(kernel_sparse @ density_contrast_clean, dtype=np.float64)
    residual = g_observed - g_modeled

    n = len(residual)

    # ── Chi-Squared — R-04: sigma adaptivo (Li & Oldenburg) ─────────────────
    # noise_floor=0.02 SI ≈ 2000 mGal >> señal típica → chi² → 0 (ininterpretable).
    # Nueva formulación: sigma_i = max(0.02·|d_i|, 0.01·data_range) invariante de escala.
    _data_range = max(float(np.max(g_observed) - np.min(g_observed)), 1e-30)
    if noise_floor == 0.02 and noise_pct == 0.02:
        _sigma = np.maximum(0.02 * np.abs(g_observed), 0.01 * _data_range)
        _sigma = np.maximum(_sigma, 1e-30)
    else:
        # Piso instrumental: misma fórmula que _sigma_parametric del solver.
        _sigma = np.maximum(noise_floor, noise_pct * np.abs(g_observed))
        _sigma = np.maximum(_sigma, 1e-30)

    # chi²_inicial: modelo de referencia (contraste = 0 → g_pred = 0)
    # Interpretación: si chi²_inicial << 1, sigma >> señal (noise_floor problemático).
    # Valor esperado si sigma calibrado: chi²_inicial >> 1 (los datos superan el ruido).
    phi_d_initial = float(np.sum((g_observed / _sigma) ** 2))
    chi_squared_initial = phi_d_initial / n

    # chi²_final: modelo invertido
    phi_d = float(np.sum(((g_observed - g_modeled) / _sigma) ** 2))
    chi_squared = phi_d / n

    rmse = float(np.sqrt(np.mean(residual ** 2)))
    mae = float(np.mean(np.abs(residual)))
    l2 = float(np.linalg.norm(residual))
    bias = float(np.mean(residual))
    residual_std = float(np.std(residual))

    signal_scale = max(float(np.max(np.abs(g_observed))), 1e-12)
    normalized_rmse = rmse / signal_scale

    if normalized_rmse < 0.05:
        fit_level = "GOOD"
        fit_quality = 1.0
    elif normalized_rmse < 0.20:
        fit_level = "MEDIUM"
        fit_quality = 0.6
    else:
        fit_level = "LOW"
        fit_quality = 0.3

    # ── residualSamples (hasta 50, siempre presente) ─────────────────────────
    max_samples = 50
    sample_indices = np.linspace(0, n - 1, min(n, max_samples), dtype=int)

    has_coords = sensor_coords is not None
    if has_coords:
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

    residual_samples = []
    for i in sample_indices:
        entry = {
            "sensor_index": int(i),
            "observed": round(float(g_observed[i]), 8),
            "modeled": round(float(g_modeled[i]), 8),
            "residual": round(float(residual[i]), 8),
        }
        if has_coords:
            entry["x_m"] = round(float(sensor_coords[i, 0]), 4)
            entry["y_m"] = round(float(sensor_coords[i, 1]), 4)
            entry["z_m"] = round(float(sensor_coords[i, 2]), 4)
        residual_samples.append(entry)

    # ── residualMap (hasta 500 sensores, sólo si hay coordenadas) ────────────
    residual_map = None
    if has_coords:
        max_map_points = 500
        abs_residual = np.abs(residual)
        max_abs = max(float(np.max(abs_residual)), 1e-12)

        map_indices = (
            np.arange(n, dtype=int)
            if n <= max_map_points
            else np.linspace(0, n - 1, max_map_points, dtype=int)
        )

        residual_map = []
        for i in map_indices:
            abs_r = float(abs_residual[i])
            norm_r = abs_r / max_abs
            if norm_r < 0.33:
                level = "LOW"
            elif norm_r < 0.66:
                level = "MEDIUM"
            else:
                level = "HIGH"
            residual_map.append({
                "sensor_index": int(i),
                "x_m": round(float(sensor_coords[i, 0]), 4),
                "y_m": round(float(sensor_coords[i, 1]), 4),
                "z_m": round(float(sensor_coords[i, 2]), 4),
                "observed": round(float(g_observed[i]), 8),
                "modeled": round(float(g_modeled[i]), 8),
                "residual": round(float(residual[i]), 8),
                "abs_residual": round(abs_r, 8),
                "normalized_residual": round(norm_r, 6),
                "residual_level": level,
            })

    result = {
        "observed_min": round(float(np.min(g_observed)), 8),
        "observed_max": round(float(np.max(g_observed)), 8),
        "observed_mean": round(float(np.mean(g_observed)), 8),
        "modeled_min": round(float(np.min(g_modeled)), 8),
        "modeled_max": round(float(np.max(g_modeled)), 8),
        "modeled_mean": round(float(np.mean(g_modeled)), 8),
        "residual_min": round(float(np.min(residual)), 8),
        "residual_max": round(float(np.max(residual)), 8),
        "residual_mean": round(float(np.mean(residual)), 8),
        "residual_std": round(residual_std, 8),
        "residual_l2": round(l2, 8),
        "residual_rmse": round(rmse, 8),
        "residual_mae": round(mae, 8),
        "residual_bias": round(bias, 8),
        "normalized_rmse": round(normalized_rmse, 6),
        "fit_quality": fit_quality,
        "fit_level": fit_level,
        "chi_squared_initial": round(chi_squared_initial, 4),
        "chi_squared_final": round(chi_squared, 4),
        "chi_squared": round(chi_squared, 4),           # backward compat
        "chi_squared_target": "~1.0 (< 2 = acceptable)",
        "chi_squared_note": (
            "chi_squared_initial = phi_d(m=0)/n; deberia ser >> 1 si sigma calibrado. "
            "chi_squared_final ~ 1.0 indica ajuste al nivel de ruido (Morozov)."
        ),
        "residualSamples": residual_samples,
        "residualMap": residual_map,
    }
    return result



def build_run_inputs_snapshot(params: GeophysicsInvertInput):
    return {
        "project_id": params.project_id,
        "run_id": params.run_id,
        "depth": params.depth,
        "nir": params.nir,
        "fe": params.fe,
        "region": params.region,
        "lat": params.lat,
        "lon": params.lon,
        "nx": params.nx,
        "ny": params.ny,
        "nz": params.nz,
        "block_size": params.block_size,
        "cutoff_radius": params.cutoff_radius,
        "lambda_mag": params.lambda_mag,
        "alpha_spatial": params.alpha_spatial,
        "enable_focusing": params.enable_focusing,
    }


def build_observations_snapshot(params: GeophysicsInvertInput):
    return [
        {
            "x_m": obs.x_m,
            "y_m": obs.y_m,
            "z_m": obs.z_m,
            "g": obs.g,
        }
        for obs in params.observations
    ]


def write_run_json_snapshots(params: GeophysicsInvertInput):
    inputs_path = get_run_inputs_path(
        project_id=params.project_id,
        run_id=params.run_id,
    )
    observations_path = get_run_observations_path(
        project_id=params.project_id,
        run_id=params.run_id,
    )

    if inputs_path is None or observations_path is None:
        return

    inputs_path.parent.mkdir(parents=True, exist_ok=True)

    with inputs_path.open("w", encoding="utf-8") as f:
        json.dump(build_run_inputs_snapshot(params), f, indent=2)

    with observations_path.open("w", encoding="utf-8") as f:
        json.dump(build_observations_snapshot(params), f, indent=2)


def write_run_report_snapshot(params: GeophysicsInvertInput, report: dict):
    report_path = get_run_report_path(
        project_id=params.project_id,
        run_id=params.run_id,
    )

    if report_path is None:
        return

    report_path.parent.mkdir(parents=True, exist_ok=True)

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def normalize_array(values: np.ndarray):
    values = np.asarray(values, dtype=float)

    v_min = float(np.min(values))
    v_max = float(np.max(values))
    v_range = max(v_max - v_min, 1e-9)

    return np.clip((values - v_min) / v_range, 0.0, 1.0)


_GRADE_PROVENANCE = {
    "grade_source": "heuristic_gravity_proxy",
    "assay_supported": False,
    "economically_validated": False,
}


def build_voxel_output(df_anomaly: pl.DataFrame, block_size: float, cutoff_density: float = 2.75):
    _log.warning("[WARNING] Grade heuristic used for exploration preview")
    voxels = []

    for row in df_anomaly.iter_rows(named=True):
        raw_density = row["density"]
        # NaN y None → celda de aire (is_active=False), serializar como null en JSON
        # bool() explícito: np.isfinite() devuelve numpy.bool_ que rompe jsonable_encoder
        is_active = bool((raw_density is not None) and np.isfinite(float(raw_density)))

        if is_active:
            density = float(raw_density)
            density_proxy_index = float(row["grade"]) if row.get("grade") is not None and np.isfinite(float(row["grade"])) else None
            probability = float(row["probability"]) if row.get("probability") is not None and np.isfinite(float(row["probability"])) else None
            modeled_rock_mass_kg_val = float(row["modeled_rock_mass_tonnes"]) if row.get("modeled_rock_mass_tonnes") is not None and np.isfinite(float(row["modeled_rock_mass_tonnes"])) else None
            density_anomaly_score = min(1.0, max(0.0, density - cutoff_density) / max(cutoff_density, 1e-9))
            sens_raw = row.get("sensitivity_proxy", 0.0)
            sensitivity_proxy = float(sens_raw) if sens_raw is not None and np.isfinite(float(sens_raw)) else 0.0
            doi_raw_val = row.get("doi_raw")
            doi_raw_val = float(doi_raw_val) if doi_raw_val is not None and np.isfinite(float(doi_raw_val)) else None
            ps_raw = row.get("posterior_std")
            posterior_std_val = float(ps_raw) if ps_raw is not None and np.isfinite(float(ps_raw)) else None
            density_zone_flag_val = int(row["density_zone_flag"])
        else:
            density = None
            density_proxy_index = None
            probability = None
            modeled_rock_mass_kg_val = None
            density_anomaly_score = None
            sensitivity_proxy = None
            doi_raw_val = None
            posterior_std_val = None
            density_zone_flag_val = None

        voxels.append(
            {
                "ix": int(row["ix"]),
                "iy": int(row["iy"]),
                "iz": int(row["iz"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "z": float(row["z"]),
                "x_m": float(row["x"]),
                "y_m": float(row["y"]),
                "z_m": float(row["z"]),
                "density": density,
                "density_proxy_index": density_proxy_index,
                "modeled_rock_mass_tonnes": modeled_rock_mass_kg_val,
                "density_zone_flag": density_zone_flag_val,
                "is_demo_grade": True,
                "provenance": _GRADE_PROVENANCE,
                "probability": probability,
                "anomaly_intensity": density_proxy_index,
                "target_score": probability,
                "relative_target_score": probability,
                "modeled_density_index": density,
                "density_anomaly_score": density_anomaly_score,
                "sensitivity_proxy": sensitivity_proxy,
                "doi_raw": doi_raw_val,
                "posterior_std": posterior_std_val,  # σ posterior (t/m³), null si no se calculó
                "is_active": is_active,
            }
        )

    return voxels


def build_best_target(df_full, technical_summary: dict = None, uncertainty_diagnostics: dict = None,
                      *, density_min=None, density_max=None, block_size=None,
                      cutoff_density=None):
    """Selecciona el blanco de perforación RESOLUBLE (B1 — null-space honesto).

    ANTES elegía la celda de mayor (probabilidad × max(densidad−2.6, 0) × proxy), un
    scoring sesgado a ALTA densidad: para un objetivo de BAJA densidad (p.ej. el reservorio
    de Laguna del Maule) premiaba el cuerpo ESPURIO de alta densidad saturado al bound en
    el PISO de malla — masa null-space NO constreñida por el dato — y le ponía sello HIGH.
    Recomendaba perforar el lugar equivocado: la mentira más cara del reporte.

    AHORA, sobre el CAMPO ACTIVO COMPLETO (df_full, no sólo las anomalías de alta densidad):
      • excluye celdas bound-saturadas en el piso (densidad ≈ límite petrofísico Y
        profundidad ≈ piso de malla) — son artefactos null-space, no blancos;
      • puntúa por |densidad − fondo| (anomalía de CUALQUIER signo) → surfacea el cuerpo
        dominante a profundidad RESOLUBLE, también de baja densidad;
      • reporta con transparencia el artefacto degradado y JAMÁS lo presenta como HIGH.

    GUARDRAIL: si no se pasan density_min/density_max/block_size, NO se detecta saturación
    de piso (artifact_mask vacío) → comportamiento de selección por |anomalía| sin democión.
    """
    if df_full is None or len(df_full) == 0:
        return None
    active = df_full.filter(pl.col("density").is_not_null() & pl.col("density").is_finite())
    if len(active) == 0:
        return None

    def _arr(name):
        return active[name].to_numpy() if name in active.columns else None

    dens = active["density"].to_numpy().astype(float)
    xs, ys, zs = _arr("x"), _arr("y"), _arr("z")
    prob = _arr("probability")
    prob = np.nan_to_num(prob.astype(float), nan=0.0) if prob is not None else np.zeros_like(dens)
    grade = _arr("grade")
    sens = _arr("sensitivity_proxy")
    if sens is not None:
        sens = np.clip(np.nan_to_num(sens.astype(float), nan=0.0), 0.0, None)

    background = float(np.median(dens))                # fondo robusto del campo recuperado
    anomaly = np.abs(dens - background)                # anomalía de cualquier signo
    floor_depth = float(np.max(ys)) if ys is not None else None

    # ── Detección de null-space: bound-saturado en el piso de malla ──────────────
    artifact_mask = np.zeros(dens.shape, dtype=bool)
    if (density_min is not None and density_max is not None and block_size is not None
            and ys is not None and floor_depth is not None):
        rng = max(float(density_max) - float(density_min), 1e-9)
        tol = 0.02 * rng                               # 2% del rango = "saturado al bound"
        band = 1.5 * float(block_size)                 # dentro de ~1 celda del piso
        saturated = (dens >= float(density_max) - tol) | (dens <= float(density_min) + tol)
        at_floor = ys >= (floor_depth - band)
        artifact_mask = saturated & at_floor
    n_artifact = int(artifact_mask.sum())

    # Targeting ponderado por RESOLUBILIDAD del dato: recomendar perforar donde el dato
    # MUESTRA anomalía Y la CONSTRIÑE (sensitivity_proxy / DOI). El artefacto profundo de
    # null-space (masa apilada en el piso, sensibilidad ~0) queda down-rankeado frente al
    # cuerpo somero data-constreñido — aunque su |anomalía| absoluta sea menor. Sin
    # columna de sensibilidad → fallback a |anomalía| pura (comportamiento previo).
    if sens is not None and np.any(sens > 0):
        score = sens * anomaly
    else:
        score = anomaly
    resolvable = ~artifact_mask
    surfaced_is_artifact = False
    if resolvable.any():
        bi = int(np.argmax(np.where(resolvable, score, -np.inf)))
    else:
        # Degenerado: TODO el modelo satura en el piso → no hay blanco fiable.
        bi = int(np.argmax(score))
        surfaced_is_artifact = True

    # Artefacto degradado (mayor anomalía entre los de piso) — transparencia, no silencio.
    demoted = None
    if n_artifact > 0:
        ai = int(np.argmax(np.where(artifact_mask, anomaly, -np.inf)))
        demoted = {
            "x_m": float(xs[ai]), "y_m": float(ys[ai]), "z_m": float(zs[ai]),
            "density": round(float(dens[ai]), 4), "depth_m": float(ys[ai]),
            "reason": ("bound_saturated_floor: densidad ≈ límite petrofísico y profundidad ≈ "
                       "piso de malla → masa null-space NO constreñida por el dato; no es un "
                       "blanco de perforación."),
        }

    # ── Confianza: JAMÁS HIGH si el blanco surfaceado es un artefacto null-space. ─
    ts = technical_summary or {}
    ud = uncertainty_diagnostics or {}
    overall_level = str(ts.get("overall_level", "")).upper()
    uncertainty_level = str(ud.get("uncertainty_level", "")).upper()
    if overall_level == "GOOD" or uncertainty_level == "LOW":
        confidence_level = "HIGH"
    elif overall_level == "MEDIUM" or uncertainty_level == "MEDIUM":
        confidence_level = "MEDIUM"
    elif overall_level == "LOW" or uncertainty_level == "HIGH":
        confidence_level = "LOW"
    else:
        confidence_level = "UNKNOWN"
    if surfaced_is_artifact:
        confidence_level = "LOW"

    g_val = (float(grade[bi]) if (grade is not None and grade[bi] is not None
                                  and np.isfinite(grade[bi])) else None)
    p_val = float(prob[bi])
    d_val = float(dens[bi])
    das = None
    if cutoff_density is not None:
        das = min(1.0, max(0.0, d_val - float(cutoff_density)) / max(float(cutoff_density), 1e-9))
    is_resolvable = (None if (floor_depth is None or block_size is None)
                     else bool(float(ys[bi]) < floor_depth - 1.5 * float(block_size)))

    return {
        "x_m": float(xs[bi]),
        "y_m": float(ys[bi]),
        "z_m": float(zs[bi]),
        "density": d_val,
        "density_proxy_index": g_val,
        "grade": g_val,
        "is_demo_grade": True,
        "provenance": _GRADE_PROVENANCE,
        "probability": p_val,
        "anomaly_intensity": g_val,
        "target_score": p_val,
        "relative_target_score": p_val,
        "modeled_density_index": d_val,
        "density_anomaly_score": das,
        "confidence_level": confidence_level,
        # ── B1: transparencia null-space ───────────────────────────────────────
        "anomaly_magnitude": round(float(anomaly[bi]), 4),
        "anomaly_background_density": round(background, 4),
        "depth_m": float(ys[bi]),
        "is_resolvable_depth": is_resolvable,
        "is_null_space_artifact": bool(surfaced_is_artifact),
        "n_floor_saturated_cells": n_artifact,
        "floor_saturated_demoted": demoted,
        "selection_note": (
            "Blanco RESOLUBLE = (sensibilidad × |densidad−fondo|) máx excluyendo celdas "
            "bound-saturadas en el piso de malla (null-space). "
            + (f"{n_artifact} celda(s) de piso degradada(s) como artefacto." if n_artifact
               else "Sin artefacto de piso detectado.")
            + (" ADVERTENCIA: todo el modelo satura en el piso; el blanco mostrado es "
               "null-space, NO fiable." if surfaced_is_artifact else "")
        ),
    }


# ── B3: veredicto de calidad RECONCILIADO (un solo veredicto honesto) ──────────
_VERDICT_ORD = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
_ORD_VERDICT = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}


def _priority_to_level(pc: str):
    pc = str(pc or "").upper()
    if "HIGH" in pc:
        return "HIGH"
    if "MEDIUM" in pc:
        return "MEDIUM"
    if pc:  # LOW_RELATIVE_PRIORITY, UNCLASSIFIED, TOTALLY_UNKNOWN_PRIORITY, NONE…
        return "LOW"
    return None


def _reliability_to_level(mrl: str):
    mrl = str(mrl or "").upper()
    if "HIGH" in mrl:
        return "HIGH"
    if "MEDIUM" in mrl:
        return "MEDIUM"
    if "LOW" in mrl or "UNCLASSIFIED" in mrl:
        return "LOW"
    return None


def build_reconciled_verdict(report_payload: dict) -> dict:
    """B3 — UN SOLO veredicto honesto: el eslabón MÁS DÉBIL (worst-of) de las señales de
    calidad que hoy conviven contradictorias en el reporte (confianza de survey,
    confiabilidad del modelo, prioridad de targeting, gate físico de padding/regional r06,
    y si el blanco recuperado es null-space).

    NO inventa métrica nueva: reconcilia las que YA existen tomando la más conservadora.
    Nunca deja sobrevivir un 'HIGH' junto a un REMEDIATION_REQUIRED / UNCLASSIFIED /
    blanco null-space. Devuelve el veredicto; el caller capa (downgrade-only) los campos
    individuales para que el payload sea internamente consistente.
    """
    components = {}
    levels = []  # (nivel, etiqueta_de_la_señal)

    survey_conf = str(report_payload.get("confidence_level", "")).upper()
    components["survey_confidence"] = survey_conf or "UNKNOWN"
    if survey_conf in _VERDICT_ORD:
        levels.append((survey_conf, "survey_confidence"))

    mrl = str(report_payload.get("model_reliability_level", "")).upper()
    components["model_reliability"] = mrl or "UNKNOWN"
    rl = _reliability_to_level(mrl)
    if rl:
        levels.append((rl, "model_reliability"))

    pc = str(report_payload.get("priority_class", "")).upper()
    components["priority_class"] = pc or "UNKNOWN"
    pl_ = _priority_to_level(pc)
    if pl_:
        levels.append((pl_, "priority_class"))

    r06 = report_payload.get("r06_padding_saturation_audit") or {}
    gate = str(r06.get("phase_gate_recommendation", "")).upper()
    components["r06_padding_gate"] = gate or "NOT_RUN"
    if r06:
        # Severidad FÍSICA del padding saturado: fracción de la masa / del forward / del
        # RMS que explica el padding pegado al bound. Se IGNORA delta_chi2_pct (driver del
        # gate): compara el chi2 del solver contra un chi2 recalculado con σ distinto →
        # dispara REMEDIATION falsa aunque mass/forward/rms ≈ 0 (medido en LdM/porphyry:
        # delta_chi2≈80-95% con forward_frac≈0). El veredicto honesto usa lo físico.
        def _f(k):
            try:
                return float(r06.get(k))
            except (TypeError, ValueError):
                return 0.0
        phys = max(_f("forward_fraction_pad_saturated"),
                   _f("mass_fraction_pad_saturated"),
                   _f("delta_rms_pct") / 100.0)
        components["r06_physical_severity"] = round(phys, 6)
        if phys >= 0.10:
            levels.append(("LOW", "r06_padding_physical"))
        elif phys >= 0.01:
            levels.append(("MEDIUM", "r06_padding_physical"))
        # phys < 1% → padding físicamente irrelevante → sin contribución (no cap),
        # aunque el gate diga REMEDIATION (falso por el delta_chi2 inconsistente).

    bt = report_payload.get("best_target") or {}
    bt_artifact = bool(bt.get("is_null_space_artifact"))
    components["best_target_null_space"] = bt_artifact
    if bt_artifact:
        levels.append(("LOW", "best_target_null_space"))

    if not levels:
        overall = "UNKNOWN"
        overall_ord = None
        limiting = []
    else:
        overall_ord = min(_VERDICT_ORD[lv] for lv, _ in levels)
        overall = _ORD_VERDICT[overall_ord]
        limiting = [name for lv, name in levels if _VERDICT_ORD[lv] == overall_ord]

    if overall == "HIGH":
        headline = ("Modelo geofísicamente confiable a su escala: blanco resoluble y bien "
                    "constreñido por el dato.")
        action = "Usar como soporte técnico; integrar con geología antes de decisiones críticas."
    elif overall == "MEDIUM":
        headline = ("Modelo utilizable con CAUTELA; limitado por: " + ", ".join(limiting) +
                    ". Tratar el blanco como indicio a corroborar.")
        action = "Revisar cobertura/residuales/regional antes de comprometer perforación."
    elif overall == "LOW":
        headline = ("Modelo NO confiable como base ÚNICA; limitado por: " + ", ".join(limiting) +
                    ". El blanco es un INDICIO, no un objetivo de perforación.")
        action = ("No perforar sólo con este modelo: recolectar más dato / remover regional / "
                  "revisar saturación de padding antes de decidir.")
    else:
        headline = "Veredicto de calidad indeterminado (señales insuficientes)."
        action = "Revisar la calidad del survey y re-ejecutar."

    return {
        "level": overall,
        "limiting_factors": limiting,
        "components": components,
        "headline": headline,
        "recommended_action": action,
        "method": "weakest_link_reconciliation",
        "note": (
            "Veredicto ÚNICO = el más conservador entre confianza de survey, confiabilidad "
            "del modelo, prioridad de targeting, gate físico de padding/regional (r06) y "
            "validez del blanco (null-space). Reconcilia señales que antes se reportaban por "
            "separado y podían contradecirse (p.ej. GOOD/HIGH junto a UNCLASSIFIED/REMEDIATION)."
        ),
    }


def _cap_confidence_str(current: str, overall_ord) -> str:
    """Downgrade-only de un confidence_level (HIGH/MEDIUM/LOW) al techo del veredicto."""
    if overall_ord is None:
        return current
    cur = str(current or "").upper()
    if cur not in _VERDICT_ORD:
        return current
    if _VERDICT_ORD[cur] <= overall_ord:
        return current
    return _ORD_VERDICT[overall_ord]


def _cap_reliability_str(current: str, overall_ord) -> str:
    """Downgrade-only de model_reliability_level (…_RELIABILITY) al techo del veredicto."""
    if overall_ord is None:
        return current
    cur_lv = _reliability_to_level(current)
    if cur_lv is None or _VERDICT_ORD[cur_lv] <= overall_ord:
        return current
    return {1: "LOW_RELIABILITY", 2: "MEDIUM_RELIABILITY", 3: "HIGH_RELIABILITY"}[overall_ord]


def apply_reconciled_verdict(report_payload: dict) -> dict:
    """Calcula el veredicto reconciliado, lo adjunta como `overall_verdict` y CAPA
    (downgrade-only) confidence_level / model_reliability_level / best_target.confidence_level
    para que el payload no sostenga un 'HIGH' que el veredicto único contradice. NO toca
    priority_class (concepto distinto y con tests propios). Idempotente y non-fatal."""
    verdict = build_reconciled_verdict(report_payload)
    report_payload["overall_verdict"] = verdict
    overall_ord = _VERDICT_ORD.get(verdict["level"])
    if overall_ord is not None:
        report_payload["confidence_level"] = _cap_confidence_str(
            report_payload.get("confidence_level"), overall_ord)
        report_payload["model_reliability_level"] = _cap_reliability_str(
            report_payload.get("model_reliability_level"), overall_ord)
        bt = report_payload.get("best_target")
        if isinstance(bt, dict) and bt.get("confidence_level") is not None:
            bt["confidence_level"] = _cap_confidence_str(bt.get("confidence_level"), overall_ord)
    return verdict


def build_depth_resolution(df_full, observable_depth_max_m, best_target,
                           block_size) -> dict:
    """B2 — resolución de profundidad POR-EJE, derivada del MODELO recuperado (NO usa el
    posterior σ Hutchinson, que sale 100% NaN en casos tipo LdM).

    La gravimetría resuelve la posición HORIZONTAL (apretada) pero NO la PROFUNDIDAD: la
    masa que cae bajo la profundidad observable es cola null-space (data-consistente pero no
    constreñida). Este bloque MIDE esa cola y reporta una historia honesta por-eje, en vez
    de ofrecer un número de profundidad global engañoso.

    Pura y aditiva. df_full = block model recuperado (polars, columnas density,x,y,z).
    observable_depth_max_m = min(cutoff, ny·block) (r05). best_target = salida de B1
    (usa depth_m + is_resolvable_depth). Nunca crashea: df vacío → computed=False.
    """
    out = {
        "computed": False,
        "method": "model_derived_depth_resolution_no_posterior",
        "note": ("Derivado del modelo recuperado (df_full), NO del posterior σ (Hutchinson "
                 "sale NaN en casos tipo LdM). Cuantifica la cola null-space de profundidad."),
    }
    try:
        if df_full is None or len(df_full) == 0:
            out["reason"] = "df_full vacío"
            return out
        active = df_full.filter(pl.col("density").is_not_null() & pl.col("density").is_finite())
        if len(active) == 0 or "y" not in active.columns:
            out["reason"] = "sin celdas activas o sin columna y"
            return out

        dens = active["density"].to_numpy().astype(float)
        xs = active["x"].to_numpy().astype(float) if "x" in active.columns else None
        ys = active["y"].to_numpy().astype(float)
        zs = active["z"].to_numpy().astype(float) if "z" in active.columns else None
        sens = (np.clip(np.nan_to_num(active["sensitivity_proxy"].to_numpy().astype(float), nan=0.0), 0.0, None)
                if "sensitivity_proxy" in active.columns else None)

        background = float(np.median(dens))                 # MISMA def de fondo que B1
        anomaly = np.abs(dens - background)
        total_mass = float(anomaly.sum())
        if total_mass <= 0.0:
            out["reason"] = "campo plano (sin anomalía)"
            return out

        geometric_max = (float(observable_depth_max_m) if observable_depth_max_m is not None
                         else float(np.max(ys)))

        # ── Horizonte de RESOLUBILIDAD = profundidad de investigación (DOI) por SENSIBILIDAD,
        #    NO el cutoff geométrico. MEDIDO: el cutoff (p.ej. 5022 m en LdM) es más profundo
        #    que el propio artefacto null-space → daría deep_mass_fraction=0, contradiciendo
        #    la cola real (~0.88). La sensibilidad cae con la profundidad (el dato deja de
        #    restringir); el horizonte = capa más profunda con sens media ≥ 15% del pico. ──
        horizon_method = "geometric_cutoff_fallback"
        doi_horizon = geometric_max
        if sens is not None and float(np.max(sens)) > 0.0:
            # DOI half-max: capa más profunda cuya sensibilidad media ≥ 50% del PICO de capa.
            # Es la "profundidad de investigación" donde la sensibilidad del dato cae a la
            # mitad de su máximo — convención estándar y robusta (no un umbral arbitrario).
            layers = np.unique(ys)
            layer_mean = np.array([float(sens[ys == yy].mean()) for yy in layers])
            peak = float(layer_mean.max())
            if peak > 0.0:
                ok = layers[layer_mean >= 0.5 * peak]
                doi_horizon = float(ok.max()) if ok.size > 0 else float(layers.min())
                horizon_method = "sensitivity_doi_half_max_layer"
        # No puede ser más profundo que la observabilidad geométrica.
        rdmax = float(min(doi_horizon, geometric_max))

        # ── Cola null-space: fracción de la "masa" de anomalía bajo el horizonte resoluble ──
        deep_mask = ys > rdmax
        deep_mass_fraction = float(anomaly[deep_mask].sum()) / total_mass

        # ── Localización horizontal del cuerpo RESOLUBLE (sobre umbral de anomalía) ──
        horiz_metric_m = None
        resolvable_mask = (ys <= rdmax) & (anomaly > 0)
        if np.any(resolvable_mask) and xs is not None and zs is not None:
            a_r = anomaly[resolvable_mask]
            strong = a_r > 0.5 * float(a_r.max())
            if not np.any(strong):
                strong = a_r > 0
            xr = xs[resolvable_mask][strong]
            zr = zs[resolvable_mask][strong]
            wr = a_r[strong]
            wsum = float(wr.sum())
            if wsum > 0:
                xm = float(np.average(xr, weights=wr))
                zm = float(np.average(zr, weights=wr))
                std_x = float(np.sqrt(np.average((xr - xm) ** 2, weights=wr)))
                std_z = float(np.sqrt(np.average((zr - zm) ** 2, weights=wr)))
                horiz_metric_m = round(0.5 * (std_x + std_z), 1)  # semi-anchura característica

        bs = float(block_size) if block_size else 0.0
        # COMPACIDAD del cuerpo (descriptivo del ANCHO), NO calidad de resolución: la
        # gravimetría SÍ determina el footprint en planta; el ancho es una propiedad
        # GEOLÓGICA (LdM=sistema silícico ancho; DO-27=pipe compacto), no un límite de
        # resolución. Por eso 'broad' ≠ 'malo' y NO degrada el veredicto ni el targeting.
        if horiz_metric_m is None:
            compactness = "unknown"
        elif bs > 0 and horiz_metric_m <= 2.0 * bs:
            compactness = "compact"
        elif bs > 0 and horiz_metric_m <= 5.0 * bs:
            compactness = "broad"
        else:
            compactness = "diffuse"
        horizontal_determined = horiz_metric_m is not None

        # Calidad vertical: dominada por la cola null-space si la mayoría de la masa cae profundo.
        if deep_mass_fraction >= 0.66:
            vert_quality = "null_space_dominated"
        elif deep_mass_fraction >= 0.33:
            vert_quality = "poor"
        else:
            vert_quality = "resolved"

        bt = best_target or {}
        resolvable_body_depth_m = (
            bt.get("depth_m") if bt.get("is_resolvable_depth") else None)

        pct = round(100.0 * deep_mass_fraction, 1)
        statement = (
            (f"Footprint horizontal DETERMINADO (~{horiz_metric_m} m de extensión, "
             f"cuerpo {compactness})."
             if horiz_metric_m is not None else "Footprint horizontal no estimable.")
            + f" Profundidad NO resuelta bajo ~{round(rdmax,1)} m: {pct}% de la masa "
              "recuperada vive en la cola null-space (no constreñida por el dato gravimétrico)."
            + (f" Cuerpo resoluble a ~{round(resolvable_body_depth_m,1)} m." if resolvable_body_depth_m is not None else "")
            + " La gravimetría resuelve DÓNDE en planta, no a qué profundidad."
        )

        out.update({
            "computed": True,
            "resolvable_depth_max_m": round(rdmax, 1),
            "resolvable_depth_horizon_method": horizon_method,
            "geometric_observable_depth_max_m": round(geometric_max, 1),
            "resolvable_body_depth_m": (round(float(resolvable_body_depth_m), 1)
                                        if resolvable_body_depth_m is not None else None),
            "deep_mass_fraction": round(deep_mass_fraction, 3),
            "horizontal_extent_m": horiz_metric_m,
            "background_density_median": round(background, 4),
            "per_axis": {
                # Horizontal = FORTALEZA (lo que gravedad SÍ resuelve), sin 'quality/poor'.
                "horizontal": {
                    "determined": bool(horizontal_determined),
                    "compactness": compactness,
                    "extent_m": horiz_metric_m,
                    "note": ("Gravimetría resuelve el footprint en planta; el ancho "
                             "(compactness) es una propiedad geológica, NO un límite de "
                             "resolución ni una falla de targeting."),
                },
                "vertical": {
                    "quality": vert_quality,
                    "deep_mass_fraction": round(deep_mass_fraction, 3),
                    "reason": (f"deep_mass_fraction={round(deep_mass_fraction,3)}; "
                               f"bajo {round(rdmax,1)} m el dato no restringe"),
                },
            },
            "statement": statement,
        })
        return out
    except Exception as exc:  # nunca rompe la inversión
        out["reason"] = f"error: {exc}"
        return out


def build_geophysical_technical_summary(observation_quality: dict, fit_diagnostics: dict) -> dict:
    oq = observation_quality or {}
    fd = fit_diagnostics or {}
    residual_map = fd.get("residualMap") or []

    survey_level = oq.get("quality_level", "UNKNOWN")
    fit_level = fd.get("fit_level", "UNKNOWN")

    high_count = sum(1 for p in residual_map if p.get("residual_level") == "HIGH")
    total = len(residual_map)
    high_ratio = high_count / total if total > 0 else 0.0

    if high_ratio <= 0.10:
        residual_level = "GOOD"
    elif high_ratio <= 0.25:
        residual_level = "MEDIUM"
    else:
        residual_level = "LOW"

    if survey_level == "GOOD" and fit_level == "GOOD" and residual_level == "GOOD":
        overall_level = "GOOD"
    elif survey_level == "LOW" or fit_level == "LOW" or (residual_level == "LOW" and total >= 10):
        overall_level = "LOW"
    else:
        overall_level = "MEDIUM"

    if overall_level == "GOOD":
        summary = "El levantamiento presenta buena cobertura y el modelo reproduce adecuadamente las observaciones gravimétricas."
    elif overall_level == "MEDIUM":
        summary = "El levantamiento es utilizable, pero existen advertencias de cobertura o ajuste que deben revisarse antes de perforación."
    else:
        summary = "La inversión produjo un resultado de baja confiabilidad técnica; se recomienda mejorar datos de entrada antes de usar el modelo para decisión."

    key_findings = [
        f"Observaciones procesadas: {oq.get('observation_count', 'N/A')}.",
        f"Cobertura X: {oq.get('coverage_ratio_x', 'N/A')}; cobertura Z: {oq.get('coverage_ratio_z', 'N/A')}.",
        f"Ajuste observed vs modeled: {fit_level}.",
        f"Sensores con residual alto: {high_count} de {total}."
    ]

    warnings = list(oq.get("warnings", []))
    if fit_level == "LOW":
        warnings.append("El modelo tiene un nivel de ajuste general débil con respecto a las observaciones.")
    if residual_level == "LOW":
        warnings.append(f"Alta proporción de sensores ({high_ratio*100:.1f}%) presentan residuales anómalos (HIGH).")

    if overall_level == "GOOD":
        recommended_next_steps = ["Usar el modelo como base para interpretación preliminar y targeting."]
    elif overall_level == "MEDIUM":
        recommended_next_steps = [
            "Revisar sensores con residual alto antes de priorizar perforación.",
            "Considerar aumentar cobertura de observaciones en zonas débiles."
        ]
    else:
        recommended_next_steps = [
            "No usar el modelo como base única para decisión de perforación.",
            "Recolectar observaciones adicionales o revisar calidad del survey."
        ]

    return {
        "overall_level": overall_level,
        "survey_level": survey_level,
        "fit_level": fit_level,
        "residual_level": residual_level,
        "summary": summary,
        "key_findings": key_findings,
        "warnings": warnings,
        "recommended_next_steps": recommended_next_steps,
    }


def build_uncertainty_diagnostics(observation_quality: dict, fit_diagnostics: dict, technical_summary: dict) -> dict:
    oq = observation_quality or {}
    fd = fit_diagnostics or {}
    ts = technical_summary or {}
    residual_map = fd.get("residualMap") or []

    score = 0.0
    drivers = []

    # A) Calidad del survey
    survey_level = str(oq.get("quality_level", "UNKNOWN")).upper()
    if survey_level == "MEDIUM":
        score += 0.15
        drivers.append("Calidad del survey evaluada como MEDIA.")
    elif survey_level == "LOW":
        score += 0.30
        drivers.append("Calidad del survey evaluada como BAJA.")

    # B) Cobertura espacial
    cov_x = float(oq.get("coverage_ratio_x", 1.0))
    cov_z = float(oq.get("coverage_ratio_z", 1.0))
    if cov_x < 0.6 and cov_z < 0.6:
        score += 0.20
        drivers.append("Cobertura espacial baja en ambos ejes (X, Z).")
    elif cov_x < 0.6:
        score += 0.10
        drivers.append("Cobertura espacial baja en el eje X.")
    elif cov_z < 0.6:
        score += 0.10
        drivers.append("Cobertura espacial baja en el eje Z.")

    # C) Señal gravimétrica
    dyn_range = float(oq.get("signal_dynamic_range", 1.0))
    g_std = float(oq.get("g_std", 1.0))
    warnings_list = oq.get("warnings", [])
    has_range_warning = any("rango dinámico" in str(w).lower() for w in warnings_list)
    
    if dyn_range <= 1e-6 or has_range_warning:
        score += 0.15
        drivers.append("Señal gravimétrica con bajo rango dinámico.")
    if g_std <= 1e-9:
        score += 0.15
        drivers.append("Señal gravimétrica con varianza excepcionalmente baja.")

    # D) Ajuste observed vs modeled
    fit_level = str(fd.get("fit_level", "UNKNOWN")).upper()
    if fit_level == "MEDIUM":
        score += 0.20
        drivers.append("Ajuste (observed vs modeled) clasificado como MEDIO.")
    elif fit_level == "LOW":
        score += 0.40
        drivers.append("Ajuste (observed vs modeled) clasificado como DÉBIL.")

    # E) Residuales
    high_count = sum(1 for p in residual_map if p.get("residual_level") == "HIGH")
    total = len(residual_map)
    high_ratio = high_count / total if total > 0 else 0.0

    if high_ratio > 0.25:
        score += 0.30
        drivers.append("Alta proporción de sensores (>25%) con residual HIGH.")
    elif high_ratio > 0.10:
        score += 0.15
        drivers.append("Proporción moderada de sensores (>10%) con residual HIGH.")

    # F) technicalSummary
    overall_level = str(ts.get("overall_level", "UNKNOWN")).upper()
    if overall_level == "LOW":
        score += 0.25
        drivers.append("Resumen técnico global indica baja confiabilidad general.")
    elif overall_level == "MEDIUM":
        score += 0.10
        drivers.append("Resumen técnico global indica confiabilidad moderada.")

    score = min(round(score, 3), 1.0)

    # Reglas de nivel e interpretación
    if score < 0.35:
        level = "LOW"
        interpretation = "La incertidumbre geofísica estimada es baja; el modelo es apto para interpretación preliminar."
        recommended_action = "Usar el modelo como soporte técnico preliminar y continuar con integración geológica."
    elif score < 0.70:
        level = "MEDIUM"
        interpretation = "La incertidumbre geofísica estimada es media; se recomienda revisar cobertura, residuales y calidad del survey antes de decisiones críticas."
        recommended_action = "Revisar sensores con residual alto y considerar nuevas observaciones en zonas de baja cobertura."
    else:
        level = "HIGH"
        interpretation = "La incertidumbre geofísica estimada es alta; el modelo no debe usarse como base única para perforación o diseño."
        recommended_action = "Recolectar más observaciones, revisar calibración instrumental y repetir inversión antes de tomar decisiones."

    return {
        "uncertainty_level": level,
        "uncertainty_score": score,
        "drivers": drivers,
        "interpretation": interpretation,
        "recommended_action": recommended_action,
        # Transparencia científica: esto es una RÚBRICA CUALITATIVA (suma de
        # penalizaciones por calidad de survey, cobertura, ajuste y residuales),
        # NO un posterior estadístico. No produce barras de error por vóxel ni
        # cuantifica la no-unicidad gravimétrica. La incertidumbre estadística
        # real (diag de la covarianza posterior vía Hutchinson) es un upgrade
        # planificado (Fase 3) y debe presentarse por separado cuando exista.
        "method": "heuristic_qualitative_rubric",
        "is_statistical_posterior": False,
        "method_note": (
            "Score heurístico cualitativo de confiabilidad; no es una "
            "cuantificación de incertidumbre estadística (posterior) ni "
            "sustituye barras de error por vóxel."
        ),
    }


def build_sensor_quality_flags(fit_diagnostics: dict) -> dict:
    fd = fit_diagnostics or {}
    residual_map = fd.get("residualMap") or []

    sensor_count = len(residual_map)
    flagged_sensors = []

    for p in residual_map:
        flags = []
        if p.get("residual_level") == "HIGH":
            flags.append("HIGH_RESIDUAL")
        if float(p.get("normalized_residual", 0.0)) >= 0.85:
            flags.append("EXTREME_NORMALIZED_RESIDUAL")
        
        if flags:
            sensor_data = dict(p)
            sensor_data["flags"] = flags
            sensor_data["review_priority"] = "HIGH" if "EXTREME_NORMALIZED_RESIDUAL" in flags else "MEDIUM"
            flagged_sensors.append(sensor_data)

    flagged_sensors.sort(key=lambda x: float(x.get("abs_residual", 0.0)), reverse=True)
    flagged_sensors = flagged_sensors[:50]
    
    flagged_count = len([p for p in residual_map if p.get("residual_level") == "HIGH" or float(p.get("normalized_residual", 0.0)) >= 0.85])
    flagged_ratio = flagged_count / sensor_count if sensor_count > 0 else 0.0

    if flagged_ratio <= 0.10:
        flag_level = "LOW"
        summary = "La mayoría de sensores presenta comportamiento consistente con el ajuste del modelo."
        recommended_action = "Mantener sensores, revisar solo los de prioridad alta si existen."
    elif flagged_ratio <= 0.25:
        flag_level = "MEDIUM"
        summary = "Existe un subconjunto de sensores con residuales altos que debe revisarse antes de decisiones críticas."
        recommended_action = "Revisar sensores marcados y contrastarlos con libreta de terreno/calibración."
    else:
        flag_level = "HIGH"
        summary = "Una proporción importante de sensores presenta residuales altos; se recomienda revisar survey y calibración."
        recommended_action = "Revisar calibración, posicionamiento y calidad del levantamiento antes de usar el modelo como soporte principal."

    return {
        "sensor_count": sensor_count,
        "flagged_count": flagged_count,
        "flagged_ratio": round(flagged_ratio, 4),
        "flag_level": flag_level,
        "flagged_sensors": flagged_sensors,
        "summary": summary,
        "recommended_action": recommended_action
    }



def compute_priority_class_from_report(
    favorability_result: dict,
    technical_summary: dict,
    uncertainty_diagnostics: dict,
) -> tuple:
    """Clasifica prioridad relativa de exploración amarrada al favorability_score real.

    Reglas inviolables:
    - Rule 1: overall_level == "LOW"  → no puede ser HIGH_RELATIVE_PRIORITY.
    - Rule 2: favorability_score < 25 → no puede ser HIGH_RELATIVE_PRIORITY.
    - Rule 3: quality_label BAJA/INSUFICIENTE → máximo LOW_RELATIVE_PRIORITY.
    - Rule 4: satellite_support not_evaluated → warning sin cambiar clase.

    Retorna (priority_class_str, warnings_list).
    """
    fav = favorability_result or {}
    ts = technical_summary or {}

    warnings_out = []

    favorability_score = float(fav.get("score", 0.0))
    quality_label = str(fav.get("quality_label", "")).upper()
    satellite_support = str(fav.get("satellite_support", "")).lower()
    overall_level = str(ts.get("overall_level", "")).upper()

    # Rule 4: warning only, no class change
    if satellite_support in ("not_evaluated", "no_evaluado", ""):
        warnings_out.append(
            "Soporte satelital no evaluado; la clasificación de prioridad tiene mayor incertidumbre."
        )

    # Rule 3: quality BAJA or INSUFICIENTE → max LOW_RELATIVE_PRIORITY
    if quality_label in ("BAJA", "INSUFICIENTE"):
        warnings_out.append(
            f"Calidad geofísica '{quality_label}' limita la clase máxima a LOW_RELATIVE_PRIORITY."
        )
        return PriorityClass.LOW_RELATIVE_PRIORITY.value, warnings_out

    # Rules 1 & 2: cannot be HIGH if overall_level=LOW or favorability_score < 25
    blocked_from_high = (overall_level == "LOW") or (favorability_score < 25.0)

    if favorability_score >= 65.0:
        candidate = PriorityClass.HIGH_RELATIVE_PRIORITY
    elif favorability_score >= 35.0:
        candidate = PriorityClass.MEDIUM_RELATIVE_PRIORITY
    elif favorability_score >= 10.0:
        candidate = PriorityClass.LOW_RELATIVE_PRIORITY
    else:
        return PriorityClass.UNCLASSIFIED.value, warnings_out

    if blocked_from_high and candidate == PriorityClass.HIGH_RELATIVE_PRIORITY:
        candidate = PriorityClass.MEDIUM_RELATIVE_PRIORITY
        warnings_out.append(
            "Reclasificado HIGH→MEDIUM: overall_level=LOW o favorability_score < 25."
        )

    return candidate.value, warnings_out


def build_geophysics_report(
    voxels,
    total_voxels: int,
    cutoff_density: float,
    total_tonnage: float,
    parquet_path: str,
    technical_summary: dict = None,
    uncertainty_diagnostics: dict = None,
    expose_demo_grade: bool = True,
    expose_economic_estimates: bool = False,
):
    # Integridad científica (gap #1): cuando expose_demo_grade=False, la ley proxy
    # (avg_grade / avg_density_proxy_index) se reporta como None en lugar de un número
    # fabricado. Las claves permanecen presentes (compatibilidad de consumidores).
    _demo_grade_value = (lambda v: v if expose_demo_grade else None)
    # Compliance JORC / NI 43-101 (gap #1, V2 quick-win): los campos que insinúan
    # recurso/reserva o instrucción accionable —estimated_*_tonnage, max_probability y
    # drill_recommendation— NO se emiten en modo exploración (por defecto). Solo se
    # exponen bajo expose_economic_estimates=True (modo "escenario conceptual" opt-in).
    # Las claves permanecen presentes en None (compatibilidad de consumidores) y las
    # variantes canónicas seguras (max_ranking_score, preliminary_signal, max_target_score,
    # avg_anomaly_intensity) se conservan siempre. La gravimetría mide contraste de
    # densidad, no leyes ni tonelajes de mineral; emitir un tonelaje junto a un disclaimer
    # que lo niega es un pasivo regulatorio, no una mitigación.
    _econ_value = (lambda v: v if expose_economic_estimates else None)
    compliance_mode = "conceptual_scenario" if expose_economic_estimates else "exploration_only"
    semantic_note = (
        "anomaly_intensity, target_score y relative_target_score son interpretaciones preliminares "
        "derivadas del modelo gravimétrico; no representan ley mineral confirmada ni reserva."
    )
    jorc_disclaimer = (
        "Este informe es una interpretación geofísica preliminar y no constituye "
        "una estimación de recursos minerales bajo NI 43-101 o JORC 2012. "
        "No ha sido revisado por un Qualified Person ni Competent Person. "
        "Requiere validación profesional independiente antes de cualquier uso regulatorio o de inversión."
    )
    ts = technical_summary or {}
    ud = uncertainty_diagnostics or {}
    overall_level = str(ts.get("overall_level", "")).upper()
    uncertainty_level = str(ud.get("uncertainty_level", "")).upper()
    
    if overall_level == "GOOD" or uncertainty_level == "LOW":
        confidence_level = "HIGH"
    elif overall_level == "MEDIUM" or uncertainty_level == "MEDIUM":
        confidence_level = "MEDIUM"
    elif overall_level == "LOW" or uncertainty_level == "HIGH":
        confidence_level = "LOW"
    else:
        confidence_level = "UNKNOWN"

    if overall_level == "GOOD" or uncertainty_level == "LOW":
        model_reliability_level = "HIGH_RELIABILITY"
    elif overall_level == "LOW" or uncertainty_level == "HIGH":
        model_reliability_level = "LOW_RELIABILITY"
    elif overall_level == "MEDIUM" or uncertainty_level == "MEDIUM":
        model_reliability_level = "MEDIUM_RELIABILITY"
    else:
        model_reliability_level = "UNCLASSIFIED_RELIABILITY"

    if not voxels:
        return {
            "status": "done",
            "priority_class": PriorityClass.UNCLASSIFIED.value,
            "model_reliability_level": model_reliability_level,
            "max_ranking_score": 0,
            "preliminary_signal": "OBSERVE",
            "risk_level": "HIGH",
            "max_probability": _econ_value(0),
            "drill_recommendation": _econ_value("OBSERVE"),
            "compliance_mode": compliance_mode,
            "min_density": 0,
            "avg_density": 0,
            "max_density": 0,
            "estimated_total_tonnage": _econ_value(int(total_tonnage)),
            "estimated_anomaly_tonnage": _econ_value(0),
            "avg_grade": _demo_grade_value(0),
            "avg_density_proxy_index": _demo_grade_value(0),
            "is_demo_grade": True,
            "provenance": _GRADE_PROVENANCE,
            "anomaly_score": 0,
            "cutoff_density": cutoff_density,
            "total_voxels": total_voxels,
            "returned_voxels": 0,
            "parquet_path": parquet_path,
            "avg_anomaly_intensity": 0,
            "max_target_score": 0,
            "confidence_level": confidence_level,
            "semantic_note": semantic_note,
            "disclaimer": jorc_disclaimer,
        }

    # Excluir celdas de aire (is_active=False) del cálculo de bounds y percentiles
    active_voxels = [v for v in voxels if v.get("is_active", True) and v["density"] is not None]
    if not active_voxels:
        active_voxels = voxels  # fallback defensivo
    densities = np.array([float(v["density"]) for v in active_voxels], dtype=float)
    grades = np.array([float(v.get("density_proxy_index") or 0.0) for v in active_voxels], dtype=float)
    probabilities = np.array([float(v["probability"] or 0.0) for v in active_voxels], dtype=float)
    tonnages = np.array([float(v.get("modeled_rock_mass_tonnes") or 0.0) for v in active_voxels], dtype=float)

    min_density = float(np.min(densities))
    avg_density = float(np.mean(densities))
    max_density = float(np.max(densities))

    avg_grade = float(np.average(grades, weights=np.maximum(tonnages, 1e-9)))
    max_probability = float(np.max(probabilities))

    anomaly_score = float(
        np.mean(
            probabilities
            * np.clip((densities - 2.6) / max(4.2 - 2.6, 1e-9), 0.0, 1.0)
        )
    )

    estimated_anomaly_tonnage = float(np.sum(tonnages))

    recommendation = (
        "DRILL"
        if max_density >= 2.75 and max_probability >= 0.45 and avg_grade >= 0.3
        else "OBSERVE"
    )
    # preliminary_signal: nombre técnico sin connotación accionable; DRILL_CANDIDATE
    # reemplaza DRILL para evitar interpretación como instrucción formal de perforación.
    preliminary_signal = "DRILL_CANDIDATE" if recommendation == "DRILL" else recommendation

    if max_probability < 0.45 or max_density < cutoff_density:
        risk_level = "HIGH"
    elif max_probability < 0.75:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "status": "done",
        "priority_class": PriorityClass.UNCLASSIFIED.value,
        "model_reliability_level": model_reliability_level,
        "max_ranking_score": round(max_probability, 3),
        "preliminary_signal": preliminary_signal,
        "risk_level": risk_level,
        "max_probability": _econ_value(round(max_probability, 3)),
        "drill_recommendation": _econ_value(preliminary_signal),
        "compliance_mode": compliance_mode,
        "min_density": round(min_density, 3),
        "avg_density": round(avg_density, 3),
        "max_density": round(max_density, 3),
        "estimated_total_tonnage": _econ_value(int(total_tonnage)),
        "estimated_anomaly_tonnage": _econ_value(int(estimated_anomaly_tonnage)),
        "avg_grade": _demo_grade_value(round(avg_grade, 3)),
        "avg_density_proxy_index": _demo_grade_value(round(avg_grade, 3)),
        "is_demo_grade": True,
        "provenance": _GRADE_PROVENANCE,
        "anomaly_score": round(anomaly_score, 3),
        "cutoff_density": cutoff_density,
        "total_voxels": total_voxels,
        "returned_voxels": len(voxels),
        "parquet_path": parquet_path,
        "avg_anomaly_intensity": round(avg_grade, 3),
        "max_target_score": round(max_probability, 3),
        "confidence_level": confidence_level,
        "semantic_note": semantic_note,
        "disclaimer": jorc_disclaimer,
    }


def _run_checkerboard_qa_fast(
    kernel_sparse_core,
    nx: int,
    ny: int,
    nz: int,
    lambda_mag: float,
) -> dict:
    """
    QA de resolución automático post-inversión.

    Reutiliza kernel_sparse_core (ya construido) — sin reconstruir el kernel.
    LSQR reducido a 150 iteraciones con damp=lambda_mag (Tikhonov escalar).
    No modifica resultados principales. Llamado desde run_geophysics_inversion.

    Retorna: {"pearson_r", "status", "sign_recovery_pct", "elapsed_s"}
    """
    import time as _time
    from scipy.sparse.linalg import lsqr as _lsqr
    from exploration.checkerboard_test import (
        build_checkerboard_model,
        compute_checkerboard_metrics,
    )

    t0 = _time.perf_counter()

    true_contrast = build_checkerboard_model(nx, ny, nz, contrast=0.3)
    g_synth = kernel_sparse_core @ true_contrast

    result = _lsqr(
        kernel_sparse_core,
        g_synth,
        damp=float(lambda_mag),
        iter_lim=150,
        show=False,
    )
    est_density_qa = 2.6 + result[0]

    metrics = compute_checkerboard_metrics(true_contrast, est_density_qa, base_density=2.6)
    pearson_r = float(metrics.get("pearson_r", 0.0))

    if pearson_r >= 0.6:
        status = "PASS"
    elif pearson_r >= 0.4:
        status = "WARNING"
    else:
        status = "FAIL"

    return {
        "pearson_r": pearson_r,
        "status": status,
        "sign_recovery_pct": float(metrics.get("sign_recovery_pct", 0.0)),
        "elapsed_s": round(_time.perf_counter() - t0, 2),
    }


def _build_implicit_geology_reference(params, x_c_full, y_c_full, z_c_full, base_density):
    """FASE 7.2 (God-Tier) — Modelo de referencia (contraste, grilla completa) desde φ.

    Construye el campo implícito φ (HRBF) desde los contactos litológicos de los
    sondajes, lo evalúa en los centros de la grilla de inversión y lo convierte en
    un m_ref petrofísico por celda (Li & Oldenburg 1999). El m_ref vive en espacio
    de CONTRASTE (densidad − base_density), igual que el resto del solver.

    Devuelve (m_ref_contrast_full | None, meta | None). None si implicit_geology no
    está activado → la inversión queda byte-idéntica. Levanta HTTPException 422 si se
    activa pero NO hay sondajes con litología (input incoherente: no se inventa
    geología desde la nada).
    """
    geo = getattr(params, "implicit_geology", None)
    if geo is None or not bool(getattr(geo, "enabled", False)):
        return None, None

    _bh_list = getattr(params, "boreholes", None) or []
    _lith_intervals = [b for b in _bh_list if getattr(b, "lithology", None)]
    if not _lith_intervals:
        raise HTTPException(
            status_code=422,
            detail=(
                "implicit_geology está activado pero ningún sondaje declara litología "
                "(boreholes[].lithology). El prior geológico implícito requiere contactos "
                "litológicos de sondaje; no se infiere geología sin dato."
            ),
        )

    from exploration.implicit_modeling import (
        ImplicitGeologicalModel,
        OrientationDatum,
        build_spatial_prior_from_implicit,
    )

    orientations = None
    if geo.orientations:
        orientations = [
            OrientationDatum.from_dip_azimuth(o.x_m, o.y_m, o.z_m, o.dip_deg, o.azimuth_deg)
            for o in geo.orientations
        ]

    try:
        model = ImplicitGeologicalModel.from_boreholes(
            intervals=_lith_intervals,
            target_lithologies=geo.target_lithologies,
            orientations=orientations,
            smoothing=float(geo.smoothing),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"implicit_geology: {exc}")

    pts = np.column_stack([
        np.asarray(x_c_full, dtype=np.float64),
        np.asarray(y_c_full, dtype=np.float64),
        np.asarray(z_c_full, dtype=np.float64),
    ])
    phi = model.field.evaluate(pts)

    host_mean = (
        float(base_density) if geo.host_density_t_m3 is None
        else float(geo.host_density_t_m3)
    )
    prior = build_spatial_prior_from_implicit(
        phi,
        target_mean=float(geo.target_density_t_m3),
        host_mean=host_mean,
        target_std=float(geo.target_std_t_m3),
        host_std=float(geo.host_std_t_m3),
        softness=float(geo.softness),
    )
    # m_ref del solver vive en CONTRASTE (densidad − base_density).
    m_ref_contrast = (prior.mean - float(base_density)).astype(np.float64)

    meta = {
        "enabled": True,
        "binding": "m_ref (Li & Oldenburg reference model)",
        "target_lithologies": list(model.target_lithologies),
        "n_value_points": int(model.n_value_points),
        "n_contact_points": int(model.n_contact_points),
        "n_orientations": int(model.n_orientations),
        "n_target_cells": int(np.count_nonzero(prior.class_label)),
        "n_total_cells": int(phi.size),
        "target_density_t_m3": float(geo.target_density_t_m3),
        "host_density_t_m3": float(host_mean),
        "softness": float(geo.softness),
    }
    return m_ref_contrast, meta


def _build_lithology_bounds_array(params, axis: str):
    """FASE 2.3 — Arma el array (n,6) de bounds por unidad litológica para el solver.

    Empareja la `lithology` de cada intervalo de sondaje (case-insensitive) contra la
    tabla LITHOLOGY_BOUNDS_DEFAULTS extendida/sobreescrita por params.lithology_bounds.
    axis ∈ {"density","susc"}. Devuelve np.ndarray (n,6) [x,z,yf,yt,min,max] o None.
    Solo activo si params.lithology_hard_constraint es True.
    """
    if not bool(getattr(params, "lithology_hard_constraint", False)):
        return None
    _bh_list = getattr(params, "boreholes", None) or []
    if not _bh_list:
        return None

    from exploration.pgi_engine import LITHOLOGY_BOUNDS_DEFAULTS

    # Tabla efectiva: defaults + overrides del usuario (normalizada a minúsculas).
    _table: dict[str, tuple] = {}
    for _name, _b in LITHOLOGY_BOUNDS_DEFAULTS.items():
        _table[_name.lower()] = _b.get(axis)
    for _lb in (getattr(params, "lithology_bounds", None) or []):
        if axis == "density":
            _rng = (_lb.density_min, _lb.density_max)
        else:
            _rng = (_lb.susc_min, _lb.susc_max)
        if _rng[0] is not None and _rng[1] is not None:
            _table[str(_lb.name).lower()] = (float(_rng[0]), float(_rng[1]))

    _rows = []
    for _bh in _bh_list:
        _lith = getattr(_bh, "lithology", None)
        if not _lith:
            continue
        _rng = _table.get(str(_lith).lower())
        if _rng is None or _rng[0] is None or _rng[1] is None:
            continue
        _rows.append([_bh.x_m, _bh.z_m, _bh.y_from_m, _bh.y_to_m, float(_rng[0]), float(_rng[1])])
    if not _rows:
        return None
    return np.asarray(_rows, dtype=np.float64)


def run_magnetic_inversion(params: GeophysicsInvertInput):
    """
    FASE 9A — Orquestación del motor magnético INDEPENDIENTE.

    Activado por run_geophysics_inversion cuando params.magnetic_nt está presente.
    Construye la grilla core, arma el kernel dipolar TMI y resuelve la inversión de
    SUSCEPTIBILIDAD (SI). NO toca el pipeline gravimétrico ni fabrica densidad/ley.
    Motor aislado: sin Joint Inversion, sin Cross-Gradient (Fase 9A).

    Las coordenadas vienen de `observations` (x_m,y_m,z_m); el campo `g` se IGNORA
    en este modo. El dato invertido es params.magnetic_nt (anomalía TMI, nT).
    """
    from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
    from exploration.geophysics_weights import apparent_susceptibility, true_susceptibility

    project_id = params.project_id
    run_id = params.run_id

    def _update(status, progress, stage, message, metrics=None, error=None):
        if project_id and run_id:
            try:
                update_run_status(project_id, run_id, status, progress, stage, message, metrics, error)
            except Exception:
                pass

    _log.info("magnetic_inversion_start", project_id=project_id, run_id=run_id)
    _mag_start_utc = datetime.now(timezone.utc)
    ensure_runtime_dirs()
    _update("running", 0.0, "loading_data", "Validando input magnético (Fase 9A)...")

    # ── Validación del input magnético (independiente de la gravimétrica) ─────
    obs = params.observations
    mag = np.asarray(params.magnetic_nt, dtype=float)
    if len(mag) != len(obs):
        raise HTTPException(
            status_code=422,
            detail=f"magnetic_nt (len={len(mag)}) debe tener el mismo largo que observations (len={len(obs)}).",
        )
    if not np.isfinite(mag).all():
        raise HTTPException(status_code=422, detail="magnetic_nt contiene valores no finitos (NaN/Inf).")
    if np.allclose(mag, 0.0):
        raise HTTPException(status_code=422, detail="magnetic_nt es todo ~0: no hay señal magnética para invertir.")
    if params.susc_max <= params.susc_min:
        raise HTTPException(status_code=422, detail="susc_max debe ser mayor que susc_min.")

    total_voxels = params.nx * params.ny * params.nz
    if total_voxels > 10_000_000:
        raise HTTPException(status_code=422, detail=f"Modelo demasiado grande (nx*ny*nz>10 000 000): {total_voxels} voxels.")
    if params.cutoff_radius < params.block_size:
        raise HTTPException(status_code=422, detail="cutoff_radius no puede ser menor que block_size.")

    nx, ny, nz, dx = params.nx, params.ny, params.nz, params.block_size

    # ── PRODUCCIÓN MAGNÉTICA: Tensor Mesh con Padding (paridad con gravedad) ───
    # El motor magnético recibía la malla CORE pelada (sin padding) → una fuente
    # fuerte en el borde del survey saturaba la pared del modelo (artefacto de borde
    # medido en Raglan). Aquí se construye la misma malla extendida que ya usa el
    # path gravimétrico (build_tensor_mesh_with_padding): un bloque core uniforme +
    # n_pad capas geométricas por cara. El padding es la condición de frontera
    # físicamente correcta de campos potenciales (la Tierra no termina en el borde).
    #
    # Criterio FÍSICO del padding (no la métrica Raglan): con n_pad=5 y pad_factor=1.3
    # el padding extiende ~9 anchos de celda más allá de cada cara
    # (Σ dx·1.3^k, k=0..4 ≈ 9.04·dx). Para el campo dipolar (decaimiento 1/r³) eso
    # lleva la magnetización del borde a un nivel despreciable en la frontera externa.
    # Se reusa el default de producción de gravedad (idéntico criterio, mismo build).
    mesh         = build_tensor_mesh_with_padding(params)
    x_c_full     = mesh["x_c"]
    y_c_full     = mesh["y_c"]
    z_c_full     = mesh["z_c"]
    is_core      = mesh["is_core"]
    hx, hy, hz   = mesh["hx"], mesh["hy"], mesh["hz"]
    nx_total     = mesh["nx_total"]
    ny_total     = mesh["ny_total"]
    nz_total     = mesh["nz_total"]
    # Arrays CORE (sin padding): índices y centros para voxels/parquet/anclajes.
    ix  = mesh["ix_core"]
    iy  = mesh["iy_core"]
    iz  = mesh["iz_core"]
    x_c = mesh["x_c_core"]
    y_c = mesh["y_c_core"]
    z_c = mesh["z_c_core"]
    # Máscara de padding sobre la grilla COMPLETA (True = celda de padding).
    _padding_mask_mag = ~is_core

    sensor_coords = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)
    if not np.isfinite(sensor_coords).all():
        raise HTTPException(status_code=422, detail="Coordenadas de sensores con NaN/Inf.")

    # ── Superficie DEM densa (anti-staircase), paridad con gravedad ───────────
    # Reemplaza topography_elevations=None por la superficie suave interpolada desde
    # sensor_elevations_masl (interpolación LINEAL dentro del convex hull, nearest en
    # el padding). Fallback seguro a None si no hay elevaciones o falla la interpolación.
    _topo_mag = None
    _topo_used_mag = "flat"
    _sensor_elevs_mag = getattr(params, "sensor_elevations_masl", None)
    if _sensor_elevs_mag is not None and len(_sensor_elevs_mag) == len(obs):
        try:
            from core.geo_utils import interpolate_surface_depths as _interp_surface_mag
            _elev_arr_mag = np.asarray(_sensor_elevs_mag, dtype=np.float64)
            _max_elev_mag = float(np.max(_elev_arr_mag))
            _surface_depths_mag = _max_elev_mag - _elev_arr_mag  # prof desde el punto más alto
            _topo_mag, _surf_mode_mag = _interp_surface_mag(
                sensor_coords[:, [0, 2]],                       # (x=Norte, z=Este)
                _surface_depths_mag,
                np.column_stack([x_c_full, z_c_full]),
            )
            _topo_used_mag = f"from_sensor_elevations_masl[{_surf_mode_mag}]"
            _log.info(
                "magnetic_topography_activated",
                max_elev_masl=round(_max_elev_mag, 1),
                surface_mode=_surf_mode_mag,
            )
        except Exception as _topo_exc_mag:
            _log.warning("magnetic_topography_nonfatal", error=str(_topo_exc_mag))
            _topo_mag = None
            _topo_used_mag = "flat_fallback"

    _update("running", 0.2, "building_kernel", "Construyendo kernel dipolar TMI...")
    forward = MagnetometryForward(
        dx, dx, dx,
        cutoff_radius=params.cutoff_radius,
        inclination_deg=params.inclination_deg,
        declination_deg=params.declination_deg,
        field_intensity_nt=params.field_intensity_nt,
        near_field_mode=getattr(params, "magnetic_near_field", "dipole"),
    )
    # Inversor sobre la malla COMPLETA (core + padding) — el Laplaciano no-uniforme
    # y la smallness diferencial de padding operan en esta grilla; los resultados se
    # reducen al core (is_core) antes de construir voxels/parquet.
    inversor = MagnetometryInversion(nx_total, ny_total, nz_total, dx)

    # ── FASE 20C: Magnetic Vector Inversion (MVI) — modo OPT-IN ───────────────
    # magnetization_model="vector" invierte el VECTOR M=(Mx,My,Mz) por celda y
    # recupera la DIRECCIÓN de magnetización desde los datos (maneja remanencia
    # oblicua sin asumirla). Reemplaza conceptualmente la remanencia Q-ratio (Fase 12)
    # y NO usa anclaje de sondajes (fuera de alcance). El observable de targeting es
    # la amplitud |M| (susceptibilidad efectiva), que se publica en la columna
    # susceptibility_si para reutilizar todo el payload/parquet escalar sin duplicar.
    _is_mvi = getattr(params, "magnetization_model", "scalar") == "vector"

    # ── FASE 1.2: Auto-desmagnetización (self-demag) — cambio de variable κ↔κ_eff ──
    # El motor lineal invierte la susceptibilidad APARENTE κ_eff = κ/(1+Nκ). Para
    # mantener el solver INTACTO, la corrección se aplica en la frontera del servicio:
    # bounds y anclajes VERDADEROS → APARENTES antes de resolver; salida APARENTE →
    # VERDADERA al reportar. Solo en el modo escalar inducido (no MVI, no remanencia
    # total_field, que usan otro kernel). κ_eff es monótona en κ → los bounds mapean
    # sin ambigüedad. Ver exploration/geophysics_weights.py.
    _demag_N = float(getattr(params, "self_demag_factor", 0.0) or 0.0)
    _use_demag = _demag_N > 0.0 and not _is_mvi
    # susc_max APARENTE para los bounds del solver (susc_min=0 → 0 aparente también).
    _susc_max_solve = (
        float(apparent_susceptibility(params.susc_max, _demag_N)) if _use_demag else params.susc_max
    )

    # ── Anclaje por sondajes (FASE 9B): el motor magnético lee ESTRICTAMENTE
    # susceptibility_si. Los intervalos sin susceptibilidad (None) se SALTAN: un
    # sondaje netamente gravimétrico no aporta restricción magnética. Validado
    # contra bounds. ──
    boreholes_arr = None
    _bh_list = getattr(params, "boreholes", None) or []
    if _bh_list:
        _rows = []
        for _i, _bh in enumerate(_bh_list):
            _susc = _bh.susceptibility_si
            if _susc is None:
                continue  # intervalo sin susceptibilidad → no ancla la inversión magnética
            if _susc < params.susc_min or _susc > params.susc_max:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Susceptibilidad de sondaje fuera de bounds (intervalo {_i}: {_susc} SI "
                        f"no en [{params.susc_min}, {params.susc_max}] SI)."
                    ),
                )
            # FASE 1.2: el sondaje mide la susceptibilidad VERDADERA; el solver ancla
            # en el espacio APARENTE → convertir antes de anclar.
            _susc_anchor = float(apparent_susceptibility(_susc, _demag_N)) if _use_demag else _susc
            _rows.append([_bh.x_m, _bh.z_m, _bh.y_from_m, _bh.y_to_m, _susc_anchor])
        if _rows:
            boreholes_arr = np.asarray(_rows, dtype=np.float64)

    # FASE 2.3: bounds de susceptibilidad por unidad litológica (membership dura).
    # Si self-demag está activo el solver trabaja en susc APARENTE → convertir el box
    # (apparent_susceptibility es monótona, preserva el orden min/max).
    _litho_bounds_m = _build_lithology_bounds_array(params, "susc")
    if _litho_bounds_m is not None and _use_demag:
        _litho_bounds_m = _litho_bounds_m.copy()
        _litho_bounds_m[:, 4] = [apparent_susceptibility(v, _demag_N) for v in _litho_bounds_m[:, 4]]
        _litho_bounds_m[:, 5] = [apparent_susceptibility(v, _demag_N) for v in _litho_bounds_m[:, 5]]

    # ── FASE 12: Remanencia — construir kernel total J_ind + Q·J_rem si aplica ──
    _rem = getattr(params, "remanence", None)
    _use_remanence = (
        _rem is not None
        and _rem.enabled
        and _rem.inversion_mode in ("total_field", "amplitude")
        and _rem.q_ratio > 0.0
    )
    _override_kernel = None
    _q_sweep_result = None

    if _use_remanence and _rem.inversion_mode == "total_field" and not _is_mvi:
        _update("running", 0.35, "building_kernel_rem", f"Construyendo kernel total J_ind + {_rem.q_ratio:.2f}·J_rem...")
        # El kernel de remanencia se construye sobre la grilla COMPLETA (core+padding):
        # el solver lo usa como override y exige shape (n_obs, n_active). En el path de
        # remanencia se invierte SIN topografía DEM (topography_elevations=None abajo) →
        # n_active = todas las celdas de la malla extendida, así que el kernel debe
        # cubrirlas todas. El padding sigue activo vía padding_mask (BC física). Combinar
        # remanencia Q-ratio con DEM denso queda fuera de alcance (caso raro; usar MVI).
        _override_kernel = forward.build_kernel_with_remanence(
            x_c_full, y_c_full, z_c_full,
            sensor_coords,
            q_ratio=_rem.q_ratio,
            inc_rem_deg=_rem.remanence_inc_deg,
            dec_rem_deg=_rem.remanence_dec_deg,
        )

        if _rem.do_q_sweep:
            from exploration.magnetometry import sweep_q_ratio
            _update("running", 0.38, "q_sweep", "Barriendo Q para estimación óptima...")
            _q_sweep_result = sweep_q_ratio(
                forward=forward,
                inversor=inversor,
                x_c_act=x_c_full,
                y_c_act=y_c_full,
                z_c_act=z_c_full,
                sensor_coords=sensor_coords,
                d_observed=mag,
                inc_rem_deg=_rem.remanence_inc_deg,
                dec_rem_deg=_rem.remanence_dec_deg,
                lambda_mag=(params.lambda_mag if params.lambda_mag > 0 else 1e-4),
                alpha_spatial=params.alpha_spatial,
                susc_min=params.susc_min,
                susc_max=params.susc_max,
            )

    solver_meta = {}
    # ── FASE 20C: campos de dirección MVI (None en modo escalar) ──────────────
    _mvi_inc_full = None
    _mvi_dec_full = None
    # Topografía DEM para el solver: en el path de remanencia (override_kernel
    # construido sobre TODAS las celdas) se invierte sin topografía para que n_active
    # coincida con el kernel; en el path inducido/MVI se usa la superficie DEM densa.
    _topo_for_solve = None if _override_kernel is not None else _topo_mag

    if _is_mvi:
        _update("running", 0.4, "solving_mvi", "Resolviendo MVI (vector de magnetización, modelo 3N) LSQR...")
        _mvi = inversor.solve_mvi_inversion_lsqr(
            d_observed=mag,
            y_c=y_c_full,
            forward_model=forward,
            sensor_coords=sensor_coords,
            x_c=x_c_full,
            z_c=z_c_full,
            lambda_mag=(params.lambda_mag if params.lambda_mag > 0 else 1e-3),
            alpha_spatial=params.alpha_spatial,
            topography_elevations=_topo_mag,
            hx=hx, hy=hy, hz=hz,                       # Tensor mesh (Laplaciano no-uniforme)
            padding_mask=_padding_mask_mag,            # R-02: BC física del padding (3C)
            padding_kappa=float(getattr(params, "padding_kappa", 1e5)),
            detect_outliers=bool(getattr(params, "robust_sigma", True)),
            solver_meta=solver_meta,
        )
        # |M| (susceptibilidad efectiva) ocupa la columna susceptibility_si: reutiliza
        # todo el payload/parquet escalar. La dirección se inyecta aparte (voxels+report).
        susc_full = _mvi["amplitude_full"]
        score_full = _mvi["relative_score_full"]
        sens_full = np.full_like(susc_full, np.nan)   # MVI no expone proxy de sensibilidad
        misfit_percent = _mvi["misfit_percent"]
        _mvi_inc_full = _mvi["inclination_full"]
        _mvi_dec_full = _mvi["declination_full"]
    else:
        _update("running", 0.4, "solving_lsqr", "Resolviendo inversión magnética LSQR + Tikhonov...")
        susc_full, score_full, misfit_percent, sens_full = inversor.solve_magnetic_inversion_lsqr(
            d_observed=mag,
            y_c=y_c_full,
            lambda_mag=(params.lambda_mag if params.lambda_mag > 0 else 1e-4),
            alpha_spatial=params.alpha_spatial,
            topography_elevations=_topo_for_solve,
            sensor_coords=sensor_coords,
            x_c=x_c_full,
            z_c=z_c_full,
            forward_model=forward,
            susc_min=params.susc_min,
            susc_max=_susc_max_solve,                  # FASE 1.2: bound APARENTE si self-demag
            hx=hx, hy=hy, hz=hz,                       # Tensor mesh (Laplaciano no-uniforme)
            padding_mask=_padding_mask_mag,            # R-02: BC física del padding
            padding_kappa=float(getattr(params, "padding_kappa", 1e5)),
            boreholes=boreholes_arr,
            anchor_mode=str(getattr(params, "anchor_mode", "soft")),      # FASE 2.1
            lithology_bounds=_litho_bounds_m,                             # FASE 2.3
            detect_outliers=bool(getattr(params, "robust_sigma", True)),  # FASE 20B Tarea 4
            auto_kappa=bool(getattr(params, "auto_kappa", True)),         # FASE 20B Tarea 5
            regularization_norm=getattr(params, "regularization_norm", "L2"),  # FASE 20B Tarea 6
            solver_meta=solver_meta,
            override_kernel=_override_kernel,
        )

    # ── Reducir las salidas de la malla COMPLETA al CORE (descartar padding) ──
    # El solver devuelve arrays de longitud total_padded; voxels/parquet/best_target
    # operan sobre el core (mismo orden Fortran que ix/iy/iz/x_c). El padding cumplió
    # su rol de BC física y se descarta del modelo reportado (paridad con gravedad).
    susc_full  = susc_full[is_core]
    score_full = score_full[is_core]
    sens_full  = sens_full[is_core]
    if _is_mvi:
        _mvi_inc_full = _mvi_inc_full[is_core]
        _mvi_dec_full = _mvi_dec_full[is_core]

    # ── FASE 1.2: self-demag — la inversión recuperó la susceptibilidad APARENTE
    # κ_eff; se reporta la VERDADERA κ = κ_eff/(1−N·κ_eff). Los NaN (celdas inactivas)
    # se preservan. El misfit/score quedan en el espacio aparente (física correcta del
    # ajuste). El bound aparente garantiza N·κ_eff < 1 (denominador positivo).
    if _use_demag:
        susc_full = true_susceptibility(susc_full, _demag_N)

    _update("running", 0.85, "building_payload", "Construyendo payload de susceptibilidad...")

    # ── Voxels de susceptibilidad (honestos: sin densidad/ley/tonelaje fabricado) ──
    susc_clean = np.nan_to_num(susc_full, nan=0.0)
    is_active = np.isfinite(susc_full)
    smax = float(np.max(susc_clean)) if susc_clean.size else 0.0
    susc_cutoff = max(1e-6, 0.01 * smax)   # 1% del máximo recuperado o piso 1e-6
    order = np.argsort(-susc_clean)
    voxels = []
    for j in order:
        if not is_active[j]:
            continue
        s = float(susc_full[j])
        if s < susc_cutoff:
            break   # orden descendente → el resto queda bajo cutoff
        _vox = {
            "ix": int(ix[j]), "iy": int(iy[j]), "iz": int(iz[j]),
            "x_m": float(x_c[j]), "y_m": float(y_c[j]), "z_m": float(z_c[j]),
            "susceptibility": s,
            "relative_target_score": float(score_full[j]) if np.isfinite(score_full[j]) else None,
            "sensitivity_proxy": float(sens_full[j]) if np.isfinite(sens_full[j]) else None,
            "is_active": True,
        }
        if _is_mvi:
            # MVI: |M| (susceptibilidad efectiva) + dirección de magnetización recuperada.
            _vox["magnetization_amplitude"] = s
            _vox["magnetization_inc_deg"] = (
                float(_mvi_inc_full[j]) if np.isfinite(_mvi_inc_full[j]) else None
            )
            _vox["magnetization_dec_deg"] = (
                float(_mvi_dec_full[j]) if np.isfinite(_mvi_dec_full[j]) else None
            )
        voxels.append(_vox)
        if len(voxels) >= 5000:
            break

    best_target = None
    if voxels:
        _b = voxels[0]
        best_target = {
            "x_m": _b["x_m"], "y_m": _b["y_m"], "z_m": _b["z_m"],
            "susceptibility": _b["susceptibility"],
            "relative_target_score": _b["relative_target_score"],
        }

    _remanence_report = None
    if _use_remanence and _rem is not None:
        _remanence_report = {
            "enabled": True,
            "inversion_mode": _rem.inversion_mode,
            "q_ratio": _rem.q_ratio,
            "remanence_inc_deg": _rem.remanence_inc_deg,
            "remanence_dec_deg": _rem.remanence_dec_deg,
            "q_sweep": _q_sweep_result,
        }

    report = {
        "method": "magnetic_vector_inversion_phase20c" if _is_mvi else "magnetic_dipole_tmi_phase9a",
        "engine": (
            "MagnetometryInversion MVI (vector M=Mx,My,Mz; dirección recuperada, Fase 20C)"
            if _is_mvi
            else (
                f"MagnetometryInversion (J_ind + {_rem.q_ratio:.2f}·J_rem, Fase 12)"
                if _use_remanence and _rem is not None
                else "MagnetometryInversion (magnetización inducida, sin remanencia)"
            )
        ),
        "magnetization_model": "vector" if _is_mvi else "scalar",
        "mvi": (
            {
                "amplitude_is_effective_susceptibility": True,
                "amplitude_max_si": solver_meta.get("amplitude_max"),
                "n_unknowns": solver_meta.get("n_unknowns"),
                "note": (
                    "|M| (susceptibilidad efectiva) publicado en susceptibility_si; "
                    "dirección por vóxel en magnetization_inc_deg/dec_deg. Sin bounds de "
                    "no-negatividad (las componentes tienen signo). Anclaje de sondajes y "
                    "remanencia Q-ratio NO aplican en modo MVI."
                ),
            }
            if _is_mvi
            else None
        ),
        "is_joint_inversion": False,
        "field": {
            "inclination_deg": params.inclination_deg,
            "declination_deg": params.declination_deg,
            "field_intensity_nt": params.field_intensity_nt,
            "field_unit_vector_xyz": solver_meta.get("field_unit_vector"),
            "axis_convention": "x=Norte, z=Este, y=profundidad(+abajo)",
        },
        "remanence": _remanence_report,
        "self_demagnetization": (
            {
                "enabled": True,
                "demag_factor_N": _demag_N,
                "note": (
                    "Susceptibilidad reportada = VERDADERA κ (corregida por self-demag "
                    "κ_eff=κ/(1+Nκ)); el solver invirtió la APARENTE. Aproximación LOCAL "
                    "(celda aislada); el solve acoplado finite-volume queda diferido."
                ),
            }
            if _use_demag
            else {"enabled": False}
        ),
        "susceptibility_bounds_si": [params.susc_min, params.susc_max],
        "solver": {
            "cond_A": solver_meta.get("acond"),
            "chi2_final": solver_meta.get("chi2_final"),
            "misfit_percent": misfit_percent,
            "depth_beta": solver_meta.get("depth_beta"),
            "n_active": solver_meta.get("n_active"),
            "saturation_fraction": solver_meta.get("sat_fraction"),
            "n_sat_lower": solver_meta.get("n_sat_lower"),
            "n_sat_upper": solver_meta.get("n_sat_upper"),
            "n_anchored_voxels": solver_meta.get("n_anchored_voxels"),
        },
        # ── Malla extendida con padding (BC física) + superficie DEM densa ────────
        "mesh": {
            "nx_total": int(nx_total), "ny_total": int(ny_total), "nz_total": int(nz_total),
            "n_core": int(nx * ny * nz),
            "n_padding": int(np.sum(_padding_mask_mag)),
            "padding_active": bool(solver_meta.get("padding_active", False)),
            "n_padding_solved": solver_meta.get("n_padding_solved"),
            "padding_kappa": solver_meta.get("padding_kappa"),
            "topography": _topo_used_mag,
        },
        "observation_count": int(len(mag)),
        "tmi_min_nt": float(np.min(mag)),
        "tmi_max_nt": float(np.max(mag)),
        "anomaly_voxels": len(voxels),
        "disclaimer": (
            "Motor magnético aislado (Fase 9A). La susceptibilidad NO es densidad; "
            "no se emite ley ni tonelaje. Resolución en profundidad limitada (campo potencial)."
        ),
    }

    try:
        write_run_report_snapshot(params, report)
    except Exception as _exc:
        _log.warning("magnetic_report_snapshot_nonfatal", error=str(_exc))

    # ── HITO 1: Persistencia Parquet magnético (schema v3.0) ─────────────────
    # Columnas exportadas: coordenadas, susceptibility_si, run_type="magnetic",
    # schema_version="v3.0". Solo se persiste cuando hay project_id/run_id válidos
    # (is_legacy=False). NUNCA escribe a DEFAULT_BLOCK_MODEL_PATH.
    try:
        _nC_mag = len(x_c)
        _susc_safe = np.nan_to_num(susc_full, nan=0.0)
        _active_mag = np.isfinite(susc_full)

        _mag_cols = {
            "x_c": x_c.astype(float).tolist(),
            "y_c": y_c.astype(float).tolist(),
            "z_c": z_c.astype(float).tolist(),
            "x_m": x_c.astype(float).tolist(),
            "y_m": y_c.astype(float).tolist(),
            "z_m": z_c.astype(float).tolist(),
            "x": x_c.astype(float).tolist(),
            "y": y_c.astype(float).tolist(),
            "z": z_c.astype(float).tolist(),
            "ix": ix.astype(int).tolist(),
            "iy": iy.astype(int).tolist(),
            "iz": iz.astype(int).tolist(),
            "susceptibility_si": _susc_safe.astype(float).tolist(),
            "relative_target_score": score_full.astype(float).tolist(),
            "sensitivity_proxy": sens_full.astype(float).tolist(),
            "is_active": _active_mag.tolist(),
            "run_type": ["magnetic"] * _nC_mag,
            "schema_version": ["v4.0"] * _nC_mag,
        }
        # FASE 20C: persistir la dirección de magnetización recuperada (columnas extra,
        # opcionales — el validador solo exige las required). susceptibility_si ya lleva
        # |M| (susc. efectiva). NaN en celdas de aire (dirección indefinida).
        if _is_mvi:
            _mag_cols["magnetization_amplitude_si"] = _susc_safe.astype(float).tolist()
            _mag_cols["magnetization_inc_deg"] = np.asarray(_mvi_inc_full, dtype=float).tolist()
            _mag_cols["magnetization_dec_deg"] = np.asarray(_mvi_dec_full, dtype=float).tolist()
            _mag_cols["magnetization_model"] = ["vector"] * _nC_mag
        _df_mag = pl.DataFrame(_mag_cols)

        _mag_ref = get_run_block_model_reference(
            project_id=params.project_id,
            run_id=params.run_id,
            filename=RUN_MAGNETIC_BLOCK_MODEL_FILENAME,
        )
        if not _mag_ref.is_legacy:
            _mag_ref.path.parent.mkdir(parents=True, exist_ok=True)
            _df_mag.write_parquet(str(_mag_ref.path))
            _mag_path = str(_mag_ref.path)
            _mag_val = validate_parquet_schema(_mag_ref.path, expected_run_type="magnetic")
            if not _mag_val["valid"]:
                _log.warning(
                    "magnetic_parquet_schema_invalid",
                    run=getattr(params, "run_id", "unknown"),
                    errors=_mag_val["errors"],
                )
            report["magnetic_parquet_path"] = _mag_path
            _log.info("magnetic_parquet_written", path=_mag_path, voxels=_nC_mag)
    except Exception as _mag_pq_exc:
        _log.warning("magnetic_parquet_nonfatal", error=str(_mag_pq_exc))

    # ── HITO 2: Run Manifest magnético (provenance audit trail) ──────────────
    try:
        def _mag_git_hash_short() -> str:
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL, timeout=2,
                ).decode().strip()
            except Exception:
                return "unknown"

        _mag_ref_manifest = get_run_block_model_reference(
            project_id=params.project_id,
            run_id=params.run_id,
            filename=RUN_MAGNETIC_BLOCK_MODEL_FILENAME,
        )
        _mag_run_dir = _mag_ref_manifest.path.parent
        _mag_parquet_path = _mag_ref_manifest.path
        _csv_path_mag = _mag_run_dir / RUN_SOURCE_GRAVITY_FILENAME
        write_run_manifest(_mag_run_dir, {
            "schema_version": "v4.0",
            "run_type": "magnetic",
            "code_version": _mag_git_hash_short(),
            "rng_seed": None,
            "timestamp_utc_start": _mag_start_utc.isoformat(),
            "timestamp_utc_end": datetime.now(timezone.utc).isoformat(),
            "sha256_parquet": sha256_file(_mag_parquet_path) if _mag_parquet_path.exists() else None,
            "sha256_csv": sha256_file(_csv_path_mag) if _csv_path_mag.exists() else None,
            "inversion_params": {
                "nx": params.nx, "ny": params.ny, "nz": params.nz,
                "block_size": params.block_size,
                "lambda_mag": params.lambda_mag,
                "alpha_spatial": params.alpha_spatial,
                "cutoff_radius": params.cutoff_radius,
                "inclination_deg": params.inclination_deg,
                "declination_deg": params.declination_deg,
                "field_intensity_nt": params.field_intensity_nt,
                "susc_min": params.susc_min,
                "susc_max": params.susc_max,
            },
            "solver_stats": {
                "acond": solver_meta.get("acond"),
                "chi2_final": solver_meta.get("chi2_final"),
                "misfit_percent": misfit_percent,
                "depth_beta": solver_meta.get("depth_beta"),
                "n_active": solver_meta.get("n_active"),
                "saturation_fraction": solver_meta.get("sat_fraction"),
                "n_sat_lower": solver_meta.get("n_sat_lower"),
                "n_sat_upper": solver_meta.get("n_sat_upper"),
                "n_anchored_voxels": solver_meta.get("n_anchored_voxels"),
                "anomaly_voxels": len(voxels),
            },
        })
    except Exception as _mag_mfst_exc:
        _log.warning("magnetic_run_manifest_nonfatal", error=str(_mag_mfst_exc))
    # ── Fin HITO 2 ────────────────────────────────────────────────────────────

    _update(
        "done", 1.0, "completed", "Inversión magnética completada (Fase 9A).",
        metrics={"misfit_error_percent": misfit_percent, "cond_A": solver_meta.get("acond"),
                 "anomaly_voxels": len(voxels)},
    )

    return {
        # projectId/runId al nivel superior: el frontend (parseCsvInversionProjectRun)
        # los necesita para cargar el block model. La rama gravimétrica los expone en
        # el report; la magnética debe exponerlos también o la UI no carga el modelo.
        "project_id": params.project_id,
        "run_id": params.run_id,
        "projectId": params.project_id,
        "runId": params.run_id,
        "voxels": voxels,
        "best_target": best_target,
        "report": report,
        "misfit_error_percent": misfit_percent,
    }


def _attach_multimodal_plan(result: dict, params, coverage_pct: float = 1.0) -> dict:
    """FASE 21: adjunta el plan de fusión multimodal a result["report"] (non-fatal).

    Deriva las banderas de datos (g≠0, magnetic_nt≠0, sondaje con densidad) de los
    mismos campos que usa el dispatcher, así el plan SIEMPRE concuerda con el solver
    realmente ejecutado. No cambia el flujo ni la física; sólo añade metadato.
    """
    try:
        from services.multimodal_fusion_service import plan_multimodal

        g_arr = np.asarray([o.g for o in params.observations], dtype=float)
        has_g = g_arr.size > 0 and not np.allclose(g_arr, 0.0)
        mag = getattr(params, "magnetic_nt", None)
        has_m = (
            mag is not None
            and len(mag) > 0
            and not np.allclose(np.asarray(mag, dtype=float), 0.0)
        )
        _bh = getattr(params, "boreholes", None) or []
        has_b = any(getattr(b, "density_t_m3", None) is not None for b in _bh)

        dq = None
        meta = getattr(params, "auto_params_metadata", None) or {}
        if isinstance(meta, dict):
            dq = meta.get("data_quality_score", meta.get("data_quality"))
            if isinstance(dq, dict):
                dq = dq.get("score")

        plan = plan_multimodal(
            has_gravity=has_g,
            has_magnetic=has_m,
            has_borehole=has_b,
            n_sensors=len(params.observations),
            data_quality=(float(dq) if dq is not None else None),
            coverage_pct=coverage_pct,
        )
        rep = result.get("report") if isinstance(result, dict) else None
        if isinstance(rep, dict):
            rep["multimodal_plan"] = plan.to_dict()
    except Exception as exc:  # non-fatal: la inversión ya es válida
        _log.warning("multimodal_plan_nonfatal", error=str(exc))
    return result


def run_geophysics_inversion(params: GeophysicsInvertInput):
    project_id = params.project_id
    run_id = params.run_id

    # ── FASE 9A / 9C-2: ruteo a motor magnético o a inversión conjunta ────────
    # Si el input trae magnetic_nt:
    #   • magnética CON señal gravimétrica real (g≠0)  → Inversión Conjunta (9C-2)
    #   • magnética SIN señal gravimétrica (g=0 placeholder) → motor magnético aislado (9A)
    # El cuerpo gravimétrico de abajo NO se ejecuta y queda intacto bit a bit para
    # inputs sin magnetic_nt (modo gravedad por defecto).
    if getattr(params, "magnetic_nt", None):
        mag = np.asarray(params.magnetic_nt, dtype=float)
        g_arr = np.asarray([o.g for o in params.observations], dtype=float)
        mag_has_signal = mag.size > 0 and not np.allclose(mag, 0.0)
        grav_has_signal = g_arr.size > 0 and not np.allclose(g_arr, 0.0)
        if mag_has_signal and grav_has_signal:
            from services.joint_inversion import run_joint_inversion
            return _attach_multimodal_plan(run_joint_inversion(params), params)
        return _attach_multimodal_plan(run_magnetic_inversion(params), params)

    def _update(status, progress, stage, message, metrics=None, error=None):
        if project_id and run_id:
            try:
                update_run_status(project_id, run_id, status, progress, stage, message, metrics, error)
            except Exception:
                pass

    _log.info("inversion_start", project_id=project_id, run_id=run_id)
    _inversion_start_utc = datetime.now(timezone.utc)

    ensure_runtime_dirs()

    _update("running", 0.0, "loading_data", "Validando parámetros de entrada...")
    validate_geophysics_input(params)

    # ── FASE 8 (Q4): Validación estricta de bounds de sondajes + array de anclaje ──
    # La matemática debe ser consistente desde la entrada: si un intervalo de sondaje
    # declara una densidad fuera de [density_min, density_max] de la inversión, no hay
    # forma coherente de anclarlo dentro del bound → se rechaza con 422 (no se intenta
    # "resolver mágicamente" el conflicto). El array (n,5) [x_m, z_m, y_from_m, y_to_m,
    # density_t_m3] es lo que consume el solver para el mapeo de vóxeles.
    boreholes_arr = None
    _bh_list = getattr(params, "boreholes", None) or []
    if _bh_list:
        _bh_rows = []
        for _i, _bh in enumerate(_bh_list):
            # FASE 9B: lectura segura. Un intervalo netamente magnético (density_t_m3
            # None) no aporta restricción de densidad → se salta sin error.
            if _bh.density_t_m3 is None:
                continue
            if _bh.density_t_m3 < params.density_min or _bh.density_t_m3 > params.density_max:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Borehole density outside inversion bounds "
                        f"(interval {_i}: {_bh.density_t_m3} t/m3 not in "
                        f"[{params.density_min}, {params.density_max}] t/m3)."
                    ),
                )
            _bh_rows.append([_bh.x_m, _bh.z_m, _bh.y_from_m, _bh.y_to_m, _bh.density_t_m3])
        if _bh_rows:
            boreholes_arr = np.asarray(_bh_rows, dtype=np.float64)

    # FASE 2.3: bounds de densidad por unidad litológica (membership dura, KKT).
    _litho_bounds_g = _build_lithology_bounds_array(params, "density")

    _update("running", 0.05, "loading_data", "Input validado. Construyendo grilla y sensores...")

    nx = params.nx
    ny = params.ny
    nz = params.nz
    dx = params.block_size

    total_voxels = nx * ny * nz  # Vóxeles Core — reportados al frontend

    # ── F0.9: Tensor Mesh con Padding Geométrico ──────────────────────────────
    mesh       = build_tensor_mesh_with_padding(params)
    x_c_full   = mesh["x_c"]
    y_c_full   = mesh["y_c"]
    z_c_full   = mesh["z_c"]
    is_core    = mesh["is_core"]
    hx, hy, hz = mesh["hx"], mesh["hy"], mesh["hz"]
    nx_total   = mesh["nx_total"]
    ny_total   = mesh["ny_total"]
    nz_total   = mesh["nz_total"]

    # Arrays Core: para diagnósticos, focusing y block model (sin padding)
    ix  = mesh["ix_core"]      # 0..nx-1, Fortran order
    iy  = mesh["iy_core"]      # 0..ny-1
    iz  = mesh["iz_core"]      # 0..nz-1
    x_c = mesh["x_c_core"]
    y_c = mesh["y_c_core"]
    z_c = mesh["z_c_core"]

    sensor_coords, g_observed = build_sensor_arrays(params)

    qaqc_report = build_observation_qaqc_report(params, sensor_coords, g_observed)

    forward = GravimetryForward(
        dx,
        dx,
        dx,
        cutoff_radius=params.cutoff_radius,
    )

    # ── Sprint 3 cierre: TreeMesh — auto-default para surveys grandes/regionales ──
    # Auto-select: se activa cuando el survey supera 50 km de extensión O la grilla
    # regular excede 50k celdas (RAM/compute costoso). El flag use_treemesh del schema
    # puede forzar True (siempre TreeMesh) o False (siempre grilla regular).
    from services.octree_mesh_builder import should_auto_use_treemesh, build_treemesh_from_survey
    _x_extent_m = float(nx * dx)
    _z_extent_m = float(nz * dx)
    _treemesh_flag = getattr(params, "use_treemesh", False)
    _use_treemesh = _treemesh_flag or should_auto_use_treemesh(total_voxels, _x_extent_m, _z_extent_m)

    # kernel_sparse (diagnóstico, grilla Core) se construye SÓLO en el path regular.
    # Antes se armaba aquí incondicionalmente y el path TreeMesh lo DESCARTABA: con
    # un cutoff denso eso era un kernel de ~1.7 GB tirado a la basura (DOBLE BUILD:
    # regular 160k + TreeMesh 220k → OOM en DO-27). El path TreeMesh construye su
    # propio kernel desde la malla Octree; no necesita este diagnóstico Core.
    kernel_sparse = None
    if not _use_treemesh:
        # kernel_sparse: SOLO sobre grilla Core — para build_fit_diagnostics.
        # El solver LSQR opera sobre la grilla completa (Core + Padding) vía HPC F0.2.
        kernel_sparse = forward.build_sparse_kernel(
            x_c,
            y_c,
            z_c,
            sensor_coords,
        )
        _update("running", 0.25, "building_kernel",
                "Kernel diagnóstico construido. Tensor Mesh F0.9 + Noise Floor activos...")

        if kernel_sparse.shape[0] != len(g_observed):
            raise RuntimeError(
                "La matriz forward no coincide con la cantidad de observaciones gravimétricas."
            )

    if _use_treemesh:
        from exploration.gravimetry import solve_inversion_treemesh

        _update("running", 0.35, "treemesh_build", "Construyendo malla Octree adaptativa...")

        _mean_spacing_m = float(
            np.sqrt((_x_extent_m * _z_extent_m) / max(len(g_observed), 1))
        )
        _max_refine_override = getattr(params, "treemesh_max_refine", None)
        if isinstance(_max_refine_override, int) and _max_refine_override == 2 \
                and not getattr(params, "use_treemesh", False):
            # Default schema value (2) no es override explícito — dejar al builder calibrar
            _max_refine_override = None

        mesh, _oct_p = build_treemesh_from_survey(
            block_size_m=dx,
            nx=nx, ny=ny, nz=nz,
            x_extent_m=_x_extent_m,
            z_extent_m=_z_extent_m,
            mean_spacing_m=_mean_spacing_m,
            sensor_coords=sensor_coords,
            max_refine_override=_max_refine_override,
        )

        _update("running", 0.40, "treemesh_solve", f"Resolviendo inversión sobre TreeMesh ({mesh.n_cells:,} celdas)...")

        _solver_meta = {}
        est_density, probability, misfit_percent = solve_inversion_treemesh(
            mesh=mesh,
            g_observed=g_observed,
            sensor_coords=sensor_coords,
            forward_model=forward,
            lambda_mag=params.lambda_mag if params.lambda_mag > 0 else PRECONDITIONED_OPERATING_LAMBDA,
            alpha_spatial=params.alpha_spatial,
            depth_beta=getattr(params, "depth_beta", 2.0),
            density_min=params.density_min,
            density_max=params.density_max,
            solver_meta=_solver_meta,
        )

        # Construir vóxeles mínimos from TreeMesh
        cell_centers = mesh.get_cell_centers()
        voxels = []
        for i in range(mesh.n_cells):
            voxels.append({
                "ix": i % 32 if mesh.n_cells > 0 else 0,  # Dummy index
                "iy": (i // 32) % 32,
                "iz": (i // 1024) % 32,
                "x_m": float(cell_centers[i, 0]),
                "y_m": float(cell_centers[i, 1]),
                "z_m": float(cell_centers[i, 2]),
                "density": float(est_density[i]) if np.isfinite(est_density[i]) else None,
                "probability": float(probability[i]) if np.isfinite(probability[i]) else None,
                "is_active": bool(np.isfinite(est_density[i])),
            })

        _mesh_info = {
            'n_cells': mesh.n_cells,
            'n_levels': mesh.max_refinement_depth + 1,
            'min_cell_size_m': float(np.min(mesh.get_cell_sizes())),
            'max_cell_size_m': float(np.max(mesh.get_cell_sizes())),
            'base_cell_size_m': float(mesh.base_cell_size),
            'sensor_guided_refine': True,
            'auto_selected': not _treemesh_flag,
            'octree_params': _oct_p.as_dict(),
        }

        _update("done", 1.0, "completed", f"TreeMesh inversión completada ({mesh.n_cells} celdas).",
                metrics={"misfit_percent": misfit_percent, "mesh_cells": mesh.n_cells, "mesh_levels": mesh.max_refinement_depth + 1})

        return {
            "voxels": voxels,
            "best_target": None,
            "report": {"mesh_info": _mesh_info, "misfit_error_percent": misfit_percent},
            "misfit_error_percent": misfit_percent,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Regular Grid path (original, unmodified)
    # ─────────────────────────────────────────────────────────────────────────

    # FASE 16: base_density configurable desde params (default 2.6 = granito host rock)
    _base_density = float(getattr(params, "base_density", 2.6))

    # inversor_padded: opera sobre grilla completa (Core + Padding) para LSQR + Laplaciano
    inversor_padded = GravimetryInversion(nx_total, ny_total, nz_total, dx, base_density=_base_density)
    # inversor_core: para focusing y regularizador de diagnóstico (grilla Core solamente)
    inversor_core   = GravimetryInversion(nx, ny, nz, dx, base_density=_base_density)

    # ── R-02: Máscara de padding — κ configurable (FASE 16) ──────────────────
    # Default 1e5 post-auditoría R-A1: suprime smallness del padding 100000× más
    # que el core para evitar mass escape. Ahora configurable desde el schema.
    _padding_mask_r02 = ~is_core
    _kappa        = float(getattr(params, "padding_kappa", 1e5))
    _anchor_kappa = float(getattr(params, "anchor_kappa", 1e4))
    _anchor_mode  = str(getattr(params, "anchor_mode", "soft"))   # FASE 2.1
    _auto_kappa   = bool(getattr(params, "auto_kappa", True))

    # ── FASE 7.2 (God-Tier): prior geológico implícito (φ HRBF → m_ref) ───────
    # Si implicit_geology está activado, φ se construye desde los contactos
    # litológicos de los sondajes y se inyecta como modelo de referencia por celda
    # (contraste). _geo_m_ref=None → m_ref histórico (sin sesgo geológico).
    _geo_m_ref, _geo_meta = _build_implicit_geology_reference(
        params, x_c_full, y_c_full, z_c_full, _base_density
    )
    if _geo_meta is not None:
        _log.info(
            "implicit_geology_reference",
            n_target_cells=_geo_meta["n_target_cells"],
            n_total_cells=_geo_meta["n_total_cells"],
            n_contact_points=_geo_meta["n_contact_points"],
            n_orientations=_geo_meta["n_orientations"],
        )

    # ── HITO 5 (B-05): Topografía activa desde sensor_elevations_masl ──────────
    # Se calcula ANTES del lambda scan para que todos los solvers (lambda, UQ, DOI)
    # usen la misma máscara de aire topográfica. Datum = sensor más alto (y=0).
    _topography_elevations_padded = None
    _topography_used = "flat"
    _sensor_elevs = getattr(params, "sensor_elevations_masl", None)
    if _sensor_elevs is not None and len(_sensor_elevs) == len(params.observations):
        try:
            from core.geo_utils import interpolate_surface_depths as _interp_surface
            _elev_arr = np.asarray(_sensor_elevs, dtype=np.float64)
            _max_elev = float(np.max(_elev_arr))
            _surface_depths = _max_elev - _elev_arr  # profundidad desde el punto más alto

            # ── FASE 24B Tarea 3: superficie de malla SUAVE (anti-staircase) ──────
            # nearest-neighbor produce una superficie escalonada en bloques entre
            # sensores → aristas ortogonales falsas → máscara de aire incorrecta →
            # error de profundidad. interpolate_surface_depths usa interpolación LINEAL
            # (superficie suave) con fallback nearest fuera del convex hull (padding).
            # NOTA: el upgrade a DEM denso bilineal (30 m OpenTopography) muestreado en
            # el (x,z) geográfico real de cada columna requiere la georef local→UTM de
            # Fase 19 (no cableada en este path); cuando exista, sustituye a esta
            # interpolación de sensores sin perder el comportamiento de fallback.
            _topography_elevations_padded, _surface_mode = _interp_surface(
                sensor_coords[:, [0, 2]],
                _surface_depths,
                np.column_stack([x_c_full, z_c_full]),
            )
            _topography_used = f"from_sensor_elevations_masl[{_surface_mode}]"
            _log.info(
                "topography_activated",
                max_elev_masl=round(float(_max_elev), 1),
                surface_mode=_surface_mode,
                surface_depth_range_m=[round(float(_surface_depths.min()), 1),
                                       round(float(_surface_depths.max()), 1)],
            )
        except Exception as _topo_exc:
            _log.warning("topography_activation_nonfatal", error=str(_topo_exc))
            _topography_elevations_padded = None
            _topography_used = "flat_fallback"

    # ── FASE 4 (causa J): Operating point fijo de lambda (reemplaza chi²-target) ─
    # Se activa cuando auto_lambda=True o lambda_mag==0 (sentinel de auto-selección).
    # Antes se usaba select_lambda_chi2_target(chi2_target=1, candidatos ≤1e-3), que
    # sub-regularizaba (problema sub-determinado; ver PRECONDITIONED_OPERATING_LAMBDA).
    # Se reemplaza por el operating point fijo en espacio preconditioned. El método
    # chi²-target permanece disponible en gravimetry.py para diagnóstico.
    _lambda_mag = params.lambda_mag
    _lambda_scan_meta = {}
    _use_morozov = False
    if getattr(params, "auto_lambda", False) or params.lambda_mag == 0.0:
        # Tier 1 A2: cuando el sigma es EXPLÍCITO (noise_floor declarado o
        # gravímetro conocido), chi²_red es físicamente interpretable y el
        # principio de discrepancia de Morozov (chi²→1) es el selector correcto.
        # Con sigma sentinel adaptivo, chi² no es confiable → operating point.
        _sigma_is_explicit = (
            getattr(params, "noise_floor_mgal", None) is not None
            or (getattr(params, "gravimeter_type", "unknown") or "unknown") != "unknown"
        )
        if _sigma_is_explicit:
            _use_morozov = True
            _update("running", 0.30, "lambda_scan",
                    "Selección de lambda por discrepancia de Morozov (chi²→1)...")
            _log.info("auto_lambda_morozov_scan_started")
        else:
            _lambda_mag = PRECONDITIONED_OPERATING_LAMBDA
            _lambda_scan_meta = {
                "selection_method": "fixed_preconditioned_operating_point",
                "lambda_selected":  _lambda_mag,
                "rationale": (
                    "underdetermined inversion: data-driven selectors (L-curve, "
                    "chi2-target, GCV) under-regularize. Preconditioned optimum O(1-10), "
                    "validated vs synthetic ground-truth (lambda~3 -> pearson~0.95)."
                ),
            }
            _update("running", 0.30, "lambda_set",
                    f"Lambda operativo fijo (preconditioned) = {_lambda_mag:.2f}")
            _log.info(
                "auto_lambda_fixed_operating_point",
                lambda_selected=_lambda_mag,
                method="fixed_preconditioned_operating_point",
            )

    # P1-2: Diagnóstico de lambda_spatial efectivo (auditoría R09).
    # lambda_spatial = alpha_spatial * (n_sensors / n_active). Para grillas grandes
    # con pocos sensores el ratio puede ser <<1, reduciendo la regularización espacial.
    _n_padded_est = nx_total * ny_total * nz_total
    _lambda_spatial_eff = float(params.alpha_spatial) * (len(g_observed) / max(_n_padded_est, 1))
    if _lambda_spatial_eff < 1e-4:
        _log.warning(
            "lambda_spatial_potentially_low",
            lambda_spatial_approx=round(_lambda_spatial_eff, 8),
            alpha_spatial=params.alpha_spatial,
            n_sensors=len(g_observed),
            n_padded_est=_n_padded_est,
            recommendation="Si el resultado es rugoso, aumentar alpha_spatial.",
        )

    # ── Fase 2: extraer noise params del input (v2 los aporta; v1 usa defaults) ──
    # noise_floor_mgal (mGal) → m/s² (unidades del pipeline de import). 1 mGal = 1e-5 m/s².
    # Default 0.02 activa _sigma_adaptive interna (sentinel del solver, comportamiento v1).
    _noise_floor_mgal = getattr(params, "noise_floor_mgal", None)
    _noise_pct = getattr(params, "noise_pct_v2", None)
    _gravimeter_type = getattr(params, "gravimeter_type", "unknown") or "unknown"
    if _noise_floor_mgal is not None:
        # Sigma explícito (v2 o σ por estación desde el CSV): piso parametric.
        # noise_pct None → 0 (piso puro).
        _noise_floor_solver = float(_noise_floor_mgal) * 1e-5   # mGal → m/s²
        _noise_pct_solver = float(_noise_pct) if _noise_pct is not None else 0.0
    elif _gravimeter_type != "unknown":
        # Flujo de datos de campo: piso instrumental desde la tabla por gravímetro.
        # sigma_i = max(noise_floor, noise_pct·|d_i|); noise_pct=0 → piso puro,
        # chi²_red interpretable contra el ruido real del instrumento.
        from core.config import GRAVIMETER_NOISE_FLOOR
        _noise_floor_solver = float(
            GRAVIMETER_NOISE_FLOOR.get(_gravimeter_type, GRAVIMETER_NOISE_FLOOR["unknown"])
        ) * 1e-5  # mGal → m/s²
        _noise_pct_solver = 0.0
        _log.info(
            "sigma_gravimeter_floor",
            gravimeter_type=_gravimeter_type,
            noise_floor_mgal=_noise_floor_solver * 1e5,
        )
    else:
        # v1 path: sentinel 0.02/0.02 activa _sigma_adaptive invariante de escala
        _noise_floor_solver = 0.02
        _noise_pct_solver = 0.02

    # ── Solver sobre grilla completa (Core + Padding) ─────────────────────────
    _solver_meta = {}   # recibe acond, chi2_final, saturación del solver

    def _solve_full_grid(_lam: float, _meta_out: dict):
        """Un solve completo del sistema con lambda dado (kernel cacheado por geometría)."""
        return _run_lsqr_with_heartbeat(
            inversor=inversor_padded,
            g_observed=g_observed,
            kernel_sparse=None,             # HPC F0.2 exclusivo; no se usa
            y_c=y_c_full,
            lambda_mag=_lam,
            alpha_spatial=params.alpha_spatial,
            project_id=project_id,
            run_id=run_id,
            forward_model=forward,          # F0.2: KDTree directo sobre active_cells
            sensor_coords=sensor_coords,
            m_ref=_geo_m_ref,               # FASE 7.2: prior geológico implícito (None = sin sesgo)
            x_c=x_c_full,
            z_c=z_c_full,
            topography_elevations=_topography_elevations_padded,  # HITO 5: activo si MASL provisto
            hx=hx, hy=hy, hz=hz,           # F0.9: Laplaciano no-uniforme
            density_min=params.density_min, # P2: bound petrofísico configurable desde API
            density_max=params.density_max,
            padding_mask=_padding_mask_r02, # R-02: κ configurable (FASE 16)
            padding_kappa=_kappa,
            boreholes=boreholes_arr,        # FASE 8: anclaje por sondajes (None si no hay)
            anchor_kappa=_anchor_kappa,     # FASE 16: configurable desde schema
            anchor_mode=_anchor_mode,       # FASE 2.1: soft (histórico) / hard (exacto)
            lithology_bounds=_litho_bounds_g,  # FASE 2.3: bounds por unidad litológica
            auto_kappa=_auto_kappa,         # FASE 16: ajuste automático si cond>1e12
            noise_floor=_noise_floor_solver, # Fase 2: sigma calibrado por gravímetro
            noise_pct=_noise_pct_solver,
            solver_meta=_meta_out,          # OUT: acond, chi2_final, sat_*
            detect_outliers=bool(getattr(params, "robust_sigma", True)),  # FASE 18
            regularization_norm=getattr(params, "regularization_norm", "L2"),  # FASE 24B
            compact_max_irls=int(getattr(params, "compact_max_irls", 8)),     # FASE 24B knobs
            compact_eps=float(getattr(params, "compact_eps", 0.05)),
            cut_cell_topography=bool(getattr(params, "cut_cell_topography", False)),  # FASE 24B T4
        )

    if _use_morozov:
        # ── Tier 1 A2: discrepancia de Morozov sobre el SOLVER REAL ────────────
        # NOTA: select_lambda_chi2_target (gravimetry.py) usa la maquinaria
        # pre-W_z (column scaling viejo + sigma adaptivo hardcodeado) — su
        # chi²(λ) no corresponde al operador actual. Aquí el scan llama al
        # path de producción (kernel cacheado → costo ≈ 1 solve por candidato)
        # y ADOPTA directamente la mejor solución: ≤ 6 solves en total.
        _morozov_candidates = [0.01, 0.05623, 0.31623, 1.77828, 10.0]  # logspace(-2,1,5)
        _morozov_trials: list = []
        _morozov_best: "dict | None" = None

        def _morozov_try(_lam: float) -> float:
            nonlocal _morozov_best
            _meta_i: dict = {}
            _out_i = _solve_full_grid(_lam, _meta_i)
            _chi2_i = _meta_i.get("chi2_final")
            _chi2_i = float(_chi2_i) if _chi2_i is not None else float("nan")
            _score_i = (
                abs(np.log10(_chi2_i)) if np.isfinite(_chi2_i) and _chi2_i > 0
                else float("inf")
            )
            _morozov_trials.append({"lambda": _lam, "chi2_red": _chi2_i})
            if _morozov_best is None or _score_i < _morozov_best["score"]:
                _morozov_best = {
                    "score": _score_i, "lambda": _lam,
                    "out": _out_i, "meta": _meta_i, "chi2": _chi2_i,
                }
            return _chi2_i

        _chi2_scan = [_morozov_try(_lam_c) for _lam_c in _morozov_candidates]

        # Bisección geométrica del bracket de chi²=1 (chi² crece con λ): 1 solve extra.
        for _i_b in range(len(_morozov_candidates) - 1):
            _c1, _c2 = _chi2_scan[_i_b], _chi2_scan[_i_b + 1]
            if np.isfinite(_c1) and np.isfinite(_c2) and (_c1 - 1.0) * (_c2 - 1.0) < 0:
                _morozov_try(float(np.sqrt(
                    _morozov_candidates[_i_b] * _morozov_candidates[_i_b + 1]
                )))
                break

        _morozov_warnings: list = []
        _finite_scan = [c for c in _chi2_scan if np.isfinite(c)]
        if _finite_scan and all(c > 1.0 for c in _finite_scan):
            _morozov_warnings.append(
                "morozov_underfit_floor: ni λ=0.01 alcanza chi²≤1 — los datos no son "
                "ajustables al nivel del sigma declarado (revisar correcciones/sigma)."
            )
        if _finite_scan and all(c < 1.0 for c in _finite_scan):
            _morozov_warnings.append(
                "morozov_overfit_ceiling: incluso λ=10 da chi²<1 — sigma declarado "
                "posiblemente mayor que el ruido real."
            )

        _lambda_mag = float(_morozov_best["lambda"])
        _solver_meta = _morozov_best["meta"]
        est_density_full, probability_full, misfit_percent, sensitivity_full = _morozov_best["out"]
        _lambda_scan_meta = {
            "selection_method": "morozov_chi2_discrepancy",
            "lambda_selected": _lambda_mag,
            "chi2_achieved": _morozov_best["chi2"],
            "n_solves": len(_morozov_trials),
            "trials": _morozov_trials,
            "warnings": _morozov_warnings,
            "rationale": (
                "Sigma explícito (gravímetro/uncertainty) → chi²_red interpretable; "
                "se elige λ con |log10(chi²)| mínimo (discrepancia de Morozov), "
                "scan sobre el solver de producción (bounds GPCG incluidos)."
            ),
        }
        _update("running", 0.55, "lambda_scan",
                f"Morozov: λ={_lambda_mag:.4g} (chi²_red={_morozov_best['chi2']:.3g}, "
                f"{len(_morozov_trials)} solves)")
        _log.info(
            "auto_lambda_morozov_selected",
            lambda_selected=_lambda_mag,
            chi2_red=_morozov_best["chi2"],
            n_solves=len(_morozov_trials),
        )
    else:
        est_density_full, probability_full, misfit_percent, sensitivity_full = _solve_full_grid(
            _lambda_mag, _solver_meta
        )

    if float(misfit_percent) <= 0.01:
        _log.warning(
            "misfit_perfecto_detectado",
            misfit_percent=misfit_percent,
            note="Posible datos sintéticos o lambda sub-óptima. Las observaciones NO son modificadas.",
        )

    # ── FASE 11: Inversión Guiada Petrológica (PGI — Astic & Oldenburg 2019) ─
    # Bucle alternado: m_PGI = MAP_GMM(m^k) → resolver con bloque PGI extra →
    # verificar convergencia. Se inyecta vía extra_reg_blocks con
    # prune_observable_domain=False (conformable con n_active total sin podar).
    _pgi_p = getattr(params, "pgi_params", None)
    if _pgi_p is not None:
        from exploration.pgi_engine import PGIEngine

        # Inicializar motor PGI
        if _pgi_p.fit_from_model:
            _init_finite = est_density_full[np.isfinite(est_density_full)]
            _init_contrast = _init_finite - inversor_padded.base_density
            _pgi_engine = PGIEngine.fit_from_model(
                m_contrast=_init_contrast,
                n_components=_pgi_p.n_components_auto,
                alpha_pgi=_pgi_p.alpha_pgi,
                base_density=inversor_padded.base_density,
            )
        else:
            _pgi_engine = PGIEngine(
                means=[c.mean_density_t_m3 for c in _pgi_p.components],
                stds=[c.std_density_t_m3 for c in _pgi_p.components],
                weights=[c.weight for c in _pgi_p.components],
                alpha_pgi=_pgi_p.alpha_pgi,
                base_density=inversor_padded.base_density,
            )

        print(
            f"[FASE 11 PGI] Motor iniciado — K={_pgi_engine.K}, "
            f"α={_pgi_engine.alpha_pgi}, max_iter={_pgi_p.max_iter}"
        )
        _log.info("pgi_start", k=_pgi_engine.K, alpha=_pgi_engine.alpha_pgi,
                  max_iter=_pgi_p.max_iter, fit_from_model=_pgi_p.fit_from_model)

        # n_active para prune_observable_domain=False: todas las celdas sub-topográficas
        _pgi_topo = (
            np.zeros(len(y_c_full), dtype=np.float64)
            if _topography_elevations_padded is None
            else np.asarray(_topography_elevations_padded, dtype=np.float64)
        )
        _pgi_voxel_top = y_c_full - (inversor_padded.dy / 2.0)
        _pgi_active_mask = _pgi_voxel_top >= _pgi_topo   # bool, longitud total padded
        n_active_pgi = int(_pgi_active_mask.sum())

        # Estado inicial del modelo para el bucle
        _curr_density_full = est_density_full.copy()
        _curr_contrast_active = np.nan_to_num(
            _curr_density_full[_pgi_active_mask] - inversor_padded.base_density, nan=0.0
        )
        m_pgi_prev = _pgi_engine.compute_m_pgi(_curr_contrast_active)

        _pgi_conv = 1.0  # convergencia entre iteraciones
        _pgi_iters_done = 0

        for _pgi_iter in range(_pgi_p.max_iter):
            _pgi_iters_done = _pgi_iter + 1
            _update(
                "running",
                0.65 + 0.20 * (_pgi_iter / max(_pgi_p.max_iter, 1)),
                "pgi_iteration",
                f"PGI iteración {_pgi_iters_done}/{_pgi_p.max_iter} (conv={_pgi_conv:.4e})...",
            )

            # Construir bloque PGI (A_pgi, b_pgi) con modelo del paso anterior
            _curr_contrast_active = np.nan_to_num(
                _curr_density_full[_pgi_active_mask] - inversor_padded.base_density, nan=0.0
            )
            A_pgi, b_pgi = _pgi_engine.build_pgi_block(_curr_contrast_active, n_active_pgi)

            # Resolver con término PGI inyectado
            _pgi_meta = {}
            _density_pgi_full, _prob_pgi, _misfit_pgi, _sens_pgi = (
                inversor_padded.solve_inversion_lsqr(
                    g_observed, None, y_c=y_c_full,
                    lambda_mag=_lambda_mag,
                    alpha_spatial=params.alpha_spatial,
                    topography_elevations=_topography_elevations_padded,
                    forward_model=forward,
                    sensor_coords=sensor_coords,
                    m_ref=_geo_m_ref,           # FASE 7.2: mismo prior geológico que pass-1
                    x_c=x_c_full,
                    z_c=z_c_full,
                    hx=hx, hy=hy, hz=hz,
                    density_min=params.density_min,
                    density_max=params.density_max,
                    padding_mask=_padding_mask_r02,
                    padding_kappa=_kappa,
                    boreholes=boreholes_arr,
                    anchor_kappa=_anchor_kappa,
                    anchor_mode=_anchor_mode,   # FASE 2.1
                    lithology_bounds=_litho_bounds_g,   # FASE 2.3
                    auto_kappa=_auto_kappa,
                    noise_floor=_noise_floor_solver,
                    noise_pct=_noise_pct_solver,
                    extra_reg_blocks=[A_pgi],
                    extra_reg_rhs=[b_pgi],
                    prune_observable_domain=False,
                    solver_meta=_pgi_meta,
                    regularization_norm=getattr(params, "regularization_norm", "L2"),  # FASE 24B
                    compact_max_irls=int(getattr(params, "compact_max_irls", 8)),     # FASE 24B knobs
                    compact_eps=float(getattr(params, "compact_eps", 0.05)),
                )
            )
            _density_pgi_full = np.asarray(_density_pgi_full, dtype=np.float64)

            # Actualizar m_pgi y verificar convergencia
            _new_contrast_active = np.nan_to_num(
                _density_pgi_full[_pgi_active_mask] - inversor_padded.base_density, nan=0.0
            )

            # ── FASE 2.2: GMM DINÁMICO (re-estimar la mixtura del modelo actual) ──
            # Con dynamic_gmm=True, la mixtura se re-ajusta al modelo invertido en
            # cada iteración (EM MAP regularizado al prior NIW) antes de recomputar
            # m_pgi → las clases petrológicas se adaptan al dato. Default (False) =
            # GMM estático histórico (Fase 11), means/stds/weights sin cambios.
            if getattr(_pgi_p, "dynamic_gmm", False):
                _refit_info = _pgi_engine.refit(
                    _new_contrast_active,
                    prior_kappa=float(getattr(_pgi_p, "prior_kappa", 50.0)),
                    prior_nu=float(getattr(_pgi_p, "prior_nu", 50.0)),
                    weight_concentration=float(getattr(_pgi_p, "weight_concentration", 1.0)),
                )
                _log.info("pgi_refit", iter=_pgi_iters_done,
                          mean_shift_rel=float(_refit_info["mean_shift_rel"]),
                          means=[float(x) for x in _pgi_engine.means])

            m_pgi_new = _pgi_engine.compute_m_pgi(_new_contrast_active)
            _pgi_conv = _pgi_engine.convergence_norm(m_pgi_prev, m_pgi_new)

            print(
                f"[FASE 11 PGI] iter={_pgi_iters_done}, "
                f"misfit={_misfit_pgi:.2f}%, conv={_pgi_conv:.4e}"
            )
            _log.info("pgi_iter", iter=_pgi_iters_done, misfit=float(_misfit_pgi),
                      conv=float(_pgi_conv))

            _curr_density_full = _density_pgi_full
            m_pgi_prev = m_pgi_new

            if _pgi_conv < _pgi_p.convergence_tol:
                print(
                    f"[FASE 11 PGI] Convergencia en iter={_pgi_iters_done} "
                    f"(conv={_pgi_conv:.2e} < tol={_pgi_p.convergence_tol})"
                )
                break

        # Modelo PGI final reemplaza el resultado principal
        est_density_full = _curr_density_full
        probability_full = _prob_pgi
        misfit_percent   = _misfit_pgi
        sensitivity_full = _sens_pgi
        _solver_meta.update({
            "pgi_iters": _pgi_iters_done,
            "pgi_conv":  float(_pgi_conv),
            "pgi_k":     _pgi_engine.K,
            "pgi_alpha": _pgi_engine.alpha_pgi,
            "pgi_dynamic_gmm": bool(getattr(_pgi_p, "dynamic_gmm", False)),
            "pgi_gmm_means": [float(x) for x in _pgi_engine.means],
            "pgi_gmm_stds":  [float(x) for x in _pgi_engine.stds],
        })

        _log.info("pgi_complete", iters=_pgi_iters_done, final_misfit=float(_misfit_pgi),
                  final_conv=float(_pgi_conv))
        print(f"[FASE 11 PGI] Completo. Iters={_pgi_iters_done}, misfit={_misfit_pgi:.2f}%")

    # ── FASE 20: Detección de conflictos sondaje vs modelo recuperado ────────
    # Compara la densidad anclada (medida en sondaje) con la densidad recuperada en
    # los mismos vóxeles. El anclaje es soft (κ finito), así que el solver PUEDE
    # apartarse del valor medido si los datos gravimétricos lo exigen → un Δ grande
    # señala datos inconsistentes (sondaje vs gravimetría) que el usuario debe revisar.
    if boreholes_arr is not None and len(boreholes_arr) > 0:
        try:
            from services.borehole_service import detect_borehole_conflicts
            _bh_validation = detect_borehole_conflicts(
                getattr(params, "boreholes", None) or [],
                est_density_full,
                x_c_full, y_c_full, z_c_full,
                dx,
            )
            _solver_meta["borehole_validation"] = _bh_validation["status"]
            _solver_meta["borehole_conflicts"] = _bh_validation["conflicts"]
            _solver_meta["borehole_validation_detail"] = {
                k: v for k, v in _bh_validation.items() if k != "conflicts"
            }
            print(
                f"[FASE 20] Validación sondajes: {_bh_validation['status']} | "
                f"{_bh_validation['n_conflicts']} conflictos / "
                f"{_bh_validation['n_warnings']} avisos de {_bh_validation['n_evaluated']} intervalos"
            )
        except Exception as _bh_exc:  # non-fatal: la inversión ya es válida
            _log.warning("borehole_conflict_detection_nonfatal", error=str(_bh_exc))

    # ── F0.9: Descartar Padding — solo celdas Core al frontend ───────────────
    est_density          = est_density_full[is_core]
    probability          = probability_full[is_core]
    normalized_sensitivity = sensitivity_full[is_core]

    _log.info(
        "tensor_mesh_padding_stripped",
        nx_total=nx_total, ny_total=ny_total, nz_total=nz_total,
        core_voxels=int(np.sum(is_core)),
        total_padded_voxels=int(len(est_density_full)),
    )

    # ── R-01: Forward consistente del solver (G_pad @ m_pad) ─────────────────
    # El solver internamente usa G_pad (grilla completa activa). Los diagnósticos
    # anteriores usaban G_core (solo core), ignorando la contribución de masa en padding.
    # Se reconstruye g_modeled usando el mismo kernel cacheado del solver.
    g_modeled_solver = None
    r01_consistency = {}
    try:
        _active_full = np.isfinite(est_density_full)  # coincide con active_cells del solver
        _G_pad = forward._build_sparse_kernel(         # cache HIT: misma geometría que el solver
            x_c_full[_active_full],
            y_c_full[_active_full],
            z_c_full[_active_full],
            sensor_coords,
        )
        _contrast_active = np.nan_to_num(
            est_density_full[_active_full] - inversor_padded.base_density, nan=0.0
        )
        g_modeled_solver = np.asarray(_G_pad @ _contrast_active, dtype=np.float64)

        # Test de consistencia R-01: ||G_pad·m_pad - G_core·m_core|| / ||G_pad·m_pad||
        _g_core_only = kernel_sparse @ np.nan_to_num(
            est_density - inversor_core.base_density, nan=0.0
        )
        _consistency_err = float(np.linalg.norm(g_modeled_solver - _g_core_only))
        _solver_norm     = float(np.linalg.norm(g_modeled_solver))
        _consistency_ratio = _consistency_err / max(_solver_norm, 1e-30)
        r01_consistency = {
            "consistency_ratio": round(_consistency_ratio, 8),
            "threshold": 1e-6,
            "status": "PASS" if _consistency_ratio < 1e-6 else "KERNEL_DUAL_DETECTED",
            "g_modeled_solver_norm": round(_solver_norm, 8),
            "g_modeled_core_norm": round(float(np.linalg.norm(_g_core_only)), 8),
        }
        _log.info(
            "r01_kernel_dual_consistency",
            consistency_ratio=round(_consistency_ratio, 8),
            status=r01_consistency["status"],
        )
        if _consistency_ratio >= 1e-6:
            _log.warning(
                "r01_kernel_dual_FAIL",
                consistency_ratio=round(_consistency_ratio, 8),
                detail=(
                    "||G_pad·m_pad - G_core·m_core|| / ||G_pad·m_pad|| >= 1e-6. "
                    "Existe masa significativa en padding que afecta el forward."
                ),
            )
    except Exception as _r01_exc:
        _log.warning("r01_consistency_nonfatal", error=str(_r01_exc))

    # ── R-02: Diagnóstico de masa en padding ──────────────────────────────────
    r02_padding_leak = {}
    try:
        _contrast_full = np.nan_to_num(
            est_density_full - inversor_padded.base_density, nan=0.0
        )
        _abs_mass_core  = float(np.sum(np.abs(_contrast_full[is_core])))
        _abs_mass_pad   = float(np.sum(np.abs(_contrast_full[~is_core])))
        _abs_mass_total = _abs_mass_core + _abs_mass_pad
        _mass_pad_ratio = _abs_mass_pad / max(_abs_mass_total, 1e-30)
        _acond_r02      = _solver_meta.get("acond", float("nan"))
        r02_padding_leak = {
            "mass_core_abs":     round(_abs_mass_core, 6),
            "mass_padding_abs":  round(_abs_mass_pad, 6),
            "mass_total_abs":    round(_abs_mass_total, 6),
            "mass_pad_ratio":    round(_mass_pad_ratio, 6),
            "kappa_applied":     _kappa,
            "cond_A":            round(_acond_r02, 4) if np.isfinite(_acond_r02) else None,
            "lambda_used":       _lambda_mag,
            "status": "PASS" if _mass_pad_ratio < 0.05 else "REVIEW_REQUIRED",
            "threshold": 0.05,
            "note": (
                "kappa=1e5 post-auditoría R-A1 (previo 1e4 → 15.4%). "
                "Solo actúa sobre smallness; smoothing invariante."
            ),
        }
        _log.info(
            "r02_padding_leak_diagnostic",
            mass_pad_ratio=round(_mass_pad_ratio, 4),
            kappa=_kappa,
            cond_A=round(_acond_r02, 4) if np.isfinite(_acond_r02) else None,
            status=r02_padding_leak["status"],
        )
        if _mass_pad_ratio >= 0.05:
            _log.warning(
                "r02_mass_pad_ratio_high",
                mass_pad_ratio=round(_mass_pad_ratio, 4),
                recommendation="Aumentar kappa a 1e6 si persiste > 5%.",
            )
    except Exception as _r02_exc:
        _log.warning("r02_mass_diagnostic_nonfatal", error=str(_r02_exc))

    # ── OBJETIVO 3: Diagnóstico de saturación (bound petrofísico) ─────────────
    # Breakdown por bound inferior/superior y por zona Core/Padding.
    # Determina si R-03 (Bound Relaxation) es REQUIRED.
    r03_saturation = {}
    try:
        _DMIN = _solver_meta.get("density_min", 2.6)
        _DMAX = _solver_meta.get("density_max", 5.5)
        _eps  = 1e-5
        _density_fin  = np.isfinite(est_density_full)
        _n_active_tot = int(np.sum(_density_fin))
        _n_core_active = int(np.sum(_density_fin & is_core))
        _n_pad_active  = int(np.sum(_density_fin & ~is_core))

        _sat_lo = _density_fin & (est_density_full <= _DMIN + _eps)
        _sat_hi = _density_fin & (est_density_full >= _DMAX - _eps)
        _n_sat_lo = int(np.sum(_sat_lo))
        _n_sat_hi = int(np.sum(_sat_hi))
        _n_sat_total = _n_sat_lo + _n_sat_hi

        _n_sat_lo_core = int(np.sum(_sat_lo & is_core))
        _n_sat_lo_pad  = int(np.sum(_sat_lo & ~is_core))
        _n_sat_hi_core = int(np.sum(_sat_hi & is_core))
        _n_sat_hi_pad  = int(np.sum(_sat_hi & ~is_core))

        # R-05: vóxeles muertos reciben base_density = D_min por diseño (contraste=0),
        # no por saturación del bound. Excluirlos del conteo de sat_lower.
        _n_dead_corr_core = _solver_meta.get("n_dead_core_active", 0)
        _n_dead_corr_pad  = _solver_meta.get("n_dead_pad_active",  0)
        _n_sat_lo_core = max(0, _n_sat_lo_core - _n_dead_corr_core)
        _n_sat_lo_pad  = max(0, _n_sat_lo_pad  - _n_dead_corr_pad)
        _n_sat_lo      = _n_sat_lo_core + _n_sat_lo_pad
        _n_sat_total   = _n_sat_lo + _n_sat_hi

        _sat_pct        = 100.0 * _n_sat_total / max(_n_active_tot, 1)
        _sat_pct_core   = 100.0 * (_n_sat_lo_core + _n_sat_hi_core) / max(_n_core_active, 1)
        _sat_pct_pad    = 100.0 * (_n_sat_lo_pad  + _n_sat_hi_pad)  / max(_n_pad_active, 1)

        # R-03 es REQUIRED solo si la saturación persiste >10% DESPUÉS de
        # corregir lambda (R-A2) y kappa (R-A1). Si la corrección la elimina → NO REQUIRED.
        _r03_required   = bool(_sat_pct > 10.0)

        r03_saturation = {
            "n_active_total":    _n_active_tot,
            "n_core_active":     _n_core_active,
            "n_pad_active":      _n_pad_active,
            "n_sat_lower":       _n_sat_lo,
            "n_sat_upper":       _n_sat_hi,
            "n_sat_total":       _n_sat_total,
            "n_sat_lower_core":  _n_sat_lo_core,
            "n_sat_lower_pad":   _n_sat_lo_pad,
            "n_sat_upper_core":  _n_sat_hi_core,
            "n_sat_upper_pad":   _n_sat_hi_pad,
            "sat_percent_total": round(_sat_pct, 2),
            "sat_percent_core":  round(_sat_pct_core, 2),
            "sat_percent_pad":   round(_sat_pct_pad, 2),
            "density_bounds":    [_DMIN, _DMAX],
            "r03_required":      _r03_required,
            "r03_decision":      "R03_REQUIRED" if _r03_required else "R03_NOT_REQUIRED",
            "threshold_pct":     10.0,
            "note": (
                "Saturación medida POST corrección lambda (R-A2) + kappa (R-A1). "
                "R-03 solo se implementa si saturación > 10% persiste aquí."
            ),
        }
        _log.info(
            "r03_saturation_diagnostic",
            sat_pct_total=round(_sat_pct, 2),
            sat_pct_core=round(_sat_pct_core, 2),
            sat_pct_pad=round(_sat_pct_pad, 2),
            r03_decision=r03_saturation["r03_decision"],
        )
    except Exception as _r03_exc:
        _log.warning("r03_saturation_nonfatal", error=str(_r03_exc))

    # ── R-06: Auditoría cuantitativa del impacto físico del padding saturado ───
    # Solo diagnóstico — no modifica solver, lambda, sigma, kappa, clipping ni bounds.
    # Determina si la saturación residual en padding es físicamente irrelevante
    # (impacto < 1% en masa y forward, Δchi² < 5%, ΔRMS < 5%) o requiere remediación.
    r06_padding_saturation_audit = {}
    try:
        _DMIN_r06     = _solver_meta.get("density_min", 2.6)
        _DMAX_r06     = _solver_meta.get("density_max", 5.5)   # H-A0 Bug 3
        _eps_r06      = 1e-5
        _chi2_orig_r06 = _solver_meta.get("chi2_final")

        # Celdas de padding activas que tocan el bound inferior o superior
        _active_r06 = np.isfinite(est_density_full)
        _pad_sat_full_r06 = (
            _active_r06 & ~is_core
            & (
                (est_density_full <= _DMIN_r06 + _eps_r06)
                | (est_density_full >= _DMAX_r06 - _eps_r06)
            )
        )
        _n_pad_sat_r06 = int(np.sum(_pad_sat_full_r06))

        _contrast_full_r06    = np.nan_to_num(
            est_density_full - inversor_padded.base_density, nan=0.0
        )

        # Kernel sobre celdas activas — cache HIT (misma geometría que solver y R-01)
        _G_r06 = forward._build_sparse_kernel(
            x_c_full[_active_r06],
            y_c_full[_active_r06],
            z_c_full[_active_r06],
            sensor_coords,
        )
        _contrast_act_r06    = _contrast_full_r06[_active_r06]    # (n_active,)
        _pad_sat_in_act_r06  = _pad_sat_full_r06[_active_r06]     # bool (n_active,)

        # 1. mass_pad_saturated = sum(|contrast_pad_sat|)
        _mass_pad_sat_r06 = float(np.sum(np.abs(_contrast_act_r06[_pad_sat_in_act_r06])))

        # 2. mass_fraction_pad_saturated = mass_pad_sat / mass_total
        _mass_total_r06   = float(np.sum(np.abs(_contrast_act_r06)))
        _mass_frac_r06    = _mass_pad_sat_r06 / max(_mass_total_r06, 1e-30)

        # 3. forward_pad_saturated = G[:, pad_sat] @ m_pad_sat
        _d_full_r06       = _G_r06 @ _contrast_act_r06
        _fwd_pad_sat_r06  = (_G_r06[:, _pad_sat_in_act_r06]
                             @ _contrast_act_r06[_pad_sat_in_act_r06])
        _d_norm_r06       = float(np.linalg.norm(_d_full_r06))
        _fwd_pad_sat_norm = float(np.linalg.norm(_fwd_pad_sat_r06))

        # 4. forward_fraction_pad_saturated = ||fwd_pad_sat|| / ||G @ m||
        _fwd_frac_r06 = _fwd_pad_sat_norm / max(_d_norm_r06, 1e-30)

        # Contrafactual: m_test = m con pad_saturated puesto a 0
        _contrast_test_r06 = _contrast_act_r06.copy()
        _contrast_test_r06[_pad_sat_in_act_r06] = 0.0
        _d_test_r06 = _G_r06 @ _contrast_test_r06

        # delta_rms como % del RMS del forward original
        _rms_orig_r06  = float(np.sqrt(np.mean(_d_full_r06 ** 2)))
        _delta_rms_r06 = (
            100.0
            * float(np.sqrt(np.mean((_d_test_r06 - _d_full_r06) ** 2)))
            / max(_rms_orig_r06, 1e-30)
        )

        # delta_chi2 como % del chi2 original (sigma adaptivo idéntico al solver)
        _dr_r06        = max(float(np.max(g_observed) - np.min(g_observed)), 1e-30)
        _sigma_r06     = np.maximum(0.02 * np.abs(g_observed), 0.01 * _dr_r06)
        _sigma_r06     = np.maximum(_sigma_r06, 1e-30)
        _res_test_r06  = g_observed - _d_test_r06
        _chi2_test_r06 = (
            float(np.sum((_res_test_r06 / _sigma_r06) ** 2))
            / max(len(g_observed), 1)
        )
        if _chi2_orig_r06 and _chi2_orig_r06 > 0:
            _delta_chi2_r06 = (
                100.0 * abs(_chi2_test_r06 - _chi2_orig_r06)
                / max(_chi2_orig_r06, 1e-30)
            )
        else:
            _delta_chi2_r06 = None

        # delta_mass = |mass_original - mass_test|
        _mass_test_r06  = float(np.sum(np.abs(_contrast_test_r06)))
        _delta_mass_r06 = abs(_mass_total_r06 - _mass_test_r06)

        # Criterios de decisión (todos deben cumplirse para IRRELEVANT)
        _all_ok_r06 = (
            _mass_frac_r06 < 0.01
            and _fwd_frac_r06 < 0.01
            and (_delta_chi2_r06 is not None and _delta_chi2_r06 < 5.0)
            and _delta_rms_r06 < 5.0
        )
        _r06_decision   = (
            "PADDING_SATURATION_PHYSICALLY_IRRELEVANT"
            if _all_ok_r06
            else "PADDING_SATURATION_SIGNIFICANT"
        )
        _phase_gate_r06 = "APPROVE_USING_SAT_CORE" if _all_ok_r06 else "REMEDIATION_REQUIRED"

        r06_padding_saturation_audit = {
            "n_pad_saturated":               _n_pad_sat_r06,
            "mass_pad_saturated":            round(_mass_pad_sat_r06, 6),
            "mass_fraction_pad_saturated":   round(_mass_frac_r06, 6),
            "forward_fraction_pad_saturated": round(_fwd_frac_r06, 6),
            "delta_rms_pct":                 round(_delta_rms_r06, 4),
            "delta_chi2_pct": (
                round(_delta_chi2_r06, 4) if _delta_chi2_r06 is not None else None
            ),
            "delta_mass":                    round(_delta_mass_r06, 6),
            "chi2_original":                 round(_chi2_orig_r06, 4) if _chi2_orig_r06 else None,
            "chi2_test":                     round(_chi2_test_r06, 4),
            "r06_decision":                  _r06_decision,
            "phase_gate_recommendation":     _phase_gate_r06,
            "criteria_thresholds": {
                "mass_fraction_pct": 1.0,
                "forward_fraction_pct": 1.0,
                "delta_chi2_pct": 5.0,
                "delta_rms_pct": 5.0,
            },
            "note": (
                "Diagnóstico R-06: impacto físico del padding saturado. "
                "Sin modificar solver, lambda, sigma, kappa, clipping ni bounds. "
                "IRRELEVANT si masa<1% AND forward<1% AND Δchi²<5% AND ΔRMS<5%."
            ),
        }
        _log.info(
            "r06_padding_saturation_audit",
            n_pad_sat=_n_pad_sat_r06,
            mass_frac_pct=round(_mass_frac_r06 * 100, 3),
            fwd_frac_pct=round(_fwd_frac_r06 * 100, 3),
            delta_rms_pct=round(_delta_rms_r06, 2),
            delta_chi2_pct=(
                round(_delta_chi2_r06, 2) if _delta_chi2_r06 is not None else None
            ),
            r06_decision=_r06_decision,
            phase_gate=_phase_gate_r06,
        )
    except Exception as _r06_exc:
        _log.warning("r06_saturation_audit_nonfatal", error=str(_r06_exc))

    # ── Track 3 / T3.1: Incertidumbre posterior por vóxel (Hutchinson) ────────
    # Opt-in (compute_uncertainty). Usa EXACTAMENTE la misma regularización que el
    # solve principal (mismo lambda_mag, alpha_spatial, topografía, tensor mesh).
    # σ en t/m³ por vóxel; NaN donde no se calculó → esquema estable.
    posterior_std = np.full(est_density.shape[0], np.nan, dtype=float)
    if getattr(params, "compute_uncertainty", False):
        try:
            _std_full = inversor_padded.estimate_posterior_std(
                g_observed, y_c_full, forward, sensor_coords, x_c_full, z_c_full,
                lambda_mag=_lambda_mag,   # FIX P0: usar lambda auto-seleccionado, no params.lambda_mag
                alpha_spatial=params.alpha_spatial,
                topography_elevations=_topography_elevations_padded,
                hx=hx, hy=hy, hz=hz,
            )
            posterior_std = _std_full[is_core]
            _log.info(
                "posterior_uncertainty_done",
                sigma_p50=round(float(np.nanpercentile(posterior_std, 50)), 6),
                sigma_p95=round(float(np.nanpercentile(posterior_std, 95)), 6),
            )
        except Exception as _uq_exc:
            _log.warning("posterior_uncertainty_nonfatal", error=str(_uq_exc))

    # ── FASE 8.3: targeting probabilístico automático (opt-in, non-fatal) ─────
    # Rankea blancos perforables desde el modelo invertido (core) + σ posterior por
    # vóxel. Reusa la σ de Hutchinson si compute_uncertainty la calculó; si no, la
    # función cae a una σ homoscedástica del MAD (degradado pero defendible). No
    # ejecuta física nueva — es post-proceso estadístico sobre est_density/x_c/y_c/z_c.
    drill_targets_report = None
    if getattr(params, "compute_drill_targets", False):
        try:
            from exploration.gravimetry import rank_drill_targets
            _ps_for_targets = posterior_std if np.isfinite(posterior_std).any() else None
            _sense = getattr(params, "drill_targets_sense", "positive")
            _rank_by = getattr(params, "drill_targets_rank_by", "expected_exceedance")
            _targets = rank_drill_targets(
                est_density, x_c, y_c, z_c,
                posterior_std=_ps_for_targets,
                top_n=int(getattr(params, "drill_targets_top_n", 10)),
                sense=_sense,
                rank_by=_rank_by,
            )
            drill_targets_report = {
                "computed": True,
                "n_targets": len(_targets),
                "sense": _sense,
                "rank_by": _rank_by,
                "used_posterior_std": _ps_for_targets is not None,
                "unit": "t/m3",
                "method": "probabilistic_targeting_linear_gaussian_posterior_nms3d",
                "note": (
                    "Ranking de TARGETING/ESTRUCTURA (dónde perforar): prob. de "
                    "exceedencia y exceedencia esperada bajo el posterior LINEAL por vóxel + "
                    "supresión de no-máximos 3D. NO es probabilidad de mena/ley. La "
                    "incertidumbre proviene de la σ de Hutchinson (compute_uncertainty=True); "
                    "sin ella se usa una σ homoscedástica del MAD (degradado)."
                ),
                "targets": _targets,
            }
            _log.info(
                "drill_targets_done",
                n=len(_targets),
                used_sigma=bool(_ps_for_targets is not None),
            )
        except Exception as _dt_exc:
            _log.warning("drill_targets_nonfatal", error=str(_dt_exc))

    # ── FASE 8.1: ensemble null-space (mapa de no-unicidad, opt-in non-fatal) ─
    # Abanico de modelos data-consistentes por proyección al espacio nulo; su σ por
    # vóxel mide la NO-UNICIDAD (dónde el dato NO fija la densidad), complementando la
    # σ posterior de Hutchinson (covarianza alrededor de UN óptimo). Mismos operadores
    # que el solve principal; sobre el modelo padded, reducido a core.
    ensemble_uncertainty_summary = None
    if getattr(params, "compute_ensemble_uncertainty", False):
        try:
            _ens = inversor_padded.null_space_shuttle_ensemble(
                est_density_full, g_observed, y_c_full, forward, sensor_coords,
                x_c_full, z_c_full,
                lambda_mag=_lambda_mag,
                alpha_spatial=params.alpha_spatial,
                topography_elevations=_topography_elevations_padded,
                hx=hx, hy=hy, hz=hz,
                n_shuttles=int(getattr(params, "ensemble_n_shuttles", 12)),
                density_min=params.density_min,
                density_max=params.density_max,
            )
            _ens_std_core = np.asarray(_ens["ensemble_std"], dtype=float)[is_core]
            _ens_fin = _ens_std_core[np.isfinite(_ens_std_core)]
            ensemble_uncertainty_summary = {
                "computed": True,
                "unit": "t/m3",
                "n_shuttles": int(_ens.get("n_shuttles", 0)),
                "p50": round(float(np.percentile(_ens_fin, 50)), 6) if _ens_fin.size else None,
                "p95": round(float(np.percentile(_ens_fin, 95)), 6) if _ens_fin.size else None,
                "max": round(float(np.max(_ens_fin)), 6) if _ens_fin.size else None,
                "n_voxels": int(_ens_fin.size),
                "null_fraction": round(float(_ens.get("null_fraction", 0.0)), 6),
                "data_fit_preserved": round(float(_ens.get("data_fit_preserved", 0.0)), 6),
                "method": "null_space_shuttle_ensemble_linear",
                "note": (
                    "σ del ENSEMBLE por vóxel (no-unicidad): abanico de modelos que ajustan "
                    "el dato igual de bien, perturbados por el espacio nulo de datos. Spread "
                    "alto = la densidad ahí NO está restringida por el dato (típico en "
                    "profundidad). Complementa la σ posterior de Hutchinson; ambas son "
                    "LINEALES alrededor de la solución. null_fraction alto = más no-unicidad."
                ),
            }
            _log.info(
                "ensemble_uncertainty_done",
                n=int(_ens.get("n_shuttles", 0)),
                null_fraction=round(float(_ens.get("null_fraction", 0.0)), 4),
            )
        except Exception as _ens_exc:
            _log.warning("ensemble_uncertainty_nonfatal", error=str(_ens_exc))

    # ── DOI: doble inversión con modelos de referencia (Li & Oldenburg 1999) ──
    # Inversión 1 (m_ref1) es IDÉNTICA a la corrida principal de arriba (mismo m_ref):
    # por eso m1 = est_density principal y solo se ejecuta UNA inversión extra, con
    # m_ref2 = m_ref1 + 0.1 (desplazamiento constante sobre la grilla completa).
    # La diferencia m1 - m2 cancela la densidad base (ambas llevan +base_density),
    # de modo que doi_raw mide directamente la sensibilidad del contraste recuperado
    # frente al desplazamiento del modelo de referencia. FASE 7.2: sin prior geológico
    # m_ref1 = 0 (histórico byte-idéntico); con prior, m_ref1 = m_ref geológico para
    # que la pass-1 (m1) y la pass-2 (m2) compartan la misma línea base.
    n_padded = int(est_density_full.shape[0])
    m_ref1   = (
        np.zeros(n_padded, dtype=float) if _geo_m_ref is None
        else np.asarray(_geo_m_ref, dtype=float).copy()
    )
    m_ref2   = m_ref1 + 0.1                            # referencia desplazada +0.1 t/m³

    doi_raw = np.full(est_density.shape[0], np.nan, dtype=float)   # fallback de esquema estable
    try:
        est_density_full_ref2, _doi_p2, _doi_mf2, _doi_s2 = _run_lsqr_with_heartbeat(
            inversor=inversor_padded,
            g_observed=g_observed,
            kernel_sparse=None,
            y_c=y_c_full,
            lambda_mag=_lambda_mag,        # FIX P0: usar lambda auto-seleccionado, no params.lambda_mag
            alpha_spatial=params.alpha_spatial,
            project_id=project_id,
            run_id=run_id,
            forward_model=forward,
            sensor_coords=sensor_coords,
            x_c=x_c_full,
            z_c=z_c_full,
            topography_elevations=_topography_elevations_padded,
            hx=hx, hy=hy, hz=hz,
            m_ref=m_ref2,                  # Inversión 2: referencia 0.1
            density_min=params.density_min,
            density_max=params.density_max,
            boreholes=boreholes_arr,       # FASE 8: anclar igual que pass-1 → doi_raw coherente
            anchor_mode=_anchor_mode,      # FASE 2.1: mismo modo que pass-1
            lithology_bounds=_litho_bounds_g,  # FASE 2.3: mismo box que pass-1
            noise_floor=_noise_floor_solver,
            noise_pct=_noise_pct_solver,
        )

        # m1, m2 reducidos a la grilla Core (padding descartado).
        m1          = est_density                       # Inversión 1 (m_ref1 = 0)
        m2          = est_density_full_ref2[is_core]    # Inversión 2 (m_ref2 = 0.1)
        m_ref1_core = m_ref1[is_core]
        m_ref2_core = m_ref2[is_core]

        # Métrica DOI continua — sin clipping agresivo ni reinterpretación heurística.
        doi_raw = np.abs(m1 - m2) / np.maximum(
            np.abs(m_ref1_core - m_ref2_core),
            1e-12,
        )
        _log.info(
            "doi_double_inversion",
            n_core=int(doi_raw.shape[0]),
            doi_p50=round(float(np.nanpercentile(doi_raw, 50)), 4),
            doi_p95=round(float(np.nanpercentile(doi_raw, 95)), 4),
            doi_max=round(float(np.nanmax(doi_raw)), 4),
        )
    except Exception as _doi_exc:
        _log.warning("doi_nonfatal", error=str(_doi_exc))

    # ── Checkerboard QA automático — reutiliza kernel_sparse Core, non-fatal ──
    _cb_qa = None
    try:
        _cb_qa = _run_checkerboard_qa_fast(
            kernel_sparse_core=kernel_sparse,
            nx=nx, ny=ny, nz=nz,
            lambda_mag=_lambda_mag,    # FIX P1: usar lambda auto-seleccionado, no params.lambda_mag
        )
        _log.info("checkerboard_qa", pearson_r=_cb_qa["pearson_r"], status=_cb_qa["status"])
    except Exception as _cb_exc:
        _log.warning("checkerboard_qa_nonfatal", error=str(_cb_exc))
    # ──────────────────────────────────────────────────────────────────────────

    misfit_error_percent = round(float(misfit_percent), 2)
    _update("running", 0.85, "solving_lsqr", "Solver LSQR completado. Post-procesando...",
            metrics={"misfit_error_percent": misfit_error_percent})

    fit_diagnostics = build_fit_diagnostics(
        g_observed=g_observed,
        kernel_sparse=kernel_sparse,         # Core-only (fallback si g_modeled_solver es None)
        est_density=est_density,
        base_density=inversor_core.base_density,
        sensor_coords=sensor_coords,
        g_modeled_precomputed=g_modeled_solver,  # R-01: G_pad @ m_pad (None si falló)
        # CRÍTICO: usar el MISMO sigma que usó el solver/Morozov. Antes se usaba el
        # default sentinel (0.02/0.02 → σ≈0.01·rango ≈ 0.29 mGal), que daba un chi²
        # artificialmente bajo (~0.02) y disparaba la falsa alarma de "sobreajuste",
        # mientras Morozov optimizaba contra σ instrumental (0.05 mGal → chi²≈0.65).
        # El chi² reportado debe corresponder al σ contra el que se invirtió.
        noise_floor=_noise_floor_solver,
        noise_pct=_noise_pct_solver,
    )
    fit_diagnostics["misfit_error_percent"] = misfit_error_percent
    fit_diagnostics["chi2_final_solver"]   = _solver_meta.get("chi2_final")
    fit_diagnostics["cond_A_solver"]       = _solver_meta.get("acond")
    fit_diagnostics["lambda_used"]         = _lambda_mag
    fit_diagnostics["lambda_effective"]    = _solver_meta.get("lambda_effective", _lambda_mag)
    # R-01, R-02, R-A1, R-A2, OBJETIVO 3
    fit_diagnostics["r01_kernel_dual_consistency"] = r01_consistency
    fit_diagnostics["r02_padding_leak"]            = r02_padding_leak
    fit_diagnostics["r03_saturation"]              = r03_saturation
    fit_diagnostics["r06_padding_saturation_audit"] = r06_padding_saturation_audit
    if _lambda_scan_meta:
        fit_diagnostics["lambda_scan_chi2"]        = _lambda_scan_meta

    # Cutoff adaptativo según escala del dataset.
    # Para datos regionales (blockSize > 500m), el percentil 40 falla cuando la
    # distribución de densidades es muy estrecha (ej. HVC: 2.6-2.9 t/m³) porque
    # p40 ≈ mínimo real → 100% de vóxeles clasificados como anomalía → sin contraste.
    # Se usa mean + 0.5σ para garantizar ~30% de vóxeles sobre umbral sin importar
    # cuán estrecha sea la distribución.
    if dx > 500:
        mean_d = float(np.nanmean(est_density))
        std_d = float(np.nanstd(est_density))
        cutoff_density = mean_d + 0.5 * std_d
        # Guard: nunca más bajo que el mínimo real
        cutoff_density = max(cutoff_density, float(np.nanmin(est_density)) + 0.01)
        # Guard: nunca más alto que el máximo real
        cutoff_density = min(cutoff_density, float(np.nanmax(est_density)) - 0.01)
        _log.info(
            "regional_adaptive_cutoff",
            block_size=dx,
            cutoff_density=round(cutoff_density, 4),
            mean_density=round(mean_d, 4),
            std_density=round(std_d, 4),
            expected_anomaly_pct=round(
                100 * float((est_density > cutoff_density).mean()), 1
            ),
        )
    else:
        cutoff_density = 2.75

    # Se sigue ejecutando TargetingEngine por compatibilidad industrial.
    # Pero NO usamos su Parquet como archivo principal, porque suele exportar solo anomalías.
    try:
        TargetingEngine.extract_and_export(
            x_c,
            y_c,
            z_c,
            est_density,
            probability,
            cutoff_density=cutoff_density,
            posterior_std=posterior_std,  # σ posterior Hutchinson (NaN si no se calculó)
        )
    except Exception as exc:
        _log.warning("targeting_engine_warning", error=str(exc))

    # MS-x focusing runs by backend policy since A1.4.
    # No-fatal: un error de focusing no interrumpe la inversión base.
    # El modelo LSQR y todos los outputs existentes quedan intactos.
    # Backend policy ignores params.enable_focusing; MS-x is attempted every run.
    focusing_payload = None
    try:
        focus_result = run_focusing(
            kernel_sparse=kernel_sparse,   # Core-only (coincide con inversor_core)
            g_obs=g_observed,
            y_c=y_c,                       # Core y_c
            inversor=inversor_core,        # F0.9: usa inversor Core, no el padded
            est_density=est_density,       # Core est_density (padding ya descartado)
            alpha_spatial=params.alpha_spatial,
            lambda_mag=_lambda_mag,        # no-op en MS-x (ver focusing.py); consistencia
        )

        msx_max   = max(float(np.max(focus_result.m_best)), 1e-9)
        msx_score = np.clip(focus_result.m_best / msx_max, 0.0, 1.0)

        _n_focus = len(x_c)
        df_focusing = pl.DataFrame({
            "x":                     x_c.astype(float),
            "y":                     y_c.astype(float),
            "z":                     z_c.astype(float),
            "ix":                    ix.astype(int),
            "iy":                    iy.astype(int),
            "iz":                    iz.astype(int),
            "msx_score":             msx_score.astype(float),
            "msx_density_candidate": focus_result.m_best.astype(float),
            "scale_status":          [focus_result.scale_status] * _n_focus,
            "use_mode":              [focus_result.use_mode] * _n_focus,
            "run_type":              ["gravity"] * _n_focus,
            "schema_version":        ["v4.0"] * _n_focus,
        })

        focusing_ref  = get_run_focusing_reference(
            project_id=params.project_id,
            run_id=params.run_id,
        )
        focusing_path = None
        # Solo persistir cuando hay project_id/run_id (evitar sobrescribir bloque legacy)
        if not focusing_ref.is_legacy:
            focusing_ref.path.parent.mkdir(parents=True, exist_ok=True)
            df_focusing.write_parquet(str(focusing_ref.path))
            focusing_path = str(focusing_ref.path)

        focusing_payload = {
            "enabled":      True,
            "source":       "backend_policy",
            "scale_status": str(focus_result.scale_status) if focus_result.scale_status is not None else None,
            "use_mode":     str(focus_result.use_mode) if focus_result.use_mode is not None else None,
            # [FIX] safety_labels: garantizar lista de str Python nativo
            "safety_labels": [str(s) for s in (focus_result.safety_labels or [])],
            "focusing_metadata": {
                # [FIX] int/bool explícitos: focus_result puede devolver numpy.int_ / numpy.bool_
                "best_iter":        int(focus_result.best_iter),
                "total_iters":      int(focus_result.total_iters),
                "converged":        bool(focus_result.converged),
                # float() explícito sobre round(): numpy.float64.__round__ devuelve float Python,
                # pero el cast extra protege ante cambios de versión de NumPy
                "rms_base":         float(round(focus_result.rms_base, 8)),
                "rms_best":         float(round(focus_result.rms_best, 8)),
                "max_density_base": float(round(focus_result.max_density_base, 4)),
                "max_density_msx":  float(round(focus_result.max_density_msx, 4)),
                "elapsed_seconds":  float(round(focus_result.elapsed_seconds, 2)),
                **focus_result.config_summary,
            },
            "focusing_parquet_path": focusing_path,
        }

    except Exception as exc:
        _log.warning("focusing_warning_nonfatal", source="backend_policy", error=str(exc))
        focusing_payload = {
            "enabled": False,
            "source": "backend_policy",
            "error": str(exc),
            "safety_labels": ["not_resource_estimate"],
        }
    # ─────────────────────────────────────────────────────────────────────────

    df_full = build_full_block_model_dataframe(
        params=params,
        ix=ix,
        iy=iy,
        iz=iz,
        x_c=x_c,
        y_c=y_c,
        z_c=z_c,
        est_density=est_density,
        probability=probability,
        base_density=float(inversor_core.base_density),
        cutoff_density=float(cutoff_density),
    )
    df_full = df_full.with_columns(
        pl.Series("sensitivity_proxy", normalized_sensitivity.astype(float))
    )
    # DOI (Li & Oldenburg 1999) — v4.0 usa doi_index; doi_raw se mantiene como alias.
    df_full = df_full.with_columns([
        pl.Series("doi_index", doi_raw.astype(float)),  # v4.0 canonical
        pl.Series("doi_raw",   doi_raw.astype(float)),  # v3.0 backward compat
    ])
    # Track 3 / T3.1: σ posterior (Hutchinson) por vóxel — NaN si no se calculó.
    df_full = df_full.with_columns(
        pl.Series("posterior_std", posterior_std.astype(float))
    )

    n_full = len(df_full)
    df_full = df_full.with_columns([
        pl.Series("run_type", ["gravity"] * n_full),
        pl.Series("schema_version", ["v4.0"] * n_full),
    ])

    df_anomaly = build_anomaly_dataframe(
        df_full=df_full,
        cutoff_density=cutoff_density,
    )

    # Fallback: si no hay anomalías (señal débil), devolver todos los vóxeles activos
    # para que el frontend pueda siempre renderizar el modelo de densidad.
    if len(df_anomaly) == 0 and len(df_full) > 0:
        _active_mask = pl.col("density").is_not_null() & pl.col("density").is_finite()
        df_anomaly = df_full.filter(_active_mask).sort("density", descending=True)
        _log.info("anomaly_fallback_all_voxels", total_voxels=len(df_anomaly))

    block_model_ref = get_run_block_model_reference(
        project_id=params.project_id,
        run_id=params.run_id,
    )
    block_model_ref.path.parent.mkdir(parents=True, exist_ok=True)
    _update("running", 0.90, "postprocessing", "Exportando block model y generando reportes...")
    df_full.write_parquet(str(block_model_ref.path))
    _grav_schema_result = validate_parquet_schema(block_model_ref.path, expected_run_type="gravity")

    # ── Fase 10: Zarr out-of-core para grids >500k vóxeles ────────────────────
    _n_vox_full = len(df_full)
    _zarr_info: dict | None = None
    if _n_vox_full > 500_000:
        try:
            _run_dir_zarr = str(block_model_ref.path.parent)
            _zarr_voxels = df_full.select(
                ["x_m", "y_m", "z_m", "density", "susceptibility_si", "doi_index"]
            ).rename({"x_m": "cx", "y_m": "cy", "z_m": "cz", "susceptibility_si": "susceptibility"}).to_dicts()
            _zarr_info = create_zarr_block_model(
                voxels=_zarr_voxels,
                project_id=params.project_id,
                run_id=params.run_id,
                run_dir=_run_dir_zarr,
            )
            _log.info("zarr_block_model_written", n_voxels=_n_vox_full, zarr_path=_zarr_info.get("zarr_path"))
        except Exception as _zarr_exc:
            _log.warning("zarr_block_model_nonfatal", error=str(_zarr_exc))
    if not _grav_schema_result["valid"]:
        _log.warning(
            "gravity_parquet_schema_invalid",
            run=params.run_id,
            errors=_grav_schema_result["errors"],
        )

    anomaly_ref = get_run_anomaly_reference(
        project_id=params.project_id,
        run_id=params.run_id,
    )
    anomaly_ref.path.parent.mkdir(parents=True, exist_ok=True)
    df_anomaly.write_parquet(str(anomaly_ref.path))

    # ── H-C1: persistir obs_vs_calc.parquet ───────────────────────────────────
    try:
        _d_obs   = _solver_meta.get("d_obs")
        _d_pred  = _solver_meta.get("d_pred")
        _resids  = _solver_meta.get("residuals")
        _sc      = _solver_meta.get("station_coords")
        if _d_obs is not None and _d_pred is not None and _resids is not None:
            _ovc_cols: dict = {}
            if _sc is not None:
                _sc_arr = np.asarray(_sc, dtype=np.float64)
                if _sc_arr.ndim == 2 and _sc_arr.shape[1] >= 3:
                    _ovc_cols["x"] = _sc_arr[:, 0]
                    _ovc_cols["y"] = _sc_arr[:, 1]
                    _ovc_cols["z"] = _sc_arr[:, 2]
            _ovc_cols["d_obs"]    = np.asarray(_d_obs, dtype=np.float64)
            _ovc_cols["d_pred"]   = np.asarray(_d_pred, dtype=np.float64)
            _ovc_cols["residual"] = np.asarray(_resids, dtype=np.float64)
            df_ovc = pl.DataFrame(_ovc_cols)
            _ovc_path = block_model_ref.path.parent / "obs_vs_calc.parquet"
            df_ovc.write_parquet(str(_ovc_path))
            _log.info("obs_vs_calc_written", n_stations=len(_d_obs), path=str(_ovc_path))
    except Exception as _ovc_exc:
        _log.warning("obs_vs_calc_nonfatal", error=str(_ovc_exc))

    # ── HITO 2: Run Manifest (provenance audit trail) ─────────────────────────
    try:
        def _git_hash_short() -> str:
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL, timeout=2,
                ).decode().strip()
            except Exception:
                return "unknown"

        _run_dir_manifest = block_model_ref.path.parent
        _csv_path_manifest = _run_dir_manifest / RUN_SOURCE_GRAVITY_FILENAME
        write_run_manifest(_run_dir_manifest, {
            "schema_version": "v4.0",
            "run_type": "gravity",
            "code_version": _git_hash_short(),
            "rng_seed": None,
            "timestamp_utc_start": _inversion_start_utc.isoformat(),
            "timestamp_utc_end": datetime.now(timezone.utc).isoformat(),
            "sha256_parquet": sha256_file(block_model_ref.path),
            "sha256_csv": sha256_file(_csv_path_manifest) if _csv_path_manifest.exists() else None,
            "inversion_params": {
                "nx": params.nx, "ny": params.ny, "nz": params.nz,
                "block_size": params.block_size,
                "lambda_mag": params.lambda_mag,
                "alpha_spatial": params.alpha_spatial,
                "cutoff_radius": params.cutoff_radius,
                "depth": getattr(params, "depth", None),
                "enable_focusing": getattr(params, "enable_focusing", False),
            },
            "solver_stats": {
                "acond": _solver_meta.get("acond"),
                "chi2_final": _solver_meta.get("chi2_final"),
                "n_sat_lower": _solver_meta.get("n_sat_lower"),
                "n_sat_upper": _solver_meta.get("n_sat_upper"),
                "n_sat_total": _solver_meta.get("n_sat_total"),
                "n_active": _solver_meta.get("n_active"),
                "misfit_error_percent": misfit_error_percent,
            },
        })
    except Exception as _mfst_exc:
        _log.warning("run_manifest_nonfatal", error=str(_mfst_exc))
    # ── Fin HITO 2 ────────────────────────────────────────────────────────────

    # ── FASE 10: Exportación Industrial VTK (.vtr) ────────────────────────────
    # Non-fatal: si pyevtk no está instalado, vtr_path = None y se omite en el report.
    # Solo exportamos la zona CORE (padding ya descartado en est_density / normalized_sensitivity).
    vtr_export_path: str | None = None
    try:
        _vtr_output_dir = str(block_model_ref.path.parent)
        vtr_export_path = export_core_to_vtr(
            output_dir=_vtr_output_dir,
            run_prefix="block_model_core",
            nx=nx,
            ny=ny,
            nz=nz,
            dx=float(dx),
            est_density=est_density,                # Core 1D Fortran order
            sensitivity=normalized_sensitivity,     # Core 1D Fortran order
            is_active_flat=None,                    # se infiere de np.isfinite(est_density)
        )
        if vtr_export_path:
            _log.info("vtk_export_done", path=vtr_export_path)
        else:
            _log.info("vtk_export_skipped", reason="pyevtk_not_available_or_error")
    except Exception as _vtr_exc:
        _log.warning("vtk_export_nonfatal", error=str(_vtr_exc))
    # ── Fin FASE 10 ───────────────────────────────────────────────────────────

    write_run_json_snapshots(params)

    if block_model_ref.path != DEFAULT_BLOCK_MODEL_PATH:
        DEFAULT_BLOCK_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        df_full.write_parquet(str(DEFAULT_BLOCK_MODEL_PATH))

    voxels = build_voxel_output(df_anomaly, dx, cutoff_density=cutoff_density)
    total_tonnage = float(df_full["modeled_rock_mass_tonnes"].fill_nan(0.0).sum())

    technical_summary = build_geophysical_technical_summary(qaqc_report, fit_diagnostics)
    uncertainty_diagnostics = build_uncertainty_diagnostics(qaqc_report, fit_diagnostics, technical_summary)
    sensor_quality_flags = build_sensor_quality_flags(fit_diagnostics)

    # B1 (null-space honesto): el blanco se elige sobre el CAMPO ACTIVO COMPLETO (df_full),
    # no sólo las anomalías de alta densidad, para que el cuerpo de baja densidad a
    # profundidad resoluble pueda surfacear y el artefacto bound-saturado del piso se degrade.
    best_target = build_best_target(
        df_full,
        technical_summary=technical_summary,
        uncertainty_diagnostics=uncertainty_diagnostics,
        density_min=getattr(params, "density_min", None),
        density_max=getattr(params, "density_max", None),
        block_size=dx,
        cutoff_density=float(cutoff_density),
    )

    report = build_geophysics_report(
        voxels=voxels,
        total_voxels=total_voxels,
        cutoff_density=cutoff_density,
        total_tonnage=total_tonnage,
        parquet_path=str(block_model_ref.path),
        technical_summary=technical_summary,
        uncertainty_diagnostics=uncertainty_diagnostics,
        expose_demo_grade=getattr(params, "expose_demo_grade", False),
    )

    # ── DOI: estadísticas resumen (Li & Oldenburg 1999) ──────────────────────
    _doi_finite = doi_raw[np.isfinite(doi_raw)]
    if _doi_finite.size > 0:
        doi_summary = {
            "p50": round(float(np.percentile(_doi_finite, 50)), 6),
            "p85": round(float(np.percentile(_doi_finite, 85)), 6),
            "p95": round(float(np.percentile(_doi_finite, 95)), 6),
            "max": round(float(np.max(_doi_finite)), 6),
            "n_voxels": int(_doi_finite.size),
            "reference_models": {"m_ref1": 0.0, "m_ref2": 0.1},
            "method": "double_inversion_li_oldenburg_1999",
            "note": (
                "doi_raw = |m1 - m2| / max(|m_ref1 - m_ref2|, 1e-12). "
                "Valores altos = modelo recuperado más dependiente del modelo de referencia "
                "(menor resolución/profundidad de investigación)."
            ),
        }
    else:
        doi_summary = {
            "p50": None, "p85": None, "p95": None, "max": None,
            "n_voxels": 0,
            "reference_models": {"m_ref1": 0.0, "m_ref2": 0.1},
            "method": "double_inversion_li_oldenburg_1999",
            "note": "DOI no disponible para esta corrida.",
        }

    # ── Track 3 / T3.1: resumen de incertidumbre posterior (Hutchinson) ──────
    _ps_finite = posterior_std[np.isfinite(posterior_std)]
    if _ps_finite.size > 0:
        posterior_uncertainty_summary = {
            "computed": True,
            "unit": "t/m3",
            "p50": round(float(np.percentile(_ps_finite, 50)), 6),
            "p95": round(float(np.percentile(_ps_finite, 95)), 6),
            "max": round(float(np.max(_ps_finite)), 6),
            "n_voxels": int(_ps_finite.size),
            "method": "hutchinson_posterior_diag_linear_gaussian",
            "is_statistical_posterior": True,
            "note": (
                "σ posterior LINEAL por vóxel: sqrt(diag((GᵀWdG + λ_spatial²LᵀL + "
                "λ_mag²I)⁻¹)) vía estimador de Hutchinson. Es incertidumbre estadística "
                "(1σ), no heurística. No captura la no-unicidad no-lineal ni el sesgo "
                "de profundidad inherente a la gravimetría."
            ),
        }
    else:
        posterior_uncertainty_summary = {
            "computed": False,
            "is_statistical_posterior": True,
            "method": "hutchinson_posterior_diag_linear_gaussian",
            "note": "No calculada (compute_uncertainty=False o no disponible en esta corrida).",
        }

    # ── FASE 5.2: Volumen volumétrico co-registrado (opt-in, non-fatal) ────────
    # Lee el block model gravimétrico ya escrito en disco y, si en el mismo run dir
    # existe el parquet magnético (joint), co-registra ambas físicas en un volumen
    # esparso (.npz siempre; .vdb si pyopenvdb está instalado). Aditivo: OFF (default)
    # = sin export. No ejecuta física nueva — solo lee parquets persistidos.
    # El SVDAG categórico (5.3) deriva del MISMO volumen co-registrado, así que basta
    # con que CUALQUIERA de los dos flags esté ON para construir el volumen una vez.
    _coregistered_volume_info = None
    _want_vol = getattr(params, "export_coregistered_volume", False)
    _want_svdag = getattr(params, "export_categorical_svdag", False)
    if _want_vol or _want_svdag:
        try:
            from services.volumetric_service import export_coregistered_volume
            _run_dir_vol = block_model_ref.path.parent
            _mag_pq_vol = _run_dir_vol / RUN_MAGNETIC_BLOCK_MODEL_FILENAME
            _coregistered_volume_info = export_coregistered_volume(
                output_dir=str(_run_dir_vol),
                run_prefix="coregistered_volume",
                gravity_path=str(block_model_ref.path),
                magnetic_path=str(_mag_pq_vol) if _mag_pq_vol.exists() else None,
                write_vdb=_want_vol,
                write_svdag=_want_svdag,
            )
            _log.info(
                "coregistered_volume_written",
                npz=_coregistered_volume_info.get("npz_path"),
                vdb=_coregistered_volume_info.get("vdb_path"),
                channels=_coregistered_volume_info.get("channels"),
                svdag=(_coregistered_volume_info.get("svdag") or {}).get("npz_path"),
            )
        except Exception as _vol_exc:
            _log.warning("coregistered_volume_nonfatal", error=str(_vol_exc))

    # ── Decisión final R-03 (basada en saturación real medida) ──────────────
    _r03_decision = r03_saturation.get("r03_decision", "R03_NOT_REQUIRED") if r03_saturation else "R03_NOT_REQUIRED"

    # ── B2: resolución de profundidad POR-EJE (aditivo; no usa el posterior σ NaN) ──
    _observable_depth_max_m = round(min(params.cutoff_radius, params.ny * params.block_size), 1)
    _depth_resolution = build_depth_resolution(
        df_full, _observable_depth_max_m, best_target, dx)

    report_payload = {
        **report,
        **block_model_ref.metadata(),
        "misfit_error_percent": misfit_error_percent,
        "misfit_warning": (
            "Misfit perfecto detectado. Datos posiblemente sintéticos o lambda sub-óptima"
            if misfit_error_percent <= 0.01 else None
        ),
        "doiDiagnostics": doi_summary,
        "uncertaintyPosterior": posterior_uncertainty_summary,
        # ── B2: resolución de profundidad por-eje (cola null-space MEDIDA) ────
        "depthResolution": _depth_resolution,
        # ── FASE 8.3: targeting probabilístico (null si compute_drill_targets=False) ─
        "drillTargets": drill_targets_report or {
            "computed": False,
            "method": "probabilistic_targeting_linear_gaussian_posterior_nms3d",
            "note": "No calculado (compute_drill_targets=False o no disponible).",
        },
        # ── FASE 8.1: ensemble null-space (no-unicidad; null si flag OFF) ─────
        "ensembleUncertainty": ensemble_uncertainty_summary or {
            "computed": False,
            "method": "null_space_shuttle_ensemble_linear",
            "note": "No calculado (compute_ensemble_uncertainty=False o no disponible).",
        },
        "anomalyPath": str(anomaly_ref.path),
        "legacyBlockModelPath": str(DEFAULT_BLOCK_MODEL_PATH),
        "observationQuality": qaqc_report,
        "fitDiagnostics": fit_diagnostics,
        "technicalSummary": technical_summary,
        "uncertaintyDiagnostics": uncertainty_diagnostics,
        "sensorQualityFlags": sensor_quality_flags,
        "best_target": best_target,
        "anomaly_selection_mode": "physical_density_or_visual_score",
        "anomaly_selection_note": (
            "grade/anomaly_intensity se conserva como interpretación geometalúrgica, "
            "pero no selecciona anomalías físicas. El filtro usa density >= cutoff "
            "OR visual_score >= 0.35."
        ),
        # P2-1: Clarificación del campo 'probability' en el payload de vóxeles.
        # NO es una probabilidad estadística; es un score de ranking normalizado [0,1]
        # derivado de la sensibilidad residual: score_j = 1 - |G^T r|_j / max|G^T r|.
        # Es una métrica de priorización relativa, no un estimador de probabilidad de
        # mineralización. El campo 'uncertaintyPosterior' (Hutchinson) es la estimación
        # estadística real cuando compute_uncertainty=True.
        "probability_field_interpretation": {
            "field_name": "probability",
            "is_statistical_probability": False,
            "actual_meaning": "ranking_score_normalized_residual_sensitivity",
            "formula": "score_j = 1 - |G^T r|_j / max_j(|G^T r|)",
            "range": "[0, 1]",
            "note": (
                "Usar 'uncertaintyPosterior' (Hutchinson, compute_uncertainty=True) "
                "para incertidumbre estadística real por vóxel."
            ),
        },
        "auto_params": build_report_auto_params(params),
        # ── Post-auditoría R-A1/R-A2/R-03 ────────────────────────────────────
        "r03_decision":           _r03_decision,
        "r03_saturation":         r03_saturation,
        "lambda_used":            _lambda_mag,
        "lambda_effective":       _solver_meta.get("lambda_effective", _lambda_mag),
        "lambda_spatial_approx":  round(_lambda_spatial_eff, 8),
        "kappa_used":             _kappa,
        "chi2_final":             _solver_meta.get("chi2_final"),
        "cond_A":                 _solver_meta.get("acond"),
        "lambda_scan_chi2":       _lambda_scan_meta if _lambda_scan_meta else None,
        # ── FASE 7.2: prior geológico implícito (φ HRBF → m_ref) ─────────────
        "implicit_geology":       _geo_meta,
        # ── FASE 20: Validación de sondajes (anclaje vs modelo recuperado) ────
        "borehole_validation":    _solver_meta.get("borehole_validation"),
        "borehole_conflicts":     _solver_meta.get("borehole_conflicts"),
        "borehole_validation_detail": _solver_meta.get("borehole_validation_detail"),
        # ── R-05: Auditoría de dominio geométrico observable ──────────────────
        "r05_geometry_audit": {
            "dead_voxels":         _solver_meta.get("n_dead_voxels", 0),
            "observable_voxels":   _solver_meta.get("n_observable", 0),
            "observable_ratio":    _solver_meta.get("observable_ratio", None),
            "observable_depth_max_m": round(
                min(params.cutoff_radius, params.ny * params.block_size), 1
            ),
            "status": (
                "PASS" if _solver_meta.get("n_dead_voxels", 0) == 0
                else "DEAD_VOXELS_REMOVED"
            ),
            "note": (
                "Dead voxels = celdas activas con sens=0 para todos los sensores "
                "(más allá del cutoff_radius). Excluidas del solver; "
                "asignadas density=base_density=2.60 t/m3 en la reconstruccion."
            ),
        },
        # ── HITO 5: Topografía y solver bound-constrained ─────────────────────────
        "topography_used": _topography_used,
        "bounded_solver_active": os.getenv("USE_BOUNDED_SOLVER", "true").lower() != "false",
        # ── R-06: Auditoría de impacto físico del padding saturado ───────────────
        "r06_padding_saturation_audit": r06_padding_saturation_audit,
        # ── Fase 10: Zarr out-of-core storage ─────────────────────────────────
        "zarr_storage": _zarr_info,
        # ── FASE 5.2: volumen volumétrico co-registrado (None si no se pidió) ───
        "coregistered_volume": _coregistered_volume_info,
        # ── FASE 10: VTK export ────────────────────────────────────────────────
        "vtk_export": {
            "vtr_path": vtr_export_path,
            "format": "VTK Rectilinear Grid XML (.vtr)",
            "compatible_with": ["ParaView", "Leapfrog Geo", "Vulcan", "GOCAD"],
            "fields": ["Density_Contrast_gcm3", "Sensitivity_Proxy", "Is_Active"],
            "note": (
                "Filtrar celdas de aire en ParaView con Threshold → Is_Active == 1. "
                "Densidad base: 2.6 g/cm³. Sentinel de aire: -9999.0."
            ),
            "available": vtr_export_path is not None,
        },
    }

    if focusing_payload is not None:
        report_payload["focusing"] = focusing_payload

    if _cb_qa is not None:
        report_payload["checkerboard_qa"] = _cb_qa

    # ── Fase 5: Contexto geológico honesto ───────────────────────────────────
    _survey_extent_m = max(params.nx, params.nz) * params.block_size
    if _survey_extent_m > 50_000:
        _geo_hint = "regional"
    elif _survey_extent_m > 5_000:
        _geo_hint = "local_to_district"
    else:
        _geo_hint = "local_deposit"
    report_payload["geological_context"] = {
        "hint": _geo_hint,
        "disclaimer": (
            "Este modelo invertido es geofísicamente válido a su escala. "
            "NO emite ley, tonelaje, reserves minerales ni indicadores de rentabilidad. "
            "Solo densidad / susceptibilidad recuperadas. Requiere integración con datos "
            "geológicos/mineros independientes para cualquier decisión de inversión."
        ),
        "estimated_survey_extent_m": _survey_extent_m,
        "block_size_m": params.block_size,
        "mining_metrics_disclaimer": {
            "grade": (
                "NOT computed by TerraQuantum. Grade requires geological assays and "
                "commodity-specific economic models (Whittle, Gemcom, etc.)."
            ),
            "tonnage": (
                "NOT computed by TerraQuantum. Tonnage requires mine design, pit optimization, "
                "and geotechnical constraints outside geophysics scope."
            ),
            "why_zero": (
                "TerraQuantum inverts gravity/magnetic data and outputs density/susceptibility. "
                "Mining feasibility (grade, tonnage, NPV, LOM) requires integration with "
                "assay data, commodity prices, and mine engineering — domains external to geophysics."
            ),
        },
    }

    write_run_report_snapshot(params, report_payload)

    try:
        fav_result = compute_favorability_score(
            project_id=params.project_id,
            run_id=params.run_id,
            df_full=df_full,
            report_payload=report_payload,
            nx=params.nx,
            ny=params.ny,
            nz=params.nz,
            block_size=params.block_size,
        )
        report_payload["favorability"] = fav_result
        priority_class_val, priority_warnings = compute_priority_class_from_report(
            favorability_result=fav_result,
            technical_summary=technical_summary,
            uncertainty_diagnostics=uncertainty_diagnostics,
        )
        report_payload["priority_class"] = priority_class_val
        if priority_warnings:
            report_payload["priority_class_warnings"] = priority_warnings

        # R3.5-E: apply spatial readiness caps before persisting
        _sr_dict = (params.auto_params_metadata or {}).get("spatial_readiness")
        _apply_spatial_readiness_caps(report_payload, _sr_dict)

        # R3.5-G — promote spatial_readiness to report_payload top-level for stable report.json access
        if _sr_dict and "spatial_readiness" not in report_payload:
            report_payload["spatial_readiness"] = _sr_dict

        # R3.7-E — promote regional_scale_preflight to report_payload top-level
        _rsp_dict = (params.auto_params_metadata or {}).get("regional_scale_preflight")
        if _rsp_dict and "regional_scale_preflight" not in report_payload:
            report_payload["regional_scale_preflight"] = _rsp_dict
        _ack_regional = (params.auto_params_metadata or {}).get("acknowledge_regional_scale")
        if _ack_regional is not None and "acknowledge_regional_scale" not in report_payload:
            report_payload["acknowledge_regional_scale"] = _ack_regional

        fav_path = get_run_favorability_path(params.project_id, params.run_id)
        if fav_path:
            fav_path.write_text(
                json.dumps(
                    report_payload.get("favorability", fav_result),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        write_run_report_snapshot(params, report_payload)
    except Exception as exc:
        _log.warning("favorability_nonfatal", error=str(exc))

    # B3: veredicto de calidad RECONCILIADO (eslabón más débil). VA EN SU PROPIO try,
    # FUERA del bloque de favorabilidad: ese bloque falla a menudo (NaN de UQ), y el
    # veredicto honesto debe emitirse SIEMPRE. Para entonces report_payload ya tiene
    # confianza, confiabilidad, priority_class, r06 y best_target. Adjunta overall_verdict
    # y capa (downgrade-only) los campos individuales para que el payload no sostenga un
    # 'HIGH' contradicho por REMEDIATION/UNCLASSIFIED/blanco null-space.
    try:
        apply_reconciled_verdict(report_payload)
        write_run_report_snapshot(params, report_payload)
    except Exception as exc:
        _log.warning("reconciled_verdict_nonfatal", error=str(exc))

    _log.info(
        "inversion_done",
        total_voxels=len(df_full),
        anomaly_voxels=len(voxels),
        priority_class=report_payload.get("priority_class", PriorityClass.UNCLASSIFIED.value),
        preliminary_signal=report.get("preliminary_signal"),
    )

    _update(
        "done", 1.0, "exporting_mesh",
        "Inversión geofísica completada exitosamente.",
        metrics={
            "misfit_error_percent": misfit_error_percent,
            "total_voxels": total_voxels,
            "anomaly_voxels": len(voxels),
            "preliminary_signal": report.get("preliminary_signal"),
        },
    )

    # ── FASE 21: plan de fusión multimodal (cobertura del survey gravimétrico) ──
    try:
        _cov_x = float(qaqc_report.get("coverage_ratio_x", 1.0))
        _cov_z = float(qaqc_report.get("coverage_ratio_z", 1.0))
        _coverage_pct = max(0.0, min(1.0, _cov_x * _cov_z))
    except Exception:
        _coverage_pct = 1.0

    result = {
        "voxels": voxels,
        "run_id": params.run_id,
        "misfit_pct": misfit_error_percent,
        "best_target": best_target,
        "report": report_payload,
        "misfit_error_percent": misfit_error_percent,
    }
    return _attach_multimodal_plan(result, params, coverage_pct=_coverage_pct)


def run_geophysics_sensitivity_sweep(
    params: GeophysicsInvertInput,
    lambda_values: list[float] | None = None,
    alpha_values: list[float] | None = None,
    max_cases: int = 9,
) -> dict:
    validate_geophysics_input(params)

    if lambda_values is None:
        lambda_values = [params.lambda_mag * 0.5, params.lambda_mag, params.lambda_mag * 2.0]
    if alpha_values is None:
        alpha_values = [max(params.alpha_spatial * 0.5, 0.0), params.alpha_spatial, params.alpha_spatial * 2.0]

    if any(l < 0 for l in lambda_values):
        raise ValueError("lambda_values no puede tener valores negativos.")
    if any(a < 0 for a in alpha_values):
        raise ValueError("alpha_values no puede tener valores negativos.")

    max_cases = min(max_cases, 12)

    combinations = []
    for l in lambda_values:
        for a in alpha_values:
            combinations.append((l, a))
    
    combinations = combinations[:max_cases]
    case_count = len(combinations)

    nx = params.nx
    ny = params.ny
    nz = params.nz
    dx = params.block_size
    ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(params)
    sensor_coords, g_observed = build_sensor_arrays(params)

    forward = GravimetryForward(
        dx,
        dx,
        dx,
        cutoff_radius=params.cutoff_radius,
    )
    # kernel_sparse: solo para build_fit_diagnostics de cada caso. Solver usa F0.2 HPC.
    kernel_sparse = forward.build_sparse_kernel(
        x_c,
        y_c,
        z_c,
        sensor_coords,
    )

    if kernel_sparse.shape[0] != len(g_observed):
        raise RuntimeError("La matriz forward no coincide con la cantidad de observaciones.")

    inversor = GravimetryInversion(nx, ny, nz, dx)

    cases = []
    case_idx = 1
    for l_mag, a_spatial in combinations:
        est_density, _, case_misfit_percent, _ = inversor.solve_inversion_lsqr(
            g_observed,
            None,                   # kernel_sparse — HPC F0.2 exclusivo
            y_c=y_c,
            lambda_mag=l_mag,
            alpha_spatial=a_spatial,
            forward_model=forward,
            sensor_coords=sensor_coords,
            x_c=x_c,
            z_c=z_c,
            topography_elevations=None,
        )

        fd = build_fit_diagnostics(
            g_observed=g_observed,
            kernel_sparse=kernel_sparse,
            est_density=est_density,
            base_density=inversor.base_density,
            sensor_coords=None,
        )

        cases.append({
            "case_id": f"case_{case_idx}",
            "lambda_mag": l_mag,
            "alpha_spatial": a_spatial,
            "fit_level": fd.get("fit_level", "UNKNOWN"),
            "fit_quality": fd.get("fit_quality", 0.0),
            "normalized_rmse": fd.get("normalized_rmse", 0.0),
            "residual_rmse": fd.get("residual_rmse", 0.0),
            "residual_mae": fd.get("residual_mae", 0.0),
            "residual_bias": fd.get("residual_bias", 0.0),
            "residual_l2": fd.get("residual_l2", 0.0),
            "misfit_error_percent": round(float(case_misfit_percent), 2),
        })
        case_idx += 1

    cases.sort(key=lambda c: (c["normalized_rmse"], -c["fit_quality"], c["lambda_mag"]))

    best_case = cases[0] if cases else None

    warnings_list = []
    if case_count < 3:
        warnings_list.append("Sweep limitado: pocas combinaciones evaluadas.")
    
    if all(c["fit_level"] == "LOW" for c in cases):
        warnings_list.append("Todas las combinaciones evaluadas presentan ajuste débil.")
    
    if best_case and (best_case["lambda_mag"] != params.lambda_mag or best_case["alpha_spatial"] != params.alpha_spatial):
        warnings_list.append("Los parámetros actuales no son la mejor combinación del sweep.")

    recommendation = "No se evaluaron combinaciones."
    if best_case:
        lvl = best_case["fit_level"]
        if lvl == "GOOD":
            recommendation = "La combinación recomendada logra ajuste GOOD con el menor normalized_rmse."
        elif lvl == "MEDIUM":
            recommendation = "La mejor combinación logra ajuste MEDIUM; revisar cobertura o regularización antes de decisiones críticas."
        elif lvl == "LOW":
            recommendation = "Todas las combinaciones evaluadas tienen ajuste LOW; revisar datos de entrada y parametrización."

    return {
        "status": "done",
        "case_count": case_count,
        "best_case": best_case,
        "cases": cases,
        "recommendation": recommendation,
        "warnings": warnings_list
    }


def run_geophysics_live_update(req) -> dict:
    """
    FASE 8.2 — Live Update local (Woodbury rank-k / sub-octree), STATELESS sobre malla
    CORE. Incorpora un dato/sondaje nuevo a una solución YA invertida sin re-correr el
    pipeline: reconstruye el forward y la malla CORE desde req.params (que ya incluyen
    las observations existentes), y aplica la actualización LINEAL local del motor
    (gravimetry.live_update_add_data / live_update_suboctree) sobre req.prior_model.

    Diseño stateless: el cliente reenvía los params originales + el modelo previo (core,
    el que devolvió la inversión) + el dato nuevo / la sub-región. El servidor NO guarda
    estado. La actualización opera en la malla CORE (sin padding) — es una corrección
    local, no el solve global; honesto y suficiente para el bucle interactivo.

    ALCANCE HONESTO: actualización de la solución de mínimos cuadrados LINEAL con
    operadores congelados (mismos Wd/Ws/depth-weighting que la σ posterior); NO es un
    re-solve acotado desde cero (que recomputaría Ws/σ). Devuelve el modelo actualizado
    (core) + diagnósticos del update.
    """
    params = req.params
    nx, ny, nz = int(params.nx), int(params.ny), int(params.nz)
    dx = float(params.block_size)
    base_density = float(getattr(params, "base_density", 2.6))
    total_core = nx * ny * nz

    prior = np.asarray(req.prior_model, dtype=np.float64)
    if prior.shape[0] != total_core:
        raise HTTPException(
            status_code=422,
            detail=f"prior_model debe tener nx*ny*nz={total_core} elementos, tiene {prior.shape[0]}.",
        )
    # Air/NaN del modelo previo → tratadas como fondo (base_density) para el update local.
    prior = np.nan_to_num(prior, nan=base_density)

    # ── Malla CORE + forward + dato existente (mismos helpers que la inversión) ─
    mesh = build_tensor_mesh_with_padding(params)
    x_c = mesh["x_c_core"]
    y_c = mesh["y_c_core"]
    z_c = mesh["z_c_core"]
    sensor_coords, g_observed = build_sensor_arrays(params)
    forward = GravimetryForward(dx, dx, dx, cutoff_radius=params.cutoff_radius)
    inversor = GravimetryInversion(nx, ny, nz, dx, base_density=base_density)

    lambda_mag = max(float(getattr(params, "lambda_mag", 1e-3) or 1e-3), 1e-9)
    alpha_spatial = float(getattr(params, "alpha_spatial", 1.0))
    density_min = getattr(params, "density_min", None)
    density_max = getattr(params, "density_max", None)

    _new_sensors = None
    _new_g = None
    if req.new_observations:
        _new_sensors = np.array(
            [[o.x_m, o.y_m, o.z_m] for o in req.new_observations], dtype=float
        )
        _new_g = np.array([o.g for o in req.new_observations], dtype=float)

    if req.mode == "woodbury":
        if _new_sensors is None or _new_sensors.shape[0] == 0:
            raise HTTPException(
                status_code=422,
                detail="mode='woodbury' requiere al menos una observación en new_observations.",
            )
        out = inversor.live_update_add_data(
            prior, g_observed, y_c, forward, sensor_coords, x_c, z_c,
            new_sensor_coords=_new_sensors, new_g_observed=_new_g,
            lambda_mag=lambda_mag, alpha_spatial=alpha_spatial,
            density_min=density_min, density_max=density_max,
        )
        _model = np.nan_to_num(out["model"], nan=base_density)
        _log.info("live_update_woodbury_done", n_new=out["n_new"],
                  update_norm=round(float(out["update_norm"]), 6))
        return {
            "mode": "woodbury",
            "model": _model.tolist(),
            "n_voxels": int(_model.shape[0]),
            "update_norm": float(out["update_norm"]),
            "capacitance_cond": float(out["capacitance_cond"]),
            "new_data_misfit_before": float(out["new_data_misfit_before"]),
            "new_data_misfit_after": float(out["new_data_misfit_after"]),
            "n_new": int(out["n_new"]),
            "note": "Update Woodbury rango-k (lineal, A congelada) en malla core.",
        }

    # mode == "suboctree"
    if req.region_center is None or req.region_radius is None:
        raise HTTPException(
            status_code=422,
            detail="mode='suboctree' requiere region_center [x,y,z] y region_radius.",
        )
    out = inversor.live_update_suboctree(
        prior, g_observed, y_c, forward, sensor_coords, x_c, z_c,
        region_center=[float(c) for c in req.region_center],
        region_radius=float(req.region_radius),
        new_sensor_coords=_new_sensors, new_g_observed=_new_g,
        lambda_mag=lambda_mag, alpha_spatial=alpha_spatial,
        anchor_strength=float(req.anchor_strength),
        density_min=density_min, density_max=density_max,
    )
    _model = np.nan_to_num(out["model"], nan=base_density)
    _log.info("live_update_suboctree_done", region_size=out["region_size"],
              update_norm=round(float(out["update_norm"]), 6))
    return {
        "mode": "suboctree",
        "model": _model.tolist(),
        "n_voxels": int(_model.shape[0]),
        "update_norm": float(out["update_norm"]),
        "region_size": int(out["region_size"]),
        "region_misfit_before": float(out["region_misfit_before"]),
        "region_misfit_after": float(out["region_misfit_after"]),
        "note": "Re-solve local sub-octree (fondo congelado) en malla core.",
    }
