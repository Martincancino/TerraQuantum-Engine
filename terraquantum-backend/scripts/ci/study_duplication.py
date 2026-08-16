# -*- coding: utf-8 -*-
"""FASE 7 — medidor de duplicación estructural entre módulos del backend.

La auditoría 06 (§9B.1, hallazgo H-9) midió **228 ventanas duplicadas** entre
`exploration/gravimetry.py` y `exploration/magnetometry.py` y fijó como criterio
de aceptación de la Fase 7 bajar de 40 «medido con el mismo script». Ese script
no estaba en el repositorio: era una herramienta ad-hoc del auditor. Sin él, el
criterio no es verificable y la fase no se puede cerrar midiendo.

Esto lo reconstruye a partir del método que la auditoría describe:

  «normalización de tokens (se eliminan comentarios, docstrings, literales y
   nombres de identificadores; se conserva la estructura), ventanas deslizantes
   de 12 líneas, huella criptográfica»

Reconstruido ≠ idéntico: el número absoluto de la línea base puede no coincidir
con el 228 del informe porque los detalles finos (qué archivos se barren, si una
línea en blanco corta la ventana, cómo se cuenta una coincidencia múltiple) no
están escritos. Por eso este script **congela su propia línea base** en
`scripts/ci/duplication_baseline.json` y el gate compara contra ella. Lo que se
defiende es la propiedad —«la duplicación no vuelve a subir»— con un medidor
estable, no un número heredado de una herramienta perdida.

Normalización, en concreto:
  * `NAME`  → `K` si es palabra clave (se conserva cuál), `N` si es identificador
              → renombrar variables NO esconde el clon.
  * `NUMBER`/`STRING` → `#` / `S`  → cambiar constantes o textos tampoco.
  * `OP` se conserva literal: es la estructura.
  * comentarios, líneas en blanco, y líneas cuyo único contenido es un string
    (docstrings) se descartan ANTES de formar las ventanas.

Uso:
    python scripts/ci/study_duplication.py                 # informe legible
    python scripts/ci/study_duplication.py --json          # informe máquina
    python scripts/ci/study_duplication.py --update        # (re)congela la base
    python scripts/ci/study_duplication.py --gate          # exit 1 si empeora
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import token as token_mod
import tokenize
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "duplication_baseline.json"

#: Paquetes barridos. Es el backend de producción: se excluyen tests, scripts,
#: build/ y dist/ porque duplicar un `assert` entre dos tests no es deuda.
PACKAGES = ("api", "core", "exploration", "middleware", "reporting", "schemas", "services")

#: Ventana deslizante, en líneas de código normalizadas (§9B.1 usa 12).
WINDOW = 12

#: El par que la Fase 7 tiene que bajar. El gate lo vigila explícitamente.
FASE7_PAIR = ("exploration/gravimetry.py", "exploration/magnetometry.py")

#: Umbral del criterio de aceptación (a) de la Fase 7.
FASE7_MAX = 40


def _normalized_lines(path: Path) -> list[tuple[int, str]]:
    """Devuelve [(línea_física, firma_normalizada)] para las líneas con código.

    Una línea lógica repartida en varias físicas produce una sola entrada, anclada
    en su primera línea: así el conteo no depende del ancho de la envoltura.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []

    por_linea: dict[int, list[str]] = defaultdict(list)
    ancla: dict[int, int] = {}
    linea_logica_actual: int | None = None

    for tok in toks:
        tt, txt, (row, _c), _end, _line = tok
        if tt in (token_mod.COMMENT, token_mod.NL, token_mod.INDENT,
                  token_mod.DEDENT, token_mod.ENCODING, token_mod.ENDMARKER):
            continue
        if tt == token_mod.NEWLINE:
            linea_logica_actual = None
            continue
        if linea_logica_actual is None:
            linea_logica_actual = row
            ancla[linea_logica_actual] = row
        if tt == token_mod.NAME:
            por_linea[linea_logica_actual].append(txt if txt in _KEYWORDS else "N")
        elif tt == token_mod.NUMBER:
            por_linea[linea_logica_actual].append("#")
        elif tt == token_mod.STRING or tt == getattr(token_mod, "FSTRING_START", -1):
            por_linea[linea_logica_actual].append("S")
        elif tt in _FSTRING_MIDDLE:
            continue          # el interior de una f-string ya está cubierto por S
        else:
            por_linea[linea_logica_actual].append(txt)

    salida: list[tuple[int, str]] = []
    for row in sorted(por_linea):
        firma = " ".join(por_linea[row])
        if not firma or firma == "S":      # línea vacía o docstring suelto
            continue
        salida.append((ancla.get(row, row), firma))
    return salida


_KEYWORDS = frozenset(
    "False None True and as assert async await break class continue def del elif "
    "else except finally for from global if import in is lambda nonlocal not or "
    "pass raise return try while with yield match case".split()
)
_FSTRING_MIDDLE = frozenset(
    t for t in (getattr(token_mod, n, None) for n in ("FSTRING_MIDDLE", "FSTRING_END"))
    if t is not None
)


def _windows(path: Path, rel: str) -> list[tuple[str, str, int]]:
    """[(huella, archivo_rel, línea_inicio)] para cada ventana de WINDOW líneas."""
    lineas = _normalized_lines(path)
    out: list[tuple[str, str, int]] = []
    for i in range(len(lineas) - WINDOW + 1):
        bloque = "\n".join(f for _r, f in lineas[i:i + WINDOW])
        huella = hashlib.sha1(bloque.encode("utf-8")).hexdigest()[:16]
        out.append((huella, rel, lineas[i][0]))
    return out


