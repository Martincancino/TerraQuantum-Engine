import csv
import math
from pathlib import Path
from typing import List, Optional

import numpy as np

from schemas.geophysics_schema import GravityObservation
from schemas.gravity_import_schema import (
    AutoGrid,
    CoordinateTransform,
    CsvAnalysisResult,
    GravityImportMetadata,
    GravityImportResult,
)
from core.logging import get_logger
from services.coordinate_transform_service import transform_coordinates
from services.csv_analysis_service import (
    analyze_csv_observations,
    CORRECTION_ALIASES,
    ELEVATION_ALIASES,
    INSTRUMENT_ALIASES,
    UNCERTAINTY_ALIASES,
)
from services.grid_calculator_service import compute_auto_grid
from scipy.spatial import cKDTree as _cKDTree

_log = get_logger(__name__)

ALLOWED_UNITS = {"m/s2", "m/s²", "mGal", "uGal", "µGal"}
ALLOWED_GRAVITY_TYPES = {
    "absolute_gravity",
    "g_raw",            # alias de absolute_gravity (datos de campo sin corregir)
    "corrected_gravity",
    "free_air_anomaly",
    "free_air_mgal",
    "bouguer_anomaly",
    "bouguer_mgal",
    "complete_bouguer_anomaly",
    "residual_anomaly",
    "residual_gravity",
    "terrain_corrected_bouguer",
    "magnetic_only",
    "synthetic_demo",
}
GRAVITY_COLUMN_PRIORITY = [
    "gravity_anomaly",
    "g_corrected",
    "complete_bouguer_anomaly",
    "bouguer_anomaly",
    "free_air_anomaly",
    "cba",
    "faa",
    "gravity_mgal",
    "g_mgal",
    "observed_gravity",
    "observed_g",
    "residual_gravity",
    "gravity",
    "g",
    "g_raw",
]

# ---------------------------------------------------------------------------
# R3.5-J — Flexible coordinate column aliases
# Internal convention: x_m slot = east/lon, z_m slot = north/lat
# ---------------------------------------------------------------------------
_LON_ALIASES: frozenset = frozenset({"lon", "longitude", "long", "lon_deg", "x_lon"})
_LAT_ALIASES: frozenset = frozenset({"lat", "latitude", "lat_deg", "y_lat"})
_UTM_EASTING_ALIASES: frozenset = frozenset({"easting", "east", "utm_e", "utm_x", "x_utm"})
_UTM_NORTHING_ALIASES: frozenset = frozenset({"northing", "north", "utm_n", "utm_y", "y_utm"})
_UTM_ZONE_COL_ALIASES: frozenset = frozenset({"utm_zone", "zone", "zone_utm"})
_LOCAL_X_ALIASES: frozenset = frozenset({"x", "local_x", "coord_x"})
_LOCAL_Z_ALIASES: frozenset = frozenset({"z", "local_z", "coord_z"})
_LOCAL_Y_ALIASES: frozenset = frozenset({"y", "local_y", "coord_y"})
_DEPTH_COL_ALIASES: frozenset = frozenset({
    "depth", "depth_m", "depth_below_surface", "depth_below_surface_m",
    "profundidad", "profundidad_m",
})
_ELEVATION_SURFACE_ALIASES: frozenset = frozenset({
    "elevation", "elevation_m", "elev", "elev_m", "rl", "rl_m",
    "altitude", "altitude_m", "height", "height_m", "cota", "cota_m",
})


def _find_first_alias(
    headers_lower: list[str], headers: list[str], aliases: frozenset
) -> "str | None":
    for i, h in enumerate(headers_lower):
        if h in aliases:
            return headers[i]
    return None


def _resolve_coordinate_columns(
    headers_lower: list[str], headers: list[str]
) -> dict:
    """
    Detect coordinate format from CSV headers and return slot mapping.

    coord_type: "legacy" | "latlon" | "utm" | "local" | None
    x_col: original column name for x_m slot (lon / easting / local_x)
    y_col: original column name for y_m slot (depth_m) or None → defaults to 0.0
    z_col: original column name for z_m slot (lat / northing / local_z)
    utm_zone_col: column name carrying utm_zone string, or None
    errors/warnings: validation messages
    raw_cols: mapping of slot → original column name for metadata
    """
    errors: list[str] = []
    warnings: list[str] = []
    h_set = set(headers_lower)

    # 1. Legacy: x_m + z_m present (y_m optional, defaults to 0.0)
    if "x_m" in h_set and "z_m" in h_set:
        x_col = headers[headers_lower.index("x_m")]
        z_col = headers[headers_lower.index("z_m")]
        y_col = headers[headers_lower.index("y_m")] if "y_m" in h_set else None
        if y_col is None:
            warnings.append(
                "No se encontró coordenada vertical/profundidad (y_m); se asumió y_m=0."
            )
        return {
            "coord_type": "legacy",
            "x_col": x_col, "y_col": y_col, "z_col": z_col,
            "utm_zone_col": None,
            "elev_col": _find_first_alias(headers_lower, headers, _ELEVATION_SURFACE_ALIASES),
            "errors": errors, "warnings": warnings,
            "raw_cols": {"x_m": x_col, "z_m": z_col},
        }

    # 2. Lat/lon: lon→x_m slot, lat→z_m slot (matches _latlon_to_local_meters)
    lat_col = _find_first_alias(headers_lower, headers, _LAT_ALIASES)
    lon_col = _find_first_alias(headers_lower, headers, _LON_ALIASES)
    if lat_col and lon_col:
        depth_col = _find_first_alias(headers_lower, headers, _DEPTH_COL_ALIASES)
        elev_col = _find_first_alias(headers_lower, headers, _ELEVATION_SURFACE_ALIASES)
        y_col = depth_col
        if not depth_col and elev_col:
            warnings.append(
                f"Columna de elevación '{elev_col}' detectada. "
                "Las estaciones superficiales usan y_m=0; "
                "el enriquecimiento DEM maneja la elevación MASL."
            )
        if not depth_col:
            warnings.append(
                "No se encontró columna de profundidad (depth_m); se asumió y_m=0."
            )
        return {
            "coord_type": "latlon",
            "x_col": lon_col, "y_col": y_col, "z_col": lat_col,
            "utm_zone_col": None,
            "elev_col": elev_col,  # H-B2: preserved for corrections service
            "errors": errors, "warnings": warnings,
            "raw_cols": {"lat": lat_col, "lon": lon_col},
        }

    # 3. UTM: easting→x_m slot, northing→z_m slot
    east_col = _find_first_alias(headers_lower, headers, _UTM_EASTING_ALIASES)
    north_col = _find_first_alias(headers_lower, headers, _UTM_NORTHING_ALIASES)
    if east_col and north_col:
        depth_col = _find_first_alias(headers_lower, headers, _DEPTH_COL_ALIASES)
        elev_col = _find_first_alias(headers_lower, headers, _ELEVATION_SURFACE_ALIASES)
        utm_zone_col = _find_first_alias(headers_lower, headers, _UTM_ZONE_COL_ALIASES)
        y_col = depth_col
        if not depth_col and elev_col:
            warnings.append(
                f"Columna de elevación '{elev_col}' detectada. "
                "Las estaciones superficiales usan y_m=0."
            )
        if not depth_col:
            warnings.append(
                "No se encontró columna de profundidad (depth_m); se asumió y_m=0."
            )
        return {
            "coord_type": "utm",
            "x_col": east_col, "y_col": y_col, "z_col": north_col,
            "utm_zone_col": utm_zone_col,
            "elev_col": elev_col,  # topografía activa (sensor_elevations_masl)
            "errors": errors, "warnings": warnings,
            "raw_cols": {"easting": east_col, "northing": north_col},
        }

    # 4. Local aliases without x_m/z_m
    local_x_col = _find_first_alias(headers_lower, headers, _LOCAL_X_ALIASES)
    if not local_x_col and "x_m" in h_set:
        local_x_col = headers[headers_lower.index("x_m")]
    local_z_col = _find_first_alias(headers_lower, headers, _LOCAL_Z_ALIASES)
    if not local_z_col and "z_m" in h_set:
        local_z_col = headers[headers_lower.index("z_m")]
    if local_x_col and local_z_col:
        local_y_col = _find_first_alias(headers_lower, headers, _LOCAL_Y_ALIASES)
        if not local_y_col and "y_m" in h_set:
            local_y_col = headers[headers_lower.index("y_m")]
        depth_col = _find_first_alias(headers_lower, headers, _DEPTH_COL_ALIASES)
        y_col = local_y_col or depth_col
        if not y_col:
            warnings.append(
                "No se encontró coordenada vertical/profundidad; se asumió y_m=0."
            )
        return {
            "coord_type": "local",
            "x_col": local_x_col, "y_col": y_col, "z_col": local_z_col,
            "utm_zone_col": None,
            "elev_col": _find_first_alias(headers_lower, headers, _ELEVATION_SURFACE_ALIASES),
            "errors": errors, "warnings": warnings,
            "raw_cols": {"x": local_x_col, "z": local_z_col},
        }

    errors.append(
        "No se encontraron columnas de coordenadas válidas. "
        "Se requiere: (x_m, z_m), (lat/lon), (easting/northing), o (x, z)."
    )
    return {
        "coord_type": None,
        "x_col": None, "y_col": None, "z_col": None, "utm_zone_col": None,
        "errors": errors, "warnings": warnings, "raw_cols": {},
    }


