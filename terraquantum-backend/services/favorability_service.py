import json
import math
from typing import Any, Optional

import numpy as np
import polars as pl
from scipy.ndimage import label

from core.utils import utc_now_iso, safe_float
from services.block_model_store import (
    get_run_block_model_reference,
    get_run_focusing_reference,
    get_run_inputs_path,
    get_run_report_path,
)
from services.spectral_service import load_cached_spectral_indices


VERSION = "0.1"
DISCLAIMER = (
    "Este score indica qu\u00e9 zona re\u00fane m\u00e1s evidencia geof\u00edsica "
    "independiente para priorizaci\u00f3n exploratoria. NO confirma presencia "
    "de mineral econ\u00f3mico ni dep\u00f3sito viable."
)

FACTOR_WEIGHTS = {
    "anomaly_intensity": 0.25,
    "depth_accessibility": 0.20,
    "core_coherence": 0.25,
    "structural_gradient": 0.15,
    "msx_support": 0.10,
    "satellite_support": 0.05,
}


def compute_favorability_score(
    project_id: Optional[str],
    run_id: Optional[str],
    df_full: Optional[pl.DataFrame] = None,
    report_payload: Optional[dict] = None,
    nx: Optional[int] = None,
    ny: Optional[int] = None,
    nz: Optional[int] = None,
    block_size: Optional[float] = None,
) -> dict:
    if df_full is None:
        block_ref = get_run_block_model_reference(project_id, run_id)
        if not block_ref.path.exists():
            raise FileNotFoundError(f"Block model no encontrado: {block_ref.path}")
        df_full = pl.read_parquet(str(block_ref.path))

    if report_payload is None:
        report_path = get_run_report_path(project_id=project_id, run_id=run_id)
        report_payload = _read_json_file(report_path, "report")

    nx, ny, nz = _resolve_grid_shape(df_full, nx, ny, nz)
    block_size = _resolve_block_size(df_full, block_size)

    density_1d = _numeric_array(df_full, "density")
    ix_arr = _index_array(df_full, "ix")
    iy_arr = _index_array(df_full, "iy")
    iz_arr = _index_array(df_full, "iz")
    _validate_value_length(density_1d, ix_arr, "density")
    _validate_indices(ix_arr, iy_arr, iz_arr, nx, ny, nz)

    density_3d = np.zeros((nx, ny, nz), dtype=np.float64)
    density_3d[ix_arr, iy_arr, iz_arr] = density_1d

    factors = [
        _factor_anomaly_intensity(density_1d),
        _factor_depth_accessibility(df_full, density_1d, iy_arr, block_size),
        _factor_core_coherence(density_3d, density_1d),
        _factor_structural_gradient(density_3d, density_1d, block_size),
        _factor_msx_support(project_id, run_id, density_3d, density_1d, nx, ny, nz),
        _factor_satellite_support(project_id),
    ]

    quality_gate = _score_quality_gate(report_payload)
    uncertainty_gate = _score_uncertainty_gate(report_payload)
    scoring_detail = _aggregate_score(factors, quality_gate, uncertainty_gate)
    final_score = scoring_detail["final_score"]

    return {
        "version": VERSION,
        "score": final_score,
        "level": _score_level(final_score),
        "not_mineral_confirmation": True,
        "disclaimer": DISCLAIMER,
        "factors": factors,
        "gates": {
            "quality_gate": quality_gate,
            "uncertainty_gate": uncertainty_gate,
        },
        "scoring_detail": scoring_detail,
        "warnings": [],
        "computed_at": utc_now_iso(use_z_format=True),
    }


def compute_favorability_score_from_disk(project_id: str, run_id: str) -> dict:
    block_ref = get_run_block_model_reference(project_id=project_id, run_id=run_id)
    if not block_ref.path.exists():
        raise FileNotFoundError(f"Block model no encontrado: {block_ref.path}")

    inputs_path = get_run_inputs_path(project_id=project_id, run_id=run_id)
    report_path = get_run_report_path(project_id=project_id, run_id=run_id)
    inputs = _read_json_file(inputs_path, "inputs")
    report = _read_json_file(report_path, "report")

    df_full = pl.read_parquet(str(block_ref.path))
    return compute_favorability_score(
        project_id=project_id,
        run_id=run_id,
        df_full=df_full,
        report_payload=report,
        nx=int(_required_input_value(inputs, "nx")),
        ny=int(_required_input_value(inputs, "ny")),
        nz=int(_required_input_value(inputs, "nz")),
        block_size=float(_required_input_value(inputs, "block_size")),
    )


