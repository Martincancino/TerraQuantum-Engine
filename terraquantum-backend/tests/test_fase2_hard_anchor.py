"""
FASE 2.1 (God-Tier) — Anclaje DURO de sondajes (hard constraint por eliminación).

El anclaje "soft" (histórico) penaliza la celda anclada con smallness × anchor_kappa:
con κ finito queda un error residual (~unos %). El anclaje "hard" ELIMINA la celda
del sistema (su contribución pasa al RHS) y reinyecta el valor medido del sondaje
→ la densidad/susceptibilidad de la celda anclada es EXACTA (a precisión de máquina).

Estos tests verifican:
  1) hard recupera el valor medido EXACTO (≤1e-6) en gravedad y magnetometría;
  2) el modo "soft" explícito es byte-idéntico al default (sin regresión);
  3) hard es estrictamente MÁS exacto que soft;
  4) exactitud a varias profundidades;
  5) anclar una celda no destruye la recuperación de un cuerpo libre vecino;
  6) anchor_mode inválido eleva ValueError.

Reusa la geometría sintética de test_fase25b/20b_anchor_magnitude.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


# ── Geometría sintética común ──────────────────────────────────────────────
NX, NY, NZ = 6, 6, 6
BS = 30.0
BASE_DENSITY = 2.6
BASE_SUSC = 0.0


def _grid_centers():
    ix, iy, iz = np.meshgrid(
        np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij"
    )
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS   # y = profundidad
    z_c = (iz.ravel() + 0.5) * BS
    return x_c, y_c, z_c


def _voxel_index(ix, iy, iz):
    return ix * NY * NZ + iy * NZ + iz


def _sensors():
    xs_s = np.linspace(BS, (NX - 1) * BS, 5)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs_s, zs_s)
    return np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])


def _thin_bh(x, z, y_center, val):
    return np.array([[x, z, y_center - 1.0, y_center + 1.0, val]], dtype=np.float64)


# ── Solvers controlados ─────────────────────────────────────────────────────
def _solve_grav(boreholes_arr, true_contrast=None, anchor_mode="soft"):
    rng = np.random.default_rng(11)
    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sensor_coords = _sensors()
    if true_contrast is None:
        true_contrast = np.zeros(NX * NY * NZ)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_contrast + 1e-10 * rng.standard_normal(sensor_coords.shape[0])
    meta: dict = {}
    dens_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=6.0,
        boreholes=boreholes_arr,
        anchor_kappa=1e4, anchor_mode=anchor_mode,
        auto_kappa=True, prune_observable_domain=True,
        solver_meta=meta,
    )
    return dens_full, misfit, meta


def _solve_mag(boreholes_arr, true_susc=None, anchor_mode="soft"):
    rng = np.random.default_rng(11)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    fwd = MagnetometryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sensor_coords = _sensors()
    if true_susc is None:
        true_susc = np.zeros(NX * NY * NZ)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    d_obs = G @ true_susc + 1e-9 * rng.standard_normal(sensor_coords.shape[0])
    meta: dict = {}
    susc_full, _score, misfit, _sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c,
        lambda_mag=1e-2, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=2.0,
        boreholes=boreholes_arr,
        anchor_kappa=1e4, anchor_mode=anchor_mode,
        solver_meta=meta,
    )
    return susc_full, misfit, meta


EXACT = 1e-6   # tolerancia "exacto" (precisión de máquina, no κ finito)


# ═══════════════════════════ GRAVEDAD ═══════════════════════════════════════
def test_grav_hard_anchor_is_exact():
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS
    anchored_idx = _voxel_index(ix, iy, iz)
    rho = 3.4   # contraste 0.8

    dens, misfit, meta = _solve_grav(
        _thin_bh(75.0, 75.0, y_c_target, rho), anchor_mode="hard"
    )
    assert meta.get("anchor_mode") == "hard"
    assert meta.get("anchor_kappa") is None, "hard ignora anchor_kappa"
    assert np.isfinite(misfit)
    rec = dens[anchored_idx]
    assert abs(rec - rho) <= EXACT, (
        f"hard debe ser EXACTO: recuperó {rec:.8f}, se esperaba {rho} (±{EXACT})."
    )


def test_grav_hard_strictly_more_exact_than_soft():
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS
    anchored_idx = _voxel_index(ix, iy, iz)
    rho = 3.4
    bh = _thin_bh(75.0, 75.0, y_c_target, rho)

    dens_soft, _ms, _ = _solve_grav(bh, anchor_mode="soft")
    dens_hard, _mh, _ = _solve_grav(bh, anchor_mode="hard")
    err_soft = abs(dens_soft[anchored_idx] - rho)
    err_hard = abs(dens_hard[anchored_idx] - rho)
    assert err_hard < err_soft, (
        f"hard (err={err_hard:.2e}) no es más exacto que soft (err={err_soft:.2e})"
    )
    assert err_hard <= EXACT


def test_grav_soft_default_byte_identical():
    """El modo 'soft' explícito = default (sin kwarg) → cero regresión."""
    ix, iy, iz = 2, 2, 2
    bh = _thin_bh(75.0, 75.0, (iy + 0.5) * BS, 3.4)
    # default (sin pasar anchor_mode) reusa _solve_grav con "soft".
    dens_a, _, _ = _solve_grav(bh, anchor_mode="soft")

    # Repetir con el path histórico SIN el kwarg (firma con default "soft").
    rng = np.random.default_rng(11)
    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sensor_coords = _sensors()
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ np.zeros(NX * NY * NZ) + 1e-10 * rng.standard_normal(sensor_coords.shape[0])
    dens_b, _s, _m, _se = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=6.0,
        boreholes=bh, anchor_kappa=1e4, auto_kappa=True,
        prune_observable_domain=True, solver_meta={},
    )
    assert np.array_equal(dens_a, dens_b, equal_nan=True), (
        "anchor_mode='soft' explícito difiere del default histórico (regresión)."
    )


def test_grav_hard_across_depths_exact():
    ix, iz = 2, 2
    rho = 3.4
    for iy in (0, 2, 4):
        y_c_target = (iy + 0.5) * BS
        anchored_idx = _voxel_index(ix, iy, iz)
        dens, _m, meta = _solve_grav(
            _thin_bh(75.0, 75.0, y_c_target, rho), anchor_mode="hard"
        )
        rec = dens[anchored_idx]
        assert abs(rec - rho) <= EXACT, (
            f"iy={iy}: hard recuperó {rec:.8f}, se esperaba {rho} exacto."
        )


def test_grav_hard_preserves_free_body():
    """Anclar una celda no destruye un cuerpo libre vecino ni el misfit."""
    anch = _voxel_index(1, 2, 1)
    body = _voxel_index(4, 2, 4)
    true = np.zeros(NX * NY * NZ)
    true[body] = 0.8
    y_c_target = (2 + 0.5) * BS
    dens, misfit, meta = _solve_grav(
        _thin_bh((1 + 0.5) * BS, (1 + 0.5) * BS, y_c_target, BASE_DENSITY),
        true_contrast=true, anchor_mode="hard",
    )
    # celda anclada a base exacta
    assert abs(dens[anch] - BASE_DENSITY) <= EXACT
    # el cuerpo libre sigue por encima de base (no fue aplanado por el anclaje).
    # La magnitud recuperada es modesta: la gravimetría sola atenúa con la
    # profundidad (la misma no-unicidad del campo potencial) — el test solo
    # comprueba que el anclaje duro NO destruye la señal del cuerpo vecino.
    assert dens[body] > BASE_DENSITY + 1e-3
    assert np.isfinite(misfit)


# ═══════════════════════════ MAGNETOMETRÍA ══════════════════════════════════
def test_mag_hard_anchor_is_exact():
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS
    anchored_idx = _voxel_index(ix, iy, iz)
    chi = 0.3
    true = np.zeros(NX * NY * NZ)
    true[anchored_idx] = chi
    susc, misfit, meta = _solve_mag(
        _thin_bh(75.0, 75.0, y_c_target, chi), true_susc=true, anchor_mode="hard"
    )
    assert meta.get("anchor_mode") == "hard"
    assert meta.get("anchor_kappa") is None
    assert np.isfinite(misfit)
    rec = susc[anchored_idx]
    assert abs(rec - chi) <= EXACT, (
        f"mag hard debe ser EXACTO: recuperó {rec:.8f}, se esperaba {chi}."
    )


def test_mag_hard_strictly_more_exact_than_soft():
    ix, iy, iz = 2, 4, 2   # profunda: soft atenúa más
    anchored_idx = _voxel_index(ix, iy, iz)
    chi = 0.3
    true = np.zeros(NX * NY * NZ)
    true[anchored_idx] = chi
    bh = _thin_bh(75.0, 75.0, (iy + 0.5) * BS, chi)
    susc_soft, _ms, _ = _solve_mag(bh, true_susc=true, anchor_mode="soft")
    susc_hard, _mh, _ = _solve_mag(bh, true_susc=true, anchor_mode="hard")
    err_soft = abs(susc_soft[anchored_idx] - chi)
    err_hard = abs(susc_hard[anchored_idx] - chi)
    assert err_hard < err_soft
    assert err_hard <= EXACT


def test_mag_hard_across_depths_exact():
    ix, iz = 2, 2
    chi = 0.3
    for iy in (0, 2, 4):
        y_c_target = (iy + 0.5) * BS
        anchored_idx = _voxel_index(ix, iy, iz)
        true = np.zeros(NX * NY * NZ)
        true[anchored_idx] = chi
        susc, _m, _meta = _solve_mag(
            _thin_bh(75.0, 75.0, y_c_target, chi), true_susc=true, anchor_mode="hard"
        )
        rec = susc[anchored_idx]
        assert abs(rec - chi) <= EXACT, (
            f"mag iy={iy}: recuperó {rec:.8f}, se esperaba {chi} exacto."
        )


# ═══════════════════════════ VALIDACIÓN ═════════════════════════════════════
def test_invalid_anchor_mode_raises():
    bh = _thin_bh(75.0, 75.0, 75.0, 3.4)
    with pytest.raises(ValueError, match="anchor_mode"):
        _solve_grav(bh, anchor_mode="bogus")
    with pytest.raises(ValueError, match="anchor_mode"):
        _solve_mag(bh, anchor_mode="bogus")
