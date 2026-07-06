"""F2B — Desurvey por curvatura mínima + QA/QC + compositación.

Verdades del gate:
  - Pozo vertical: traza exacta (collar + (0,0,md)).
  - Pozo recto inclinado (dip 60, az 90): forma cerrada este=MD·cos60,
    abajo=MD·sin60.
  - Pozo de 3 TRAMOS calculado A MANO con la fórmula de curvatura mínima
    (RF = (2/β)·tan(β/2)): valores esperados hardcodeados ±0.05 m.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.borehole_desurvey_service import (  # noqa: E402
    DesurveyInputError,
    composite_intervals,
    desurvey_minimum_curvature,
    position_intervals_on_trace,
    qaqc_intervals,
)


# ── 1. Desurvey ──────────────────────────────────────────────────────────────
def test_vertical_hole_exact():
    tr = desurvey_minimum_curvature("V1", [0, 50, 120], [0, 0, 0], [90, 90, 90])
    np.testing.assert_allclose(tr.east, 0.0, atol=1e-12)
    np.testing.assert_allclose(tr.north, 0.0, atol=1e-12)
    np.testing.assert_allclose(tr.depth, [0, 50, 120], atol=1e-9)


def test_straight_inclined_closed_form():
    """dip 60 bajo horizontal, az 90 (este): este=MD/2, abajo=MD·√3/2."""
    tr = desurvey_minimum_curvature("I1", [0, 100], [90, 90], [60, 60])
    assert abs(tr.east[-1] - 50.0) < 1e-9
    assert abs(tr.north[-1]) < 1e-9
    assert abs(tr.depth[-1] - 86.60254) < 1e-4


def test_three_segment_hand_computed():
    """3 tramos con dogleg 10°/tramo — esperados calculados a mano:
    MD100: (E 8.7046, N 0, D 99.494); MD200: (E 34.554, N 0, D 195.963)."""
    tr = desurvey_minimum_curvature(
        "H3", [0, 100, 200], [0, 90, 90], [90, 80, 70],
    )
    # Estación MD=100 (índice 1).
    assert abs(tr.east[1] - 8.7046) < 0.05, tr.east[1]
    assert abs(tr.north[1]) < 0.05
    assert abs(tr.depth[1] - 99.494) < 0.05, tr.depth[1]
    # Estación MD=200.
    assert abs(tr.east[2] - 34.554) < 0.05, tr.east[2]
    assert abs(tr.depth[2] - 195.963) < 0.05, tr.depth[2]


def test_survey_extension_and_first_station_warnings():
    tr = desurvey_minimum_curvature(
        "W1", [30, 60], [0, 0], [90, 90], total_depth_m=100.0,
    )
    assert any("MD=30" in w for w in tr.warnings)
    assert any("se extendió" in w for w in tr.warnings)
    assert abs(tr.depth[-1] - 100.0) < 1e-9


def test_desurvey_guardrails():
    with pytest.raises(DesurveyInputError, match="crecientes"):
        desurvey_minimum_curvature("B", [0, 50, 40], [0, 0, 0], [90, 90, 90])
    with pytest.raises(DesurveyInputError, match="dip fuera"):
        desurvey_minimum_curvature("B", [0, 50], [0, 0], [90, 120])
    with pytest.raises(DesurveyInputError, match="mismo largo"):
        desurvey_minimum_curvature("B", [0, 50], [0], [90, 90])


def test_position_intervals_true_vertical_depths():
    """El pozo inclinado queda en su posición VERDADERA (la deuda que cierra
    F2B: antes se asumía vertical y quedaba mal en silencio)."""
    tr = desurvey_minimum_curvature("I1", [0, 100], [90, 90], [60, 60])
    ivs = position_intervals_on_trace(
        tr, collar_x_m=1000.0, collar_z_m=2000.0,
        intervals=[{"depth_from": 40.0, "depth_to": 60.0, "density": 2.9}],
    )
    iv = ivs[0]
    assert abs(iv["x_m"] - (1000.0 + 25.0)) < 1e-6          # este del punto medio
    assert abs(iv["z_m"] - 2000.0) < 1e-6
    assert abs(iv["y_from_m"] - 40.0 * np.sin(np.radians(60))) < 1e-6
    assert abs(iv["y_to_m"] - 60.0 * np.sin(np.radians(60))) < 1e-6
    assert abs(iv["vertical_over_md_ratio"] - np.sin(np.radians(60))) < 1e-9


# ── 2. QA/QC ─────────────────────────────────────────────────────────────────
def test_qaqc_detects_each_defect_with_row_and_severity():
    ivs = [
        {"hole_id": "A", "depth_from": 0, "depth_to": 10, "density": 2.7},      # ok
        {"hole_id": "A", "depth_from": 10, "depth_to": 8, "density": 2.7},      # FROM>=TO
        {"hole_id": "A", "depth_from": 8, "depth_to": 20, "density": 2.7},      # solape con fila1
        {"hole_id": "A", "depth_from": 30, "depth_to": 40, "density": 2.7},     # hueco 20-30
        {"hole_id": "A", "depth_from": 30, "depth_to": 40, "density": 2.7},     # duplicado
        {"hole_id": "B", "depth_from": 0, "depth_to": 5, "density": 99.0},      # fuera de rango
        {"hole_id": "B", "depth_from": 5, "depth_to": 9},                        # sin dens ni lito
        {"hole_id": "C", "depth_from": -2, "depth_to": 5, "density": 2.7},      # negativa
    ]
    rep = qaqc_intervals(ivs)
    codes = {f["code"] for f in rep["findings"]}
    assert {"FROM_MAYOR_IGUAL_TO", "SOLAPE", "HUECO", "INTERVALO_DUPLICADO",
            "DENSIDAD_FUERA_DE_RANGO", "SIN_DENSIDAD_NI_LITOLOGIA",
            "PROFUNDIDAD_NEGATIVA"} <= codes
    assert rep["n_blocking"] >= 3 and rep["usable"] is False
    dup = next(f for f in rep["findings"] if f["code"] == "INTERVALO_DUPLICADO")
    assert dup["row"] == 5


def test_qaqc_clean_table_usable():
    ivs = [
        {"hole_id": "A", "depth_from": 0, "depth_to": 10, "density": 2.7},
        {"hole_id": "A", "depth_from": 10, "depth_to": 20, "density": 3.1},
    ]
    rep = qaqc_intervals(ivs)
    assert rep["usable"] is True and rep["findings"] == []


# ── 3. Compositación ─────────────────────────────────────────────────────────
def test_composite_weighted_density_and_mode_lithology():
    ivs = [
        {"hole_id": "A", "depth_from": 0, "depth_to": 10, "density": 2.0, "lithology": "andesita"},
        {"hole_id": "A", "depth_from": 10, "depth_to": 20, "density": 3.0, "lithology": "magnetita"},
        {"hole_id": "A", "depth_from": 20, "depth_to": 25, "density": 4.0, "lithology": "magnetita"},
    ]
    comps, warns = composite_intervals(ivs, 20.0)
    assert len(comps) == 1, (comps, warns)      # el 2º composite cubre 25% → fuera
    c = comps[0]
    assert abs(c["density"] - 2.5) < 1e-9       # (2.0·10 + 3.0·10)/20
    assert c["coverage"] == 1.0
    assert any("descartaron" in w for w in warns)


def test_composite_guardrail():
    with pytest.raises(ValueError, match="> 0"):
        composite_intervals([], 0.0)


# ── 4. Endpoint HTTP ─────────────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_endpoint_parse_csv_file_multipart_encoding():
    """F2B — la variante multipart pasa por el sniffer de encoding: un CSV
    latin-1 con litologías con ñ llega INTACTO (la variante csv_text lo
    corrompía a mojibake por decodificarse como UTF-8 en el navegador)."""
    csv_es = (
        "hole_id,easting,northing,depth_from,depth_to,density,lithology\n"
        "DDH-1,100,200,0,10,2.7,andesita con ñ\n"
        "DDH-1,100,200,10,25,3.9,magnetita\n"
    )
    r = _client().post(
        "/borehole/parse-csv-file",
        files={"file": ("sondajes.csv", csv_es.encode("latin-1"), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_samples"] == 2
    assert "andesita con ñ" in body["lithologies_detected"]


def test_endpoint_desurvey_roundtrip():
    r = _client().post("/borehole/desurvey", json={
        "holes": [{
            "hole_id": "DDH-01",
            "collar_x_m": 500.0, "collar_z_m": 600.0,
            "survey": [
                {"md": 0, "azimuth_deg": 90, "dip_deg": 60},
                {"md": 100, "azimuth_deg": 90, "dip_deg": 60},
            ],
            "intervals": [
                {"depth_from": 40.0, "depth_to": 60.0, "density": 2.9},
            ],
        }],
        "composite_length_m": 20.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    hole = body["holes"][0]
    assert abs(hole["trace"][-1]["x_m"] - 550.0) < 1e-6
    iv = hole["intervals_positioned"][0]
    assert abs(iv["x_m"] - 525.0) < 1e-6
    assert body["qaqc"]["usable"] is True
    assert body["composites"], body
