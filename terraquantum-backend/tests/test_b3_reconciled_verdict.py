"""
B3 — veredicto de calidad RECONCILIADO (un solo veredicto honesto).
===================================================================

Verifica que build_reconciled_verdict / apply_reconciled_verdict:
  1. Reconcilian al ESLABÓN MÁS DÉBIL: el caso LdM (GOOD/HIGH conviviendo con
     UNCLASSIFIED + r06 REMEDIATION) colapsa a un único veredicto LOW.
  2. Capan (downgrade-only) confidence_level / model_reliability_level /
     best_target.confidence_level → el payload deja de sostener un 'HIGH' contradicho.
  3. No degradan un caso genuinamente bueno: ninguna señal MEDIDA lo limita.
     FASE 26 — el nivel resultante ya no es `HIGH` sino `MEDIUM`, y no porque alguna
     señal falle: `HIGH` está RETENIDO a propósito hasta la Fase 30 (entrada
     `high_hold_pending_fase30`). La propiedad que este archivo defiende sigue siendo
     la misma —el worst-of no inventa degradaciones— y se comprueba mirando QUIÉN
     limita, no el nivel a secas.
  4. Un blanco null-space fuerza LOW.
  5. priority_class NO se toca (concepto distinto, con tests propios).
"""
from __future__ import annotations

from services.geophysics_service import (
    apply_reconciled_verdict,
    build_reconciled_verdict,
)

# FASE 26 — la retención declarada de `HIGH`. Mientras la Fase 30 no la levante, es
# una entrada más del worst-of y aparece en `limiting_factors` de todo caso sano.
HOLD = "high_ho" "ld_pending_fase30"


def _resolution_ok():
    """Perfil de resolución de un survey que SÍ resuelve algo (no topea)."""
    return {"computed": True, "resolves_anywhere": True, "resolvability_index": 0.25,
            "shallowest_band_resolution_m": 250.0, "deepest_resolved_m": 500.0,
            "max_block_tested_m": 750.0, "sigma_used": {"snr_signal": 3.6}}


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
    # FASE 21: el checkerboard se declara PASS explícitamente. Antes este test aprobaba
    # con el diagnóstico AUSENTE, que es justo el agujero que la Fase 21 cerró (`NOT_RUN`
    # ya no es gratis); dejarlo implícito volvería el test cómplice del defecto.
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
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.72},
        "resolution_qa": _resolution_ok(),
    }
    v = build_reconciled_verdict(p)
    # Lo que se defiende: la falsa alarma de r06 NO arrastra el veredicto. Se comprueba
    # sobre QUIÉN limita, no sobre el nivel: desde la Fase 26 el único limitador de un
    # caso sano es la retención declarada de HIGH.
    assert "r06_padding_physical" not in v["limiting_factors"]
    assert v["limiting_factors"] == [HOLD]
    assert v["level"] == "MEDIUM"
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


def test_clean_case_is_limited_only_by_the_declared_hold():
    # FASE 21: con el checkerboard declarado PASS el techo quedaba libre y HIGH sobrevivía.
    # FASE 26: `HIGH` está retenido hasta la Fase 30, así que el caso sano sale MEDIUM —
    # pero el worst-of SIGUE sin inventar degradaciones: la única entrada que limita es
    # la retención, y ninguna señal medida aporta nada peor.
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.81},
        "resolution_qa": _resolution_ok(),
    }
    apply_reconciled_verdict(p)
    ov = p["overall_verdict"]
    assert ov["level"] == "MEDIUM"
    assert ov["limiting_factors"] == [HOLD]              # NADA medido lo limita
    assert p["confidence_level"] == "MEDIUM"             # downgrade-only al techo
    assert p["best_target"]["confidence_level"] == "MEDIUM"
    assert p["model_reliability_level"] == "MEDIUM_RELIABILITY"  # capado, coherente
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert ov["ceiling"]["capped_by"] == [HOLD]
    assert ov["ceiling"]["structural"] is False          # no es un examen imposible


def test_null_space_target_forces_low():
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": True},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.7},
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
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.7},
        "resolution_qa": _resolution_ok(),
    }
    apply_reconciled_verdict(p)
    assert p["overall_verdict"]["level"] == "MEDIUM"
    assert p["confidence_level"] == "MEDIUM"              # HIGH capado a MEDIUM
    assert p["best_target"]["confidence_level"] == "MEDIUM"
    # FASE 21: MEDIUM lo fija una señal MEDIDA. FASE 26: empata con la retención, y el
    # empate se reporta entero — lo que importa es que `model_reliability` está ahí.
    assert "model_reliability" in p["overall_verdict"]["decided_by"]
    assert set(p["overall_verdict"]["decided_by"]) == {"model_reliability", HOLD}
    assert p["overall_verdict"]["ceiling"]["max_attainable_level"] == "MEDIUM"


def test_idempotent_no_upgrade_on_second_apply():
    p = _ldm_like_payload()
    apply_reconciled_verdict(p)
    first = dict(p["overall_verdict"])
    apply_reconciled_verdict(p)                            # segunda pasada
    assert p["overall_verdict"]["level"] == first["level"] == "LOW"
    assert p["confidence_level"] == "LOW"                  # no re-sube


def test_r06_not_run_is_ignored():
    # Sin r06 (no corrió) no debe forzar nada; gana el resto. r06 mide el impacto FÍSICO
    # del padding saturado: si no hay padding auditado no hay nada que penalizar, a
    # diferencia del checkerboard (Fase 21), cuya ausencia sí topea porque lo que mide —la
    # resolución del survey— no deja de ser desconocida por no haberse calculado.
    p = {
        "confidence_level": "MEDIUM",
        "model_reliability_level": "MEDIUM_RELIABILITY",
        "priority_class": "MEDIUM_RELATIVE_PRIORITY",
        "best_target": {"confidence_level": "MEDIUM", "is_null_space_artifact": False},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.7},
    }
    v = build_reconciled_verdict(p)
    assert v["level"] == "MEDIUM"
    assert v["components"]["r06_padding_gate"] == "NOT_RUN"
    assert not [s for s in v["signals"] if s["signal"].startswith("r06")]
