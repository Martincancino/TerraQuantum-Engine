"""FASE 11 — Administración: claves de API.

Está aparte del resto de la API a propósito. `enrich`/`run_inversion` son el
trabajo del consultor; esto es administración del despliegue, y sólo tiene
sentido en el modo SERVIDOR (`TQ_AUTH_ENABLED=true`), que es donde una clave
protege algo. En local-first la autenticación va apagada y estas funciones
responden 503 con el motivo — no fingen haber creado nada.

La Fase 9 declaró `/api/keys/` sin camino de usuario con este motivo: *«las
claves las emite Martín por CLI. Dueña: Fase 11, que es donde una key tiene
sentido»*. Aquí es donde tiene sentido: un script que corra contra un backend
remoto necesita una, y ésta es la vía sin abrir un navegador.

    tq.admin.create_api_key("lote-nocturno", master_key="…")
    tq.Session(base_url="http://…", api_key=<la clave devuelta>)

La clave en claro se muestra UNA vez (el backend guarda su hash): si se pierde,
se revoca y se emite otra.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ._pipeline import default_session
from ._session import Session
from .errors import TerraquantumError

_KEYS = "/api/keys/"


def _cabecera_maestra(master_key: Optional[str]) -> Dict[str, str]:
    clave = master_key or os.environ.get("TQ_MASTER_KEY") or ""
    if not clave:
        raise TerraquantumError(
            "Falta la clave maestra: estas operaciones la exigen.",
            code="MASTER_KEY_MISSING",
            suggested_action=(
                "Pasa master_key= o exporta TQ_MASTER_KEY. Es la misma variable "
                "que el backend lee para validar la cabecera X-TQ-Master-Key."
            ),
        )
    return {"X-TQ-Master-Key": clave}


def _peticion(session: Optional[Session], metodo: str, master_key: Optional[str],
              json_body: Optional[Any] = None) -> Any:
    ses = session or default_session()
    cliente = ses._ensure_client()  # noqa: SLF001 — la cabecera maestra no va en Session
    kwargs: Dict[str, Any] = {"headers": _cabecera_maestra(master_key)}
    if json_body is not None:
        kwargs["json"] = json_body
    respuesta = cliente.request(metodo, _KEYS, **kwargs)
    if respuesta.status_code >= 400:
        cuerpo: Any
        try:
            cuerpo = respuesta.json()
        except Exception:  # noqa: BLE001
            cuerpo = respuesta.text
        raise TerraquantumError.from_response(_KEYS, respuesta.status_code, cuerpo)
    return respuesta.json()


def create_api_key(name: str, *, master_key: Optional[str] = None,
                   session: Optional[Session] = None) -> str:
    """Emite una clave nueva y devuelve el valor EN CLARO (sólo esta vez)."""
    respuesta = _peticion(session, "POST", master_key, json_body={"name": name})
    clave = respuesta.get("key")
    if not clave:
        raise TerraquantumError(
            "El backend no devolvió la clave.", code="API_KEY_NOT_RETURNED",
            details=respuesta if isinstance(respuesta, dict) else {}, path=_KEYS,
        )
    return str(clave)


def list_api_keys(*, master_key: Optional[str] = None,
                  session: Optional[Session] = None) -> List[dict]:
    """Claves emitidas (prefijo del hash, nunca el valor en claro)."""
    respuesta = _peticion(session, "GET", master_key)
    if isinstance(respuesta, dict):
        return list(respuesta.get("keys") or [])
    return list(respuesta or [])


def revoke_api_key(key_hash_prefix: str, *, master_key: Optional[str] = None,
                   session: Optional[Session] = None) -> Dict[str, Any]:
    """Revoca una clave por el prefijo de su hash (lo que devuelve `list_api_keys`)."""
    return _peticion(
        session, "DELETE", master_key, json_body={"key_hash_prefix": key_hash_prefix}
    )


__all__ = ["create_api_key", "list_api_keys", "revoke_api_key"]
