import math
from typing import Any

from schemas.gravity_import_schema import RegionalScalePreflight


_DEPTH_LOCAL_WARNING = (
    "La profundidad estimada excede una escala típica de modelo minero local; "
    "revise parámetros o use subset/tile."
)
_DEPTH_REGIONAL_WARNING = (
    "La profundidad estimada corresponde a escala regional; no debe interpretarse "
    "como modelo minero local."
)
_BBOX_APPROXIMATE_WARNING = (
    "La ventana de subset sugerida es aproximada; "
    "valide las coordenadas antes de uso operacional."
)


def _suggest_tile_size_m(scale_class: str) -> float | None:
    # Heurística inicial conservadora — no es verdad geofísica.
    if scale_class in ("TOO_LARGE_SINGLE_INVERSION", "REGIONAL_SCALE"):
        return 10_000.0
    return None


def _build_suggested_subset_bbox(
    extent_x_m: float | None,
    extent_z_m: float | None,
    tile_size_m: float | None,
) -> dict[str, float] | None:
    if tile_size_m is None or extent_x_m is None or extent_z_m is None:
        return None
    half = tile_size_m / 2.0
    center_x = extent_x_m / 2.0
    center_z = extent_z_m / 2.0
    return {
        "x_min_m": round(max(0.0, center_x - half), 2),
        "x_max_m": round(min(extent_x_m, center_x + half), 2),
        "z_min_m": round(max(0.0, center_z - half), 2),
        "z_max_m": round(min(extent_z_m, center_z + half), 2),
    }


