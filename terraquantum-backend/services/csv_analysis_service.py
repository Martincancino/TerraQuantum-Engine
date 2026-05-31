import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from schemas.geophysics_schema import GravityObservation
from schemas.gravity_import_schema import (
    CoordSystemDetection,
    CsvAnalysisResult,
    DuplicateInfo,
    GravityStats,
    OutlierInfo,
    SamplingStats,
    SpatialExtent,
    UnitDetection,
)


NEAR_DUPLICATE_TOLERANCE_M = 1.0
MAX_EXAMPLES = 3

# ---------------------------------------------------------------------------
# R3.5-I — Professional column alias sets
# ---------------------------------------------------------------------------

# R3.5-I-FIX1 — Value presence detection helpers
_EMPTY_VALUE_TOKENS: frozenset = frozenset({"", "nan", "null", "none", "na", "n/a"})


def _is_real_value(v: Any) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() not in _EMPTY_VALUE_TOKENS


def _column_has_values(values: List[Any]) -> bool:
    return any(_is_real_value(v) for v in values)


def _group_has_values(col_values: Dict[str, List[Any]], aliases: frozenset) -> bool:
    """Return True if any alias column in col_values has at least one real value."""
    for alias in aliases:
        if alias in col_values and _column_has_values(col_values[alias]):
            return True
    return False

# z / z_m are NOT here because they serve as coordinate columns in the v1 format
# and must not be miscounted as elevation metadata.
ELEVATION_ALIASES: frozenset = frozenset({
    "elevation", "elevation_m", "elev_m", "elev",
    "rl", "rl_m", "altitude", "altitude_m",
    "height", "height_m", "cota", "cota_m",
})

UNCERTAINTY_ALIASES: frozenset = frozenset({
    "uncertainty", "uncertainty_mgal", "sigma", "sigma_mgal",
    "std", "stddev", "standard_deviation",
    "error", "error_mgal", "measurement_error",
    "gravity_uncertainty", "uncertainty_gravity",
})

INSTRUMENT_ALIASES: frozenset = frozenset({
    "instrument", "instrument_id", "instrument_model",
    "gravimeter", "gravimeter_id",
    "sensor", "sensor_id", "device", "device_id",
    "operator", "survey_date", "date", "timestamp",
})

# bouguer_anomaly / cba / faa are intentionally dual-use: they can appear as
# gravity value columns AND as correction metadata markers simultaneously.
CORRECTION_ALIASES: frozenset = frozenset({
    "bouguer_correction", "free_air_correction", "terrain_correction",
    "drift_correction", "tide_correction", "latitude_correction",
    "eotvos_correction", "correction", "corrections_applied",
    "bouguer_anomaly", "free_air_anomaly", "complete_bouguer_anomaly",
    "cba", "faa",
})

_ALL_PROFESSIONAL_ALIASES: frozenset = (
    ELEVATION_ALIASES | UNCERTAINTY_ALIASES | INSTRUMENT_ALIASES | CORRECTION_ALIASES
)


def detect_professional_columns(
    column_names: Sequence[str],
) -> Tuple[bool, bool, bool, bool, List[str]]:
    """Detect professional survey flags from CSV header names.

    Returns (has_elevation, has_uncertainty, has_instrument, has_corrections, detected_list).
    detected_list is sorted for deterministic output.
    """
    normalized = {col.strip().lower() for col in column_names}
    detected = sorted(normalized & _ALL_PROFESSIONAL_ALIASES)
    return (
        bool(normalized & ELEVATION_ALIASES),
        bool(normalized & UNCERTAINTY_ALIASES),
        bool(normalized & INSTRUMENT_ALIASES),
        bool(normalized & CORRECTION_ALIASES),
        detected,
    )


def _finite_values(values: Iterable[float]) -> List[float]:
    return [float(value) for value in values if math.isfinite(float(value))]


