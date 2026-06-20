"""
FASE 20B Tarea 1 — Tests de MAGNITUD del anclaje de sondajes MAGNÉTICO.

CONTEXTO (medido 2026-06-20): la Fase 25B arregló un bug de anclaje en m̃ del motor
de GRAVEDAD: su bloque smallness es `diags(_ws)` (identidad en m̃), por lo que anclar
m̃→contraste dejaba la densidad atenuada en base + diag(Wz_inv)·contraste. El fix de
gravedad fue dividir el target por diag(Wz_inv).

El motor MAGNÉTICO NO tiene ese bug. Su bloque smallness es
`_small_block = diags(_w_small) @ Wz_inv` (magnetometry.py), de modo que la fila de la
celda anclada penaliza  w·(Wz_inv·m̃ − target) = w·(susc_físico − target). Es decir, el
bloque ya opera en el espacio FÍSICO de la susceptibilidad y el target es el contraste
físico medido (= susc, porque base_susc=0). Por construcción ancla la susceptibilidad
física directamente, sin atenuación por profundidad.

Estos tests LO VERIFICAN (deben pasar con el motor ACTUAL, sin cambios): una celda
anclada con susceptibilidad X recupera X (±tol) a varias profundidades, mientras que la
inversión libre (sin anclaje) la atenúa con la profundidad (no-unicidad del campo
potencial, idéntico a gravedad). Sirven como guarda de regresión: si alguien "porta" el
fix de gravedad a magnético (dividir por diag(Wz_inv)), estos tests fallarían por
sobre-corrección — exactamente lo que se quiere evitar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


# ── Geometría sintética común ──────────────────────────────────────────────
NX, NY, NZ = 6, 6, 6
BS = 30.0
BASE_SUSC = 0.0   # MagnetometryInversion: la susceptibilidad ES el contraste


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


def _solve(boreholes_arr, true_susc=None, anchor_kappa=1e4):
    """Inversión controlada. `true_susc` define el modelo que genera d_obs.

    A diferencia del test de gravedad, el modelo NO puede ser exactamente nulo: con
    d_obs≈0 el sigma adaptivo colapsa (data_range→0) y el peso de datos (1/σ) aplasta
    cualquier otro término. Por eso se inyecta SIEMPRE una anomalía real (≥1 celda con
    susc>0) para que la calibración de σ sea representativa.
    """
    rng = np.random.default_rng(11)
    inv = MagnetometryInversion(NX, NY, NZ, BS)          # base_susc=0
    fwd = MagnetometryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()

    xs_s = np.linspace(BS, (NX - 1) * BS, 5)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])

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
        anchor_kappa=anchor_kappa,
        solver_meta=meta,
    )
    return susc_full, misfit, meta


def _thin_bh(x, z, y_center, susc):
    """Intervalo más corto que dy → mapea al vóxel más cercano al midpoint."""
    return np.array([[x, z, y_center - 1.0, y_center + 1.0, susc]], dtype=np.float64)


# ─────────────────────────────────────────────────────────────────────────
#  1) MAGNITUD: susc 0.3 → susceptibilidad recuperada ≈ 0.3
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_magnitude_susc_0p3_recovers_0p3():
    ix, iy, iz = 2, 2, 2
    y_c_target = (iy + 0.5) * BS                 # 75 m
    anchored_idx = _voxel_index(ix, iy, iz)
    susc_measured = 0.3

    true = np.zeros(NX * NY * NZ)
    true[anchored_idx] = susc_measured           # anomalía real en la celda anclada

    susc, misfit, meta = _solve(
        _thin_bh(75.0, 75.0, y_c_target, susc_measured),
        true_susc=true,
    )

    assert meta.get("n_anchored_voxels", 0) >= 1
    assert np.isfinite(misfit)
    rec = susc[anchored_idx]
    assert abs(rec - susc_measured) <= 0.03, (
        f"susceptibilidad recuperada en celda anclada = {rec:.4f}, "
        f"se esperaba ≈ {susc_measured} (±0.03). El anclaje magnético debe operar en "
        f"el espacio físico de χ (bloque diags(w)·Wz_inv)."
    )


# ─────────────────────────────────────────────────────────────────────────
#  2) Anclar una celda estéril a χ=0 no la levanta (caso bueno)
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_zero_stays_zero():
    # Anomalía real en una celda (body) y anclaje a 0 en OTRA celda estéril.
    body_idx = _voxel_index(4, 2, 4)
    sterile = (1, 2, 1)
    sterile_idx = _voxel_index(*sterile)
    y_c_target = (sterile[1] + 0.5) * BS

    true = np.zeros(NX * NY * NZ)
    true[body_idx] = 0.3

    susc, _misfit, meta = _solve(
        _thin_bh((sterile[0] + 0.5) * BS, (sterile[2] + 0.5) * BS, y_c_target, 0.0),
        true_susc=true,
    )
    assert meta.get("n_anchored_voxels", 0) >= 1
    rec = susc[sterile_idx]
    assert abs(rec - 0.0) <= 0.02, (
        f"celda estéril anclada a χ=0 debería quedar ≈0, obtuvo {rec:.6f}."
    )


# ─────────────────────────────────────────────────────────────────────────
#  3) La magnitud se respeta a DISTINTAS profundidades (no se atenúa)
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_magnitude_across_depths():
    ix, iz = 2, 2
    susc_measured = 0.3
    for iy in (0, 2, 4):                          # somero, medio, profundo
        y_c_target = (iy + 0.5) * BS
        anchored_idx = _voxel_index(ix, iy, iz)
        true = np.zeros(NX * NY * NZ)
        true[anchored_idx] = susc_measured
        susc, misfit, meta = _solve(
            _thin_bh(75.0, 75.0, y_c_target, susc_measured),
            true_susc=true,
        )
        assert meta.get("n_anchored_voxels", 0) >= 1
        rec = susc[anchored_idx]
        assert abs(rec - susc_measured) <= 0.03, (
            f"profundidad iy={iy} (y={y_c_target:.0f}m): χ recuperada {rec:.4f}, "
            f"se esperaba ≈ {susc_measured} (±0.03). El anclaje magnético se atenúa "
            f"con la profundidad → indicaría el bug m̃ (que magnético NO tiene)."
        )


# ─────────────────────────────────────────────────────────────────────────
#  4) El anclaje MEJORA la magnitud vs grav/mag sola (corrige la atenuación)
# ─────────────────────────────────────────────────────────────────────────
def test_anchor_lifts_susc_vs_free():
    ix, iy, iz = 2, 4, 2                          # celda profunda (atenuación fuerte)
    anchored_idx = _voxel_index(ix, iy, iz)
    y_c_target = (iy + 0.5) * BS
    susc_measured = 0.3

    true = np.zeros(NX * NY * NZ)
    true[anchored_idx] = susc_measured

    susc_free, _m0, _meta0 = _solve(None, true_susc=true)
    susc_anch, _m1, meta1 = _solve(
        _thin_bh(75.0, 75.0, y_c_target, susc_measured),
        true_susc=true,
    )
    assert meta1.get("n_anchored_voxels", 0) >= 1

    rec_free = susc_free[anchored_idx]
    rec_anch = susc_anch[anchored_idx]

    assert abs(rec_anch - susc_measured) < abs(rec_free - susc_measured), (
        f"anclada={rec_anch:.4f} no está más cerca de {susc_measured} que "
        f"libre={rec_free:.4f}"
    )
    assert abs(rec_anch - susc_measured) <= 0.03, (
        f"χ anclada {rec_anch:.4f} fuera de tolerancia de {susc_measured}"
    )
