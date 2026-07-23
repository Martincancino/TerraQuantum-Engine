"""F7 — Directorio de datos portable (local-first).

Sin env var: los datos viven junto al código (comportamiento dev intacto). Con
TERRAQUANTUM_DATA_DIR (modo escritorio → %APPDATA%): DATA_DIR y TODO lo derivado
(proyectos, licencia, api keys, historial SQLite) se mueven en bloque.
"""
import importlib
from pathlib import Path


def test_default_data_dir_is_next_to_code(monkeypatch):
    monkeypatch.delenv("TERRAQUANTUM_DATA_DIR", raising=False)
    from core import config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.DATA_DIR == cfg.BASE_DIR / "data"
        assert cfg.PROJECTS_DIR == cfg.BASE_DIR / "data" / "projects"
    finally:
        importlib.reload(cfg)


def test_resolver_reads_env_each_call(monkeypatch, tmp_path):
    from core import config as cfg
    target = tmp_path / "appdata" / "TerraQuantum" / "data"
    monkeypatch.setenv("TERRAQUANTUM_DATA_DIR", str(target))
    assert cfg._resolve_data_dir() == target
    monkeypatch.delenv("TERRAQUANTUM_DATA_DIR", raising=False)
    assert cfg._resolve_data_dir() == cfg.BASE_DIR / "data"


def test_all_user_data_paths_follow_env(monkeypatch, tmp_path):
    target = tmp_path / "TQData"
    monkeypatch.setenv("TERRAQUANTUM_DATA_DIR", str(target))
    from core import config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.DATA_DIR == target
        assert cfg.PROJECTS_DIR == target / "projects"
        assert cfg.TQ_LICENSE_FILE == target / "license.key"
        assert cfg.TQ_API_KEYS_DB == target / "api_keys.db"
        # Los assets de instalación NO se mueven con los datos.
        assert cfg.MODELS_DIR == cfg.BASE_DIR / "public" / "models"
        assert cfg.TMP_DIR == cfg.BASE_DIR / "tmp"
    finally:
        monkeypatch.delenv("TERRAQUANTUM_DATA_DIR", raising=False)
        importlib.reload(cfg)


def test_expanduser_supported(monkeypatch):
    from core import config as cfg
    monkeypatch.setenv("TERRAQUANTUM_DATA_DIR", "~/tq_data_test_marker")
    resolved = cfg._resolve_data_dir()
    assert "~" not in str(resolved)
    assert resolved == Path("~/tq_data_test_marker").expanduser()
    monkeypatch.delenv("TERRAQUANTUM_DATA_DIR", raising=False)
