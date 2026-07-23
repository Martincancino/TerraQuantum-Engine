"""F6 — Copiloto IA: grounding + compliance + migración a google-genai.

Suite 100% mockeada (sin gastar tokens ni requerir una API key real). Verifica:
  * Guardrails de compliance JORC/NI 43-101 (redacción de estimaciones de recursos).
  * Guard de anclaje numérico (números inventados detectados; los anclados pasan).
  * Anclaje de la trilogía B1/B2/B3 en el contexto del prompt.
  * Los 3 modos del copiloto (explicar / redactar / enseñar).
  * Wiring del SDK nuevo google-genai (modelo, contents, system_instruction, api_key).
  * BYO-key (cuerpo / header / env) y rechazo honesto sin clave.
  * Migración de gemini_agent.request_gemini_interpretation al SDK nuevo.
"""
import json
from pathlib import Path

import google.genai as _genai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import chat_api
from api.chat_api import (
    _apply_compliance_filter,
    _build_geological_context,
    _call_gemini,
    build_system_instruction,
    find_ungrounded_quantities,
)
from services import gemini_agent


# ─────────────────────────────────────────────────────────────────────────────
# Fake del SDK google-genai (parcheado sobre google.genai.Client).
# ─────────────────────────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _patch_genai(monkeypatch, text, *, cache_name="cachedContents/test", cache_raises=False):
    """Parchea google.genai.Client; devuelve un dict que graba los kwargs de la llamada."""
    rec: dict = {"cache_creates": 0}

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            rec["model"] = model
            rec["contents"] = contents
            rec["config"] = config
            return _FakeResponse(text)

    class _FakeCache:
        name = cache_name

    class _FakeCaches:
        def create(self, *, model, config):
            rec["cache_creates"] += 1
            rec["cache_config"] = config
            if cache_raises:
                raise RuntimeError("cached content is too small")
            return _FakeCache()

    class _FakeClient:
        def __init__(self, *, api_key=None, **kw):
            rec["api_key"] = api_key
            self.models = _FakeModels()
            self.caches = _FakeCaches()

    monkeypatch.setattr(_genai, "Client", _FakeClient)
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Report sintético con "números trampa" para probar el anclaje.
# ─────────────────────────────────────────────────────────────────────────────
def _synthetic_report() -> dict:
    return {
        "priority_class": "MEDIUM_RELATIVE_PRIORITY",
        "model_reliability_level": "MEDIUM_RELIABILITY",
        "risk_level": "HIGH",
        "preliminary_signal": "OBSERVE",
        "max_density": 2.692,
        "misfit_error_percent": 2.07,
        "observationQuality": {
            "observation_count": 121,
            "spatial_span_x": 600.0,
            "spatial_span_z": 600.0,
            "quality_level": "GOOD",
        },
        "fitDiagnostics": {
            "chi_squared_final": 0.264,
            "residual_rmse": 1.9e-07,
            "fit_level": "GOOD",
            "normalized_rmse": 0.0093,
            "lambda_used": 0.1,
        },
        "best_target": {
            "x_m": 14.0, "y_m": 14.0, "z_m": 14.0,
            "depth_m": 14.0, "density": 2.516,
            "relative_target_score": 0.982, "confidence_level": "MEDIUM",
            "is_resolvable_depth": True, "is_null_space_artifact": False,
            "selection_note": "seleccionado por score relativo",
        },
        "depthResolution": {
            "computed": True,
            "resolvable_depth_max_m": 126.0,
            "resolvable_body_depth_m": 14.0,
            "geometric_observable_depth_max_m": 200.0,
            "deep_mass_fraction": 0.433,
            "horizontal_extent_m": 79.8,
            "per_axis": {"horizontal": {"compactness": "broad"}},
            "statement": "Footprint horizontal determinado; profundidad no resuelta.",
        },
        "overall_verdict": {
            "level": "MEDIUM",
            "limiting_factors": ["priority_class"],
            "headline": "Modelo utilizable con cautela.",
            "recommended_action": "Revisar cobertura antes de perforar.",
        },
    }


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(chat_api.router)
    # Aisla el endpoint del disco: report sintético en memoria vía tmp file.
    return TestClient(app)


