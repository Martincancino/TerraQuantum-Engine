import json
import math
from typing import Any

import polars as pl

from core.block_model_store import (
    get_run_block_model_reference,
    get_run_inputs_path,
    get_run_report_path,
)
from core.logging import get_logger
from services.block_model_service import get_index_columns

_log = get_logger(__name__)

_DISCLAIMER = (
    "Esta clasificación es conceptual y se basa en proxies heurísticos derivados de la "
    "inversión gravimétrica. No reemplaza un estudio de factibilidad, análisis geotécnico "
    "profesional, muestreo real ni evaluación económica bancable."
)

_NEEDS_MORE_DATA = {
    "recommendation": "needs_more_data",
    "confidence": 0.0,
    "level": "conceptual",
    "rationale": {
        "depth_m": 0.0,
        "strip_ratio_estimate": 0.0,
        "tonnage_estimate_kt": 0.0,
        "geometry": "unknown",
        "aspect_ratio": 0.0,
        "uncertainty_flag": "high",
        "avg_grade_proxy": 0.0,
        "ore_blocks": 0,
        "total_blocks": 0,
        "key_factors": [],
    },
    "disclaimer": _DISCLAIMER,
}


def _needs_more_data_with_error(error_msg: str) -> dict:
    result = dict(_NEEDS_MORE_DATA)
    rationale = dict(result["rationale"])
    rationale["error"] = error_msg
    result["rationale"] = rationale
    return result


def _read_json_file(path) -> dict:
    if not path or not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return data if isinstance(data, dict) else {}


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback

    return parsed if math.isfinite(parsed) else fallback


