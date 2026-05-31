import sys
import os
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).parent.parent.parent))

from main import app

client = TestClient(app)

def build_valid_payload():
    return {
        "project_id": "api_sweep_test",
        "run_id": "run_001",
        "nx": 4,
        "ny": 4,
        "nz": 4,
        "block_size": 10,
        "depth": 20,
        "cutoff_radius": 300,
        "lambda_mag": 0.00005,
        "alpha_spatial": 1.0,
        "lat": "-22.28",
        "lon": "-68.89",
        "nir": 83,
        "fe": 79,
        "region": "norte_chile",
        "observations": [
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
        ],
        "lambda_values": [0.00001, 0.00005],
        "alpha_values": [0.5, 1.0]
    }

def test_api_sweep_valid():
    payload = build_valid_payload()
    response = client.post("/geophysics-sensitivity-sweep", json=payload)
    
    assert response.status_code == 200, f"Error en endpoint: {response.text}"
    data = response.json()
    
    assert data["status"] == "done"
    assert data["case_count"] == 4
    assert "best_case" in data
    assert "cases" in data
    assert len(data["cases"]) == 4

def test_api_sweep_negative_lambda():
    payload = build_valid_payload()
    payload["lambda_values"] = [-0.00001, 0.00005]
    
    response = client.post("/geophysics-sensitivity-sweep", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "negativos" in data["detail"].lower()

def test_api_sweep_max_cases():
    payload = build_valid_payload()
    payload["lambda_values"] = [0.00001, 0.00005, 0.0001]
    payload["alpha_values"] = [0.5, 1.0, 1.5]
    payload["max_cases"] = 5
    
    response = client.post("/geophysics-sensitivity-sweep", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["case_count"] == 5

if __name__ == "__main__":
    print("Running test_geophysics_sensitivity_api...")
    test_api_sweep_valid()
    test_api_sweep_negative_lambda()
    test_api_sweep_max_cases()
    print("PASS: test_geophysics_sensitivity_api.py")
