"""
R1 georef contract tests — _classify_georef returns (confidence, type, utm_zone, warnings).

Tests are unit-level: they import _classify_georef directly and pass mock
CoordinateTransform objects (using the real schema for correctness).
"""
import pytest
from schemas.gravity_import_schema import CoordinateTransform
from api.gravity_import_api import _classify_georef


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
# Return signature
# ---------------------------------------------------------------------------

def test_classify_georef_returns_four_values():
    result = _classify_georef(_ct("latlon", "high"), -22.28, -68.89)
    assert len(result) == 4, "Must return (confidence, type, utm_zone, warnings)"


def test_classify_georef_returns_four_values_without_anchor():
    result = _classify_georef(_ct("local_meters", "high"), None, None)
    assert len(result) == 4


# ---------------------------------------------------------------------------
# latlon cases
# ---------------------------------------------------------------------------

def test_classify_georef_latlon_high_with_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("latlon", "high"), -22.28, -68.89)
    assert conf == "HIGH"
    assert tp == "latlon"
    assert utm is None
    assert warns == []


def test_classify_georef_latlon_medium_without_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("latlon", "high"), None, None)
    assert conf == "MEDIUM"
    assert tp == "latlon"
    assert utm is None
    assert any("anclaje" in w.lower() or "central" in w.lower() for w in warns)


def test_classify_georef_latlon_medium_when_extent_over_100km():
    conf, tp, utm, warns = _classify_georef(
        _ct("latlon", "high", x_extent_m=150_000.0, z_extent_m=150_000.0),
        -22.28, -68.89,
    )
    assert conf == "MEDIUM"
    assert tp == "latlon"
    assert any("100km" in w for w in warns)


def test_classify_georef_latlon_over_100km_without_anchor():
    conf, tp, utm, warns = _classify_georef(
        _ct("latlon", "high", x_extent_m=150_000.0, z_extent_m=150_000.0),
        None, None,
    )
    assert conf == "MEDIUM"
    assert len(warns) >= 2


# ---------------------------------------------------------------------------
# UTM cases
# ---------------------------------------------------------------------------

def test_classify_georef_utm_medium_with_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("utm", "high"), -22.28, -68.89)
    assert conf == "MEDIUM"
    assert tp == "csv_utm"
    assert utm is None
    assert len(warns) >= 1
    assert any("UTM" in w or "zona" in w.lower() for w in warns)


def test_classify_georef_utm_low_without_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("utm", "high"), None, None)
    assert conf == "LOW"
    assert tp == "csv_utm"
    assert utm is None
    assert len(warns) >= 2


def test_classify_georef_utm_utm_zone_always_none_in_r1():
    _, _, utm, _ = _classify_georef(_ct("utm", "high"), -22.28, -68.89)
    assert utm is None, "R1 does not auto-detect UTM zone — must be None"


# ---------------------------------------------------------------------------
# local_meters cases
# ---------------------------------------------------------------------------

def test_classify_georef_local_meters_low_with_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("local_meters", "high"), -22.28, -68.89)
    assert conf == "LOW"
    assert tp == "local_meters_anchored"
    assert utm is None
    assert len(warns) >= 1
    assert any("metros locales" in w.lower() or "orientación" in w.lower() for w in warns)


def test_classify_georef_local_meters_missing_without_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("local_meters", "high"), None, None)
    assert conf == "MISSING"
    assert tp == "local_reference"
    assert utm is None
    assert len(warns) >= 1


def test_classify_georef_local_meters_includes_unverified_correspondence_warning():
    _, _, _, warns = _classify_georef(_ct("local_meters", "high"), -22.28, -68.89)
    joined = " ".join(w.lower() for w in warns)
    assert "verificad" in joined or "matemáticamente" in joined


# ---------------------------------------------------------------------------
# unknown / fallback
# ---------------------------------------------------------------------------

def test_classify_georef_unknown_low_with_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("unknown", "low"), -22.28, -68.89)
    assert conf == "LOW"
    assert tp == "derived"
    assert utm is None
    assert len(warns) >= 1


def test_classify_georef_unknown_missing_without_anchor():
    conf, tp, utm, warns = _classify_georef(_ct("unknown", "low"), None, None)
    assert conf == "MISSING"
    assert tp == "local_reference"
    assert utm is None
    assert len(warns) >= 1


# ---------------------------------------------------------------------------
# None coordinate_transform
# ---------------------------------------------------------------------------

def test_classify_georef_none_ct_returns_missing():
    conf, tp, utm, warns = _classify_georef(None, -22.28, -68.89)
    assert conf == "MISSING"
    assert tp == "local_reference"
    assert utm is None
    assert len(warns) >= 1
