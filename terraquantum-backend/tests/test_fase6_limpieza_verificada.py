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
    # Primera pasada (2026-08-09): los 7 que la auditoría había nombrado.
    ("exploration.solver_preconditioned", "solve_inversion_lsmr_wavelet"),
    ("exploration.preprocessing", "remove_regional_scale"),
    ("exploration.geophysics_math", "build_gradient_operators_from_mesh"),
    ("services.export_service", "export_core_to_gslib"),
    ("services.export_service", "export_block_model_to_gslib"),
    ("core.logging", "configure_logging"),
    ("services.block_model_store", "resolve_mine_design_block_model_reference"),
    # Cierre (2026-08-14): H-13 pedía revisar los 16 "uno a uno" y la primera pasada
    # resolvió los 6 que la auditoría había listado como "destacables" (§9B.5) — los
    # otros nunca se enumeraron. Al volver a medirlos con el cruce de referencias AST
    # aparecieron estos 11, cada uno con su lápida en el sitio donde vivía.
    ("core.metrics", "INVERSIONS_TOTAL"),
    ("core.metrics", "INVERSION_DURATION"),
    ("core.metrics", "ACTIVE_INVERSIONS"),
    ("exploration.preprocessing", "upward_continue_gravity_fft"),
    ("services.geophysics_service", "normalize_array"),
    ("services.gravity_corrections_service", "compute_free_air_correction_simple"),
    ("services.gravity_import_service", "normalize_unit"),
    ("services.gravity_import_service", "ALLOWED_MAGNETIC_UNITS"),
    ("services.gravity_import_service", "calculate_optimal_block_size"),
    ("services.gravity_import_service", "auto_compute_grid_params"),
    ("services.run_queue_service", "queue_snapshot"),
    ("core.config", "MAGNETIC_SUSCEPTIBILITY_PRESETS"),
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
    ("core.logging", "get_logger"),
    ("core.utils", "clean_trace_id"),
    # Cierre 2026-08-14: cada borrado del cierre tiene al lado el vivo que se le parece
    # y que un borrado por nombre se llevaría por delante.
    ("core.metrics", "PrometheusMiddleware"),                      # la instrumentación HTTP SÍ mide
    ("core.metrics", "HTTP_REQUESTS_TOTAL"),
    ("services.gravity_import_service", "canonicalize_unit"),      # el normalizador de unidades de verdad
    ("services.grid_calculator_service", "compute_auto_grid"),     # la calculadora de grilla A1.3, viva
    ("services.gravity_corrections_service", "compute_free_air_correction"),  # la FAC con latitud
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


