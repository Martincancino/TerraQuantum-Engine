"""Core utility functions shared across services and APIs."""

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

# Fase 6 (H-35): `TRACE_ID_PATTERN` y `clean_trace_id` vivían en el almacén de
# modelos de bloques, y este módulo del Core los importaba HACIA ARRIBA. Saneárun
# identificador para que sea seguro como nombre de carpeta es infraestructura, no
# dominio minero: su sitio es el Core. Mover el almacén fuera de `core/` sin esto
# habría creado una arista core/ → services/, justo la que la Fase 3 va a prohibir.
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def clean_trace_id(value: Optional[str], field_name: str) -> Optional[str]:
    """Valida un project_id/run_id como identificador seguro para rutas.

    Devuelve None si viene vacío; lanza ValueError si trae caracteres que
    permitirían escapar del directorio de datos ('.', '..', separadores).
    """
    if value is None:
        return None

    clean_value = str(value).strip()
    if clean_value == "":
        return None

    if clean_value in {".", ".."} or not TRACE_ID_PATTERN.match(clean_value):
        raise ValueError(
            f"{field_name} invalido. Use letras, numeros, guion, punto o underscore."
        )

    return clean_value


def sanitize_nan_value(value: Any) -> Any:
    """Convert a single NaN/Inf value to None for JSON serialization.

    Handles booleans, ints, floats, and other types.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            fval = float(value)
            if math.isnan(fval) or math.isinf(fval):
                return None
            return fval
        except (ValueError, TypeError, OverflowError):
            return None
    return value


def sanitize_nan(obj: Any) -> Any:
    """Convert NaN/Inf floats to None for valid JSON serialization.

    Recursively processes dicts and lists.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def model_to_dict(model: Any) -> dict:
    """Convert a Pydantic model to dict.

    Handles both model_dump() (Pydantic v2) and dict() (v1) methods.
    Plain dicts pass through unchanged (run_geophysics_inversion returns dict).
    """
    if isinstance(model, dict):
        return model
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def utc_now_iso(use_z_format: bool = False) -> str:
    """Return current UTC time in ISO 8601 format.

    Parameters
    ----------
    use_z_format : bool
        If True, replace "+00:00" with "Z" and remove microseconds.
        If False, keep full format with microseconds.
    """
    ts = datetime.now(timezone.utc)
    if use_z_format:
        return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return ts.isoformat()


def clean_project_id(project_id: str) -> str:
    """Validate and clean project_id.

    Raises ValueError if project_id is invalid or empty.
    """
    result = clean_trace_id(project_id, "project_id")
    if not result:
        raise ValueError("project_id es requerido.")
    return result


def safe_float(value: Any, fallback: Optional[float] = None) -> Optional[float]:
    """Safely parse a float, returning fallback on error or non-finite value.

    Parameters
    ----------
    value : Any
        The value to parse.
    fallback : float or None
        Return value if parsing fails or result is NaN/Inf. Defaults to None.
    """
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    except (TypeError, ValueError):
        pass
    return fallback
