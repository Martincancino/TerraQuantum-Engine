"""
Tier 1 A2 — Selección de λ por discrepancia de Morozov (chi²→1).

Contrato:
  - Con sigma EXPLÍCITO (gravímetro conocido o uncertainty del CSV) y λ=0/auto,
    el servicio escanea λ con el solver real y elige chi²_red ≈ 1 (≤ 6 solves).
  - Con sigma sentinel adaptivo, se conserva el operating point fijo (0.1).
  - Con λ explícito (> 0) jamás se ejecuta el scan.
"""
import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_field_data_complete_flow import build_field_csv


def _run_flow(lambda_override, pid):
    from services.gravity_import_service import run_field_data_inversion_with_corrections
    csv_text, _, _ = build_field_csv()
    tmp_csv = Path(__file__).parent.parent / "tmp" / f"morozov_{uuid.uuid4().hex[:6]}.csv"
    tmp_csv.parent.mkdir(exist_ok=True)
    tmp_csv.write_text(csv_text, encoding="utf-8")
    overrides = dict(
        nx=20, ny=10, nz=20, block_size=100, depth=1000,
        cutoff_radius=4000, density_min=0.0, density_max=5.5,
    )
    if lambda_override is not None:
        overrides["lambda_mag"] = lambda_override
    try:
        return asyncio.run(run_field_data_inversion_with_corrections(
            csv_path=tmp_csv, project_id=pid, run_id=uuid.uuid4().hex[:10],
            gravimeter_type="scintrex_cg6", apply_terrain=False,
            inversion_overrides=overrides,
        ))
    finally:
        try:
            tmp_csv.unlink()
        except OSError:
            pass


@pytest.mark.integration
def test_morozov_selects_lambda_with_explicit_sigma():
    """λ auto + sigma CG-6 → Morozov: chi²_red ∈ [0.5, 2.0] con ≤ 6 solves."""
    from core.config import PROJECTS_DIR
    pid = f"test_mzv_{uuid.uuid4().hex[:6]}"
    try:
        r = _run_flow(lambda_override=None, pid=pid)   # sin override → λ=0 → auto
        ir = r["inversion_results"]
        chi2 = float(ir["chi_squared_reduced"])
        assert 0.5 <= chi2 <= 2.0, f"Morozov no alcanzó chi²≈1: chi²_red={chi2:.3f}"
        assert ir["lambda_used"] is not None and float(ir["lambda_used"]) > 0
    finally:
        shutil.rmtree(Path(PROJECTS_DIR) / pid, ignore_errors=True)


@pytest.mark.integration
def test_explicit_lambda_never_scans():
    """λ explícito (0.1) → sin scan: lambda_used == 0.1 exacto."""
    from core.config import PROJECTS_DIR
    pid = f"test_mzvfix_{uuid.uuid4().hex[:6]}"
    try:
        r = _run_flow(lambda_override=0.1, pid=pid)
        assert float(r["inversion_results"]["lambda_used"]) == pytest.approx(0.1)
    finally:
        shutil.rmtree(Path(PROJECTS_DIR) / pid, ignore_errors=True)


@pytest.mark.integration
def test_sentinel_sigma_keeps_operating_point():
    """Sin sigma explícito (gravímetro unknown, sin uncertainty) y λ=0 →
    operating point fijo, NO Morozov (chi² adaptivo no es interpretable)."""
    import numpy as np
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import (
        run_geophysics_inversion,
        PRECONDITIONED_OPERATING_LAMBDA,
    )
    from core.config import PROJECTS_DIR

    rng = np.random.default_rng(11)
    obs = [
        GravityObservation(
            x_m=float(100 + i * 45), y_m=0.0, z_m=float(100 + (i * 37) % 500),
            g=float(2e-5 + rng.normal(0, 2e-6)),
        )
        for i in range(16)
    ]
    pid = f"test_op_{uuid.uuid4().hex[:6]}"
    params = GeophysicsInvertInput(
        project_id=pid, run_id=uuid.uuid4().hex[:10],
        depth=400, nir=0, fe=0, region="test",
        nx=6, ny=6, nz=6, block_size=100, cutoff_radius=800,
        lambda_mag=0.0,                  # sentinel auto
        alpha_spatial=1.0,
        observations=obs,
        # gravimeter_type default "unknown" + sin noise_floor → sentinel
    )
    try:
        result = run_geophysics_inversion(params)
        report = result["report"]
        assert float(report["lambda_used"]) == pytest.approx(PRECONDITIONED_OPERATING_LAMBDA)
        scan = report.get("lambda_scan_chi2") or {}
        assert scan.get("selection_method") == "fixed_preconditioned_operating_point"
    finally:
        shutil.rmtree(Path(PROJECTS_DIR) / pid, ignore_errors=True)