def normalize_unit(unit: str) -> str:
    return unit.strip()

def convert_to_ms2(value: float, unit: str) -> float:
    u = normalize_unit(unit)
    if u in ("m/s2", "m/s²"):
        return value
    elif u == "mGal":
        return value * 0.00001
    elif u in ("uGal", "µGal"):
        return value * 0.00000001
    raise ValueError(f"Unknown unit: {unit}")

def parse_float(value: str, field_name: str, row_number: int) -> float:
    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Row {row_number}: NaN or Inf not allowed for {field_name}")
        return val
    except ValueError as e:
        raise ValueError(f"Row {row_number}: Invalid numeric value for {field_name}: '{value}'")

def choose_gravity_column(headers: list[str]) -> str | None:
    headers_lower = [h.strip().lower() for h in headers]
    for col in GRAVITY_COLUMN_PRIORITY:
        if col in headers_lower:
            idx = headers_lower.index(col)
            return headers[idx]
    return None

def normalize_header_name(header: str) -> str:
    return header.replace("\ufeff", "").strip()

def import_gravity_csv_v1(file_path: str | Path, strict: bool = True, allow_g_raw: bool = False) -> GravityImportResult:
    _log.info("import_gravity_csv_start", file=str(file_path))
    path = Path(file_path)
    warnings_list = []
    errors_list = []
    
    if not path.exists():
        errors_list.append(f"File not found: {path}")
        return _build_error_result(path.name, errors_list, warnings_list)
        
    try:
        import pandas as pd
        df = pd.read_csv(path, sep=r'[,;]', engine='python', encoding='utf-8', on_bad_lines='skip')
        
        if df.empty and len(df.columns) == 0:
            errors_list.append("Empty file or missing headers")
            return _build_error_result(path.name, errors_list, warnings_list)
        
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        df = df.fillna("")
        
        headers = [normalize_header_name(str(h)) for h in df.columns if h]
        
        reader = []
        for row in df.to_dict(orient='records'):
            clean_row = {}
            for orig_h, clean_h in zip(df.columns, headers):
                clean_row[clean_h] = str(row[orig_h])
            reader.append(clean_row)
            
        headers_lower = [h.lower() for h in headers]

        if "unit" not in headers_lower:
            errors_list.append("Missing required column: unit")

        # R3.5-K — station_id is optional; auto-generate if column absent
        _sid_idx = next(
            (i for i, h in enumerate(headers_lower) if h == "station_id"), None
        )
        _station_id_original_col: "str | None" = (
            headers[_sid_idx] if _sid_idx is not None else None
        )
        if _station_id_original_col is None:
            warnings_list.append(
                "No se encontró station_id; se generaron IDs automáticos por orden de fila."
            )

        coord_map = _resolve_coordinate_columns(headers_lower, headers)
        if coord_map["coord_type"] is None:
            errors_list.extend(coord_map["errors"])
        else:
            warnings_list.extend(coord_map["warnings"])
        
        gravity_col = choose_gravity_column(headers)
        if not gravity_col:
            errors_list.append("Missing gravity column (g, gravity_anomaly, g_corrected, or g_raw)")
        elif gravity_col.lower() == "g_raw" and not allow_g_raw:
            errors_list.append("Only g_raw is present but allow_g_raw is False")
        
        if strict and "gravity_type" not in headers:
            errors_list.append("Missing required column: gravity_type (strict mode)")
            
        if errors_list:
            return _build_error_result(path.name, errors_list, warnings_list)
            
        observations = []
        raw_gravity_values = []
        raw_latlon_elev_list: "list[dict]" = []  # H-B2: per-station lat/lon/elev (latlon surveys)
        # Topografía activa + sigma por estación (cualquier tipo de coordenada)
        station_elev_list: "list[float]" = []      # m s.n.m. (NaN si ausente)
        station_unc_list: "list[float]" = []       # mGal (NaN si ausente)
        _elev_col_any = coord_map.get("elev_col")
        _unc_col_any = _find_first_alias(headers_lower, headers, UNCERTAINTY_ALIASES)
        dup_coords_log = []
        seen_coords = set()
        exact_duplicate_count = 0
        row_count = 0
        valid_rows = 0
        rejected_rows = 0

        first_unit = None
        first_gravity_type = None
        first_utm_zone: "str | None" = None
        
        has_uncertainty = "uncertainty" in headers
        has_timestamp = "timestamp" in headers
        has_instrument_id = "instrument_id" in headers
        has_quality_flag = "quality_flag" in headers
        
        if not has_uncertainty:
            warnings_list.append("Missing recommended column: uncertainty")
        if not has_timestamp:
            warnings_list.append("Missing professional column: timestamp")
        if not has_instrument_id:
            warnings_list.append("Missing professional column: instrument_id")
        if not has_quality_flag:
            warnings_list.append("Missing recommended column: quality_flag")
            
        if gravity_col and gravity_col.lower() in ("gravity_anomaly", "g_corrected"):
            if "lat" not in headers or "lon" not in headers:
                warnings_list.append("Professional format but missing lat/lon")
                
        if gravity_col and gravity_col.lower() == "g_corrected":
            warnings_list.append("Using g_corrected instead of gravity_anomaly")
        if gravity_col and gravity_col.lower() == "g_raw" and allow_g_raw:
            warnings_list.append("Using g_raw. Data might lack geological reliability.")

        # R3.5-I-FIX1: Build professional column map for value-presence detection
        _all_prof_aliases = (
            ELEVATION_ALIASES | UNCERTAINTY_ALIASES | INSTRUMENT_ALIASES | CORRECTION_ALIASES
        )
        _prof_col_map: dict[str, str] = {}
        for _i, _hl in enumerate(headers_lower):
            if _hl in _all_prof_aliases:
                _prof_col_map[_hl] = headers[_i]
        _prof_col_values: dict[str, list[str]] = {col: [] for col in _prof_col_map}

        for row_num, row in enumerate(reader, start=2):
            row_count += 1
            # R3.5-I-FIX1: Collect raw professional column values before validation
            for _col_lower, _col_orig in _prof_col_map.items():
                _prof_col_values[_col_lower].append(
                    str(row.get(_col_orig, "") or "").strip()
                )
            try:
                # R3.5-K — use existing column or fall back to auto-generated ID
                if _station_id_original_col:
                    station_id = row.get(_station_id_original_col, "").strip()
                    if not station_id:
                        station_id = f"ST_{row_count:06d}"
                else:
                    station_id = f"ST_{row_count:06d}"
                    
                unit = row.get("unit", "").strip()
                if not unit:
                    raise ValueError(f"Row {row_num}: Empty unit")
                if unit not in ALLOWED_UNITS:
                    raise ValueError(f"Row {row_num}: Unsupported unit: {unit}")
                if first_unit is None:
                    first_unit = unit
                elif unit != first_unit:
                    raise ValueError("Mixed units are not allowed in TerraQuantum Gravity CSV v1")
                
                g_type = row.get("gravity_type", "").strip()
                if strict and not g_type:
                    raise ValueError(f"Row {row_num}: gravity_type cannot be empty in strict mode")
                if g_type:
                    if g_type not in ALLOWED_GRAVITY_TYPES:
                        raise ValueError(f"Row {row_num}: Unsupported gravity_type: {g_type}")
                    if first_gravity_type is None:
                        first_gravity_type = g_type
                        if g_type == "synthetic_demo":
                            warnings_list.append("Data is marked as synthetic_demo")
                    elif g_type != first_gravity_type:
                        raise ValueError(f"Row {row_num}: Mixed gravity_type values are not allowed")
                        
                raw_x = row.get(coord_map["x_col"], "").strip() if coord_map["x_col"] else ""
                if not raw_x:
                    raise ValueError(
                        f"Row {row_num}: Empty/missing x coordinate "
                        f"(column '{coord_map['x_col']}')"
                    )
                x = parse_float(raw_x, coord_map["x_col"] or "x", row_num)

                raw_z = row.get(coord_map["z_col"], "").strip() if coord_map["z_col"] else ""
                if not raw_z:
                    raise ValueError(
                        f"Row {row_num}: Empty/missing z coordinate "
                        f"(column '{coord_map['z_col']}')"
                    )
                z = parse_float(raw_z, coord_map["z_col"] or "z", row_num)

                # F2.0 — Hard Reject: coordenadas geográficas imposibles (lat/lon invertidos)
                if coord_map["coord_type"] == "latlon":
                    if abs(z) > 90 or abs(x) > 180:
                        raise ValueError(
                            f"Row {row_num}: Coordenadas imposibles. "
                            "Posible inversión de Latitud y Longitud."
                        )

                if coord_map["y_col"]:
                    raw_y = row.get(coord_map["y_col"], "").strip()
                    y = parse_float(raw_y, coord_map["y_col"], row_num) if raw_y else 0.0
                else:
                    y = 0.0

                if coord_map["utm_zone_col"] and first_utm_zone is None:
                    first_utm_zone = row.get(coord_map["utm_zone_col"], "").strip() or None
                
                coord_tuple = (x, y, z)
                if coord_tuple in seen_coords:
                    exact_duplicate_count += 1
                    rejected_rows += 1
                    _log.warning(
                        "csv_duplicate_coords_rejected",
                        row_num=row_num,
                        x_m=x, y_m=y, z_m=z,
                    )
                    if len(dup_coords_log) < 3:
                        dup_coords_log.append(
                            {
                                "row_number": row_num,
                                "coordinates": {
                                    "x_m": x,
                                    "y_m": y,
                                    "z_m": z,
                                },
                            }
                        )
                    continue
                seen_coords.add(coord_tuple)
                
                g_val = parse_float(row.get(gravity_col, ""), gravity_col, row_num)
                g_converted = convert_to_ms2(g_val, unit)
                
                obs = GravityObservation(x_m=x, y_m=y, z_m=z, g=g_converted)
                observations.append(obs)
                raw_gravity_values.append(g_val)
                valid_rows += 1

                # Elevación de estación (m s.n.m.) — paralela a observations
                _st_elev = float("nan")
                if _elev_col_any:
                    _ev = row.get(_elev_col_any, "").strip()
                    try:
                        _st_elev = float(_ev) if _ev else float("nan")
                    except (ValueError, TypeError):
                        _st_elev = float("nan")
                station_elev_list.append(_st_elev)

                # Incertidumbre por estación → mGal (misma unidad declarada que g)
                _st_unc = float("nan")
                if _unc_col_any:
                    _uv = row.get(_unc_col_any, "").strip()
                    try:
                        _st_unc = convert_to_ms2(float(_uv), unit) * 1e5 if _uv else float("nan")
                    except (ValueError, TypeError):
                        _st_unc = float("nan")
                station_unc_list.append(_st_unc)

                # H-B2: capture raw lat/lon/elev for corrections service (latlon surveys only)
                if coord_map.get("coord_type") == "latlon":
                    _elev_col = coord_map.get("elev_col")
                    if _elev_col:
                        _raw_elev_str = row.get(_elev_col, "").strip()
                        try:
                            _raw_elev = float(_raw_elev_str) if _raw_elev_str else float("nan")
                        except (ValueError, TypeError):
                            _raw_elev = float("nan")
                    else:
                        _raw_elev = float("nan")
                    raw_latlon_elev_list.append({
                        "lat_deg": z,   # z slot = latitude before transform
                        "lon_deg": x,   # x slot = longitude before transform
                        "elev_m": _raw_elev,
                    })
            except ValueError as e:
                error_msg = str(e)
                errors_list.append(error_msg)
                rejected_rows += 1
                _log.warning("csv_row_rejected", row_num=row_num, reason=error_msg)
        
        csv_analysis = analyze_csv_observations(
            observations=observations,
            declared_unit=first_unit,
            raw_gravity_values=raw_gravity_values,
            exact_duplicate_count=exact_duplicate_count,
            exact_duplicate_examples=dup_coords_log,
            warnings=warnings_list,
            column_names=headers,
            professional_column_values=_prof_col_values if _prof_col_map else None,
        )
        if first_utm_zone:
            csv_analysis.coordinate_system.utm_zone = first_utm_zone

        # Column names are authoritative evidence of coordinate type.
        # Value-range inference (_infer_coordinate_system) fails for regional surveys
        # (e.g. 350 km Bouguer grids) where spans exceed the 200 km threshold.
        # When the column resolver found a clear coord_type but inference returned
        # "unknown", trust the column names.
        _COORD_TYPE_TO_DETECTED = {
            "legacy": "local_meters",
            "local": "local_meters",
            "latlon": "latlon",
            "utm": "utm",
        }
        if (
            coord_map.get("coord_type") is not None
            and csv_analysis.coordinate_system.detected == "unknown"
        ):
            csv_analysis.coordinate_system.detected = _COORD_TYPE_TO_DETECTED.get(
                coord_map["coord_type"], "local_meters"
            )
            csv_analysis.coordinate_system.confidence = "high"
            csv_analysis.coordinate_system.warning = None

        warnings_list = list(csv_analysis.warnings)
        observations, coordinate_transform = transform_coordinates(
            observations,
            csv_analysis.coordinate_system,
        )
        if coord_map.get("raw_cols"):
            coordinate_transform.origin_input_coordinates["raw_coord_cols"] = (
                coord_map["raw_cols"]
            )
        auto_grid = compute_auto_grid(
            x_extent_m=coordinate_transform.x_extent_m,
            z_extent_m=coordinate_transform.z_extent_m,
            observation_count=csv_analysis.observation_count,
            quality_label=csv_analysis.quality_label,
        )
        csv_analysis.coordinate_transform = coordinate_transform
        csv_analysis.auto_grid = auto_grid
        warnings_list = list(
            dict.fromkeys(
                warnings_list
                + coordinate_transform.warnings
                + auto_grid.warnings
            )
        )
        csv_analysis.warnings = warnings_list
        conversion_applied = first_unit not in ("m/s2", "m/sÂ²") if first_unit else False
        is_demo = first_gravity_type == "synthetic_demo"

        if errors_list:
            return _build_error_result(
                path.name,
                errors_list,
                warnings_list,
                csv_analysis=csv_analysis,
                row_count=row_count,
                valid_rows=valid_rows,
                rejected_rows=rejected_rows,
                unit_original=first_unit,
                gravity_column_used=gravity_col,
                gravity_type=first_gravity_type,
                conversion_applied=conversion_applied,
                is_demo=is_demo,
                coordinate_transform=coordinate_transform,
                auto_grid=auto_grid,
            )
            
        if valid_rows < 10:
            errors_list.append("Less than 10 valid observations")
            return _build_error_result(
                path.name,
                errors_list,
                warnings_list,
                csv_analysis=csv_analysis,
                row_count=row_count,
                valid_rows=valid_rows,
                rejected_rows=rejected_rows,
                unit_original=first_unit,
                gravity_column_used=gravity_col,
                gravity_type=first_gravity_type,
                conversion_applied=conversion_applied,
                is_demo=is_demo,
                coordinate_transform=coordinate_transform,
                auto_grid=auto_grid,
            )
            
        if (
            first_gravity_type != "magnetic_only"
            and all(math.isclose(obs.g, 0.0, abs_tol=1e-15) for obs in observations)
        ):
            errors_list.append("All normalized gravity values are zero or near zero")
            return _build_error_result(
                path.name,
                errors_list,
                warnings_list,
                csv_analysis=csv_analysis,
                row_count=row_count,
                valid_rows=valid_rows,
                rejected_rows=rejected_rows,
                unit_original=first_unit,
                gravity_column_used=gravity_col,
                gravity_type=first_gravity_type,
                conversion_applied=conversion_applied,
                is_demo=is_demo,
                coordinate_transform=coordinate_transform,
                auto_grid=auto_grid,
            )
            
        xs = [o.x_m for o in observations]
        zs = [o.z_m for o in observations]
        span_x = max(xs) - min(xs)
        span_z = max(zs) - min(zs)
        if span_x < 1.0 and span_z < 1.0:
            warnings_list.append("Low spatial coverage: span_x and span_z are very low")

        # F2.0 — Spatial near-duplicate check en coordenadas métricas (post-transformación)
        if len(observations) >= 2:
            _coords_m = np.array([[o.x_m, o.y_m, o.z_m] for o in observations])
            if _cKDTree(_coords_m).query_pairs(r=0.1):
                warnings_list.append(
                    "Estaciones duplicadas o espaciamiento degenerado detectado."
                )

        gs = [o.g for o in observations]
        g_range = max(gs) - min(gs)
        if g_range < 1e-12:
            warnings_list.append("Low dynamic range: gravity variance is almost zero")

        # ---- QC FÍSICO DURO (Fase 2) ----
        g_mgal = np.array([obs.g for obs in observations]) * 1e5
        if np.any(np.isnan(g_mgal)) or np.any(np.isinf(g_mgal)):
            errors_list.append(
                "Datos corruptos: se detectaron valores NaN o Infinitos en la columna de gravedad"
            )
            return _build_error_result(
                path.name, errors_list, warnings_list,
                csv_analysis=csv_analysis, row_count=row_count, valid_rows=valid_rows,
                rejected_rows=rejected_rows, unit_original=first_unit,
                gravity_column_used=gravity_col, gravity_type=first_gravity_type,
                conversion_applied=conversion_applied, is_demo=is_demo,
                coordinate_transform=coordinate_transform, auto_grid=auto_grid,
            )
        if first_gravity_type != "magnetic_only" and np.std(g_mgal) < 1e-6:
            errors_list.append(
                "Varianza casi cero detectada. Los datos no contienen anomalías medibles"
            )
            return _build_error_result(
                path.name, errors_list, warnings_list,
                csv_analysis=csv_analysis, row_count=row_count, valid_rows=valid_rows,
                rejected_rows=rejected_rows, unit_original=first_unit,
                gravity_column_used=gravity_col, gravity_type=first_gravity_type,
                conversion_applied=conversion_applied, is_demo=is_demo,
                coordinate_transform=coordinate_transform, auto_grid=auto_grid,
            )
        # Gravedad absoluta (~9.8e5 mGal) solo es válida en el flujo de datos de
        # campo (allow_g_raw + tipo crudo), donde las correcciones FAC/BC/TC se
        # aplican después del import. En cualquier otro caso sigue siendo error.
        _is_raw_type = (
            (first_gravity_type or "").strip() in ("g_raw", "absolute_gravity")
            or (gravity_col or "").lower() == "g_raw"
        )
        if np.any(np.abs(g_mgal) > 1000.0):
            if allow_g_raw and _is_raw_type:
                # Plausibilidad física: gravedad en superficie terrestre
                # ≈ 976 000–983 000 mGal (con elevaciones 0–9 km).
                if np.any((g_mgal < 970_000.0) | (g_mgal > 990_000.0)):
                    errors_list.append(
                        "Valores de gravedad absoluta fuera del rango físico terrestre "
                        "[970000, 990000] mGal. Verificar unidades y columna de gravedad."
                    )
                    return _build_error_result(
                        path.name, errors_list, warnings_list,
                        csv_analysis=csv_analysis, row_count=row_count, valid_rows=valid_rows,
                        rejected_rows=rejected_rows, unit_original=first_unit,
                        gravity_column_used=gravity_col, gravity_type=first_gravity_type,
                        conversion_applied=conversion_applied, is_demo=is_demo,
                        coordinate_transform=coordinate_transform, auto_grid=auto_grid,
                    )
                warnings_list.append(
                    "Gravedad absoluta detectada (~9.8e5 mGal). Se requieren "
                    "correcciones GRS80/FAC/BC/TC antes de invertir; el flujo "
                    "/v2/gravity-import/invert-with-corrections las aplica automáticamente."
                )
            else:
                errors_list.append(
                    "Anomalía supera los 1000 mGal. Se requiere Anomalía de Bouguer o Residual, no Gravedad Absoluta"
                )
                return _build_error_result(
                    path.name, errors_list, warnings_list,
                    csv_analysis=csv_analysis, row_count=row_count, valid_rows=valid_rows,
                    rejected_rows=rejected_rows, unit_original=first_unit,
                    gravity_column_used=gravity_col, gravity_type=first_gravity_type,
                    conversion_applied=conversion_applied, is_demo=is_demo,
                    coordinate_transform=coordinate_transform, auto_grid=auto_grid,
                )
        if np.any(np.abs(g_mgal) > 100.0):
            warnings_list.append(
                "Large gravity anomaly detected (>100 mGal). Verify Bouguer/residual correction."
            )

        if len(warnings_list) != len(csv_analysis.warnings):
            warnings_list = list(dict.fromkeys(warnings_list))
            csv_analysis.warnings = warnings_list
        
        meta = GravityImportMetadata(
            source_file=path.name,
            schema_version="TerraQuantum Gravity CSV v1",
            unit_original=first_unit,
            unit_internal="m/s²",
            gravity_column_used=gravity_col,
            gravity_type=first_gravity_type,
            conversion_applied=conversion_applied,
            row_count=row_count,
            valid_rows=valid_rows,
            rejected_rows=rejected_rows,
            warnings=warnings_list,
            errors=errors_list,
            is_demo=is_demo,
            csv_analysis=csv_analysis,
            coordinate_transform=coordinate_transform,
            auto_grid=auto_grid
        )
        
        # Topografía/sigma por estación: solo si hay al menos un valor real
        _has_elev_vals = any(not math.isnan(v) for v in station_elev_list)
        _has_unc_vals = any(not math.isnan(v) for v in station_unc_list)

        return GravityImportResult(
            status="ok",
            observations=observations,
            import_metadata=meta,
            warnings=warnings_list,
            errors=errors_list,
            csv_analysis=csv_analysis,
            coordinate_transform=coordinate_transform,
            auto_grid=auto_grid,
            # H-B2: only populated for latlon surveys; None otherwise
            raw_latlon_elev=raw_latlon_elev_list if raw_latlon_elev_list else None,
            station_elevations=station_elev_list if _has_elev_vals else None,
            station_uncertainties=station_unc_list if _has_unc_vals else None,
        )
        
    except Exception as e:
        errors_list.append(f"File parsing error: {str(e)}")
        return _build_error_result(path.name, errors_list, warnings_list)

