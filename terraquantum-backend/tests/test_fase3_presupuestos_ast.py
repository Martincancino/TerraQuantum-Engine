"""Fase 3 — el gate de presupuestos AST mide de verdad y puede fallar.

Un gate que no puede ponerse rojo es decorativo, y uno que mide cero pasa
siempre. Estos tests cubren las dos formas de que este gate se vuelva inútil sin
que nadie se entere:

* que la medición devuelva números vacíos (canario: el backend tiene funciones
  monstruosas conocidas y medidas; si no aparecen, el medidor está roto);
* que la comparación no detecte un empeoramiento.

La línea base vive en `scripts/ci/ast_baseline.json` y se commitea. Este archivo
también comprueba que sigue en sincronía con el árbol: si alguien deja crecer una
función y no actualiza la base, la CI lo dice.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "ci" / "ast_budgets.py"
BASELINE = BACKEND_ROOT / "scripts" / "ci" / "ast_baseline.json"


@pytest.fixture(scope="module")
def ab():
    spec = importlib.util.spec_from_file_location("tq_ast_budgets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registrar ANTES de ejecutar: `@dataclass` resuelve anotaciones mirando
    # sys.modules[cls.__module__] y sin esto revienta.
    sys.modules["tq_ast_budgets"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def medido(ab):
    return ab.to_baseline(ab.measure())


def test_the_baseline_exists_and_covers_every_package(ab, medido):
    assert BASELINE.is_file(), "falta scripts/ci/ast_baseline.json (corre --update)"
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert set(baseline) == set(ab.PACKAGES) == set(medido)


def test_the_tree_is_within_its_budget(ab, medido):
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    peor, _mejor = ab._compare(medido, baseline)
    assert not peor, (
        "El árbol superó su presupuesto de complejidad:\n  " + "\n  ".join(peor)
    )


def test_the_measurement_is_not_empty(medido):
    """Canario: el backend tiene monstruos medidos; si no salen, el medidor miente.

    MEDIDO 2026-08-11: `services/geophysics_service.py::run_geophysics_inversion`
    tenía 2.013 LOC y CC 183 — la espina dorsal que la Fase 8 iba a partir, y este
    canario exigía ver ese número «mientras siga ahí».

    **ACTUALIZADO 2026-08-16: ya no está ahí.** La Fase 8 lo dejó en 152 LOC y
    CC 12 con byte-identidad verificada, así que el umbral de 1.000 LOC dejó de
    describir el repositorio y pasó a describir el pasado. Se baja a 300 —el techo
    que la propia Fase 8 fija para el camino crítico— porque el canario existe para
    detectar que el MEDIDOR se rompió (devolvería ceros), no para exigir que el
    monolito siga vivo. Hoy el máximo de `services` es
    `gravity_import_service.py::_import_gravity_csv_v1_impl` (777 LOC, CC 181), que
    la Fase 8 dejó fuera a propósito por no ser la espina de inversión.
    """
    assert medido["services"]["cc_max"] > 100, medido["services"]
    assert medido["services"]["func_loc_max"] > 300, medido["services"]
    assert medido["exploration"]["loc"] > 5000
    assert medido["core"]["cc_max"] < 40, (
        "el Core dejó de ser simple: mira qué entró"
    )


def test_comparison_detects_a_regression(ab, medido):
    baseline = json.loads(json.dumps(json.loads(BASELINE.read_text(encoding="utf-8"))))
    baseline["services"]["cc_max"] = 50  # como si ayer fuera mucho más simple
    peor, _ = ab._compare(medido, baseline)
    assert any("services.cc_max" in linea for linea in peor)


def test_comparison_reports_an_improvement(ab, medido):
    baseline = json.loads(json.dumps(json.loads(BASELINE.read_text(encoding="utf-8"))))
    baseline["services"]["cc_max"] = 10_000
    peor, mejor = ab._compare(medido, baseline)
    assert not peor
    assert any("mejoro" in linea for linea in mejor), (
        "Una mejora sin aviso deja el listón alto por inercia: el gate debe "
        "invitar a bajar la línea base."
    )


def test_a_vanished_package_is_a_failure(ab, medido):
    baseline = json.loads(json.dumps(json.loads(BASELINE.read_text(encoding="utf-8"))))
    baseline["paquete_fantasma"] = {"files": 1, "loc": 1, "func_loc_max": 1, "cc_max": 1}
    peor, _ = ab._compare(medido, baseline)
    assert any("paquete_fantasma" in linea for linea in peor)


def test_cyclomatic_counts_what_it_promises(ab):
    import ast

    simple = ast.parse("def f():\n    return 1\n").body[0]
    assert ab._cyclomatic(simple) == 1

    ramificada = ast.parse(
        "def f(a, b):\n"
        "    if a and b:\n"          # +1 if, +1 boolop
        "        for x in a:\n"      # +1
        "            pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"   # +1
        "        pass\n"
        "    return [y for y in b]\n"  # +1 comprensión
    ).body[0]
    assert ab._cyclomatic(ramificada) == 6
