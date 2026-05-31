"""
R3.5-D — Hard gate industrial en /gravity-import/invert según SpatialReadiness.

Verifica:
  - Preview NO_SPATIAL_DATA no bloquea y devuelve spatial_readiness (HTTP 200)
  - Invert NO_SPATIAL_DATA bloquea HTTP 422
  - NO_SPATIAL_DATA no acepta acknowledge bypass
  - Invert LOCAL_UNANCHORED sin ack bloquea HTTP 422
  - Invert LOCAL_UNANCHORED con ack permite (HTTP 200)
  - Invert LOCAL_ANCHORED_CENTER sin ack bloquea HTTP 422
  - Invert LOCAL_ANCHORED_CENTER con ack permite (HTTP 200)
  - Invert UTM_NO_ZONE sin ack bloquea HTTP 422
  - Invert UTM_NO_ZONE con ack permite (HTTP 200)
  - Invert UTM_WITH_ZONE permite sin ack (HTTP 200)
  - Invert GEOGRAPHIC_COORDS permite sin ack (HTTP 200)
  - synthetic_demo bypass no bloquea (HTTP 200)
  - Error 422 incluye error="SPATIAL_READINESS_GATE"
  - Error 422 incluye required_acknowledgement cuando aplica
  - Gate se ejecuta antes del solver (solver no llamado en bloqueo)
  - /invert permitido sigue devolviendo spatial_readiness
  - /invert permitido sigue devolviendo georef
  - /invert permitido sigue devolviendo r3_enrichment
"""
import io
import pytest
from fastapi import FastAPI, HTTPException
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
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


# ── CSV builders ──────────────────────────────────────────────────────────────

def _make_csv_local_meters(rows: int = 10) -> bytes:
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{1000 + i * 200},0,{2000 + i * 200},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _make_csv_utm(rows: int = 10) -> bytes:
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{300000 + i * 1000},0,{6000000 + i * 1000},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _make_csv_unknown_coords(rows: int = 10) -> bytes:
    """Values > 1_000_000 → detected='unknown' → NO_SPATIAL_DATA."""
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{2000000 + i * 500},0,{3000000 + i * 500},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _make_csv_unknown_synthetic_demo(rows: int = 10) -> bytes:
    """Unknown coords + gravity_type=synthetic_demo → gate bypass."""
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{2000000 + i * 500},0,{3000000 + i * 500},mGal,{10.0 + i * 0.5},synthetic_demo")
    return "\n".join(lines).encode()


# ── Shared form base ──────────────────────────────────────────────────────────

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


# ── Unit tests: _enforce_spatial_readiness_gate directly ─────────────────────

