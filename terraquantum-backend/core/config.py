import os
from pathlib import Path


APP_NAME = "terraquantum-backend"
APP_TITLE = "TerraQuantum Backend"
APP_VERSION = "0.2.0"

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

GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

# H-B3: OpenTopography API key for DEM fetch (terrain correction).
# Obtener en https://portal.opentopography.org/myopentopo
# Límites: 200 calls/día (académico), 50/día (sin key).
OPENTOPO_API_KEY: str = os.getenv("OPENTOPO_API_KEY", "")

# Flujo de datos de campo: piso de ruido instrumental por gravímetro [mGal].
# sigma_i = max(noise_floor, noise_pct * |d_i|) — el piso domina cuando la
# anomalía está bien corregida y el ruido restante es instrumental.
# Fuentes: especificaciones de fábrica (repetibilidad en campo).
GRAVIMETER_NOISE_FLOOR: dict = {
    "scintrex_cg6": 0.005,      # mGal
    "zls_burris": 0.002,
    "lacoste_romberg": 0.010,
    "unknown": 0.020,           # conservador para gravímetro desconocido
}

# FASE 20B Tarea 5: presets de susceptibilidad magnética por litología (SI volumétrico).
# Valores típicos para fijar bounds [susc_min, susc_max] o priors de litología en el
# motor magnético (magnetita masiva = χ alta; roca estéril/sedimentaria ≈ 0).
# Cada entrada: (susc_típica, susc_max_recomendado) en SI. Fuentes: Clark 1997
# (rangos de susceptibilidad de rocas y minerales); Hunt et al. 1995 (rock magnetism).
MAGNETIC_SUSCEPTIBILITY_PRESETS: dict = {
    "magnetite_massive": (1.0, 5.0),     # magnetita masiva (IOCG/skarn): χ muy alta
    "magnetite_disseminated": (0.1, 1.0),  # magnetita diseminada (pórfido magnético)
    "bif": (0.5, 3.0),                   # banded iron formation
    "chromite": (0.05, 0.5),
    "mafic_intrusive": (0.01, 0.2),      # gabro/diorita (magnetita accesoria)
    "granite": (0.001, 0.05),            # granito (mag-series vs ilmenite-series)
    "sediment_barren": (0.0, 0.01),      # roca estéril/sedimentaria ≈ 0
    "unknown": (0.0, 1.0),               # default conservador del schema
}

# HITO 5: Solver con bounds (B-06). Env var USE_BOUNDED_SOLVER=false fuerza LSQR+clip (rollback).
USE_BOUNDED_SOLVER: bool = os.getenv("USE_BOUNDED_SOLVER", "true").lower() != "false"

# Tier 1 A1: FISTA proyectado refina la solución LSQR/LSMR+clip para n>8K,
# respetando los bounds petrofísicos SIN clip destructivo (el clip degradaba
# el misfit ~35% en cuerpos compactos). USE_PROJECTED_SOLVER=false = rollback
# exacto al comportamiento clip.
USE_PROJECTED_SOLVER: bool = os.getenv("USE_PROJECTED_SOLVER", "true").lower() != "false"

# Sprint 5A: solver directo SuperLU para n_active > 8000. Default OFF (LSQR).
USE_SPARSE_DIRECT: bool = os.getenv("USE_SPARSE_DIRECT", "false").lower() == "true"

# Fase 10: LSMR para n_active > LSMR_THRESHOLD_N_ACTIVE (default 50K).
# LSMR tiene mejor convergencia que LSQR para sistemas mal condicionados.
# Default ON. Rollback: USE_LSMR_LARGE=false.
USE_LSMR_LARGE: bool = os.getenv("USE_LSMR_LARGE", "true").lower() != "false"
LSMR_THRESHOLD_N_ACTIVE: int = int(os.getenv("LSMR_THRESHOLD_N_ACTIVE", "50000"))

# Fase 10: Compresión wavelet del Jacobiano G (Farquharson & Oldenburg 2003).
# Default OFF — activar solo para surveys con n_active > WAVELET_THRESHOLD_N_ACTIVE.
# Requiere PyWavelets>=1.6.0 en requirements.txt.
USE_WAVELET_COMPRESSION: bool = os.getenv("USE_WAVELET_COMPRESSION", "false").lower() == "true"
WAVELET_THRESHOLD_N_ACTIVE: int = int(os.getenv("WAVELET_THRESHOLD_N_ACTIVE", "200000"))

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
