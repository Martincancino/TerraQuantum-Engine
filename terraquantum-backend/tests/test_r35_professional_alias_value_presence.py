"""
R3.5-I-FIX1 — Professional column value-presence tests.

Verifies that PROFESSIONAL_SURVEY is NOT activated by headers alone when column values
are empty (NOAA Andes 1997 benchmark regression).

Tests:
  1.  Empty uncertainty_mgal header does not activate has_uncertainty_column
  2.  Empty instrument_id header does not activate has_instrument_metadata
  3.  Populated elevation_m activates has_elevation_column
  4.  Populated terrain_correction activates has_corrections_metadata
  5.  lat/lon + elevation + correction (empty uncertainty/instrument) → GEOGRAPHIC_COORDS
  6.  lat/lon + all 4 professional fields with values → PROFESSIONAL_SURVEY
  7.  UTM_WITH_ZONE + all 4 professional fields with values → PROFESSIONAL_SURVEY
  8.  "nan", "null", "None", whitespace treated as empty (no flag activation)
  9.  professional_columns_detected still lists header aliases regardless of values
  10. professional_columns_with_values lists only columns with real values
  11. NOAA B1 sparse fixture → preview ok, spatial_readiness = GEOGRAPHIC_COORDS
  12. NOAA B1 full fixture → PROFESSIONAL_SURVEY
  13. Backward compat: analyze_csv_observations without professional_column_values
      still activates flags from headers (existing test_r35_professional_aliases unchanged)
"""
from pathlib import Path

import pytest

from schemas.geophysics_schema import GravityObservation
from services.csv_analysis_service import analyze_csv_observations
from services.gravity_import_service import import_gravity_csv_v1
from services.spatial_readiness_service import classify_from_csv_analysis


# ---------------------------------------------------------------------------
# Helpers (mirrors those in test_r35_professional_aliases.py)
# ---------------------------------------------------------------------------

def _latlon_obs(count: int = 15):
    return [
        GravityObservation(
            x_m=-70.0 + i * 0.01,
            y_m=0.0,
            z_m=-30.0 + i * 0.01,
            g=5e-5 + i * 1e-6,
        )
        for i in range(count)
    ]


def _utm_obs(count: int = 15):
    return [
        GravityObservation(
            x_m=350_000.0 + i * 500,
            y_m=0.0,
            z_m=6_200_000.0 + i * 500,
            g=5e-5 + i * 1e-6,
        )
        for i in range(count)
    ]


def _raw(count: int = 15):
    return [5.0 + i * 0.1 for i in range(count)]


def _write_csv(path: Path, headers: list, rows: list) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(str(h) for h in headers) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


def _prof_vals_empty(count: int = 15) -> dict:
    """All professional column values empty — simulates NOAA sparse case."""
    return {
        "elevation_m": [""] * count,
        "uncertainty_mgal": [""] * count,
        "instrument_id": [""] * count,
        "terrain_correction": [""] * count,
    }


def _prof_vals_elev_corr(count: int = 15) -> dict:
    """elevation_m and terrain_correction populated; uncertainty/instrument empty."""
    return {
        "elevation_m": [str(2200 + i * 10) for i in range(count)],
        "uncertainty_mgal": [""] * count,
        "instrument_id": [""] * count,
        "terrain_correction": [str(0.3 + i * 0.01) for i in range(count)],
    }


def _prof_vals_all(count: int = 15) -> dict:
    """All four professional columns populated."""
    return {
        "elevation_m": [str(2200 + i * 10) for i in range(count)],
        "uncertainty_mgal": ["0.02"] * count,
        "instrument_id": ["G1"] * count,
        "terrain_correction": [str(0.3 + i * 0.01) for i in range(count)],
    }


_PROF_HEADERS = [
    "station_id", "x_m", "y_m", "z_m", "unit",
    "gravity_anomaly", "gravity_type",
    "elevation_m", "uncertainty_mgal", "instrument_id", "terrain_correction",
]


# ---------------------------------------------------------------------------
# 1. Empty uncertainty_mgal does not activate has_uncertainty_column
# ---------------------------------------------------------------------------

def test_empty_uncertainty_header_does_not_activate_flag():
    obs = _latlon_obs()
    col_values = {
        "elevation_m": ["2200"] * 15,
        "uncertainty_mgal": [""] * 15,
        "instrument_id": ["G1"] * 15,
        "terrain_correction": ["0.3"] * 15,
    }
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=col_values,
    )
    assert analysis.has_uncertainty_column is False, (
        "Empty uncertainty_mgal must not activate has_uncertainty_column"
    )
    # Others with data remain True
    assert analysis.has_elevation_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True


