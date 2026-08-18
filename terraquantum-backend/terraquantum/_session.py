"""FASE 11 — La sesión: el único sitio de esta API que habla con el backend.

## Por qué la API de scripting llama a los ENDPOINTS y no a los servicios

Era la decisión de diseño de la fase y se tomó midiendo. El camino dorado NO
vive entero en `services/`: `POST /v2/gravity-import/load-package` tiene ~250
líneas de orquestación **en el handler HTTP** — la grilla efectiva (si el
paquete trae `nx` lo usa, si no deriva el auto-grid), el ruteo magnético (mover
`g`→`magnetic_nt`), el σ por estación desde la mediana de la columna de
incertidumbre, la topografía sólo si el rango supera 10 m, los sondajes
persistidos para el visor, el presupuesto de vóxeles… Una API que reconstruyera
eso llamando a los servicios sería **una segunda implementación del camino
dorado**, y este proyecto ya sabe cómo acaba: H-29 fue un movimiento
multi-campo escrito a mano en dos sitios que divergieron.

Así que la sesión es un CLIENTE. Y como el backend es un ASGI, el cliente
puede hablarle **en el mismo proceso, sin servidor, sin red y sin puerto**:

    tq.Session()                              # ASGI en proceso (por defecto)
    tq.Session(base_url="http://127.0.0.1:8000")   # un backend ya levantado

Consecuencia comprobable, y hay un test que la comprueba: la API de scripting y
la interfaz web recorren **el mismo código**. Cuando el motor cambia, cambian
las dos, o falla el test.

## El rate-limiter, que es el hallazgo de esta fase

El informe justifica la fase con una frase: *«procesa estos 12 surveys con la
misma configuración»*. MEDIDO: por el camino natural eso **falla en el survey
número 11** con `429 Rate limit exceeded: 10 per 1 minute`, porque
`/v2/gravity-import/enrich-package` y `/load-package` están limitados a 10/min
por dirección de origen — y en proceso todas las llamadas comparten la misma
clave. La respuesta 429 **no trae `Retry-After`** (medido), así que un cliente
no puede saber cuánto esperar.

Política, explícita en el constructor (`rate_limit`):

* `"reset"` — vacía el contador antes de cada llamada. **Es el DEFAULT sólo en
  proceso**, y el motivo es que ahí el limitador no protege nada: no hay
  perímetro de red, el «cliente remoto» es el propio script. Vaciarlo no
  debilita una defensa, retira una que no está defendiendo.
* `"wait"` — **DEFAULT contra un backend remoto**: ahí el límite sí protege un
  servicio real, así que se respeta esperando. El backoff es CIEGO (5→10→20→40 s,
  tope `rate_limit_max_wait_s`) porque el servidor no dice cuánto falta.
* `"raise"` — no toca nada y deja subir `RateLimited`. Es el modo honesto para
  medir el límite, y el que usan los tests que lo comprueban.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .errors import RateLimited, TerraquantumError

#: Valores válidos de `Session(rate_limit=...)`. Los tres se ejercitan en
#: `tests/test_fase11_api_scripting.py` (criterio 3 de la plantilla de gate).
RATE_LIMIT_POLICIES: Tuple[str, ...] = ("reset", "wait", "raise")

#: Backoff ciego de la política "wait". No hay `Retry-After` que consultar.
_BACKOFF_S: Tuple[float, ...] = (5.0, 10.0, 20.0, 40.0)

#: Raíz del backend: la sesión en proceso tiene que poder importar `main`.
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def backend_root() -> pathlib.Path:
    """Directorio del backend (el que contiene `main.py`).

    Público porque los scripts de ejemplo lo usan para localizar datos de
    prueba sin depender del directorio de trabajo.
    """
    return _BACKEND_ROOT


class Session:
    """Punto de entrada de la API de scripting.

    Parámetros
    ----------
    base_url:
        `None` (por defecto) monta la app en proceso: ni servidor ni puerto.
        Una URL habla con un backend ya levantado (el de la app de escritorio,
        por ejemplo, o uno en Docker).
    api_key:
        Se envía como `X-TQ-API-Key`. Sólo hace falta si el backend corre con
        `TQ_AUTH_ENABLED=true` (modo servidor). En local-first la auth va
        apagada; si no se pasa, se toma de `TQ_API_KEY` del entorno.
    rate_limit:
        Uno de `RATE_LIMIT_POLICIES`. Ver la explicación en la cabecera del
        módulo. `None` = el default de cada transporte (`"reset"` en proceso,
        `"wait"` remoto).
    timeout_s:
        Plazo de UNA petición HTTP. El default es alto a propósito: una
        inversión síncrona de un survey real tarda minutos (MEDIDO: 255 s para
        Laguna del Maule con malla 12×12×8 y padding).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        rate_limit: Optional[str] = None,
        timeout_s: float = 3600.0,
    ) -> None:
        if rate_limit is not None and rate_limit not in RATE_LIMIT_POLICIES:
            raise ValueError(
                f"rate_limit inválido: {rate_limit!r}. Válidos: {RATE_LIMIT_POLICIES}."
            )
        self.base_url = base_url
        self.in_process = base_url is None
        self.rate_limit = rate_limit or ("reset" if self.in_process else "wait")
        self.rate_limit_max_wait_s = 150.0
        self.timeout_s = timeout_s
        self.api_key = api_key or os.environ.get("TQ_API_KEY") or None
        self._client: Any = None

    # ── Transporte ────────────────────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self.in_process:
            if str(_BACKEND_ROOT) not in sys.path:
                sys.path.insert(0, str(_BACKEND_ROOT))
            # El backend resuelve rutas de datos relativas a su raíz.
            os.environ.setdefault("TQ_AUTH_ENABLED", "false")
            from fastapi.testclient import TestClient  # httpx, ya declarada

            import main  # importa la app COMPLETA: middlewares, handlers, routers

            self._client = TestClient(main.app, raise_server_exceptions=False)
        else:
            import httpx

            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        cliente = self._client
        self._client = None
        if cliente is not None and hasattr(cliente, "close"):
            try:
                cliente.close()
            except Exception:  # noqa: BLE001 — cerrar nunca es motivo de fallo
                pass

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Rate limit ────────────────────────────────────────────────────────────

    def _reset_rate_limit(self) -> bool:
        """Vacía el contador del limitador. Sólo tiene sentido EN PROCESO.

        Devuelve si pudo hacerlo: contra un backend remoto el almacenamiento
        vive en el otro proceso y no hay nada que vaciar, así que la política
        `"reset"` degrada a `"wait"` con un aviso — no en silencio.
        """
        if not self.in_process:
            return False
        try:
            from core.rate_limit import limiter

            almacen = getattr(limiter, "_storage", None)
            if almacen is None:
                return False
            almacen.reset()
            return True
        except Exception:  # noqa: BLE001 — el limitador nunca rompe una corrida
            return False

    # ── Petición ──────────────────────────────────────────────────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Any] = None,
        files: Optional[Mapping[str, Any]] = None,
        expect_json: bool = True,
    ) -> Any:
        """Una llamada al backend, con la política de rate-limit aplicada.

        Devuelve el JSON decodificado (o `bytes` si `expect_json=False`).
        Cualquier respuesta que no sea 2xx sube como `TerraquantumError` con el
        código del catálogo dentro: **esta capa no convierte un fallo en un
        valor de retorno plausible.**
        """
        cliente = self._ensure_client()
        if self.rate_limit == "reset":
            self._reset_rate_limit()

        intentos = 0
        esperado_s = 0.0
        while True:
            kwargs: Dict[str, Any] = {}
            if params is not None:
                kwargs["params"] = params
            if data is not None:
                kwargs["data"] = data
            if json_body is not None:
                kwargs["json"] = json_body
            if files is not None:
                kwargs["files"] = files
            if not self.in_process:
                kwargs["timeout"] = self.timeout_s
            cabeceras = {"X-TQ-API-Key": self.api_key} if self.api_key else None
            if cabeceras:
                kwargs["headers"] = cabeceras

            respuesta = cliente.request(method, path, **kwargs)
            if respuesta.status_code != 429:
                break

            # 429. La política decide, y "reset" contra remoto degrada a espera.
            if self.rate_limit == "raise":
                raise RateLimited.from_response(path, 429, _cuerpo(respuesta))
            if intentos >= len(_BACKOFF_S) or esperado_s >= self.rate_limit_max_wait_s:
                err = RateLimited.from_response(path, 429, _cuerpo(respuesta))
                err.suggested_action = (
                    f"El backend limita esta ruta y ya se esperó {esperado_s:.0f} s. "
                    "Sube rate_limit_max_wait_s, reparte el lote en el tiempo, o "
                    "usa una sesión en proceso (donde el límite no protege nada)."
                )
                raise err
            espera = _BACKOFF_S[intentos]
            intentos += 1
            esperado_s += espera
            time.sleep(espera)

        if respuesta.status_code >= 400:
            raise TerraquantumError.from_response(path, respuesta.status_code, _cuerpo(respuesta))
        if not expect_json:
            return respuesta.content
        return _cuerpo(respuesta)

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    # ── Utilidades ────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """`GET /health`. Útil como primera línea de un script: si esto falla,
        el problema es el backend, no el dato."""
        return self.get("/health")


def _cuerpo(respuesta: Any) -> Any:
    try:
        return respuesta.json()
    except Exception:  # noqa: BLE001 — texto plano es un borde real (413, proxy)
        try:
            return respuesta.text
        except Exception:  # noqa: BLE001
            return None


def as_json_form(valor: Any) -> Optional[str]:
    """Serializa un campo de formulario que el backend espera como JSON.

    Los endpoints reciben `config_json`, `boreholes_json`, `column_map_json`…
    Que el usuario de la API escriba diccionarios de Python y no cadenas es
    justo la clase de fricción que esta fase viene a quitar.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False)


