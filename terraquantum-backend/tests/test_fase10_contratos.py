"""FASE 10 (auditoría 06 §10, H-16) — El contrato tiene un solo dueño.

H-16 midió que el frontend replicaba a mano los esquemas Pydantic y avisó de la
consecuencia: *el backend cambia un campo y no falla nada hasta que el usuario ve
un dato vacío*. La fase genera los tipos desde OpenAPI. Este archivo es lo que
impide que esa cadena se rompa en silencio, y vigila los **tres** puntos donde
puede romperse:

1. **Declarar un contrato no puede cambiar el payload.** MEDIDO al escribir la
   fase, y las dos direcciones muerden:
     · un `response_model` estricto **borra** los campos que no declara;
     · un `response_model` a secas **inyecta** los opcionales que el endpoint no
       emitió (apareció `user_supplied_key: null` en 3 de las 4 features de
       conectividad, donde antes la clave no existía).
   Aquí se comprueba llamando a los endpoints de verdad y comparando con el
   servicio que hay detrás.

2. **Los espejos no derivan.** `SniffReportContract` y
   `ColumnMappingPlanContract` describen estructuras que ya existían (una
   `@dataclass` y un `dict`). Duplicar una forma es el pecado que la fase
   persigue, así que el espejo se sostiene con un test que compara campo a campo
   contra la fuente REAL, no con buena voluntad.

3. **Los tipos del frontend están al día.** El `--check` del generador. Un
   backend que cambia un contrato y no regenera deja el rojo aquí, que es donde
   se puede arreglar, y no en la pantalla de un consultor.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest
from fastapi.routing import APIRoute

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_ROOT = (BACKEND_ROOT.parent / "terraquantum-web").resolve()

os.environ.setdefault("TQ_AUTH_ENABLED", "false")


@pytest.fixture(scope="module")
def app():
    import main  # import perezoso: monta la app entera

    return main.app


@pytest.fixture(scope="module")
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _rutas_con_modelo(app) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and r.response_model is not None]


def _claves_de_dicts_devueltos(fn) -> list[set[str]]:
    """Claves de cada `return {...}` literal del handler, por AST.

    Sólo mira literales: un `return sanitize_nan(algo)` no dice nada estático y
    se ignora a propósito — para eso está la comparación dinámica de abajo.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return []
    # Los decoradores (`@limiter.limit(...)`) rompen el parseo de un fragmento.
    limpio = "\n".join(l for l in src.split("\n") if not l.strip().startswith("@"))
    try:
        arbol = ast.parse(inspect.cleandoc(limpio))
    except SyntaxError:
        return []
    salida = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Return) and isinstance(nodo.value, ast.Dict):
            salida.append({k.value for k in nodo.value.keys if isinstance(k, ast.Constant)})
    return salida


# ── 1. Declarar un contrato no puede cambiar el payload ──────────────────────

def test_ningun_response_model_borra_campos_que_el_endpoint_emite(app):
    """La regla, medida y no nombrada: si un handler devuelve un `dict` literal
    bajo un `response_model`, cada clave de ese dict tiene que estar declarada —
    o el modelo tiene que aceptar extras.

    Se mide por AST sobre TODAS las rutas, así que también caza el endpoint que
    alguien escriba mañana. Es el caso peor, y el más silencioso: el campo
    desaparece del JSON sin error, sin log y sin test rojo.
    """
    delitos = []
    for r in _rutas_con_modelo(app):
        modelo = r.response_model
        campos = getattr(modelo, "model_fields", None)
        if campos is None:  # List[...] u otro genérico: sin campos que filtrar
            continue
        permisivo = getattr(modelo, "model_config", {}).get("extra") == "allow"
        if permisivo:
            continue
        declarados = set(campos)
        for claves in _claves_de_dicts_devueltos(r.endpoint):
            borradas = claves - declarados
            if borradas:
                delitos.append(
                    f"{sorted(r.methods)[0]} {r.path} → {modelo.__name__} "
                    f"BORRA {sorted(borradas)}"
                )

    assert not delitos, (
        "Hay endpoints cuyo `response_model` filtra campos que el handler sí "
        "emite. El frontend no los verá NUNCA y nada falla.\n"
        "Arreglo: declarar el campo en el modelo, o `model_config = "
        "ConfigDict(extra=\"allow\")` si el endpoint emite superficie abierta.\n  "
        + "\n  ".join(delitos)
    )


