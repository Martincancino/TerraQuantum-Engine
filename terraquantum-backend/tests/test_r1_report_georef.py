"""
R1-BE-4 tests — georef section in HTML report.

Fixtures write minimal run + project_meta artifacts into tmp_path,
monkeypatch PROJECTS_DIR, then call generate_technical_report_html().
"""
import json

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_LOW_FOOTPRINT = {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "local_meters_anchored",
    "confidence": "LOW",
    "center_lat": -22.28,
    "center_lon": -68.89,
    "extent_x_m": 49679.0,
    "extent_z_m": 48995.0,
    "utm_zone": None,
    "sw": {"lat": -22.50, "lon": -69.12},
    "se": {"lat": -22.50, "lon": -68.66},
    "ne": {"lat": -22.06, "lon": -68.66},
    "nw": {"lat": -22.06, "lon": -69.12},
    "warnings": [
        "Metros locales anclados al punto central. Orientación y escala real no garantizadas.",
        "El footprint es una estimación derivada, no un polígono real del survey.",
    ],
    "precision_notes": ["Aproximación equirectangular — error <1% para extensiones <100km."],
}

_MINIMAL_INPUTS = {
    "lat": -22.28,
    "lon": -68.89,
    "depth": 3000,
    "nir": 1.0,
    "fe": 0.1,
    "nx": 32,
    "ny": 20,
    "nz": 32,
    "block_size": 1552.0,
    "cutoff_radius": 3000.0,
    "lambda_mag": 1.0,
    "alpha_spatial": 1.0,
    "enable_focusing": False,
    "region": "Test Region",
}

_MINIMAL_REPORT = {
    "confidence_level": "MEDIUM",
    "priority_class": "LOW_RELATIVE_PRIORITY",
    "model_reliability_level": "MEDIUM",
    "fitDiagnostics": {
        "fit_level": "ACCEPTABLE",
        "residual_rmse": 0.1,
        "residual_mae": 0.08,
        "residual_bias": 0.01,
        "residual_l2": 1.0,
        "misfit_error_percent": 5.0,
        "normalized_rmse": 0.05,
        "fit_quality": "GOOD",
        "residualMap": [],
    },
    "observationQuality": {
        "quality_score": 75,
        "quality_level": "MEDIUM",
        "observation_count": 251,
        "warnings": [],
    },
    "technicalSummary": {
        "overall_level": "MEDIUM",
        "summary": "Test summary",
        "key_findings": ["Finding 1"],
        "warnings": [],
        "recommended_next_steps": ["Step 1"],
    },
    "uncertaintyDiagnostics": {
        "uncertainty_level": "MEDIUM",
        "recommended_action": "Verify with drilling",
    },
    "best_target": {
        "x_m": 1000.0,
        "y_m": 500.0,
        "z_m": 1000.0,
        "density": 2.8,
        "relative_target_score": 0.75,
        "grade": 0.5,
        "confidence_level": "MEDIUM",
    },
}


def _setup_run(tmp_path, project_id, run_id, georef_confidence, footprint_data):
    """Write minimal inputs.json, report.json, and project_meta.json to tmp_path."""
    run_path = tmp_path / "projects" / project_id / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    (run_path / "inputs.json").write_text(
        json.dumps(_MINIMAL_INPUTS), encoding="utf-8"
    )
    (run_path / "report.json").write_text(
        json.dumps(_MINIMAL_REPORT), encoding="utf-8"
    )

    meta = {
        "project_id": project_id,
        "latitude": -22.28,
        "longitude": -68.89,
        "crs": "EPSG:4326",
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
        "georef_confidence": georef_confidence,
        "georef_type": "local_meters_anchored",
        "utm_zone": None,
        "footprint": footprint_data,
    }
    meta_path = tmp_path / "projects" / project_id / "project_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _generate(tmp_path, monkeypatch, project_id, run_id) -> str:
    import services.block_model_store as store
    monkeypatch.setattr(store, "PROJECTS_DIR", tmp_path / "projects")

    from reporting.report_generator import generate_technical_report_html
    return generate_technical_report_html(project_id=project_id, run_id=run_id)


# ---------------------------------------------------------------------------
# Presence of georef section
# ---------------------------------------------------------------------------

