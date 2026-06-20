"""
FASE 25 — Tests de Validación de Campo (Field Validation).

Cubren el servicio de métricas (services/field_validation_service.py) con grillas
sintéticas DIRECTAS (sin correr la inversión completa → rápidos y deterministas):

  - validate_against_boreholes: MAE / RMSE / %dentro / bias / fuera-de-grilla / aire
  - estimate_depth_error: recupera la profundidad del cuerpo conocido
  - CaseStudy.status y passes_gate (gate 0.3 t/m³ @ 75%)
  - aggregate_case_studies: veredicto GO/NO-GO + confianza predictiva
  - render_case_study_table: formato Markdown del roadmap

El harness end-to-end (con inversión real) vive en
scripts/validation/field_validation_harness.py y no se ejecuta aquí (lento).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from schemas.geophysics_schema import BoreholeInterval
from services.field_validation_service import (
    BoreholeValidationMetrics,
    CaseStudy,
    GATE_MIN_FRACTION,
    GATE_THRESHOLD_T_M3,
    aggregate_case_studies,
    estimate_depth_error,
    estimate_location_error,
    render_case_study_table,
    validate_against_boreholes,
)

# Grilla 4×4×4 con celdas de 30 m (misma convención que el solver / borehole tests).
NX = NY = NZ = 4
BS = 30.0


def _grid_centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return (
        (ix.ravel() + 0.5) * BS,
        (iy.ravel() + 0.5) * BS,
        (iz.ravel() + 0.5) * BS,
    )


def _density_full(value_at, default=2.6):
    x_c, _, _ = _grid_centers()
    dens = np.full(x_c.size, default, dtype=np.float64)
    for idx, val in value_at.items():
        dens[idx] = val
    return dens


# ─────────────────────────────────────────────────────────────────────────
#  validate_against_boreholes
# ─────────────────────────────────────────────────────────────────────────
def test_validate_perfect_agreement():
    x_c, y_c, z_c = _grid_centers()
    # Columna (15,15) → vóxeles {0,4} cubren y∈[0,60]; ambos a 3.0; sondaje mide 3.0.
    dens = _density_full({0: 3.0, 4: 3.0})
    it = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)

    m = validate_against_boreholes([it], dens, x_c, y_c, z_c, BS)
    assert m.n_evaluated == 1 and m.n_total == 1
    assert m.mae_t_m3 == pytest.approx(0.0, abs=1e-9)
    assert m.rmse_t_m3 == pytest.approx(0.0, abs=1e-9)
    assert m.bias_t_m3 == pytest.approx(0.0, abs=1e-9)
    assert m.pct_within[0.2] == pytest.approx(1.0)
    assert m.passes_gate() is True


def test_validate_mae_rmse_known():
    x_c, y_c, z_c = _grid_centers()
    # Dos sondajes en columnas distintas con residuales conocidos: +0.4 y -0.1.
    # Col (15,15)→{0,4}; col (105,15)→ix=3 → idx base 3*16=48 → {48,52}.
    dens = _density_full({0: 3.4, 4: 3.4, 48: 2.9, 52: 2.9})
    it1 = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)   # +0.4
    it2 = BoreholeInterval(x_m=105.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)  # -0.1

    m = validate_against_boreholes([it1, it2], dens, x_c, y_c, z_c, BS)
    assert m.n_evaluated == 2
    assert m.mae_t_m3 == pytest.approx((0.4 + 0.1) / 2)
    assert m.rmse_t_m3 == pytest.approx(np.sqrt((0.16 + 0.01) / 2))
    assert m.bias_t_m3 == pytest.approx((0.4 - 0.1) / 2)
    assert m.max_abs_diff_t_m3 == pytest.approx(0.4)
    # |res|: 0.4 y 0.1 → dentro de 0.2: solo el de 0.1 → 50%; dentro de 0.5: 100%.
    assert m.pct_within[0.2] == pytest.approx(0.5)
    assert m.pct_within[0.5] == pytest.approx(1.0)


def test_validate_out_of_grid_counts_in_total_not_evaluated():
    x_c, y_c, z_c = _grid_centers()
    dens = _density_full({0: 3.0, 4: 3.0})
    inside = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)
    outside = BoreholeInterval(x_m=9999.0, z_m=9999.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)

    m = validate_against_boreholes([inside, outside], dens, x_c, y_c, z_c, BS)
    assert m.n_total == 2
    assert m.n_evaluated == 1
    statuses = {r["status"] for r in m.residuals}
    assert "OUT_OF_GRID" in statuses


def test_validate_air_voxel_nan_skipped():
    x_c, y_c, z_c = _grid_centers()
    dens = _density_full({0: np.nan, 4: np.nan})
    it = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=3.0)
    m = validate_against_boreholes([it], dens, x_c, y_c, z_c, BS)
    assert m.n_total == 1 and m.n_evaluated == 0
    assert m.mae_t_m3 is None
    assert m.residuals[0]["status"] == "AIR_VOXEL"


def test_validate_intervals_without_density_ignored():
    x_c, y_c, z_c = _grid_centers()
    dens = _density_full({0: 3.0})
    only_susc = BoreholeInterval(
        x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, susceptibility_si=0.01
    )
    m = validate_against_boreholes([only_susc], dens, x_c, y_c, z_c, BS)
    assert m.n_total == 0 and m.n_evaluated == 0
    assert m.pct_within[0.3] is None


# ─────────────────────────────────────────────────────────────────────────
#  estimate_depth_error
# ─────────────────────────────────────────────────────────────────────────
def test_depth_error_recovers_known_body():
    x_c, y_c, z_c = _grid_centers()
    # Cuerpo denso en iy=2 → y_c=75 m. Contraste fuerte sobre fondo 2.6.
    dens = np.full(x_c.size, 2.6)
    body = (np.abs(y_c - 75.0) < 1e-6) & (np.abs(x_c - 45.0) < 1e-6) & (np.abs(z_c - 45.0) < 1e-6)
    dens[body] = 4.0
    res = estimate_depth_error(dens, y_c, depth_true_m=75.0, base_density=2.6)
    assert res["depth_recovered_m"] == pytest.approx(75.0, abs=BS)
    assert res["depth_error_m"] <= BS
    assert res["peak_depth_m"] == pytest.approx(75.0)
    assert res["n_anomalous_voxels"] >= 1


def test_depth_error_no_anomaly_returns_none():
    x_c, y_c, _ = _grid_centers()
    flat = np.full(x_c.size, 2.6)  # sin contraste
    res = estimate_depth_error(flat, y_c, depth_true_m=100.0, base_density=2.6)
    assert res["depth_recovered_m"] is None
    assert res["depth_error_m"] is None


# ─────────────────────────────────────────────────────────────────────────
#  estimate_location_error (horizontal + profundidad, umbral fuerte >50% máx)
# ─────────────────────────────────────────────────────────────────────────
def test_location_error_recovers_horizontal_and_depth():
    x_c, y_c, z_c = _grid_centers()
    # Cuerpo fuerte en un único vóxel: (ix=2,iy=2,iz=2) → x=75,y=75,z=75.
    dens = np.full(x_c.size, 2.6)
    body = (np.abs(x_c - 75) < 1e-6) & (np.abs(y_c - 75) < 1e-6) & (np.abs(z_c - 75) < 1e-6)
    dens[body] = 4.0
    res = estimate_location_error(dens, x_c, y_c, z_c, (75.0, 75.0, 75.0), base_density=2.6)
    assert res["horizontal_error_m"] == pytest.approx(0.0, abs=1e-6)
    assert res["depth_error_m"] == pytest.approx(0.0, abs=1e-6)
    assert res["n_strong"] == 1
    assert res["recovered_x_m"] == pytest.approx(75.0)


def test_location_error_no_anomaly_returns_none():
    x_c, y_c, z_c = _grid_centers()
    flat = np.full(x_c.size, 2.6)
    res = estimate_location_error(flat, x_c, y_c, z_c, (45.0, 45.0, 45.0), base_density=2.6)
    assert res["horizontal_error_m"] is None
    assert res["n_strong"] == 0


# ─────────────────────────────────────────────────────────────────────────
#  CaseStudy.status / passes_gate
# ─────────────────────────────────────────────────────────────────────────
def _metrics(frac02, frac03):
    # Construye métricas mínimas con las fracciones deseadas (4 intervalos).
    return BoreholeValidationMetrics(
        n_evaluated=4, n_total=4, mae_t_m3=0.2, rmse_t_m3=0.25,
        max_abs_diff_t_m3=0.4, bias_t_m3=0.0,
        pct_within={0.2: frac02, 0.3: frac03, 0.5: 1.0},
    )


def test_case_status_ok_when_strong():
    c = CaseStudy(project="P", route="gravity_with_constraints", metrics=_metrics(0.9, 0.9))
    assert c.metrics.passes_gate() is True
    assert c.status == "OK"


def test_case_status_marginal():
    c = CaseStudy(project="P", route="gravity_only", metrics=_metrics(0.6, 0.8))
    assert c.metrics.passes_gate() is True   # 0.8 ≥ 0.75 @ 0.3
    assert c.status == "OK_MARGINAL"          # pero <0.8 dentro de 0.2


def test_case_status_fail():
    c = CaseStudy(project="P", route="gravity_only", metrics=_metrics(0.4, 0.5))
    assert c.metrics.passes_gate() is False
    assert c.status == "FAIL"


def test_case_status_no_borehole():
    c = CaseStudy(project="P", route="gravity_only", metrics=None)
    assert c.status == "NO_BOREHOLE"


# ─────────────────────────────────────────────────────────────────────────
#  aggregate_case_studies (GO/NO-GO)
# ─────────────────────────────────────────────────────────────────────────
def test_aggregate_go_when_majority_pass_and_confidence_predictive():
    cases = [
        CaseStudy(project="A", route="r", confidence=0.90, metrics=_metrics(0.9, 0.95)),
        CaseStudy(project="B", route="r", confidence=0.85, metrics=_metrics(0.85, 0.90)),
        CaseStudy(project="C", route="r", confidence=0.70, metrics=_metrics(0.6, 0.78)),
    ]
    s = aggregate_case_studies(cases)
    assert s["n_projects_with_borehole"] == 3
    assert s["n_projects_passing_gate"] == 3
    assert s["go_no_go"] == "GO"
    # confianza alta ↔ mayor fracción → correlación positiva
    assert s["confidence_predictive"] is True
    assert s["confidence_corr"] > 0


def test_aggregate_no_go_when_majority_fail():
    cases = [
        CaseStudy(project="A", route="r", confidence=0.65, metrics=_metrics(0.3, 0.4)),
        CaseStudy(project="B", route="r", confidence=0.65, metrics=_metrics(0.3, 0.5)),
        CaseStudy(project="C", route="r", confidence=0.85, metrics=_metrics(0.9, 0.95)),
    ]
    s = aggregate_case_studies(cases)
    assert s["n_projects_passing_gate"] == 1
    assert s["go_no_go"] == "NO_GO"


def test_aggregate_empty_is_no_go():
    s = aggregate_case_studies([CaseStudy(project="A", route="r", metrics=None)])
    assert s["n_projects_with_borehole"] == 0
    assert s["go_no_go"] == "NO_GO"


# ─────────────────────────────────────────────────────────────────────────
#  render_case_study_table
# ─────────────────────────────────────────────────────────────────────────
def test_render_table_format():
    cases = [
        CaseStudy(
            project="LdM", route="gravity_only", n_sensors_gravity=24,
            n_boreholes=1, depth_range_m=(0.0, 1000.0), data_quality_score=87.0,
            confidence=0.85, metrics=_metrics(0.82, 0.9),
        ),
        CaseStudy(project="NoBH", route="gravity_only", n_sensors_gravity=10),
    ]
    table = render_case_study_table(cases)
    lines = table.splitlines()
    assert lines[0].startswith("| Project | n_sens | n_bh | Depth | DQ% | Conf | MAE | %<0.2 | Status |")
    assert "| LdM |" in table
    assert "1.0km" in table          # 1000 m → 1.0km
    assert "85%" in table            # confianza
    assert "82%" in table            # %<0.2
    assert "s/sondaje" in table      # proyecto sin sondaje


def test_gate_constants_match_roadmap():
    # GO/NO-GO Fase 25: error <0.3 t/m³ en ≥75% de los intervalos.
    assert GATE_THRESHOLD_T_M3 == 0.3
    assert GATE_MIN_FRACTION == 0.75


# ─────────────────────────────────────────────────────────────────────────
#  PASO 2 — Ruta del COMBO grav+sondajes (harness): partes deterministas
#  (la inversión real es lenta y vive en el harness; aquí sólo helpers + veredicto)
# ─────────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts", "validation"))
import field_validation_harness as H  # noqa: E402


def test_boreholes_to_anchor_array_shape_and_filter():
    # 2 intervalos con densidad + 1 sin densidad (solo susceptibilidad) → (2,5).
    intervals = [
        BoreholeInterval(x_m=10.0, z_m=20.0, y_from_m=100.0, y_to_m=140.0, density_t_m3=3.4),
        BoreholeInterval(x_m=80.0, z_m=20.0, y_from_m=100.0, y_to_m=140.0, density_t_m3=2.6),
        BoreholeInterval(x_m=50.0, z_m=20.0, y_from_m=100.0, y_to_m=140.0, susceptibility_si=0.01),
    ]
    arr = H._boreholes_to_anchor_array(intervals)
    assert arr is not None
    assert arr.shape == (2, 5)
    # Orden de columnas que consume el solver: [x_m, z_m, y_from_m, y_to_m, density].
    assert list(arr[0]) == [10.0, 20.0, 100.0, 140.0, 3.4]


def test_boreholes_to_anchor_array_none_when_no_density():
    intervals = [
        BoreholeInterval(x_m=50.0, z_m=20.0, y_from_m=100.0, y_to_m=140.0, susceptibility_si=0.01),
    ]
    assert H._boreholes_to_anchor_array(intervals) is None


def test_evaluate_thesis_go_when_both_met():
    # Combo: profundidad ≤15m en todos + ≥75% proyectos pasan gate densidad >75%.
    rows = [
        {"depth_err_solo_m": 28.0, "depth_err_combo_m": 9.0, "pct_within_0_3_solo": 0.5, "pct_within_0_3_combo": 1.0},
        {"depth_err_solo_m": 24.0, "depth_err_combo_m": 12.0, "pct_within_0_3_solo": 0.5, "pct_within_0_3_combo": 0.8},
    ]
    t = H.evaluate_thesis(rows)
    assert t["depth_thesis_met"] is True
    assert t["density_gate_thesis_met"] is True
    assert t["verdict"] == "GO"
    assert t["median_depth_err_combo_m"] == pytest.approx(10.5)


def test_evaluate_thesis_no_go_when_depth_too_large():
    rows = [
        {"depth_err_solo_m": 28.0, "depth_err_combo_m": 22.0, "pct_within_0_3_solo": 0.5, "pct_within_0_3_combo": 1.0},
    ]
    t = H.evaluate_thesis(rows)
    assert t["depth_thesis_met"] is False
    assert t["verdict"] == "NO_GO"


def test_evaluate_thesis_no_go_when_gate_not_met():
    # Profundidad cumple, pero el gate de densidad NO (<75% de proyectos pasan).
    rows = [
        {"depth_err_solo_m": 28.0, "depth_err_combo_m": 8.0, "pct_within_0_3_solo": 0.3, "pct_within_0_3_combo": 0.4},
        {"depth_err_solo_m": 24.0, "depth_err_combo_m": 9.0, "pct_within_0_3_solo": 0.3, "pct_within_0_3_combo": 0.5},
    ]
    t = H.evaluate_thesis(rows)
    assert t["depth_thesis_met"] is True
    assert t["density_gate_thesis_met"] is False
    assert t["verdict"] == "NO_GO"


def test_render_combo_table_format():
    rows = [{
        "project": "Synthetic-Shallow", "true_depth_m": 150.0,
        "depth_err_solo_m": 28.0, "depth_err_combo_m": 9.0, "depth_improvement_m": 19.0,
        "pct_within_0_3_solo": 0.5, "pct_within_0_3_combo": 1.0, "n_anchored_vox": "3",
    }]
    table = H._render_combo_table(rows)
    assert table.splitlines()[0].startswith("| Proyecto | y_real | prof_err SOLA")
    assert "Synthetic-Shallow" in table
    assert "9.0m" in table
    assert "100%" in table
