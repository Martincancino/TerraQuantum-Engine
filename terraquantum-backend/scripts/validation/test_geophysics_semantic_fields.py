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
    valid_file_path = mock_data_dir / "valid_minimal_bouguer_mgal.csv"
    
    print("Testing inversion with new semantic fields...")
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
        sys.exit(1)
        
    resp_data = response.json()
    if resp_data.get("status") != "done":
        print(f"FAIL: Expected status='done', got {resp_data.get('status')}")
        sys.exit(1)
        
    inversion_result = resp_data.get("inversionResult")
    if not inversion_result:
        print("FAIL: inversionResult missing")
        sys.exit(1)
        
    all_passed = True
    
    # Check voxels
    voxels = inversion_result.get("voxels", [])
    if not voxels:
        print("FAIL: No voxels returned")
        all_passed = False
    else:
        v = voxels[0]
        if "grade" not in v: print("FAIL: voxel missing legacy 'grade'"); all_passed = False
        if "probability" not in v: print("FAIL: voxel missing legacy 'probability'"); all_passed = False
        if "anomaly_intensity" not in v: print("FAIL: voxel missing 'anomaly_intensity'"); all_passed = False
        if "target_score" not in v: print("FAIL: voxel missing 'target_score'"); all_passed = False
        if "modeled_density_index" not in v: print("FAIL: voxel missing 'modeled_density_index'"); all_passed = False
        if "density_anomaly_score" not in v: print("FAIL: voxel missing 'density_anomaly_score'"); all_passed = False

    # Check best_target
    best_target = inversion_result.get("best_target", {})
    if not best_target:
        print("FAIL: best_target missing")
        all_passed = False
    else:
        if "grade" not in best_target: print("FAIL: best_target missing legacy 'grade'"); all_passed = False
        if "probability" not in best_target: print("FAIL: best_target missing legacy 'probability'"); all_passed = False
        if "anomaly_intensity" not in best_target: print("FAIL: best_target missing 'anomaly_intensity'"); all_passed = False
        if "target_score" not in best_target: print("FAIL: best_target missing 'target_score'"); all_passed = False
        if "confidence_level" not in best_target: print("FAIL: best_target missing 'confidence_level'"); all_passed = False

    # Check report
    report = inversion_result.get("report", {})
    if not report:
        print("FAIL: report missing")
        all_passed = False
    else:
        if "avg_grade" not in report: print("FAIL: report missing legacy 'avg_grade'"); all_passed = False
        if "recommendation" not in report: print("FAIL: report missing legacy 'recommendation'"); all_passed = False
        if "avg_anomaly_intensity" not in report: print("FAIL: report missing 'avg_anomaly_intensity'"); all_passed = False
        if "max_target_score" not in report: print("FAIL: report missing 'max_target_score'"); all_passed = False
        if "drill_recommendation" not in report: print("FAIL: report missing 'drill_recommendation'"); all_passed = False
        if "confidence_level" not in report: print("FAIL: report missing 'confidence_level'"); all_passed = False
        semantic_note = report.get("semantic_note", "")
        if "no representan ley mineral confirmada" not in semantic_note:
            print("FAIL: report missing or bad 'semantic_note'")
            all_passed = False
            
    if all_passed:
        print("ALL TESTS PASS: Semantic fields are properly populated and backward compatible.")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
