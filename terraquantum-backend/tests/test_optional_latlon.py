"""
Test: Inversión gravimétrica sin lat/lon (datos reales del gravímetro)
=====================================================================

Los datos crudos de un gravímetro no incluyen coordenadas geográficas.
El API debe aceptar lat/lon = null y funcionar sin ellos.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation


def test_inversion_without_latlon():
    """Crear payload sin lat/lon (None) debe ser válido."""
    observations = [
        GravityObservation(x_m=float(i), y_m=1000.0, z_m=0.0, g=0.001 * (i + 1))
        for i in range(20)
    ]

    # Crear payload SIN lat/lon (null)
    payload = GeophysicsInvertInput(
        project_id="test_no_latlon",
        depth=500,
        nir=50,
        fe=30,
        region="test_region",
        lat=None,  # ← Datos reales del gravímetro
        lon=None,  # ← No tienen esto
        nx=10,
        ny=10,
        nz=10,
        block_size=100,
        cutoff_radius=5000,
        lambda_mag=0.1,
        alpha_spatial=1.0,
        observations=observations,
    )

    # Validación Pydantic debe pasar
    assert payload.lat is None
    assert payload.lon is None
    assert payload.project_id == "test_no_latlon"
    assert len(payload.observations) == 20
    print("[PASS] Payload sin lat/lon es válido")


def test_inversion_with_latlon():
    """Backward compat: payload CON lat/lon sigue siendo válido."""
    observations = [
        GravityObservation(x_m=float(i), y_m=1000.0, z_m=0.0, g=0.001 * (i + 1))
        for i in range(20)
    ]

    payload = GeophysicsInvertInput(
        project_id="test_with_latlon",
        depth=500,
        nir=50,
        fe=30,
        region="south_africa",
        lat="-25.5",
        lon="29.0",
        nx=10,
        ny=10,
        nz=10,
        block_size=100,
        cutoff_radius=5000,
        lambda_mag=0.1,
        alpha_spatial=1.0,
        observations=observations,
    )

    assert payload.lat == "-25.5"
    assert payload.lon == "29.0"
    assert payload.project_id == "test_with_latlon"
    print("[PASS] Payload con lat/lon sigue siendo válido")


def test_inversion_mixed_latlon():
    """lat=None, lon="value" → ambos deben estar presentes o ambos ausentes (gracefully)."""
    observations = [
        GravityObservation(x_m=float(i), y_m=1000.0, z_m=0.0, g=0.001 * (i + 1))
        for i in range(20)
    ]

    # Parcialmente especificado: lon sin lat
    payload = GeophysicsInvertInput(
        project_id="test_partial",
        depth=500,
        nir=50,
        fe=30,
        region="test",
        lat=None,
        lon="29.0",
        nx=10,
        ny=10,
        nz=10,
        block_size=100,
        cutoff_radius=5000,
        lambda_mag=0.1,
        alpha_spatial=1.0,
        observations=observations,
    )

    # Debe ser válido (Pydantic solo valida que es Optional, no que sean pareados)
    assert payload.lat is None
    assert payload.lon == "29.0"
    print("[PASS] Combinaciones parciales de lat/lon aceptadas")


if __name__ == "__main__":
    test_inversion_without_latlon()
    test_inversion_with_latlon()
    test_inversion_mixed_latlon()
    print("\n[ALL PASS] lat/lon opcionales funcionan correctamente")
