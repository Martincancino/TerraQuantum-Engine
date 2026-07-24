import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config, items):
    """F9: los tests marcados `validation` re-invierten el motor real (minutos) → NO
    corren en la suite normal ni en el CI rápido. Se ejecutan A DEMANDA cuando
    `TQ_RUN_VALIDATION=1` (lo pone el gate `scripts/validation/f9_gate_regression.py`)
    o con `--run-validation`. Por defecto se SALTAN (skip), nunca fallan por timeout."""
    if os.environ.get("TQ_RUN_VALIDATION") == "1" or config.getoption("--run-validation", default=False):
        return
    skip = pytest.mark.skip(reason="suite de validación física F9 (lenta): usar TQ_RUN_VALIDATION=1 o --run-validation")
    for item in items:
        if "validation" in item.keywords:
            item.add_marker(skip)


def pytest_addoption(parser):
    parser.addoption("--run-validation", action="store_true", default=False,
                     help="Ejecuta la suite de validación física F9 (lenta, re-invierte el motor).")


@pytest.fixture(scope="session", autouse=True)
def _add_backend_to_path():
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="session")
def backend_root():
    return BACKEND_ROOT


@pytest.fixture
def test_project_id():
    return f"pytest_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_run_id():
    return f"pytest_run_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Aísla el estado del rate limiter entre tests.

    Los endpoints FastAPI comparten un único `limiter` de slowapi (singleton de módulo
    en core.rate_limit) cuyo almacenamiento en memoria cuenta peticiones por
    (IP, endpoint) y PERSISTE entre tests del mismo proceso pytest. Sin reset, varios
    tests que golpean el mismo endpoint (p.ej. /v2/gravity-import/enrich-package,
    10/minuto) agotan el presupuesto y los ÚLTIMOS reciben 429 → fallo orden-dependiente
    que pasa aislado pero falla en suite. Reseteamos ANTES de cada test para darle a
    cada uno su propio presupuesto. No altera producción (el límite sigue activo en
    runtime); solo aísla estado compartido entre tests.
    """
    try:
        from core.rate_limit import limiter
    except Exception:
        yield
        return

    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield
