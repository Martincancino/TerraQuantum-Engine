"""
E2E TEST: CSV → Inversión → API → 3D Rendering
===============================================

Flujo completo end-to-end con CSV pequeño real.
Detecta qué está roto en cada paso.

Ejecución:
  python tests/test_e2e_csv_to_3d.py
"""

import sys
import json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion
import logging

logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


def test_e2e_small_csv():
    """
    Crear CSV pequeño (20 sensores), invertir, verificar que API retorna vóxeles
    que podrían ser renderizados.
    """
    print("\n" + "="*70)
    print("E2E TEST: CSV -> Inversion -> Voxels -> 3D Check")
    print("="*70)

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 1: Crear payload (simula CSV parseado)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[1/4] Creando payload (CSV pequeño, 20 sensores)...")

    observations = []
    for i in range(20):
        x = (i % 5) * 1000.0  # Grid 5x4
        z = (i // 5) * 1000.0
        g = 0.001 + 0.0001 * i  # Valores realistas mGal
        # Y = profundidad positiva hacia abajo; los sensores van EN LA SUPERFICIE
        # (Y=0), sobre la malla. Y=1000 los metía dentro del dominio → ValueError.
        observations.append(GravityObservation(x_m=x, y_m=0.0, z_m=z, g=g))

    payload = GeophysicsInvertInput(
        project_id="test_e2e_csv",
        run_id="run_001",  # FIX: backend requiere ambos project_id y run_id juntos
        depth=500,
        nir=50,
        fe=30,
        region="test_mining",
        lat=None,  # ← CSV sin latlon (datos reales gravímetro)
        lon=None,
        nx=5,
        ny=5,
        nz=5,
        block_size=400,
        cutoff_radius=2000,
        lambda_mag=0.1,
        alpha_spatial=1.0,
        observations=observations,
        remove_regional=False,
        expose_demo_grade=False,
        compute_uncertainty=False,
        density_min=2.5,
        density_max=4.2,
    )

    print(f"  [OK] Payload: {len(payload.observations)} observaciones")
    print(f"  [OK] Grid: {payload.nx}x{payload.ny}x{payload.nz} = {payload.nx*payload.ny*payload.nz} voxels")
    print(f"  [OK] lat/lon: {payload.lat}/{payload.lon} (None = datos reales)")

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 2: Correr inversión
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[2/4] Ejecutando inversión geofísica...")

    try:
        response = run_geophysics_inversion(payload)
        print(f"  [OK] Inversion completada")
        print(f"  [OK] Response type: {type(response).__name__}")
        print(f"  [OK] Response keys: {list(response.keys()) if isinstance(response, dict) else 'NOT A DICT'}")

        misfit = response.get('misfit_pct', 'N/A')
        if isinstance(misfit, str):
            print(f"  [OK] Misfit: {misfit} (string, not float)")
        else:
            print(f"  [OK] Misfit: {float(misfit):.2f}%")

        run_id = response.get('run_id', 'UNKNOWN')
        print(f"  [OK] Run ID: {run_id}")

    except Exception as e:
        log.error(f"INVERSION FALLO: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"Inversión falló: {type(e).__name__}: {e}") from e

    # Paso 3: Validar estructura de respuesta
    print("\n[3/4] Validando respuesta (pueden renderizar estos voxels?)...")

    checks = {
        "response_is_dict": isinstance(response, dict),
        "has_voxels": "voxels" in response or "grid_data" in response,
        "has_coordinates": all(k in response for k in ["x_min", "y_min", "z_min"]) or "voxels" in response,
        "has_density": "density_grid" in response or (
            "voxels" in response and len(response["voxels"]) > 0 and "density" in response["voxels"][0]
        ),
        "no_nan": True,  # Will check below
        "density_range_plausible": True,  # Will check below
    }

    if "voxels" in response and len(response["voxels"]) > 0:
        first_vox = response["voxels"][0]
        print(f"\n  Primer vóxel: {first_vox}")

        # Verificar coordenadas
        has_xyz = all(k in first_vox for k in ["x", "y", "z"])
        if not has_xyz:
            log.warning(f"  ⚠️ FALTA: coordenadas x,y,z en vóxel")
            checks["has_coordinates"] = False

        # Verificar densidad
        has_density = "density" in first_vox
        if has_density:
            dens = first_vox["density"]
            checks["density_range_plausible"] = 2.0 <= dens <= 5.0
            if not checks["density_range_plausible"]:
                log.warning(f"  ⚠️ RANGO IMPLAUSIBLE: densidad={dens} (esperado 2-5 t/m³)")
        else:
            log.warning(f"  ⚠️ FALTA: field 'density' en vóxel")
            checks["has_density"] = False

        # Verificar NaN
        all_finite = all(
            isinstance(v, (int, float)) and np.isfinite(v)
            for k, v in first_vox.items()
            if isinstance(v, (int, float))
        )
        if not all_finite:
            log.warning(f"  ⚠️ VALORES NO-FINITOS (NaN/Inf) en vóxel")
            checks["no_nan"] = False

    else:
        log.error(f"  ❌ NO HAY VÓXELES en respuesta. Keys: {list(response.keys())}")

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 4: Diagnóstico final
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[4/4] Diagnóstico 3D...")

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    print(f"\n  Checks: {passed}/{total} PASS")
    for check, result in checks.items():
        status = "[OK]" if result else "[FAIL]"
        print(f"    {status} {check}")

    if passed == total:
        print("\n[PASS] PIPELINE FUNCIONAL: CSV -> Inversion -> Voxels -> 3D READY")
    else:
        print(f"\n[FAIL] PIPELINE ROTO: {total - passed} problemas encontrados")
        print("\n  PROBLEMAS IDENTIFICADOS:")
        if not checks["has_voxels"]:
            print("    1. Respuesta no contiene voxels -> API puede estar fallando")
        if not checks["has_coordinates"]:
            print("    2. Voxels sin x,y,z -> Frontend no puede posicionarlos")
        if not checks["has_density"]:
            print("    3. Voxels sin density -> Frontend no puede colorearlos")
        if not checks["density_range_plausible"]:
            print("    4. Densidades fuera de rango -> Colormap roto (todo rojo O todo azul)")
        if not checks["no_nan"]:
            print("    5. NaN/Inf en voxels -> Shader crash")

    failed = [name for name, ok in checks.items() if not ok]
    assert passed == total, (
        f"PIPELINE ROTO: {total - passed}/{total} checks fallaron: {failed}"
    )


if __name__ == "__main__":
    try:
        test_e2e_small_csv()
    except AssertionError as exc:
        print(f"\n[FAIL] {exc}")
        sys.exit(1)
    sys.exit(0)
