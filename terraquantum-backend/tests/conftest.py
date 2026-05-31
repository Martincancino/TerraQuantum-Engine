import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
