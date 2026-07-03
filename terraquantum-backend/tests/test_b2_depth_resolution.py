"""
B2 — resolución de profundidad POR-EJE (depthResolution).
=========================================================

Verifica build_depth_resolution:
  1. Cuerpo somero compacto bien sensado → vertical 'resolved' + deep_mass_fraction bajo +
     horizontal determinado + compactness 'compact'.
  2. Masa apilada profunda mal sensada → vertical 'null_space_dominated' + deep_frac alto;
     el horizonte DOI (sensibilidad half-max) cae somero (NO el cutoff geométrico).
  3. df vacío/plano → computed=False, sin crash.
  4. Sin columna de sensibilidad → fallback geométrico (horizon = observable_depth_max).
  5. Semántica (b): el eje horizontal es FORTALEZA (determined + compactness), NUNCA
     'quality/poor'; 'broad'/'diffuse' describe el ancho geológico, no una falla.
  6. El bloque aparece en report_payload de una corrida real (integración).
"""
from __future__ import annotations

import numpy as np
import polars as pl

from services.geophysics_service import build_depth_resolution

BLOCK = 200.0


def _df(cells):
    """cells = lista de (x, y, z, density, sensitivity_proxy)."""
    return pl.DataFrame({
        "x": [float(c[0]) for c in cells],
        "y": [float(c[1]) for c in cells],
        "z": [float(c[2]) for c in cells],
        "density": [float(c[3]) for c in cells],
        "sensitivity_proxy": [float(c[4]) for c in cells],
        "probability": [1.0 for _ in cells],
        "grade": [0.0 for _ in cells],
    })


def _bg(y, sens, n=4):
    """Celdas de fondo (densidad 2.6) dispersas en una capa, con sensibilidad dada."""
    return [(1000 + 600 * i, y, 200, 2.6, sens) for i in range(n)]


def test_shallow_compact_body_is_resolved_and_compact():
    cells = []
    # Capas someras bien sensadas, fondo plano salvo un cuerpo compacto en y=300.
    cells += _bg(100, 1.0)
    cells += [(1000, 300, 1000, 4.0, 1.0), (1000, 300, 1000 + 1e-3, 4.0, 1.0)]  # compacto
    cells += _bg(300, 1.0)
    cells += _bg(500, 0.8)
    cells += _bg(700, 0.2)     # profundo, fondo (sin anomalía)
    cells += _bg(900, 0.05)
    dr = build_depth_resolution(_df(cells), observable_depth_max_m=900.0,
                                best_target={"depth_m": 300.0, "is_resolvable_depth": True},
                                block_size=BLOCK)
    assert dr["computed"] is True
    assert dr["per_axis"]["vertical"]["quality"] == "resolved"
    assert dr["deep_mass_fraction"] < 0.33
    assert dr["per_axis"]["horizontal"]["determined"] is True
    assert dr["per_axis"]["horizontal"]["compactness"] == "compact"
    # Semántica (b): NUNCA 'quality' en horizontal.
    assert "quality" not in dr["per_axis"]["horizontal"]


def test_deep_pile_low_sensitivity_is_null_space_dominated():
    cells = []
    # Someras bien sensadas pero SIN anomalía; masa apilada en profundidad con sens baja.
    cells += _bg(100, 1.0)
    cells += _bg(300, 0.9)
    cells += _bg(500, 0.35)
    cells += [(1000, 700, 1000, 4.5, 0.10), (1600, 700, 1000, 4.5, 0.10)]   # pila profunda
    cells += [(1000, 900, 1000, 4.8, 0.04), (1600, 900, 1000, 4.8, 0.04)]
    dr = build_depth_resolution(_df(cells), observable_depth_max_m=5000.0,  # cutoff geom. profundo
                                best_target=None, block_size=BLOCK)
    assert dr["computed"] is True
    assert dr["per_axis"]["vertical"]["quality"] == "null_space_dominated"
    assert dr["deep_mass_fraction"] >= 0.66
    # El horizonte DOI (sensibilidad) es MUCHO más somero que el cutoff geométrico (5000).
    assert dr["resolvable_depth_horizon_method"] == "sensitivity_doi_half_max_layer"
    assert dr["resolvable_depth_max_m"] < 700.0
    assert dr["geometric_observable_depth_max_m"] == 5000.0


def test_empty_or_flat_field_computed_false_no_crash():
    empty = pl.DataFrame({"x": [], "y": [], "z": [], "density": [],
                          "sensitivity_proxy": [], "probability": [], "grade": []})
    dr = build_depth_resolution(empty, 1000.0, None, BLOCK)
    assert dr["computed"] is False
    # Campo plano (sin anomalía) → computed False, sin crash.
    flat = _df(_bg(100, 1.0) + _bg(300, 0.9))
    dr2 = build_depth_resolution(flat, 1000.0, None, BLOCK)
    assert dr2["computed"] is False


def test_no_sensitivity_column_uses_geometric_fallback():
    df = pl.DataFrame({
        "x": [1000.0, 1600.0], "y": [300.0, 700.0], "z": [1000.0, 1000.0],
        "density": [4.0, 2.6], "probability": [1.0, 1.0], "grade": [0.0, 0.0],
    })
    dr = build_depth_resolution(df, observable_depth_max_m=800.0, best_target=None,
                                block_size=BLOCK)
    assert dr["computed"] is True
    assert dr["resolvable_depth_horizon_method"] == "geometric_cutoff_fallback"
    assert dr["resolvable_depth_max_m"] == 800.0


def test_method_label_states_no_posterior():
    dr = build_depth_resolution(_df(_bg(100, 1.0) + [(1000, 300, 1000, 4.0, 1.0)]),
                                900.0, None, BLOCK)
    assert dr["method"] == "model_derived_depth_resolution_no_posterior"


def test_depth_resolution_present_in_report_payload():
    # Integración: el bloque aparece en una corrida real por producción.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import scripts.validation.tanda_a_part1b_shallow_vs_smear as B
    from services.geophysics_service import run_geophysics_inversion
    out = run_geophysics_inversion(B._build_ldm_input(
        lambda_mag=0.0, auto_lambda=True, density_min=0.0, density_max=5.5, tag="b2test"))
    dr = out["report"]["depthResolution"]
    assert dr["computed"] is True
    assert "per_axis" in dr and "horizontal" in dr["per_axis"] and "vertical" in dr["per_axis"]
    assert "compactness" in dr["per_axis"]["horizontal"]
    assert "quality" not in dr["per_axis"]["horizontal"]
    # LdM: cola null-space alta medida.
    assert dr["per_axis"]["vertical"]["quality"] == "null_space_dominated"
    assert dr["deep_mass_fraction"] >= 0.66
