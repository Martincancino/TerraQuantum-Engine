import os
from pathlib import Path


APP_NAME = "terraquantum-backend"
APP_TITLE = "TerraQuantum Backend"
APP_VERSION = "0.1.0"

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
TMP_DIR = BASE_DIR / "tmp"
PUBLIC_DIR = BASE_DIR / "public"
MODELS_DIR = PUBLIC_DIR / "models"

DEFAULT_BLOCK_MODEL_FILENAME = "block_model_001.parquet"
DEFAULT_BLOCK_MODEL_PATH = DATA_DIR / DEFAULT_BLOCK_MODEL_FILENAME
RUN_BLOCK_MODEL_FILENAME  = "block_model.parquet"
RUN_ANOMALY_FILENAME      = "block_model_anomaly.parquet"
RUN_FOCUSING_FILENAME     = "block_model_focusing.parquet"

MODELS_ROUTE_PREFIX = "/models"

BACKEND_HOST = os.getenv("TERRAQUANTUM_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("TERRAQUANTUM_PORT", "8010"))

_cors_raw = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000",
)
CORS_ORIGINS: list[str] = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()]

CSV_MAX_BYTES: int = int(os.getenv("CSV_MAX_BYTES", "10485760"))

GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-pro")

# HITO 5: Solver con bounds (B-06). Env var USE_BOUNDED_SOLVER=false fuerza LSQR+clip (rollback).
USE_BOUNDED_SOLVER: bool = os.getenv("USE_BOUNDED_SOLVER", "true").lower() != "false"

# SPRINT 5A: Solver directo disperso (SuperLU sobre ecuaciones normales) como
# reemplazo del path LSQR iterativo en grillas grandes (n>8000). OPT-IN: default
# false → comportamiento de producción intacto (LSQR+clip). Poner
# USE_SPARSE_DIRECT=true para benchmarquear el solver directo. Sin dependencias
# nuevas: usa scipy.sparse.linalg.splu (SuperLU ya incluido en scipy).
USE_SPARSE_DIRECT: bool = os.getenv("USE_SPARSE_DIRECT", "false").lower() == "true"

# HITO 7: Cloud storage abstraction.
# STORAGE_BACKEND env var is read by core/storage.py at import time.
# Valid values: "local" (default), "s3", "gcs".

# HITO 7: Celery async workers.
# Default points at a local Redis instance (docker run -d -p 6379:6379 redis:7-alpine).
CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# HITO 7: Observability — OpenTelemetry + Prometheus.
# OTEL_ENABLED=false (default) → zero overhead; set true to activate tracing.
# OTEL_EXPORTER_OTLP_ENDPOINT: omit for console exporter (dev), set for Jaeger/Tempo (prod).
OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "false").lower() == "true"
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "terraquantum-backend")
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

# HITO 7: Auth middleware (B-11).
# Default OFF para desarrollo local. En producción: TQ_AUTH_ENABLED=true + crear keys.
# TQ_MASTER_KEY es requerido para gestionar API keys via /api/keys/.
TQ_AUTH_ENABLED: bool = os.getenv("TQ_AUTH_ENABLED", "false").lower() != "false"
TQ_MASTER_KEY: str = os.getenv("TQ_MASTER_KEY", "")
TQ_API_KEYS_DB: Path = DATA_DIR / "api_keys.db"


def ensure_runtime_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
