import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from services.geophysics_service import build_geophysical_technical_summary

def test_good_case():
    oq = {
        "quality_level": "GOOD",
        "observation_count": 100,
        "coverage_ratio_x": 0.9,
        "coverage_ratio_z": 0.8,
        "warnings": []
    }
    fd = {
        "fit_level": "GOOD",
        "residualMap": [
            {"residual_level": "LOW"} for _ in range(95)
        ] + [
            {"residual_level": "HIGH"} for _ in range(5)
        ]
    }
    
    res = build_geophysical_technical_summary(oq, fd)
    
    assert res["overall_level"] == "GOOD"
    assert res["survey_level"] == "GOOD"
    assert res["fit_level"] == "GOOD"
    assert res["residual_level"] == "GOOD"  # 5/100 <= 0.10
    assert "buena cobertura" in res["summary"]

def test_medium_case():
    oq = {
        "quality_level": "MEDIUM",
        "observation_count": 100,
        "coverage_ratio_x": 0.5,
        "coverage_ratio_z": 0.5,
        "warnings": ["Cobertura baja."]
    }
    fd = {
        "fit_level": "GOOD",
        "residualMap": [
            {"residual_level": "LOW"} for _ in range(80)
        ] + [
            {"residual_level": "HIGH"} for _ in range(20)
        ]
    }
    
    res = build_geophysical_technical_summary(oq, fd)
    
    assert res["overall_level"] == "MEDIUM"
    assert res["residual_level"] == "MEDIUM"  # 20/100 <= 0.25
    assert len(res["warnings"]) == 1
    assert res["warnings"][0] == "Cobertura baja."

def test_low_case():
    oq = {
        "quality_level": "GOOD",
        "observation_count": 50,
        "coverage_ratio_x": 0.8,
        "coverage_ratio_z": 0.8,
        "warnings": []
    }
    fd = {
        "fit_level": "LOW",
        "residualMap": [
            {"residual_level": "LOW"} for _ in range(20)
        ] + [
            {"residual_level": "HIGH"} for _ in range(30)
        ]
    }
    
    res = build_geophysical_technical_summary(oq, fd)
    
    assert res["overall_level"] == "LOW"
    assert res["fit_level"] == "LOW"
    assert res["residual_level"] == "LOW"  # 30/50 > 0.25
    assert len(res["warnings"]) == 2  # fit_level LOW warning + residual_level LOW warning
    assert any("No usar el modelo" in step for step in res["recommended_next_steps"])

def test_no_residual_map():
    oq = {"quality_level": "GOOD", "warnings": ["w1"]}
    fd = {"fit_level": "GOOD"}  # no residualMap
    
    res = build_geophysical_technical_summary(oq, fd)
    
    assert res["overall_level"] == "GOOD"
    assert res["residual_level"] == "GOOD"
    assert res["survey_level"] == "GOOD"
    assert len(res["warnings"]) == 1
    assert res["warnings"][0] == "w1"

def test_warnings_qaqc():
    oq = {"quality_level": "GOOD", "warnings": ["QAQC Error"]}
    fd = {"fit_level": "GOOD", "residualMap": []}
    
    res = build_geophysical_technical_summary(oq, fd)
    assert "QAQC Error" in res["warnings"]

if __name__ == "__main__":
    print("Running test_geophysics_technical_summary...")
    test_good_case()
    test_medium_case()
    test_low_case()
    test_no_residual_map()
    test_warnings_qaqc()
    print("PASS: test_geophysics_technical_summary.py")
