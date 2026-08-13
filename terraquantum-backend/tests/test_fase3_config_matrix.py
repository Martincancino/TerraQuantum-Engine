"""Fase 3 — la superficie de configuración se ejercita, no se documenta y ya.

La auditoría midió que **29 de 44 variables de entorno no las toca ningún test**
(H-11), y que entre ellas hay flags que prometen cosas que no hacen: el bloque
`USE_SPARSE_DIRECT` llamaba a una función inexistente y activarlo rompía la
inversión con `NameError` (H-2, ya eliminado en la Fase 6). Un flag documentado
que nadie ejercita es una promesa sin respaldo.

Esta es la mitad barata y completa del trabajo:

* **Inventario**: cada `os.getenv` de `core/config.py` está declarado abajo con
  su tipo. Una variable nueva sin declarar rompe la suite — que es el momento en
  que alguien decide si de verdad hace falta otra perilla.
* **Cada camino recarga**: se recarga `core.config` en un subproceso con un valor
  alternativo de cada variable. Barato (el módulo no importa nada pesado) y caza
  exactamente la clase de fallo del `int()` sin nombre.
* **Dos arranques completos**: la aplicación entera, en subproceso, con y sin
  autenticación.

**Límite declarado, para no exagerar lo que esto prueba:** que un flag *arranca*
no significa que *haga* lo que promete. Las perillas del solver
(`USE_BOUNDED_SOLVER`, `USE_PROJECTED_SOLVER`, `USE_LSMR_LARGE`) podrían estar
tan inertes como lo estuvieron las de wavelet, y esta sonda no lo vería: eso
exige una inversión medida, y va con la Fase 5.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_ROOT / "core" / "config.py"

#: nombre -> (tipo, valor alternativo con el que se prueba el camino)
#: El valor alternativo es SIEMPRE distinto del default: probar el default no
#: prueba nada.
DECLARED_ENV: dict[str, tuple[str, str]] = {
    "TERRAQUANTUM_DATA_DIR": ("ruta", "__TMP__"),
    "TERRAQUANTUM_HOST": ("str", "0.0.0.0"),
    "TERRAQUANTUM_PORT": ("int", "8099"),
    "TERRAQUANTUM_INSTANCE_TOKEN": ("str", "tq-test-token"),
    "CORS_ALLOWED_ORIGINS": ("lista", "http://localhost:4000"),
    "CSV_MAX_BYTES": ("int", "2048"),
    "GEMINI_MODEL_NAME": ("str", "gemini-x"),
    "GEMINI_CHAT_MODEL": ("str", "gemini-chat-x"),
    "GEMINI_REPORT_MODEL": ("str", "gemini-report-x"),
    "OPENTOPO_API_KEY": ("secreto", "clave-de-prueba"),
    "USE_BOUNDED_SOLVER": ("bool", "false"),
    "USE_PROJECTED_SOLVER": ("bool", "false"),
    "USE_LSMR_LARGE": ("bool", "false"),
    "LSMR_THRESHOLD_N_ACTIVE": ("int", "1234"),
    "OTEL_ENABLED": ("bool", "true"),
    "OTEL_SERVICE_NAME": ("str", "tq-test"),
    "OTEL_EXPORTER_OTLP_ENDPOINT": ("str", "http://localhost:4318"),
    "TQ_AUTH_ENABLED": ("bool", "true"),
    "TQ_MASTER_KEY": ("secreto", "tqmaster_de_prueba"),
    "TQ_LICENSE": ("secreto", "tqlic1.x.y"),
    "TQ_LICENSE_PUBLIC_KEY_HEX": ("secreto", "00" * 32),
    "TQ_FREE_MAX_VOXELS": ("int", "1000"),
}

#: Las que se parsean como entero: un valor basura debe morir NOMBRÁNDOSE.
INT_VARS = [name for name, (tipo, _) in DECLARED_ENV.items() if tipo == "int"]


def _env_names_in_config() -> set[str]:
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        etiqueta = getattr(func, "attr", None) or getattr(func, "id", None)
        if etiqueta in ("getenv", "_env_int") and node.args:
            primero = node.args[0]
            if isinstance(primero, ast.Constant) and isinstance(primero.value, str):
                nombres.add(primero.value)
    return nombres


def _run_probe(code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {k: v for k, v in os.environ.items() if k not in DECLARED_ENV}
    env.update(extra_env)
    # `main.py` carga `.env.local` para las claves AUSENTES; al fijarlas aquí
    # explícitamente, la prueba mide lo que declara y no lo que tenga la máquina.
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


# ── Inventario ────────────────────────────────────────────────────────────────

def test_every_config_variable_is_declared():
    encontradas = _env_names_in_config()
    sin_declarar = sorted(encontradas - set(DECLARED_ENV))
    fantasma = sorted(set(DECLARED_ENV) - encontradas)
    assert not sin_declarar, (
        f"Variables nuevas en core/config.py sin declarar aquí: {sin_declarar}. "
        "Declararlas es el momento de preguntarse si hace falta otra perilla."
    )
    assert not fantasma, (
        f"Declaradas aquí pero ya no existen en core/config.py: {fantasma}."
    )


# ── Cada camino recarga ───────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre", sorted(DECLARED_ENV))
def test_config_reloads_with_each_flag(nombre, tmp_path):
    _tipo, valor = DECLARED_ENV[nombre]
    if valor == "__TMP__":
        valor = str(tmp_path)
    probe = (
        "import json, core.config as c;"
        "print(json.dumps({'host': c.BACKEND_HOST, 'port': c.BACKEND_PORT}))"
    )
    res = _run_probe(probe, {nombre: valor})
    assert res.returncode == 0, (
        f"core.config no carga con {nombre}={valor!r}:\n{res.stderr[-1200:]}"
    )
    datos = json.loads(res.stdout.strip().splitlines()[-1])
    assert "host" in datos and "port" in datos


@pytest.mark.parametrize("nombre", INT_VARS)
def test_bad_integers_die_saying_which_variable(nombre):
    """El fallo tiene que decir QUÉ perilla está mal, no `invalid literal`."""
    probe = "import core.config"
    res = _run_probe(probe, {nombre: "no-soy-un-numero"})
    assert res.returncode != 0, f"{nombre} basura debería impedir el arranque"
    assert nombre in res.stderr, (
        f"El error de {nombre} no nombra la variable — quien lo reciba en la "
        f"máquina de un cliente no sabrá cuál de las veintitantas es:\n"
        f"{res.stderr[-600:]}"
    )


# ── Dos arranques completos de la aplicación ──────────────────────────────────

_APP_PROBE = (
    "import json;"
    "from fastapi.testclient import TestClient;"
    "import main;"
    "c = TestClient(main.app);"
    "h = c.get('/health');"
    "p = c.get('/__ruta_que_no_existe__');"
    "print(json.dumps({'health': h.status_code, 'inexistente': p.status_code}))"
)


def test_the_app_boots_without_auth(tmp_path):
    res = _run_probe(_APP_PROBE, {"TERRAQUANTUM_DATA_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr[-1500:]
    datos = json.loads(res.stdout.strip().splitlines()[-1])
    assert datos["health"] == 200
    assert datos["inexistente"] == 404, (
        "Sin autenticación una ruta inexistente debe dar 404. Si diera 401, el "
        "smoke de /health estaría midiendo una app que rechaza todo lo demás."
    )


def test_the_app_boots_with_auth_enabled(tmp_path):
    """`TQ_AUTH_ENABLED` está documentado como «rompería la UI si se activa».

    Ese es justo el tipo de afirmación que se pudre: aquí queda DECLARADO qué
    hace hoy — la app arranca y protege todo salvo las rutas públicas. El día
    que alguien arregle la UI, este test cambia de expectativa a propósito.
    """
    res = _run_probe(
        _APP_PROBE,
        {
            "TERRAQUANTUM_DATA_DIR": str(tmp_path),
            "TQ_AUTH_ENABLED": "true",
            "TQ_MASTER_KEY": "tqmaster_de_prueba",
        },
    )
    assert res.returncode == 0, res.stderr[-1500:]
    datos = json.loads(res.stdout.strip().splitlines()[-1])
    assert datos["health"] == 200, "/health es pública a propósito"
    assert datos["inexistente"] == 401, (
        "Con autenticación activada, todo lo que no sea público debe pedir clave."
    )