#: Rutas ANTERIORES a esta fase cuyo `response_model` permisivo no lleva
#: `exclude_unset`, toleradas con motivo y fase dueña. Igual que
#: `HUERFANOS_TOLERADOS` (Fase 6) y las excusas de la Fase 9: la lista es
#: portante — hay un test abajo que la obliga a describir la realidad.
INYECCION_TOLERADA: dict[str, str] = {
    "GET /block-model": (
        "MEDIDO al cerrar la Fase 10 sobre una respuesta real (127 claves): con "
        "`exclude_unset` NO desaparecería ninguna, porque el constructor emite "
        "todos los campos declarados. Añadirlo sería un cambio sin efecto "
        "observable en el camino dorado y con riesgo distinto de cero en las "
        "ramas que no se midieron (Arrow, zarr, modo mineral). Dueña: Fase 13."
    ),
    "POST /gravity-import/preview": (
        "Ruta v1 de previsualización. No se pudo medir el delta sin un CSV real "
        "por endpoint, y esta fase no cambia payloads que no puede medir — es la "
        "regla que evitó la regresión de `user_supplied_key`. Dueña: Fase 11, "
        "que es la que se hace cargo de la superficie v1 de scripting."
    ),
    "POST /gravity-import/invert": (
        "Igual que la anterior, y además invierte de verdad: medir su delta "
        "cuesta minutos de solver. Dueña: Fase 11."
    ),
}


def test_los_contratos_permisivos_no_inyectan_campos(app):
    """`extra="allow"` protege de que se borre, no de que se AÑADA.

    Un modelo con opcionales serializa sus defaults aunque el endpoint no los
    haya emitido, y eso cambia el payload igual de silenciosamente. La contra es
    `response_model_exclude_unset=True`. Se exige a todo modelo permisivo que
    declare algún campo opcional Y cuyo handler devuelva un `dict`
    (con un `Response` ya construido FastAPI no serializa, así que no aplica).
    """
    from fastapi.responses import Response as _Response

    delitos = []
    for r in _rutas_con_modelo(app):
        modelo = r.response_model
        campos = getattr(modelo, "model_fields", None)
        if campos is None:
            continue
        if getattr(modelo, "model_config", {}).get("extra") != "allow":
            continue
        if r.response_model_exclude_unset:
            continue
        tiene_opcionales = any(not c.is_required() for c in campos.values())
        if not tiene_opcionales:
            continue
        # ¿El handler devuelve un Response ya construido? Entonces no serializa.
        try:
            src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            src = ""
        if "JSONResponse(" in src or "PlainTextResponse(" in src or "FileResponse(" in src:
            continue
        anotacion = inspect.signature(r.endpoint).return_annotation
        if isinstance(anotacion, type) and issubclass(anotacion, _Response):
            continue
        clave = f"{sorted(r.methods)[0]} {r.path}"
        if clave in INYECCION_TOLERADA:
            continue
        delitos.append(f"{clave} → {modelo.__name__}")

    assert not delitos, (
        "Modelos permisivos con campos opcionales y sin "
        "`response_model_exclude_unset=True`: la respuesta saldrá con los "
        "opcionales en `null` aunque el endpoint no los emita, y eso ES un "
        "cambio de contrato.\n"
        "O se añade `response_model_exclude_unset=True`, o se declara en "
        "INYECCION_TOLERADA con motivo MEDIDO y fase dueña.\n  "
        + "\n  ".join(delitos)
    )


def test_la_lista_de_inyeccion_tolerada_es_portante(app):
    """Cada excusa tiene que seguir describiendo una ruta real que de verdad
    inyecta. Sin esto la lista se pudre: una ruta arreglada seguiría tolerada
    para siempre y el guard perdería fuerza sin que nadie se entere."""
    rutas = {f"{sorted(r.methods)[0]} {r.path}": r for r in _rutas_con_modelo(app)}
    for clave, motivo in INYECCION_TOLERADA.items():
        assert clave in rutas, f"{clave} ya no existe o perdió su response_model: quítala."
        assert motivo.strip(), f"{clave} tolerada sin motivo escrito."
        assert not rutas[clave].response_model_exclude_unset, (
            f"{clave} YA lleva `response_model_exclude_unset`: quítala de "
            "INYECCION_TOLERADA (la excusa dejó de ser cierta)."
        )


