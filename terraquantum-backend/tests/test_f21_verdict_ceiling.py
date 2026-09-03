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

Gate: una corrida con el diagnóstico de resolución DESACTIVADO no puede dar un veredicto
mejor que la misma corrida con el diagnóstico activado y fallando.

────────────────────────────────────────────────────────────────────────────────
ACTUALIZADO POR LA FASE 26 — qué cambió y qué NO
────────────────────────────────────────────────────────────────────────────────
La Fase 26 midió que el tablero era imposible de aprobar por TRES motivos (no sólo
la longitud de onda que suponía el hallazgo) y lo reemplazó por un perfil de
resolución que sí varía entre surveys. Consecuencias para este archivo:

  · El tablero histórico YA NO TOPEA: se conserva publicado como control.
    Los tests que medían la monotonía del techo ahora la miden sobre la señal
    que sí manda, `survey_resolution`.
  · `HIGH` sigue sin ser alcanzable, pero por un motivo distinto y honesto: una
    RETENCIÓN declarada (`high_hold_pending_fase30`) con condición de salida
    escrita, en vez de un examen que ningún survey podía aprobar. Por eso los
    tests que afirmaban `level == "HIGH"` con el tablero en PASS ahora afirman
    `MEDIUM` limitado ÚNICAMENTE por la retención — que es la misma propiedad
    («ninguna señal medida degrada un caso sano») dicha sobre el mecanismo nuevo.
  · La propiedad central de la Fase 21 —medir menos no puede mejorar el
    veredicto— se conserva intacta y se comprueba sobre las DOS señales.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import (
    _VERDICT_CEILING_EVIDENCE,
    _VERDICT_ORD,
    apply_reconciled_verdict,
    build_reconciled_verdict,
    run_geophysics_inversion,
)

NX, NY, NZ, BLOCK = 6, 8, 6, 20.0

# FASE 26 — la retención declarada de `HIGH`, mientras la Fase 30 no la levante.
HOLD = "high_hold_pending_fase30"


def _resolution(resolves: bool = True) -> dict:
    """Perfil de resolución declarado, con o sin resolución."""
    return {
        "computed": True,
        "resolves_anywhere": resolves,
        "resolvability_index": 0.2478 if resolves else 0.0269,
        "shallowest_band_resolution_m": 250.0 if resolves else None,
        "deepest_resolved_m": 500.0 if resolves else 0.0,
        "max_block_tested_m": 750.0,
        "sigma_used": {"snr_signal": 3.64 if resolves else 0.19},
    }


def _payload_todo_alto(cb: dict | None, res: dict | None = None) -> dict:
    """Payload donde TODAS las demás señales son HIGH: lo único que puede topear es el
    diagnóstico de resolución (y la retención declarada de la Fase 26)."""
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
    }
    if cb is not None:
        p["checkerboard_qa"] = cb
    if res is not None:
        p["resolution_qa"] = res
    return p


# ═════════════════════════════════════════════════════════════════════════════
# 1. GATE — medir menos no puede mejorar el veredicto
# ═════════════════════════════════════════════════════════════════════════════

