"""F4.5 — Tests del servicio de horizonte DOI (incertidumbre visible en el 3D).

Verdad conocida: sensibilidad sintética que decae con la profundidad → el
horizonte half-max cae en la capa esperada. Respaldo doi_index y bordes
(corridas joint sin columnas → error claro que NO estima).
"""
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from services import block_model_store as store
from services.doi_overlay_service import build_doi_overlay_response

N = 10
CELL = 48.0
ORIGIN = 24.0


def _base_frame(extra: dict | None = None) -> pl.DataFrame:
    gi, gj, gk = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    gi, gj, gk = gi.ravel(), gj.ravel(), gk.ravel()
    x = ORIGIN + gi * CELL
    y = ORIGIN + gj * CELL  # profundidad, + hacia abajo
    z = ORIGIN + gk * CELL
    cols = {
        "x_m": x, "y_m": y, "z_m": z,
        "x": x, "y": y, "z": z,
        "density": np.full(x.shape, 2.7),
    }
    if extra:
        cols.update(extra)
    return pl.DataFrame(cols)


def _setup(projects_dir: Path, pid: str, df: pl.DataFrame) -> None:
    run_dir = projects_dir / pid / "runs" / "r"
    run_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(run_dir / "block_model.parquet"))
    (projects_dir / pid / "project_meta.json").write_text(json.dumps({"project_id": pid}))


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def test_sensitivity_half_max_horizon(patched_projects_dir):
    """Sensibilidad = 1.0 en las 4 capas someras, 0.1 después → horizonte en capa 4.

    Capas de profundidad: 24, 72, 120, 168 (índices 0-3, sens 1.0) y el resto 0.1.
    half-max (≥0.5·pico=0.5) → capa más profunda = 168 m.
    """
    gj = ((_base_frame()["y_m"].to_numpy() - ORIGIN) / CELL).astype(int)
    sens = np.where(gj <= 3, 1.0, 0.1)
    df = _base_frame({"sensitivity_proxy": sens})
    _setup(patched_projects_dir, "p1", df)

    resp = build_doi_overlay_response("p1", "r")
    assert resp["error"] is None
    assert resp["method"] == "sensitivity_doi_half_max_layer"
    assert abs(resp["depth_m"] - (ORIGIN + 3 * CELL)) < 1e-6  # 168 m
    # visual: y_c = (24+456)/2 = 240 → cy_horizon = 240 - 168 = 72
    assert abs(resp["cy_horizon"] - (240.0 - 168.0)) < 1e-6
    # 6 de 10 capas quedan bajo el horizonte
    assert abs(resp["cells_below_fraction"] - 0.6) < 1e-6
    # extent visual coherente (techo arriba, fondo abajo)
    assert resp["extent"]["cy_max"] > resp["extent"]["cy_min"]


def test_doi_index_fallback(patched_projects_dir):
    """Sin sensitivity_proxy pero con doi_index: umbral 0.4 define el horizonte."""
    gj = ((_base_frame()["y_m"].to_numpy() - ORIGIN) / CELL).astype(int)
    doi = np.where(gj <= 5, 0.1, 0.9)  # bien restringido hasta capa 5 (264 m)
    df = _base_frame({"doi_index": doi})
    _setup(patched_projects_dir, "p2", df)

    resp = build_doi_overlay_response("p2", "r")
    assert resp["error"] is None
    assert resp["method"] == "doi_index_threshold"
    assert abs(resp["depth_m"] - (ORIGIN + 5 * CELL)) < 1e-6


def test_joint_run_without_columns_clear_error(patched_projects_dir):
    """Corrida joint (sin sensibilidad ni doi por celda) → error claro, NO estima."""
    _setup(patched_projects_dir, "p3", _base_frame())
    resp = build_doi_overlay_response("p3", "r")
    assert resp["cy_horizon"] is None
    assert resp["error"] is not None
    assert "no se estima" in resp["error"].lower() or "F5" in resp["error"]


def test_flat_zero_sensitivity_falls_back(patched_projects_dir):
    """Sensibilidad toda cero → no hay pico → cae al respaldo o error (sin crash)."""
    df = _base_frame({"sensitivity_proxy": np.zeros(N ** 3)})
    _setup(patched_projects_dir, "p4", df)
    resp = build_doi_overlay_response("p4", "r")
    assert resp["error"] is not None  # sin doi_index tampoco → error catalogado


def test_missing_run(patched_projects_dir):
    resp = build_doi_overlay_response("nope", "rx")
    assert resp["error"] is not None
