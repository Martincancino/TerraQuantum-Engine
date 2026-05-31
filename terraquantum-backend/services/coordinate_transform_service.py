import math
from typing import List, Sequence, Tuple

import numpy as np
from pyproj import Transformer

from schemas.geophysics_schema import GravityObservation
from schemas.gravity_import_schema import CoordSystemDetection, CoordinateTransform


METERS_PER_DEG_LAT = 111_320.0
LATLON_PRECISION_EXTENT_WARNING_M = 100_000.0
# If any coordinate magnitude exceeds this, the data is already projected (UTM / local mine grid)
_PROJECTED_MAGNITUDE_THRESHOLD = 10_000.0


def _raw_bounds(observations: Sequence[GravityObservation]) -> tuple[float | None, float | None, float | None, float | None]:
    if not observations:
        return None, None, None, None

    xs = [obs.x_m for obs in observations]
    zs = [obs.z_m for obs in observations]
    return min(xs), max(xs), min(zs), max(zs)


def _is_effectively_zero(value: float | None, tolerance: float = 1e-9) -> bool:
    return value is not None and abs(value) <= tolerance


def _build_shifted_observations(
    observations: Sequence[GravityObservation],
    x_values_m: Sequence[float],
    z_values_m: Sequence[float],
) -> tuple[List[GravityObservation], float, float]:
    if not observations:
        return [], 0.0, 0.0

    x_min = min(x_values_m)
    z_min = min(z_values_m)
    shifted_x = [value - x_min for value in x_values_m]
    shifted_z = [value - z_min for value in z_values_m]

    transformed = [
        GravityObservation(x_m=x, y_m=obs.y_m, z_m=z, g=obs.g)
        for obs, x, z in zip(observations, shifted_x, shifted_z)
    ]

    return transformed, max(shifted_x) - min(shifted_x), max(shifted_z) - min(shifted_z)