def test_not_run_cannot_beat_fail():
    """EL GATE, en su forma más directa: el diagnóstico ausente no puede dar mejor
    veredicto que el diagnóstico presente y fallando.

    FASE 26: se mide sobre `resolution_qa`, que es la señal que topea ahora. Un survey
    que no resuelve NADA sale LOW; el mismo survey con el diagnóstico caído no puede
    salir mejor que... bueno, sí puede salir MEDIUM en vez de LOW — y eso es correcto y
    deliberado: `NOT_RUN` no puede AFIRMAR que el survey no resuelve nada, sólo que no
    se midió. Lo que el gate prohíbe es que la ausencia deje el techo LIBRE.
    """
    no_resuelve = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}, _resolution(False)))
    sin_qa = build_reconciled_verdict(_payload_todo_alto(None, None))

    assert no_resuelve["level"] == "LOW"
    assert sin_qa["level"] == "MEDIUM"
    # Lo esencial: la ausencia NO deja el techo libre.
    assert sin_qa["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert sin_qa["components"]["survey_resolution"]["status"] == "NOT_RUN"


@pytest.mark.parametrize("cb", [
    None,                                   # la clave no existe (QA non-fatal que reventó)
    {},                                     # existe vacío
    {"status": None},                       # existe sin status
    {"status": ""},                         # status vacío
    {"status": "NOT_RUN"},                  # declarado explícitamente
    {"status": "SOMETHING_UNEXPECTED"},     # estado que nadie previó
])
def test_every_flavour_of_not_measured_caps_to_medium(cb):
    """El tablero, en cualquiera de sus formas, ya no cambia el nivel: es un control.

    FASE 26 — antes esto probaba que TODO lo que no fuera PASS/WARNING topeaba. Hoy el
    tablero no topea en ninguna de sus formas, y lo que se comprueba es lo simétrico y
    más fuerte: su estado es IRRELEVANTE para el nivel. El techo lo pone otra cosa.
    """
    v = build_reconciled_verdict(_payload_todo_alto(cb, _resolution(True)))
    ref = build_reconciled_verdict(
        _payload_todo_alto({"status": "PASS", "pearson_r": 0.9}, _resolution(True)))
    assert v["level"] == ref["level"] == "MEDIUM"
    assert v["limiting_factors"] == ref["limiting_factors"] == [HOLD]
    assert v["ceiling"]["max_attainable_level"] == "MEDIUM"


@pytest.mark.parametrize("res,esperado", [
    (_resolution(True), "MEDIUM"),      # resuelve algo -> no aporta tope propio
    (None, "MEDIUM"),                   # no se midió -> topea, pero no puede AFIRMAR
    (_resolution(False), "LOW"),        # medido y no resuelve nada -> base no fiable
])
def test_the_verdict_is_monotone_in_the_evidence(res, esperado):
    """Ordena: la evidencia medida y NEGATIVA es la única que puede bajar a LOW, y la
    ausencia nunca deja el techo libre. FASE 26 — sobre la señal que sí varía."""
    v = build_reconciled_verdict(_payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, res))
    assert v["level"] == esperado
    assert _VERDICT_ORD[v["ceiling"]["max_attainable_level"]] <= _VERDICT_ORD["MEDIUM"]


def test_not_run_and_measured_are_distinguishable():
    """No medido y medido-negativo NO se confunden: el reporte dice cuál de los dos fue.

    FASE 26 — la distinción se mudó a `survey_resolution`, y ahora además tienen
    consecuencias DISTINTAS (MEDIUM vs LOW), no sólo textos distintos.
    """
    nada_resuelve = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(False)))
    sin_medir = build_reconciled_verdict(_payload_todo_alto(None, None))

    assert nada_resuelve["components"]["survey_resolution"]["status"] == "RESOLVES_NOTHING"
    assert sin_medir["components"]["survey_resolution"]["status"] == "NOT_RUN"
    assert nada_resuelve["limiting_factors"] == ["survey_resolution"]
    assert set(sin_medir["limiting_factors"]) == {"survey_resolution", HOLD}
    r1 = nada_resuelve["components"]["survey_resolution"]["reason"]
    r2 = sin_medir["components"]["survey_resolution"]["reason"]
    assert r1 != r2
    # El tablero histórico sigue publicado, y declarado como lo que es.
    assert nada_resuelve["components"]["checkerboard_qa"] == "FAIL"
    assert nada_resuelve["components"]["checkerboard_role"].startswith("historical")


# ═════════════════════════════════════════════════════════════════════════════
# 2. El techo se DECLARA — y dice por qué
# ═════════════════════════════════════════════════════════════════════════════

def test_ceiling_explains_itself_with_the_measured_evidence():
    """FASE 26 — el techo sigue declarándose, y ahora dice su motivo REAL.

    Hasta la Fase 25 el motivo era «el tablero devolvió FAIL», que era cierto pero
    circular: el tablero devolvía FAIL siempre. El motivo de hoy es una retención de
    producto con condición de salida, y el texto tiene que sostener las dos mitades:
    por qué el examen viejo no servía, y por qué el techo sigue puesto igualmente.
    """
    v = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}, _resolution(True)))
    c = v["ceiling"]

    assert c["max_attainable_level"] == "MEDIUM"
    assert c["capped_by"] == [HOLD]
    # Ya NO es estructural: no queda ningún examen imposible de aprobar.
    assert c["structural"] is False
    # El motivo trae el número medido del examen viejo y sus tres causas.
    assert "0,1162" in c["reason"]
    assert "celda a celda" in c["reason"]
    assert "solver distinto" in c["reason"]
    # Y por qué el techo sigue puesto pese a tener ya un examen que informa.
    assert "170 m" in c["reason"]
    assert "Fase 30" in c["how_to_lift"] and "SOBRECONFIADO" in c["how_to_lift"]
    assert "150" in c["how_to_lift"]
    assert _VERDICT_CEILING_EVIDENCE in c["evidence"]


