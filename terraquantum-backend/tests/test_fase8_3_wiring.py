"""
FASE 8.3 — Cableado de PRODUCCIÓN del targeting probabilístico.

Fase 8.3 entregó rank_drill_targets (ranking 3D de blancos perforables) como función
standalone. Este test cubre su cableado a run_geophysics_inversion vía el flag
compute_drill_targets:

  est_density (core) + σ posterior  →  rank_drill_targets  →  report["drillTargets"]

Verifica:
  1) flag OFF → report["drillTargets"]["computed"] is False (byte-idéntico histórico);
  2) flag ON → blancos poblados, ordenados, bien formados, y al menos uno cae sobre el
     cuerpo anómalo (cableado real, no placeholder);
  3) compute_uncertainty=True → used_posterior_std True (usa la σ de Hutchinson);
  4) determinismo.
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


def _run(compute_drill_targets, compute_uncertainty=False, sense="positive", top_n=8):
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
        project_id="pytest_geo83", run_id=f"run_{int(compute_drill_targets)}_{int(compute_uncertainty)}",
        depth=int(NY * BS), nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BS), cutoff_radius=int(NX * BS * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
        compute_uncertainty=compute_uncertainty,
        compute_drill_targets=compute_drill_targets,
        drill_targets_top_n=top_n,
        drill_targets_sense=sense,
    )
    return run_geophysics_inversion(params)


@pytest.mark.benchmark
def test_disabled_drill_targets_not_computed():
    result = _run(compute_drill_targets=False)
    dt = result["report"]["drillTargets"]
    assert dt["computed"] is False


@pytest.mark.benchmark
def test_enabled_populates_targets_on_the_body():
    result = _run(compute_drill_targets=True, top_n=8)
    dt = result["report"]["drillTargets"]
    assert dt["computed"] is True
    targets = dt["targets"]
    assert 1 <= len(targets) <= 8
    assert dt["n_targets"] == len(targets)

    # Bien formados y ordenados por score descendente.
    scores = [t["score"] for t in targets]
    assert scores == sorted(scores, reverse=True)
    for i, t in enumerate(targets, start=1):
        assert t["rank"] == i
        assert 0.0 <= t["exceedance_prob"] <= 1.0
        assert t["model_value"] > t["threshold"]   # positive sense
        for key in ("x", "y", "z", "depth", "expected_exceedance"):
            assert key in t

    # Cableado real: algún blanco cae sobre el cuerpo (proximidad horizontal).
    near = [
        t for t in targets
        if (t["x"] - CX) ** 2 + (t["z"] - CZ) ** 2 <= (2 * BS) ** 2
    ]
    assert near, f"ningún blanco cerca del cuerpo en (x={CX}, z={CZ}): {[(t['x'], t['z']) for t in targets]}"


@pytest.mark.benchmark
def test_uses_posterior_std_when_available():
    with_sigma = _run(compute_drill_targets=True, compute_uncertainty=True)
    dt = with_sigma["report"]["drillTargets"]
    assert dt["computed"] is True
    assert dt["used_posterior_std"] is True

    without = _run(compute_drill_targets=True, compute_uncertainty=False)
    assert without["report"]["drillTargets"]["used_posterior_std"] is False


@pytest.mark.benchmark
def test_deterministic():
    a = _run(compute_drill_targets=True)["report"]["drillTargets"]["targets"]
    b = _run(compute_drill_targets=True)["report"]["drillTargets"]["targets"]
    assert [t["score"] for t in a] == [t["score"] for t in b]
    assert [(t["x"], t["y"], t["z"]) for t in a] == [(t["x"], t["y"], t["z"]) for t in b]
