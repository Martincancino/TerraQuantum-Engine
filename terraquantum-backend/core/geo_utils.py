import csv
import math
from pathlib import Path


METERS_PER_DEG_LAT = 111_320.0
BBOX_BUFFER = 0.20


def compute_bbox(
    center_lat: float,
    center_lon: float,
    extent_x_m: float,
    extent_z_m: float,
    buffer: float = BBOX_BUFFER,
) -> dict:
    """
    Calcula un bounding box WGS84 aproximado desde un centro lat/lon y extensiones en metros.

    Limitación mock_v1: no normaliza cruces del antimeridiano (±180°).
    """
    half_extent_x = max(float(extent_x_m), 0.0) / 2.0
    half_extent_z = max(float(extent_z_m), 0.0) / 2.0
    buffered_x = half_extent_x * (1.0 + buffer)
    buffered_z = half_extent_z * (1.0 + buffer)

    lat_rad = math.radians(float(center_lat))
    cos_lat = max(abs(math.cos(lat_rad)), 1e-6)
    meters_per_deg_lon = METERS_PER_DEG_LAT * cos_lat

    offset_lat_deg = buffered_z / METERS_PER_DEG_LAT
    offset_lon_deg = buffered_x / meters_per_deg_lon

    return {
        "min_lat": float(center_lat) - offset_lat_deg,
        "max_lat": float(center_lat) + offset_lat_deg,
        "min_lon": float(center_lon) - offset_lon_deg,
        "max_lon": float(center_lon) + offset_lon_deg,
    }


def _derive_extent_from_csv(csv_path: Path) -> tuple[float, float]:
    """
    Lee source_gravity.csv y retorna (extent_x_m, extent_z_m).

    Espera columnas x_m y z_m, tolerando espacios y mayúsculas en headers.
    """
    xs: list[float] = []
    zs: list[float] = []

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)

        if not reader.fieldnames:
            raise ValueError("CSV sin headers.")

        header_map = {
            header.strip().lower(): header
            for header in reader.fieldnames
            if header is not None
        }
        x_key = header_map.get("x_m")
        z_key = header_map.get("z_m")

        if not x_key or not z_key:
            raise ValueError("CSV sin columnas x_m/z_m.")

        for row in reader:
            xs.append(float(str(row.get(x_key, "")).strip()))
            zs.append(float(str(row.get(z_key, "")).strip()))

    if not xs or not zs:
        raise ValueError("CSV sin observaciones válidas.")

    return max(xs) - min(xs), max(zs) - min(zs)


_MISSING_FOOTPRINT_BASE = {
    "crs": "EPSG:4326",
    "type": "missing",
    "source": "missing",
    "confidence": "MISSING",
    "center_lat": None,
    "center_lon": None,
    "extent_x_m": None,
    "extent_z_m": None,
    "utm_zone": None,
    "sw": {"lat": None, "lon": None},
    "se": {"lat": None, "lon": None},
    "ne": {"lat": None, "lon": None},
    "nw": {"lat": None, "lon": None},
}

_OVER_100KM_NOTE = (
    "Extent >100km: error equirectangular puede superar 1%. Usar pyproj en R2."
)


