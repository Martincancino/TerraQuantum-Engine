"""
R3.5-B tests — spatial_readiness_service.py

Covers all 7 spatial readiness levels (0–5), caps, acknowledgement flags,
blocked/allowed outputs, classify_from_csv_analysis with dict and object inputs.
"""
import pytest

from schemas.gravity_import_schema import (
    SPATIAL_LEVEL_MAX_FAVORABILITY,
    SPATIAL_LEVEL_MAX_PRIORITY,
    SPATIAL_LEVEL_RANKS,
)
from services.spatial_readiness_service import (
    classify_from_csv_analysis,
    classify_spatial_readiness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(**kwargs):
    """Thin wrapper with sensible defaults."""
    defaults = dict(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
    )
    defaults.update(kwargs)
    return classify_spatial_readiness(**defaults)


# ---------------------------------------------------------------------------
# Level classification
# ---------------------------------------------------------------------------

def test_no_spatial_data_solo_gravedad():
    """Solo gravedad — no station coordinates → NO_SPATIAL_DATA."""
    result = classify_spatial_readiness(
        coordinate_system_detected=None,
        has_station_coordinates=False,
    )
    assert result.level == "NO_SPATIAL_DATA"
    assert result.level_rank == 0


def test_no_spatial_data_station_id_sin_coords():
    """station_id present but no coordinate data → NO_SPATIAL_DATA."""
    result = classify_spatial_readiness(
        coordinate_system_detected="unknown",
        has_station_coordinates=False,
    )
    assert result.level == "NO_SPATIAL_DATA"
    assert result.level_rank == 0


def test_no_spatial_data_unknown_detected_no_flags():
    """Detected unknown + no explicit flags → NO_SPATIAL_DATA."""
    result = classify_spatial_readiness(
        coordinate_system_detected="unknown",
        has_station_coordinates=True,
        has_latlon_per_station=False,
        has_utm_coordinates=False,
        has_local_coordinates=False,
    )
    assert result.level == "NO_SPATIAL_DATA"


def test_local_unanchored_local_xy_sin_anchor():
    """Local x/y without anchor → LOCAL_UNANCHORED."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_anchor_latlon=False,
    )
    assert result.level == "LOCAL_UNANCHORED"
    assert result.level_rank == 1


def test_local_anchored_center_local_xy_con_anchor():
    """Local x/y with anchor lat/lon → LOCAL_ANCHORED_CENTER."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_anchor_latlon=True,
    )
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.level_rank == 2


def test_utm_no_zone_utm_sin_zona():
    """UTM coordinates without zone → UTM_NO_ZONE."""
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=False,
    )
    assert result.level == "UTM_NO_ZONE"
    assert result.level_rank == 2


def test_utm_with_zone_utm_con_zona():
    """UTM coordinates with zone declared → UTM_WITH_ZONE."""
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=True,
    )
    assert result.level == "UTM_WITH_ZONE"
    assert result.level_rank == 3


def test_geographic_coords_latlon_por_estacion():
    """lat/lon per station → GEOGRAPHIC_COORDS."""
    result = classify_spatial_readiness(
        coordinate_system_detected="latlon",
        has_station_coordinates=True,
    )
    assert result.level == "GEOGRAPHIC_COORDS"
    assert result.level_rank == 4


def test_professional_survey_utm_with_zone_plus_all_professional_fields():
    """UTM + zone + elevation + uncertainty + instrument + corrections → PROFESSIONAL_SURVEY."""
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=True,
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    assert result.level == "PROFESSIONAL_SURVEY"
    assert result.level_rank == 5


def test_professional_survey_latlon_plus_all_professional_fields():
    """lat/lon + elevation + uncertainty + instrument + corrections → PROFESSIONAL_SURVEY."""
    result = classify_spatial_readiness(
        coordinate_system_detected="latlon",
        has_station_coordinates=True,
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    assert result.level == "PROFESSIONAL_SURVEY"
    assert result.level_rank == 5


# ---------------------------------------------------------------------------
# Critical rule: anchor lat/lon must NOT elevate to GEOGRAPHIC_COORDS
# ---------------------------------------------------------------------------

def test_anchor_latlon_does_not_elevate_to_geographic_coords():
    """
    Anchor lat/lon is a user-declared central point.
    It must NOT produce GEOGRAPHIC_COORDS — that requires lat/lon per station.
    """
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_local_coordinates=True,
        has_anchor_latlon=True,
        has_latlon_per_station=False,
    )
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.level != "GEOGRAPHIC_COORDS"
    assert result.can_compute_voxel_latlon is False


