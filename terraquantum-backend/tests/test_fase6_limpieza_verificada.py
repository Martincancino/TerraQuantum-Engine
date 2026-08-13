"""Fase 6 — Limpieza verificada: la red que impide que lo borrado vuelva.

La Fase 6 del plan (`docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §10) borró código muerto
con evidencia. Un borrado sin guardia se deshace solo: alguien reintroduce el flag,
o vuelve a meter dominio en el Core, y nadie se entera hasta la siguiente auditoría.

Este archivo convierte cada borrado en un INVARIANTE EJECUTABLE. Sigue el patrón que
dejó la Fase 1 (`test_fase1_literal_dispatch.py`): no basta con que el código muerto
no esté — hay que fallar ruidosamente el día que reaparezca.

Cubre H-2, H-12, H-13, H-14 y H-35.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# Paquetes de código de producción que se escanean para contar referencias.
PROD_DIRS = ("api", "core", "exploration", "middleware", "reporting", "schemas", "services")
ALL_DIRS = PROD_DIRS + ("tests", "scripts")


def _py_files(dirs) -> list[Path]:
    out: list[Path] = [BACKEND / "main.py"]
    for d in dirs:
        out.extend(p for p in (BACKEND / d).rglob("*.py") if "__pycache__" not in p.parts)
    return out


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


# --------------------------------------------------------------------------- #
# H-2 — el path USE_SPARSE_DIRECT llamaba a una función inexistente            #
# --------------------------------------------------------------------------- #

def test_h2_el_simbolo_fantasma_no_reaparece():
    """`solve_sparse_normal_equations` se invocaba y no existía: NameError en mitad
    de la inversión, después de construir el kernel (lo más caro del pipeline)."""
    # Sólo cuenta el CÓDIGO: los comentarios que explican por qué se borró el bloque
    # nombran el símbolo a propósito, y esa memoria es justamente lo que queremos
    # conservar para que nadie lo reintroduzca por ignorancia.
    culpables = [
        f"{p.relative_to(BACKEND)}:{i}"
        for p in _py_files(ALL_DIRS)
        if p.name != Path(__file__).name
        for i, line in enumerate(_read(p).splitlines(), 1)
        if "solve_sparse_normal_equations" in line and not line.strip().startswith("#")
    ]
    assert not culpables, (
        "Volvió a aparecer `solve_sparse_normal_equations`, el símbolo que no existe "
        f"en el repositorio: {culpables}. Si de verdad hace falta un solver directo, "
        "debe DEFINIRSE antes de invocarse — y no sobre las ecuaciones normales, que "
        "elevan cond(A) al cuadrado."
    )


@pytest.mark.parametrize(
    "flag",
    ["USE_SPARSE_DIRECT", "USE_WAVELET_COMPRESSION", "WAVELET_THRESHOLD_N_ACTIVE"],
)
def test_h2_h13_las_perillas_que_no_despachaban_siguen_borradas(flag):
    """Tres flags que prometían un comportamiento y no despachaban a ninguna parte.

    Es el mismo pecado que la Fase 1 cerró con el modo `amplitude`: una opción que el
    usuario puede activar y que no hace lo que dice.
    """
    from core import config

    assert not hasattr(config, flag), (
        f"`{flag}` volvió a core/config.py. Antes de reintroducirla, exige que ALGÚN "
        "código de producción la lea y que un test ejercite ese camino — si no, es "
        "una promesa rota con forma de variable de entorno."
    )


# --------------------------------------------------------------------------- #
# H-12 — core/storage.py: abstracción de una nube que el producto rechazó       #
# --------------------------------------------------------------------------- #

def test_h12_la_abstraccion_de_cloud_storage_sigue_borrada():
    assert not (BACKEND / "core" / "storage.py").exists(), (
        "core/storage.py volvió. Era una jerarquía de 3 backends (local/S3/GCS, los "
        "dos últimos NotImplementedError) con CERO importadores, para una nube que "
        "docs/02_PRODUCTO.md §6 rechaza explícitamente."
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("core.storage")


# --------------------------------------------------------------------------- #
# H-13 — símbolos públicos sin un solo consumidor                              #
# --------------------------------------------------------------------------- #

SIMBOLOS_BORRADOS = [
    ("exploration.solver_preconditioned", "solve_inversion_lsmr_wavelet"),
    ("exploration.preprocessing", "remove_regional_scale"),
    ("exploration.geophysics_math", "build_gradient_operators_from_mesh"),
    ("services.export_service", "export_core_to_gslib"),
    ("services.export_service", "export_block_model_to_gslib"),
    ("core.logging", "configure_logging"),
    ("services.block_model_store", "resolve_mine_design_block_model_reference"),
]


@pytest.mark.parametrize("modulo,simbolo", SIMBOLOS_BORRADOS)
def test_h13_los_simbolos_huerfanos_siguen_borrados(modulo, simbolo):
    mod = importlib.import_module(modulo)
    assert not hasattr(mod, simbolo), (
        f"`{modulo}.{simbolo}` reapareció. En la Fase 6 se borró por tener CERO "
        "referencias en todo el repositorio. Si vuelve, que vuelva CON su llamador y "
        "su test en el mismo commit."
    )


SUPERVIVIENTES = [
    # Lo que NO se borró, y que un borrado descuidado se llevaría por delante.
    ("exploration.geophysics_math", "build_gradient_operators"),   # joint_inversion lo usa
    ("exploration.preprocessing", "remove_regional_trend"),        # producción vía gravity_preprocessing_service
    ("exploration.jacobian_wavelet", "build_compressed_kernel"),   # tiene tests (test_fase10_solver)
    ("core.logging", "get_logger"),
    ("core.utils", "clean_trace_id"),
]


@pytest.mark.parametrize("modulo,simbolo", SUPERVIVIENTES)
def test_h13_lo_vivo_sigue_vivo(modulo, simbolo):
    """Contraprueba: la poda no se llevó por delante nada con consumidores reales."""
    mod = importlib.import_module(modulo)
    assert hasattr(mod, simbolo), f"`{modulo}.{simbolo}` desapareció y SÍ tiene consumidores."


def test_h13_el_gslib_que_el_producto_entrega_sigue_en_pie():
    """Se borró el par muerto de exportadores GSLIB, no la funcionalidad.

    El .gslib que viaja en el bundle ZIP industrial lo genera `_gslib_text`, que es
    otro camino. README_BACKEND y la UI siguen diciendo la verdad.
    """
    from services import export_service

    assert hasattr(export_service, "_gslib_text")
    texto = export_service._gslib_text([1.0, 2.0, 3.0, 4.0], nx=2, ny=2, nz=1, bs=10.0)
    assert "GSLIB" in texto or texto.strip(), "El exportador GSLIB vivo dejó de producir texto."


# --------------------------------------------------------------------------- #
# H-14 — dependencias declaradas y no importadas                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("dep", ["shapely", "distributed"])
def test_h14_las_dependencias_muertas_no_vuelven_a_requirements(dep):
    req = _read(BACKEND / "requirements.txt")
    declaradas = [
        ln.strip() for ln in req.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert not any(re.match(rf"^{dep}\b", ln, re.I) for ln in declaradas), (
        f"`{dep}` volvió a requirements.txt. Se quitó por tener 0 imports en todo el "
        "backend. Si un módulo nuevo la necesita de verdad, este test debe caer junto "
        "con el import que la justifica."
    )


@pytest.mark.parametrize("dep", ["shapely", "distributed"])
def test_h14_y_tampoco_vuelven_como_import(dep):
    patron = re.compile(rf"^\s*(?:import\s+{dep}\b|from\s+{dep}[.\s])", re.M)
    culpables = [
        str(p.relative_to(BACKEND)) for p in _py_files(PROD_DIRS) if patron.search(_read(p))
    ]
    assert not culpables, f"Alguien importó `{dep}` en producción sin declararlo: {culpables}"


# --------------------------------------------------------------------------- #
# H-35 — el Core debe ser infraestructura, y microscópico                      #
# --------------------------------------------------------------------------- #

# Whitelist explícita: el Core es el estrato que debe permanecer estable durante años.
# Añadir un módulo aquí es una DECISIÓN de arquitectura, no un descuido.
CORE_PERMITIDO = {
    "__init__.py",
    "auth.py",              # infraestructura de acceso
    "config.py",            # configuración
    "diagnostics_buffer.py",
    "errors.py",            # catálogo de errores
    "license_service.py",   # infraestructura de producto
    "logging.py",
    "metrics.py",
    "observability.py",
    "rate_limit.py",
    "utils.py",
}


def test_h35_el_core_no_acumula_dominio():
    presentes = {p.name for p in (BACKEND / "core").glob("*.py")}
    intrusos = presentes - CORE_PERMITIDO
    assert not intrusos, (
        f"Módulos nuevos en core/ sin declarar: {sorted(intrusos)}. El Core es "
        "infraestructura: si lo que añadiste sabe de modelos de bloques, geología, "
        "sondajes o formatos mineros, su sitio es services/. Si de verdad es "
        "infraestructura, añádelo a CORE_PERMITIDO y explica por qué."
    )
    faltantes = CORE_PERMITIDO - presentes - {"__init__.py"}
    assert not faltantes, f"Módulos del Core que desaparecieron sin actualizar la lista: {sorted(faltantes)}"


def test_h35_el_dominio_movido_vive_en_services():
    for nombre in ("block_model_store", "geo_utils", "gee_client"):
        assert (BACKEND / "services" / f"{nombre}.py").exists(), f"services/{nombre}.py no está"
        assert not (BACKEND / "core" / f"{nombre}.py").exists(), f"{nombre} volvió a core/"
        importlib.import_module(f"services.{nombre}")


def test_h35_el_core_no_importa_hacia_arriba():
    """El Core no puede depender de services/, api/, exploration/ ni reporting/.

    Hoy esto se cumple; antes de la Fase 6 NO: `core/utils.py` importaba
    `clean_trace_id` desde el almacén de modelos de bloques. Mover el almacén sin
    resolver eso habría creado la arista core/ → services/.

    Es también el anticipo del test de capas que pide la Fase 3 (§9I.6).
    """
    prohibidos = ("services", "api", "exploration", "reporting", "middleware", "schemas")
    violaciones: list[str] = []

    for p in (BACKEND / "core").glob("*.py"):
        tree = ast.parse(_read(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in prohibidos:
                        violaciones.append(f"{p.name}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.split(".")[0] in prohibidos:
                    violaciones.append(f"{p.name}:{node.lineno} from {node.module}")

    assert not violaciones, (
        "El Core importa hacia arriba, que es exactamente lo que lo vuelve inestable: "
        f"{violaciones}. Si el Core necesita algo de una capa superior, es que ese algo "
        "es infraestructura y debe bajar al Core — no que el Core deba subir."
    )


# --------------------------------------------------------------------------- #
# Guardia general: perillas de configuración que no lee nadie                  #
# --------------------------------------------------------------------------- #

def test_ninguna_constante_de_config_queda_sin_lector():
    """Una constante que nadie lee es una promesa que nadie cumple.

    Es la versión ligera del `config-matrix` que pide la Fase 5 (H-11): no comprueba
    que el camino FUNCIONE (eso es de la Fase 5), sólo que alguien lo lea. Con esto,
    las dos perillas wavelet que se borraron en la Fase 6 no pueden volver calladas.
    """
    config_py = BACKEND / "core" / "config.py"
    tree = ast.parse(_read(config_py))

    nombres: list[str] = []
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target and target.isupper():
            nombres.append(target)

    textos = [_read(p) for p in _py_files(ALL_DIRS)]
    propio = _read(config_py)

    sin_lector = []
    for n in nombres:
        patron = re.compile(rf"\b{n}\b")
        # referencias en el resto del backend...
        fuera = sum(1 for t in textos if patron.search(t))
        # ...o uso interno dentro del propio config.py (más allá de su definición)
        dentro = len(patron.findall(propio))
        if fuera == 0 and dentro <= 1:
            sin_lector.append(n)

    assert not sin_lector, (
        f"Constantes de core/config.py que no lee nadie: {sin_lector}. O se cablean, o "
        "se borran. Dejarlas es cómo sobrevivieron USE_SPARSE_DIRECT (rota) y las dos "
        "perillas de wavelet (inertes) hasta la auditoría."
    )
