"""
TerraQuantum Synthetic Copper Demo v1 — Smoke Test

Valida que el backend puede importar e invertir el dataset demo grande
antes de probarlo en la interfaz web.

Uso:
    cd C:\\Users\\marti\\OneDrive\\Documentos\\TerraQuantum\\terraquantum-backend
    python scripts\\demo\\run_tq_synthetic_copper_demo_v1_smoke.py

No modifica servicios productivos. Solo lectura de servicios existentes.
No usa datos reales.
"""

import os
import sys
import time

# Asegurar que el backend esté en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from services.gravity_import_service import import_gravity_csv_v1
from services.geophysics_service import run_geophysics_inversion
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation

# ---------------------------------------------------------------------------
# Constantes del smoke test
# ---------------------------------------------------------------------------
PROJECT_ID  = "tq_synthetic_copper_demo_v1"
RUN_ID      = "smoke_demo_v1"
CSV_RELPATH = os.path.join("scripts", "demo_data", "tq_synthetic_copper_demo_v1_bouguer_mgal.csv")

EXPECTED_OBSERVATIONS = 1089
EXPECTED_GRAVITY_TYPE = "synthetic_demo"
EXPECTED_UNIT         = "mGal"

# Parámetros del perfil industrial_demo_v1
NX          = 32
NY          = 20
NZ          = 32
BLOCK_SIZE  = 25
DEPTH       = 250


def separator(label: str = ""):
    width = 60
    if label:
        print(f"\n{'─' * 4} {label} {'─' * max(0, width - len(label) - 6)}")
    else:
        print("─" * width)


def run_smoke_test():
    print("=" * 60)
    print("TerraQuantum — Smoke Test CSV Demo Grande v1")
    print("=" * 60)

    # Resolver ruta absoluta del CSV
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    csv_path = os.path.join(backend_root, CSV_RELPATH)

    print(f"\nCSV path : {csv_path}")
    if not os.path.exists(csv_path):
        print(f"\n❌  CSV no encontrado: {csv_path}")
        print("    Ejecuta primero:")
        print("    python scripts\\demo\\generate_tq_synthetic_copper_demo_v1.py")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # PASO 1 — Importar y validar el CSV
    # -----------------------------------------------------------------------
    separator("PASO 1 — Importar CSV")
    t_import_start = time.perf_counter()

    try:
        import_result = import_gravity_csv_v1(csv_path, strict=True, allow_g_raw=False)
    except Exception as exc:
        print(f"❌  Excepción durante import_gravity_csv_v1: {exc}")
        raise

    t_import_end = time.perf_counter()
    t_import = t_import_end - t_import_start

    meta = import_result.import_metadata
    print(f"  Status            : {import_result.status}")
    print(f"  Observaciones     : {meta.valid_rows}")
    print(f"  gravity_type      : {meta.gravity_type}")
    print(f"  unit_original     : {meta.unit_original}")
    print(f"  Tiempo importación: {t_import:.3f} s")
    if import_result.warnings:
        print(f"  Warnings          : {import_result.warnings}")

    # Verificaciones de importación
    assert import_result.status == "ok", \
        f"❌  status esperado 'ok', obtenido '{import_result.status}'. Errores: {import_result.errors}"
    assert meta.valid_rows == EXPECTED_OBSERVATIONS, \
        f"❌  Observaciones esperadas {EXPECTED_OBSERVATIONS}, obtenidas {meta.valid_rows}"
    assert meta.gravity_type == EXPECTED_GRAVITY_TYPE, \
        f"❌  gravity_type esperado '{EXPECTED_GRAVITY_TYPE}', obtenido '{meta.gravity_type}'"
    assert meta.unit_original == EXPECTED_UNIT, \
        f"❌  unit_original esperado '{EXPECTED_UNIT}', obtenido '{meta.unit_original}'"

    print("  ✅  Importación validada correctamente.")

    # -----------------------------------------------------------------------
    # PASO 2 — Construir GeophysicsInvertInput
    # -----------------------------------------------------------------------
    separator("PASO 2 — Construir payload de inversión")

    observations = [
        GravityObservation(x_m=obs.x_m, y_m=obs.y_m, z_m=obs.z_m, g=obs.g)
        for obs in import_result.observations
    ]

    invert_input = GeophysicsInvertInput(
        project_id    = PROJECT_ID,
        run_id        = RUN_ID,
        nx            = NX,
        ny            = NY,
        nz            = NZ,
        block_size    = BLOCK_SIZE,
        depth         = DEPTH,
        nir           = 83,
        fe            = 79,
        region        = "norte_chile",
        lat           = "-22.28",
        lon           = "-68.89",
        cutoff_radius = 300.0,
        lambda_mag    = 0.00005,
        alpha_spatial = 1.0,
        observations  = observations,
    )

    total_voxels = NX * NY * NZ
    print(f"  project_id   : {invert_input.project_id}")
    print(f"  run_id       : {invert_input.run_id}")
    print(f"  Grilla       : {NX}×{NY}×{NZ} = {total_voxels:,} vóxeles")
    print(f"  block_size   : {BLOCK_SIZE} m")
    print(f"  depth        : {DEPTH} m")
    print(f"  Observaciones: {len(observations)}")
    print("  ✅  Payload construido.")

    # -----------------------------------------------------------------------
    # PASO 3 — Ejecutar inversión
    # -----------------------------------------------------------------------
    separator("PASO 3 — Ejecutar inversión geofísica")
    print("  (esto puede tardar 1–3 min dependiendo del hardware)")

    t_inversion_start = time.perf_counter()

    try:
        result = run_geophysics_inversion(invert_input)
    except Exception as exc:
        print(f"\n❌  Excepción durante run_geophysics_inversion: {exc}")
        raise

    t_inversion_end = time.perf_counter()
    t_inversion = t_inversion_end - t_inversion_start

    # -----------------------------------------------------------------------
    # PASO 4 — Mostrar resultados
    # -----------------------------------------------------------------------
    separator("RESULTADOS")

    voxels      = result.get("voxels", [])
    best_target = result.get("best_target")
    report      = result.get("report", {})

    recommendation = report.get("recommendation", "N/A")
    parquet_path   = report.get("parquet_path", "N/A")
    anomaly_count  = report.get("returned_voxels", len(voxels))

    print(f"  Tiempo inversión   : {t_inversion:.1f} s")
    print(f"  Total vóxeles      : {total_voxels:,}")
    print(f"  Anomalías reportadas: {anomaly_count:,}")
    print(f"  Recomendación      : {recommendation}")
    print(f"  Parquet path       : {parquet_path}")

    if best_target:
        print(f"\n  Best target:")
        print(f"    x_m={best_target.get('x_m'):.1f}  y_m={best_target.get('y_m'):.1f}  z_m={best_target.get('z_m'):.1f}")
        print(f"    densidad={best_target.get('density'):.3f} t/m³  prob={best_target.get('probability'):.3f}")
        print(f"    confianza={best_target.get('confidence_level', 'N/A')}")

    separator()
    print("=" * 60)
    print("✅  SMOKE TEST PASÓ — Backend listo para flujo web con demo v1.")
    print("=" * 60)
    print()
    print("Próximos pasos:")
    print("  1. Abrir TerraQuantum en el navegador (Figura 3D).")
    print(f"  2. Cargar: {CSV_RELPATH}")
    print("  3. Seleccionar perfil: Demo industrial v1.")
    print("  4. Invertir y cargar modelo 3D.")
    print("  5. Revisar Datos → Diseño Mina.")
    print()


if __name__ == "__main__":
    run_smoke_test()