def test_anchor_without_local_flag_stays_at_local_anchored():
    """Anchor + detected=local_meters → LOCAL_ANCHORED_CENTER, not GEOGRAPHIC_COORDS."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_anchor_latlon=True,
    )
    assert result.level == "LOCAL_ANCHORED_CENTER"


# ---------------------------------------------------------------------------
# Inversion flags
# ---------------------------------------------------------------------------

def test_no_spatial_data_blocks_3d_inversion():
    """NO_SPATIAL_DATA must have can_run_3d_inversion = False."""
    result = classify_spatial_readiness(
        coordinate_system_detected=None,
        has_station_coordinates=False,
    )
    assert result.can_run_3d_inversion is False
    assert result.can_run_local_conceptual_inversion is False


def test_local_unanchored_requires_acknowledgement():
    """LOCAL_UNANCHORED requires_user_acknowledgement = True, required_acknowledgement set."""
    result = _classify(
        coordinate_system_detected="local_meters",
        has_anchor_latlon=False,
    )
    assert result.level == "LOCAL_UNANCHORED"
    assert result.requires_user_acknowledgement is True
    assert result.required_acknowledgement == "ACK_LOCAL_CONCEPTUAL_ONLY"
    assert result.can_run_3d_inversion is False
    assert result.can_run_local_conceptual_inversion is True


def test_local_anchored_center_no_voxel_latlon():
    """LOCAL_ANCHORED_CENTER: can_compute_voxel_latlon must be False."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_anchor_latlon=True,
    )
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.can_compute_voxel_latlon is False
    assert result.can_run_3d_inversion is True
    assert result.can_use_dem is True
    assert result.can_compute_voxel_masl is True


def test_utm_no_zone_does_not_allow_dem():
    """UTM_NO_ZONE: can_use_dem = False, can_compute_voxel_masl = False."""
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=False,
    )
    assert result.level == "UTM_NO_ZONE"
    assert result.can_use_dem is False
    assert result.can_compute_voxel_masl is False
    assert result.can_compute_voxel_latlon is False
    assert result.can_run_3d_inversion is True
    assert result.requires_user_acknowledgement is True
    assert result.required_acknowledgement == "ACK_UTM_ZONE_MISSING"


def test_utm_with_zone_allows_dem_masl_latlon():
    """UTM_WITH_ZONE: DEM, MASL and voxel lat/lon all enabled."""
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=True,
    )
    assert result.level == "UTM_WITH_ZONE"
    assert result.can_use_dem is True
    assert result.can_compute_voxel_masl is True
    assert result.can_compute_voxel_latlon is True
    assert result.can_run_3d_inversion is True
    assert result.requires_user_acknowledgement is False


# ---------------------------------------------------------------------------
# Favorability caps
# ---------------------------------------------------------------------------

def test_favorability_cap_no_spatial_data():
    result = classify_spatial_readiness(
        coordinate_system_detected=None, has_station_coordinates=False
    )
    assert result.max_favorability_score_allowed == SPATIAL_LEVEL_MAX_FAVORABILITY["NO_SPATIAL_DATA"]
    assert result.max_favorability_score_allowed == 0.0


def test_favorability_cap_local_unanchored():
    result = _classify(coordinate_system_detected="local_meters", has_anchor_latlon=False)
    assert result.level == "LOCAL_UNANCHORED"
    assert result.max_favorability_score_allowed == 45.0


def test_favorability_cap_local_anchored_center():
    result = _classify(coordinate_system_detected="local_meters", has_anchor_latlon=True)
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.max_favorability_score_allowed == 45.0


