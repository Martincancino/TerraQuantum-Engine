"""Fase 3 (cierre) — la CI instala EXACTAMENTE lo que el código importa.

QUÉ IMPIDE
==========
Que el backend importe un paquete que `pip install -r requirements.txt` no
instalaría. En esa situación todo pasa en la máquina de desarrollo (donde el
paquete está, de rebote de una dependencia vieja) y todo se rompe en el runner
— o peor: no se rompe, porque el import va dentro de un `try/except` y lo único
que muere en silencio es una red de seguridad.

Es el mismo pecado que la Fase 3 ya diagnosticó con el intérprete («la CI
validaba un árbol de dependencias que no llega al cliente», zarr 2.x contra
zarr 3.x). Aquel arreglo fijó la VERSIÓN DE PYTHON; este fija el CONJUNTO DE
PAQUETES, que es la otra mitad del mismo problema.

CASO REAL QUE LO MOTIVA (medido 2026-08-13, ver docs/06 §FASE 3)
================================================================
`psutil` desapareció del árbol de dependencias cuando la Fase 6 eliminó
`distributed` — que era quien la arrastraba. Nadie lo notó porque seguía
instalada en la máquina de Martín. En un runner limpio: 6 tests en rojo, y la
red de seguridad de memoria del kernel (`SOLVER_KERNEL_TOO_DENSE`) callada.

CÓMO DECIDE
===========
 1. Cierre transitivo de `requirements.txt` a partir de los metadatos instalados.
 2. Módulos de primer nivel que ese cierre puede satisfacer.
 3. Todos los `import` de nivel superior del código que la CI EJECUTA (AST, sin
    ejecutar nada).
 4. Un import que no sea stdlib, ni del propio repo, ni satisfecho por el cierre,
    tiene que estar declarado en OPCIONALES con su motivo. Si no lo está → exit 1.

Los OPCIONALES no son una lista de perdón: son la declaración explícita de «esto
se importa bajo guarda y el producto funciona sin ello», que es justo lo que el
inventario de gates (H-22) hace con `scripts/validation/`. Uno nuevo sin declarar
rompe el gate a propósito.

LÍMITE DECLARADO
================
El paso 1 lee los metadatos INSTALADOS. En un runner —donde lo instalado es, por
construcción, el cierre— este gate no puede fallar: su valor está en la máquina
de desarrollo, donde detecta la divergencia ANTES del push. Por eso corre también
en `check.ps1`, no sólo en `ci.yml`.
"""
from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Paquetes cuyo código ejecuta la CI (job `backend` + nocturno).
# `scripts/diagnostics/` queda fuera A PROPÓSITO: no lo ejecuta ningún job ni lo
# recoge pytest (`testpaths = tests scripts/validation`), y ahí vive matplotlib,
# que es legítimo no empaquetar.
PAQUETES_QUE_CORREN = (
    "api", "core", "exploration", "middleware", "reporting", "schemas",
    "services", "tests", "scripts/ci", "scripts/validation",
)

# Imports que NO están en requirements.txt y NO deben estarlo, con su motivo.
# Todos tienen que ir bajo guarda (`try/import` o `is_available()`), de modo que
# el backend arranque y sus tests pasen sin ellos.
# El nombre del módulo que se importa NO siempre es el de la distribución que se
# instala. Mientras la distribución esté instalada aquí, `packages_distributions()`
# resuelve el par sola; pero si NO lo está (caso real: PyWavelets está declarada en
# requirements.txt y no instalada en esta máquina), no hay metadatos que leer y el
# gate acusaría en falso. Esta tabla hace explícito el puente para que el veredicto
# no dependa de qué haya instalado quien lo corre.
ALIAS_MODULO_DIST: dict[str, str] = {
    "pywt": "pywavelets",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "ee": "earthengine-api",
    "multipart": "python-multipart",
    "dateutil": "python-dateutil",
    "yaml": "pyyaml",
}

# Imports que NO están en requirements.txt y NO deben estarlo, con su motivo.
OPCIONALES: dict[str, str] = {
    "pyopenvdb": "export .vdb gateado tras `import pyopenvdb` (services/volumetric_service.py); sin la binding retorna None, non-fatal",
    "simpeg": "sólo scripts de comparación externa contra SimPEG; no es camino de producción",
    "SimPEG": "idem `simpeg` (el paquete cambió de capitalización entre versiones)",
    "discretize": "malla de SimPEG, sólo en comparaciones externas",
}


def _norm(nombre: str) -> str:
    return re.sub(r"[-_.]+", "-", nombre).lower()


def requisitos_declarados(ruta: Path) -> list[str]:
    fuera = []
    for cruda in ruta.read_text(encoding="utf-8").splitlines():
        linea = cruda.split("#")[0].strip()
        if not linea:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)", linea)
        if m:
            fuera.append(_norm(m.group(1)))
    return fuera


