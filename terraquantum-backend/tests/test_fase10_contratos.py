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
