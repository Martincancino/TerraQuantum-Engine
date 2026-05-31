import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from services.geophysics_service import build_sensor_quality_flags

def test_no_residual_map():
    fd = {}
    res = build_sensor_quality_flags(fd)
    assert res["sensor_count"] == 0
    assert res["flagged_count"] == 0
    assert res["flag_level"] == "LOW"
    assert res["flagged_sensors"] == []

def test_clean_case():
    fd = {
        "residualMap": [
            {"residual_level": "LOW", "normalized_residual": 0.1, "abs_residual": 1e-5},
            {"residual_level": "MEDIUM", "normalized_residual": 0.5, "abs_residual": 2e-5}
        ]
    }
    res = build_sensor_quality_flags(fd)
    assert res["sensor_count"] == 2
    assert res["flagged_count"] == 0
    assert res["flag_level"] == "LOW"
    assert len(res["flagged_sensors"]) == 0

def test_high_sensors():
    fd = {
        "residualMap": [
            {"sensor_index": 0, "residual_level": "LOW", "normalized_residual": 0.1, "abs_residual": 1e-5},
            {"sensor_index": 1, "residual_level": "HIGH", "normalized_residual": 0.6, "abs_residual": 5e-5}
        ]
    }
    res = build_sensor_quality_flags(fd)
    assert res["sensor_count"] == 2
    assert res["flagged_count"] == 1
    # 1/2 = 0.5 > 0.25 -> HIGH flag_level
    assert res["flag_level"] == "HIGH"
    
    assert len(res["flagged_sensors"]) == 1
    sensor = res["flagged_sensors"][0]
    assert sensor["sensor_index"] == 1
    assert "HIGH_RESIDUAL" in sensor["flags"]
    assert sensor["review_priority"] == "MEDIUM"  # since no extreme normalized residual

def test_extreme_case():
    fd = {
        "residualMap": [
            {"sensor_index": 2, "residual_level": "MEDIUM", "normalized_residual": 0.9, "abs_residual": 3e-5}
        ]
    }
    res = build_sensor_quality_flags(fd)
    assert res["flagged_count"] == 1
    
    sensor = res["flagged_sensors"][0]
    assert "EXTREME_NORMALIZED_RESIDUAL" in sensor["flags"]
    assert sensor["review_priority"] == "HIGH"

def test_many_flags():
    # 100 sensors, 30 flagged -> ratio 0.3 -> HIGH flag_level
    res_map = [{"residual_level": "LOW", "normalized_residual": 0.1, "abs_residual": 1e-5} for _ in range(70)]
    res_map.extend([{"sensor_index": i, "residual_level": "HIGH", "normalized_residual": 0.9, "abs_residual": 5e-5} for i in range(30)])
    
    fd = {"residualMap": res_map}
    res = build_sensor_quality_flags(fd)
    
    assert res["sensor_count"] == 100
    assert res["flagged_count"] == 30
    assert res["flagged_ratio"] == 0.30
    assert res["flag_level"] == "HIGH"
    assert len(res["flagged_sensors"]) == 30

if __name__ == "__main__":
    print("Running test_geophysics_sensor_flags...")
    test_no_residual_map()
    test_clean_case()
    test_high_sensors()
    test_extreme_case()
    test_many_flags()
    print("PASS: test_geophysics_sensor_flags.py")
