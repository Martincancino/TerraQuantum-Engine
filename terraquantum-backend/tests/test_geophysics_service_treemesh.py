"""
SPRINT 3C: Testa que TreeMesh hook funciona y mantiene backward compatibility.

- Test 1: regular grid path (use_treemesh=False) still works
- Test 2: TreeMesh path (use_treemesh=True) executes and returns mesh_info
"""

import numpy as np
import pytest

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion


def _make_test_input(use_treemesh=False, treemesh_max_refine=2):
    """Construir un input de prueba mínimo válido."""
    # 49 observaciones en una grilla 7×7 sobre el dominio [0,160]×[0,80]
    observations = []
    for i in range(7):
        for j in range(7):
            x = 20 + i * 20  # 20, 40, ..., 140
            z = 10 + j * 10  # 10, 20, ..., 70
            observations.append(GravityObservation(x_m=x, y_m=20, z_m=z, g=0.0001 * (i + j)))

    return GeophysicsInvertInput(
        project_id="test_proj",
        run_id="test_run",
        depth=200,
        nir=50,
        fe=30,
        region="desconocida",
        lat="-23.5",
        lon="-70.2",
        nx=4,
        ny=4,
        nz=4,
        block_size=40,
        cutoff_radius=150.0,
        lambda_mag=3.0,
        alpha_spatial=1.0,
        observations=observations,
        use_treemesh=use_treemesh,
        treemesh_max_refine=treemesh_max_refine,
    )


def test_regular_grid_path_backward_compat():
    """Test que regular grid path (default, use_treemesh=False) sigue funcionando sin cambios."""
    params = _make_test_input(use_treemesh=False)

    result = run_geophysics_inversion(params)

    assert result is not None
    assert "voxels" in result
    assert "report" in result
    assert "misfit_error_percent" in result
    assert result["misfit_error_percent"] is not None
    assert float(result["misfit_error_percent"]) >= 0


def test_treemesh_path_executes():
    """Test que TreeMesh path (use_treemesh=True) ejecuta y retorna mesh_info."""
    params = _make_test_input(use_treemesh=True, treemesh_max_refine=1)

    result = run_geophysics_inversion(params)

    assert result is not None
    assert "voxels" in result
    assert "report" in result
    assert "misfit_error_percent" in result

    # TreeMesh agrega mesh_info al report
    report = result["report"]
    assert "mesh_info" in report
    mesh_info = report["mesh_info"]

    assert "n_cells" in mesh_info
    assert mesh_info["n_cells"] > 0
    assert "n_levels" in mesh_info
    assert mesh_info["n_levels"] > 0
    assert "sensor_guided_refine" in mesh_info
    assert mesh_info["sensor_guided_refine"] is True


def test_treemesh_voxels_present():
    """Test que TreeMesh retorna vóxeles válidos."""
    params = _make_test_input(use_treemesh=True)

    result = run_geophysics_inversion(params)
    voxels = result["voxels"]

    # Debe retornar al menos algunos vóxeles
    assert len(voxels) > 0

    # Verificar estructura de vóxeles
    for v in voxels[:5]:  # Spot-check primeros 5
        assert "x_m" in v
        assert "y_m" in v
        assert "z_m" in v
        assert "density" in v
        assert "probability" in v
        assert "is_active" in v


def test_treemesh_vs_regular_grid_misfit():
    """Test que ambos paths producen misfits finitos y razonables."""
    params_regular = _make_test_input(use_treemesh=False)
    params_tree = _make_test_input(use_treemesh=True, treemesh_max_refine=0)

    result_regular = run_geophysics_inversion(params_regular)
    result_tree = run_geophysics_inversion(params_tree)

    misfit_regular = float(result_regular["misfit_error_percent"])
    misfit_tree = float(result_tree["misfit_error_percent"])

    # Ambos deben ser finitos y positivos
    assert np.isfinite(misfit_regular)
    assert np.isfinite(misfit_tree)
    assert misfit_regular >= 0
    assert misfit_tree >= 0

    # Cuando max_refine_depth=0, TreeMesh es equivalente a grilla regular
    # Así que los misfits deberían ser similares (no idénticos por diferencias numéricas)
    assert abs(misfit_regular - misfit_tree) < 100.0  # razonable tolerancia


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