def test_h13_el_modulo_wavelet_sigue_borrado():
    """`exploration/jacobian_wavelet.py`: el limbo que dejó la primera pasada.

    La Fase 6 borró su único llamador posible (`solve_inversion_lsmr_wavelet`) y dejó
    el módulo "vivo y con tests". Sin llamador, esos tests eran sus únicos importadores
    — y la Fase 3 los ejecutó en un runner con PyWavelets y midió que el algoritmo NO
    cumple su criterio §10.6.1 (98,2% retenido exigiendo <15%). Cablearlo exigía
    rehacerlo, que es física; así que al cerrar la fase se borró.
    """
    assert not (BACKEND / "exploration" / "jacobian_wavelet.py").exists(), (
        "jacobian_wavelet.py volvió. Si alguien retoma Farquharson & Oldenburg (2003), "
        "que vuelva CON su llamador de producción y con un criterio de compresión que "
        "el algoritmo cumpla de verdad — no con dos tests en xfail."
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("exploration.jacobian_wavelet")


SCRIPTS_VALIDACION_BORRADOS = ["wz_smallness_liveness.py", "wz_tradeoff.py"]


@pytest.mark.parametrize("script", SCRIPTS_VALIDACION_BORRADOS)
def test_h13_los_instrumentos_rotos_no_vuelven(script):
    """Un instrumento que no puede correr y que la documentación cita como si midiera.

    Ambos pasaban `smallness_depth_beta=` a `solve_inversion_lsqr` después de que el
    W_z-fix se revirtiera: ejecutarlos daba `TypeError`. La Fase 4 los marcó y dejó el
    borrado a esta fase. Su EVIDENCIA no se tocó: los report JSON siguen al lado.
    """
    val = BACKEND / "scripts" / "validation"
    assert not (val / script).exists(), (
        f"{script} volvió. Daba TypeError contra el solver actual. El sucesor vivo es "
        "wz_separation_probe.py."
    )
    reporte = val / script.replace(".py", "_report.json")
    assert reporte.exists(), (
        f"Se borró {reporte.name}, que es justamente lo que NO había que borrar: es la "
        "medición que docs/05 cita. El script era el instrumento roto; el reporte es la "
        "evidencia."
    )


# --------------------------------------------------------------------------- #
# H-14 — dependencias declaradas y no importadas                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("dep", ["shapely", "distributed", "PyWavelets"])
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


@pytest.mark.parametrize("dep", ["shapely", "distributed", "pywt"])
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


# --------------------------------------------------------------------------- #
# Guardia general: H-13 no puede volver a acumularse en silencio               #
# --------------------------------------------------------------------------- #
#
# Los tests de arriba defienden borrados CONCRETOS: nombran los símbolos que se fueron.
# Eso no impide que aparezcan OTROS. Y es justo lo que pasó: la auditoría contó 16
# símbolos huérfanos, la primera pasada resolvió los 6 que estaban listados por nombre
# en §9B.5, y los demás siguieron ahí — invisibles, porque nadie volvió a MEDIR.
#
# Este test mide. Un símbolo público de producción cuya única aparición en todo el
# repositorio (código + tests + scripts) es su propia definición rompe la suite.

# Excepciones DECLARADAS, con su motivo y su fase dueña. No son código muerto: son
# CONTRATOS escritos que hoy nadie ENFORZA — que es un problema distinto y con otra cura.
# Borrarlos tiraría la única descripción escrita de la forma de esas respuestas; el
# arreglo (cablear `response_model=` o generar los tipos del frontend desde OpenAPI)
# cambia la serialización en runtime, o sea comportamiento, y eso es la Fase 10 (H-16).
HUERFANOS_TOLERADOS = {
    "GeophysicsInvertResponse": "schemas/geophysics_schema.py — describe la respuesta de la inversión, pero el endpoint declara GeophysicsInversionStartResponse. Contrato sin enforcar → Fase 10.",
    "GeorefSummary": "schemas/project_schema.py — el frontend lo replica A MANO en lib/terraquantum/frontendApi.ts (H-16: 40 tipos duplicados). Generarlo desde OpenAPI → Fase 10.",
    "BlockModelArrowMetadata": "schemas/response_schema.py — documenta las cabeceras X-TQ-* del stream Arrow, que se escriben a mano. Contrato sin enforcar → Fase 10.",
    # Lo dejó la Fase 8 al partir la espina dorsal y lleva rojo desde entonces;
    # la Fase 12 lo midió y le puso nombre sin cerrarlo. La Fase 13 lo declara
    # (salida 3 del mensaje de este test) porque es exactamente eso: NO es código
    # muerto, es un contrato sin enforcar, hermano de los tres de arriba.
    # MEDIDO: los cuatro solvers del repositorio ya devuelven la tupla que este
    # Protocol describe; lo que falta es que alguien la compruebe. Cablearlo es
    # anotar cuatro firmas del camino crítico, que no es una fase de frontend.
    # SIN FASE DUEÑA en el plan §10.
    "Solver": "exploration/protocols.py — Protocol que nombra el contrato de los cuatro solvers (tupla de 4 arrays + `solver_meta`). Ningún módulo lo importa porque nada tipa contra él. Contrato sin enforcar, no código muerto.",
}


def _simbolos_publicos_de_produccion() -> dict[str, tuple[str, int, list[str]]]:
    """nombre → (archivo, línea, decoradores) de cada def/class/CONSTANTE pública."""
    encontrados: dict[str, list[tuple[str, int, list[str]]]] = {}
    for p in _py_files(PROD_DIRS):
        rel = str(p.relative_to(BACKEND)).replace("\\", "/")
        for node in ast.parse(_read(p)).body:
            nombre = None
            decoradores: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nombre = node.name
                decoradores = [ast.unparse(d) for d in node.decorator_list]
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id.isupper():
                    nombre = target.id
            if nombre and not nombre.startswith("_"):
                encontrados.setdefault(nombre, []).append((rel, node.lineno, decoradores))
    # Un nombre definido en dos sitios es un reexport o una variante por plataforma:
    # medir sus referencias por nombre no distingue cuál se usa, así que no se juzga.
    return {k: v[0] for k, v in encontrados.items() if len(v) == 1}


def _nombres_referenciados() -> set[str]:
    """Todo identificador que APARECE en el repo, mirando el AST y no el texto.

    A propósito no cuenta comentarios ni docstrings: si contaran, la lápida que explica
    un borrado mantendría vivo al muerto, y bastaría nombrar un símbolo en un comentario
    para que este test dejara de verlo.

    Sí cuenta CADENAS, porque `getattr(mod, "x")` y `monkeypatch.setattr("mod.x", ...)`
    son referencias reales. Y por eso ESTE archivo se excluye del barrido: los nombres
    de `HUERFANOS_TOLERADOS` y de `SIMBOLOS_BORRADOS` son cadenas, así que incluirse a
    sí mismo hacía que la lista que existe para TOLERAR un huérfano lo marcara como
    vivo — la excepción se volvía innecesaria y, peor, cualquier símbolo muerto pasaría
    inadvertido con sólo nombrarlo aquí. Medido el 2026-08-15: sin esta exclusión los
    tres contratos de `HUERFANOS_TOLERADOS` desaparecían del recuento.
    """
    vistos: set[str] = set()
    for p in _py_files(ALL_DIRS):
        if p.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                vistos.add(node.id)
            elif isinstance(node, ast.Attribute):
                vistos.add(node.attr)
            elif isinstance(node, ast.alias):
                vistos.add(node.name.split(".")[-1])
                if node.asname:
                    vistos.add(node.asname)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # `__all__`, getattr(m, "x"), monkeypatch.setattr("mod.x", ...)
                vistos.add(node.value)
                vistos.add(node.value.split(".")[-1])
    return vistos


def _es_endpoint(decoradores: list[str]) -> bool:
    """A un handler lo referencia su decorador, no su nombre."""
    return any(
        marca in d
        for d in decoradores
        for marca in ("router.", "app.", "route", "exception_handler", "middleware")
    )


def test_h13_ningun_simbolo_publico_nuevo_se_queda_sin_consumidor():
    definidos = _simbolos_publicos_de_produccion()
    referenciados = _nombres_referenciados()

    huerfanos = {}
    for nombre, (archivo, linea, decoradores) in definidos.items():
        if nombre in referenciados or nombre in HUERFANOS_TOLERADOS or _es_endpoint(decoradores):
            continue
        huerfanos[nombre] = f"{archivo}:{linea}"

    assert not huerfanos, (
        "Símbolos públicos de producción cuya única aparición en el repositorio es su "
        f"propia definición: {huerfanos}\n\n"
        "Esto es H-13 volviendo a crecer. Tres salidas legítimas, en este orden:\n"
        "  1. CABLEARLO — si hace falta, que lo llame producción y que un test ejercite "
        "ese camino. Un símbolo entra el mismo día que su consumidor.\n"
        "  2. BORRARLO — con su lápida explicando por qué, como los demás de esta fase.\n"
        "  3. DECLARARLO en HUERFANOS_TOLERADOS — sólo si NO es código muerto sino un "
        "contrato sin enforcar, con el motivo medido y la fase que lo cierra.\n"
        "Lo que no vale es dejarlo: así llegaron los 16 de la auditoría."
    )
