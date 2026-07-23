"""F5 — Reporte HTML: veredicto B3 en prosa + resolución de profundidad B2 +
campos honestos de B1 en la tabla de target. Extiende generate_technical_report_html
(reporting/report_generator.py) sin dependencias nuevas — el "PDF" del plan
maestro se entrega como HTML imprimible (@media print ya existente) desde el
navegador, evitando instalar una librería PDF (regla del proyecto: no
dependencias nuevas sin permiso).
"""
import json

import pytest

_INPUTS = {
    "lat": -22.28, "lon": -68.89, "depth": 3000, "nir": 1.0, "fe": 0.1,
    "nx": 32, "ny": 20, "nz": 32, "block_size": 1552.0, "cutoff_radius": 3000.0,
    "lambda_mag": 1.0, "alpha_spatial": 1.0, "enable_focusing": False,
    "region": "Test Region",
}

_BASE_REPORT_FIELDS = {
    "confidence_level": "MEDIUM",
    "priority_class": "LOW_RELATIVE_PRIORITY",
    "model_reliability_level": "MEDIUM",
    "fitDiagnostics": {
        "fit_level": "ACCEPTABLE", "residual_rmse": 0.1, "residual_mae": 0.08,
        "residual_bias": 0.01, "residual_l2": 1.0, "misfit_error_percent": 5.0,
        "normalized_rmse": 0.05, "fit_quality": "GOOD", "residualMap": [],
    },
    "observationQuality": {
        "quality_score": 75, "quality_level": "MEDIUM", "observation_count": 251,
        "warnings": [],
    },
    "technicalSummary": {
        "overall_level": "MEDIUM", "summary": "Test summary",
        "key_findings": ["Finding 1"], "warnings": [],
        "recommended_next_steps": ["Step 1"],
    },
    "uncertaintyDiagnostics": {
        "uncertainty_level": "MEDIUM", "recommended_action": "Verify with drilling",
    },
}


def _setup_run(tmp_path, project_id, run_id, report_extra):
    run_path = tmp_path / "projects" / project_id / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    (run_path / "inputs.json").write_text(json.dumps(_INPUTS), encoding="utf-8")
    report = dict(_BASE_REPORT_FIELDS)
    report.update(report_extra)
    (run_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    meta_path = tmp_path / "projects" / project_id / "project_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({"project_id": project_id}), encoding="utf-8")


def _generate(tmp_path, monkeypatch, project_id, run_id) -> str:
    import core.block_model_store as store
    monkeypatch.setattr(store, "PROJECTS_DIR", tmp_path / "projects")
    from reporting.report_generator import generate_technical_report_html
    return generate_technical_report_html(project_id=project_id, run_id=run_id)


def test_reconciled_verdict_and_depth_resolution_render_with_full_data(tmp_path, monkeypatch):
    report_extra = {
        "best_target": {
            "x_m": 1000.0, "y_m": 500.0, "z_m": 1000.0, "density": 2.8,
            "relative_target_score": 0.75, "grade": 0.5, "confidence_level": "LOW",
            "depth_m": 1600.0, "is_resolvable_depth": True,
            "is_null_space_artifact": False, "n_floor_saturated_cells": 0,
            "selection_note": "Sin artefacto de piso detectado.",
        },
        "overall_verdict": {
            "level": "LOW",
            "limiting_factors": ["priority_class", "r06_padding_physical"],
            "components": {"survey_confidence": "MEDIUM", "priority_class": "LOW_RELATIVE_PRIORITY"},
            "headline": "Modelo NO confiable como base ÚNICA; limitado por: priority_class.",
            "recommended_action": "No perforar sólo con este modelo.",
            "note": "Veredicto ÚNICO = el más conservador entre las señales.",
        },
        "depthResolution": {
            "computed": True,
            "statement": "Footprint horizontal DETERMINADO. Profundidad NO resuelta bajo ~1600 m.",
            "per_axis": {
                "horizontal": {"determined": True, "compactness": "compact", "extent_m": 220.0},
                "vertical": {"quality": "null_space_dominated", "deep_mass_fraction": 0.88},
            },
            "deep_mass_fraction": 0.88,
            "resolvable_depth_max_m": 1600.0,
            "resolvable_depth_horizon_method": "sensitivity_doi_half_max_layer",
            "resolvable_body_depth_m": 1600.0,
            "note": "Derivado del modelo recuperado, no del posterior.",
        },
    }
    _setup_run(tmp_path, "p1", "r1", report_extra)
    html = _generate(tmp_path, monkeypatch, "p1", "r1")

    # B3 en prosa
    assert "Veredicto Reconciliado" in html
    assert "Modelo NO confiable como base" in html
    assert "priority_class" in html

    # B1 honesto: depth_m + flags null-space en la tabla de target
    assert "¿Profundidad Resoluble?" in html
    assert "¿Es Artefacto Null-Space?" in html
    assert "1600" in html

    # B2 resolución de profundidad
    assert "Resolución de Profundidad por-Eje" in html
    assert "null_space_dominated" in html
    assert "0.88" in html


def test_missing_overall_verdict_and_depth_resolution_no_crash(tmp_path, monkeypatch):
    """Corridas viejas (pre-B2/B3) o degradadas: sin estas claves, el reporte
    debe seguir generando HTML válido, sin sección vacía rota ni crash."""
    report_extra = {
        "best_target": {
            "x_m": 1000.0, "y_m": 500.0, "z_m": 1000.0, "density": 2.8,
            "relative_target_score": 0.75, "grade": 0.5, "confidence_level": "MEDIUM",
        },
    }
    _setup_run(tmp_path, "p2", "r2", report_extra)
    html = _generate(tmp_path, monkeypatch, "p2", "r2")
    assert "<html" in html and "</html>" in html
    assert "Target Geofísico Principal" in html


def test_null_space_artifact_target_shown_honestly_in_html(tmp_path, monkeypatch):
    report_extra = {
        "best_target": {
            "x_m": 1000.0, "y_m": 500.0, "z_m": 900.0, "density": 4.59,
            "relative_target_score": 0.1, "grade": None, "confidence_level": "LOW",
            "depth_m": 900.0, "is_resolvable_depth": False,
            "is_null_space_artifact": True, "n_floor_saturated_cells": 8,
            "selection_note": "ADVERTENCIA: todo el modelo satura en el piso; el blanco mostrado es null-space, NO fiable.",
        },
    }
    _setup_run(tmp_path, "p3", "r3", report_extra)
    html = _generate(tmp_path, monkeypatch, "p3", "r3")
    assert "null-space, NO fiable" in html
