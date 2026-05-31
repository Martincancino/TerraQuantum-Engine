"""
R3-BE-3 — Tests for terrain_metadata.json and terrain_dem_matrix.json persistence.

All tests are unit-level or light integration; they do NOT require GEE or a real
project.  File-system tests use pytest's tmp_path fixture and monkeypatch to
redirect PROJECTS_DIR so no real project data is touched.
"""
import json
import pytest

from core import block_model_store as store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_METADATA = {
    "project_id": "test_proj",
    "generated_at": "2026-05-19T00:00:00Z",
    "bbox": {"min_lat": -22.5, "max_lat": -22.1, "min_lon": -69.1, "max_lon": -68.7},
    "dem_rows": 32,
    "dem_cols": 32,
    "cell_size_x_m": 375.0,
    "cell_size_z_m": 375.0,
    "min_elevation_m": 2800.0,
    "max_elevation_m": 3200.0,
    "mean_elevation_m": 3000.0,
    "source": "mock_v1",
    "footprint_source": "utm_pyproj",
    "georef_confidence": "HIGH",
    "terrain_margin_factor": 1.5,
    "warnings": [],
    "center_lat": -22.3,
    "center_lon": -68.9,
    "extent_x_m": 3000.0,
    "extent_z_m": 3000.0,
    "dem_matrix_path": "terrain_dem_matrix.json",
}

