"""
FASE 1.2 — Auto-desmagnetización (self-demagnetization).

Para cuerpos de alta susceptibilidad (κ≳0.1) la magnetización inducida perturba el
campo local: M = κ·H0/(1+Nκ), de modo que el motor lineal "ve" la susceptibilidad
APARENTE κ_eff = κ/(1+Nκ) < κ. Ignorarlo SUBESTIMA la susceptibilidad.

La corrección vive como cambio de variable en la frontera del servicio (bounds y
anclajes verdadero→aparente; salida aparente→verdadera). Aquí se valida:
  1. Las funciones κ↔κ_eff (inversa exacta, saturación, identidad en N=0).
  2. El pipeline a nivel solver (réplica EXACTA del mapeo del servicio): un cuerpo de
     alta susceptibilidad se recupera CORRECTAMENTE con self-demag, mientras que sin
     corrección queda subestimado por el factor 1/(1+Nκ).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.geophysics_weights import apparent_susceptibility, true_susceptibility
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion

NX, NY, NZ = 6, 6, 6
BS = 30.0


def _voxel_index(ix, iy, iz):
    return ix * NY * NZ + iy * NZ + iz


def _grid_centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return (ix.ravel() + 0.5) * BS, (iy.ravel() + 0.5) * BS, (iz.ravel() + 0.5) * BS


# ─────────────────────────────────────────────────────────────────────────
#  1) Funciones físicas κ ↔ κ_eff
# ─────────────────────────────────────────────────────────────────────────
def test_apparent_true_are_exact_inverses():
    N = 1.0 / 3.0
    for k in [0.0, 0.05, 0.3, 1.0, 2.5, 7.0]:
        keff = apparent_susceptibility(k, N)
        back = true_susceptibility(keff, N)
        assert abs(float(back) - k) < 1e-9, f"κ={k} keff={keff} back={back}"
        assert keff <= k + 1e-12  # la aparente NUNCA supera la verdadera


def test_zero_factor_is_identity():
    for k in [0.0, 0.3, 2.0]:
        assert float(apparent_susceptibility(k, 0.0)) == k
        assert float(true_susceptibility(k, 0.0)) == k


def test_high_kappa_saturates_to_one_over_N():
    N = 1.0 / 3.0
    keff = float(apparent_susceptibility(1e6, N))
    assert abs(keff - 1.0 / N) < 1e-3  # κ→∞ ⇒ κ_eff→1/N = 3


# ─────────────────────────────────────────────────────────────────────────
#  2) Pipeline a nivel solver (réplica del cambio de variable del servicio)
# ─────────────────────────────────────────────────────────────────────────
def _solve_anchored(true_model, anchor_susc, susc_max):
    """Inversión anclada (replica el path escalar del servicio)."""
    rng = np.random.default_rng(7)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    fwd = MagnetometryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 12)
    x_c, y_c, z_c = _grid_centers()

    xs_s = np.linspace(BS, (NX - 1) * BS, 5)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 5)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])

    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    d_obs = G @ true_model + 1e-9 * rng.standard_normal(sensor_coords.shape[0])

    # Ancla la celda central (ix,iy,iz)=(2,2,2) con su valor APARENTE.
    y_center = (2 + 0.5) * BS
    bh = np.array([[2.5 * BS, 2.5 * BS, y_center - 1.0, y_center + 1.0, anchor_susc]],
                  dtype=np.float64)
    meta: dict = {}
    susc, _score, misfit, _sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c,
        lambda_mag=1e-2, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=susc_max,
        boreholes=bh, anchor_kappa=1e4,
        solver_meta=meta,
    )
    return susc, meta


def test_self_demag_recovers_true_high_susceptibility():
    """Cuerpo de κ_verdadera=1.5 (magnetita): self-demag lo recupera; ignorarlo subestima."""
    N = 1.0 / 3.0
    true_kappa = 1.5
    kappa_eff = float(apparent_susceptibility(true_kappa, N))  # = 1.0

    # El dato físico de un cuerpo de alta κ se genera con la susceptibilidad APARENTE
    # (es lo que produce el campo: M = κ_eff·H0·kernel).
    idx = _voxel_index(2, 2, 2)
    true_model = np.zeros(NX * NY * NZ)
    true_model[idx] = kappa_eff

    # Servicio: bound y anclaje en espacio APARENTE.
    susc_max_app = float(apparent_susceptibility(2.0, N))
    susc_app, meta = _solve_anchored(true_model, anchor_susc=kappa_eff, susc_max=susc_max_app)

    assert meta.get("n_anchored_voxels", 0) >= 1
    rec_apparent = float(susc_app[idx])            # lo que ve el motor lineal
    rec_true = float(true_susceptibility(rec_apparent, N))  # lo que reporta el servicio

    # Con self-demag se recupera la susceptibilidad VERDADERA.
    assert abs(rec_true - true_kappa) < 0.08, f"true_rec={rec_true} vs {true_kappa}"
    # Sin self-demag (reportar la aparente) se SUBESTIMA notablemente.
    underestimate = (true_kappa - rec_apparent) / true_kappa
    assert underestimate > 0.25, f"subestimación esperada >25%, fue {underestimate:.2%}"


def test_no_demag_path_is_unchanged():
    """N=0 (default): bound y salida quedan idénticos (sin cambio de variable)."""
    N = 0.0
    assert float(apparent_susceptibility(0.7, N)) == 0.7
    assert float(true_susceptibility(0.7, N)) == 0.7


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