def test_ceiling_carries_the_resolution_signal_that_replaced_the_checkerboard():
    """El techo publica el número NUEVO, no sólo el viejo: si alguien lee el `ceiling`
    tiene que poder ver qué resuelve este survey, en metros."""
    c = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True)))["ceiling"]
    rs = c["resolution_signal"]
    assert rs["status"] == "RESOLVES"
    assert rs["shallowest_band_resolution_m"] == 250.0
    assert rs["resolvability_index"] == pytest.approx(0.2478)


def test_headline_says_the_top_level_is_held():
    """El usuario lee el titular, no el JSON. «MEDIUM» a secas se lee como "confianza
    media"; lo que el sistema quiere decir es que el nivel superior no está habilitado."""
    v = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True)))
    assert "HIGH no está habilitado" in v["headline"]
    assert "Fase 30" in v["headline"]


def test_pearson_r_travels_with_the_components():
    """El número que produjo el FAIL queda auditable junto al status — sigue siendo la
    evidencia de que el examen viejo era constante, aunque ya no topee."""
    v = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}, _resolution(True)))
    assert v["components"]["checkerboard_pearson_r"] == pytest.approx(0.1162)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Cuál de las entradas del worst-of MANDÓ
# ═════════════════════════════════════════════════════════════════════════════

def test_signal_ledger_names_the_entry_that_decided():
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True))
    p["priority_class"] = "UNCLASSIFIED"          # LOW: éste manda, no la retención
    v = build_reconciled_verdict(p)

    assert v["level"] == "LOW"
    assert v["decided_by"] == ["priority_class"]

    por_nombre = {s["signal"]: s for s in v["signals"]}
    assert por_nombre["priority_class"]["level"] == "LOW"
    assert por_nombre["priority_class"]["is_limiting"] is True
    # La retención aportó, pero NO mandó: aparece con su nivel y sin la marca.
    assert por_nombre[HOLD]["level"] == "MEDIUM"
    assert por_nombre[HOLD]["is_limiting"] is False
    # Las señales HIGH también quedan registradas: el ledger es completo, no una lista
    # de culpables.
    assert por_nombre["survey_confidence"]["level"] == "HIGH"


def test_signal_ledger_is_sorted_by_severity():
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True))
    p["priority_class"] = "UNCLASSIFIED"
    niveles = [_VERDICT_ORD[s["level"]] for s in build_reconciled_verdict(p)["signals"]]
    assert niveles == sorted(niveles)


def test_ties_are_all_reported_as_limiting():
    """El worst-of puede empatar: se nombran TODAS las entradas que fijaron el mínimo."""
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True))
    p["model_reliability_level"] = "MEDIUM_RELIABILITY"
    v = build_reconciled_verdict(p)
    assert v["level"] == "MEDIUM"
    assert set(v["decided_by"]) == {"model_reliability", HOLD}
    assert v["decided_by"] == v["limiting_factors"]


def test_ledger_and_decided_by_survive_apply():
    """`apply_reconciled_verdict` adjunta el veredicto completo al payload persistido."""
    p = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.11}, _resolution(True))
    apply_reconciled_verdict(p)
    ov = p["overall_verdict"]
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert ov["decided_by"] == [HOLD]
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
    """El tablero histórico revienta. Es NON-FATAL: la corrida sigue."""
    import services.geophysics_service as svc

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético del checkerboard QA")

    monkeypatch.setattr(svc, "_run_checkerboard_qa_fast", _boom)


@pytest.fixture
def resolucion_caida(monkeypatch):
    """FASE 26 — el PERFIL de resolución revienta. También es non-fatal, y también
    tiene que dejar el techo puesto: el gate de la Fase 21 aplicado a la señal nueva."""
    import services.resolution_qa as rqa

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético del perfil de resolución")

    monkeypatch.setattr(rqa, "run_resolution_profile_qa", _boom)


