"""F4.4 — Tests del servicio de vista de sondajes (cilindros en el visor 3D).

Verifica que los sondajes persistidos se transforman al espacio visual con el
MISMO centrado + flip-Y que los vóxeles/isosuperficies, para que caigan donde
está el cuerpo. No usa data real; parquet + boreholes.json temporales.
"""
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from services import block_model_store as store
from services.borehole_view_service import build_borehole_view_response


def _make_block_model(run_dir: Path, n: int = 20, cell: float = 48.0) -> None:
    ix, iy, iz = np.meshgrid(np.arange(n), np.arange(n), np.arange(n), indexing="ij")
    ix = ix.ravel(); iy = iy.ravel(); iz = iz.ravel()
    x = 24.0 + ix * cell
    y = 24.0 + iy * cell
    z = 24.0 + iz * cell
    # densidad de fondo 2.7 + una gota densa al centro
    c = (n - 1) / 2.0
    r2 = (ix - c) ** 2 + (iy - c) ** 2 + (iz - c) ** 2
    dens = 2.7 + 1.0 * np.exp(-0.5 * r2 / 5.0 ** 2)
    df = pl.DataFrame({
        "x_m": x, "y_m": y, "z_m": z,
        "x": x, "y": y, "z": z,
        "density": dens,
    })
    run_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(run_dir / "block_model.parquet"))


def _write_boreholes(run_dir: Path, intervals: list) -> None:
    (run_dir / "boreholes.json").write_text(json.dumps(intervals), encoding="utf-8")


def _setup(projects_dir: Path, pid: str, rid: str, intervals: list | None = None) -> Path:
    run_dir = projects_dir / pid / "runs" / rid
    _make_block_model(run_dir)
    (projects_dir / pid / "project_meta.json").write_text(json.dumps({"project_id": pid}))
    if intervals is not None:
        _write_boreholes(run_dir, intervals)
    return run_dir


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ── 1. Transformación de coordenadas (alineación con el visor) ───────────────

def test_borehole_coords_centered_and_flipped(patched_projects_dir):
    """Un pozo vertical al centro se transforma con el MISMO centro que el modelo.

    Modelo: x_m∈[24, 24+19*48=936] → x_c = (24+936)/2 = 480. Igual para y,z.
    Un intervalo en (480, 480) a profundidad 100-300 → cx=cz=0, cy_top=480-100=380.
    """
    intervals = [{
        "x_m": 480.0, "z_m": 480.0, "y_from_m": 100.0, "y_to_m": 300.0,
        "density_t_m3": 3.7, "lithology": "magnetita",
    }]
    _setup(patched_projects_dir, "p", "r1", intervals)

    resp = build_borehole_view_response("p", "r1")
    assert resp["error"] is None
    assert resp["n_intervals"] == 1
    iv = resp["intervals"][0]
    assert abs(iv["cx"]) < 1e-6 and abs(iv["cz"]) < 1e-6  # centrado en el eje
    # y_c = 480 → cy_top = 480 - 100 = 380 (somero, arriba); cy_bot = 480 - 300 = 180
    assert abs(iv["cy_top"] - 380.0) < 1e-6
    assert abs(iv["cy_bot"] - 180.0) < 1e-6
    assert iv["cy_top"] > iv["cy_bot"]  # top = más somero = más arriba en Y visual
    assert iv["lithology"] == "magnetita"


def test_borehole_density_contrast_matches_model(patched_projects_dir):
    """El contraste con signo usa la MISMA escala robusta del block model."""
    intervals = [
        {"x_m": 480.0, "z_m": 480.0, "y_from_m": 100.0, "y_to_m": 300.0, "density_t_m3": 3.7, "lithology": "magnetita"},
        {"x_m": 480.0, "z_m": 480.0, "y_from_m": 0.0, "y_to_m": 100.0, "density_t_m3": 2.7, "lithology": "andesita"},
    ]
    _setup(patched_projects_dir, "p", "r2", intervals)

    resp = build_borehole_view_response("p", "r2")
    assert resp["background"] is not None and resp["scale"] is not None
    dense = next(i for i in resp["intervals"] if i["lithology"] == "magnetita")
    host = next(i for i in resp["intervals"] if i["lithology"] == "andesita")
    # la magnetita (más densa) tiene mayor contraste con signo que la andesita
    assert dense["signed_contrast"] > host["signed_contrast"]
    assert dense["signed_contrast"] > 0  # exceso de masa


def test_multiple_holes_collars(patched_projects_dir):
    """Varios pozos → collares únicos por (cx, cz)."""
    intervals = [
        {"x_m": 480.0, "z_m": 480.0, "y_from_m": 0.0, "y_to_m": 300.0, "density_t_m3": 3.7, "lithology": "magnetita"},
        {"x_m": 480.0, "z_m": 480.0, "y_from_m": 300.0, "y_to_m": 500.0, "density_t_m3": 2.7, "lithology": "andesita"},
        {"x_m": 240.0, "z_m": 720.0, "y_from_m": 0.0, "y_to_m": 500.0, "density_t_m3": 2.7, "lithology": "andesita"},
    ]
    _setup(patched_projects_dir, "p", "r3", intervals)

    resp = build_borehole_view_response("p", "r3")
    assert resp["n_intervals"] == 3
    assert resp["n_holes"] == 2  # dos collares distintos


# ── 2. Bordes ────────────────────────────────────────────────────────────────

def test_no_boreholes_file_returns_clear_error(patched_projects_dir):
    """Corrida sin boreholes.json (cargada antes de F4.4) → error claro, sin crash."""
    _setup(patched_projects_dir, "p", "r4", intervals=None)
    resp = build_borehole_view_response("p", "r4")
    assert resp["n_intervals"] == 0
    assert resp["error"] is not None
    assert "sondajes" in resp["error"].lower()


def test_missing_run_returns_error(patched_projects_dir):
    """Corrida inexistente → error catalogado."""
    resp = build_borehole_view_response("nope", "rx")
    assert resp["intervals"] == []
    assert resp["error"] is not None


def test_intervals_without_coords_skipped(patched_projects_dir):
    """Intervalos sin coordenadas válidas se omiten con aviso, sin crash."""
    intervals = [
        {"x_m": 480.0, "z_m": 480.0, "y_from_m": 0.0, "y_to_m": 300.0, "density_t_m3": 3.7},
        {"lithology": "andesita"},  # sin coords
    ]
    _setup(patched_projects_dir, "p", "r5", intervals)
    resp = build_borehole_view_response("p", "r5")
    assert resp["n_intervals"] == 1
    assert any("omitid" in w.lower() for w in resp["warnings"])


def test_density_only_no_lithology(patched_projects_dir):
    """Intervalo con densidad pero sin litología → válido, lithology=None."""
    intervals = [{"x_m": 480.0, "z_m": 480.0, "y_from_m": 0.0, "y_to_m": 300.0, "density_t_m3": 3.5}]
    _setup(patched_projects_dir, "p", "r6", intervals)
    resp = build_borehole_view_response("p", "r6")
    assert resp["n_intervals"] == 1
    assert resp["intervals"][0]["lithology"] is None
    assert resp["intervals"][0]["signed_contrast"] is not None
