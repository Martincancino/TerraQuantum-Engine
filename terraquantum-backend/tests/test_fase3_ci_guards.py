"""Fase 3 — la CI defiende lo que la documentación promete.

Estos tests no prueban física: prueban que **la red de seguridad existe y está
enchufada**. Son la respuesta a H-5 (la CI compilaba dos directorios que no
existen y pasaba en verde) y al patrón que lo hizo posible: listas de paquetes
mantenidas a mano en dos archivos distintos, ambas equivocadas de formas
distintas.

El invariante que imponen es simple: **ningún archivo de configuración vuelve a
llevar la lista de paquetes escrita a mano.** Se declara en un solo sitio
(`scripts/ci/compile_check.py`) y esa declaración se contrasta con el disco.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CHECK_PS1 = REPO_ROOT / "check.ps1"


def _load_compile_check():
    path = BACKEND_ROOT / "scripts" / "ci" / "compile_check.py"
    spec = importlib.util.spec_from_file_location("tq_compile_check", path)
    assert spec and spec.loader, f"no se pudo cargar {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["tq_compile_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compile_check():
    return _load_compile_check()


# ── El descubridor de paquetes ────────────────────────────────────────────────

def test_declared_packages_match_the_disk(compile_check):
    """El corazón de H-5: lo declarado y lo que existe tienen que coincidir."""
    discovered = compile_check.discover_packages(BACKEND_ROOT) - set(
        compile_check.NON_SOURCE_PACKAGES
    )
    missing, unexpected = compile_check.diff_packages(
        set(compile_check.DECLARED_PACKAGES), discovered
    )
    assert not missing, (
        "Paquetes declarados que ya no existen (esto es exactamente H-5): "
        f"{missing}"
    )
    assert not unexpected, (
        "Paquetes nuevos sin declarar; añadirlos a DECLARED_PACKAGES es parte "
        f"del PR que los crea: {unexpected}"
    )


def test_diff_detects_a_vanished_package(compile_check):
    """La regresión que la CI no vio durante meses, ahora en un assert."""
    missing, unexpected = compile_check.diff_packages(
        {"api", "workers"}, {"api"}
    )
    assert missing == ["workers"]
    assert unexpected == []


def test_diff_detects_an_undeclared_package(compile_check):
    missing, unexpected = compile_check.diff_packages({"api"}, {"api", "nuevo"})
    assert missing == []
    assert unexpected == ["nuevo"]


def test_discovery_ignores_directories_that_are_not_packages(compile_check, tmp_path):
    (tmp_path / "paquete").mkdir()
    (tmp_path / "paquete" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "sueltos").mkdir()  # sin __init__.py
    (tmp_path / "sueltos" / "algo.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()

    assert compile_check.discover_packages(tmp_path) == {"paquete"}


# ── La CI ya no mantiene la lista a mano ──────────────────────────────────────

def _executable_lines(text: str) -> str:
    """Quita los comentarios: lo que se juzga es lo que la CI EJECUTA.

    Hablar de `workers` en un comentario histórico es correcto — documentar por
    qué existe una guarda es parte de la guarda. Lo que no puede volver es que
    un comando la mencione.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_ci_delegates_the_compile_check():
    """`ci.yml` debe invocar el script, no repetir la lista de paquetes."""
    ci = CI_FILE.read_text(encoding="utf-8")
    assert "scripts/ci/compile_check.py" in ci, (
        "La CI debe llamar a scripts/ci/compile_check.py en vez de escribir a "
        "mano los directorios que compila."
    )
    commands = _executable_lines(ci)
    assert "compileall" not in commands, (
        "Volvió el compileall a mano en ci.yml — es la forma exacta en que "
        "apareció H-5."
    )
    for ghost in ("Camiones", "workers"):
        assert ghost not in commands, (
            f"'{ghost}' no existe en el árbol y un comando de ci.yml lo cita"
        )


def test_local_check_delegates_the_compile_check():
    """`check.ps1` llevaba su propia lista, distinta e incompleta."""
    check = CHECK_PS1.read_text(encoding="utf-8")
    assert "scripts/ci/compile_check.py" in check.replace("\\", "/"), (
        "check.ps1 debe usar el mismo comprobador que la CI; mantener dos "
        "listas fue lo que dejó middleware/ y reporting/ sin compilar en local."
    )
    assert "compileall" not in _executable_lines(check), (
        "volvió la lista a mano en check.ps1"
    )


