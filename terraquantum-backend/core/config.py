import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Lee un entero de entorno diciendo QUÉ variable está mal si lo está.

    Fase 3. Antes esto era `int(os.getenv("CSV_MAX_BYTES", "10485760"))`, y un
    valor basura mataba el arranque con `ValueError: invalid literal for int()
    with base 10: 'abc'` — un mensaje que no nombra la variable. Quien lo recibe
    en la máquina de un cliente no tiene forma de saber cuál de las veintitantas
    es. El proceso sigue muriendo (un puerto inválido no admite continuación),
    pero ahora muere diciendo dónde mirar.
    """
    crudo = os.getenv(name)
    if crudo is None or crudo.strip() == "":
        return default
    try:
        return int(crudo.strip())
    except ValueError as exc:
        raise ValueError(
            f"La variable de entorno {name} debe ser un número entero; "
            f"llegó {crudo!r}. Corrígela (o bórrala para usar el valor por "
            f"defecto, {default})."
        ) from exc


APP_NAME = "terraquantum-backend"
APP_TITLE = "TerraQuantum Backend"
APP_VERSION = "0.2.0"

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_data_dir() -> Path:
    """Raíz de DATOS DE USUARIO (proyectos, corridas, historial SQLite, licencia,
    api keys).

    F7 local-first: en desarrollo vive junto al código (`<repo>/data`), pero el
    launcher de escritorio fija `TERRAQUANTUM_DATA_DIR` a una carpeta del usuario
    FUERA del árbol de instalación — %APPDATA%\\TerraQuantum\\data (Windows),
    ~/Library/Application Support/TerraQuantum/data (macOS),
    ~/.local/share/TerraQuantum/data (Linux) — para que los datos del cliente
    NUNCA se pierdan al actualizar la app y se respalden copiando UNA carpeta.
    Solo se mueven los DATOS del usuario; los assets de instalación
    (`public/models`, `tmp` de scratch) siguen junto al código.
    """
    env = os.getenv("TERRAQUANTUM_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return BASE_DIR / "data"


# DATOS DE USUARIO (portables vía TERRAQUANTUM_DATA_DIR en modo escritorio).
DATA_DIR = _resolve_data_dir()
PROJECTS_DIR = DATA_DIR / "projects"
# ASSETS DE INSTALACIÓN (siempre junto al código, NO se mueven con los datos).
TMP_DIR = BASE_DIR / "tmp"
PUBLIC_DIR = BASE_DIR / "public"
MODELS_DIR = PUBLIC_DIR / "models"

DEFAULT_BLOCK_MODEL_FILENAME = "block_model_001.parquet"
DEFAULT_BLOCK_MODEL_PATH = DATA_DIR / DEFAULT_BLOCK_MODEL_FILENAME
RUN_BLOCK_MODEL_FILENAME  = "block_model.parquet"
RUN_ANOMALY_FILENAME      = "block_model_anomaly.parquet"
RUN_FOCUSING_FILENAME     = "block_model_focusing.parquet"

MODELS_ROUTE_PREFIX = "/models"

# Fase 2 (H-15/H-21): el default es LOOPBACK, no todas las interfaces.
# El producto real es local-first y la API corre sin autenticación por defecto
# (TQ_AUTH_ENABLED=false), así que el binding a 127.0.0.1 es la única barrera
# real entre el motor de inversión y la red del sitio minero. El único camino
# que necesita exponerse —Docker— lo pide EXPLÍCITO (docker-compose.yml y el
# CMD del Dockerfile fijan 0.0.0.0), por lo que invertir el default no rompe
# nada y hace seguro por construcción cualquier lanzador futuro.
BACKEND_HOST = os.getenv("TERRAQUANTUM_HOST", "127.0.0.1")
BACKEND_PORT = _env_int("TERRAQUANTUM_PORT", 8010)

# Fase 2 (H-19): identidad del proceso. El orquestador de escritorio genera un
# token al arrancar y se lo pasa a ESTE proceso; luego pregunta por /health y
# compara. Así distingue "mi sidecar" de "un zombi de un arranque anterior o de
# otra aplicación que ocupa el puerto" — un fallo de identidad, no de
# disponibilidad. Vacío = nadie declaró identidad (desarrollo, Docker): /health
# no publica el campo y el chequeo se degrada a "responde y es TerraQuantum".
INSTANCE_TOKEN: str = os.getenv("TERRAQUANTUM_INSTANCE_TOKEN", "").strip()

_cors_raw = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000",
)
CORS_ORIGINS: list[str] = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()]

CSV_MAX_BYTES: int = _env_int("CSV_MAX_BYTES", 10485760)

GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

# F6 copiloto — modelos por tier (SDK google-genai). Todos configurables por env
# para no fijar un ID que aún no exista en la cuenta del consultor (BYO-key).
# Default seguro = GEMINI_MODEL_NAME (gemini-2.0-flash, verificado). Recomendación
# del plan (state-of-the-art 2026, ajustar por env cuando estén disponibles en la
# cuenta): chat ágil → "gemini-3.5-flash"; borrador de informe → "gemini-3.1-pro".
#   GEMINI_CHAT_MODEL   = chat conversacional anclado a la corrida (tier Flash).
#   GEMINI_REPORT_MODEL = reporte estructurado / borrador de informe (tier Pro).
GEMINI_CHAT_MODEL: str = os.getenv("GEMINI_CHAT_MODEL", GEMINI_MODEL_NAME)
GEMINI_REPORT_MODEL: str = os.getenv("GEMINI_REPORT_MODEL", GEMINI_MODEL_NAME)

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

# Fase 6 (H-2): USE_SPARSE_DIRECT ELIMINADA. Prometía un solver directo SuperLU
# para n_active > 8000, pero la función a la que llamaba no existía: activarla
# rompía la inversión con NameError. No se repara — formar las ecuaciones normales
# eleva cond(A) al cuadrado; LSMR (abajo) es la respuesta correcta para n grande.

# Fase 10: LSMR para n_active > LSMR_THRESHOLD_N_ACTIVE (default 50K).
# LSMR tiene mejor convergencia que LSQR para sistemas mal condicionados.
# Default ON. Rollback: USE_LSMR_LARGE=false.
USE_LSMR_LARGE: bool = os.getenv("USE_LSMR_LARGE", "true").lower() != "false"
LSMR_THRESHOLD_N_ACTIVE: int = _env_int("LSMR_THRESHOLD_N_ACTIVE", 50000)

# Fase 6 (H-13): USE_WAVELET_COMPRESSION y WAVELET_THRESHOLD_N_ACTIVE ELIMINADAS.
# Prometían activar la compresión wavelet del Jacobiano (Farquharson & Oldenburg
# 2003) por encima de cierto n_active, pero NINGÚN código las leía: el único
# consumidor posible era `solve_inversion_lsmr_wavelet`, que nunca se cableó y se
# borró en esta misma fase. Mismo pecado que USE_SPARSE_DIRECT: una perilla que
# promete un comportamiento y no despacha a ninguna parte.
# Los building blocks siguen vivos y con tests en `exploration/jacobian_wavelet.py`.

# Fase 6 (H-12): la abstracción de cloud storage (HITO 7) fue ELIMINADA junto con
# core/storage.py y la env var STORAGE_BACKEND. Tenía cero importadores: era una
# jerarquía de tres backends (local/S3/GCS, los dos últimos NotImplementedError)
# para una nube que el producto rechazó por estrategia (docs/02 §6: "NO es una
# plataforma cloud multi-tenant"). El almacenamiento local-first usa pathlib directo.

# F3: la configuración Celery/Redis (HITO 7) fue ELIMINADA — la vía asíncrona
# del producto es nativa (services/run_queue_service, workers de proceso,
# cero infraestructura que un local-first no debe pedir).

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


# ── F7 — Licenciamiento local-first (Ed25519, offline, sin servidor) ──────────
# Producto local-first: la licencia es una clave firmada offline (producto,
# cliente, tier, expiración) que el backend verifica en la propia máquina; NO
# hay servidor de activación (un dev solo no opera esa infraestructura).
#
# Regla dura: SIN emisor configurado o SIN archivo de licencia el backend corre
# en modo LOCAL LIBRE (sin límites, nunca bloquea el arranque ni el camino
# dorado). Los tiers con límites aplican solo cuando una licencia los declara
# (canal freemium de distribución) — jamás se castiga la instalación propia.
TQ_LICENSE_PRODUCT: str = "terraquantum"
# Archivo de licencia activo: en el directorio de DATOS del usuario, así se
# respalda y sobrevive actualizaciones junto al resto de los datos.
TQ_LICENSE_FILE: Path = DATA_DIR / "license.key"
# La licencia también puede inyectarse por env (CI, servidor de demo).
TQ_LICENSE_TOKEN: str = os.getenv("TQ_LICENSE", "")
# Clave PÚBLICA Ed25519 del emisor (Martín) que valida las licencias. La clave
# PRIVADA jamás va al repo — se usa offline para FIRMAR (ver
# scripts/mint_license.py --genkey). Vacío = sin emisor → modo local libre.
TQ_LICENSE_PUBLIC_KEY_HEX: str = os.getenv("TQ_LICENSE_PUBLIC_KEY_HEX", "")

# Límites por tier. `local` (default sin licencia) y `pro` = sin límite; `free`
# = tier de distribución gratuita con tope de vóxeles y marca de agua en export.
TQ_TIER_LIMITS: dict = {
    "local": {"max_voxels": None, "watermark": False},
    "pro":   {"max_voxels": None, "watermark": False},
    "free":  {"max_voxels": _env_int("TQ_FREE_MAX_VOXELS", 40000), "watermark": True},
}


def ensure_runtime_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
