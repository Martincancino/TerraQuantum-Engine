"""F4.1 — Tests del servicio de isosuperficies (marching cubes del block model).

Verifica contra geometría SINTÉTICA con verdad conocida:
  - Gota gaussiana centrada → isosuperficies anidadas (volumen monótono
    decreciente con la fracción), centroide en el origen visual, normales hacia
    afuera, malla cerrada.
  - Campo uniforme → ningún nivel produce superficie (error catalogado).
  - Susceptibilidad (magnético) como campo alternativo.
  - Bordes: parquet ausente, grilla degenerada (<2 celdas por eje), anomalía débil.

No usa data histórica real; todos los parquets son temporales en tmp_path.
"""
import base64
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from services import block_model_store as store
from services.isosurface_service import build_isosurface_response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _decode_f32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype="<f4")


def _decode_u32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype="<u4")


def _write_project_meta(projects_dir: Path, project_id: str) -> None:
    proj_dir = projects_dir / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    meta_path = proj_dir / "project_meta.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps({"project_id": project_id, "latitude": -22.28, "longitude": -68.89}),
            encoding="utf-8",
        )


def _make_grid_df(
    values: np.ndarray,
    cell: float,
    value_col: str = "density",
) -> pl.DataFrame:
    """DataFrame block-model desde un volumen 3D nx×ny×nz de `value_col`."""
    nx, ny, nz = values.shape
    ix, iy, iz = np.meshgrid(
        np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"
    )
    ix = ix.ravel(); iy = iy.ravel(); iz = iz.ravel()
    x_m = ix * cell + cell / 2.0
    y_m = iy * cell + cell / 2.0
    z_m = iz * cell + cell / 2.0
    data = {
        "ix": ix.astype(np.int64),
        "iy": iy.astype(np.int64),
        "iz": iz.astype(np.int64),
        "x_m": x_m,
        "y_m": y_m,
        "z_m": z_m,
        value_col: values.ravel().astype(np.float64),
    }
    # density siempre presente (máscara de actividad la usa)
    if value_col != "density":
        data["density"] = np.full(ix.size, 2.67)
    return pl.DataFrame(data)


def _gaussian_blob(n: int, amp: float, sigma_cells: float, bg: float = 2.67) -> np.ndarray:
    """Volumen n×n×n = bg + amp·exp(-½ (r/σ)²) centrado en la grilla."""
    c = (n - 1) / 2.0
    idx = np.arange(n)
    gx, gy, gz = np.meshgrid(idx, idx, idx, indexing="ij")
    r2 = (gx - c) ** 2 + (gy - c) ** 2 + (gz - c) ** 2
    return bg + amp * np.exp(-0.5 * r2 / (sigma_cells ** 2))


def _setup_run(projects_dir: Path, pid: str, rid: str, df: pl.DataFrame) -> None:
    run_dir = projects_dir / pid / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(run_dir / "block_model.parquet"))
    _write_project_meta(projects_dir, pid)


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ── 1. Gota gaussiana: geometría con verdad conocida ─────────────────────────

def test_gaussian_blob_nested_monotonic_volumes(patched_projects_dir):
    """Isosuperficies anidadas: mayor fracción → menor volumen encerrado."""
    n, cell = 40, 10.0
    df = _make_grid_df(_gaussian_blob(n, amp=0.8, sigma_cells=6.0), cell)
    _setup_run(patched_projects_dir, "blob", "run_1", df)

    resp = build_isosurface_response("blob", "run_1", field="density")

    assert resp["error"] is None
    assert resp["n_levels"] == 3, "las 3 fracciones 0.5/0.7/0.9 deben producir superficie"
    assert resp["peak_contrast"] > 0

    vols = [lvl["enclosed_volume_m3"] for lvl in resp["levels"]]
    fracs = [lvl["fraction"] for lvl in resp["levels"]]
    # levels vienen ordenados por fracción ascendente
    assert fracs == sorted(fracs)
    # Volumen estrictamente decreciente con la fracción (superficies anidadas).
    assert vols[0] > vols[1] > vols[2] > 0, f"volúmenes no monótonos: {vols}"


