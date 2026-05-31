"""
R2.3 — Tests for compute_utm_footprint_with_pyproj and approx_dist_km.

Reference: Atacama Chile, UTM zone 19S (EPSG:32719).
  lat_ref = -22.28, lon_ref = -68.89
"""
import math
import pytest

from services.coordinate_transform_real import (
    approx_dist_km,
    compute_utm_footprint_with_pyproj,
    transform_wgs84_to_utm,
)

LAT_REF = -22.28
LON_REF = -68.89
EPSG_19S = 32719
DELTA_M = 25_000  # 25 km half-extent → 50 km bbox


def _chile_bbox() -> dict:
    """Derive a 50×50 km UTM bbox centered at reference point."""
    e0, n0 = transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=EPSG_19S)
    return {
        "min_easting": e0 - DELTA_M,
        "max_easting": e0 + DELTA_M,
        "min_northing": n0 - DELTA_M,
        "max_northing": n0 + DELTA_M,
    }


# ---------------------------------------------------------------------------
# 1. Helper returns bbox with sw/se/ne/nw
# ---------------------------------------------------------------------------

def test_footprint_has_all_four_corners():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    for corner in ("sw", "se", "ne", "nw"):
        assert fp[corner] is not None
        assert math.isfinite(fp[corner]["lat"])
        assert math.isfinite(fp[corner]["lon"])


# ---------------------------------------------------------------------------
# 2. UTM 19S Chile produces lat/lon in reasonable ranges
# ---------------------------------------------------------------------------

def test_footprint_center_lat_in_chile_range():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert -60.0 <= fp["center_lat"] <= -15.0, f"center_lat={fp['center_lat']}"


def test_footprint_center_lon_in_chile_range():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert -76.0 <= fp["center_lon"] <= -60.0, f"center_lon={fp['center_lon']}"


def test_footprint_all_corners_in_chile_range():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    for corner in ("sw", "se", "ne", "nw"):
        assert -60.0 <= fp[corner]["lat"] <= -15.0
        assert -76.0 <= fp[corner]["lon"] <= -60.0


# ---------------------------------------------------------------------------
# 3. footprint.source == "utm_pyproj"
# ---------------------------------------------------------------------------

def test_footprint_source_is_utm_pyproj():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert fp["source"] == "utm_pyproj"


# ---------------------------------------------------------------------------
# 4. footprint.epsg_code == 32719
# ---------------------------------------------------------------------------

def test_footprint_epsg_code_from_epsg_param():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert fp["epsg_code"] == EPSG_19S


def test_footprint_epsg_code_from_zone_string():
    fp = compute_utm_footprint_with_pyproj(utm_zone="19S", **_chile_bbox())
    assert fp["epsg_code"] == EPSG_19S


# ---------------------------------------------------------------------------
# 5. precision_notes mentions pyproj
# ---------------------------------------------------------------------------

def test_footprint_precision_notes_mention_pyproj():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    joined = " ".join(fp["precision_notes"]).lower()
    assert "pyproj" in joined


# ---------------------------------------------------------------------------
# 6. center_lat/center_lon finite
# ---------------------------------------------------------------------------

def test_footprint_center_lat_finite():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert math.isfinite(fp["center_lat"])


def test_footprint_center_lon_finite():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert math.isfinite(fp["center_lon"])


# ---------------------------------------------------------------------------
# 7. extent_x_m / extent_z_m correct
# ---------------------------------------------------------------------------

def test_footprint_extent_x_m_correct():
    bbox = _chile_bbox()
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **bbox)
    expected = bbox["max_easting"] - bbox["min_easting"]
    assert abs(fp["extent_x_m"] - expected) < 1.0


def test_footprint_extent_z_m_correct():
    bbox = _chile_bbox()
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **bbox)
    expected = bbox["max_northing"] - bbox["min_northing"]
    assert abs(fp["extent_z_m"] - expected) < 1.0


# ---------------------------------------------------------------------------
# 8. Anchor lat/lon consistent (≤5 km) — approx_dist_km test
# ---------------------------------------------------------------------------

def test_approx_dist_km_same_point():
    assert approx_dist_km(LAT_REF, LON_REF, LAT_REF, LON_REF) < 0.001


def test_approx_dist_km_one_degree_lat():
    # 1 degree latitude ≈ 111.32 km
    dist = approx_dist_km(0.0, 0.0, 1.0, 0.0)
    assert abs(dist - 111.32) < 1.0


def test_approx_dist_km_symmetry():
    d1 = approx_dist_km(LAT_REF, LON_REF, -22.0, -68.0)
    d2 = approx_dist_km(-22.0, -68.0, LAT_REF, LON_REF)
    assert abs(d1 - d2) < 1e-9


def test_anchor_consistent_under_5km():
    """Anchor consistent with pyproj center → distance < 5 km."""
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    dist = approx_dist_km(LAT_REF, LON_REF, fp["center_lat"], fp["center_lon"])
    # pyproj center should be very close to the reference point used to build the bbox
    assert dist < 5.0


# ---------------------------------------------------------------------------
# 9. Anchor lat/lon very far (>5 km) — should exceed threshold
# ---------------------------------------------------------------------------

def test_anchor_far_exceeds_5km_threshold():
    """Anchor 50 km away should exceed the 5 km warning threshold."""
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    # Use a point ~50 km north of the actual center
    fake_lat = LAT_REF + 0.45  # ~50 km northward
    dist = approx_dist_km(fake_lat, LON_REF, fp["center_lat"], fp["center_lon"])
    assert dist > 5.0


# ---------------------------------------------------------------------------
# 10. fallback: missing epsg/zone raises ValueError (not crash)
# ---------------------------------------------------------------------------

def test_missing_crs_raises_value_error():
    with pytest.raises((ValueError, RuntimeError)):
        compute_utm_footprint_with_pyproj(
            min_easting=500_000,
            max_easting=550_000,
            min_northing=7_500_000,
            max_northing=7_550_000,
            # no epsg_code and no utm_zone → _resolve_epsg raises ValueError
        )


def test_zone_string_and_epsg_produce_same_center():
    """utm_zone='19S' and epsg_code=32719 must produce identical results."""
    bbox = _chile_bbox()
    fp_z = compute_utm_footprint_with_pyproj(utm_zone="19S", **bbox)
    fp_e = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **bbox)
    assert abs(fp_z["center_lat"] - fp_e["center_lat"]) < 1e-9
    assert abs(fp_z["center_lon"] - fp_e["center_lon"]) < 1e-9


def test_footprint_crs_source_preserved():
    fp = compute_utm_footprint_with_pyproj(
        epsg_code=EPSG_19S, crs_source="user_declared", **_chile_bbox()
    )
    assert fp["crs_source"] == "user_declared"


def test_footprint_utm_hemisphere_south():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert fp["utm_hemisphere"] == "S"


def test_footprint_utm_zone_string():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert fp["utm_zone"] == "19S"


def test_footprint_crs_is_wgs84():
    fp = compute_utm_footprint_with_pyproj(epsg_code=EPSG_19S, **_chile_bbox())
    assert fp["crs"] == "EPSG:4326"