# ---------------------------------------------------------------------------
# 2. Empty instrument_id does not activate has_instrument_metadata
# ---------------------------------------------------------------------------

def test_empty_instrument_header_does_not_activate_flag():
    obs = _latlon_obs()
    col_values = {
        "elevation_m": ["2200"] * 15,
        "uncertainty_mgal": ["0.02"] * 15,
        "instrument_id": [""] * 15,
        "terrain_correction": ["0.3"] * 15,
    }
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=col_values,
    )
    assert analysis.has_instrument_metadata is False, (
        "Empty instrument_id must not activate has_instrument_metadata"
    )
    assert analysis.has_uncertainty_column is True
    assert analysis.has_elevation_column is True
    assert analysis.has_corrections_metadata is True


# ---------------------------------------------------------------------------
# 3. Populated elevation_m activates has_elevation_column
# ---------------------------------------------------------------------------

def test_populated_elevation_activates_flag():
    obs = _latlon_obs()
    col_values = {"elevation_m": ["2200", "2210", "2220"] + ["2230"] * 12}
    headers = ["station_id", "x_m", "y_m", "z_m", "unit", "gravity_anomaly", "gravity_type", "elevation_m"]
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=headers,
        professional_column_values=col_values,
    )
    assert analysis.has_elevation_column is True


# ---------------------------------------------------------------------------
# 4. Populated terrain_correction activates has_corrections_metadata
# ---------------------------------------------------------------------------

def test_populated_corrections_activates_flag():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type", "terrain_correction",
    ]
    col_values = {"terrain_correction": ["0.3"] * 15}
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=headers,
        professional_column_values=col_values,
    )
    assert analysis.has_corrections_metadata is True


# ---------------------------------------------------------------------------
# 5. lat/lon + elevation + correction (empty uncertainty/instrument) → GEOGRAPHIC_COORDS
# ---------------------------------------------------------------------------

def test_partial_professional_stays_geographic_coords():
    obs = _latlon_obs()
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=_prof_vals_elev_corr(),
    )
    assert analysis.has_elevation_column is True
    assert analysis.has_corrections_metadata is True
    assert analysis.has_uncertainty_column is False
    assert analysis.has_instrument_metadata is False

    result = classify_from_csv_analysis(analysis)
    assert result.level == "GEOGRAPHIC_COORDS", (
        f"Expected GEOGRAPHIC_COORDS (not PROFESSIONAL_SURVEY), got {result.level}"
    )


# ---------------------------------------------------------------------------
# 6. lat/lon + all 4 fields with real values → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_full_professional_latlon_activates_professional_survey():
    obs = _latlon_obs()
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=_prof_vals_all(),
    )
    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "PROFESSIONAL_SURVEY", (
        f"Expected PROFESSIONAL_SURVEY, got {result.level}"
    )


# ---------------------------------------------------------------------------
# 7. UTM_WITH_ZONE + all 4 fields with real values → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_full_professional_utm_with_zone_activates_professional_survey():
    obs = _utm_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "terrain_correction",
    ]
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=headers,
        professional_column_values=_prof_vals_all(),
    )
    result = classify_from_csv_analysis(analysis, utm_zone="19S")
    assert result.level == "PROFESSIONAL_SURVEY", (
        f"UTM_WITH_ZONE + all professional values → expected PROFESSIONAL_SURVEY, got {result.level}"
    )


# ---------------------------------------------------------------------------
# 8. "nan", "null", "None", whitespace treated as empty
# ---------------------------------------------------------------------------

def test_nan_null_none_whitespace_are_treated_as_empty():
    obs = _latlon_obs()
    col_values = {
        "elevation_m": ["nan", "NaN", "null", "NULL", "None", "none", "  ", "N/A", "na"] + [""] * 6,
        "uncertainty_mgal": ["nan"] * 15,
        "instrument_id": [" ", "null", "None"] + [""] * 12,
        "terrain_correction": ["null", " ", "NaN"] + [""] * 12,
    }
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=col_values,
    )
    assert analysis.has_elevation_column is False, "nan/null/whitespace must be treated as empty"
    assert analysis.has_uncertainty_column is False
    assert analysis.has_instrument_metadata is False
    assert analysis.has_corrections_metadata is False

    result = classify_from_csv_analysis(analysis)
    assert result.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 9. professional_columns_detected still shows header aliases regardless of values
# ---------------------------------------------------------------------------

def test_professional_columns_detected_shows_all_header_aliases():
    obs = _latlon_obs()
    # All headers present, but uncertainty empty
    col_values = _prof_vals_elev_corr()
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=col_values,
    )
    # Headers detected even if values are empty
    detected = set(analysis.professional_columns_detected)
    assert "elevation_m" in detected
    assert "uncertainty_mgal" in detected
    assert "instrument_id" in detected
    assert "terrain_correction" in detected


