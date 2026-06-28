"""
FASE 8.1 — Cableado de PRODUCCIÓN del ensemble null-space (mapa de no-unicidad).

Cablea null_space_shuttle_ensemble a run_geophysics_inversion vía el flag
compute_ensemble_uncertainty:

  est_density_full + operadores congelados  →  ensemble null-space  →
  report["ensembleUncertainty"] (σ de no-unicidad por vóxel, reducida a core).

Verifica:
  1) flag OFF → report["ensembleUncertainty"]["computed"] is False (byte-idéntico);
  2) flag ON → resumen poblado (σ p50/p95 ≥ 0, null_fraction, n_shuttles correcto);
  3) determinismo del resumen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_inversion


NX, NY, NZ, BS = 8, 6, 8, 20.0
CX, CY, CZ = NX * BS / 2, 70.0, NZ * BS / 2


def _run(compute_ensemble_uncertainty, n_shuttles=8):
    from exploration.gravimetry import GravimetryForward

    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BS + BS / 2
    y_c = gy.flatten(order="F") * BS + BS / 2
    z_c = gz.flatten(order="F") * BS + BS / 2
    r = np.sqrt((x_c - CX) ** 2 + (y_c - CY) ** 2 + (z_c - CZ) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BS, BS, BS, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(np.arange(5, NX * BS, BS), np.arange(5, NZ * BS, BS), indexing="ij")
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    params = GeophysicsInvertInput(
        project_id="pytest_geo81", run_id=f"run_{int(compute_ensemble_uncertainty)}",
        depth=int(NY * BS), nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BS), cutoff_radius=int(NX * BS * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
        compute_ensemble_uncertainty=compute_ensemble_uncertainty,
        ensemble_n_shuttles=n_shuttles,
    )
    return run_geophysics_inversion(params)


@pytest.mark.benchmark
def test_disabled_ensemble_not_computed():
    eu = _run(compute_ensemble_uncertainty=False)["report"]["ensembleUncertainty"]
    assert eu["computed"] is False


@pytest.mark.benchmark
def test_enabled_populates_ensemble_summary():
    eu = _run(compute_ensemble_uncertainty=True, n_shuttles=8)["report"]["ensembleUncertainty"]
    assert eu["computed"] is True
    assert eu["n_shuttles"] == 8
    assert eu["n_voxels"] > 0
    assert eu["p50"] is not None and eu["p50"] >= 0.0
    assert eu["p95"] is not None and eu["p95"] >= eu["p50"]
    assert eu["unit"] == "t/m3"
    assert "null_fraction" in eu and np.isfinite(eu["null_fraction"])


@pytest.mark.benchmark
def test_deterministic_summary():
    a = _run(compute_ensemble_uncertainty=True, n_shuttles=8)["report"]["ensembleUncertainty"]
    b = _run(compute_ensemble_uncertainty=True, n_shuttles=8)["report"]["ensembleUncertainty"]
    assert a["p50"] == b["p50"]
    assert a["p95"] == b["p95"]
    assert a["null_fraction"] == b["null_fraction"]
