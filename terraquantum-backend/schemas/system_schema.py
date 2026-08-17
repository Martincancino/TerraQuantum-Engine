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
    #: Fase 9: `configured` responde «¿está lista para usarse?». Para el copiloto
    #: la clave la pone el usuario (BYO-key), así que `configured:false` NO
    #: significa «no disponible» — de ahí `user_supplied_key`.
    configured: bool
    local_fallback: bool
    message: str
    user_supplied_key: Optional[bool] = None


class ConnectivitySummaryResponse(BaseModel):
    """Honestidad offline. `probed` es SIEMPRE `false`: el resumen no toca la red.

    La Fase 9 midió que este endpoint devolvía `probed: true` sin haber abierto
    jamás un socket. No se implementó el sondeo —meter red en el servicio que
    certifica que el producto es offline es contradictorio—: se dice la verdad,
    y `probe_requested` + `probe_note` explican por qué cuando alguien pide
    `?probe=true`.
    """
    model_config = ConfigDict(extra="allow")

    golden_path_offline: bool
    golden_path_note: str
    probed: bool = False
    probe_requested: Optional[bool] = None
    probe_note: Optional[str] = None
    online_features: List[ConnectivityFeature] = Field(default_factory=list)


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

    max_voxels: Optional[int] = None
    watermark: bool = False


class LicenseStatusResponse(BaseModel):
    """`GET /license/status`.

    `tier` es cadena LIBRE dentro del token firmado: `license_service` no la
    valida contra un enumerado y sólo hay límites tabulados para
    `local`/`pro`/`free`. Cerrarla aquí sería inventar un contrato.
    """
    model_config = ConfigDict(extra="allow")

    valid: bool
    tier: str
    #: Motivo en español escrito por el backend: la única explicación del estado.
    reason: str
    licensee: Optional[str] = None
    product: Optional[str] = None
    issued_at: Optional[str] = None
    #: ISO-8601, o `null` = licencia perpetua.
    expires_at: Optional[str] = None
    expired: bool = False
    #: De dónde salió el token vigente. `env` GANA sobre `file`: activar desde la
    #: UI puede quedar anulado en silencio, y el panel lo avisa.
    source: str = "none"
    effective_tier: str
    limits: Optional[LicenseLimits] = None
    #: `licensed` | `local_free`. **Sólo en /status** — ver cabecera del módulo.
    mode: str


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
    licensee: Optional[str] = None
    product: Optional[str] = None
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    expired: bool = False
    source: str = "none"
    effective_tier: str
    limits: Optional[LicenseLimits] = None
    activated: bool


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

    system: Dict[str, Any] = Field(default_factory=dict)
    packages: Dict[str, str] = Field(default_factory=dict)
    config_sanitized: Dict[str, Any] = Field(default_factory=dict)
    connectivity: ConnectivitySummaryResponse
    license: Dict[str, Any] = Field(default_factory=dict)
    recent_errors: List[Dict[str, Any]] = Field(default_factory=list)


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
    status: str
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

    runs: List[HistoryRun] = Field(default_factory=list)
    count: int = 0


class HistoryRunDetailResponse(BaseModel):
    """`found:false` con `run:null` es una respuesta LEGÍTIMA (HTTP 200), no un
    error: preguntar por una corrida que no existe no es fallar."""
    model_config = ConfigDict(extra="allow")

    run: Optional[HistoryRun] = None
    found: bool = False