def test_gaussian_blob_centroid_at_visual_origin(patched_projects_dir):
    """La gota está en el centro de la grilla → centroide de la malla ≈ origen visual."""
    n, cell = 40, 10.0
    df = _make_grid_df(_gaussian_blob(n, amp=0.8, sigma_cells=6.0), cell)
    _setup_run(patched_projects_dir, "blob", "run_c", df)

    resp = build_isosurface_response("blob", "run_c", field="density")
    lvl = resp["levels"][0]
    pos = _decode_f32(lvl["positions_b64"]).reshape(-1, 3)
    centroid = pos.mean(axis=0)

    # Tolerancia = 1 celda: el cuerpo está centrado, el centro visual es (0,0,0).
    assert np.all(np.abs(centroid) < cell), f"centroide fuera del origen: {centroid}"


def test_gaussian_blob_outward_normals_and_closed(patched_projects_dir):
    """Normales hacia afuera (valida winding tras flip-Y) y malla cerrada."""
    n, cell = 40, 10.0
    df = _make_grid_df(_gaussian_blob(n, amp=0.8, sigma_cells=6.0), cell)
    _setup_run(patched_projects_dir, "blob", "run_n", df)

    resp = build_isosurface_response("blob", "run_n", field="density")
    lvl = resp["levels"][1]  # nivel intermedio
    pos = _decode_f32(lvl["positions_b64"]).reshape(-1, 3)
    nrm = _decode_f32(lvl["normals_b64"]).reshape(-1, 3)
    idx = _decode_u32(lvl["indices_b64"])

    # Normales unitarias.
    lengths = np.linalg.norm(nrm, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-3)

    # Índices dentro de rango.
    assert idx.max() < len(pos)
    assert len(idx) % 3 == 0

    # Cuerpo centrado en el origen → normal debe apuntar en el sentido de la
    # posición (hacia afuera). Promedio del coseno claramente positivo.
    r = np.linalg.norm(pos, axis=1, keepdims=True)
    r = np.where(r > 1e-6, r, 1.0)
    radial = pos / r
    cos = np.einsum("ij,ij->i", nrm, radial)
    assert cos.mean() > 0.5, f"normales no apuntan hacia afuera: mean cos={cos.mean():.3f}"


def test_edge_body_open_mesh_outward_normals(patched_projects_dir):
    """Cuerpo PEGADO al borde del dominio → malla abierta; las normales deben
    seguir apuntando hacia afuera (valida la orientación por gradiente, no por
    volumen firmado). Caso real: artefactos de borde sin padding (p.ej. Raglan)."""
    n, cell = 32, 10.0
    # Gota corrida hacia una esquina para que la anomalía toque los bordes.
    idx = np.arange(n)
    gx, gy, gz = np.meshgrid(idx, idx, idx, indexing="ij")
    r2 = (gx - 4) ** 2 + (gy - 4) ** 2 + (gz - 4) ** 2  # centro cerca de (4,4,4)
    dens = 2.67 + 0.9 * np.exp(-0.5 * r2 / (5.0 ** 2))
    df = _make_grid_df(dens, cell)
    _setup_run(patched_projects_dir, "edge", "run_1", df)

    resp = build_isosurface_response("edge", "run_1", field="density")
    assert resp["n_levels"] >= 1
    lvl = resp["levels"][0]
    pos = _decode_f32(lvl["positions_b64"]).reshape(-1, 3)
    nrm = _decode_f32(lvl["normals_b64"]).reshape(-1, 3)

    # El "centro" del cuerpo en coords visuales está corrido de la malla; la
    # normal debe apuntar desde ese centro hacia afuera para la mayoría de vértices.
    # Centro visual del blob ≈ (x_m - cx0, cy0 - y_m, z_m - cz0) con x_m=45.
    center_v = np.array([
        (4 * cell + cell / 2) - resp["center_m"]["x"],
        resp["center_m"]["y"] - (4 * cell + cell / 2),
        (4 * cell + cell / 2) - resp["center_m"]["z"],
    ])
    to_out = pos - center_v
    norm = np.linalg.norm(to_out, axis=1, keepdims=True)
    norm = np.where(norm > 1e-6, norm, 1.0)
    cos = np.einsum("ij,ij->i", nrm, to_out / norm)
    assert cos.mean() > 0.4, f"normales no apuntan hacia afuera en malla abierta: {cos.mean():.3f}"


