import math

from schemas.geophysics_schema import GravityObservation
from schemas.gravity_import_schema import CoordSystemDetection
from services.coordinate_transform_service import transform_coordinates


def _obs(x, y, z, g=1e-5):
    return GravityObservation(x_m=x, y_m=y, z_m=z, g=g)


def test_latlon_small_extent_to_local_meters():
    observations = [
        _obs(-70.00, 5.0, -30.00),
        _obs(-69.99, 7.5, -29.99),
        _obs(-69.98, 9.0, -30.00),
    ]

    transformed, transform = transform_coordinates(
        observations,
        CoordSystemDetection(detected="latlon", confidence="high"),
    )

    xs = [obs.x_m for obs in transformed]
    zs = [obs.z_m for obs in transformed]

    # El path lat/lon reproyecta a UTM real vía pyproj (más preciso que la
    # aproximación equirectangular, que ahora solo es fallback si pyproj falla).
    assert transform.method == "utm_pyproj_vectorized"
    assert min(xs) == 0.0
    assert min(zs) == 0.0
    assert 1900.0 <= transform.x_extent_m <= 2000.0
    assert 1100.0 <= transform.z_extent_m <= 1125.0
    assert transformed[1].y_m == 7.5


def test_utm_offset_to_sw_origin():
    observations = [
        _obs(350_000.0, 1.0, 6_200_000.0),
        _obs(350_500.0, 2.0, 6_201_000.0),
    ]

    transformed, transform = transform_coordinates(
        observations,
        CoordSystemDetection(detected="utm", confidence="high"),
    )

    assert transform.method == "utm_sw_origin_shift"
    assert min(obs.x_m for obs in transformed) == 0.0
    assert min(obs.z_m for obs in transformed) == 0.0
    assert math.isclose(transform.x_extent_m, 500.0)
    assert math.isclose(transform.z_extent_m, 1000.0)


def test_local_meters_with_offset_normalizes_to_sw_origin():
    observations = [
        _obs(10_000.0, 3.0, 20_000.0),
        _obs(12_500.0, 4.0, 25_000.0),
    ]

    transformed, transform = transform_coordinates(
        observations,
        CoordSystemDetection(detected="local_meters", confidence="high"),
    )

    assert transform.method == "local_meters_sw_origin_shift"
    assert transformed[0].x_m == 0.0
    assert transformed[0].z_m == 0.0
    assert transformed[1].x_m == 2500.0
    assert transformed[1].z_m == 5000.0


def test_unknown_falls_back_with_warning():
    observations = [_obs(100.0, 1.0, 200.0), _obs(150.0, 2.0, 260.0)]

    transformed, transform = transform_coordinates(
        observations,
        CoordSystemDetection(detected="unknown", confidence="low"),
    )

    assert transform.method == "sw_origin_shift_low_confidence"
    assert transform.warnings
    assert min(obs.x_m for obs in transformed) == 0.0
    assert min(obs.z_m for obs in transformed) == 0.0


def test_y_m_is_preserved_for_all_transforms():
    observations = [_obs(-70.0, 12.5, -30.0), _obs(-69.99, 15.0, -29.99)]

    transformed, _ = transform_coordinates(
        observations,
        CoordSystemDetection(detected="latlon", confidence="high"),
    )

    assert [obs.y_m for obs in transformed] == [12.5, 15.0]
