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

import math
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

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
#   "elevation_unit"     → "m" | "ft" (unidad de la columna de elevación; default "m")
#   "gravity_type"       → tipo literal (ej. "bouguer_anomaly") cuando el dato YA viene
#                          reducido y no hay columna de tipo (evita el doble Bouguer).
#                          OJO: gravity_type es DUAL — si el valor es un nombre de
#                          columna del archivo, se trata como override de columna (rol),
#                          no como literal. Se distingue por el catálogo de tipos.
LITERAL_KEYS = ("unit", "coordinate_system", "elevation_unit")


def _is_gravity_type_literal(value: Optional[str]) -> bool:
    """True si `value` es un VALOR del catálogo de tipos (literal), no una columna.

    Import lazy del catálogo para evitar el ciclo con gravity_import_service.
    """
    if not value:
        return False
    from services.gravity_import_service import ALLOWED_GRAVITY_TYPES
    return str(value).strip() in ALLOWED_GRAVITY_TYPES

# Factor de conversión de la unidad de elevación declarada → metros. La elevación
# (ROLE_ELEVATION) se asume en METROS salvo que el `column_map` declare lo contrario;
# una columna en pies leída como metros mete un error de ~3.28× en la superficie de
# malla y en la corrección de Bouguer. Aliases tolerantes (normalize_token) → factor.
_FEET_TO_M = 0.3048
_ELEVATION_UNIT_TO_METERS: Dict[str, float] = {
    "ft": _FEET_TO_M, "feet": _FEET_TO_M, "foot": _FEET_TO_M,
    "pies": _FEET_TO_M, "pie": _FEET_TO_M,
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metro": 1.0, "metros": 1.0,
    "masl": 1.0, "msnm": 1.0,
}


def resolve_elevation_unit_factor(value: Optional[str]) -> float:
    """Factor para convertir la unidad de elevación declarada → metros.

    Tolerante a alias ("ft"/"feet"/"pies" → 0.3048; "m"/"meter"/"metros" → 1.0) vía
    normalize_token. GUARDRAIL: None / vacío / desconocido → 1.0 (asume metros), por lo
    que el comportamiento histórico es byte-idéntico cuando la clave no se declara.
    """
    if not value:
        return 1.0
    return _ELEVATION_UNIT_TO_METERS.get(normalize_token(value), 1.0)

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


# ─────────────────────────────────────────────────────────────────────────────
# F2 — Heurística por RANGO físico (segunda opinión sobre el mapeo por nombre)
#
# GOTCHA MEDIDO (2026-07-03, fixtures test_r37 / commit 60d1c56): la convención
# interna es x=este, z=norte, y=PROFUNDIDAD. Un usuario que pone el northing en
# la columna 'y' corrompe la geometría EN SILENCIO. La heurística detecta ese y
# otros desajustes comparando los VALORES contra rangos físicos:
#   lat ∈ [-90,90] · lon ∈ [-180,180] · UTM este ∈ [1e4,1.2e6] ·
#   UTM norte ∈ [1e5,1.1e7] · elevación ∈ [-500,7000] · anomalía ∈ ±500 mGal ·
#   TMI anomalía ∈ ±10k nT (campo total 15k-75k).
#
# Regla de confianza (NUNCA auto-mapear silencioso con confianza no-alta):
#   alta  = nombre resuelto y rango plausible → pre-mapea (el plan lo muestra).
#   media = nombre resuelto pero rango sospechoso, o solo sugerencia por rango
#           → `needs_confirmation`: el endpoint DEVUELVE el plan y PREGUNTA.
#   baja  = rol requerido sin resolver → `needs_mapping` (mapeo manual, ya existía).
# ─────────────────────────────────────────────────────────────────────────────
_EMPTY_TOKENS = {"", "nan", "none", "null", "na", "n/a"}


