"""PILAR 1 (KEYSTONE) — Mapeo de columnas robusto + plan de MAPEO MANUAL.

El agujero histórico del flujo de ingesta era la detección RÍGIDA de columnas: un
encabezado raro ("Anomalia_Bouguer_mGal", "X", "Y", "Z", "Elevación (m)") rompía la
auto-detección y el CSV se rechazaba. Este módulo añade dos capas:

  1. Normalización fuzzy del encabezado (sin acentos, sin mayúsculas, sin
     separadores) para AMPLIAR la auto-detección sin falsos positivos (igualdad
     normalizada, no edit-distance).
  2. Un PLAN DE MAPEO: cuando la confianza es baja (falta algún rol requerido), se
     devuelven las columnas crudas + los roles necesarios para que el usuario asigne
     manualmente. El `column_map` resultante sobre-escribe la auto-detección.

GUARDRAIL — nada se inventa: el mapeo solo re-etiqueta columnas que YA existen en el
archivo; si un rol requerido no se resuelve, se marca `needs_mapping` (error claro),
nunca se fabrica un valor.

Este servicio NO importa `gravity_import_service` a nivel de módulo (la dependencia
es lazy dentro de `build_column_mapping_plan`) para evitar import circular: el
importador sí importa `normalize_token` desde aquí.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Sequence

# ── Roles canónicos del mapeo ────────────────────────────────────────────────
# Convención interna del importador: x_m slot = este/lon, z_m slot = norte/lat,
# y_m slot = profundidad bajo superficie (opcional).
ROLE_X = "x"                      # horizontal primaria (este / lon / x local) → x_m
ROLE_Y = "y"                      # horizontal secundaria (norte / lat / y local) → z_m
ROLE_ELEVATION = "elevation"     # elevación de superficie (m s.n.m.)
ROLE_DEPTH = "depth"             # profundidad bajo superficie → y_m (opcional)
ROLE_GRAVITY_VALUE = "gravity_value"
ROLE_GRAVITY_TYPE = "gravity_type"
ROLE_MAGNETIC_VALUE = "magnetic_value"
ROLE_SIGMA = "sigma"
ROLE_STATION_ID = "station_id"

# Claves literales especiales que `column_map` puede llevar además de role→columna:
#   "unit"               → unidad literal (ej. "mGal") cuando no hay columna de unidad
#   "coordinate_system"  → "latlon" | "utm" | "local" (fuerza el tipo de coordenada)
LITERAL_KEYS = ("unit", "coordinate_system")

ROLE_LABELS: Dict[str, str] = {
    ROLE_X: "Coordenada X (este / longitud)",
    ROLE_Y: "Coordenada Y (norte / latitud)",
    ROLE_ELEVATION: "Elevación de superficie (m s.n.m.)",
    ROLE_DEPTH: "Profundidad bajo superficie (m)",
    ROLE_GRAVITY_VALUE: "Valor gravimétrico",
    ROLE_GRAVITY_TYPE: "Tipo de gravedad (Bouguer / Free-Air / …)",
    ROLE_MAGNETIC_VALUE: "Valor magnético (TMI, nT)",
    ROLE_SIGMA: "Incertidumbre por estación (σ)",
    ROLE_STATION_ID: "Identificador de estación",
}

# Roles requeridos / opcionales por tipo de dato.
_REQUIRED_GRAVITY = (ROLE_X, ROLE_Y, ROLE_GRAVITY_VALUE)
_OPTIONAL_GRAVITY = (
    ROLE_ELEVATION, ROLE_DEPTH, ROLE_GRAVITY_TYPE,
    ROLE_MAGNETIC_VALUE, ROLE_SIGMA, ROLE_STATION_ID,
)
_REQUIRED_MAGNETIC = (ROLE_X, ROLE_Y, ROLE_MAGNETIC_VALUE)
_OPTIONAL_MAGNETIC = (ROLE_ELEVATION, ROLE_DEPTH, ROLE_SIGMA, ROLE_STATION_ID)


def required_roles_for(data_kind: str) -> tuple:
    return _REQUIRED_MAGNETIC if data_kind == "magnetic" else _REQUIRED_GRAVITY


def optional_roles_for(data_kind: str) -> tuple:
    return _OPTIONAL_MAGNETIC if data_kind == "magnetic" else _OPTIONAL_GRAVITY


def normalize_token(value: Optional[str]) -> str:
    """Canonicaliza un encabezado para comparación fuzzy.

    Quita BOM, acentos (NFKD + drop combining), pasa a minúsculas y elimina todo
    separador/no-alfanumérico. Ej.: "Anomalía Bouguer (mGal)" → "anomaliabouguermgal";
    "UTM-X" → "utmx"; "X " → "x". Igualdad normalizada = match (sin edit-distance,
    para no introducir falsos positivos).
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value)).replace("﻿", "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def resolve_mapped_column(
    col: Optional[str], headers: Sequence[str]
) -> Optional[str]:
    """Devuelve el encabezado real para `col` (match exacto o normalizado), o None.

    Se usa para validar que una columna elegida por el usuario en `column_map`
    realmente existe en el archivo (tolerando diferencias de mayúsculas/acentos).
    """
    if not col:
        return None
    if col in headers:
        return col
    target = normalize_token(col)
    if not target:
        return None
    for h in headers:
        if normalize_token(h) == target:
            return h
    return None


