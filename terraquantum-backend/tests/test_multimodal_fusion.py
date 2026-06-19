"""FASE 21 — Tests de la estrategia de fusión multimodal.

Cubre los 12 casos del roadmap (Fase 21): ruteo por combinación de datos,
confianza ajustada, error de profundidad, clasificación de conflicto y pesado
por modalidad. Todo aquí es lógica de decisión pura (sin inversión).
"""

import numpy as np
import pytest

from services.multimodal_fusion_service import (
    InsufficientDataError,
    MIN_SENSORS_FOR_INVERSION,
    ROUTE_GRAVITY_ONLY,
    ROUTE_MAGNETIC_ONLY,
    ROUTE_JOINT,
    ROUTE_GRAVITY_BOREHOLE,
    ROUTE_JOINT_BOREHOLE,
    _BASE_CONFIDENCE,
    borehole_sigma,
    classify_density_conflict,
    compute_confidence,
    estimate_error_depth,
    gravity_sigma,
    magnetic_sigma,
    plan_multimodal,
    select_route,
)


# ── Ruteo ──────────────────────────────────────────────────────────────────────

def test_route_gravity_only():
    assert select_route(True, False, False, n_sensors=24) == ROUTE_GRAVITY_ONLY
    plan = plan_multimodal(True, False, False, n_sensors=24)
    assert plan.route == ROUTE_GRAVITY_ONLY
    assert plan.has_gravity and not plan.has_magnetic and not plan.has_borehole


def test_route_magnetic_only():
    assert select_route(False, True, False, n_sensors=30) == ROUTE_MAGNETIC_ONLY
    # Magnética + sondaje de densidad (sin gravedad) → sigue siendo magnético, con aviso.
    plan = plan_multimodal(False, True, True, n_sensors=30)
    assert plan.route == ROUTE_MAGNETIC_ONLY
    assert any("sondaje" in w.lower() for w in plan.warnings)


def test_route_gravity_magnetic():
    assert select_route(True, True, False, n_sensors=40) == ROUTE_JOINT


def test_route_gravity_borehole():
    assert select_route(True, False, True, n_sensors=20) == ROUTE_GRAVITY_BOREHOLE


def test_route_all_four():
    # "all" = gravedad + magnetismo + sondaje (las 3 modalidades del proyecto).
    assert select_route(True, True, True, n_sensors=50) == ROUTE_JOINT_BOREHOLE
    plan = plan_multimodal(True, True, True, n_sensors=50)
    assert plan.base_confidence == _BASE_CONFIDENCE[ROUTE_JOINT_BOREHOLE]


def test_route_insufficient_data():
    # Sin ningún campo potencial.
    with pytest.raises(InsufficientDataError):
        select_route(False, False, True, n_sensors=100)
    # Con potencial pero muy pocos sensores.
    with pytest.raises(InsufficientDataError):
        select_route(True, False, False, n_sensors=MIN_SENSORS_FOR_INVERSION - 1)


# ── Confianza ──────────────────────────────────────────────────────────────────

def test_confidence_calculation():
    # Sin data_quality → confianza base intacta.
    assert compute_confidence(ROUTE_JOINT) == pytest.approx(0.80)
    # Con calidad 90/100 → base * 0.90.
    assert compute_confidence(ROUTE_JOINT, data_quality=90.0) == pytest.approx(0.80 * 0.90)
    # Más modalidades → más confianza base (monotonicidad del diseño).
    assert (
        _BASE_CONFIDENCE[ROUTE_JOINT_BOREHOLE]
        > _BASE_CONFIDENCE[ROUTE_GRAVITY_BOREHOLE]
        > _BASE_CONFIDENCE[ROUTE_JOINT]
        > _BASE_CONFIDENCE[ROUTE_GRAVITY_ONLY]
        > _BASE_CONFIDENCE[ROUTE_MAGNETIC_ONLY]
    )
    # Calidad pobre penaliza.
    plan = plan_multimodal(True, False, False, n_sensors=24, data_quality=45.0)
    assert plan.confidence < plan.base_confidence
    assert any("calidad" in w.lower() for w in plan.warnings)


# ── Error de profundidad ───────────────────────────────────────────────────────

