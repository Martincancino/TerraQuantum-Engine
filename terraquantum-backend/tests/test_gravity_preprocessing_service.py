"""
Tests del servicio de preprocesamiento gravimétrico
(services/gravity_preprocessing_service.py) y de su integración opcional en
build_sensor_arrays (OFF por defecto → comportamiento intacto).
"""
import numpy as np
import pytest

from services.gravity_preprocessing_service import (
    maybe_separate_regional_residual,
    separate_regional_residual,
)


def _grid(n=200, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.random(n) * 1.0e5
    z = rng.random(n) * 1.0e5
    y = np.zeros(n)
    coords = np.column_stack([x, y, z])
    return coords, x, z


def test_service_removes_known_regional():
    coords, x, z = _grid()
    regional = 50.0 + 1e-4 * x - 3e-4 * z          # plano conocido
    anomaly = 8.0 * np.exp(-(((x - 5e4) ** 2 + (z - 5e4) ** 2) / (2 * 1.2e4 ** 2)))
    g = regional + anomaly
    residual, meta = separate_regional_residual(coords, g, order=1)
    assert meta["applied"] is True
    assert abs(meta["residual_mean"]) < 1e-6           # media-cero
    assert np.corrcoef(residual, anomaly)[0, 1] > 0.95  # recupera la anomalía local


def test_service_validates_shape():
    with pytest.raises(ValueError):
        separate_regional_residual(np.zeros((10, 2)), np.zeros(10))
    with pytest.raises(ValueError):
        separate_regional_residual(np.zeros((10, 3)), np.zeros(9))


def test_toggle_off_returns_field_unchanged():
    coords, _, _ = _grid()
    g = np.linspace(1.0, 2.0, coords.shape[0])
    out, meta = maybe_separate_regional_residual(coords, g, enabled=False)
    assert meta is None
    assert np.array_equal(out, g)            # idéntico, sin tocar


def test_toggle_on_applies_separation():
    coords, x, z = _grid(seed=1)
    g = 10.0 + 2e-4 * x + np.random.default_rng(1).normal(0, 0.3, coords.shape[0])
    out, meta = maybe_separate_regional_residual(coords, g, enabled=True, order=2)
    assert meta is not None
    assert abs(float(out.mean())) < 1e-6


def test_build_sensor_arrays_default_off_is_unchanged():
    """Sin remove_regional, build_sensor_arrays devuelve g intacto (backward compat)."""
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import build_sensor_arrays

    rng = np.random.default_rng(2)
    obs = [
        GravityObservation(x_m=float(rng.random() * 1e4), y_m=0.0,
                           z_m=float(rng.random() * 1e4), g=float(5.0 + rng.random()))
        for _ in range(20)
    ]
    common = dict(depth=1000, nir=0, fe=0, region="t", lat="0", lon="0",
                  nx=4, ny=4, nz=4, block_size=100, cutoff_radius=800.0,
                  lambda_mag=1e-3, alpha_spatial=1.0, observations=obs)

    params_off = GeophysicsInvertInput(**common)
    _, g_off = build_sensor_arrays(params_off)
    g_raw = np.array([o.g for o in obs])
    assert np.array_equal(g_off, g_raw)

    params_on = GeophysicsInvertInput(**common, remove_regional=True, regional_order=2)
    _, g_on = build_sensor_arrays(params_on)
    assert abs(float(g_on.mean())) < 1e-6      # residual media-cero
    assert not np.array_equal(g_on, g_raw)     # efectivamente cambió
