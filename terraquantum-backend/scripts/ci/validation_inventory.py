"""Fase 3 (H-22) — cada script de validación declara si es una PUERTA o un instrumento.

**El hallazgo.** La auditoría contó que de los 65 scripts de `scripts/validation/`
sólo 22 contienen un camino de salida distinto de cero: los otros 43 imprimen
números y dejan el juicio de PASS/FALLO a quien lea la salida. El problema no es
que existan —un diagnóstico es una herramienta legítima— sino que **el proyecto
los llama «gates» y cierra fases con ellos**. Dentro de seis meses nadie
recordará qué número era aceptable.

**La respuesta barata y honesta.** No reescribir 43 scripts: obligar a que cada
uno **declare lo que es**, y comprobar que la declaración se sostiene:

* `gate` — decide. Debe tener un camino de salida ≠ 0 verificable por AST.
* `diagnostico` — mide e imprime. **No puede citarse en la documentación como
  gate**: ahí está exactamente el engaño que H-22 describe.
* `biblioteca` — ni una cosa ni la otra; la importan otros.
* `tests` — colección de pytest (este directorio está en `testpaths`).

Un script nuevo sin declarar rompe el gate. Eso es deliberado: clasificarlo
cuesta treinta segundos y es el momento en que alguien decide si lo que acaba de
escribir protege algo o sólo informa.

Uso (desde terraquantum-backend):
    python scripts/ci/validation_inventory.py            # decide
    python scripts/ci/validation_inventory.py --update   # regenera el manifiesto
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
VALIDATION_DIR = BACKEND_ROOT / "scripts" / "validation"
MANIFEST_PATH = VALIDATION_DIR / "GATES.json"
DOCS_DIR = REPO_ROOT / "docs"

TIPOS = ("gate", "diagnostico", "biblioteca", "tests")


def decides(source: str) -> bool:
    """¿Tiene el script un camino de salida distinto de cero?

    Se mira el AST, no el texto: `sys.exit(main())` cuenta (main devuelve 1),
    `return 1` cuenta, `raise SystemExit(1)` cuenta. Un `exit(0)` no.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("exit", "_exit"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value not in (0, None):
                        return True
                    if isinstance(arg, ast.Call):  # sys.exit(main())
                        return True
        elif isinstance(node, ast.Return):
            value = node.value
            if isinstance(value, ast.Constant) and value.value == 1:
                return True
            if isinstance(value, ast.IfExp):
                for branch in (value.body, value.orelse):
                    if isinstance(branch, ast.Constant) and branch.value == 1:
                        return True
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if getattr(node.exc.func, "id", None) == "SystemExit":
                return True
    return False


def _first_docline(source: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(source)) or ""
    except SyntaxError:
        doc = ""
    linea = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return linea[:160]


def _classify(path: Path, source: str) -> str:
    if decides(source):
        return "gate"
    if re.search(r"^def test_", source, re.M):
        return "tests"
    if "def main(" in source or '__name__ == "__main__"' in source:
        return "diagnostico"
    return "biblioteca"


def scan() -> dict[str, dict]:
    inventario: dict[str, dict] = {}
    for path in sorted(VALIDATION_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        inventario[path.name] = {
            "tipo": _classify(path, source),
            "decide": decides(source),
            "que_hace": _first_docline(source),
        }
    return inventario


def _cited_as_gate_in_docs(gates: set[str]) -> dict[str, list[str]]:
    """Scripts que la documentación menciona en una frase que dice «gate».

    Con un matiz que evita el falso positivo obvio: si en la MISMA línea se cita
    un script que sí es gate, la palabra se refiere a ése. `docs/01` dice
    «`f9_gate_regression.py` + `f9_report.py` → gate PASS 6/6»: el gate es el
    primero, el segundo sólo dibuja el informe. Acusar ahí sería ruido, y un
    gate ruidoso se apaga.
    """
    citas: dict[str, list[str]] = {}
    nombres = {p.name for p in VALIDATION_DIR.glob("*.py")}
    for doc in sorted(DOCS_DIR.glob("*.md")):
        for numero, linea in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "gate" not in linea.lower():
                continue
            citados = {nombre for nombre in nombres if nombre in linea}
            if citados & gates:
                continue  # la palabra «gate» tiene dueño en esta línea
            for nombre in citados:
                citas.setdefault(nombre, []).append(f"{doc.name}:{numero}")
    return citas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    actual = scan()

    if args.update or not MANIFEST_PATH.exists():
        previo = {}
        if MANIFEST_PATH.exists():
            previo = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("scripts", {})
        for nombre, datos in actual.items():
            # Respeta una clasificación puesta a mano: la máquina propone, el
            # humano dispone (y su decisión sobrevive a los --update).
            if nombre in previo and previo[nombre].get("tipo_manual"):
                datos["tipo"] = previo[nombre]["tipo"]
                datos["tipo_manual"] = True
        MANIFEST_PATH.write_text(
            json.dumps(
                {
                    "_doc": (
                        "Fase 3 / H-22: cada script de scripts/validation/ declara si es "
                        "una PUERTA (gate: decide, exit != 0), un INSTRUMENTO (diagnostico: "
                        "mide e imprime), una BIBLIOTECA o una coleccion de TESTS. "
                        "Lo verifica scripts/ci/validation_inventory.py. Pon "
                        "\"tipo_manual\": true para que --update respete tu clasificacion."
                    ),
                    "scripts": actual,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        conteo = {t: sum(1 for d in actual.values() if d["tipo"] == t) for t in TIPOS}
        print(f"manifiesto escrito: {len(actual)} scripts {conteo}")
        return 0

    manifiesto = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["scripts"]
    problemas: list[str] = []

    sin_declarar = sorted(set(actual) - set(manifiesto))
    for nombre in sin_declarar:
        problemas.append(
            f"{nombre}: script nuevo sin declarar. Di si es 'gate', 'diagnostico', "
            f"'biblioteca' o 'tests' en GATES.json (hoy {'decide' if actual[nombre]['decide'] else 'NO decide'})."
        )
    for nombre in sorted(set(manifiesto) - set(actual)):
        problemas.append(f"{nombre}: declarado en GATES.json pero ya no existe.")

    for nombre, declarado in sorted(manifiesto.items()):
        if nombre not in actual:
            continue
        tipo = declarado.get("tipo")
        if tipo not in TIPOS:
            problemas.append(f"{nombre}: tipo '{tipo}' no valido.")
            continue
        if tipo == "gate" and not actual[nombre]["decide"]:
            problemas.append(
                f"{nombre}: declarado 'gate' pero NO tiene salida distinta de cero. "
                "Un gate que no puede fallar es decorativo."
            )

    declarados_gate = {n for n, d in manifiesto.items() if d.get("tipo") == "gate"}
    citas = _cited_as_gate_in_docs(declarados_gate)
    for nombre, sitios in sorted(citas.items()):
        tipo = manifiesto.get(nombre, {}).get("tipo")
        if tipo == "diagnostico":
            problemas.append(
                f"{nombre}: es un DIAGNOSTICO (no decide) y la documentacion lo llama gate "
                f"en {', '.join(sitios[:3])}. Ese es exactamente H-22: o lo conviertes en "
                "puerta, o la doc deja de llamarlo asi."
            )

    conteo = {t: sum(1 for d in manifiesto.values() if d.get("tipo") == t) for t in TIPOS}
    if problemas:
        print("INVENTARIO DE VALIDACION: FALLA")
        for p in problemas:
            print(f"  {p}")
        return 1

    print(
        f"inventario de validacion OK - {len(manifiesto)} scripts declarados {conteo}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
