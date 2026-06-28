"""
FASE 8.1b (peldaño 1 de la escalera de UQ — PARIDAD MAGNÉTICA) — "null-space shuttle".

Espejo del test de gravimetría (test_fase8_null_space_shuttle.py, Nivel 2) para el
motor MAGNÉTICO: MagnetometryInversion.null_space_shuttle_ensemble. El kernel
standalone null_space_shuttle_directions es COMPARTIDO (vive en gravimetry.py) y ya
está cubierto por el Nivel 1 de ese test; aquí solo se valida el método de motor con
el scaling magnético (Wz_inv depth-weighting, sin Ws, unidades SI).

Verifica:
  - forma del ensemble, máscara de aire (NaN bajo topografía), determinismo por semilla;
  - cada modelo alternativo reproduce el dato TMI casi igual de bien (promesa del shuttle);
  - respeto de bounds [susceptibility_min, susceptibility_max];
  - el abanico de modelos se ABRE con la profundidad (no-unicidad física magnética);
  - rechazo de m0 mal dimensionado.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ, BS = 8, 4, 8, 30.0


def _synthetic_setup():
    """Survey denso en superficie + un cuerpo susceptible compacto."""
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    xs = np.linspace(BS, (NX - 1) * BS, 6)
    zs = np.linspace(BS, (NZ - 1) * BS, 6)
    xg, zg = np.meshgrid(xs, zs)
    sensors = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()]).astype(np.float64)
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    mask = ((x_c - 120.0) ** 2 + (y_c - 60.0) ** 2 + (z_c - 120.0) ** 2) < 60.0 ** 2
    true[mask] = 0.2
    d_obs = G @ true
    return inv, fwd, sensors, x_c, y_c, z_c, d_obs, true


def test_ensemble_shape_air_mask_and_data_fit():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=10, seed=0,
    )
    assert out["ensemble"].shape == (10, inv.total_voxels)
    assert out["ensemble_std"].shape[0] == inv.total_voxels
    # Sin topografía todas las celdas están activas → todo finito.
    assert np.isfinite(out["ensemble_std"]).all()
    assert np.isfinite(out["ensemble"]).all()
    assert np.all(out["ensemble_std"] >= 0.0)
    # El abanico tiene spread (no degenerado a un solo modelo).
    assert np.median(out["ensemble_std"]) > 0.0
    # Honestidad: las alternativas preservan razonablemente el dato.
    assert out["data_fit_preserved"] < 0.25, out["data_fit_preserved"]


def test_ensemble_members_actually_fit_the_data():
    """Cada modelo alternativo reproduce el dato TMI casi tan bien como la
    solución de referencia (esa es la promesa del null-space shuttle)."""
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=8,
        shuttle_scale=0.5, smooth_strength=5.0, seed=0,
    )
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    base_misfit = np.linalg.norm((G @ true) - d_obs) / np.linalg.norm(d_obs)
    for k in range(out["n_shuttles"]):
        member = np.nan_to_num(out["ensemble"][k])
        d_k = G @ member
        misfit = np.linalg.norm(d_k - d_obs) / max(np.linalg.norm(d_obs), 1e-30)
        assert misfit < base_misfit + 0.15, (
            f"shuttle {k} degrada el ajuste: {misfit:.3g} vs base {base_misfit:.3g}"
        )


def test_ensemble_respects_bounds():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=8,
        shuttle_scale=2.0, susceptibility_min=0.0, susceptibility_max=0.25, seed=0,
    )
    finite = np.isfinite(out["ensemble"])
    vals = out["ensemble"][finite]
    assert vals.min() >= 0.0 - 1e-9
    assert vals.max() <= 0.25 + 1e-9


def test_ensemble_air_cells_nan_under_topography():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    topo = np.full(inv.total_voxels, BS)   # superficie a y=30 m → primera capa = aire
    out = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        topography_elevations=topo,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=6, seed=0,
    )
    voxel_top = y_c - BS / 2.0
    air = voxel_top < topo
    assert np.isnan(out["ensemble_std"][air]).all(), "Celdas de aire deben ser NaN."
    assert np.isfinite(out["ensemble_std"][~air]).all(), "Celdas activas deben ser finitas."


def test_ensemble_spread_grows_with_depth():
    """No-unicidad física: el abanico de modelos se ABRE en profundidad (la
    magnetometría no resuelve la susceptibilidad profunda → más alternativas)."""
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    out = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=24,
        shuttle_scale=0.5, smooth_strength=5.0, seed=0,
    )
    std = out["ensemble_std"]
    layer_means = []
    for iy in range(NY):
        mask = np.isclose(y_c, (iy + 0.5) * BS)
        layer_means.append(float(np.nanmean(std[mask])))
    assert layer_means[-1] > layer_means[0], (
        f"σ del ensemble debería crecer con la profundidad: {layer_means}"
    )


def test_ensemble_deterministic_with_seed():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    a = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=6, seed=11,
    )
    b = inv.null_space_shuttle_ensemble(
        true, d_obs, y_c, fwd, sensors, x_c, z_c,
        lambda_mag=1e-3, alpha_spatial=1.5, n_shuttles=6, seed=11,
    )
    np.testing.assert_array_equal(a["ensemble"], b["ensemble"])
    np.testing.assert_array_equal(a["ensemble_std"], b["ensemble_std"])


def test_rejects_wrong_m0_size():
    inv, fwd, sensors, x_c, y_c, z_c, d_obs, true = _synthetic_setup()
    with np.testing.assert_raises(ValueError):
        inv.null_space_shuttle_ensemble(
            true[:-1], d_obs, y_c, fwd, sensors, x_c, z_c,
        )