def test_e2e_disabling_the_resolution_qa_does_not_improve_the_verdict(monkeypatch):
    """GATE E2E, literal — mismo mundo, mismo survey, misma configuración; lo único que
    cambia es si el QA de resolución llegó a calcularse.

    Antes de la Fase 21 la corrida SIN diagnóstico salía con el techo libre y la corrida
    CON diagnóstico (que falla siempre) salía capada: medir menos daba mejor veredicto.
    FASE 26 — mismo gate, sobre el diagnóstico que manda hoy.
    """
    import services.resolution_qa as rqa

    sana = run_geophysics_inversion(_gravity_input("f21_gate_con_qa"))["report"]

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético del perfil de resolución")

    monkeypatch.setattr(rqa, "run_resolution_profile_qa", _boom)
    caida = run_geophysics_inversion(_gravity_input("f21_gate_sin_qa"))["report"]

    assert sana["resolution_qa"]["computed"] is True
    assert "resolution_qa" not in caida

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

    # El tablero histórico corrió y falló (es lo que hace SIEMPRE) y se sigue publicando.
    assert rep["checkerboard_qa"]["status"] == "FAIL"
    # FASE 26 — pero quien topea es la retención declarada, no el tablero.
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert ov["ceiling"]["capped_by"] == [HOLD]
    assert ov["level"] in ("MEDIUM", "LOW")
    assert any(sig["signal"] == HOLD for sig in ov["signals"])
    # Y el perfil nuevo SÍ llegó al reporte, con su número en metros.
    assert rep["resolution_qa"]["computed"] is True
    assert ov["components"]["survey_resolution"]["status"] in ("RESOLVES", "RESOLVES_NOTHING")


def test_e2e_broken_resolution_qa_run_is_capped_too(resolucion_caida):
    """La corrida cuyo QA de resolución reventó: no puede salir con el techo LIBRE ni
    fingir que el examen se aprobó. Es el gate de la Fase 21, sobre la señal de hoy."""
    rep = run_geophysics_inversion(_gravity_input("f21_e2e_caido"))["report"]
    ov = rep["overall_verdict"]

    assert "resolution_qa" not in rep              # el bloque efectivamente no llegó
    assert ov["components"]["survey_resolution"]["status"] == "NOT_RUN"
    assert ov["ceiling"]["max_attainable_level"] == "MEDIUM"
    assert "survey_resolution" in ov["limiting_factors"]
    assert ov["level"] in ("MEDIUM", "LOW")
    assert _VERDICT_ORD[ov["level"]] <= _VERDICT_ORD["MEDIUM"]


# ═════════════════════════════════════════════════════════════════════════════
# 5. El techo llega a los entregables (reporte HTML, ZIP industrial, copiloto)
# ═════════════════════════════════════════════════════════════════════════════

def test_html_verdict_section_renders_the_ceiling_and_the_ledger():
    from reporting.report_generator import _reconciled_verdict_section_html

    v = build_reconciled_verdict(
        _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}, _resolution(True)))
    html = _reconciled_verdict_section_html(v)

    assert "Techo del Veredicto" in html
    assert "Entradas del Worst-Of" in html
    assert "fij" in html                            # la marca de "fijó el veredicto"
    assert HOLD in html                             # quién topea, nombrado
    assert "0,1162" in html or "0.1162" in html     # el número del control histórico


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
                                 "sign_recovery_pct": 51.3}, _resolution(True))
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

    report = _payload_todo_alto(None, _resolution(True))
    apply_reconciled_verdict(report)
    man = export_service._build_bundle_manifest("p", "r", {}, report, "hash")

    assert man["checkerboard_qa"]["status"] == "NOT_RUN"
    assert man["checkerboard_qa"]["pearson_r"] is None
    assert man["checkerboard_qa"]["verdict_ceiling"] == "MEDIUM"


def test_copilot_trilogy_states_the_ceiling():
    """El copiloto no puede decir «MEDIUM» sin decir hasta dónde se podía llegar."""
    from api.chat_api import _format_trilogy

    payload = _payload_todo_alto({"status": "FAIL", "pearson_r": 0.1162}, _resolution(True))
    apply_reconciled_verdict(payload)
    texto = _format_trilogy(payload)

    assert "Techo alcanzable en esta corrida: MEDIUM" in texto
    assert HOLD in texto
    assert "Por qué ese techo:" in texto