class TestEnforceSpatialReadinessGate:
    """Unit tests for the gate helper — fast, no HTTP overhead."""

    def _sr(self, level: str):
        from services.spatial_readiness_service import (
            _build_no_spatial_data,
            _build_local_unanchored,
            _build_local_anchored_center,
            _build_utm_no_zone,
            _build_utm_with_zone,
            _build_geographic_coords,
            _build_professional_survey,
        )
        builders = {
            "NO_SPATIAL_DATA": _build_no_spatial_data,
            "LOCAL_UNANCHORED": _build_local_unanchored,
            "LOCAL_ANCHORED_CENTER": _build_local_anchored_center,
            "UTM_NO_ZONE": _build_utm_no_zone,
            "UTM_WITH_ZONE": _build_utm_with_zone,
            "GEOGRAPHIC_COORDS": _build_geographic_coords,
            "PROFESSIONAL_SURVEY": _build_professional_survey,
        }
        return builders[level]()

    def _gate(self, level: str, ack: bool = False, gravity_type: str | None = None):
        from api.gravity_import_api import _enforce_spatial_readiness_gate
        _enforce_spatial_readiness_gate(
            self._sr(level),
            acknowledge_spatial_risk=ack,
            gravity_type=gravity_type,
        )

    # NO_SPATIAL_DATA — siempre bloqueado
    def test_no_spatial_data_blocks_without_ack(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert exc.value.status_code == 422

    def test_no_spatial_data_blocks_even_with_ack(self):
        """NO_SPATIAL_DATA no acepta bypass por acknowledgement."""
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=True)
        assert exc.value.status_code == 422

    def test_no_spatial_data_detail_has_error_key(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert exc.value.detail["error"] == "SPATIAL_READINESS_GATE"

    def test_no_spatial_data_detail_has_level(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert exc.value.detail["level"] == "NO_SPATIAL_DATA"

    def test_no_spatial_data_required_acknowledgement_is_none(self):
        """NO_SPATIAL_DATA no ofrece camino de bypass."""
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert exc.value.detail["required_acknowledgement"] is None

    # LOCAL_UNANCHORED
    def test_local_unanchored_blocks_without_ack(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("LOCAL_UNANCHORED", ack=False)
        assert exc.value.status_code == 422

    def test_local_unanchored_allows_with_ack(self):
        self._gate("LOCAL_UNANCHORED", ack=True)  # must not raise

    def test_local_unanchored_required_acknowledgement_key(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("LOCAL_UNANCHORED", ack=False)
        assert exc.value.detail["required_acknowledgement"] == "ACK_LOCAL_CONCEPTUAL_ONLY"

    # LOCAL_ANCHORED_CENTER
    def test_local_anchored_center_blocks_without_ack(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("LOCAL_ANCHORED_CENTER", ack=False)
        assert exc.value.status_code == 422

    def test_local_anchored_center_allows_with_ack(self):
        self._gate("LOCAL_ANCHORED_CENTER", ack=True)  # must not raise

    def test_local_anchored_center_has_required_acknowledgement(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("LOCAL_ANCHORED_CENTER", ack=False)
        assert exc.value.detail["required_acknowledgement"] is not None

    # UTM_NO_ZONE
    def test_utm_no_zone_blocks_without_ack(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("UTM_NO_ZONE", ack=False)
        assert exc.value.status_code == 422

    def test_utm_no_zone_allows_with_ack(self):
        self._gate("UTM_NO_ZONE", ack=True)  # must not raise

    def test_utm_no_zone_has_required_acknowledgement(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("UTM_NO_ZONE", ack=False)
        assert exc.value.detail["required_acknowledgement"] is not None

    # UTM_WITH_ZONE / GEOGRAPHIC_COORDS / PROFESSIONAL_SURVEY — always allowed
    def test_utm_with_zone_allows_without_ack(self):
        self._gate("UTM_WITH_ZONE", ack=False)  # must not raise

    def test_geographic_coords_allows_without_ack(self):
        self._gate("GEOGRAPHIC_COORDS", ack=False)  # must not raise

    def test_professional_survey_allows_without_ack(self):
        self._gate("PROFESSIONAL_SURVEY", ack=False)  # must not raise

    # synthetic_demo bypass
    def test_synthetic_demo_bypasses_no_spatial_data(self):
        """synthetic_demo bypasses gate even for NO_SPATIAL_DATA."""
        self._gate("NO_SPATIAL_DATA", ack=False, gravity_type="synthetic_demo")

    def test_synthetic_demo_bypasses_local_unanchored(self):
        self._gate("LOCAL_UNANCHORED", ack=False, gravity_type="synthetic_demo")

    def test_synthetic_demo_case_insensitive(self):
        """Bypass debe ser case-insensitive."""
        self._gate("NO_SPATIAL_DATA", ack=False, gravity_type="Synthetic_Demo")

    # Detail structure
    def test_detail_contains_missing_fields(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert "missing_fields" in exc.value.detail

    def test_detail_contains_blocked_outputs(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert "blocked_outputs" in exc.value.detail

    def test_detail_contains_allowed_outputs(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert "allowed_outputs" in exc.value.detail

    def test_detail_contains_rationale(self):
        with pytest.raises(HTTPException) as exc:
            self._gate("NO_SPATIAL_DATA", ack=False)
        assert "rationale" in exc.value.detail


# ── Integration tests via TestClient ─────────────────────────────────────────

# 1. Preview NO_SPATIAL_DATA no bloquea y devuelve spatial_readiness
def test_preview_no_spatial_data_does_not_block(client):
    """Preview nunca bloquea, incluso con NO_SPATIAL_DATA."""
    resp = _post_preview(client, _make_csv_unknown_coords())
    assert resp.status_code == 200, resp.text


def test_preview_no_spatial_data_returns_spatial_readiness(client):
    resp = _post_preview(client, _make_csv_unknown_coords())
    assert resp.status_code == 200
    body = resp.json()
    assert "spatial_readiness" in body
    assert body["spatial_readiness"]["level"] == "NO_SPATIAL_DATA"


# 2. Invert NO_SPATIAL_DATA bloquea HTTP 422
def test_invert_no_spatial_data_returns_422(client):
    resp = _post_invert(client, _make_csv_unknown_coords())
    assert resp.status_code == 422, resp.text


def test_invert_no_spatial_data_detail_has_gate_error(client):
    resp = _post_invert(client, _make_csv_unknown_coords())
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "SPATIAL_READINESS_GATE"


# 3. NO_SPATIAL_DATA no acepta acknowledge bypass
def test_invert_no_spatial_data_ack_still_blocks(client):
    """acknowledge_spatial_risk=True no puede bypassear NO_SPATIAL_DATA."""
    resp = _post_invert(
        client,
        _make_csv_unknown_coords(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 422, resp.text


# 4. LOCAL_UNANCHORED sin ack bloquea
def test_invert_local_unanchored_blocks_without_ack(client):
    """local_meters + lat/lon inválidos → LOCAL_UNANCHORED → bloquea sin ack."""
    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "9999", "lon": "9999"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "SPATIAL_READINESS_GATE"


def test_invert_local_unanchored_detail_has_required_ack(client):
    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "9999", "lon": "9999"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["required_acknowledgement"] == "ACK_LOCAL_CONCEPTUAL_ONLY"


# 5. LOCAL_UNANCHORED con ack permite
def test_invert_local_unanchored_with_ack_allows(client, monkeypatch):
    """LOCAL_UNANCHORED + acknowledge_spatial_risk=true → HTTP 200."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "9999", "lon": "9999", "acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


# 6. LOCAL_ANCHORED_CENTER sin ack bloquea
def test_invert_local_anchored_center_blocks_without_ack(client):
    """local_meters + lat/lon válidos → LOCAL_ANCHORED_CENTER → bloquea sin ack."""
    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "SPATIAL_READINESS_GATE"
    assert resp.json()["detail"]["level"] == "LOCAL_ANCHORED_CENTER"


# 7. LOCAL_ANCHORED_CENTER con ack permite
def test_invert_local_anchored_center_with_ack_allows(client, monkeypatch):
    """LOCAL_ANCHORED_CENTER + acknowledge_spatial_risk=true → HTTP 200."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


# 8. UTM_NO_ZONE sin ack bloquea
def test_invert_utm_no_zone_blocks_without_ack(client):
    resp = _post_invert(client, _make_csv_utm())
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "SPATIAL_READINESS_GATE"
    assert resp.json()["detail"]["level"] == "UTM_NO_ZONE"


# 9. UTM_NO_ZONE con ack permite
def test_invert_utm_no_zone_with_ack_allows(client, monkeypatch):
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_utm(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


# 10. UTM_WITH_ZONE permite sin ack
def test_invert_utm_with_zone_allows_without_ack(client, monkeypatch):
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_utm(),
        extra_form={"utm_zone": "19S"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["spatial_readiness"]["level"] == "UTM_WITH_ZONE"


# 11. GEOGRAPHIC_COORDS permite sin ack (via monkeypatch de classify)
def test_invert_geographic_coords_allows_without_ack(client, monkeypatch):
    import api.gravity_import_api as api_mod
    from services.spatial_readiness_service import _build_geographic_coords

    monkeypatch.setattr(api_mod, "_compute_spatial_readiness_for_import",
                        lambda *a, **kw: _build_geographic_coords())
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 200, resp.text
    assert resp.json()["spatial_readiness"]["level"] == "GEOGRAPHIC_COORDS"


# 12. synthetic_demo bypass no bloquea
def test_invert_synthetic_demo_bypasses_gate(client, monkeypatch):
    """CSV con gravity_type=synthetic_demo bypassa el gate aunque sea NO_SPATIAL_DATA."""
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(client, _make_csv_unknown_synthetic_demo())
    assert resp.status_code == 200, (
        f"synthetic_demo debería bypassar el gate. Status: {resp.status_code}\n{resp.text}"
    )


# 13. Gate se ejecuta ANTES del solver (solver no llamado en bloqueo)
def test_gate_fires_before_solver_no_calls_on_block(client, monkeypatch):
    """Cuando el gate bloquea, run_geophysics_inversion no debe ser llamado."""
    import api.gravity_import_api as api_mod

    solver_calls: list = []

    def _spy_solver(*args, **kwargs):
        solver_calls.append(1)
        return {"status": "done", "blocks": [], "mock": True}

    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _spy_solver)

    resp = _post_invert(client, _make_csv_unknown_coords())  # → NO_SPATIAL_DATA → bloquea
    assert resp.status_code == 422
    assert len(solver_calls) == 0, (
        f"El solver fue llamado {len(solver_calls)} veces, pero el gate debería "
        "haberlo bloqueado antes de llegar al solver."
    )


# 14. /invert permitido sigue devolviendo spatial_readiness
def test_invert_allowed_returns_spatial_readiness(client, monkeypatch):
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "spatial_readiness" in body, "spatial_readiness ausente en /invert permitido"
    assert "level" in body["spatial_readiness"]


# 15. /invert permitido sigue devolviendo georef
def test_invert_allowed_returns_georef(client, monkeypatch):
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "georef" in body, "georef ausente en /invert permitido"
    assert "confidence" in body["georef"]


# 16. /invert permitido sigue devolviendo r3_enrichment
def test_invert_allowed_returns_r3_enrichment(client, monkeypatch):
    import api.gravity_import_api as api_mod
    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
    monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)

    resp = _post_invert(
        client,
        _make_csv_utm(),
        extra_form={"utm_zone": "19S"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "r3_enrichment" in body, "r3_enrichment ausente en /invert permitido"
    assert "attempted" in body["r3_enrichment"]