def _value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _float_or_none(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if math.isfinite(candidate) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extent_or_none(value: Any) -> float | None:
    candidate = _float_or_none(value)
    if candidate is None or candidate < 0:
        return None
    return candidate


def _depth_warnings(estimated_depth_m: float | None) -> list[str]:
    warnings: list[str] = []
    if estimated_depth_m is None:
        return warnings
    if estimated_depth_m > 5_000:
        warnings.append(_DEPTH_LOCAL_WARNING)
    if estimated_depth_m > 20_000:
        warnings.append(_DEPTH_REGIONAL_WARNING)
    return warnings


def _dimension_overflow_reasons(
    *,
    estimated_nx: int | None,
    estimated_ny: int | None,
    estimated_nz: int | None,
    max_allowed_nx: int,
    max_allowed_ny: int,
    max_allowed_nz: int,
) -> list[str]:
    reasons: list[str] = []
    for axis, estimate, limit in (
        ("nx", estimated_nx, max_allowed_nx),
        ("ny", estimated_ny, max_allowed_ny),
        ("nz", estimated_nz, max_allowed_nz),
    ):
        if estimate is not None and estimate > limit:
            reasons.append(f"estimated_{axis}={estimate} > max_allowed_{axis}={limit}.")
    return reasons


def classify_regional_scale_preflight(
    *,
    extent_x_m: float | None,
    extent_z_m: float | None,
    station_count: int | None,
    estimated_nx: int | None,
    estimated_ny: int | None,
    estimated_nz: int | None,
    estimated_voxel_count: int | None,
    estimated_depth_m: float | None,
    estimated_block_size_m: float | None = None,
    max_allowed_nx: int = 80,
    max_allowed_ny: int = 80,
    max_allowed_nz: int = 80,
) -> RegionalScalePreflight:
    safe_x_extent = _extent_or_none(extent_x_m)
    safe_z_extent = _extent_or_none(extent_z_m)
    safe_depth = _float_or_none(estimated_depth_m)
    safe_block_size = _float_or_none(estimated_block_size_m)
    safe_nx = _int_or_none(estimated_nx)
    safe_ny = _int_or_none(estimated_ny)
    safe_nz = _int_or_none(estimated_nz)
    safe_voxel_count = _int_or_none(estimated_voxel_count)
    safe_station_count = _int_or_none(station_count)

    warnings = _depth_warnings(safe_depth)
    blocked_reasons = _dimension_overflow_reasons(
        estimated_nx=safe_nx,
        estimated_ny=safe_ny,
        estimated_nz=safe_nz,
        max_allowed_nx=max_allowed_nx,
        max_allowed_ny=max_allowed_ny,
        max_allowed_nz=max_allowed_nz,
    )

    max_extent = (
        max(safe_x_extent, safe_z_extent)
        if safe_x_extent is not None and safe_z_extent is not None
        else None
    )
    area_km2 = (
        (safe_x_extent * safe_z_extent) / 1_000_000.0
        if safe_x_extent is not None and safe_z_extent is not None
        else None
    )

    if blocked_reasons:
        scale_class = "TOO_LARGE_SINGLE_INVERSION"
        can_run_single_inversion = False
        requires_user_acknowledgement = False
        recommended_action = (
            "Inversion unica no recomendada para este dataset. "
            "Cree un subset o aplique tileado para reducir la ventana de interes."
        )
        allowed_outputs = ["preview", "subset", "tile"]
        suggested_tile_size_m = _suggest_tile_size_m("TOO_LARGE_SINGLE_INVERSION")
        suggested_subset_bbox = _build_suggested_subset_bbox(
            safe_x_extent, safe_z_extent, suggested_tile_size_m
        )
        if suggested_subset_bbox is not None:
            warnings.append(_BBOX_APPROXIMATE_WARNING)
        rationale = (
            "La grilla estimada reutilizada desde auto_grid excede al menos un "
            "limite por dimension del schema de inversion."
        )
    elif max_extent is None:
        scale_class = "UNKNOWN_SCALE"
        can_run_single_inversion = True
        requires_user_acknowledgement = False
        recommended_action = (
            "Revise el extent y la grilla estimada antes de interpretar la escala."
        )
        warnings.append(
            "No hay extent horizontal suficiente para clasificar la escala del dataset."
        )
        allowed_outputs = ["preview"]
        suggested_tile_size_m = None
        suggested_subset_bbox = None
        rationale = (
            "La clasificacion queda indeterminada porque falta extent_x_m o "
            "extent_z_m."
        )
    elif max_extent <= 10_000:
        scale_class = "LOCAL_SURVEY"
        can_run_single_inversion = True
        requires_user_acknowledgement = False
        recommended_action = (
            "Puede continuar con la inversion unica usando la grilla estimada."
        )
        allowed_outputs = ["preview", "single_inversion"]
        suggested_tile_size_m = None
        suggested_subset_bbox = None
        rationale = (
            "El extent maximo es local y la grilla estimada cabe en los limites "
            "por dimension."
        )
    elif max_extent <= 30_000:
        scale_class = "DISTRICT_SCALE"
        can_run_single_inversion = True
        requires_user_acknowledgement = False
        recommended_action = (
            "Puede invertir una vez, revisando la escala y los parametros del modelo."
        )
        warnings.append(
            "Dataset de escala distrital: revise la grilla y profundidad estimadas."
        )
        allowed_outputs = ["preview", "single_inversion", "subset"]
        suggested_tile_size_m = None
        suggested_subset_bbox = None
        rationale = (
            "El extent maximo esta sobre escala local pero no excede escala "
            "distrital y la grilla cabe por dimension."
        )
    else:
        scale_class = "REGIONAL_SCALE"
        can_run_single_inversion = True
        requires_user_acknowledgement = True
        recommended_action = (
            "Revise la interpretacion regional y considere subset/tile para "
            "contexto minero local."
        )
        warnings.append(
            "Dataset de escala regional: la inversion unica requiere contexto de escala."
        )
        allowed_outputs = ["preview", "single_inversion", "subset", "tile"]
        suggested_tile_size_m = _suggest_tile_size_m("REGIONAL_SCALE")
        suggested_subset_bbox = _build_suggested_subset_bbox(
            safe_x_extent, safe_z_extent, suggested_tile_size_m
        )
        if suggested_subset_bbox is not None:
            warnings.append(_BBOX_APPROXIMATE_WARNING)
        rationale = (
            "El extent maximo supera 30000 m y la grilla estimada aun cabe en "
            "los limites por dimension."
        )

    return RegionalScalePreflight(
        scale_class=scale_class,
        can_run_single_inversion=can_run_single_inversion,
        requires_user_acknowledgement=requires_user_acknowledgement,
        recommended_action=recommended_action,
        extent_x_m=safe_x_extent,
        extent_z_m=safe_z_extent,
        area_km2=area_km2,
        station_count=safe_station_count,
        estimated_nx=safe_nx,
        estimated_ny=safe_ny,
        estimated_nz=safe_nz,
        estimated_voxel_count=safe_voxel_count,
        estimated_depth_m=safe_depth,
        estimated_block_size_m=safe_block_size,
        max_allowed_nx=max_allowed_nx,
        max_allowed_ny=max_allowed_ny,
        max_allowed_nz=max_allowed_nz,
        warnings=list(dict.fromkeys(warnings)),
        blocked_reasons=blocked_reasons,
        allowed_outputs=allowed_outputs,
        suggested_tile_size_m=suggested_tile_size_m,
        suggested_subset_bbox=suggested_subset_bbox,
        rationale=rationale,
    )


def build_preflight_from_import_result(import_result: Any) -> RegionalScalePreflight:
    csv_analysis = _value(import_result, "csv_analysis")
    import_metadata = _value(import_result, "import_metadata")
    if csv_analysis is None:
        csv_analysis = _value(import_metadata, "csv_analysis")

    coordinate_transform = _value(import_result, "coordinate_transform")
    if coordinate_transform is None:
        coordinate_transform = _value(csv_analysis, "coordinate_transform")
    if coordinate_transform is None:
        coordinate_transform = _value(import_metadata, "coordinate_transform")

    auto_grid = _value(import_result, "auto_grid")
    if auto_grid is None:
        auto_grid = _value(csv_analysis, "auto_grid")
    if auto_grid is None:
        auto_grid = _value(import_metadata, "auto_grid")

    station_count = _int_or_none(_value(csv_analysis, "observation_count"))
    if station_count is None:
        station_count = _int_or_none(_value(import_metadata, "valid_rows"))

    preflight = classify_regional_scale_preflight(
        extent_x_m=_value(coordinate_transform, "x_extent_m"),
        extent_z_m=_value(coordinate_transform, "z_extent_m"),
        station_count=station_count,
        estimated_nx=_value(auto_grid, "nx"),
        estimated_ny=_value(auto_grid, "ny"),
        estimated_nz=_value(auto_grid, "nz"),
        estimated_voxel_count=_value(auto_grid, "voxel_count"),
        estimated_depth_m=_value(auto_grid, "depth_m"),
        estimated_block_size_m=_value(auto_grid, "block_size_m"),
    )

    sampling = _value(csv_analysis, "sampling")
    sampling_area_km2 = _float_or_none(_value(sampling, "area_km2"))
    if sampling_area_km2 is not None:
        preflight.area_km2 = sampling_area_km2

    return preflight
