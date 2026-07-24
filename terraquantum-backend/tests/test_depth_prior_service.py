# -*- coding: utf-8 -*-
"""Tests del prior de profundidad (services/depth_prior_service.py).

Unit tests RÁPIDOS de la construcción del ancla + un test `validation` (lento, se salta
por defecto) que verifica la GANANCIA física medida: el prior baja el error de profundidad
de la gravedad-sola.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.depth_prior_service import (
    build_depth_floor_prior,
    estimate_depth_prior_from_grid,
    estimate_depth_prior_from_stations,
    recommend_depth_floor,
)


def _grid(nx=4, ny=3, nz=4, bs=100.0):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def test_anchor_wellformed_and_forbids_shallow():
    x_c, y_c, z_c = _grid(nx=4, ny=3, nz=4, bs=100.0)
    prior = build_depth_floor_prior(x_c, z_c, base_density=2.67, depth_floor_m=150.0, source="test")
    assert prior is not None
    # Una columna por par (x,z) único = nx*nz = 16.
    assert prior.n_columns == 16
    assert prior.anchor.shape == (16, 5)
    # Todas ancladas a densidad base, desde y=0 hasta el horizonte.
    assert np.allclose(prior.anchor[:, 4], 2.67)          # densidad = base (contraste 0)
    assert np.allclose(prior.anchor[:, 2], 0.0)           # y_from = 0
    assert np.allclose(prior.anchor[:, 3], 150.0)         # y_to = horizonte
    # Las columnas cubren exactamente los pares (x,z) de la malla.
    cols = np.unique(np.column_stack([x_c, z_c]), axis=0)
    assert np.allclose(np.unique(prior.anchor[:, :2], axis=0), cols)


def test_no_prior_when_floor_nonpositive_or_nan():
    x_c, y_c, z_c = _grid()
    assert build_depth_floor_prior(x_c, z_c, 2.67, 0.0) is None
    assert build_depth_floor_prior(x_c, z_c, 2.67, -50.0) is None
    assert build_depth_floor_prior(x_c, z_c, 2.67, float("nan")) is None


def test_recommend_depth_floor_is_conservative():
    # Techo estimado = 70% de la profundidad-a-fuente (deja margen).
    assert recommend_depth_floor(500.0, safety_fraction=0.7) == pytest.approx(350.0)
    assert recommend_depth_floor(500.0, safety_fraction=1.0) == pytest.approx(500.0)
    with pytest.raises(ValueError):
        recommend_depth_floor(-10.0)
    with pytest.raises(ValueError):
        recommend_depth_floor(500.0, safety_fraction=1.5)


def test_bad_grid_shapes_raise():
    with pytest.raises(ValueError):
        build_depth_floor_prior(np.zeros((3, 3)), np.zeros((3, 3)), 2.67, 100.0)
    with pytest.raises(ValueError):
        build_depth_floor_prior(np.zeros(5), np.zeros(4), 2.67, 100.0)


def test_estimate_from_grid_gives_reasonable_floor():
    """Cadena automática RÁPIDA (espectro, sin inversión): grilla de una esfera analítica
    a 500 m → el espectro estima la profundidad → piso conservador POR DEBAJO de la verdad."""
    span, n, depth = 2000.0, 28, 500.0
    a = np.linspace(-span / 2, span / 2, n)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    grid = depth / (gx ** 2 + depth ** 2 + gz ** 2) ** 1.5   # g_y de esfera (forma, escala-invariante)
    mx, _my, mz = _grid(nx=8, ny=6, nz=8, bs=125.0)
    prior = estimate_depth_prior_from_grid(
        grid, x0=-span / 2, y0=-span / 2, dx=span / (n - 1), dy=span / (n - 1),
        mesh_x_c=mx, mesh_z_c=mz, base_density=2.67)
    assert prior is not None, "el espectro debería dar una profundidad utilizable en esta grilla densa"
    # Piso conservador: por debajo del centro verdadero (500 m) y positivo.
    assert 0 < prior.depth_floor_m < depth
    assert "espectro" in prior.source


def test_estimate_from_grid_none_on_tiny_grid():
    """Grilla demasiado chica para un espectro útil → None (no revienta)."""
    tiny = np.random.default_rng(0).standard_normal((5, 5))
    mx, _my, mz = _grid()
    assert estimate_depth_prior_from_grid(tiny, 0, 0, 100, 100, mx, mz, 2.67) is None


def test_estimate_from_stations_grids_and_estimates():
    """Cadena desde estaciones DISPERSAS (grid_scattered + espectro), rápida."""
    span, n, depth = 2000.0, 20, 500.0
    a = np.linspace(0.0, span, n)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    g = depth / (gx ** 2 + depth ** 2 + gz ** 2) ** 1.5
    mx, _my, mz = _grid(nx=8, ny=6, nz=8, bs=125.0)
    prior = estimate_depth_prior_from_stations(gx.ravel(), gz.ravel(), g.ravel(), mx, mz, 2.67)
    assert prior is not None and 0 < prior.depth_floor_m < depth


@pytest.mark.validation
@pytest.mark.slow
def test_depth_prior_flag_suppresses_shallow_mass_in_flow():
    """INTEGRACIÓN del flag opt-in en `run_geophysics_inversion` (flujo de producción):
    con `enable_depth_prior=True` la capa somera queda SIN contraste (el prior prohíbe masa
    somera); con False (default) NO. Lento (2 inversiones completas)."""
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import run_geophysics_inversion

    NX = NZ = 16
    NY = 12
    BLOCK = 125.0
    CENTER = NX * BLOCK / 2.0
    DEPTH, R, DRHO, BASE = 500.0, 150.0, 0.6, 2.67
    G = 6.67430e-11
    M = (DRHO * 1000.0) * (4.0 / 3.0) * np.pi * R ** 3
    a = np.linspace(120.0, NX * BLOCK - 120.0, 20)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    obs = [
        GravityObservation(
            x_m=float(x), y_m=0.0, z_m=float(z),
            g=float(G * M * DEPTH / (((x - CENTER) ** 2 + DEPTH ** 2 + (z - CENTER) ** 2) ** 1.5)),
        )
        for x, z in zip(gx.ravel(), gz.ravel())
    ]

    def _inp(flag):
        return GeophysicsInvertInput(
            project_id=None, run_id=None, depth=int(NY * BLOCK), nir=0, fe=0, region="test",
            nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=2600.0, lambda_mag=1e-3,
            alpha_spatial=1.0, observations=obs, density_min=0.0, density_max=5.5,
            base_density=BASE, enable_depth_prior=flag,
        )

    def _shallow(res):
        vs = [abs(v["density"] - BASE) for v in res.get("voxels", []) if int(v["iy"]) == 0]
        return float(np.mean(vs)) if vs else 0.0

    off = run_geophysics_inversion(_inp(False))
    on = run_geophysics_inversion(_inp(True))
    assert _shallow(on) < _shallow(off), (
        f"el prior no suprimió la masa somera: on={_shallow(on):.4f} off={_shallow(off):.4f}")


@pytest.mark.validation
@pytest.mark.slow
def test_depth_prior_reduces_gravity_depth_error():
    """GANANCIA física MEDIDA: con un buen horizonte, el error de profundidad de la
    gravedad-sola baja fuerte. Lento (re-invierte) → se salta salvo TQ_RUN_VALIDATION=1."""
    from scripts.validation.depth_prior_experiment import solve_grav_prior
    import scripts.validation.multiphysics_gain as MP

    sensors, g_obs, tmi, sig_g, sig_m, _pm, _pn = MP._make_data()
    base = solve_grav_prior(g_obs, sensors, sig_g, depth_floor=None)
    # Horizonte ~ techo real del cuerpo (lo que daría una fuente confiable).
    primed = solve_grav_prior(g_obs, sensors, sig_g,
                              depth_floor=MP.BODY_DEPTH - MP.BODY_RADIUS)
    assert base["depth_centroid_m"] is not None and primed["depth_centroid_m"] is not None
    # El prior debe recortar el error de profundidad al menos a la mitad.
    assert primed["depth_centroid_m"] <= 0.5 * base["depth_centroid_m"], (
        f"prior no mejoró: base={base['depth_centroid_m']} m primed={primed['depth_centroid_m']} m")
