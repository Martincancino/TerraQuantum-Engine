"""
Servicio OpenTopography — H-B3 Plan Industrial Tier 1.

Descarga DEM (SRTM30, COP30, etc.) de la API pública de OpenTopography
y calcula la corrección de terreno (TC) por el método de prismas usando
el servicio de correcciones ya implementado en gravity_corrections_service.

Referencia:
    https://portal.opentopography.org/apidocs/
    Hammer (1939) "Terrain corrections for gravimeter stations"
    Hinze et al. (2005), Geophysics — NAGD standardization

Requiere env var: OPENTOPO_API_KEY
Obtener en: https://portal.opentopography.org/myopentopo
Límites: 200 calls/día (cuenta académica), 50 calls/día (sin cuenta).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import httpx
import numpy as np

from core.config import OPENTOPO_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_OPENTOPO_BASE_URL = "https://portal.opentopography.org/API/globaldem"

_DEM_TYPES: Dict[str, str] = {
    "SRTM30":  "SRTMGL1",    # 30 m, global
    "SRTM90":  "SRTMGL3",    # 90 m, global, más rápido
    "COP30":   "COP30",       # Copernicus GLO-30, calidad máxima
    "ALOS":    "AW3D30",      # 30 m, mejor cobertura forestal
    "NASADEM": "NASADEM",     # 30 m, SRTM reprocesado
}

# Tamaño aproximado de celda en metros (en latitud media)
_CELL_SIZE_M: Dict[str, float] = {
    "SRTM30":  30.0,
    "SRTM90":  90.0,
    "COP30":   30.0,
    "ALOS":    30.0,
    "NASADEM": 30.0,
}


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------
class OpenTopoError(RuntimeError):
    """Error genérico de OpenTopography."""


class OpenTopoKeyMissingError(OpenTopoError):
    """OPENTOPO_API_KEY no configurado."""


# ---------------------------------------------------------------------------
# Parser AAIGrid (Esri ASCII Grid)
# ---------------------------------------------------------------------------

def _parse_aaigrid(
    content: str,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """
    Parsea un Esri ASCII Grid (AAIGrid) y retorna coordenadas y elevaciones.

    El formato estándar tiene cabecera de 6 líneas seguida de filas de datos.
    Las filas van de NORTE a SUR (fila 0 = latitud máxima).

    Returns:
        lat_1d: array 1-D, norte-a-sur [deg], shape (nrows,)
        lon_1d: array 1-D, oeste-a-este [deg], shape (ncols,)
        elev_2d: array 2-D [m AMSL], shape (nrows, ncols)
            elev_2d[i, j] ↔ lat_1d[i], lon_1d[j]
        cell_size_deg: tamaño de celda en grados
    """
    lines = content.strip().splitlines()

    header: Dict[str, str] = {}
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Header lines start with a letter
        if stripped[0].isalpha() or stripped[0] == '_':
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                header[parts[0].lower()] = parts[1].strip()
            data_start = i + 1
        else:
            data_start = i
            break

    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    # Support both xllcorner/yllcorner and xllcenter/yllcenter
    if "xllcorner" in header:
        xll = float(header["xllcorner"])
        yll = float(header["yllcorner"])
        center_offset = 0.0
    else:
        xll = float(header["xllcenter"])
        yll = float(header["yllcenter"])
        center_offset = -0.5  # already at cell center → no half-cell offset

    cell_size = float(header["cellsize"])
    nodata_raw = header.get("nodata_value", header.get("nodata", "-9999"))
    nodata = float(nodata_raw)

    # Build coordinate vectors
    # lon (west-to-east): center of each column
    lon_1d = xll + (np.arange(ncols) + 0.5 + center_offset) * cell_size
    # lat (north-to-south): row 0 = northernmost
    lat_1d = yll + (nrows - 0.5 - np.arange(nrows) + center_offset) * cell_size

    # Parse data rows
    data_lines = [l for l in lines[data_start:] if l.strip()]
    if len(data_lines) != nrows:
        raise OpenTopoError(
            f"AAIGrid: se esperaban {nrows} filas de datos, se obtuvieron {len(data_lines)}."
        )

    elev_rows = []
    for line in data_lines:
        row = [float(v) for v in line.split()]
        if len(row) != ncols:
            raise OpenTopoError(
                f"AAIGrid: fila con {len(row)} cols, se esperaban {ncols}."
            )
        elev_rows.append(row)

    elev_2d = np.array(elev_rows, dtype=np.float64)
    elev_2d[elev_2d == nodata] = np.nan

    return lat_1d, lon_1d, elev_2d, float(cell_size)


# ---------------------------------------------------------------------------
# Fetch DEM desde OpenTopography
# ---------------------------------------------------------------------------

async def fetch_dem_for_survey(
    south: float,
    north: float,
    west: float,
    east: float,
    dem_type: str = "SRTM30",
    buffer_deg: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float, dict]:
    """
    Descarga DEM de OpenTopography para el bbox de la encuesta.

    Se agrega un buffer alrededor del bbox para cubrir el radio de integración
    de TC (típicamente 22 km ≈ 0.20°).

    Args:
        south, north, west, east: bbox del survey en grados decimales
        dem_type: "SRTM30" | "SRTM90" | "COP30" | "ALOS" | "NASADEM"
        buffer_deg: buffer extra en grados (default 0 → el caller calcula el buffer)

    Returns:
        lat_1d [deg], lon_1d [deg], elev_2d [m], cell_size_deg, source_info

    Raises:
        OpenTopoKeyMissingError: OPENTOPO_API_KEY no configurado
        OpenTopoError: error de red o respuesta inválida de la API
    """
    api_key = OPENTOPO_API_KEY
    if not api_key:
        raise OpenTopoKeyMissingError(
            "OPENTOPO_API_KEY no configurado. "
            "Obtener en https://portal.opentopography.org/myopentopo y "
            "definir como variable de entorno OPENTOPO_API_KEY=<key>. "
            "Sin la clave, la corrección de terreno (TC) no está disponible."
        )

    demtype = _DEM_TYPES.get(dem_type, "SRTMGL1")

    s = south - buffer_deg
    n = north + buffer_deg
    w = west - buffer_deg
    e = east + buffer_deg

    params = {
        "demtype": demtype,
        "south":   round(s, 6),
        "north":   round(n, 6),
        "west":    round(w, 6),
        "east":    round(e, 6),
        "outputFormat": "AAIGrid",
        "API_Key": api_key,
    }

    logger.info(
        "[OPENTOPO] Descargando %s (demtype=%s) bbox=[%.4f,%.4f,%.4f,%.4f]",
        dem_type, demtype, s, n, w, e,
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.get(_OPENTOPO_BASE_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body_snippet = exc.response.text[:300] if exc.response.text else ""
            raise OpenTopoError(
                f"OpenTopography retornó HTTP {status} para demtype={demtype}. "
                f"Verificar límites de rate (200 calls/día académico) y bbox válido. "
                f"Respuesta: {body_snippet}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OpenTopoError(
                f"Timeout conectando a OpenTopography (120s). "
                "Verificar conectividad o reducir el área de bbox."
            ) from exc
        except httpx.RequestError as exc:
            raise OpenTopoError(
                f"Error de red al conectar a OpenTopography: {exc}"
            ) from exc

    content = resp.text
    lat_1d, lon_1d, elev_2d, cell_size = _parse_aaigrid(content)

    # Replace any NaN with linear interpolation using nearest valid neighbor
    _fill_nan_nearest(elev_2d)

    source_info: dict = {
        "source": f"OpenTopography/{demtype}",
        "dem_type": dem_type,
        "cell_size_deg": float(cell_size),
        "cell_size_m_approx": _CELL_SIZE_M.get(dem_type, 30.0),
        "n_rows": int(len(lat_1d)),
        "n_cols": int(len(lon_1d)),
        "bbox_south": s,
        "bbox_north": n,
        "bbox_west":  w,
        "bbox_east":  e,
    }

    logger.info(
        "[OPENTOPO] DEM OK: %dx%d celdas, cellsize=%.6f°, NaN restantes: %d",
        len(lon_1d), len(lat_1d), cell_size, int(np.isnan(elev_2d).sum()),
    )

    return lat_1d, lon_1d, elev_2d, float(cell_size), source_info


def _fill_nan_nearest(elev_2d: np.ndarray) -> None:
    """
    Rellena NaN con el vecino válido más cercano (in-place).
    Necesario para bordes de DEM o datos faltantes sobre océanos.
    """
    nan_mask = np.isnan(elev_2d)
    if not np.any(nan_mask):
        return

    valid_mask = ~nan_mask
    if not np.any(valid_mask):
        elev_2d[nan_mask] = 0.0
        return

    rows_valid, cols_valid = np.where(valid_mask)
    rows_nan, cols_nan = np.where(nan_mask)

    # For each NaN, find nearest valid cell (brute-force, OK for small NaN counts)
    for ri, ci in zip(rows_nan, cols_nan):
        dists = (rows_valid - ri) ** 2 + (cols_valid - ci) ** 2
        nearest = int(np.argmin(dists))
        elev_2d[ri, ci] = elev_2d[rows_valid[nearest], cols_valid[nearest]]


# ---------------------------------------------------------------------------
# Compute TC from DEM (local-projection wrapper)
# ---------------------------------------------------------------------------

def compute_tc_from_dem(
    stations_lat: np.ndarray,
    stations_lon: np.ndarray,
    stations_elev_m: np.ndarray,
    dem_lat_1d: np.ndarray,
    dem_lon_1d: np.ndarray,
    dem_elev_2d: np.ndarray,
    dem_cell_size_deg: float,
    terrain_radius_m: float = 22000.0,
    reduction_density_gcc: float = 2.67,
) -> np.ndarray:
    """
    Calcula la corrección de terreno (TC) por estación usando el DEM descargado.

    Proyección: equirectangular centrada en el baricentro del survey.
    Válida para surveys de extensión < 500 km (error < 0.5% en Chile central).

    Args:
        stations_lat: latitudes de las estaciones [deg], shape (n,)
        stations_lon: longitudes de las estaciones [deg], shape (n,)
        stations_elev_m: elevaciones de las estaciones [m AMSL], shape (n,)
        dem_lat_1d: latitudes del DEM (norte-a-sur) [deg], shape (nrows,)
        dem_lon_1d: longitudes del DEM (oeste-a-este) [deg], shape (ncols,)
        dem_elev_2d: elevaciones del DEM [m AMSL], shape (nrows, ncols)
        dem_cell_size_deg: tamaño de celda del DEM [deg]
        terrain_radius_m: radio máximo de integración [m] (Hammer zones A-M = 22 km)
        reduction_density_gcc: densidad de reducción [g/cm³]

    Returns:
        tc_mgal: array [mGal], shape (n,), siempre >= 0
    """
    from services.gravity_corrections_service import compute_terrain_correction_prism

    lats = np.asarray(stations_lat, dtype=np.float64)
    lons = np.asarray(stations_lon, dtype=np.float64)
    elevs = np.asarray(stations_elev_m, dtype=np.float64)

    # Reference point: baricentro del survey
    lat_ref = float(np.nanmean(lats))
    lon_ref = float(np.nanmean(lons))

    # Metros por grado (proyección equirectangular)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * np.cos(np.radians(lat_ref))

    # Estaciones → metros
    sx_m = (lons - lon_ref) * m_per_deg_lon   # este/oeste
    sz_m = (lats - lat_ref) * m_per_deg_lat   # norte/sur

    # DEM → metros (1-D vectors para dem_x_grid y dem_z_grid)
    dem_x_m_1d = (np.asarray(dem_lon_1d) - lon_ref) * m_per_deg_lon  # ncols
    dem_z_m_1d = (np.asarray(dem_lat_1d) - lat_ref) * m_per_deg_lat  # nrows

    # Tamaño de celda efectivo en metros (promedio lat/lon)
    cell_size_lat_m = dem_cell_size_deg * m_per_deg_lat
    cell_size_lon_m = dem_cell_size_deg * m_per_deg_lon
    cell_size_eff_m = float(np.sqrt(cell_size_lat_m * cell_size_lon_m))

    tc = compute_terrain_correction_prism(
        station_x_m=sx_m,
        station_z_m=sz_m,
        station_elev_m=elevs,
        dem_x_grid=dem_x_m_1d,
        dem_z_grid=dem_z_m_1d,
        dem_elev_grid=dem_elev_2d,
        dem_cell_size_m=cell_size_eff_m,
        reduction_density_gcc=reduction_density_gcc,
        max_radius_m=terrain_radius_m,
    )

    return tc
