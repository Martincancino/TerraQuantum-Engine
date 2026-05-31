import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    import core.block_model_store as store

    projects_path = tmp_path / "projects"
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_path)
    return projects_path


@pytest.fixture
def client(projects_dir):
    from api.project_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_create_project_with_coords(client, projects_dir):
    response = client.post(
        "/projects",
        json={
            "project_id": "hvc",
            "latitude": 50.483,
            "longitude": -121.012,
            "crs": "EPSG:4326",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == "hvc"
    assert body["latitude"] == 50.483
    assert body["longitude"] == -121.012
    assert body["crs"] == "EPSG:4326"
    assert body["created_at"]
    assert body["updated_at"]

    meta_path = projects_dir / "hvc" / "project_meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["project_id"] == "hvc"
    assert meta["latitude"] == 50.483
    assert meta["longitude"] == -121.012


def test_create_project_without_coords(client):
    response = client.post("/projects", json={"project_id": "no_coords"})

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == "no_coords"
    assert body["latitude"] is None
    assert body["longitude"] is None
    assert body["crs"] == "EPSG:4326"


def test_create_project_duplicate(client):
    payload = {"project_id": "duplicate", "latitude": 10.0, "longitude": -70.0}

    assert client.post("/projects", json=payload).status_code == 201
    response = client.post("/projects", json=payload)

    assert response.status_code == 409


def test_get_project(client):
    client.post(
        "/projects",
        json={"project_id": "get_me", "latitude": -22.28, "longitude": -68.89},
    )

    response = client.get("/projects/get_me")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "get_me"
    assert body["latitude"] == -22.28
    assert body["longitude"] == -68.89
    assert body["run_count"] == 0


def test_get_old_project_no_meta(client, projects_dir):
    old_project_dir = projects_dir / "old_project"
    (old_project_dir / "runs" / "run_001").mkdir(parents=True)

    response = client.get("/projects/old_project")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "old_project"
    assert body["latitude"] is None
    assert body["longitude"] is None
    assert body["crs"] == "EPSG:4326"
    assert body["run_count"] == 1


def test_update_project_coords(client, projects_dir):
    client.post("/projects", json={"project_id": "patch_me"})

    response = client.patch(
        "/projects/patch_me",
        json={"latitude": 51.0, "longitude": -121.5, "crs": "EPSG:4326"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["latitude"] == 51.0
    assert body["longitude"] == -121.5

    meta = json.loads(
        (projects_dir / "patch_me" / "project_meta.json").read_text(encoding="utf-8")
    )
    assert meta["latitude"] == 51.0
    assert meta["longitude"] == -121.5
    assert meta["updated_at"] >= meta["created_at"]


def test_list_projects_includes_meta(client, projects_dir):
    client.post(
        "/projects",
        json={"project_id": "listed", "latitude": 50.1, "longitude": -120.9},
    )
    (projects_dir / "listed" / "runs" / "run_001").mkdir(parents=True)

    response = client.get("/projects")

    assert response.status_code == 200
    body = response.json()
    listed = next(project for project in body["projects"] if project["project_id"] == "listed")
    assert listed["projectMeta"]["project_id"] == "listed"
    assert listed["projectMeta"]["latitude"] == 50.1
    assert listed["projectMeta"]["longitude"] == -120.9
    assert listed["run_count"] == 1
