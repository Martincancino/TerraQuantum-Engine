"""
R3.5-C tests — spatial_readiness conectado a /preview e /invert.

Verifica:
  - spatial_readiness aparece en response /preview
  - spatial_readiness aparece en response /invert
  - Niveles correctos por tipo de CSV (local_meters, utm, unknown)
  - can_compute_voxel_latlon y requires_user_acknowledgement correctos
  - No se bloquea /invert aunque el nivel sea bajo
  - georef y spatial_readiness coexisten en /invert
  - Anchor central NO produce GEOGRAPHIC_COORDS
  - spatial_readiness se persiste en gravity_import_metadata.json
  - spatial_readiness se persiste en project_meta.json
"""
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import core.block_model_store as store
from api.gravity_import_api import router
from core.rate_limit import limiter


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Reset in-memory rate limit storage between tests to avoid 429."""
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ── CSV builders ──────────────────────────────────────────────────────────────

def _make_csv_local_meters(rows: int = 10) -> bytes:
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{1000 + i * 200},0,{2000 + i * 200},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _make_csv_utm(rows: int = 10) -> bytes:
    """x in UTM easting range (100k-900k), z in northing range (0-10M)."""
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{300000 + i * 1000},0,{6000000 + i * 1000},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _make_csv_unknown_coords(rows: int = 10) -> bytes:
    """Values > 1_000_000 → max_abs > 1e6 → detected='unknown' → NO_SPATIAL_DATA."""
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{2000000 + i * 500},0,{3000000 + i * 500},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


# ── Common form fields for /invert ────────────────────────────────────────────

_INVERT_BASE_FORM = {
    "depth": "500",
    "nir": "20",
    "fe": "60",
    "region": "test_region",
    "lat": "-29.5",
    "lon": "-70.5",
    "nx": "8",
    "ny": "4",
    "nz": "8",
    "block_size": "200",
    "cutoff_radius": "600.0",
    "lambda_mag": "1.0",
    "alpha_spatial": "1.0",
    "strict": "false",
    "allow_g_raw": "false",
    "acknowledge_spatial_risk": "true",  # R3.5-D hard gate: requerido para niveles LOW/LOCAL/UTM_NO_ZONE
}


def _post_invert(client, csv_bytes: bytes, extra_form: dict | None = None, filename: str = "test.csv"):
    form = dict(_INVERT_BASE_FORM)
    if extra_form:
        form.update(extra_form)
    return client.post(
        "/gravity-import/invert",
        data=form,
        files={"file": (filename, io.BytesIO(csv_bytes), "text/csv")},
    )


def _post_preview(client, csv_bytes: bytes, filename: str = "test.csv"):
    return client.post(
        "/gravity-import/preview",
        files={"file": (filename, io.BytesIO(csv_bytes), "text/csv")},
    )


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _mock_inversion(*args, **kwargs):
    return {"status": "done", "blocks": [], "mock": True}


def _mock_terrain(*args, **kwargs):
    return {"status": "ok", "source": "mock"}


def _mock_enrich(*args, **kwargs):
    return {"status": "ok", "has_elevation_data": False, "warnings": []}


# ── Tests: /preview ───────────────────────────────────────────────────────────

def test_preview_local_meters_returns_spatial_readiness(client):
    """spatial_readiness debe aparecer en response de /preview."""
    resp = _post_preview(client, _make_csv_local_meters())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "spatial_readiness" in body, "Falta clave spatial_readiness en /preview"


def test_preview_local_meters_no_anchor_level_local_unanchored(client):
    """Preview sin lat/lon → LOCAL_UNANCHORED (no hay anchor disponible en preview)."""
    resp = _post_preview(client, _make_csv_local_meters())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] == "LOCAL_UNANCHORED", f"Esperado LOCAL_UNANCHORED, got: {sr['level']}"


def test_preview_unknown_coords_returns_no_spatial_data(client):
    """CSV con coords > 1M (detectadas como unknown) → NO_SPATIAL_DATA en preview."""
    resp = _post_preview(client, _make_csv_unknown_coords())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] == "NO_SPATIAL_DATA", f"Esperado NO_SPATIAL_DATA, got: {sr['level']}"


def test_preview_has_version_field(client):
    """spatial_readiness debe tener campo version."""
    resp = _post_preview(client, _make_csv_local_meters())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr.get("version") == "spatial_readiness_v0_1"


# ── Tests: /invert — niveles ──────────────────────────────────────────────────

def test_invert_local_meters_with_anchor_level_local_anchored_center(client, monkeypatch):
    """local_meters + lat/lon anchor → LOCAL_ANCHORED_CENTER."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200, resp.text
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] == "LOCAL_ANCHORED_CENTER", f"Esperado LOCAL_ANCHORED_CENTER, got: {sr['level']}"


