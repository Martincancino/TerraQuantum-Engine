"""F7 — Honestidad offline.

El camino dorado (ingesta→inversión→3D→export) es offline; las features de red
están marcadas y ninguna es requisito del flujo principal.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.connectivity_service import connectivity_summary


def test_golden_path_is_offline():
    s = connectivity_summary()
    assert s["golden_path_offline"] is True
    assert s["probed"] is False  # por defecto no toca la red


def test_no_online_feature_is_required_for_golden_path():
    s = connectivity_summary()
    for feat in s["online_features"]:
        if feat["requires_internet"]:
            assert feat["required_for_golden_path"] is False, feat["name"]


def test_igrf_is_offline_and_required():
    s = connectivity_summary()
    igrf = next(f for f in s["online_features"] if f["key"] == "igrf")
    assert igrf["requires_internet"] is False
    assert igrf["required_for_golden_path"] is True


def test_dem_has_local_fallback():
    s = connectivity_summary()
    dem = next(f for f in s["online_features"] if f["key"] == "dem_opentopo")
    assert dem["requires_internet"] is True
    assert dem["local_fallback"] is True


def test_connectivity_endpoint():
    from api import system_api
    app = FastAPI()
    app.include_router(system_api.router)
    client = TestClient(app)
    r = client.get("/system/connectivity")
    assert r.status_code == 200
    body = r.json()
    assert body["golden_path_offline"] is True
    assert len(body["online_features"]) >= 3


# ─── FASE 9 — los dos defectos de honestidad que este archivo NO medía ─────────
#
# Los tests de arriba pasaban con las dos mentiras dentro: sólo miraban el caso
# por defecto (`probed is False` sin pedir sondeo) y nunca preguntaban si
# `configured` podía llegar a ser True. Un indicador de conectividad que miente
# es peor que no tenerlo, y la Fase 9 lo pone delante del usuario.


def test_pedir_sondeo_no_hace_que_se_declare_sondeado():
    """`probe=True` NO puede devolver `probed=True`: el sondeo no existe.

    Antes de la Fase 9 la respuesta era `"probed": bool(probe)` — declaraba
    haber comprobado el alcance real sin haber abierto un socket jamás.
    """
    s = connectivity_summary(probe=True)
    assert s["probed"] is False, "declara sondeo hecho sin tocar la red"
    assert s["probe_requested"] is True
    assert s["probe_note"].strip(), "no explica por qué no sondea"


def test_probed_es_false_por_la_ruta_http(monkeypatch):
    from api import system_api
    app = FastAPI()
    app.include_router(system_api.router)
    client = TestClient(app)
    body = client.get("/system/connectivity?probe=true").json()
    assert body["probed"] is False
    assert body["probe_requested"] is True


def test_copiloto_detecta_la_clave_del_entorno(monkeypatch):
    """`copilot_gemini.configured` debe MOVERSE con la clave real.

    El defecto: leía `config.GEMINI_API_KEY`, atributo inexistente, protegido
    con `hasattr` → False constante. Este test falla con aquel código porque la
    clave está puesta y `configured` sigue en False. La fuente correcta es la
    misma que resuelve `api/chat_api.py::_resolve_api_key`: el entorno.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba-no-real")
    feat = next(f for f in connectivity_summary()["online_features"]
                if f["key"] == "copilot_gemini")
    assert feat["configured"] is True

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    feat = next(f for f in connectivity_summary()["online_features"]
                if f["key"] == "copilot_gemini")
    assert feat["configured"] is False


def test_copiloto_declara_que_la_clave_la_pone_el_usuario():
    """Sin este campo, `configured: false` se lee como «no disponible».

    El copiloto es BYO-key: la clave se pega en la interfaz y no vive en el
    servidor. La UI necesita poder distinguir «no hay clave en el servidor» de
    «esta función no se puede usar».
    """
    feat = next(f for f in connectivity_summary()["online_features"]
                if f["key"] == "copilot_gemini")
    assert feat["user_supplied_key"] is True


def test_ninguna_feature_declara_configured_por_un_atributo_fantasma():
    """Guardia genérica: `configured` tiene que ser un bool de verdad.

    No caza un atributo inexistente por sí sola —para eso está el test de
    monkeypatch—, pero impide que alguien devuelva None/''/un objeto y que la UI
    lo pinte como si fuera un estado.
    """
    for feat in connectivity_summary()["online_features"]:
        assert isinstance(feat["configured"], bool), feat["key"]
        assert feat["message"].strip(), feat["key"]