def _factor_anomaly_intensity(density_1d: np.ndarray) -> dict:
    density_1d = np.asarray(density_1d, dtype=np.float64)
    if density_1d.size == 0:
        score = 0.0
        robust_z = 0.0
    else:
        contrast = density_1d - np.median(density_1d)
        p95 = np.percentile(contrast, 95)
        median_c = np.median(contrast)
        mad = np.median(np.abs(contrast - median_c))
        robust_z = (p95 - median_c) / (1.4826 * mad + 1e-9)
        score = float(np.clip(robust_z / 3.0, 0.0, 1.0))

    return _factor(
        factor_id="anomaly_intensity",
        label="Intensidad de Anomal\u00eda",
        value=score,
        status="evaluated",
        explanation=(
            "P95 de contraste de densidad 3-MAD sobre la mediana de fondo "
            f"(robust_z={_round(robust_z, 3)})"
        ),
    )


def _factor_depth_accessibility(
    df: pl.DataFrame,
    density_1d: np.ndarray,
    iy_arr: Optional[np.ndarray] = None,
    block_size: Optional[float] = None,
) -> dict:
    density_1d = np.asarray(density_1d, dtype=np.float64)
    if density_1d.size == 0:
        depth_m = 0.0
    else:
        top10_mask = density_1d >= np.percentile(density_1d, 90)
        if "y" in df.columns:
            y_values = _numeric_array(df, "y")
        elif iy_arr is not None and block_size is not None:
            y_values = np.asarray(iy_arr, dtype=np.float64) * float(block_size)
            y_values = y_values + (float(block_size) / 2.0)
        else:
            raise ValueError("No se puede calcular profundidad sin columna y.")
        depth_m = float(np.mean(y_values[top10_mask])) if np.any(top10_mask) else 0.0

    score = _depth_score(depth_m)
    return _factor(
        factor_id="depth_accessibility",
        label="Accesibilidad de Profundidad",
        value=score,
        status="evaluated",
        explanation=(
            f"Centroide an\u00f3malo a {_round(depth_m, 1)}m "
            "seg\u00fan top 10% por densidad"
        ),
    )


def _depth_score(depth_m: float) -> float:
    d = float(depth_m)
    if d <= 50:
        return 0.65
    if d <= 500:
        return 1.00
    if d <= 1200:
        return 0.85
    if d <= 2500:
        return 0.55
    if d <= 4000:
        return 0.25
    return 0.05


def _factor_core_coherence(density_3d: np.ndarray, density_1d: np.ndarray) -> dict:
    density_1d = np.asarray(density_1d, dtype=np.float64)
    if density_1d.size == 0:
        score = 0.0
        main_ratio = 0.0
    else:
        threshold = np.percentile(density_1d, 90)
        binary_mask = np.asarray(density_3d, dtype=np.float64) >= threshold
        labeled, n_components = label(binary_mask)
        if n_components == 0:
            score = 0.0
            main_ratio = 0.0
        else:
            comp_sizes = np.bincount(labeled.ravel())[1:]
            vol_main = int(comp_sizes.max())
            vol_total = int(binary_mask.sum())
            main_ratio = vol_main / max(vol_total, 1)
            score = float(main_ratio)

    return _factor(
        factor_id="core_coherence",
        label="Coherencia del N\u00facleo",
        value=score,
        status="evaluated",
        explanation=(
            "El componente conexo principal ocupa "
            f"{_round(main_ratio * 100.0, 1)}% del volumen an\u00f3malo (top 10%)"
        ),
    )


