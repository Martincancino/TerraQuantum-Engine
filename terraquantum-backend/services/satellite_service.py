import datetime
import json
import math
from pathlib import Path

import numpy as np
import scipy.ndimage

from core import block_model_store as store
from core import gee_client
from core.geo_utils import METERS_PER_DEG_LAT, _derive_extent_from_csv, compute_bbox
from core.logging import get_logger
from core.utils import clean_project_id
from schemas.terrain_schema import BBoxData, TerrainMetadata, TerrainResponse


DEFAULT_EXTENT_M = 3_000.0
DEM_ROWS = 32
DEM_COLS = 32
DEM_RESOLUTION = 32
TERRAIN_MARGIN_FACTOR = 1.5

_log = get_logger(__name__)


# ─── Internal helpers ────────────────────────────────────────────────────────


def _project_dir(project_id: str) -> Path:
    return store.PROJECTS_DIR / project_id


def _read_project_center(project_id: str) -> tuple[float, float]:
    project_dir = _project_dir(project_id)

    if not project_dir.exists():
        raise ValueError("Proyecto no encontrado.")

    meta = store.load_project_meta(project_id)

    if not meta:
        raise ValueError("Proyecto sin coordenadas geoespaciales.")

    latitude = meta.get("latitude")
    longitude = meta.get("longitude")

    if latitude is None or longitude is None:
        raise ValueError("Proyecto sin latitude/longitude.")

    try:
        return float(latitude), float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordenadas de proyecto inválidas.") from exc


