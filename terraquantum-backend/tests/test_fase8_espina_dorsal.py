"""
FASE 8 (auditoría 06 §10) — La espina dorsal partida, y que siga partida.
=========================================================================

La Fase 8 no se termina el día que la función baja de 2.030 líneas a 152: se
termina cuando algo IMPIDE que vuelva a crecer. La propia auditoría lo dice en su
lista de instrumentos: «publicar métricas AST como gate que **falla si empeoran**
— así la Fase 8 no se deshace sola con el tiempo».

Este archivo es ese gate, con cuatro clases de afirmación:

1. **Los techos del camino crítico**, por nombre. El presupuesto AST de la Fase 3
   vigila el MÁXIMO de cada paquete; eso deja pasar que una función concreta del
   camino dorado crezca mientras otra sea peor. Aquí se nombran las funciones.

2. **El contrato HTTP de `/invert`**, campo a campo. El paso 2 agrupó 41
   parámetros en objetos de configuración; si esa agrupación cambiara el
   formulario que viaja por el cable, el frontend dejaría de funcionar sin que
   ningún test lo dijera. Medido: con `Annotated[Modelo, Form()]` —la lectura
   literal de la auditoría— el formulario SÍ cambia; con `Depends`, no.

3. **La configuración fuera del bucle del solver** (paso 4), y la razón por la
   que NO sube a nivel de módulo: media docena de sondas de validación fijan
   `core.config` por atributo justo antes de llamar.

4. **Los protocolos** de la frontera orquestación ↔ física (paso 5) se cumplen de
   verdad, no sólo en el papel.

Ninguna de estas afirmaciones toca física: la física la defiende
`scripts/validation/fase8_byte_identity.py` (28 configuraciones, SHA-256 sobre el
payload y sobre los bits del parquet) y `fase7_byte_identity.py` (34 casos sobre
los motores).
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

#: Techos de la fase. La auditoría pide «~300 LOC, CC 40, 12 args» para el camino
#: crítico; se toman literales y sin margen: el margen ya lo da `SLACK` en el
#: presupuesto por paquete, y aquí lo que se vigila son cinco funciones contadas.
MAX_LOC = 300
MAX_CC = 40
MAX_ARGS = 12

#: El camino dorado, por nombre. Si mañana se parte otra función y aparece aquí,
#: es porque alguien decidió que también es camino crítico — no por inercia.
CAMINO_CRITICO = [
    ("services/geophysics_service.py", "run_geophysics_inversion"),
    ("api/gravity_import_api.py", "invert_gravity_csv"),
    ("exploration/gravimetry.py", "solve_inversion_lsqr"),
]

_BRANCHING = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.Assert, ast.IfExp,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)


def _cc(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCHING):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


def _n_args(node: ast.AST) -> int:
    a = node.args
    return (len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
            + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


def _buscar(rel: str, nombre: str):
    tree = ast.parse((BACKEND_ROOT / rel).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre:
            return n
    raise AssertionError(f"{nombre} no existe en {rel}")


# ── 1. techos del camino crítico ─────────────────────────────────────────────

@pytest.mark.parametrize("rel,nombre", CAMINO_CRITICO)
def test_camino_critico_bajo_los_techos(rel, nombre):
    """Ninguna función del camino crítico supera ~300 LOC ni CC 40."""
    fn = _buscar(rel, nombre)
    loc = fn.end_lineno - fn.lineno + 1
    cc = _cc(fn)
    assert loc <= MAX_LOC, (
        f"{rel}::{nombre} mide {loc} líneas (techo {MAX_LOC}). "
        "La Fase 8 la partió; si vuelve a crecer, se parte otra vez — no se sube "
        "el techo sin explicar por qué en el PR."
    )
    assert cc <= MAX_CC, f"{rel}::{nombre} tiene CC={cc} (techo {MAX_CC})."


def test_todo_helper_de_la_espina_bajo_el_techo():
    """Partir no vale si las piezas son igual de grandes que el original."""
    grandes = []
    for rel in {r for r, _ in CAMINO_CRITICO}:
        tree = ast.parse((BACKEND_ROOT / rel).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (n.name.startswith("_lsqr_") or n.name.startswith("_invert_")
                    or n.name.startswith("_armar_") or n.name.startswith("_preparar_")
                    or n.name.startswith("_diagnosticar_") or n.name.startswith("_persistir_")
                    or n.name.startswith("_ejecutar_") or n.name.startswith("_resolver_")):
                continue
            loc = n.end_lineno - n.lineno + 1
            if loc > MAX_LOC or _cc(n) > MAX_CC or _n_args(n) > MAX_ARGS:
                grandes.append(f"{rel}::{n.name} LOC={loc} CC={_cc(n)} args={_n_args(n)}")
    assert not grandes, "helpers de la Fase 8 fuera de techo:\n  " + "\n  ".join(grandes)


def test_handler_http_no_tiene_41_parametros():
    """El paso 2: `validar, delegar, serializar` con una firma que se lee."""
    fn = _buscar("api/gravity_import_api.py", "invert_gravity_csv")
    n = _n_args(fn)
    assert n <= MAX_ARGS, (
        f"invert_gravity_csv tiene {n} parámetros (techo {MAX_ARGS}). "
        "Los `Form(...)` van en las dependencias `_cfg_*`, no en el handler."
    )


def test_presupuesto_ast_vigila_tambien_los_argumentos():
    """`args_max` existe en la línea base: antes NADIE medía el ancho de firma."""
    base = json.loads(
        (BACKEND_ROOT / "scripts" / "ci" / "ast_baseline.json").read_text(encoding="utf-8"))
    sin_args = [p for p, d in base.items() if "args_max" not in d]
    assert not sin_args, (
        f"paquetes sin `args_max` en la línea base: {sin_args}. "
        "Corre `python scripts/ci/ast_budgets.py --update`."
    )


# ── 2. el contrato HTTP no cambió al agrupar los parámetros ──────────────────

#: Los 40 campos del formulario multipart de `/invert`, tal como los recibía el
#: frontend ANTES de la Fase 8. Agrupar los parámetros en objetos NO puede tocar
#: esta lista: es el contrato con la UI.
CAMPOS_INVERT = {
    "acknowledge_regional_scale", "acknowledge_spatial_risk", "allow_g_raw",
    "alpha_spatial", "anchor_kappa", "auto_kappa", "block_size", "boreholes_json",
    "compact_eps", "compact_max_irls", "cutoff_radius", "data_type",
    "declination_deg", "density_max", "density_min", "depth", "fe",
    "field_intensity_nt", "file", "gravimeter_type", "helmert_control_points_json",
    "inclination_deg", "lambda_mag", "lat", "lon", "nir", "nx", "ny", "nz",
    "padding_kappa", "pgi_params_json", "project_id", "region",
    "regularization_norm", "remanence_json", "run_id", "strict", "susc_max",
    "susc_min", "utm_zone",
}


def test_formulario_de_invert_sigue_plano():
    """Si esto falla, el frontend deja de poder invertir — y nada más lo diría."""
    os.environ.setdefault("TQ_AUTH_ENABLED", "false")
    from main import app

    esquema = app.openapi()
    cuerpo = (esquema["paths"]["/gravity-import/invert"]["post"]["requestBody"]
              ["content"]["multipart/form-data"]["schema"])
    ref = cuerpo.get("$ref", "")
    if ref:
        cuerpo = esquema["components"]["schemas"][ref.split("/")[-1]]
    campos = set(cuerpo.get("properties", {}).keys())

    faltan = CAMPOS_INVERT - campos
    sobran = campos - CAMPOS_INVERT
    assert not faltan, f"campos del formulario que desaparecieron: {sorted(faltan)}"
    assert not sobran, (
        f"campos nuevos en el formulario: {sorted(sobran)}. "
        "Si son objetos anidados (`malla`, `reg`…), el agrupamiento se hizo con "
        "`Annotated[Modelo, Form()]` en vez de `Depends` y el contrato cambió."
    )


# ── 3. la configuración, fuera del bucle del solver ──────────────────────────

def test_config_no_se_importa_dentro_del_bucle_irls():
    """Paso 4: la configuración se resuelve UNA vez, no en cada reponderación."""
    tree = ast.parse((BACKEND_ROOT / "exploration" / "gravimetry.py").read_text(encoding="utf-8"))
    dentro_de_bucle = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.For, ast.While)):
            continue
        for hijo in ast.walk(n):
            if isinstance(hijo, ast.ImportFrom) and (hijo.module or "").startswith("core.config"):
                dentro_de_bucle.append(hijo.lineno)
    assert not dentro_de_bucle, (
        f"`from core.config import ...` dentro de un bucle, líneas {dentro_de_bucle}. "
        "Se resuelve arriba de la función."
    )


def test_config_se_lee_por_llamada_y_no_al_importar():
    """Y NO sube a nivel de módulo: hay sondas que la fijan por atributo.

    `wz_separation_probe.py` lo dice en un comentario propio: «gravimetry lo
    importa dentro del bucle». Si el import subiera al módulo, esas sondas
    seguirían escribiendo `core.config.USE_BOUNDED_SOLVER` y el solver ya no lo
    leería: medirían en silencio la configuración equivocada.
    """
    fuente = (BACKEND_ROOT / "exploration" / "gravimetry.py").read_text(encoding="utf-8")
    tree = ast.parse(fuente)
    for n in tree.body:                      # nivel de MÓDULO
        if isinstance(n, ast.ImportFrom) and (n.module or "") == "core.config":
            nombres = [a.name for a in n.names]
            assert not {"USE_BOUNDED_SOLVER", "USE_PROJECTED_SOLVER",
                        "USE_LSMR_LARGE"} & set(nombres), (
                f"perillas del solver importadas a nivel de módulo: {nombres}")
    # Se leen DENTRO de alguna función del motor — hoy, en el que prepara el
    # bucle IRLS (`_lsqr_resolver_irls`). Lo que importa no es en cuál, sino que
    # sea en tiempo de llamada y no en tiempo de import.
    perillas = set()
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for h in ast.walk(n):
            if isinstance(h, ast.ImportFrom) and (h.module or "") == "core.config":
                perillas |= {a.name for a in h.names}
    assert {"USE_BOUNDED_SOLVER", "USE_PROJECTED_SOLVER", "USE_LSMR_LARGE"} <= perillas, (
        "el solver debe leer sus perillas EN CADA LLAMADA "
        f"(encontradas: {sorted(perillas)})")


# ── 4. la frontera orquestación ↔ física existe y se cumple ──────────────────

def test_protocolos_los_cumplen_los_operadores_reales():
    """Paso 5: escribir la forma sólo vale si la forma es la del código real."""
    from exploration.gravimetry import GravimetryForward
    from exploration.magnetometry import MagnetometryForward
    from exploration.protocols import CLAVES_SOLVER_META_MINIMAS, ForwardOperator

    g = GravimetryForward(10.0, 10.0, 10.0, cutoff_radius=100.0)
    m = MagnetometryForward(10.0, 10.0, 10.0, cutoff_radius=100.0,
                            inclination_deg=-30.0, declination_deg=2.0,
                            field_intensity_nt=23500.0)
    assert isinstance(g, ForwardOperator)
    assert isinstance(m, ForwardOperator)
    assert "solver_path" in CLAVES_SOLVER_META_MINIMAS, (
        "la Fase 5 midió que publicar lo PEDIDO en vez de lo OCURRIDO produjo un "
        "reporte falso: `solver_path` es parte del contrato mínimo.")


# ── 5. el instrumento de la fase está y cubre lo que dice cubrir ─────────────

def test_arnes_de_byte_identidad_congelado():
    """Sin línea base congelada, el criterio duro de la fase no es verificable."""
    base_path = (BACKEND_ROOT / "scripts" / "validation"
                 / "fase8_byte_identity_baseline.json")
    assert base_path.is_file(), (
        "falta la línea base de byte-identidad de la Fase 8: "
        "`python scripts/validation/fase8_byte_identity.py --freeze`")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    servicio = [k for k in base if k.startswith("servicio/")]
    api = [k for k in base if k.startswith("api/")]
    assert len(servicio) >= 20, f"sólo {len(servicio)} casos de servicio congelados"
    assert len(api) >= 7, f"sólo {len(api)} casos de API congelados"