def _normalizar(objeto, ignorar=()):
    from core.utils import sanitize_nan

    d = json.loads(json.dumps(sanitize_nan(objeto), default=str, sort_keys=True))
    for ruta in ignorar:
        cur = d
        *padres, hoja = ruta.split(".")
        for p in padres:
            cur = cur.get(p, {}) if isinstance(cur, dict) else {}
        if isinstance(cur, dict):
            cur.pop(hoja, None)
    return d


def test_la_respuesta_http_es_identica_a_la_del_servicio(client):
    """La comprobación que de verdad cierra el riesgo: llamar de las dos formas.

    El AST no ve lo que pasa dentro de `sanitize_nan(...)` ni dentro de un
    servicio; esto sí. Si un `response_model` de esta fase empezara a filtrar o a
    inyectar, la comparación cae con el nombre del campo.
    """
    from core import license_service
    from services import diagnostics_service, project_store
    from services.connectivity_service import connectivity_summary

    casos = [
        ("/license/status", "/license/status", license_service.get_license_status, ()),
        ("/system/connectivity", "/system/connectivity",
         lambda: connectivity_summary(probe=False), ()),
        # `generated_at` es un reloj: se excluye de la COMPARACIÓN, no del payload.
        ("/diagnostics/manifest", "/diagnostics/manifest",
         diagnostics_service.diagnostic_manifest, ("system.generated_at",)),
        ("/v2/history/runs", "/v2/history/runs?limit=3",
         lambda: {"runs": project_store.list_runs(limit=3),
                  "count": len(project_store.list_runs(limit=3))}, ()),
    ]
    for nombre, url, servicio, ignorar in casos:
        respuesta = client.get(url)
        assert respuesta.status_code == 200, f"{nombre} devolvió {respuesta.status_code}"
        via_http = _normalizar(respuesta.json(), ignorar)
        directo = _normalizar(servicio(), ignorar)
        assert via_http == directo, (
            f"{nombre}: el `response_model` CAMBIÓ el payload.\n"
            f"  sólo por HTTP: {sorted(set(via_http) - set(directo))}\n"
            f"  sólo del servicio: {sorted(set(directo) - set(via_http))}"
        )


def test_activate_no_promete_un_campo_que_nunca_manda(client):
    """La asimetría concreta que la fase encontró midiendo, anclada por nombre.

    `GET /license/status` devuelve `mode`; `POST /license/activate` **no**. El
    frontend usaba UN tipo con `mode` obligatorio para las dos respuestas: leer
    `.mode` tras activar da `undefined` y TypeScript no dice nada. No se cambia
    la conducta del backend (añadir un campo es decisión de producto): se
    declaran dos contratos distintos. Si algún día `activate` empieza a devolver
    `mode`, este test cae y toca unificarlos — que es la conversación correcta.
    """
    activacion = client.post("/license/activate", json={"token": "no-es-un-token"})
    assert activacion.status_code == 200, (
        "El endpoint de licencias NUNCA lanza: un token inválido responde 200 "
        "con `activated:false`. Mirar el código de estado no basta."
    )
    cuerpo = activacion.json()
    assert cuerpo.get("activated") is False
    assert "mode" not in cuerpo, (
        "`/license/activate` ahora devuelve `mode`: unifica "
        "LicenseActivationResponse con LicenseStatusResponse y regenera los "
        "tipos del frontend."
    )
    assert "mode" in client.get("/license/status").json(), (
        "`/license/status` dejó de devolver `mode`, que es de donde el panel "
        "saca «Licencia activa» vs «Modo local libre»."
    )


# ── 2. Los espejos no derivan ────────────────────────────────────────────────

