"""
FASE 2.3 (God-Tier) — Membership dura por litología (bounds KKT por unidad).

Una celda atravesada por un intervalo de sondaje con litología CONOCIDA se restringe
al BOX petrofísico [min,max] de su unidad (no a un valor único como el anclaje). El
solver con bounds (TRF/FISTA proyectado) impone esas cajas satisfaciendo KKT por celda.
Funciona incluso sin densidad/susc puntual medida: basta conocer la unidad.

Verifica:
  1) lithology-only: celda sin dato puntual se restringe al box (densidad ∈ [min,max]);
  2) KKT superior: un cuerpo que empujaría sobre el box satura en el máximo, no lo excede;
  3) default (lithology_bounds=None) byte-idéntico al histórico;
  4) magnetometría: box de susceptibilidad respetado;
  5) helper de servicio _build_lithology_bounds_array (tabla + flag + match);
  6) schema: intervalo litología-only aceptado y propagado por to_intervals().
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ = 6, 6, 6
BS = 30.0
BASE_DENSITY = 2.6


def _grid_centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return (ix.ravel() + 0.5) * BS, (iy.ravel() + 0.5) * BS, (iz.ravel() + 0.5) * BS


def _voxel_index(ix, iy, iz):
    return ix * NY * NZ + iy * NZ + iz


def _sensors():
    xs = np.linspace(BS, (NX - 1) * BS, 5)
    zs = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs, zs)
    return np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])


def _litho_row(x, z, y_center, lo, hi):
    return np.array([[x, z, y_center - 1.0, y_center + 1.0, lo, hi]], dtype=np.float64)


def _solve_grav(lithology_bounds=None, true_contrast=None):
    rng = np.random.default_rng(11)
    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sensor_coords = _sensors()
    if true_contrast is None:
        true_contrast = np.zeros(NX * NY * NZ)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_contrast + 1e-10 * rng.standard_normal(sensor_coords.shape[0])
    meta = {}
    dens, _s, mis, _se = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=6.0,
        lithology_bounds=lithology_bounds,
        prune_observable_domain=True, solver_meta=meta,
    )
    return dens, mis, meta


def _solve_mag(lithology_bounds=None, true_susc=None):
    rng = np.random.default_rng(11)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    fwd = MagnetometryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sensor_coords = _sensors()
    if true_susc is None:
        true_susc = np.zeros(NX * NY * NZ)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    d_obs = G @ true_susc + 1e-9 * rng.standard_normal(sensor_coords.shape[0])
    meta = {}
    susc, _s, mis, _se = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-2, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=2.0,
        lithology_bounds=lithology_bounds, solver_meta=meta,
    )
    return susc, mis, meta


TOL = 1e-3


# ── 1) lithology-only: la celda se restringe al box (sin dato puntual) ──────
def test_grav_lithology_only_constrains_to_box():
    ix, iy, iz = 2, 2, 2
    idx = _voxel_index(ix, iy, iz)
    # Box [2.9, 3.1] (sobre base 2.6); data nula → min-norm querría 2.6, pero el
    # bound inferior 2.9 lo fuerza hacia arriba.
    dens, mis, meta = _solve_grav(_litho_row(75.0, 75.0, 75.0, 2.9, 3.1))
    assert meta.get("n_lithology_bounded", 0) >= 1
    assert np.isfinite(mis)
    rec = dens[idx]
    assert 2.9 - TOL <= rec <= 3.1 + TOL, f"densidad {rec:.4f} fuera del box [2.9,3.1]"
    assert abs(rec - 2.9) < 0.05, f"min-norm debería saturar en el bound inferior, got {rec:.4f}"


# ── 2) KKT superior: un cuerpo fuerte satura en el box, no lo excede ─────────
def test_grav_lithology_box_caps_strong_body():
    ix, iy, iz = 2, 2, 2
    idx = _voxel_index(ix, iy, iz)
    true = np.zeros(NX * NY * NZ)
    true[idx] = 1.5   # cuerpo fuerte (densidad real ~4.1) en la celda
    # Box estrecho [2.70, 2.80]: la inversión NO debe pasar de 2.80 en esa celda.
    dens, _m, meta = _solve_grav(_litho_row(75.0, 75.0, 75.0, 2.70, 2.80), true_contrast=true)
    assert meta.get("n_lithology_bounded", 0) >= 1
    rec = dens[idx]
    assert 2.70 - TOL <= rec <= 2.80 + TOL, f"densidad {rec:.4f} no respeta el box [2.70,2.80]"


# ── 3) default (None) byte-idéntico al histórico ────────────────────────────
def test_grav_default_none_byte_identical():
    dens_a, _m, _meta = _solve_grav(lithology_bounds=None)
    # Camino histórico SIN el kwarg.
    rng = np.random.default_rng(11)
    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()
    sc = _sensors()
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sc)
    g_obs = G @ np.zeros(NX * NY * NZ) + 1e-10 * rng.standard_normal(sc.shape[0])
    dens_b, _s, _mm, _se = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sc, x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=6.0,
        prune_observable_domain=True, solver_meta={},
    )
    assert np.array_equal(dens_a, dens_b, equal_nan=True)


# ── 4) magnetometría: box de susceptibilidad respetado ──────────────────────
def test_mag_lithology_box_respected():
    ix, iy, iz = 2, 2, 2
    idx = _voxel_index(ix, iy, iz)
    true = np.zeros(NX * NY * NZ)
    true[idx] = 1.0   # cuerpo fuerte
    susc, _m, meta = _solve_mag(_litho_row(75.0, 75.0, 75.0, 0.10, 0.30), true_susc=true)
    assert meta.get("n_lithology_bounded", 0) >= 1
    rec = susc[idx]
    assert 0.10 - TOL <= rec <= 0.30 + TOL, f"susc {rec:.4f} fuera del box [0.10,0.30]"


# ── 5) helper de servicio: tabla + flag + match case-insensitive ────────────
def test_service_builds_lithology_array():
    from services.geophysics_service import _build_lithology_bounds_array

    bh = [
        SimpleNamespace(x_m=10.0, z_m=20.0, y_from_m=0.0, y_to_m=30.0, lithology="Magnetite"),
        SimpleNamespace(x_m=40.0, z_m=50.0, y_from_m=10.0, y_to_m=40.0, lithology="granite"),
        SimpleNamespace(x_m=0.0, z_m=0.0, y_from_m=0.0, y_to_m=5.0, lithology=None),  # sin litología
    ]
    params_on = SimpleNamespace(lithology_hard_constraint=True, boreholes=bh, lithology_bounds=None)
    arr = _build_lithology_bounds_array(params_on, "density")
    assert arr is not None and arr.shape == (2, 6)   # 2 con litología conocida
    # magnetite density box default ≈ (4.90, 5.20)
    assert np.isclose(arr[0, 4], 4.90) and np.isclose(arr[0, 5], 5.20)

    # Flag apagado → None (default histórico).
    params_off = SimpleNamespace(lithology_hard_constraint=False, boreholes=bh, lithology_bounds=None)
    assert _build_lithology_bounds_array(params_off, "density") is None

    # Override del usuario.
    ov = SimpleNamespace(name="granite", density_min=2.60, density_max=2.70,
                         susc_min=None, susc_max=None)
    params_ov = SimpleNamespace(lithology_hard_constraint=True, boreholes=bh, lithology_bounds=[ov])
    arr2 = _build_lithology_bounds_array(params_ov, "density")
    _gran = arr2[np.isclose(arr2[:, 0], 40.0)][0]
    assert np.isclose(_gran[4], 2.60) and np.isclose(_gran[5], 2.70)


# ── 6) schema: intervalo litología-only aceptado y propagado ────────────────
def test_schema_lithology_only_interval():
    from schemas.geophysics_schema import BoreholeInterval, BoreholeSample, BoreholeSurvey

    iv = BoreholeInterval(x_m=0, z_m=0, y_from_m=0, y_to_m=10, lithology="diorite")
    assert iv.lithology == "diorite"
    assert iv.density_t_m3 is None and iv.susceptibility_si is None

    survey = BoreholeSurvey(holes=[
        BoreholeSample(hole_id="BH1", x_m=0, z_m=0, depth_from_m=0, depth_to_m=10, lithology="gabbro"),
    ])
    ivs = survey.to_intervals()
    assert len(ivs) == 1 and ivs[0].lithology == "gabbro"   # litología-only NO se descarta