def compute_footprint_from_center(
    center_lat: float,
    center_lon: float,
    extent_x_m: float,
    extent_z_m: float,
    source: str = "derived",
    confidence: str = "LOW",
    warnings: "list[str] | None" = None,
    precision_notes: "list[str] | None" = None,
    utm_zone: "str | None" = None,
) -> dict:
    """Full ProjectFootprint dict from center + extents. Equirectangular, no buffer.

    Returns type='missing' dict if extent <= 0 or lat/lon are None/non-finite.
    Does NOT handle antimeridian crossings.
    """
    warn_out: list[str] = list(warnings or [])
    notes_out: list[str] = list(precision_notes or [])

    try:
        clat = float(center_lat)
        clon = float(center_lon)
        ext_x = float(extent_x_m)
        ext_z = float(extent_z_m)
        import math as _math
        if not (_math.isfinite(clat) and _math.isfinite(clon)
                and _math.isfinite(ext_x) and _math.isfinite(ext_z)):
            raise ValueError("non-finite")
    except (TypeError, ValueError):
        return {
            **_MISSING_FOOTPRINT_BASE,
            "source": source,
            "warnings": warn_out + ["Coordenadas o extensión inválidas. Footprint no calculable."],
            "precision_notes": notes_out,
        }

    if ext_x <= 0 or ext_z <= 0:
        return {
            **_MISSING_FOOTPRINT_BASE,
            "source": source,
            "warnings": warn_out + ["Extensión cero o negativa. Footprint no calculable."],
            "precision_notes": notes_out,
        }

    half_x = ext_x / 2.0
    half_z = ext_z / 2.0
    lat_rad = math.radians(clat)
    cos_lat = max(abs(math.cos(lat_rad)), 1e-6)
    meters_per_deg_lon = METERS_PER_DEG_LAT * cos_lat
    offset_lat_deg = half_z / METERS_PER_DEG_LAT
    offset_lon_deg = half_x / meters_per_deg_lon

    if not notes_out:
        if max(ext_x, ext_z) > 100_000:
            notes_out.append(_OVER_100KM_NOTE)
        else:
            notes_out.append(
                "Aproximación equirectangular — error <1% para extensiones <100km."
            )

    return {
        "crs": "EPSG:4326",
        "type": "bbox",
        "source": source,
        "confidence": confidence,
        "center_lat": clat,
        "center_lon": clon,
        "extent_x_m": ext_x,
        "extent_z_m": ext_z,
        "utm_zone": utm_zone,
        "sw": {"lat": clat - offset_lat_deg, "lon": clon - offset_lon_deg},
        "se": {"lat": clat - offset_lat_deg, "lon": clon + offset_lon_deg},
        "ne": {"lat": clat + offset_lat_deg, "lon": clon + offset_lon_deg},
        "nw": {"lat": clat + offset_lat_deg, "lon": clon - offset_lon_deg},
        "warnings": warn_out,
        "precision_notes": notes_out,
    }


# ---------------------------------------------------------------------------
# DEM sampling utilities  (R3-BE-2)
# ---------------------------------------------------------------------------


def _bilinear_interp(
    matrix: "list[list[float]]",
    row_f: float,
    col_f: float,
) -> float:
    """Bilinear interpolation over a 2-D float matrix at fractional indices."""
    rows = len(matrix)
    cols = len(matrix[0]) if rows > 0 else 0
    # Clamp row0/col0 so that row0+1 and col0+1 remain valid indices
    row0 = max(0, min(int(row_f), max(rows - 2, 0)))
    col0 = max(0, min(int(col_f), max(cols - 2, 0)))
    row1 = min(row0 + 1, rows - 1)
    col1 = min(col0 + 1, cols - 1)
    dr = row_f - row0
    dc = col_f - col0
    v00 = matrix[row0][col0]
    v01 = matrix[row0][col1]
    v10 = matrix[row1][col0]
    v11 = matrix[row1][col1]
    return (
        v00 * (1 - dr) * (1 - dc)
        + v01 * (1 - dr) * dc
        + v10 * dr * (1 - dc)
        + v11 * dr * dc
    )