def test_ci_runs_every_gate_of_this_phase():
    """Una puerta que no está enchufada a la CI no protege nada.

    Es el mismo error que H-4 (la regresión física existía y nunca corría) en
    versión pequeña: escribir el gate y no invocarlo.
    """
    ci = _executable_lines(CI_FILE.read_text(encoding="utf-8"))
    for gate in (
        "scripts/ci/ast_budgets.py",
        "scripts/ci/validation_inventory.py",
        "scripts/ci/deps_closure.py",
        "tests/test_fase3_capas.py",
        "tests/test_fase3_f9_no_evaluado.py",
        "tests/test_fase3_calibracion_absoluta.py",
    ):
        assert gate in ci, f"la CI no invoca {gate}"

    # H-4: la regresión física tiene que correr en alguna parte, y el canario
    # tiene que invocarse por nodeid (con `-m \"not slow\"` nunca se ejecutaría).
    assert "TQ_RUN_VALIDATION" in ci, "la CI sigue sin ejecutar la regresión física"
    assert "test_f9_physics_regression.py::" in ci, (
        "el canario de física debe invocarse por nodeid: el marcador `slow` lo "
        "deselecciona antes de que el skip de conftest entre en juego"
    )
    assert "f9_gate_regression.py" in ci, "falta el job nocturno de regresión física"


def test_local_check_runs_the_cheap_gates():
    check = _executable_lines(CHECK_PS1.read_text(encoding="utf-8")).replace("\\", "/")
    for gate in ("scripts/ci/ast_budgets.py", "scripts/ci/validation_inventory.py",
                 "scripts/ci/deps_closure.py"):
        assert gate in check, f"check.ps1 no corre {gate}"


# ── Lo que se descubrió AL CERRAR la fase ─────────────────────────────────────

def test_ci_covers_branches_with_a_slash():
    """`*` no cruza la barra en los filtros de GitHub Actions.

    Con `branches: ["*"]`, un push a `fix/algo` no disparaba ningún job. La CI
    existía y no cubría el nombre de rama más común del oficio.
    """
    ci = CI_FILE.read_text(encoding="utf-8")
    assert 'branches: ["*"]' not in ci, (
        'volvió `branches: ["*"]`: no cubre ramas con barra (fix/…, feature/…). '
        'Debe ser ["**"].'
    )
    assert 'branches: ["**"]' in ci, "el disparador de push debe cubrir ramas con barra"


def _archivos_con_tests_validation() -> set[str]:
    """Ficheros de tests/ que contienen algún test marcado `validation`.

    Se hace con AST (sin importar nada) y cubre las dos formas de marcar: el
    `pytestmark` de módulo y el decorador por test.
    """
    import ast

    encontrados: set[str] = set()
    for archivo in sorted((BACKEND_ROOT / "tests").glob("test_*.py")):
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            # Sólo `<algo>.mark.validation`, no cualquier atributo que se llame
            # `validation`: una guarda que acusa en falso se acaba desactivando.
            if (isinstance(nodo, ast.Attribute) and nodo.attr == "validation"
                    and isinstance(nodo.value, ast.Attribute) and nodo.value.attr == "mark"):
                encontrados.add(archivo.name)
                break
    return encontrados


# Ficheros cuyos tests `validation` NO se invocan desde ci.yml porque el gate
# nocturno `f9_gate_regression.py` ya re-invierte esos MISMOS datasets con el
# MISMO motor: correrlos además por pytest duplicaría entre 33 min y 6,9 h.
# Es una excepción declarada, no un olvido.
CUBIERTOS_POR_EL_GATE_F9 = {
    "test_f9_physics_regression.py",
}


def test_every_validation_test_runs_somewhere():
    """H-4, la mitad que quedaba abierta.

    El diseño de la fase pedía `pytest -m validation` completo. Medido al cerrar:
    los 8 tests `validation` llevan también `slow` (los deselecciona el job de PR)
    y el gate F9 es main()-only —no invoca pytest—, así que sólo UNO corría de
    verdad. Un test de regresión física que no corre es exactamente el hallazgo
    H-4 en pequeño.
    """
    ci = _executable_lines(CI_FILE.read_text(encoding="utf-8"))
    huerfanos = [
        nombre for nombre in sorted(_archivos_con_tests_validation())
        if nombre not in CUBIERTOS_POR_EL_GATE_F9 and nombre not in ci
    ]
    assert not huerfanos, (
        "estos ficheros tienen tests marcados `validation` que no corren en NINGÚN "
        f"job: {huerfanos}. Añádelos a un paso del nocturno (sin el filtro "
        '`-m "not slow"`, que los deselecciona antes del skip de conftest) o '
        "decláralos en CUBIERTOS_POR_EL_GATE_F9 con su motivo."
    )


def test_ci_pins_the_same_interpreter_that_ships():
    """La CI no puede validar con un intérprete distinto al que se empaqueta.

    Medido: `zarr==3.2.1` exige Python >= 3.12, así que en el 3.11 que fijaba la
    CI pip resolvía un **major distinto** del que corre en desarrollo y viaja en
    el instalador. La forma de que eso no vuelva a pasar es que la versión no se
    escriba a mano en dos sitios.
    """
    ci = CI_FILE.read_text(encoding="utf-8")
    assert "python-version-file" in ci, (
        "La CI debe leer terraquantum-backend/.python-version en vez de fijar "
        "un número a mano."
    )
    assert (BACKEND_ROOT / ".python-version").is_file()
