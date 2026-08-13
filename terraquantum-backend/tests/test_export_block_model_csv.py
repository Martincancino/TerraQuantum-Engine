"""F5 — Export de block model a CSV estándar minero (x,y,z,densidad[,susceptibilidad]).

Verifica export_block_model_to_csv: lee el parquet REAL persistido (coordenadas
verdaderas x_m/y_m/z_m, sin re-derivar grilla), nunca crashea, y produce un CSV
con encabezados estándar. Cubre grav-only (sin susceptibilidad), joint (con
susceptibilidad) y ausencia de parquet (404 honesto, no crash).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from services import block_model_store as store
from services.export_service import export_block_model_to_csv

N = 6
CELL = 50.0


def _grav_frame() -> pl.DataFrame:
    gi, gj, gk = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    gi, gj, gk = gi.ravel(), gj.ravel(), gk.ravel()
    x = gi.astype(float) * CELL
    y = gj.astype(float) * CELL
    z = gk.astype(float) * CELL
    n = x.shape[0]
    return pl.DataFrame({
        "x_m": x, "y_m": y, "z_m": z,
        "x": x, "y": y, "z": z,
        "density_t_m3": np.full(n, 2.7),
        "density": np.full(n, 2.7),
        "sensitivity_proxy": np.linspace(1.0, 0.1, n),
        "doi_index": np.linspace(1.0, 0.1, n),
        "posterior_std": np.full(n, np.nan),
        "probability": np.full(n, 0.5),
        "is_active": np.full(n, True),
    })


def _joint_frame() -> pl.DataFrame:
    df = _grav_frame()
    return df.with_columns(pl.Series("susceptibility_si", np.full(df.height, 0.02)))


def _setup(projects_dir: Path, pid: str, rid: str, df: "pl.DataFrame | None") -> Path:
    run_dir = projects_dir / pid / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    if df is not None:
        df.write_parquet(str(run_dir / "block_model.parquet"))
    (projects_dir / pid / "project_meta.json").write_text(json.dumps({"project_id": pid}))
    return run_dir


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def test_grav_only_csv_has_standard_columns_no_susceptibility(patched_projects_dir):
    _setup(patched_projects_dir, "p1", "r1", _grav_frame())
    csv_path = export_block_model_to_csv("p1", "r1")
    assert csv_path is not None
    out = pd.read_csv(csv_path)
    for col in ("X_m", "Y_m", "Z_m", "Density_gcm3", "Sensitivity_Proxy", "DOI_Index",
                "Probability", "Is_Active"):
        assert col in out.columns
    assert "Susceptibility_SI" not in out.columns
    assert len(out) == N ** 3
    # Posterior_std 100% NaN en este caso: no debe romper el CSV (queda como campo vacío/NaN).
    assert "Posterior_Std_gcm3" in out.columns
    assert out["Posterior_Std_gcm3"].isna().all()


def test_joint_csv_includes_susceptibility(patched_projects_dir):
    _setup(patched_projects_dir, "p2", "r2", _joint_frame())
    csv_path = export_block_model_to_csv("p2", "r2")
    assert csv_path is not None
    out = pd.read_csv(csv_path)
    assert "Susceptibility_SI" in out.columns
    assert np.allclose(out["Susceptibility_SI"].to_numpy(), 0.02)


def test_missing_parquet_returns_none_no_crash(patched_projects_dir):
    _setup(patched_projects_dir, "p3", "r3", None)  # sin parquet
    assert export_block_model_to_csv("p3", "r3") is None


def test_missing_run_dir_returns_none_no_crash(patched_projects_dir):
    assert export_block_model_to_csv("nope", "nope") is None