def test_report_html_contains_georef_heading(tmp_path, monkeypatch):
    """HTML must contain the georef section heading."""
    _setup_run(tmp_path, "rpt_low", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_low", "run_001")
    assert "Georreferenciación del Proyecto" in html


def test_report_html_contains_georef_section_id(tmp_path, monkeypatch):
    """HTML must contain the <section id='georef'> element."""
    _setup_run(tmp_path, "rpt_id", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_id", "run_001")
    assert 'id="georef"' in html


# ---------------------------------------------------------------------------
# Confidence level rendering
# ---------------------------------------------------------------------------

def test_report_html_low_confidence_badge(tmp_path, monkeypatch):
    """HTML includes 'Confianza BAJA' badge for LOW confidence."""
    _setup_run(tmp_path, "rpt_low2", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_low2", "run_001")
    assert "Confianza BAJA" in html
    assert "georef-LOW" in html


def test_report_html_high_confidence_badge(tmp_path, monkeypatch):
    """HTML includes 'Confianza ALTA' badge for HIGH confidence."""
    high_fp = {**_LOW_FOOTPRINT, "confidence": "HIGH", "source": "latlon", "warnings": []}
    _setup_run(tmp_path, "rpt_high", "run_001", "HIGH", high_fp)
    html = _generate(tmp_path, monkeypatch, "rpt_high", "run_001")
    assert "Confianza ALTA" in html
    assert "georef-HIGH" in html


def test_report_html_missing_confidence_badge(tmp_path, monkeypatch):
    """HTML includes 'Sin Georreferenciación' badge for MISSING confidence."""
    _setup_run(tmp_path, "rpt_missing", "run_001", "MISSING", None)
    html = _generate(tmp_path, monkeypatch, "rpt_missing", "run_001")
    assert "Sin Georreferenciación" in html
    assert "georef-MISSING" in html


def test_report_html_medium_confidence_badge(tmp_path, monkeypatch):
    """HTML includes 'Confianza MEDIA' badge for MEDIUM confidence."""
    med_fp = {**_LOW_FOOTPRINT, "confidence": "MEDIUM", "source": "csv_utm"}
    _setup_run(tmp_path, "rpt_medium", "run_001", "MEDIUM", med_fp)
    html = _generate(tmp_path, monkeypatch, "rpt_medium", "run_001")
    assert "Confianza MEDIA" in html
    assert "georef-MEDIUM" in html


# ---------------------------------------------------------------------------
# LOW disclaimer — terrain visual context warning
# ---------------------------------------------------------------------------

def test_report_html_low_terrain_disclaimer(tmp_path, monkeypatch):
    """For LOW confidence, HTML must warn that terrain is visual context only."""
    _setup_run(tmp_path, "rpt_low_disc", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_low_disc", "run_001")
    html_lower = html.lower()
    assert "contexto visual" in html_lower or "terreno visible" in html_lower


# ---------------------------------------------------------------------------
# MISSING disclaimer
# ---------------------------------------------------------------------------

def test_report_html_missing_local_coords_disclaimer(tmp_path, monkeypatch):
    """For MISSING confidence, HTML must mention 'coordenadas locales'."""
    _setup_run(tmp_path, "rpt_miss_disc", "run_001", "MISSING", None)
    html = _generate(tmp_path, monkeypatch, "rpt_miss_disc", "run_001")
    html_lower = html.lower()
    assert "coordenadas locales" in html_lower or "sin georreferenciación" in html_lower


# ---------------------------------------------------------------------------
# Footprint data in table
# ---------------------------------------------------------------------------

def test_report_html_shows_footprint_type(tmp_path, monkeypatch):
    """HTML includes the footprint type from the footprint object."""
    _setup_run(tmp_path, "rpt_fp_type", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_fp_type", "run_001")
    assert "bbox" in html


def test_report_html_shows_center_coords(tmp_path, monkeypatch):
    """HTML includes center_lat and center_lon when available."""
    _setup_run(tmp_path, "rpt_center", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_center", "run_001")
    assert "-22.28" in html


def test_report_html_no_footprint_shows_not_available(tmp_path, monkeypatch):
    """When footprint is None, table values default to 'No disponible'."""
    _setup_run(tmp_path, "rpt_no_fp", "run_001", "MISSING", None)
    html = _generate(tmp_path, monkeypatch, "rpt_no_fp", "run_001")
    assert "No disponible" in html


# ---------------------------------------------------------------------------
# Forbidden content — no DRILL / probability reintroduction
# ---------------------------------------------------------------------------

def test_report_html_does_not_reintroduce_drill_recommendation(tmp_path, monkeypatch):
    """HTML must NOT contain 'Recomendación: DRILL' or '>DRILL<'."""
    _setup_run(tmp_path, "rpt_no_drill", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_no_drill", "run_001")
    assert "Recomendación: DRILL" not in html
    assert ">DRILL<" not in html


def test_report_html_does_not_reintroduce_probabilidad_ia(tmp_path, monkeypatch):
    """HTML must NOT contain 'Probabilidad IA'."""
    _setup_run(tmp_path, "rpt_no_prob", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_no_prob", "run_001")
    assert "Probabilidad IA" not in html


def test_report_html_does_not_reintroduce_riesgo_low_recommendation(tmp_path, monkeypatch):
    """HTML must NOT contain 'Riesgo LOW' as a standalone recommendation."""
    _setup_run(tmp_path, "rpt_no_riesgo", "run_001", "LOW", _LOW_FOOTPRINT)
    html = _generate(tmp_path, monkeypatch, "rpt_no_riesgo", "run_001")
    assert "Riesgo LOW" not in html