def _files() -> list[tuple[Path, str]]:
    encontrados: list[tuple[Path, str]] = []
    for pkg in PACKAGES:
        base = BACKEND_ROOT / pkg
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            encontrados.append((p, p.relative_to(BACKEND_ROOT).as_posix()))
    return encontrados


def measure() -> dict:
    """Mide duplicación cruzada (par a par) y propia (archivo consigo mismo)."""
    archivos = _files()
    por_huella: dict[str, list[tuple[str, int]]] = defaultdict(list)
    total_ventanas = 0
    for path, rel in archivos:
        for huella, _rel, row in _windows(path, rel):
            por_huella[huella].append((rel, row))
            total_ventanas += 1

    cruzado: dict[tuple[str, str], int] = defaultdict(int)
    propio: dict[str, int] = defaultdict(int)
    for huella, apariciones in por_huella.items():
        if len(apariciones) < 2:
            continue
        conteo_por_archivo: dict[str, int] = defaultdict(int)
        for rel, _row in apariciones:
            conteo_por_archivo[rel] += 1
        # Duplicación propia: apariciones repetidas dentro del MISMO archivo.
        for rel, n in conteo_por_archivo.items():
            if n > 1:
                propio[rel] += n - 1
        # Duplicación cruzada: la ventana existe en dos archivos distintos.
        rels = sorted(conteo_por_archivo)
        for i, a in enumerate(rels):
            for b in rels[i + 1:]:
                cruzado[(a, b)] += min(conteo_por_archivo[a], conteo_por_archivo[b])

    return {
        "window": WINDOW,
        "n_archivos": len(archivos),
        "n_ventanas": total_ventanas,
        "n_ventanas_unicas": len(por_huella),
        "cruzado": {f"{a} <-> {b}": n for (a, b), n in
                    sorted(cruzado.items(), key=lambda kv: -kv[1])},
        "propio": dict(sorted(propio.items(), key=lambda kv: -kv[1])),
    }


def fase7_pair_count(medido: dict) -> int:
    """Ventanas duplicadas gravimetría ↔ magnetometría (el número de la Fase 7)."""
    a, b = FASE7_PAIR
    return int(medido["cruzado"].get(f"{a} <-> {b}", medido["cruzado"].get(f"{b} <-> {a}", 0)))


def _render(medido: dict) -> str:
    L = [
        f"Duplicación estructural — ventanas de {medido['window']} líneas normalizadas",
        f"  archivos barridos : {medido['n_archivos']}",
        f"  ventanas totales  : {medido['n_ventanas']:,}  ({medido['n_ventanas_unicas']:,} únicas)",
        "",
        f"  FASE 7 · {FASE7_PAIR[0]} <-> {FASE7_PAIR[1]}: "
        f"{fase7_pair_count(medido)} (criterio: < {FASE7_MAX})",
        "",
        "  Peores pares cruzados:",
    ]
    for k, v in list(medido["cruzado"].items())[:10]:
        L.append(f"    {v:5d}  {k}")
    L.append("")
    L.append("  Peores archivos consigo mismos:")
    for k, v in list(medido["propio"].items())[:10]:
        L.append(f"    {v:5d}  {k}")
    return "\n".join(L)


def _compare(medido: dict, base: dict) -> list[str]:
    peor: list[str] = []
    n_now = fase7_pair_count(medido)
    n_base = int(base.get("fase7_pair", 10**9))
    if n_now > max(n_base, 0):
        peor.append(
            f"{FASE7_PAIR[0]} <-> {FASE7_PAIR[1]}: {n_now} ventanas duplicadas "
            f"(la base congelada son {n_base}). La Fase 7 extrajo ese núcleo: "
            f"volver a copiarlo entre los dos motores es exactamente lo que H-9 mide."
        )
    if n_now >= FASE7_MAX:
        peor.append(
            f"{FASE7_PAIR[0]} <-> {FASE7_PAIR[1]}: {n_now} ventanas ≥ el umbral "
            f"{FASE7_MAX} del criterio de aceptación (a) de la Fase 7."
        )
    for par, n_base_par in base.get("cruzado", {}).items():
        n_now_par = int(medido["cruzado"].get(par, 0))
        if n_now_par > int(n_base_par) + 20:
            peor.append(f"{par}: {n_now_par} ventanas (base {n_base_par}).")
    return peor


def to_baseline(medido: dict) -> dict:
    return {
        "window": medido["window"],
        "n_archivos": medido["n_archivos"],
        "n_ventanas": medido["n_ventanas"],
        "fase7_pair": fase7_pair_count(medido),
        # Sólo los pares gordos: congelar la cola larga produce ruido en cada commit.
        "cruzado": {k: v for k, v in medido["cruzado"].items() if v >= 20},
        "propio": {k: v for k, v in medido["propio"].items() if v >= 20},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="salida JSON completa")
    ap.add_argument("--update", action="store_true", help="(re)congela la línea base")
    ap.add_argument("--gate", action="store_true", help="exit 1 si la duplicación empeora")
    args = ap.parse_args()

    medido = measure()

    if args.update:
        BASELINE_PATH.write_text(
            json.dumps(to_baseline(medido), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Línea base escrita en {BASELINE_PATH}")
        print(_render(medido))
        return 0

    if args.json:
        print(json.dumps(medido, indent=2, ensure_ascii=False))
    else:
        print(_render(medido))

    if args.gate:
        if not BASELINE_PATH.is_file():
            print(f"FALTA la línea base {BASELINE_PATH} (corre --update)", file=sys.stderr)
            return 1
        peor = _compare(medido, json.loads(BASELINE_PATH.read_text(encoding="utf-8")))
        if peor:
            print("\nGATE DE DUPLICACIÓN EN ROJO:", file=sys.stderr)
            for p in peor:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("\nGate de duplicación: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
