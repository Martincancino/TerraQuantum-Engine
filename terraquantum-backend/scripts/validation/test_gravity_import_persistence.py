import sys
import shutil
import json
from datetime import datetime
from pathlib import Path
from fastapi.testclient import TestClient

current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent.parent
sys.path.insert(0, str(backend_dir))

from main import app
from core.config import PROJECTS_DIR

client = TestClient(app)

def main():
    mock_data_dir = current_dir / "mock_data" / "gravity_csv_v1"
    valid_file_path = mock_data_dir / "valid_minimal_bouguer_mgal.csv"
    invalid_file_path = mock_data_dir / "invalid_missing_unit.csv"
    
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    project_1 = f"csv_persistence_test_{suffix}"
    run_1 = "run_001"
    
    project_2 = f"csv_persistence_invalid_{suffix}"
    run_2 = "run_bad"
    
    dir_1 = PROJECTS_DIR / project_1
    dir_2 = PROJECTS_DIR / project_2
    
    # Cleanup before tests
    if dir_1.exists():
        try:
            shutil.rmtree(dir_1)
        except PermissionError:
            print(f"Warning: Could not remove {dir_1} due to PermissionError")
    if dir_2.exists():
        try:
            shutil.rmtree(dir_2)
        except PermissionError:
            print(f"Warning: Could not remove {dir_2} due to PermissionError")
        
    all_passed = True
    
    print("Test 1: Testing persistence with valid CSV and valid project/run ids...")
    with open(valid_file_path, "rb") as f:
        data = {
            "project_id": project_1,
            "run_id": run_1,
            "depth": 20, "nir": 83, "fe": 79, "region": "norte_chile",
            "lat": "-22.28", "lon": "-68.89", "nx": 4, "ny": 4, "nz": 4,
            "block_size": 10, "cutoff_radius": 300, "lambda_mag": 0.00005,
            "alpha_spatial": 1.0, "strict": "true", "allow_g_raw": "false"
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
            
        persistence = resp_data.get("importPersistence", {})
        if not persistence.get("persisted"):
            print("FAIL: Expected persisted=True")
            all_passed = False
            
        csv_path = PROJECTS_DIR / project_1 / "runs" / run_1 / "source_gravity.csv"
        meta_path = PROJECTS_DIR / project_1 / "runs" / run_1 / "gravity_import_metadata.json"
        
        if not csv_path.exists():
            print("FAIL: source_gravity.csv not created")
            all_passed = False
        if not meta_path.exists():
            print("FAIL: gravity_import_metadata.json not created")
            all_passed = False
        else:
            with open(meta_path, "r", encoding="utf-8") as meta_f:
                meta_json = json.load(meta_f)
                if meta_json.get("original_filename") != "valid_minimal_bouguer_mgal.csv":
                    print("FAIL: Bad original_filename in meta")
                    all_passed = False
                if meta_json.get("project_id") != project_1:
                    print("FAIL: Bad project_id in meta")
                    all_passed = False
                if meta_json.get("run_id") != run_1:
                    print("FAIL: Bad run_id in meta")
                    all_passed = False
                import_meta = meta_json.get("import_metadata", {})
                if import_meta.get("gravity_column_used") != "g":
                    print("FAIL: Bad gravity_column_used in meta")
                    all_passed = False
                if import_meta.get("unit_internal") != "m/s²":
                    print("FAIL: Bad unit_internal in meta")
                    all_passed = False

        if all_passed:
            print("  PASS")

    print("\nTest 2: Testing persistence with invalid CSV...")
    with open(invalid_file_path, "rb") as f:
        data = {
            "project_id": project_2,
            "run_id": run_2,
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
            
        csv_path_2 = PROJECTS_DIR / project_2 / "runs" / run_2 / "source_gravity.csv"
        if csv_path_2.exists():
            print("FAIL: source_gravity.csv should NOT exist for failed import")
            all_passed = False
            
        print("  PASS")

    print("\nTest 3: Testing persistence missing project_id/run_id...")
    with open(valid_file_path, "rb") as f:
        data = {
            "depth": 20, "nir": 83, "fe": 79, "region": "norte_chile",
            "lat": "-22.28", "lon": "-68.89", "nx": 4, "ny": 4, "nz": 4,
            "block_size": 10, "cutoff_radius": 300, "lambda_mag": 0.00005,
            "alpha_spatial": 1.0, "strict": "true", "allow_g_raw": "false"
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
            
        persistence = resp_data.get("importPersistence", {})
        if persistence.get("persisted") is not False:
            print("FAIL: Expected persisted=False")
            all_passed = False
        if not persistence.get("warning"):
            print("FAIL: Expected a warning message")
            all_passed = False
            
        print("  PASS")

    if all_passed:
        print("\nALL TESTS PASS")
    else:
        print("\nSOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
