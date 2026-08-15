"""
Prometheus metrics — HITO 7 observability.

Exposed at GET /metrics (scraped by Prometheus).

Cardinality rules:
  - HTTP paths are normalized (route templates, not raw URIs) to avoid label explosion.

Fase 6 (cierre, H-13): las tres métricas de INVERSIÓN fueron ELIMINADAS
(`INVERSIONS_TOTAL`, `INVERSION_DURATION`, `ACTIVE_INVERSIONS`). Estaban definidas
y **ningún código las incrementaba**: el docstring de arriba enseñaba a instrumentar
una llamada que nunca se escribió. Con `ACTIVE_INVERSIONS` el daño era peor que
código muerto — un Gauge sin etiquetas SÍ se emite, así que `GET /metrics`
publicaba `terraquantum_active_inversions 0.0` **también mientras una inversión
estaba corriendo**: una lectura falsa, no una ausencia.

Lo que queda aquí (instrumentación HTTP) está VIVO: `PrometheusMiddleware` se monta
en `main.py` y mide cada request de verdad.

Si algún día se quiere telemetría de corridas, la fuente de verdad ya existe y no
es un contador paralelo: `services/run_queue_service` conoce activas y pendientes,
y `services/project_store` conoce estado y duración de cada corrida.
"""
import re
import time

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

# ── Metric definitions ────────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "terraquantum_http_requests_total",
    "Total HTTP requests handled",
    ["method", "path_template", "status_code"],
)

HTTP_REQUEST_DURATION = Histogram(
    "terraquantum_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path_template"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)


# ── Path normalizer (prevents cardinality explosion) ─────────────────────────

# Replace UUID-like hex IDs, numeric segments, and known ID patterns with placeholders.
_PATH_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"/[0-9a-f]{16,}"), "/{id}"),           # run_ids (hex)
    (re.compile(r"/[0-9a-f]{8}-[0-9a-f-]{27}"), "/{uuid}"),  # UUIDs
    (re.compile(r"/\d+"), "/{n}"),                        # pure numeric segments
]


def normalize_path(path: str) -> str:
    for pattern, replacement in _PATH_RULES:
        path = pattern.sub(replacement, path)
    return path


# ── HTTP instrumentation middleware ──────────────────────────────────────────

class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Records HTTP_REQUESTS_TOTAL and HTTP_REQUEST_DURATION for every request.
    The /metrics endpoint itself is excluded to avoid self-instrumentation noise.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        path_template = normalize_path(request.url.path)
        start = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start
        labels = {"method": request.method, "path_template": path_template}

        HTTP_REQUEST_DURATION.labels(**labels).observe(duration)
        HTTP_REQUESTS_TOTAL.labels(
            **labels, status_code=str(response.status_code)
        ).inc()

        return response


# ── /metrics response helper ──────────────────────────────────────────────────

def metrics_response() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