def calculate_optimal_block_size(
    x_m: list[float],
    z_m: list[float],
    nx: int = 32,
    nz: int = 32,
    min_block_size: float = 25.0,
) -> float:
    """
    Calcula blockSize para que la malla nx×nz cubra la extensión completa del dataset.
    Evita que perfiles con blockSize sintético (ej. 25 m) subestimulen datasets regionales.
    """
    x_extent = max(x_m) - min(x_m)
    z_extent = max(z_m) - min(z_m)

    if x_extent <= 0 or z_extent <= 0:
        return min_block_size

    block_size_x = x_extent / nx
    block_size_z = z_extent / nz

    optimal = max(block_size_x, block_size_z)
    return max(optimal, min_block_size)


def auto_compute_grid_params(
    x_m: list[float],
    z_m: list[float],
    depth_m: float,
    frontend_nx: int,
    frontend_ny: int,
    frontend_nz: int,
    frontend_block_size: int | float,
    max_voxels: int = 100_000,
) -> dict:
    """
    Legacy A1.0 grid helper. A1.3 flow uses services.grid_calculator_service.compute_auto_grid.

    Calcula nx, ny, nz y block_size para cubrir automáticamente el extent real del CSV.
    Preserva la grilla pedida por frontend cuando ya cubre el área y no excede el límite.
    """
    def clamp(value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, value))

    def build_result(
        nx: int,
        ny: int,
        nz: int,
        block_size: int | float,
        auto_adapted: bool,
        reason: str,
        extent_x_m: float | None,
        extent_z_m: float | None,
    ) -> dict:
        effective_nx = clamp(int(nx), 4, 80)
        effective_ny = clamp(int(ny), 4, 80)
        effective_nz = clamp(int(nz), 4, 80)
        effective_block_size = int(max(25, min(10_000, math.ceil(float(block_size)))))

        return {
            "nx": effective_nx,
            "ny": effective_ny,
            "nz": effective_nz,
            "block_size": effective_block_size,
            "auto_adapted": auto_adapted,
            "reason": reason,
            "extent_x_m": extent_x_m,
            "extent_z_m": extent_z_m,
            "total_voxels": effective_nx * effective_ny * effective_nz,
        }

    if not x_m or not z_m:
        return build_result(
            frontend_nx,
            frontend_ny,
            frontend_nz,
            frontend_block_size,
            False,
            "empty_observations",
            None,
            None,
        )

    extent_x = max(x_m) - min(x_m)
    extent_z = max(z_m) - min(z_m)

    if extent_x < 1.0 or extent_z < 1.0:
        return build_result(
            frontend_nx,
            frontend_ny,
            frontend_nz,
            frontend_block_size,
            False,
            "degenerate_extent",
            extent_x,
            extent_z,
        )

    frontend_bs = float(frontend_block_size)
    frontend_total = frontend_nx * frontend_ny * frontend_nz
    covers_x = frontend_bs > 0 and (frontend_nx * frontend_bs) >= extent_x
    covers_z = frontend_bs > 0 and (frontend_nz * frontend_bs) >= extent_z
    voxels_ok = frontend_total <= max_voxels

    if covers_x and covers_z and voxels_ok:
        return build_result(
            frontend_nx,
            frontend_ny,
            frontend_nz,
            frontend_block_size,
            False,
            "frontend_grid_covers_dataset",
            extent_x,
            extent_z,
        )

    max_extent = max(extent_x, extent_z)
    depth_safe = max(float(depth_m), 1.0)
    block_size = max_extent / 40.0
    block_size = max(block_size, depth_safe / 80.0)
    block_size = int(max(25.0, min(10_000.0, math.ceil(block_size))))

    nx = clamp(math.ceil(extent_x / block_size), 4, 80)
    ny = clamp(math.ceil(depth_safe / block_size), 4, 80)
    nz = clamp(math.ceil(extent_z / block_size), 4, 80)

    while nx * ny * nz > max_voxels and block_size < 10_000:
        block_size = min(10_000, int(block_size * 1.1) + 1)
        nx = clamp(math.ceil(extent_x / block_size), 4, 80)
        ny = clamp(math.ceil(depth_safe / block_size), 4, 80)
        nz = clamp(math.ceil(extent_z / block_size), 4, 80)

    if ny * block_size < depth_safe:
        block_size = int(max(25.0, min(10_000.0, math.ceil(depth_safe / ny))))
        nx = clamp(math.ceil(extent_x / block_size), 4, 80)
        nz = clamp(math.ceil(extent_z / block_size), 4, 80)

    reason_parts = []
    if not covers_x or not covers_z:
        reason_parts.append("frontend_grid_does_not_cover_dataset")
    if not voxels_ok:
        reason_parts.append("frontend_grid_exceeds_voxel_budget")
    reason = ", ".join(reason_parts) if reason_parts else "auto_grid_recomputed"

    return build_result(
        nx,
        ny,
        nz,
        block_size,
        True,
        reason,
        extent_x,
        extent_z,
    )


