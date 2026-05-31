"""
R3-BE-5 — Tests para build_block_model_response con campos de elevación R3.

Cubre:
  - Parquet legacy sin columnas R3 → has_elevation_data=False, cells con None, sin crash.
  - Parquet enriquecido con columnas R3 → has_elevation_data=True, campos correctos.
  - elevation_range calculado correctamente (min/max ignorando nulls).
  - mode=full, mode=exploration, mode=anomaly — sin crash, comportamiento correcto.
  - Conteos legacy intactos (total_voxels, stored_voxels, returned_voxels).
  - Campos legacy intactos (density, rho, probability, x_m/y_m/z_m).

Todos los tests usan proyectos temporales en tmp_path via monkeypatch.
No usan data histórica real.
"""
import json
import math
from pathlib import Path

import polars as pl
import pytest

from core import block_model_store as store
from services.block_model_service import build_block_model_response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_legacy_parquet(path: Path) -> pl.DataFrame:
    """Parquet sin columnas R3 — simula run anterior a R3."""
    df = pl.DataFrame({
        "ix": [0, 0, 1, 1],
        "iy": [0, 1, 0, 1],
        "iz": [0, 0, 1, 1],
        "x":  [500.0, 500.0, 1500.0, 1500.0],
        "y":  [250.0, 750.0, 250.0,  750.0],
        "z":  [500.0, 500.0, 1500.0, 1500.0],
        "density":     [2.5, 2.6, 2.7, 2.8],
        "rho":         [2.5, 2.6, 2.7, 2.8],
        "probability": [0.8, 0.9, 0.7, 1.0],
        "visual_score":[0.5, 0.6, 0.4, 0.7],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def _make_enriched_parquet(path: Path) -> pl.DataFrame:
    """Parquet con columnas R3 completas — simula run enriquecido con R3-BE-4."""
    df = pl.DataFrame({
        "ix": [0, 0, 1, 1],
        "iy": [0, 1, 0, 1],
        "iz": [0, 0, 1, 1],
        "x":  [500.0, 500.0, 1500.0, 1500.0],
        "y":  [250.0, 750.0, 250.0,  750.0],
        "z":  [500.0, 500.0, 1500.0, 1500.0],
        "density":     [2.5, 2.6, 2.7, 2.8],
        "rho":         [2.5, 2.6, 2.7, 2.8],
        "probability": [0.8, 0.9, 0.7, 1.0],
        "visual_score":[0.5, 0.6, 0.4, 0.7],
        # Columnas R3
        "lat":  [-22.28, -22.29, -22.27, -22.30],
        "lon":  [-68.89, -68.90, -68.88, -68.91],
        "surface_elevation_masl": [3000.0, 3010.0, 2990.0, 3005.0],
        "depth_below_surface_m":  [250.0,  750.0,  250.0,  750.0],
        "voxel_elevation_masl":   [2750.0, 2260.0, 2740.0, 2255.0],
        "georef_confidence":      ["HIGH", "HIGH", "HIGH", "HIGH"],
        "dem_source":             ["mock_v1", "mock_v1", "mock_v1", "mock_v1"],
        "dem_sample_method":      ["bilinear", "bilinear", "bilinear", "bilinear"],
        "spatial_reference_warning": ["", "", "", ""],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def _make_r3_edge_case_parquet(
    path: Path,
    *,
    voxel_values: list,
    surface_values: list,
    depth_values: list,
) -> pl.DataFrame:
    """Parquet enriquecido para bordes null/NaN/inf en campos R3 numericos."""
    n = len(voxel_values)
    df = pl.DataFrame({
        "ix": list(range(n)),
        "iy": [0] * n,
        "iz": [0] * n,
        "x":  [float(i * 10.0) for i in range(n)],
        "y":  [float(i) for i in range(n)],
        "z":  [0.0] * n,
        "density":     [2.5 + (i * 0.1) for i in range(n)],
        "rho":         [2.5 + (i * 0.1) for i in range(n)],
        "probability": [0.8] * n,
        "visual_score":[0.5] * n,
        "lat":  [-22.28] * n,
        "lon":  [-68.89] * n,
        "surface_elevation_masl": surface_values,
        "depth_below_surface_m":  depth_values,
        "voxel_elevation_masl":   voxel_values,
        "georef_confidence":      ["HIGH"] * n,
        "dem_source":             ["mock_v1"] * n,
        "dem_sample_method":      ["bilinear"] * n,
        "spatial_reference_warning": [None] * n,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def _make_anomaly_parquet(path: Path, with_r3: bool = False) -> pl.DataFrame:
    """Parquet de anomalía (subconjunto), con o sin columnas R3."""
    data: dict = {
        "ix": [0],
        "iy": [0],
        "iz": [0],
        "x":  [500.0],
        "y":  [250.0],
        "z":  [500.0],
        "density":     [2.5],
        "rho":         [2.5],
        "probability": [0.8],
        "visual_score":[0.5],
    }
    if with_r3:
        data["lat"] = [-22.28]
        data["lon"] = [-68.89]
        data["surface_elevation_masl"] = [3000.0]
        data["depth_below_surface_m"]  = [250.0]
        data["voxel_elevation_masl"]   = [2750.0]
        data["georef_confidence"]      = ["HIGH"]
        data["dem_source"]             = ["mock_v1"]
        data["dem_sample_method"]      = ["bilinear"]
        data["spatial_reference_warning"] = [""]
    df = pl.DataFrame(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def _setup_project(
    projects_dir: Path,
    project_id: str,
    run_id: str,
    *,
    enriched: bool = False,
    with_anomaly: bool = False,
    anomaly_has_r3: bool = False,
) -> Path:
    """Crea estructura de directorios y archivos para el test."""
    run_dir = projects_dir / project_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    bm_path = run_dir / "block_model.parquet"
    if enriched:
        _make_enriched_parquet(bm_path)
    else:
        _make_legacy_parquet(bm_path)

    if with_anomaly:
        anomaly_path = run_dir / "block_model_anomaly.parquet"
        _make_anomaly_parquet(anomaly_path, with_r3=anomaly_has_r3)

    # project_meta mínimo para que resolve_block_model_reference no falle
    proj_dir = projects_dir / project_id
    meta_path = proj_dir / "project_meta.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps({"project_id": project_id, "latitude": -22.28, "longitude": -68.89}),
            encoding="utf-8",
        )

    return bm_path


def _write_project_meta(projects_dir: Path, project_id: str) -> None:
    proj_dir = projects_dir / project_id
    meta_path = proj_dir / "project_meta.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps({"project_id": project_id, "latitude": -22.28, "longitude": -68.89}),
            encoding="utf-8",
        )


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ── 1. Legacy parquet sin columnas R3 ────────────────────────────────────────

def test_legacy_parquet_has_elevation_data_false(patched_projects_dir):
    """Parquet sin columnas R3 → has_elevation_data=False, sin crash."""
    pid, rid = "legacy_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("has_elevation_data") is False


def test_block_model_response_includes_score_percentiles(patched_projects_dir):
    """El contrato JSON expone percentiles puros para visualizacion frontend."""
    pid, rid = "percentiles_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    score_stats = resp.get("scoreStats", {})
    assert score_stats.get("column") == "visual_score"
    assert score_stats.get("p2") is not None
    assert score_stats.get("p50") is not None
    assert score_stats.get("p85") is not None
    assert score_stats.get("p98") is not None
    assert score_stats.get("isDegenerate") is False
    assert resp.get("visualScoreP85") == score_stats.get("p85")
    assert (
        resp.get("diagnosticStats", {}).get("visual_score", {}).get("p95")
        == resp.get("visualScoreP95")
    )


def test_block_model_response_flags_degenerate_visual_score(patched_projects_dir):
    """Modelo con visual_score uniforme se marca como degenerado."""
    pid, rid = "degenerate_proj", "run_1"
    run_dir = patched_projects_dir / pid / "runs" / rid
    _make_r3_edge_case_parquet(
        run_dir / "block_model.parquet",
        voxel_values=[100.0, 100.0, 100.0, 100.0],
        surface_values=[200.0, 200.0, 200.0, 200.0],
        depth_values=[100.0, 100.0, 100.0, 100.0],
    )
    _write_project_meta(patched_projects_dir, pid)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("isDegenerate") is True
    assert resp.get("visualScoreIsDegenerate") is True
    assert resp.get("scoreStats", {}).get("p85") == 0.5
    assert resp.get("scoreStats", {}).get("p98") == 0.5


def test_legacy_parquet_r3_cell_fields_are_none(patched_projects_dir):
    """Celdas de parquet legacy tienen campos R3 en None."""
    pid, rid = "legacy_proj_2", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    for cell in resp["cells"]:
        assert cell.get("voxel_elevation_masl") is None
        assert cell.get("surface_elevation_masl") is None
        assert cell.get("depth_below_surface_m") is None
        assert cell.get("lat") is None
        assert cell.get("lon") is None


def test_legacy_parquet_elevation_range_all_none(patched_projects_dir):
    """elevation_range de parquet legacy → todos los valores None."""
    pid, rid = "legacy_proj_3", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    er = resp.get("elevation_range", {})
    assert er.get("min_voxel_elevation_masl") is None
    assert er.get("max_voxel_elevation_masl") is None
    assert er.get("min_surface_elevation_masl") is None
    assert er.get("max_surface_elevation_masl") is None
    assert er.get("min_depth_below_surface_m") is None
    assert er.get("max_depth_below_surface_m") is None


# ── 2. Parquet enriquecido con columnas R3 ────────────────────────────────────

def test_enriched_parquet_has_elevation_data_true(patched_projects_dir):
    """Parquet enriquecido → has_elevation_data=True."""
    pid, rid = "enrich_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("has_elevation_data") is True


def test_enriched_parquet_cells_have_voxel_elevation(patched_projects_dir):
    """Celdas de parquet enriquecido incluyen voxel_elevation_masl no null."""
    pid, rid = "enrich_proj_2", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert len(resp["cells"]) > 0
    for cell in resp["cells"]:
        assert cell.get("voxel_elevation_masl") is not None
        assert cell.get("surface_elevation_masl") is not None
        assert cell.get("depth_below_surface_m") is not None


def test_enriched_parquet_cells_have_latlon(patched_projects_dir):
    """Celdas de parquet enriquecido incluyen lat/lon no null."""
    pid, rid = "enrich_proj_3", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    for cell in resp["cells"]:
        assert cell.get("lat") is not None
        assert cell.get("lon") is not None


def test_enriched_parquet_top_dem_source_correct(patched_projects_dir):
    """dem_source top-level viene del parquet enriquecido."""
    pid, rid = "enrich_proj_4", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("dem_source") == "mock_v1"


def test_enriched_parquet_top_georef_confidence_correct(patched_projects_dir):
    """georef_confidence top-level viene del parquet enriquecido."""
    pid, rid = "enrich_proj_5", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("georef_confidence") == "HIGH"


def test_enriched_parquet_elevation_range_correct(patched_projects_dir):
    """elevation_range tiene min/max correctos del parquet enriquecido."""
    pid, rid = "enrich_proj_6", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    er = resp.get("elevation_range", {})
    # voxel_elevation_masl values: [2750.0, 2260.0, 2740.0, 2255.0]
    assert er.get("min_voxel_elevation_masl") == pytest.approx(2255.0, abs=0.1)
    assert er.get("max_voxel_elevation_masl") == pytest.approx(2750.0, abs=0.1)
    # surface_elevation_masl values: [3000.0, 3010.0, 2990.0, 3005.0]
    assert er.get("min_surface_elevation_masl") == pytest.approx(2990.0, abs=0.1)
    assert er.get("max_surface_elevation_masl") == pytest.approx(3010.0, abs=0.1)
    # depth_below_surface_m values: [250.0, 750.0, 250.0, 750.0]
    assert er.get("min_depth_below_surface_m") == pytest.approx(250.0, abs=0.1)
    assert er.get("max_depth_below_surface_m") == pytest.approx(750.0, abs=0.1)


def test_elevation_range_not_null_for_enriched(patched_projects_dir):
    """Todos los valores de elevation_range son non-null para parquet enriquecido."""
    pid, rid = "enrich_proj_7", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    er = resp.get("elevation_range", {})
    for key, val in er.items():
        assert val is not None, f"elevation_range[{key!r}] no debe ser None para parquet enriquecido"


# ── 3. mode=full ──────────────────────────────────────────────────────────────

def test_all_nan_voxel_elevation_has_elevation_data_false(patched_projects_dir):
    """voxel_elevation_masl con solo NaN no cuenta como datos de elevacion."""
    pid, rid = "all_nan_has_elevation", "run_1"
    bm_path = patched_projects_dir / pid / "runs" / rid / "block_model.parquet"
    _make_r3_edge_case_parquet(
        bm_path,
        voxel_values=[float("nan"), float("nan")],
        surface_values=[float("nan"), float("nan")],
        depth_values=[float("nan"), float("nan")],
    )
    _write_project_meta(patched_projects_dir, pid)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    assert resp.get("has_elevation_data") is False


def test_all_nan_elevation_range_returns_none(patched_projects_dir):
    """elevation_range no debe devolver NaN si las columnas R3 son solo NaN."""
    pid, rid = "all_nan_range", "run_1"
    bm_path = patched_projects_dir / pid / "runs" / rid / "block_model.parquet"
    _make_r3_edge_case_parquet(
        bm_path,
        voxel_values=[float("nan"), float("nan")],
        surface_values=[float("nan"), float("nan")],
        depth_values=[float("nan"), float("nan")],
    )
    _write_project_meta(patched_projects_dir, pid)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    er = resp.get("elevation_range", {})
    assert all(value is None for value in er.values())


def test_elevation_range_ignores_nan_and_inf(patched_projects_dir):
    """elevation_range calcula min/max solo con valores finitos."""
    pid, rid = "mixed_non_finite_range", "run_1"
    bm_path = patched_projects_dir / pid / "runs" / rid / "block_model.parquet"
    _make_r3_edge_case_parquet(
        bm_path,
        voxel_values=[float("nan"), None, float("inf"), float("-inf"), 100.0, 250.0],
        surface_values=[float("nan"), None, float("inf"), float("-inf"), 3000.0, 3010.0],
        depth_values=[float("nan"), None, float("inf"), float("-inf"), 10.0, 50.0],
    )
    _write_project_meta(patched_projects_dir, pid)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    er = resp.get("elevation_range", {})
    assert er.get("min_voxel_elevation_masl") == pytest.approx(100.0)
    assert er.get("max_voxel_elevation_masl") == pytest.approx(250.0)
    assert er.get("min_surface_elevation_masl") == pytest.approx(3000.0)
    assert er.get("max_surface_elevation_masl") == pytest.approx(3010.0)
    assert er.get("min_depth_below_surface_m") == pytest.approx(10.0)
    assert er.get("max_depth_below_surface_m") == pytest.approx(50.0)
    assert all(value is None or math.isfinite(value) for value in er.values())


def test_mode_full_returns_r3_fields(patched_projects_dir):
    """mode=full retorna campos R3 si el parquet está enriquecido."""
    pid, rid = "full_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    assert resp.get("has_elevation_data") is True
    for cell in resp["cells"]:
        assert cell.get("voxel_elevation_masl") is not None


def test_mode_full_legacy_no_crash(patched_projects_dir):
    """mode=full con parquet legacy no crashea."""
    pid, rid = "full_legacy", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    assert "cells" in resp
    assert resp.get("has_elevation_data") is False


# ── 4. mode=exploration ───────────────────────────────────────────────────────

def test_mode_exploration_returns_r3_if_enriched(patched_projects_dir):
    """mode=exploration retorna campos R3 si el parquet está enriquecido."""
    pid, rid = "expl_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("has_elevation_data") is True
    assert all(c.get("voxel_elevation_masl") is not None for c in resp["cells"])


# ── 5. mode=anomaly ───────────────────────────────────────────────────────────

def test_mode_anomaly_without_r3_no_crash(patched_projects_dir):
    """mode=anomaly con anomaly parquet sin R3 no crashea → has_elevation_data=False."""
    pid, rid = "anom_proj", "run_1"
    _setup_project(
        patched_projects_dir, pid, rid,
        enriched=True,          # full parquet tiene R3
        with_anomaly=True,      # anomaly parquet existe
        anomaly_has_r3=False,   # pero sin columnas R3
    )

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="anomaly")

    assert "cells" in resp
    # anomaly parquet sin R3 → has_elevation_data False (basado en df_view)
    assert resp.get("has_elevation_data") is False
    # cells no tienen R3
    for cell in resp["cells"]:
        assert cell.get("voxel_elevation_masl") is None


def test_anomaly_mode_elevation_range_uses_view_not_full(patched_projects_dir):
    """mode=anomaly usa df_view para elevation_range, no el full parquet."""
    pid, rid = "anom_range_uses_view", "run_1"
    _setup_project(
        patched_projects_dir, pid, rid,
        enriched=True,
        with_anomaly=True,
        anomaly_has_r3=False,
    )

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="anomaly")

    assert resp.get("has_elevation_data") is False
    er = resp.get("elevation_range", {})
    assert all(value is None for value in er.values())


def test_mode_anomaly_not_available_no_crash(patched_projects_dir):
    """mode=anomaly sin anomaly parquet → warning, sin crash."""
    pid, rid = "anom_missing", "run_1"
    _setup_project(
        patched_projects_dir, pid, rid,
        enriched=True,
        with_anomaly=False,
    )

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="anomaly")

    assert "cells" in resp
    assert any("anomaly" in w.lower() for w in resp.get("warnings", []))


def test_mode_anomaly_with_r3_returns_elevation(patched_projects_dir):
    """mode=anomaly con anomaly parquet enriquecido → has_elevation_data=True."""
    pid, rid = "anom_enriched", "run_1"
    _setup_project(
        patched_projects_dir, pid, rid,
        enriched=True,
        with_anomaly=True,
        anomaly_has_r3=True,
    )

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="anomaly")

    assert resp.get("has_elevation_data") is True


# ── 6. Campos legacy intactos ────────────────────────────────────────────────

def test_legacy_fields_unchanged_enriched(patched_projects_dir):
    """Parquet enriquecido: campos legacy (density, rho, probability) intactos."""
    pid, rid = "legacy_fields", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    for cell in resp["cells"]:
        assert "density" in cell
        assert "rho" in cell
        assert "probability" in cell
        assert "x_m" in cell
        assert "y_m" in cell
        assert "z_m" in cell


def test_voxel_counts_unchanged(patched_projects_dir):
    """Parquet enriquecido: conteos de voxels no cambian."""
    pid, rid = "counts_proj", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=True)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="full")

    # 4 voxeles en el parquet de test
    assert resp.get("total_voxels") is not None
    assert resp.get("stored_voxels") == 4
    assert resp.get("returned_voxels") == 4


