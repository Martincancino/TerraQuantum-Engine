"""
FASE 21 (ACAD-11) — El veredicto deja de mejorar cuando se mide menos · backend.
================================================================================

Cierra una mentira concreta del veredicto reconciliado B3. El QA de resolución del survey
(checkerboard) topaba el veredicto a MEDIUM cuando devolvía `FAIL`, pero `NOT_RUN` **no
tenía efecto**. Y ese QA es NON-FATAL: `_checkerboard_qa` se traga la excepción y deja
`_cb_qa = None`, de modo que el bloque nunca llega al reporte. Consecuencia:

    **el veredicto podía MEJORAR si se corrían menos diagnósticos.**

En un producto cuyo argumento de venta es la honestidad, eso es lo único inaceptable.

Lo que esta fase hace, en las tres piezas que pide el plan:

  1. `NOT_RUN` topea igual que `FAIL` — DECISIÓN escrita, frente a la alternativa de
     negarse a emitir veredicto: el checkerboard es accesorio y no fatal, y convertir su
     caída en un bloqueo dejaría sin veredicto a una corrida cuya física es válida.
     Topear conserva el worst-of y hace el veredicto MONÓTONO.
  2. El techo se DECLARA (`overall_verdict.ceiling`): hasta dónde se podía llegar, por
     qué, si es estructural y qué haría falta para levantarlo.
  3. El reporte registra CUÁL de las entradas del worst-of fijó el veredicto
     (`overall_verdict.signals` con `is_limiting`, y `decided_by`).

Lo que esta fase **NO** hace: desbloquear `HIGH`. Ver Fase 26 y Fase 30, en ese orden —
`validation/HALLAZGO_2026-08-06_techo_medium.md` advierte que liberarlo antes de que la
señal discrimine sería PEOR que el estado actual (1 de cada 3 realizaciones de ruido
desvía el blanco ~170 m con diagnósticos idénticos).

Gate: una corrida con el checkerboard DESACTIVADO no puede dar un veredicto mejor que la
misma corrida con el checkerboard activado y fallando.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import (
    _VERDICT_ORD,
    apply_reconciled_verdict,
    build_reconciled_verdict,
    run_geophysics_inversion,
)

NX, NY, NZ, BLOCK = 6, 8, 6, 20.0


def _payload_todo_alto(cb: dict | None) -> dict:
    """Payload donde TODAS las demás señales son HIGH: lo único que puede topear es el
    checkerboard. Aísla la variable de esta fase."""
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }
    if cb is not None:
        p["checkerboard_qa"] = cb
    return p


# ═════════════════════════════════════════════════════════════════════════════
# 1. GATE — medir menos no puede mejorar el veredicto
# ═════════════════════════════════════════════════════════════════════════════

def test_not_run_cannot_beat_fail():
    """EL GATE, en su forma más directa: el diagnóstico ausente no puede dar mejor
    veredicto que el diagnóstico presente y fallando."""
    con_fail = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}))
    sin_qa = build_reconciled_verdict(_payload_todo_alto(None))

    assert _VERDICT_ORD[sin_qa["level"]] <= _VERDICT_ORD[con_fail["level"]]
    assert sin_qa["level"] == con_fail["level"] == "MEDIUM"


@pytest.mark.parametrize("cb", [
    None,                                   # la clave no existe (QA non-fatal que reventó)
    {},                                     # existe vacío
    {"status": None},                       # existe sin status
    {"status": ""},                         # status vacío
    {"status": "NOT_RUN"},                  # declarado explícitamente
    {"status": "SOMETHING_UNEXPECTED"},     # estado que nadie previó
])
def test_every_flavour_of_not_measured_caps_to_medium(cb):
    """`PASS`/`WARNING` son evidencia medida; TODO lo demás se trata como no medido.

    Incluye el estado inesperado a propósito: si mañana alguien agrega un status nuevo, el
    default seguro es topear, no dejar el techo libre por descuido.
    """
    v = build_reconciled_verdict(_payload_todo_alto(cb))
    assert v["level"] == "MEDIUM"
    assert v["ceiling"]["max_attainable_level"] == "MEDIUM"


@pytest.mark.parametrize("status,esperado", [
    ("PASS", "HIGH"),
    ("WARNING", "HIGH"),
    ("FAIL", "MEDIUM"),
    ("NOT_RUN", "MEDIUM"),
])
def test_the_verdict_is_monotone_in_the_evidence(status, esperado):
    """Ordena: sólo la evidencia medida y suficiente deja el techo libre."""
    v = build_reconciled_verdict(_payload_todo_alto({"status": status, "pearson_r": 0.5}))
    assert v["level"] == esperado


def test_not_run_and_fail_are_distinguishable_even_capping_the_same():
    """Topean igual pero NO se confunden: el reporte dice cuál de los dos fue."""
    fail = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}))
    nada = build_reconciled_verdict(_payload_todo_alto(None))

    assert fail["limiting_factors"] == ["checkerboard_resolution"]
    assert nada["limiting_factors"] == ["checkerboard_not_run"]
    assert fail["components"]["checkerboard_qa"] == "FAIL"
    assert nada["components"]["checkerboard_qa"] == "NOT_RUN"
    # Y el motivo del techo NO es el mismo texto: uno habla del examen, otro de su ausencia.
    assert fail["ceiling"]["reason"] != nada["ceiling"]["reason"]
    assert fail["ceiling"]["structural"] is True        # más dato no lo levanta
    assert nada["ceiling"]["structural"] is False       # correr el QA sí puede cambiarlo


# ═════════════════════════════════════════════════════════════════════════════
# 2. El techo se DECLARA — y dice por qué
# ═════════════════════════════════════════════════════════════════════════════

def test_ceiling_explains_itself_with_the_measured_evidence():
    v = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}))
    c = v["ceiling"]

    assert c["max_attainable_level"] == "MEDIUM"
    assert c["capped_by"] == ["checkerboard_resolution"]
    assert c["structural"] is True
    # El motivo trae el número medido y el umbral, no un adjetivo.
    assert "0,1162" in c["reason"] and "0,60" in c["reason"]
    assert "no depende" in c["reason"]
    assert "Recolectar más dato NO lo levanta" in c["reason"]
    # Y dice qué haría falta, en el orden correcto (Fase 26 antes que Fase 30).
    assert "DESPUÉS" in c["how_to_lift"]
    assert "170 m" in c["how_to_lift"] and "285 m" in c["how_to_lift"]
    assert c["evidence"] == "validation/HALLAZGO_2026-08-06_techo_medium.md"


def test_ceiling_is_high_when_the_qa_actually_passes():
    """El techo no es un adorno fijo: con evidencia suficiente queda libre."""
    c = build_reconciled_verdict(_payload_todo_alto({"status": "PASS", "pearson_r": 0.72}))["ceiling"]
    assert c["max_attainable_level"] == "HIGH"
    assert c["capped_by"] == []
    assert c["structural"] is False
    assert c["how_to_lift"] is None


def test_headline_says_the_top_level_was_unavailable():
    """El usuario lee el titular, no el JSON. «MEDIUM» a secas se lee como "confianza
    media"; lo que el sistema quiere decir es que el nivel superior no estaba disponible."""
    v = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}))
    assert "HIGH no estaba disponible" in v["headline"]
    assert "checkerboard" in v["headline"]

    limpio = build_reconciled_verdict(_payload_todo_alto({"status": "PASS", "pearson_r": 0.8}))
    assert "HIGH no estaba disponible" not in limpio["headline"]


