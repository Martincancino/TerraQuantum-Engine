"""FASE 10 — Contratos declarados de la superficie de sistema (salud, licencia,
diagnóstico, conectividad).

Por qué existe este archivo. La Fase 9 dio camino de usuario a los 5 endpoints de
F7 y dejó anotado, con nombre, lo que NO arregló: *«no declaran `response_model`,
así que su esquema OpenAPI va vacío»*. Un esquema vacío no es un detalle
cosmético: es lo que impide **generar** los tipos del frontend y obliga a
escribirlos a mano mirando el código Python — que es exactamente la clase de bug
que la Fase 10 viene a eliminar (H-16).

Dos decisiones de diseño que hay que leer juntas, porque una sin la otra sería
peligrosa:

1. **`extra="allow"` en todo lo que el endpoint devuelve como `dict`.** MEDIDO
   con FastAPI 0.135.3 / Pydantic 2.13.0: un `response_model` ESTRICTO **filtra
   en silencio** los campos no declarados —

       @app.get("/x", response_model=Estricto)  -> {"a": 1}
       (el endpoint devolvía {"a": 1, "extra_no_declarado": "…"})

   Declarar un contrato incompleto sobre un endpoint vivo no documenta: **borra
   datos que el frontend ya consume**. Con `extra="allow"` el payload sale
   idéntico, y hay un test que lo comprueba llamando a los endpoints de verdad
   (`tests/test_fase10_contratos.py`).

2. **Los campos declarados son los MEDIDOS**, leyendo la respuesta real de
   `core/license_service.py`, `services/diagnostics_service.py` y
   `services/connectivity_service.py`, no los que uno esperaría encontrar.

**Asimetría real que este archivo hace visible en vez de tapar:**
`GET /license/status` devuelve `mode` (`licensed` | `local_free`) y
`POST /license/activate` **no lo devuelve nunca** — `activate_license()` no lo
añade. El frontend usaba UN SOLO tipo para las dos respuestas, con `mode`
obligatorio: leer `.mode` tras activar da `undefined` sin que TypeScript diga
nada. Aquí van dos modelos distintos. No se cambia la conducta del backend
(añadir un campo es decisión de producto, no de una fase de contratos): se
declara lo que hace, y el tipo generado hace que el compilador lo sepa.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# GET /health  y  GET /system-status
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Latido + IDENTIDAD del proceso (Fase 2, H-19).

    `instance_token` se OMITE cuando el proceso no recibió token por entorno —
    nunca se inventa. Por eso es opcional y no `""`.
    """
    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    service: str
    version: str
    pid: int
    instance_token: Optional[str] = None