SAMPLE_MATRIX = [[float(i * 32 + j) for j in range(32)] for i in range(32)]


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    """Redirect PROJECTS_DIR to a temp directory for isolation."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ---------------------------------------------------------------------------
# 1. save_terrain_metadata creates file
# ---------------------------------------------------------------------------

def test_save_terrain_metadata_creates_file(patched_projects_dir):
    store.save_terrain_metadata("test_proj", SAMPLE_METADATA)
    path = patched_projects_dir / "test_proj" / "terrain_metadata.json"
    assert path.exists(), "terrain_metadata.json deve existir após save"


# ---------------------------------------------------------------------------
# 2. load_terrain_metadata returns dict
# ---------------------------------------------------------------------------

def test_load_terrain_metadata_returns_dict(patched_projects_dir):
    store.save_terrain_metadata("test_proj", SAMPLE_METADATA)
    loaded = store.load_terrain_metadata("test_proj")
    assert isinstance(loaded, dict)
    assert loaded["project_id"] == "test_proj"
    assert loaded["dem_rows"] == 32


# ---------------------------------------------------------------------------
# 3. load_terrain_metadata returns None if file does not exist
# ---------------------------------------------------------------------------

def test_load_terrain_metadata_returns_none_if_missing(patched_projects_dir):
    result = store.load_terrain_metadata("nonexistent_project")
    assert result is None


# ---------------------------------------------------------------------------
# 4. save_terrain_dem_matrix creates file
# ---------------------------------------------------------------------------

def test_save_terrain_dem_matrix_creates_file(patched_projects_dir):
    store.save_terrain_dem_matrix("test_proj", SAMPLE_MATRIX)
    path = patched_projects_dir / "test_proj" / "terrain_dem_matrix.json"
    assert path.exists(), "terrain_dem_matrix.json deve existir após save"


# ---------------------------------------------------------------------------
# 5. load_terrain_dem_matrix returns matrix
# ---------------------------------------------------------------------------

def test_load_terrain_dem_matrix_returns_matrix(patched_projects_dir):
    store.save_terrain_dem_matrix("test_proj", SAMPLE_MATRIX)
    loaded = store.load_terrain_dem_matrix("test_proj")
    assert isinstance(loaded, list)
    assert len(loaded) == 32
    assert len(loaded[0]) == 32
    assert loaded[0][0] == 0.0
    assert loaded[1][0] == 32.0


# ---------------------------------------------------------------------------
# 6. load_terrain_dem_matrix returns None if file does not exist
# ---------------------------------------------------------------------------

def test_load_terrain_dem_matrix_returns_none_if_missing(patched_projects_dir):
    result = store.load_terrain_dem_matrix("nonexistent_project")
    assert result is None


# ---------------------------------------------------------------------------
# 7. Saved metadata includes dem_matrix_path
# ---------------------------------------------------------------------------

def test_saved_metadata_includes_dem_matrix_path(patched_projects_dir):
    store.save_terrain_metadata("test_proj", SAMPLE_METADATA)
    loaded = store.load_terrain_metadata("test_proj")
    assert loaded is not None
    assert loaded.get("dem_matrix_path") == "terrain_dem_matrix.json"


# ---------------------------------------------------------------------------
# 8. get_terrain_data persists metadata and matrix (GEE mocked off)
# ---------------------------------------------------------------------------

def test_get_terrain_data_persists_metadata_and_matrix(
    patched_projects_dir, monkeypatch
):
    from core import gee_client
    from services.satellite_service import get_terrain_data

    project_id = "persist_test_001"
    project_dir = patched_projects_dir / project_id
    project_dir.mkdir()
    meta = {"latitude": -22.3, "longitude": -68.9}
    (project_dir / "project_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    monkeypatch.setattr(gee_client, "is_available", lambda: False)

    result = get_terrain_data(project_id)

    meta_path = project_dir / "terrain_metadata.json"
    matrix_path = project_dir / "terrain_dem_matrix.json"
    assert meta_path.exists(), "terrain_metadata.json deve ser criado"
    assert matrix_path.exists(), "terrain_dem_matrix.json deve ser criado"

    loaded_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert loaded_meta["project_id"] == project_id
    assert loaded_meta["dem_matrix_path"] == "terrain_dem_matrix.json"
    assert "dem_rows" in loaded_meta
    assert "bbox" in loaded_meta
    assert result.metadata.extent_x_m == 3000.0
    assert result.metadata.extent_z_m == 3000.0
    assert loaded_meta["extent_x_m"] == 3000.0
    assert loaded_meta["extent_z_m"] == 3000.0


def test_get_terrain_data_persists_latlon_import_bbox_extent(
    patched_projects_dir, monkeypatch
):
    from core import gee_client
    from services.satellite_service import DEFAULT_EXTENT_M, get_terrain_data

    project_id = "latlon_extent_001"
    project_dir = patched_projects_dir / project_id
    run_dir = project_dir / "runs" / "run_001"
    run_dir.mkdir(parents=True)
    (project_dir / "project_meta.json").write_text(
        json.dumps({"latitude": -22.35, "longitude": -69.10}),
        encoding="utf-8",
    )
    (run_dir / "gravity_import_metadata.json").write_text(
        json.dumps({
            "coordinate_transform": {
                "input_coordinate_system": "latlon",
                "x_min_raw": -69.35,
                "x_max_raw": -68.85,
                "z_min_raw": -22.58,
                "z_max_raw": -22.12,
            },
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(gee_client, "is_available", lambda: False)

    result = get_terrain_data(project_id)
    loaded_meta = store.load_terrain_metadata(project_id)

    assert result.metadata.extent_x_m > DEFAULT_EXTENT_M
    assert result.metadata.extent_z_m > DEFAULT_EXTENT_M
    assert result.metadata.footprint_source == "latlon_bbox"
    assert any("equirectangular" in w.lower() for w in result.metadata.warnings)
    assert loaded_meta is not None
    assert loaded_meta["extent_x_m"] == pytest.approx(result.metadata.extent_x_m)
    assert loaded_meta["extent_z_m"] == pytest.approx(result.metadata.extent_z_m)
    assert loaded_meta["footprint_source"] == "latlon_bbox"


def test_get_terrain_data_keeps_utm_footprint_extent(
    patched_projects_dir, monkeypatch
):
    from core import gee_client
    from services.satellite_service import get_terrain_data

    project_id = "utm_extent_001"
    project_dir = patched_projects_dir / project_id
    project_dir.mkdir()
    footprint = {
        "source": "utm_pyproj",
        "confidence": "HIGH",
        "extent_x_m": 42000.0,
        "extent_z_m": 51000.0,
        "sw": {"lat": -22.50, "lon": -69.30},
        "se": {"lat": -22.50, "lon": -68.89},
        "ne": {"lat": -22.04, "lon": -68.89},
        "nw": {"lat": -22.04, "lon": -69.30},
    }
    (project_dir / "project_meta.json").write_text(
        json.dumps({
            "latitude": -22.27,
            "longitude": -69.10,
            "footprint": footprint,
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(gee_client, "is_available", lambda: False)

    result = get_terrain_data(project_id)

    assert result.metadata.extent_x_m == 42000.0
    assert result.metadata.extent_z_m == 51000.0
    assert result.metadata.footprint_source == "utm_pyproj"


# ---------------------------------------------------------------------------
# 9. If save fails, get_terrain_data does NOT crash and adds warning
# ---------------------------------------------------------------------------

def test_get_terrain_data_persist_failure_no_crash(patched_projects_dir, monkeypatch):
    from core import gee_client
    from services.satellite_service import get_terrain_data

    project_id = "persist_fail_001"
    project_dir = patched_projects_dir / project_id
    project_dir.mkdir()
    meta = {"latitude": -22.3, "longitude": -68.9}
    (project_dir / "project_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    monkeypatch.setattr(gee_client, "is_available", lambda: False)

    def _fail_save(*args, **kwargs):
        raise IOError("disco lleno simulado")

    monkeypatch.setattr(store, "save_terrain_metadata", _fail_save)

    # Must not raise
    result = get_terrain_data(project_id)

    # Warning must appear in metadata
    assert any(
        "No se pudo persistir" in w for w in result.metadata.warnings
    ), f"Expected persist warning, got: {result.metadata.warnings}"
