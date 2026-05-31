"""
R3.5-E — SpatialReadiness caps on favorability score and priority_class.

Tests _apply_spatial_readiness_caps directly and verifies that
gravity_import_api passes spatial_readiness into auto_params_metadata.
"""
import io
import pytest

from services.geophysics_service import _apply_spatial_readiness_caps, PriorityClass
from schemas.gravity_import_schema import (
    SPATIAL_LEVEL_MAX_FAVORABILITY,
    SPATIAL_LEVEL_MAX_PRIORITY,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_rate_limit():
    from core.rate_limit import limiter
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_sr(level: str) -> dict:
    """Minimal spatial_readiness dict for a given level."""
    return {
        "level": level,
        "max_favorability_score_allowed": SPATIAL_LEVEL_MAX_FAVORABILITY[level],
        "max_priority_class_allowed": SPATIAL_LEVEL_MAX_PRIORITY[level],
    }


def _make_report(score: float, priority: str) -> dict:
    """Minimal report_payload for testing caps."""
    return {
        "favorability": {
            "score": score,
            "level": "MUY ALTO",
            "warnings": [],
        },
        "priority_class": priority,
        "existing_field": "should_be_preserved",
    }


def _make_csv_local_meters_bytes(rows: int = 10) -> bytes:
    lines = ["station_id,x_m,y_m,z_m,unit,gravity_anomaly,gravity_type"]
    for i in range(rows):
        lines.append(
            f"st_{i},{1000 + i * 200},0,{2000 + i * 200},"
            f"mGal,{10.0 + i * 0.5},bouguer_anomaly"
        )
    return "\n".join(lines).encode()


# ── Score cap tests ───────────────────────────────────────────────────────────

def test_local_anchored_center_caps_score_80_to_45():
    report = _make_report(80.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["score"] == 45.0


def test_local_anchored_center_score_below_max_not_capped():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["score"] == 30.0


def test_local_unanchored_caps_score_70_to_45():
    report = _make_report(70.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_UNANCHORED"))
    assert report["favorability"]["score"] == 45.0


def test_utm_no_zone_caps_score_80_to_60():
    report = _make_report(80.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("UTM_NO_ZONE"))
    assert report["favorability"]["score"] == 60.0


def test_utm_with_zone_caps_score_90_to_85():
    report = _make_report(90.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("UTM_WITH_ZONE"))
    assert report["favorability"]["score"] == 85.0


def test_geographic_coords_score_90_not_capped():
    report = _make_report(90.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("GEOGRAPHIC_COORDS"))
    assert report["favorability"]["score"] == 90.0


def test_professional_survey_score_100_not_capped():
    report = _make_report(100.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("PROFESSIONAL_SURVEY"))
    assert report["favorability"]["score"] == 100.0


def test_score_exactly_at_cap_not_capped():
    """Score == max_fav must NOT be capped (only strictly greater)."""
    report = _make_report(45.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["score"] == 45.0


# ── Level recalculation ───────────────────────────────────────────────────────

def test_level_recalculated_after_score_cap():
    """When score 80 is capped to 45 (LOCAL_ANCHORED_CENTER), level must reflect 45."""
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["level"] == "BAJO"


def test_level_not_changed_when_no_cap():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    report["favorability"]["level"] = "BAJO"
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["level"] == "BAJO"


# ── Priority cap tests ────────────────────────────────────────────────────────

def test_local_anchored_center_caps_high_priority_to_low():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["priority_class"] == "LOW_RELATIVE_PRIORITY"


def test_local_anchored_center_caps_medium_priority_to_low():
    report = _make_report(80.0, "MEDIUM_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["priority_class"] == "LOW_RELATIVE_PRIORITY"


def test_utm_no_zone_caps_medium_priority_to_low():
    report = _make_report(80.0, "MEDIUM_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("UTM_NO_ZONE"))
    assert report["priority_class"] == "LOW_RELATIVE_PRIORITY"


def test_utm_with_zone_high_priority_not_capped():
    report = _make_report(90.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("UTM_WITH_ZONE"))
    assert report["priority_class"] == "HIGH_RELATIVE_PRIORITY"


def test_geographic_coords_high_priority_not_capped():
    report = _make_report(90.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("GEOGRAPHIC_COORDS"))
    assert report["priority_class"] == "HIGH_RELATIVE_PRIORITY"


def test_low_priority_not_degraded_further_at_low_cap():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["priority_class"] == "LOW_RELATIVE_PRIORITY"


# ── spatial_readiness_cap metadata ───────────────────────────────────────────

def test_cap_applied_true_when_score_exceeds_max():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["applied"] is True


def test_cap_applied_false_when_score_within_max():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["applied"] is False


def test_cap_metadata_original_score_preserved():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["original_favorability_score"] == 80.0


def test_cap_metadata_capped_score_equals_max():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["capped_favorability_score"] == 45.0
    assert cap["max_favorability_score_allowed"] == 45.0


def test_cap_metadata_level_field_set():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["level"] == "LOCAL_ANCHORED_CENTER"


def test_cap_metadata_no_applied_has_original_equals_score():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    cap = report["favorability"]["spatial_readiness_cap"]
    assert cap["original_favorability_score"] == cap["capped_favorability_score"]


# ── Warnings ──────────────────────────────────────────────────────────────────

def test_warning_added_to_priority_class_warnings_when_cap_applied():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    warnings = report.get("priority_class_warnings", [])
    assert len(warnings) > 0


def test_warning_added_to_favorability_warnings_when_score_capped():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    fav_warnings = report["favorability"]["warnings"]
    assert len(fav_warnings) > 0


def test_no_warning_when_no_cap_applied():
    report = _make_report(30.0, "LOW_RELATIVE_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    warnings = report.get("priority_class_warnings", [])
    assert len(warnings) == 0


# ── Robustness ────────────────────────────────────────────────────────────────

def test_none_spatial_readiness_does_not_crash():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    result = _apply_spatial_readiness_caps(report, None)
    assert result["favorability"]["score"] == 80.0


def test_malformed_spatial_readiness_non_numeric_max_does_not_crash():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    result = _apply_spatial_readiness_caps(
        report, {"max_favorability_score_allowed": "not_a_number"}
    )
    assert result["favorability"]["score"] == 80.0


def test_malformed_spatial_readiness_empty_dict_does_not_crash():
    """Empty dict: max_fav defaults to 100 → no score cap."""
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    result = _apply_spatial_readiness_caps(report, {})
    assert result["favorability"]["score"] == 80.0


def test_unknown_priority_class_does_not_crash():
    """Unknown priority string: rank -1 < max rank → no priority cap."""
    report = _make_report(80.0, "TOTALLY_UNKNOWN_PRIORITY")
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    # Score is still capped
    assert report["favorability"]["score"] == 45.0
    # Priority stays as-is (unknown rank -1 is not > LOW rank 2)
    assert report["priority_class"] == "TOTALLY_UNKNOWN_PRIORITY"


def test_existing_fields_preserved_after_cap():
    report = _make_report(80.0, "HIGH_RELATIVE_PRIORITY")
    report["some_other_field"] = "intact"
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["some_other_field"] == "intact"
    assert report["existing_field"] == "should_be_preserved"


def test_missing_favorability_key_does_not_crash():
    """report_payload without favorability key must not raise."""
    report = {"priority_class": "HIGH_RELATIVE_PRIORITY"}
    result = _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert result["priority_class"] == "LOW_RELATIVE_PRIORITY"


def test_favorability_without_warnings_list_does_not_crash():
    """favorability dict missing 'warnings' key must not raise."""
    report = {
        "favorability": {"score": 80.0, "level": "MUY ALTO"},
        "priority_class": "HIGH_RELATIVE_PRIORITY",
    }
    _apply_spatial_readiness_caps(report, _make_sr("LOCAL_ANCHORED_CENTER"))
    assert report["favorability"]["score"] == 45.0


# ── API wiring test ───────────────────────────────────────────────────────────

def test_gravity_import_api_passes_spatial_readiness_in_auto_params(monkeypatch):
    """Verify that /invert puts spatial_readiness into auto_params_metadata."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import router
    from core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=True)

    captured: list = []

    def _spy(params):
        captured.append(params)
        return {"voxels": [], "best_target": None, "report": {}, "misfit_error_percent": 0.0}

    monkeypatch.setattr(api_mod, "run_geophysics_inversion", _spy)
    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: None)
    monkeypatch.setattr(
        api_mod,
        "enrich_block_model_with_elevation",
        lambda *a, **kw: {"status": "ok", "has_elevation_data": False, "warnings": []},
    )

    csv_bytes = _make_csv_local_meters_bytes()
    form = {
        "depth": "500",
        "nir": "20",
        "fe": "60",
        "region": "test",
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
        "acknowledge_spatial_risk": "true",
    }
    resp = client.post(
        "/gravity-import/invert",
        data=form,
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    assert len(captured) == 1, "run_geophysics_inversion should have been called once"

    params = captured[0]
    assert params.auto_params_metadata is not None
    assert "spatial_readiness" in params.auto_params_metadata, (
        "spatial_readiness must be present in auto_params_metadata"
    )
    sr = params.auto_params_metadata["spatial_readiness"]
    assert isinstance(sr, dict)
    assert "level" in sr
    assert "max_favorability_score_allowed" in sr
    assert "max_priority_class_allowed" in sr
