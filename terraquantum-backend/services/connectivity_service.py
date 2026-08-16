"""F7 — Honestidad offline: qué features necesitan internet y qué NO.

Principio del producto: el camino dorado (ingesta → corrección/preparación →
inversión → 3D → export/reporte) es 100% OFFLINE. Solo funciones SECUNDARIAS
salen a la red, cada una marcada explícitamente y con fallback local cuando
existe. Ninguna llamada de red está en la ruta crítica de inversión.

Este servicio NO hace red NUNCA: reporta *configuración/disponibilidad*. El
parámetro `probe` se acepta por compatibilidad de firma, pero `probed` dice
siempre la verdad (ver `probe_note`).

FASE 9 — dos correcciones MEDIDAS sobre este mismo archivo, porque un indicador
de conectividad que miente es peor que no tener indicador:

  1. `copilot_gemini.configured` era **siempre False**: leía
     `config.GEMINI_API_KEY`, un atributo que NO EXISTE en `core/config.py`
     (allí sólo viven `GEMINI_MODEL_NAME`, `GEMINI_CHAT_MODEL`,
     `GEMINI_REPORT_MODEL`). El `hasattr` lo convertía en un False silencioso.
     La clave que el copiloto usa de verdad la resuelve
     `api/chat_api.py::_resolve_api_key` en este orden:
     petición (BYO-key pegada en la UI) → cabecera `X-Gemini-Api-Key` → env
     `GEMINI_API_KEY`. O sea: el copiloto es **BYO-key**, y "sin clave en el
     servidor" NO significa "no disponible". Se declara así, con campo propio.

  2. `probed` devolvía `True` cuando alguien pedía `probe=True`, **sin haber
     tocado la red jamás**. El sondeo nunca se implementó. Un panel que dijera
     "sondeado" sobre eso estaría inventando. No se implementa el sondeo (meter
     una llamada de red en el servicio que certifica que el producto es offline
     sería contradictorio): se dice la verdad y se explica por qué.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

#: Por qué `probed` es siempre False. Va en la respuesta para que la UI lo cite
#: en vez de inventarse una explicación.
PROBE_NOTE = (
    "Este resumen no sale a la red: reporta CONFIGURACIÓN, no alcance real. "
    "TerraQuantum es local-first y el camino dorado no depende de internet, así "
    "que no se hace ningún sondeo remoto para responder esta pregunta."
)


def _gee_available() -> bool:
    try:
        from services import gee_client
        return bool(gee_client.is_available())
    except Exception:  # noqa: BLE001
        return False


def _gemini_server_key() -> bool:
    """¿Hay clave de Gemini en el ENTORNO DEL SERVIDOR?

    Es la MISMA fuente que usa `api/chat_api.py::_resolve_api_key` como último
    recurso. No mira la BYO-key del usuario: ésa viaja en cada petición y no es
    estado del servidor, así que preguntarla aquí no tendría respuesta.
    """
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def connectivity_summary(probe: bool = False) -> Dict[str, Any]:
    """Estado de conectividad de cada feature online + garantía de camino dorado
    offline. NUNCA toca la red: `probed` es siempre False (ver `PROBE_NOTE`)."""
    from core import config

    opentopo_configured = bool(config.OPENTOPO_API_KEY.strip())
    gemini_env_key = _gemini_server_key()

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
            # El copiloto se usa pegando la clave EN LA INTERFAZ: que el servidor
            # no tenga `GEMINI_API_KEY` no lo deja inutilizable. Sin este campo,
            # `configured: false` se lee como "no disponible", que es falso.
            "user_supplied_key": True,
            "local_fallback": False,
            "message": (
                "El copiloto envía el contexto de la corrida a Google con la key "
                "del propio consultor (BYO-key): se pega en la interfaz y no se "
                "guarda en el servidor. Requiere conexión; es una ayuda de "
                "redacción/explicación, nunca parte del cálculo. "
                + (
                    "Hay además una clave en el entorno del servidor como último recurso."
                    if gemini_env_key
                    else "No hay clave en el entorno del servidor: pega la tuya en la interfaz."
                )
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
        # `probed` describe lo que PASÓ, no lo que se pidió. Antes devolvía
        # `bool(probe)` sin haber sondeado nada.
        "probed": False,
        "probe_requested": bool(probe),
        "probe_note": PROBE_NOTE,
        "online_features": features,
    }