def _factor_structural_gradient(
    density_3d: np.ndarray,
    density_1d: np.ndarray,
    block_size: float,
) -> dict:
    dx = float(block_size)
    if min(np.asarray(density_3d).shape) < 2 or dx <= 0:
        score = 0.0
    else:
        grad_x, grad_y, grad_z = np.gradient(density_3d, dx, dx, dx)
        grad_mag = np.sqrt(grad_x**2 + grad_y**2 + grad_z**2)
        p90_grad = float(np.percentile(grad_mag, 90))
        density_range = float(np.max(density_1d) - np.min(density_1d))
        max_grad_ref = density_range / dx
        score = float(np.clip(p90_grad / (max_grad_ref + 1e-9), 0.0, 1.0))

    return _factor(
        factor_id="structural_gradient",
        label="Gradiente Estructural",
        value=score,
        status="evaluated",
        explanation="P90 de magnitud de gradiente 3D normalizado por rango m\u00e1ximo te\u00f3rico",
    )


def _factor_msx_support(
    project_id: Optional[str],
    run_id: Optional[str],
    density_3d: np.ndarray,
    density_1d: np.ndarray,
    nx: int,
    ny: int,
    nz: int,
) -> dict:
    focusing_ref = get_run_focusing_reference(project_id=project_id, run_id=run_id)
    if not focusing_ref.path.exists():
        return _factor(
            factor_id="msx_support",
            label="Soporte MS-x",
            value=None,
            status="not_evaluated",
            explanation="MS-x no disponible para esta corrida.",
        )

    df_msx = pl.read_parquet(str(focusing_ref.path))
    required = {"ix", "iy", "iz", "msx_score"}
    if not required.issubset(set(df_msx.columns)):
        return _factor(
            factor_id="msx_support",
            label="Soporte MS-x",
            value=None,
            status="not_evaluated",
            explanation="Archivo MS-x sin columnas requeridas.",
        )

    ix_m = _index_array(df_msx, "ix")
    iy_m = _index_array(df_msx, "iy")
    iz_m = _index_array(df_msx, "iz")
    _validate_indices(ix_m, iy_m, iz_m, nx, ny, nz)

    msx_3d = np.zeros((nx, ny, nz), dtype=np.float64)
    msx_values = _numeric_array(df_msx, "msx_score")
    _validate_value_length(msx_values, ix_m, "msx_score")
    msx_3d[ix_m, iy_m, iz_m] = msx_values

    lsqr_mask = density_3d >= np.percentile(density_1d, 90)
    positive_msx = msx_3d[msx_3d > 0]
    if msx_3d.max() > 0 and positive_msx.size > 0:
        msx_mask = msx_3d >= np.percentile(positive_msx, 90)
    else:
        msx_mask = np.zeros_like(lsqr_mask, dtype=bool)

    union = int((lsqr_mask | msx_mask).sum())
    overlap = int((lsqr_mask & msx_mask).sum())
    score = float(overlap / max(union, 1))

    return _factor(
        factor_id="msx_support",
        label="Soporte MS-x",
        value=score,
        status="evaluated",
        explanation=(
            "Overlap Jaccard del "
            f"{_round(score * 100.0, 1)}% entre n\u00facleo LSQR y n\u00facleo MS-x"
        ),
    )


