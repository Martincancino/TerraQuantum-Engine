# -*- coding: utf-8 -*-
"""FASE 5 (auditoría 06 §10, hallazgo H-11) — cerrar la superficie de configuración.

**El encargo, literal.** *«Que ninguna variable de entorno documentada pueda estar
rota sin que la CI lo diga. Test parametrizado sobre las 44 variables: para cada
una, arrancar el camino que controla y verificar que importa y responde. Las 8 del
solver, además, con una inversión mínima real.»*

**Qué había ya, y qué le faltaba.** La Fase 3 dejó `test_fase3_config_matrix.py`, un
buen primer corte que **este archivo sustituye y borra** (la propia auditoría decía
que la Fase 5 *«se solapa con la Fase 3 y puede fusionarse con ella»*; mantener DOS
registros de las mismas variables es la enfermedad que esta fase existe para curar —
se separan y nadie se entera). Sus cuatro comprobaciones están aquí, cada una más
fuerte: inventario (42 variables de todo el árbol, no 22 de un archivo), llegada del
valor, entero basura que se nombra, y arranque con y sin autenticación. Se declaró a
sí mismo incompleto en dos frentes:

1. **Inventariaba sólo `core/config.py` (22 variables).** Medido con AST sobre TODO
   el backend —producción, tests y scripts, incluidos los `os.environ[...]` y los
   `os.environ.get(...)` que un `grep getenv` no ve— salen **42**. Las veinte que
   faltaban viven en `api/chat_api.py`, `services/run_queue_service.py`,
   `services/gee_client.py`, `services/joint_inversion.py`, `services/gemini_agent.py`
   y en los propios scripts de gate.
2. **Su sonda comprobaba que el módulo CARGA, no que la variable LLEGUE.** El cuerpo
   era «recarga `core.config` y mira que existan `host` y `port`»: eso pasa igual si
   la variable se ignora por completo. Aquí cada variable declara **dónde se observa
   su efecto** y el test lee ese valor.

**Y lo que la Fase 3 dijo que no podía ver** (su propio docstring: *«que un flag
arranca no significa que haga lo que promete… eso exige una inversión medida, y va
con la Fase 5»*): las perillas del solver se miden con una inversión real de 384
celdas, A/B, con la variable puesta **en el entorno del subproceso**, de modo que lo
que se ejercita es la cadena completa entorno → `core.config` → despacho del solver.

---

**Los cinco huecos que esta fase encontró al medir** (todos corregidos, cada uno con
su test abajo):

| | Qué | Cómo se midió |
|---|---|---|
| 1 | `ENABLE_FOCUSING` era una perilla **inerte**: `main.py` la leía, la guardaba en `_ENABLE_FOCUSING` y nadie la miraba jamás | sus 2 únicas apariciones en el repo eran su comentario y su asignación |
| 2 | El rollback documentado **no funcionaba con `0`, `no` ni `off`**: `USE_BOUNDED_SOLVER=0` dejaba el solver bounded activo | inversión real: modelo byte-idéntico al default |
| 3 | `TQ_AUTH_ENABLED=` (vacío) **encendía** la autenticación | arranque completo: `/geophysics/invert` 404 → **401** |
| 4 | `bounded_solver_active` en el reporte decía lo que se **pidió**, no lo que **pasó** | 8.712 celdas activas: el solver despachó `LSQR+clip` y el campo decía `true` |
| 5 | Tres lecturas numéricas fuera de `core/config.py` morían **sin nombrar la variable** | `chat_api`, y dos en `run_queue_service` (una de ellas dentro del worker) |

    python -m pytest tests/test_fase5_superficie_config.py -q
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DOC_DESPLIEGUE = REPO_ROOT / "docs" / "04_EMPAQUE_LOCAL_FIRST.md"

#: Los nombres de función que LEEN entorno. Se comparan por sufijo (`X` o `*_X`)
#: para que un alias local —`from core.config import env_bool as _eb`— no saque una
#: variable del censo en silencio. Pasó de verdad mientras se escribía esta fase.
LECTORES = ("getenv", "env_int", "env_bool", "env_float")

#: `terraquantum-backend/tmp/` es scratch y está en `.gitignore`: lo que haya ahí no
#: existe en un checkout limpio, así que incluirlo haría que el inventario diera un
#: número distinto en la CI y en la máquina de Martín. Un invariante que depende del
#: entorno no es un invariante (lección de la Fase 4).
DIRECTORIOS_FUERA_DEL_CENSO = ("build/", "dist/", ".venv", "tmp/")

# ─────────────────────────────────────────────────────────────────────────────
# EL REGISTRO
# ─────────────────────────────────────────────────────────────────────────────
# Cada variable declara CINCO cosas. Las tres primeras describen; las dos últimas
# son las que impiden que esto se pudra:
#
#   tipo      — bool | int | float | str | ruta | secreto | lista
#   ambito    — "produccion" (la lee código del producto) | "prueba" (sólo tests/scripts)
#   dueno     — el archivo que la lee
#   nivel     — CÓMO se ejercita, y es una escala honesta de fuerza de prueba:
#                 "inversion" → se mide con una inversión real (lo más fuerte)
#                 "arranque"  → se importa el módulo dueño y se LEE el valor derivado
#                 "llamada"   → se invoca la función que la lee y se comprueba el efecto
#                 "externo"   → el ejercicio vive en otro archivo, que se nombra
#                 "sitio"     → sólo se verifica el sitio de lectura (el más débil)
#   sonda     — lo que hace falta para ejecutar ese nivel (expresión, archivo o razón)
#
# `alterno` es SIEMPRE distinto del default: probar el default no prueba nada.

_C = "core/config.py"


def _v(tipo, ambito, dueno, nivel, sonda, alterno=None, esperado=None):
    return {"tipo": tipo, "ambito": ambito, "dueno": dueno, "nivel": nivel,
            "sonda": sonda, "alterno": alterno, "esperado": esperado}


REGISTRO: dict[str, dict] = {
    # ── core/config.py — arranque, red, datos ────────────────────────────────
    "TERRAQUANTUM_DATA_DIR": _v("ruta", "produccion", _C, "arranque",
                                "str(c.DATA_DIR)", "__TMP__"),
    "TERRAQUANTUM_HOST": _v("str", "produccion", _C, "arranque",
                            "c.BACKEND_HOST", "0.0.0.0"),
    "TERRAQUANTUM_PORT": _v("int", "produccion", _C, "arranque",
                            "c.BACKEND_PORT", "8099", 8099),
    "TERRAQUANTUM_INSTANCE_TOKEN": _v("str", "produccion", _C, "arranque",
                                      "c.INSTANCE_TOKEN", "tq-test-token"),
    "CORS_ALLOWED_ORIGINS": _v("lista", "produccion", _C, "arranque",
                               "c.CORS_ORIGINS", "http://localhost:4000",
                               ["http://localhost:4000"]),
    "CSV_MAX_BYTES": _v("int", "produccion", _C, "arranque",
                        "c.CSV_MAX_BYTES", "2048", 2048),
    # ── core/config.py — copiloto y datos externos ───────────────────────────
    "GEMINI_MODEL_NAME": _v("str", "produccion", _C, "arranque",
                            "c.GEMINI_MODEL_NAME", "gemini-x"),
    "GEMINI_CHAT_MODEL": _v("str", "produccion", _C, "arranque",
                            "c.GEMINI_CHAT_MODEL", "gemini-chat-x"),
    "GEMINI_REPORT_MODEL": _v("str", "produccion", _C, "arranque",
                              "c.GEMINI_REPORT_MODEL", "gemini-report-x"),
    "OPENTOPO_API_KEY": _v("secreto", "produccion", _C, "arranque",
                           "c.OPENTOPO_API_KEY", "clave-de-prueba"),
    # ── core/config.py — solver (las que la Fase 3 no pudo medir) ────────────
    # Nivel "inversion": además de comprobar que el valor LLEGA (como todas las de
    # arranque), se mide con una inversión real que CAMBIA algo — §5 de este archivo.
    "USE_BOUNDED_SOLVER": _v("bool", "produccion", _C, "inversion",
                             "c.USE_BOUNDED_SOLVER", "false", False),
    "USE_PROJECTED_SOLVER": _v("bool", "produccion", _C, "inversion",
                               "c.USE_PROJECTED_SOLVER", "false", False),
    "USE_LSMR_LARGE": _v("bool", "produccion", _C, "inversion",
                         "c.USE_LSMR_LARGE", "false", False),
    "LSMR_THRESHOLD_N_ACTIVE": _v("int", "produccion", _C, "inversion",
                                  "c.LSMR_THRESHOLD_N_ACTIVE", "1234", 1234),
    # ── core/config.py — observabilidad, auth, licencia ──────────────────────
    "OTEL_ENABLED": _v("bool", "produccion", _C, "arranque",
                       "c.OTEL_ENABLED", "true", True),
    "OTEL_SERVICE_NAME": _v("str", "produccion", _C, "arranque",
                            "c.OTEL_SERVICE_NAME", "tq-test"),
    "OTEL_EXPORTER_OTLP_ENDPOINT": _v("str", "produccion", _C, "arranque",
                                      "c.OTEL_EXPORTER_OTLP_ENDPOINT",
                                      "http://localhost:4318"),
    "TQ_AUTH_ENABLED": _v("bool", "produccion", _C, "arranque",
                          "c.TQ_AUTH_ENABLED", "true", True),
    "TQ_MASTER_KEY": _v("secreto", "produccion", _C, "arranque",
                        "c.TQ_MASTER_KEY", "tqmaster_de_prueba"),
    "TQ_LICENSE": _v("secreto", "produccion", _C, "arranque",
                     "c.TQ_LICENSE_TOKEN", "tqlic1.x.y"),
    "TQ_LICENSE_PUBLIC_KEY_HEX": _v("secreto", "produccion", _C, "arranque",
                                    "c.TQ_LICENSE_PUBLIC_KEY_HEX", "00" * 32),
    "TQ_FREE_MAX_VOXELS": _v("int", "produccion", _C, "arranque",
                             "c.TQ_TIER_LIMITS['free']['max_voxels']", "1000", 1000),
    # ── Producción FUERA de core/config.py (las que el inventario anterior no veía) ──
    "GEMINI_CONTEXT_CACHE": _v("bool", "produccion", "api/chat_api.py", "arranque",
                               "__import__('api.chat_api', fromlist=['x'])._CACHE_ENABLED",
                               "true", True),
    "GEMINI_CONTEXT_CACHE_TTL": _v("int", "produccion", "api/chat_api.py", "arranque",
                                   "__import__('api.chat_api', fromlist=['x'])._CACHE_TTL_SECONDS",
                                   "999", 999),
    "TQ_INVERSION_WORKERS": _v("int", "produccion", "services/run_queue_service.py",
                               "arranque",
                               "__import__('services.run_queue_service', fromlist=['x'])._MAX_WORKERS",
                               "3", 3),
    "GEMINI_API_KEY": _v("secreto", "produccion", "api/chat_api.py", "llamada",
                         "api.chat_api._resolve_api_key", "clave-de-entorno"),
    "GEE_CREDENTIALS_PATH": _v("ruta", "produccion", "services/gee_client.py", "llamada",
                               "services.gee_client.init_gee", "__TMP__"),
    # Gancho de prueba que lee CÓDIGO DE PRODUCCIÓN: `run_queue_service` duerme si
    # está puesta. Inocua sin la variable, pero queda declarada como lo que es.
    "TQ_TEST_SLOW_BEFORE_SOLVE_S": _v("float", "produccion",
                                      "services/run_queue_service.py", "externo",
                                      "tests/test_async_load_package.py"),
    "JOINT_ENABLE_GEMINI": _v("bool", "produccion", "services/joint_inversion.py", "sitio",
                              "se lee a mitad de `run_joint_inversion`, después de una "
                              "inversión conjunta completa (minutos); su único efecto es "
                              "llamar o no a un LLM externo. Ejercitarla de verdad exige "
                              "una corrida joint, que vive en la suite `validation`"),
    # ── Sólo pruebas y scripts de gate ───────────────────────────────────────
    "TQ_RUN_VALIDATION": _v("bool", "prueba", "tests/conftest.py", "externo",
                            "tests/conftest.py"),
    "TQ_GEN_N": _v("int", "prueba", "tests/test_ingesta_generativa.py", "externo",
                   "tests/test_ingesta_generativa.py"),
    "TQ_RUN_LARGE_BENCH": _v("bool", "prueba", "tests/test_projected_solver.py", "externo",
                             "tests/test_projected_solver.py"),
    "TQ_RUN_LARGE_FLOW": _v("bool", "prueba", "tests/test_field_data_complete_flow.py",
                            "externo", "tests/test_field_data_complete_flow.py"),
    "TQ_F8_FULL": _v("bool", "prueba", "scripts/validation/f8_gate_storm.py", "externo",
                     "scripts/validation/f8_gate_storm.py"),
    "TQ_F8_MATRIX_LIMIT": _v("int", "prueba", "scripts/validation/f8_gate_storm.py",
                             "externo", "scripts/validation/f8_gate_storm.py"),
    "TQ_F8_SKIP_FUZZ": _v("bool", "prueba", "scripts/validation/f8_gate_storm.py",
                          "externo", "scripts/validation/f8_gate_storm.py"),
    "TQ_F8_INGEST_BUDGET_S": _v("float", "prueba", "tests/test_f8_perf_budgets.py",
                                "externo", "tests/test_f8_perf_budgets.py"),
    "TQ_F8_INVERT_BUDGET_S": _v("float", "prueba", "tests/test_f8_perf_budgets.py",
                                "externo", "tests/test_f8_perf_budgets.py"),
    "TQ_F8_INVERT_GRID": _v("int", "prueba", "tests/test_f8_perf_budgets.py",
                            "externo", "tests/test_f8_perf_budgets.py"),
    "TQ_F8_SOAK_N": _v("int", "prueba", "tests/test_f8_soak.py", "externo",
                       "tests/test_f8_soak.py"),
    "TQ_F8_SOAK_MB_PER_ITER": _v("float", "prueba", "tests/test_f8_soak.py", "externo",
                                 "tests/test_f8_soak.py"),
    "TEMP": _v("ruta", "prueba", "scripts/validation/f7_gate_packaging.py", "externo",
               "scripts/validation/f7_gate_packaging.py"),
}

#: Las de producción que se quedan en el nivel más débil. Esta lista es FRÍA: si
#: alguien añade una, tiene que venir aquí y escribir por qué. Que sea incómodo es
#: el punto — el hallazgo H-11 nació de que nadie tuvo que justificar nada.
SOLO_SITIO_PERMITIDO = frozenset({"JOINT_ENABLE_GEMINI"})

#: Perillas BORRADAS por prometer y no despachar. No pueden volver sin su consumidor.
PERILLAS_ENTERRADAS = {
    "ENABLE_FOCUSING": "Fase 5: leída y jamás mirada (`_ENABLE_FOCUSING` sin lectores)",
    "USE_SPARSE_DIRECT": "Fase 6 (H-2): llamaba a una función inexistente",
    "USE_WAVELET_COMPRESSION": "Fase 6 (H-13): sin ningún lector",
    "WAVELET_THRESHOLD_N_ACTIVE": "Fase 6 (H-13): sin ningún lector",
    "STORAGE_BACKEND": "Fase 6 (H-12): la abstracción de nube se borró entera",
}

TIPOS_NUMERICOS = {"int", "float"}


# ─────────────────────────────────────────────────────────────────────────────
# Censo por AST
# ─────────────────────────────────────────────────────────────────────────────

def _es_environ(nodo: ast.AST) -> bool:
    return ((isinstance(nodo, ast.Attribute) and nodo.attr == "environ")
            or (isinstance(nodo, ast.Name) and nodo.id == "environ"))


def _es_lector(etiqueta: str | None) -> bool:
    if not etiqueta:
        return False
    return any(etiqueta == lec or etiqueta.endswith("_" + lec) for lec in LECTORES)


def censo_de_entorno() -> dict[str, list[str]]:
    """Toda lectura de entorno del backend, por AST, con archivo:línea.

    Cubre las cuatro formas que existen en este repositorio: `os.getenv(...)`,
    `os.environ["X"]`, `os.environ.get("X")` y los lectores tipados de
    `core.config` (`env_int`/`env_bool`/`env_float`). Recorre el AST entero, no
    sólo la cabecera: aquí hay lecturas dentro de funciones.
    """
    encontrado: dict[str, list[str]] = {}
    for ruta in BACKEND_ROOT.rglob("*.py"):
        rel = ruta.relative_to(BACKEND_ROOT).as_posix()
        if "__pycache__" in rel or rel.startswith(DIRECTORIOS_FUERA_DEL_CENSO):
            continue
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            nombre = None
            if isinstance(nodo, ast.Call):
                func = nodo.func
                etiqueta = getattr(func, "attr", None) or getattr(func, "id", None)
                primero = nodo.args[0] if nodo.args else None
                literal = (isinstance(primero, ast.Constant)
                           and isinstance(primero.value, str))
                if literal and _es_lector(etiqueta):
                    nombre = primero.value
                elif (literal and etiqueta in ("get", "setdefault", "pop")
                      and isinstance(func, ast.Attribute) and _es_environ(func.value)):
                    nombre = primero.value
                elif (literal and etiqueta in ("setenv", "delenv")
                      and isinstance(func, ast.Attribute)):
                    nombre = primero.value
            elif isinstance(nodo, ast.Subscript) and _es_environ(nodo.value):
                clave = nodo.slice
                if isinstance(clave, ast.Constant) and isinstance(clave.value, str):
                    nombre = clave.value
            if nombre:
                encontrado.setdefault(nombre, []).append(f"{rel}:{nodo.lineno}")
    return encontrado


def _run_probe(codigo: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    """Subproceso limpio: se le quitan TODAS las variables del registro.

    Sin esto la prueba mide el `.env.local` de la máquina en vez del código.
    """
    env = {k: v for k, v in os.environ.items() if k not in REGISTRO}
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", codigo], cwd=str(BACKEND_ROOT), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. El inventario está completo y no puede crecer a escondidas
# ─────────────────────────────────────────────────────────────────────────────

def test_el_inventario_cubre_todo_el_backend():
    """Una variable nueva sin declarar rompe la suite. Ése es el criterio de la fase.

    Y es el momento —el único— en que alguien se pregunta si de verdad hace falta
    otra perilla, que es como no se llega a cuarenta y cuatro.
    """
    censadas = set(censo_de_entorno())
    sin_declarar = sorted(censadas - set(REGISTRO))
    fantasma = sorted(set(REGISTRO) - censadas)
    assert not sin_declarar, (
        f"Variables de entorno que el backend lee y este registro no declara: "
        f"{sin_declarar}. Declararlas aquí (con su dueño y su nivel de ejercicio) "
        f"es el trabajo; si no vale la pena declararla, tampoco vale la pena leerla."
    )
    assert not fantasma, (
        f"Declaradas aquí pero ya nadie las lee: {fantasma}. Si se borró la perilla, "
        f"bórrala también de este registro y anótala en PERILLAS_ENTERRADAS."
    )


def test_ninguna_variable_se_queda_sin_ejercicio():
    """«0 variables sin ejercitar» — el criterio de aceptación, comprobado."""
    niveles = {"inversion", "arranque", "llamada", "externo", "sitio"}
    for nombre, ficha in sorted(REGISTRO.items()):
        assert ficha["nivel"] in niveles, f"{nombre}: nivel desconocido {ficha['nivel']!r}"
        assert ficha["sonda"], f"{nombre}: declara un nivel pero no cómo ejercitarlo"
        assert ficha["ambito"] in ("produccion", "prueba"), nombre
        if ficha["nivel"] != "sitio":
            continue
        assert nombre in SOLO_SITIO_PERMITIDO, (
            f"{nombre} se queda en el nivel más débil (sólo se verifica el sitio de "
            f"lectura). Si es inevitable, añádela a SOLO_SITIO_PERMITIDO con el "
            f"motivo escrito; que cueste es a propósito."
        )


def test_el_dueno_declarado_es_el_que_de_verdad_la_lee():
    """El registro documenta; si documenta mal, no sirve de nada."""
    censo = censo_de_entorno()
    for nombre, ficha in sorted(REGISTRO.items()):
        sitios = {sitio.rsplit(":", 1)[0] for sitio in censo.get(nombre, [])}
        assert ficha["dueno"] in sitios, (
            f"{nombre}: el registro dice que la lee {ficha['dueno']}, pero el censo "
            f"la encuentra en {sorted(sitios)}."
        )


@pytest.mark.parametrize(
    "nombre", sorted(n for n, f in REGISTRO.items() if f["nivel"] == "externo"))
def test_el_ejercicio_externo_existe_y_nombra_la_variable(nombre):
    """Si el ejercicio vive en otro archivo, ese archivo tiene que existir y usarla.

    Es la trampa de §9D.2 en pequeño: una ficha que dice «lo mide aquel de allá»
    y aquel de allá ya no la mide.
    """
    ruta = BACKEND_ROOT / REGISTRO[nombre]["sonda"]
    assert ruta.exists(), f"{nombre}: su ejercicio declarado {ruta} no existe"
    assert nombre in ruta.read_text(encoding="utf-8", errors="replace"), (
        f"{nombre}: {ruta.name} ya no la menciona — el ejercicio se perdió y la "
        f"ficha seguía diciendo que existía."
    )


@pytest.mark.parametrize("perilla", sorted(PERILLAS_ENTERRADAS))
def test_las_perillas_enterradas_no_vuelven(perilla):
    """Prometer un comportamiento y no despacharlo es el patrón de H-2/H-13/H-37.

    `ENABLE_FOCUSING` es el ejemplar que cazó esta fase: `main.py` la leía del
    entorno, la guardaba en `_ENABLE_FOCUSING` y **nadie la miraba nunca**. Una
    variable así no es inofensiva: aparece en el inventario, aparenta configurar
    algo y el día que alguien la ponga a `true` no pasará nada, sin aviso.
    """
    censo = censo_de_entorno()
    assert perilla not in censo, (
        f"{perilla} volvió al código ({censo.get(perilla)}). Motivo por el que se "
        f"borró: {PERILLAS_ENTERRADAS[perilla]}. Si ahora tiene un consumidor real, "
        f"entra con él en el mismo commit y se declara en REGISTRO."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cada camino arranca CON la variable puesta — y se lee el valor derivado
# ─────────────────────────────────────────────────────────────────────────────

#: Las que se leen al IMPORTAR su módulo dueño: se puede comprobar que el valor
#: llega arrancando ese módulo. Las de nivel "inversion" también entran aquí — que
#: la perilla cambie la física no exime de comprobar que el valor llegó.
_LLEGAN = sorted(n for n, f in REGISTRO.items() if f["nivel"] in ("arranque", "inversion"))


@pytest.mark.parametrize("nombre", _LLEGAN)
def test_la_variable_llega_a_su_consumidor(nombre, tmp_path):
    """Importar el módulo dueño y LEER el valor que la variable produce.

    La diferencia con la sonda de la Fase 3 es todo el asunto: aquélla comprobaba
    que `core.config` cargaba; ésta comprueba que el valor **llegó**. Un módulo que
    ignora por completo la variable pasaba aquella prueba y no pasa ésta.
    """
    ficha = REGISTRO[nombre]
    valor = ficha["alterno"]
    if valor == "__TMP__":
        valor = str(tmp_path)
    codigo = (
        "import json, core.config as c;"
        f"print('SONDA ' + json.dumps({{'v': {ficha['sonda']}}}, default=str))"
    )
    res = _run_probe(codigo, {nombre: valor})
    assert res.returncode == 0, (
        f"{ficha['dueno']} no carga con {nombre}={valor!r}:\n{res.stderr[-1500:]}"
    )
    linea = [ln for ln in res.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    obtenido = json.loads(linea[len("SONDA "):])["v"]
    esperado = ficha["esperado"] if ficha["esperado"] is not None else valor
    assert obtenido == esperado, (
        f"{nombre}={valor!r} no llegó a su destino: {ficha['sonda']} vale "
        f"{obtenido!r} y debería valer {esperado!r}."
    )


@pytest.mark.parametrize(
    "nombre", sorted(n for n, f in REGISTRO.items()
                     if f["ambito"] == "produccion" and f["tipo"] in TIPOS_NUMERICOS
                     and f["nivel"] in ("arranque", "inversion")))
def test_un_numero_basura_muere_nombrando_la_variable(nombre):
    """Fase 3 arregló esto dentro de `core/config.py`. Faltaban tres fuera.

    `int(os.getenv("GEMINI_CONTEXT_CACHE_TTL", "600"))` moría con `invalid literal
    for int()`, un mensaje que no nombra ninguna de las cuarenta y tantas. El peor
    de los tres era `TQ_TEST_SLOW_BEFORE_SOLVE_S`, que se lee **dentro del worker
    de inversión**: la corrida del usuario se caía a mitad.
    """
    ficha = REGISTRO[nombre]
    modulo = ficha["dueno"].replace("/", ".").removesuffix(".py")
    res = _run_probe(f"import {modulo}", {nombre: "no-soy-un-numero"})
    assert res.returncode != 0, (
        f"{nombre} con un valor no numérico debería impedir el arranque, no "
        f"seguir con un valor inventado."
    )
    assert nombre in res.stderr, (
        f"El error de {nombre} no la nombra — quien lo reciba en la máquina de un "
        f"cliente no sabrá cuál de las cuarenta y tantas es:\n{res.stderr[-800:]}"
    )


def test_los_lectores_tipados_se_nombran_tambien_fuera_del_arranque(monkeypatch):
    """El caso que el test de arriba NO puede cubrir, y es el peor de los tres.

    `TQ_TEST_SLOW_BEFORE_SOLVE_S` no se lee al importar: se lee **dentro del worker
    de inversión**, ya empezada la corrida del usuario. Un valor no numérico no
    rompía el arranque —eso se habría visto— sino la corrida, a mitad, con un
    `could not convert string to float` que no nombra ninguna variable. Como el
    fallo no ocurre en un `import`, se comprueba sobre el lector directamente.
    """
    from core.config import env_bool, env_float, env_int

    monkeypatch.setenv("TQ_TEST_SLOW_BEFORE_SOLVE_S", "dos segundos")
    with pytest.raises(ValueError, match="TQ_TEST_SLOW_BEFORE_SOLVE_S"):
        env_float("TQ_TEST_SLOW_BEFORE_SOLVE_S", 0.0)

    # El nombre se compone en tiempo de ejecución A PROPÓSITO: el censo de arriba
    # recorre también `tests/`, así que una variable inventada escrita como literal
    # entraría en el inventario y rompería su propio test. Pasó al escribir esto, y
    # es buena señal: significa que la red cubre de verdad todo el árbol.
    ficticia = "TQ_" + "VARIABLE_QUE_NO_EXISTE"
    monkeypatch.setenv(ficticia, "ni sí ni no")
    with pytest.raises(ValueError, match=ficticia):
        env_bool(ficticia, False)
    with pytest.raises(ValueError, match=ficticia):
        env_int(ficticia, 0)

    # Y el default se respeta cuando no hay nada que interpretar.
    monkeypatch.delenv(ficticia)
    assert env_bool(ficticia, True) is True
    assert env_int(ficticia, 7) == 7
    assert env_float(ficticia, 1.5) == 1.5


# ─────────────────────────────────────────────────────────────────────────────
# 3. Las dos de nivel "llamada": se invoca la función que las lee
# ─────────────────────────────────────────────────────────────────────────────

def test_gemini_api_key_llega_al_resolvedor(monkeypatch):
    """`GEMINI_API_KEY` es el último recurso de una cadena de tres.

    El producto es BYO-key: la clave viaja del navegador del consultor. La variable
    de entorno es el fallback del servidor, y hay que comprobar las dos cosas — que
    se usa cuando no hay nada mejor, y que **no pisa** a la clave del usuario.
    """
    import types

    from api.chat_api import _resolve_api_key

    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-entorno")
    peticion_sin_clave = types.SimpleNamespace(api_key=None)
    assert _resolve_api_key(peticion_sin_clave, None) == "clave-de-entorno"

    peticion_con_clave = types.SimpleNamespace(api_key="clave-del-usuario")
    assert _resolve_api_key(peticion_con_clave, None) == "clave-del-usuario", (
        "La clave del entorno del servidor pisó a la del usuario: eso rompe el "
        "modelo BYO-key (la corrida se cobraría a la cuenta equivocada)."
    )
    assert _resolve_api_key(peticion_sin_clave, "clave-de-cabecera") == "clave-de-cabecera"


def test_gee_credentials_path_llega_a_init_gee(monkeypatch, tmp_path):
    """La ruta de credenciales de Earth Engine se toma del entorno de verdad.

    Se apunta a un archivo que NO existe y se comprueba que el aviso nombra
    exactamente esa ruta: si la variable se ignorara, nombraría la de por defecto.
    No hace falta `ee` instalado ni credenciales reales.
    """
    import services.gee_client as gee

    registrado: list[tuple[str, dict]] = []

    class _LogEspia:
        def warning(self, evento, **kw):
            registrado.append((evento, kw))

        def info(self, evento, **kw):
            registrado.append((evento, kw))

    inexistente = tmp_path / "credenciales_que_no_estan.json"
    monkeypatch.setenv("GEE_CREDENTIALS_PATH", str(inexistente))
    monkeypatch.setattr(gee, "_log", _LogEspia())
    # `_gee_available` es un global de módulo que otro test (o el `init_gee()` que
    # `main.py` llama al arrancar) puede haber dejado en True. Se fija a False AQUÍ,
    # y monkeypatch lo restaura: así la comprobación de abajo dice algo —que esta
    # llamada no lo encendió— en vez de depender del orden de la suite. La primera
    # versión de este test asertaba `is False` a secas: pasaba aislado y fallaba en
    # la suite completa, que es exactamente la trampa que la Fase 4 dejó documentada.
    monkeypatch.setattr(gee, "_gee_available", False)
    gee.init_gee()

    assert registrado, "init_gee() no dijo nada con una ruta de credenciales inexistente"
    evento, datos = registrado[0]
    assert evento == "gee_credentials_not_found"
    assert datos.get("path") == str(inexistente), (
        f"GEE_CREDENTIALS_PATH se ignoró: init_gee() miró {datos.get('path')!r}."
    )
    assert gee.is_available() is False, (
        "init_gee() se declaró disponible con un archivo de credenciales que no existe."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. El vocabulario booleano — el hueco nº 2 y el nº 3
# ─────────────────────────────────────────────────────────────────────────────

_BOOLS_PRODUCCION = sorted(
    n for n, f in REGISTRO.items() if f["tipo"] == "bool" and f["ambito"] == "produccion"
    and f["dueno"] == _C
)

#: MEDIDO antes y después del arreglo. La columna «antes» está en el docstring de
#: `_env_bool`; esto congela el «después».
VOCABULARIO = [
    ("true", True), ("TRUE", True), ("True", True), ("1", True), ("yes", True),
    ("y", True), ("on", True), ("si", True), ("t", True),
    ("false", False), ("FALSE", False), ("0", False), ("no", False), ("n", False),
    ("off", False), ("f", False),
]


@pytest.mark.parametrize("valor,esperado", VOCABULARIO)
@pytest.mark.parametrize("nombre", _BOOLS_PRODUCCION)
def test_el_vocabulario_booleano_es_uno_solo(nombre, valor, esperado):
    """Antes de la Fase 5 había DOS vocabularios y los dos mentían fuera de
    `"true"`/`"false"`.

    Las perillas con default ON se leían `!= "false"`, así que `USE_BOUNDED_SOLVER=0`
    dejaba el solver bounded **activo** pese a que su propio comentario documenta
    `=false` como rollback. Las de default OFF se leían `== "true"`, así que
    `OTEL_ENABLED=1` no encendía nada. Un usuario no tiene por qué saber cuál de las
    dos formas le tocó.
    """
    codigo = f"import json, core.config as c; print('SONDA ' + json.dumps(c.{nombre}))"
    res = _run_probe(codigo, {nombre: valor})
    assert res.returncode == 0, res.stderr[-800:]
    linea = [ln for ln in res.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    assert json.loads(linea[len("SONDA "):]) is esperado, (
        f"{nombre}={valor!r} se interpretó al revés de lo que cualquiera esperaría."
    )


@pytest.mark.parametrize("nombre", _BOOLS_PRODUCCION)
def test_un_booleano_vacio_es_el_default_declarado(nombre):
    """`TQ_AUTH_ENABLED=` en un `.env.local` **encendía** la autenticación.

    Y no es rebuscado: el cargador de `.env.local` de `main.py` parte por el primer
    `=`, así que una línea `TQ_AUTH_ENABLED=` deja la cadena vacía en el entorno.
    Antes, vacío → `"" != "false"` → **True**. Medido de punta a punta:
    `POST /geophysics/invert` pasaba de 404 a **401**, o sea el camino dorado roto
    por escribir una variable que se lee como apagada. Vacío = no declarada.
    """
    codigo = f"import json, core.config as c; print('SONDA ' + json.dumps(c.{nombre}))"
    con_vacio = _run_probe(codigo, {nombre: ""})
    sin_nada = _run_probe(codigo, {})
    assert con_vacio.returncode == 0 and sin_nada.returncode == 0
    v1 = [ln for ln in con_vacio.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    v2 = [ln for ln in sin_nada.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    assert v1 == v2, (
        f"{nombre}='' no se comporta como {nombre} sin declarar: {v1} vs {v2}."
    )


@pytest.mark.parametrize("nombre", _BOOLS_PRODUCCION)
def test_un_booleano_ininteligible_muere_nombrando_la_variable(nombre):
    """Un flag de seguridad no se adivina: o se entiende, o se para y se dice cuál.

    Es la misma regla que la Fase 3 impuso a los enteros. La alternativa —elegir un
    default en silencio— es cómo `TQ_AUTH_ENABLED=quizas` acabaría encendiendo la
    autenticación sin que nadie lo pidiera.
    """
    res = _run_probe("import core.config", {nombre: "quizas"})
    assert res.returncode != 0, f"{nombre}='quizas' debería parar el arranque"
    assert nombre in res.stderr, res.stderr[-800:]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Las perillas del solver, con una INVERSIÓN MÍNIMA REAL
# ─────────────────────────────────────────────────────────────────────────────
# Esto es lo que la Fase 3 dijo que no podía hacer y dejó escrito para esta fase:
# «que un flag ARRANCA no significa que HAGA lo que promete».
#
# Malla de 8x6x8 = 384 celdas activas, 49 estaciones, cuerpo enterrado y 1% de
# ruido: la misma que usa `test_fase4_depth_weighting`, elegida porque cabe en
# segundos. Cada configuración corre en su propio subproceso **con la variable en
# el entorno**, así que lo que se ejercita es la cadena entera —entorno,
# `core.config`, despacho— y no un atributo de módulo parcheado a mano.
#
# El truco que lo hace barato: 384 celdas están por debajo del umbral de TRF
# (8.000) y por encima de un `LSMR_THRESHOLD_N_ACTIVE` que se puede bajar a 100.
# Con eso, los tres caminos del solver —TRF, LSMR y LSQR— se alcanzan en la misma
# malla diminuta.

BLOQUE = 100.0
BASE_DENSIDAD = 2.67
NX = NZ = 8
NY = 6


def _caso_minimo():
    import numpy as np

    from exploration.gravimetry import GravimetryForward

    rng = np.random.default_rng(20260814)
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel(order="F") + 0.5) * BLOQUE
    y_c = (iy.ravel(order="F") + 0.5) * BLOQUE
    z_c = (iz.ravel(order="F") + 0.5) * BLOQUE
    centro = NX * BLOQUE / 2.0
    eje = np.linspace(BLOQUE, (NX - 1) * BLOQUE, 7)
    gx, gz = np.meshgrid(eje, eje, indexing="ij")
    sensores = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(float)

    contraste = np.zeros(x_c.size)
    cuerpo = ((np.abs(x_c - centro) <= BLOQUE) & (np.abs(z_c - centro) <= BLOQUE)
              & (y_c >= 2 * BLOQUE) & (y_c <= 3 * BLOQUE))
    contraste[cuerpo] = 0.8
    fwd = GravimetryForward(BLOQUE, BLOQUE, BLOQUE, cutoff_radius=3000.0)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ contraste).ravel()
    g = g + 0.01 * float(np.max(np.abs(g))) * rng.standard_normal(g.size)
    return x_c, y_c, z_c, sensores, g, 0.02 * float(np.max(np.abs(g)))


def _sonda_inversion() -> int:
    """Punto de entrada del subproceso: invierte y escribe una línea JSON."""
    import numpy as np

    from exploration.gravimetry import GravimetryForward, GravimetryInversion

    x_c, y_c, z_c, sensores, g_obs, piso = _caso_minimo()
    inv = GravimetryInversion(NX, NY, NZ, BLOQUE, base_density=BASE_DENSIDAD)
    fwd = GravimetryForward(BLOQUE, BLOQUE, BLOQUE, cutoff_radius=3000.0)
    meta: dict = {}
    rho, _s, _m, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=0.31623, alpha_spatial=1.0, forward_model=fwd,
        sensor_coords=sensores, x_c=x_c, z_c=z_c, density_min=BASE_DENSIDAD,
        density_max=BASE_DENSIDAD + 1.5, noise_floor=piso, noise_pct=0.02,
        prune_observable_domain=True, regularization_norm="L2", solver_meta=meta,
    )
    v = np.nan_to_num(np.asarray(rho, dtype=float), nan=BASE_DENSIDAD) - BASE_DENSIDAD
    print("SONDA " + json.dumps({
        "solver_path": meta.get("solver_path"),
        "bounded_usado": meta.get("bounded_solver_used"),
        "bounded_pedido": meta.get("bounded_solver_requested"),
        "lsmr_usado": meta.get("lsmr_used"),
        "proyectado_usado": meta.get("projected_solver_used"),
        "n_active": meta.get("n_active"),
        "chi2": float(meta.get("chi2_final", float("nan"))),
        "l2": float(np.linalg.norm(v)),
        "pico": float(np.max(np.abs(v))),
    }))
    return 0


def _invertir_con(**entorno) -> dict:
    codigo = (
        "from tests.test_fase5_superficie_config import _sonda_inversion;"
        "_sonda_inversion()"
    )
    res = _run_probe(codigo, {k: str(v) for k, v in entorno.items()})
    assert res.returncode == 0, (
        f"La inversión mínima no corrió con {entorno}:\n{res.stderr[-2000:]}"
    )
    linea = [ln for ln in res.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    return json.loads(linea[len("SONDA "):])


def _difieren(a: dict, b: dict) -> float:
    """Diferencia relativa entre dos modelos, por su norma L2."""
    escala = max(abs(a["l2"]), abs(b["l2"]), 1e-30)
    return abs(a["l2"] - b["l2"]) / escala


@pytest.mark.slow
def test_use_bounded_solver_esta_vivo_y_cambia_el_modelo():
    """La perilla despacha OTRO solver y produce OTRO modelo. No es decorativa."""
    con = _invertir_con()
    sin = _invertir_con(USE_BOUNDED_SOLVER="false")

    assert con["n_active"] == sin["n_active"] == 384, "cambió la malla, no el solver"
    assert con["solver_path"] == "TRF/bounded"
    assert con["bounded_usado"] is True
    assert sin["solver_path"] == "LSQR+clip"
    assert sin["bounded_usado"] is False
    assert _difieren(con, sin) > 1e-8, (
        "USE_BOUNDED_SOLVER cambia el solver despachado pero el modelo sale "
        "idéntico: o el despacho no ocurre, o esta sonda dejó de medir el solver."
    )


@pytest.mark.slow
def test_el_rollback_documentado_tambien_funciona_con_cero():
    """El hueco nº 2, convertido en invariante.

    `core/config.py` documenta `USE_BOUNDED_SOLVER=false` como rollback a LSQR+clip.
    MEDIDO antes del arreglo: con `=0` el solver seguía despachando **TRF/bounded** y
    el modelo salía byte a byte igual al default. Quien intentara el rollback con la
    forma que escribe todo el mundo no obtenía rollback **ni aviso**.
    """
    for apagado in ("false", "0", "no", "off", "FALSE"):
        r = _invertir_con(USE_BOUNDED_SOLVER=apagado)
        assert r["bounded_usado"] is False and r["solver_path"] == "LSQR+clip", (
            f"USE_BOUNDED_SOLVER={apagado!r} no hizo rollback: despachó "
            f"{r['solver_path']!r}."
        )


@pytest.mark.slow
def test_use_projected_solver_esta_vivo_y_lo_que_cuesta_apagarlo():
    """FISTA proyectado no es una preferencia de estilo: es ajustar el dato o no.

    MEDIDO en esta misma malla: con la perilla encendida χ² = 0,244; apagada,
    χ² = 22,7 — **93 veces peor**. El comentario histórico decía «el clip degradaba
    el misfit ~35%»; el número real, en este caso, es de otro orden. La perilla se
    conserva (es la vía de escape si FISTA se rompe) pero ahora su coste está medido
    en vez de estimado.
    """
    encendido = _invertir_con(USE_BOUNDED_SOLVER="false")
    apagado = _invertir_con(USE_BOUNDED_SOLVER="false", USE_PROJECTED_SOLVER="false")

    assert encendido["proyectado_usado"] is True
    assert apagado["proyectado_usado"] is False
    assert apagado["chi2"] > 5.0 * encendido["chi2"], (
        f"USE_PROJECTED_SOLVER dejó de importar: chi2 {encendido['chi2']:.3f} -> "
        f"{apagado['chi2']:.3f}. Si el refinamiento ya no cambia el ajuste, o se "
        f"volvió inerte o el warm start dejó de ser un clip."
    )


@pytest.mark.slow
def test_use_lsmr_large_y_su_umbral_estan_vivos():
    """El tercer camino del solver, alcanzado bajando el umbral en la misma malla.

    **Matiz honesto y medido**: LSMR y LSQR producen aquí el MISMO modelo (coinciden
    a nueve decimales; cond(A)≈1e2, o sea un sistema bien condicionado donde los dos
    convergen al mismo sitio). Eso NO es que la perilla esté inerte —el despacho
    cambia y se comprueba— sino que en este régimen los dos solvers están de acuerdo,
    que es exactamente lo que uno querría. La perilla existe para mallas de 50k+
    celdas mal condicionadas, y ese régimen no cabe en un test de segundos: se dice
    en vez de fingir que se prueba.
    """
    lsmr = _invertir_con(USE_BOUNDED_SOLVER="false", LSMR_THRESHOLD_N_ACTIVE="100")
    lsqr = _invertir_con(USE_BOUNDED_SOLVER="false", LSMR_THRESHOLD_N_ACTIVE="100",
                         USE_LSMR_LARGE="false")

    assert lsmr["lsmr_usado"] is True, (
        "Con el umbral en 100 y 384 celdas activas, el solver debería haber "
        "despachado LSMR. LSMR_THRESHOLD_N_ACTIVE no está moviendo la frontera."
    )
    assert lsmr["solver_path"].startswith("LSMR")
    assert lsqr["lsmr_usado"] is False and lsqr["solver_path"] == "LSQR+clip", (
        "USE_LSMR_LARGE=false no devolvió el despacho a LSQR."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. El hueco nº 4: el reporte decía lo que se PIDIÓ, no lo que PASÓ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_el_reporte_dice_que_solver_corrio_de_verdad():
    """`bounded_solver_active` mentía en el régimen NORMAL del producto.

    El campo se calculaba con `os.getenv("USE_BOUNDED_SOLVER")` en
    `geophysics_service`, o sea lo que se pidió. Pero el solver sólo despacha TRF por
    debajo de **8.000 celdas activas**; el producto declara mallas de 30k-100k
    vóxeles. MEDIDO con 8.712 celdas y la variable sin tocar: el solver ejecutó
    `LSQR+clip` y el reporte afirmaba `bounded_solver_active: true`.

    No es cosmético. `validation/runner.py` lee ese campo para caracterizar cada
    corrida: era evidencia de validación contaminada, y es el mismo patrón que la
    auditoría llamó el más grave (H-37) — el sistema afirmando algo que no hizo.
    """
    import importlib

    import numpy as np

    from exploration.gravimetry import GravimetryForward, GravimetryInversion

    cfg = importlib.import_module("core.config")   # el módulo VIVO, no una copia
    previo = cfg.USE_BOUNDED_SOLVER
    cfg.USE_BOUNDED_SOLVER = True                  # se PIDE el solver con bounds
    try:
        nx = nz = 22
        ny = 18
        ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
        x_c = (ix.ravel(order="F") + 0.5) * BLOQUE
        y_c = (iy.ravel(order="F") + 0.5) * BLOQUE
        z_c = (iz.ravel(order="F") + 0.5) * BLOQUE
        centro = nx * BLOQUE / 2.0
        eje = np.linspace(BLOQUE, (nx - 1) * BLOQUE, 7)
        gx, gz = np.meshgrid(eje, eje, indexing="ij")
        sensores = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(float)
        contraste = np.zeros(x_c.size)
        contraste[((np.abs(x_c - centro) <= BLOQUE) & (np.abs(z_c - centro) <= BLOQUE)
                   & (y_c >= 2 * BLOQUE) & (y_c <= 3 * BLOQUE))] = 0.8
        fwd = GravimetryForward(BLOQUE, BLOQUE, BLOQUE, cutoff_radius=3000.0)
        g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ contraste).ravel()
        g = g + 0.01 * float(np.max(np.abs(g))) * np.random.default_rng(1).standard_normal(g.size)

        meta: dict = {}
        inv = GravimetryInversion(nx, ny, nz, BLOQUE, base_density=BASE_DENSIDAD)
        inv.solve_inversion_lsqr(
            g, None, y_c, lambda_mag=0.31623, alpha_spatial=1.0, forward_model=fwd,
            sensor_coords=sensores, x_c=x_c, z_c=z_c, density_min=BASE_DENSIDAD,
            density_max=BASE_DENSIDAD + 1.5, noise_floor=0.02 * float(np.max(np.abs(g))),
            noise_pct=0.02, prune_observable_domain=True, regularization_norm="L2",
            solver_meta=meta,
        )
    finally:
        cfg.USE_BOUNDED_SOLVER = previo

    assert meta["n_active"] > 8_000, (
        "Este test necesita pasarse del umbral de TRF para medir lo que mide."
    )
    assert meta["bounded_solver_requested"] is True
    assert meta["bounded_solver_used"] is False, (
        "Con más de 8.000 celdas activas el solver NO usa TRF. Si esto cambió, "
        "cambió el umbral: actualiza el test a propósito."
    )
    assert meta["solver_path"] == "LSQR+clip"


def test_el_servicio_publica_el_solver_real_y_no_la_variable_de_entorno():
    """Guarda estática del mismo hueco: el campo no puede volver a leer el entorno.

    Vale la pena tenerla además del test que mide, porque es instantánea y porque el
    error original era de UNA línea: alguien puede rehacerlo sin querer.
    """
    fuente = (BACKEND_ROOT / "services" / "geophysics_service.py").read_text(
        encoding="utf-8", errors="replace")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Dict)):
            continue
        for clave, valor in zip(nodo.keys, nodo.values):
            if not (isinstance(clave, ast.Constant) and clave.value == "bounded_solver_active"):
                continue
            leido = ast.dump(valor)
            assert "getenv" not in leido and "environ" not in leido, (
                "`bounded_solver_active` volvió a leer la variable de entorno. Ese "
                "campo describe lo que HIZO el solver, y el solver decide también "
                "por tamaño de malla: publicar la variable es afirmar algo que no "
                "se comprobó. Sale de `solver_meta`."
            )
            assert "solver_meta" in leido, (
                "`bounded_solver_active` debe salir de `solver_meta`, que es quien "
                "sabe qué se despachó."
            )
            return
    pytest.fail("No se encontró el campo `bounded_solver_active` en el reporte.")


# ─────────────────────────────────────────────────────────────────────────────
# 7. TQ_AUTH_ENABLED: resuelta explícitamente, como pedía la fase
# ─────────────────────────────────────────────────────────────────────────────

_SONDA_APP = (
    "import json;"
    "from fastapi.testclient import TestClient;"
    "import main;"
    "c = TestClient(main.app);"
    "print('SONDA ' + json.dumps({"
    "  'health': c.get('/health').status_code,"
    "  'invert': c.post('/geophysics/invert', json={}).status_code,"
    "  'desconocida': c.get('/__ruta_que_no_existe__').status_code}))"
)


def _arrancar_app(tmp_path, **entorno) -> dict:
    res = _run_probe(_SONDA_APP, {"TERRAQUANTUM_DATA_DIR": str(tmp_path), **entorno})
    assert res.returncode == 0, res.stderr[-2000:]
    linea = [ln for ln in res.stdout.splitlines() if ln.startswith("SONDA ")][-1]
    return json.loads(linea[len("SONDA "):])


@pytest.mark.slow
def test_tq_auth_enabled_queda_declarada_con_lo_que_hace_hoy(tmp_path):
    """La fase exigía resolverla: *o se arregla, o se elimina, o se marca*.

    **Se marca, y con el número corregido.** `docs/03` decía *«el frontend nunca
    envía X-TQ-API-Key»*. Es falso: **17 de los 43 proxies de Next.js SÍ la
    reenvían** desde `process.env.TQ_API_KEY`. Los otros 26 no, y entre ellos está
    `geophysics-invert`. La rotura no es total sino **asimétrica** —importar y
    exportar funcionan, invertir devuelve 401—, que es peor de diagnosticar. Y el
    orquestador de escritorio (`src-tauri/src/lib.rs`) no fija `TQ_AUTH_ENABLED` ni
    `TQ_API_KEY`, así que ni los 17 tendrían clave que enviar.

    Veredicto: **perilla de despliegue SERVIDOR/Docker, no soportada con la UI web**,
    escrito en `docs/04` y dicho en voz alta en cada arranque (`main.py`). Este test
    congela el comportamiento REAL; el día que se cablee de verdad, cambia a
    propósito y en el mismo commit.
    """
    apagada = _arrancar_app(tmp_path, TQ_AUTH_ENABLED="false")
    assert apagada["health"] == 200
    assert apagada["desconocida"] == 404, (
        "Sin autenticación una ruta inexistente da 404. Si diera 401, el resto de "
        "esta comprobación estaría midiendo otra cosa."
    )
    assert apagada["invert"] != 401, "sin autenticación no debería pedir clave"

    encendida = _arrancar_app(tmp_path, TQ_AUTH_ENABLED="true",
                              TQ_MASTER_KEY="tqmaster_de_prueba")
    assert encendida["health"] == 200, "/health es pública a propósito (arranque)"
    assert encendida["invert"] == 401, (
        "Con la autenticación activada, invertir DEBE pedir clave. Si esto deja de "
        "ser 401 es que alguien abrió el camino dorado sin autenticar."
    )
    assert encendida["desconocida"] == 401


# ─────────────────────────────────────────────────────────────────────────────
# 8. La documentación de despliegue no puede quedarse atrás
# ─────────────────────────────────────────────────────────────────────────────

def test_la_doc_de_despliegue_documenta_todas_las_de_produccion():
    """Una perilla que el producto lee y la doc de despliegue no menciona es una
    perilla que el cliente no sabe que existe — o que descubre por accidente.

    Sale gratis mantenerlo cierto y evita la clase entera de deriva que produjo
    H-11: la superficie creció durante catorce fases sin que nadie llevara la lista.
    """
    assert DOC_DESPLIEGUE.exists(), f"falta {DOC_DESPLIEGUE}"
    texto = DOC_DESPLIEGUE.read_text(encoding="utf-8", errors="replace")
    de_produccion = sorted(n for n, f in REGISTRO.items() if f["ambito"] == "produccion")
    faltan = [n for n in de_produccion if n not in texto]
    assert not faltan, (
        f"{len(faltan)} variables que el producto lee y `docs/04` no documenta: "
        f"{faltan}."
    )


if __name__ == "__main__":   # `python -c "...import _sonda_inversion..."` no pasa por aquí
    raise SystemExit(_sonda_inversion())
