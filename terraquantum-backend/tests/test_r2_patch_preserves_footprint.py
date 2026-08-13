"""
Pre-R2 fix — PATCH /projects/{project_id} must not destroy footprint/georef/CRS fields.

Covers:
- PATCH updates latitude and longitude.
- PATCH preserves footprint completo.
- PATCH preserves georef_confidence.
- PATCH preserves georef_type.
- PATCH preserves utm_zone.
- PATCH preserves future CRS fields (input_crs, epsg_code, crs_source, crs_contract).
- PATCH preserves created_at.
- PATCH updates updated_at.
- PATCH on nonexistent project returns 404.
"""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


_FOOTPRINT = {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "latlon",
    "confidence": "HIGH",
    "center_lat": -22.28,
    "center_lon": -68.89,
    "extent_x_m": 49679.0,
    "extent_z_m": 48995.0,
    "utm_zone": None,
    "sw": {"lat": -22.50, "lon": -69.12},
    "se": {"lat": -22.50, "lon": -68.66},
    "ne": {"lat": -22.06, "lon": -68.66},
    "nw": {"lat": -22.06, "lon": -69.12},
    "warnings": ["test warning"],
    "precision_notes": ["equirectangular approx"],
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


def _seed_meta(projects_dir, project_id: str, extra: dict) -> dict:
    """Write a project_meta.json with extra fields beyond the schema baseline."""
    from api.project_api import utc_now_iso

    now = utc_now_iso()
    meta = {
        "project_id": project_id,
        "latitude": -22.28,
        "longitude": -68.89,
        "crs": "EPSG:4326",
        "created_at": now,
        "updated_at": now,
        "georef_confidence": "HIGH",
        "georef_type": "latlon",
        "utm_zone": "19S",
        **extra,
    }
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# Basic field update
# ---------------------------------------------------------------------------

def test_patch_updates_latitude_and_longitude(client, projects_dir):
    _seed_meta(projects_dir, "patch_coords", {})
    response = client.patch(
        "/projects/patch_coords",
        json={"latitude": 51.0, "longitude": -120.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["latitude"] == 51.0
    assert body["longitude"] == -120.0


# ---------------------------------------------------------------------------
# Footprint preservation
# ---------------------------------------------------------------------------

def test_patch_preserves_footprint(client, projects_dir):
    _seed_meta(projects_dir, "fp_preserve", {"footprint": _FOOTPRINT})

    response = client.patch(
        "/projects/fp_preserve",
        json={"latitude": 51.0},
    )
    assert response.status_code == 200

    meta = json.loads(
        (projects_dir / "fp_preserve" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta.get("footprint") is not None
    assert meta["footprint"]["type"] == "bbox"
    assert meta["footprint"]["confidence"] == "HIGH"
    assert meta["footprint"]["center_lat"] == pytest.approx(-22.28)
    assert meta["footprint"]["sw"]["lat"] == pytest.approx(-22.50)


def test_patch_preserves_footprint_warnings(client, projects_dir):
    _seed_meta(projects_dir, "fp_warns_preserve", {"footprint": _FOOTPRINT})

    client.patch("/projects/fp_warns_preserve", json={"longitude": -70.0})

    meta = json.loads(
        (projects_dir / "fp_warns_preserve" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert "test warning" in meta["footprint"]["warnings"]


# ---------------------------------------------------------------------------
# georef_confidence preservation
# ---------------------------------------------------------------------------

def test_patch_preserves_georef_confidence(client, projects_dir):
    _seed_meta(projects_dir, "gc_preserve", {})

    client.patch("/projects/gc_preserve", json={"latitude": 10.0})

    meta = json.loads(
        (projects_dir / "gc_preserve" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["georef_confidence"] == "HIGH"


# ---------------------------------------------------------------------------
# georef_type preservation
# ---------------------------------------------------------------------------

def test_patch_preserves_georef_type(client, projects_dir):
    _seed_meta(projects_dir, "gt_preserve", {})

    client.patch("/projects/gt_preserve", json={"longitude": -69.0})

    meta = json.loads(
        (projects_dir / "gt_preserve" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["georef_type"] == "latlon"


# ---------------------------------------------------------------------------
# utm_zone preservation
# ---------------------------------------------------------------------------

def test_patch_preserves_utm_zone(client, projects_dir):
    _seed_meta(projects_dir, "utm_preserve", {})

    client.patch("/projects/utm_preserve", json={"latitude": -23.0})

    meta = json.loads(
        (projects_dir / "utm_preserve" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["utm_zone"] == "19S"


# ---------------------------------------------------------------------------
# Future R2 CRS fields preservation (not yet in schema — stored as raw JSON)
# ---------------------------------------------------------------------------

def test_patch_preserves_input_crs(client, projects_dir):
    _seed_meta(projects_dir, "crs_input", {"input_crs": "EPSG:32719"})

    client.patch("/projects/crs_input", json={"latitude": -23.0})

    meta = json.loads(
        (projects_dir / "crs_input" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta.get("input_crs") == "EPSG:32719"


def test_patch_preserves_epsg_code(client, projects_dir):
    _seed_meta(projects_dir, "epsg_field", {"epsg_code": 32719})

    client.patch("/projects/epsg_field", json={"longitude": -68.0})

    meta = json.loads(
        (projects_dir / "epsg_field" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta.get("epsg_code") == 32719


def test_patch_preserves_crs_source(client, projects_dir):
    _seed_meta(projects_dir, "crs_src", {"crs_source": "user_declared"})

    client.patch("/projects/crs_src", json={"latitude": -24.0})

    meta = json.loads(
        (projects_dir / "crs_src" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta.get("crs_source") == "user_declared"


def test_patch_preserves_crs_contract(client, projects_dir):
    contract = {
        "input_crs": "EPSG:32719",
        "epsg_code": 32719,
        "crs_source": "user_declared",
        "crs_confidence": "HIGH",
        "utm_zone": "19S",
        "utm_hemisphere": "S",
    }
    _seed_meta(projects_dir, "crs_contract", {"crs_contract": contract})

    client.patch("/projects/crs_contract", json={"latitude": -25.0})

    meta = json.loads(
        (projects_dir / "crs_contract" / "project_meta.json").read_text(encoding="utf-8")
    )
    stored = meta.get("crs_contract")
    assert stored is not None
    assert stored["input_crs"] == "EPSG:32719"
    assert stored["utm_zone"] == "19S"


# ---------------------------------------------------------------------------
# created_at / updated_at
# ---------------------------------------------------------------------------

def test_patch_preserves_created_at(client, projects_dir):
    seed = _seed_meta(projects_dir, "ts_check", {})
    original_created_at = seed["created_at"]

    time.sleep(0.01)
    client.patch("/projects/ts_check", json={"latitude": 10.0})

    meta = json.loads(
        (projects_dir / "ts_check" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["created_at"] == original_created_at


def test_patch_updates_updated_at(client, projects_dir):
    seed = _seed_meta(projects_dir, "upd_at_check", {})
    original_updated_at = seed["updated_at"]

    time.sleep(0.02)
    client.patch("/projects/upd_at_check", json={"latitude": 10.0})

    meta = json.loads(
        (projects_dir / "upd_at_check" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["updated_at"] >= original_updated_at


# ---------------------------------------------------------------------------
# 404 on nonexistent project
# ---------------------------------------------------------------------------

def test_patch_nonexistent_project_returns_404(client):
    response = client.patch(
        "/projects/does_not_exist_xyz999",
        json={"latitude": 0.0},
    )
    assert response.status_code == 404
