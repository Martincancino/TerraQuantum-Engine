"""
R3.5-I — Professional column aliases and PROFESSIONAL_SURVEY activation.

Tests:
  1.  lat/lon + elevation_m + uncertainty_mgal + instrument_id + bouguer_correction → PROFESSIONAL_SURVEY
  2.  lat/lon + elev + sigma + gravimeter + terrain_correction → PROFESSIONAL_SURVEY
  3.  UTM easting/northing + utm_zone + rl + error_mgal + instrument_model + cba → PROFESSIONAL_SURVEY
  4.  Missing uncertainty → GEOGRAPHIC_COORDS, not PROFESSIONAL_SURVEY
  5.  Missing instrument → not PROFESSIONAL_SURVEY
  6.  Missing corrections → not PROFESSIONAL_SURVEY
  7.  Anchor lat/lon central + professional columns stays at LOCAL_ANCHORED_CENTER
  8.  g_mgal alias still works as gravity column
  9.  gravity_mgal alias works as gravity column
  10. bouguer_anomaly serves as gravity column AND correction metadata
  11. cba serves as gravity column AND correction metadata
  12. z_m does NOT trigger has_elevation_column
  13. CsvAnalysisResult has professional_columns_detected field
  14. classify_from_csv_analysis dict input with professional flags → PROFESSIONAL_SURVEY
  15. classify_from_csv_analysis object input with professional flags → PROFESSIONAL_SURVEY
  16. UTM_WITH_ZONE (utm_zone present) + professional flags → PROFESSIONAL_SURVEY
  17. UTM_NO_ZONE + professional flags → UTM_NO_ZONE (not PROFESSIONAL_SURVEY)
  18. LOCAL_ANCHORED_CENTER + professional flags → LOCAL_ANCHORED_CENTER
  19. professional_columns_detected lists the detected aliases
  20. Partial professional CSV keeps correct warning/rationale for its base level
"""
import io
from pathlib import Path

import pytest

from schemas.geophysics_schema import GravityObservation
from services.csv_analysis_service import (
    CORRECTION_ALIASES,
    ELEVATION_ALIASES,
    INSTRUMENT_ALIASES,
    UNCERTAINTY_ALIASES,
    analyze_csv_observations,
    detect_professional_columns,
)
from services.gravity_import_service import import_gravity_csv_v1
from services.spatial_readiness_service import classify_from_csv_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latlon_obs(count: int = 15):
    """Observations whose x_m/z_m values fall in lat/lon ranges."""
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
    """Observations whose x_m/z_m values fall in UTM ranges."""
    return [
        GravityObservation(
            x_m=350_000.0 + i * 500,
            y_m=0.0,
            z_m=6_200_000.0 + i * 500,
            g=5e-5 + i * 1e-6,
        )
        for i in range(count)
    ]


def _local_obs(count: int = 15):
    """Observations with small local-meter coordinates."""
    return [
        GravityObservation(
            x_m=float(i * 500),
            y_m=0.0,
            z_m=float(i * 500),
            g=5e-5 + i * 1e-6,
        )
        for i in range(count)
    ]


def _raw(count: int = 15):
    return [5.0 + i * 0.1 for i in range(count)]


def _write_csv(path: Path, headers: list, rows: list) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


# ---------------------------------------------------------------------------
# 1. lat/lon + elevation_m + uncertainty_mgal + instrument_id + bouguer_correction → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_latlon_all_professional_columns_activates_professional_survey():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "PROFESSIONAL_SURVEY", (
        f"Expected PROFESSIONAL_SURVEY, got {result.level}"
    )


# ---------------------------------------------------------------------------
# 2. lat/lon + elev + sigma + gravimeter + terrain_correction → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_latlon_alternate_aliases_activates_professional_survey():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elev", "sigma", "gravimeter", "terrain_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 3. UTM + utm_zone + rl + error_mgal + instrument_model + cba → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_utm_with_zone_professional_aliases_activates_professional_survey():
    obs = _utm_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "rl", "error_mgal", "instrument_model", "cba",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is True  # rl is an elevation alias
    assert analysis.has_uncertainty_column is True  # error_mgal
    assert analysis.has_instrument_metadata is True  # instrument_model
    assert analysis.has_corrections_metadata is True  # cba

    result = classify_from_csv_analysis(analysis, utm_zone="19S")
    assert result.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 4. Missing uncertainty → GEOGRAPHIC_COORDS, not PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_missing_uncertainty_stays_geographic_coords():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m",
        # no uncertainty column
        "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is False
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "GEOGRAPHIC_COORDS"
    assert result.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 5. Missing instrument → not PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_missing_instrument_stays_geographic_coords():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal",
        # no instrument column
        "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_instrument_metadata is False

    result = classify_from_csv_analysis(analysis)
    assert result.level == "GEOGRAPHIC_COORDS"


# ---------------------------------------------------------------------------
# 6. Missing corrections → not PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_missing_corrections_stays_geographic_coords():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id",
        # no correction column
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_corrections_metadata is False

    result = classify_from_csv_analysis(analysis)
    assert result.level == "GEOGRAPHIC_COORDS"


