"""
R2.2/R2.3 — CRS utilities: EPSG lookup, UTM zone parsing, easting/northing validation,
reproyección geodésica real UTM ↔ WGS84 via pyproj, y footprint UTM real.
"""
import math
import re
from typing import Tuple


def get_epsg_from_utm(zone_number: int, hemisphere: str) -> int:
    """
    Retorna el código EPSG WGS84 para una zona UTM.

    UTM Norte: EPSG 32601–32660  (zona 1–60 N)
    UTM Sur:   EPSG 32701–32760  (zona 1–60 S)
    """
    n = int(zone_number)
    if not (1 <= n <= 60):
        raise ValueError(f"Número de zona UTM inválido: {n}. Debe ser 1-60.")
    h = hemisphere.upper()
    if h == "N":
        return 32600 + n
    if h == "S":
        return 32700 + n
    raise ValueError(f"Hemisferio inválido: {hemisphere!r}. Debe ser 'N' o 'S'.")


def parse_utm_zone_string(zone_str: str) -> Tuple[int, str]:
    """
    Parsea una cadena de zona UTM a (zona_numero, hemisferio).

    Acepta: '19S', '19s', '3N', ' 33 n ', etc.
    Retorna: (19, 'S'), (3, 'N'), (33, 'N'), etc.
    Lanza ValueError si el formato es inválido o la zona está fuera de 1-60.
    """
    m = re.match(r"^\s*(\d{1,2})\s*([NnSs])\s*$", zone_str)
    if not m:
        raise ValueError(
            f"Formato de zona UTM inválido: '{zone_str}'. "
            "Usar formato '19S' o '33N' (número 1-60 + letra N/S)."
        )
    n = int(m.group(1))
    h = m.group(2).upper()
    if not (1 <= n <= 60):
        raise ValueError(
            f"Número de zona UTM inválido: {n}. Debe ser entre 1 y 60."
        )
    return n, h


def validate_utm_easting_northing(
    easting: float,
    northing: float,
    zone_num: int,
    hemisphere: str,
) -> list:
    """
    Valida que easting/northing estén dentro del rango válido UTM.

    Retorna lista de warnings (strings). Lista vacía significa valores válidos.
    No lanza excepciones salvo tipos imposibles.
    """
    warns = []
    if not (100_000 <= easting <= 900_000):
        warns.append(
            f"Easting {easting:.0f} m fuera del rango válido UTM (100,000–900,000 m). "
            "Verificar zona declarada."
        )
    h = hemisphere.upper()
    if h == "N" and not (0 <= northing <= 9_330_000):
        warns.append(
            f"Northing {northing:.0f} m fuera del rango válido UTM Norte (0–9,330,000 m)."
        )
    if h == "S" and not (1_000_000 <= northing <= 10_000_000):
        warns.append(
            f"Northing {northing:.0f} m fuera del rango válido UTM Sur (1,000,000–10,000,000 m)."
        )
    return warns


def _resolve_epsg(
    utm_zone: "str | None",
    utm_hemisphere: "str | None",
    epsg_code: "int | None",
    direction: str,
) -> int:
    """
    Determina el EPSG UTM a partir de los parámetros disponibles.
    Lanza ValueError si no hay suficiente información.
    """
    if epsg_code is not None:
        return epsg_code

    if utm_zone is not None:
        # "19S" format: hemisphere embedded in the zone string
        try:
            zone_num, hemi = parse_utm_zone_string(utm_zone)
        except ValueError:
            raise ValueError(
                f"utm_zone='{utm_zone}' inválido para {direction}. "
                "Formato esperado: '19S', '33N', etc."
            )
        # If utm_hemisphere also provided, validate consistency
        if utm_hemisphere is not None and utm_hemisphere.upper() != hemi:
            raise ValueError(
                f"Inconsistencia: utm_zone='{utm_zone}' implica hemisferio '{hemi}', "
                f"pero utm_hemisphere='{utm_hemisphere}'."
            )
        return get_epsg_from_utm(zone_num, hemi)

    raise ValueError(
        f"Se requiere epsg_code o utm_zone para {direction}. "
        "Ejemplo: utm_zone='19S' o epsg_code=32719."
    )


