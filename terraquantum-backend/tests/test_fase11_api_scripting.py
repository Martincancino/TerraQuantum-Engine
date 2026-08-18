"""FASE 11 (auditoría 06 §10) — La API de scripting, MEDIDA.

La fase se justifica con una frase del informe 04: *«procesa estos 12 surveys con
la misma configuración»*. Así que aquí hay un test que procesa doce.

Y con una promesa de método: *«la propia API se vuelve el mejor test de
integración del proyecto: un script que corra los datasets canónicos de punta a
punta es simultáneamente el ejemplo de la documentación y un test E2E»*. Por eso
esta suite **ejecuta los ejemplos** en vez de reimplementarlos — un ejemplo que
nadie corre es documentación que caduca en silencio, que es el defecto que la
Fase 9 encontró cuatro veces.

Lo que se mide, en orden:
  1. el camino dorado completo desde el CSV crudo de un Excel chileno;
  2. que la API y la interfaz recorren EL MISMO código (anti-H-29);
  3. que el lote de doce pasa — y por qué no pasaba;
  4. que la superficie publicada está ejercitada y documentada;
  5. que las rutas que la Fase 9 declaró «scripting» tienen consumidor;
  6. dos defectos del backend que esta API destapó, pinchados donde están.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import terraquantum as tq  # noqa: E402

FIXTURES = BACKEND_ROOT / "tests" / "fixtures" / "csv_reales"
#: El CSV que exporta un Excel chileno: 2 líneas de preámbulo, separador ';',
#: coma decimal y cabeceras en español. Dato real (Miller et al. 2017).
LDM_CRUDO = FIXTURES / "LdM_gravimetria_CRUDO_usuario.csv"
#: Malla mínima que cabe en la matriz de LdM. La profundidad va con la malla
#: (ver `docs/08_API_SCRIPTING.md` §5): fijar una sin la otra es un rechazo.
MALLA_MINIMA = {"utm_zone": "19S", "nx": 5, "ny": 5, "nz": 4, "depth": 900}

#: Símbolos de `__all__` que se ejercitan indirectamente y dónde. Una entrada
#: aquí es una excusa ESCRITA, no un hueco: el test de cobertura la exige.
EJERCITADOS_INDIRECTAMENTE = {
    "invert_field_csv": "test_invert_field_csv_usa_el_canal_de_estado_canonico",
    "estimate_depth": "test_estimate_depth_responde_sin_invertir",
    "admin": "test_admin_exige_clave_maestra_y_no_finge",
    "backend_root": "usado por todos los tests para localizar fixtures",
    "invert_direct": "test_invert_direct_es_la_entrada_al_motor_sin_paquete",
    "ESTADOS_TERMINALES": "test_wait_no_cancela_ni_miente_con_un_estado_terminal",
    "ESTADO_OK": "test_camino_dorado_completo_desde_csv_crudo",
    "set_default_session": "test_la_sesion_por_defecto_es_sustituible",
    "RunTimeout": "test_wait_no_cancela_ni_miente_con_un_estado_terminal",
}


def _cadenas_de_codigo(paquete: pathlib.Path) -> set:
    """Literales de cadena que son CÓDIGO, sin docstrings ni comentarios.

    Un endpoint citado en un docstring no le da a nadie forma de llegar a él —
    es exactamente la distinción que hace el guard de la Fase 9 al excluir el
    archivo de tipos generados.
    """
    import ast

    salida: set = set()
    for archivo in sorted(paquete.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        docstrings = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                cuerpo = getattr(nodo, "body", None) or []
                if (cuerpo and isinstance(cuerpo[0], ast.Expr)
                        and isinstance(cuerpo[0].value, ast.Constant)
                        and isinstance(cuerpo[0].value.value, str)):
                    docstrings.add(id(cuerpo[0].value))
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                    and id(nodo) not in docstrings):
                salida.add(nodo.value)
    return salida


@pytest.fixture(scope="module")
def sesion():
    """Una sola sesión para todo el módulo: montar la app cuesta ~3 s."""
    s = tq.Session()
    yield s
    s.close()


@pytest.fixture(scope="module")
def corrida_ldm(sesion):
    """UNA corrida real reutilizada por los tests de lectura (≈8 s)."""
    paquete = tq.enrich(gravity=LDM_CRUDO, config=MALLA_MINIMA, enable_dem=False,
                        session=sesion)
    return paquete, tq.run_inversion(
        paquete, project_id="f11_suite", run_id="dorado", session=sesion
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. El criterio de aceptación de la fase
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.slow
def test_camino_dorado_completo_desde_csv_crudo(corrida_ldm):
    """CSV crudo de Excel-ES → modelo 3D, informe y entregable. Sin interfaz.

    Es el criterio de aceptación literal de la fase: *«un script de ~20 líneas
    reproduce el camino dorado completo sobre Laguna del Maule sin tocar la
    UI»*. Aquí se comprueba que **llega hasta el final**, no que la física sea
    buena: eso es la suite F9, que es otra pregunta.
    """
    paquete, corrida = corrida_ldm

    assert paquete.n_stations == 191, "el dato real de LdM tiene 191 estaciones"
    assert paquete.route == "gravity_only"
    assert paquete.warnings, (
        "un CSV con preámbulo, coma decimal y sin columna de unidad TIENE que "
        "producir avisos: si llega limpio es que algo se comió la degradación"
    )
    assert corrida.status == tq.ESTADO_OK
    assert corrida.chi2 is not None, "una corrida 'done' publica su χ²"

    # La trilogía honesta (B1/B2/B3) llega entera al script, no sólo al JSON.
    assert corrida.verdict and corrida.verdict.get("level")
    assert corrida.best_target and "x_m" in corrida.best_target
    assert corrida.depth_resolution and "deep_mass_fraction" in corrida.depth_resolution

    # Y el modelo 3D existe de verdad: el parquet es la fuente, no la vista.
    marco = corrida.block_model_frame()
    assert len(marco) == 5 * 5 * 4, "el modelo persistido tiene las celdas del core"
    assert "density" in marco.columns


@pytest.mark.slow
def test_los_entregables_se_escriben_y_no_estan_vacios(corrida_ldm, tmp_path):
    """El gabinete: paquete reproducible + ZIP + CSV minero + informe."""
    paquete, corrida = corrida_ldm

    ruta_pkg = paquete.save(tmp_path / "corrida.tqpkg")
    releido = tq.Package.from_file(ruta_pkg)
    assert releido.text == paquete.text, "el paquete guardado ES el paquete"
    assert releido.config["nx"] == 5, "y su configuración se relee con el parser oficial"

    for escritor in ("save_bundle", "save_block_model_csv", "save_report"):
        destino = getattr(corrida, escritor)(tmp_path)
        assert destino.is_file() and destino.stat().st_size > 500, (
            f"{escritor} escribió un archivo vacío o inexistente"
        )


@pytest.mark.slow
def test_las_lecturas_de_la_corrida_hablan_con_el_backend(corrida_ldm):
    """`misfit`, `convergence`, `block_model`, `profile`, `isosurface`, `section`.

    Ninguna calcula nada: todas preguntan. El test existe para que una ruta que
    cambie de forma se note aquí y no en el script de un consultor.
    """
    _, corrida = corrida_ldm

    desajuste = corrida.misfit()
    assert desajuste["n_stations"] == 191

    convergencia = corrida.convergence()
    assert "available" in convergencia, "el contrato incluye decir que NO hay datos"

    modelo = corrida.block_model(limit=10)
    assert len(modelo["cells"]) == 10

    perfil = corrida.profile(x0_m=0.0, z0_m=0.0, x1_m=2000.0, z1_m=2000.0)
    assert "profile_voxels" in perfil

    assert corrida.isosurface()["n_levels"] >= 1
    assert isinstance(corrida.section(axis="y", position=0.0), dict)

    estado = corrida.status_now()
    assert estado["status"] == tq.ESTADO_OK


# ═════════════════════════════════════════════════════════════════════════════
# 2. Anti-H-29: la API y la interfaz recorren el MISMO código
# ═════════════════════════════════════════════════════════════════════════════
def test_la_api_no_es_una_segunda_implementacion_del_camino_dorado(sesion):
    """El payload de la API es idéntico al de llamar al endpoint a mano.

    Éste es EL test de la decisión de diseño de la fase. H-29 fue un movimiento
    multi-campo escrito a mano en dos sitios que divergieron; una API de
    scripting que reconstruyera la orquestación de `load-package` sería el mismo
    error con otro disfraz. Aquí se comprueba que no hay tal reconstrucción:
    mismo endpoint, mismo cuerpo, byte a byte.
    """
    from fastapi.testclient import TestClient

    import main

    crudo = LDM_CRUDO.read_bytes()
    config = json.dumps(MALLA_MINIMA)

    por_la_api = tq.enrich(gravity=LDM_CRUDO, config=MALLA_MINIMA,
                           enable_dem=False, session=sesion)

    cliente = TestClient(main.app)
    a_mano = cliente.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": (LDM_CRUDO.name, crudo, "text/csv")},
        data={"config_json": config},
        params={"data_type": "gravity", "strict": "false",
                "allow_g_raw": "true", "enable_dem": "false"},
    ).json()

    assert por_la_api.text == a_mano["package_text"], (
        "El paquete de la API difiere del que produce el endpoint. O la API "
        "está construyendo algo por su cuenta, o traduce mal los parámetros. "
        "Las dos cosas son la divergencia que esta fase viene a impedir."
    )
    assert por_la_api.warnings == list(a_mano["warnings"])
    assert por_la_api.plan == a_mano["plan"]

    # CONTROL: que dos payloads iguales salgan iguales no prueba nada si la
    # comparación no sabe distinguirlos. Con OTRA configuración el paquete tiene
    # que cambiar — si no, este test estaría comparando algo que no depende de
    # lo que la API transporta, que es como pasan los gates que no defienden
    # nada (la lección del gate de física de la Fase 3).
    otra_malla = dict(MALLA_MINIMA, nx=7, ny=7)
    distinto = cliente.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": (LDM_CRUDO.name, crudo, "text/csv")},
        data={"config_json": json.dumps(otra_malla)},
        params={"data_type": "gravity", "strict": "false",
                "allow_g_raw": "true", "enable_dem": "false"},
    ).json()
    assert distinto["package_text"] != por_la_api.text, (
        "la comparación no discrimina: cambiar la malla no cambió el paquete"
    )


def test_la_api_no_declara_defaults_de_fisica_propios():
    """Cero números de física en la capa de scripting.

    La regla del repositorio es que la física vive SOLO en el backend. Una API
    que copiara `density_max=5.5` o `reduction_density=2.67` crearía un segundo
    sitio donde ese número puede quedarse viejo. Los únicos valores permitidos
    aquí son los de transporte (plazos, reintentos, tamaños de página) y los que
    el propio endpoint exige en su firma.
    """
    prohibidos = re.compile(
        r"\b(density_min|density_max|lambda_mag|alpha_spatial|cutoff_radius|"
        r"block_size|padding_kappa|anchor_kappa|depth_beta|noise_floor)\s*[:=]\s*"
        r"[0-9]",
    )
    delitos = []
    for archivo in sorted((BACKEND_ROOT / "terraquantum").glob("*.py")):
        for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if linea.lstrip().startswith("#"):
                continue          # los comentarios CITAN valores medidos: eso vale
            if prohibidos.search(linea):
                delitos.append(f"{archivo.name}:{n}  {linea.strip()[:90]}")
    assert not delitos, (
        "La API de scripting está fijando parámetros de FÍSICA. Tienen que venir "
        "del backend (o del usuario), nunca de esta capa:\n  " + "\n  ".join(delitos)
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. El lote de doce — la frase que justifica la fase
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.slow
def test_doce_surveys_con_la_misma_configuracion(sesion, tmp_path):
    """*«Procesa estos 12 surveys con la misma configuración.»*

    Es la justificación literal de la fase en el informe, así que es un test.

    Y es el que destapó el hallazgo: por el camino natural esto **falla en el
    survey número 11** con `429 Rate limit exceeded: 10 per 1 minute`, porque
    `enrich-package` y `load-package` limitan a 10/minuto por origen y en
    proceso todas las llamadas comparten clave. Se comprueba abajo, aparte.
    """
    surveys = [{"name": f"s{i:02d}", "gravity": LDM_CRUDO} for i in range(1, 13)]
    corridas = tq.batch(surveys, config=MALLA_MINIMA, project_prefix="f11_lote",
                        session=sesion, enable_dem=False)

    assert len(corridas) == 12
    fallos = [c for c in corridas if isinstance(c, Exception)]
    assert not fallos, (
        "El lote de doce no llegó entero. Si el motivo es 429, la política de "
        f"rate-limit dejó de proteger el caso de uso principal:\n  {fallos[:3]}"
    )
    assert all(c.status == tq.ESTADO_OK for c in corridas)
    assert len({c.run_id for c in corridas}) == 12, "cada survey, su propia corrida"


def test_el_limite_de_peticiones_muerde_en_la_llamada_11(sesion):
    """El hallazgo, medido y fijado: 10 por minuto, y salta en la 11.ª.

    Con `rate_limit="raise"` la API no toca el limitador: es el modo honesto
    para MEDIRLO. Se mide sobre `enrich-package`, que es el primer paso del
    lote — o sea, el límite que de verdad estrangula el caso de uso que
    justifica la fase. Si alguien sube o baja el límite del backend, este test
    lo dice, y con él la justificación de que el default en proceso sea
    `"reset"`.
    """
    s = tq.Session(rate_limit="raise")
    exitosas = 0
    with pytest.raises(tq.RateLimited) as capturado:
        for _ in range(14):
            tq.enrich(gravity=LDM_CRUDO, config=MALLA_MINIMA, enable_dem=False,
                      session=s)
            exitosas += 1
    s.close()

    assert exitosas == 10, (
        "enrich-package declara 10/minuto y el lote del informe son DOCE: si "
        f"este número cambió, cambió el contrato de ritmo (pasaron {exitosas})"
    )
    assert capturado.value.code == "RATE_LIMITED", (
        "el código tiene que ser estable: el texto de slowapi lleva el número "
        "del límite dentro y cambia cuando cambia el límite"
    )
    assert capturado.value.http_status == 429
    assert "Retry-After" not in str(capturado.value.details), (
        "si el backend empezó a mandar Retry-After, el backoff CIEGO de la "
        "política 'wait' ya no hace falta: se puede leer la espera"
    )


def test_la_politica_reset_desarma_el_limite_solo_en_proceso(sesion):
    """`"reset"` es el default EN PROCESO y hay que poder justificarlo.

    Ahí el limitador no protege ningún perímetro: no hay red, y el «cliente
    remoto» es el propio script. Contra un backend remoto sí protege algo, y por
    eso `_reset_rate_limit` devuelve False y la política degrada a esperar.
    """
    en_proceso = tq.Session(rate_limit="reset")
    assert en_proceso.in_process and en_proceso.rate_limit == "reset"
    assert en_proceso._reset_rate_limit() is True

    for _ in range(12):
        tq.analyze_columns(LDM_CRUDO, session=en_proceso)      # 12 > 10, sin 429
    en_proceso.close()

    remota = tq.Session(base_url="http://127.0.0.1:9", rate_limit="reset")
    assert remota.rate_limit == "reset"
    assert remota._reset_rate_limit() is False, (
        "contra un backend remoto el contador vive en el OTRO proceso: decir "
        "que se reseteó sería exactamente el fallback que finge"
    )

    # `"wait"` respeta el límite ajeno esperando. Aquí sólo se comprueba que la
    # política se acepta y no estorba: su espera real son 60 s de reloj y un
    # test no puede pagarlos sin volverse inútil (queda medida en docs/08 §5).
    esperando = tq.Session(rate_limit="wait")
    assert esperando.rate_limit == "wait" and esperando.rate_limit_max_wait_s > 0
    tq.analyze_columns(LDM_CRUDO, session=esperando)
    esperando.close()


def test_toda_politica_de_rate_limit_declarada_esta_ejercitada():
    """Patrón de `test_fase1_literal_dispatch`: un valor nuevo sin ejercitar
    rompe la suite en vez de quedarse sin probar durante dos auditorías."""
    fuente = (pathlib.Path(__file__)).read_text(encoding="utf-8")
    sin_ejercitar = [
        p for p in tq.RATE_LIMIT_POLICIES if f'rate_limit="{p}"' not in fuente
    ]
    assert not sin_ejercitar, f"políticas declaradas y no ejercitadas: {sin_ejercitar}"

    with pytest.raises(ValueError):
        tq.Session(rate_limit="loquesea")

    remota = tq.Session(base_url="http://127.0.0.1:9")
    assert remota.rate_limit == "wait", "el default remoto respeta el límite ajeno"
    assert tq.Session().rate_limit == "reset", "el default en proceso, no"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Superficie publicada: versión, promesa escrita y cobertura
# ═════════════════════════════════════════════════════════════════════════════
def test_la_version_esta_declarada_y_la_promesa_escrita_existe():
    """Criterio de aceptación de la fase: *«La API tiene versión declarada y una
    promesa de estabilidad escrita»*. Las dos cosas, y coincidiendo."""
    assert tq.API_VERSION == "0", "publicar v1 es un compromiso; hoy es v0"

    documento = REPO_ROOT / tq.STABILITY_DOC
    assert documento.is_file(), (
        f"{tq.STABILITY_DOC} no existe: la promesa de estabilidad es un "
        "criterio de aceptación, no un extra"
    )
    texto = documento.read_text(encoding="utf-8")
    assert f"**v0**" in texto or "· **v0**" in texto, "el documento declara la versión"
    for obligatorio in ("Qué promete la v0", "Qué haría falta para llamarla v1"):
        assert obligatorio in texto, f"a la promesa le falta la sección «{obligatorio}»"


def test_todo_simbolo_publico_esta_ejercitado_o_declarado():
    """`__all__` es la superficie; ejercitarla entera es lo que la hace real.

    La Fase 9 aprendió que «tener el cable» y «estar enchufado» son distintos.
    Un símbolo exportado que ninguna prueba toca es una promesa sin comprobar.
    """
    fuente = (pathlib.Path(__file__)).read_text(encoding="utf-8")
    sin_tocar = []
    for simbolo in tq.__all__:
        if simbolo in EJERCITADOS_INDIRECTAMENTE:
            continue
        if not re.search(rf"\btq\.{re.escape(simbolo)}\b", fuente):
            sin_tocar.append(simbolo)
    assert not sin_tocar, (
        "Símbolos exportados que ninguna prueba usa. O se ejercitan, o se "
        f"declaran en EJERCITADOS_INDIRECTAMENTE con dónde: {sin_tocar}"
    )

    caducadas = [s for s in EJERCITADOS_INDIRECTAMENTE if s not in tq.__all__]
    assert not caducadas, (
        "La excusa dejó de describir la realidad: estos símbolos ya no se "
        f"exportan y siguen en la lista: {caducadas}"
    )


def test_las_dos_fisicas_declaradas_se_ejercitan(sesion):
    """`DATA_TYPES` = ('gravity', 'magnetic'), y las dos se recorren de verdad.

    La magnética se comprueba en el plan de columnas (barato) y en el recorrido
    de los canónicos (`examples/02`, más abajo), no aquí, para no invertir dos
    veces en la suite rápida.
    """
    assert tq.DATA_TYPES == ("gravity", "magnetic")
    for fisica in tq.DATA_TYPES:
        plan = tq.analyze_columns(LDM_CRUDO, data_type=fisica, session=sesion)
        assert isinstance(plan, tq.ColumnPlan)
    with pytest.raises(ValueError):
        tq.analyze_columns(LDM_CRUDO, data_type="telepatia", session=sesion)


def test_la_sesion_por_defecto_es_sustituible():
    """`set_default_session` existe para que un script hable con un backend
    remoto sin pasar `session=` en cada llamada."""
    previa = tq.default_session()
    propia = tq.Session()
    tq.set_default_session(propia)
    try:
        assert tq.default_session() is propia
    finally:
        tq.set_default_session(previa)
    assert tq.default_session() is previa


# ═════════════════════════════════════════════════════════════════════════════
# 5. Un fallo nunca es un valor plausible
# ═════════════════════════════════════════════════════════════════════════════
def test_un_csv_sin_roles_reconocibles_PREGUNTA_en_vez_de_fallar(sesion):
    """`needs_mapping` es el Pilar 1 funcionando, no un error del archivo.

    El backend contesta 200 SIN paquete; devolver eso como resultado sería el
    valor plausible que el proyecto prohíbe. Sube `NeedsColumnMapping` con el
    plan adjunto, que es lo que hace falta para responder.
    """
    anonimo = "a;b;c\n1;2;3\n4;5;6\n7;8;9\n10;11;12\n13;14;15\n"
    with pytest.raises(tq.NeedsColumnMapping) as capturado:
        tq.enrich(gravity=anonimo, config=MALLA_MINIMA, enable_dem=False, session=sesion)

    pregunta = capturado.value
    assert pregunta.missing_required, "una pregunta sin qué falta no es una pregunta"
    assert pregunta.raw_columns == ["a", "b", "c"]
    assert pregunta.suggested_action
    assert isinstance(pregunta, tq.TerraquantumError), "sigue siendo un error del árbol"


def test_solo_sondajes_no_define_una_inversion(sesion):
    """Pilar 6: los sondajes ANCLAN, no definen. Error catalogado, con acción."""
    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.enrich(boreholes=[{"x_m": 0.0, "z_m": 0.0, "y_from_m": 0.0,
                              "y_to_m": 10.0, "density_t_m3": 3.0}], session=sesion)
    assert capturado.value.code == "INSUFFICIENT_DATA"
    assert capturado.value.suggested_action


def test_una_ruta_que_no_existe_se_dice_antes_de_llamar_al_backend(sesion):
    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.enrich(gravity="no_existe_en_ningun_disco.csv", session=sesion)
    assert capturado.value.code == "CSV_FILE_NOT_FOUND"

    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.run_inversion("no_existe_ningun_paquete.tqpkg", session=sesion)
    assert capturado.value.code == "PACKAGE_FILE_NOT_FOUND"


def test_wait_no_cancela_ni_miente_con_un_estado_terminal(sesion):
    """Una corrida que no existe no se convierte en un `done` optimista, y un
    plazo agotado no aborta el trabajo del backend (`RunTimeout` lo dice)."""
    fantasma = tq.open_run("f11_no_existe", "jamas", session=sesion)
    assert isinstance(fantasma, tq.Run)
    assert fantasma.status != tq.ESTADO_OK
    assert tq.ESTADOS_TERMINALES[0] == tq.ESTADO_OK
    assert fantasma.verdict is None and fantasma.best_target is None

    assert issubclass(tq.RunTimeout, tq.TerraquantumError)
    assert issubclass(tq.InversionFailed, tq.TerraquantumError)


@pytest.mark.slow
def test_H_F11_3_una_corrida_sincrona_no_entra_en_el_historial(sesion, corrida_ldm):
    """🟠 Caracterización: el camino SÍNCRONO no escribe en el historial SQLite.

    Y el síncrono es el que el propio endpoint recomienda para scripts, y el
    default de `run_inversion`. Consecuencia para el usuario: **un consultor
    procesa doce surveys desde un script y la pantalla «Historial» no muestra
    ninguno.** El modelo está en disco y se re-abre por id, pero el listado que
    la interfaz consume sale vacío.

    La causa está a la vista: `submit_package_inversion` (cola) llama a
    `project_store.record_run`; la rama `sync=true` de `load-package` sólo llama
    a `update_run_status`, que escribe `schedule.json` y no la base.

    No se arregla desde aquí: que el cliente escribiera el historial sería la
    API fabricando una persistencia que el backend no hizo. Se mide, se declara
    (docs/08 §6) y `run_inversion` documenta el compromiso: `wait=False` sí pasa
    por la cola —y sí queda en el historial— a cambio de exigir el guard de
    `__main__`.
    """
    _, sincrona = corrida_ldm

    historial = tq.list_runs(project_id=sincrona.project_id, session=sesion)
    assert not any(r.get("run_id") == sincrona.run_id for r in historial), (
        "¡Arreglado! la rama síncrona ya registra en el historial. Actualiza "
        "este test, docs/08 §6 y el compromiso escrito en run_inversion."
    )

    # Y sin embargo el modelo existe y se re-abre: el hueco es el LISTADO.
    reabierta = tq.open_run(sincrona.project_id, sincrona.run_id, session=sesion)
    assert reabierta.status == tq.ESTADO_OK
    assert reabierta.chi2 == sincrona.chi2, "el informe releído es el mismo informe"


@pytest.mark.slow
def test_la_cola_si_registra_en_el_historial(sesion):
    """El contraste que convierte H-F11-3 en un hallazgo y no en una sospecha.

    Mismo paquete, misma malla; lo único que cambia es `wait=False`, que encola
    en un worker de proceso. Esa corrida SÍ aparece en el historial con su
    estado, su ruta y sus tiempos.
    """
    paquete = tq.enrich(gravity=LDM_CRUDO, config=MALLA_MINIMA, enable_dem=False,
                        session=sesion)
    encolada = tq.run_inversion(paquete, project_id="f11_cola", run_id="rc",
                                wait=False, session=sesion)
    assert encolada.status == "queued"
    assert encolada.budget.get("voxel_count") == 5 * 5 * 4, (
        "el presupuesto previo de vóxeles viaja al script antes de invertir"
    )
    encolada.wait(timeout_s=600, poll_s=1.0)

    historial = tq.list_runs(project_id="f11_cola", session=sesion)
    registrada = [r for r in historial if r.get("run_id") == "rc"]
    assert registrada, f"la corrida encolada tampoco quedó registrada: {historial}"
    assert registrada[0]["status"] == "done" and registrada[0]["source"] == "package"


def test_admin_exige_clave_maestra_y_no_finge(sesion, monkeypatch):
    """La administración de claves no inventa un éxito cuando no hay maestra."""
    monkeypatch.delenv("TQ_MASTER_KEY", raising=False)
    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.admin.create_api_key("lote-nocturno", session=sesion)
    assert capturado.value.code == "MASTER_KEY_MISSING"
    assert "TQ_MASTER_KEY" in capturado.value.suggested_action


def _payload_directo(**extra):
    """Payload mínimo de `GeophysicsInvertInputV2` (mismo molde que
    `tests/test_v2_inversion.py`: 12 observaciones sintéticas en m/s²)."""
    base = dict(
        project_id="f11_directo", run_id="d1",
        depth=500, nir=50, fe=50, region="norte_chile",
        nx=8, ny=8, nz=8, block_size=100, cutoff_radius=800.0,
        lambda_mag=3.0, alpha_spatial=1.0,
        gravity_type="complete_bouguer_anomaly",
        observations=[
            {"x_m": float(i * 100), "y_m": float(i * 5), "z_m": float(i * 100),
             "g": float(-1.2e-5 + i * 1e-7)}
            for i in range(12)
        ],
    )
    base.update(extra)
    return base


@pytest.mark.slow
def test_invert_direct_es_la_entrada_al_motor_sin_paquete(sesion):
    """`/v2/geophysics-invert`: la tercera ruta que la Fase 9 declaró de scripting.

    Es la vía del experto que ya decidió la malla y quiere repetir la corrida
    cambiando UN parámetro (barrer λ, comparar regularizaciones). Sin CSV, sin
    enriquecimiento y sin auto-grid.
    """
    corrida = tq.invert_direct(_payload_directo(), session=sesion)
    assert corrida.status == tq.ESTADO_OK
    assert corrida.project_id == "f11_directo"


def test_invert_direct_no_disfraza_la_estrategia_de_lambda_que_no_existe(sesion):
    """H-37b (Fase 1) sigue cerrado, y ahora también desde un script.

    `lambda_strategy="lcurve"` prometía la esquina de la L-curve y caía en la
    misma rama que `chi2`. Se rechaza en voz alta; la API transporta ese rechazo
    con su código en vez de dejar creer que se hizo otra cosa.
    """
    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.invert_direct(_payload_directo(lambda_strategy="lcurve", run_id="d_lcurve"),
                         session=sesion)
    assert capturado.value.code == "LAMBDA_STRATEGY_UNAVAILABLE"


@pytest.mark.slow
def test_estimate_depth_responde_sin_invertir(sesion):
    """Euler + espectro: el chequeo cruzado independiente de la inversión."""
    filas = tq.parse_rows(LDM_CRUDO, session=sesion)
    assert len(filas) == 191
    estaciones = [
        {"x_m": float(f["Este_UTM"]), "y_m": float(f["Norte_UTM"]),
         "gravity_mgal": float(f["Anom_Bouguer_mGal"])}
        for f in filas
    ]
    salida = tq.estimate_depth(estaciones, value_column="gravity_mgal",
                               structural_index=2.0, session=sesion)
    assert "euler" in salida and "spectrum" in salida


@pytest.mark.slow
def test_invert_field_csv_usa_el_canal_de_estado_canonico(sesion):
    """La ruta de campo contesta `status: "success"`, vocabulario distinto del de
    la máquina de estados. Traducirlo sería inventar una equivalencia: la API
    pregunta al canal canónico, que es el que mira la interfaz."""
    corrida = tq.invert_field_csv(
        LDM_CRUDO, project_id="f11_campo", run_id="rc1",
        nx=5, ny=5, nz=4, depth=900, apply_terrain=False, session=sesion,
    )
    assert corrida.status in tq.ESTADOS_TERMINALES, (
        f"el estado tiene que venir de la máquina de estados, no de la ruta "
        f"(salió {corrida.status!r})"
    )
    assert corrida.status == tq.ESTADO_OK


# ═════════════════════════════════════════════════════════════════════════════
# 6. La deuda heredada de la Fase 9: las rutas «de scripting»
# ═════════════════════════════════════════════════════════════════════════════
def test_las_rutas_declaradas_de_scripting_tienen_consumidor_de_scripting():
    """La Fase 9 toleró 10 rutas sin camino de usuario. Seis llevaban escrito
    «Dueña: Fase 11», y dos de ellas se justificaban diciendo que son *«la
    superficie natural del scripting»* y que se conservan *«por compatibilidad
    de scripts»*.

    Eso era una PROMESA. Este test la convierte en una medición: si la excusa
    dice Fase 11, el paquete `terraquantum` tiene que llamar a esa ruta — o la
    excusa tiene que decir otra cosa, con la verdad medida dentro.

    Se miran **cadenas de código, no texto**: los docstrings de esta API citan
    cada endpoint que envuelven, y contarlos valdría como consumidor. Sería el
    mismo defecto que la Fase 6 encontró (un guard que una allowlist de cadenas
    anulaba) y que la Fase 10 evitó mirando CUERPOS y no nombres. Verificado por
    mutación: renombrar la constante de la ruta pone esto en rojo aunque el
    docstring siga nombrándola.
    """
    from tests.test_fase9_camino_de_usuario import RUTAS_SIN_UI_TOLERADAS

    codigo = "\n".join(sorted(_cadenas_de_codigo(BACKEND_ROOT / "terraquantum")))
    incumplidas = []
    for ruta, motivo in RUTAS_SIN_UI_TOLERADAS.items():
        if "Fase 11" not in motivo:
            continue
        if ruta.rstrip("/") not in codigo:
            incumplidas.append(f"{ruta} — «{motivo[:80]}…»")

    assert not incumplidas, (
        "Rutas cuya excusa nombra a la Fase 11 como dueña y que la API de "
        "scripting NO usa. Una excusa que nadie cumple es peor que no tenerla: "
        "o se cablean, o se reescribe el motivo con lo que de verdad las "
        "mantiene vivas:\n  " + "\n  ".join(incumplidas)
    )


def test_la_ruta_v1_de_invertir_la_mantienen_los_tests_y_un_arnes_interno():
    """Corrección medida a una excusa de la Fase 9.

    `/gravity-import/invert` se toleró diciendo que *«se conserva por
    compatibilidad de scripts»*, lo que sugiere scripts de usuario. Medido, lo
    que la mantiene viva es otra cosa:

      · **13 tests de contrato** que la ejercitan (Helmert, sondajes,
        readiness espacial, escala regional, errores de runtime…);
      · **un arnés interno**, `scripts/validation/fase8_byte_identity.py`, que
        la usa para comprobar la identidad byte a byte del refactor de la Fase 8;
      · y **ningún script de consultor**: la API de esta fase invierte por el
        paquete, que es el camino reproducible.

    La excusa no era falsa, pero nombraba al dueño equivocado. Este test fija
    los tres hechos: si desaparecen los tests Y el arnés, ya no la sostiene
    nada y toca borrarla.
    """
    marca = '"/gravity-import/invert"'
    tests_de_contrato = sorted(
        f.name for f in (BACKEND_ROOT / "tests").glob("test_*.py")
        if marca in f.read_text(encoding="utf-8", errors="ignore")
    )
    assert len(tests_de_contrato) >= 10, (
        f"la cobertura de contrato de la ruta v1 se desplomó: {tests_de_contrato}"
    )

    arneses = sorted(
        f.name for f in (BACKEND_ROOT / "scripts").rglob("*.py")
        if marca in f.read_text(encoding="utf-8", errors="ignore")
        and not f.name.startswith("test_")
        and "generate_frontend_types" not in f.name   # sólo la NOMBRA, no la llama
    )
    assert arneses == ["fase8_byte_identity.py"], (
        "El conjunto de arneses que llaman a la ruta v1 cambió. Si quedó vacío, "
        "la excusa de la Fase 9 dejó de ser cierta por completo; si creció, "
        f"actualiza el motivo: {arneses}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 7. Caracterización: dos defectos del backend que esta API destapó
#    Estos tests NO comprueban que algo funcione: fijan lo que HOY pasa, para
#    que el día que alguien lo arregle se entere aquí. Ver docs/08 §6.
# ═════════════════════════════════════════════════════════════════════════════
def test_H_F11_1_un_csv_XYZ_se_automapea_mal_y_sin_avisar(sesion):
    """🔴 El northing va al rol PROFUNDIDAD y nadie pregunta (Raglan).

    `X,Y,Z` es el encabezado de los DOS benchmarks magnéticos publicados. La
    guarda `northing_in_depth_slot` existe pero exige `> 1e5 m`, así que caza a
    DO-27 (northing 7,1e6) y **no a Raglan** (4,1e4, coordenadas locales).
    """
    raglan = REPO_ROOT / "Raglan_Magnetic" / "Raglan_Magnetic_TMI_nT.csv"
    if not raglan.is_file():
        pytest.skip("el dataset Raglan no está en este árbol")

    plan = tq.analyze_columns(raglan, data_type="magnetic", session=sesion)
    assert plan.roles["depth"] == "Y" and plan.roles["y"] == "Z", (
        "¡Arreglado! `X,Y,Z` ya no manda el northing al rol profundidad. "
        "Actualiza este test, docs/08 §6 y el column_map de examples/02."
    )
    assert not plan.needs_mapping and not plan.needs_confirmation, (
        "¡Arreglado! el mapeo de Raglan ya PREGUNTA en vez de aceptar en silencio."
    )
    assert not plan.suspicions, "¡Arreglado! la heurística de rango ya sospecha aquí."

    # Y el contraste que lo prueba: el MISMO encabezado, con northing UTM, sí avisa.
    do27 = REPO_ROOT / "DO-27_Kimberlite" / "DO27_Magnetic_TMI_nT.csv"
    if do27.is_file():
        plan_do27 = tq.analyze_columns(do27, data_type="magnetic", session=sesion)
        assert plan_do27.needs_confirmation, (
            "DO-27 sí cruza el umbral de 1e5: si dejó de avisar, la guarda se rompió"
        )
        assert any(s.get("kind") == "northing_in_depth_slot"
                   for s in (plan_do27.suspicions or []))


@pytest.mark.slow
def test_H_F11_2_el_autogrid_puede_proponer_una_malla_que_el_esquema_rechaza(sesion):
    """🟠 `nx=82` propuesto, `nx ≤ 80` exigido → error CRUDO de Pydantic.

    Con el mapeo ya correcto. La asimetría está en `load-package::_eff_dim`:
    acota el valor del USUARIO a 1..80 y devuelve el AUTOMÁTICO sin acotar.
    """
    raglan = REPO_ROOT / "Raglan_Magnetic" / "Raglan_Magnetic_TMI_nT.csv"
    if not raglan.is_file():
        pytest.skip("el dataset Raglan no está en este árbol")

    mapeo = {"x": "X", "y": "Y", "elevation": "Z",
             "magnetic_value": "TMI_nT", "sigma": "Std_nT"}
    paquete = tq.enrich(magnetic=raglan, column_map=mapeo, config={},
                        enable_dem=False, session=sesion)
    with pytest.raises(tq.TerraquantumError) as capturado:
        tq.run_inversion(paquete, project_id="f11_h2", run_id="auto", session=sesion)

    error = capturado.value
    assert error.code == "PACKAGE_INPUT_VALIDATION", (
        "¡Arreglado! el auto-grid ya no propone una malla que el esquema rechaza. "
        "Actualiza este test y docs/08 §6."
    )
    campos = {tuple(e.get("loc", ())) for e in (error.details.get("errors") or [])}
    assert ("nx",) in campos or ("nz",) in campos


@pytest.mark.slow
def test_los_datasets_canonicos_recorren_el_camino_del_usuario():
    """El ejemplo ES el test (estrategia de pruebas del informe para esta fase).

    Se ejecuta `examples/02_datasets_canonicos.py` en modo rápido. Tres de los
    cuatro canónicos completan la ruta; San Nicolás queda **declarado como no
    evaluable** —su dato es un `.mat` sin versionar y no hay conversor— con la
    misma disciplina que `DatosNoVersionados` en el gate F9: ni llamar fallo a
    lo que no se midió, ni PASS a una suite incompleta.
    """
    ruta = BACKEND_ROOT / "examples" / "02_datasets_canonicos.py"
    spec = importlib.util.spec_from_file_location("ejemplo_canonicos", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    salidas = modulo.main(rapido=True)
    por_nombre = {caso["nombre"]: salida for caso, salida in salidas}

    completados = [n for n, s in por_nombre.items() if s["estado"] == tq.ESTADO_OK]
    assert len(completados) == 3, (
        f"se esperaban 3 canónicos completos por la ruta del usuario: {por_nombre}"
    )
    assert por_nombre["San Nicolás VMS (México)"]["estado"] == "no_evaluado"
    assert "no versionado" in por_nombre["San Nicolás VMS (México)"]["motivo"] or \
           ".mat" in por_nombre["San Nicolás VMS (México)"]["motivo"]

    # Las dos físicas, de verdad, por la ruta completa.
    rutas = {s.get("ruta") for s in por_nombre.values() if s["estado"] == tq.ESTADO_OK}
    assert rutas == {"gravity_only", "magnetic_only"}
