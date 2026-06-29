import csv
import math
import re
from pathlib import Path
from typing import List, Optional

import numpy as np

from schemas.geophysics_schema import GravityObservation
from schemas.gravity_import_schema import (
    AutoGrid,
    CoordinateTransform,
    CsvAnalysisResult,
    DataTypeDetection,
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
from services.column_mapping_service import (
    normalize_token as _norm,
    resolve_elevation_unit_factor as _resolve_elev_unit_factor,
    resolve_mapped_column as _resolve_mapped,
)
from scipy.spatial import cKDTree as _cKDTree

_log = get_logger(__name__)

ALLOWED_UNITS = {"m/s2", "m/s²", "mGal", "uGal", "µGal", "Gal"}

# PILAR 3 (Fase 3) — Canonicalización de unidades: acepta variantes de ortografía
# (mayúsculas/espacios/µ vs u/superíndices/sinónimos) y las mapea a la forma canónica.
# Clave = forma normalizada (minúsculas, sin espacios, ² → 2, ^ y · quitados, µ/μ → u).
_GRAVITY_UNIT_CANON = {
    "mgal": "mGal", "milligal": "mGal", "milligals": "mGal", "miligal": "mGal",
    "ugal": "µGal", "microgal": "µGal", "microgals": "µGal",
    "gal": "Gal", "gals": "Gal",
    "m/s2": "m/s2", "ms2": "m/s2", "m/s^2": "m/s2", "ms-2": "m/s2",
    "ms2-": "m/s2", "meterspersecondsquared": "m/s2",
}
_MAGNETIC_UNIT_CANON = {
    "nt": "nT", "ntesla": "nT", "nanotesla": "nT", "nanoteslas": "nT",
    "gamma": "nT", "gammas": "nT",
}


def _unit_key(raw: str) -> str:
    s = str(raw).strip().lower()
    s = (
        s.replace("²", "2").replace("^", "").replace(" ", "")
        .replace("·", "").replace("µ", "u").replace("μ", "u")
    )
    return s


def canonicalize_unit(raw: str, *, magnetic: bool = False) -> str:
    """Devuelve la forma canónica de la unidad (o el original sin espacios si es
    desconocida, para que la validación la rechace con claridad)."""
    if raw is None:
        return ""
    table = _MAGNETIC_UNIT_CANON if magnetic else _GRAVITY_UNIT_CANON
    return table.get(_unit_key(raw), str(raw).strip())
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
    # Pase 1 — match exacto (comportamiento histórico, sin regresión).
    for i, h in enumerate(headers_lower):
        if h in aliases:
            return headers[i]
    # Pase 2 — match fuzzy normalizado (acentos/mayúsculas/separadores). Aditivo:
    # solo dispara cuando el exacto falló, así no cambia detecciones previas.
    norm_aliases = {_norm(a) for a in aliases}
    for i, h in enumerate(headers_lower):
        if _norm(h) in norm_aliases:
            return headers[i]
    return None


def _coords_from_column_map(
    headers: list[str], headers_lower: list[str], column_map: dict
) -> "dict | None":
    """PILAR 1 — Construye el slot de coordenadas desde un `column_map` manual.

    Devuelve None si el mapeo no resuelve las dos horizontales (x, y) → se cae a la
    auto-detección. El tipo de coordenada se toma de `coordinate_system` si se provee;
    si no, se infiere por el NOMBRE de las columnas mapeadas (lon/lat → latlon,
    easting/northing → utm, otro → local).
    """
    x_col = _resolve_mapped(column_map.get("x"), headers)
    y_col = _resolve_mapped(column_map.get("y"), headers)  # 2.ª horizontal → z_m slot
    if not x_col or not y_col:
        return None

    elev_col = _resolve_mapped(column_map.get("elevation"), headers)
    depth_col = _resolve_mapped(column_map.get("depth"), headers)  # → y_m slot

    coord_sys = (column_map.get("coordinate_system") or "").strip().lower() or None
    if coord_sys not in (None, "latlon", "utm", "local"):
        coord_sys = None
    if coord_sys is None:
        xn, yn = _norm(x_col), _norm(y_col)
        lon_n = {_norm(a) for a in _LON_ALIASES}
        lat_n = {_norm(a) for a in _LAT_ALIASES}
        east_n = {_norm(a) for a in _UTM_EASTING_ALIASES}
        north_n = {_norm(a) for a in _UTM_NORTHING_ALIASES}
        if xn in lon_n and yn in lat_n:
            coord_sys = "latlon"
        elif xn in east_n and yn in north_n:
            coord_sys = "utm"
        else:
            coord_sys = "local"

    utm_zone_col = (
        _find_first_alias(headers_lower, headers, _UTM_ZONE_COL_ALIASES)
        if coord_sys == "utm" else None
    )
    return {
        "coord_type": coord_sys,
        "x_col": x_col, "y_col": depth_col, "z_col": y_col,
        "utm_zone_col": utm_zone_col,
        "elev_col": elev_col,
        "errors": [], "warnings": [],
        "raw_cols": {"x": x_col, "z": y_col},
    }


def _resolve_coordinate_columns(
    headers_lower: list[str], headers: list[str],
    column_map: "dict | None" = None,
) -> dict:
    """
    Detect coordinate format from CSV headers and return slot mapping.

    Si `column_map` resuelve las horizontales (x, y), ese mapeo MANUAL gana sobre la
    auto-detección (PILAR 1). En cualquier otro caso se usa la detección automática
    (ahora fuzzy: tolera acentos/mayúsculas/separadores vía _find_first_alias).

    coord_type: "legacy" | "latlon" | "utm" | "local" | None
    x_col: original column name for x_m slot (lon / easting / local_x)
    y_col: original column name for y_m slot (depth_m) or None → defaults to 0.0
    z_col: original column name for z_m slot (lat / northing / local_z)
    utm_zone_col: column name carrying utm_zone string, or None
    errors/warnings: validation messages
    raw_cols: mapping of slot → original column name for metadata
    """
    if column_map:
        mapped = _coords_from_column_map(headers, headers_lower, column_map)
        if mapped is not None:
            return mapped

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
    u = canonicalize_unit(unit)
    if u in ("m/s2", "m/s²"):
        return value
    elif u == "mGal":
        return value * 0.00001          # 1 mGal = 1e-5 m/s²
    elif u in ("uGal", "µGal"):
        return value * 0.00000001       # 1 µGal = 1e-8 m/s²
    elif u == "Gal":
        return value * 0.01             # 1 Gal  = 1e-2 m/s²
    raise ValueError(f"Unknown unit: {unit}")

def _is_metadata_row(row: dict, coord_cols: list[str]) -> bool:
    """True si la fila es METADATA: alguna columna de coordenada tiene texto no-numérico.

    Discrimina filas de cabecera/IGRF embebidas en CSVs crudos (texto donde debería
    ir una coordenada) de datos reales (coords numéricas). Coords vacías → NO metadata
    (se deja a la validación por fila, que las rechaza con mensaje claro).
    """
    for c in coord_cols:
        v = str(row.get(c, "") or "").strip()
        if not v:
            continue
        try:
            float(v)
        except (ValueError, TypeError):
            return True
    return False


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
    # Fallback fuzzy normalizado (aditivo): solo si el exacto no halló nada.
    norm_headers = [_norm(h) for h in headers_lower]
    for col in GRAVITY_COLUMN_PRIORITY:
        nc = _norm(col)
        if nc in norm_headers:
            return headers[norm_headers.index(nc)]
    return None


# ── Magnetometría (Fase 9A): columna de anomalía TMI en nanoTesla ────────────
# El dato magnético es UNA columna escalar por estación (TMI/total-field anomaly),
# en nT. Reusa toda la maquinaria de coordenadas/UTM/elevación de gravedad.
MAGNETIC_COLUMN_PRIORITY = [
    "magnetic_nt",
    "tmi_nt",
    "tmi",
    "magnetic_anomaly",
    "magnetic_anomaly_nt",
    "total_field_anomaly",
    "rtp",                 # reduced-to-pole
    "rtp_nt",
    "mag_nt",
    "magnetic",
    "nt",
]
# Unidades magnéticas aceptadas (no se convierte: nT es la unidad del pipeline TMI).
ALLOWED_MAGNETIC_UNITS = {"nt", "ntesla", "nanotesla", "nanoteslas", "gamma", "gammas"}


def choose_magnetic_column(headers: list[str]) -> str | None:
    headers_lower = [h.strip().lower() for h in headers]
    for col in MAGNETIC_COLUMN_PRIORITY:
        if col in headers_lower:
            idx = headers_lower.index(col)
            return headers[idx]
    # Fallback fuzzy normalizado (aditivo): solo si el exacto no halló nada.
    norm_headers = [_norm(h) for h in headers_lower]
    for col in MAGNETIC_COLUMN_PRIORITY:
        nc = _norm(col)
        if nc in norm_headers:
            return headers[norm_headers.index(nc)]
    return None

# \u2500\u2500 Sondajes (Fase 20): columnas de intervalo de profundidad / litolog\u00eda \u2500\u2500\u2500\u2500\u2500
# La se\u00f1al fuerte de un CSV de sondaje es el par depth_from / depth_to (intervalo)
# y/o un identificador de pozo. No comparte columnas con gravedad/magnetometr\u00eda.
BOREHOLE_DEPTH_FROM_ALIASES: frozenset = frozenset({
    "depth_from", "depth_from_m", "from_m", "from", "desde_m", "desde",
})
BOREHOLE_DEPTH_TO_ALIASES: frozenset = frozenset({
    "depth_to", "depth_to_m", "to_m", "to", "hasta_m", "hasta",
})
BOREHOLE_ID_ALIASES: frozenset = frozenset({
    "hole_id", "holeid", "bhid", "borehole_id", "dhid",
    "drillhole", "drillhole_id", "pozo", "sondaje", "sondaje_id",
})


def detect_csv_data_type(headers: list[str]) -> dict:
    """Fase 19 Tarea 1 \u2014 infiere el tipo de dato del CSV desde sus columnas.

    Devuelve un dict serializable (lo consume el schema DataTypeDetection):
      detected_type \u2208 {gravity, magnetic, borehole, joint, ambiguous, unknown}.

    Criterios:
      - gravity: alguna columna de GRAVITY_COLUMN_PRIORITY (g, bouguer_anomaly, ...).
      - magnetic: alguna columna de MAGNETIC_COLUMN_PRIORITY (magnetic_nt, tmi, ...).
      - borehole: par depth_from/depth_to, o id de pozo con al menos un depth.
      - joint: gravedad Y magnetometr\u00eda co-localizadas (sin sondaje).
      - ambiguous: se\u00f1ales mixtas geof\u00edsica + sondaje \u2192 pedir confirmaci\u00f3n.
      - unknown: ninguna columna reconocible \u2192 pedir tipo al usuario.
    """
    headers_lower = {h.strip().lower() for h in headers if h}
    grav_col = choose_gravity_column(list(headers))
    mag_col = choose_magnetic_column(list(headers))

    has_from = bool(headers_lower & BOREHOLE_DEPTH_FROM_ALIASES)
    has_to = bool(headers_lower & BOREHOLE_DEPTH_TO_ALIASES)
    has_hole_id = bool(headers_lower & BOREHOLE_ID_ALIASES)
    has_borehole = (has_from and has_to) or (has_hole_id and (has_from or has_to))

    has_g = grav_col is not None
    has_m = mag_col is not None

    signals: list[str] = []
    if has_g:
        signals.append(f"columna de gravedad '{grav_col}'")
    if has_m:
        signals.append(f"columna magn\u00e9tica '{mag_col}'")
    if has_borehole:
        signals.append("columnas de intervalo de sondaje (depth_from/depth_to)")

    is_joint = has_g and has_m and not has_borehole
    warning: "str | None" = None

    if has_borehole and not has_g and not has_m:
        detected, confidence = "borehole", "high"
    elif is_joint:
        detected, confidence = "joint", "high"
        warning = (
            "Columnas de gravedad y magnetometr\u00eda detectadas en el mismo CSV "
            "(survey co-localizado) \u2192 inversi\u00f3n conjunta (joint cross-gradient)."
        )
    elif has_g and not has_m and not has_borehole:
        detected, confidence = "gravity", "high"
    elif has_m and not has_g and not has_borehole:
        detected, confidence = "magnetic", "high"
    elif not has_g and not has_m and not has_borehole:
        detected, confidence = "unknown", "low"
        warning = (
            "No se detect\u00f3 columna de gravedad, magnetometr\u00eda ni sondaje. "
            "Especifique manualmente el tipo de dato del CSV."
        )
    else:
        detected, confidence = "ambiguous", "low"
        warning = (
            "Se detectaron se\u00f1ales mixtas (geof\u00edsica + sondaje) en el mismo CSV. "
            "Confirme el tipo de dato o separe los archivos."
        )

    return {
        "detected_type": detected,
        "confidence": confidence,
        "has_gravity_column": has_g,
        "has_magnetic_column": has_m,
        "has_borehole_columns": has_borehole,
        "is_joint_candidate": is_joint,
        "gravity_column": grav_col,
        "magnetic_column": mag_col,
        "signals": signals,
        "warning": warning,
    }


def normalize_header_name(header: str) -> str:
    return header.replace("\ufeff", "").strip()


def read_csv_headers(file_path: str | Path) -> list[str]:
    """Extrae los encabezados crudos del CSV con el MISMO parseo que el importador.

    (sep=[,;], engine python, descarta columnas 'Unnamed', normaliza BOM/espacios.)
    Devuelve [] si el archivo no existe o no es parseable. Lo usa el plan de mapeo
    manual (/analyze-columns) para ofrecer las columnas reales al usuario.
    """
    path = Path(file_path)
    if not path.exists():
        return []
    try:
        df, _ = _read_csv_dataframe(path, nrows=0)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        return [normalize_header_name(str(h)) for h in df.columns if h]
    except Exception:
        return []

# PILAR 4 (Fase 4) — Errores de fila que son DATOS sucios (NaN/vacío/no-numérico en
# una estación puntual): se OMITEN con aviso (tolerante), no rompen el import. Los
# errores estructurales/de consistencia (sin coords, unidad/tipo no soportado o mixto,
# lat/lon imposible) NO están aquí → siguen siendo fatales.
_SKIPPABLE_ROW_MARKERS = (
    "Invalid numeric value",
    "Empty/missing x coordinate",
    "Empty/missing z coordinate",
    "NaN or Inf not allowed",
    "Empty unit",
)


def _is_skippable_row_error(msg: str) -> bool:
    return any(m in msg for m in _SKIPPABLE_ROW_MARKERS)


class AmbiguousDelimiterError(ValueError):
    """No se puede determinar delimitador/decimal del CSV con confianza.

    INVARIANTE (BUG decimal-coma): la ingesta entrega dato LIMPIO o un ERROR CLARO,
    jamás un número silenciosamente equivocado con sello "Calidad GOOD". Se lanza,
    p.ej., con separador de miles (1,234,567) o comas de texto mezcladas dentro de
    un CSV ';'-delimitado, donde adivinar produciría basura.
    """


_AMBIGUOUS_DELIM_MSG = (
    "Detecté ';' como delimitador pero las comas están mezcladas (no son todas "
    "decimales): no puedo decidir el formato sin adivinar y produciría valores "
    "equivocados. Re-exporta el CSV con punto decimal, o declara el formato "
    "(delimitador ';' + decimal ',')."
)


def _sample_nonempty_lines(path: "str | Path", encoding: str, limit: int = 20) -> list[str]:
    """Primeras `limit` líneas no vacías (sin salto), para sniff de formato."""
    out: list[str] = []
    try:
        with open(path, encoding=encoding, errors="replace") as fh:
            for line in fh:
                if line.strip():
                    out.append(line.rstrip("\r\n"))
                    if len(out) >= limit:
                        break
    except Exception:
        return []
    return out


def _detect_semicolon_decimal_comma(lines: list[str]) -> str:
    """Refina la rama [,;]: ¿es ';'-delim con coma decimal (Excel-ES)?

    Devuelve:
      - "historic": comportamiento byte-idéntico (coma-delim inglés, o ';'-delim
        punto-decimal, o ';' inconsistente → no es claramente delimitador).
      - "semicolon_comma_decimal": usar sep=';' decimal=',' (caso LdM crudo).
      - "ambiguous": lanzar error claro (miles 1,234,567 / comas de texto).

    SOLO se invoca cuando _choose_read_sep ya resolvió r"[,;]" (nunca tab/pipe), así
    que la matriz de delimitadores del blindaje Fase 4 queda byte-idéntica.
    """
    if not lines:
        return "historic"
    semic_counts = [l.count(";") for l in lines]
    if sum(semic_counts) == 0:
        return "historic"  # sin ';' → coma-delim inglés (camino histórico)
    positive = [c for c in semic_counts if c > 0]
    # Consistencia por MODA (tolerante a filas ragged / preámbulo): un delimitador
    # real aparece el mismo nº de veces en la mayoría (≥80%) de las líneas.
    semic_mode = max(set(positive), key=positive.count)
    if sum(1 for c in semic_counts if c == semic_mode) < 0.8 * len(lines):
        return "historic"  # ';' inconsistente → no es claramente delimitador
    if sum(l.count(",") for l in lines) == 0:
        return "historic"  # ';'-delim punto-decimal (p.ej. matriz Fase 4)
    # ';' consistente + comas presentes → ¿las comas son TODAS decimales?
    total_comma = 0
    decimal_comma = 0
    for line in lines:
        for field in line.split(";"):
            ncomma = field.count(",")
            if ncomma == 0:
                continue
            total_comma += ncomma
            if ncomma >= 2:
                return "ambiguous"  # separador de miles (1,234,567): no adivinar
            # Coma decimal = coma seguida de dígito, entre dígitos o al inicio del
            # número (tolera europeo sin cero inicial y con signo: ",05" / "-,1396").
            if re.search(r"(?:^|[\d\s+\-]),\d", field):
                decimal_comma += 1
    if total_comma > 0 and decimal_comma == total_comma:
        return "semicolon_comma_decimal"
    return "ambiguous"  # comas de texto mezcladas, etc. → error claro


def _resolve_sep_decimal(path: "str | Path", encoding: str) -> "tuple[str, str]":
    """Resuelve (sep, decimal) para pandas. Lanza AmbiguousDelimiterError si no es
    decidible. Para tab/pipe y para los caminos históricos de [,;] devuelve decimal
    "." (== default de pandas → byte-idéntico)."""
    sep = _choose_read_sep(path, encoding)
    if sep != r"[,;]":
        return sep, "."
    verdict = _detect_semicolon_decimal_comma(_sample_nonempty_lines(path, encoding))
    if verdict == "semicolon_comma_decimal":
        return ";", ","
    if verdict == "ambiguous":
        raise AmbiguousDelimiterError(_AMBIGUOUS_DELIM_MSG)
    return sep, "."


def _choose_read_sep(path: "str | Path", encoding: str) -> str:
    """Sniff del delimitador desde la primera línea no vacía: , ; tab |.

    Para mantener CERO regresión, los CSV de coma/punto-y-coma siguen el mismo
    camino histórico (regex `[,;]`); solo tab y pipe activan un delimitador nuevo.
    """
    try:
        with open(path, encoding=encoding, errors="replace") as fh:
            first = ""
            for line in fh:
                if line.strip():
                    first = line
                    break
    except Exception:
        return r"[,;]"
    if not first:
        return r"[,;]"
    counts = {
        ",": first.count(","), ";": first.count(";"),
        "\t": first.count("\t"), "|": first.count("|"),
    }
    best = max(counts, key=lambda k: counts[k])
    if counts[best] == 0 or best in (",", ";"):
        return r"[,;]"
    return "\t" if best == "\t" else r"\|"


def _read_csv_dataframe(path: "str | Path", nrows: "int | None" = None):
    """Lee el CSV tolerando BOM/encoding y delimitadores (, ; tab |).

    Devuelve (df, warnings). `utf-8-sig` quita el BOM transparente; si el archivo no
    es UTF-8 se reintenta como latin-1 con aviso. Propaga pd.errors.EmptyDataError.
    """
    import pandas as pd

    warns: list[str] = []
    encoding = "utf-8-sig"
    try:
        sep, decimal = _resolve_sep_decimal(path, encoding)
        df = pd.read_csv(
            path, sep=sep, engine="python", encoding=encoding,
            on_bad_lines="skip", nrows=nrows, decimal=decimal,
        )
    except UnicodeDecodeError:
        encoding = "latin-1"
        warns.append("El archivo no es UTF-8; se leyó como latin-1.")
        sep, decimal = _resolve_sep_decimal(path, encoding)
        df = pd.read_csv(
            path, sep=sep, engine="python", encoding=encoding,
            on_bad_lines="skip", nrows=nrows, decimal=decimal,
        )

    # DEFENSA EN PROFUNDIDAD (BUG decimal-coma): si el CSV colapsó a UNA sola columna
    # pese a que las líneas crudas tenían delimitadores, la estructura está rota — no
    # sellar "Calidad GOOD" en silencio; dejar un aviso honesto. El fix principal es el
    # parseo correcto de arriba; esto sólo cubre colapsos no anticipados.
    if len(df.columns) <= 1:
        sample = _sample_nonempty_lines(path, encoding, limit=5)
        if any(any(d in s for d in (";", ",", "\t", "|")) for s in sample):
            warns.append(
                "El CSV se leyó como UNA sola columna pese a contener delimitadores; "
                "la estructura puede estar colapsada (revisa delimitador y decimal)."
            )
    return df, warns


def import_gravity_csv_v1(
    file_path: str | Path,
    strict: bool = True,
    allow_g_raw: bool = False,
    data_kind: str = "gravity",
    column_map: "dict | None" = None,
) -> GravityImportResult:
    # PILAR 1 — `column_map` (opcional) re-etiqueta columnas crudas a roles
    # (x, y, elevation, depth, gravity_value, gravity_type, magnetic_value, sigma,
    # station_id) + literales `unit`/`coordinate_system`/`elevation_unit`. La
    # elevación se convierte a metros vía `elevation_unit` (m/ft). Sobre-escribe la
    # auto-detección. column_map=None → comportamiento histórico idéntico.
    # data_kind="magnetic" (Fase 9A): parsea una columna TMI (nT) en lugar de
    # gravedad, reusando coordenadas/UTM/elevación. El valor TMI se guarda en el
    # slot escalar `g` de cada observación (sin conversión de unidades); el endpoint
    # lo extrae a magnetic_nt y pone g=0. gravity_type se fija a "magnetic_only".
    _is_magnetic = (data_kind == "magnetic")
    _log.info("import_gravity_csv_start", file=str(file_path), data_kind=data_kind)
    path = Path(file_path)
    warnings_list = []
    errors_list = []
    
    if not path.exists():
        errors_list.append(f"File not found: {path}")
        return _build_error_result(path.name, errors_list, warnings_list)
        
    try:
        import pandas as pd
        try:
            df, _read_warns = _read_csv_dataframe(path)
        except pd.errors.EmptyDataError:
            errors_list.append("El archivo CSV está vacío (sin columnas ni datos).")
            return _build_error_result(path.name, errors_list, warnings_list)
        except AmbiguousDelimiterError as exc:
            errors_list.append(str(exc))
            return _build_error_result(path.name, errors_list, warnings_list)
        warnings_list.extend(_read_warns)

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

        # PILAR 1 — mapeo manual: literales y overrides de columnas por rol.
        _cmap = column_map or {}
        _forced_unit = (str(_cmap.get("unit") or "").strip()) or None
        # BUG doble-Bouguer — `gravity_type` en column_map puede ser:
        #   (a) un VALOR LITERAL del catálogo (p.ej. "bouguer_anomaly") → declara que
        #       el dato YA viene reducido; puebla meta.gravity_type SIN inventar una
        #       columna, para que el enriquecimiento NO lo re-reduzca (doble Bouguer); o
        #   (b) el NOMBRE de una columna con el tipo por fila (histórico).
        # Se distingue por pertenencia al catálogo ALLOWED_GRAVITY_TYPES. GUARDRAIL:
        # sin la clave → byte-idéntico (no fuerza nada, columna por defecto "gravity_type").
        _gtype_raw = (str(_cmap.get("gravity_type") or "").strip()) or None
        _forced_gravity_type: "str | None" = None
        _gtype_col = "gravity_type"
        if _gtype_raw and not _is_magnetic:
            if _gtype_raw in ALLOWED_GRAVITY_TYPES:
                _forced_gravity_type = _gtype_raw          # literal declarado
            else:
                _mapped_gtype = _resolve_mapped(_gtype_raw, headers)
                if _mapped_gtype:
                    _gtype_col = _mapped_gtype              # override de columna (histórico)
                else:
                    errors_list.append(
                        f"gravity_type='{_gtype_raw}' no es un tipo válido ni una columna "
                        f"del archivo. Tipos válidos: {', '.join(sorted(ALLOWED_GRAVITY_TYPES))}."
                    )
        # TAREA B — unidad de la columna de elevación (m/ft). Default 1.0 (metros) →
        # byte-idéntico al histórico cuando no se declara. Si es "ft"/"pies", la
        # elevación cruda se convierte a metros en el punto de ingestión (abajo).
        _elev_unit_factor = _resolve_elev_unit_factor(_cmap.get("elevation_unit"))

        # Fase 19 Tarea 1 — auto-detección del tipo de dato desde las columnas.
        # Informativo (no altera el ruteo, que sigue gobernado por data_kind):
        # el frontend lo usa para pre-seleccionar el tipo o pedir confirmación.
        _detected_data_type = DataTypeDetection(**detect_csv_data_type(headers))

        # Magnetometría: la columna `unit` es opcional (nT implícito). Gravedad: se
        # exige columna `unit` salvo que el mapeo manual provea una unidad literal.
        if "unit" not in headers_lower and not _is_magnetic and not _forced_unit:
            errors_list.append("Missing required column: unit")

        # R3.5-K — station_id is optional; auto-generate if column absent
        _sid_idx = next(
            (i for i, h in enumerate(headers_lower) if h == "station_id"), None
        )
        _station_id_original_col: "str | None" = (
            headers[_sid_idx] if _sid_idx is not None else None
        )
        # PILAR 1 — override manual del station_id.
        _sid_override = _resolve_mapped(_cmap.get("station_id"), headers)
        if _sid_override:
            _station_id_original_col = _sid_override
        if _station_id_original_col is None:
            warnings_list.append(
                "No se encontró station_id; se generaron IDs automáticos por orden de fila."
            )

        coord_map = _resolve_coordinate_columns(headers_lower, headers, _cmap)
        if coord_map["coord_type"] is None:
            errors_list.extend(coord_map["errors"])
        else:
            warnings_list.extend(coord_map["warnings"])
        
        if _is_magnetic:
            # El "value column" es la anomalía TMI (nT). gravity_type no se exige.
            gravity_col = (
                _resolve_mapped(_cmap.get("magnetic_value"), headers)
                or choose_magnetic_column(headers)
            )
            if not gravity_col:
                errors_list.append(
                    "Missing magnetic column (magnetic_nt, tmi, magnetic_anomaly, ...)"
                )
        else:
            gravity_col = (
                _resolve_mapped(_cmap.get("gravity_value"), headers)
                or choose_gravity_column(headers)
            )
            if not gravity_col:
                errors_list.append("Missing gravity column (g, gravity_anomaly, g_corrected, or g_raw)")
            elif gravity_col.lower() == "g_raw" and not allow_g_raw:
                errors_list.append("Only g_raw is present but allow_g_raw is False")

            if strict and _gtype_col not in headers:
                errors_list.append("Missing required column: gravity_type (strict mode)")

        # Fase 9C: en modo gravedad, detectar si el CSV trae ADEMÁS una columna
        # magnética (survey co-localizado) → se captura paralela a observations
        # para habilitar la inversión conjunta (joint cross-gradient).
        _joint_mag_col = None if _is_magnetic else (
            _resolve_mapped(_cmap.get("magnetic_value"), headers)
            or choose_magnetic_column(headers)
        )
        _has_joint_mag = _joint_mag_col is not None
        joint_mag_values: "list[float]" = []

        if errors_list:
            return _build_error_result(
                path.name, errors_list, warnings_list,
                detected_data_type=_detected_data_type,
            )

        # PILAR 3/4 (Fase 3) — Pre-filtro de filas de METADATA/no-numéricas. CSVs
        # crudos (ej. DO-27 magnético) traen líneas de cabecera/IGRF embebidas con
        # texto en las columnas de coordenadas. Una fila cuya coordenada X o Z lleva
        # texto NO es un dato → se omite con un aviso agregado (no rompe el import ni
        # contamina errors_list). Las filas con coords vacías siguen a la validación
        # por fila (se rechazan con mensaje claro).
        _coord_key_cols = [
            c for c in (coord_map.get("x_col"), coord_map.get("z_col")) if c
        ]
        if _coord_key_cols:
            _kept_rows = []
            _meta_dropped = 0
            for _r in reader:
                if _is_metadata_row(_r, _coord_key_cols):
                    _meta_dropped += 1
                else:
                    _kept_rows.append(_r)
            if _meta_dropped:
                reader = _kept_rows
                warnings_list.append(
                    f"{_meta_dropped} fila(s) de metadata/no-numéricas detectadas y "
                    "omitidas (texto en columnas de coordenadas; p. ej. IGRF embebido "
                    "en CSV crudo)."
                )

        observations = []
        raw_gravity_values = []
        raw_latlon_elev_list: "list[dict]" = []  # H-B2: per-station lat/lon/elev (latlon surveys)
        # Topografía activa + sigma por estación (cualquier tipo de coordenada)
        station_elev_list: "list[float]" = []      # m s.n.m. (NaN si ausente)
        station_unc_list: "list[float]" = []       # mGal (NaN si ausente)
        _elev_col_any = coord_map.get("elev_col")
        _unc_col_any = (
            _resolve_mapped(_cmap.get("sigma"), headers)
            or _find_first_alias(headers_lower, headers, UNCERTAINTY_ALIASES)
        )
        dup_coords_log = []
        seen_coords = set()
        exact_duplicate_count = 0
        row_count = 0
        valid_rows = 0
        rejected_rows = 0
        # PILAR 4 — filas de DATOS sucios omitidas (tolerante, no fatal).
        skipped_dirty_rows = 0
        skipped_examples: "list[str]" = []

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
                    
                # PILAR 3 — canonicaliza la unidad (acepta mgal/Gal/m·s⁻²/nT, etc.).
                unit_raw = row.get("unit", "").strip() or (_forced_unit or "")
                if _is_magnetic:
                    # nT implícito; si se declara unidad, validarla como magnética.
                    unit = canonicalize_unit(unit_raw, magnetic=True) if unit_raw else ""
                    if unit_raw and unit != "nT":
                        raise ValueError(f"Row {row_num}: Unsupported magnetic unit: {unit_raw}")
                    if first_unit is None:
                        first_unit = unit or "nT"
                else:
                    if not unit_raw:
                        raise ValueError(f"Row {row_num}: Empty unit")
                    unit = canonicalize_unit(unit_raw)
                    if unit not in ALLOWED_UNITS:
                        raise ValueError(f"Row {row_num}: Unsupported unit: {unit_raw}")
                    if first_unit is None:
                        first_unit = unit
                    elif unit != first_unit:
                        raise ValueError("Mixed units are not allowed in TerraQuantum Gravity CSV v1")

                if _is_magnetic:
                    # gravity_type no aplica; se fija el sentinel magnético.
                    if first_gravity_type is None:
                        first_gravity_type = "magnetic_only"
                    g_type = ""
                elif _forced_gravity_type:
                    # Literal declarado en column_map: el dato YA viene reducido; se usa
                    # tal cual sin exigir columna por fila (evita el doble Bouguer).
                    g_type = _forced_gravity_type
                else:
                    g_type = row.get(_gtype_col, "").strip()
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
                # Magnetometría: el valor TMI (nT) NO se convierte; se guarda crudo
                # en el slot `g` y el endpoint lo extrae a magnetic_nt.
                g_converted = g_val if _is_magnetic else convert_to_ms2(g_val, unit)

                obs = GravityObservation(x_m=x, y_m=y, z_m=z, g=g_converted)
                observations.append(obs)
                raw_gravity_values.append(g_val)
                # Fase 9C: capturar TMI (nT) co-localizada, alineada con la
                # observación recién aceptada (mismo manejo de duplicados).
                if _has_joint_mag:
                    _mraw = str(row.get(_joint_mag_col, "") or "").strip()
                    joint_mag_values.append(
                        parse_float(_mraw, _joint_mag_col, row_num) if _mraw else float("nan")
                    )
                valid_rows += 1

                # Elevación de estación (m s.n.m.) — paralela a observations
                _st_elev = float("nan")
                if _elev_col_any:
                    _ev = row.get(_elev_col_any, "").strip()
                    try:
                        _st_elev = float(_ev) * _elev_unit_factor if _ev else float("nan")
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
                            _raw_elev = (
                                float(_raw_elev_str) * _elev_unit_factor
                                if _raw_elev_str else float("nan")
                            )
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
                rejected_rows += 1
                # PILAR 4 — fila de DATOS sucios (NaN/vacío/no-numérico) → OMITIR con
                # aviso (tolerante). Errores estructurales/consistencia → fatal.
                if _is_skippable_row_error(error_msg):
                    skipped_dirty_rows += 1
                    if len(skipped_examples) < 3:
                        skipped_examples.append(error_msg)
                    _log.warning("csv_row_skipped", row_num=row_num, reason=error_msg)
                else:
                    errors_list.append(error_msg)
                    _log.warning("csv_row_rejected", row_num=row_num, reason=error_msg)

        # PILAR 4 — aviso agregado de filas sucias omitidas (no fatal por sí mismo;
        # si quedan <10 válidas, el gate posterior falla con mensaje claro).
        if skipped_dirty_rows:
            warnings_list.append(
                f"{skipped_dirty_rows} fila(s) con datos inválidos/vacíos (coords o "
                "valores no numéricos, NaN) se omitieron. "
                f"Ejemplos: {'; '.join(skipped_examples)}"
            )

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
        # Magnetometría: obs.g es TMI cruda (nT); gravedad: m/s² → mGal (×1e5).
        g_mgal = np.array([obs.g for obs in observations]) * (1.0 if _is_magnetic else 1e5)
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
        # Magnetometría (nT): los chequeos de magnitud en mGal no aplican.
        _is_raw_type = (
            (first_gravity_type or "").strip() in ("g_raw", "absolute_gravity")
            or (gravity_col or "").lower() == "g_raw"
        )
        if not _is_magnetic and np.any(np.abs(g_mgal) > 1000.0):
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
        if not _is_magnetic and np.any(np.abs(g_mgal) > 100.0):
            warnings_list.append(
                "Large gravity anomaly detected (>100 mGal). Verify Bouguer/residual correction."
            )

        if len(warnings_list) != len(csv_analysis.warnings):
            warnings_list = list(dict.fromkeys(warnings_list))
            csv_analysis.warnings = warnings_list
        
        # ── Fase 5: Resolución real + contexto geológico honesto ─────────────
        _mean_spacing = (
            csv_analysis.sampling.mean_spacing_m
            if csv_analysis and csv_analysis.sampling.mean_spacing_m
            else None
        )
        _depth_resolution = round(_mean_spacing / 2, 2) if _mean_spacing else None
        _x_ext = getattr(coordinate_transform, "x_extent_m", None) or 0
        _z_ext = getattr(coordinate_transform, "z_extent_m", None) or 0
        _extent_m = max(_x_ext, _z_ext)
        if _extent_m > 50_000:
            _context_hint: str = "regional"
        elif _extent_m > 5_000:
            _context_hint = "local_to_district"
        else:
            _context_hint = "local_deposit"
        _honesty_note = (
            "Resolución real ≈ mean_spacing; profundidad resoluble ≈ spacing/2 (Li & Oldenburg). "
            "Este modelo NO emite ley, tonelaje ni rentabilidad. "
            "Solo densidad/susceptibilidad invertidas."
        )

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
            auto_grid=auto_grid,
            estimated_mean_spacing_m=round(_mean_spacing, 2) if _mean_spacing else None,
            estimated_depth_resolution_m=_depth_resolution,
            geological_context_hint=_context_hint,
            honesty_note=_honesty_note,
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
            # Fase 9C: TMI co-localizada por estación (None si el CSV no la trae).
            magnetic_values=joint_mag_values if _has_joint_mag else None,
            # Fase 19 Tarea 1: tipo de dato inferido desde las columnas.
            detected_data_type=_detected_data_type,
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
    detected_data_type: Optional[DataTypeDetection] = None,
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
        auto_grid=auto_grid,
        detected_data_type=detected_data_type,
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
    # λ: override explícito = fijo; sin override = 0 → selección automática por
    # Morozov (en este flujo el sigma SIEMPRE es explícito: σ por estación o
    # piso del gravímetro, así que chi²_red es interpretable).
    lambda_mag = float(overrides.get("lambda_mag") or 0.0)
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
        lambda_strategy="fixed" if lambda_mag > 0 else "chi2",
        lambda_fixed=lambda_mag if lambda_mag > 0 else None,
        auto_lambda=(lambda_mag == 0.0),
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


# ═════════════════════════════════════════════════════════════════════════════
# FASE 19 — Export de "CSV limpio"
# Serializa el resultado de import validado/enriquecido a un CSV descargable con
# columnas normalizadas (coordenadas + valor medido + sigma/elev/lat-lon cuando
# existan). NO recalcula física: solo refleja lo que import_gravity_csv_v1 ya
# produjo (unidades normalizadas, elevación enriquecida, sigma por estación).
# ═════════════════════════════════════════════════════════════════════════════
def build_clean_csv_from_import(
    result: GravityImportResult,
    *,
    data_kind: str = "gravity",
) -> str:
    """Construye el texto del CSV limpio a partir de un GravityImportResult.

    Para gravimetría el valor se exporta en mGal (el slot interno `g` está en m/s²
    tras el import → ×1e5). Para magnetometría el valor es TMI (nT) tal cual.
    Las columnas opcionales (sigma_mgal, elev_masl, lat_deg, lon_deg, magnetic_nt)
    solo aparecen si el import las pobló (listas paralelas a observations).

    Devuelve el CSV como string (UTF-8, separador coma). Si no hay observaciones,
    devuelve solo la fila de cabecera.
    """
    import io

    obs = list(result.observations or [])
    n = len(obs)
    is_magnetic = (data_kind == "magnetic")

    def _parallel(lst: "Optional[list]") -> "Optional[list]":
        return lst if (lst is not None and len(lst) == n) else None

    elevs = _parallel(result.station_elevations)
    sigmas = _parallel(result.station_uncertainties)
    mags = _parallel(result.magnetic_values)
    latlon = _parallel(result.raw_latlon_elev)

    value_col = "tmi_nt" if is_magnetic else "g_mgal"
    headers = ["station_id", "x_m", "y_m", "z_m", value_col]
    if not is_magnetic and sigmas is not None:
        headers.append("sigma_mgal")
    if elevs is not None:
        headers.append("elev_masl")
    if latlon is not None:
        headers += ["lat_deg", "lon_deg"]
    if not is_magnetic and mags is not None:
        headers.append("magnetic_nt")

    def _fmt(v) -> str:
        if v is None:
            return ""
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(fv):
            return ""
        return f"{fv:.6g}"

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for i, o in enumerate(obs):
        value = o.g if is_magnetic else o.g * 1e5  # m/s² → mGal para gravimetría
        row = [f"ST{i + 1:04d}", _fmt(o.x_m), _fmt(o.y_m), _fmt(o.z_m), _fmt(value)]
        if not is_magnetic and sigmas is not None:
            row.append(_fmt(sigmas[i]))
        if elevs is not None:
            row.append(_fmt(elevs[i]))
        if latlon is not None:
            ll = latlon[i] or {}
            row += [_fmt(ll.get("lat_deg")), _fmt(ll.get("lon_deg"))]
        if not is_magnetic and mags is not None:
            row.append(_fmt(mags[i]))
        writer.writerow(row)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# FASE 19 (Caso B) — Georef Helmert cableada al flujo de inversión
# Cuando el CSV trae coordenadas LOCALES y el usuario aporta ≥2 puntos de control,
# resolvemos la transformada de similitud y georeferenciamos las estaciones ANTES
# de calcular el footprint del modelo. Servicio additivo: NO toca la física ni la
# grilla (que opera en metros locales, invariante a traslación/rotación); produce
# la ubicación real del modelo + la validación del anclaje (residual).
# ═════════════════════════════════════════════════════════════════════════════
def georeference_stations_with_helmert(
    control_input,
    station_local_xz: "list[tuple[float, float]]",
) -> dict:
    """Resuelve Helmert y georeferencia las estaciones locales → (E, N) reales.

    Args:
        control_input: HelmertControlPointsInput (≥2 puntos local↔real).
        station_local_xz: [(x_local, z_local), ...] de las estaciones del survey.

    Returns:
        dict con: transform (HelmertTransformResult como dict), confidence,
        georeferenced_center {e, n}, georeferenced_extent {e_m, n_m},
        n_stations, warnings. Pensado para auto_params_metadata["helmert_georef"].

    Lanza ValueError si hay <2 puntos o son coincidentes (vía el servicio Helmert).
    """
    from core.utils import model_to_dict
    from services.helmert_transform_service import (
        apply_similarity_transform,
        solve_similarity_transform,
    )

    pts = list(getattr(control_input, "points", []) or [])
    local_points = [(float(p.local_x), float(p.local_z)) for p in pts]
    real_points = [(float(p.real_e), float(p.real_n)) for p in pts]
    residual_warn_m = float(getattr(control_input, "residual_warn_m", 10.0) or 10.0)

    transform = solve_similarity_transform(
        local_points, real_points, residual_warn_m=residual_warn_m,
    )

    real_xz = apply_similarity_transform(transform, list(station_local_xz)) if station_local_xz else []
    warnings_out = list(transform.warnings)
    center = None
    extent = None
    if real_xz:
        es = [e for e, _ in real_xz]
        ns = [n for _, n in real_xz]
        center = {"e": float(sum(es) / len(es)), "n": float(sum(ns) / len(ns))}
        extent = {"e_m": float(max(es) - min(es)), "n_m": float(max(ns) - min(ns))}

    return {
        "version": "helmert_georef_v0_1",
        "transform": model_to_dict(transform),
        "confidence": transform.confidence,
        "georeferenced_center": center,
        "georeferenced_extent": extent,
        "n_stations": len(real_xz),
        "warnings": warnings_out,
    }