# ---------------------------------------------------------------------------
# 10. professional_columns_with_values lists only columns with real values
# ---------------------------------------------------------------------------

def test_professional_columns_with_values_only_lists_populated():
    obs = _latlon_obs()
    col_values = _prof_vals_elev_corr()  # elev + correction have values; uncertainty/instrument empty
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        professional_column_values=col_values,
    )
    with_values = set(analysis.professional_columns_with_values)
    assert "elevation_m" in with_values
    assert "terrain_correction" in with_values
    assert "uncertainty_mgal" not in with_values
    assert "instrument_id" not in with_values


# ---------------------------------------------------------------------------
# 11. NOAA B1 sparse fixture via import_gravity_csv_v1 → GEOGRAPHIC_COORDS
# ---------------------------------------------------------------------------

def test_noaa_b1_sparse_import_returns_geographic_coords(tmp_path):
    """
    Reproduces the NOAA Andes 1997 benchmark: elevation_m and terrain_correction
    present, uncertainty_mgal and instrument_id empty.
    Expected: spatial_readiness = GEOGRAPHIC_COORDS, NOT PROFESSIONAL_SURVEY.
    """
    headers = [
        "station_id", "lat", "lon", "g_mgal",
        "elevation_m", "uncertainty_mgal", "instrument_id", "terrain_correction",
        "unit", "gravity_type",
    ]
    rows = [
        (
            f"A{i}",
            -22.1 - i * 0.01, -68.1 - i * 0.01,
            10 + i * 0.1,
            2200 + i * 10,
            "",            # uncertainty_mgal → empty
            "",            # instrument_id → empty
            round(0.3 + i * 0.01, 3),
            "mGal", "free_air_anomaly",
        )
        for i in range(12)
    ]
    csv_path = tmp_path / "noaa_b1_sparse.csv"
    _write_csv(csv_path, headers, rows)

    result = import_gravity_csv_v1(csv_path)
    assert result.status == "ok", f"Import failed: {result.errors}"

    analysis = result.csv_analysis
    assert analysis.has_elevation_column is True
    assert analysis.has_corrections_metadata is True
    assert analysis.has_uncertainty_column is False, (
        "Empty uncertainty_mgal must not activate has_uncertainty_column"
    )
    assert analysis.has_instrument_metadata is False, (
        "Empty instrument_id must not activate has_instrument_metadata"
    )

    spatial = classify_from_csv_analysis(analysis)
    assert spatial.level == "GEOGRAPHIC_COORDS", (
        f"NOAA B1 sparse → expected GEOGRAPHIC_COORDS, got {spatial.level}"
    )
    assert spatial.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 12. NOAA B1 full fixture → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_noaa_b1_full_import_returns_professional_survey(tmp_path):
    """All 4 professional columns populated → PROFESSIONAL_SURVEY."""
    headers = [
        "station_id", "lat", "lon", "g_mgal",
        "elevation_m", "uncertainty_mgal", "instrument_id", "terrain_correction",
        "unit", "gravity_type",
    ]
    rows = [
        (
            f"A{i}",
            -22.1 - i * 0.01, -68.1 - i * 0.01,
            10 + i * 0.1,
            2200 + i * 10,
            "0.02",
            "G1",
            round(0.3 + i * 0.01, 3),
            "mGal", "free_air_anomaly",
        )
        for i in range(12)
    ]
    csv_path = tmp_path / "noaa_b1_full.csv"
    _write_csv(csv_path, headers, rows)

    result = import_gravity_csv_v1(csv_path)
    assert result.status == "ok", f"Import failed: {result.errors}"

    analysis = result.csv_analysis
    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    spatial = classify_from_csv_analysis(analysis)
    assert spatial.level == "PROFESSIONAL_SURVEY", (
        f"NOAA B1 full → expected PROFESSIONAL_SURVEY, got {spatial.level}"
    )


# ---------------------------------------------------------------------------
# 13. Backward compat: analyze_csv_observations without professional_column_values
#     still activates flags from headers (preserves R3.5-I behavior for direct callers)
# ---------------------------------------------------------------------------

def test_backward_compat_header_only_detection_when_no_values_provided():
    """Direct callers that omit professional_column_values get header-only detection."""
    obs = _latlon_obs()
    analysis = analyze_csv_observations(
        obs, "mGal", _raw(), column_names=_PROF_HEADERS,
        # professional_column_values intentionally omitted
    )
    # Header-only path: all four headers present → all flags True
    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "PROFESSIONAL_SURVEY", (
        "Backward compat: header-only detection must still yield PROFESSIONAL_SURVEY"
    )