def test_pearson_r_travels_with_the_components():
    """El número que produjo el FAIL queda auditable junto al status."""
    v = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}))
    assert v["components"]["checkerboard_pearson_r"] == pytest.approx(0.1162)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Cuál de las entradas del worst-of MANDÓ
# ═════════════════════════════════════════════════════════════════════════════

def test_signal_ledger_names_the_entry_that_decided():
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11})
    p["priority_class"] = "UNCLASSIFIED"          # LOW: éste manda, no el checkerboard
    v = build_reconciled_verdict(p)

    assert v["level"] == "LOW"
    assert v["decided_by"] == ["priority_class"]

    por_nombre = {s["signal"]: s for s in v["signals"]}
    assert por_nombre["priority_class"]["level"] == "LOW"
    assert por_nombre["priority_class"]["is_limiting"] is True
    # El checkerboard aportó, pero NO mandó: aparece con su nivel y sin la marca.
    assert por_nombre["checkerboard_resolution"]["level"] == "MEDIUM"
    assert por_nombre["checkerboard_resolution"]["is_limiting"] is False
    # Las señales HIGH también quedan registradas: el ledger es completo, no una lista
    # de culpables.
    assert por_nombre["survey_confidence"]["level"] == "HIGH"


def test_signal_ledger_is_sorted_by_severity():
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11})
    p["priority_class"] = "UNCLASSIFIED"
    niveles = [_VERDICT_ORD[s["level"]] for s in build_reconciled_verdict(p)["signals"]]
    assert niveles == sorted(niveles)


