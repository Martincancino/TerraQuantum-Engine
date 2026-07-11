"""F4.3 — Tests del servicio de sección (cara del corte pintada).

Verdad conocida: gota gaussiana en una grilla regular con coordenadas en METROS
(sin ix/iy/iz — el esquema REAL del motor, lección del OOM de F4.1). Se verifica
snap de posición, extent del raster, ubicación del máximo, flip-Y y bordes.
"""
import base64
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from core import block_model_store as store
from services.section_service import build_section_response

N = 21           # celdas por eje (impar → centro exacto)
CELL = 48.0
ORIGIN = 24.0    # coordenada de la primera celda (como el motor real)


def _make_blob_model(run_dir: Path) -> None:
    """Gota gaussiana centrada; y_m = profundidad (+ hacia abajo)."""
    gi, gj, gk = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    gi, gj, gk = gi.ravel(), gj.ravel(), gk.ravel()
    x = ORIGIN + gi * CELL
    y = ORIGIN + gj * CELL
    z = ORIGIN + gk * CELL
    c = (N - 1) / 2.0
    r2 = (gi - c) ** 2 + (gj - c) ** 2 + (gk - c) ** 2
    dens = 2.7 + 1.0 * np.exp(-0.5 * r2 / 4.0 ** 2)
    df = pl.DataFrame({
        "x_m": x, "y_m": y, "z_m": z,
        "x": x, "y": y, "z": z,
        "density": dens,
        "susceptibility_si": 0.001 + 0.14 * np.exp(-0.5 * r2 / 4.0 ** 2),
    })
    run_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(run_dir / "block_model.parquet"))


def _setup(projects_dir: Path, pid: str = "p", rid: str = "r") -> None:
    run_dir = projects_dir / pid / "runs" / rid
    _make_blob_model(run_dir)
    (projects_dir / pid / "project_meta.json").write_text(json.dumps({"project_id": pid}))


def _decode(resp: dict) -> np.ndarray:
    arr = np.frombuffer(base64.b64decode(resp["values_b64"]), dtype="<f4")
    return arr.reshape(resp["nv"], resp["nu"])


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def test_center_section_x_peaks_at_center(patched_projects_dir):
    """Sección x=0 (visual) atraviesa el centro de la gota → máx del raster al centro."""
    _setup(patched_projects_dir)
    resp = build_section_response("p", "r", axis="x", position=0.0)
    assert resp["error"] is None
    assert resp["position_snapped"] == 0.0  # N impar → hay capa exacta en el centro
    assert resp["nu"] == N and resp["nv"] == N
    raster = _decode(resp)
    assert np.isfinite(raster).all()  # grilla llena: sin huecos
    iv, iu = np.unravel_index(np.nanargmax(raster), raster.shape)
    assert abs(iu - (N - 1) / 2) <= 1 and abs(iv - (N - 1) / 2) <= 1
    # centro = pico de contraste positivo; esquina = fondo (contraste ~<=0)
    assert raster[iv, iu] > raster[0, 0]


def test_snap_to_nearest_layer(patched_projects_dir):
    """Posición entre capas se snapea a la capa de celdas más cercana."""
    _setup(patched_projects_dir)
    # capas visuales en múltiplos de CELL (…, -48, 0, 48, …); 20 → snap a 0? no: 20<24 → 0
    resp = build_section_response("p", "r", axis="x", position=20.0)
    assert resp["error"] is None
    assert resp["position_snapped"] == 0.0
    resp2 = build_section_response("p", "r", axis="x", position=30.0)
    assert resp2["position_snapped"] == 48.0


def test_y_axis_flip_shallow_layer_high_v(patched_projects_dir):
    """Corte vertical (axis z): una capa somera densa aparece en v ALTO (arriba).

    Se agrega una placa densa en la capa más somera (y_m mínimo = profundidad
    mínima → cy máximo). En el raster (v ascendente), debe caer en iv = nv-1.
    """
    projects_dir = patched_projects_dir
    run_dir = projects_dir / "p2" / "runs" / "r"
    gi, gj, gk = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    gi, gj, gk = gi.ravel(), gj.ravel(), gk.ravel()
    x = ORIGIN + gi * CELL
    y = ORIGIN + gj * CELL   # y_m: ORIGIN = capa MÁS SOMERA
    z = ORIGIN + gk * CELL
    dens = np.full(x.shape, 2.7)
    dens[gj == 0] = 3.9      # placa densa en la capa más somera
    df = pl.DataFrame({"x_m": x, "y_m": y, "z_m": z, "x": x, "y": y, "z": z, "density": dens})
    run_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(run_dir / "block_model.parquet"))
    (projects_dir / "p2" / "project_meta.json").write_text(json.dumps({"project_id": "p2"}))

    resp = build_section_response("p2", "r", axis="z", position=0.0)
    assert resp["error"] is None
    raster = _decode(resp)  # [iv, iu]; v = cy ascendente
    row_means = np.nanmean(raster, axis=1)
    assert np.nanargmax(row_means) == resp["nv"] - 1  # capa densa arriba del todo


def test_horizontal_section_axis_y(patched_projects_dir):
    """Corte horizontal (axis y) al centro → plano XZ con el pico centrado."""
    _setup(patched_projects_dir)
    resp = build_section_response("p", "r", axis="y", position=0.0)
    assert resp["error"] is None
    raster = _decode(resp)
    iv, iu = np.unravel_index(np.nanargmax(raster), raster.shape)
    assert abs(iu - (N - 1) / 2) <= 1 and abs(iv - (N - 1) / 2) <= 1


def test_susceptibility_field(patched_projects_dir):
    """Campo susceptibility (escala log) también produce raster válido."""
    _setup(patched_projects_dir)
    resp = build_section_response("p", "r", axis="x", position=0.0, field="susceptibility")
    assert resp["error"] is None
    assert resp["field"] == "susceptibility"
    raster = _decode(resp)
    iv, iu = np.unravel_index(np.nanargmax(raster), raster.shape)
    assert abs(iu - (N - 1) / 2) <= 1 and abs(iv - (N - 1) / 2) <= 1


def test_extent_matches_model(patched_projects_dir):
    """u0/v0 + (n-1)*d cubren el extent visual del modelo (±(N-1)/2·CELL)."""
    _setup(patched_projects_dir)
    resp = build_section_response("p", "r", axis="x", position=0.0)
    half = (N - 1) / 2 * CELL
    assert abs(resp["u0"] + half) < 1e-6
    assert abs(resp["v0"] + half) < 1e-6
    assert abs(resp["u0"] + (resp["nu"] - 1) * resp["du"] - half) < 1e-6


def test_invalid_axis_and_missing_run(patched_projects_dir):
    """Bordes: eje inválido y corrida inexistente → error catalogado, sin crash."""
    _setup(patched_projects_dir)
    assert build_section_response("p", "r", axis="w", position=0.0)["error"] is not None
    assert build_section_response("nope", "rx", axis="x", position=0.0)["error"] is not None


def test_position_outside_domain_snaps_to_edge(patched_projects_dir):
    """Posición fuera del dominio se snapea al borde, no crashea."""
    _setup(patched_projects_dir)
    resp = build_section_response("p", "r", axis="x", position=1e9)
    assert resp["error"] is None
    half = (N - 1) / 2 * CELL
    assert resp["position_snapped"] == half
