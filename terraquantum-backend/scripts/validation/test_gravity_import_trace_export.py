import sys
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from fastapi.testclient import TestClient

current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent.parent
sys.path.insert(0, str(backend_dir))

from main import app
from core.config import PROJECTS_DIR
from core.block_model_store import get_project_run_detail, export_project_run_zip

client = TestClient(app)

def main():
    mock_data_dir = current_dir / "mock_data" / "gravity_csv_v1"
    valid_file_path = mock_data_dir / "valid_minimal_bouguer_mgal.csv"
    
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    project_1 = f"csv_trace_export_test_{suffix}"
    run_1 = "run_001"
    
    project_2 = f"legacy_trace_test_{suffix}"
    run_2 = "run_legacy"
    
    dir_1 = PROJECTS_DIR / project_1
    dir_2 = PROJECTS_DIR / project_2
    
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
    
    print("Test 1: Creating run using /gravity-import/invert...")
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
        
    if response.status_code != 200 or response.json().get("status") != "done":
        print(f"FAIL: Invert failed. Code: {response.status_code}")
        all_passed = False
    else:
        print("  PASS")

    print("\nTest 2: Verifying with get_project_run_detail...")
    detail_1 = get_project_run_detail(project_1, run_1)
    if not detail_1.get("files", {}).get("source_gravity"):
        print("FAIL: files.source_gravity should be True")
        all_passed = False
    if not detail_1.get("files", {}).get("gravity_import_metadata"):
        print("FAIL: files.gravity_import_metadata should be True")
        all_passed = False
    
    meta = detail_1.get("gravityImportMetadata")
    if meta is None:
        print("FAIL: gravityImportMetadata is None")
        all_passed = False
    elif meta.get("import_metadata", {}).get("gravity_column_used") != "g":
        print("FAIL: Bad gravity_column_used in gravityImportMetadata")
        all_passed = False
        
    if not detail_1.get("sourceGravityExists"):
        print("FAIL: sourceGravityExists should be True")
        all_passed = False
    path_val = detail_1.get("sourceGravityPath")
    if not path_val or not path_val.endswith("source_gravity.csv"):
        print("FAIL: sourceGravityPath is incorrect")
        all_passed = False
        
    if all_passed:
        print("  PASS")
        
    print("\nTest 3: Exporting ZIP and verifying contents...")
    try:
        zip_path = export_project_run_zip(project_1, run_1)
        if not zip_path.exists():
            print("FAIL: ZIP file was not created")
            all_passed = False
        else:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                expected = [
                    "source_gravity.csv",
                    "gravity_import_metadata.json",
                    "block_model.parquet",
                    "block_model_anomaly.parquet",
                    "inputs.json",
                    "observations.json",
                    "report.json"
                ]
                for exp in expected:
                    if exp not in names:
                        print(f"FAIL: Missing {exp} in ZIP")
                        all_passed = False
            if all_passed:
                print("  PASS")
    except Exception as e:
        print(f"FAIL: Export failed with exception {e}")
        all_passed = False

    print("\nTest 4: Verifying legacy run without CSV files...")
    run_2_dir = dir_2 / "runs" / run_2
    run_2_dir.mkdir(parents=True, exist_ok=True)
    # create some dummy file to simulate existence
    (run_2_dir / "report.json").write_text('{"legacy": true}')
    
    detail_2 = get_project_run_detail(project_2, run_2)
    if detail_2.get("files", {}).get("source_gravity") is not False:
        print("FAIL: legacy files.source_gravity should be False")
        all_passed = False
    if detail_2.get("files", {}).get("gravity_import_metadata") is not False:
        print("FAIL: legacy files.gravity_import_metadata should be False")
        all_passed = False
    if detail_2.get("gravityImportMetadata") is not None:
        print("FAIL: legacy gravityImportMetadata should be None")
        all_passed = False
    if detail_2.get("sourceGravityExists") is not False:
        print("FAIL: legacy sourceGravityExists should be False")
        all_passed = False
    if detail_2.get("sourceGravityPath") is not None:
        print("FAIL: legacy sourceGravityPath should be None")
        all_passed = False
        
    if all_passed:
        print("  PASS")

    if all_passed:
        print("\nALL TESTS PASS")
    else:
        print("\nSOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
