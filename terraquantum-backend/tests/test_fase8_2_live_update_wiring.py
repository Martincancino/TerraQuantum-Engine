"""
FASE 8.2 — Cableado de PRODUCCIÓN del Live Update (Woodbury / sub-octree).

Cablea live_update_add_data / live_update_suboctree a un endpoint STATELESS sobre malla
core (run_geophysics_live_update). El servicio reconstruye el forward/mesh core desde
req.params (que incluyen las observations existentes) y aplica la actualización lineal
local sobre req.prior_model. RÁPIDO: no corre la inversión completa.

Verifica:
  1) woodbury: incorpora un dato nuevo → modelo del tamaño correcto, n_new=1, el misfit
     del dato nuevo BAJA;
  2) suboctree: re-solve local → region_size>0, misfit del dato (exist.+nuevo) no sube;
  3) validaciones (422): woodbury sin new_observations, suboctree sin región,
     prior_model mal dimensionado;
  4) determinismo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from fastapi import HTTPException

from exploration.gravimetry import GravimetryForward
from schemas.geophysics_schema import (
    GeophysicsInvertInput,
    GeophysicsLiveUpdateRequest,
    LiveUpdateObservation,
)
from services.geophysics_service import run_geophysics_live_update
from services.inversion_kernel_service import build_tensor_mesh_with_padding


NX, NY, NZ, BS = 8, 6, 8, 20.0


def _base_params(observations):
    return GeophysicsInvertInput(
        project_id="pytest_lu", run_id="run_lu",
        depth=int(NY * BS), nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BS), cutoff_radius=int(NX * BS * 4),
        lambda_mag=1e-3, alpha_spatial=1.0,
        density_min=0.0, density_max=5.5,   # permite el contraste sintético sin clip espurio
        observations=observations,
    )


def _setup():
    """Construye un modelo de contraste + dato consistente sobre la MALLA CORE real
    del servicio, para que prior_model y g_observed estén alineados índice a índice."""
    # La malla solo depende de la geometría (nx/ny/nz/block_size), no de las
    # observations; placeholder de ≥10 para satisfacer la validación del schema.
    skel = _base_params(observations=[
        {"x_m": float(10 * i), "y_m": 0.0, "z_m": 0.0, "g": 0.0} for i in range(12)
    ])
    mesh = build_tensor_mesh_with_padding(skel)
    x_c, y_c, z_c = mesh["x_c_core"], mesh["y_c_core"], mesh["z_c_core"]

    cx, cz, cy = NX * BS / 2, NZ * BS / 2, 70.0
    r = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BS, BS, BS, cutoff_radius=NX * BS * 4)
    sx, sz = np.meshgrid(np.arange(5, NX * BS, BS), np.arange(5, NZ * BS, BS), indexing="ij")
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    params = _base_params(
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ]
    )
    return params, contrast, fwd, x_c, y_c, z_c, sensors, (cx, cy, cz)


def test_woodbury_reduces_new_data_misfit():
    params, contrast, fwd, x_c, y_c, z_c, _sensors, (cx, cy, cz) = _setup()
    new_xyz = np.array([[cx, -5.0, cz]])
    pred0 = float((fwd.build_sparse_kernel(x_c, y_c, z_c, new_xyz) @ contrast)[0])
    req = GeophysicsLiveUpdateRequest(
        params=params,
        prior_model=contrast.tolist(),
        mode="woodbury",
        new_observations=[LiveUpdateObservation(x_m=cx, y_m=-5.0, z_m=cz, g=pred0 * 1.6)],
    )
    out = run_geophysics_live_update(req)
    assert out["mode"] == "woodbury"
    assert out["n_voxels"] == NX * NY * NZ
    assert out["n_new"] == 1
    assert len(out["model"]) == NX * NY * NZ
    assert out["new_data_misfit_after"] < out["new_data_misfit_before"]


def test_suboctree_resolves_region():
    """Prior que SUBAJUSTA (mitad del contraste) + re-solve local contra el dato
    EXISTENTE → el misfit del dato baja (la sub-región se acerca al verdadero)."""
    params, contrast, fwd, x_c, y_c, z_c, _sensors, (cx, cy, cz) = _setup()
    req = GeophysicsLiveUpdateRequest(
        params=params,
        prior_model=(contrast * 0.5).tolist(),   # subajusta el cuerpo
        mode="suboctree",
        region_center=[cx, cy, cz],
        region_radius=40.0,
        anchor_strength=0.1,
    )
    out = run_geophysics_live_update(req)
    assert out["mode"] == "suboctree"
    assert out["region_size"] > 0
    assert out["n_voxels"] == NX * NY * NZ
    assert out["region_misfit_after"] < out["region_misfit_before"]


def test_validation_woodbury_requires_new_obs():
    params, contrast, *_ = _setup()
    req = GeophysicsLiveUpdateRequest(
        params=params, prior_model=contrast.tolist(), mode="woodbury",
    )
    with pytest.raises(HTTPException) as exc:
        run_geophysics_live_update(req)
    assert exc.value.status_code == 422


def test_validation_suboctree_requires_region():
    params, contrast, *_ = _setup()
    req = GeophysicsLiveUpdateRequest(
        params=params, prior_model=contrast.tolist(), mode="suboctree",
    )
    with pytest.raises(HTTPException) as exc:
        run_geophysics_live_update(req)
    assert exc.value.status_code == 422


def test_validation_wrong_prior_model_length():
    params, contrast, *_ = _setup()
    req = GeophysicsLiveUpdateRequest(
        params=params,
        prior_model=contrast[:-1].tolist(),   # longitud incorrecta
        mode="woodbury",
        new_observations=[LiveUpdateObservation(x_m=80.0, y_m=-5.0, z_m=80.0, g=1.0)],
    )
    with pytest.raises(HTTPException) as exc:
        run_geophysics_live_update(req)
    assert exc.value.status_code == 422


def test_deterministic():
    params, contrast, fwd, x_c, y_c, z_c, _sensors, (cx, cy, cz) = _setup()
    pred0 = float((fwd.build_sparse_kernel(x_c, y_c, z_c, np.array([[cx, -5.0, cz]])) @ contrast)[0])
    kw = dict(
        params=params, prior_model=contrast.tolist(), mode="woodbury",
        new_observations=[LiveUpdateObservation(x_m=cx, y_m=-5.0, z_m=cz, g=pred0 * 1.6)],
    )
    a = run_geophysics_live_update(GeophysicsLiveUpdateRequest(**kw))
    b = run_geophysics_live_update(GeophysicsLiveUpdateRequest(**kw))
    assert a["model"] == b["model"]
    assert a["update_norm"] == b["update_norm"]
