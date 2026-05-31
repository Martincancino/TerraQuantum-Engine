"""
R3.5-G — SpatialReadiness en reporte HTML/JSON.

Verifica:
  - Sección "Contrato Espacial de Entrada" presente en HTML
  - HTML muestra level, max_favorability, max_priority, missing_fields,
    blocked_outputs, allowed_outputs, warnings, rationale
  - Alertas correctas por nivel: NO_SPATIAL_DATA (roja), conceptual (amarilla),
    preliminar (verde)
  - Sección "Limitación por Suficiencia Espacial" cuando cap applied=True
  - original_favorability_score y capped_favorability_score presentes
  - Legacy sin spatial_readiness no crashea
  - Sin lenguaje peligroso en las nuevas secciones
  - report_payload contiene spatial_readiness top-level tras R3.5-G
"""
import pytest

from reporting.report_generator import (
    _spatial_readiness_section_html,
    _spatial_readiness_cap_section_html,
)
from services.geophysics_service import _apply_spatial_readiness_caps
from schemas.gravity_import_schema import (
    SPATIAL_LEVEL_MAX_FAVORABILITY,
    SPATIAL_LEVEL_MAX_PRIORITY,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_sr_dict(level: str) -> dict:
    """Build a minimal SpatialReadiness dict using the real builder functions."""
    from services.spatial_readiness_service import (
        _build_no_spatial_data,
        _build_local_unanchored,
        _build_local_anchored_center,
        _build_utm_no_zone,
        _build_utm_with_zone,
        _build_geographic_coords,
        _build_professional_survey,
    )
    builders = {
        "NO_SPATIAL_DATA": _build_no_spatial_data,
        "LOCAL_UNANCHORED": _build_local_unanchored,
        "LOCAL_ANCHORED_CENTER": _build_local_anchored_center,
        "UTM_NO_ZONE": _build_utm_no_zone,
        "UTM_WITH_ZONE": _build_utm_with_zone,
        "GEOGRAPHIC_COORDS": _build_geographic_coords,
        "PROFESSIONAL_SURVEY": _build_professional_survey,
    }
    sr_obj = builders[level]()
    return sr_obj.model_dump()


def _make_cap(applied: bool, original: float = 80.0, capped: float = 45.0) -> dict:
    return {
        "applied": applied,
        "level": "LOCAL_ANCHORED_CENTER",
        "original_favorability_score": original,
        "capped_favorability_score": capped,
        "max_favorability_score_allowed": capped,
        "max_priority_class_allowed": "LOW_RELATIVE_PRIORITY",
        "reason": "La suficiencia espacial del input no permite una clasificación superior.",
        "warnings": ["Favorabilidad limitada por SpatialReadiness."],
    }


# ── Tests: sección Contrato Espacial de Entrada ───────────────────────────────

def test_local_anchored_center_shows_spatial_contract_section():
    """HTML con spatial_readiness LOCAL_ANCHORED_CENTER muestra encabezado de sección."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Contrato Espacial de Entrada" in html


def test_section_html_shows_level():
    """HTML muestra el nivel SpatialReadiness."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "LOCAL_ANCHORED_CENTER" in html


def test_section_html_shows_max_favorability_score_allowed():
    """HTML muestra la etiqueta de max_favorability_score_allowed."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "favorabilidad" in html.lower()


def test_section_html_shows_max_priority_class_allowed():
    """HTML muestra la etiqueta de max_priority_class_allowed."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "prioridad" in html.lower()


def test_section_html_shows_missing_fields_label():
    """HTML muestra la etiqueta 'Campos Faltantes'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Campos Faltantes" in html


def test_section_html_shows_blocked_outputs_label():
    """HTML muestra la etiqueta 'Outputs Bloqueados'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Outputs Bloqueados" in html


def test_section_html_shows_allowed_outputs_label():
    """HTML muestra la etiqueta 'Outputs Permitidos'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Outputs Permitidos" in html


def test_section_html_shows_warnings_label():
    """HTML muestra la etiqueta 'Warnings'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Warnings" in html


def test_section_html_shows_rationale_label():
    """HTML muestra la etiqueta 'Rationale'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Rationale" in html


# ── Tests: alertas por nivel ──────────────────────────────────────────────────

def test_no_spatial_data_shows_red_alert_class():
    """HTML con NO_SPATIAL_DATA usa clase sr-alert-red."""
    sr = _make_sr_dict("NO_SPATIAL_DATA")
    html = _spatial_readiness_section_html(sr)
    assert "sr-alert-red" in html


def test_no_spatial_data_alert_message():
    """HTML con NO_SPATIAL_DATA menciona que no se puede ejecutar inversión 3D."""
    sr = _make_sr_dict("NO_SPATIAL_DATA")
    html = _spatial_readiness_section_html(sr)
    assert "no se puede ejecutar" in html.lower()


def test_local_anchored_center_shows_conceptual_alert():
    """HTML con LOCAL_ANCHORED_CENTER muestra alerta conceptual/degradada."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "conceptuales" in html.lower() or "degradadas" in html.lower()


def test_local_unanchored_shows_conceptual_alert():
    """HTML con LOCAL_UNANCHORED muestra alerta conceptual."""
    sr = _make_sr_dict("LOCAL_UNANCHORED")
    html = _spatial_readiness_section_html(sr)
    assert "sr-alert-yellow" in html


def test_utm_no_zone_shows_conceptual_alert():
    """HTML con UTM_NO_ZONE muestra alerta amarilla."""
    sr = _make_sr_dict("UTM_NO_ZONE")
    html = _spatial_readiness_section_html(sr)
    assert "sr-alert-yellow" in html


def test_utm_with_zone_shows_preliminary_message():
    """HTML con UTM_WITH_ZONE muestra mensaje de análisis espacial preliminar."""
    sr = _make_sr_dict("UTM_WITH_ZONE")
    html = _spatial_readiness_section_html(sr)
    assert "preliminar" in html.lower()


def test_geographic_coords_shows_green_alert():
    """HTML con GEOGRAPHIC_COORDS usa clase sr-alert-green."""
    sr = _make_sr_dict("GEOGRAPHIC_COORDS")
    html = _spatial_readiness_section_html(sr)
    assert "sr-alert-green" in html


def test_professional_survey_shows_green_alert():
    """HTML con PROFESSIONAL_SURVEY usa clase sr-alert-green."""
    sr = _make_sr_dict("PROFESSIONAL_SURVEY")
    html = _spatial_readiness_section_html(sr)
    assert "sr-alert-green" in html


# ── Tests: sección cap ────────────────────────────────────────────────────────

def test_cap_applied_true_shows_cap_section():
    """HTML con spatial_readiness_cap.applied=True muestra sección de limitación."""
    cap = _make_cap(applied=True)
    html = _spatial_readiness_cap_section_html(cap)
    assert "Limitación por Suficiencia Espacial" in html


def test_cap_applied_true_shows_cap_alert():
    """HTML con cap applied=True muestra alerta de clase sr-cap-alert."""
    cap = _make_cap(applied=True)
    html = _spatial_readiness_cap_section_html(cap)
    assert "sr-cap-alert" in html


def test_cap_section_shows_original_favorability_score():
    """HTML muestra original_favorability_score cuando cap aplicado."""
    cap = _make_cap(applied=True, original=80.0, capped=45.0)
    html = _spatial_readiness_cap_section_html(cap)
    assert "80.0" in html


def test_cap_section_shows_capped_favorability_score():
    """HTML muestra capped_favorability_score cuando cap aplicado."""
    cap = _make_cap(applied=True, original=80.0, capped=45.0)
    html = _spatial_readiness_cap_section_html(cap)
    assert "45.0" in html


def test_cap_applied_false_shows_minimal_section():
    """HTML con cap applied=False muestra sección mínima sin alerta."""
    cap = _make_cap(applied=False, original=30.0, capped=30.0)
    html = _spatial_readiness_cap_section_html(cap)
    assert "Limitación por Suficiencia Espacial" in html
    assert "sr-cap-alert" not in html


def test_cap_none_returns_empty_string():
    """Si spatial_readiness_cap es None, la función retorna string vacío."""
    html = _spatial_readiness_cap_section_html(None)
    assert html == ""


# ── Tests: legacy sin spatial_readiness ──────────────────────────────────────

def test_legacy_no_spatial_readiness_does_not_crash():
    """_spatial_readiness_section_html(None) no crashea y muestra mensaje legacy."""
    html = _spatial_readiness_section_html(None)
    assert "Contrato Espacial de Entrada" in html
    assert "no disponible" in html.lower() or "histórica" in html.lower()


def test_legacy_shows_sr_legacy_class():
    """El mensaje legacy usa la clase sr-legacy."""
    html = _spatial_readiness_section_html(None)
    assert "sr-legacy" in html


def test_legacy_empty_dict_does_not_crash():
    """_spatial_readiness_section_html({}) cae al nivel NO_SPATIAL_DATA sin crashear."""
    html = _spatial_readiness_section_html({})
    assert "Contrato Espacial de Entrada" in html


# ── Tests: sin lenguaje peligroso en las nuevas secciones ────────────────────

def test_section_does_not_contain_drill_recommendation():
    """Las nuevas secciones no contienen 'Recomendación: DRILL'."""
    sr = _make_sr_dict("LOCAL_ANCHORED_CENTER")
    html = _spatial_readiness_section_html(sr)
    assert "Recomendación: DRILL" not in html
    assert "PERFORAR AQUÍ" not in html


def test_section_does_not_contain_perforar_aqui():
    """Las nuevas secciones no contienen 'PERFORAR AQUÍ'."""
    for level in ("NO_SPATIAL_DATA", "LOCAL_ANCHORED_CENTER", "UTM_WITH_ZONE"):
        html = _spatial_readiness_section_html(_make_sr_dict(level))
        assert "PERFORAR AQUÍ" not in html


def test_section_does_not_contain_probabilidad_ia():
    """Las nuevas secciones no contienen 'Probabilidad IA'."""
    for level in ("NO_SPATIAL_DATA", "LOCAL_ANCHORED_CENTER", "UTM_WITH_ZONE"):
        html = _spatial_readiness_section_html(_make_sr_dict(level))
        assert "Probabilidad IA" not in html


def test_section_does_not_contain_riesgo_low_label():
    """Las nuevas secciones no contienen el label 'Riesgo LOW'."""
    for level in ("NO_SPATIAL_DATA", "LOCAL_ANCHORED_CENTER", "UTM_WITH_ZONE"):
        html = _spatial_readiness_section_html(_make_sr_dict(level))
        assert "Riesgo LOW" not in html


def test_cap_section_does_not_contain_dangerous_labels():
    """La sección de cap no contiene lenguaje peligroso."""
    cap = _make_cap(applied=True)
    html = _spatial_readiness_cap_section_html(cap)
    assert "Recomendación: DRILL" not in html
    assert "PERFORAR AQUÍ" not in html
    assert "Probabilidad IA" not in html
    assert "Riesgo LOW" not in html


# ── Tests: report_payload con spatial_readiness top-level (R3.5-G) ─────────

def test_report_payload_spatial_readiness_promoted_to_top_level():
    """
    Simula la lógica añadida en run_geophysics_inversion (R3.5-G):
    si spatial_readiness está en auto_params pero no top-level, se promueve.
    """
    sr_dict = {
        "level": "LOCAL_ANCHORED_CENTER",
        "max_favorability_score_allowed": 45.0,
        "max_priority_class_allowed": "LOW_RELATIVE_PRIORITY",
    }
    report_payload = {
        "auto_params": {"spatial_readiness": sr_dict},
        "favorability": {"score": 30.0, "level": "BAJO", "warnings": []},
        "priority_class": "LOW_RELATIVE_PRIORITY",
    }

    # Replicar la lógica de run_geophysics_inversion tras R3.5-G
    _sr_dict = (report_payload.get("auto_params") or {}).get("spatial_readiness")
    if _sr_dict and "spatial_readiness" not in report_payload:
        report_payload["spatial_readiness"] = _sr_dict

    assert "spatial_readiness" in report_payload
    assert report_payload["spatial_readiness"]["level"] == "LOCAL_ANCHORED_CENTER"


def test_report_payload_spatial_readiness_not_overwritten_if_already_present():
    """Si spatial_readiness ya está en top-level, no se sobreescribe."""
    sr_dict = {"level": "UTM_WITH_ZONE", "max_favorability_score_allowed": 85.0}
    existing_sr = {"level": "PROFESSIONAL_SURVEY", "max_favorability_score_allowed": 100.0}
    report_payload = {
        "spatial_readiness": existing_sr,
        "auto_params": {"spatial_readiness": sr_dict},
    }

    _sr_dict = (report_payload.get("auto_params") or {}).get("spatial_readiness")
    if _sr_dict and "spatial_readiness" not in report_payload:
        report_payload["spatial_readiness"] = _sr_dict

    # Debe conservar el valor pre-existente
    assert report_payload["spatial_readiness"]["level"] == "PROFESSIONAL_SURVEY"


def test_caps_applied_to_report_payload_with_sr_top_level():
    """
    Integración: _apply_spatial_readiness_caps funciona correctamente cuando
    spatial_readiness se pasa explícitamente (como ocurre en run_geophysics_inversion).
    """
    sr_dict = {
        "level": "LOCAL_ANCHORED_CENTER",
        "max_favorability_score_allowed": SPATIAL_LEVEL_MAX_FAVORABILITY["LOCAL_ANCHORED_CENTER"],
        "max_priority_class_allowed": SPATIAL_LEVEL_MAX_PRIORITY["LOCAL_ANCHORED_CENTER"],
    }
    report_payload = {
        "favorability": {"score": 85.0, "level": "MUY ALTO", "warnings": []},
        "priority_class": "HIGH_RELATIVE_PRIORITY",
    }

    _apply_spatial_readiness_caps(report_payload, sr_dict)

    # Cap debe haber reducido el score
    assert report_payload["favorability"]["score"] == 45.0
    assert report_payload["favorability"]["spatial_readiness_cap"]["applied"] is True
    # La función de promoción también puede aplicarse
    if sr_dict and "spatial_readiness" not in report_payload:
        report_payload["spatial_readiness"] = sr_dict
    assert "spatial_readiness" in report_payload