def _exigir_requeridos(modelo, claves_reales: set[str], quien: str) -> None:
    """En un modelo de RESPUESTA, un default es una promesa que nadie quiso hacer.

    Descubierto cableando el frontend: `Field(default_factory=list)` hace que
    OpenAPI marque el campo como opcional, el tipo generado sale con `?`, y el
    consumidor acaba con 25 `?? []` defensivos para un caso que **no puede
    ocurrir** — porque el servicio emite ese campo siempre. Peor: la maraña
    defensiva esconde los sitios donde el campo SÍ puede faltar de verdad.

    La regla, entonces: lo que el servicio emite siempre, el contrato lo declara
    obligatorio. Un default sólo se justifica si el campo puede no venir.
    """
    flojos = sorted(
        nombre for nombre, campo in modelo.model_fields.items()
        if nombre in claves_reales and not campo.is_required()
    )
    assert not flojos, (
        f"{modelo.__name__} declara opcionales unos campos que {quien} emite "
        f"SIEMPRE: {flojos}.\n"
        "El tipo generado saldrá con `?` y el frontend se llenará de guardas "
        "para un caso imposible. Quítales el default."
    )

def test_el_espejo_del_sniff_report_no_ha_derivado(tmp_path):
    """`SniffReportContract` describe el cable; la `@dataclass` del servicio hace
    el trabajo. Son dos declaraciones de la misma forma — exactamente lo que H-16
    contó — y sólo es aceptable porque esto falla si divergen."""
    from schemas.ingest_contracts_schema import SniffReportContract
    from services.csv_sniffer_service import sniff_csv

    csv = tmp_path / "sniff.csv"
    csv.write_text(
        "x_m,y_m,z_m,g_obs_mgal\n"
        + "\n".join(f"{i * 10},{i * 5},{100 + i},{9.8 + i * 0.001:.4f}" for i in range(6)),
        encoding="utf-8",
    )
    reales = set(sniff_csv(csv).to_dict())
    declarados = set(SniffReportContract.model_fields)

    assert not (reales - declarados), (
        "El sniffer emite campos que el contrato no declara: el frontend no los "
        f"verá tipados. Falta declarar {sorted(reales - declarados)}."
    )
    assert not (declarados - reales), (
        "El contrato declara campos que el sniffer ya no emite: el frontend los "
        f"cree garantizados y llegan `undefined`. Sobra {sorted(declarados - reales)}."
    )
    _exigir_requeridos(SniffReportContract, reales, "el sniffer")


def test_el_espejo_del_plan_de_mapeo_no_ha_derivado():
    """Mismo trato para el plan de mapeo, que es el PILAR 1 de la ingesta."""
    from schemas.ingest_contracts_schema import ColumnMappingPlanContract
    from services.column_mapping_service import build_column_mapping_plan

    plan = build_column_mapping_plan(
        ["x_m", "y_m", "z_m", "g_obs_mgal"], data_kind="gravity",
    )
    reales = set(plan)
    declarados = set(ColumnMappingPlanContract.model_fields)

    assert not (reales - declarados), (
        f"El plan emite campos sin declarar: {sorted(reales - declarados)}."
    )
    assert not (declarados - reales), (
        f"El contrato declara campos que el plan ya no emite: {sorted(declarados - reales)}."
    )
    _exigir_requeridos(ColumnMappingPlanContract, reales, "el plan de mapeo")


def test_los_contratos_de_sistema_no_declaran_opcional_lo_que_siempre_llega():
    """Misma regla para la superficie F7, medida contra los servicios reales.

    Es la que hizo falta para que `ConnectivityPanel` pudiera escribir
    `summary.online_features.map(...)` sin una guarda para un `undefined` que el
    backend no produce nunca.
    """
    from core import license_service
    from services import diagnostics_service, project_store
    from services.connectivity_service import connectivity_summary
    from schemas.system_schema import (
        ConnectivitySummaryResponse,
        DiagnosticManifestResponse,
        HistoryRunsResponse,
        LicenseStatusResponse,
    )

    casos = [
        (LicenseStatusResponse, set(license_service.get_license_status()), "license_service"),
        (ConnectivitySummaryResponse, set(connectivity_summary(probe=False)),
         "connectivity_service"),
        (DiagnosticManifestResponse, set(diagnostics_service.diagnostic_manifest()),
         "diagnostics_service"),
        (HistoryRunsResponse, {"runs", "count"}, "history_api"),
    ]
    for modelo, reales, quien in casos:
        sin_declarar = reales - set(modelo.model_fields)
        assert not sin_declarar, (
            f"{quien} emite {sorted(sin_declarar)} y {modelo.__name__} no lo declara."
        )
        _exigir_requeridos(modelo, reales, quien)


