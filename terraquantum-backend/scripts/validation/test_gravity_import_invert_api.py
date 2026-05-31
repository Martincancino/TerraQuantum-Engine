import sys
from pathlib import Path
from fastapi.testclient import TestClient

current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent.parent
sys.path.insert(0, str(backend_dir))

from main import app

client = TestClient(app)

def main():
    mock_data_dir = current_dir / "mock_data" / "gravity_csv_v1"
    
    all_passed = True
    
    print("Test 1: Testing /gravity-import/invert with valid CSV and small parameters...")
    valid_file_path = mock_data_dir / "valid_minimal_bouguer_mgal.csv"
    with open(valid_file_path, "rb") as f:
        data = {
            "project_id": "csv_import_test",
            "run_id": "run_001",
            "depth": 20,
            "nir": 83,
            "fe": 79,
            "region": "norte_chile",
            "lat": "-22.28",
            "lon": "-68.89",
            "nx": 4,
            "ny": 4,
            "nz": 4,
            "block_size": 10,
            "cutoff_radius": 300,
            "lambda_mag": 0.00005,
            "alpha_spatial": 1.0,
            "strict": "true",
            "allow_g_raw": "false"
        }
        response = client.post(
            "/gravity-import/invert",
            data=data,
            files={"file": ("valid_minimal_bouguer_mgal.csv", f, "text/csv")}
        )
    
    if response.status_code != 200:
        print(f"FAIL: Expected 200, got {response.status_code}")
        all_passed = False
    else:
        resp_data = response.json()
        if resp_data.get("status") != "done":
            print(f"FAIL: Expected status='done', got {resp_data.get('status')}")
            all_passed = False
        if resp_data.get("stage") != "inversion":
            print(f"FAIL: Expected stage='inversion', got {resp_data.get('stage')}")
            all_passed = False
        if "importMetadata" not in resp_data or not resp_data["importMetadata"]:
            print("FAIL: Expected importMetadata to be populated")
            all_passed = False
        elif resp_data["importMetadata"].get("gravity_column_used") != "g":
            print(f"FAIL: Expected gravity_column_used='g', got {resp_data['importMetadata'].get('gravity_column_used')}")
            all_passed = False
        if "inversionResult" not in resp_data or not resp_data["inversionResult"]:
            print("FAIL: Expected inversionResult to be populated")
            all_passed = False
        
        if all_passed:
            print("  PASS")

    print("\nTest 2: Testing /gravity-import/invert with invalid CSV (missing unit)...")
    invalid_file_path = mock_data_dir / "invalid_missing_unit.csv"
    with open(invalid_file_path, "rb") as f:
        data = {
            "depth": 20, "nir": 83, "fe": 79, "region": "norte_chile",
            "lat": "-22.28", "lon": "-68.89", "nx": 4, "ny": 4, "nz": 4,
            "block_size": 10, "cutoff_radius": 300, "lambda_mag": 0.00005,
            "alpha_spatial": 1.0, "strict": "true", "allow_g_raw": "false"
        }
        response = client.post(
            "/gravity-import/invert",
            data=data,
            files={"file": ("invalid_missing_unit.csv", f, "text/csv")}
        )
        
    if response.status_code != 200:
        print(f"FAIL: Expected 200, got {response.status_code}")
        all_passed = False
    else:
        resp_data = response.json()
        if resp_data.get("status") != "error":
            print(f"FAIL: Expected status='error', got {resp_data.get('status')}")
            all_passed = False
        if resp_data.get("stage") != "import":
            print(f"FAIL: Expected stage='import', got {resp_data.get('stage')}")
            all_passed = False
        if not resp_data.get("errors"):
            print("FAIL: Expected errors to be populated")
            all_passed = False
        if resp_data.get("inversionResult") is not None:
            print("FAIL: Expected inversionResult to be null")
            all_passed = False
        
        print("  PASS")

    print("\nTest 3: Testing /gravity-import/invert with fake extension...")
    data = {
        "depth": 20, "nir": 83, "fe": 79, "region": "norte_chile",
        "lat": "-22.28", "lon": "-68.89", "nx": 4, "ny": 4, "nz": 4,
        "block_size": 10, "cutoff_radius": 300, "lambda_mag": 0.00005,
        "alpha_spatial": 1.0, "strict": "true", "allow_g_raw": "false"
    }
    response = client.post(
        "/gravity-import/invert",
        data=data,
        files={"file": ("fake_file.txt", b"dummy content", "text/plain")}
    )
    if response.status_code != 400:
        print(f"FAIL: Expected 400, got {response.status_code}")
        all_passed = False
    else:
        print("  PASS")

    if all_passed:
        print("\nALL TESTS PASS")
    else:
        print("\nSOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
