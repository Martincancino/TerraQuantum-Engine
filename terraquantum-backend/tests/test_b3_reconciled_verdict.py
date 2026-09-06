"""
B3 — veredicto de calidad RECONCILIADO (un solo veredicto honesto).
===================================================================

Verifica que build_reconciled_verdict / apply_reconciled_verdict:
  1. Reconcilian al ESLABÓN MÁS DÉBIL: el caso LdM (GOOD/HIGH conviviendo con
     UNCLASSIFIED + r06 REMEDIATION) colapsa a un único veredicto LOW.
  2. Capan (downgrade-only) confidence_level / model_reliability_level /
     best_target.confidence_level → el payload deja de sostener un 'HIGH' contradicho.
  3. No degradan un caso genuinamente bueno: ninguna señal MEDIDA lo limita.
     FASE 26 — el nivel resultante dejó de ser `HIGH` porque `HIGH` estaba RETENIDO a
     propósito hasta la Fase 30. FASE 30 — la retención se levantó y `HIGH` vuelve a
     ser alcanzable, pero ya no se concede por AUSENCIA de defectos: lo sella
     `high_seal` con dos pruebas medidas (resolución por debajo del peldaño más grueso
     del examen, y exceso de masa de piso <= 0,5). La propiedad que este archivo
     defiende es la misma desde el principio —el worst-of no inventa degradaciones— y
     se comprueba mirando QUIÉN limita, no el nivel a secas.
  4. Un blanco null-space fuerza LOW.
  5. priority_class NO se toca (se capa el payload, no la clase) y desde la Fase 30
     tampoco TOPEA: mide atractivo de targeting, no confiabilidad. Se sigue publicando.
"""
from __future__ import annotations

from services.geophysics_service import (
    apply_reconciled_verdict,
    build_reconciled_verdict,
)

# FASE 30 — la retención declarada de la Fase 26 se RETIRÓ. El literal se conserva sólo
# para poder afirmar que ya no aparece en ningún veredicto (regresión, al final).
HOLD_RETIRADO = "high_ho" "ld_pending_fase30"


def _resolution_ok():
    """Perfil de resolución de un survey que SÍ resuelve algo (no topea) y que además
    resuelve POR DEBAJO del peldaño más grueso del examen (250 m de 750): la primera de
    las dos pruebas del sello de HIGH de la Fase 30."""
    return {"computed": True, "resolves_anywhere": True, "resolvability_index": 0.25,
            "shallowest_band_resolution_m": 250.0, "deepest_resolved_m": 500.0,
            "max_block_tested_m": 750.0, "sigma_used": {"snr_signal": 3.6}}


# Segunda prueba del sello: masa de piso dentro del límite. Se declara EXPLÍCITAMENTE para
# que un payload "sano" lo sea de verdad y no por omisión — la ausencia del dato NO sella.
PISO_LIMPIO = 0.13


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
    # El veredicto nombra QUÉ lo limita. FASE 30: ya NO es `priority_class` —que dejó de
    # topear— sino la severidad FÍSICA de r06, que es una medición del dato y no una
    # opinión sobre el atractivo del blanco. El colapso sobrevive sin esa muleta.
    assert "r06_padding_physical" in v["limiting_factors"]
    assert "priority_class" not in v["limiting_factors"]
    # …y `priority_class` se sigue PUBLICANDO, con su papel declarado.
    assert v["components"]["priority_class"] == "UNCLASSIFIED"
    assert v["components"]["priority_class_role"].startswith("targeting_attractiveness")
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
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": PISO_LIMPIO},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.72},
        "resolution_qa": _resolution_ok(),
    }
    v = build_reconciled_verdict(p)
    # Lo que se defiende: la falsa alarma de r06 NO arrastra el veredicto. FASE 30 — con
    # la retención retirada y el sello cumplido, vuelve a poder comprobarse sobre el
    # NIVEL y no sólo sobre quién limita, que es la forma fuerte del enunciado.
    assert "r06_padding_physical" not in v["limiting_factors"]
    assert v["level"] == "HIGH"
    assert v["limiting_factors"] == []                   # nadie limita un HIGH
    assert v["components"]["high_seal"]["sealed"] is True
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


