import io
import logging
import math

import polars as pl

from core.block_model_store import resolve_block_model_reference
from core.config import RUN_ANOMALY_FILENAME
from core.utils import sanitize_nan_value, sanitize_nan

logger = logging.getLogger(__name__)

# Mode "economic" eliminado (2026-06-10): sin módulos de economía minera.
SUPPORTED_BLOCK_MODEL_MODES = {"exploration", "full", "anomaly", "doi_reliable", "profile"}
PERFORMANCE_WARNING_VOXEL_THRESHOLD = 200_000
DIAGNOSTIC_PERCENTILES = (
    ("p2", 0.02),
    ("p5", 0.05),
    ("p50", 0.50),
    ("p85", 0.85),
    ("p90", 0.90),
    ("p95", 0.95),
    ("p98", 0.98),
)
DEGENERATE_RANGE_EPSILON = 1e-9

_PERCENTILE_STAT_FIELDS = ("density", "visual_score", "relative_target_score")
_NUMERIC_POLARS_DTYPES = frozenset({
    pl.Float32, pl.Float64,
    pl.Int8, pl.Int16, pl.Int32, pl.Int64,
    pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
})
_PERCENTILE_EPSILON = 1e-6

# Columnas R3 de elevación/georef que pueden estar en el parquet post-enriquecimiento
_R3_CELL_COLS = (
    "lat",
    "lon",
    "surface_elevation_masl",
    "depth_below_surface_m",
    "voxel_elevation_masl",
    "georef_confidence",
    "dem_source",
    "dem_sample_method",
    "spatial_reference_warning",
)


def normalize_block_model_mode(mode: str) -> tuple[str, list[str]]:
    mode_clean = str(mode or "exploration").lower().strip()
    warnings: list[str] = []

    if mode_clean not in SUPPORTED_BLOCK_MODEL_MODES:
        warnings.append(
            f"unsupported block model mode '{mode_clean}'; using exploration."
        )
        return "exploration", warnings

    return mode_clean, warnings


def get_index_columns(df: pl.DataFrame):
    columns = set(df.columns)

    if {"ix", "iy", "iz"}.issubset(columns):
        return "ix", "iy", "iz"

    if {"x", "y", "z"}.issubset(columns):
        return "x", "y", "z"

    raise ValueError("El block model no tiene columnas ix/iy/iz ni x/y/z.")


def ensure_visual_columns(df: pl.DataFrame) -> pl.DataFrame:
    _density_degraded = False

    if "density" not in df.columns:
        if "rho" in df.columns:
            df = df.with_columns(pl.col("rho").alias("density"))
        elif "density_t_m3" in df.columns:
            # Joint schema: density_t_m3 is the absolute density — use it as the canonical density column.
            df = df.with_columns(pl.col("density_t_m3").alias("density"))
        else:
            # Sin densidad real: emitir null en vez de inventar 2.6 t/m³.
            df = df.with_columns(pl.lit(None).cast(pl.Float64).alias("density"))
            _density_degraded = True

    if "rho" not in df.columns:
        df = df.with_columns(pl.col("density").alias("rho"))

    if "probability" not in df.columns:
        # Sin score real: emitir null en vez de inventar 100% de probabilidad.
        df = df.with_columns(pl.lit(None).cast(pl.Float64).alias("probability"))

    if "visual_score" not in df.columns:
        density_min_val = df["density"].min()
        density_max_val = df["density"].max()
        if density_min_val is None or density_max_val is None:
            # Densidad degenerada (toda null): no inventar visual_score.
            df = df.with_columns(pl.lit(None).cast(pl.Float64).alias("visual_score"))
        else:
            density_min = float(density_min_val)
            density_max = float(density_max_val)
            density_range = max(density_max - density_min, 1e-9)
            df = df.with_columns(
                (
                    ((pl.col("density") - density_min) / density_range)
                    * pl.col("probability").fill_null(0.0).clip(0.0, 1.0)
                ).alias("visual_score")
            )

    if "degraded" not in df.columns:
        df = df.with_columns(pl.lit(_density_degraded).alias("degraded"))

    if "grade" not in df.columns:
        df = df.with_columns(pl.lit(0.0).alias("grade"))

    if "domain" not in df.columns:
        df = df.with_columns(pl.lit(0).alias("domain"))

    if "tonnage" not in df.columns:
        df = df.with_columns(pl.lit(0.0).alias("tonnage"))

    return df


def infer_cell_size(df: pl.DataFrame) -> float:
    """Infiere cell_size desde diferencias positivas entre coordenadas unicas."""
    for col in ("x", "y", "z"):
        if col not in df.columns:
            continue
        unique_vals = df[col].drop_nulls().unique().sort().to_numpy()
        if len(unique_vals) < 2:
            continue
        diffs = unique_vals[1:] - unique_vals[:-1]
        positive_diffs = diffs[diffs > 0]
        if len(positive_diffs) == 0:
            continue
        return float(positive_diffs.min())
    return 10.0


def read_numeric_row_value(row: dict, key: str, fallback=None):
    value = row.get(key)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    if fallback is None:
        return None
    return float(fallback)


def round_stat(value: float | None) -> float | None:
    if value is None:
        return None

    try:
        fval = float(value)
        if not math.isfinite(fval):
            return None
        rounded = round(fval, 6)
        return 0.0 if rounded == 0 else rounded
    except (ValueError, TypeError, OverflowError):
        return None


