"""
GET /metrics — Prometheus scrape endpoint.

Exposes all registered prometheus_client metrics in the standard text format.
Protected by X-TQ-API-Key (same as all other endpoints) unless
TQ_AUTH_ENABLED=false.

Scrape config for prometheus.yml:
    scrape_configs:
      - job_name: terraquantum
        static_configs:
          - targets: ["localhost:8010"]
        metrics_path: /metrics
        params:
          format: ["prometheus"]
        bearer_token: "<your-api-key>"     # maps to X-TQ-API-Key via relabeling,
        # OR use http_headers:             # or set the header directly:
        # http_headers:
        #   X-TQ-API-Key: <your-api-key>
"""
from fastapi import APIRouter
from fastapi.responses import Response

from core.metrics import metrics_response

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    return metrics_response()
