import sys
import numpy as np
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import build_observation_qaqc_report

def get_base_params():
    return GeophysicsInvertInput(
        depth=100,
        nir=50,
        fe=50,
        region="andes",
        lat="-33.0",
        lon="-70.0",
        nx=10,
        ny=10,
        nz=10,
        block_size=20,
        cutoff_radius=50.0,
        lambda_mag=0.1,
        alpha_spatial=1.0,
        observations=[
            GravityObservation(x_m=0.0, y_m=0.0, z_m=0.0, g=9.8) for _ in range(12)
        ]
    )

def run_tests():
    params = get_base_params()
    all_passed = True
    print("Running QA/QC Tests...\n")

    # 1. Caso bueno
    sensor_coords_1 = np.array([
        [0.0, 0.0, 0.0],
        [200.0, 200.0, 200.0],
        [100.0, 50.0, 100.0]
    ] * 10, dtype=float)
    g_observed_1 = np.array([9.8, 9.85, 9.82] * 10, dtype=float)
    
    report1 = build_observation_qaqc_report(params, sensor_coords_1, g_observed_1)
    if report1["quality_level"] in ["GOOD", "MEDIUM"] and report1["observation_count"] == 30:
        print("PASS: 1. Caso bueno")
    else:
        print("FAIL: 1. Caso bueno")
        all_passed = False

    # 2. Caso cobertura pobre
    sensor_coords_2 = np.array([
        [0.0, 0.0, 0.0],
        [5.0, 5.0, 5.0],
        [2.0, 2.0, 2.0]
    ] * 10, dtype=float)
    g_observed_2 = np.array([9.8, 9.85, 9.82] * 10, dtype=float)
    
    report2 = build_observation_qaqc_report(params, sensor_coords_2, g_observed_2)
    warnings_str2 = " ".join(report2["warnings"])
    if "Cobertura espacial baja en X." in warnings_str2:
        print("PASS: 2. Caso cobertura pobre")
    else:
        print("FAIL: 2. Caso cobertura pobre")
        all_passed = False

    # 3. Caso señal plana
    sensor_coords_3 = sensor_coords_1.copy()
    g_observed_3 = np.array([9.8, 9.8, 9.8] * 10, dtype=float)
    
    report3 = build_observation_qaqc_report(params, sensor_coords_3, g_observed_3)
    warnings_str3 = " ".join(report3["warnings"])
    if "bajo rango dinámico" in warnings_str3:
        print("PASS: 3. Caso señal plana")
    else:
        print("FAIL: 3. Caso señal plana")
        all_passed = False

    # 4. Caso mínimo (exactamente 10)
    sensor_coords_4 = sensor_coords_1[:10]
    g_observed_4 = g_observed_1[:10]
    
    report4 = build_observation_qaqc_report(params, sensor_coords_4, g_observed_4)
    warnings_str4 = " ".join(report4["warnings"])
    if "Cantidad mínima de observaciones" in warnings_str4:
        print("PASS: 4. Caso mínimo")
    else:
        print("FAIL: 4. Caso mínimo")
        all_passed = False

    print("\nRESULT:")
    if all_passed:
        print("PASS")
    else:
        print("FAIL")

if __name__ == "__main__":
    run_tests()
