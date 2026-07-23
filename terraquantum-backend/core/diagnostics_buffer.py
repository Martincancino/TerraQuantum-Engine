"""F7 — Buffer en memoria de los últimos errores del backend (para diagnóstico).

Guarda SOLO metadatos de error a nivel de código: timestamp, ruta (path, sin
query ni body), tipo de excepción y la cola del traceback. JAMÁS guarda el
cuerpo de la petición ni datos de survey — el body de un crash puede contener
fragmentos de datos del cliente (riesgo real documentado en el plan F7).

Anillo acotado (últimos N), thread-safe. Los handlers globales de main.py lo
alimentan; `diagnostics_service` lo lee al exportar el bundle.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Dict, List

_MAX_ERRORS = 25
_buffer: Deque[Dict[str, str]] = deque(maxlen=_MAX_ERRORS)
_lock = Lock()


def record_error(path: str, error_type: str, traceback_text: str) -> None:
    """Registra un error. Solo path + tipo + cola del traceback (sin body)."""
    try:
        with _lock:
            _buffer.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "path": str(path)[:200],
                "type": str(error_type)[:120],
                "traceback": str(traceback_text)[-2000:],
            })
    except Exception:  # noqa: BLE001 — el diagnóstico jamás rompe el flujo
        pass


def recent_errors() -> List[Dict[str, str]]:
    with _lock:
        return list(_buffer)


def clear() -> None:
    with _lock:
        _buffer.clear()
