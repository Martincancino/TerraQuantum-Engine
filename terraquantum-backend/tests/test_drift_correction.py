"""F2B — Corrección de deriva por cierres de base (drift_correction_service).

Verdad sintética: se inyecta una deriva CONOCIDA sobre lecturas limpias y se
exige recuperación exacta (lineal → deriva lineal; por tramos → exacta en
cada cierre). Guardarraíles: <2 bases, tiempos desordenados, todo-base.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.drift_correction_service import (  # noqa: E402
    DriftInputError,
    correct_drift,
    suggest_base_station,
)

T0 = datetime(2012, 3, 1, 8, 0, 0)


def _survey(drift_fn, n_st=8):
    """BASE,S1..S4,BASE,S5..S8,BASE con g_true conocida + deriva inyectada."""
    times, g_true, is_base = [], [], []
    plan = (
        [("BASE", 0.0)]
        + [(f"S{i}", None) for i in range(1, 5)]
        + [("BASE", 0.0)]
        + [(f"S{i}", None) for i in range(5, 9)]
        + [("BASE", 0.0)]
    )
    rng = np.random.RandomState(42)
    for k, (sid, base_val) in enumerate(plan):
        t = T0 + timedelta(minutes=45 * k)
        times.append(t)
        is_base.append(sid == "BASE")
        g_true.append(0.0 if sid == "BASE" else float(rng.uniform(-20, 20)))
    hours = np.array([(t - T0).total_seconds() / 3600.0 for t in times])
    readings = np.array(g_true) + np.array([drift_fn(h) for h in hours])
    return times, readings, np.array(is_base), np.array(g_true), hours


def test_linear_drift_recovered_exactly():
    """Deriva lineal 0.05 mGal/h → 'linear' la recupera exacta (<1e-9)."""
    times, readings, is_base, g_true, _ = _survey(lambda h: 0.05 * h)
    res = correct_drift(times, readings, is_base, method="linear")
    np.testing.assert_allclose(res.corrected_mgal, g_true, atol=1e-9)
    np.testing.assert_almost_equal(res.drift_rate_mgal_per_day, 0.05 * 24, 6)
    assert res.n_base_occupations == 3
    # Cierre total = deriva acumulada entre primer (t=0) y último (t=7.5 h)
    # paso por base: 0.05 mGal/h × 7.5 h = 0.375 mGal.
    assert abs(res.closure_mgal - 0.05 * 7.5) < 1e-9


def test_piecewise_exact_at_closures_and_better_for_nonlinear():
    """Deriva cuadrática: 'piecewise' clava las bases y supera a 'linear'."""
    quad = lambda h: 0.02 * h + 0.01 * h * h  # noqa: E731
    times, readings, is_base, g_true, hours = _survey(quad)
    lin = correct_drift(times, readings, is_base, method="linear")
    pw = correct_drift(times, readings, is_base, method="piecewise")
    # En cada ocupación de base, piecewise devuelve la lectura de la 1ª base.
    base_vals = pw.corrected_mgal[is_base]
    np.testing.assert_allclose(base_vals, base_vals[0], atol=1e-9)
    err_lin = np.abs(lin.corrected_mgal[~is_base] - g_true[~is_base]).max()
    err_pw = np.abs(pw.corrected_mgal[~is_base] - g_true[~is_base]).max()
    assert err_pw < err_lin, (err_pw, err_lin)


def test_high_rate_warns_units_suspicion():
    times, readings, is_base, _, _ = _survey(lambda h: 1.0 * h)  # 24 mGal/día!
    res = correct_drift(times, readings, is_base, method="linear")
    assert any("inusualmente alta" in w for w in res.warnings)


def test_out_of_window_extrapolation_warns():
    times, readings, is_base, _, _ = _survey(lambda h: 0.05 * h)
    # Última lectura DESPUÉS del último cierre de base.
    times.append(times[-1] + timedelta(hours=2))
    readings = np.append(readings, 5.0)
    is_base = np.append(is_base, False)
    res = correct_drift(times, readings, is_base, method="piecewise")
    assert any("fuera de la ventana" in w for w in res.warnings)


def test_guardrails_clear_errors():
    times, readings, is_base, _, _ = _survey(lambda h: 0.0)
    with pytest.raises(DriftInputError, match="≥2 ocupaciones"):
        correct_drift(times, readings, np.zeros_like(is_base), method="linear")
    with pytest.raises(DriftInputError, match="no son crecientes"):
        correct_drift(list(reversed(times)), readings, is_base)
    with pytest.raises(DriftInputError, match="Todas las filas"):
        correct_drift(times, readings, np.ones_like(is_base))
    with pytest.raises(DriftInputError, match="desconocido"):
        correct_drift(times, readings, is_base, method="spline")


def test_suggest_base_station():
    sids = ["BASE", "S1", "S2", "BASE", "S3", "BASE", "S1"]
    best = suggest_base_station(sids)
    assert best == ("BASE", 3)
    assert suggest_base_station(["A", "B", "C"]) is None