def transform_utm_to_wgs84(
    easting: float,
    northing: float,
    utm_zone: "str | None" = None,
    utm_hemisphere: "str | None" = None,
    epsg_code: "int | None" = None,
) -> tuple:
    """
    Reproyecta coordenadas UTM → WGS84 usando pyproj.

    Retorna (latitude, longitude) en grados decimales WGS84.
    Prioridad: epsg_code > utm_zone (formato '19S').
    """
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError(
            "pyproj no está disponible. Instalar con: pip install pyproj>=3.6.0"
        ) from exc

    src_epsg = _resolve_epsg(utm_zone, utm_hemisphere, epsg_code, "UTM→WGS84")

    transformer = Transformer.from_crs(f"EPSG:{src_epsg}", "EPSG:4326", always_xy=True)
    # always_xy=True → pyproj retorna (lon, lat)
    lon, lat = transformer.transform(easting, northing)

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(
            f"Latitud resultante {lat:.6f}° fuera del rango válido [-90, 90]. "
            "Verificar coordenadas de entrada y CRS."
        )
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(
            f"Longitud resultante {lon:.6f}° fuera del rango válido [-180, 180]. "
            "Verificar coordenadas de entrada y CRS."
        )

    return lat, lon


def transform_wgs84_to_utm(
    lat: float,
    lon: float,
    utm_zone: "str | None" = None,
    epsg_code: "int | None" = None,
) -> tuple:
    """
    Reproyecta coordenadas WGS84 → UTM usando pyproj.

    Retorna (easting, northing) en metros.
    Prioridad: epsg_code > utm_zone (formato '19S').
    """
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError(
            "pyproj no está disponible. Instalar con: pip install pyproj>=3.6.0"
        ) from exc

    dst_epsg = _resolve_epsg(utm_zone, None, epsg_code, "WGS84→UTM")

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{dst_epsg}", always_xy=True)
    # always_xy=True → input (lon, lat), output (easting, northing)
    easting, northing = transformer.transform(lon, lat)

    return easting, northing


def approx_dist_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km between two WGS84 points (haversine)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def compute_utm_footprint_with_pyproj(
    *,
    min_easting: float,
    max_easting: float,
    min_northing: float,
    max_northing: float,
    utm_zone: "str | None" = None,
    epsg_code: "int | None" = None,
    crs_source: str = "user_declared",
    warnings: "list[str] | None" = None,
) -> dict:
    """
    Compute a real WGS84 footprint bbox from UTM corners using pyproj.

    Transforms SW/SE/NE/NW corners and center via transform_utm_to_wgs84.
    Returns dict compatible with ProjectFootprint schema.
    source = "utm_pyproj"
    """
    resolved_epsg = _resolve_epsg(utm_zone, None, epsg_code, "UTM footprint")

    # Derive zone string and hemisphere for output fields
    if utm_zone is not None:
        zone_num, hemi = parse_utm_zone_string(utm_zone)
        zone_str = f"{zone_num}{hemi}"
    else:
        if resolved_epsg >= 32700:
            zone_num = resolved_epsg - 32700
            hemi = "S"
        else:
            zone_num = resolved_epsg - 32600
            hemi = "N"
        zone_str = f"{zone_num}{hemi}"

    # Transform 4 bbox corners: SW, SE, NE, NW
    sw_lat, sw_lon = transform_utm_to_wgs84(min_easting, min_northing, epsg_code=resolved_epsg)
    se_lat, se_lon = transform_utm_to_wgs84(max_easting, min_northing, epsg_code=resolved_epsg)
    ne_lat, ne_lon = transform_utm_to_wgs84(max_easting, max_northing, epsg_code=resolved_epsg)
    nw_lat, nw_lon = transform_utm_to_wgs84(min_easting, max_northing, epsg_code=resolved_epsg)

    # Transform center
    center_lat, center_lon = transform_utm_to_wgs84(
        (min_easting + max_easting) / 2.0,
        (min_northing + max_northing) / 2.0,
        epsg_code=resolved_epsg,
    )

    return {
        "crs": "EPSG:4326",
        "type": "bbox",
        "source": "utm_pyproj",
        "confidence": "HIGH",
        "center_lat": center_lat,
        "center_lon": center_lon,
        "extent_x_m": float(max_easting - min_easting),
        "extent_z_m": float(max_northing - min_northing),
        "utm_zone": zone_str,
        "utm_hemisphere": hemi,
        "epsg_code": resolved_epsg,
        "crs_source": crs_source,
        "crs_confidence": "HIGH",
        "sw": {"lat": sw_lat, "lon": sw_lon},
        "se": {"lat": se_lat, "lon": se_lon},
        "ne": {"lat": ne_lat, "lon": ne_lon},
        "nw": {"lat": nw_lat, "lon": nw_lon},
        "warnings": list(warnings or []),
        "precision_notes": ["Footprint UTM transformado a WGS84 usando pyproj."],
    }
