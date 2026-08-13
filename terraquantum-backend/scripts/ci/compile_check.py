"""Fase 3 (H-5) — comprobación de sintaxis que falla cuando el árbol se mueve.

**El problema medido.** La CI ejecutaba:

    python -m compileall api services exploration schemas Camiones core middleware workers

`Camiones` nunca existió y `workers/` se borró en la F3 del plan de producto.
`compileall` imprime `Can't list 'Camiones'`, `Can't list 'workers'` y **devuelve
0**. Comprobado en esta máquina: la CI llevaba meses declarando que compilaba
ocho paquetes y compilando seis, en verde. Y `check.ps1` mantenía a mano OTRA
lista, distinta y también incompleta (sin `middleware` ni `reporting`).

**El arreglo no es corregir la lista: es dejar de mantenerla a mano dos veces.**
Este script descubre los paquetes reales del backend (directorios con
`__init__.py`, excluyendo los de test) y los contrasta con la lista declarada:

* un paquete declarado que **desaparece** → error (era lo que pasaba, en verde);
* un paquete nuevo que **aparece** sin declararse → error (añadir un paquete al
  backend debe ser un acto consciente, no un descubrimiento a posteriori).

Sólo entonces compila. Así la deriva futura falla ruidosamente, que es el
principio que el producto ya aplica a los datos y no aplicaba a su propia CI.

Uso:
    python scripts/ci/compile_check.py          # desde terraquantum-backend/
    python scripts/ci/compile_check.py --list   # imprime los paquetes y sale 0
"""
from __future__ import annotations

import compileall
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: Los paquetes de código fuente del backend. Cambiar esta lista es parte de
#: cualquier PR que añada o elimine un paquete — ese es exactamente el punto.
DECLARED_PACKAGES: tuple[str, ...] = (
    "api",
    "core",
    "exploration",
    "middleware",
    "reporting",
    "schemas",
    "services",
)

#: Paquetes que existen pero NO son código de producción: no se declaran ni se
#: exigen, aunque sí se compilan si están presentes (un error de sintaxis en un
#: test también rompe la suite, y es mejor verlo aquí que a los 20 minutos).
NON_SOURCE_PACKAGES: tuple[str, ...] = ("tests",)


def discover_packages(root: Path) -> set[str]:
    """Directorios de primer nivel que son paquetes Python de verdad."""
    return {
        entry.name
        for entry in root.iterdir()
        if entry.is_dir()
        and (entry / "__init__.py").is_file()
        and not entry.name.startswith((".", "_"))
    }


def diff_packages(declared: set[str], discovered: set[str]) -> tuple[list[str], list[str]]:
    """(faltantes, no declarados). Función pura: es la que se testea."""
    return sorted(declared - discovered), sorted(discovered - declared)


def main() -> int:
    declared = set(DECLARED_PACKAGES)
    discovered = discover_packages(BACKEND_ROOT) - set(NON_SOURCE_PACKAGES)

    if "--list" in sys.argv:
        for name in sorted(discovered):
            print(name)
        return 0

    missing, unexpected = diff_packages(declared, discovered)

    if missing:
        print(
            "ERROR: paquetes declarados que NO existen: " + ", ".join(missing),
            file=sys.stderr,
        )
        print(
            "       Alguien los borró y la comprobación de sintaxis seguía en verde.\n"
            "       Actualiza DECLARED_PACKAGES en este archivo si la eliminación es correcta.",
            file=sys.stderr,
        )
    if unexpected:
        print(
            "ERROR: paquetes nuevos sin declarar: " + ", ".join(unexpected),
            file=sys.stderr,
        )
        print(
            "       Añadir un paquete al backend es una decisión de arquitectura:\n"
            "       decláralo en DECLARED_PACKAGES para que la CI lo compile a propósito.",
            file=sys.stderr,
        )
    if missing or unexpected:
        return 1

    targets = sorted(declared) + [
        name for name in NON_SOURCE_PACKAGES if (BACKEND_ROOT / name).is_dir()
    ]
    ok = True
    for name in targets:
        # quiet=1 imprime sólo los errores; force=True evita que un .pyc viejo
        # oculte un archivo que ya no compila.
        if not compileall.compile_dir(
            str(BACKEND_ROOT / name), quiet=1, force=True, legacy=False
        ):
            ok = False

    if not ok:
        print("ERROR: hay errores de sintaxis (arriba).", file=sys.stderr)
        return 1

    # Salida ASCII a proposito: la consola de Windows no usa UTF-8 por defecto
    # y un guion largo llega como basura al log de quien lo lee.
    print(f"compile OK - {len(targets)} paquetes: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
