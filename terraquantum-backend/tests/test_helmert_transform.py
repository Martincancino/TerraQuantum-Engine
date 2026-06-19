"""
Tests Fase 19 Tarea 7 (Caso B) — transformada de similitud (Helmert) 2D.

Verifica solve_similarity_transform / apply_similarity_transform:
  - recuperación exacta de escala/rotación/traslación conocidas
  - confidence HIGH/MEDIUM/LOW según nº de puntos y residual
  - validaciones (puntos insuficientes, coincidentes, longitudes distintas)
  - detección de mezcla de unidades (escala lejos de 1.0)
  - round-trip apply()
"""
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.helmert_transform_service import (
    solve_similarity_transform,
    apply_similarity_transform,
)


def _synth_real(local_points, scale, rotation_deg, t_e, t_n):
    """Genera coords reales aplicando una similitud conocida (ground truth)."""
    theta = math.radians(rotation_deg)
    a = scale * math.cos(theta)
    b = scale * math.sin(theta)
    return [(a * x - b * z + t_e, b * x + a * z + t_n) for (x, z) in local_points]


_LOCAL = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (50.0, 80.0)]


# ---------------------------------------------------------------------------
# Recuperación de parámetros
# ---------------------------------------------------------------------------

def test_pure_translation():
    real = _synth_real(_LOCAL, scale=1.0, rotation_deg=0.0, t_e=345000.0, t_n=6298000.0)
    r = solve_similarity_transform(_LOCAL, real)
    assert r.scale == pytest.approx(1.0, abs=1e-6)
    assert r.rotation_deg == pytest.approx(0.0, abs=1e-6)
    assert r.translation_e == pytest.approx(345000.0, abs=1e-4)
    assert r.translation_n == pytest.approx(6298000.0, abs=1e-4)
    assert r.residual_rms_m == pytest.approx(0.0, abs=1e-6)
    assert r.confidence == "HIGH"


def test_recover_scale_rotation():
    real = _synth_real(_LOCAL, scale=1.5, rotation_deg=30.0, t_e=10000.0, t_n=20000.0)
    r = solve_similarity_transform(_LOCAL, real)
    assert r.scale == pytest.approx(1.5, abs=1e-6)
    assert r.rotation_deg == pytest.approx(30.0, abs=1e-6)
    assert r.residual_rms_m == pytest.approx(0.0, abs=1e-6)
    assert r.confidence == "HIGH"


def test_rotation_90_degrees():
    real = _synth_real(_LOCAL, scale=1.0, rotation_deg=90.0, t_e=0.0, t_n=0.0)
    r = solve_similarity_transform(_LOCAL, real)
    assert r.rotation_deg == pytest.approx(90.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Confidence según nº de puntos / residual
# ---------------------------------------------------------------------------

def test_two_points_medium_confidence():
    local = [(0.0, 0.0), (100.0, 0.0)]
    real = _synth_real(local, scale=1.0, rotation_deg=15.0, t_e=500.0, t_n=900.0)
    r = solve_similarity_transform(local, real)
    assert r.n_control_points == 2
    assert r.confidence == "MEDIUM"
    assert any("redundancia" in w.lower() for w in r.warnings)


def test_three_points_clean_high_confidence():
    local = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0)]
    real = _synth_real(local, scale=1.2, rotation_deg=10.0, t_e=1000.0, t_n=2000.0)
    r = solve_similarity_transform(local, real)
    assert r.confidence == "HIGH"
    assert r.residual_rms_m == pytest.approx(0.0, abs=1e-6)


def test_high_residual_low_confidence():
    real = _synth_real(_LOCAL, scale=1.0, rotation_deg=0.0, t_e=0.0, t_n=0.0)
    # Corromper un punto con un error grande (anclaje inconsistente).
    real[2] = (real[2][0] + 500.0, real[2][1] - 400.0)
    r = solve_similarity_transform(_LOCAL, real)
    assert r.residual_rms_m > 10.0
    assert r.confidence == "LOW"
    assert any("residual" in w.lower() for w in r.warnings)


# ---------------------------------------------------------------------------
# Validaciones
# ---------------------------------------------------------------------------

def test_single_point_raises():
    with pytest.raises(ValueError, match="al menos 2"):
        solve_similarity_transform([(0.0, 0.0)], [(1.0, 1.0)])


def test_mismatched_lengths_raises():
    with pytest.raises(ValueError, match="misma cantidad"):
        solve_similarity_transform([(0.0, 0.0), (1.0, 1.0)], [(1.0, 1.0)])


def test_coincident_local_points_raises():
    with pytest.raises(ValueError, match="coincidentes"):
        solve_similarity_transform(
            [(5.0, 5.0), (5.0, 5.0)], [(1.0, 1.0), (2.0, 2.0)]
        )


# ---------------------------------------------------------------------------
# Mezcla de unidades + round-trip
# ---------------------------------------------------------------------------

def test_unit_mismatch_warning():
    # local en pies, real en metros → escala ~0.3048.
    real = _synth_real(_LOCAL, scale=0.3048, rotation_deg=0.0, t_e=0.0, t_n=0.0)
    r = solve_similarity_transform(_LOCAL, real)
    assert any("escala" in w.lower() and "unidades" in w.lower() for w in r.warnings)


def test_apply_round_trip():
    real = _synth_real(_LOCAL, scale=1.3, rotation_deg=22.0, t_e=345000.0, t_n=6298000.0)
    r = solve_similarity_transform(_LOCAL, real)
    mapped = apply_similarity_transform(r, _LOCAL)
    for (em, nm), (ed, nd) in zip(mapped, real):
        assert em == pytest.approx(ed, abs=1e-3)
        assert nm == pytest.approx(nd, abs=1e-3)
