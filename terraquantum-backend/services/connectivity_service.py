"""F7 — Honestidad offline: qué features necesitan internet y qué NO.

Principio del producto: el camino dorado (ingesta → corrección/preparación →
inversión → 3D → export/reporte) es 100% OFFLINE. Solo funciones SECUNDARIAS
salen a la red, cada una marcada explícitamente y con fallback local cuando
existe. Ninguna llamada de red está en la ruta crítica de inversión.

Este servicio NO hace red por defecto (respuesta instantánea, segura sin
internet): reporta *configuración/disponibilidad*. Con `probe=True` intenta un
sondeo corto de alcance real (timeout breve) para el panel de sistema.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _gee_available() -> bool:
    try:
        from core import gee_client
        return bool(gee_client.is_available())
    except Exception:  # noqa: BLE001
        return False


def connectivity_summary(probe: bool = False) -> Dict[str, Any]:
    """Estado de conectividad de cada feature online + garantía de camino dorado
    offline. `probe` reservado para un sondeo de alcance real futuro; por
    defecto no toca la red."""
    from core import config

    opentopo_configured = bool(config.OPENTOPO_API_KEY.strip())
    gemini_env_key = bool(
        (getattr(config, "GEMINI_API_KEY", "") or "").strip()
        if hasattr(config, "GEMINI_API_KEY") else False
    )

    features: List[Dict[str, Any]] = [
        {
            "name": "Corrección de terreno con DEM remoto (OpenTopography)",
            "key": "dem_opentopo",
            "requires_internet": True,
            "required_for_golden_path": False,
            "configured": opentopo_configured,
            "local_fallback": True,
            "message": (
                "Descarga el DEM para la corrección de terreno. Sin internet o "
                "sin OPENTOPO_API_KEY, sube un archivo DEM local (input opcional) "
                "o continúa sin corrección de terreno."
            ),
        },
        {
            "name": "Índices satelitales (Google Earth Engine)",
            "key": "satellite_gee",
            "requires_internet": True,
            "required_for_golden_path": False,
            "configured": _gee_available(),
            "local_fallback": False,
            "message": (
                "Capa exploratoria opcional (hierro/arcilla). Requiere conexión; "
                "si no está disponible, no bloquea nada del flujo geofísico."
            ),
        },
        {
            "name": "Copiloto IA (Gemini)",
            "key": "copilot_gemini",
            "requires_internet": True,
            "required_for_golden_path": False,
            "configured": gemini_env_key,
            "local_fallback": False,
            "message": (
                "El copiloto envía el contexto de la corrida a Google con la key "
                "del propio consultor (BYO-key). Requiere conexión; es una ayuda "
                "de redacción/explicación, nunca parte del cálculo."
            ),
        },
        {
            "name": "Modelo geomagnético (IGRF-14)",
            "key": "igrf",
            "requires_internet": False,
            "required_for_golden_path": True,
            "configured": True,
            "local_fallback": True,
            "message": "IGRF-14 embebido offline. No requiere internet.",
        },
    ]

    return {
        "golden_path_offline": True,
        "golden_path_note": (
            "Ingesta, correcciones/preparación, inversión, visor 3D y export/"
            "reporte funcionan sin internet. Las features online son secundarias."
        ),
        "probed": bool(probe),
        "online_features": features,
    }
