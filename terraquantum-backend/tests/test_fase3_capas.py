"""Fase 3 — la dirección de las dependencias, impuesta por el build.

**Por qué existe este archivo.** La auditoría (§9I) midió que la dirección de
dependencias del backend es limpia, y añadió la advertencia correcta: *lo es por
disciplina*. El informe 14 insiste en que las reglas de visibilidad las imponga
la construcción y no la voluntad humana, porque la voluntad humana se cansa un
viernes por la tarde.

**Lo que ya se ganó y hay que no perder.** La Fase 6 sacó el dominio del `core/`
(borró el almacén de block models, el cliente de Earth Engine, las utilidades
geográficas y el almacenamiento). El resultado, MEDIDO hoy con AST sobre los
siete paquetes del backend:

    core         -> (no importa ningún otro paquete del proyecto)
    schemas      -> (idem)
    exploration  -> core
    middleware   -> core
    reporting    -> core, services
    services     -> core, exploration, schemas
    api          -> core, reporting, schemas, services

Cero violaciones. Este test congela ese grafo. No es aspiracional: describe lo
que hay, y falla el día en que alguien lo rompa.

**Los imports LAZY cuentan.** Recorre el AST completo, no sólo la cabecera del
archivo: en este repositorio muchos imports viven dentro de funciones (para
arranque rápido y para dependencias opcionales), y una arista escondida dentro
de un `def` es exactamente igual de real que una de la primera línea.
"""
from __future__ import annotations

import ast
import functools
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PROJECT_PACKAGES = (
    "api",
    "core",
    "exploration",
    "middleware",
    "reporting",
    "schemas",
    "services",
)

#: Qué puede importar cada paquete. Cambiar esta tabla es cambiar la
#: arquitectura: hágase a propósito, en un PR que lo explique.
ALLOWED_IMPORTS: dict[str, set[str]] = {
    "core": set(),           # infraestructura pura: no conoce a nadie
    "schemas": set(),        # contratos de datos: tampoco
    "exploration": {"core"}, # el motor de física no sabe que existe una API
    "middleware": {"core"},
    # `reporting -> services` es DELIBERADA: el generador de informes lee el
    # block model persistido a través del servicio. Queda escrita aquí para que
    # nadie la "arregle" a ciegas creyendo que es una fuga.
    "reporting": {"core", "services"},
    "services": {"core", "exploration", "schemas"},
    "api": {"core", "reporting", "schemas", "services"},
}

#: `scripts/` no es un paquete (no tiene `__init__.py`) pero contiene 65
#: utilidades de validación. Si el código de producción empezara a importarlas,
#: la frontera se movería sin que nadie lo decidiera. Hoy no ocurre; la regla
#: existe para que siga sin ocurrir.
FORBIDDEN_EVERYWHERE = {"scripts", "tests"}

#: El Core es infraestructura. Si aparece un módulo nuevo, decláralo aquí — ese
#: momento de fricción es el punto: obliga a preguntarse "¿esto es
#: infraestructura o es dominio?" antes de que sean 1.300 líneas (H-35).
CORE_MODULES = {
    "__init__",
    "auth",
    "config",
    "diagnostics_buffer",
    "errors",
    "license_service",
    "logging",
    "metrics",
    "observability",
    "rate_limit",
    "utils",
}

#: Si estas bibliotecas aparecen en `core/`, ha entrado dominio: son las
#: herramientas con las que se hace física, geometría y modelos de bloques.
#: MEDIDO: hoy `core/` no importa ninguna (sus terceros son cryptography,
#: fastapi/starlette, opentelemetry, prometheus_client, slowapi y structlog).
#:
#: HONESTIDAD SOBRE SU ALCANCE: esta regla sola **no habría cazado** los cuatro
#: módulos de dominio que la Fase 6 sacó del Core (`block_model_store`,
#: `gee_client`, `geo_utils`, `storage`): todos usaban sólo la biblioteca
#: estándar. Por eso la guarda principal es el allowlist de ficheros de abajo,
#: y ésta es la señal complementaria.
SCIENTIFIC_STACK = {
    "numpy",
    "scipy",
    "polars",
    "pandas",
    "pyproj",
    "zarr",
    "dask",
    "sklearn",
    "skimage",
    "pywt",
    "pyevtk",
}