def _build_error_result(
    filename: str,
    errors: List[str],
    warnings: List[str],
    csv_analysis: Optional[CsvAnalysisResult] = None,
    coordinate_transform: Optional[CoordinateTransform] = None,
    auto_grid: Optional[AutoGrid] = None,
    row_count: int = 0,
    valid_rows: int = 0,
    rejected_rows: int = 0,
    unit_original: Optional[str] = None,
    gravity_column_used: Optional[str] = None,
    gravity_type: Optional[str] = None,
    conversion_applied: bool = False,
    is_demo: bool = False,
) -> GravityImportResult:
    meta = GravityImportMetadata(
        source_file=filename,
        schema_version="TerraQuantum Gravity CSV v1",
        unit_original=unit_original,
        gravity_column_used=gravity_column_used,
        gravity_type=gravity_type,
        conversion_applied=conversion_applied,
        row_count=row_count,
        valid_rows=valid_rows,
        rejected_rows=rejected_rows,
        warnings=warnings,
        errors=errors,
        is_demo=is_demo,
        csv_analysis=csv_analysis,
        coordinate_transform=coordinate_transform,
        auto_grid=auto_grid
    )
    return GravityImportResult(
        status="error",
        observations=[],
        import_metadata=meta,
        warnings=warnings,
        errors=errors,
        csv_analysis=csv_analysis,
        coordinate_transform=coordinate_transform,
        auto_grid=auto_grid
    )


