"""
R2.2 — Tests de reproyección geodésica real UTM ↔ WGS84 via pyproj.

Benchmark: zona 19S (EPSG:32719), región de Atacama-Chile.
  lat_ref = -22.28, lon_ref = -68.89
"""
import pytest

# ---------------------------------------------------------------------------
# 1. pyproj import works
# ---------------------------------------------------------------------------

def test_pyproj_importable():
    import pyproj
    assert hasattr(pyproj, "__version__")


def test_pyproj_transformer_importable():
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True)
    assert t is not None


# ---------------------------------------------------------------------------
# Helper: reference point in Chile (Atacama, zone 19S)
# lat=-22.28, lon=-68.89 → UTM 19S
# ---------------------------------------------------------------------------

LAT_REF = -22.28
LON_REF = -68.89

def _get_utm_ref():
    """Derive reference UTM easting/northing from known lat/lon."""
    from services.coordinate_transform_real import transform_wgs84_to_utm
    return transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=32719)


# ---------------------------------------------------------------------------
# 2. transform_utm_to_wgs84 con EPSG:32719 — punto conocido en Chile
# ---------------------------------------------------------------------------

def test_utm_to_wgs84_epsg_chile_lat_range():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat, lon = transform_utm_to_wgs84(east, north, epsg_code=32719)
    # Chile zona 19S: latitud en [-60, -15]
    assert -60.0 <= lat <= -15.0, f"Latitud {lat} fuera del rango esperado para Chile"


def test_utm_to_wgs84_epsg_chile_lon_range():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat, lon = transform_utm_to_wgs84(east, north, epsg_code=32719)
    # Chile zona 19S: longitud en [-76, -60]
    assert -76.0 <= lon <= -60.0, f"Longitud {lon} fuera del rango esperado para Chile"


def test_utm_to_wgs84_epsg_returns_tuple_of_two():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    result = transform_utm_to_wgs84(east, north, epsg_code=32719)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 3. utm_zone="19S" produce el mismo resultado que epsg_code=32719
# ---------------------------------------------------------------------------

def test_utm_to_wgs84_zone_string_equals_epsg():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat_epsg, lon_epsg = transform_utm_to_wgs84(east, north, epsg_code=32719)
    lat_zone, lon_zone = transform_utm_to_wgs84(east, north, utm_zone="19S")
    assert abs(lat_epsg - lat_zone) < 1e-9
    assert abs(lon_epsg - lon_zone) < 1e-9


def test_utm_to_wgs84_zone_string_lowercase():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat_upper, lon_upper = transform_utm_to_wgs84(east, north, utm_zone="19S")
    lat_lower, lon_lower = transform_utm_to_wgs84(east, north, utm_zone="19s")
    assert abs(lat_upper - lat_lower) < 1e-9
    assert abs(lon_upper - lon_lower) < 1e-9


# ---------------------------------------------------------------------------
# 4. Roundtrip WGS84 → UTM → WGS84
# ---------------------------------------------------------------------------

def test_roundtrip_wgs84_utm_wgs84_lat():
    from services.coordinate_transform_real import (
        transform_wgs84_to_utm,
        transform_utm_to_wgs84,
    )
    east, north = transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=32719)
    lat_rt, lon_rt = transform_utm_to_wgs84(east, north, epsg_code=32719)
    assert abs(lat_rt - LAT_REF) < 1e-5, f"Roundtrip lat error: {abs(lat_rt - LAT_REF):.2e}"


def test_roundtrip_wgs84_utm_wgs84_lon():
    from services.coordinate_transform_real import (
        transform_wgs84_to_utm,
        transform_utm_to_wgs84,
    )
    east, north = transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=32719)
    lat_rt, lon_rt = transform_utm_to_wgs84(east, north, epsg_code=32719)
    assert abs(lon_rt - LON_REF) < 1e-5, f"Roundtrip lon error: {abs(lon_rt - LON_REF):.2e}"


