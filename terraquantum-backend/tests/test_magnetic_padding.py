"""
Padding de malla magnético — condición de frontera física (fix del artefacto de borde).
========================================================================================

El motor magnético no tenía padding: una fuente fuerte en el límite del survey no tiene
celdas donde ubicarse y satura el borde de la malla (artefacto medido en Raglan, pico global
a 1061 m del cuerpo real). El padding (celdas que crecen geométricamente hacia afuera) es la
condición de frontera físicamente correcta de campos potenciales — estándar en toda inversión
(VOXI/UBC la usan). Estos tests verifican, sobre un caso SINTÉTICO controlado con la fuente
DELIBERADAMENTE fuera del borde del survey, que el padding:

  1. Genera celdas correctas (core alineado, padding geométrico, máscara is_core).
  2. Hace EXPLICABLE el dato (el misfit se desploma) al darle a la fuente de borde celdas
     reales donde ubicarse, en vez de saturar la pared del core.
  3. Mueve el pico recuperado del borde hacia la fuente verdadera (mejor targeting).
  4. Es opt-in: padding_mask=None reproduce el comportamiento histórico EXACTO.
  5. Interactúa bien con la poda observable (R-05): el padding lateral sensible se conserva,
     solo el far-field ciego se descarta.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from services.inversion_kernel_service import (
    build_padded_tensor_grid,
    build_tensor_mesh_with_padding,
)

BS = 100.0
NX, NY, NZ = 14, 4, 14          # North, depth (down+), East
INC, DEC, B0 = 75.0, 10.0, 55000.0
CUTOFF = 2500.0


# ───────────────────────────── Generación de malla ──────────────────────────────
def test_padded_tensor_grid_geometry():
    """Core alineado con build_voxel_grid + padding que crece geométricamente."""
    m = build_padded_tensor_grid(nx=4, ny=2, nz=4, block_size=100.0, n_pad=3, pad_factor=1.3)
    assert m["nx_total"] == 4 + 2 * 3
    assert m["ny_total"] == 2 + 2 * 3
    assert m["nz_total"] == 4 + 2 * 3
    # Núcleo: nx*ny*nz celdas marcadas is_core
    assert int(m["is_core"].sum()) == 4 * 2 * 4
    # Centros del core alineados con (k+0.5)*dx
    np.testing.assert_allclose(np.unique(m["x_c_core"]), [50, 150, 250, 350])
    # Anchos: core uniforme = dx; padding crece hacia afuera (h·f^i)
    hx = m["hx"]
    np.testing.assert_allclose(hx[3:7], 100.0)                 # 4 celdas core
    assert hx[2] == pytest.approx(100.0)                       # 1ª de padding = h_core
    assert hx[1] == pytest.approx(130.0)                       # h·1.3
    assert hx[0] == pytest.approx(169.0)                       # h·1.3²
    assert hx[0] > hx[1] > hx[2]                               # ensancha hacia el exterior


def test_padded_grid_n_pad_zero_is_pure_core():
    """n_pad=0 = grilla uniforme pura (fallback 'sin padding' por el mismo code path)."""
    m = build_padded_tensor_grid(nx=4, ny=2, nz=4, block_size=100.0, n_pad=0)
    assert m["nx_total"] == 4 and m["ny_total"] == 2 and m["nz_total"] == 4
    assert bool(m["is_core"].all())
    np.testing.assert_allclose(m["hx"], 100.0)


def test_build_tensor_mesh_with_padding_wrapper_matches():
    """El wrapper sobre params delega en build_padded_tensor_grid (gravedad producción)."""
    class _P:
        nx, ny, nz, block_size = 5, 3, 6, 120.0
    m1 = build_tensor_mesh_with_padding(_P(), n_pad=4, pad_factor=1.25)
    m2 = build_padded_tensor_grid(5, 3, 6, 120.0, n_pad=4, pad_factor=1.25)
    np.testing.assert_array_equal(m1["hx"], m2["hx"])
    np.testing.assert_array_equal(m1["is_core"], m2["is_core"])


# ───────────────────────────── Helpers de inversión ─────────────────────────────
def _mkfwd():
    return MagnetometryForward(
        BS, BS, BS, cutoff_radius=CUTOFF,
        inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0,
    )


def _grid_uniform(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _make_edge_source_data():
    """Dato sintético de una fuente FUERTE ubicada MÁS ALLÁ del borde Este del survey.

    El mundo verdadero se define sobre coords con padding para que el cuerpo viva fuera del
    core. Los sensores cubren solo el footprint del core (el survey). Sin padding el motor no
    tiene dónde poner la fuente → artefacto de borde. Devuelve (d, sensors, true_east).
    """
    mw = build_padded_tensor_grid(NX, NY, NZ, BS, n_pad=4, pad_factor=1.3)
    wx, wy, wz = mw["x_c"], mw["y_c"], mw["z_c"]
    core_edge_E = wz[mw["is_core"]].max()
    true_east = core_edge_E + 250.0
    true = np.zeros(wx.size)
    body = (np.abs(wx - 700) <= 110) & (np.abs(wy - 150) <= 110) & (np.abs(wz - true_east) <= 160)
    true[body] = 0.08
    sx, sy = np.meshgrid(np.linspace(50, NX * BS - 50, 18), np.linspace(50, NZ * BS - 50, 18))
    sensors = np.column_stack([sx.ravel(), np.full(sx.size, -30.0), sy.ravel()])
    active = wy >= 0
    G = _mkfwd()._build_sparse_kernel(wx[active], wy[active], wz[active], sensors)
    d = G @ true[active]
    return d, sensors, true_east


def _invert(d, sensors, n_pad):
    if n_pad == 0:
        gx, gy, gz = _grid_uniform(NX, NY, NZ, BS)
        inv = MagnetometryInversion(NX, NY, NZ, BS)
        pmask, hx, hy, hz, is_core = None, None, None, None, np.ones(gx.size, bool)
    else:
        m = build_padded_tensor_grid(NX, NY, NZ, BS, n_pad=n_pad, pad_factor=1.3)
        gx, gy, gz = m["x_c"], m["y_c"], m["z_c"]
        inv = MagnetometryInversion(m["nx_total"], m["ny_total"], m["nz_total"], BS)
        pmask, hx, hy, hz, is_core = ~m["is_core"], m["hx"], m["hy"], m["hz"], m["is_core"]
    meta = {}
    chi, _, misfit, _ = inv.solve_magnetic_inversion_lsqr(
        d_observed=d, y_c=gy, forward_model=_mkfwd(), sensor_coords=sensors,
        x_c=gx, z_c=gz, lambda_mag=1e-3, alpha_spatial=1.0,
        susc_min=0.0, susc_max=0.12,
        noise_floor=float(np.max(np.abs(d))) * 0.01 + 1e-6, noise_pct=0.0,
        detect_outliers=False, prune_observable_domain=True,
        regularization_norm="compact", compact_max_irls=2,
        hx=hx, hy=hy, hz=hz, padding_mask=pmask, padding_kappa=1e5, solver_meta=meta,
    )
    return chi, misfit, meta, (gx, gy, gz), is_core


# ───────────────────────────── Tests del fix físico ─────────────────────────────
def test_padding_makes_edge_source_explainable():
    """El misfit se desploma con padding: la fuente de borde por fin tiene dónde ubicarse."""
    d, sensors, _ = _make_edge_source_data()
    _, misfit_no, _, _, _ = _invert(d, sensors, n_pad=0)
    _, misfit_pad, meta_pad, _, _ = _invert(d, sensors, n_pad=4)
    # Sin padding la fuente de borde es prácticamente inexplicable (misfit alto);
    # con padding el dato se ajusta bien.
    assert misfit_no > 30.0, f"esperado misfit alto sin padding, got {misfit_no:.1f}%"
    assert misfit_pad < 10.0, f"esperado misfit bajo con padding, got {misfit_pad:.1f}%"
    assert misfit_pad < 0.5 * misfit_no
    assert meta_pad["padding_active"] is True
    assert meta_pad["n_padding_solved"] > 0


def test_padding_moves_peak_off_the_edge():
    """El pico recuperado se mueve del borde del core hacia la fuente verdadera (targeting)."""
    d, sensors, true_east = _make_edge_source_data()
    chi_no, _, _, (gx0, gy0, gz0), isc0 = _invert(d, sensors, n_pad=0)
    chi_pad, _, _, (gxp, gyp, gzp), iscp = _invert(d, sensors, n_pad=4)

    # Pico GLOBAL (incluye padding): East debe acercarse a la fuente real (fuera del core).
    gip0 = int(np.nanargmax(np.where(np.isfinite(chi_no), chi_no, -np.inf)))
    gipp = int(np.nanargmax(np.where(np.isfinite(chi_pad), chi_pad, -np.inf)))
    peak_E_no, peak_E_pad = gz0[gip0], gzp[gipp]
    core_edge_E = gz0[isc0].max()
    assert peak_E_no <= core_edge_E + 1, "sin padding el pico queda clavado en el borde del core"
    assert peak_E_pad > peak_E_no, "con padding el pico se aleja del borde hacia la fuente"
    assert abs(peak_E_pad - true_east) < abs(peak_E_no - true_east)


def test_padding_default_none_is_opt_in():
    """padding_mask=None NO altera el camino histórico (sin padding activo en meta)."""
    d, sensors, _ = _make_edge_source_data()
    _, _, meta, _, _ = _invert(d, sensors, n_pad=0)
    assert meta["padding_active"] is False
    assert meta["n_padding_active"] == 0
    assert meta["padding_kappa"] is None


def test_lateral_padding_survives_observable_pruning():
    """R-05 conserva el padding lateral sensible (el que absorbe el borde); poda el far-field."""
    d, sensors, _ = _make_edge_source_data()
    _, _, meta, _, _ = _invert(d, sensors, n_pad=4)
    # Hay padding far-field ciego que se poda, PERO una mayoría del padding sensible sobrevive
    # (de lo contrario no podría absorber el artefacto de borde).
    assert meta["n_padding_active"] > 0
    assert meta["n_padding_solved"] > 0
    assert meta["n_padding_solved"] > meta["n_padding_pruned"], (
        "la poda no debe eliminar el grueso del padding sensible"
    )


def test_padding_mask_wrong_length_raises():
    """padding_mask con longitud != total_voxels es un error explícito (no silent)."""
    d, sensors, _ = _make_edge_source_data()
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    gx, gy, gz = _grid_uniform(NX, NY, NZ, BS)
    with pytest.raises(ValueError, match="padding_mask"):
        inv.solve_magnetic_inversion_lsqr(
            d_observed=d, y_c=gy, forward_model=_mkfwd(), sensor_coords=sensors,
            x_c=gx, z_c=gz, lambda_mag=1e-3,
            padding_mask=np.zeros(gx.size + 5, dtype=bool),
        )