def test_ties_are_all_reported_as_limiting():
    """El worst-of puede empatar: se nombran TODAS las entradas que fijaron el mínimo."""
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11})
    p["model_reliability_level"] = "MEDIUM_RELIABILITY"
    v = build_reconciled_verdict(p)
    assert v["level"] == "MEDIUM"
    assert set(v["decided_by"]) == {"model_reliability", "checkerboard_resolution"}
    assert v["decided_by"] == v["limiting_factors"]


def test_ledger_and_decided_by_survive_apply():
    """`apply_reconciled_verdict` adjunta el veredicto completo al payload persistido."""
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11})
    apply_reconciled_verdict(p)
    ov = p["overall_verdict"]
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert ov["decided_by"] == ["checkerboard_resolution"]
    assert any(s["is_limiting"] for s in ov["signals"])


# ═════════════════════════════════════════════════════════════════════════════
# 4. E2E — por el motor real, con el QA sano y con el QA caído
# ═════════════════════════════════════════════════════════════════════════════

def _gravity_input(run_id: str) -> GeophysicsInvertInput:
    from exploration.gravimetry import GravimetryForward

    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    r = np.sqrt((x_c - NX * BLOCK / 2) ** 2 + (y_c - 70.0) ** 2 + (z_c - NZ * BLOCK / 2) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(
        np.arange(5, NX * BLOCK, BLOCK), np.arange(5, NZ * BLOCK, BLOCK), indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    return GeophysicsInvertInput(
        project_id="pytest_f21", run_id=run_id,
        depth=int(NY * BLOCK), nir=83, fe=79, region="norte_chile",
        lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BLOCK), cutoff_radius=int(NX * BLOCK * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
    )


@pytest.fixture
def checkerboard_caido(monkeypatch):
    """El QA de resolución revienta. Es NON-FATAL: la corrida sigue y hasta la Fase 21
    salía SIN el bloque `checkerboard_qa` — y por tanto sin techo."""
    import services.geophysics_service as svc

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético del checkerboard QA")

    monkeypatch.setattr(svc, "_run_checkerboard_qa_fast", _boom)


def test_e2e_disabling_the_checkerboard_does_not_improve_the_verdict(monkeypatch):
    """GATE E2E, literal — mismo mundo, mismo survey, misma configuración; lo único que
    cambia es si el QA de resolución llegó a calcularse.

    Antes de la Fase 21 la corrida SIN diagnóstico salía con el techo libre y la corrida
    CON diagnóstico (que falla siempre) salía capada: medir menos daba mejor veredicto.
    """
    import services.geophysics_service as svc

    sana = run_geophysics_inversion(_gravity_input("f21_gate_con_qa"))["report"]

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético del checkerboard QA")

    monkeypatch.setattr(svc, "_run_checkerboard_qa_fast", _boom)
    caida = run_geophysics_inversion(_gravity_input("f21_gate_sin_qa"))["report"]

    assert sana["checkerboard_qa"]["status"] == "FAIL"
    assert "checkerboard_qa" not in caida

    nivel_sana = sana["overall_verdict"]["level"]
    nivel_caida = caida["overall_verdict"]["level"]
    assert _VERDICT_ORD[nivel_caida] <= _VERDICT_ORD[nivel_sana], (
        f"medir menos mejoró el veredicto: sin QA={nivel_caida} > con QA={nivel_sana}")

    techo_sana = sana["overall_verdict"]["ceiling"]["max_attainable_level"]
    techo_caida = caida["overall_verdict"]["ceiling"]["max_attainable_level"]
    assert _VERDICT_ORD[techo_caida] <= _VERDICT_ORD[techo_sana] == _VERDICT_ORD["MEDIUM"]


def test_e2e_healthy_run_is_capped_and_says_so():
    rep = run_geophysics_inversion(_gravity_input("f21_e2e_sano"))["report"]
    ov = rep["overall_verdict"]

    # El QA corrió y falló (es lo que hace SIEMPRE: el examen es sub-resolución).
    assert rep["checkerboard_qa"]["status"] == "FAIL"
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert "checkerboard_resolution" in ov["ceiling"]["capped_by"]
    assert ov["level"] in ("MEDIUM", "LOW")
    assert any(s["signal"] == "checkerboard_resolution" for s in ov["signals"])


def test_e2e_broken_qa_run_is_capped_too(checkerboard_caido):
    """La corrida cuyo QA reventó: antes salía con el techo LIBRE; ahora queda capada,
    con el motivo correcto (no se midió) y sin fingir que el examen se aprobó."""
    rep = run_geophysics_inversion(_gravity_input("f21_e2e_caido"))["report"]
    ov = rep["overall_verdict"]

    assert "checkerboard_qa" not in rep            # el bloque efectivamente no llegó
    assert ov["components"]["checkerboard_qa"] == "NOT_RUN"
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert ov["ceiling"]["capped_by"] == ["checkerboard_not_run"]
    assert ov["level"] in ("MEDIUM", "LOW")
    assert _VERDICT_ORD[ov["level"]] <= _VERDICT_ORD["MEDIUM"]


# ═════════════════════════════════════════════════════════════════════════════
# 5. El techo llega a los entregables (reporte HTML, ZIP industrial, copiloto)
# ═════════════════════════════════════════════════════════════════════════════

def test_html_verdict_section_renders_the_ceiling_and_the_ledger():
    from reporting.report_generator import _reconciled_verdict_section_html

    v = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}))
    html = _reconciled_verdict_section_html(v)

    assert "Techo del Veredicto" in html
    assert "Entradas del Worst-Of" in html
    assert "fij" in html                            # la marca de "fijó el veredicto"
    assert "checkerboard_resolution" in html
    assert "0,1162" in html or "0.1162" in html


