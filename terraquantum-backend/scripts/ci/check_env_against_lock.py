"""Fase 27 (NUEVO-4) — ¿este intérprete puede construir el instalador?

QUÉ IMPIDE
==========
Que `build_desktop.ps1` empaquete con un entorno al que le FALTA algo. Ése es
el defecto NUEVO-4: el `.spec` recolectaba `[]` en silencio y el instalador
salía sin OMF —o sin los datos de pyproj— sin que nada lo dijera. El `.spec` ya
aborta por su cuenta; esto lo dice ANTES de empezar, con la lista completa en
vez de con el primer paquete que falle.

QUÉ **NO** HACE, Y POR QUÉ
==========================
No instala nada. Comprueba y reporta.

Y no trata igual «falta» que «versión distinta», porque no son el mismo daño y
mezclarlos habría hecho el gate inservible desde el primer día:

* **FALTA** ⇒ fatal. Es NUEVO-4 literal: el ejecutable saldría incompleto.
* **DERIVA de un paquete pineado `==` en `requirements.txt`** ⇒ fatal. Ese `==`
  está puesto por una razón escrita (determinismo del solver, o cadena de
  suministro de un binario que se firma). Si se incumple, el binario no es el
  que dice ser.
* **DERIVA de un paquete con RANGO** ⇒ aviso, no bloqueo. El rango es
  deliberado (`requirements.txt` lo explica paquete por paquete) y la CI lleva
  desde siempre resolviendo dentro de él. Bloquear aquí no protegería nada y
  convertiría el gate en algo que se desactiva a la semana.

MEDIDO el 2026-09-03 en esta máquina: 0 faltantes, 0 derivas de pineados
exactos, **37 de 105** derivas dentro de rango o en transitivas (entre ellas
`zarr 3.2.1` frente a `3.3.0` y `protobuf 5.29.6` frente a `6.33.6`). Es la
cuantificación de un riesgo que la auditoría ya había declarado sin número
(docs/06, «riesgo residual medido»).

USO
===
    py -3.14 scripts/ci/check_env_against_lock.py           # exit 1 si es fatal
    py -3.14 scripts/ci/check_env_against_lock.py --quiet   # sólo lo que falla
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCKFILE = BACKEND_ROOT / "requirements.lock"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"

_LOCK_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\S+?)\s*\\?\s*$")
_REQ_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(\[[^\]]+\])?\s*==\s*([^\s;#]+)")


def _canon(name: str) -> str:
    return name.lower().replace("_", "-")


def read_lock(path: Path = LOCKFILE) -> dict[str, str]:
    """{paquete canónico: versión} de requirements.lock."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith((" ", "\t", "#")) or not raw.strip():
            continue
        match = _LOCK_PIN.match(raw.strip())
        if match:
            pins[_canon(match.group(1))] = match.group(2)
    return pins


def read_exact_pins(path: Path = REQUIREMENTS) -> dict[str, str]:
    """Requisitos DIRECTOS pineados con `==` en requirements.txt."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQ_PIN.match(line)
        if match:
            pins[_canon(match.group(1))] = match.group(3)
    return pins


def audit(lock: dict[str, str], exact: dict[str, str]):
    missing, fatal_drift, soft_drift = [], [], []
    for name in sorted(lock):
        want = lock[name]
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        if have != want:
            (fatal_drift if name in exact else soft_drift).append((name, want, have))
    return missing, fatal_drift, soft_drift


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara el entorno con requirements.lock.")
    parser.add_argument("--quiet", action="store_true", help="Callar si todo va bien.")
    # `--lock`/`--requirements` existen para que el GATE pueda ejercitar la
    # decisión de salida contra un lock preparado. Sin ellos, en esta máquina no
    # falta nada y el camino `return 1` no se ejecutaba nunca: una mutación que
    # volvía no-fatal la ausencia de una dependencia se ESCAPÓ del gate.
    parser.add_argument("--lock", type=Path, default=LOCKFILE)
    parser.add_argument("--requirements", type=Path, default=REQUIREMENTS)
    args = parser.parse_args()

    if not args.lock.exists():
        print(f"FALTA {args.lock}. Genéralo:\n"
              "    py -3.14 scripts/ci/gen_lockfile.py", file=sys.stderr)
        return 1

    lock = read_lock(args.lock)
    exact = read_exact_pins(args.requirements)
    missing, fatal_drift, soft_drift = audit(lock, exact)

    if not args.quiet:
        print(f"  intérprete : {sys.executable}")
        print(f"  python     : {sys.version.split()[0]}")
        print(f"  lock       : {len(lock)} paquetes")

    if soft_drift and not args.quiet:
        print(f"  AVISO: {len(soft_drift)} de {len(lock)} paquetes con version distinta "
              f"de la del lock (rango deliberado o transitiva). El instalador que "
              f"salga de aqui NO sera identico al que salga del lock:")
        for name, want, have in soft_drift:
            print(f"      {name:<32} lock={want:<16} instalado={have}")

    if missing:
        print("\n==================================================================",
              file=sys.stderr)
        print(" BUILD ABORTADO — faltan dependencias en este interprete", file=sys.stderr)
        print("==================================================================",
              file=sys.stderr)
        for name in missing:
            print(f"   FALTA  {name}=={lock[name]}", file=sys.stderr)
        print("\n  Esto es NUEVO-4: sin esto, el `.spec` recolectaba [] y el\n"
              "  instalador salia incompleto SIN avisar. Instala el cierre:\n\n"
              "      py -3.14 -m pip install --require-hashes -r requirements.lock\n",
              file=sys.stderr)

    if fatal_drift:
        print("\n==================================================================",
              file=sys.stderr)
        print(" BUILD ABORTADO — un paquete pineado EXACTO no coincide", file=sys.stderr)
        print("==================================================================",
              file=sys.stderr)
        for name, want, have in fatal_drift:
            print(f"   {name:<32} requirements.txt=={want:<16} instalado={have}",
                  file=sys.stderr)
        print("\n  Esos `==` estan puestos por determinismo numerico o por cadena de\n"
              "  suministro del binario firmado. Incumplirlos hace que el ejecutable\n"
              "  no sea el que dice ser.\n", file=sys.stderr)

    if missing or fatal_drift:
        return 1
    if not args.quiet:
        print("  entorno apto para construir el instalador.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