def test_las_variantes_de_load_package_existen_en_el_contrato(app):
    """El frontend conserva una unión discriminada por `status` que es MÁS
    precisa que lo que OpenAPI sabe expresar. Se acepta que siga escrita a mano
    —degradarla a un tipo con todo opcional sería empeorar— a cambio de que sus
    campos estén anclados aquí."""
    from schemas.ingest_contracts_schema import LoadPackageResponse

    declarados = set(LoadPackageResponse.model_fields)
    # Un campo por cada variante real del endpoint (error / queued / done).
    for campo in ("status", "stage", "errors", "warnings",
                  "project_id", "run_id", "route", "poll", "budget",
                  "multimodal_plan", "inversionResult"):
        assert campo in declarados, (
            f"`{campo}` desapareció de LoadPackageResponse: la unión escrita a "
            "mano del frontend dejó de tener respaldo en el contrato."
        )


# ── 3. Los tipos del frontend están al día ───────────────────────────────────

def _web_disponible() -> bool:
    return WEB_ROOT.is_dir() and (WEB_ROOT / "types").is_dir()


@pytest.mark.skipif(not _web_disponible(),
                    reason="terraquantum-web no está presente: este guard cruza backend↔frontend.")
def test_los_tipos_del_frontend_estan_al_dia():
    """El `--check` del generador, ejecutado de verdad.

    Se lanza en un proceso aparte porque el generador monta la app y escribe;
    aquí sólo interesa su veredicto. Rojo = alguien cambió un contrato del
    backend y no regeneró: los tipos del frontend están describiendo un backend
    que ya no existe.
    """
    guion = BACKEND_ROOT / "scripts" / "ci" / "generate_frontend_types.py"
    proceso = subprocess.run(
        [sys.executable, str(guion), "--check"],
        cwd=str(BACKEND_ROOT), capture_output=True, text=True, timeout=600,
        env={**os.environ, "TQ_AUTH_ENABLED": "false", "PYTHONIOENCODING": "utf-8"},
    )
    assert proceso.returncode == 0, (
        "Los tipos generados del frontend no coinciden con el OpenAPI de HOY.\n"
        "Corre:  python scripts/ci/generate_frontend_types.py\n\n"
        + (proceso.stdout or "") + (proceso.stderr or "")
    )


def test_la_lista_de_rutas_del_cable_es_portante(app):
    """Como `HUERFANOS_TOLERADOS` en la Fase 6 y las excusas de la Fase 9: una
    lista que nombra rutas se pudre en cuanto una se renombra. Ésta no puede."""
    sys.path.insert(0, str(BACKEND_ROOT / "scripts" / "ci"))
    from generate_frontend_types import RUTAS_DEL_CABLE

    existentes = {r.path for r in app.routes if isinstance(r, APIRoute)}
    muertas = [r for r in RUTAS_DEL_CABLE if r not in existentes]
    assert not muertas, (
        "RUTAS_DEL_CABLE nombra rutas que ya no existen; el generador estaría "
        f"emitiendo tipos de un backend imaginario: {muertas}"
    )


# ── 4. El frontend: presupuesto de estado y contratos sin copiar ─────────────

#: Techo de `useState` por componente (criterio de aceptación de la Fase 10).
#: 12 no es un número redondo elegido al azar: es el de la auditoría, y el
#: argumento es que por encima de ahí el número de combinaciones alcanzables deja
#: de poder razonarse y de poder testearse.
PRESUPUESTO_USE_STATE = 12

_DECL_TS = re.compile(
    r"^\s*(?:export\s+)?(?:type\s+([A-Za-z0-9_]+)\s*=\s*\{"
    r"|interface\s+([A-Za-z0-9_]+)\s*(?:extends[^{]*)?\{)",
    re.M,
)

