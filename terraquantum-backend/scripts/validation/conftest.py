"""
conftest.py para scripts/validation/ — Fase 6

Agrega terraquantum-backend/ a sys.path ANTES de que pytest importe
los módulos de test, para que todos los scripts puedan hacer
`from exploration.gravimetry import ...` sin `sys.path.append()` manual.

También define fixtures compartidas usadas por los scripts de esta carpeta.
"""
import sys
from pathlib import Path

import pytest

# terraquantum-backend/ (parent.parent de scripts/validation/)
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def tmp_dir(tmp_path: Path) -> str:
    """Directorio temporal como str — fixture compatible con test_vtk_export.py."""
    return str(tmp_path)
