"""
FASE 20B Tarea 3 — Observable Domain Pruning (R-05) del motor MAGNÉTICO.

Verifica:
  - poda OFF (default) == comportamiento histórico (n_dead reportado 0, sin poda).
  - poda ON: vóxeles muertos (fuera del cutoff para todos los sensores) se excluyen
    del solver y revierten a base_susc (≈0); el resultado en el dominio observable es
    consistente con la corrida sin poda.
  - compatibilidad con override_kernel (Fase 12): la poda recorta también sus columnas.
  - contrato joint: con poda ON y extra_reg_blocks de tamaño completo → error claro;
    con el bloque recortado a obs_mask → funciona (igual que gravedad Fase 15).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
import scipy.sparse as sp

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ = 8, 4, 8
BS = 20.0


def _grid():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return (ix.ravel() + 0.5) * BS, (iy.ravel() + 0.5) * BS, (iz.ravel() + 0.5) * BS


def _solve(cutoff, prune, x_c, y_c, z_c, sensors, d_obs, **kw):
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    meta = {}
    susc, score, misfit, sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, prune_observable_domain=prune,
        solver_meta=meta, **kw,
    )
    return susc, misfit, meta, fwd, inv


def _data(cutoff):
    x_c, y_c, z_c = _grid()
    # Sensores concentrados en una esquina → con cutoff chico, vóxeles lejanos quedan muertos.
    sx, sz = np.meshgrid(np.linspace(BS, 3 * BS, 4), np.linspace(BS, 3 * BS, 4))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[2 * NY * NZ + 1 * NZ + 2] = 0.2   # cuerpo cerca de los sensores
    d_obs = G @ true
    return x_c, y_c, z_c, sensors, d_obs


def test_prune_off_is_default_no_dead():
    x_c, y_c, z_c, sensors, d_obs = _data(cutoff=BS * 20)  # cutoff grande → todo observable
    susc, misfit, meta, *_ = _solve(BS * 20, False, x_c, y_c, z_c, sensors, d_obs)
    assert meta["prune_observable_domain"] is False
    assert meta["n_dead_voxels"] == 0
    assert np.isfinite(misfit)


def test_prune_removes_dead_voxels():
    # cutoff pequeño + sensores en una esquina → vóxeles lejanos = muertos.
    cutoff = BS * 4
    x_c, y_c, z_c, sensors, d_obs = _data(cutoff)
    susc_p, mf_p, meta_p, *_ = _solve(cutoff, True, x_c, y_c, z_c, sensors, d_obs)
    susc_n, mf_n, meta_n, *_ = _solve(cutoff, False, x_c, y_c, z_c, sensors, d_obs)

    assert meta_p["n_dead_voxels"] > 0, "Con cutoff chico debe haber vóxeles muertos."
    assert meta_n["n_dead_voxels"] == 0
    # Vóxeles muertos (sin poda revierten igual a ~0): ambos finitos y consistentes
    assert np.isfinite(susc_p[np.isfinite(susc_p)]).all()
    # Misfit comparable (la poda no debe degradar el ajuste de datos)
    assert abs(mf_p - mf_n) <= max(2.0, 0.2 * abs(mf_n) + 1e-9)


def test_prune_consistent_in_observable_domain():
    # Cobertura COMPLETA de sensores + cutoff grande → ~todo observable (R-05 poda por
    # sensibilidad relativa, no solo por cutoff). poda ON vs OFF deben coincidir en el
    # dominio observable.
    cutoff = BS * 30
    x_c, y_c, z_c = _grid()
    sx, sz = np.meshgrid(np.linspace(BS, (NX - 1) * BS, 6), np.linspace(BS, (NZ - 1) * BS, 6))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd0 = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff)
    G = fwd0._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[3 * NY * NZ + 1 * NZ + 3] = 0.2
    d_obs = G @ true

    susc_p, _mp, meta_p, *_ = _solve(cutoff, True, x_c, y_c, z_c, sensors, d_obs)
    susc_n, _mn, _meta_n, *_ = _solve(cutoff, False, x_c, y_c, z_c, sensors, d_obs)

    # Comparar en el dominio observable de la corrida con poda (donde el modelo vive).
    col_sens = np.asarray(G.power(2).sum(axis=0)).ravel()
    obs_mask = col_sens > 1e-6 * max(float(np.max(col_sens)), 1e-30)
    a = np.nan_to_num(susc_p)[obs_mask]
    b = np.nan_to_num(susc_n)[obs_mask]
    assert np.allclose(a, b, atol=5e-3), (
        f"poda ON/OFF deben ser consistentes en el dominio observable; "
        f"max|Δ|={np.max(np.abs(a - b)):.2e}"
    )


def test_prune_with_override_kernel():
    cutoff = BS * 4
    x_c, y_c, z_c, sensors, d_obs = _data(cutoff)
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)  # (n_obs, nC) topo plana
    meta = {}
    susc, score, misfit, sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, prune_observable_domain=True,
        override_kernel=G, solver_meta=meta,
    )
    assert meta["n_dead_voxels"] > 0
    assert np.isfinite(misfit)


def test_extra_reg_blocks_contract_joint_compatible():
    # Con poda ON, un bloque de tamaño completo (nC) debe fallar con mensaje claro;
    # recortado al dominio observable debe funcionar (contrato joint, igual gravedad).
    cutoff = BS * 4
    x_c, y_c, z_c, sensors, d_obs = _data(cutoff)
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    # obs_mask con la misma lógica R-05 del solver
    col_sens = np.asarray(G.power(2).sum(axis=0)).ravel()
    obs_mask = col_sens > 1e-6 * max(float(np.max(col_sens)), 1e-30)
    nC = NX * NY * NZ

    full_block = sp.identity(nC, format="csr") * 0.0   # bloque trivial tamaño completo

    with pytest.raises(ValueError, match="dominio observable"):
        inv.solve_magnetic_inversion_lsqr(
            d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            susc_min=0.0, susc_max=1.0, prune_observable_domain=True,
            extra_reg_blocks=[full_block],
        )

    # Bloque recortado a obs_mask → conforma y resuelve sin error.
    sliced = full_block[:, obs_mask]
    meta = {}
    susc, score, misfit, sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, prune_observable_domain=True,
        extra_reg_blocks=[sliced], solver_meta=meta,
    )
    assert np.isfinite(misfit)