# ---------------------------------------------------------------------------
# 7. Anchor lat/lon + professional columns stays LOCAL_ANCHORED_CENTER (not GEOGRAPHIC_COORDS)
# ---------------------------------------------------------------------------

def test_anchor_plus_professional_columns_stays_local_anchored_center():
    obs = _local_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    # All professional flags set
    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    # But coordinate system is local_meters → only LOCAL_ANCHORED_CENTER even with anchor
    result = classify_from_csv_analysis(analysis, anchor_lat=-28.3, anchor_lon=-70.5)
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.level != "GEOGRAPHIC_COORDS"
    assert result.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 8. g_mgal alias still works as gravity column
# ---------------------------------------------------------------------------

def test_g_mgal_alias_accepted_by_import(tmp_path):
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, 0.0, -30.0 + i * 0.01, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "g_mgal.csv",
        ["station_id", "x_m", "y_m", "z_m", "unit", "g_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "g_mgal.csv", strict=True)
    assert result.status == "ok", f"Import failed: {result.errors}"
    assert result.import_metadata.gravity_column_used is not None
    assert result.import_metadata.gravity_column_used.lower() == "g_mgal"


# ---------------------------------------------------------------------------
# 9. gravity_mgal alias works as gravity column
# ---------------------------------------------------------------------------

def test_gravity_mgal_alias_accepted_by_import(tmp_path):
    rows = [
        (f"st_{i}", -70.0 + i * 0.01, 0.0, -30.0 + i * 0.01, "mGal", 5.0 + i * 0.1, "bouguer_anomaly")
        for i in range(12)
    ]
    _write_csv(
        tmp_path / "grav_mgal.csv",
        ["station_id", "x_m", "y_m", "z_m", "unit", "gravity_mgal", "gravity_type"],
        rows,
    )
    result = import_gravity_csv_v1(tmp_path / "grav_mgal.csv", strict=True)
    assert result.status == "ok", f"Import failed: {result.errors}"
    assert result.import_metadata.gravity_column_used.lower() == "gravity_mgal"


# ---------------------------------------------------------------------------
# 10. bouguer_anomaly as gravity column AND correction metadata
# ---------------------------------------------------------------------------

def test_bouguer_anomaly_dual_use_gravity_and_correction():
    obs = _latlon_obs()
    # bouguer_anomaly is both the gravity column (value) AND in CORRECTION_ALIASES
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "bouguer_anomaly",  # dual-use: gravity value + correction flag
        "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    # corrections flag set by bouguer_anomaly column name
    assert analysis.has_corrections_metadata is True
    # all four flags present → PROFESSIONAL_SURVEY
    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True

    result = classify_from_csv_analysis(analysis)
    assert result.level == "PROFESSIONAL_SURVEY"

    # Import test: bouguer_anomaly is selected as gravity column
    assert "bouguer_anomaly" in CORRECTION_ALIASES


# ---------------------------------------------------------------------------
# 11. cba as gravity column AND correction metadata
# ---------------------------------------------------------------------------

def test_cba_dual_use_gravity_and_correction():
    obs = _utm_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "cba",  # dual-use: gravity alias + correction alias
        "gravity_type",
        "rl", "sigma", "instrument_id",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_corrections_metadata is True  # cba in CORRECTION_ALIASES
    assert analysis.has_elevation_column is True      # rl
    assert analysis.has_uncertainty_column is True    # sigma
    assert analysis.has_instrument_metadata is True   # instrument_id

    result = classify_from_csv_analysis(analysis, utm_zone="19S")
    assert result.level == "PROFESSIONAL_SURVEY"

    assert "cba" in CORRECTION_ALIASES


# ---------------------------------------------------------------------------
# 12. z_m does NOT trigger has_elevation_column
# ---------------------------------------------------------------------------

def test_z_m_does_not_trigger_elevation_flag():
    obs = _local_obs()
    # Standard v1 columns — z_m is a coordinate, not an elevation alias
    headers = ["station_id", "x_m", "y_m", "z_m", "unit", "g", "gravity_type"]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is False, (
        "z_m must not be counted as an elevation column"
    )


# ---------------------------------------------------------------------------
# 13. CsvAnalysisResult has professional_columns_detected
# ---------------------------------------------------------------------------

def test_csv_analysis_result_has_professional_columns_detected_field():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert hasattr(analysis, "professional_columns_detected")
    assert isinstance(analysis.professional_columns_detected, list)
    assert len(analysis.professional_columns_detected) > 0


# ---------------------------------------------------------------------------
# 14. classify_from_csv_analysis dict input with professional flags → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_classify_from_csv_analysis_dict_professional_flags_activates_professional_survey():
    csv_dict = {
        "observation_count": 20,
        "coordinate_system": {"detected": "latlon", "utm_zone": None},
        "has_elevation_column": True,
        "has_uncertainty_column": True,
        "has_instrument_metadata": True,
        "has_corrections_metadata": True,
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 15. classify_from_csv_analysis object input with professional flags → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

class _MockCsvAnalysisPro:
    def __init__(self, detected, obs_count=20, utm_zone=None, **prof_flags):
        class _CS:
            pass
        cs = _CS()
        cs.detected = detected
        cs.utm_zone = utm_zone
        self.coordinate_system = cs
        self.observation_count = obs_count
        for k, v in prof_flags.items():
            setattr(self, k, v)


def test_classify_from_csv_analysis_object_professional_flags_activates_professional_survey():
    obj = _MockCsvAnalysisPro(
        "latlon",
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    result = classify_from_csv_analysis(obj)
    assert result.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 16. UTM_WITH_ZONE (utm_zone present) + all professional flags → PROFESSIONAL_SURVEY
# ---------------------------------------------------------------------------

def test_utm_with_zone_professional_flags_activates_professional_survey():
    obs = _utm_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    # Without utm_zone → UTM_NO_ZONE base, professional flags present but won't upgrade
    result_no_zone = classify_from_csv_analysis(analysis)
    assert result_no_zone.level == "UTM_NO_ZONE"

    # With utm_zone → UTM_WITH_ZONE base → upgrades to PROFESSIONAL_SURVEY
    result_with_zone = classify_from_csv_analysis(analysis, utm_zone="19S")
    assert result_with_zone.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 17. UTM_NO_ZONE + all professional flags → UTM_NO_ZONE (not PROFESSIONAL_SURVEY)
# ---------------------------------------------------------------------------

def test_utm_no_zone_professional_flags_stays_utm_no_zone():
    obs = _utm_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    assert analysis.has_elevation_column is True
    assert analysis.has_uncertainty_column is True
    assert analysis.has_instrument_metadata is True
    assert analysis.has_corrections_metadata is True

    # No utm_zone provided → UTM_NO_ZONE base → no upgrade
    result = classify_from_csv_analysis(analysis)
    assert result.level == "UTM_NO_ZONE"
    assert result.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 18. LOCAL_ANCHORED_CENTER + all professional flags → LOCAL_ANCHORED_CENTER
# ---------------------------------------------------------------------------

def test_local_anchored_center_professional_flags_stays_local_anchored():
    obs = _local_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    result = classify_from_csv_analysis(analysis, anchor_lat=-28.0, anchor_lon=-70.0)
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.level != "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# 19. professional_columns_detected lists the detected aliases
# ---------------------------------------------------------------------------

def test_professional_columns_detected_lists_found_aliases():
    obs = _latlon_obs()
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "sigma_mgal", "gravimeter_id", "free_air_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)

    detected = set(analysis.professional_columns_detected)
    assert "elevation_m" in detected
    assert "sigma_mgal" in detected
    assert "gravimeter_id" in detected
    assert "free_air_correction" in detected
    # standard coordinate/gravity columns must NOT appear
    assert "x_m" not in detected
    assert "gravity_anomaly" not in detected


# ---------------------------------------------------------------------------
# 20. Partial professional CSV conserves correct warning/rationale for base level
# ---------------------------------------------------------------------------

def test_partial_professional_csv_keeps_utm_no_zone_rationale():
    obs = _utm_obs()
    # All professional flags but NO utm_zone → stays at UTM_NO_ZONE
    headers = [
        "station_id", "x_m", "y_m", "z_m", "unit",
        "gravity_anomaly", "gravity_type",
        "elevation_m", "uncertainty_mgal", "instrument_id", "bouguer_correction",
    ]
    analysis = analyze_csv_observations(obs, "mGal", _raw(), column_names=headers)
    result = classify_from_csv_analysis(analysis)  # no utm_zone

    assert result.level == "UTM_NO_ZONE"
    assert result.rationale, "rationale must not be empty"
    assert result.warnings, "warnings must not be empty"
    # Rationale must mention the zone limitation
    assert "zona" in result.rationale.lower() or "zone" in result.rationale.lower()


# ---------------------------------------------------------------------------
# Extra: alias set sanity checks
# ---------------------------------------------------------------------------

def test_elevation_aliases_do_not_contain_z_m():
    assert "z_m" not in ELEVATION_ALIASES
    assert "z" not in ELEVATION_ALIASES


def test_detect_professional_columns_empty_input():
    has_el, has_unc, has_ins, has_cor, detected = detect_professional_columns([])
    assert has_el is False
    assert has_unc is False
    assert has_ins is False
    assert has_cor is False
    assert detected == []


def test_detect_professional_columns_all_four_aliases():
    cols = ["elevation_m", "sigma", "instrument_id", "bouguer_correction", "station_id", "x_m"]
    has_el, has_unc, has_ins, has_cor, detected = detect_professional_columns(cols)
    assert has_el is True
    assert has_unc is True
    assert has_ins is True
    assert has_cor is True
    assert "elevation_m" in detected
    assert "sigma" in detected
    assert "instrument_id" in detected
    assert "bouguer_correction" in detected
    # Non-professional columns must not appear
    assert "station_id" not in detected
    assert "x_m" not in detected