def test_favorability_cap_utm_no_zone():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=False)
    assert result.level == "UTM_NO_ZONE"
    assert result.max_favorability_score_allowed == 60.0


def test_favorability_cap_utm_with_zone():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=True)
    assert result.level == "UTM_WITH_ZONE"
    assert result.max_favorability_score_allowed == 85.0


def test_favorability_cap_geographic_coords():
    result = _classify(coordinate_system_detected="latlon")
    assert result.level == "GEOGRAPHIC_COORDS"
    assert result.max_favorability_score_allowed == 100.0


def test_favorability_cap_professional_survey():
    result = classify_spatial_readiness(
        coordinate_system_detected="latlon",
        has_station_coordinates=True,
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    assert result.level == "PROFESSIONAL_SURVEY"
    assert result.max_favorability_score_allowed == 100.0


# ---------------------------------------------------------------------------
# Priority caps
# ---------------------------------------------------------------------------

def test_priority_cap_no_spatial_data():
    result = classify_spatial_readiness(
        coordinate_system_detected=None, has_station_coordinates=False
    )
    assert result.max_priority_class_allowed == "NONE"


def test_priority_cap_local_levels():
    for cs, anchor in [("local_meters", False), ("local_meters", True)]:
        result = _classify(coordinate_system_detected=cs, has_anchor_latlon=anchor)
        assert result.max_priority_class_allowed == "LOW_RELATIVE_PRIORITY"


def test_priority_cap_utm_no_zone():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=False)
    assert result.max_priority_class_allowed == "LOW_RELATIVE_PRIORITY"


def test_priority_cap_utm_with_zone():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=True)
    assert result.max_priority_class_allowed == "HIGH_RELATIVE_PRIORITY"


def test_priority_cap_geographic_coords():
    result = _classify(coordinate_system_detected="latlon")
    assert result.max_priority_class_allowed == "HIGH_RELATIVE_PRIORITY"


def test_priority_cap_professional_survey():
    result = classify_spatial_readiness(
        coordinate_system_detected="utm",
        has_station_coordinates=True,
        has_utm_zone=True,
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    assert result.max_priority_class_allowed == "HIGH_RELATIVE_PRIORITY"


# ---------------------------------------------------------------------------
# blocked_outputs correctness
# ---------------------------------------------------------------------------

def test_no_spatial_data_blocks_correct_outputs():
    result = classify_spatial_readiness(
        coordinate_system_detected=None, has_station_coordinates=False
    )
    assert "3d_inversion" in result.blocked_outputs
    assert "dem_coregistration" in result.blocked_outputs
    assert "voxel_masl" in result.blocked_outputs
    assert "voxel_latlon" in result.blocked_outputs


def test_local_unanchored_blocks_3d_inversion_output():
    result = _classify(coordinate_system_detected="local_meters", has_anchor_latlon=False)
    assert "3d_inversion" in result.blocked_outputs


def test_local_anchored_center_blocks_voxel_latlon_only():
    result = _classify(coordinate_system_detected="local_meters", has_anchor_latlon=True)
    assert "voxel_latlon" in result.blocked_outputs
    assert "3d_inversion" not in result.blocked_outputs
    assert "dem_coregistration" not in result.blocked_outputs


def test_utm_no_zone_blocks_dem_and_elevation():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=False)
    assert "dem_coregistration" in result.blocked_outputs
    assert "voxel_masl" in result.blocked_outputs
    assert "voxel_latlon" in result.blocked_outputs


def test_utm_with_zone_has_empty_blocked_outputs():
    result = _classify(coordinate_system_detected="utm", has_utm_zone=True)
    assert result.blocked_outputs == []


def test_geographic_coords_has_empty_blocked_outputs():
    result = _classify(coordinate_system_detected="latlon")
    assert result.blocked_outputs == []