class SystemPaths(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_dir: str
    projects_dir: str
    tmp_dir: str
    models_dir: str
    block_model: str


class SystemPathsExist(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_dir: bool
    projects_dir: bool
    tmp_dir: bool
    models_dir: bool
    block_model: bool


class SystemStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    service: str
    version: str
    host: str
    port: int
    paths: SystemPaths
    exists: SystemPathsExist


# ─────────────────────────────────────────────────────────────────────────────
# GET /system/connectivity
# ─────────────────────────────────────────────────────────────────────────────

class ConnectivityFeature(BaseModel):
    """Una función que puede necesitar internet, tal como la declara el backend."""
    model_config = ConfigDict(extra="allow")

    name: str
    key: str
    requires_internet: bool
    required_for_golden_path: bool
    configured: bool = Field(
        ...,
        description=(
            "¿Está lista para usarse? OJO: para el copiloto la clave la pone el "
            "usuario (BYO-key), así que `configured:false` NO significa «no "
            "disponible» — hay que mirar `user_supplied_key`."
        ),
    )
    local_fallback: bool = Field(
        ..., description="Hay una alternativa local que no necesita internet.")
    message: str
    user_supplied_key: Optional[bool] = Field(
        default=None,
        description=(
            "La clave la aporta el usuario desde la interfaz. Sin este campo, "
            "`configured:false` se lee como «no disponible», que es falso."
        ),
    )


class ConnectivitySummaryResponse(BaseModel):
    """Honestidad offline. `probed` es SIEMPRE `false`: el resumen no toca la red.

    La Fase 9 midió que este endpoint devolvía `probed: true` sin haber abierto
    jamás un socket. No se implementó el sondeo —meter red en el servicio que
    certifica que el producto es offline es contradictorio—: se dice la verdad,
    y `probe_requested` + `probe_note` explican por qué cuando alguien pide
    `?probe=true`.
    """
    model_config = ConfigDict(extra="allow")

    golden_path_offline: bool = Field(
        ...,
        description=(
            "El camino dorado (ingesta→inversión→3D→export) funciona sin conexión."
        ),
    )
    golden_path_note: str
    probed: bool = Field(
        ...,
        description=(
            "SIEMPRE `false`: este resumen no abre un socket jamás. Antes "
            "devolvía `true` sin tocar la red (defecto medido en la Fase 9)."
        ),
    )
    # El servicio los emite SIEMPRE (aunque `probe` sea false): son la
    # explicación de por qué no se sondeó, no un extra.
    probe_requested: Optional[bool] = Field(
        ..., description="El cliente pidió `?probe=true`.")
    probe_note: Optional[str] = Field(
        ..., description="Por qué no se sondeó pese a pedirlo.")
    online_features: List[ConnectivityFeature]


# ─────────────────────────────────────────────────────────────────────────────
# GET /license/status  y  POST /license/activate
# ─────────────────────────────────────────────────────────────────────────────

class LicenseLimits(BaseModel):
    """Límites tabulados del tier efectivo.

    OJO — `max_voxels` lo DECLARA el token; hoy **ninguna inversión lo
    comprueba** (`check_voxel_budget` no tiene llamador de producción, medido en
    la Fase 9). El panel lo rotula así; el contrato no promete un tope que no
    existe.
    """
    model_config = ConfigDict(extra="allow")

    max_voxels: Optional[int] = Field(
        default=None,
        description=(
            "Lo DECLARA el token; hoy ninguna inversión lo comprueba "
            "(`check_voxel_budget` no tiene llamador de producción, medido en la "
            "Fase 9). No prometer un tope que no se aplica."
        ),
    )
    watermark: bool = False


class LicenseStatusResponse(BaseModel):
    """`GET /license/status`.

    `tier` es cadena LIBRE dentro del token firmado: `license_service` no la
    valida contra un enumerado y sólo hay límites tabulados para
    `local`/`pro`/`free`. Cerrarla aquí sería inventar un contrato.
    """
    model_config = ConfigDict(extra="allow")

    valid: bool
    tier: str = Field(
        ...,
        description=(
            "Cadena LIBRE dentro del token firmado: el backend no la valida "
            "contra un enumerado y sólo hay límites tabulados para "
            "`local`/`pro`/`free`. Cerrarla en el cliente sería inventar."
        ),
    )
    reason: str = Field(
        ...,
        description="Motivo en español escrito por el backend: la única explicación del estado.",
    )
    # `Optional[...]` SIN default: la clave viene SIEMPRE, el valor puede ser
    # `null`. `= None` diría "puede faltar", que es otra cosa y obliga al
    # frontend a distinguir `undefined` de `null` sin motivo.
    licensee: Optional[str]
    product: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str] = Field(
        ..., description="ISO-8601, o `null` = licencia perpetua.")
    expired: bool
    source: str = Field(
        ...,
        description=(
            "De dónde salió el token vigente: `env` | `file` | `none`. `env` GANA "
            "sobre el archivo que escribe /license/activate, así que activar "
            "desde la UI puede quedar anulado en silencio — el panel lo avisa."
        ),
    )
    effective_tier: str
    limits: Optional[LicenseLimits]
    mode: str = Field(
        ...,
        description=(
            "`licensed` | `local_free`. SÓLO en /status: /license/activate no "
            "devuelve este campo."
        ),
    )


class LicenseActivationResponse(BaseModel):
    """`POST /license/activate`.

    Es el estado de licencia **sin `mode`** (medido: `activate_license()` no lo
    añade) y **con `activated`**. Y `activated` es la única condición de éxito:
    un token inválido responde **HTTP 200**, y existe el caso real
    `valid:true` + `activated:false` (licencia buena que no se pudo escribir en
    disco, con `reason` sobreescrito por el motivo).
    """
    model_config = ConfigDict(extra="allow")

    valid: bool
    tier: str
    reason: str
    # `Optional[...]` SIN default: la clave viene SIEMPRE, el valor puede ser
    # `null`. `= None` diría "puede faltar", que es otra cosa y obliga al
    # frontend a distinguir `undefined` de `null` sin motivo.
    licensee: Optional[str]
    product: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    expired: bool
    source: str
    effective_tier: str
    limits: Optional[LicenseLimits]
    activated: bool = Field(
        ...,
        description=(
            "LA condición de éxito. Un token inválido responde HTTP 200 con "
            "`activated:false`, así que mirar el código de estado no basta. Y "
            "existe `valid:true` + `activated:false`: licencia buena que no se "
            "pudo escribir en disco, con `reason` sobreescrito por el motivo."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /diagnostics/manifest
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosticManifestResponse(BaseModel):
    """Lo que va DENTRO del ZIP de diagnóstico, para poder mirarlo antes de
    descargarlo: es lo que hace comprobable la promesa de que no sale ningún
    dato de survey.

    `system`, `packages` y `config_sanitized` son mapas abiertos a propósito: su
    contenido depende de la máquina y de las variables presentes, y tabularlo
    aquí sería una lista que se queda vieja sin que nadie se entere.
    """
    model_config = ConfigDict(extra="allow")

    system: Dict[str, Any]
    packages: Dict[str, str]
    config_sanitized: Dict[str, Any]
    connectivity: ConnectivitySummaryResponse
    license: Dict[str, Any]
    recent_errors: List[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# GET /v2/history/runs  y  GET /v2/history/runs/{project_id}/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

class HistoryRun(BaseModel):
    """Una corrida registrada en SQLite (`services/project_store`).

    Sobrevive a reinicios del backend, a diferencia de `GET /project-runs` que
    escanea disco. `status` distingue `done` / `error` / `cancelled` / la corrida
    interrumpida por un cierre del proceso.
    """
    model_config = ConfigDict(extra="allow")

    project_id: str
    run_id: str
    status: str = Field(
        ...,
        description=(
            "`done` | `error` | `cancelled`, y también la corrida interrumpida "
            "por un cierre del proceso: sobrevive a reinicios del backend."
        ),
    )
    source: Optional[str] = None
    route: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    artifacts: Optional[Dict[str, Any]] = None


class HistoryRunsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runs: List[HistoryRun]
    count: int


class HistoryRunDetailResponse(BaseModel):
    """`found:false` con `run:null` es una respuesta LEGÍTIMA (HTTP 200), no un
    error: preguntar por una corrida que no existe no es fallar."""
    model_config = ConfigDict(extra="allow")

    run: Optional[HistoryRun]
    found: bool
