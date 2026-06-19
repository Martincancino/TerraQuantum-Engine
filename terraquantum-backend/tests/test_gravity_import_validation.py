"""
Tests Fase 14: CSV Validator Strict.

Verifica que _validate_gravity_observations detecta correctamente:
  - NaN / Inf en los datos
  - n_sensors < mínimo requerido
  - rango cero (todos iguales)
  - sensores duplicados (promediados automáticamente)
  - ruido anómalo (outlier aislado flaggeado)
  - datos limpios (sin warnings)
  - duplicados en malla 2D (columnas x,z)
  - mix de duplicados y datos limpios
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from exploration.gravimetry import _validate_gravity_observations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sensor_coords(n, *, seed=0, depth=0.0):
    """Genera n sensores en posiciones únicas (x, y=depth, z)."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0, 1000, n)
    zs = rng.uniform(0, 1000, n)
    ys = np.full(n, depth)
    return np.column_stack([xs, ys, zs])


def _make_clean_g(n, *, seed=0):
    """Genera n observaciones limpias con variación."""
    rng = np.random.default_rng(seed)
    return rng.uniform(-0.05, 0.05, n)


# ---------------------------------------------------------------------------
# 1. NaN / Inf
# ---------------------------------------------------------------------------

def test_nan_raises():
    g = _make_clean_g(10)
    g[3] = float("nan")
    with pytest.raises(ValueError, match="NaN o Inf"):
        _validate_gravity_observations(g, None)


def test_inf_raises():
    g = _make_clean_g(10)
    g[5] = float("inf")
    with pytest.raises(ValueError, match="NaN o Inf"):
        _validate_gravity_observations(g, None)


# ---------------------------------------------------------------------------
# 2. n_sensors mínimo
# ---------------------------------------------------------------------------

def test_min_sensors_error():
    """Menos de 5 observaciones → ValueError."""
    g = _make_clean_g(4)
    with pytest.raises(ValueError, match="al menos 5"):
        _validate_gravity_observations(g, None)


def test_exactly_min_sensors_ok():
    """Exactamente 5 observaciones → OK."""
    g = _make_clean_g(5)
    g_out, _, warns = _validate_gravity_observations(g, None)
    assert len(g_out) == 5
    # no debe haber error de mínimo
    assert not any("al menos" in w for w in warns)


# ---------------------------------------------------------------------------
# 3. Rango cero
# ---------------------------------------------------------------------------

def test_zero_range_error():
    """Todos los valores iguales → ValueError."""
    g = np.full(10, 0.03)
    with pytest.raises(ValueError, match="Rango de datos cero"):
        _validate_gravity_observations(g, None)


def test_zero_range_all_zeros_error():
    """Array de ceros → ValueError."""
    g = np.zeros(10)
    with pytest.raises(ValueError, match="Rango de datos cero"):
        _validate_gravity_observations(g, None)


# ---------------------------------------------------------------------------
# 4. Sensores duplicados → promedio + warning
# ---------------------------------------------------------------------------

def test_duplicate_sensors_averaged():
    """2 sensores en la misma posición (x,z) deben promediar g y emitir warning."""
    g = _make_clean_g(10)
    sc = _make_sensor_coords(10)
    # Copiar posición del sensor 0 al sensor 9
    sc[9, 0] = sc[0, 0]  # misma x
    sc[9, 2] = sc[0, 2]  # misma z
    g_orig_0 = g[0]
    g_orig_9 = g[9]

    g_out, sc_out, warns = _validate_gravity_observations(g, sc)

    # Debe haber 9 sensores (1 fusionado)
    assert len(g_out) == 9
    assert sc_out is not None and len(sc_out) == 9
    # El primer sensor debe tener el promedio
    assert abs(g_out[0] - (g_orig_0 + g_orig_9) / 2.0) < 1e-12
    # Warning presente
    assert any("duplicad" in w.lower() for w in warns), f"Warns: {warns}"


def test_duplicate_sensors_ok_if_different_positions():
    """Sensores en posiciones distintas no deben activar deduplication."""
    g = _make_clean_g(10)
    sc = _make_sensor_coords(10, seed=42)
    g_out, sc_out, warns = _validate_gravity_observations(g, sc)
    assert len(g_out) == 10
    assert not any("duplicad" in w.lower() for w in warns)


# ---------------------------------------------------------------------------
# 5. Ruido anómalo (outlier)
# ---------------------------------------------------------------------------

def test_anomalous_noise_flagged():
    """Un sensor con |g| >> 10× mediana debe generar warning."""
    g = _make_clean_g(20)
    g[5] = 100.0   # outlier masivo
    _, _, warns = _validate_gravity_observations(g, None)
    assert any("anómal" in w.lower() or "anomal" in w.lower() for w in warns), f"Warns: {warns}"


def test_anomalous_noise_no_false_positive():
    """Datos limpios no deben generar warning de ruido anómalo."""
    g = _make_clean_g(20)
    _, _, warns = _validate_gravity_observations(g, None)
    assert not any("anómal" in w.lower() or "anomal" in w.lower() for w in warns)


# ---------------------------------------------------------------------------
# 6. Datos completamente limpios → sin warnings, g inalterado
# ---------------------------------------------------------------------------

def test_clean_data_no_warnings():
    g = _make_clean_g(30)
    sc = _make_sensor_coords(30)
    g_out, sc_out, warns = _validate_gravity_observations(g, sc)
    assert len(warns) == 0
    assert len(g_out) == 30
    np.testing.assert_array_equal(g_out, g)