# ═════════════════════════════════════════════════════════════════════════════
# Flujo de datos de campo — CSV crudo → FAC/BC/TC/GRS80 → inversión → UBC-GIF
# (POST /v2/gravity-import/invert-with-corrections)
# ═════════════════════════════════════════════════════════════════════════════

# Tipos que YA traen las correcciones aplicadas (no se re-corrigen).
_FIELD_ALREADY_CORRECTED = {
    "free_air_anomaly", "free_air_mgal",
    "bouguer_anomaly", "bouguer_mgal",
    "complete_bouguer_anomaly", "terrain_corrected_bouguer",
    "residual_anomaly", "residual_gravity",
    "corrected_gravity", "synthetic_demo",
}

# Mapeo gravity_type del CSV → Literal de GeophysicsInvertInputV2.
_FIELD_TYPE_TO_V2 = {
    "free_air_anomaly": "free_air_anomaly",
    "free_air_mgal": "free_air_anomaly",
    "bouguer_anomaly": "bouguer_anomaly",
    "bouguer_mgal": "bouguer_anomaly",
    "complete_bouguer_anomaly": "complete_bouguer_anomaly",
    "terrain_corrected_bouguer": "complete_bouguer_anomaly",
}

# Correcciones del meta del servicio → Literal del schema V2.
_CORR_META_TO_V2 = {
    "latitude_grs80": "latitude",
    "free_air": "free_air",
    "bouguer": "bouguer",
    "terrain": "terrain",
}