def test_html_verdict_section_tolerates_a_legacy_verdict_without_ceiling():
    """Reportes anteriores a la Fase 21 no traen `ceiling` ni `signals`: se siguen
    dibujando, sin secciones fantasma."""
    from reporting.report_generator import _reconciled_verdict_section_html

    html = _reconciled_verdict_section_html({
        "level": "MEDIUM", "limiting_factors": ["priority_class"],
        "components": {"survey_confidence": "MEDIUM"},
        "headline": "titular", "recommended_action": "acción", "note": "nota",
    })
    assert "Veredicto Reconciliado" in html
    assert "Techo del Veredicto" not in html
    assert "Entradas del Worst-Of" not in html


def test_industrial_manifest_carries_the_qa_and_the_ceiling(tmp_path, monkeypatch):
    """El manifiesto del ZIP leía `report['checkerboard_pearson_r']`, una clave que NADIE
    escribe: el cliente recibía `pearson_r: null` y ningún status. Se afirma sobre el
    manifiesto CONSTRUIDO, no sobre el código fuente."""
    import services.block_model_store as store
    monkeypatch.setattr(store, "PROJECTS_DIR", tmp_path / "projects")
    from services.export_service import _build_bundle_manifest

    report = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162,
                                 "sign_recovery_pct": 51.3})
    apply_reconciled_verdict(report)
    report["technicalSummary"] = {"overall_level": "MEDIUM"}
    report["fitDiagnostics"] = {"fit_level": "ACCEPTABLE"}

    man = _build_bundle_manifest("p", "r", {"nx": 6, "ny": 8, "nz": 6}, report, "hash")
    cb = man["checkerboard_qa"]

    assert cb["pearson_r"] == pytest.approx(0.1162)     # antes: None, siempre
    assert cb["status"] == "FAIL"
    assert cb["sign_recovery_pct"] == pytest.approx(51.3)
    assert cb["verdict_ceiling"] == "MEDIUM"
    assert "0,1162" in cb["verdict_ceiling_reason"]


def test_industrial_manifest_says_not_run_when_the_qa_did_not_run():
    """Sin bloque de QA el manifiesto dice NOT_RUN, no un hueco silencioso."""
    import services.export_service as export_service

    report = _payload_todo_alto(None)
    apply_reconciled_verdict(report)
    man = export_service._build_bundle_manifest("p", "r", {}, report, "hash")

    assert man["checkerboard_qa"]["status"] == "NOT_RUN"
    assert man["checkerboard_qa"]["pearson_r"] is None
    assert man["checkerboard_qa"]["verdict_ceiling"] == "MEDIUM"


def test_copilot_trilogy_states_the_ceiling():
    """El copiloto no puede decir «MEDIUM» sin decir hasta dónde se podía llegar."""
    from api.chat_api import _format_trilogy

    payload = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162})
    apply_reconciled_verdict(payload)
    texto = _format_trilogy(payload)

    assert "Techo alcanzable en esta corrida: MEDIUM" in texto
    assert "checkerboard_resolution" in texto
    assert "Por qué ese techo:" in texto
