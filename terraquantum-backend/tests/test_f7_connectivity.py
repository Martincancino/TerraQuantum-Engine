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
