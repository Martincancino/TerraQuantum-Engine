"""
R3.5-J — Flexible coordinate column parser tests.

Covers all alias formats: legacy x_m/z_m, local x/z, UTM easting/northing,
lat/lon, depth vs elevation handling, metadata preservation, and no-regression
against R3.5-I spatial readiness levels.
"""
import math
from pathlib import Path

import pytest

from services.gravity_import_service import (
    _resolve_coordinate_columns,
    import_gravity_csv_v1,
)
from services.spatial_readiness_service import classify_from_csv_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, headers: list, rows: list) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(str(h) for h in headers) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


def _legacy_rows(count: int = 12, x0: float = 0.0, z0: float = 0.0):
    return [
        (f"st_{i}", x0 + i * 100, 5.0, z0 + i * 100, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(count)
    ]


def _latlon_rows(count: int = 12):
    return [
        (f"st_{i}", -70.0 + i * 0.01, -30.0 + i * 0.01, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(count)
    ]


def _utm_rows(count: int = 12):
    return [
        (f"st_{i}", 350_000 + i * 500, 6_200_000 + i * 500, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# _resolve_coordinate_columns unit tests
# ---------------------------------------------------------------------------

def test_resolve_legacy_x_m_z_m():
    headers = ["station_id", "x_m", "y_m", "z_m", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "legacy"
    assert result["x_col"] == "x_m"
    assert result["z_col"] == "z_m"
    assert result["y_col"] == "y_m"
    assert result["errors"] == []


def test_resolve_legacy_x_m_z_m_without_y_m():
    headers = ["station_id", "x_m", "z_m", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "legacy"
    assert result["y_col"] is None
    assert any("y_m" in w or "y_m=0" in w for w in result["warnings"])


def test_resolve_latlon():
    headers = ["station_id", "lat", "lon", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "latlon"
    assert result["x_col"] == "lon"
    assert result["z_col"] == "lat"
    assert result["y_col"] is None


def test_resolve_latitude_longitude():
    headers = ["station_id", "latitude", "longitude", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "latlon"
    assert result["z_col"] == "latitude"
    assert result["x_col"] == "longitude"


def test_resolve_utm_easting_northing():
    headers = ["station_id", "easting", "northing", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "utm"
    assert result["x_col"] == "easting"
    assert result["z_col"] == "northing"


def test_resolve_utm_utm_e_utm_n():
    headers = ["station_id", "utm_e", "utm_n", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "utm"
    assert result["x_col"] == "utm_e"
    assert result["z_col"] == "utm_n"


def test_resolve_local_x_z():
    headers = ["station_id", "x", "z", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "local"
    assert result["x_col"] == "x"
    assert result["z_col"] == "z"


def test_resolve_local_local_x_local_z():
    headers = ["station_id", "local_x", "local_z", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] == "local"


def test_resolve_no_coords_returns_error():
    headers = ["station_id", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["coord_type"] is None
    assert len(result["errors"]) > 0


def test_resolve_depth_m_maps_to_y_col():
    headers = ["station_id", "lat", "lon", "depth_m", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["y_col"] == "depth_m"


def test_resolve_elevation_m_does_not_map_to_y_col():
    headers = ["station_id", "lat", "lon", "elevation_m", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["y_col"] is None
    assert any("elevaci" in w.lower() or "elevation" in w.lower() for w in result["warnings"])


def test_resolve_utm_zone_col_detected():
    headers = ["station_id", "easting", "northing", "utm_zone", "unit", "g_mgal"]
    hl = [h.lower() for h in headers]
    result = _resolve_coordinate_columns(hl, headers)
    assert result["utm_zone_col"] == "utm_zone"


# ---------------------------------------------------------------------------
# import_gravity_csv_v1 integration tests
# ---------------------------------------------------------------------------

def test_legacy_x_m_y_m_z_m_still_works(tmp_path):
    """Legacy v1 format must not be broken."""
    rows = _legacy_rows()
    _write_csv(
        tmp_path / "legacy.csv",
        ["station_id", "x_m", "y_m", "z_m", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "legacy.csv")
    assert result.status == "ok", result.errors
    assert len(result.observations) == 12
    assert result.coordinate_transform.method in (
        "local_meters_sw_origin_shift", "sw_origin_shift_low_confidence"
    )


def test_local_alias_x_y_z_imports_correctly(tmp_path):
    rows = [
        (f"st_{i}", i * 100.0, 5.0, i * 100.0, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "local_xyz.csv",
        ["station_id", "x", "y", "z", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "local_xyz.csv")
    assert result.status == "ok", result.errors
    assert len(result.observations) == 12


def test_local_x_z_without_y_assumes_y_zero(tmp_path):
    rows = [
        (f"st_{i}", i * 100.0, i * 100.0, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "local_xz.csv",
        ["station_id", "x", "z", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "local_xz.csv")
    assert result.status == "ok", result.errors
    assert all(obs.y_m == 0.0 for obs in result.observations)
    assert any("y_m=0" in w or "profundidad" in w.lower() for w in result.warnings)


def test_utm_easting_northing_imports_correctly(tmp_path):
    rows = _utm_rows()
    _write_csv(
        tmp_path / "utm.csv",
        ["station_id", "easting", "northing", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm.csv")
    assert result.status == "ok", result.errors
    assert len(result.observations) == 12
    assert result.coordinate_transform.method == "utm_sw_origin_shift"


def test_utm_utm_e_utm_n_imports_correctly(tmp_path):
    rows = _utm_rows()
    _write_csv(
        tmp_path / "utm_en.csv",
        ["station_id", "utm_e", "utm_n", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm_en.csv")
    assert result.status == "ok", result.errors
    assert result.coordinate_transform.method == "utm_sw_origin_shift"


def test_utm_raw_bbox_preserved(tmp_path):
    rows = _utm_rows()
    _write_csv(
        tmp_path / "utm_bbox.csv",
        ["station_id", "easting", "northing", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm_bbox.csv")
    assert result.status == "ok", result.errors
    ct = result.coordinate_transform
    assert ct.x_min_raw is not None and ct.x_min_raw > 0
    assert ct.z_min_raw is not None and ct.z_min_raw > 0
    assert ct.x_max_raw > ct.x_min_raw
    assert ct.z_max_raw > ct.z_min_raw


def test_utm_without_y_assumes_y_zero(tmp_path):
    rows = _utm_rows()
    _write_csv(
        tmp_path / "utm_noy.csv",
        ["station_id", "easting", "northing", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm_noy.csv")
    assert result.status == "ok", result.errors
    assert all(obs.y_m == 0.0 for obs in result.observations)


def test_latlon_imports_correctly(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon.csv")
    assert result.status == "ok", result.errors
    assert len(result.observations) == 12


def test_latitude_longitude_imports_correctly(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlong.csv",
        ["station_id", "latitude", "longitude", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlong.csv")
    assert result.status == "ok", result.errors


def test_latlon_produces_detected_latlon(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon_cs.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_cs.csv")
    assert result.status == "ok", result.errors
    assert result.csv_analysis.coordinate_system.detected == "latlon"


def test_latlon_x_m_z_m_are_finite(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon_fin.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_fin.csv")
    assert result.status == "ok", result.errors
    for obs in result.observations:
        assert math.isfinite(obs.x_m)
        assert math.isfinite(obs.z_m)


def test_latlon_does_not_require_x_m_y_m_z_m(tmp_path):
    """CSV with only lat/lon (no x_m/y_m/z_m columns) must succeed."""
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon_noxyz.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_noxyz.csv")
    assert result.status == "ok", result.errors
    assert "Missing required column: x_m" not in str(result.errors)


def test_latlon_method_is_utm_pyproj(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon_meth.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_meth.csv")
    assert result.status == "ok", result.errors
    # lat/lon se reproyecta a UTM real vía pyproj (equirectangular quedó como fallback).
    assert result.coordinate_transform.method == "utm_pyproj_vectorized"


def test_elevation_m_not_used_as_depth(tmp_path):
    """elevation_m column must not be assigned to y_m; surface stations use y_m=0."""
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, -30.0 + i * 0.01, 1500.0 + i, "mGal",
         5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "latlon_elev.csv",
        ["station_id", "lat", "lon", "elevation_m", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_elev.csv")
    assert result.status == "ok", result.errors
    assert all(obs.y_m == 0.0 for obs in result.observations), (
        "elevation_m must not be used as depth (y_m)"
    )


def test_depth_m_is_used_as_y_m(tmp_path):
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, -30.0 + i * 0.01, float(i * 10), "mGal",
         5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "latlon_depth.csv",
        ["station_id", "lat", "lon", "depth_m", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_depth.csv")
    assert result.status == "ok", result.errors
    for i, obs in enumerate(result.observations):
        assert math.isclose(obs.y_m, float(i * 10), abs_tol=1e-6), (
            f"Expected y_m={i * 10}, got {obs.y_m}"
        )


def test_z_m_not_counted_as_elevation_professional(tmp_path):
    """z_m column is a coordinate, not an elevation alias. Must not set has_elevation_column."""
    rows = _legacy_rows()
    _write_csv(
        tmp_path / "legacy_z.csv",
        ["station_id", "x_m", "y_m", "z_m", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "legacy_z.csv")
    assert result.status == "ok", result.errors
    assert result.csv_analysis.has_elevation_column is False


def test_g_mgal_still_works(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "g_mgal.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "g_mgal.csv")
    assert result.status == "ok", result.errors
    assert result.import_metadata.gravity_column_used.lower() == "g_mgal"


def test_gravity_mgal_still_works(tmp_path):
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, -30.0 + i * 0.01, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "grav_mgal.csv",
        ["station_id", "lat", "lon", "unit", "gravity_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "grav_mgal.csv")
    assert result.status == "ok", result.errors
    assert result.import_metadata.gravity_column_used.lower() == "gravity_mgal"


def test_bouguer_anomaly_works_as_gravity_column(tmp_path):
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, -30.0 + i * 0.01, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "ba.csv",
        ["station_id", "lat", "lon", "unit", "bouguer_anomaly", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "ba.csv")
    assert result.status == "ok", result.errors
    assert result.import_metadata.gravity_column_used.lower() == "bouguer_anomaly"


def test_csv_no_coords_stays_no_spatial_data(tmp_path):
    """CSV with only station_id/g_mgal and no coordinate columns → import error (not spatial)."""
    rows = [(f"st_{i}", "mGal", 5.0 + i * 0.1, "bouguer_anomaly") for i in range(12)]
    _write_csv(
        tmp_path / "no_coords.csv",
        ["station_id", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "no_coords.csv")
    assert result.status == "error"
    assert any("coordenadas" in e.lower() for e in result.errors)


def test_coordinate_transform_method_local(tmp_path):
    rows = [
        (f"st_{i}", i * 100.0, i * 100.0, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "local_meth.csv",
        ["station_id", "x", "z", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "local_meth.csv")
    assert result.status == "ok", result.errors
    assert result.coordinate_transform.method in (
        "local_meters_sw_origin_shift", "sw_origin_shift_low_confidence"
    )


def test_coordinate_transform_method_utm(tmp_path):
    rows = _utm_rows()
    _write_csv(
        tmp_path / "utm_meth.csv",
        ["station_id", "easting", "northing", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm_meth.csv")
    assert result.status == "ok", result.errors
    assert result.coordinate_transform.method == "utm_sw_origin_shift"


def test_coordinate_transform_method_latlon(tmp_path):
    rows = _latlon_rows()
    _write_csv(
        tmp_path / "latlon_meth2.csv",
        ["station_id", "lat", "lon", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_meth2.csv")
    assert result.status == "ok", result.errors
    # lat/lon se reproyecta a UTM real vía pyproj (equirectangular quedó como fallback).
    assert result.coordinate_transform.method == "utm_pyproj_vectorized"


def test_latlon_professional_plus_metadata_reaches_professional_survey(tmp_path):
    """Lat/lon CSV with all 4 professional metadata columns → PROFESSIONAL_SURVEY."""
    rows = [
        (
            f"st_{i}",
            -70.0 + i * 0.01,
            -30.0 + i * 0.01,
            1500.0 + i,  # elevation_m
            0.05,        # uncertainty_mgal
            "Scintrex",  # instrument_id
            "mGal",
            5.0 + i * 0.1,
            "bouguer_anomaly",
        )
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "latlon_pro.csv",
        [
            "station_id", "lat", "lon",
            "elevation_m", "uncertainty_mgal", "instrument_id",
            "unit", "bouguer_anomaly", "gravity_type",
        ],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "latlon_pro.csv")
    assert result.status == "ok", result.errors
    # bouguer_anomaly column serves as both gravity col and correction metadata
    # elevation_m → has_elevation_column, bouguer_anomaly → has_corrections_metadata
    sr = classify_from_csv_analysis(result.csv_analysis)
    assert sr.level == "PROFESSIONAL_SURVEY", (
        f"Expected PROFESSIONAL_SURVEY, got {sr.level}. "
        f"has_elevation={result.csv_analysis.has_elevation_column}, "
        f"has_uncertainty={result.csv_analysis.has_uncertainty_column}, "
        f"has_instrument={result.csv_analysis.has_instrument_metadata}, "
        f"has_corrections={result.csv_analysis.has_corrections_metadata}"
    )


def test_utm_with_zone_col_professional_reaches_professional_survey(tmp_path):
    """UTM CSV with utm_zone column + all 4 professional metadata cols → PROFESSIONAL_SURVEY."""
    rows = [
        (
            f"st_{i}",
            350_000 + i * 500,
            6_200_000 + i * 500,
            "19S",
            1500.0 + i,  # rl (elevation alias)
            0.05,        # uncertainty_mgal
            "Scintrex",  # instrument_id
            "mGal",
            5.0 + i * 0.1,
            "bouguer_anomaly",
        )
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "utm_pro.csv",
        [
            "station_id", "easting", "northing", "utm_zone",
            "rl", "uncertainty_mgal", "instrument_id",
            "unit", "bouguer_anomaly", "gravity_type",
        ],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "utm_pro.csv")
    assert result.status == "ok", result.errors
    # utm_zone extracted from CSV column and stored in coordinate_transform
    utm_zone = result.coordinate_transform.utm_zone or "19S"
    sr = classify_from_csv_analysis(result.csv_analysis, utm_zone=utm_zone)
    assert sr.level == "PROFESSIONAL_SURVEY", (
        f"Expected PROFESSIONAL_SURVEY, got {sr.level}. "
        f"utm_zone={utm_zone}, "
        f"has_elevation={result.csv_analysis.has_elevation_column}, "
        f"has_uncertainty={result.csv_analysis.has_uncertainty_column}, "
        f"has_instrument={result.csv_analysis.has_instrument_metadata}, "
        f"has_corrections={result.csv_analysis.has_corrections_metadata}"
    )


def test_anchor_central_without_per_station_latlon_not_geographic(tmp_path):
    """Local x/z CSV does NOT become GEOGRAPHIC_COORDS even with anchor lat/lon."""
    rows = [
        (f"st_{i}", i * 100.0, i * 100.0, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "local_anchor.csv",
        ["station_id", "x", "z", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "local_anchor.csv")
    assert result.status == "ok", result.errors
    sr = classify_from_csv_analysis(result.csv_analysis, anchor_lat=-28.0, anchor_lon=-70.0)
    assert sr.level in ("LOCAL_ANCHORED_CENTER", "LOCAL_UNANCHORED")
    assert sr.level != "GEOGRAPHIC_COORDS"
    assert sr.level != "PROFESSIONAL_SURVEY"
