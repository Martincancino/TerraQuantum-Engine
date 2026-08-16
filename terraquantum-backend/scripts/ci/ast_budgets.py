"""Fase 3 — presupuestos de complejidad: la Fase 8 no puede deshacerse sola.

**Por qué.** El plan tiene una Fase 8 («partir la espina dorsal») cuyo valor se
evapora si, seis meses después, las funciones vuelven a crecer. La auditoría lo
dijo con estas palabras: publicar métricas AST como gate que **falla si
empeoran**. Eso es lo que hace este script.

**Cómo mide.** Sólo biblioteca estándar (`ast`), sin dependencias nuevas:

* `loc`  — líneas físicas del paquete (código, comentarios y blancos incluidos:
  lo que hay que leer).
* `func_loc_max` — la función más larga del paquete (última línea − primera + 1).
* `cc_max` — complejidad ciclomática de la función más ramificada, contando +1
  por cada `if`/`for`/`while`/`except`/`with`/`assert`, cada operador booleano,
  cada comprensión y cada expresión condicional. Es la definición práctica de
  McCabe; no pretende ser la de un libro, pretende ser **estable**.
* `args_max` — la firma más ancha del paquete (posicionales + keyword-only,
  `self` incluido; `*args`/`**kwargs` cuentan uno cada uno). **Añadido por la
  Fase 8**, cuyo criterio de aceptación pide `máx args ≤ 12` y que hasta ahora
  NADIE medía: el gate vigilaba longitud y ramas mientras `invert_gravity_csv`
  llevaba 41 parámetros y `solve_inversion_lsqr` 38.

**Cómo decide.** Compara contra `ast_baseline.json`, que se genera con
`--update` y se commitea. Un PR que empeore cualquier techo falla y dice
exactamente qué función. Un PR que lo mejore **también avisa** (con éxito), para
que la línea base se baje a propósito y el listón no se quede alto por inercia.

Uso (desde terraquantum-backend):
    python scripts/ci/ast_budgets.py            # gate: 0 si nadie empeoró
    python scripts/ci/ast_budgets.py --update   # re-mide y reescribe la línea base
    python scripts/ci/ast_budgets.py --top 10   # los peores ofensores de hoy
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "ast_baseline.json"

PACKAGES = ("api", "core", "exploration", "middleware", "reporting", "schemas", "services")

#: Margen de tolerancia. Un PR puede empeorar hasta este porcentaje sin romper la
#: CI — porque exigir "ni una línea más" convierte el gate en un obstáculo que se
#: desactiva. Por encima, hay que actualizar la línea base a propósito.
SLACK = 0.05

_BRANCHING = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.Assert, ast.IfExp,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)


@dataclass
class FuncMetric:
    name: str
    file: str
    line: int
    loc: int
    cc: int
    args: int = 0


@dataclass
class PackageMetric:
    files: int = 0
    loc: int = 0
    funcs: list[FuncMetric] = field(default_factory=list)

    @property
    def func_loc_max(self) -> FuncMetric | None:
        return max(self.funcs, key=lambda f: f.loc, default=None)

    @property
    def cc_max(self) -> FuncMetric | None:
        return max(self.funcs, key=lambda f: f.cc, default=None)

    @property
    def args_max(self) -> FuncMetric | None:
        return max(self.funcs, key=lambda f: f.args, default=None)


def _cyclomatic(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCHING):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


def _n_args(node: ast.AST) -> int:
    """Ancho de la firma. `self` cuenta: quien llama al método lo ve igual de ancho."""
    a = node.args
    total = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    total += 1 if a.vararg is not None else 0
    total += 1 if a.kwarg is not None else 0
    return total


def measure(root: Path = BACKEND_ROOT) -> dict[str, PackageMetric]:
    result: dict[str, PackageMetric] = {}
    for package in PACKAGES:
        metric = PackageMetric()
        for path in sorted((root / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            metric.files += 1
            metric.loc += len(source.splitlines())
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue  # lo caza compile_check.py, no este script
            rel = path.relative_to(root).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno) or node.lineno
                    metric.funcs.append(
                        FuncMetric(
                            name=node.name,
                            file=rel,
                            line=node.lineno,
                            loc=end - node.lineno + 1,
                            cc=_cyclomatic(node),
                            args=_n_args(node),
                        )
                    )
        result[package] = metric
    return result


def to_baseline(metrics: dict[str, PackageMetric]) -> dict:
    out: dict[str, dict] = {}
    for package, metric in metrics.items():
        worst_loc = metric.func_loc_max
        worst_cc = metric.cc_max
        worst_args = metric.args_max
        out[package] = {
            "files": metric.files,
            "loc": metric.loc,
            "func_loc_max": worst_loc.loc if worst_loc else 0,
            "func_loc_max_where": f"{worst_loc.file}:{worst_loc.line} {worst_loc.name}" if worst_loc else "",
            "cc_max": worst_cc.cc if worst_cc else 0,
            "cc_max_where": f"{worst_cc.file}:{worst_cc.line} {worst_cc.name}" if worst_cc else "",
            "args_max": worst_args.args if worst_args else 0,
            "args_max_where": f"{worst_args.file}:{worst_args.line} {worst_args.name}" if worst_args else "",
        }
    return out


def _compare(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    peor: list[str] = []
    mejor: list[str] = []
    for package, actual in sorted(current.items()):
        base = baseline.get(package)
        if base is None:
            peor.append(f"{package}: paquete nuevo sin linea base (corre --update)")
            continue
        for key in ("loc", "func_loc_max", "cc_max", "args_max"):
            if key not in base:
                # Métrica nueva sin línea base (p.ej. `args_max`, añadida en la
                # Fase 8): no se puede comparar, y fingir un techo de 0 haría
                # fallar la CI por existir. Se registra al correr `--update`.
                continue
            techo = base[key] * (1 + SLACK)
            if actual[key] > techo:
                donde = actual.get(f"{key}_where", "")
                peor.append(
                    f"{package}.{key}: {actual[key]} > {base[key]} (+{SLACK:.0%} = {techo:.0f}) "
                    f"{donde}"
                )
            elif actual[key] < base[key] * 0.9:
                mejor.append(f"{package}.{key}: {actual[key]} < {base[key]} (mejoro)")
    for package in baseline:
        if package not in current:
            peor.append(f"{package}: estaba en la linea base y ya no existe")
    return peor, mejor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="reescribe la linea base")
    parser.add_argument("--top", type=int, default=0, help="lista los N peores por complejidad")
    args = parser.parse_args()

    metrics = measure()
    current = to_baseline(metrics)

    if args.top:
        todas = [f for m in metrics.values() for f in m.funcs]
        print(f"{'CC':>4} {'LOC':>5} {'ARGS':>5}  funcion")
        for f in sorted(todas, key=lambda f: f.cc, reverse=True)[: args.top]:
            print(f"{f.cc:>4} {f.loc:>5} {f.args:>5}  {f.file}:{f.line} {f.name}")
        return 0

    if args.update or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(
            json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"linea base escrita en {BASELINE_PATH.name}")
        for package, data in sorted(current.items()):
            print(
                f"  {package:12} {data['files']:>3} archivos  {data['loc']:>6} LOC  "
                f"func_max={data['func_loc_max']:>4}  cc_max={data['cc_max']:>3}  "
                f"args_max={data['args_max']:>3}"
            )
        return 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    peor, mejor = _compare(current, baseline)

    for linea in mejor:
        print(f"  MEJORA  {linea}")
    if mejor:
        print("  (baja la linea base con --update para que la mejora quede protegida)")

    if peor:
        print("\nPRESUPUESTOS AST: FALLA")
        for linea in peor:
            print(f"  {linea}")
        print(
            "\nSi el crecimiento es deliberado, corre --update y explica en el PR "
            "por que el techo sube."
        )
        return 1

    print(f"presupuestos AST OK - {len(current)} paquetes dentro de su techo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
