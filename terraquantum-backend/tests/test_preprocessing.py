"""
Tests de regresión del módulo de preprocesamiento gravimétrico
(exploration/preprocessing.py): proyección equirectangular, separación
regional-residual polinómica y conversión a SI.

Estos pasos cierran el "gap industrial #2" (preprocesamiento que antes se hacía
a mano en los scripts de auditoría). Los tests fijan su comportamiento físico.
"""
import numpy as np
import pytest

from exploration.preprocessing import (
    MGAL_TO_SI,
    project_geographic_to_local,
    remove_regional_trend,
    residual_mgal_to_si,
)


# ── Proyección ────────────────────────────────────────────────────────────────
def test_projection_origin_at_sw_corner():
    lon = np.array([28.4, 28.6, 29.6])
    lat = np.array([-24.6, -24.0, -23.4])
    x, z, meta = project_geographic_to_local(lon, lat)
    # El origen es la esquina SW → mínimos en 0.
    assert np.isclose(x.min(), 0.0)
    assert np.isclose(z.min(), 0.0)
    assert meta["lon0"] == pytest.approx(28.4)
    assert meta["lat0"] == pytest.approx(-24.6)


def test_projection_scale_is_physically_reasonable():
    # 1° de latitud ≈ 110.54 km; 1° de longitud a -24° ≈ 111.32·cos(24°) ≈ 101.7 km
    lon = np.array([0.0, 1.0])
    lat = np.array([-24.0, -24.0])
    x, z, meta = project_geographic_to_local(lon, lat)
    assert x.max() == pytest.approx(111320.0 * np.cos(np.radians(-24.0)), rel=1e-6)
    # z no varía (misma latitud) → extensión 0
    assert np.isclose(z.max(), 0.0)


def test_projection_recovers_relative_geometry():
    # Distancia entre dos puntos debe preservarse aproximadamente.
    lon = np.array([28.5, 28.5])
    lat = np.array([-24.5, -24.0])  # 0.5° de latitud ≈ 55.27 km
    x, z, _ = project_geographic_to_local(lon, lat)
    dist = np.hypot(x[1] - x[0], z[1] - z[0])
    assert dist == pytest.approx(0.5 * 110540.0, rel=1e-6)


def test_projection_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        project_geographic_to_local(np.array([1.0, 2.0]), np.array([1.0]))


def test_projection_rejects_empty():
    with pytest.raises(ValueError):
        project_geographic_to_local(np.array([]), np.array([]))


# ── Separación regional-residual ────────────────────────────────────────────────
def test_regional_recovers_known_linear_trend():
    rng = np.random.default_rng(0)
    lon = 28.4 + 1.2 * rng.random(400)
    lat = -24.6 + 1.2 * rng.random(400)
    x, z, _ = project_geographic_to_local(lon, lat)

    # Tendencia regional lineal conocida (mGal) + anomalía local gaussiana.
    true_regional = 5.0 + 0.02 * x / 1000.0 + 0.01 * z / 1000.0
    anomaly = 10.0 * np.exp(-(((x - 60000) ** 2 + (z - 60000) ** 2) / (2 * 15000.0 ** 2)))
    g = true_regional + anomaly

    residual, regional, coef = remove_regional_trend(x, z, g, order=1)

    # El regional ajustado debe recuperar la tendencia conocida.
    assert np.corrcoef(regional, true_regional)[0, 1] > 0.99
    # El residual debe parecerse a la anomalía local inyectada.
    assert np.corrcoef(residual, anomaly)[0, 1] > 0.95


def test_residual_is_zero_mean():
    rng = np.random.default_rng(1)
    x = rng.random(200) * 1e5
    z = rng.random(200) * 1e5
    g = 3.0 + 1e-4 * x - 2e-4 * z + rng.normal(0, 0.5, 200)
    residual, _, _ = remove_regional_trend(x, z, g, order=2)
    # Un polinomio con término constante garantiza media del residual ≈ 0.
    assert abs(float(residual.mean())) < 1e-6


def test_regional_plus_residual_reconstructs_input():
    rng = np.random.default_rng(2)
    x = rng.random(150) * 5e4
    z = rng.random(150) * 5e4
    g = rng.normal(0, 10, 150) + 0.001 * x
    residual, regional, _ = remove_regional_trend(x, z, g, order=2)
    assert np.allclose(residual + regional, g, atol=1e-9)


def test_regional_rejects_insufficient_stations():
    # poly-2 → 6 términos; con 5 estaciones debe fallar.
    x = np.arange(5.0)
    z = np.arange(5.0)
    g = np.arange(5.0)
    with pytest.raises(ValueError):
        remove_regional_trend(x, z, g, order=2)


def test_regional_rejects_negative_order():
    x = np.arange(10.0)
    z = np.arange(10.0)
    g = np.arange(10.0)
    with pytest.raises(ValueError):
        remove_regional_trend(x, z, g, order=-1)


# ── Conversión de unidades ──────────────────────────────────────────────────────
def test_mgal_to_si_scale():
    res = np.array([1.0, -37.2, 85.4])
    si = residual_mgal_to_si(res)
    assert np.allclose(si, res * 1e-5)
    assert MGAL_TO_SI == 1.0e-5


def test_pipeline_end_to_end_runs():
    # Smoke test: lon/lat crudos → x,z → residual → SI, sin excepciones.
    rng = np.random.default_rng(3)
    lon = 28.4 + rng.random(300)
    lat = -24.6 + rng.random(300)
    g = 10.0 + rng.normal(0, 1, 300)
    x, z, _ = project_geographic_to_local(lon, lat)
    residual, _, _ = remove_regional_trend(x, z, g, order=2)
    g_si = residual_mgal_to_si(residual)
    assert g_si.shape == lon.shape
    assert np.isfinite(g_si).all()
