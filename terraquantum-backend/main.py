import logging
import os
from pathlib import Path

# Load .env.local before any config imports so os.getenv picks up local values.
# Uses stdlib only — no python-dotenv dependency required.
_ENV_FILE = Path(__file__).parent / ".env.local"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.keys_api import router as keys_router
from api.metrics_api import router as metrics_router
from api.system_api import router as system_router
from api.geophysics_api import router as geophysics_router
from api.block_model_api import router as block_model_router
from api.gravity_import_api import router as gravity_import_router
from api.gravity_import_api import router_v2 as gravity_import_router_v2
from api.borehole_api import router as borehole_router
from api.multimodal_api import router as multimodal_router
from api.report_api import router as report_router
from api.project_api import router as project_router
from api.terrain_api import router as terrain_router
from api.favorability_api import router as favorability_router
from api.spectral_api import router as spectral_router
from api.export_api import router as export_router
from api.chat_api import router as chat_router
from api.gravity_corrections_api import router as gravity_corrections_router
from api.history_api import router as history_router
from api.mag_enhancement_api import router as mag_enhancement_router
from api.depth_estimate_api import router as depth_estimate_router

from core.config import (
    APP_TITLE,
    APP_VERSION,
    BACKEND_HOST,
    BACKEND_PORT,
    CORS_ORIGINS,
    MODELS_DIR,
    MODELS_ROUTE_PREFIX,
    TQ_AUTH_ENABLED,
    ensure_runtime_dirs,
)
from core.gee_client import init_gee
from core.metrics import PrometheusMiddleware
from core.observability import init_tracing, instrument_app
from core.rate_limit import limiter
from middleware.api_key_middleware import ApiKeyMiddleware

# Los módulos económicos/mineros (pit design, escenarios, métodos de minado,
# flota FMS) fueron ELIMINADOS del producto (2026-06-10): TerraQuantum es una
# plataforma de exploración geofísica — solo modelo 3D, sin NPV/LOM.
# ENABLE_FOCUSING: reservado para un futuro router de focusing MS-IRLS dedicado.
# El focusing actual corre internamente en geophysics_service; esta flag prepara
# la arquitectura para exponerlo como endpoint independiente cuando sea necesario.
_ENABLE_FOCUSING = os.environ.get("ENABLE_FOCUSING", "false").lower() == "true"

ensure_runtime_dirs()
init_gee()
init_tracing()

_startup_log = logging.getLogger(__name__)

# CORS safety: wildcard + credentials is rejected by browsers and signals misconfiguration.
if "*" in CORS_ORIGINS:
    _cors_warn = (
        "ADVERTENCIA DE SEGURIDAD: CORS_ALLOWED_ORIGINS contiene '*'. "
        "Combinado con allow_credentials=True esto viola la especificación CORS "
        "y los navegadores rechazarán las respuestas. "
        "Define orígenes explícitos en la var de entorno CORS_ALLOWED_ORIGINS."
    )
    _startup_log.error(_cors_warn)
    if TQ_AUTH_ENABLED:
        raise RuntimeError(_cors_warn)