@pytest.fixture
def report_on_disk(tmp_path, monkeypatch):
    p = tmp_path / "report.json"
    p.write_text(json.dumps(_synthetic_report()), encoding="utf-8")
    monkeypatch.setattr(chat_api, "get_run_report_path", lambda **kw: p)
    monkeypatch.setattr(chat_api, "get_run_inputs_path", lambda **kw: None)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Capa 1 — Compliance.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "El yacimiento tiene 5000 toneladas de cobre.",
    "La ley de 1.2 % es económicamente atractiva.",
    "El VAN de $3M y la TIR de 18% son positivos.",
    "Estimated resource of 10 Mt at high grade.",
])
def test_compliance_redacts_economic_estimates(text):
    out = _apply_compliance_filter(text)
    assert out.startswith("[Respuesta redactada")


@pytest.mark.parametrize("text", [
    "La densidad máxima recuperada es 2.69 t/m³.",
    "El χ² reducido es 0.26, un buen ajuste.",
    "JORC exige que un Competent Person valide los recursos y reservas; por eso "
    "esta herramienta no reporta recursos.",
])
def test_compliance_allows_grounded_and_education(text):
    assert _apply_compliance_filter(text) == text


# ─────────────────────────────────────────────────────────────────────────────
# Capa 2 — Guard de anclaje numérico.
# ─────────────────────────────────────────────────────────────────────────────
_CTX = (
    "Chi2 0.264. Profundidad max resoluble: 126.0 m. "
    "Densidad maxima recuperada: 2.692 t/m3. Blanco x=14.0 m."
)

def test_grounding_flags_fabricated_depth():
    flagged = find_ungrounded_quantities("El cuerpo está a 350 m de profundidad.", _CTX)
    assert "350 m" in flagged

def test_grounding_passes_grounded_numbers():
    assert find_ungrounded_quantities("La profundidad máx. resoluble es 126 m.", _CTX) == []
    assert find_ungrounded_quantities("La densidad es 2.692 t/m³.", _CTX) == []

def test_grounding_flags_fabricated_density():
    flagged = find_ungrounded_quantities("La densidad del cuerpo es 4.8 t/m³.", _CTX)
    assert any("4.8" in q for q in flagged)


# ─────────────────────────────────────────────────────────────────────────────
# System prompt: reglas base + overlay por modo.
# ─────────────────────────────────────────────────────────────────────────────
def test_system_instruction_has_hard_rules():
    si = build_system_instruction("CTX", [])
    assert "nunca lo estimes" in si.lower()
    assert "no-unicidad" in si.lower()
    assert "jorc" in si.lower()

@pytest.mark.parametrize("mode,needle", [
    ("explicar", "MODO EXPLICAR"),
    ("redactar", "BORRADOR"),
    ("ensenar", "MODO ENSEÑAR"),
])
def test_system_instruction_mode_overlay(mode, needle):
    assert needle in build_system_instruction("CTX", [], mode)

def test_system_instruction_includes_warnings():
    si = build_system_instruction("CTX", ["⚠️ ejemplo"])
    assert "ADVERTENCIAS AUTOMÁTICAS" in si and "ejemplo" in si


# ─────────────────────────────────────────────────────────────────────────────
# Anclaje de la trilogía B1/B2/B3 en el contexto.
# ─────────────────────────────────────────────────────────────────────────────
def test_context_anchors_trilogy():
    ctx, warns = _build_geological_context("p", "r", _synthetic_report())
    assert "B1 — TARGETING" in ctx
    assert "B2 — RESOLUCIÓN DE PROFUNDIDAD" in ctx
    assert "B3 — VEREDICTO RECONCILIADO" in ctx
    assert "126.00 m" in ctx           # resolvable_depth_max_m
    assert "MEDIUM" in ctx             # verdict level
    assert "0.433" in ctx              # deep_mass_fraction