def csv_payload(origen: Any, *, nombre_por_defecto: str) -> Tuple[str, bytes]:
    """Normaliza «un CSV» a (nombre, bytes).

    Acepta una ruta (`str`/`Path`), `bytes` ya leídos, o un texto. Un consultor
    tiene archivos; un script generado tiene cadenas. Las dos cosas valen.
    """
    if isinstance(origen, (str, pathlib.Path)) and not _parece_contenido(origen):
        ruta = pathlib.Path(origen)
        if not ruta.is_file():
            raise TerraquantumError(
                f"No existe el archivo CSV: {ruta}",
                code="CSV_FILE_NOT_FOUND",
                suggested_action="Comprueba la ruta (¿relativa a otro directorio de trabajo?).",
            )
        nombre = ruta.name if ruta.name.lower().endswith(".csv") else f"{ruta.stem}.csv"
        return nombre, ruta.read_bytes()
    if isinstance(origen, bytes):
        return nombre_por_defecto, origen
    if isinstance(origen, str):
        return nombre_por_defecto, origen.encode("utf-8")
    raise TypeError(
        f"CSV no reconocido: {type(origen).__name__}. Usa una ruta, bytes o texto."
    )


def _parece_contenido(valor: Any) -> bool:
    """Un texto con salto de línea es CONTENIDO, no una ruta."""
    return isinstance(valor, str) and ("\n" in valor or "\r" in valor)


def iter_named(items: Iterable[Any]) -> Iterable[Tuple[int, Any]]:
    return enumerate(items)
