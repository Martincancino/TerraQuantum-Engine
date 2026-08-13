"""
R1-BE-3 tests — build_project_response georef fields + GET /projects/{id}/footprint endpoint.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


_FOOTPRINT_WITH_COORDS = {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "local_meters_anchored",
    "confidence": "LOW",
    "center_lat": -22.28,
    "center_lon": -68.89,
    "extent_x_m": 49679.0,
    "extent_z_m": 48995.0,
    "utm_zone": None,
    "sw": {"lat": -22.50, "lon": -69.12},
    "se": {"lat": -22.50, "lon": -68.66},
    "ne": {"lat": -22.06, "lon": -68.66},
    "nw": {"lat": -22.06, "lon": -69.12},
    "warnings": ["Metros locales anclados al punto central. Orientación y escala real no garantizadas."],
    "precision_notes": ["Aproximación equirectangular — error <1% para extensiones <100km."],
}


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    import services.block_model_store as store

    projects_path = tmp_path / "projects"
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_path)
    return projects_path


@pytest.fixture
def client(projects_dir):
    from api.project_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# build_project_response tests (exercised via GET /projects/{id})
# ---------------------------------------------------------------------------

def test_build_project_response_includes_georef_confidence_from_meta(client, projects_dir):
    """GET /projects/{id} returns georef_confidence read from meta, not hardcoded."""
    client.post("/projects", json={"project_id": "georef_high"})
    meta_path = projects_dir / "georef_high" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["georef_confidence"] = "HIGH"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/georef_high")
    assert response.status_code == 200
    assert response.json()["georef_confidence"] == "HIGH"


def test_build_project_response_includes_footprint_from_meta(client, projects_dir):
    """GET /projects/{id} returns populated footprint when meta has one."""
    client.post("/projects", json={"project_id": "has_footprint"})
    meta_path = projects_dir / "has_footprint" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["footprint"] = _FOOTPRINT_WITH_COORDS
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/has_footprint")
    assert response.status_code == 200
    body = response.json()
    assert body["footprint"] is not None
    assert body["footprint"]["type"] == "bbox"
    assert body["footprint"]["confidence"] == "LOW"
    assert body["footprint"]["center_lat"] == pytest.approx(-22.28)


def test_build_project_response_georef_missing_when_no_meta(client, projects_dir):
    """Project dir exists but no project_meta.json → georef_confidence='MISSING', no crash."""
    old_project_dir = projects_dir / "legacy_no_meta"
    (old_project_dir / "runs" / "run_001").mkdir(parents=True)

    response = client.get("/projects/legacy_no_meta")
    assert response.status_code == 200
    body = response.json()
    assert body["georef_confidence"] == "MISSING"
    assert body["footprint"] is None


def test_build_project_response_footprint_none_for_meta_without_footprint(client, projects_dir):
    """Meta without 'footprint' key → footprint=None, no crash."""
    client.post("/projects", json={"project_id": "legacy_null_fp"})
    meta_path = projects_dir / "legacy_null_fp" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("footprint", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/legacy_null_fp")
    assert response.status_code == 200
    assert response.json()["footprint"] is None


def test_build_project_response_invalid_footprint_dict_no_crash(client, projects_dir):
    """Footprint dict with invalid corner types → footprint=None via except, no crash."""
    client.post("/projects", json={"project_id": "bad_fp"})
    meta_path = projects_dir / "bad_fp" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # Integers where Pydantic expects nested models → triggers ValidationError
    meta["footprint"] = {"sw": 99999, "se": 99999, "ne": 99999, "nw": 99999}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/bad_fp")
    assert response.status_code == 200
    assert response.json()["footprint"] is None


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/footprint endpoint tests
# ---------------------------------------------------------------------------

def test_footprint_endpoint_404_on_nonexistent_project(client):
    """GET /projects/nonexistent/footprint → HTTP 404."""
    response = client.get("/projects/nonexistent_xyz999/footprint")
    assert response.status_code == 404


def test_footprint_endpoint_200_for_project_with_footprint(client, projects_dir):
    """GET /projects/{id}/footprint → 200 with full footprint data."""
    client.post("/projects", json={"project_id": "fp_test"})
    meta_path = projects_dir / "fp_test" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["georef_confidence"] = "LOW"
    meta["georef_type"] = "local_meters_anchored"
    meta["footprint"] = _FOOTPRINT_WITH_COORDS
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/fp_test/footprint")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "fp_test"
    assert body["georef_confidence"] == "LOW"
    assert body["georef_type"] == "local_meters_anchored"
    assert body["footprint"] is not None
    assert body["footprint"]["type"] == "bbox"
    assert body["footprint"]["center_lat"] == pytest.approx(-22.28)
    assert body["footprint"]["center_lon"] == pytest.approx(-68.89)
    assert body["coordinate_system_detected"] == "local_meters_anchored"


def test_footprint_endpoint_missing_for_legacy_without_footprint(client, projects_dir):
    """GET /projects/{id}/footprint → 200 with MISSING and warning when no footprint in meta."""
    client.post("/projects", json={"project_id": "no_fp_proj"})
    meta_path = projects_dir / "no_fp_proj" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("footprint", None)
    meta.pop("georef_confidence", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/no_fp_proj/footprint")
    assert response.status_code == 200
    body = response.json()
    assert body["georef_confidence"] == "MISSING"
    assert body["footprint"] is None
    assert len(body["warnings"]) >= 1
    assert any("footprint" in w.lower() or "inversión" in w.lower() for w in body["warnings"])


def test_footprint_endpoint_returns_warnings_from_footprint(client, projects_dir):
    """GET /projects/{id}/footprint returns warnings from the footprint object."""
    client.post("/projects", json={"project_id": "fp_warns"})
    meta_path = projects_dir / "fp_warns" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["georef_confidence"] = "LOW"
    meta["footprint"] = _FOOTPRINT_WITH_COORDS
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/fp_warns/footprint")
    assert response.status_code == 200
    body = response.json()
    assert len(body["warnings"]) >= 1


def test_footprint_endpoint_utm_zone_from_meta(client, projects_dir):
    """GET /projects/{id}/footprint returns utm_zone from meta."""
    client.post("/projects", json={"project_id": "utm_proj"})
    meta_path = projects_dir / "utm_proj" / "project_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["georef_confidence"] = "MEDIUM"
    meta["utm_zone"] = "19S"
    meta["footprint"] = {**_FOOTPRINT_WITH_COORDS, "confidence": "MEDIUM", "source": "csv_utm"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get("/projects/utm_proj/footprint")
    assert response.status_code == 200
    body = response.json()
    assert body["utm_zone"] == "19S"
    assert body["georef_confidence"] == "MEDIUM"
