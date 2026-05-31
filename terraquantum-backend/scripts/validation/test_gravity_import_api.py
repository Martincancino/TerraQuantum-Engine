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
    
    print("Testing /gravity-import/preview with valid CSV...")
    valid_file_path = mock_data_dir / "valid_minimal_bouguer_mgal.csv"
    with open(valid_file_path, "rb") as f:
        response = client.post(
            "/gravity-import/preview",
            files={"file": ("valid_minimal_bouguer_mgal.csv", f, "text/csv")}
        )
    
    if response.status_code != 200:
        print(f"FAIL: Expected 200, got {response.status_code}")
        all_passed = False
    else:
        data = response.json()
        if data["status"] != "ok":
            print(f"FAIL: Expected status='ok', got {data['status']}")
            all_passed = False
        if data["totalObservations"] < 10:
            print("FAIL: totalObservations < 10")
            all_passed = False
        if data["previewCount"] > 20:
            print("FAIL: previewCount > 20")
            all_passed = False
        if data["importMetadata"]["gravity_column_used"] != "g":
            print(f"FAIL: expected gravity_column_used='g', got {data['importMetadata']['gravity_column_used']}")
            all_passed = False
        if data["importMetadata"]["unit_internal"] != "m/s²":
            print(f"FAIL: expected unit_internal='m/s²', got {data['importMetadata']['unit_internal']}")
            all_passed = False
        if all_passed:
            print("  PASS")
            
    print("Testing /gravity-import/preview with invalid CSV...")
    invalid_file_path = mock_data_dir / "invalid_missing_unit.csv"
    with open(invalid_file_path, "rb") as f:
        response = client.post(
            "/gravity-import/preview",
            files={"file": ("invalid_missing_unit.csv", f, "text/csv")}
        )
        
    if response.status_code != 200:
        print(f"FAIL: Expected 200 for invalid CSV logic, got {response.status_code}")
        all_passed = False
    else:
        data = response.json()
        if data["status"] != "error":
            print(f"FAIL: Expected status='error', got {data['status']}")
            all_passed = False
        if not data["errors"]:
            print("FAIL: Expected errors list to be populated")
            all_passed = False
        print("  PASS")
            
    print("Testing /gravity-import/preview with non-CSV extension...")
    response = client.post(
        "/gravity-import/preview",
        files={"file": ("fake_file.txt", b"dummy content", "text/plain")}
    )
    if response.status_code != 400:
        print(f"FAIL: Expected 400 for bad extension, got {response.status_code}")
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