def build_column_mapping_plan(
    headers: Sequence[str],
    data_kind: str = "gravity",
    column_map: Optional[dict] = None,
) -> dict:
    """Construye el plan de mapeo: auto-detección + overrides → roles resueltos.

    Devuelve un dict serializable (lo consume el endpoint /analyze-columns y la UI):
      raw_columns      — encabezados crudos del CSV (para los selectores de rol).
      auto_detected    — {rol: columna|None} que encontró la auto-detección fuzzy.
      roles            — {rol: columna|None} final (auto-detección + column_map).
      overridden       — {rol: columna} efectivamente aplicados desde column_map.
      invalid_overrides— {rol: columna_pedida} que no existen en el archivo.
      required_roles   — roles que DEBEN resolverse para ingerir este data_kind.
      optional_roles   — roles que enriquecen pero no bloquean.
      missing_required — roles requeridos sin resolver (→ needs_mapping).
      needs_mapping    — bool: hay al menos un rol requerido sin resolver.
      confidence       — "high" si needs_mapping=False, "low" si True.
      role_labels      — etiquetas humanas (ES) para la UI.
      literals         — {unit?, coordinate_system?} pasados en column_map.
    """
    # Import lazy para evitar ciclo (gravity_import importa normalize_token de aquí).
    from services.gravity_import_service import (
        _resolve_coordinate_columns,
        choose_gravity_column,
        choose_magnetic_column,
        _find_first_alias,
    )
    from services.csv_analysis_service import UNCERTAINTY_ALIASES

    headers = [str(h) for h in headers if h is not None]
    headers_lower = [h.strip().lower() for h in headers]
    cm = dict(column_map or {})

    # ── 1. Auto-detección fuzzy (sin overrides) ───────────────────────────────
    coord_auto = _resolve_coordinate_columns(headers_lower, headers, None)
    auto: Dict[str, Optional[str]] = {
        ROLE_X: coord_auto.get("x_col"),
        ROLE_Y: coord_auto.get("z_col"),
        ROLE_ELEVATION: coord_auto.get("elev_col"),
        ROLE_DEPTH: coord_auto.get("y_col"),
        ROLE_GRAVITY_VALUE: choose_gravity_column(headers),
        ROLE_MAGNETIC_VALUE: choose_magnetic_column(headers),
        ROLE_GRAVITY_TYPE: _resolve_present(["gravity_type"], headers),
        ROLE_SIGMA: _find_first_alias(headers_lower, headers, UNCERTAINTY_ALIASES),
        ROLE_STATION_ID: _resolve_present(["station_id"], headers),
    }

    # ── 2. Overrides explícitos del usuario ───────────────────────────────────
    roles = dict(auto)
    overridden: Dict[str, str] = {}
    invalid: Dict[str, str] = {}
    all_roles = set(ROLE_LABELS.keys())
    for role, requested in cm.items():
        if role in LITERAL_KEYS or role not in all_roles:
            continue
        if not requested:
            continue
        real = resolve_mapped_column(requested, headers)
        if real is None:
            invalid[role] = requested
        else:
            roles[role] = real
            overridden[role] = real

    required = list(required_roles_for(data_kind))
    optional = list(optional_roles_for(data_kind))
    missing = [r for r in required if not roles.get(r)]
    needs_mapping = bool(missing)

    literals = {k: cm[k] for k in LITERAL_KEYS if cm.get(k)}

    return {
        "data_kind": data_kind,
        "raw_columns": headers,
        "auto_detected": auto,
        "roles": roles,
        "overridden": overridden,
        "invalid_overrides": invalid,
        "required_roles": required,
        "optional_roles": optional,
        "missing_required": missing,
        "needs_mapping": needs_mapping,
        "confidence": "low" if needs_mapping else "high",
        "role_labels": {r: ROLE_LABELS[r] for r in (required + optional)},
        "literals": literals,
    }


def _resolve_present(candidates: List[str], headers: Sequence[str]) -> Optional[str]:
    """Primer candidato presente en headers (match normalizado)."""
    for c in candidates:
        real = resolve_mapped_column(c, headers)
        if real is not None:
            return real
    return None
