"""F7 — "Exportar diagnóstico" compatible con confidencialidad.

Empaqueta SOLO lo necesario para depurar un problema de soporte: versiones,
config saneada, estado de conectividad y la cola de los últimos errores (a nivel
de código, sin body de request). NUNCA incluye datos de survey — ni parquets, ni
CSVs, ni report_payloads con coordenadas/valores, ni secretos.

El consultor exporta el ZIP con un clic y lo envía por correo MANUALMENTE: ningún
byte sale de la máquina sin su acción explícita (regla local-first). El test
`test_f7_diagnostics.py` abre el ZIP e inspecciona que no haya ninguna huella de
datos de survey ni secretos.
"""
from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core import config
from core import diagnostics_buffer

# Paquetes cuya versión ayuda a depurar (motor físico + stack web + cripto).
_KEY_PACKAGES = [
    "fastapi", "uvicorn", "starlette", "pydantic", "numpy", "scipy",
    "pandas", "pyproj", "scikit-image", "cryptography", "structlog",
    "httpx", "slowapi", "google-genai",
]

# Nombres de campo de config que JAMÁS entran al bundle (secretos).
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "MASTER", "PASSWORD", "CREDENTIAL")


def _package_versions() -> Dict[str, str]:
    try:
        from importlib import metadata
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, str] = {}
    for name in _KEY_PACKAGES:
        try:
            out[name] = metadata.version(name)
        except Exception:  # noqa: BLE001 — no instalado / no medible
            out[name] = "not-installed"
    return out


def _sanitized_config() -> Dict[str, Any]:
    """Valores de config seguros para diagnóstico. Excluye cualquier secreto y
    NUNCA incluye contenidos de datos — solo rutas (string) y flags."""
    safe: Dict[str, Any] = {}
    for name in dir(config):
        if name.startswith("_") or not name.isupper():
            continue
        if any(marker in name for marker in _SECRET_MARKERS):
            continue  # secreto → fuera
        try:
            value = getattr(config, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(value):
            continue
        if isinstance(value, Path):
            safe[name] = str(value)
        elif isinstance(value, (str, int, float, bool, list, dict)) or value is None:
            safe[name] = value
        else:
            safe[name] = repr(value)
    return safe


def build_system_info() -> Dict[str, Any]:
    return {
        "app": config.APP_TITLE,
        "app_version": config.APP_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "data_dir": str(config.DATA_DIR),
        "data_dir_is_portable": bool(
            str(config.DATA_DIR) != str(config.BASE_DIR / "data")
        ),
    }


def diagnostic_manifest() -> Dict[str, Any]:
    """El contenido del bundle como dict (reusable en tests y en el endpoint)."""
    from services import connectivity_service
    from core import license_service

    lic = license_service.get_license_status()
    # Defensa en profundidad: la licencia no lleva secretos, pero recortamos a
    # los campos informativos por si el payload trajera extras.
    lic_safe = {k: lic.get(k) for k in
                ("valid", "tier", "effective_tier", "mode", "expired",
                 "expires_at", "source", "reason")}

    return {
        "system": build_system_info(),
        "packages": _package_versions(),
        "config_sanitized": _sanitized_config(),
        "connectivity": connectivity_service.connectivity_summary(probe=False),
        "license": lic_safe,
        "recent_errors": diagnostics_buffer.recent_errors(),
    }


_README = """TerraQuantum — Paquete de diagnóstico
=======================================

Contenido (SOLO metadatos para soporte):
  - system.json        : versión de la app, Python, sistema operativo, ruta de datos.
  - packages.txt       : versiones de las librerías clave.
  - config.json        : configuración SANEADA (sin claves ni tokens).
  - connectivity.json  : qué features necesitan internet (el flujo principal es offline).
  - license.json       : estado del tier (sin material secreto).
  - recent_errors.json : últimos errores a nivel de código (ruta + tipo + traceback).

Lo que este paquete NO contiene, a propósito:
  - Ningún dato de survey (CSV, parquet, coordenadas, valores medidos).
  - Ninguna clave, token, licencia privada ni credencial.
  - Ningún cuerpo de petición.

Este ZIP lo generaste tú y lo envías tú, manualmente. Nada sale de tu máquina
sin tu acción explícita.
"""


def build_diagnostic_zip(dest_dir: Path | None = None) -> Path:
    """Escribe el ZIP de diagnóstico en el directorio de scratch y devuelve la
    ruta. Nunca incluye datos de survey ni secretos."""
    dest = dest_dir or config.TMP_DIR
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = dest / f"terraquantum_diagnostico_{stamp}.zip"

    manifest = diagnostic_manifest()
    packages_txt = "\n".join(f"{k}=={v}" for k, v in manifest["packages"].items())

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", _README)
        zf.writestr("system.json", json.dumps(manifest["system"], ensure_ascii=False, indent=2))
        zf.writestr("packages.txt", packages_txt)
        zf.writestr("config.json", json.dumps(manifest["config_sanitized"], ensure_ascii=False, indent=2, default=str))
        zf.writestr("connectivity.json", json.dumps(manifest["connectivity"], ensure_ascii=False, indent=2))
        zf.writestr("license.json", json.dumps(manifest["license"], ensure_ascii=False, indent=2))
        zf.writestr("recent_errors.json", json.dumps(manifest["recent_errors"], ensure_ascii=False, indent=2))

    return zip_path


# Rutas/artefactos de DATOS que jamás deben aparecer en el bundle (referencia
# para el test que inspecciona el ZIP).
FORBIDDEN_DATA_NAMES: List[str] = [
    ".parquet", ".csv", "block_model", "boreholes", "report_payload",
    "license.key", "api_keys.db", "terraquantum.db",
]