#: Contratos generados que TODAVÍA tienen un cuerpo escrito a mano en el
#: frontend. Es deuda MEDIDA, no una excusa abierta: la lista no puede crecer, y
#: cada entrada dice por qué sigue ahí.
#:
#: Se intentó aliasarlos y `tsc` devolvió 20 errores de UNA sola causa:
#: `default_factory` en esquemas de otras fases (convergencia, sondajes,
#: correcciones) marca opcionales campos que el servicio emite siempre. Hacerlo
#: bien exige tocar cinco esquemas más, con riesgo de HTTP 500 en rutas que sí
#: validan. Dueña: **Fase 11**.
CONTRATOS_AUN_A_MANO: dict[str, str] = {
    "BlockModelResponse": (
        "NO es deuda: el tipo del frontend es el NORMALIZADO. El adaptador de "
        "`frontendApi` emite snake_case Y camelCase para que el visor no tenga "
        "que saber de qué endpoint vino el modelo. Generarlo sería declarar como "
        "contrato del backend algo que fabrica el cliente."
    ),
    "GravityImportPreviewResponse": "Diverge del backend a propósito (campos legacy camelCase). Dueña: Fase 11.",
    "GravityImportMetadata": "Idem: metadatos con alias camelCase heredados. Dueña: Fase 11.",
    "GeophysicsStatusResponse": "El frontend añade `metrics`/`heartbeat_at` del canal SSE. Dueña: Fase 11.",
    "ApplyCorrectionsResponse": "`default_factory` la vuelve opcional; el servicio siempre la emite. Fase 11.",
    "BoreholeSample": "Idem. Dueña: Fase 11.",
    "BoreholeSurvey": "Idem (`holes` opcional en el contrato, siempre presente en la respuesta). Fase 11.",
    "ConvergenceResponse": "Idem (`trials`, `lambda_selected`). Dueña: Fase 11.",
    "ConvergenceTrial": "Idem. Dueña: Fase 11.",
    "DataQualityScore": "Idem. Dueña: Fase 11.",
    "HistoryRun": "Idem. Dueña: Fase 11.",
    "MisfitResponse": "Idem. Dueña: Fase 11.",
    "MisfitStationData": "Idem. Dueña: Fase 11.",
    "MultimodalPlanResponse": "Idem. Dueña: Fase 11.",
    "ParseBoreholeCsvResponse": "Idem. Dueña: Fase 11.",
    "PercentileStats": "Idem. Dueña: Fase 11.",
    "RegionalScalePreflight": "Idem. Dueña: Fase 11.",
    "SpatialReadiness": "Idem. Dueña: Fase 11.",
    "VoxelData": (
        "Vive en `lib/terraQuantumGeology.ts`, que es código de RENDER: describe "
        "lo que el visor necesita para pintar, no lo que el motor calcula. "
        "Coinciden de nombre, no de propósito."
    ),
}


def _ficheros_web(*dirs: str):
    for d in dirs:
        base = WEB_ROOT / d
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.suffix not in (".ts", ".tsx") or "node_modules" in f.parts:
                continue
            yield f


@pytest.mark.skipif(not _web_disponible(), reason="terraquantum-web no está presente.")
def test_ningun_componente_supera_el_presupuesto_de_useState():
    """El criterio de aceptación de la Fase 10, medido y no prometido.

    `PrepPanel` llegó a tener 41 —el 24 % de todo el estado local del frontend en
    un archivo—, y la auditoría lo llamó *«el candidato número uno a una máquina
    de estados explícita»*. Este guard no defiende ese archivo concreto: mide
    TODOS, así que también caza el próximo componente que crezca hasta ahí.
    """
    excesos = []
    for f in _ficheros_web("componentes", "app", "lib", "store"):
        n = len(re.findall(r"useState[<(]", f.read_text(encoding="utf-8", errors="ignore")))
        if n > PRESUPUESTO_USE_STATE:
            excesos.append(f"{n:3d}  {f.relative_to(WEB_ROOT).as_posix()}")

    assert not excesos, (
        f"Componentes con más de {PRESUPUESTO_USE_STATE} `useState`. Con ese "
        "número de piezas independientes las combinaciones alcanzables dejan de "
        "poder razonarse, y los bugs pasan a ser «en cierta secuencia de clics "
        "queda inconsistente» (H-16, y H-29 fue uno).\n"
        "Arreglo: agrupar en `useReducer` por MOTIVO DE CAMBIO, con transiciones "
        "con nombre para los movimientos que tocan varias piezas.\n  "
        + "\n  ".join(sorted(excesos, reverse=True))
    )


