"""F2B — Marea terrestre Longman 1959 (earth_tide_service).

Oráculo primario: el valor de test PUBLICADO de la implementación de
referencia MIT LongmanTide (J. Leeman) — coincidencia exigida a 1e-8 mGal.
Además: cotas físicas (|marea| < 0.4 mGal), periodicidad semidiurna (~12.4 h
M2) y contrato del parser de timestamps (todo-o-nada).
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.earth_tide_service import (  # noqa: E402
    parse_survey_timestamps,
    solve_longman_tide,
    tide_series_mgal,
)


# ── 1. Oráculo publicado (LongmanTide test_basic) ────────────────────────────
def test_reference_values_leeman_2015():
    """lat 40.7914, lon 282.1414 E, alt 370 m, 2015-04-23T00:00Z."""
    gm, gs, g = solve_longman_tide(40.7914, 282.1414, 370.0, datetime(2015, 4, 23))
    np.testing.assert_almost_equal(gm, 0.0324029651226, 8)
    np.testing.assert_almost_equal(gs, -0.0288682178454, 8)
    np.testing.assert_almost_equal(g, 0.00353474727722, 8)


def test_longitude_convention_east_positive():
    """282.1414°E ≡ −77.8586°E (misma física, dos notaciones estándar)."""
    g1 = solve_longman_tide(40.7914, 282.1414, 370.0, datetime(2015, 4, 23))[2]
    g2 = solve_longman_tide(40.7914, -77.8586, 370.0, datetime(2015, 4, 23))[2]
    np.testing.assert_almost_equal(g1, g2, 10)


# ── 2. Física: amplitud y periodicidad ───────────────────────────────────────
def test_amplitude_within_physical_bounds():
    """3 días en Laguna del Maule: la marea total jamás excede ±0.4 mGal."""
    times = [datetime(2012, 3, 1) + timedelta(minutes=30 * i) for i in range(144)]
    series = tide_series_mgal(-36.06, -70.50, 2200.0, times)
    assert np.all(np.abs(series) < 0.4), float(np.abs(series).max())
    assert np.abs(series).max() > 0.02, "una marea siempre ~0 sería sospechosa"


def test_semidiurnal_periodicity():
    """Los máximos locales dominantes se separan ~12.4 h (constituyente M2)."""
    times = [datetime(2012, 3, 1) + timedelta(minutes=10 * i) for i in range(432)]
    series = tide_series_mgal(-36.06, -70.50, 2200.0, times)
    peaks = [
        i for i in range(1, len(series) - 1)
        if series[i] > series[i - 1] and series[i] > series[i + 1]
    ]
    assert len(peaks) >= 4, "3 días deben contener ≥4 máximos de marea"
    gaps_h = np.diff(peaks) * 10.0 / 60.0
    # Mezcla de constituyentes diurnas/semidiurnas: los gaps caen en 8-16 h.
    assert np.all((gaps_h > 8.0) & (gaps_h < 16.0)), gaps_h


def test_series_matches_scalar():
    times = [datetime(2015, 4, 23), datetime(2015, 4, 23, 6)]
    series = tide_series_mgal(40.7914, 282.1414, 370.0, times)
    assert len(series) == 2
    np.testing.assert_almost_equal(
        series[0], solve_longman_tide(40.7914, 282.1414, 370.0, times[0])[2], 12
    )


# ── 3. Parser de timestamps de campo (todo-o-nada) ───────────────────────────
def test_parse_timestamps_common_formats():
    parsed = parse_survey_timestamps([
        "2012-03-01T08:30:00", "2012-03-01 09:15", "2012/03/01 10:00:30",
    ])
    assert parsed is not None and len(parsed) == 3
    assert parsed[0] == datetime(2012, 3, 1, 8, 30)
    assert parsed[2] == datetime(2012, 3, 1, 10, 0, 30)


def test_parse_timestamps_all_or_nothing():
    """Un timestamp ilegible invalida la SERIE completa (jamás corrección a
    medias silenciosa)."""
    assert parse_survey_timestamps(["2012-03-01 08:30", "ayer por la tarde"]) is None
    assert parse_survey_timestamps(["2012-03-01 08:30", ""]) is None
