import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.geo_utils import compute_bbox
from services.satellite_service import DEFAULT_EXTENT_M, DEM_COLS, DEM_ROWS


@pytest.fixture(autouse=True)
def disable_gee(monkeypatch):
    """Force GEE unavailable for all tests in this module so they test mock behavior."""
    import core.gee_client as gee_module
    monkeypatch.setattr(gee_module, "_gee_available", False)


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    import core.block_model_store as store

    projects_path = tmp_path / "projects"
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_path)
    return projects_path


@pytest.fixture
def client(projects_dir):
    from api.project_api import router as project_router
    from api.terrain_api import router as terrain_router

    app = FastAPI()
    app.include_router(project_router)
    app.include_router(terrain_router)
    return TestClient(app)


def _model_dump(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _write_project_meta(projects_dir, project_id, latitude=-22.28, longitude=-68.89):
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "project_id": project_id,
        "latitude": latitude,
        "longitude": longitude,
        "crs": "EPSG:4326",
        "created_at": "2026-05-17T00:00:00+00:00",
        "updated_at": "2026-05-17T00:00:00+00:00",
    }
    (project_dir / "project_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    return project_dir


def _write_source_gravity_csv(project_dir, run_id, rows):
    run_dir = project_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_lines = ["x_m,z_m,g"]
    csv_lines.extend(f"{row['x_m']},{row['z_m']},{row.get('g', 0.0)}" for row in rows)
    (run_dir / "source_gravity.csv").write_text(
        "\n".join(csv_lines),
        encoding="utf-8",
    )


def _assert_dem_shape(dem_matrix, rows=DEM_ROWS, cols=DEM_COLS):
    assert len(dem_matrix) == rows
    assert all(len(row) == cols for row in dem_matrix)


def _assert_bbox_matches(actual_bbox, center_lat, center_lon, extent_x_m, extent_z_m):
    expected_bbox = compute_bbox(
        center_lat=center_lat,
        center_lon=center_lon,
        extent_x_m=extent_x_m,
        extent_z_m=extent_z_m,
    )

    for key, expected_value in expected_bbox.items():
        assert actual_bbox[key] == pytest.approx(expected_value)


def test_get_terrain_data_valid_project_without_runs_uses_default_extent(projects_dir):
    from services.satellite_service import get_terrain_data

    project_id = "valid_no_runs"
    _write_project_meta(projects_dir, project_id)

    terrain = get_terrain_data(project_id)
    bbox = _model_dump(terrain.metadata.bbox)

    assert terrain.project_id == project_id
    assert terrain.metadata.source == "mock_v1_no_run"
    assert terrain.metadata.extent_x_m == DEFAULT_EXTENT_M
    assert terrain.metadata.extent_z_m == DEFAULT_EXTENT_M
    assert terrain.metadata.resolution_m == DEFAULT_EXTENT_M / 32
    _assert_dem_shape(terrain.dem_matrix)
    _assert_bbox_matches(
        bbox,
        center_lat=-22.28,
        center_lon=-68.89,
        extent_x_m=DEFAULT_EXTENT_M,
        extent_z_m=DEFAULT_EXTENT_M,
    )


def test_get_terrain_data_project_without_meta_raises_value_error(projects_dir):
    from services.satellite_service import get_terrain_data

    (projects_dir / "missing_meta").mkdir(parents=True)

    with pytest.raises(ValueError, match="Proyecto sin coordenadas"):
        get_terrain_data("missing_meta")


def test_get_terrain_data_uses_extent_derived_from_latest_csv(projects_dir):
    from services.satellite_service import get_terrain_data

    project_id = "with_csv"
    project_dir = _write_project_meta(projects_dir, project_id)
    _write_source_gravity_csv(
        project_dir,
        "run_001",
        [
            {"x_m": 0.0, "z_m": 0.0},
            {"x_m": 10.0, "z_m": 10.0},
        ],
    )
    _write_source_gravity_csv(
        project_dir,
        "run_002",
        [
            {"x_m": -100.0, "z_m": 50.0},
            {"x_m": 400.0, "z_m": 1_050.0},
            {"x_m": 150.0, "z_m": 500.0},
        ],
    )

    terrain = get_terrain_data(project_id)
    bbox = _model_dump(terrain.metadata.bbox)

    assert terrain.metadata.source == "mock_v1"
    assert terrain.metadata.extent_x_m == 500.0
    assert terrain.metadata.extent_z_m == 1_000.0
    assert terrain.metadata.resolution_m == pytest.approx(1_000.0 / 32)
    _assert_dem_shape(terrain.dem_matrix)
    _assert_bbox_matches(
        bbox,
        center_lat=-22.28,
        center_lon=-68.89,
        extent_x_m=500.0,
        extent_z_m=1_000.0,
    )


def test_get_project_terrain_endpoint_returns_mock_dem(client):
    response = client.post(
        "/projects",
        json={
            "project_id": "endpoint_ok",
            "latitude": -22.28,
            "longitude": -68.89,
        },
    )
    assert response.status_code == 201

    response = client.get("/projects/endpoint_ok/terrain")

    assert response.status_code == 200
    body = response.json()
    bbox = body["metadata"]["bbox"]

    assert body["project_id"] == "endpoint_ok"
    assert body["texture_url"] == ""
    assert body["metadata"]["source"] == "mock_v1_no_run"
    _assert_dem_shape(body["dem_matrix"])
    assert all(value == 0.0 for row in body["dem_matrix"] for value in row)
    assert bbox["min_lat"] < bbox["max_lat"]
    assert bbox["min_lon"] < bbox["max_lon"]


def test_get_project_terrain_endpoint_missing_project_returns_404(client):
    response = client.get("/projects/inexistente/terrain")

    assert response.status_code == 404


def test_get_project_terrain_endpoint_without_lat_lon_returns_404(client):
    response = client.post("/projects", json={"project_id": "no_coords"})
    assert response.status_code == 201

    response = client.get("/projects/no_coords/terrain")

    assert response.status_code == 404


def test_dem_matrix_has_exact_configured_dimensions(projects_dir):
    from services.satellite_service import get_terrain_data

    project_id = "dem_shape"
    _write_project_meta(projects_dir, project_id)

    terrain = get_terrain_data(project_id)

    assert terrain.metadata.dem_rows == DEM_ROWS
    assert terrain.metadata.dem_cols == DEM_COLS
    _assert_dem_shape(terrain.dem_matrix, rows=32, cols=32)
