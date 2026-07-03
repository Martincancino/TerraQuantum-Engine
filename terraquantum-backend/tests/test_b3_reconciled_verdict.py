"""
B3 — veredicto de calidad RECONCILIADO (un solo veredicto honesto).
===================================================================

Verifica que build_reconciled_verdict / apply_reconciled_verdict:
  1. Reconcilian al ESLABÓN MÁS DÉBIL: el caso LdM (GOOD/HIGH conviviendo con
     UNCLASSIFIED + r06 REMEDIATION) colapsa a un único veredicto LOW.
  2. Capan (downgrade-only) confidence_level / model_reliability_level /
     best_target.confidence_level → el payload deja de sostener un 'HIGH' contradicho.
  3. No degradan un caso genuinamente bueno (todo HIGH → HIGH, sin cambios).
  4. Un blanco null-space fuerza LOW.
  5. priority_class NO se toca (concepto distinto, con tests propios).
"""
from __future__ import annotations

from services.geophysics_service import (
    apply_reconciled_verdict,
    build_reconciled_verdict,
)


def _ldm_like_payload():
    # El caso de Laguna del Maule: survey "GOOD"/HIGH pero sin blanco clasificable y con
    # padding/regional FÍSICAMENTE significativo (forward_fraction alto).
    return {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "UNCLASSIFIED",
        "r06_padding_saturation_audit": {
            "phase_gate_recommendation": "REMEDIATION_REQUIRED",
            "forward_fraction_pad_saturated": 0.5,   # físicamente severo
            "mass_fraction_pad_saturated": 0.4,
            "delta_rms_pct": 30.0,
        },
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }


def test_ldm_contradiction_collapses_to_low():
    p = _ldm_like_payload()
    v = build_reconciled_verdict(p)
    assert v["level"] == "LOW"
    # El veredicto nombra QUÉ lo limita.
    assert "priority_class" in v["limiting_factors"]
    assert "r06_padding_physical" in v["limiting_factors"]
    assert "NO confiable" in v["headline"]


def test_r06_false_alarm_chi2_only_does_not_cap():
    # REMEDIATION disparado SÓLO por delta_chi2 (bug conocido) con mass/forward/rms ≈ 0:
    # NO debe arrastrar el veredicto. Aquí el resto es HIGH → overall HIGH pese al gate.
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {
            "phase_gate_recommendation": "REMEDIATION_REQUIRED",
            "forward_fraction_pad_saturated": 0.0,
            "mass_fraction_pad_saturated": 2e-6,
            "delta_rms_pct": 0.0,
            "delta_chi2_pct": 94.8,                  # falso alarma
        },
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }
    v = build_reconciled_verdict(p)
    assert v["level"] == "HIGH"
    assert "r06_padding_physical" not in v["limiting_factors"]
    assert v["components"]["r06_padding_gate"] == "REMEDIATION_REQUIRED"  # transparencia


def test_apply_caps_confidence_and_reliability_and_target():
    p = _ldm_like_payload()
    apply_reconciled_verdict(p)
    # El 'HIGH' contradictorio queda capado a LOW en TODOS los campos individuales.
    assert p["overall_verdict"]["level"] == "LOW"
    assert p["confidence_level"] == "LOW"
    assert p["model_reliability_level"] == "LOW_RELIABILITY"
    assert p["best_target"]["confidence_level"] == "LOW"
    # priority_class NO se toca.
    assert p["priority_class"] == "UNCLASSIFIED"


def test_clean_all_high_stays_high():
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }
    apply_reconciled_verdict(p)
    assert p["overall_verdict"]["level"] == "HIGH"
    assert p["confidence_level"] == "HIGH"               # sin downgrade
    assert p["model_reliability_level"] == "HIGH_RELIABILITY"
    assert p["best_target"]["confidence_level"] == "HIGH"


def test_null_space_target_forces_low():
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": True},
    }
    v = apply_reconciled_verdict(p)
    assert v["level"] == "LOW"
    assert "best_target_null_space" in v["limiting_factors"]
    assert p["best_target"]["confidence_level"] == "LOW"


def test_medium_is_the_weakest_link():
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "MEDIUM_RELIABILITY",   # eslabón más débil = MEDIUM
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }
    apply_reconciled_verdict(p)
    assert p["overall_verdict"]["level"] == "MEDIUM"
    assert p["confidence_level"] == "MEDIUM"              # HIGH capado a MEDIUM
    assert p["best_target"]["confidence_level"] == "MEDIUM"


def test_idempotent_no_upgrade_on_second_apply():
    p = _ldm_like_payload()
    apply_reconciled_verdict(p)
    first = dict(p["overall_verdict"])
    apply_reconciled_verdict(p)                            # segunda pasada
    assert p["overall_verdict"]["level"] == first["level"] == "LOW"
    assert p["confidence_level"] == "LOW"                  # no re-sube


def test_r06_not_run_is_ignored():
    # Sin r06 (no corrió) no debe forzar nada; gana el resto.
    p = {
        "confidence_level": "MEDIUM",
        "model_reliability_level": "MEDIUM_RELIABILITY",
        "priority_class": "MEDIUM_RELATIVE_PRIORITY",
        "best_target": {"confidence_level": "MEDIUM", "is_null_space_artifact": False},
    }
    v = build_reconciled_verdict(p)
    assert v["level"] == "MEDIUM"
    assert v["components"]["r06_padding_gate"] == "NOT_RUN"
