"""
B2 — resolución de profundidad POR-EJE (depthResolution).
=========================================================

Verifica build_depth_resolution:
  1. Cuerpo somero compacto bien sensado → vertical 'resolved' + deep_mass_fraction bajo +
     horizontal determinado + compactness 'compact'.
  2. Masa apilada profunda mal sensada (SIN doi) → 'null_space_dominated'; el horizonte de
     sensibilidad half-max (FALLBACK) cae somero (NO el cutoff geométrico).
  3. df vacío/plano → computed=False, sin crash.
  4. Sin columna de sensibilidad → fallback geométrico (horizon = observable_depth_max).
  5. Semántica (b): el eje horizontal es FORTALEZA (determined + compactness), NUNCA
     'quality/poor'; 'broad'/'diffuse' describe el ancho geológico, no una falla.
  6. El bloque aparece en report_payload de una corrida real (integración).

F5/B2 — HORIZONTE DOI RECALIBRADO (2026-07): el horizonte PRIMARIO usa el índice DOI de
doble inversión (doi_index/doi_raw, Oldenburg & Li 1999), que mide la resolubilidad del
modelo RECUPERADO (post depth-weighting), NO la sensibilidad CRUDA pre-Wz. Medido: con
sensibilidad cruda, deep_mass_fraction≈0.92-0.98 SIEMPRE (sano o patológico, sin
discriminar); con el horizonte DOI (umbral absoluto 1.0), sólo el smear patológico (LdM
0.75) es null_space y los sanos (DO-27 0.43, San Nicolás 0.40) caen en 'poor'. La
sensibilidad half-max queda como FALLBACK cuando no hay doi. Ver
scripts/validation/f5_b2_doi_calibration.py para los números medidos.
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


def _df_doi(cells):
    """cells = lista de (x, y, z, density, sensitivity_proxy, doi_index)."""
    return pl.DataFrame({
        "x": [float(c[0]) for c in cells],
        "y": [float(c[1]) for c in cells],
        "z": [float(c[2]) for c in cells],
        "density": [float(c[3]) for c in cells],
        "sensitivity_proxy": [float(c[4]) for c in cells],
        "doi_index": [float(c[5]) for c in cells],
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
    # LdM: cola null-space alta medida (horizonte DOI recalibrado: deep_frac≈0.75).
    assert dr["per_axis"]["vertical"]["quality"] == "null_space_dominated"
    assert dr["deep_mass_fraction"] >= 0.66
    # F5/B2: en producción el horizonte lo fija el índice DOI (no la sensibilidad cruda).
    assert dr["resolvable_depth_horizon_method"] == "doi_double_inversion_horizon"


# ─────────────────────────────────────────────────────────────────────────────
# F5/B2 — Horizonte DOI recalibrado (Oldenburg & Li 1999, doble inversión).
# El horizonte PRIMARIO ahora usa doi_index (resolubilidad del modelo RECUPERADO,
# post depth-weighting), NO la sensibilidad cruda pre-Wz (que daba deep_mass_fraction
# ≈0.94 SIEMPRE, sano o patológico). Umbral null-space DOI = 1.0 (absoluto).
# ─────────────────────────────────────────────────────────────────────────────

def _bg_doi(y, sens, doi, n=6):
    """Capa de fondo (densidad 2.6) dominante → median = 2.6 (fondo robusto)."""
    return [(1000 + 400 * i, y, 200, 2.6, sens, doi) for i in range(n)]


def test_doi_horizon_preferred_when_present_and_flags_deep_smear():
    # Cuerpo somero BIEN resuelto (DOI bajo) + smear profundo mal resuelto (DOI alto).
    # La sensibilidad cruda es alta en el somero y decae — pero el DISCRIMINADOR es el DOI.
    cells = []
    cells += _bg_doi(100, 1.0, 0.2)
    cells += _bg_doi(200, 1.0, 0.2) + [(1000, 200, 900, 4.0, 1.0, 0.2),
                                       (1400, 200, 900, 4.0, 1.0, 0.2)]  # somero resuelto
    cells += _bg_doi(400, 0.7, 0.3)                                       # fondo resuelto (sin masa)
    cells += _bg_doi(1000, 0.2, 2.6) + [(1000, 1000, 900, 4.6, 0.2, 2.6),
                                        (1400, 1000, 900, 4.6, 0.2, 2.6),
                                        (1800, 1000, 900, 4.6, 0.2, 2.6)]  # smear DOI alto
    cells += _bg_doi(1200, 0.1, 3.1) + [(1000, 1200, 900, 4.9, 0.1, 3.1),
                                        (1400, 1200, 900, 4.9, 0.1, 3.1),
                                        (1800, 1200, 900, 4.9, 0.1, 3.1)]  # smear DOI alto
    dr = build_depth_resolution(_df_doi(cells), observable_depth_max_m=5000.0,
                                best_target=None, block_size=BLOCK)
    assert dr["computed"] is True
    # El horizonte lo fija el DOI, no la sensibilidad ni el cutoff geométrico (5000).
    assert dr["resolvable_depth_horizon_method"] == "doi_double_inversion_horizon"
    # Horizonte ~200 m (última capa material con DOI≤1), MUY por encima del smear profundo.
    assert dr["resolvable_depth_max_m"] <= 400.0
    assert dr["per_axis"]["vertical"]["quality"] == "null_space_dominated"
    assert dr["deep_mass_fraction"] >= 0.66
    assert dr["per_axis"]["vertical"]["doi_cutoff"] == 1.0


def test_doi_horizon_shallow_body_resolved_ignores_empty_base_layers():
    # Toda la masa somera con DOI bajo; capas profundas = fondo vacío con DOI≈0 trivial.
    # La restricción "material" (masa ≥1% del pico) impide que esas capas base extiendan
    # el horizonte artificialmente → deep_mass_fraction ≈ 0 → 'resolved'.
    cells = []
    cells += _bg_doi(200, 1.0, 0.2) + [(1000, 200, 900, 4.0, 1.0, 0.2),
                                       (1400, 200, 900, 4.0, 1.0, 0.25)]  # cuerpo somero
    cells += _bg_doi(400, 0.7, 0.4) + [(1000, 400, 900, 3.6, 0.7, 0.4),
                                       (1400, 400, 900, 3.6, 0.7, 0.4)]   # cuerpo somero
    cells += _bg_doi(1000, 0.05, 0.0)                                      # base vacía (DOI 0 trivial)
    cells += _bg_doi(1400, 0.02, 0.0)                                      # base vacía (DOI 0 trivial)
    dr = build_depth_resolution(_df_doi(cells), observable_depth_max_m=2000.0,
                                best_target=None, block_size=BLOCK)
    assert dr["resolvable_depth_horizon_method"] == "doi_double_inversion_horizon"
    # El horizonte NO baja hasta las capas base vacías (1000/1400): se queda en la masa (400).
    assert dr["resolvable_depth_max_m"] <= 400.0
    assert dr["per_axis"]["vertical"]["quality"] == "resolved"
    assert dr["deep_mass_fraction"] < 0.33


def test_san_nicolas_healthy_case_no_longer_null_space():
    """EMPÍRICO: San Nicolás (SANO, geometría aprobada) re-derivado del block model
    persistido → con el horizonte DOI recalibrado deja de ser 'null_space_dominated'
    (antes 0.975; ahora ~0.40 → 'poor'). Prueba que el 0.94 universal era artefacto."""
    import os
    parq = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "projects", "val_san_nicolas", "runs", "a407c45e6d", "block_model.parquet",
    )
    if not os.path.exists(parq):
        import pytest
        pytest.skip("corrida persistida de San Nicolás no disponible en este entorno")
    df = pl.read_parquet(parq)
    dr = build_depth_resolution(df, observable_depth_max_m=1000.0, best_target=None,
                                block_size=50.0)
    assert dr["computed"] is True
    assert dr["resolvable_depth_horizon_method"] == "doi_double_inversion_horizon"
    # Caso SANO: NO debe ser null_space_dominated (el discriminante quedó restaurado).
    assert dr["per_axis"]["vertical"]["quality"] != "null_space_dominated"
    assert dr["deep_mass_fraction"] < 0.66