@functools.lru_cache(maxsize=None)
def _imports_of_file(path: Path) -> list[tuple[str, int]]:
    """(módulo raíz importado, línea) — incluye imports dentro de funciones."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - lo caza el compile check
        raise AssertionError(f"{path} no parsea: {exc}") from exc

    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` / `from .otro import y`: dentro del propio
            # paquete, no cruza ninguna frontera.
            if node.level:
                continue
            if node.module:
                found.append((node.module.split(".")[0], node.lineno))
    return found


@functools.lru_cache(maxsize=1)
def _source_files() -> tuple[tuple[str, Path], ...]:
    """(paquete, ruta) de todos los .py del backend. Se recorre el disco UNA vez."""
    return tuple(
        (package, path)
        for package in PROJECT_PACKAGES
        for path in sorted((BACKEND_ROOT / package).rglob("*.py"))
        if "__pycache__" not in path.parts
    )


@functools.lru_cache(maxsize=1)
def _package_graph() -> dict[str, dict[str, list[str]]]:
    graph: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for package, path in _source_files():
        for module, lineno in _imports_of_file(path):
            if module in PROJECT_PACKAGES and module != package:
                rel = path.relative_to(BACKEND_ROOT).as_posix()
                graph[package][module].append(f"{rel}:{lineno}")
    return graph


# ── Las reglas ────────────────────────────────────────────────────────────────

def test_dependency_direction_is_enforced():
    graph = _package_graph()
    violations: list[str] = []

    for package in PROJECT_PACKAGES:
        allowed = ALLOWED_IMPORTS[package]
        for target, sites in sorted(graph.get(package, {}).items()):
            if target not in allowed:
                muestra = ", ".join(sites[:4])
                extra = f" (+{len(sites) - 4} más)" if len(sites) > 4 else ""
                violations.append(
                    f"{package} -> {target}: {len(sites)} import(s) en {muestra}{extra}"
                )

    assert not violations, (
        "La dirección de dependencias se rompió:\n  "
        + "\n  ".join(violations)
        + "\n\nSi el cambio es deliberado, actualiza ALLOWED_IMPORTS y explica "
        "por qué en el PR. Si no lo es, la arista sobra."
    )


def test_core_depends_on_nothing_of_the_project():
    """La afirmación más fuerte y hoy cierta: el Core no conoce a nadie."""
    graph = _package_graph()
    assert not graph.get("core"), (
        "core/ empezó a importar otros paquetes del proyecto: "
        f"{dict(graph.get('core', {}))}"
    )


def test_no_domain_leaked_into_core():
    """El Core es infraestructura: sin stack científico dentro (H-35)."""
    offenders: list[str] = []
    for path in sorted((BACKEND_ROOT / "core").rglob("*.py")):
        for module, lineno in _imports_of_file(path):
            if module in SCIENTIFIC_STACK:
                rel = path.relative_to(BACKEND_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno} importa {module}")

    assert not offenders, (
        "Entró dominio en el Core (stack científico):\n  "
        + "\n  ".join(offenders)
        + "\n\nEso pertenece a exploration/ o services/, no a core/."
    )


def test_core_modules_are_declared():
    """Un módulo nuevo en el Core es una decisión, no un descubrimiento."""
    on_disk = {p.stem for p in (BACKEND_ROOT / "core").glob("*.py")}
    added = sorted(on_disk - CORE_MODULES)
    removed = sorted(CORE_MODULES - on_disk)
    assert not added, (
        f"Módulos nuevos en core/ sin declarar: {added}. Antes de añadirlos a "
        "CORE_MODULES, comprueba que son infraestructura y no dominio."
    )
    assert not removed, (
        f"Módulos declarados que ya no existen en core/: {removed}."
    )


def test_production_code_never_imports_scripts_or_tests():
    """Las utilidades de validación no son una capa: son herramientas."""
    offenders: list[str] = []
    for _package, path in _source_files():
        for module, lineno in _imports_of_file(path):
            if module in FORBIDDEN_EVERYWHERE:
                rel = path.relative_to(BACKEND_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno} importa '{module}'")
    assert not offenders, (
        "Código de producción importando utilidades de desarrollo:\n  "
        + "\n  ".join(offenders)
    )


def test_core_size_budget():
    """Alarma de engorde del Core, no juicio de contenido.

    Umbrales elegidos con margen sobre lo MEDIDO hoy (1.774 LOC en total,
    `errors.py` como techo con 763), no derivados de ninguna teoría. Si algún
    día estorban, ésta es la regla prescindible de las tres: las otras dos
    dicen *qué* hay en el Core; ésta sólo dice *cuánto*.
    """
    sizes = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in (BACKEND_ROOT / "core").glob("*.py")
    }
    total = sum(sizes.values())
    biggest = max(sizes.items(), key=lambda kv: kv[1])

    assert total <= 2000, (
        f"core/ creció a {total} LOC (medido en la Fase 3: 1.774). "
        "¿Entró dominio, o es infraestructura que merece su propio módulo?"
    )
    assert biggest[1] <= 850, (
        f"core/{biggest[0]} tiene {biggest[1]} LOC (techo medido: errors.py, 763)."
    )


def test_the_rule_table_covers_every_package():
    """Un paquete nuevo sin regla sería un agujero silencioso en la guarda."""
    sin_regla = sorted(set(PROJECT_PACKAGES) - set(ALLOWED_IMPORTS))
    assert not sin_regla, f"paquetes sin regla de visibilidad: {sin_regla}"
    for package in PROJECT_PACKAGES:
        assert (BACKEND_ROOT / package / "__init__.py").is_file(), (
            f"{package} dejó de ser un paquete; actualiza PROJECT_PACKAGES"
        )


def test_the_guard_can_actually_fail(tmp_path):
    """Una guarda que no puede fallar es decorativa: se comprueba el detector."""
    fake = tmp_path / "mod.py"
    fake.write_text(
        "import os\n"
        "def f():\n"
        "    from services import algo  # import lazy, cuenta igual\n"
        "    return algo\n",
        encoding="utf-8",
    )
    modules = [m for m, _ in _imports_of_file(fake)]
    assert "services" in modules, (
        "El detector no ve los imports dentro de funciones — sería ciego "
        "justo donde este repositorio los pone."
    )
    assert "os" in modules
