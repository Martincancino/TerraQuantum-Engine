"""F7 — "Exportar diagnóstico" compatible con confidencialidad.

Garantía central: el bundle contiene SOLO archivos de metadatos fijos y JAMÁS un
secreto (master key, api key, licencia privada) ni un archivo de datos de survey
(.parquet/.csv/.db). El test SEMBRÁ secretos y verifica que no aparecen.
"""
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import diagnostics_buffer
from services import diagnostics_service as ds

EXPECTED_ENTRIES = {
    "README.txt", "system.json", "packages.txt", "config.json",
    "connectivity.json", "license.json", "recent_errors.json",
}

# Extensiones de archivos de DATOS que NUNCA deben ser una entrada del ZIP.
DATA_FILE_EXTS = (".parquet", ".csv", ".db", ".npy", ".npz", ".glb", ".vtu", ".vtr", ".tqpkg")


@pytest.fixture
def built_zip(tmp_path):
    diagnostics_buffer.clear()
    diagnostics_buffer.record_error("/geophysics-invert", "ValueError", "Traceback ...\nValueError: x")
    return ds.build_diagnostic_zip(dest_dir=tmp_path)


def test_bundle_has_exactly_the_metadata_files(built_zip):
    with zipfile.ZipFile(built_zip) as zf:
        assert set(zf.namelist()) == EXPECTED_ENTRIES


def test_bundle_contains_no_data_file_entries(built_zip):
    with zipfile.ZipFile(built_zip) as zf:
        for name in zf.namelist():
            assert not name.lower().endswith(DATA_FILE_EXTS), f"dato de survey filtrado: {name}"


def test_bundle_leaks_no_secrets(tmp_path, monkeypatch):
    """Sembramos secretos en config y verificamos que NO aparecen en el bundle."""
    sentinel_master = "SENTINEL_MASTER_KEY_9f3a"
    sentinel_apikey = "SENTINEL_API_KEY_7c1d"
    sentinel_privkey = "SENTINEL_PRIVATE_HEX_deadbeef"
    monkeypatch.setattr("core.config.TQ_MASTER_KEY", sentinel_master, raising=False)
    # Atributo secreto arbitrario (marcador KEY en el nombre) para el filtro.
    monkeypatch.setattr("core.config.SOME_SECRET_API_KEY", sentinel_apikey, raising=False)
    monkeypatch.setattr("core.config.TQ_LICENSE_TOKEN", sentinel_privkey, raising=False)

    z = ds.build_diagnostic_zip(dest_dir=tmp_path)
    with zipfile.ZipFile(z) as zf:
        blob = " ".join(zf.read(n).decode("utf-8", "ignore") for n in zf.namelist())

    assert sentinel_master not in blob
    assert sentinel_apikey not in blob
    # El token de licencia crudo tampoco se serializa (license.json lleva solo estado).
    assert sentinel_privkey not in blob


def test_manifest_captures_recent_error():
    diagnostics_buffer.clear()
    diagnostics_buffer.record_error("/foo", "RuntimeError", "boom")
    m = ds.diagnostic_manifest()
    assert m["recent_errors"] and m["recent_errors"][-1]["type"] == "RuntimeError"
    # El error registra path + tipo + traceback, nunca un body de request.
    assert set(m["recent_errors"][-1].keys()) == {"ts", "path", "type", "traceback"}


def test_config_section_excludes_secret_named_fields(monkeypatch):
    monkeypatch.setattr("core.config.TQ_MASTER_KEY", "zzz", raising=False)
    cfg = ds._sanitized_config()
    for name in cfg:
        assert not any(mark in name for mark in ds._SECRET_MARKERS)


def test_export_endpoint_returns_zip(tmp_path, monkeypatch):
    from api import diagnostics_api
    monkeypatch.setattr("core.config.TMP_DIR", tmp_path, raising=False)

    app = FastAPI()
    app.include_router(diagnostics_api.router)
    client = TestClient(app)

    r = client.get("/diagnostics/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    m = client.get("/diagnostics/manifest").json()
    assert "system" in m and "connectivity" in m and "license" in m
    assert json.dumps(m)  # serializable
