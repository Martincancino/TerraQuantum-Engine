"""
R2 — Tests: EPSG lookup, parse_utm_zone_string, validate_utm_easting_northing.
"""
import pytest
from services.coordinate_transform_real import (
    get_epsg_from_utm,
    parse_utm_zone_string,
    validate_utm_easting_northing,
)


# ---------------------------------------------------------------------------
# get_epsg_from_utm
# ---------------------------------------------------------------------------

def test_epsg_zone_19S():
    assert get_epsg_from_utm(19, "S") == 32719


def test_epsg_zone_19N():
    assert get_epsg_from_utm(19, "N") == 32619


def test_epsg_zone_1N():
    assert get_epsg_from_utm(1, "N") == 32601


def test_epsg_zone_60S():
    assert get_epsg_from_utm(60, "S") == 32760


def test_epsg_zone_33N():
    assert get_epsg_from_utm(33, "N") == 32633


def test_epsg_zone_20S():
    assert get_epsg_from_utm(20, "S") == 32720


def test_epsg_invalid_zone_zero():
    with pytest.raises(ValueError, match="1-60"):
        get_epsg_from_utm(0, "N")


def test_epsg_invalid_zone_61():
    with pytest.raises(ValueError, match="1-60"):
        get_epsg_from_utm(61, "S")


def test_epsg_invalid_hemisphere():
    with pytest.raises(ValueError, match="[Hh]emisferio|'N' o 'S'"):
        get_epsg_from_utm(19, "X")


def test_epsg_accepts_lowercase_hemisphere():
    assert get_epsg_from_utm(19, "s") == 32719
    assert get_epsg_from_utm(19, "n") == 32619


# ---------------------------------------------------------------------------
# parse_utm_zone_string
# ---------------------------------------------------------------------------

def test_parse_19S():
    n, h = parse_utm_zone_string("19S")
    assert n == 19 and h == "S"


def test_parse_19s_lowercase():
    n, h = parse_utm_zone_string("19s")
    assert n == 19 and h == "S"


def test_parse_33N():
    n, h = parse_utm_zone_string("33N")
    assert n == 33 and h == "N"


def test_parse_with_spaces():
    n, h = parse_utm_zone_string(" 33 n ")
    assert n == 33 and h == "N"


def test_parse_zone_1():
    n, h = parse_utm_zone_string("1N")
    assert n == 1 and h == "N"


def test_parse_zone_60():
    n, h = parse_utm_zone_string("60S")
    assert n == 60 and h == "S"


def test_parse_invalid_string_text():
    with pytest.raises(ValueError):
        parse_utm_zone_string("zona_invalida")


def test_parse_invalid_zone_99():
    with pytest.raises(ValueError):
        parse_utm_zone_string("99S")


def test_parse_invalid_zone_0():
    with pytest.raises(ValueError):
        parse_utm_zone_string("0N")


def test_parse_invalid_no_hemisphere():
    with pytest.raises(ValueError):
        parse_utm_zone_string("19")


# ---------------------------------------------------------------------------
# validate_utm_easting_northing
# ---------------------------------------------------------------------------

def test_validate_valid_returns_empty():
    warns = validate_utm_easting_northing(580_000, 5_650_000, 19, "N")
    assert warns == []


def test_validate_easting_too_low():
    warns = validate_utm_easting_northing(50_000, 5_000_000, 19, "N")
    assert any("easting" in w.lower() or "Easting" in w for w in warns)


def test_validate_easting_too_high():
    warns = validate_utm_easting_northing(950_000, 5_000_000, 19, "N")
    assert any("easting" in w.lower() or "Easting" in w for w in warns)


def test_validate_northing_north_too_high():
    warns = validate_utm_easting_northing(500_000, 10_000_000, 19, "N")
    assert any("northing" in w.lower() or "Northing" in w for w in warns)


def test_validate_valid_south():
    warns = validate_utm_easting_northing(350_000, 6_200_000, 19, "S")
    assert warns == []


def test_validate_northing_south_too_low():
    warns = validate_utm_easting_northing(350_000, 500_000, 19, "S")
    assert any("northing" in w.lower() or "Northing" in w for w in warns)