def test_error_depth_estimation():
    # Cobertura plena: valores base por combo.
    assert estimate_error_depth(ROUTE_GRAVITY_ONLY, coverage_pct=1.0) == pytest.approx(30.0)
    assert estimate_error_depth(ROUTE_MAGNETIC_ONLY, coverage_pct=1.0) == pytest.approx(40.0)
    assert estimate_error_depth(ROUTE_JOINT, coverage_pct=1.0) == pytest.approx(20.0)
    # Cobertura parcial empeora el error (combos sin sondaje).
    assert estimate_error_depth(ROUTE_GRAVITY_ONLY, coverage_pct=0.5) == pytest.approx(35.0)
    # Combos con sondaje escalan con (1 - confianza).
    assert estimate_error_depth(ROUTE_GRAVITY_BOREHOLE, confidence=1.0) == pytest.approx(15.0)
    assert estimate_error_depth(ROUTE_JOINT_BOREHOLE, confidence=1.0) == pytest.approx(10.0)
    assert estimate_error_depth(ROUTE_JOINT_BOREHOLE, confidence=0.5) == pytest.approx(11.0)
    # Más modalidades → menos error (con confianza plena).
    assert estimate_error_depth(ROUTE_JOINT_BOREHOLE, confidence=1.0) < estimate_error_depth(
        ROUTE_GRAVITY_ONLY, coverage_pct=1.0
    )


# ── Conflictos ─────────────────────────────────────────────────────────────────

def test_conflict_small_diff():
    status, msg = classify_density_conflict(0.1)
    assert status == "OK"
    # Justo bajo el umbral de FLAG pero sobre WARNING.
    status_w, _ = classify_density_conflict(0.35)
    assert status_w == "WARNING"


def test_conflict_large_diff():
    status, msg = classify_density_conflict(0.8)
    assert status == "FLAG"
    assert "conflicto" in msg.lower()
    # El signo no importa, sólo la magnitud.
    assert classify_density_conflict(-0.8)[0] == "FLAG"


# ── Pesado por modalidad ───────────────────────────────────────────────────────

def test_weighting_multimodal():
    g = np.array([10.0, 11.0, 9.5, 10.5, 50.0])  # 50 es outlier
    sg = gravity_sigma(g, robust=True)
    sm = magnetic_sigma(g, robust=True)
    assert sg.shape == g.shape and np.all(sg > 0)
    assert sm.shape == g.shape and np.all(sm > 0)
    # Robusto: el outlier recibe sigma mayor que los datos limpios (downweight).
    assert float(sg[-1]) > float(np.mean(sg[:-1]))
    # Sondaje sin réplicas: sigma = 15% de la densidad.
    assert borehole_sigma(2.8) == pytest.approx(0.15 * 2.8)


def test_weighting_borehole_multiple_samples():
    samples = [2.70, 2.80, 2.90, 2.85]
    sig = borehole_sigma(2.8, samples=samples)
    expected = float(np.std(np.asarray(samples))) / np.sqrt(len(samples))
    assert sig == pytest.approx(expected)
    # Con réplicas muy consistentes el sigma es menor que el piso del 15%.
    tight = borehole_sigma(2.8, samples=[2.80, 2.81, 2.80, 2.79])
    assert tight < 0.15 * 2.8


# ── Endpoint de previsualización (POST /multimodal/plan) ────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def test_endpoint_gravity_only():
    r = _client().post("/multimodal/plan", json={"n_gravity_sensors": 24})
    assert r.status_code == 200
    body = r.json()
    assert body["has_gravity"] and not body["has_magnetic"]
    assert body["plan"]["route"] == ROUTE_GRAVITY_ONLY
    assert body["insufficient_reason"] is None


def test_endpoint_all_modalities_with_quality():
    r = _client().post(
        "/multimodal/plan",
        json={
            "n_gravity_sensors": 40,
            "n_magnetic_sensors": 40,
            "n_boreholes_with_density": 3,
            "data_quality": 87.0,
            "coverage_pct": 0.9,
        },
    )
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["route"] == ROUTE_JOINT_BOREHOLE
    # confianza ajustada = 0.90 * 0.87.
    assert plan["confidence"] == pytest.approx(0.90 * 0.87, abs=1e-3)


def test_endpoint_insufficient_data():
    # Sólo sondajes → sin campo potencial → plan None + razón.
    r = _client().post("/multimodal/plan", json={"n_boreholes_with_density": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] is None
    assert body["insufficient_reason"]
