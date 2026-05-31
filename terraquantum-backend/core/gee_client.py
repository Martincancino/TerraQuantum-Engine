import json
import os
from pathlib import Path

from core.config import BASE_DIR
from core.logging import get_logger

_log = get_logger(__name__)
_gee_available: bool = False


def init_gee() -> None:
    """Initialize GEE using a Service Account JSON.

    Fails silently so the app continues with mock data if credentials are
    missing, invalid, or the service account is not registered with GEE.
    Never logs credential contents.
    """
    global _gee_available

    creds_path = Path(
        os.getenv("GEE_CREDENTIALS_PATH", str(BASE_DIR / "credenciales_gee.json"))
    )

    if not creds_path.exists():
        _log.warning("gee_credentials_not_found", path=str(creds_path))
        return

    try:
        import ee  # local import: tolerates environments without the package

        with open(creds_path, encoding="utf-8") as f:
            data = json.load(f)

        service_email: str = data.get("client_email", "")
        if not service_email:
            _log.warning("gee_credentials_missing_client_email")
            return

        credentials = ee.ServiceAccountCredentials(service_email, str(creds_path))
        ee.Initialize(credentials)
        _gee_available = True
        _log.info("gee_initialized", account=service_email)

    except ImportError:
        _log.warning("gee_package_not_installed")
    except Exception as exc:
        # Truncate message to avoid leaking credential fragments from stack traces
        _log.warning("gee_init_failed", error=str(exc)[:200])


def is_available() -> bool:
    """Return True if GEE was initialized successfully."""
    return _gee_available
