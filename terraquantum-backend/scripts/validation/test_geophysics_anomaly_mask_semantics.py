"""
Fase 6 — Test semántico: anomaly mask no depende de `grade`.

Verifica que build_anomaly_dataframe selecciona vóxeles por `density` y
`visual_score`, nunca por `grade`.
"""
import polars as pl
import pytest

from services.geophysics_service import build_anomaly_dataframe

CUTOFF_DENSITY = 2.75


def _df():
    return pl.DataFrame({
        "x":            [100.0, 200.0, 300.0, 400.0, 500.0],
        "y":            [50.0,  50.0,  50.0,  50.0,  50.0],
        "z":            [100.0, 200.0, 300.0, 400.0, 500.0],
        "ix":           [0, 1, 2, 3, 4],
        "iy":           [0, 0, 0, 0, 0],
        "iz":           [0, 1, 2, 3, 4],
        "density":      [2.60, 3.10, 2.60, 2.60, 3.00],
        "rho":          [2.60, 3.10, 2.60, 2.60, 3.00],
        "probability":  [0.20, 0.80, 0.90, 0.10, 0.85],
        "visual_score": [0.05, 0.30, 0.50, 0.02, 0.40],
        "grade":        [1.80, 0.10, 0.10, 0.05, 2.50],
        "tonnage":      [100.0, 100.0, 100.0, 100.0, 100.0],
        "domain":       [0, 1, 1, 0, 1],
        "resource_class": [3, 1, 1, 3, 1],
    })


def _selected_ixs():
    return set(build_anomaly_dataframe(_df(), CUTOFF_DENSITY)["ix"].to_list())


@pytest.mark.unit
def test_grade_high_density_low_not_selected():
    """Caso A (ix=0): grade alto pero density y visual_score bajos → NO entra."""
    assert 0 not in _selected_ixs()


@pytest.mark.unit
def test_density_high_is_selected():
    """Caso B (ix=1): density alta (3.10 > 2.75) → SÍ entra."""
    assert 1 in _selected_ixs()


@pytest.mark.unit
def test_visual_score_high_is_selected():
    """Caso C (ix=2): visual_score alto (0.50) → SÍ entra aunque density baja."""
    assert 2 in _selected_ixs()


@pytest.mark.unit
def test_all_low_not_selected():
    """Caso D (ix=3): density, visual_score y grade bajos → NO entra."""
    assert 3 not in _selected_ixs()


@pytest.mark.unit
def test_density_and_visual_score_both_high_selected():
    """Caso E (ix=4): density alta Y visual_score alto → SÍ entra."""
    assert 4 in _selected_ixs()


@pytest.mark.unit
def test_grade_does_not_drive_selection():
    """grade alto en ix=0 NO lo incluye; grade bajo en ix=1 NO lo excluye."""
    selected = _selected_ixs()
    assert 0 not in selected, "ix=0 (grade=1.80, density baja) NO debe entrar"
    assert 1 in selected,     "ix=1 (grade=0.10, density alta) SÍ debe entrar"
