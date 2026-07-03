"""
B1 — best_target honesto: degradar el artefacto null-space del piso de malla.
=============================================================================

Verifica que build_best_target:
  1. NO presenta como blanco el cuerpo bound-saturado en el piso (null-space); lo degrada
     y surfacea en su lugar el cuerpo de BAJA densidad a profundidad RESOLUBLE.
  2. Caso limpio (sin saturación de piso) → sin democión, elige la anomalía dominante.
  3. Caso degenerado (todo satura en el piso) → marca is_null_space_artifact + confianza LOW.
  4. Guardrail: sin bounds → no se detecta saturación de piso.

Reproduce el patrón de Laguna del Maule: objetivo de baja densidad + blob espurio de alta
densidad saturado a density_max en el fondo de malla.
"""
from __future__ import annotations

import polars as pl

from services.geophysics_service import build_best_target

BLOCK = 100.0
DMIN, DMAX = 2.0, 5.5
FLOOR_Y = 900.0   # piso de malla

# Fondo homogéneo (densidad 2.6) lejos de los cuerpos: (x, y, z, density)
_BG = [
    (100, 100, 800, 2.6), (800, 100, 100, 2.6), (800, 300, 800, 2.6),
    (100, 500, 100, 2.6), (700, 700, 700, 2.6), (300, 100, 300, 2.6),
]


def _grid(extra_rows):
    """Campo de fondo homogéneo (densidad 2.6) + filas extra (cuerpos/artefactos)."""
    rows = list(_BG)
    rows.extend(extra_rows)
    return pl.DataFrame(
        {
            "x": [float(r[0]) for r in rows],
            "y": [float(r[1]) for r in rows],
            "z": [float(r[2]) for r in rows],
            "density": [float(r[3]) for r in rows],
            "probability": [1.0 for _ in rows],
            "grade": [0.0 for _ in rows],
        }
    )


def test_floor_saturated_artifact_is_demoted_low_density_body_surfaces():
    # Cuerpo REAL de baja densidad a profundidad resoluble + artefacto saturado en el piso.
    df = _grid([
        (500, 300, 500, 2.1),       # cuerpo de baja densidad RESOLUBLE (y=300 << piso)
        (200, FLOOR_Y, 200, 5.5),   # artefacto: saturado a DMAX, en el piso
        (250, FLOOR_Y, 250, 5.5),   # segundo artefacto de piso
    ])
    bt = build_best_target(
        df, technical_summary={"overall_level": "GOOD"},
        density_min=DMIN, density_max=DMAX, block_size=BLOCK, cutoff_density=3.0,
    )
    assert bt is not None
    # El blanco surfaceado es el cuerpo RESOLUBLE, NO el piso saturado.
    assert bt["x_m"] == 500.0 and bt["y_m"] == 300.0 and bt["z_m"] == 500.0
    assert abs(bt["density"] - 2.1) < 1e-9
    assert bt["is_null_space_artifact"] is False
    assert bt["is_resolvable_depth"] is True
    # El artefacto del piso fue detectado y degradado con transparencia.
    assert bt["n_floor_saturated_cells"] >= 2
    assert bt["floor_saturated_demoted"] is not None
    assert bt["floor_saturated_demoted"]["y_m"] == FLOOR_Y
    assert "bound_saturated_floor" in bt["floor_saturated_demoted"]["reason"]
    # NUNCA se sella HIGH un blanco contaminado por el artefacto del piso... salvo que el
    # blanco surfaceado sea legítimo: aquí lo es (resoluble) → la confianza de survey se honra.
    assert bt["confidence_level"] == "HIGH"


def test_clean_case_no_floor_saturation_picks_dominant_anomaly():
    # Sólo un cuerpo de alta densidad NO saturado (4.5 < DMAX) a media profundidad.
    df = _grid([(600, 400, 600, 4.5)])
    bt = build_best_target(
        df, technical_summary={"overall_level": "MEDIUM"},
        density_min=DMIN, density_max=DMAX, block_size=BLOCK, cutoff_density=3.0,
    )
    assert bt is not None
    assert bt["x_m"] == 600.0 and bt["y_m"] == 400.0
    assert abs(bt["density"] - 4.5) < 1e-9
    assert bt["is_null_space_artifact"] is False
    assert bt["n_floor_saturated_cells"] == 0
    assert bt["floor_saturated_demoted"] is None
    assert bt["confidence_level"] == "MEDIUM"