def _percentile(sorted_values: Sequence[float], percentile: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    rank = (len(sorted_values) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[int(rank)])

    weight = rank - low
    return float(sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight)


def _build_spatial_extent(observations: Sequence[GravityObservation]) -> SpatialExtent:
    if not observations:
        return SpatialExtent()

    xs = [obs.x_m for obs in observations]
    ys = [obs.y_m for obs in observations]
    zs = [obs.z_m for obs in observations]

    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    z_min = min(zs)
    z_max = max(zs)

    return SpatialExtent(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z_min=z_min,
        z_max=z_max,
        x_span=x_max - x_min,
        y_span=y_max - y_min,
        z_span=z_max - z_min,
    )


def _build_sampling_stats(extent: SpatialExtent, observation_count: int) -> SamplingStats:
    span_x = float(extent.x_span or 0.0)
    span_z = float(extent.z_span or 0.0)
    area_m2 = max(span_x, 0.0) * max(span_z, 0.0)
    area_km2 = area_m2 / 1_000_000.0

    mean_spacing_m = None
    point_density_per_km2 = None
    if observation_count > 0 and area_m2 > 0:
        mean_spacing_m = math.sqrt(area_m2 / observation_count)
    if observation_count > 0 and area_km2 > 0:
        point_density_per_km2 = observation_count / area_km2

    return SamplingStats(
        area_km2=area_km2,
        mean_spacing_m=mean_spacing_m,
        point_density_per_km2=point_density_per_km2,
    )


def _build_gravity_stats(values: Sequence[float]) -> GravityStats:
    clean_values = _finite_values(values)
    if not clean_values:
        return GravityStats()

    sorted_values = sorted(clean_values)
    mean = sum(clean_values) / len(clean_values)
    variance = sum((value - mean) ** 2 for value in clean_values) / len(clean_values)

    return GravityStats(
        min=min(clean_values),
        max=max(clean_values),
        mean=mean,
        std=math.sqrt(variance),
        p5=_percentile(sorted_values, 0.05),
        p95=_percentile(sorted_values, 0.95),
    )


def _example_coordinates(obs: GravityObservation) -> Dict[str, float]:
    return {"x_m": obs.x_m, "y_m": obs.y_m, "z_m": obs.z_m}


def _neighbor_keys(key: Tuple[int, int, int]) -> Iterable[Tuple[int, int, int]]:
    base_x, base_y, base_z = key
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (base_x + dx, base_y + dy, base_z + dz)


def _detect_near_duplicates(
    observations: Sequence[GravityObservation],
    tolerance_m: float,
) -> Tuple[int, List[Dict[str, Any]]]:
    if len(observations) < 2 or tolerance_m <= 0:
        return 0, []

    bins: Dict[Tuple[int, int, int], List[Tuple[int, GravityObservation]]] = defaultdict(list)
    near_count = 0
    examples: List[Dict[str, Any]] = []
    inv_tolerance = 1.0 / tolerance_m

    for index, obs in enumerate(observations):
        key = (
            math.floor(obs.x_m * inv_tolerance),
            math.floor(obs.y_m * inv_tolerance),
            math.floor(obs.z_m * inv_tolerance),
        )

        matched = False
        for neighbor_key in _neighbor_keys(key):
            for previous_index, previous in bins.get(neighbor_key, []):
                distance = math.sqrt(
                    (obs.x_m - previous.x_m) ** 2
                    + (obs.y_m - previous.y_m) ** 2
                    + (obs.z_m - previous.z_m) ** 2
                )
                if 0.0 < distance <= tolerance_m:
                    near_count += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(
                            {
                                "index": index,
                                "matched_index": previous_index,
                                "distance_m": distance,
                                "coordinates": _example_coordinates(obs),
                                "matched_coordinates": _example_coordinates(previous),
                            }
                        )
                    matched = True
                    break
            if matched:
                break

        bins[key].append((index, obs))

    return near_count, examples


def _build_duplicate_info(
    observations: Sequence[GravityObservation],
    exact_duplicate_count: int,
    exact_duplicate_examples: Optional[Sequence[Dict[str, Any]]],
) -> DuplicateInfo:
    near_count, near_examples = _detect_near_duplicates(
        observations,
        NEAR_DUPLICATE_TOLERANCE_M,
    )

    examples: List[Dict[str, Any]] = []
    for example in list(exact_duplicate_examples or [])[:MAX_EXAMPLES]:
        examples.append({"type": "exact", **example})
    for example in near_examples[: max(0, MAX_EXAMPLES - len(examples))]:
        examples.append({"type": "near", **example})

    return DuplicateInfo(
        exact_count=exact_duplicate_count,
        near_count=near_count,
        tolerance_m=NEAR_DUPLICATE_TOLERANCE_M,
        examples=examples,
    )


def _build_outlier_info(
    observations: Sequence[GravityObservation],
    gravity_values: Sequence[float],
) -> OutlierInfo:
    values = _finite_values(gravity_values)
    if len(values) < 2:
        return OutlierInfo()

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    if std == 0:
        return OutlierInfo()

    count = 0
    examples: List[Dict[str, Any]] = []
    limit = min(len(values), len(observations))

    for index in range(limit):
        value = values[index]
        zscore = (value - mean) / std
        if abs(zscore) > 3.0:
            count += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append(
                    {
                        "index": index,
                        "g_value": value,
                        "value": value,
                        "zscore": zscore,
                        "coordinates": _example_coordinates(observations[index]),
                    }
                )

    return OutlierInfo(count=count, method="zscore_3sigma", examples=examples)


def _normalize_unit(unit: Optional[str]) -> str:
    if not unit:
        return ""
    return unit.strip().replace(" ", "").replace("²", "2").replace("Â²", "2")


def _infer_unit_consistency(
    declared_unit: Optional[str],
    raw_gravity_values: Sequence[float],
) -> UnitDetection:
    clean_values = _finite_values(raw_gravity_values)
    normalized = _normalize_unit(declared_unit)

    if not normalized:
        return UnitDetection(
            declared=declared_unit,
            value_range_consistent=False,
            confidence="low",
            warning="No se declaro unidad de gravedad en el CSV.",
        )

    if not clean_values:
        return UnitDetection(
            declared=declared_unit,
            value_range_consistent=False,
            confidence="low",
            warning="No hay valores raw de gravedad para validar la unidad declarada.",
        )

    max_abs = max(abs(value) for value in clean_values)
    thresholds = {
        "mGal": 100_000.0,
        "m/s2": 20.0,
        "uGal": 1_000_000_000.0,
        "µGal": 1_000_000_000.0,
        "ÂµGal": 1_000_000_000.0,
    }
    limit = thresholds.get(normalized)

    if limit is None:
        return UnitDetection(
            declared=declared_unit,
            value_range_consistent=False,
            confidence="low",
            warning=f"Unidad declarada no reconocida para analisis: {declared_unit}",
        )

    if max_abs > limit:
        return UnitDetection(
            declared=declared_unit,
            value_range_consistent=False,
            confidence="high",
            warning=(
                f"Rango raw de gravedad inconsistente con unidad declarada {declared_unit}: "
                f"max_abs={max_abs:.6g}"
            ),
        )

    return UnitDetection(
        declared=declared_unit,
        value_range_consistent=True,
        confidence="high",
        warning=None,
    )


def _all_in_range(values: Sequence[float], min_value: float, max_value: float) -> bool:
    return bool(values) and all(min_value <= value <= max_value for value in values)


def _infer_coordinate_system(observations: Sequence[GravityObservation]) -> CoordSystemDetection:
    if not observations:
        return CoordSystemDetection(
            detected="unknown",
            confidence="low",
            warning="No hay observaciones para inferir sistema de coordenadas.",
        )

    xs = [obs.x_m for obs in observations]
    zs = [obs.z_m for obs in observations]
    x_span = max(xs) - min(xs)
    z_span = max(zs) - min(zs)
    max_abs = max(max(abs(value) for value in xs), max(abs(value) for value in zs))

    x_lon_z_lat = _all_in_range(xs, -180.0, 180.0) and _all_in_range(zs, -90.0, 90.0)
    x_lat_z_lon = _all_in_range(xs, -90.0, 90.0) and _all_in_range(zs, -180.0, 180.0)
    if max_abs <= 180.0 and (x_lon_z_lat or x_lat_z_lon):
        confidence = "high"
        warning = None
        if min(xs) >= 0.0 and min(zs) >= 0.0 and max_abs <= 90.0:
            confidence = "medium"
            warning = "Coordenadas compatibles con lat/lon y grilla local pequena; revisar CRS declarado."
        return CoordSystemDetection(
            detected="latlon",
            confidence=confidence,
            warning=warning,
        )

    if _all_in_range(xs, 100_000.0, 900_000.0) and _all_in_range(zs, 0.0, 10_000_000.0):
        return CoordSystemDetection(detected="utm", confidence="high", warning=None)

    if (
        min(xs) >= 0.0
        and min(zs) >= 0.0
        and max(xs) <= 50_000.0
        and max(zs) <= 50_000.0
    ):
        return CoordSystemDetection(detected="local_meters", confidence="high", warning=None)

    if x_span <= 200_000.0 and z_span <= 200_000.0 and max_abs <= 1_000_000.0:
        return CoordSystemDetection(
            detected="local_meters",
            confidence="medium",
            warning="Sistema local en metros inferido con confianza media; revisar CRS declarado.",
        )

    return CoordSystemDetection(
        detected="unknown",
        confidence="low",
        warning="No se pudo inferir con confianza el sistema de coordenadas del CSV.",
    )


def _select_gravity_values(
    observations: Sequence[GravityObservation],
    raw_gravity_values: Optional[Sequence[float]],
    warnings: List[str],
) -> List[float]:
    if raw_gravity_values is not None and len(raw_gravity_values) == len(observations):
        return _finite_values(raw_gravity_values)

    if raw_gravity_values is not None and len(raw_gravity_values) != len(observations):
        warnings.append(
            "Cantidad de valores raw no coincide con observaciones validas; usando gravedad interna para estadisticas."
        )

    return [obs.g for obs in observations]


def analyze_csv_observations(
    observations: Sequence[GravityObservation],
    declared_unit: Optional[str],
    raw_gravity_values: Optional[Sequence[float]] = None,
    exact_duplicate_count: int = 0,
    exact_duplicate_examples: Optional[Sequence[Dict[str, Any]]] = None,
    warnings: Optional[Sequence[str]] = None,
    column_names: Optional[List[str]] = None,
    professional_column_values: Optional[Dict[str, List[Any]]] = None,
) -> CsvAnalysisResult:
    """
    professional_column_values: when provided (from import service), refines professional
    flags to require at least one non-empty value per column category (R3.5-I-FIX1).
    When None (direct callers), falls back to header-only detection for backward compat.
    """
    analysis_warnings = list(warnings or [])
    observation_count = len(observations)
    gravity_values = _select_gravity_values(observations, raw_gravity_values, analysis_warnings)

    # R3.5-I — detect professional columns from header names when provided
    if column_names is not None:
        has_elevation, has_uncertainty, has_instrument, has_corrections, prof_detected = (
            detect_professional_columns(column_names)
        )
    else:
        has_elevation = has_uncertainty = has_instrument = has_corrections = False
        prof_detected: List[str] = []

    # R3.5-I-FIX1 — refine flags using actual row values when available
    professional_columns_with_values: List[str] = []
    if column_names is not None and professional_column_values is not None:
        has_elevation = has_elevation and _group_has_values(professional_column_values, ELEVATION_ALIASES)
        has_uncertainty = has_uncertainty and _group_has_values(professional_column_values, UNCERTAINTY_ALIASES)
        has_instrument = has_instrument and _group_has_values(professional_column_values, INSTRUMENT_ALIASES)
        has_corrections = has_corrections and _group_has_values(professional_column_values, CORRECTION_ALIASES)
        professional_columns_with_values = sorted(
            col for col in prof_detected
            if col in professional_column_values and _column_has_values(professional_column_values[col])
        )

    extent = _build_spatial_extent(observations)
    sampling = _build_sampling_stats(extent, observation_count)
    gravity_stats = _build_gravity_stats(gravity_values)
    duplicates = _build_duplicate_info(
        observations,
        exact_duplicate_count=exact_duplicate_count,
        exact_duplicate_examples=exact_duplicate_examples,
    )
    outliers = _build_outlier_info(observations, gravity_values)
    units = _infer_unit_consistency(declared_unit, raw_gravity_values or gravity_values)
    coordinate_system = _infer_coordinate_system(observations)

    if observation_count < 10:
        analysis_warnings.append("Menos de 10 observaciones validas; inversion no permitida.")
    if duplicates.exact_count > 0:
        analysis_warnings.append(
            f"Se descartaron {duplicates.exact_count} filas con coordenadas exactas duplicadas."
        )
    if duplicates.near_count > 0:
        analysis_warnings.append(
            f"Se detectaron {duplicates.near_count} observaciones cercanas con tolerancia {duplicates.tolerance_m:g} m."
        )
    if outliers.count > 0:
        analysis_warnings.append(
            f"Se detectaron {outliers.count} outliers de gravedad por zscore 3 sigma; no fueron eliminados."
        )
    if units.warning:
        analysis_warnings.append(units.warning)
    if coordinate_system.warning:
        analysis_warnings.append(coordinate_system.warning)
    if sampling.area_km2 == 0.0 and observation_count > 0:
        analysis_warnings.append("Area cubierta degenerada o nula; revisar coordenadas del CSV.")

    deduped_warnings = list(dict.fromkeys(analysis_warnings))

    has_quality_issue = (
        duplicates.exact_count > 0
        or duplicates.near_count > 0
        or outliers.count > 0
        or not units.value_range_consistent
        or coordinate_system.detected == "unknown"
        or sampling.area_km2 == 0.0
    )
    low_density = (
        sampling.point_density_per_km2 is None
        or sampling.point_density_per_km2 < 1.0
    )

    if observation_count < 10:
        quality_label = "INSUFICIENTE"
    elif observation_count < 30 or low_density or has_quality_issue:
        quality_label = "BAJA"
    elif deduped_warnings:
        quality_label = "MEDIA"
    else:
        quality_label = "ALTA"

    return CsvAnalysisResult(
        observation_count=observation_count,
        spatial_extent=extent,
        sampling=sampling,
        gravity_stats=gravity_stats,
        duplicates=duplicates,
        outliers=outliers,
        units=units,
        coordinate_system=coordinate_system,
        warnings=deduped_warnings,
        quality_label=quality_label,
        has_elevation_column=has_elevation,
        has_uncertainty_column=has_uncertainty,
        has_instrument_metadata=has_instrument,
        has_corrections_metadata=has_corrections,
        professional_columns_detected=prof_detected,
        professional_columns_with_values=professional_columns_with_values,
    )