def test_context_warns_on_null_space_artifact():
    rep = _synthetic_report()
    rep["best_target"]["is_null_space_artifact"] = True
    _, warns = _build_geological_context("p", "r", rep)
    assert any("NULL-SPACE" in w for w in warns)

def test_context_warns_on_high_chi2():
    rep = _synthetic_report()
    rep["fitDiagnostics"]["chi_squared_final"] = 5.0
    _, warns = _build_geological_context("p", "r", rep)
    assert any("chi²" in w.lower() or "chi2" in w.lower() for w in warns)


# ─────────────────────────────────────────────────────────────────────────────
# Wiring del SDK google-genai.
# ─────────────────────────────────────────────────────────────────────────────
def test_call_gemini_wiring(monkeypatch):
    rec = _patch_genai(monkeypatch, "respuesta")
    out = _call_gemini(
        api_key="KEY123", model="gemini-test",
        system_instruction="SYS", history=[{"role": "user", "content": "hola"}],
        user_message="¿por qué MEDIUM?",
    )
    assert out == "respuesta"
    assert rec["api_key"] == "KEY123"
    assert rec["model"] == "gemini-test"
    assert rec["config"].system_instruction == "SYS"
    # último turno = el mensaje del usuario
    last = rec["contents"][-1]
    assert last.role == "user"
    assert last.parts[0].text == "¿por qué MEDIUM?"


def test_no_toplevel_deprecated_sdk_import():
    """El SDK no debe importarse a nivel de módulo (arranque no depende de él)."""
    src = Path(chat_api.__file__).read_text(encoding="utf-8")
    assert "import google.generativeai" not in src
    # El import del SDK nuevo debe ser perezoso (dentro de una función).
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("from google import genai") or stripped.startswith("import google.genai"):
            assert line.startswith(" "), "El import de google-genai debe ser perezoso (indentado)."


# ─────────────────────────────────────────────────────────────────────────────
# Context caching (opt-in, con fallback).
# ─────────────────────────────────────────────────────────────────────────────
def test_cache_disabled_by_default_uses_inline(monkeypatch):
    monkeypatch.setattr(chat_api, "_CACHE_ENABLED", False)
    monkeypatch.setattr(chat_api, "_cache_registry", {})
    rec = _patch_genai(monkeypatch, "ok")
    chat_api._call_gemini(api_key="K", model="m", system_instruction="SYS", history=[], user_message="hola")
    assert rec["config"].system_instruction == "SYS"
    assert rec["config"].cached_content is None
    assert rec["cache_creates"] == 0

def test_cache_reuse_when_enabled(monkeypatch):
    monkeypatch.setattr(chat_api, "_CACHE_ENABLED", True)
    monkeypatch.setattr(chat_api, "_cache_registry", {})
    rec = _patch_genai(monkeypatch, "ok", cache_name="cachedContents/x1")
    for _ in range(2):
        chat_api._call_gemini(api_key="K", model="m", system_instruction="SYS", history=[], user_message="q")
    assert rec["cache_creates"] == 1  # creada una vez, reusada la 2ª
    assert rec["config"].cached_content == "cachedContents/x1"
    assert rec["config"].system_instruction is None

def test_cache_fallback_on_create_error(monkeypatch):
    monkeypatch.setattr(chat_api, "_CACHE_ENABLED", True)
    monkeypatch.setattr(chat_api, "_cache_registry", {})
    rec = _patch_genai(monkeypatch, "ok", cache_raises=True)
    out = chat_api._call_gemini(api_key="K", model="m", system_instruction="SYS", history=[], user_message="q")
    assert out == "ok"
    assert rec["config"].system_instruction == "SYS"  # cae al inline
    assert rec["config"].cached_content is None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint /api/chat — flujo completo con _call_gemini mockeado.
# ─────────────────────────────────────────────────────────────────────────────
def _payload(**extra):
    base = {
        "project_id": "p", "run_id": "r",
        "messages": [{"role": "user", "content": "¿por qué el veredicto es MEDIUM?"}],
        "api_key": "BYO-KEY",
    }
    base.update(extra)
    return base