def cierre_transitivo(raices: list[str]) -> tuple[set[str], set[str]]:
    """(distribuciones alcanzables, distribuciones sin metadatos locales)."""
    visto: set[str] = set()
    sin_meta: set[str] = set()
    pila = list(raices)
    while pila:
        dist = pila.pop()
        if dist in visto:
            continue
        visto.add(dist)
        try:
            requiere = metadata.requires(dist) or []
        except metadata.PackageNotFoundError:
            sin_meta.add(dist)
            continue
        for req in requiere:
            # "foo (>=1) ; extra == 'test'" → los extras NO se instalan salvo que
            # requirements.txt los pida explícitamente (p. ej. `dask[array]`).
            if ";" in req and "extra" in req.split(";", 1)[1]:
                continue
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", req)
            if m:
                pila.append(_norm(m.group(1)))
    return visto, sin_meta


def modulos_del_cierre(cierre: set[str]) -> set[str]:
    modulos: set[str] = set()
    for modulo, dists in metadata.packages_distributions().items():
        if {_norm(d) for d in dists} & cierre:
            modulos.add(modulo)
    return modulos


def modulos_propios(raiz: Path) -> set[str]:
    """Módulos que el repo resuelve por sí mismo (paquetes, y .py sueltos que se
    importan por nombre desde `tests/` o `scripts/validation/`)."""
    propios: set[str] = set()
    for hijo in raiz.iterdir():
        if hijo.is_dir() and not hijo.name.startswith((".", "__")):
            propios.add(hijo.name)
        elif hijo.suffix == ".py":
            propios.add(hijo.stem)
    for sub in ("tests", "scripts", "scripts/validation", "scripts/ci", "scripts/diagnostics"):
        d = raiz / sub
        if d.is_dir():
            for hijo in d.iterdir():
                if hijo.suffix == ".py":
                    propios.add(hijo.stem)
                elif hijo.is_dir() and (hijo / "__init__.py").exists():
                    propios.add(hijo.name)
    return propios


def imports_de_nivel_superior(raiz: Path) -> dict[str, set[str]]:
    encontrados: dict[str, set[str]] = {}
    for paquete in PAQUETES_QUE_CORREN:
        base = raiz / paquete
        if not base.exists():
            continue
        for archivo in base.rglob("*.py"):
            if "__pycache__" in archivo.parts:
                continue
            try:
                arbol = ast.parse(archivo.read_text(encoding="utf-8", errors="replace"),
                                  filename=str(archivo))
            except SyntaxError:
                continue  # `compile_check.py` es quien juzga la sintaxis
            rel = str(archivo.relative_to(raiz)).replace("\\", "/")
            for nodo in ast.walk(arbol):
                nombres: list[str] = []
                if isinstance(nodo, ast.Import):
                    nombres = [a.name.split(".")[0] for a in nodo.names]
                elif isinstance(nodo, ast.ImportFrom) and not nodo.level and nodo.module:
                    nombres = [nodo.module.split(".")[0]]
                for n in nombres:
                    encontrados.setdefault(n, set()).add(rel)
    return encontrados


def main() -> int:
    req = BACKEND_ROOT / "requirements.txt"
    if not req.is_file():
        print(f"deps closure ERROR - no existe {req}")
        return 1

    cierre, sin_meta = cierre_transitivo(requisitos_declarados(req))
    disponibles = modulos_del_cierre(cierre)
    propios = modulos_propios(BACKEND_ROOT)
    stdlib = set(sys.stdlib_module_names)

    infractores: dict[str, set[str]] = {}
    for modulo, archivos in imports_de_nivel_superior(BACKEND_ROOT).items():
        if (modulo in stdlib or modulo in propios or modulo in disponibles
                or modulo in OPCIONALES or modulo.startswith("_")):
            continue
        if _norm(ALIAS_MODULO_DIST.get(modulo, "")) in cierre:
            continue
        infractores[modulo] = archivos

    if not infractores:
        print(f"deps closure OK - {len(cierre)} distribuciones declaradas cubren "
              f"todos los imports de {len(PAQUETES_QUE_CORREN)} paquetes "
              f"({len(OPCIONALES)} opcionales declarados)")
        return 0

    print("deps closure FALLO - el codigo importa lo que la CI no instalaria:\n")
    for modulo, archivos in sorted(infractores.items()):
        instalada = ""
        try:
            dists = metadata.packages_distributions().get(modulo, [])
            if dists:
                instalada = (f"  [instalada AQUI como {', '.join(dists)} -> por eso "
                             f"no lo ves fallar en local]")
        except Exception:  # noqa: BLE001
            pass
        print(f"  {modulo}{instalada}")
        for archivo in sorted(archivos)[:6]:
            print(f"      {archivo}")
        if len(archivos) > 6:
            print(f"      ... y {len(archivos) - 6} archivo(s) mas")
    print("\nArreglo: declararlo en requirements.txt (con techo de major, H-23), o")
    print("anadirlo a OPCIONALES de este script con su motivo si va bajo guarda.")
    if sin_meta:
        print(f"\n(aviso: sin metadatos locales, no expandidas: {', '.join(sorted(sin_meta))})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