def test_clean_case_reaches_high_because_it_SEALED():
    # FASE 21: con el checkerboard declarado PASS el techo quedaba libre y HIGH sobrevivía.
    # FASE 26: `HIGH` quedó retenido hasta la Fase 30, así que el caso sano salía MEDIUM.
    # FASE 30: la retención se retiró y el caso sano vuelve a HIGH — pero AHORA porque
    # SELLÓ, no porque nadie lo contradijera. Es la diferencia entre "no encontré nada
    # malo" y "medí que resuelve": lo primero es lo que declaraba HIGH a corridas de
    # 978 m de error en el barrido de la Fase 26.
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": PISO_LIMPIO},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.81},
        "resolution_qa": _resolution_ok(),
    }
    apply_reconciled_verdict(p)
    ov = p["overall_verdict"]
    assert ov["level"] == "HIGH"
    assert ov["limiting_factors"] == []                  # NADA lo limita
    assert p["confidence_level"] == "HIGH"               # el downgrade-only no degrada
    assert p["best_target"]["confidence_level"] == "HIGH"
    assert p["model_reliability_level"] == "HIGH_RELIABILITY"
    assert ov["ceiling"]["max_attainable_level"] == "HIGH"
    assert ov["ceiling"]["capped_by"] == []
    assert ov["ceiling"]["structural"] is False          # no es un examen imposible
    # Y el sello dice POR QUÉ, con los dos números que lo concedieron.
    seal = ov["components"]["high_seal"]
    assert seal["sealed"] is True
    assert seal["shallowest_band_resolution_m"] == 250.0
    assert seal["max_block_tested_m"] == 750.0
    assert seal["floor_mass_excess"] == PISO_LIMPIO


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
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": PISO_LIMPIO},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.7},
        "resolution_qa": _resolution_ok(),
    }
    apply_reconciled_verdict(p)
    assert p["overall_verdict"]["level"] == "MEDIUM"
    assert p["confidence_level"] == "MEDIUM"              # HIGH capado a MEDIUM
    assert p["best_target"]["confidence_level"] == "MEDIUM"
    # FASE 21: MEDIUM lo fija una señal MEDIDA. FASE 30: con la retención retirada y el
    # sello cumplido, esa señal medida es la ÚNICA que lo fija — el empate desapareció y
    # el enunciado queda más fuerte, no más débil.
    assert p["overall_verdict"]["decided_by"] == ["model_reliability"]
    assert p["overall_verdict"]["components"]["high_seal"]["sealed"] is True
    assert p["overall_verdict"]["ceiling"]["capped_by"] == ["model_reliability"]
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


# ═════════════════════════════════════════════════════════════════════════════
# FASE 30 — regresión: la retención declarada ya no existe en ningún veredicto
# ═════════════════════════════════════════════════════════════════════════════

def test_the_declared_hold_is_gone_from_every_verdict():
    """`high_hold_pending_fase30` fue una entrada del worst-of durante las Fases 26-29.
    La Fase 30 la retiró. Este test existe para que su reaparición sea un fallo y no un
    silencio: el literal viaja al reporte HTML, al manifiesto del ZIP y al copiloto.

    Se comprueba sobre tres payloads DISTINTOS —sano, capado y roto— porque la retención
    aparecía en los tres.
    """
    sanos = [
        {"confidence_level": "HIGH", "model_reliability_level": "HIGH_RELIABILITY",
         "priority_class": "HIGH_RELATIVE_PRIORITY",
         "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
         "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                         "floor_mass_excess": PISO_LIMPIO},
         "resolution_qa": _resolution_ok()},
        _ldm_like_payload(),
        {},                                    # payload vacío: ni siquiera ahí
    ]
    for p in sanos:
        v = build_reconciled_verdict(p)
        texto = repr(v)
        assert HOLD_RETIRADO not in texto, f"la retención reapareció en {v['level']}"
        assert HOLD_RETIRADO not in v["limiting_factors"]
        assert HOLD_RETIRADO not in (v["ceiling"].get("capped_by") or [])