def test_roundtrip_utm_wgs84_utm():
    from services.coordinate_transform_real import (
        transform_wgs84_to_utm,
        transform_utm_to_wgs84,
    )
    east_ref, north_ref = _get_utm_ref()
    lat_mid, lon_mid = transform_utm_to_wgs84(east_ref, north_ref, epsg_code=32719)
    east_rt, north_rt = transform_wgs84_to_utm(lat_mid, lon_mid, epsg_code=32719)
    assert abs(east_rt - east_ref) < 0.01, f"Roundtrip easting error: {abs(east_rt - east_ref):.4f} m"
    assert abs(north_rt - north_ref) < 0.01, f"Roundtrip northing error: {abs(north_rt - north_ref):.4f} m"


def test_roundtrip_via_zone_string():
    from services.coordinate_transform_real import (
        transform_wgs84_to_utm,
        transform_utm_to_wgs84,
    )
    east, north = transform_wgs84_to_utm(LAT_REF, LON_REF, utm_zone="19S")
    lat_rt, lon_rt = transform_utm_to_wgs84(east, north, utm_zone="19S")
    assert abs(lat_rt - LAT_REF) < 1e-5
    assert abs(lon_rt - LON_REF) < 1e-5


# ---------------------------------------------------------------------------
# 5. invalid zone raises ValueError
# ---------------------------------------------------------------------------

def test_utm_to_wgs84_invalid_zone_string():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    with pytest.raises(ValueError):
        transform_utm_to_wgs84(500_000, 7_500_000, utm_zone="99X")


def test_utm_to_wgs84_invalid_zone_format():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    with pytest.raises(ValueError):
        transform_utm_to_wgs84(500_000, 7_500_000, utm_zone="zona_invalida")


def test_wgs84_to_utm_invalid_zone_string():
    from services.coordinate_transform_real import transform_wgs84_to_utm
    with pytest.raises(ValueError):
        transform_wgs84_to_utm(LAT_REF, LON_REF, utm_zone="0S")


# ---------------------------------------------------------------------------
# 6. missing CRS raises ValueError
# ---------------------------------------------------------------------------

def test_utm_to_wgs84_no_crs_raises():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    with pytest.raises(ValueError, match="epsg_code|utm_zone"):
        transform_utm_to_wgs84(500_000, 7_500_000)


def test_wgs84_to_utm_no_crs_raises():
    from services.coordinate_transform_real import transform_wgs84_to_utm
    with pytest.raises(ValueError, match="epsg_code|utm_zone"):
        transform_wgs84_to_utm(LAT_REF, LON_REF)


def test_utm_to_wgs84_inconsistent_zone_hemisphere():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    with pytest.raises(ValueError, match="[Ii]nconsistencia|hemisferio"):
        # utm_zone="19S" implies S, but utm_hemisphere="N" contradicts
        transform_utm_to_wgs84(500_000, 7_500_000, utm_zone="19S", utm_hemisphere="N")


# ---------------------------------------------------------------------------
# 7. lat/lon output en rangos válidos
# ---------------------------------------------------------------------------

def test_output_lat_in_valid_range():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat, lon = transform_utm_to_wgs84(east, north, epsg_code=32719)
    assert -90.0 <= lat <= 90.0


def test_output_lon_in_valid_range():
    from services.coordinate_transform_real import transform_utm_to_wgs84
    east, north = _get_utm_ref()
    lat, lon = transform_utm_to_wgs84(east, north, epsg_code=32719)
    assert -180.0 <= lon <= 180.0


def test_wgs84_to_utm_easting_in_valid_range():
    from services.coordinate_transform_real import transform_wgs84_to_utm
    east, north = transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=32719)
    assert 100_000 <= east <= 900_000, f"Easting {east:.0f} fuera del rango UTM esperado"


def test_wgs84_to_utm_northing_south_in_valid_range():
    from services.coordinate_transform_real import transform_wgs84_to_utm
    east, north = transform_wgs84_to_utm(LAT_REF, LON_REF, epsg_code=32719)
    # Southern hemisphere: northing 1,000,000–10,000,000
    assert 1_000_000 <= north <= 10_000_000, f"Northing {north:.0f} fuera del rango UTM Sur"
