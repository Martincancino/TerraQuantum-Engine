import sys
import os
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_sensitivity_sweep

def build_mock_params() -> GeophysicsInvertInput:
    return GeophysicsInvertInput(
        project_id="test_sweep",
        run_id="run_1",
        nx=4,
        ny=4,
        nz=4,
        block_size=10,
        depth=20,
        cutoff_radius=300,
        lambda_mag=0.00005,
        alpha_spatial=1.0,
        lat="-22.28",
        lon="-68.89",
        nir=83,
        fe=79,
        region="norte_chile",
        observations=[
            {"x_m": 0, "y_m": 0, "z_m": 100, "g": 8.0e-7},
            {"x_m": 10, "y_m": 0, "z_m": 100, "g": 8.1e-7},
            {"x_m": 20, "y_m": 0, "z_m": 100, "g": 8.2e-7},
            {"x_m": 0, "y_m": 10, "z_m": 100, "g": 8.3e-7},
            {"x_m": 10, "y_m": 10, "z_m": 100, "g": 8.4e-7},
            {"x_m": 20, "y_m": 10, "z_m": 100, "g": 8.5e-7},
            {"x_m": 0, "y_m": 20, "z_m": 100, "g": 8.6e-7},
            {"x_m": 10, "y_m": 20, "z_m": 100, "g": 8.7e-7},
            {"x_m": 20, "y_m": 20, "z_m": 100, "g": 8.8e-7},
            {"x_m": 30, "y_m": 30, "z_m": 100, "g": 8.9e-7},
        ]
    )

def test_run_geophysics_sensitivity_sweep_basic():
    params = build_mock_params()
    # 2 lambda x 2 alpha = 4 cases
    res = run_geophysics_sensitivity_sweep(
        params,
        lambda_values=[0.1, 0.2],
        alpha_values=[0.01, 0.02]
    )
    
    assert res["status"] == "done"
    assert res["case_count"] == 4
    assert len(res["cases"]) == 4
    assert res["best_case"] is not None
    
    # Check best case structure
    bc = res["best_case"]
    assert "case_id" in bc
    assert "lambda_mag" in bc
    assert "alpha_spatial" in bc
    assert "fit_level" in bc
    assert "normalized_rmse" in bc
    assert "residual_rmse" in bc
    
    # Ensure ranked correctly
    assert res["cases"][0]["normalized_rmse"] <= res["cases"][-1]["normalized_rmse"]

def test_run_geophysics_sensitivity_sweep_max_cases():
    params = build_mock_params()
    # 3 lambda x 3 alpha = 9 cases -> max_cases=5 -> 5 cases
    res = run_geophysics_sensitivity_sweep(
        params,
        lambda_values=[0.1, 0.2, 0.3],
        alpha_values=[0.01, 0.02, 0.03],
        max_cases=5
    )
    
    assert res["case_count"] == 5
    assert len(res["cases"]) == 5

def test_run_geophysics_sensitivity_sweep_invalid_values():
    params = build_mock_params()
    
    try:
        run_geophysics_sensitivity_sweep(
            params,
            lambda_values=[-0.1, 0.2]
        )
        assert False, "Should have raised ValueError for negative lambda"
    except ValueError as e:
        assert "lambda_values no puede tener valores negativos" in str(e)
        
    try:
        run_geophysics_sensitivity_sweep(
            params,
            alpha_values=[-0.01, 0.02]
        )
        assert False, "Should have raised ValueError for negative alpha"
    except ValueError as e:
        assert "alpha_values no puede tener valores negativos" in str(e)

if __name__ == "__main__":
    print("Running test_geophysics_sensitivity_sweep...")
    test_run_geophysics_sensitivity_sweep_basic()
    test_run_geophysics_sensitivity_sweep_max_cases()
    test_run_geophysics_sensitivity_sweep_invalid_values()
    print("PASS: test_geophysics_sensitivity_sweep.py")