# ---------------------------------------------------------------------------
# warnings and rationale non-empty for all levels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level_result", [
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected=None, has_station_coordinates=False
        ),
        id="NO_SPATIAL_DATA",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="local_meters", has_station_coordinates=True
        ),
        id="LOCAL_UNANCHORED",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="local_meters",
            has_station_coordinates=True,
            has_anchor_latlon=True,
        ),
        id="LOCAL_ANCHORED_CENTER",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="utm",
            has_station_coordinates=True,
            has_utm_zone=False,
        ),
        id="UTM_NO_ZONE",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="utm",
            has_station_coordinates=True,
            has_utm_zone=True,
        ),
        id="UTM_WITH_ZONE",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="latlon", has_station_coordinates=True
        ),
        id="GEOGRAPHIC_COORDS",
    ),
    pytest.param(
        classify_spatial_readiness(
            coordinate_system_detected="latlon",
            has_station_coordinates=True,
            has_elevation_column=True,
            has_uncertainty_column=True,
            has_instrument_metadata=True,
            has_corrections_metadata=True,
        ),
        id="PROFESSIONAL_SURVEY",
    ),
])
def test_warnings_and_rationale_non_empty_all_levels(level_result):
    assert level_result.rationale, f"rationale must not be empty for level={level_result.level}"
    assert level_result.warnings, f"warnings must not be empty for level={level_result.level}"


# ---------------------------------------------------------------------------
# Schema version and rank consistency
# ---------------------------------------------------------------------------

def test_schema_version_is_set():
    result = _classify(coordinate_system_detected="latlon")
    assert result.version == "spatial_readiness_v0_1"


def test_level_rank_matches_constants():
    for cs, kwargs, expected_level in [
        ("latlon", {}, "GEOGRAPHIC_COORDS"),
        ("utm", {"has_utm_zone": True}, "UTM_WITH_ZONE"),
        ("utm", {"has_utm_zone": False}, "UTM_NO_ZONE"),
        ("local_meters", {"has_anchor_latlon": True}, "LOCAL_ANCHORED_CENTER"),
        ("local_meters", {"has_anchor_latlon": False}, "LOCAL_UNANCHORED"),
    ]:
        result = _classify(coordinate_system_detected=cs, **kwargs)
        assert result.level == expected_level
        assert result.level_rank == SPATIAL_LEVEL_RANKS[expected_level]


# ---------------------------------------------------------------------------
# Professional survey partial fields should NOT upgrade
# ---------------------------------------------------------------------------