def test_signed_contrast_positive_for_mass_excess(patched_projects_dir):
    """Exceso de masa (densidad alta) → contraste con signo positivo en la superficie."""
    n, cell = 40, 10.0
    df = _make_grid_df(_gaussian_blob(n, amp=0.8, sigma_cells=6.0), cell)
    _setup_run(patched_projects_dir, "blob", "run_s", df)

    resp = build_isosurface_response("blob", "run_s", field="density")
    lvl = resp["levels"][0]
    signed = _decode_f32(lvl["signed_contrast_b64"])
    assert signed.mean() > 0
    assert resp["colormap"] == "viridis_divergent"
    assert resp["background"] is not None and resp["scale"] is not None


# ── 2. Campo uniforme: no hay nada que contornear ────────────────────────────

def test_uniform_field_produces_no_surface(patched_projects_dir):
    """Densidad uniforme → peak de contraste ~0 → ningún nivel produce superficie."""
    n, cell = 20, 10.0
    df = _make_grid_df(np.full((n, n, n), 2.67), cell)
    _setup_run(patched_projects_dir, "flat", "run_1", df)

    resp = build_isosurface_response("flat", "run_1", field="density")
    assert resp["n_levels"] == 0
    assert resp["error"] is not None


# ── 3. Susceptibilidad (magnético) ───────────────────────────────────────────

def test_susceptibility_field(patched_projects_dir):
    """El campo 'susceptibility' contornea susceptibility_si en escala log."""
    n, cell = 36, 10.0
    # Gota de susceptibilidad sobre un fondo bajo (orden de magnitud).
    chi = _gaussian_blob(n, amp=0.05, sigma_cells=5.0, bg=1e-4)
    df = _make_grid_df(chi, cell, value_col="susceptibility_si")
    _setup_run(patched_projects_dir, "mag", "run_1", df)

    resp = build_isosurface_response("mag", "run_1", field="susceptibility")
    assert resp["field"] == "susceptibility"
    assert resp["n_levels"] >= 1
    assert resp["error"] is None


# ── 4. Bordes ────────────────────────────────────────────────────────────────

def test_missing_parquet_returns_catalogued_error(patched_projects_dir):
    """Corrida inexistente → error catalogado, sin crash, levels vacío."""
    resp = build_isosurface_response("nope", "run_x", field="density")
    assert resp["levels"] == []
    assert resp["n_levels"] == 0
    assert resp["error"] is not None


def test_degenerate_grid_single_plane(patched_projects_dir):
    """Grilla con un solo plano en Z (<2 celdas) → sin superficie, error claro."""
    nx, ny, nz, cell = 10, 10, 1, 10.0
    df = _make_grid_df(_gaussian_blob_rect(nx, ny, nz), cell)
    _setup_run(patched_projects_dir, "plane", "run_1", df)

    resp = build_isosurface_response("plane", "run_1", field="density")
    assert resp["n_levels"] == 0
    assert resp["error"] is not None


def test_weak_anomaly_flagged(patched_projects_dir):
    """Anomalía de bajo contraste → weak_anomaly True con aviso."""
    n, cell = 30, 10.0
    # amp minúsculo respecto a la dispersión → pico de contraste bajo.
    vals = _gaussian_blob(n, amp=0.02, sigma_cells=4.0)
    # Ruido de fondo para inflar la escala robusta y bajar el contraste del pico.
    rng = np.random.default_rng(0)
    vals = vals + rng.normal(0.0, 0.05, size=vals.shape)
    df = _make_grid_df(vals, cell)
    _setup_run(patched_projects_dir, "weak", "run_1", df)

    resp = build_isosurface_response("weak", "run_1", field="density")
    # weak_anomaly refleja peak_contrast < 0.60 (mismo umbral que el visor).
    if resp["peak_contrast"] is not None:
        assert resp["weak_anomaly"] == (resp["peak_contrast"] < 0.60)


