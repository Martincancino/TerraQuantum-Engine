import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from services.geophysics_service import build_uncertainty_diagnostics

def test_low_uncertainty():
    oq = {
        "quality_level": "GOOD",
        "coverage_ratio_x": 0.9,
        "coverage_ratio_z": 0.9,
        "signal_dynamic_range": 5.0,
        "g_std": 0.5,
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
    ts = {"overall_level": "GOOD"}
    
    res = build_uncertainty_diagnostics(oq, fd, ts)
    
    assert res["uncertainty_level"] == "LOW"
    assert res["uncertainty_score"] < 0.35
    assert len(res["drivers"]) == 0
    assert "apto para interpretación preliminar" in res["interpretation"]

def test_medium_uncertainty():
    oq = {
        "quality_level": "MEDIUM",
        "coverage_ratio_x": 0.5,  # driver 1
        "coverage_ratio_z": 0.9,
        "signal_dynamic_range": 5.0,
        "g_std": 0.5,
        "warnings": []
    }
    fd = {
        "fit_level": "MEDIUM", # driver 2
        "residualMap": []
    }
    ts = {"overall_level": "MEDIUM"} # driver 3
    
    res = build_uncertainty_diagnostics(oq, fd, ts)
    
    assert res["uncertainty_level"] == "MEDIUM"
    assert 0.35 <= res["uncertainty_score"] < 0.70
    assert len(res["drivers"]) > 0

def test_high_uncertainty():
    oq = {
        "quality_level": "LOW", # +0.30
        "coverage_ratio_x": 0.4, # +0.20 (ambos)
        "coverage_ratio_z": 0.4,
        "signal_dynamic_range": 1e-7, # +0.15
        "g_std": 1e-10, # +0.15
        "warnings": []
    }
    fd = {
        "fit_level": "LOW", # +0.40
        "residualMap": [
            {"residual_level": "HIGH"} for _ in range(30)
        ] + [
            {"residual_level": "LOW"} for _ in range(70)
        ] # > 25% -> +0.30
    }
    ts = {"overall_level": "LOW"} # +0.25
    
    res = build_uncertainty_diagnostics(oq, fd, ts)
    
    assert res["uncertainty_level"] == "HIGH"
    assert res["uncertainty_score"] >= 0.70
    assert res["uncertainty_score"] <= 1.0
    assert len(res["drivers"]) >= 5
    assert "Recolectar más observaciones" in res["recommended_action"]

def test_no_residual_map_and_warnings():
    oq = {
        "quality_level": "GOOD",
        "coverage_ratio_x": 1.0,
        "coverage_ratio_z": 1.0,
        "signal_dynamic_range": 10.0,
        "g_std": 1.0,
        "warnings": ["Warning: rango dinámico pobre."]
    }
    fd = {
        "fit_level": "GOOD"
        # sin residualMap
    }
    ts = {"overall_level": "GOOD"}
    
    res = build_uncertainty_diagnostics(oq, fd, ts)
    
    # Debe ser LOW pero con driver de señal
    assert "Señal gravimétrica con bajo rango dinámico." in res["drivers"]
    assert res["uncertainty_score"] == 0.15
    assert res["uncertainty_level"] == "LOW"

if __name__ == "__main__":
    print("Running test_geophysics_uncertainty_diagnostics...")
    test_low_uncertainty()
    test_medium_uncertainty()
    test_high_uncertainty()
    test_no_residual_map_and_warnings()
    print("PASS: test_geophysics_uncertainty_diagnostics.py")
