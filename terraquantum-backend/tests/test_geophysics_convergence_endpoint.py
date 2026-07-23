"""F5 — GET /v2/geophysics-convergence/{project_id}/{run_id}.

Expone el barrido de λ (Morozov chi² discrepancy) ya calculado por el solver.
Verifica: caso disponible (con trials), caso no-disponible (lambda fijo, sin
auto_lambda — 200 honesto, no error), y run inexistente (404, nunca crashea).
"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import block_model_store as store
from api.geophysics_api import get_geophysics_convergence


def _write_report(projects_dir: Path, pid: str, rid: str, report: dict) -> None:
    run_dir = projects_dir / pid / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (projects_dir / pid / "project_meta.json").write_text(json.dumps({"project_id": pid}))


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def test_available_scan_returns_trials(patched_projects_dir):
    report = {
        "fitDiagnostics": {
            "lambda_scan_chi2": {
                "selection_method": "morozov_chi2_discrepancy",
                "lambda_selected": 0.31623,
                "chi2_achieved": 1.02,
                "n_solves": 5,
                "trials": [
                    {"lambda": 0.01, "chi2_red": 3.4},
                    {"lambda": 0.31623, "chi2_red": 1.02},
                    {"lambda": 10.0, "chi2_red": 0.2},
                ],
                "warnings": [],
            }
        }
    }
    _write_report(patched_projects_dir, "p1", "r1", report)
    resp = asyncio.run(get_geophysics_convergence("p1", "r1"))
    assert resp["available"] is True
    assert resp["selection_method"] == "morozov_chi2_discrepancy"
    assert resp["n_solves"] == 5
    assert len(resp["trials"]) == 3
    assert resp["trials"][1]["lambda_value"] == 0.31623
    assert resp["trials"][1]["chi2_reduced"] == 1.02
    assert "NO es chi² por iteración" in resp["note"]


def test_fixed_lambda_no_scan_is_honest_not_an_error(patched_projects_dir):
    report = {"fitDiagnostics": {}, "lambda_used": 0.05}
    _write_report(patched_projects_dir, "p2", "r2", report)
    resp = asyncio.run(get_geophysics_convergence("p2", "r2"))
    assert resp["available"] is False
    assert resp["trials"] == []
    assert "lambda_mag" in resp["note"] or "fijo" in resp["note"]


def test_missing_run_raises_404_not_crash(patched_projects_dir):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_geophysics_convergence("nope", "nope"))
    assert exc_info.value.status_code == 404