def test_an_empty_payload_does_not_reach_high():
    """Sin ninguna señal, `HIGH` no se concede: el sello no puede evaluarse y capa.

    Es la propiedad de la Fase 21 —la ausencia nunca mejora el veredicto— aplicada al
    nivel nuevo. Antes de la Fase 30 la garantizaba la retención declarada; si al
    retirarla nadie la garantizara, un reporte vacío saldría HIGH.
    """
    v = build_reconciled_verdict({})
    assert v["level"] == "MEDIUM"
    # Topean DOS: el perfil de resolucion (NOT_RUN, Fase 21) y el sello (no evaluable).
    assert set(v["limiting_factors"]) == {"survey_resolution", "high_seal"}
    assert v["components"]["high_seal"]["sealed"] is False
    assert v["components"]["high_seal"]["status"] == "NOT_MEASURABLE"


def test_the_demoted_priority_class_is_published_with_the_level_it_would_have_imposed():
    """FASE 30 — degradar una señal no puede ser hacerla desaparecer.

    `priority_class` dejó de topear, pero el reporte publica (a) su valor, (b) su papel
    declarado y (c) **el nivel que habría aportado**. Sin (c) la degradación sería un
    silencio: nadie podría ver, desde el reporte, qué habría pasado si siguiera contando.
    Es el mismo criterio por el que la Fase 26 siguió publicando `checkerboard_pearson_r`
    tras quitarle el poder de topear — la constancia de ese número ES la evidencia.

    El caso elegido es el más severo posible: `UNCLASSIFIED` mapea a LOW, así que bajo las
    reglas anteriores esta corrida —impecable en todo lo demás— habría salido LOW.
    """
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "UNCLASSIFIED",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": PISO_LIMPIO},
        "resolution_qa": _resolution_ok(),
    }
    v = build_reconciled_verdict(p)

    assert v["components"]["priority_class"] == "UNCLASSIFIED"
    assert v["components"]["priority_class_level_not_applied"] == "LOW"
    # Publicar no es aplicar: no entra en el worst-of ni en el ledger de señales.
    assert v["level"] == "HIGH"
    assert "priority_class" not in [s["signal"] for s in v["signals"]]


def test_a_low_verdict_never_claims_the_seal_was_satisfied():
    """FASE 30 — la tercera rama de `_verdict_ceiling`, que es la fácil de escribir mal.

    Cuando algo baja el veredicto por debajo de MEDIUM, `capped_by` sólo trae las señales de
    ESE nivel, así que `high_seal` no aparece — aunque haya fallado. Un texto que dedujera de
    esa ausencia que «el sello ya está superado» estaría MINTIENDO justo en la corrida peor.
    """
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        # el sello NO se cumple: exceso de piso 0,9 > 0,5
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": 0.9},
        # …y además el survey no resuelve nada, que baja a LOW y manda antes
        "resolution_qa": dict(_resolution_ok(), resolves_anywhere=False,
                              shallowest_band_resolution_m=None),
    }
    c = build_reconciled_verdict(p)["ceiling"]

    assert c["max_attainable_level"] == "LOW"
    assert c["capped_by"] == ["survey_resolution"]
    assert "tampoco se cumplió" in c["reason"]
    assert "ya está superado" not in c["reason"]
    assert c["high_seal"]["sealed"] is False


def test_a_capped_run_whose_seal_DID_pass_says_so():
    """La rama simétrica: el sello sí se cumplió y quien topea es otra señal. Ahí el texto
    SÍ puede afirmarlo, y tiene que hacerlo — es información accionable distinta."""
    p = {
        "confidence_level": "MEDIUM",
        "model_reliability_level": "MEDIUM_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "floor_mass_excess": PISO_LIMPIO},
        "resolution_qa": _resolution_ok(),
    }
    c = build_reconciled_verdict(p)["ceiling"]

    assert c["max_attainable_level"] == "MEDIUM"
    assert set(c["capped_by"]) == {"survey_confidence", "model_reliability"}
    assert "ya está superado" in c["how_to_lift"]
    assert c["high_seal"]["sealed"] is True
