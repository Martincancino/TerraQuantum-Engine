import math

import pytest

from services.geo_utils import METERS_PER_DEG_LAT, compute_bbox, compute_footprint_from_center


def _bbox_size(bbox):
    return bbox["max_lat"] - bbox["min_lat"], bbox["max_lon"] - bbox["min_lon"]


def test_compute_bbox_typical_chile_coordinates():
    bbox = compute_bbox(
        center_lat=-22.28,
        center_lon=-68.89,
        extent_x_m=50_000.0,
        extent_z_m=50_000.0,
    )

    lat_span, lon_span = _bbox_size(bbox)

    assert bbox["min_lat"] < -22.28 < bbox["max_lat"]
    assert bbox["min_lon"] < -68.89 < bbox["max_lon"]
    assert lat_span == pytest.approx((50_000.0 * 1.2) / METERS_PER_DEG_LAT)
    assert lon_span == pytest.approx(
        (50_000.0 * 1.2)
        / (METERS_PER_DEG_LAT * abs(math.cos(math.radians(-22.28))))
    )


def test_compute_bbox_zero_extent_is_degenerate_without_crashing():
    bbox = compute_bbox(
        center_lat=-22.28,
        center_lon=-68.89,
        extent_x_m=0.0,
        extent_z_m=0.0,
    )

    assert bbox == {
        "min_lat": -22.28,
        "max_lat": -22.28,
        "min_lon": -68.89,
        "max_lon": -68.89,
    }


def test_compute_bbox_at_equator_lon_offset_matches_lat_offset_for_equal_extents():
    bbox = compute_bbox(
        center_lat=0.0,
        center_lon=-68.89,
        extent_x_m=10_000.0,
        extent_z_m=10_000.0,
    )

    lat_span, lon_span = _bbox_size(bbox)

    assert lon_span == pytest.approx(lat_span)


def test_compute_bbox_near_pole_keeps_finite_longitude_offset():
    bbox = compute_bbox(
        center_lat=89.0,
        center_lon=0.0,
        extent_x_m=10_000.0,
        extent_z_m=10_000.0,
    )

    lat_span, lon_span = _bbox_size(bbox)

    assert math.isfinite(lon_span)
    assert lon_span > lat_span

    pole_bbox = compute_bbox(
        center_lat=90.0,
        center_lon=0.0,
        extent_x_m=10_000.0,
        extent_z_m=10_000.0,
    )

    assert math.isfinite(pole_bbox["min_lon"])
    assert math.isfinite(pole_bbox["max_lon"])


def test_compute_bbox_without_buffer_uses_exact_half_extent():
    bbox = compute_bbox(
        center_lat=0.0,
        center_lon=0.0,
        extent_x_m=10_000.0,
        extent_z_m=20_000.0,
        buffer=0.0,
    )

    assert bbox["min_lon"] == pytest.approx(-5_000.0 / METERS_PER_DEG_LAT)
    assert bbox["max_lon"] == pytest.approx(5_000.0 / METERS_PER_DEG_LAT)
    assert bbox["min_lat"] == pytest.approx(-10_000.0 / METERS_PER_DEG_LAT)
    assert bbox["max_lat"] == pytest.approx(10_000.0 / METERS_PER_DEG_LAT)


def test_compute_bbox_equal_extents_span_ratio_matches_latitude_cosine():
    center_lat = -35.0

    bbox = compute_bbox(
        center_lat=center_lat,
        center_lon=-70.0,
        extent_x_m=25_000.0,
        extent_z_m=25_000.0,
    )

    lat_span, lon_span = _bbox_size(bbox)

    assert lat_span / lon_span == pytest.approx(
        abs(math.cos(math.radians(center_lat)))
    )


# ---------------------------------------------------------------------------
# compute_footprint_from_center — R1 tests
# ---------------------------------------------------------------------------

def test_compute_footprint_from_center_returns_full_schema():
    fp = compute_footprint_from_center(-22.28, -68.89, 50_000.0, 49_000.0)
    assert fp["type"] == "bbox"
    assert fp["crs"] == "EPSG:4326"
    assert fp["confidence"] == "LOW"
    assert fp["source"] == "derived"
    for corner in ("sw", "se", "ne", "nw"):
        assert math.isfinite(fp[corner]["lat"])
        assert math.isfinite(fp[corner]["lon"])


def test_compute_footprint_from_center_includes_center_and_extents():
    fp = compute_footprint_from_center(-22.28, -68.89, 50_000.0, 49_000.0,
                                       source="local_meters_anchored",
                                       confidence="LOW")
    assert fp["center_lat"] == pytest.approx(-22.28)
    assert fp["center_lon"] == pytest.approx(-68.89)
    assert fp["extent_x_m"] == pytest.approx(50_000.0)
    assert fp["extent_z_m"] == pytest.approx(49_000.0)


def test_compute_footprint_from_center_corners_straddle_center():
    fp = compute_footprint_from_center(-22.28, -68.89, 50_000.0, 49_000.0)
    assert fp["sw"]["lat"] < -22.28 < fp["ne"]["lat"]
    assert fp["sw"]["lon"] < -68.89 < fp["ne"]["lon"]


def test_compute_footprint_from_center_missing_when_zero_extent():
    fp = compute_footprint_from_center(-22.28, -68.89, 0.0, 50_000.0)
    assert fp["type"] == "missing"
    assert fp["confidence"] == "MISSING"
    assert fp["center_lat"] is None


def test_compute_footprint_from_center_missing_when_negative_extent():
    fp = compute_footprint_from_center(-22.28, -68.89, -100.0, 50_000.0)
    assert fp["type"] == "missing"


def test_compute_footprint_from_center_missing_when_invalid_lat():
    fp = compute_footprint_from_center(float("nan"), -68.89, 50_000.0, 50_000.0)
    assert fp["type"] == "missing"
    assert fp["confidence"] == "MISSING"


def test_compute_footprint_from_center_precision_note_under_100km():
    fp = compute_footprint_from_center(-22.28, -68.89, 50_000.0, 50_000.0)
    assert any("100km" in n for n in fp["precision_notes"])
    assert fp["type"] == "bbox"


def test_compute_footprint_from_center_warns_over_100km():
    fp = compute_footprint_from_center(-22.28, -68.89, 150_000.0, 150_000.0)
    assert any(">100km" in n or "100km" in n for n in fp["precision_notes"])
    assert fp["type"] == "bbox"


def test_compute_footprint_from_center_carries_source_and_confidence():
    fp = compute_footprint_from_center(
        0.0, 0.0, 10_000.0, 10_000.0,
        source="latlon", confidence="HIGH",
    )
    assert fp["source"] == "latlon"
    assert fp["confidence"] == "HIGH"


def test_compute_footprint_from_center_carries_utm_zone():
    fp = compute_footprint_from_center(
        0.0, 0.0, 10_000.0, 10_000.0, utm_zone="19S"
    )
    assert fp["utm_zone"] == "19S"


def test_compute_footprint_from_center_carries_custom_warnings():
    fp = compute_footprint_from_center(
        0.0, 0.0, 10_000.0, 10_000.0,
        warnings=["custom warning"],
    )
    assert "custom warning" in fp["warnings"]