def test_invert_local_meters_anchor_cannot_compute_voxel_latlon(client, monkeypatch):
    """LOCAL_ANCHORED_CENTER → can_compute_voxel_latlon = False."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr["can_compute_voxel_latlon"] is False


def test_invert_local_meters_anchor_requires_acknowledgement(client, monkeypatch):
    """LOCAL_ANCHORED_CENTER → requires_user_acknowledgement = True."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr["requires_user_acknowledgement"] is True


def test_invert_utm_no_zone_level(client, monkeypatch):
    """UTM sin zona → UTM_NO_ZONE."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_utm(), extra_form={"lat": "-29.5", "lon": "-70.5"})
    assert resp.status_code == 200, resp.text
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] == "UTM_NO_ZONE", f"Esperado UTM_NO_ZONE, got: {sr['level']}"


def test_invert_utm_with_zone_level(client, monkeypatch):
    """UTM con zona → UTM_WITH_ZONE."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_utm(), extra_form={"utm_zone": "19S"})
    assert resp.status_code == 200, resp.text
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] == "UTM_WITH_ZONE", f"Esperado UTM_WITH_ZONE, got: {sr['level']}"


# ── Tests: /invert — contrato response ───────────────────────────────────────

def test_invert_returns_spatial_readiness_key(client, monkeypatch):
    """spatial_readiness debe aparecer en response top-level de /invert."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200
    assert "spatial_readiness" in resp.json()


def test_invert_not_blocked_when_level_is_low(client, monkeypatch):
    """Inversión NO se bloquea si spatial_readiness es bajo Y acknowledge_spatial_risk=true (R3.5-D)."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    # lat/lon inválidos → LOCAL_UNANCHORED (anchor inválido, csv local_meters)
    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "9999", "lon": "9999"},  # fuera de rango → parse → None
    )
    assert resp.status_code == 200, f"Inversión bloqueada indebidamente: {resp.text}"
    body = resp.json()
    assert body["status"] == "done", f"status esperado done, got: {body['status']}"


def test_invert_georef_and_spatial_readiness_coexist(client, monkeypatch):
    """georef y spatial_readiness deben coexistir en la response de /invert."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200
    body = resp.json()
    assert "georef" in body, "Falta georef en response"
    assert "spatial_readiness" in body, "Falta spatial_readiness en response"


def test_invert_anchor_central_not_geographic_coords(client, monkeypatch):
    """Un anchor central (lat/lon del Form) NO debe producir GEOGRAPHIC_COORDS."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200
    sr = resp.json()["spatial_readiness"]
    assert sr["level"] != "GEOGRAPHIC_COORDS", (
        "Un anchor central no debe clasificar como GEOGRAPHIC_COORDS"
    )


# ── Tests: persistencia ───────────────────────────────────────────────────────

def test_invert_spatial_readiness_persisted_in_metadata_json(
    client, monkeypatch, patched_projects_dir
):
    """spatial_readiness debe persistirse en gravity_import_metadata.json."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    pid = f"pytest_{uuid.uuid4().hex[:8]}"
    rid = f"run_{uuid.uuid4().hex[:8]}"

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"project_id": pid, "run_id": rid},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"

    metadata_path = patched_projects_dir / pid / "runs" / rid / "gravity_import_metadata.json"
    assert metadata_path.exists(), f"gravity_import_metadata.json no encontrado en {metadata_path}"

    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    assert "spatial_readiness" in meta, "spatial_readiness ausente en gravity_import_metadata.json"
    assert meta["spatial_readiness"]["level"] == "LOCAL_ANCHORED_CENTER"


def test_invert_spatial_readiness_persisted_in_project_meta(
    client, monkeypatch, patched_projects_dir
):
    """spatial_readiness debe persistirse en project_meta.json."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    pid = f"pytest_{uuid.uuid4().hex[:8]}"
    rid = f"run_{uuid.uuid4().hex[:8]}"

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"project_id": pid, "run_id": rid},
    )
    assert resp.status_code == 200, resp.text

    project_meta_path = patched_projects_dir / pid / "project_meta.json"
    assert project_meta_path.exists(), f"project_meta.json no encontrado en {project_meta_path}"

    with open(project_meta_path, encoding="utf-8") as f:
        pm = json.load(f)

    assert "spatial_readiness" in pm, "spatial_readiness ausente en project_meta.json"
    assert pm["spatial_readiness"]["level"] == "LOCAL_ANCHORED_CENTER"