def test_degenerate_all_floor_saturated_flags_artifact_and_low_confidence():
    # Patológico REAL: TODAS las celdas activas están saturadas Y en el piso (sin fondo
    # resoluble). No hay blanco fiable → is_null_space_artifact + confianza LOW pese a GOOD.
    df = pl.DataFrame({
        "x": [200.0, 250.0, 300.0],
        "y": [FLOOR_Y, FLOOR_Y, FLOOR_Y],
        "z": [200.0, 250.0, 300.0],
        "density": [5.5, 5.5, 5.5],
        "probability": [1.0, 1.0, 1.0],
        "grade": [0.0, 0.0, 0.0],
    })
    bt = build_best_target(
        df, technical_summary={"overall_level": "GOOD"},   # survey "bueno" pero...
        density_min=DMIN, density_max=DMAX, block_size=BLOCK, cutoff_density=3.0,
    )
    assert bt is not None
    assert bt["is_null_space_artifact"] is True
    assert bt["confidence_level"] == "LOW"          # JAMÁS HIGH si el blanco es null-space
    assert bt["n_floor_saturated_cells"] == 3
    assert "ADVERTENCIA" in bt["selection_note"]


def test_guardrail_no_bounds_no_floor_detection():
    df = _grid([
        (500, 300, 500, 2.1),
        (200, FLOOR_Y, 200, 5.5),
    ])
    # Sin density_min/max/block_size → no se detecta saturación de piso.
    bt = build_best_target(df, technical_summary={"overall_level": "GOOD"})
    assert bt is not None
    assert bt["n_floor_saturated_cells"] == 0
    assert bt["floor_saturated_demoted"] is None
    # Sin democión, el de mayor |anomalía| es el blob 5.5 (no excluido).
    assert abs(bt["density"] - 5.5) < 1e-9


def test_sensitivity_weighting_prefers_resolvable_body_over_deep_high_anomaly():
    # Patrón LdM: cuerpo profundo de ALTA anomalía pero MAL constreñido (sens~0) vs
    # cuerpo somero de MENOR anomalía pero BIEN constreñido (sens alto). El targeting
    # ponderado por resolubilidad debe elegir el somero data-constreñido.
    df = pl.DataFrame({
        "x": [200.0, 500.0] + [c[0] for c in _BG],
        "y": [800.0, 300.0] + [float(c[1]) for c in _BG],
        "z": [200.0, 500.0] + [c[2] for c in _BG],
        "density": [4.9, 2.2] + [c[3] for c in _BG],        # profundo alta vs somero baja
        "probability": [1.0, 1.0] + [1.0 for _ in _BG],
        "grade": [0.0, 0.0] + [0.0 for _ in _BG],
        "sensitivity_proxy": [0.03, 0.85] + [0.3 for _ in _BG],  # profundo mal sensado
    })
    bt = build_best_target(
        df, technical_summary={"overall_level": "GOOD"},
        density_min=DMIN, density_max=DMAX, block_size=BLOCK, cutoff_density=3.0,
    )
    assert bt is not None
    # Elige el cuerpo SOMERO data-constreñido (no el profundo de alta anomalía/baja sens).
    assert bt["y_m"] == 300.0 and abs(bt["density"] - 2.2) < 1e-9


def test_high_density_body_saturating_bound_at_resolvable_depth_is_kept():
    # Depósito denso REAL que satura density_max pero a profundidad RESOLUBLE (no en el
    # piso) y bien sensado → es un blanco legítimo (valor clampeado, pero hay masa densa
    # ahí). B1 sólo degrada lo saturado EN EL PISO; esto NO se degrada.
    df = pl.DataFrame({
        "x": [600.0] + [c[0] for c in _BG],
        "y": [300.0] + [float(c[1]) for c in _BG],     # somero/resoluble, NO piso
        "z": [600.0] + [c[2] for c in _BG],
        "density": [DMAX] + [c[3] for c in _BG],        # satura el bound superior
        "probability": [1.0] + [1.0 for _ in _BG],
        "grade": [0.0] + [0.0 for _ in _BG],
        "sensitivity_proxy": [0.9] + [0.3 for _ in _BG],  # bien constreñido
    })
    bt = build_best_target(
        df, technical_summary={"overall_level": "GOOD"},
        density_min=DMIN, density_max=DMAX, block_size=BLOCK, cutoff_density=3.0,
    )
    assert bt is not None
    assert bt["x_m"] == 600.0 and bt["y_m"] == 300.0
    assert abs(bt["density"] - DMAX) < 1e-9
    assert bt["is_null_space_artifact"] is False
    assert bt["n_floor_saturated_cells"] == 0       # no está en el piso → no es artefacto
    assert bt["floor_saturated_demoted"] is None
    assert bt["confidence_level"] == "HIGH"


def test_empty_returns_none():
    assert build_best_target(pl.DataFrame({"x": [], "y": [], "z": [], "density": [],
                                           "probability": [], "grade": []})) is None
    assert build_best_target(None) is None