@pytest.mark.skipif(not _web_disponible(), reason="terraquantum-web no está presente.")
def test_los_contratos_generados_no_se_reescriben_a_mano():
    """H-16 en su forma medible: nadie vuelve a copiar un esquema del backend.

    La regla mira CUERPOS, no nombres: `export type X = XContract;` es un alias
    (bien) y `export type X = { … }` es una copia (mal). Y la lista de deuda no
    puede crecer: si aparece un contrato copiado que no está declarado, esto cae.
    """
    generado = WEB_ROOT / "types" / "backend-contracts.generated.ts"
    assert generado.exists(), (
        "Falta el archivo de tipos generados. Corre "
        "`python scripts/ci/generate_frontend_types.py`."
    )
    nombres_generados = set(
        re.findall(r"^export type ([A-Za-z0-9_]+) =", generado.read_text(encoding="utf-8"), re.M)
    )

    copias: dict[str, list[str]] = {}
    for f in _ficheros_web("componentes", "app", "lib", "store", "workers", "types"):
        if f.name == generado.name:
            continue
        for m in _DECL_TS.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            nombre = m.group(1) or m.group(2)
            if nombre in nombres_generados:
                copias.setdefault(nombre, []).append(f.relative_to(WEB_ROOT).as_posix())

    nuevas = sorted(set(copias) - set(CONTRATOS_AUN_A_MANO))
    assert not nuevas, (
        "Contratos del backend copiados a mano en el frontend sin declararlo. "
        "Es la clase de bug de H-16: el backend cambia un campo y no falla nada "
        "hasta que el usuario ve un dato vacío.\n"
        "O se usa el tipo generado, o se añade a CONTRATOS_AUN_A_MANO con motivo "
        "y fase dueña:\n  "
        + "\n  ".join(f"{n} en {copias[n]}" for n in nuevas)
    )

    resueltas = sorted(set(CONTRATOS_AUN_A_MANO) - set(copias))
    assert not resueltas, (
        "Estos contratos YA no se declaran a mano: quítalos de "
        f"CONTRATOS_AUN_A_MANO, la excusa dejó de describir la realidad: {resueltas}"
    )


@pytest.mark.skipif(not _web_disponible(), reason="terraquantum-web no está presente.")
def test_el_frontend_consume_de_verdad_los_tipos_generados():
    """Que el archivo exista no basta: la Fase 9 aprendió que «tener el cable»
    y «estar enchufado» son cosas distintas. Un artefacto generado que nadie
    importa es exactamente el mismo defecto con otro disfraz."""
    importadores = [
        f.relative_to(WEB_ROOT).as_posix()
        for f in _ficheros_web("componentes", "lib", "store", "app")
        if "backend-contracts.generated" in f.read_text(encoding="utf-8", errors="ignore")
    ]
    assert len(importadores) >= 3, (
        "Casi nadie importa los tipos generados: el contrato existiría y el "
        f"frontend seguiría escribiéndolo a mano. Importadores: {importadores}"
    )


def test_los_endpoints_de_f7_declaran_esquema(app):
    """El deber concreto que la Fase 9 dejó escrito: *«los 5 endpoints de F7 no
    declaran `response_model`, así que su esquema OpenAPI va vacío ⇒ Fase 10»*.

    `/diagnostics/export` queda fuera con motivo: devuelve un ZIP, no JSON.
    Declararle un esquema JSON sería documentar una mentira.
    """
    esquema = app.openapi()

    def _tiene_esquema(ruta: str, metodo: str) -> bool:
        op = esquema["paths"][ruta][metodo]
        contenido = op.get("responses", {}).get("200", {}).get("content", {})
        return bool(contenido.get("application/json", {}).get("schema"))

    for ruta, metodo in (("/license/status", "get"), ("/license/activate", "post"),
                         ("/diagnostics/manifest", "get"), ("/system/connectivity", "get")):
        assert _tiene_esquema(ruta, metodo), (
            f"{metodo.upper()} {ruta} volvió a quedarse sin `response_model`: su "
            "esquema OpenAPI va vacío y no hay tipo que generar (H-10 → Fase 10)."
        )

    export = esquema["paths"]["/diagnostics/export"]["get"]["responses"]["200"]
    contenido = export.get("content", {})
    assert "application/zip" in contenido, (
        "`/diagnostics/export` devuelve un ZIP y su OpenAPI tiene que decirlo. "
        "Por defecto FastAPI declara `application/json` para toda ruta sin "
        "`response_class`, y entonces el generador de tipos ve una respuesta "
        "JSON donde hay un binario."
    )
    assert not contenido.get("application/json"), (
        "`/diagnostics/export` volvió a declararse como JSON: es un ZIP."
    )