def _latlon_to_local_meters(
    observations: Sequence[GravityObservation],
    detection: CoordSystemDetection,
) -> Tuple[List[GravityObservation], CoordinateTransform]:
    x_min_raw, x_max_raw, z_min_raw, z_max_raw = _raw_bounds(observations)
    if not observations:
        return [], CoordinateTransform(
            input_coordinate_system=detection.detected,
            input_confidence=detection.confidence,
            method="local_equirectangular",
        )

    lons = [obs.x_m for obs in observations]
    lats = [obs.z_m for obs in observations]

    # Smart detection: if values exceed threshold, they are already projected coordinates
    # (UTM or local mine grid). Applying lat/lon reprojection would be physically wrong.
    if max(abs(v) for v in lons + lats) > _PROJECTED_MAGNITUDE_THRESHOLD:
        transformed, x_extent_m, z_extent_m = _build_shifted_observations(
            observations, lons, lats,
        )
        easting_min = float(x_min_raw) if x_min_raw is not None else 0.0
        northing_min = float(z_min_raw) if z_min_raw is not None else 0.0
        return transformed, CoordinateTransform(
            input_coordinate_system=detection.detected,
            input_confidence=detection.confidence,
            method="projected_local_shift",
            origin_input_coordinates={"easting_min": x_min_raw, "northing_min": z_min_raw},
            x_min_raw=x_min_raw,
            z_min_raw=z_min_raw,
            x_max_raw=x_max_raw,
            z_max_raw=z_max_raw,
            x_extent_m=x_extent_m,
            z_extent_m=z_extent_m,
            transformed=True,
            warnings=[
                "Valores de coordenada > 10,000 detectados; asumiendo coordenadas proyectadas "
                "(UTM o Local Mine Grid). No se intentó reproyectar desde lat/lon."
            ],
            precision_notes=["Detección automática: CRS proyectado. Solo local shift aplicado."],
            crs_source="inferred",
            absolute_origin={"easting": easting_min, "northing": northing_min},
        )

    # Valid lat/lon range: vectorized UTM reprojection via pyproj
    lons_arr = np.array(lons, dtype=np.float64)
    lats_arr = np.array(lats, dtype=np.float64)
    mean_lon = float(np.mean(lons_arr))
    mean_lat = float(np.mean(lats_arr))

    utm_zone_int = int((mean_lon + 180) / 6) + 1
    epsg = 32700 + utm_zone_int if mean_lat < 0 else 32600 + utm_zone_int
    utm_zone_str = f"{utm_zone_int}{'S' if mean_lat < 0 else 'N'}"
    utm_hemisphere = "S" if mean_lat < 0 else "N"

    warnings: list[str] = []
    try:
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        # Vectorized: transforms entire arrays in one call — no Python loop over points
        east_m, north_m = transformer.transform(lons_arr, lats_arr)
        method = "utm_pyproj_vectorized"
        precision_notes = [
            f"Reproyección UTM zona {utm_zone_str} (EPSG:{epsg}) via pyproj vectorizado.",
        ]
    except Exception as exc:
        # Fallback to equirectangular approximation if pyproj unexpectedly fails at runtime
        cos_lat0 = math.cos(math.radians(mean_lat))
        east_m = np.array([(lon - mean_lon) * METERS_PER_DEG_LAT * cos_lat0 for lon in lons])
        north_m = np.array([(lat - mean_lat) * METERS_PER_DEG_LAT for lat in lats])
        method = "local_equirectangular_fallback"
        precision_notes = ["Fallback equirectangular: pyproj falló en ejecución."]
        warnings.append(f"pyproj falló: {exc}. Usando aproximación equirectangular.")

    easting_min = float(np.min(east_m))
    northing_min = float(np.min(north_m))

    transformed, x_extent_m, z_extent_m = _build_shifted_observations(
        observations,
        east_m.tolist(),
        north_m.tolist(),
    )

    if max(x_extent_m, z_extent_m) > LATLON_PRECISION_EXTENT_WARNING_M:
        warnings.append(
            "Extent convertido supera 100 km; distorsión UTM puede aumentar en los bordes."
        )

    return transformed, CoordinateTransform(
        input_coordinate_system=detection.detected,
        input_confidence=detection.confidence,
        method=method,
        origin_input_coordinates={
            "lon0": mean_lon,
            "lat0": mean_lat,
            "x_min_raw": x_min_raw,
            "z_min_raw": z_min_raw,
        },
        x_min_raw=x_min_raw,
        z_min_raw=z_min_raw,
        x_max_raw=x_max_raw,
        z_max_raw=z_max_raw,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
        transformed=True,
        warnings=warnings,
        precision_notes=precision_notes,
        crs_source="inferred",
        epsg_code=epsg,
        utm_zone=utm_zone_str,
        utm_hemisphere=utm_hemisphere,
        absolute_origin={"easting": easting_min, "northing": northing_min},
    )


def _utm_to_local_meters(
    observations: Sequence[GravityObservation],
    detection: CoordSystemDetection,
) -> Tuple[List[GravityObservation], CoordinateTransform]:
    x_min_raw, x_max_raw, z_min_raw, z_max_raw = _raw_bounds(observations)
    transformed, x_extent_m, z_extent_m = _build_shifted_observations(
        observations,
        [obs.x_m for obs in observations],
        [obs.z_m for obs in observations],
    )
    transformed_flag = not (_is_effectively_zero(x_min_raw) and _is_effectively_zero(z_min_raw))

    utm_zone = getattr(detection, "utm_zone", None)
    utm_hemisphere = getattr(detection, "utm_hemisphere", None)
    epsg_code = getattr(detection, "epsg_code", None)
    crs_source = getattr(detection, "crs_source", "missing") or "missing"

    if utm_zone:
        precision_note = (
            f"UTM zona {utm_zone} detectada. "
            "Normalización de origen local aplicada. "
            "Reproyección geodésica pendiente (R2.2)."
        )
    else:
        precision_note = "No se realizó reproyección geográfica. Solo normalización de origen local."

    easting_min = float(x_min_raw) if x_min_raw is not None else 0.0
    northing_min = float(z_min_raw) if z_min_raw is not None else 0.0

    return transformed, CoordinateTransform(
        input_coordinate_system=detection.detected,
        input_confidence=detection.confidence,
        method="utm_sw_origin_shift",
        origin_input_coordinates={
            "easting_min": x_min_raw,
            "northing_min": z_min_raw,
        },
        x_min_raw=x_min_raw,
        z_min_raw=z_min_raw,
        x_max_raw=x_max_raw,
        z_max_raw=z_max_raw,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
        transformed=transformed_flag,
        precision_notes=[precision_note],
        utm_zone=utm_zone,
        utm_hemisphere=utm_hemisphere,
        epsg_code=epsg_code,
        crs_source=crs_source,
        absolute_origin={"easting": easting_min, "northing": northing_min},
    )


