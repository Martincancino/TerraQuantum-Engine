"""
FASE 0 Tarea 0.1 — Fix del sigma paramétrico en el motor MAGNÉTICO.

El motor magnético usaba la forma ADITIVA  sigma = noise_floor + noise_pct·|d|
en el path de ruido explícito (≠ sentinel 0.02/0.02). Para datos de campo eso
sobreestima sigma ~|d|/floor veces y COLAPSA chi²_red a ~0 (el mismo bug que
gravimetría ya había corregido a forma de PISO  sigma = max(floor, pct·|d|)).

Verifica:
  - la función compartida sigma_parametric es PISO, no aditiva (determinista);
  - una inversión TMI sintética con noise_floor=0.5, noise_pct=0.02 produce un
    chi²_red sano (no colapsado a ~0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.geophysics_weights import sigma_parametric
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


def test_sigma_parametric_is_floor_not_additive():
    d = np.array([0.0, 5.0, 50.0, 500.0])
    floor, pct = 0.5, 0.02
    sig = sigma_parametric(d, floor, pct)
    expected = np.maximum(floor, pct * np.abs(d))
    np.testing.assert_allclose(sig, np.maximum(expected, 1e-30))
    # La forma aditiva (bug) siempre es estrictamente mayor para |d|>0.
    additive = floor + pct * np.abs(d)
    assert np.all(sig <= additive)
    assert np.any(sig < additive)  # piso < aditivo cuando |d|>0


def _build_case():
    NX, NY, NZ, BS = 8, 6, 8, 20.0
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    sx, sz = np.meshgrid(
        np.linspace(BS, (NX - 1) * BS, 6), np.linspace(BS, (NZ - 1) * BS, 6)
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 14)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[4 * NY * NZ + 2 * NZ + 4] = 0.08  # cuerpo susceptible somero
    d_clean = G @ true
    return NX, NY, NZ, BS, x_c, y_c, z_c, sensors, fwd, inv, d_clean


def _solve_chi2(inv, d_obs, y_c, fwd, sensors, x_c, z_c, noise_floor, noise_pct, lam=500.0):
    meta = {}
    inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=lam, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0,
        noise_floor=noise_floor, noise_pct=noise_pct, solver_meta=meta,
    )
    return meta["chi2_final"]


def test_magnetic_chi2_sane_with_floor_and_collapses_when_sigma_inflated():
    NX, NY, NZ, BS, x_c, y_c, z_c, sensors, fwd, inv, d_clean = _build_case()

    # Señal fuerte (~50 nT) + ruido ~1 nT → operating point tipo-Morozov (residual
    # ≈ ruido) con lambda fijo; aquí el sigma SÍ discrimina (|d| ≫ floor).
    scale = 50.0 / (np.abs(d_clean).max() + 1e-12)
    d_scaled = d_clean * scale
    rng = np.random.default_rng(0)
    d_obs = d_scaled + 1.0 * rng.standard_normal(d_scaled.size)

    # (a) sigma de PISO correcto → chi²_red sano O(1).
    chi2_floor = _solve_chi2(inv, d_obs, y_c, fwd, sensors, x_c, z_c, 0.5, 0.02)
    assert 0.3 < chi2_floor < 3.0, f"chi2_final fuera de rango sano: {chi2_floor:.4f}"

    # (b) Mecanismo del bug: un sigma sobre-inflado (lo que la forma ADITIVA producía
    # cuando |d| ≫ floor) COLAPSA chi² hacia ~0. Emulamos la inflación con un floor
    # gigante y verificamos el colapso → confirma por qué el bug fingía sobreajuste.
    chi2_inflated = _solve_chi2(inv, d_obs, y_c, fwd, sensors, x_c, z_c, 1e6, 0.02)
    assert chi2_inflated < 0.01, f"sigma inflado debería colapsar chi²: {chi2_inflated:.6f}"
    assert chi2_floor > 50.0 * chi2_inflated