def _make_coord_only_df(values: np.ndarray, origin: float, step: float) -> pl.DataFrame:
    """DataFrame con SOLO x/y/z en metros (sin ix/iy/iz) — como los block models
    reales del motor (joint), donde x/y/z son coordenadas, no índices de grilla."""
    nx, ny, nz = values.shape
    gi, gj, gk = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    x = origin + gi.ravel() * step
    y = origin + gj.ravel() * step
    z = origin + gk.ravel() * step
    return pl.DataFrame({
        "x": x, "y": y, "z": z,
        "x_m": x, "y_m": y, "z_m": z,
        "density": values.ravel().astype(np.float64),
    })


def test_coordinate_only_grid_no_ix_no_oom(patched_projects_dir):
    """Regresión: block model REAL sin ix/iy/iz, con x/y/z en METROS grandes
    (24..960). El bug tomaba las coordenadas como índices → volumen de ~961³ (GiB)
    → OOM/500. El fix rank/step-encodea por coordenada → grilla compacta."""
    n, step, origin = 20, 48.0, 24.0     # x va de 24 a 24+19*48 = 936 m
    df = _make_coord_only_df(_gaussian_blob(n, amp=0.8, sigma_cells=5.0), origin, step)
    assert "ix" not in df.columns  # el caso que reventaba
    _setup_run(patched_projects_dir, "coordonly", "run_1", df)

    resp = build_isosurface_response("coordonly", "run_1", field="density")
    assert resp["error"] is None
    assert resp["n_levels"] >= 1
    # La grilla debe ser COMPACTA (~20 por eje), no ~937 (coord/1).
    assert resp["grid_dims"]["nx"] <= n + 1
    assert resp["cell_size"]["x"] == step
    # El centro replica el de Arrow: (min+max)/2 de la coordenada.
    assert abs(resp["center_m"]["x"] - (origin + (n - 1) * step / 2.0)) < 1e-6


def test_continuous_coords_hits_oom_guard_gracefully(patched_projects_dir):
    """Coordenadas continuas (no una grilla regular) → el volumen denso sería
    inviable; el tope anti-OOM aborta con gracia (error, sin crash ni OOM)."""
    # x con rango enorme y paso mínimo 1 → nx ~ 1e8 → producto > _MAX_GRID_CELLS.
    x = np.array([0.0, 1.0, 1.0e8, 1.0e8 + 1.0])
    df = pl.DataFrame({
        "x": x,
        "y": np.array([0.0, 48.0, 0.0, 48.0]),
        "z": np.array([0.0, 0.0, 48.0, 48.0]),
        "x_m": x,
        "y_m": np.array([0.0, 48.0, 0.0, 48.0]),
        "z_m": np.array([0.0, 0.0, 48.0, 48.0]),
        "density": np.array([2.7, 3.7, 3.7, 2.7]),
    })
    _setup_run(patched_projects_dir, "cont", "run_1", df)

    resp = build_isosurface_response("cont", "run_1", field="density")
    assert resp["n_levels"] == 0
    assert resp["error"] is not None  # abortó con gracia, no OOM


def test_lod_step_thresholds():
    """F4.7 (medido): step=1 hasta 2M celdas; step=2 por encima (extracción 4-10× más rápida)."""
    from services.isosurface_service import _lod_step
    assert _lod_step(42 * 21 * 42) == 1        # demo real
    assert _lod_step(2_000_000) == 1           # borde inclusivo
    assert _lod_step(2_000_001) == 2
    assert _lod_step(8_000_000) == 2


def _gaussian_blob_rect(nx: int, ny: int, nz: int, amp: float = 0.8, sigma: float = 3.0, bg: float = 2.67) -> np.ndarray:
    cx, cy, cz = (nx - 1) / 2.0, (ny - 1) / 2.0, (nz - 1) / 2.0
    gx, gy, gz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    r2 = (gx - cx) ** 2 + (gy - cy) ** 2 + (gz - cz) ** 2
    return bg + amp * np.exp(-0.5 * r2 / (sigma ** 2))