def empty_numeric_distribution_stats(column: str) -> dict:
    return {
        "column": column,
        "count": 0,
        "min": None,
        "max": None,
        **{name: None for name, _ in DIAGNOSTIC_PERCENTILES},
        "isDegenerate": True,
        "is_degenerate": True,
    }


def numeric_distribution_stats(df: pl.DataFrame, column: str) -> dict:
    if column not in df.columns or len(df) == 0:
        return empty_numeric_distribution_stats(column)

    values = [
        float(value)
        for value in df[column].drop_nulls()
        if _is_finite_number(value)
    ]

    if len(values) == 0:
        return empty_numeric_distribution_stats(column)

    series = pl.Series(values)
    min_value = float(series.min())
    max_value = float(series.max())
    value_range = max_value - min_value
    percentiles = {}

    for name, q in DIAGNOSTIC_PERCENTILES:
        percentiles[name] = round_stat(
            float(series.quantile(q, interpolation="linear"))
        )

    return {
        "column": column,
        "count": len(values),
        "min": round_stat(min_value),
        "max": round_stat(max_value),
        **percentiles,
        "isDegenerate": value_range <= DEGENERATE_RANGE_EPSILON,
        "is_degenerate": value_range <= DEGENERATE_RANGE_EPSILON,
    }


def build_diagnostic_stats(df: pl.DataFrame, prefix: str = "") -> dict:
    def key(name: str) -> str:
        parts = name.split("_")
        camel = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])

        return f"{prefix}{camel[0].upper()}{camel[1:]}" if prefix else camel

    stats = {}

    for column in ("density", "rho", "probability", "visual_score"):
        distribution = numeric_distribution_stats(df, column)
        stats[key(f"{column}_min")] = distribution["min"]
        stats[key(f"{column}_max")] = distribution["max"]
        stats[key(f"{column}_count")] = distribution["count"]
        stats[key(f"{column}_is_degenerate")] = distribution["isDegenerate"]

        for percentile_name, _ in DIAGNOSTIC_PERCENTILES:
            stats[key(f"{column}_{percentile_name}")] = distribution[
                percentile_name
            ]

    return stats


def compute_percentile_stats(df: pl.DataFrame) -> dict:
    """Estadísticas percentiles profesionales sobre el DataFrame COMPLETO (antes del sampling)."""
    result: dict = {}
    is_degenerate = False
    degenerate_reason: str | None = None
    computed_fields: list[str] = []

    try:
        for field in _PERCENTILE_STAT_FIELDS:
            if field not in df.columns:
                continue
            if df[field].dtype not in _NUMERIC_POLARS_DTYPES:
                continue
            values = df[field].drop_nulls()
            if len(values) == 0:
                continue
            for label, q in (
                ("p2", 0.02), ("p5", 0.05), ("p50", 0.50),
                ("p85", 0.85), ("p90", 0.90), ("p95", 0.95), ("p98", 0.98),
            ):
                try:
                    try:
                        raw = values.quantile(q, interpolation="linear")
                    except TypeError:
                        raw = values.quantile(q)
                    result[f"{field}_{label}"] = float(raw) if raw is not None else None
                except Exception:
                    result[f"{field}_{label}"] = None
            computed_fields.append(field)

        density_p2 = result.get("density_p2")
        density_p98 = result.get("density_p98")
        vs_p2 = result.get("visual_score_p2")
        vs_p98 = result.get("visual_score_p98")

        if density_p2 is None or density_p98 is None:
            is_degenerate = True
            degenerate_reason = "computation_failed"
        elif abs(density_p98 - density_p2) < _PERCENTILE_EPSILON:
            is_degenerate = True
            degenerate_reason = "uniform_density"
        elif (
            vs_p2 is not None
            and vs_p98 is not None
            and abs(vs_p98 - vs_p2) < _PERCENTILE_EPSILON
        ):
            is_degenerate = True
            degenerate_reason = "uniform_visual_score"

        result["is_degenerate"] = is_degenerate
        if degenerate_reason:
            result["degenerate_reason"] = degenerate_reason

        if is_degenerate:
            result["professional_threshold"] = None
            result["professional_high_threshold"] = None
            result["professional_extreme_threshold"] = None
        else:
            result["professional_threshold"] = result.get("visual_score_p85")
            result["professional_high_threshold"] = result.get("visual_score_p95")
            result["professional_extreme_threshold"] = result.get("visual_score_p98")

        logger.debug(
            "Percentile stats: is_degenerate=%s, fields=%s, n=%d",
            is_degenerate,
            computed_fields,
            len(df),
        )

    except Exception:
        return {}

    return result


def build_distribution_metadata(df: pl.DataFrame) -> dict:
    diagnostic_stats = {
        column: numeric_distribution_stats(df, column)
        for column in ("density", "rho", "probability", "visual_score")
    }
    visual_score_stats = diagnostic_stats["visual_score"]

    return {
        "diagnosticStats": diagnostic_stats,
        "densityStats": diagnostic_stats["density"],
        "rhoStats": diagnostic_stats["rho"],
        "probabilityStats": diagnostic_stats["probability"],
        "visualScoreStats": visual_score_stats,
        "scoreStats": visual_score_stats,
        "isDegenerate": visual_score_stats["isDegenerate"],
        "is_degenerate": visual_score_stats["is_degenerate"],
    }


