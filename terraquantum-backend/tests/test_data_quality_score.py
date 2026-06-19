"""
Tests Fase 19 Tarea 5 — Data Quality Score (0–100).

Verifica compute_data_quality_score y su integración en analyze_csv_observations:
  - pesos suman 1.0
  - score acotado [0,100] e interpretación válida
  - componentes derivados correctamente (spatial via convex hull, noise, resolution,
    outliers, completeness con columnas profesionales)
  - casos degenerados (colineal, vacío) no rompen
"""
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from schemas.geophysics_schema import GravityObservation
from services.csv_analysis_service import (
    analyze_csv_observations,
    compute_data_quality_score,
    DATA_QUALITY_WEIGHTS,
    _convex_hull_area,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grid(n_side, span=1000.0, g_base=10.0, g_amp=5.0):
    """Grilla n_side x n_side en el plano (x, z) con variación suave de gravedad."""
    obs = []
    for i in range(n_side):
        for j in range(n_side):
            x = span * i / (n_side - 1)
            z = span * j / (n_side - 1)
            g = g_base + g_amp * math.sin(i * 0.7) * math.cos(j * 0.5)
            obs.append(GravityObservation(x_m=x, y_m=0.0, z_m=z, g=g))
    return obs


# ---------------------------------------------------------------------------
# 1. Pesos e invariantes
# ---------------------------------------------------------------------------

def test_weights_sum_to_one():
    assert abs(sum(DATA_QUALITY_WEIGHTS.values()) - 1.0) < 1e-9


def test_data_quality_attached_and_bounded():
    res = analyze_csv_observations(_grid(6), "mGal")
    dq = res.data_quality
    assert dq is not None
    assert 0.0 <= dq.score <= 100.0
    assert dq.interpretation in {"GOOD", "MEDIOCRE", "POOR"}
    for component in (
        dq.completeness,
        dq.spatial_distribution,
        dq.noise_level,
        dq.resolution,
        dq.outlier_fraction,
    ):
        assert 0.0 <= component <= 100.0
    assert dq.weights == DATA_QUALITY_WEIGHTS
    assert dq.notes  # explicaciones presentes


# ---------------------------------------------------------------------------
# 2. Convex hull (componente espacial)
# ---------------------------------------------------------------------------

def test_convex_hull_area_square():
    pts = [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)]
    assert abs(_convex_hull_area(pts) - 1.0) < 1e-9


def test_convex_hull_collinear_zero():
    assert _convex_hull_area([(0, 0), (1, 1), (2, 2)]) == 0.0


def test_spatial_collinear_diagonal_zero():
    """Línea diagonal: bbox > 0 pero hull = 0 → spatial_distribution = 0."""
    obs = [
        GravityObservation(x_m=float(i * 100), y_m=0.0, z_m=float(i * 100), g=10.0 + 0.1 * i)
        for i in range(20)
    ]
    dq = analyze_csv_observations(obs, "mGal").data_quality
    assert dq.spatial_distribution == 0.0


def test_spatial_grid_high_coverage():
    dq = analyze_csv_observations(_grid(8), "mGal").data_quality
    # Una grilla completa llena su bounding box → cobertura cercana al 100%.
    assert dq.spatial_distribution > 90.0


# ---------------------------------------------------------------------------
# 3. Ruido y outliers
# ---------------------------------------------------------------------------

def test_outlier_reduces_score():
    dq_clean = analyze_csv_observations(_grid(6), "mGal").data_quality
    noisy = _grid(6)
    noisy[0] = GravityObservation(x_m=noisy[0].x_m, y_m=0.0, z_m=noisy[0].z_m, g=10000.0)
    dq_noisy = analyze_csv_observations(noisy, "mGal").data_quality
    assert dq_noisy.outlier_fraction < dq_clean.outlier_fraction
    assert dq_noisy.noise_level < dq_clean.noise_level


# ---------------------------------------------------------------------------
# 4. Resolución
# ---------------------------------------------------------------------------

def test_resolution_fine_beats_coarse():
    fine = analyze_csv_observations(_grid(10, span=500.0), "mGal").data_quality
    coarse = analyze_csv_observations(_grid(5, span=10000.0), "mGal").data_quality
    assert fine.resolution > coarse.resolution


# ---------------------------------------------------------------------------
# 5. Completeness con columnas profesionales
# ---------------------------------------------------------------------------

def test_completeness_with_professional_columns():
    obs = _grid(6)
    base = analyze_csv_observations(obs, "mGal").data_quality
    cols = ["x_m", "z_m", "g", "elev_m", "sigma_mgal"]
    pcv = {
        "elev_m": [100.0] * len(obs),
        "sigma_mgal": [0.01] * len(obs),
    }
    enriched = analyze_csv_observations(
        obs, "mGal", column_names=cols, professional_column_values=pcv
    ).data_quality
    assert enriched.completeness > base.completeness
    assert enriched.completeness == 100.0


# ---------------------------------------------------------------------------
# 6. Interpretación y casos degenerados
# ---------------------------------------------------------------------------

def test_good_interpretation_high_quality():
    obs = _grid(10, span=600.0)
    cols = ["x_m", "z_m", "g", "elev_m", "sigma_mgal"]
    pcv = {
        "elev_m": [100.0] * len(obs),
        "sigma_mgal": [0.01] * len(obs),
    }
    dq = analyze_csv_observations(
        obs, "mGal", column_names=cols, professional_column_values=pcv
    ).data_quality
    assert dq.score >= 75.0
    assert dq.interpretation == "GOOD"


def test_empty_observations_low_score():
    dq = analyze_csv_observations([], "mGal").data_quality
    assert dq is not None
    assert dq.interpretation == "POOR"
    assert 0.0 <= dq.score <= 100.0
