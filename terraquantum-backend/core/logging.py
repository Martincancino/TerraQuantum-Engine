"""Acceso al logger del backend.

Fase 6 (H-13): aquí vivía `configure_logging(development: bool)`, que llamaba a
`structlog.configure(...)` para elegir ConsoleRenderer (dev) o JSONRenderer (prod).
**Nadie la llamaba nunca** — ni `main.py`, ni los sidecars, ni los tests. Es decir:
el backend SIEMPRE ha corrido con la configuración por defecto de structlog, y esa
función sólo servía para sugerir una configuración central que no existía.

Se borró en vez de cablearse, a propósito: TerraQuantum es local-first y no hay
agregador de logs que consuma JSON estructurado, así que activar el JSONRenderer
cambiaría el formato de salida del sidecar sin que nadie lo pida. Si algún día hace
falta, se escribe de nuevo Y se llama desde `main.py` en el mismo commit — que es
justo lo que no pasó la primera vez.
"""

import structlog


def get_logger(name: str):
    return structlog.get_logger(name)