def sample_dem_elevation(
    dem_matrix: "list[list[float]]",
    dem_metadata: dict,
    x_m: float,
    z_m: float,
    model_extent_x_m: float,
    model_extent_z_m: float,
    method: str = "bilinear",
) -> "tuple[float | None, str]":
    """
    Sample DEM elevation at local model position (x_m, z_m).

    x_m  — local East-West offset from SW corner of model [m].
    z_m  — local North-South offset from SW corner of model [m].
    Returns (elevation_masl, warning_str); warning_str is "" when OK.

    dem_metadata bbox accepts:
      Form A: {"min_lat":…, "max_lat":…, "min_lon":…, "max_lon":…}
      Form B: {"sw": {"lat":…, "lon":…}, "ne": {"lat":…, "lon":…}}
    The DEM is assumed to be symmetrically centred over the model
    (offset = (bbox_extent - model_extent) / 2 on each side).
    Row 0 of dem_matrix is the northern-most row; z_m grows northward.
    """
    # 1 — Validate matrix
    if not dem_matrix:
        return (None, "DEM vacío.")
    row_len = len(dem_matrix[0])
    if row_len == 0:
        return (None, "DEM vacío.")
    if any(len(row) != row_len for row in dem_matrix):
        return (None, "DEM inválido: filas de longitud inconsistente.")

    # 2 — Validate method
    if method not in ("bilinear", "nearest"):
        return (None, f"Método de muestreo DEM no soportado: {method}.")

    # 3 — Validate and parse metadata / bbox
    if not dem_metadata:
        return (None, "Sin metadata DEM suficiente para muestreo.")
    bbox = dem_metadata.get("bbox")
    if not bbox:
        return (None, "Sin metadata DEM suficiente para muestreo.")

    if "min_lat" in bbox and "max_lat" in bbox:
        min_lat = bbox["min_lat"]
        max_lat = bbox["max_lat"]
        min_lon = bbox["min_lon"]
        max_lon = bbox["max_lon"]
    elif "sw" in bbox and "ne" in bbox:
        sw = bbox["sw"]
        ne = bbox["ne"]
        min_lat = sw.get("lat")
        max_lat = ne.get("lat")
        min_lon = sw.get("lon")
        max_lon = ne.get("lon")
    else:
        return (None, "Sin metadata DEM suficiente para muestreo.")

    if None in (min_lat, max_lat, min_lon, max_lon):
        return (None, "Sin metadata DEM suficiente para muestreo.")

    # 4 — Detect mock DEM (all zeros → conceptual elevation)
    if all(v == 0.0 for row in dem_matrix for v in row):
        return (0.0, "DEM mock — elevación conceptual.")

    # 5 — Compute DEM extents in metres
    rows = len(dem_matrix)
    cols = row_len
    center_lat = (float(min_lat) + float(max_lat)) / 2.0
    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(math.radians(center_lat))
    bbox_z_m = (float(max_lat) - float(min_lat)) * METERS_PER_DEG_LAT
    bbox_x_m = (float(max_lon) - float(min_lon)) * meters_per_deg_lon

    # 6 — Symmetric offset: model SW corner inside DEM bbox
    offset_x_m = (bbox_x_m - float(model_extent_x_m)) / 2.0
    offset_z_m = (bbox_z_m - float(model_extent_z_m)) / 2.0

    # 7 — Map to fractional DEM indices
    x_in_bbox_m = offset_x_m + float(x_m)
    z_in_bbox_m = offset_z_m + float(z_m)
    col_f = (x_in_bbox_m / bbox_x_m) * (cols - 1)
    # row 0 = north (max lat); z_m grows northward → invert row axis
    row_f = ((bbox_z_m - z_in_bbox_m) / bbox_z_m) * (rows - 1)

    # 8 — Clamp with warning if outside bbox
    warning = ""
    if col_f < 0.0 or col_f > cols - 1 or row_f < 0.0 or row_f > rows - 1:
        warning = "Voxel fuera del DEM bbox; se aplicó clamp al borde."
    col_f = max(0.0, min(col_f, float(cols - 1)))
    row_f = max(0.0, min(row_f, float(rows - 1)))

    # 9 — Sample
    if method == "nearest":
        row_i = max(0, min(round(row_f), rows - 1))
        col_i = max(0, min(round(col_f), cols - 1))
        return (dem_matrix[row_i][col_i], warning)

    # bilinear (default)
    return (_bilinear_interp(dem_matrix, row_f, col_f), warning)