def evaluate_mine_method(project_id: str, run_id: str) -> dict:
    _log.info("evaluate_mine_method_start", project_id=project_id, run_id=run_id)

    try:
        block_ref = get_run_block_model_reference(
            project_id=project_id,
            run_id=run_id,
        )
        parquet_path = str(block_ref.path)
    except Exception as exc:
        _log.warning("mine_method_block_ref_error", error=str(exc))
        return _needs_more_data_with_error(f"No se pudo resolver el block model: {exc}")

    try:
        df = pl.read_parquet(parquet_path)
    except Exception as exc:
        _log.warning("mine_method_parquet_read_error", error=str(exc))
        return _needs_more_data_with_error(f"No se pudo leer el block model: {exc}")

    if len(df) == 0:
        return _needs_more_data_with_error("El block model está vacío.")

    report: dict = {}
    try:
        report_path = get_run_report_path(project_id=project_id, run_id=run_id)
        report = _read_json_file(report_path)
    except Exception as exc:
        _log.warning("mine_method_report_read_error", error=str(exc))

    inputs: dict = {}
    try:
        inputs_path = get_run_inputs_path(project_id=project_id, run_id=run_id)
        inputs = _read_json_file(inputs_path)
    except Exception as exc:
        _log.warning("mine_method_inputs_read_error", error=str(exc))

    total_blocks = len(df)
    ore_df = df.filter(pl.col("domain") == 1) if "domain" in df.columns else pl.DataFrame()

    if len(ore_df) == 0 and "density" in df.columns:
        density_threshold = df["density"].quantile(0.80)
        if density_threshold is not None:
            ore_df = df.filter(pl.col("density") >= density_threshold)

    ore_blocks = len(ore_df)

    if ore_blocks == 0:
        return _needs_more_data_with_error(
            "No se detectaron bloques anómalos en el block model."
        )

    has_xyz = {"x", "y", "z"}.issubset(set(ore_df.columns))

    if has_xyz:
        depth_m = _safe_float(ore_df["y"].max())
        x_range = _safe_float(ore_df["x"].max() - ore_df["x"].min()) + 1.0
        z_range = _safe_float(ore_df["z"].max() - ore_df["z"].min()) + 1.0
        y_range = _safe_float(ore_df["y"].max() - ore_df["y"].min()) + 1.0
    else:
        try:
            ix_col, iy_col, iz_col = get_index_columns(ore_df)
        except ValueError:
            return _needs_more_data_with_error(
                "El block model no tiene columnas espaciales ni de índice reconocibles."
            )

        block_size_m = _safe_float(inputs.get("block_size"), 1.0)
        depth_m = _safe_float(ore_df[iy_col].max()) * block_size_m
        x_range = (_safe_float(ore_df[ix_col].max() - ore_df[ix_col].min()) + 1.0) * block_size_m
        z_range = (_safe_float(ore_df[iz_col].max() - ore_df[iz_col].min()) + 1.0) * block_size_m
        y_range = (_safe_float(ore_df[iy_col].max() - ore_df[iy_col].min()) + 1.0) * block_size_m

    horizontal_extent = math.sqrt(x_range * z_range)
    aspect_ratio = horizontal_extent / max(y_range, 1.0)

    if aspect_ratio > 1.5:
        geometry_type = "massive"
    elif aspect_ratio > 0.7:
        geometry_type = "intermediate"
    else:
        geometry_type = "narrow_deep"

    tonnage_kt = (
        _safe_float(ore_df["tonnage"].sum()) / 1000.0
        if "tonnage" in ore_df.columns
        else 0.0
    )
    avg_grade_proxy = (
        _safe_float(ore_df["grade"].mean())
        if "grade" in ore_df.columns
        else 0.0
    )

    waste_blocks = total_blocks - ore_blocks
    strip_ratio = float(waste_blocks) / float(ore_blocks) if ore_blocks > 0 else 99.0

    tech_summary = report.get("technicalSummary", {}) if isinstance(report, dict) else {}
    overall_level = (
        tech_summary.get("overall_level", "POOR")
        if isinstance(tech_summary, dict)
        else "POOR"
    )
    uncertainty_flag = {"GOOD": "low", "MEDIUM": "medium"}.get(overall_level, "high")

    score_open_pit = 0.0
    score_underground = 0.0
    key_factors: list[str] = []

    if depth_m < 150:
        score_open_pit += 0.40
        key_factors.append("shallow_depth")
    elif depth_m < 300:
        score_open_pit += 0.25
        score_underground += 0.10
        key_factors.append("intermediate_depth")
    elif depth_m < 450:
        score_open_pit += 0.10
        score_underground += 0.25
        key_factors.append("intermediate_depth")
    else:
        score_underground += 0.40
        key_factors.append("deep_deposit")

    if strip_ratio < 4.0:
        score_open_pit += 0.30
        key_factors.append("strip_ratio_favorable")
    elif strip_ratio < 8.0:
        score_open_pit += 0.15
        score_underground += 0.05
    else:
        score_underground += 0.30
        key_factors.append("high_strip_ratio")

    if geometry_type == "massive":
        score_open_pit += 0.20
        key_factors.append("massive_geometry")
    elif geometry_type == "narrow_deep":
        score_underground += 0.20
        key_factors.append("narrow_geometry")
    else:
        score_open_pit += 0.10
        score_underground += 0.10

    if tonnage_kt > 20_000:
        score_open_pit += 0.10
        key_factors.append("large_tonnage")
    elif tonnage_kt < 1_000:
        score_underground += 0.10
        key_factors.append("small_tonnage")

    if uncertainty_flag == "high":
        score_open_pit *= 0.60
        score_underground *= 0.60
        key_factors.append("high_uncertainty_penalty")
    elif uncertainty_flag == "medium":
        score_open_pit *= 0.85
        score_underground *= 0.85

    max_score = max(score_open_pit, score_underground)
    threshold = 0.30

    if max_score < threshold:
        recommendation = "needs_more_data"
    elif score_open_pit >= score_underground:
        recommendation = "open_pit"
    else:
        recommendation = "underground"

    confidence = round(max_score, 3)

    _log.info(
        "evaluate_mine_method_done",
        recommendation=recommendation,
        confidence=confidence,
        depth_m=round(depth_m, 1),
        strip_ratio=round(strip_ratio, 2),
        geometry=geometry_type,
        uncertainty_flag=uncertainty_flag,
    )

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "level": "conceptual",
        "rationale": {
            "depth_m": round(depth_m, 1),
            "strip_ratio_estimate": round(strip_ratio, 2),
            "tonnage_estimate_kt": round(tonnage_kt, 1),
            "geometry": geometry_type,
            "aspect_ratio": round(aspect_ratio, 2),
            "uncertainty_flag": uncertainty_flag,
            "avg_grade_proxy": round(avg_grade_proxy, 3),
            "ore_blocks": ore_blocks,
            "total_blocks": total_blocks,
            "key_factors": key_factors,
        },
        "disclaimer": _DISCLAIMER,
    }
