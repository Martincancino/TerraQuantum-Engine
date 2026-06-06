"""Core utility functions shared across services and APIs."""

import math
from datetime import datetime, timezone
from typing import Any


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
    """
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
