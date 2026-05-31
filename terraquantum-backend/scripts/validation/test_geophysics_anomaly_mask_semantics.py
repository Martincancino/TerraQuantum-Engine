"""
Test semántico: verifica que la selección de anomalías físicas en
build_anomaly_dataframe NO depende de `grade`, sino solo de
`density` y `visual_score`.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\validation\\test_geophysics_anomaly_mask_semantics.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import polars as pl
from services.geophysics_service import build_anomaly_dataframe

CUTOFF_DENSITY = 2.75


def run_test():
    print("=" * 60)
    print("Test semántico: anomaly mask (density + visual_score only)")
    print("=" * 60)

    # Construir DataFrame artificial con 5 vóxeles de prueba
    df = pl.DataFrame({
        "x":     [100.0, 200.0, 300.0, 400.0, 500.0],
        "y":     [50.0,  50.0,  50.0,  50.0,  50.0],
        "z":     [100.0, 200.0, 300.0, 400.0, 500.0],
        "ix":    [0, 1, 2, 3, 4],
        "iy":    [0, 0, 0, 0, 0],
        "iz":    [0, 1, 2, 3, 4],
        "density":      [2.60, 3.10, 2.60, 2.60, 3.00],
        "rho":          [2.60, 3.10, 2.60, 2.60, 3.00],
        "probability":  [0.20, 0.80, 0.90, 0.10, 0.85],
        "visual_score": [0.05, 0.30, 0.50, 0.02, 0.40],
        "grade":        [1.80, 0.10, 0.10, 0.05, 2.50],
        "tonnage":      [100.0, 100.0, 100.0, 100.0, 100.0],
        "domain":       [0, 1, 1, 0, 1],
        "resource_class": [3, 1, 1, 3, 1],
    })

    # Caso A: density baja, visual_score bajo, grade alto → NO debe entrar
    # Caso B: density alta, visual_score bajo, grade bajo → SÍ (por density)
    # Caso C: density baja, visual_score alto, grade bajo → SÍ (por visual_score)
    # Caso D: density baja, visual_score bajo, grade bajo → NO debe entrar
    # Caso E: density alta, visual_score alto, grade alto → SÍ (por ambos)

    df_anomaly = build_anomaly_dataframe(df, CUTOFF_DENSITY)
    anomaly_ixs = set(df_anomaly["ix"].to_list())

    passed = True

    # Verificaciones
    checks = [
        ("A (ix=0): grade alto, dens/vs bajos → NO debe entrar", 0, False),
        ("B (ix=1): density alta → SÍ debe entrar",              1, True),
        ("C (ix=2): visual_score alto → SÍ debe entrar",         2, True),
        ("D (ix=3): todo bajo → NO debe entrar",                 3, False),
        ("E (ix=4): density + vs altos → SÍ debe entrar",        4, True),
    ]

    for label, ix_val, expected_in in checks:
        actual_in = ix_val in anomaly_ixs
        status = "✅" if actual_in == expected_in else "❌"
        if actual_in != expected_in:
            passed = False
        print(f"  {status}  {label}: {'IN' if actual_in else 'OUT'} (esperado: {'IN' if expected_in else 'OUT'})")

    print()
    print(f"  Anomalías seleccionadas: {len(df_anomaly)} de {len(df)}")
    print(f"  IXs en anomalía: {sorted(anomaly_ixs)}")

    if passed:
        print("\n✅  TODOS LOS CHECKS PASARON. grade no participa en selección física.")
    else:
        print("\n❌  ALGÚN CHECK FALLÓ. Revisar build_anomaly_dataframe.")
        sys.exit(1)


if __name__ == "__main__":
    run_test()
