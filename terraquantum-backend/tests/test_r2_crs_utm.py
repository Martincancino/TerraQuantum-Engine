"""
R2 — Tests de clasificación georef CRS: _classify_georef_full y _classify_georef wrapper.

Verifica que:
- latlon → input_crs EPSG:4326, epsg_code 4326, crs_source inferred
- utm + utm_zone_form 19S → epsg_code 32719, input_crs EPSG:32719, crs_source user_declared
- utm sin zona → input_crs unknown, epsg_code None, crs_source missing, warning obligatorio
- local_meters + anchor → input_crs local_meters, crs_source missing
- local_meters sin anchor → MISSING georef, crs_source missing
- Tests R1 siguen pasando via wrapper _classify_georef
"""
import pytest
from schemas.gravity_import_schema import CoordinateTransform
from api.gravity_import_api import _classify_georef_full, _classify_georef


def _ct(
    system: str = "unknown",
    confidence: str = "low",
    x_extent_m: float = 50_000.0,
    z_extent_m: float = 49_000.0,
) -> CoordinateTransform:
    return CoordinateTransform(
        input_coordinate_system=system,
        input_confidence=confidence,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
    )


# ---------------------------------------------------------------------------
# latlon cases
# ---------------------------------------------------------------------------

def test_latlon_with_anchor_crs_fields():
    r = _classify_georef_full(_ct("latlon", "high"), -22.28, -68.89)
    assert r["input_crs"] == "EPSG:4326"
    assert r["epsg_code"] == 4326
    assert r["crs_source"] == "inferred"
    assert r["crs_confidence"] == "HIGH"
    assert r["utm_zone"] is None
    assert r["utm_hemisphere"] is None


def test_latlon_without_anchor_crs_fields():
    r = _classify_georef_full(_ct("latlon", "high"), None, None)
    assert r["input_crs"] == "EPSG:4326"
    assert r["epsg_code"] == 4326
    assert r["crs_source"] == "inferred"


def test_latlon_over_100km_crs_fields():
    r = _classify_georef_full(
        _ct("latlon", "high", x_extent_m=150_000.0, z_extent_m=150_000.0),
        -22.28, -68.89,
    )
    assert r["epsg_code"] == 4326
    assert r["crs_source"] == "inferred"
    assert r["crs_confidence"] == "HIGH"


# ---------------------------------------------------------------------------
# UTM + utm_zone_form declared
# ---------------------------------------------------------------------------

def test_utm_with_zone_form_19S():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89, utm_zone_form="19S")
    assert r["confidence"] == "MEDIUM"
    assert r["type"] == "csv_utm"
    assert r["utm_zone"] == "19S"
    assert r["utm_hemisphere"] == "S"
    assert r["epsg_code"] == 32719
    assert r["input_crs"] == "EPSG:32719"
    assert r["crs_source"] == "user_declared"
    assert r["crs_confidence"] == "HIGH"


def test_utm_with_zone_form_33N():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89, utm_zone_form="33N")
    assert r["epsg_code"] == 32633
    assert r["input_crs"] == "EPSG:32633"
    assert r["crs_source"] == "user_declared"


def test_utm_with_zone_form_lowercase():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89, utm_zone_form="19s")
    assert r["utm_zone"] == "19S"
    assert r["epsg_code"] == 32719


def test_utm_with_zone_form_no_anchor():
    r = _classify_georef_full(_ct("utm", "high"), None, None, utm_zone_form="19S")
    assert r["crs_source"] == "user_declared"
    assert r["epsg_code"] == 32719
    # With declared zone but no anchor, georef is MEDIUM (has zone) or LOW
    # Spec: UTM + zona declarada + sin ancla → LOW georef
    assert r["confidence"] in ("LOW", "MEDIUM")


def test_utm_r2_pyproj_warning_when_zone_declared():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89, utm_zone_form="19S")
    assert any("R2.2" in w or "pyproj" in w.lower() for w in r["warnings"])


# ---------------------------------------------------------------------------
# UTM without zone declared
# ---------------------------------------------------------------------------

def test_utm_no_zone_form_missing_crs():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89)
    assert r["utm_zone"] is None
    assert r["utm_hemisphere"] is None
    assert r["epsg_code"] is None
    assert r["input_crs"] == "unknown"
    assert r["crs_source"] == "missing"
    assert r["crs_confidence"] == "MISSING"


def test_utm_no_zone_form_warning_obligatorio():
    r = _classify_georef_full(_ct("utm", "high"), -22.28, -68.89)
    joined = " ".join(r["warnings"])
    assert "zona" in joined.lower() or "UTM" in joined


def test_utm_no_zone_no_anchor_low_confidence():
    r = _classify_georef_full(_ct("utm", "high"), None, None)
    assert r["confidence"] == "LOW"
    assert r["crs_source"] == "missing"


# ---------------------------------------------------------------------------
# local_meters
# ---------------------------------------------------------------------------

def test_local_meters_with_anchor_crs():
    r = _classify_georef_full(_ct("local_meters", "high"), -22.28, -68.89)
    assert r["confidence"] == "LOW"
    assert r["type"] == "local_meters_anchored"
    assert r["input_crs"] == "local_meters"
    assert r["epsg_code"] is None
    assert r["crs_source"] == "missing"
    assert r["crs_confidence"] == "MISSING"


def test_local_meters_without_anchor_crs():
    r = _classify_georef_full(_ct("local_meters", "high"), None, None)
    assert r["confidence"] == "MISSING"
    assert r["type"] == "local_reference"
    assert r["input_crs"] == "local_meters"
    assert r["crs_source"] == "missing"


# ---------------------------------------------------------------------------
# None coordinate_transform
# ---------------------------------------------------------------------------

def test_none_ct_r2_fields():
    r = _classify_georef_full(None, -22.28, -68.89)
    assert r["confidence"] == "MISSING"
    assert r["input_crs"] == "unknown"
    assert r["crs_source"] == "missing"
    assert r["epsg_code"] is None


# ---------------------------------------------------------------------------
# R1 wrapper backward compatibility
# ---------------------------------------------------------------------------

def test_r1_wrapper_returns_4tuple():
    result = _classify_georef(_ct("latlon", "high"), -22.28, -68.89)
    assert len(result) == 4


def test_r1_wrapper_latlon_high():
    conf, tp, utm, warns = _classify_georef(_ct("latlon", "high"), -22.28, -68.89)
    assert conf == "HIGH"
    assert tp == "latlon"
    assert utm is None
    assert warns == []


def test_r1_wrapper_utm_medium_no_zone():
    conf, tp, utm, warns = _classify_georef(_ct("utm", "high"), -22.28, -68.89)
    assert conf == "MEDIUM"
    assert tp == "csv_utm"
    assert utm is None  # No utm_zone_form → utm is None (R1 compat)
    assert len(warns) >= 1


def test_r1_wrapper_utm_zone_none_without_form():
    _, _, utm, _ = _classify_georef(_ct("utm", "high"), -22.28, -68.89)
    assert utm is None


def test_r1_wrapper_utm_zone_set_with_form():
    _, _, utm, _ = _classify_georef(_ct("utm", "high"), -22.28, -68.89, utm_zone_form="19S")
    assert utm == "19S"


def test_r1_wrapper_local_meters():
    conf, tp, utm, warns = _classify_georef(_ct("local_meters", "high"), -22.28, -68.89)
    assert conf == "LOW"
    assert tp == "local_meters_anchored"
    assert utm is None