def _local_meters_to_canonical(
    observations: Sequence[GravityObservation],
    detection: CoordSystemDetection,
) -> Tuple[List[GravityObservation], CoordinateTransform]:
    x_min_raw, x_max_raw, z_min_raw, z_max_raw = _raw_bounds(observations)
    transformed, x_extent_m, z_extent_m = _build_shifted_observations(
        observations,
        [obs.x_m for obs in observations],
        [obs.z_m for obs in observations],
    )
    transformed_flag = not (_is_effectively_zero(x_min_raw) and _is_effectively_zero(z_min_raw))

    return transformed, CoordinateTransform(
        input_coordinate_system=detection.detected,
        input_confidence=detection.confidence,
        method="local_meters_sw_origin_shift",
        origin_input_coordinates={
            "x_min_raw": x_min_raw,
            "z_min_raw": z_min_raw,
        },
        x_min_raw=x_min_raw,
        z_min_raw=z_min_raw,
        x_max_raw=x_max_raw,
        z_max_raw=z_max_raw,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
        transformed=transformed_flag,
        crs_source="missing",
    )


def _identity_fallback(
    observations: Sequence[GravityObservation],
    detection: CoordSystemDetection,
) -> Tuple[List[GravityObservation], CoordinateTransform]:
    x_min_raw, x_max_raw, z_min_raw, z_max_raw = _raw_bounds(observations)
    transformed, x_extent_m, z_extent_m = _build_shifted_observations(
        observations,
        [obs.x_m for obs in observations],
        [obs.z_m for obs in observations],
    )
    transformed_flag = not (_is_effectively_zero(x_min_raw) and _is_effectively_zero(z_min_raw))

    return transformed, CoordinateTransform(
        input_coordinate_system=detection.detected,
        input_confidence=detection.confidence,
        method="sw_origin_shift_low_confidence",
        origin_input_coordinates={
            "x_min_raw": x_min_raw,
            "z_min_raw": z_min_raw,
        },
        x_min_raw=x_min_raw,
        z_min_raw=z_min_raw,
        x_max_raw=x_max_raw,
        z_max_raw=z_max_raw,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
        transformed=transformed_flag,
        warnings=[
            "Sistema de coordenadas desconocido o de baja confianza; se trató como metros locales y se normalizó al origen SW."
        ],
    )


def transform_coordinates(
    observations: Sequence[GravityObservation],
    coordinate_system: CoordSystemDetection,
) -> Tuple[List[GravityObservation], CoordinateTransform]:
    detected = (coordinate_system.detected or "unknown").lower()
    confidence = (coordinate_system.confidence or "low").lower()

    if detected == "latlon" and confidence != "low":
        return _latlon_to_local_meters(observations, coordinate_system)
    if detected == "utm" and confidence != "low":
        return _utm_to_local_meters(observations, coordinate_system)
    if detected == "local_meters" and confidence != "low":
        return _local_meters_to_canonical(observations, coordinate_system)

    return _identity_fallback(observations, coordinate_system)