def test_total_voxels_not_changed_by_r3_fields(patched_projects_dir):
    """total_voxels, stored_voxels, returned_voxels iguales entre legacy y enriched."""
    pid_leg, rid = "legacy_counts", "run_1"
    pid_enr = "enrich_counts"
    _setup_project(patched_projects_dir, pid_leg, rid, enriched=False)
    _setup_project(patched_projects_dir, pid_enr, rid, enriched=True)

    resp_leg = build_block_model_response(project_id=pid_leg, run_id=rid, mode="full")
    resp_enr = build_block_model_response(project_id=pid_enr, run_id=rid, mode="full")

    assert resp_leg["stored_voxels"] == resp_enr["stored_voxels"]
    assert resp_leg["returned_voxels"] == resp_enr["returned_voxels"]
    assert resp_leg["total_voxels"] == resp_enr["total_voxels"]


# ── 7. top-level legacy fields ────────────────────────────────────────────────

def test_top_level_dem_source_none_for_legacy(patched_projects_dir):
    """dem_source top-level es None para parquet legacy."""
    pid, rid = "dem_src_legacy", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("dem_source") is None


def test_top_level_georef_confidence_none_for_legacy(patched_projects_dir):
    """georef_confidence top-level es None para parquet legacy."""
    pid, rid = "georef_legacy", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert resp.get("georef_confidence") is None


def test_elevation_range_key_always_present(patched_projects_dir):
    """La clave 'elevation_range' siempre está presente en la respuesta."""
    pid, rid = "range_key_test", "run_1"
    _setup_project(patched_projects_dir, pid, rid, enriched=False)

    resp = build_block_model_response(project_id=pid, run_id=rid, mode="exploration")

    assert "elevation_range" in resp
    er = resp["elevation_range"]
    for key in (
        "min_voxel_elevation_masl", "max_voxel_elevation_masl",
        "min_surface_elevation_masl", "max_surface_elevation_masl",
        "min_depth_below_surface_m", "max_depth_below_surface_m",
    ):
        assert key in er