def _latest_source_gravity_csv(project_id: str) -> Path | None:
    runs_dir = _project_dir(project_id) / "runs"

    if not runs_dir.exists():
        return None

    for run_dir in sorted(
        (path for path in runs_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        csv_path = run_dir / store.RUN_SOURCE_GRAVITY_FILENAME

        if csv_path.exists():
            return csv_path

    return None


def _derive_project_extent(project_id: str) -> tuple[float, float, str]:
    csv_path = _latest_source_gravity_csv(project_id)

    if not csv_path:
        return DEFAULT_EXTENT_M, DEFAULT_EXTENT_M, "mock_v1_no_run"

    try:
        extent_x_m, extent_z_m = _derive_extent_from_csv(csv_path)

        if extent_x_m <= 0 or extent_z_m <= 0:
            raise ValueError("CSV con extent degenerado.")

        return extent_x_m, extent_z_m, "mock_v1"
    except Exception as exc:
        _log.warning(
            "terrain_extent_fallback",
            project_id=project_id,
            csv_path=str(csv_path),
            error=str(exc),
        )
        return DEFAULT_EXTENT_M, DEFAULT_EXTENT_M, "mock_v1_no_run"


# ─── Footprint bbox helper ───────────────────────────────────────────────────

_LATLON_BBOX_WARNING = (
    "Extent derivado de bbox lat/lon con aproximacion equirectangular."
)


def _normalized_bbox(candidate: dict | None) -> dict | None:
    if not isinstance(candidate, dict):
        return None

    try:
        if all(key in candidate for key in ("min_lat", "max_lat", "min_lon", "max_lon")):
            min_lat = float(candidate["min_lat"])
            max_lat = float(candidate["max_lat"])
            min_lon = float(candidate["min_lon"])
            max_lon = float(candidate["max_lon"])
        elif isinstance(candidate.get("sw"), dict) and isinstance(candidate.get("ne"), dict):
            min_lat = float(candidate["sw"]["lat"])
            max_lat = float(candidate["ne"]["lat"])
            min_lon = float(candidate["sw"]["lon"])
            max_lon = float(candidate["ne"]["lon"])
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None

    values = (min_lat, max_lat, min_lon, max_lon)
    if not all(math.isfinite(value) for value in values):
        return None
    if max_lat <= min_lat or max_lon <= min_lon:
        return None

    return {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }


def _bbox_extent_m(bbox: dict | None) -> tuple[float, float] | None:
    normalized = _normalized_bbox(bbox)
    if normalized is None:
        return None

    lat_center = (normalized["min_lat"] + normalized["max_lat"]) / 2.0
    meters_per_deg_lon = METERS_PER_DEG_LAT * max(
        abs(math.cos(math.radians(lat_center))),
        1e-6,
    )
    extent_x_m = (normalized["max_lon"] - normalized["min_lon"]) * meters_per_deg_lon
    extent_z_m = (normalized["max_lat"] - normalized["min_lat"]) * METERS_PER_DEG_LAT
    if extent_x_m <= 0 or extent_z_m <= 0:
        return None

    return extent_x_m, extent_z_m


def _expand_bbox(bbox: dict, margin_factor: float) -> dict | None:
    normalized = _normalized_bbox(bbox)
    if normalized is None:
        return None

    lat_range = normalized["max_lat"] - normalized["min_lat"]
    lon_range = normalized["max_lon"] - normalized["min_lon"]
    lat_margin = lat_range * (margin_factor - 1.0) / 2.0
    lon_margin = lon_range * (margin_factor - 1.0) / 2.0
    return {
        "min_lat": normalized["min_lat"] - lat_margin,
        "max_lat": normalized["max_lat"] + lat_margin,
        "min_lon": normalized["min_lon"] - lon_margin,
        "max_lon": normalized["max_lon"] + lon_margin,
    }


def _footprint_bbox(footprint: dict | None) -> dict | None:
    if not isinstance(footprint, dict):
        return None

    bbox = _normalized_bbox(footprint.get("bbox"))
    if bbox is not None:
        return bbox

    if all(key in footprint for key in ("min_lat", "max_lat", "min_lon", "max_lon")):
        bbox = _normalized_bbox(footprint)
        if bbox is not None:
            return bbox

    corners_lat: list[float] = []
    corners_lon: list[float] = []
    for key in ("sw", "se", "ne", "nw"):
        corner = footprint.get(key) or {}
        lat_val = corner.get("lat")
        lon_val = corner.get("lon")
        if lat_val is None or lon_val is None:
            continue
        try:
            corners_lat.append(float(lat_val))
            corners_lon.append(float(lon_val))
        except (TypeError, ValueError):
            continue

    if len(corners_lat) < 2:
        return None

    return _normalized_bbox({
        "min_lat": min(corners_lat),
        "max_lat": max(corners_lat),
        "min_lon": min(corners_lon),
        "max_lon": max(corners_lon),
    })


def _positive_extent_pair(candidate: dict | None) -> tuple[float, float] | None:
    if not isinstance(candidate, dict):
        return None

    try:
        extent_x_m = float(candidate["extent_x_m"])
        extent_z_m = float(candidate["extent_z_m"])
    except (KeyError, TypeError, ValueError):
        return None

    if not math.isfinite(extent_x_m) or not math.isfinite(extent_z_m):
        return None
    if extent_x_m <= 0 or extent_z_m <= 0:
        return None

    return extent_x_m, extent_z_m


def _derive_footprint_extent(
    footprint: dict | None,
) -> tuple[float, float, str, list[str]] | None:
    footprint_bbox = _footprint_bbox(footprint)
    if footprint_bbox is None or not isinstance(footprint, dict):
        return None

    source = str(footprint.get("source") or "footprint_bbox")
    warnings: list[str] = []
    footprint_source = "latlon_bbox" if source.lower().startswith("latlon") else source

    extent = _positive_extent_pair(footprint)
    if extent is not None:
        if footprint_source == "latlon_bbox":
            warnings.append(_LATLON_BBOX_WARNING)
        return extent[0], extent[1], footprint_source, warnings

    extent = _bbox_extent_m(footprint_bbox)
    if extent is None:
        return None

    warnings.append(_LATLON_BBOX_WARNING)
    return extent[0], extent[1], footprint_source, warnings


def _latest_gravity_import_metadata(project_id: str) -> dict | None:
    runs_dir = _project_dir(project_id) / "runs"
    if not runs_dir.exists():
        return None

    run_dirs = sorted(
        (path for path in runs_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for run_dir in run_dirs:
        metadata_path = run_dir / store.RUN_GRAVITY_IMPORT_METADATA_FILENAME
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(metadata, dict):
            return metadata

    return None


def _coordinate_transform_candidates(metadata: dict | None) -> list[dict]:
    if not isinstance(metadata, dict):
        return []

    candidates = [
        metadata.get("coordinate_transform"),
        (metadata.get("csv_analysis") or {}).get("coordinate_transform"),
        (metadata.get("import_metadata") or {}).get("coordinate_transform"),
        ((metadata.get("import_metadata") or {}).get("csv_analysis") or {}).get(
            "coordinate_transform"
        ),
    ]
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def _latlon_bbox_from_coordinate_transform(coordinate_transform: dict) -> dict | None:
    if str(coordinate_transform.get("input_coordinate_system") or "").lower() != "latlon":
        return None

    return _normalized_bbox({
        "min_lat": coordinate_transform.get("z_min_raw"),
        "max_lat": coordinate_transform.get("z_max_raw"),
        "min_lon": coordinate_transform.get("x_min_raw"),
        "max_lon": coordinate_transform.get("x_max_raw"),
    })


def _utm_extent_from_coordinate_transform(
    coordinate_transform: dict,
) -> tuple[float, float] | None:
    if str(coordinate_transform.get("input_coordinate_system") or "").lower() != "utm":
        return None

    extent = _positive_extent_pair(coordinate_transform)
    if extent is not None:
        return extent

    try:
        extent_x_m = float(coordinate_transform["x_max_raw"]) - float(
            coordinate_transform["x_min_raw"]
        )
        extent_z_m = float(coordinate_transform["z_max_raw"]) - float(
            coordinate_transform["z_min_raw"]
        )
    except (KeyError, TypeError, ValueError):
        return None

    if extent_x_m <= 0 or extent_z_m <= 0:
        return None
    return extent_x_m, extent_z_m


def _derive_import_metadata_extent(
    project_id: str,
) -> tuple[float, float, str, dict | None, list[str]] | None:
    metadata = _latest_gravity_import_metadata(project_id)
    candidates = _coordinate_transform_candidates(metadata)

    for coordinate_transform in candidates:
        latlon_bbox = _latlon_bbox_from_coordinate_transform(coordinate_transform)
        extent = _bbox_extent_m(latlon_bbox)
        if extent is not None:
            return (
                extent[0],
                extent[1],
                "latlon_bbox",
                latlon_bbox,
                [_LATLON_BBOX_WARNING],
            )

    for coordinate_transform in candidates:
        extent = _utm_extent_from_coordinate_transform(coordinate_transform)
        if extent is not None:
            return extent[0], extent[1], "utm_bbox", None, []

    return None


def _footprint_to_bbox(
    footprint: dict,
    margin_factor: float = TERRAIN_MARGIN_FACTOR,
) -> tuple[dict | None, list[str]]:
    """
    Converts a ProjectFootprint dict → bbox dict for terrain request.

    HIGH/MEDIUM confidence with valid corners: applies margin_factor to real corners.
    LOW/MISSING or invalid corners: returns (None, [warning]).
    """
    if not footprint:
        return None, ["Sin footprint — terrain no disponible."]

    confidence = str(footprint.get("confidence", "MISSING")).upper()

    if confidence not in ("HIGH", "MEDIUM"):
        return None, [
            "Terreno solo contexto visual; footprint de baja confianza o ausente."
        ]

    footprint_bbox = _footprint_bbox(footprint)
    if footprint_bbox is None:
        return None, [
            "Corners de footprint inválidos o insuficientes — terrain no disponible."
        ]

    bbox = _expand_bbox(footprint_bbox, margin_factor)

    warnings: list[str] = []
    if confidence == "MEDIUM":
        warnings.append(
            "Footprint estimado — co-registro terrain/modelo aproximado."
        )

    return bbox, warnings


# ─── GEE helpers ─────────────────────────────────────────────────────────────

def _seasonal_date_window(lat: float) -> tuple[str, str]:
    """Return (start_date, end_date) optimized by hemisphere to avoid snow/ice."""
    today = datetime.date.today()
    year = today.year

    if lat >= 23.5:
        # Northern hemisphere — prefer boreal summer (June–September)
        return f"{year - 1}-06-01", f"{year}-09-30"
    elif lat <= -23.5:
        # Southern hemisphere — prefer austral summer (December–March)
        return f"{year - 1}-12-01", f"{year}-03-31"
    else:
        # Tropics — rolling 12-month window, cloud/snow filters handle quality
        start = today - datetime.timedelta(days=365)
        return start.isoformat(), today.isoformat()


def _mask_s2_scl(image):
    """EE server-side function: keep only clear pixels using the SCL classification band.

    Retained SCL classes:
      4 = Vegetation
      5 = Not-vegetated (bare soil, rock)
      6 = Water
      7 = Unclassified
    Removed: 0 no-data, 1 saturated, 2 dark areas, 3 cloud shadows,
             8 cloud medium, 9 cloud high, 10 cirrus, 11 snow/ice.
    """
    import ee  # server-side objects — local import keeps module importable without ee

    scl = image.select("SCL")
    valid = (
        scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
    )
    return image.updateMask(valid)


def _fetch_gee_terrain(
    bbox: dict,
    extent_x_m: float,
    extent_z_m: float,
    center_lat: float,
) -> tuple[list[list[float]], str, str]:
    """Query GEE for real DEM and Sentinel-2 texture.

    Returns (dem_matrix 32×32, texture_url, source_tag).
    Raises on unrecoverable errors so the caller can fall back to mock.
    """
    import ee

    region = ee.Geometry.Rectangle(
        [bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]]
    )

    # ── DEM — Copernicus GLO-30 ────────────────────────────────────────────
    # GLO30 is an ImageCollection (one 1°×1° tile per image).
    # mosaic() combines tiles; setDefaultProjection locks the native 30 m CRS.
    scale_m = max(max(extent_x_m, extent_z_m) / DEM_RESOLUTION, 30.0)

    dem_raw = (
        ee.ImageCollection("COPERNICUS/DEM/GLO30")
        .filterBounds(region)
        .select("DEM")
        .mosaic()
        .setDefaultProjection(crs="EPSG:4326", scale=30)
    )

    # Fill data gaps with focal_mean (3-pixel radius, 3 passes) so we never
    # create false zero-elevation holes in high-altitude terrain.
    dem_filled = dem_raw.focal_mean(
        radius=3, kernelType="circle", units="pixels", iterations=3
    )
    # unmask: use original where valid, filled value where masked.
    dem_final = dem_raw.unmask(dem_filled).reproject(crs="EPSG:4326", scale=scale_m)

    raw_data = dem_final.sampleRectangle(region=region).get("DEM").getInfo()

    # Convert to numpy; None → NaN for any pixels still masked after fill.
    arr = np.array(
        [[v if v is not None else np.nan for v in row] for row in raw_data],
        dtype=float,
    )

    if arr.size == 0 or np.all(np.isnan(arr)):
        raise ValueError("DEM sin datos válidos en la región — posible área oceánica.")

    # Remaining isolated NaN → regional mean (rare: only if focal_mean didn't reach)
    nan_mask = np.isnan(arr)
    if np.any(nan_mask):
        _log.warning(
            "dem_residual_nodata_filled_with_mean",
            nan_pixels=int(nan_mask.sum()),
            total_pixels=arr.size,
        )
        arr[nan_mask] = float(np.nanmean(arr))

    # Resize to exactly DEM_ROWS × DEM_COLS (bilinear via zoom order=1)
    if arr.shape != (DEM_ROWS, DEM_COLS):
        zoom_r = DEM_ROWS / arr.shape[0]
        zoom_c = DEM_COLS / arr.shape[1]
        arr = scipy.ndimage.zoom(arr, (zoom_r, zoom_c), order=1)

    dem_matrix: list[list[float]] = arr.tolist()

    # ── Sentinel-2 SR — RGB texture ───────────────────────────────────────
    texture_url = ""
    try:
        start_date, end_date = _seasonal_date_window(center_lat)

        s2_collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
            .filter(ee.Filter.lt("SNOW_ICE_PERCENTAGE", 10))
            .map(_mask_s2_scl)
            .select(["B4", "B3", "B2"])
        )

        # Median composite over the quality-filtered collection gives a
        # cloud/shadow-free representative image without picking a single scene.
        s2_composite = s2_collection.median()

        texture_url = s2_composite.getThumbURL({
            "min": 0,
            "max": 3000,
            "gamma": 1.4,
            "dimensions": 512,
            "region": region,
            "format": "png",
        })
    except Exception as exc:
        _log.warning("gee_s2_texture_failed", error=str(exc)[:200])
        texture_url = ""

    return dem_matrix, texture_url, "gee_v1"


# ─── Public API ───────────────────────────────────────────────────────────────

def get_terrain_data(
    project_id: str,
    footprint_override: dict | None = None,
    terrain_margin_factor: float = TERRAIN_MARGIN_FACTOR,
) -> TerrainResponse:
    # pid_clean: NO reutilizar el nombre de la función clean_project_id —
    # el shadowing convertía la función en variable local → UnboundLocalError.
    pid_clean = clean_project_id(project_id)

    # Read full project meta once
    project_dir = _project_dir(pid_clean)
    if not project_dir.exists():
        raise ValueError("Proyecto no encontrado.")

    meta = store.load_project_meta(pid_clean)
    if not meta:
        raise ValueError("Proyecto sin coordenadas geoespaciales.")

    latitude = meta.get("latitude")
    longitude = meta.get("longitude")
    if latitude is None or longitude is None:
        raise ValueError("Proyecto sin latitude/longitude.")
    try:
        center_lat = float(latitude)
        center_lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordenadas de proyecto inválidas.") from exc

    extent_x_m = DEFAULT_EXTENT_M
    extent_z_m = DEFAULT_EXTENT_M
    source = "mock_v1_no_run"
    extent_resolved = False

    # Attempt footprint-based bbox (R3-BE-1)
    footprint = footprint_override or meta.get("footprint")
    footprint_source: str | None = None
    georef_confidence: str = str(meta.get("georef_confidence", "MISSING"))
    terrain_warnings: list[str] = []

    bbox: dict | None = None
    if footprint:
        bbox, fp_warnings = _footprint_to_bbox(footprint, margin_factor=terrain_margin_factor)
        terrain_warnings.extend(fp_warnings)
        if bbox is not None:
            footprint_source = footprint.get("source")
            georef_confidence = str(footprint.get("confidence", "MISSING")).upper()
            footprint_extent = _derive_footprint_extent(footprint)
            if footprint_extent is not None:
                extent_x_m, extent_z_m, footprint_source, extent_warnings = footprint_extent
                terrain_warnings.extend(extent_warnings)
                extent_resolved = True

    if not extent_resolved:
        metadata_extent = _derive_import_metadata_extent(pid_clean)
        if metadata_extent is not None:
            (
                extent_x_m,
                extent_z_m,
                metadata_source,
                metadata_bbox,
                extent_warnings,
            ) = metadata_extent
            terrain_warnings.extend(extent_warnings)
            extent_resolved = True
            if footprint_source is None:
                footprint_source = metadata_source
            if bbox is None and metadata_bbox is not None:
                bbox = _expand_bbox(metadata_bbox, terrain_margin_factor)

    if not extent_resolved:
        extent_x_m, extent_z_m, source = _derive_project_extent(pid_clean)
    elif _latest_source_gravity_csv(pid_clean) is not None:
        source = "mock_v1"

    if bbox is None:
        # Fallback: center + extent (original method)
        bbox = compute_bbox(
            center_lat=center_lat,
            center_lon=center_lon,
            extent_x_m=extent_x_m,
            extent_z_m=extent_z_m,
        )
        if footprint_source is None:
            footprint_source = "center_extent_fallback"
        if not terrain_warnings:
            terrain_warnings.append(
                "Terreno solo contexto visual; footprint de baja confianza o ausente."
            )

    resolution_m = max(extent_x_m, extent_z_m) / DEM_RESOLUTION

    dem_matrix: list[list[float]] = [[0.0] * DEM_COLS for _ in range(DEM_ROWS)]
    texture_url = ""

    if gee_client.is_available():
        try:
            dem_matrix, texture_url, source = _fetch_gee_terrain(
                bbox, extent_x_m, extent_z_m, center_lat
            )
        except Exception as exc:
            _log.warning(
                "gee_terrain_fallback",
                project_id=pid_clean,
                error=str(exc)[:200],
            )
            source = "mock_v1_gee_fallback"

    # Elevation statistics (ignore NaN)
    flat_vals = [v for row in dem_matrix for v in row if not math.isnan(v)]
    min_elevation_m = float(min(flat_vals)) if flat_vals else None
    max_elevation_m = float(max(flat_vals)) if flat_vals else None
    mean_elevation_m = float(sum(flat_vals) / len(flat_vals)) if flat_vals else None

    # Cell sizes in metres
    bbox_lat_range_m = (bbox["max_lat"] - bbox["min_lat"]) * METERS_PER_DEG_LAT
    mid_lat_rad = math.radians((bbox["min_lat"] + bbox["max_lat"]) / 2.0)
    cos_mid = max(abs(math.cos(mid_lat_rad)), 1e-6)
    bbox_lon_range_m = (bbox["max_lon"] - bbox["min_lon"]) * METERS_PER_DEG_LAT * cos_mid
    cell_size_z_m = bbox_lat_range_m / DEM_ROWS
    cell_size_x_m = bbox_lon_range_m / DEM_COLS

    # ── Persist DEM metadata + matrix for R3-BE-4 ────────────────────────────
    _terrain_metadata_dict = {
        "project_id": pid_clean,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "bbox": {
            "min_lat": bbox["min_lat"],
            "max_lat": bbox["max_lat"],
            "min_lon": bbox["min_lon"],
            "max_lon": bbox["max_lon"],
        },
        "dem_rows": DEM_ROWS,
        "dem_cols": DEM_COLS,
        "cell_size_x_m": cell_size_x_m,
        "cell_size_z_m": cell_size_z_m,
        "min_elevation_m": min_elevation_m,
        "max_elevation_m": max_elevation_m,
        "mean_elevation_m": mean_elevation_m,
        "source": source,
        "footprint_source": footprint_source,
        "georef_confidence": georef_confidence,
        "terrain_margin_factor": terrain_margin_factor,
        "warnings": list(terrain_warnings),
        "center_lat": center_lat,
        "center_lon": center_lon,
        "extent_x_m": extent_x_m,
        "extent_z_m": extent_z_m,
        "dem_matrix_path": store.TERRAIN_DEM_MATRIX_FILENAME,
    }
    try:
        store.save_terrain_metadata(pid_clean, _terrain_metadata_dict)
        store.save_terrain_dem_matrix(pid_clean, dem_matrix)
    except Exception as _persist_exc:
        _persist_warning = f"No se pudo persistir terrain metadata: {_persist_exc}"
        terrain_warnings.append(_persist_warning)
        _log.warning(
            "terrain_persist_failed",
            project_id=pid_clean,
            error=str(_persist_exc)[:200],
        )

    return TerrainResponse(
        project_id=pid_clean,
        dem_matrix=dem_matrix,
        texture_url=texture_url,
        metadata=TerrainMetadata(
            bbox=BBoxData(**bbox),
            resolution_m=resolution_m,
            source=source,
            dem_rows=DEM_ROWS,
            dem_cols=DEM_COLS,
            center_lat=center_lat,
            center_lon=center_lon,
            extent_x_m=extent_x_m,
            extent_z_m=extent_z_m,
            min_elevation_m=min_elevation_m,
            max_elevation_m=max_elevation_m,
            mean_elevation_m=mean_elevation_m,
            cell_size_x_m=cell_size_x_m,
            cell_size_z_m=cell_size_z_m,
            footprint_source=footprint_source,
            georef_confidence=georef_confidence,
            terrain_margin_factor=terrain_margin_factor,
            warnings=terrain_warnings,
        ),
    )