async def _fetch_terrain_correction(
    lats: np.ndarray,
    lons: np.ndarray,
    elevs: np.ndarray,
    dem_type: str,
    terrain_radius_m: float,
    reduction_density_gcc: float,
    warnings_out: List[str],
) -> "Optional[np.ndarray]":
    """TC best-effort vía OpenTopography. None si DEM/API no disponible."""
    try:
        from services.opentopo_service import fetch_dem_for_survey, compute_tc_from_dem
        buffer_deg = terrain_radius_m / 111_000.0 + 0.01
        lat_1d, lon_1d, elev_2d, cell_deg, _src = await fetch_dem_for_survey(
            south=float(np.min(lats)), north=float(np.max(lats)),
            west=float(np.min(lons)), east=float(np.max(lons)),
            dem_type=dem_type, buffer_deg=buffer_deg,
        )
        tc = compute_tc_from_dem(
            stations_lat=lats, stations_lon=lons, stations_elev_m=elevs,
            dem_lat_1d=lat_1d, dem_lon_1d=lon_1d, dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_deg,
            terrain_radius_m=terrain_radius_m,
            reduction_density_gcc=reduction_density_gcc,
        )
        return np.asarray(tc, dtype=np.float64)
    except Exception as exc:
        warnings_out.append(
            f"Corrección de terreno (TC) omitida: {exc}. "
            "La anomalía resultante es Bouguer simple (FAC+BC sin TC)."
        )
        return None


