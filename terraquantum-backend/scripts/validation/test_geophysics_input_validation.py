import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import validate_geophysics_input

def build_valid_payload():
    return {
        "project_id": "test-proj",
        "run_id": "test-run",
        "depth": 100,
        "nir": 50,
        "fe": 50,
        "region": "andes",
        "lat": "-33.0",
        "lon": "-70.0",
        "nx": 10,
        "ny": 10,
        "nz": 10,
        "block_size": 20,
        "cutoff_radius": 50.0,
        "lambda_mag": 0.1,
        "alpha_spatial": 1.0,
        "observations": [
            GravityObservation(x_m=float(i*10), y_m=float(i*10), z_m=0.0, g=9.8)
            for i in range(12)
        ]
    }

def run_tests():
    tests = [
        ("1. observations vacío", {"observations": []}),
        ("2. menos de 10 observaciones", {"observations": [GravityObservation(x_m=float(i), y_m=float(i), z_m=0.0, g=9.8) for i in range(5)]}),
        ("3. g no finito (NaN)", {"observations": [GravityObservation(x_m=float(i), y_m=float(i), z_m=0.0, g=float('nan')) for i in range(12)]}),
        ("4. coordenada duplicada", {"observations": [GravityObservation(x_m=10.0, y_m=10.0, z_m=0.0, g=9.8)] * 12}),
        ("5. nx demasiado chico", {"nx": 3}),
        ("6. nx*ny*nz demasiado grande", {"nx": 70, "ny": 70, "nz": 70}),
        ("7. block_size <= 0", {"block_size": 0}),
        ("8. depth <= 0", {"depth": 0}),
        ("9. lat inválida", {"lat": "-100"}),
        ("10. lon inválida", {"lon": "200"}),
        ("11. nir fuera de rango", {"nir": 150}),
        ("12. fe fuera de rango", {"fe": -10}),
        ("13. lambda_mag negativa", {"lambda_mag": -0.5}),
        ("14. alpha_spatial negativa", {"alpha_spatial": -1.0}),
    ]

    all_passed = True

    print("Running Validation Tests...\n")

    for name, overrides in tests:
        payload = build_valid_payload()
        payload.update(overrides)
        
        try:
            model = GeophysicsInvertInput(**payload)
            validate_geophysics_input(model)
            print(f"FAIL: {name} (No exception raised)")
            all_passed = False
        except ValueError as e:
            print(f"PASS: {name} -> Caught ValueError: {e}")
        except Exception as e:
            print(f"PASS: {name} -> Caught Exception: {e}")

    # Valid Case
    try:
        valid_model = GeophysicsInvertInput(**build_valid_payload())
        validate_geophysics_input(valid_model)
        print("PASS: Caso Válido")
    except Exception as e:
        print(f"FAIL: Caso Válido raised an exception: {e}")
        all_passed = False

    print("\nRESULT:")
    if all_passed:
        print("PASS")
    else:
        print("FAIL")

if __name__ == "__main__":
    run_tests()
