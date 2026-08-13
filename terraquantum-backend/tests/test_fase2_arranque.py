"""Fase 2 — la mitad de backend de "que el instalador falle en voz alta".

Cubre los tres hallazgos que se cierran del lado Python:

* **H-15/H-21** — el default de escucha es LOOPBACK. La API corre sin
  autenticación por defecto, así que el binding es la única barrera real; el
  único camino que necesita exponerse (Docker) lo pide explícito, y este test
  lo verifica leyendo los archivos de Docker para que invertir el default no
  pueda romperlo en silencio.
* **H-19** — `/health` publica IDENTIDAD (token de instancia + PID), no sólo un
  latido. Sin eso, el orquestador no puede distinguir su sidecar de un zombi
  que ocupa el puerto.
* **H-23** — reproducibilidad: ningún requisito queda sin techo, y la
  herramienta que produce el ejecutable distribuible está pineada exacta.

`TERRAQUANTUM_HOST` era una de las 29 variables que ningún test ejercitaba
(H-11): a partir de aquí, una regresión del default se ve.
"""
import importlib
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def _reload_config(monkeypatch, **env):
    """Recarga core.config con un entorno controlado y devuelve el módulo.

    Los valores son constantes de módulo evaluadas al importar, así que la única
    forma honesta de probar el DEFAULT es reimportar sin la variable puesta.
    """
    for key in ("TERRAQUANTUM_HOST", "TERRAQUANTUM_PORT", "TERRAQUANTUM_INSTANCE_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("core.config", None)
    module = importlib.import_module("core.config")
    return module


@pytest.fixture(autouse=True)
def _restore_config():
    """Deja core.config como estaba: otros tests importan sus constantes."""
    yield
    sys.modules.pop("core.config", None)
    importlib.import_module("core.config")


# ── H-15: el default de escucha ───────────────────────────────────────────────

def test_default_host_is_loopback(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert cfg.BACKEND_HOST == "127.0.0.1", (
        "El default de TERRAQUANTUM_HOST debe ser loopback: la API no tiene "
        "autenticación por defecto y el binding es la única barrera."
    )


def test_host_can_still_be_opened_explicitly(monkeypatch):
    """El camino que necesita exposición la pide — y la sigue obteniendo."""
    cfg = _reload_config(monkeypatch, TERRAQUANTUM_HOST="0.0.0.0")
    assert cfg.BACKEND_HOST == "0.0.0.0"


def test_docker_declares_its_exposure_explicitly():
    """Docker NO puede depender del default: dentro de un contenedor 0.0.0.0 es
    obligatorio para el mapeo de puertos. Si alguien borra esa línea, el
    contenedor deja de responder y este test lo dice antes que el usuario."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "TERRAQUANTUM_HOST=0.0.0.0" in compose, (
        "docker-compose.yml debe fijar TERRAQUANTUM_HOST=0.0.0.0 explícito."
    )
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "TERRAQUANTUM_HOST:-0.0.0.0" in dockerfile, (
        "El CMD del Dockerfile debe llevar su propio default 0.0.0.0."
    )


def test_desktop_launchers_pin_loopback():
    """Los tres lanzadores de escritorio fijan loopback explícito. Es defensa
    redundante a propósito: el default ya es seguro, pero un lanzador que
    heredara un .env ajeno no debe poder exponer el motor."""
    shell = (REPO_ROOT / "terraquantum-web" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert '"TERRAQUANTUM_HOST", "127.0.0.1"' in shell
    plan_b = (REPO_ROOT / "run_terraquantum_desktop.ps1").read_text(encoding="utf-8")
    assert "127.0.0.1" in plan_b


# ── H-19: /health publica identidad, no sólo un latido ────────────────────────

def _client():
    from api import system_api
    app = FastAPI()
    app.include_router(system_api.router)
    return app, system_api


def test_health_publishes_pid_and_no_token_when_unclaimed(monkeypatch):
    cfg = _reload_config(monkeypatch)
    app, system_api = _client()
    monkeypatch.setattr(system_api.app_config, "INSTANCE_TOKEN", cfg.INSTANCE_TOKEN, raising=False)

    body = TestClient(app).get("/health").json()

    assert body["status"] == "ok"
    assert body["service"] == "terraquantum-backend"
    assert body["pid"] == os.getpid()
    assert "instance_token" not in body, (
        "Sin token declarado no se inventa uno: el chequeo se degrada, no miente."
    )


def test_health_echoes_instance_token(monkeypatch):
    token = "tq-boot-0123456789abcdef"
    cfg = _reload_config(monkeypatch, TERRAQUANTUM_INSTANCE_TOKEN=token)
    assert cfg.INSTANCE_TOKEN == token

    app, system_api = _client()
    monkeypatch.setattr(system_api.app_config, "INSTANCE_TOKEN", token, raising=False)

    body = TestClient(app).get("/health").json()

    assert body["instance_token"] == token, (
        "El orquestador compara este valor con el que generó: es lo que "
        "distingue su sidecar de un zombi que ocupa el puerto."
    )
    assert body["pid"] == os.getpid()


def test_instance_token_is_trimmed(monkeypatch):
    cfg = _reload_config(monkeypatch, TERRAQUANTUM_INSTANCE_TOKEN="  abc  ")
    assert cfg.INSTANCE_TOKEN == "abc"


def test_blank_instance_token_is_not_identity(monkeypatch):
    cfg = _reload_config(monkeypatch, TERRAQUANTUM_INSTANCE_TOKEN="   ")
    assert cfg.INSTANCE_TOKEN == ""


# ── H-23: reproducibilidad del build ──────────────────────────────────────────

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]+\])?\s*(.*)$")


def _requirement_lines(path: Path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        yield line


def test_no_requirement_is_unbounded():
    """Un `>=` sin techo permite que el mismo commit produzca un binario
    distinto meses después. Cada requisito debe estar pineado exacto (razón
    numérica) o acotado por arriba (razón de cadena de suministro)."""
    unbounded = []
    for line in _requirement_lines(BACKEND_ROOT / "requirements.txt"):
        match = _REQ_LINE.match(line)
        assert match, f"Línea de requisito no parseable: {line!r}"
        spec = match.group(3)
        pinned = "==" in spec
        capped = "<" in spec
        if not (pinned or capped):
            unbounded.append(line)
    assert not unbounded, (
        "Requisitos sin techo ni pin exacto (H-23): " + ", ".join(unbounded)
    )


def test_build_toolchain_is_pinned_exactly():
    build_req = BACKEND_ROOT / "requirements-build.txt"
    assert build_req.exists(), (
        "Falta requirements-build.txt: pyinstaller produce el ejecutable que se "
        "firma y distribuye, y debe estar pineado."
    )
    lines = list(_requirement_lines(build_req))
    assert any(line.lower().startswith("pyinstaller==") for line in lines), (
        f"pyinstaller debe estar pineado exacto; encontrado: {lines}"
    )


def test_numeric_core_stays_pinned_exact():
    """Lo que decide el RESULTADO numérico se pinea exacto, no se acota. Esta
    parte ya estaba bien hecha; el test evita que se relaje por comodidad."""
    text = (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("numpy", "scipy", "pyproj", "polars"):
        assert re.search(rf"^{pkg}==", text, re.MULTILINE), (
            f"{pkg} debe seguir pineado exacto (determinismo del solver)."
        )


def test_python_version_is_declared():
    marker = BACKEND_ROOT / ".python-version"
    assert marker.exists(), "Falta .python-version: el intérprete es parte del build."
    value = marker.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"3\.\d+(\.\d+)?", value), f".python-version inválido: {value!r}"