# Auth safety: recordatorio visible si el backend arranca sin autenticación.
if not TQ_AUTH_ENABLED:
    _startup_log.warning(
        "MODO SIN AUTENTICACIÓN: TQ_AUTH_ENABLED=false. "
        "Todas las rutas son accesibles sin API key. "
        "En producción establece TQ_AUTH_ENABLED=true y configura TQ_MASTER_KEY."
    )

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── F2 — Contrato "nunca crashea": PROHIBIDO el 500 pelado ────────────────────
# Dos handlers globales:
#   1. TerraquantumError sin capturar → 422/500 con el payload COMPLETO del
#      catálogo ES (code/severity/user_message/suggested_action) — antes se
#      degradaba a {"detail": "Internal Server Error"} perdiendo la acción.
#   2. Exception sin capturar → 500 catalogado TQ_INTERNAL (mensaje y acción
#      en español + tipo y traceback truncado para diagnóstico).
# Los try/except específicos de cada endpoint siguen teniendo prioridad (más
# contexto); esto es la RED de seguridad transversal.
def _register_never_crash_handlers(fastapi_app: FastAPI) -> None:
    import traceback as _tb

    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse as _JSONResponse

    from core.errors import TerraquantumError, get_spec

    @fastapi_app.exception_handler(TerraquantumError)
    async def _tq_error_handler(request: _Request, exc: TerraquantumError):
        payload = exc.to_dict()
        status = 500 if exc.code == "TQ_INTERNAL" else 422
        return _JSONResponse(
            status_code=status,
            content={"detail": {"error": exc.code, "message": payload["user_message"], **payload}},
        )

    @fastapi_app.exception_handler(Exception)
    async def _unhandled_error_handler(request: _Request, exc: Exception):
        spec = get_spec("TQ_INTERNAL")
        _startup_log.error(
            "unhandled_exception path=%s type=%s error=%s",
            str(request.url.path), type(exc).__name__, str(exc)[:500],
        )
        return _JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "error": "TQ_INTERNAL",
                    "code": "TQ_INTERNAL",
                    "severity": spec.severity if spec else "error",
                    "message": spec.user_message if spec else str(exc),
                    "user_message": spec.user_message if spec else str(exc),
                    "suggested_action": spec.suggested_action if spec else "",
                    "type": type(exc).__name__,
                    "traceback": _tb.format_exc()[-2000:],
                }
            },
        )


_register_never_crash_handlers(app)

# ── Routers siempre activos (núcleo geofísico + datos) ───────────────────────
# F3: async_router (Celery/Redis) ELIMINADO — la vía asíncrona del producto es
# la nativa (run_queue_service + /geophysics-status), cero infraestructura.
app.include_router(keys_router)
app.include_router(metrics_router)
app.include_router(system_router)
app.include_router(geophysics_router)
app.include_router(block_model_router)
app.include_router(gravity_import_router)
app.include_router(gravity_import_router_v2)
app.include_router(borehole_router)
app.include_router(multimodal_router)
app.include_router(report_router)
app.include_router(project_router)
app.include_router(terrain_router)
app.include_router(favorability_router)
app.include_router(spectral_router)
app.include_router(export_router)
app.include_router(chat_router)
app.include_router(gravity_corrections_router)
app.include_router(history_router)
app.include_router(mag_enhancement_router)
app.include_router(depth_estimate_router)

# ── F3 — Historial SQLite: esquema + reconciliación de corridas huérfanas ─────
# Una corrida queued/running al arrancar quedó huérfana (los workers mueren con
# el proceso padre) → se marca "interrumpida" en vez de quedar colgada.
try:
    from services import project_store as _project_store

    _project_store.init_db()
    _n_reconciled = _project_store.reconcile_interrupted()
    if _n_reconciled:
        _startup_log.warning(
            "F3: %d corrida(s) huérfana(s) marcadas 'interrumpida' al arrancar.",
            _n_reconciled,
        )
except Exception as _exc:  # noqa: BLE001 — el historial jamás impide arrancar
    _startup_log.error("F3: init del historial SQLite falló: %s", _exc)

# Middleware order matters: last add_middleware = outermost layer.
# Stack: CORS (outer) → ApiKey → Prometheus (inner) → routes.
# Prometheus is innermost so it measures authenticated request latency only.
app.add_middleware(PrometheusMiddleware)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Accept",
        "Authorization",
        "X-TQ-API-Key",
        "X-TQ-Master-Key",
    ],
)

instrument_app(app)

app.mount(
    MODELS_ROUTE_PREFIX,
    StaticFiles(directory=str(MODELS_DIR)),
    name="models",
)


if __name__ == "__main__":
    import uvicorn

    print(f"Levantando TerraQuantum Backend en http://{BACKEND_HOST}:{BACKEND_PORT}")
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
