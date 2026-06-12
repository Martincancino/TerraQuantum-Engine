import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.gravity_import_api import router
from core.rate_limit import limiter
from services.regional_scale_preflight_service import (
    classify_regional_scale_preflight,
)


def _classify(**updates):
    args = {
        "extent_x_m": 5_000.0,
        "extent_z_m": 4_500.0,
        "station_count": 24,
        "estimated_nx": 20,
        "estimated_ny": 8,
        "estimated_nz": 18,
        "estimated_voxel_count": 2_880,
        "estimated_depth_m": 3_000.0,
        "estimated_block_size_m": 250.0,
    }
    args.update(updates)
    return classify_regional_scale_preflight(**args)


@pytest.fixture()
def client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def isolated_api_tmp(tmp_path, monkeypatch):
    import api.gravity_import_api as api_mod

    monkeypatch.setattr(api_mod, "TMP_DIR", tmp_path)
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


def _latlon_csv(
    path: Path,
    *,
    lat_span: float,
    lon_span: float,
    rows: int = 12,
) -> Path:
    lines = ["station_id,lat,lon,unit,g_mgal,gravity_type"]
    for index in range(rows):
        fraction = index / max(rows - 1, 1)
        lat = -25.0 + (lat_span * fraction)
        lon = -70.0 + (lon_span * fraction)
        lines.append(
            f"st_{index},{lat:.8f},{lon:.8f},mGal,"
            f"{5.0 + index * 0.1:.3f},bouguer_anomaly"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _latlon_grid_csv(
    path: Path,
    *,
    lat_span: float = 2.0,
    lon_span: float = 20.0,
    n_lat: int = 10,
    n_lon: int = 100,
) -> Path:
    """Survey DENSO y alargado que genuinamente excede los límites por dimensión.

    El auto-grid scale-aware (HITO 5) deriva block_size del espaciamiento medio:
    un survey ralo de 10°×10° con 12 estaciones produce celdas de ~77 km y
    nx≈14 (clasifica REGIONAL_SCALE, no TOO_LARGE). Para ejercitar
    TOO_LARGE_SINGLE_INVERSION se necesita densidad real: 20°×2° con grilla
    100×10 → spacing ~21 km → block ~10 km → nx≈190 > 80, sin que R-10 lo
    reduzca (voxel_count queda muy bajo el límite por ny pequeño).
    """
    lines = ["station_id,lat,lon,unit,g_mgal,gravity_type"]
    idx = 0
    for i in range(n_lat):
        lat = -25.0 + lat_span * (i / max(n_lat - 1, 1))
        for j in range(n_lon):
            lon = -70.0 + lon_span * (j / max(n_lon - 1, 1))
            lines.append(
                f"st_{idx},{lat:.8f},{lon:.8f},mGal,"
                f"{5.0 + (idx % 50) * 0.1:.3f},bouguer_anomaly"
            )
            idx += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _post_preview(client: TestClient, csv_path: Path):
    return client.post(
        "/gravity-import/preview",
        files={"file": (csv_path.name, io.BytesIO(csv_path.read_bytes()), "text/csv")},
    )


_INVERT_FORM = {
    "depth": "500",
    "nir": "20",
    "fe": "60",
    "region": "r37_test",
    "lat": "-25.0",
    "lon": "-70.0",
    "nx": "8",
    "ny": "4",
    "nz": "8",
    "block_size": "200",
    "cutoff_radius": "600.0",
    "lambda_mag": "1.0",
    "alpha_spatial": "1.0",
    "strict": "true",
    "allow_g_raw": "false",
}


def _post_invert(client: TestClient, csv_path: Path):
    return client.post(
        "/gravity-import/invert",
        data=_INVERT_FORM,
        files={"file": (csv_path.name, io.BytesIO(csv_path.read_bytes()), "text/csv")},
    )


def test_local_survey_allows_single_inversion():
    preflight = _classify()

    assert preflight.scale_class == "LOCAL_SURVEY"
    assert preflight.can_run_single_inversion is True
    assert preflight.requires_user_acknowledgement is False
    assert "single_inversion" in preflight.allowed_outputs


def test_district_scale_warns_but_is_allowed():
    preflight = _classify(
        extent_x_m=20_000.0,
        extent_z_m=18_000.0,
        estimated_depth_m=12_000.0,
    )

    assert preflight.scale_class == "DISTRICT_SCALE"
    assert preflight.can_run_single_inversion is True
    assert any("distrital" in warning.lower() for warning in preflight.warnings)


def test_regional_scale_warns_and_requires_acknowledgement():
    preflight = _classify(
        extent_x_m=80_000.0,
        extent_z_m=72_000.0,
        estimated_depth_m=48_000.0,
    )

    assert preflight.scale_class == "REGIONAL_SCALE"
    assert preflight.can_run_single_inversion is True
    assert preflight.requires_user_acknowledgement is True
    assert preflight.warnings
    assert any("regional" in warning.lower() for warning in preflight.warnings)


@pytest.mark.parametrize(
    ("axis", "reason_fragment"),
    [
        ("estimated_nx", "estimated_nx"),
        ("estimated_ny", "estimated_ny"),
        ("estimated_nz", "estimated_nz"),
    ],
)
def test_dimension_overflow_is_too_large_single_inversion(axis, reason_fragment):
    preflight = _classify(**{axis: 81})

    assert preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight.can_run_single_inversion is False
    assert preflight.blocked_reasons
    assert any(reason_fragment in reason for reason in preflight.blocked_reasons)
    assert "subset" in preflight.recommended_action.lower()
    assert "tile" in preflight.recommended_action.lower()
    assert "single_inversion" not in preflight.allowed_outputs


def test_unknown_scale_when_extent_is_absent():
    preflight = _classify(extent_x_m=None, extent_z_m=None)

    assert preflight.scale_class == "UNKNOWN_SCALE"
    assert preflight.can_run_single_inversion is True
    assert preflight.warnings


def test_depth_over_5000_adds_local_model_warning():
    preflight = _classify(estimated_depth_m=5_001.0)

    assert any("modelo minero local" in warning.lower() for warning in preflight.warnings)


def test_depth_over_20000_adds_strong_regional_warning():
    preflight = _classify(estimated_depth_m=20_001.0)

    assert any("escala regional" in warning.lower() for warning in preflight.warnings)


def test_allowed_outputs_are_coherent_for_local_and_too_large():
    local_preflight = _classify()
    too_large_preflight = _classify(estimated_nx=90)

    assert "single_inversion" in local_preflight.allowed_outputs
    assert {"subset", "tile"}.issubset(set(too_large_preflight.allowed_outputs))
    assert "single_inversion" not in too_large_preflight.allowed_outputs


def test_preview_includes_preflight_and_preserves_status_and_spatial_readiness(
    client,
    tmp_path,
):
    csv_path = _latlon_csv(tmp_path / "local_preview.csv", lat_span=0.02, lon_span=0.02)

    response = _post_preview(client, csv_path)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["auto_grid"] is not None
    assert body["regional_scale_preflight"]["scale_class"] == "LOCAL_SURVEY"
    assert body["regional_scale_preflight"]["version"] == "regional_scale_preflight_v0_1"
    assert body["spatial_readiness"]["level"] == "GEOGRAPHIC_COORDS"


def test_preview_full_like_reports_too_large_without_blocking_preview(client, tmp_path):
    csv_path = _latlon_grid_csv(tmp_path / "full_like.csv")

    response = _post_preview(client, csv_path)

    assert response.status_code == 200, response.text
    body = response.json()
    preflight = body["regional_scale_preflight"]
    assert body["status"] == "ok"
    assert preflight["scale_class"] == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight["can_run_single_inversion"] is False
    assert preflight["blocked_reasons"]
    assert any("estimated_nx" in reason or "estimated_nz" in reason for reason in preflight["blocked_reasons"])
    assert "subset" in preflight["recommended_action"].lower()
    assert "tile" in preflight["recommended_action"].lower()
    assert body["spatial_readiness"]["level"] == "GEOGRAPHIC_COORDS"


def test_preview_subset_like_reports_regional_scale(client, tmp_path):
    csv_path = _latlon_csv(tmp_path / "subset_like.csv", lat_span=0.8, lon_span=0.8)

    response = _post_preview(client, csv_path)

    assert response.status_code == 200, response.text
    body = response.json()
    preflight = body["regional_scale_preflight"]
    assert preflight["scale_class"] == "REGIONAL_SCALE"
    assert preflight["can_run_single_inversion"] is True
    assert preflight["estimated_nx"] <= preflight["max_allowed_nx"]
    assert preflight["estimated_nz"] <= preflight["max_allowed_nz"]
    assert preflight["warnings"]


def test_regional_subset_invert_runs_with_r37_acknowledgement(client, tmp_path, monkeypatch):
    # R3.7-C: REGIONAL_SCALE requires acknowledge_regional_scale=True to proceed.
    import api.gravity_import_api as api_mod

    csv_path = _latlon_csv(tmp_path / "subset_invert.csv", lat_span=0.8, lon_span=0.8)
    monkeypatch.setattr(
        api_mod,
        "run_geophysics_inversion",
        lambda *_args, **_kwargs: {"status": "done", "mock": True},
    )

    response = client.post(
        "/gravity-import/invert",
        data={**_INVERT_FORM, "acknowledge_regional_scale": "true"},
        files={"file": (csv_path.name, io.BytesIO(csv_path.read_bytes()), "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"


def test_full_like_invert_blocked_by_r37_too_large_gate(
    client,
    tmp_path,
    monkeypatch,
):
    # R3.7-C: TOO_LARGE_SINGLE_INVERSION fires before schema validation now.
    import api.gravity_import_api as api_mod

    csv_path = _latlon_grid_csv(tmp_path / "full_invert.csv")

    def _solver_must_not_run(*_args, **_kwargs):
        pytest.fail("TOO_LARGE CSV should be blocked by R3.7 gate before solver")

    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _solver_must_not_run)

    response = _post_invert(client, csv_path)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail.get("error") == "REGIONAL_SCALE_PREFLIGHT"
    assert detail.get("scale_class") == "TOO_LARGE_SINGLE_INVERSION"


# ---------------------------------------------------------------------------
# R3.7-F1 — subset/tile helper tests
# ---------------------------------------------------------------------------


def test_too_large_suggested_tile_size_is_not_null():
    preflight = _classify(estimated_nx=90)
    assert preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight.suggested_tile_size_m is not None
    assert preflight.suggested_tile_size_m > 0


def test_too_large_suggested_subset_bbox_is_not_null_when_extents_exist():
    preflight = _classify(
        extent_x_m=250_000.0,
        extent_z_m=200_000.0,
        estimated_nx=90,
    )
    assert preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight.suggested_subset_bbox is not None
    bbox = preflight.suggested_subset_bbox
    assert "x_min_m" in bbox
    assert "x_max_m" in bbox
    assert "z_min_m" in bbox
    assert "z_max_m" in bbox
    assert bbox["x_max_m"] > bbox["x_min_m"]
    assert bbox["z_max_m"] > bbox["z_min_m"]


def test_regional_scale_recommended_action_mentions_subset_or_tile():
    preflight = _classify(
        extent_x_m=80_000.0,
        extent_z_m=72_000.0,
        estimated_depth_m=48_000.0,
    )
    assert preflight.scale_class == "REGIONAL_SCALE"
    action_lower = preflight.recommended_action.lower()
    assert "subset" in action_lower or "tile" in action_lower


def test_local_survey_has_no_suggested_tile_size():
    preflight = _classify()
    assert preflight.scale_class == "LOCAL_SURVEY"
    assert preflight.suggested_tile_size_m is None


def test_preview_full_like_includes_suggested_tile_size_m(client, tmp_path):
    csv_path = _latlon_grid_csv(tmp_path / "full_tile.csv")
    response = _post_preview(client, csv_path)
    assert response.status_code == 200
    preflight = response.json()["regional_scale_preflight"]
    assert preflight["scale_class"] == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight["suggested_tile_size_m"] is not None
    assert preflight["suggested_tile_size_m"] > 0


def test_preview_full_like_includes_suggested_subset_bbox(client, tmp_path):
    csv_path = _latlon_grid_csv(tmp_path / "full_bbox.csv")
    response = _post_preview(client, csv_path)
    assert response.status_code == 200
    preflight = response.json()["regional_scale_preflight"]
    assert preflight["scale_class"] == "TOO_LARGE_SINGLE_INVERSION"
    bbox = preflight["suggested_subset_bbox"]
    assert bbox is not None
    assert "x_min_m" in bbox and "x_max_m" in bbox
    assert "z_min_m" in bbox and "z_max_m" in bbox


def test_preview_full_like_recommended_action_mentions_subset_and_tile(client, tmp_path):
    csv_path = _latlon_csv(tmp_path / "full_action.csv", lat_span=10.0, lon_span=10.0)
    response = _post_preview(client, csv_path)
    assert response.status_code == 200
    preflight = response.json()["regional_scale_preflight"]
    action = preflight["recommended_action"].lower()
    assert "subset" in action
    assert "tile" in action


def test_too_large_warnings_include_approximate_bbox_note():
    preflight = _classify(
        extent_x_m=250_000.0,
        extent_z_m=200_000.0,
        estimated_nx=90,
    )
    assert preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION"
    assert preflight.suggested_subset_bbox is not None
    assert any("aproximad" in w.lower() for w in preflight.warnings)
