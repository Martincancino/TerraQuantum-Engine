"""
Prometheus metrics — HITO 7 observability.

Exposed at GET /metrics (scraped by Prometheus).

Cardinality rules:
  - HTTP paths are normalized (route templates, not raw URIs) to avoid label explosion.
  - run_type labels: "gravity" | "magnetic" | "joint" | "unknown".
  - Status labels: "completed" | "error" | "queued".

Usage in services (optional instrumentation):
    from core.metrics import INVERSIONS_TOTAL, INVERSION_DURATION
    with INVERSION_DURATION.labels(run_type="gravity").time():
        run_geophysics_inversion(params)
    INVERSIONS_TOTAL.labels(run_type="gravity", status="completed").inc()
"""
import re
import time

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
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

INVERSIONS_TOTAL = Counter(
    "terraquantum_inversions_total",
    "Total inversion runs by type and outcome",
    ["run_type", "status"],
)

INVERSION_DURATION = Histogram(
    "terraquantum_inversion_duration_seconds",
    "Inversion wall-clock duration in seconds",
    ["run_type"],
    buckets=[5, 15, 30, 60, 120, 300, 600, 1800],
)

ACTIVE_INVERSIONS = Gauge(
    "terraquantum_active_inversions",
    "Number of inversions currently running (BackgroundTask or Celery STARTED)",
)

CELERY_TASKS_ENQUEUED = Counter(
    "terraquantum_celery_tasks_enqueued_total",
    "Total tasks enqueued in Celery",
    ["task_name"],
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