def _factor_satellite_support(project_id: Optional[str]) -> dict:
    cached = load_cached_spectral_indices(project_id)
    if not cached:
        return _factor(
            factor_id="satellite_support",
            label="Soporte Satelital",
            value=None,
            status="not_evaluated",
            explanation=(
                "Sin cache de indices espectrales. No se recalcula GEE desde "
                "favorabilidad."
            ),
        )

    spectral = cached.get("spectral_indices") if isinstance(cached, dict) else None
    if not isinstance(spectral, dict) or spectral.get("status") != "evaluated":
        status = spectral.get("status") if isinstance(spectral, dict) else "invalid_cache"
        return _factor(
            factor_id="satellite_support",
            label="Soporte Satelital",
            value=None,
            status="not_evaluated",
            explanation=(
                f"Indices espectrales no evaluados (status={status}). "
                "Soporte satelital superficial no usado."
            ),
        )

    surface_support = spectral.get("surface_support_score") or {}
    if not isinstance(surface_support, dict):
        surface_support = {}

    value = surface_support.get("value")
    support_status = surface_support.get("status")
    if support_status != "evaluated" or value is None:
        return _factor(
            factor_id="satellite_support",
            label="Soporte Satelital",
            value=None,
            status="not_evaluated",
            explanation=(
                "Cache espectral existe, pero el soporte superficial no esta "
                "evaluado."
            ),
        )

    clean_value = safe_float(value, fallback=-1.0)
    if clean_value < 0:
        return _factor(
            factor_id="satellite_support",
            label="Soporte Satelital",
            value=None,
            status="not_evaluated",
            explanation="Cache espectral contiene valor invalido.",
        )

    return _factor(
        factor_id="satellite_support",
        label="Soporte Satelital",
        value=clean_value,
        status="evaluated",
        explanation=(
            "Soporte satelital superficial desde proxies Sentinel-2 "
            "(oxidos de hierro, arcillas/OH, NDVI y calidad de pixeles). "
            "Es evidencia exploratoria; no confirma mineralizacion ni "
            "deposito economico."
        ),
    )


def _score_quality_gate(report_payload: Optional[dict]) -> dict:
    report_payload = report_payload or {}
    technical_summary = report_payload.get("technicalSummary") or {}
    uncertainty = _extract_uncertainty_score(report_payload)
    overall_level = str(technical_summary.get("overall_level", "LOW")).upper()

    if overall_level == "GOOD":
        label_value = "BUENA"
        multiplier = 1.00
        cap = None
    elif overall_level == "MEDIUM":
        label_value = "ACEPTABLE"
        multiplier = 0.85
        cap = None
    elif uncertainty < 0.50:
        label_value = "REVISAR"
        multiplier = 0.60
        cap = 60.0
    else:
        label_value = "MALA"
        multiplier = 0.35
        cap = 40.0

    return {
        "label": label_value,
        "multiplier": multiplier,
        "source": f"technicalSummary.overall_level = {overall_level}",
        "cap": cap,
    }


def _score_uncertainty_gate(report_payload: Optional[dict]) -> dict:
    uncertainty_score = _extract_uncertainty_score(report_payload)
    uncertainty_score = float(np.clip(uncertainty_score, 0.0, 1.0))
    multiplier = 1.0 - (uncertainty_score * 0.5)

    return {
        "score": _round(uncertainty_score, 3),
        "multiplier": _round(multiplier, 3),
        "source": "uncertaintyDiagnostics.uncertainty_score",
    }


def _aggregate_score(
    factors: list[dict],
    quality_gate: dict,
    uncertainty_gate: dict,
) -> dict:
    evaluated_factors = [
        f for f in factors
        if f.get("status") == "evaluated" and f.get("value") is not None
    ]
    numerator = sum(float(f["value"]) * float(f["weight"]) for f in evaluated_factors)
    denom = sum(float(f["weight"]) for f in evaluated_factors)
    weighted_evidence_score = numerator / denom if denom > 0 else 0.0

    raw_score = (
        100.0
        * weighted_evidence_score
        * float(quality_gate["multiplier"])
        * float(uncertainty_gate["multiplier"])
    )
    cap = quality_gate["cap"] if quality_gate.get("cap") is not None else 100.0
    final_score = float(np.clip(raw_score, 0.0, float(cap)))
    final_score = _round(final_score, 1)

    return {
        "weighted_evidence_score": _round(weighted_evidence_score, 3),
        "evaluated_weight_sum": _round(denom, 3),
        "raw_score_before_cap": _round(raw_score, 3),
        "final_score": final_score,
    }


def _factor(
    factor_id: str,
    label: str,
    value: Optional[float],
    status: str,
    explanation: str,
) -> dict:
    weight = FACTOR_WEIGHTS[factor_id]
    clean_value = None if value is None else float(np.clip(value, 0.0, 1.0))
    points = 0.0 if clean_value is None else clean_value * weight * 100.0

    return {
        "id": factor_id,
        "label": label,
        "weight": weight,
        "value": None if clean_value is None else _round(clean_value, 3),
        "points": _round(points, 3),
        "status": status,
        "explanation": explanation,
    }


