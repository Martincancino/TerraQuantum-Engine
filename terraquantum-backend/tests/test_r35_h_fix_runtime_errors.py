"""
R3.5-H-FIX1 runtime error coverage for /gravity-import/invert.

Verifies:
  - user input ValueError from geophysics inversion becomes HTTP 422, not 500
  - import-stage errors include spatial_readiness
  - preview keeps returning spatial_readiness
  - the SPATIAL_READINESS_GATE still blocks unacknowledged risky runs
"""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.gravity_import_api import router
from core.rate_limit import limiter


@pytest.fixture()
def client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_rate_limit():
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


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


def _make_csv_local_meters(rows: int = 10) -> bytes:
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(
            f"st_{i},{1000 + i * 200},0,{2000 + i * 200},mGal,"
            f"{10.0 + i * 0.5},bouguer_anomaly"
        )
    return "\n".join(lines).encode()


def _make_csv_without_coordinates(rows: int = 10) -> bytes:
    lines = ["station_id,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},mGal,{10.0 + i * 0.5},bouguer_anomaly")
    return "\n".join(lines).encode()


def _post_invert(
    client: TestClient,
    csv_bytes: bytes,
    extra_form: dict | None = None,
    filename: str = "test.csv",
):
    form = dict(_INVERT_BASE_FORM)
    if extra_form:
        form.update(extra_form)
    return client.post(
        "/gravity-import/invert",
        data=form,
        files={"file": (filename, io.BytesIO(csv_bytes), "text/csv")},
    )


def _post_preview(client: TestClient, csv_bytes: bytes, filename: str = "test.csv"):
    return client.post(
        "/gravity-import/preview",
        files={"file": (filename, io.BytesIO(csv_bytes), "text/csv")},
    )


def _mock_inversion(*args, **kwargs):
    return {"status": "done", "blocks": [], "mock": True}


def test_invert_invalid_lat_ack_true_returns_422_not_500(client):
    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "999", "acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code != 500, resp.text
    assert resp.status_code == 422, resp.text


def test_invert_invalid_lat_detail_has_geophysics_validation_error(client):
    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"lat": "999", "acknowledge_spatial_risk": "true"},
    )
    detail = resp.json()["detail"]
    assert detail["error"] == "GEOPHYSICS_INPUT_VALIDATION"
    assert "lat" in detail["message"].lower()
    assert "-90" in detail["message"] or "90" in detail["message"]
    assert "spatial_readiness" in detail


def test_invert_valid_parameters_still_returns_200(client, monkeypatch):
    import api.gravity_import_api as api_mod

    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)

    resp = _post_invert(
        client,
        _make_csv_local_meters(),
        extra_form={"acknowledge_spatial_risk": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


def test_invert_import_error_without_coordinates_includes_spatial_readiness(client):
    resp = _post_invert(client, _make_csv_without_coordinates())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "error"
    assert body["stage"] == "import"
    assert "spatial_readiness" in body
    assert body["spatial_readiness"]["level"] == "NO_SPATIAL_DATA"


def test_preview_still_includes_spatial_readiness(client):
    resp = _post_preview(client, _make_csv_without_coordinates())
    assert resp.status_code == 200, resp.text
    assert "spatial_readiness" in resp.json()


def test_spatial_readiness_gate_still_blocks_without_ack(client, monkeypatch):
    import api.gravity_import_api as api_mod

    solver_calls = []

    def _solver_spy(*args, **kwargs):
        solver_calls.append(1)
        return _mock_inversion(*args, **kwargs)

    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _solver_spy)

    resp = _post_invert(client, _make_csv_local_meters())
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "SPATIAL_READINESS_GATE"
    assert solver_calls == []
