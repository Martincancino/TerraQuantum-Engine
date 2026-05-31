import os
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent.parent
sys.path.insert(0, str(backend_dir))

from services.gravity_import_service import import_gravity_csv_v1

def main():
    mock_data_dir = current_dir / "mock_data" / "gravity_csv_v1"
    
    valid_files = [
        "valid_minimal_bouguer_mgal.csv",
        "valid_recommended_bouguer_mgal.csv",
        "valid_professional_bouguer_mgal.csv",
        "valid_synthetic_demo_ms2.csv"
    ]
    
    invalid_files = [
        "invalid_missing_unit.csv",
        "invalid_missing_gravity_type.csv",
        "invalid_less_than_10_rows.csv",
        "invalid_duplicate_coordinates.csv",
        "invalid_unknown_unit.csv",
        "invalid_non_numeric_g.csv",
        "invalid_all_zero_signal.csv",
        "invalid_g_raw_only_without_acceptance.csv"
    ]
    
    all_passed = True
    
    print("Testing VALID files...")
    for vf in valid_files:
        fpath = mock_data_dir / vf
        print(f"Testing {vf}...")
        file_passed = True
        res = import_gravity_csv_v1(fpath, strict=True)
        
        if res.status != "ok":
            print(f"  FAIL: Expected ok, got error: {res.errors}")
            file_passed = False
            all_passed = False
            continue
            
        if len(res.observations) < 10:
            print(f"  FAIL: Expected >=10 observations, got {len(res.observations)}")
            file_passed = False
            all_passed = False
            
        if res.import_metadata.valid_rows < 10:
            print(f"  FAIL: Expected >=10 valid_rows in metadata, got {res.import_metadata.valid_rows}")
            file_passed = False
            all_passed = False
            
        if not res.import_metadata.gravity_type:
            print("  FAIL: Expected gravity_type in metadata to be non-empty")
            file_passed = False
            all_passed = False
            
        if res.import_metadata.unit_internal != "m/s²":
            print("  FAIL: Internal unit is not m/s²")
            file_passed = False
            all_passed = False
            
        if vf in ("valid_minimal_bouguer_mgal.csv", "valid_recommended_bouguer_mgal.csv", "valid_synthetic_demo_ms2.csv"):
            if res.import_metadata.gravity_column_used != "g":
                print(f"  FAIL: Expected gravity_column_used == 'g', got {res.import_metadata.gravity_column_used}")
                file_passed = False
                all_passed = False
                
        if vf == "valid_professional_bouguer_mgal.csv":
            if res.import_metadata.gravity_column_used != "gravity_anomaly":
                print(f"  FAIL: Expected gravity_anomaly, used {res.import_metadata.gravity_column_used}")
                file_passed = False
                all_passed = False
                
        if vf == "valid_synthetic_demo_ms2.csv":
            if not res.import_metadata.is_demo:
                print("  FAIL: Expected is_demo=True")
                file_passed = False
                all_passed = False
                
        # Additional checks
        for o in res.observations:
            if not isinstance(o.g, float):
                print("  FAIL: g value is not float")
                file_passed = False
                all_passed = False
                break
                
        if file_passed:
            print("  PASS")

    print("\nTesting INVALID files...")
    for invf in invalid_files:
        fpath = mock_data_dir / invf
        print(f"Testing {invf}...")
        file_passed = True
        res = import_gravity_csv_v1(fpath, strict=True)
        
        if res.status != "error":
            print(f"  FAIL: Expected error, got ok for {invf}")
            file_passed = False
            all_passed = False
            continue
            
        if not res.errors:
            print(f"  FAIL: Expected errors list to be populated")
            file_passed = False
            all_passed = False
            
        if file_passed:
            print(f"  PASS (Errors found as expected: {res.errors[0]})")
            
    if all_passed:
        print("\nALL TESTS PASS")
    else:
        print("\nSOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