def _score_level(score: float) -> str:
    if score < 25:
        return "MUY BAJO"
    if score < 50:
        return "BAJO"
    if score < 65:
        return "MODERADO"
    if score < 80:
        return "ALTO"
    return "MUY ALTO"


def _extract_uncertainty_score(report_payload: Optional[dict]) -> float:
    diagnostics = (report_payload or {}).get("uncertaintyDiagnostics") or {}
    return safe_float(diagnostics.get("uncertainty_score"), 0.0)


def _resolve_grid_shape(
    df: pl.DataFrame,
    nx: Optional[int],
    ny: Optional[int],
    nz: Optional[int],
) -> tuple[int, int, int]:
    if nx is None:
        nx = int(df["ix"].max()) + 1
    if ny is None:
        ny = int(df["iy"].max()) + 1
    if nz is None:
        nz = int(df["iz"].max()) + 1

    shape = (int(nx), int(ny), int(nz))
    if any(dim <= 0 for dim in shape):
        raise ValueError(f"Grilla invalida para favorabilidad: {shape}")

    return shape


def _resolve_block_size(df: pl.DataFrame, block_size: Optional[float]) -> float:
    if block_size is not None:
        resolved = float(block_size)
    else:
        resolved = _infer_block_size(df)

    if resolved <= 0 or not math.isfinite(resolved):
        raise ValueError("block_size invalido para favorabilidad.")

    return resolved


def _infer_block_size(df: pl.DataFrame) -> float:
    for col in ("x", "y", "z"):
        if col not in df.columns:
            continue
        unique_vals = np.sort(np.unique(_numeric_array(df, col)))
        if unique_vals.size < 2:
            continue
        diffs = np.diff(unique_vals)
        positive = diffs[diffs > 0]
        if positive.size > 0:
            return float(positive.min())
    return 1.0


def _numeric_array(df: pl.DataFrame, column: str) -> np.ndarray:
    if column not in df.columns:
        raise ValueError(f"Columna requerida ausente: {column}")
    values = np.asarray(df[column].to_numpy(), dtype=np.float64)
    if values.size == 0:
        raise ValueError(f"Columna requerida vacia: {column}")
    if not np.isfinite(values).all():
        raise ValueError(f"Columna requerida contiene valores no finitos: {column}")
    return values


def _index_array(df: pl.DataFrame, column: str) -> np.ndarray:
    values = _numeric_array(df, column)
    return values.astype(int)


def _validate_indices(
    ix_arr: np.ndarray,
    iy_arr: np.ndarray,
    iz_arr: np.ndarray,
    nx: int,
    ny: int,
    nz: int,
) -> None:
    if not (
        len(ix_arr) == len(iy_arr) == len(iz_arr)
    ):
        raise ValueError("Indices ix/iy/iz con largos inconsistentes.")

    invalid = (
        (ix_arr < 0)
        | (ix_arr >= nx)
        | (iy_arr < 0)
        | (iy_arr >= ny)
        | (iz_arr < 0)
        | (iz_arr >= nz)
    )
    if bool(np.any(invalid)):
        raise ValueError("Block model contiene indices fuera de la grilla.")


def _validate_value_length(values: np.ndarray, ix_arr: np.ndarray, label_name: str) -> None:
    if len(values) != len(ix_arr):
        raise ValueError(
            f"Columna {label_name} no coincide con la cantidad de indices."
        )


def _read_json_file(path: Any, label_name: str) -> dict:
    if path is None or not path.exists():
        raise FileNotFoundError(f"Archivo {label_name} no encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Archivo {label_name} debe contener un objeto JSON.")
    return data


def _required_input_value(inputs: dict, key: str) -> Any:
    if key not in inputs:
        raise ValueError(f"inputs.json no contiene {key}.")
    return inputs[key]


def _round(value: float, digits: int) -> float:
    return round(float(value), digits)