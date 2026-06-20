"""
FASE 25B — Tests de MAGNITUD del anclaje de sondajes.

Los tests de la Fase 20 (test_borehole_integration.py) validan la DIRECCIÓN del
anclaje (medir alto > medir bajo), no la MAGNITUD. Esos siguen verdes.

Estos tests nuevos validan la MAGNITUD: tras el fix del target de smallness al
espacio m̃ (gravimetry.py, bloque `_small_target`), una celda anclada con
contraste físico c debe recuperar densidad ≈ base_density + c.

Bug original (medido E2E en Fase 25): se anclaba `m̃ → contraste`, pero
`densidad = base + Wz_inv·m̃`, así que la densidad solo subía ~Wz_inv·c ≈ base
(atenuada). Roca caja (c=0) anclaba exacto (2.6); el cuerpo (c=0.8) no se
levantaba (≈2.62 en vez de 3.4).

Fix: el target de smallness se transforma a m̃ dividiendo por diag(Wz_inv)
(el mismo operador que mapea m̃→densidad, ya con el column-norm Ws).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import GravimetryInversion, GravimetryForward


# ── Geometría sintética común ──────────────────────────────────────────────
NX, NY, NZ = 6, 6, 6
BS = 30.0
BASE_DENSITY = 2.6   # GravimetryInversion default


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


def _solve(boreholes_arr, true_contrast=None, anchor_kappa=1e4):
    """Inversión controlada. `true_contrast` define el modelo que genera g_obs;
    None → modelo nulo (data ≈ 0, así el anclaje es el único que levanta densidad)."""
    rng = np.random.default_rng(11)
    inv = GravimetryInversion(NX, NY, NZ, BS)          # base_density=2.6
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()

    xs_s = np.linspace(BS, (NX - 1) * BS, 5)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])

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
        anchor_kappa=anchor_kappa,
        auto_kappa=True,
        prune_observable_domain=True,
        solver_meta=meta,
    )
    return dens_full, misfit, meta


def _thin_bh(x, z, y_center, rho):
    """Intervalo más corto que dy → mapea al vóxel más cercano al midpoint."""
    return np.array([[x, z, y_center - 1.0, y_center + 1.0, rho]], dtype=np.float64)


# ─────────────────────────────────────────────────────────────────────────
#  1) MAGNITUD: contraste 0.8 → densidad ≈ 3.4
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_magnitude_contrast_0p8_recovers_3p4():
    # Columna (ix=2, iz=2) → x=75, z=75. Anclamos a media profundidad (y_c=75, iy=2).
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS                 # 75 m
    anchored_idx = _voxel_index(ix, iy, iz)
    rho_measured = 3.4                           # contraste físico = 0.8

    dens, misfit, meta = _solve(
        _thin_bh(75.0, 75.0, y_c_target, rho_measured)
    )

    assert meta.get("n_anchored_voxels", 0) >= 1
    assert np.isfinite(misfit)
    rec = dens[anchored_idx]
    assert abs(rec - rho_measured) <= 0.15, (
        f"densidad recuperada en celda anclada = {rec:.4f}, "
        f"se esperaba ≈ {rho_measured} (±0.15). El target de anclaje no se "
        f"transformó correctamente a m̃."
    )


# ─────────────────────────────────────────────────────────────────────────
#  2) Caso bueno NO se rompe: contraste 0 (roca caja) → densidad ≈ 2.6
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_contrast_zero_stays_base():
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS
    anchored_idx = _voxel_index(ix, iy, iz)
    rho_measured = BASE_DENSITY                  # contraste = 0

    dens, _misfit, meta = _solve(
        _thin_bh(75.0, 75.0, y_c_target, rho_measured)
    )
    assert meta.get("n_anchored_voxels", 0) >= 1
    rec = dens[anchored_idx]
    assert abs(rec - BASE_DENSITY) <= 0.05, (
        f"roca caja (contraste 0) debería anclar a base_density={BASE_DENSITY}, "
        f"obtuvo {rec:.6f}. El fix rompió el caso bueno."
    )


# ─────────────────────────────────────────────────────────────────────────
#  3) La corrección por Wz_inv funciona a DISTINTAS profundidades
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_magnitude_across_depths():
    ix, iz = 2, 2
    rho_measured = 3.4                            # contraste 0.8 en todas
    # iy=0 (somero, y=15), iy=2 (medio, y=75), iy=4 (profundo, y=135)
    for iy in (0, 2, 4):
        y_c_target = (iy + 0.5) * BS
        anchored_idx = _voxel_index(ix, iy, iz)
        dens, misfit, meta = _solve(
            _thin_bh(75.0, 75.0, y_c_target, rho_measured)
        )
        assert meta.get("n_anchored_voxels", 0) >= 1
        rec = dens[anchored_idx]
        assert abs(rec - rho_measured) <= 0.15, (
            f"profundidad iy={iy} (y={y_c_target:.0f}m): densidad recuperada "
            f"{rec:.4f}, se esperaba ≈ {rho_measured} (±0.15). La corrección "
            f"por Wz_inv no es uniforme en profundidad."
        )


# ─────────────────────────────────────────────────────────────────────────
#  4) El fix MEJORA la magnitud vs el caso sin anclaje (la atenuación se corrige)
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_lifts_density_vs_free():
    # Cuerpo real con contraste 0.8 en (2,2,2). La gravimetría sola ATENÚA la
    # amplitud (depth-weighting); con el anclaje debe recuperar ≈ 3.4.
    ix, iy, iz = 2, 2, 2
    anchored_idx = _voxel_index(ix, iy, iz)
    y_c_target = (iy + 0.5) * BS
    rho_measured = 3.4

    true_contrast = np.zeros(NX * NY * NZ)
    true_contrast[anchored_idx] = 0.8

    dens_free, _m0, _meta0 = _solve(None, true_contrast=true_contrast)
    dens_anch, _m1, meta1 = _solve(
        _thin_bh(75.0, 75.0, y_c_target, rho_measured),
        true_contrast=true_contrast,
    )
    assert meta1.get("n_anchored_voxels", 0) >= 1

    rec_free = dens_free[anchored_idx]
    rec_anch = dens_anch[anchored_idx]

    # El anclaje levanta la densidad MÁS cerca del valor medido que la grav sola.
    assert abs(rec_anch - rho_measured) < abs(rec_free - rho_measured), (
        f"anclada={rec_anch:.4f} no está más cerca de {rho_measured} que "
        f"libre={rec_free:.4f}"
    )
    # Y la anclada queda dentro de tolerancia.
    assert abs(rec_anch - rho_measured) <= 0.15, (
        f"densidad anclada {rec_anch:.4f} fuera de tolerancia de {rho_measured}"
    )