def _numeric_stats(values: Sequence[Any]) -> Optional[Dict[str, float]]:
    """min/max/mediana/fracción-numérica de una columna muestreada (strings)."""
    nums: List[float] = []
    n_filled = 0
    for v in values:
        s = str(v).strip()
        if s.lower() in _EMPTY_TOKENS:
            continue
        n_filled += 1
        try:
            x = float(s)
        except ValueError:
            if s.count(",") == 1:
                try:
                    x = float(s.replace(",", "."))
                except ValueError:
                    continue
            else:
                continue
        if math.isfinite(x):
            nums.append(x)
    if not nums or n_filled == 0:
        return None
    nums.sort()
    return {
        "n_filled": float(n_filled),
        "numeric_fraction": len(nums) / n_filled,
        "min": nums[0],
        "max": nums[-1],
        "median": nums[len(nums) // 2],
        "abs_median": abs(nums[len(nums) // 2]),
    }


def _looks_lat(st: Dict[str, float]) -> bool:
    return st["min"] >= -90.0 and st["max"] <= 90.0


def _looks_lon(st: Dict[str, float]) -> bool:
    return st["min"] >= -180.0 and st["max"] <= 180.0


def _looks_utm_easting(st: Dict[str, float]) -> bool:
    return 1e4 <= st["abs_median"] <= 1.2e6 and st["min"] >= 0.0


def _looks_utm_northing(st: Dict[str, float]) -> bool:
    return 1e5 <= st["abs_median"] <= 1.1e7


def _looks_elevation(st: Dict[str, float]) -> bool:
    return st["min"] >= -500.0 and st["max"] <= 7000.0


def _looks_mgal_anomaly(st: Dict[str, float]) -> bool:
    return abs(st["min"]) <= 500.0 and abs(st["max"]) <= 500.0


def _looks_nt(st: Dict[str, float]) -> bool:
    anomaly = abs(st["min"]) <= 10_000.0 and abs(st["max"]) <= 10_000.0
    total_field = 15_000.0 <= st["abs_median"] <= 75_000.0
    return anomaly or total_field


def _assess_plan_ranges(
    roles: Dict[str, Optional[str]],
    overridden: Dict[str, str],
    sample_values: Dict[str, List[Any]],
) -> "tuple[dict, list, dict]":
    """Chequea los roles resueltos contra los rangos físicos.

    Devuelve (range_checks, suspicions, role_confidence). Las sospechas sobre
    roles que el USUARIO mapeó explícitamente (overridden) igualmente se
    reportan (prevenir corrupción > respetar el click), pero con nota distinta.
    """
    checks: Dict[str, Dict[str, Any]] = {}
    suspicions: List[Dict[str, Any]] = []
    confidence: Dict[str, str] = {}

    def _stats_for(col: Optional[str]) -> Optional[Dict[str, float]]:
        if not col or col not in sample_values:
            return None
        return _numeric_stats(sample_values[col])

    for role, col in roles.items():
        if not col:
            confidence[role] = "low"
            continue
        st = _stats_for(col)
        if st is None or st["numeric_fraction"] < 0.5:
            # Columna no-numérica (station_id, gravity_type) o sin muestra:
            # el rango no aplica — la confianza la da el match por nombre.
            confidence[role] = "high"
            checks[role] = {"column": col, "verdict": "unknown", "note": None}
            continue

        verdict, note = "ok", None
        if role == ROLE_DEPTH and st["abs_median"] > 1e5:
            verdict = "suspicious"
            note = (
                f"'{col}' está en el eje de PROFUNDIDAD pero su mediana "
                f"(~{st['abs_median']:,.0f} m) parece un northing UTM."
            )
            suspicions.append({
                "role": ROLE_DEPTH,
                "column": col,
                "kind": "northing_in_depth_slot",
                "user_mapped": ROLE_DEPTH in overridden,
                "message": (
                    f"La columna '{col}' quedó como PROFUNDIDAD (eje vertical) "
                    f"pero sus valores (~{st['abs_median']:,.0f} m de mediana) "
                    "parecen coordenada NORTE (northing UTM). Si es el norte, "
                    "asígnela al rol 'Coordenada Y (norte)'; de lo contrario la "
                    "geometría 3D saldría corrupta."
                ),
                "suggested_role": ROLE_Y,
            })
        elif role == ROLE_ELEVATION and st["abs_median"] > 10_000:
            verdict = "suspicious"
            note = (
                f"'{col}' está como elevación pero su mediana "
                f"(~{st['abs_median']:,.0f}) excede toda topografía terrestre "
                "(máx ~7.000 m): ¿es un northing UTM?"
            )
            suspicions.append({
                "role": ROLE_ELEVATION,
                "column": col,
                "kind": "elevation_out_of_range",
                "user_mapped": ROLE_ELEVATION in overridden,
                "message": (
                    f"La columna '{col}' quedó como ELEVACIÓN pero sus valores "
                    f"(~{st['abs_median']:,.0f} de mediana) están fuera de "
                    "cualquier topografía terrestre (−500 a 7.000 m). Verifique "
                    "el mapeo (¿coordenada norte? ¿unidad en pies?)."
                ),
                "suggested_role": None,
            })
        elif role == ROLE_GRAVITY_VALUE:
            if 9.5e5 <= st["abs_median"] <= 1.0e6:
                note = (
                    "Valores ~9,8e5 mGal = gravedad ABSOLUTA de campo: requiere "
                    "correcciones (deriva/latitud/aire libre/Bouguer) antes de invertir."
                )
            elif not _looks_mgal_anomaly(st):
                verdict = "suspicious"
                note = (
                    f"'{col}' como valor gravimétrico tiene magnitudes "
                    f"(mediana ~{st['abs_median']:,.1f}) fuera del rango típico "
                    "de anomalía (±500 mGal): verifique columna y unidad."
                )
        elif role == ROLE_MAGNETIC_VALUE and not _looks_nt(st):
            verdict = "suspicious"
            note = (
                f"'{col}' como valor magnético (mediana ~{st['abs_median']:,.0f}) "
                "no calza con anomalía TMI (±10.000 nT) ni campo total "
                "(15.000–75.000 nT): verifique columna y unidad."
            )

        checks[role] = {"column": col, "verdict": verdict, "note": note}
        confidence[role] = "high" if verdict != "suspicious" else "medium"

    return checks, suspicions, confidence


def _suggest_missing_by_range(
    missing: List[str],
    roles: Dict[str, Optional[str]],
    sample_values: Dict[str, List[Any]],
) -> Dict[str, Dict[str, Any]]:
    """Para roles requeridos SIN resolver por nombre: candidato ÚNICO por rango.

    Solo sugiere cuando exactamente UNA columna no-asignada calza el rango del
    rol (ambigüedad → nada: mejor pedir mapeo manual que adivinar). La
    sugerencia es confianza MEDIA: el endpoint pregunta, jamás aplica solo.
    """
    assigned = {c for c in roles.values() if c}
    fits = {
        ROLE_X: lambda st: _looks_lon(st) or _looks_utm_easting(st),
        ROLE_Y: lambda st: _looks_lat(st) or _looks_utm_northing(st),
        ROLE_ELEVATION: _looks_elevation,
        ROLE_GRAVITY_VALUE: lambda st: (
            _looks_mgal_anomaly(st)
            and not _looks_utm_easting(st)
            and not _looks_utm_northing(st)
        ),
        ROLE_MAGNETIC_VALUE: _looks_nt,
    }
    suggestions: Dict[str, Dict[str, Any]] = {}

    stats_by_col: Dict[str, Dict[str, float]] = {}
    for col, vals in sample_values.items():
        if col in assigned:
            continue
        st = _numeric_stats(vals)
        if st is not None and st["numeric_fraction"] >= 0.9:
            stats_by_col[col] = st

    # Caso PAR UTM (los rangos de este y norte se SOLAPAN [1e5, 1.2e6], así que
    # sueltos casi nunca son únicos): si faltan x e y, buscar el único par
    # (este, norte) con norte > este (UTM sur siempre; el caso del corpus).
    if ROLE_X in missing and ROLE_Y in missing:
        # Separación CLARA exigida (norte > 2e6 m, o > 3× el este): dos columnas
        # con medianas vecinas (~3.6e5 y ~3.6e5) calzan ambas en el solape
        # este/norte y sugerirlas sería adivinar.
        pairs = [
            (a, b)
            for a, sa in stats_by_col.items()
            for b, sb in stats_by_col.items()
            if a != b
            and _looks_utm_easting(sa)
            and _looks_utm_northing(sb)
            and (
                sb["abs_median"] > 2e6
                or sb["abs_median"] > 3.0 * sa["abs_median"]
            )
        ]
        if len(pairs) == 1:
            a, b = pairs[0]
            suggestions[ROLE_X] = {
                "column": a,
                "confidence": "medium",
                "reason": (
                    f"Rango de '{a}' (mediana ~{stats_by_col[a]['abs_median']:,.0f}) "
                    "calza con UTM este; forma par único con el norte sugerido. "
                    "Confírmelo antes de continuar."
                ),
            }
            suggestions[ROLE_Y] = {
                "column": b,
                "confidence": "medium",
                "reason": (
                    f"Rango de '{b}' (mediana ~{stats_by_col[b]['abs_median']:,.0f}) "
                    "calza con UTM norte; forma par único con el este sugerido. "
                    "Confírmelo antes de continuar."
                ),
            }

    for role in missing:
        if role in suggestions:
            continue
        fit = fits.get(role)
        if fit is None:
            continue
        candidates = [
            (col, st) for col, st in stats_by_col.items()
            if col not in {s["column"] for s in suggestions.values()} and fit(st)
        ]
        if len(candidates) == 1:
            col, st = candidates[0]
            suggestions[role] = {
                "column": col,
                "confidence": "medium",
                "reason": (
                    f"Única columna numérica cuyo rango (mín {st['min']:,.4g}, "
                    f"máx {st['max']:,.4g}) calza con el rol "
                    f"'{ROLE_LABELS.get(role, role)}'. Confírmela antes de continuar."
                ),
            }
    return suggestions


def build_column_mapping_plan(
    headers: Sequence[str],
    data_kind: str = "gravity",
    column_map: Optional[dict] = None,
    sample_values: "Optional[Dict[str, List[Any]]]" = None,
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
        _GRAVITY_TYPE_COL_CANDIDATES,
        _STATION_ID_CANDIDATES,
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
        # F2 — sinónimos ES para las columnas literales (Tipo_Gravedad, Estacion).
        ROLE_GRAVITY_TYPE: _resolve_present(list(_GRAVITY_TYPE_COL_CANDIDATES), headers),
        ROLE_SIGMA: _find_first_alias(headers_lower, headers, UNCERTAINTY_ALIASES),
        ROLE_STATION_ID: _resolve_present(list(_STATION_ID_CANDIDATES), headers),
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
        # gravity_type es dual: si el valor es un tipo del catálogo, es un LITERAL
        # (se reporta en `literals`), no un override de columna.
        if role == ROLE_GRAVITY_TYPE and _is_gravity_type_literal(requested):
            continue
        real = resolve_mapped_column(requested, headers)
        if real is None:
            invalid[role] = requested
        else:
            roles[role] = real
            overridden[role] = real
            # F2 — una columna sirve a UN solo rol: si el usuario la asigna
            # explícitamente, se des-asigna de cualquier rol AUTO-detectado
            # (p.ej. 'y_m' auto-detectada como profundidad y luego mapeada a
            # norte: dejarla en ambos roles mantendría viva la sospecha ya
            # resuelta y duplicaría la columna en el plan).
            for other_role in list(roles.keys()):
                if (
                    other_role != role
                    and roles.get(other_role) == real
                    and other_role not in overridden
                ):
                    roles[other_role] = None

    required = list(required_roles_for(data_kind))
    optional = list(optional_roles_for(data_kind))
    missing = [r for r in required if not roles.get(r)]
    needs_mapping = bool(missing)

    literals = {k: cm[k] for k in LITERAL_KEYS if cm.get(k)}
    if _is_gravity_type_literal(cm.get(ROLE_GRAVITY_TYPE)):
        literals[ROLE_GRAVITY_TYPE] = cm[ROLE_GRAVITY_TYPE]

    # ── 3. F2 — Segunda opinión por RANGO físico (si hay muestra de valores) ──
    range_checks: Dict[str, Dict[str, Any]] = {}
    suspicions: List[Dict[str, Any]] = []
    role_confidence: Dict[str, str] = {
        r: ("high" if roles.get(r) else "low") for r in roles
    }
    suggestions: Dict[str, Dict[str, Any]] = {}
    if sample_values:
        range_checks, suspicions, role_confidence = _assess_plan_ranges(
            roles, overridden, sample_values
        )
        if missing:
            suggestions = _suggest_missing_by_range(missing, roles, sample_values)

    # needs_confirmation: hay sospechas sobre roles AUTO-detectados (el usuario
    # aún no eligió) o sugerencias por rango pendientes → el endpoint PREGUNTA.
    # Las sospechas sobre roles ya overridden se reportan pero no re-preguntan
    # (el usuario ya decidió con la advertencia a la vista).
    needs_confirmation = bool(
        [s for s in suspicions if not s.get("user_mapped")] or suggestions
    )

    if needs_mapping:
        confidence = "low"
    elif needs_confirmation:
        confidence = "medium"
    else:
        confidence = "high"

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
        "confidence": confidence,
        "role_labels": {r: ROLE_LABELS[r] for r in (required + optional)},
        "literals": literals,
        # F2 — heurística por rango físico (vacíos si no hubo muestra de valores).
        "range_checks": range_checks,
        "suspicions": suspicions,
        "role_confidence": role_confidence,
        "suggestions": suggestions,
        "needs_confirmation": needs_confirmation,
    }


def _resolve_present(candidates: List[str], headers: Sequence[str]) -> Optional[str]:
    """Primer candidato presente en headers (match normalizado)."""
    for c in candidates:
        real = resolve_mapped_column(c, headers)
        if real is not None:
            return real
    return None