async def run_field_data_inversion_with_corrections(
    csv_path: "str | Path",
    project_id: str,
    run_id: str,
    gravimeter_type: str = "unknown",
    reduction_density_gcc: float = 2.67,
    apply_terrain: bool = True,
    terrain_radius_m: float = 22000.0,
    dem_type: str = "COP30",
    noise_pct: float = 0.0,
    inversion_overrides: Optional[dict] = None,
) -> dict:
    """
    Flujo completo de datos de campo (Plan Industrial Fase 1 + H-B2 producción):

        CSV crudo → FAC+BC+TC+GRS80 automáticas → sigma = piso del gravímetro
        → inversión W_z formal → obs vs calc → UBC-GIF → inversion_report.json

    - gravity_type crudo (g_raw / absolute_gravity) + lat/lon/elev → correcciones
      automáticas con reduction_density_gcc; CSV corregido persiste en
      runs/{rid}/gravity_corrected.csv.
    - gravity_type ya corregido (bouguer/complete_bouguer/...) → se usa tal cual.
    - sigma_i = max(GRAVIMETER_NOISE_FLOOR[gravimeter_type], noise_pct·|d_i|).

    Devuelve dict con corrections_summary, inversion_results, validation y exports.
    Lanza ValueError en errores de input (la API lo mapea a 422).
    """
    from core.config import (
        GRAVIMETER_NOISE_FLOOR,
        RUN_BLOCK_MODEL_FILENAME,
    )

    overrides = dict(inversion_overrides or {})
    warnings_out: List[str] = []

    # ── 1. Import + detección de columnas ────────────────────────────────────
    import_result = import_gravity_csv_v1(csv_path, strict=False, allow_g_raw=True)
    if import_result.status != "ok":
        raise ValueError(
            "Import CSV falló: " + "; ".join(import_result.errors[:5])
        )
    warnings_out.extend(import_result.warnings)

    gravity_type_in = (import_result.import_metadata.gravity_type or "").strip()
    raw_obs = import_result.observations
    n_stations = len(raw_obs)
    g_raw_mgal = np.array([o.g for o in raw_obs], dtype=np.float64) * 1e5

    has_latlon = (
        import_result.raw_latlon_elev is not None
        and len(import_result.raw_latlon_elev) == n_stations
    )

    # ── 2. Correcciones automáticas ───────────────────────────────────────────
    corrections_applied_v2: List[str] = []
    corrections_summary: dict = {}
    corr_meta: dict = {}
    effective_observations = list(raw_obs)
    g_corrected_mgal = g_raw_mgal.copy()
    output_gravity_type = _FIELD_TYPE_TO_V2.get(gravity_type_in, "bouguer_anomaly")

    needs_corrections = gravity_type_in not in _FIELD_ALREADY_CORRECTED

    if needs_corrections and not has_latlon:
        warnings_out.append(
            "gravity_type crudo pero el CSV no trae lat/lon por estación: "
            "correcciones FAC/BC/TC NO aplicadas. La inversión usa los datos tal cual. "
            "Para el flujo completo, incluir columnas lat, lon y elev_m."
        )
    elif needs_corrections:
        from services.gravity_corrections_service import (
            apply_all_corrections,
            compute_normal_gravity_mgal,
            compute_free_air_correction,
            compute_bouguer_correction,
        )

        lats = np.array([s["lat_deg"] for s in import_result.raw_latlon_elev])
        lons = np.array([s["lon_deg"] for s in import_result.raw_latlon_elev])
        elevs_raw = np.array([s["elev_m"] for s in import_result.raw_latlon_elev])

        has_elev = not np.all(np.isnan(elevs_raw)) and not np.all(elevs_raw == 0.0)
        elevs = np.where(np.isnan(elevs_raw), 0.0, elevs_raw)
        if not has_elev:
            warnings_out.append(
                "Sin columna de elevación con valores: FAC/BC/TC omitidas "
                "(solo corrección de latitud GRS80)."
            )

        tc_values = None
        if apply_terrain and has_elev:
            tc_values = await _fetch_terrain_correction(
                lats, lons, elevs, dem_type, terrain_radius_m,
                reduction_density_gcc, warnings_out,
            )

        g_corrected_mgal, corr_meta = apply_all_corrections(
            lats_deg=lats,
            lons_deg=lons,
            elevs_m=elevs,
            g_obs_mgal=g_raw_mgal,
            gravity_type_in=gravity_type_in or "g_raw",
            reduction_density_gcc=reduction_density_gcc,
            apply_lat=True,
            apply_fac=has_elev,
            apply_bouguer=has_elev,
            apply_terrain=tc_values is not None,
            tc_values_mgal=tc_values,
        )

        effective_observations = [
            GravityObservation(x_m=o.x_m, y_m=o.y_m, z_m=o.z_m, g=float(gc) * 1e-5)
            for o, gc in zip(raw_obs, g_corrected_mgal)
        ]
        corrections_applied_v2 = [
            _CORR_META_TO_V2[c] for c in corr_meta.get("corrections_applied", [])
            if c in _CORR_META_TO_V2
        ]
        output_gravity_type = _FIELD_TYPE_TO_V2.get(
            corr_meta.get("output_gravity_type", ""), "bouguer_anomaly"
        )

        # Resumen por componente (mismas fórmulas que apply_all_corrections)
        delta_cba_mean = float(np.mean(g_corrected_mgal - g_raw_mgal))
        corrections_summary = {
            "gamma_grs80_mean_mgal": round(float(np.mean(compute_normal_gravity_mgal(lats))), 2),
            "fac_mean_mgal": round(float(np.mean(compute_free_air_correction(elevs, lats))), 4) if has_elev else None,
            "bc_mean_mgal": round(float(np.mean(compute_bouguer_correction(elevs, reduction_density_gcc))), 4) if has_elev else None,
            "tc_mean_mgal": round(float(np.mean(tc_values)), 4) if tc_values is not None else None,
            "total_correction_mgal": round(delta_cba_mean, 4),
            "reduction_density_gcc": reduction_density_gcc,
            "cba_mean_mgal": round(float(np.mean(g_corrected_mgal)), 4),
            "cba_std_mgal": round(float(np.std(g_corrected_mgal)), 4),
        }
        _log.info(
            "field_corrections_applied",
            corrections=corr_meta.get("corrections_applied", []),
            delta_cba_mean_mgal=round(delta_cba_mean, 4),
            n_stations=n_stations,
        )
        print(
            f"[FIELD FLOW] Correcciones aplicadas: "
            f"{', '.join(corr_meta.get('corrections_applied', []))} — "
            f"delta_CBA media = {delta_cba_mean:.2f} mGal"
        )
    else:
        warnings_out.append(
            f"gravity_type='{gravity_type_in}' ya está corregido: se usa tal cual "
            "(sin re-aplicar FAC/BC/TC)."
        )

    # ── 3. Persistir CSV corregido en el run dir ──────────────────────────────
    from core.block_model_store import get_run_source_gravity_csv_path
    source_csv_path = get_run_source_gravity_csv_path(project_id, run_id)
    run_dir = source_csv_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    import shutil as _shutil
    _shutil.copyfile(str(csv_path), str(source_csv_path))

    corrected_csv_path = run_dir / "gravity_corrected.csv"
    with open(corrected_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "station_id", "x_m", "y_m", "z_m",
            "lat", "lon", "elev_m",
            "g_raw_mgal", "g_corrected_mgal", "unit", "gravity_type",
        ])
        for i, o in enumerate(effective_observations):
            _ll = import_result.raw_latlon_elev[i] if has_latlon else {}
            writer.writerow([
                f"ST_{i + 1:06d}",
                o.x_m, o.y_m, o.z_m,
                _ll.get("lat_deg", ""), _ll.get("lon_deg", ""), _ll.get("elev_m", ""),
                round(float(g_raw_mgal[i]), 6),
                round(float(g_corrected_mgal[i]), 6),
                "mGal",
                corr_meta.get("output_gravity_type", gravity_type_in or "unknown"),
            ])

    # ── 4. Construir input de inversión (grid auto + overrides del usuario) ──
    auto_grid = import_result.auto_grid
    if auto_grid is None and import_result.csv_analysis:
        auto_grid = import_result.csv_analysis.auto_grid
    if auto_grid is None:
        raise ValueError("auto_grid no disponible tras importar CSV.")

    _max_dim = 80

    def _eff(name: str, auto_val, cast=int, max_val=None):
        v = overrides.get(name)
        if v is None or (isinstance(v, (int, float)) and v <= 0):
            v = auto_val
        v = cast(math.ceil(v)) if cast is int else cast(v)
        if max_val is not None and v > max_val:
            v = cast(max_val)
        return v

    nx = _eff("nx", auto_grid.nx, max_val=_max_dim)
    ny = _eff("ny", auto_grid.ny, max_val=_max_dim)
    nz = _eff("nz", auto_grid.nz, max_val=_max_dim)
    block_size = _eff("block_size", auto_grid.block_size_m)
    depth = _eff("depth", auto_grid.depth_m, max_val=ny * block_size)
    cutoff_radius = _eff("cutoff_radius", auto_grid.cutoff_radius_m, cast=float)
    lambda_mag = float(overrides.get("lambda_mag") or 3.0)   # operating point validado
    alpha_spatial = float(overrides.get("alpha_spatial") or 1.0)

    # Sigma: σ por estación (columna uncertainty del CSV) > piso por gravímetro.
    noise_floor_mgal = float(
        GRAVIMETER_NOISE_FLOOR.get(gravimeter_type, GRAVIMETER_NOISE_FLOOR["unknown"])
    )
    sigma_source = f"gravimeter_table[{gravimeter_type}]"
    _unc_list = import_result.station_uncertainties
    if _unc_list:
        _unc_finite = sorted(u for u in _unc_list if u == u and u > 0.0)
        if len(_unc_finite) >= max(3, len(_unc_list) // 2):
            noise_floor_mgal = float(_unc_finite[len(_unc_finite) // 2])
            sigma_source = "csv_uncertainty_column_median"
            warnings_out.append(
                f"Sigma fijado desde la columna uncertainty del CSV: piso = "
                f"{noise_floor_mgal:.4g} mGal (mediana por estación, prioridad "
                "sobre la tabla de gravímetros)."
            )

    # Topografía activa: elevaciones por estación si el relieve es significativo.
    sensor_elevations = None
    _se_list = import_result.station_elevations
    if _se_list and len(_se_list) == len(effective_observations):
        _se_finite = [v for v in _se_list if v == v]
        if len(_se_finite) == len(_se_list) and (max(_se_finite) - min(_se_finite)) >= 10.0:
            sensor_elevations = [float(v) for v in _se_list]
            warnings_out.append(
                f"Topografía activa: elevaciones {min(_se_finite):.0f}–{max(_se_finite):.0f} m "
                "aplicadas como máscara topográfica."
            )

    from schemas.geophysics_schema import GeophysicsInvertInputV2
    invert_input = GeophysicsInvertInputV2(
        project_id=project_id,
        run_id=run_id,
        depth=depth,
        nir=0,
        fe=0,
        region=str(overrides.get("region") or "field_data"),
        lat=str(overrides["lat"]) if overrides.get("lat") is not None else None,
        lon=str(overrides["lon"]) if overrides.get("lon") is not None else None,
        nx=nx, ny=ny, nz=nz,
        block_size=block_size,
        cutoff_radius=cutoff_radius,
        lambda_mag=lambda_mag,
        alpha_spatial=alpha_spatial,
        observations=effective_observations,
        enable_focusing=True,
        gravity_type=output_gravity_type,
        corrections_applied=corrections_applied_v2,
        noise_floor_mgal=noise_floor_mgal,
        noise_pct=float(noise_pct),
        sensor_elevations_masl=sensor_elevations,
        gravimeter_type=gravimeter_type,
        lambda_strategy="fixed",
        lambda_fixed=lambda_mag,
        auto_lambda=False,
        # Default industrial v2: 0.0 (permite contrastes negativos). Con
        # no-negatividad estricta (density_min=base=2.6) el LSQR+clip degrada
        # el misfit ~35% en cuerpos compactos (lóbulos negativos recortados).
        density_min=float(overrides.get("density_min", 0.0)),
        density_max=float(overrides.get("density_max", 5.5)),
        auto_params_metadata={
            "version": "field_data_flow_v1",
            "gravity_corrections": corr_meta,
            "gravimeter_type": gravimeter_type,
            "noise_floor_mgal": noise_floor_mgal,
            "noise_pct": float(noise_pct),
            "corrected_csv": str(corrected_csv_path),
        },
    )

    # ── 5. Inversión (W_z formal, sigma = piso instrumental) ─────────────────
    from services.geophysics_service import run_geophysics_inversion
    inversion_result = run_geophysics_inversion(invert_input)
    report = inversion_result.get("report", {}) or {}
    fit = report.get("fitDiagnostics", {}) or {}

    # ── 6. Validación obs vs calc (r²) ────────────────────────────────────────
    obs_vs_calc_path = run_dir / "obs_vs_calc.parquet"
    obs_vs_calc_r2 = None
    if obs_vs_calc_path.exists():
        try:
            import polars as _pl
            _df_ovc = _pl.read_parquet(str(obs_vs_calc_path))
            _do = _df_ovc["d_obs"].to_numpy()
            _dp = _df_ovc["d_pred"].to_numpy()
            _ss_res = float(np.sum((_do - _dp) ** 2))
            _ss_tot = float(np.sum((_do - np.mean(_do)) ** 2))
            obs_vs_calc_r2 = round(1.0 - _ss_res / max(_ss_tot, 1e-30), 6)
        except Exception as _r2_exc:
            warnings_out.append(f"No fue posible calcular r² obs vs calc: {_r2_exc}")
    else:
        warnings_out.append("obs_vs_calc.parquet no generado por el solver.")

    # ── 7. Export UBC-GIF (.msh + .den) desde el block model persistido ──────
    ubc_paths: dict = {}
    try:
        import polars as _pl
        _bm_path = run_dir / RUN_BLOCK_MODEL_FILENAME
        _df_bm = _pl.read_parquet(str(_bm_path))
        _idx = (
            _df_bm["ix"].to_numpy()
            + nx * _df_bm["iy"].to_numpy()
            + nx * ny * _df_bm["iz"].to_numpy()
        )
        _density_full = np.full(nx * ny * nz, np.nan, dtype=np.float64)
        _density_full[_idx] = _df_bm["density_t_m3"].to_numpy()

        # Permutación de ejes TerraQuantum → UBC-GIF:
        # TQ: (x=Este, y=profundidad hacia abajo, z=Norte), Fortran (nx, ny, nz).
        # UBC: (Este, Norte, Z hacia arriba). El exportador hace flip del último
        # eje, así que se entrega con índice 0 = fondo (Z-up).
        _arr3d = _density_full.reshape((nx, ny, nz), order="F")      # (E, depth, N)
        _arr_ubc = np.transpose(_arr3d, (0, 2, 1))[:, :, ::-1]       # (E, N, Z-up)

        from services.export_service import export_core_to_ubc
        _ubc = export_core_to_ubc(
            output_dir=str(run_dir),
            run_prefix="model",
            nx=nx, ny=nz, nz=ny,                     # UBC: nE, nN, nZ
            dx=float(block_size),
            est_density=np.ascontiguousarray(_arr_ubc).ravel(order="F"),
            origin_z=-float(ny * block_size),        # techo del modelo = superficie (0 m)
            project_id=project_id,
            run_id=run_id,
        )
        if _ubc:
            ubc_paths = {
                "ubc_msh_path": _ubc.get("mesh_path"),
                "ubc_den_path": _ubc.get("model_path"),
                "n_cells": _ubc.get("n_cells"),
            }
        else:
            warnings_out.append("Export UBC-GIF no disponible para esta corrida.")
    except Exception as _ubc_exc:
        warnings_out.append(f"Export UBC-GIF falló: {_ubc_exc}")

    # ── 8. Reporte JSON con limitaciones honestas ─────────────────────────────
    chi2_red = report.get("chi2_final")
    rmse_ms2 = fit.get("residual_rmse")
    nrmse_pct = (
        round(float(fit.get("normalized_rmse", 0.0)) * 100.0, 4)
        if fit.get("normalized_rmse") is not None else None
    )
    n_active = (report.get("r05_geometry_audit") or {}).get("observable_voxels")

    # Guard de degradación (mismo criterio que la ruta v1)
    _mis_v2 = inversion_result.get("misfit_error_percent")
    if _mis_v2 is not None and float(_mis_v2) > 50.0:
        warnings_out.append(
            f"MODELO DEGRADADO: misfit {float(_mis_v2):.0f}% — NO usar para interpretación. "
            "Revisar cutoff_radius, lambda, bounds de densidad y correcciones."
        )
    _obs_ratio_v2 = (report.get("r05_geometry_audit") or {}).get("observable_ratio")
    if _obs_ratio_v2 is not None and float(_obs_ratio_v2) < 0.5:
        warnings_out.append(
            f"COBERTURA INSUFICIENTE: solo {float(_obs_ratio_v2) * 100:.0f}% de los vóxeles "
            "activos es sensado (cutoff_radius pequeño para el espaciamiento del survey)."
        )

    response: dict = {
        "status": "success",
        "project_id": project_id,
        "run_id": run_id,
        "gravity_type_in": gravity_type_in or "unknown",
        "gravity_type_used": output_gravity_type,
        "gravimeter_type": gravimeter_type,
        "corrections_applied": corr_meta.get("corrections_applied", []),
        "corrections_summary": corrections_summary,
        "sigma_model": {
            "formula": "sigma_i = max(noise_floor, noise_pct * |d_i|)",
            "noise_floor_mgal": noise_floor_mgal,
            "noise_pct": float(noise_pct),
            "source": sigma_source,
        },
        "inversion_results": {
            "chi_squared_reduced": chi2_red,
            "rmse_ms2": rmse_ms2,
            "nrmse_pct": nrmse_pct,
            "misfit_error_percent": inversion_result.get("misfit_error_percent"),
            "n_observations": n_stations,
            "n_active_voxels": n_active,
            "lambda_used": report.get("lambda_used"),
            "grid": {"nx": nx, "ny": ny, "nz": nz, "block_size_m": block_size, "depth_m": depth},
        },
        "validation": {
            "obs_vs_calc_r2": obs_vs_calc_r2,
            "obs_vs_calc_parquet": str(obs_vs_calc_path) if obs_vs_calc_path.exists() else None,
            "depth_weighting": {
                "scheme": "W_z formal Li & Oldenburg: (depth+z0)^(beta/2), beta=2.0",
                "verified_by": "tests/test_field_data_complete_flow.py (esfera 400m, error <15%)",
            },
            "kernel": {
                "type": "prisma rectangular (Nagy 1966) / HPC KDTree",
                "verified_by": "tests/audit_groundtruth_validation.py (H-A2)",
            },
        },
        "exports": {
            **ubc_paths,
            "block_model_parquet": str(run_dir / RUN_BLOCK_MODEL_FILENAME),
            "report_json": str(run_dir / "inversion_report.json"),
        },
        "limitations": [
            "La inversión gravimétrica es intrínsecamente no-única: la profundidad "
            "recuperada depende del depth weighting y de restricciones externas.",
            "Validado a escala local (<10 km). A escala regional (>50 km) se requiere "
            "separación regional-residual y restricciones geológicas.",
            "El modelo de densidad NO constituye una estimación de recursos "
            "JORC/NI 43-101; es un insumo de exploración temprana.",
            "TC por prismas usa aproximación de masa puntual en campo lejano; "
            "para terreno abrupto (>500 m de relieve local) validar con TC dedicado.",
            "La inversión suaviza en profundidad (smearing): la profundidad del "
            "pico de densidad es más confiable que el centroide del cuerpo recuperado.",
            "Con no-negatividad estricta (density_min=2.6) el solver LSQR+clip puede "
            "degradar el misfit en cuerpos compactos; el default v2 (density_min=0.0) "
            "permite contrastes negativos y ajusta al nivel del ruido.",
        ],
        "warnings": warnings_out,
    }

    report_json_path = run_dir / "inversion_report.json"
    try:
        import json as _json
        with open(report_json_path, "w", encoding="utf-8") as f:
            _json.dump(response, f, indent=2, ensure_ascii=False, default=str)
    except Exception as _rep_exc:
        warnings_out.append(f"inversion_report.json no persistido: {_rep_exc}")

    return response