def count_parquet_rows_or_none(parquet_path) -> int | None:
    if not parquet_path.exists():
        return None

    try:
        return int(pl.read_parquet(str(parquet_path)).height)
    except Exception as exc:
        print(f"[BLOCK-MODEL-SERVICE] No se pudo contar {parquet_path}: {exc}")
        return None


def build_voxel_trace_metadata(
    mode: str,
    total_voxels: int | None,
    stored_voxels: int | None,
    anomaly_voxels: int | None,
    returned_voxels: int,
) -> dict:
    return {
        "total_voxels": total_voxels,
        "stored_voxels": stored_voxels,
        "anomaly_voxels": anomaly_voxels,
        "returned_voxels": returned_voxels,
        "mode": mode,
    }


def add_selection_rank(df: pl.DataFrame, sort_column: str, rank_column: str) -> pl.DataFrame:
    return (
        df.sort(sort_column, descending=True)
        .with_row_index(rank_column)
        .with_columns(pl.col(rank_column).cast(pl.Int64))
    )


def select_limited_exploration_view(
    df: pl.DataFrame,
    limit: int,
    index_columns: tuple[str, str, str],
) -> pl.DataFrame:
    if limit <= 0:
        return df.head(0)

    if len(df) <= limit:
        return df

    anomaly_quota = max(1, int(limit * 0.45))
    density_quota = max(1, int(limit * 0.30))
    probability_quota = max(1, int(limit * 0.15))
    remainder_quota = max(0, limit - anomaly_quota - density_quota - probability_quota)

    anomaly_view = df.sort("visual_score", descending=True).head(anomaly_quota)
    density_view = df.sort("density", descending=True).head(density_quota)
    probability_view = df.sort("probability", descending=True).head(probability_quota)

    density_ranked = add_selection_rank(df, "density", "_density_rank")
    stride = max(len(df) // max(remainder_quota, 1), 1)
    distribution_view = (
        density_ranked
        .filter((pl.col("_density_rank") % stride) == 0)
        .head(remainder_quota)
        .drop("_density_rank")
        if remainder_quota > 0
        else df.head(0)
    )

    selected = pl.concat(
        [anomaly_view, density_view, probability_view, distribution_view],
        how="diagonal",
    ).unique(subset=list(index_columns), keep="first", maintain_order=True)

    if len(selected) < limit:
        missing = limit - len(selected)
        selected = pl.concat(
            [selected, df.sort("visual_score", descending=True).head(limit + missing)],
            how="diagonal",
        ).unique(subset=list(index_columns), keep="first", maintain_order=True)

    return selected.head(limit)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _r3_has_elevation(df: pl.DataFrame) -> bool:
    """True si voxel_elevation_masl tiene al menos un valor numerico finito."""
    if "voxel_elevation_masl" not in df.columns:
        return False
    return any(_is_finite_number(value) for value in df["voxel_elevation_masl"])


def _r3_first_str(df: pl.DataFrame, col: str):
    """Primer valor no-null de una columna str, o None si no existe/está vacía."""
    if col not in df.columns:
        return None
    s = df[col].drop_nulls()
    return str(s[0]) if len(s) > 0 else None


def _r3_col_minmax(df: pl.DataFrame, col: str):
    """(min, max) ignorando nulls, o (None, None) si la columna no existe o está vacía."""
    # R3 considera validos solo valores numericos finitos.
    if col not in df.columns:
        return None, None
    values = [
        float(value)
        for value in df[col]
        if _is_finite_number(value)
    ]
    if len(values) == 0:
        return None, None
    return min(values), max(values)


def _r3_elevation_range(df: pl.DataFrame) -> dict:
    vox_min, vox_max = _r3_col_minmax(df, "voxel_elevation_masl")
    surf_min, surf_max = _r3_col_minmax(df, "surface_elevation_masl")
    depth_min, depth_max = _r3_col_minmax(df, "depth_below_surface_m")
    return {
        "min_voxel_elevation_masl": vox_min,
        "max_voxel_elevation_masl": vox_max,
        "min_surface_elevation_masl": surf_min,
        "max_surface_elevation_masl": surf_max,
        "min_depth_below_surface_m": depth_min,
        "max_depth_below_surface_m": depth_max,
    }


def empty_block_model_response(
    mode,
    trace_metadata,
    error,
    total_rows=0,
    anomaly_voxels=None,
    warnings=None,
):
    voxel_trace = build_voxel_trace_metadata(
        mode=mode,
        total_voxels=total_rows,
        stored_voxels=total_rows,
        anomaly_voxels=anomaly_voxels,
        returned_voxels=0,
    )
    warnings_list = list(warnings or [])
    empty_distribution_metadata = build_distribution_metadata(pl.DataFrame())

    return {
        "error": error,
        "warnings": warnings_list,
        "mode": mode,
        "domainL": 0,
        "domainH": 0,
        "domainW": 0,
        "cellSize": 10,
        "visualMode": mode,
        "totalRows": total_rows,
        "returnedCells": 0,
        "cells": [],
        "has_elevation_data": False,
        "dem_source": None,
        "georef_confidence": None,
        "elevation_range": {
            "min_voxel_elevation_masl": None,
            "max_voxel_elevation_masl": None,
            "min_surface_elevation_masl": None,
            "max_surface_elevation_masl": None,
            "min_depth_below_surface_m": None,
            "max_depth_below_surface_m": None,
        },
        **build_diagnostic_stats(pl.DataFrame()),
        **empty_distribution_metadata,
        **voxel_trace,
        **trace_metadata,
    }


def build_block_model_response(
    mode: str = "exploration",
    limit: int = 5000,
    project_id: str = None,
    run_id: str = None,
):
    mode_clean, warnings = normalize_block_model_mode(mode)
    safe_limit = max(int(limit or 0), 0)

    print(
        f"[BLOCK-MODEL-SERVICE] Construyendo block model. mode={mode_clean} "
        f"limit={safe_limit} project_id={project_id} run_id={run_id}"
    )

    try:
        block_model_ref = resolve_block_model_reference(
            project_id=project_id,
            run_id=run_id,
        )
    except ValueError as exc:
        return empty_block_model_response(mode_clean, {}, str(exc), warnings=warnings)

    parquet_path = block_model_ref.path
    anomaly_path = parquet_path.with_name(RUN_ANOMALY_FILENAME)
    trace_metadata = block_model_ref.metadata()

    if not parquet_path.exists():
        return empty_block_model_response(
            mode_clean,
            trace_metadata,
            f"Archivo {parquet_path} no encontrado.",
            warnings=warnings,
        )

    df = pl.read_parquet(str(parquet_path))

    if len(df) == 0:
        return empty_block_model_response(
            mode_clean,
            trace_metadata,
            "Block model vacio.",
            warnings=warnings,
        )

    df = ensure_visual_columns(df)
    percentile_stats = compute_percentile_stats(df)
    full_stats = build_diagnostic_stats(df)
    full_distribution_metadata = build_distribution_metadata(df)

    try:
        ix_col, iy_col, iz_col = get_index_columns(df)
    except ValueError as exc:
        return empty_block_model_response(
            mode_clean,
            trace_metadata,
            str(exc),
            total_rows=len(df),
            warnings=warnings,
        )

    nx = int(df[ix_col].max()) + 1
    ny = int(df[iy_col].max()) + 1
    nz = int(df[iz_col].max()) + 1
    total_voxels = nx * ny * nz
    stored_voxels = len(df)
    anomaly_voxels = count_parquet_rows_or_none(anomaly_path)

    cell_size = infer_cell_size(df)

    has_real_coords = {"x", "y", "z"}.issubset(set(df.columns))

    if has_real_coords:
        x_min = float(df["x"].min())
        x_max = float(df["x"].max())
        y_min = float(df["y"].min())
        y_max = float(df["y"].max())
        z_min = float(df["z"].min())
        z_max = float(df["z"].max())

        x_center = (x_min + x_max) / 2.0
        y_center = (y_min + y_max) / 2.0
        z_center = (z_min + z_max) / 2.0
    else:
        x_center = nx * cell_size / 2.0
        y_center = ny * cell_size / 2.0
        z_center = nz * cell_size / 2.0

    _dens_series = df["density"].drop_nulls()
    density_min = float(_dens_series.min()) if len(_dens_series) > 0 else None
    density_max = float(_dens_series.max()) if len(_dens_series) > 0 else None

    if mode_clean == "full":
        df_view = df
        visual_mode = "density_probability"

        if stored_voxels > PERFORMANCE_WARNING_VOXEL_THRESHOLD:
            warnings.append(
                "full block model exceeds 200000 voxels; UI load may be slow and lower FPS."
            )

    elif mode_clean == "anomaly":
        visual_mode = "density_probability"

        if not anomaly_path.exists():
            warnings.append("anomaly model not available")
            anomaly_voxels = 0
            df_view = df.head(0)
        else:
            anomaly_df = pl.read_parquet(str(anomaly_path))
            anomaly_voxels = len(anomaly_df)
            df_view = (
                ensure_visual_columns(anomaly_df)
                if len(anomaly_df) > 0
                else df.head(0)
            )

    elif mode_clean == "doi_reliable":
        # Celdas con doi_index < 0.2 (Li & Oldenburg 1999) — bien constrainadas
        visual_mode = "density_probability"
        doi_col = "doi_index" if "doi_index" in df.columns else "doi_raw"
        if doi_col in df.columns:
            df_view = (
                df.filter(pl.col(doi_col) < 0.2)
                .sort("density", descending=True)
            )
        else:
            warnings.append("doi_index not available; returning exploration subset")
            df_view = select_limited_exploration_view(df, safe_limit, (ix_col, iy_col, iz_col))

    elif mode_clean == "profile":
        # Sin parámetros de perfil → devuelve exploración estándar
        # El endpoint /v2/block-model-profile maneja los parámetros A-A' directamente
        visual_mode = "density_probability"
        df_view = select_limited_exploration_view(df, safe_limit, (ix_col, iy_col, iz_col))
        warnings.append("profile mode via /block-model uses exploration fallback; use /v2/block-model-profile for A-A' sections")

    else:
        df_view = select_limited_exploration_view(
            df,
            safe_limit,
            (ix_col, iy_col, iz_col),
        )

        visual_mode = "density_probability"

    returned_stats = build_diagnostic_stats(df_view, prefix="returned")
    returned_distribution_metadata = build_distribution_metadata(df_view)

    # R3: elevation metadata (has_elevation_data basado en df_view para modo anomaly correcto)
    has_elevation_data = _r3_has_elevation(df_view)
    top_dem_source = _r3_first_str(df_view, "dem_source") or _r3_first_str(
        df,
        "dem_source",
    )
    top_georef_confidence = _r3_first_str(
        df_view,
        "georef_confidence",
    ) or _r3_first_str(df, "georef_confidence")
    elevation_range = _r3_elevation_range(df_view)

    cells = []

    for row in df_view.iter_rows(named=True):
        ix = int(row[ix_col])
        iy = int(row[iy_col])
        iz = int(row[iz_col])

        density = sanitize_nan_value(float(row.get("density", 2.6)))
        probability = sanitize_nan_value(float(row.get("probability", 1.0)))
        real_grade = sanitize_nan_value(float(row.get("grade", 0.0)))
        domain = int(row.get("domain", 0))

        # v4.0 prefers x_m/y_m/z_m; fall back to x/y/z (v3.0) then to computed value
        _xv = read_numeric_row_value(row, "x_m")
        x_m = _xv if _xv is not None else read_numeric_row_value(row, "x", (ix * cell_size) + (cell_size / 2.0))
        _yv = read_numeric_row_value(row, "y_m")
        y_m = _yv if _yv is not None else read_numeric_row_value(row, "y", (iy * cell_size) + (cell_size / 2.0))
        _zv = read_numeric_row_value(row, "z_m")
        z_m = _zv if _zv is not None else read_numeric_row_value(row, "z", (iz * cell_size) + (cell_size / 2.0))

        # Backend: y es profundidad positiva hacia abajo.
        # Three.js: y es vertical positiva hacia arriba.
        cx = x_m - x_center
        cy = y_center - y_m
        cz = z_m - z_center

        cell = {
            "cx": sanitize_nan_value(cx),
            "cy": sanitize_nan_value(cy),
            "cz": sanitize_nan_value(cz),
            "x": sanitize_nan_value(cx),
            "y": sanitize_nan_value(cy),
            "z": sanitize_nan_value(cz),
            "x_m": sanitize_nan_value(x_m),
            "y_m": sanitize_nan_value(y_m),
            "z_m": sanitize_nan_value(z_m),
            "rho": density,
            "density": density,
            "probability": probability,
            "domain": domain,
            "ix": ix,
            "iy": iy,
            "iz": iz,
            # R3 elevation fields — None si la columna no existe en el parquet
            "lat": sanitize_nan_value(row.get("lat")),
            "lon": sanitize_nan_value(row.get("lon")),
            "surface_elevation_masl": sanitize_nan_value(row.get("surface_elevation_masl")),
            "depth_below_surface_m": sanitize_nan_value(row.get("depth_below_surface_m")),
            "voxel_elevation_masl": sanitize_nan_value(row.get("voxel_elevation_masl")),
            "georef_confidence": row.get("georef_confidence"),
            "dem_source": row.get("dem_source"),
            "dem_sample_method": row.get("dem_sample_method"),
            "spatial_reference_warning": row.get("spatial_reference_warning"),
            # Multi-physics fields (magnetic + joint schema v3.0/v4.0)
            "susceptibility_si": sanitize_nan_value(row.get("susceptibility_si")),
            "joint_structural_score": sanitize_nan_value(row.get("joint_structural_score")),
            "density_t_m3": sanitize_nan_value(row.get("density_t_m3")),
            "density_contrast_t_m3": sanitize_nan_value(row.get("density_contrast_t_m3")),
            # v4.0 fields
            "doi_index": sanitize_nan_value(row.get("doi_index") or row.get("doi_raw")),
            "density_anomaly_score": sanitize_nan_value(row.get("density_anomaly_score")),
            "run_type": row.get("run_type"),
            "schema_version": row.get("schema_version"),
        }

        cell["real_grade"] = real_grade
        cell["visual_score"] = sanitize_nan_value(float(row.get("visual_score", 0.0)))

        cells.append(cell)

    returned_voxels = len(cells)
    voxel_trace = build_voxel_trace_metadata(
        mode=mode_clean,
        total_voxels=total_voxels,
        stored_voxels=stored_voxels,
        anomaly_voxels=anomaly_voxels,
        returned_voxels=returned_voxels,
    )

    response = {
        "mode": mode_clean,
        "domainL": nx * cell_size,
        "domainH": ny * cell_size,
        "domainW": nz * cell_size,
        "cellSize": cell_size,
        "visualMode": visual_mode,
        "totalRows": len(df),
        "returnedCells": returned_voxels,
        "warnings": warnings,
        **voxel_trace,
        "densityMin": round_stat(density_min),
        "densityMax": round_stat(density_max),
        "availableColumns": df.columns,
        "sourcePath": str(parquet_path),
        "percentile_stats": percentile_stats,
        **full_stats,
        **returned_stats,
        **full_distribution_metadata,
        "returnedDiagnosticStats": returned_distribution_metadata["diagnosticStats"],
        "returnedScoreStats": returned_distribution_metadata["scoreStats"],
        "cells": cells,
        "has_elevation_data": has_elevation_data,
        "dem_source": top_dem_source,
        "georef_confidence": top_georef_confidence,
        "elevation_range": elevation_range,
        **trace_metadata,
    }

    # Sanitizar recursivamente toda la respuesta para eliminar NaN/Inf antes de JSON serialization
    return sanitize_nan(response)


# ─── Arrow IPC Transport (R07) ────────────────────────────────────────────────
# Pipeline: Parquet → Polars → select → cast → write_ipc → bytes
# Sin iter_rows(), sin dicts Python, sin deep_sanitize_nan().

_ARROW_COORD_COLS = ("x", "y", "z")
_ARROW_SCALAR_FLOAT_COLS = ("density", "probability", "visual_score")
_ARROW_INT_COLS = ("ix", "iy", "iz")
_ARROW_OPTIONAL_COLS = ("professional_score", "economic_score")
_ARROW_R3_COLS = ("lat", "lon", "voxel_elevation_masl", "surface_elevation_masl")
_ARROW_MULTIPHYSICS_COLS = (
    "susceptibility_si",
    "joint_structural_score",
    "density_t_m3",
    "density_contrast_t_m3",
    "doi_index",
    "density_anomaly_score",
    "posterior_std",
)


def build_block_model_arrow_bytes(
    mode: str = "exploration",
    limit: int = 0,
    project_id=None,
    run_id=None,
):
    """Construye payload Arrow IPC para el block model.

    Pipeline puro Polars — sin iter_rows(), sin dicts, sin deep_sanitize_nan().
    Retorna (ipc_bytes: bytes, headers: dict[str, str]).
    """
    mode_clean, _warnings = normalize_block_model_mode(mode)

    try:
        block_model_ref = resolve_block_model_reference(
            project_id=project_id,
            run_id=run_id,
        )
    except ValueError as exc:
        raise ValueError(str(exc))

    parquet_path = block_model_ref.path
    trace_metadata = block_model_ref.metadata()

    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet {parquet_path} no encontrado.")

    df = pl.read_parquet(str(parquet_path))

    if len(df) == 0:
        raise ValueError("Block model vacío.")

    df = ensure_visual_columns(df)

    # Stats autoritativos del modelo COMPLETO (antes de cualquier subsetting).
    # Estos se emiten como headers X-TQ-* para que el FE los consuma directamente
    # sin re-inferir cell_size ni recalcular bounds desde el subconjunto devuelto.
    _arrow_cell_size = infer_cell_size(df)
    _density_series = df["density"].drop_nulls()
    _arrow_density_min = float(_density_series.min()) if len(_density_series) > 0 else None
    _arrow_density_max = float(_density_series.max()) if len(_density_series) > 0 else None

    try:
        ix_col, iy_col, iz_col = get_index_columns(df)
    except ValueError as exc:
        raise ValueError(str(exc))

    # Normalizar nombres de índice a ix/iy/iz
    rename_map: dict = {}
    if ix_col != "ix":
        rename_map[ix_col] = "ix"
    if iy_col != "iy":
        rename_map[iy_col] = "iy"
    if iz_col != "iz":
        rename_map[iz_col] = "iz"
    if rename_map:
        df = df.rename(rename_map)

    total_stored = len(df)

    # Selección de subconjunto si se pide límite explícito
    safe_limit = max(int(limit or 0), 0)
    if safe_limit > 0 and len(df) > safe_limit:
        df = select_limited_exploration_view(df, safe_limit, ("ix", "iy", "iz"))

    total_returned = len(df)

    # Coordenadas centradas + inversión Y para Three.js — puro Polars, sin iter_rows
    # v4.0 usa x_m/y_m/z_m; v3.0 usaba x/y/z. Normalizar a x/y/z para el transporte Arrow.
    _cols_set = set(df.columns)
    if {"x_m", "y_m", "z_m"}.issubset(_cols_set) and not {"x", "y", "z"}.issubset(_cols_set):
        df = df.rename({"x_m": "x", "y_m": "y", "z_m": "z"})
    has_real_coords = {"x", "y", "z"}.issubset(set(df.columns))
    if has_real_coords:
        x_min = float(df["x"].min())
        x_max = float(df["x"].max())
        y_min_raw = float(df["y"].min())
        y_max_raw = float(df["y"].max())
        z_min = float(df["z"].min())
        z_max = float(df["z"].max())
        x_c = (x_min + x_max) / 2.0
        y_c = (y_min_raw + y_max_raw) / 2.0
        z_c = (z_min + z_max) / 2.0
        df = df.with_columns([
            (pl.col("x") - x_c).cast(pl.Float32).alias("x"),
            (y_c - pl.col("y")).cast(pl.Float32).alias("y"),
            (pl.col("z") - z_c).cast(pl.Float32).alias("z"),
        ])
    else:
        cell_size_val = infer_cell_size(df)
        nx_v = int(df["ix"].max()) + 1
        ny_v = int(df["iy"].max()) + 1
        nz_v = int(df["iz"].max()) + 1
        x_c = nx_v * cell_size_val / 2.0
        y_c = ny_v * cell_size_val / 2.0
        z_c = nz_v * cell_size_val / 2.0
        x_min, y_min_raw, z_min = 0.0, 0.0, 0.0
        x_max = float(nx_v * cell_size_val)
        y_max_raw = float(ny_v * cell_size_val)
        z_max = float(nz_v * cell_size_val)
        df = df.with_columns([
            (pl.col("ix").cast(pl.Float32) * cell_size_val + cell_size_val / 2.0 - x_c).alias("x"),
            (y_c - (pl.col("iy").cast(pl.Float32) * cell_size_val + cell_size_val / 2.0)).alias("y"),
            (pl.col("iz").cast(pl.Float32) * cell_size_val + cell_size_val / 2.0 - z_c).alias("z"),
        ])

    # Columnas a incluir — sin aliases redundantes (cx/cy/cz, x_m/y_m/z_m, rho)
    select_cols = list(_ARROW_COORD_COLS) + list(_ARROW_SCALAR_FLOAT_COLS) + list(_ARROW_INT_COLS)

    for col in _ARROW_OPTIONAL_COLS:
        if col in df.columns:
            select_cols.append(col)

    has_elevation = _r3_has_elevation(df)
    if has_elevation:
        for col in _ARROW_R3_COLS:
            if col in df.columns:
                select_cols.append(col)

    for col in _ARROW_MULTIPHYSICS_COLS:
        if col in df.columns:
            select_cols.append(col)

    available = [c for c in select_cols if c in df.columns]
    df = df.select(available)

    # Castear tipos para reducir payload (~14× vs JSON)
    cast_exprs = []
    for col in (*_ARROW_COORD_COLS, *_ARROW_SCALAR_FLOAT_COLS, *_ARROW_MULTIPHYSICS_COLS):
        if col in df.columns and df[col].dtype != pl.Float32:
            cast_exprs.append(pl.col(col).cast(pl.Float32))
    for col in _ARROW_INT_COLS:
        if col in df.columns and df[col].dtype not in (pl.Int32,):
            cast_exprs.append(pl.col(col).cast(pl.Int32))
    if cast_exprs:
        df = df.with_columns(cast_exprs)

    buf = io.BytesIO()
    try:
        import pyarrow as _pa
        import pyarrow.ipc as _pa_ipc
        _pa_table = _pa.Table.from_pandas(df.to_pandas(), preserve_index=False)
        _opts = _pa_ipc.IpcWriteOptions(compression="lz4")
        _sink = _pa.BufferOutputStream()
        with _pa_ipc.new_stream(_sink, _pa_table.schema, options=_opts) as _writer:
            _writer.write_table(_pa_table)
        ipc_bytes = _sink.getvalue().to_pybytes()
        _lz4_used = True
    except Exception:
        df.write_ipc(buf)
        ipc_bytes = buf.getvalue()
        _lz4_used = False

    headers: dict[str, str] = {
        "X-TQ-Total-Voxels": str(total_returned),
        "X-TQ-Bounds-Min": f"{x_min:.4f},{y_min_raw:.4f},{z_min:.4f}",
        "X-TQ-Bounds-Max": f"{x_max:.4f},{y_max_raw:.4f},{z_max:.4f}",
        "X-TQ-Cell-Size": f"{_arrow_cell_size:.4f}",
        "X-TQ-Domain-L": f"{x_max - x_min:.4f}",
        "X-TQ-Domain-H": f"{y_max_raw - y_min_raw:.4f}",
        "X-TQ-Domain-W": f"{z_max - z_min:.4f}",
    }
    if _arrow_density_min is not None:
        headers["X-TQ-Density-Min"] = f"{_arrow_density_min:.6f}"
    if _arrow_density_max is not None:
        headers["X-TQ-Density-Max"] = f"{_arrow_density_max:.6f}"
    run_id_val = trace_metadata.get("runId")
    if run_id_val:
        headers["X-TQ-Run-Id"] = str(run_id_val)
    headers["X-TQ-Compression"] = "lz4" if _lz4_used else "none"

    logger.info(
        "[ARROW] mode=%s returned=%d stored=%d bytes=%d has_elevation=%s lz4=%s",
        mode_clean, total_returned, total_stored, len(ipc_bytes), has_elevation, _lz4_used,
    )

    return ipc_bytes, headers


# ─── Profile A-A' (Fase 3, §3.4) ─────────────────────────────────────────────

def build_block_model_profile_response(
    project_id: str,
    run_id: str,
    x0_m: float,
    z0_m: float,
    x1_m: float,
    z1_m: float,
    halfwidth_m: float = 50.0,
    include_observations: bool = True,
):
    """Retorna vóxeles que intersectan la sección A-A' definida por (x0,z0)→(x1,z1)
    con ancho ±halfwidth_m.  Coordenadas en sistema local del modelo [m].

    Responde:
        profile_voxels     — lista de celdas dentro de la sección
        profile_distance_m — distancia de cada celda proyectada sobre el eje A-A'
        profile_observations — d_obs/d_pred/residual si obs_vs_calc.parquet existe
        line                — {x0, z0, x1, z1, halfwidth_m}
        n_voxels            — conteo
    """
    import math

    try:
        block_model_ref = resolve_block_model_reference(project_id=project_id, run_id=run_id)
    except ValueError as exc:
        return {"error": str(exc), "profile_voxels": [], "profile_observations": []}

    parquet_path = block_model_ref.path
    if not parquet_path.exists():
        return {"error": f"Parquet no encontrado: {parquet_path}", "profile_voxels": [], "profile_observations": []}

    df = pl.read_parquet(str(parquet_path))
    if len(df) == 0:
        return {"error": "Block model vacío.", "profile_voxels": [], "profile_observations": []}

    df = ensure_visual_columns(df)

    # Normalizar coords — preferir x_m/z_m (v4.0), caer a x/z (v3.0)
    x_col = "x_m" if "x_m" in df.columns else "x"
    z_col = "z_m" if "z_m" in df.columns else "z"

    if x_col not in df.columns or z_col not in df.columns:
        cell_size = infer_cell_size(df)
        if "ix" in df.columns:
            df = df.with_columns([
                (pl.col("ix").cast(pl.Float64) * cell_size + cell_size / 2.0).alias("_xc"),
                (pl.col("iz").cast(pl.Float64) * cell_size + cell_size / 2.0).alias("_zc"),
            ])
            x_col, z_col = "_xc", "_zc"
        else:
            return {"error": "Sin columnas de coordenadas en el parquet.", "profile_voxels": [], "profile_observations": []}

    # Vector de la línea A-A'
    dx_line = x1_m - x0_m
    dz_line = z1_m - z0_m
    line_len = math.sqrt(dx_line ** 2 + dz_line ** 2)
    if line_len < 1e-6:
        return {"error": "Línea A-A' de longitud cero.", "profile_voxels": [], "profile_observations": []}

    ux = dx_line / line_len
    uz = dz_line / line_len

    # Proyección y distancia perpendicular
    df = df.with_columns([
        ((pl.col(x_col) - x0_m) * ux + (pl.col(z_col) - z0_m) * uz).alias("_proj_along"),
        (((pl.col(x_col) - x0_m) * (-uz) + (pl.col(z_col) - z0_m) * ux).abs()).alias("_dist_perp"),
    ])

    # Filtrar dentro de la sección (en el eje longitudinal + ancho)
    df_profile = df.filter(
        (pl.col("_proj_along") >= 0.0)
        & (pl.col("_proj_along") <= line_len)
        & (pl.col("_dist_perp") <= halfwidth_m)
    ).sort("_proj_along")

    profile_voxels = []
    for row in df_profile.iter_rows(named=True):
        cell_size_v = infer_cell_size(df)
        xv = float(row.get(x_col, 0.0))
        yv = float(row.get("y_m", row.get("y", 0.0)))
        zv = float(row.get(z_col, 0.0))
        profile_voxels.append({
            "x_m": xv,
            "y_m": yv,
            "z_m": zv,
            "profile_distance_m": float(row["_proj_along"]),
            "perp_distance_m": float(row["_dist_perp"]),
            "density": sanitize_nan_value(float(row.get("density", 0.0))),
            "density_t_m3": sanitize_nan_value(float(row.get("density_t_m3", row.get("density", 0.0)))),
            "density_contrast_t_m3": sanitize_nan_value(row.get("density_contrast_t_m3")),
            "doi_index": sanitize_nan_value(row.get("doi_index") or row.get("doi_raw")),
            "posterior_std": sanitize_nan_value(row.get("posterior_std")),
            "visual_score": sanitize_nan_value(row.get("visual_score")),
            "ix": int(row.get("ix", 0)),
            "iy": int(row.get("iy", 0)),
            "iz": int(row.get("iz", 0)),
        })

    # Observaciones obs vs calc dentro del perfil
    profile_observations = []
    if include_observations:
        ovc_path = parquet_path.parent / "obs_vs_calc.parquet"
        if ovc_path.exists():
            try:
                df_ovc = pl.read_parquet(str(ovc_path))
                x_ovc = "x" if "x" in df_ovc.columns else None
                z_ovc = "z" if "z" in df_ovc.columns else None
                if x_ovc and z_ovc:
                    df_ovc = df_ovc.with_columns([
                        ((pl.col(x_ovc) - x0_m) * ux + (pl.col(z_ovc) - z0_m) * uz).alias("_proj_along"),
                        (((pl.col(x_ovc) - x0_m) * (-uz) + (pl.col(z_ovc) - z0_m) * ux).abs()).alias("_dist_perp"),
                    ])
                    df_ovc_prof = df_ovc.filter(
                        (pl.col("_proj_along") >= 0.0)
                        & (pl.col("_proj_along") <= line_len)
                        & (pl.col("_dist_perp") <= halfwidth_m)
                    ).sort("_proj_along")
                    for row in df_ovc_prof.iter_rows(named=True):
                        profile_observations.append({
                            "x_m": float(row.get("x", 0.0)),
                            "z_m": float(row.get("z", 0.0)),
                            "profile_distance_m": float(row["_proj_along"]),
                            "d_obs": sanitize_nan_value(row.get("d_obs")),
                            "d_pred": sanitize_nan_value(row.get("d_pred")),
                            "residual": sanitize_nan_value(row.get("residual")),
                        })
            except Exception:
                pass

    return {
        "line": {"x0_m": x0_m, "z0_m": z0_m, "x1_m": x1_m, "z1_m": z1_m, "halfwidth_m": halfwidth_m},
        "n_voxels": len(profile_voxels),
        "n_observations": len(profile_observations),
        "profile_voxels": profile_voxels,
        "profile_observations": profile_observations,
    }