def test_endpoint_grounded_response(client, report_on_disk, monkeypatch):
    monkeypatch.setattr(
        chat_api, "_call_gemini",
        lambda **kw: "El veredicto es MEDIUM y la profundidad resoluble es 126 m.",
    )
    r = client.post("/api/chat", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert "126 m" in body["response"]
    assert body["grounding"]["redacted"] is False
    assert body["grounding"]["ungrounded"] == []

def test_endpoint_redacts_tonnage(client, report_on_disk, monkeypatch):
    monkeypatch.setattr(chat_api, "_call_gemini", lambda **kw: "Hay 9000 toneladas de cobre.")
    r = client.post("/api/chat", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["grounding"]["redacted"] is True
    assert "compliance" in body["response"].lower()

def test_endpoint_flags_ungrounded_number(client, report_on_disk, monkeypatch):
    monkeypatch.setattr(
        chat_api, "_call_gemini",
        lambda **kw: "El cuerpo está a exactamente 999 m de profundidad.",
    )
    r = client.post("/api/chat", json=_payload())
    body = r.json()
    assert "999 m" in body["grounding"]["ungrounded"]
    assert "Verificación de anclaje" in body["response"]

def test_endpoint_requires_api_key(client, report_on_disk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/api/chat", json=_payload(api_key=None))
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]

def test_endpoint_byo_key_via_header(client, report_on_disk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    captured = {}
    def _fake(**kw):
        captured.update(kw)
        return "respuesta anclada al χ² 0.26."
    monkeypatch.setattr(chat_api, "_call_gemini", _fake)
    r = client.post("/api/chat", json=_payload(api_key=None), headers={"X-Gemini-Api-Key": "HDR"})
    assert r.status_code == 200
    assert captured["api_key"] == "HDR"

def test_endpoint_redactar_mode_uses_report_model(client, report_on_disk, monkeypatch):
    captured = {}
    def _fake(**kw):
        captured.update(kw)
        return "Borrador de sección de informe."
    monkeypatch.setattr(chat_api, "_call_gemini", _fake)
    r = client.post("/api/chat", json=_payload(mode="redactar"))
    assert r.status_code == 200
    assert captured["model"] == chat_api.GEMINI_REPORT_MODEL


# ─────────────────────────────────────────────────────────────────────────────
# gemini_agent — migración del reporte estructurado al SDK nuevo.
# ─────────────────────────────────────────────────────────────────────────────
_VALID_REPORT_JSON = json.dumps({
    "executive_summary": "Resumen del levantamiento.",
    "anomalies": [],
    "overall_assessment": "Convergencia adecuada.",
    "limitations": "Inversión de campo potencial: no-unicidad inherente.",
})

def test_gemini_agent_no_key_returns_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = gemini_agent.request_gemini_interpretation({})
    assert out["executive_summary"].startswith("Gemini API key not configured")

def test_gemini_agent_parses_and_validates(monkeypatch):
    _patch_genai(monkeypatch, _VALID_REPORT_JSON)
    out = gemini_agent.request_gemini_interpretation({}, api_key="KEY")
    assert out["executive_summary"] == "Resumen del levantamiento."
    assert "regulatory_disclaimer" in out
    assert "error" not in out

def test_gemini_agent_rejects_banned_word(monkeypatch):
    bad = json.dumps({
        "executive_summary": "This body is a high grade mineral resource.",
        "anomalies": [],
        "overall_assessment": "ok",
        "limitations": "non-uniqueness",
    })
    _patch_genai(monkeypatch, bad)
    out = gemini_agent.request_gemini_interpretation({}, api_key="KEY")
    assert "error" in out
    assert out["executive_summary"] == ""

def test_gemini_agent_uses_report_model(monkeypatch):
    rec = _patch_genai(monkeypatch, _VALID_REPORT_JSON)
    gemini_agent.request_gemini_interpretation({}, api_key="KEY")
    from core.config import GEMINI_REPORT_MODEL
    assert rec["model"] == GEMINI_REPORT_MODEL
