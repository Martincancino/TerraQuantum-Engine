"""
HITO 4 — Criterio B-01: g_observed no debe ser modificado durante la inversión.

Verifica bit-a-bit que el array de observaciones pasado al servicio de inversión
es idéntico antes y después de la llamada. En HITO 0 se eliminó la inyección de
ruido gaussiano (geophysics_service.py:1988-1994); este test asegura que ningún
path futuro la reintroduzca.
"""
import numpy as np
import pytest


@pytest.mark.benchmark
def test_g_observed_immutable_during_inversion(test_project_id, test_run_id):
    """g_observed debe ser bit-idéntico antes y después de run_geophysics_inversion."""
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    raw_g = [
        0.00000080, 0.00000090, 0.00000110, 0.00000150, 0.00000110,
        0.00000085, 0.00000095, 0.00000130, 0.00000100, 0.00000090,
    ]
    observations = [
        {"x_m": x, "y_m": 0, "z_m": z, "g": g}
        for (x, z, g) in zip(
            [5, 15, 25, 35, 45, 5, 15, 25, 35, 45],
            [5, 5, 5, 5, 5, 25, 25, 25, 25, 25],
            raw_g,
        )
    ]

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=30, nir=83, fe=79,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=6, ny=6, nz=6,
        block_size=10, cutoff_radius=400,
        lambda_mag=0.00005, alpha_spatial=1.5,
        observations=observations,
    )

    g_before = np.array(raw_g, dtype=float).copy()

    run_geophysics_inversion(params)

    g_after = np.array([o["g"] for o in observations], dtype=float)

    assert np.array_equal(g_before, g_after), (
        "g_observed fue modificado durante la inversión — posible reinyección de ruido. "
        f"Diferencia máxima: {np.max(np.abs(g_before - g_after)):.2e}"
    )


@pytest.mark.unit
def test_g_observed_no_random_normal_in_service_source():
    """Guardia estática: np.random.normal no debe existir en el path de producción
    de geophysics_service.py. Si aparece, HITO 0 fue revertido."""
    from pathlib import Path
    import ast

    service_path = Path(__file__).parents[1] / "services" / "geophysics_service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # np.random.normal(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "normal"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "random"
        ):
            raise AssertionError(
                f"np.random.normal encontrado en geophysics_service.py línea {node.lineno}. "
                "B-01: inyección de ruido gaussiano prohibida en producción (HITO 0)."
            )