def test_professional_survey_requires_all_four_fields():
    """Missing any one professional field → stays at GEOGRAPHIC_COORDS."""
    base = dict(
        coordinate_system_detected="latlon",
        has_station_coordinates=True,
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    # All four present → PROFESSIONAL_SURVEY
    result_full = classify_spatial_readiness(**base)
    assert result_full.level == "PROFESSIONAL_SURVEY"

    # Remove each field one by one
    for missing_field in [
        "has_elevation_column",
        "has_uncertainty_column",
        "has_instrument_metadata",
        "has_corrections_metadata",
    ]:
        partial = {**base, missing_field: False}
        result = classify_spatial_readiness(**partial)
        assert result.level == "GEOGRAPHIC_COORDS", (
            f"Expected GEOGRAPHIC_COORDS when {missing_field}=False, got {result.level}"
        )


# ---------------------------------------------------------------------------
# classify_from_csv_analysis — dict input
# ---------------------------------------------------------------------------

def test_classify_from_csv_analysis_accepts_dict_latlon():
    csv_dict = {
        "observation_count": 20,
        "coordinate_system": {"detected": "latlon", "utm_zone": None},
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "GEOGRAPHIC_COORDS"


def test_classify_from_csv_analysis_accepts_dict_utm_with_zone_param():
    csv_dict = {
        "observation_count": 15,
        "coordinate_system": {"detected": "utm", "utm_zone": None},
    }
    result = classify_from_csv_analysis(csv_dict, utm_zone="19S")
    assert result.level == "UTM_WITH_ZONE"


def test_classify_from_csv_analysis_accepts_dict_utm_no_zone():
    csv_dict = {
        "observation_count": 15,
        "coordinate_system": {"detected": "utm", "utm_zone": None},
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "UTM_NO_ZONE"


def test_classify_from_csv_analysis_accepts_dict_local_with_anchor():
    csv_dict = {
        "observation_count": 12,
        "coordinate_system": {"detected": "local_meters", "utm_zone": None},
    }
    result = classify_from_csv_analysis(csv_dict, anchor_lat=-28.3, anchor_lon=-70.5)
    assert result.level == "LOCAL_ANCHORED_CENTER"


def test_classify_from_csv_analysis_accepts_dict_local_without_anchor():
    csv_dict = {
        "observation_count": 12,
        "coordinate_system": {"detected": "local_meters"},
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "LOCAL_UNANCHORED"


def test_classify_from_csv_analysis_dict_zero_obs_is_no_spatial_data():
    csv_dict = {
        "observation_count": 0,
        "coordinate_system": {"detected": "local_meters"},
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "NO_SPATIAL_DATA"


def test_classify_from_csv_analysis_dict_professional_fields():
    csv_dict = {
        "observation_count": 30,
        "coordinate_system": {"detected": "latlon"},
        "has_elevation_column": True,
        "has_uncertainty_column": True,
        "has_instrument_metadata": True,
        "has_corrections_metadata": True,
    }
    result = classify_from_csv_analysis(csv_dict)
    assert result.level == "PROFESSIONAL_SURVEY"


# ---------------------------------------------------------------------------
# classify_from_csv_analysis — object with attributes input
# ---------------------------------------------------------------------------

class _MockCoordSys:
    def __init__(self, detected, utm_zone=None):
        self.detected = detected
        self.utm_zone = utm_zone


class _MockCsvAnalysis:
    def __init__(self, obs_count, detected, utm_zone=None, **kwargs):
        self.observation_count = obs_count
        self.coordinate_system = _MockCoordSys(detected, utm_zone)
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_classify_from_csv_analysis_accepts_object_latlon():
    obj = _MockCsvAnalysis(20, "latlon")
    result = classify_from_csv_analysis(obj)
    assert result.level == "GEOGRAPHIC_COORDS"


def test_classify_from_csv_analysis_accepts_object_utm_with_zone_from_field():
    """UTM zone present on the coordinate_system object → UTM_WITH_ZONE."""
    obj = _MockCsvAnalysis(15, "utm", utm_zone="19S")
    result = classify_from_csv_analysis(obj)
    assert result.level == "UTM_WITH_ZONE"


def test_classify_from_csv_analysis_accepts_object_local_with_anchor():
    obj = _MockCsvAnalysis(10, "local_meters")
    result = classify_from_csv_analysis(obj, anchor_lat=-28.3, anchor_lon=-70.5)
    assert result.level == "LOCAL_ANCHORED_CENTER"


def test_classify_from_csv_analysis_accepts_object_professional():
    obj = _MockCsvAnalysis(
        25,
        "latlon",
        has_elevation_column=True,
        has_uncertainty_column=True,
        has_instrument_metadata=True,
        has_corrections_metadata=True,
    )
    result = classify_from_csv_analysis(obj)
    assert result.level == "PROFESSIONAL_SURVEY"


def test_classify_from_csv_analysis_object_anchor_does_not_elevate():
    """Anchor on object input must not produce GEOGRAPHIC_COORDS."""
    obj = _MockCsvAnalysis(10, "local_meters")
    result = classify_from_csv_analysis(obj, anchor_lat=-28.3, anchor_lon=-70.5)
    assert result.level == "LOCAL_ANCHORED_CENTER"
    assert result.level != "GEOGRAPHIC_COORDS"
    assert result.can_compute_voxel_latlon is False


# ---------------------------------------------------------------------------
# Explicit flags override detected string
# ---------------------------------------------------------------------------

def test_explicit_latlon_flag_overrides_detected():
    """has_latlon_per_station=True overrides coordinate_system_detected='local_meters'."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_latlon_per_station=True,
    )
    assert result.level == "GEOGRAPHIC_COORDS"


def test_explicit_utm_flag_overrides_detected_local():
    """has_utm_coordinates=True with has_utm_zone=True overrides detected='local_meters'."""
    result = classify_spatial_readiness(
        coordinate_system_detected="local_meters",
        has_station_coordinates=True,
        has_utm_coordinates=True,
        has_utm_zone=True,
    )
    assert result.level == "UTM_WITH_ZONE"
