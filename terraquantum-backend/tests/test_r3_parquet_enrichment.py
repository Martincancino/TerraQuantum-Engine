"""
R3-BE-4 — Tests para elevation_enrichment_service.enrich_block_model_with_elevation.

Todos los tests usan proyectos temporales en tmp_path; no tocan data histórica real.
PROJECTS_DIR se parchea via monkeypatch para aislamiento completo.
"""
import json
from pathlib import Path

import polars as pl
import pytest

from services import block_model_store as store
from services.elevation_enrichment_service import (
    R3_COLUMNS,
    enrich_block_model_with_elevation,
)


# ── Fixtures y helpers ────────────────────────────────────────────────────────

TERRAIN_META_HIGH = {
    "project_id": "test_proj",
    "generated_at": "2026-05-20T00:00:00Z",
    "bbox": {"min_lat": -22.5, "max_lat": -22.1, "min_lon": -69.1, "max_lon": -68.7},
    "dem_rows": 4,
    "dem_cols": 4,
    "cell_size_x_m": 250.0,
    "cell_size_z_m": 250.0,
    "min_elevation_m": 2800.0,
    "max_elevation_m": 3200.0,
    "mean_elevation_m": 3000.0,
    "source": "mock_v1",
    "footprint_source": "utm_pyproj",
    "georef_confidence": "HIGH",
    "terrain_margin_factor": 1.5,
    "warnings": [],
    "center_lat": -22.3,
    "center_lon": -68.9,
    "extent_x_m": 1000.0,
    "extent_z_m": 1000.0,
    "dem_matrix_path": "terrain_dem_matrix.json",
}

TERRAIN_META_MISSING = {**TERRAIN_META_HIGH, "georef_confidence": "MISSING"}

# DEM 4x4 no-zero para evitar warning de "DEM mock"
DEM_4x4 = [
    [3000.0, 3050.0, 3100.0, 3150.0],
    [2950.0, 3000.0, 3050.0, 3100.0],
    [2900.0, 2950.0, 3000.0, 3050.0],
    [2850.0, 2900.0, 2950.0, 3000.0],
]

# DEM all-zero → trigger "DEM mock" warning
DEM_ZERO_2x2 = [[0.0, 0.0], [0.0, 0.0]]


def _write_parquet(path: Path, use_xm_ym_zm: bool = False) -> pl.DataFrame:
    """Crea un block_model.parquet mínimo con 2 filas."""
    if use_xm_ym_zm:
        df = pl.DataFrame({
            "ix": [0, 1],
            "iy": [0, 0],
            "iz": [0, 1],
            "x_m": [100.0, 200.0],
            "y_m": [50.0, 100.0],
            "z_m": [100.0, 200.0],
            "density": [2.6, 2.8],
            "rho": [2.6, 2.8],
            "probability": [1.0, 0.9],
            "visual_score": [0.5, 0.7],
        })
    else:
        df = pl.DataFrame({
            "ix": [0, 1],
            "iy": [0, 0],
            "iz": [0, 1],
            "x": [100.0, 200.0],
            "y": [50.0, 100.0],
            "z": [100.0, 200.0],
            "density": [2.6, 2.8],
            "rho": [2.6, 2.8],
            "probability": [1.0, 0.9],
            "visual_score": [0.5, 0.7],
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def _setup_run(
    projects_dir: Path,
    project_id: str,
    run_id: str,
    *,
    terrain_meta: dict = None,
    dem_matrix: list = None,
    gim: dict = None,
    use_xm_ym_zm: bool = False,
) -> Path:
    """Prepara la estructura de directorios y archivos para un run de test."""
    run_dir = projects_dir / project_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    bm_path = run_dir / "block_model.parquet"
    _write_parquet(bm_path, use_xm_ym_zm=use_xm_ym_zm)

    proj_dir = projects_dir / project_id
    if terrain_meta is not None:
        (proj_dir / "terrain_metadata.json").write_text(
            json.dumps(terrain_meta), encoding="utf-8"
        )
    if dem_matrix is not None:
        (proj_dir / "terrain_dem_matrix.json").write_text(
            json.dumps(dem_matrix), encoding="utf-8"
        )
    if gim is not None:
        (run_dir / "gravity_import_metadata.json").write_text(
            json.dumps(gim), encoding="utf-8"
        )
    return bm_path


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    """Redirige PROJECTS_DIR a tmp_path para aislamiento total."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ── 1. Missing terrain_metadata → skipped ────────────────────────────────────

def test_missing_terrain_metadata_returns_skipped(patched_projects_dir):
    pid, rid = "proj_a", "run_a"
    run_dir = patched_projects_dir / pid / "runs" / rid
    run_dir.mkdir(parents=True)
    proj_dir = patched_projects_dir / pid

    # Parquet presente; dem_matrix presente; terrain_metadata AUSENTE
    _write_parquet(run_dir / "block_model.parquet")
    (proj_dir / "terrain_dem_matrix.json").write_text(
        json.dumps(DEM_4x4), encoding="utf-8"
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "skipped"
    assert any("DEM no disponible" in w for w in result["warnings"])


# ── 2. Missing dem_matrix → skipped ──────────────────────────────────────────

def test_missing_dem_matrix_returns_skipped(patched_projects_dir):
    pid, rid = "proj_b", "run_b"
    run_dir = patched_projects_dir / pid / "runs" / rid
    run_dir.mkdir(parents=True)
    proj_dir = patched_projects_dir / pid

    # Parquet presente; terrain_metadata presente; dem_matrix AUSENTE
    _write_parquet(run_dir / "block_model.parquet")
    (proj_dir / "terrain_metadata.json").write_text(
        json.dumps(TERRAIN_META_HIGH), encoding="utf-8"
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "skipped"
    assert any("DEM no disponible" in w for w in result["warnings"])


# ── 3. Missing block_model.parquet → FileNotFoundError ───────────────────────

def test_missing_block_model_raises(patched_projects_dir):
    pid, rid = "proj_c", "run_c"
    (patched_projects_dir / pid / "runs" / rid).mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="block_model.parquet"):
        enrich_block_model_with_elevation(pid, rid)


# ── 4. Enrichment agrega columnas R3 ─────────────────────────────────────────

def test_enrichment_adds_r3_columns(patched_projects_dir):
    pid, rid = "proj_d", "run_d"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "ok"
    for col in R3_COLUMNS:
        assert col in result["columns_added"], f"Columna R3 ausente: {col}"


# ── 5. depth_below_surface_m = y_m ───────────────────────────────────────────

def test_depth_below_surface_equals_y(patched_projects_dir):
    pid, rid = "proj_e", "run_e"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )

    enrich_block_model_with_elevation(pid, rid)

    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    assert "depth_below_surface_m" in df.columns
    # La columna coordenada es "y" (legacy), valores = [50.0, 100.0]
    for row in df.iter_rows(named=True):
        assert row["depth_below_surface_m"] == pytest.approx(row["y"], abs=1e-6)


# ── 6. voxel_elevation_masl = surface_elevation_masl - depth ─────────────────

def test_voxel_elevation_formula(patched_projects_dir):
    pid, rid = "proj_f", "run_f"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )

    enrich_block_model_with_elevation(pid, rid)

    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    for row in df.iter_rows(named=True):
        surf = row["surface_elevation_masl"]
        depth = row["depth_below_surface_m"]
        voxel = row["voxel_elevation_masl"]
        if surf is not None:
            assert voxel == pytest.approx(surf - depth, abs=1e-6)
        else:
            assert voxel is None


# ── 7. Proyecto UTM con epsg_code → lat/lon no null ──────────────────────────

def test_utm_project_calculates_latlon(patched_projects_dir):
    pid, rid = "proj_g", "run_g"
    gim = {
        "coordinate_transform": {
            "input_coordinate_system": "utm",
            "x_min_raw": 350000.0,
            "z_min_raw": 7494000.0,
            "epsg_code": 32719,
            "utm_zone": "19S",
        }
    }
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
        gim=gim,
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "ok"
    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    lats = df["lat"].to_list()
    lons = df["lon"].to_list()

    assert all(v is not None for v in lats), "lat no debe ser null para proyecto UTM"
    assert all(v is not None for v in lons), "lon no debe ser null para proyecto UTM"
    for lat_v in lats:
        assert -90.0 <= lat_v <= 90.0
    for lon_v in lons:
        assert -180.0 <= lon_v <= 180.0


# ── 8. MISSING georef → lat/lon null y elevation null ────────────────────────

def test_missing_georef_leaves_elevation_and_latlon_null(patched_projects_dir):
    pid, rid = "proj_h", "run_h"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_MISSING,
        dem_matrix=DEM_4x4,
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "ok"
    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    assert all(v is None for v in df["lat"].to_list()), "lat debe ser null para MISSING"
    assert all(v is None for v in df["lon"].to_list()), "lon debe ser null para MISSING"
    assert all(
        v is None for v in df["surface_elevation_masl"].to_list()
    ), "surface_elevation debe ser null para MISSING"
    assert all(
        v is None for v in df["voxel_elevation_masl"].to_list()
    ), "voxel_elevation debe ser null para MISSING"
    # depth siempre presente
    assert all(
        v is not None for v in df["depth_below_surface_m"].to_list()
    )


# ── 9. Parquet legacy con x/y/z funciona ─────────────────────────────────────

def test_legacy_xyz_columns_supported(patched_projects_dir):
    pid, rid = "proj_i", "run_i"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
        use_xm_ym_zm=False,  # columnas x/y/z
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "ok"
    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    assert "depth_below_surface_m" in df.columns


# ── 10. Parquet con x_m/y_m/z_m funciona ────────────────────────────────────

def test_xm_ym_zm_columns_supported(patched_projects_dir):
    pid, rid = "proj_j", "run_j"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
        use_xm_ym_zm=True,  # columnas x_m/y_m/z_m
    )

    result = enrich_block_model_with_elevation(pid, rid)

    assert result["status"] == "ok"
    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    assert "depth_below_surface_m" in df.columns
    # depth debe igualar y_m
    for row in df.iter_rows(named=True):
        assert row["depth_below_surface_m"] == pytest.approx(row["y_m"], abs=1e-6)


# ── 11. Re-enrich no duplica columnas ────────────────────────────────────────

def test_re_enrich_no_duplicate_columns(patched_projects_dir):
    pid, rid = "proj_k", "run_k"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )

    enrich_block_model_with_elevation(pid, rid)
    enrich_block_model_with_elevation(pid, rid)

    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    for col in R3_COLUMNS:
        count = df.columns.count(col)
        assert count == 1, f"Columna duplicada: {col} (aparece {count} veces)"


# ── 12. No cambia número de filas ─────────────────────────────────────────────

def test_no_row_count_change(patched_projects_dir):
    pid, rid = "proj_l", "run_l"
    bm_path = _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )
    original_count = pl.read_parquet(str(bm_path)).height

    enrich_block_model_with_elevation(pid, rid)

    assert pl.read_parquet(str(bm_path)).height == original_count


# ── 13. No altera density/rho/visual_score ───────────────────────────────────

def test_original_columns_unchanged(patched_projects_dir):
    pid, rid = "proj_m", "run_m"
    bm_path = _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )
    df_before = pl.read_parquet(str(bm_path))

    enrich_block_model_with_elevation(pid, rid)

    df_after = pl.read_parquet(str(bm_path))
    for col in ("density", "rho", "probability", "visual_score"):
        if col in df_before.columns:
            assert df_before[col].to_list() == pytest.approx(
                df_after[col].to_list(), abs=1e-9
            ), f"Columna {col!r} fue alterada"


# ── 14. spatial_reference_warning cuando DEM mock ────────────────────────────

def test_spatial_reference_warning_for_mock_dem(patched_projects_dir):
    pid, rid = "proj_n", "run_n"
    _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_ZERO_2x2,
    )

    enrich_block_model_with_elevation(pid, rid)

    df = pl.read_parquet(
        str(patched_projects_dir / pid / "runs" / rid / "block_model.parquet")
    )
    row_warns = df["spatial_reference_warning"].to_list()
    assert all(
        "mock" in (w or "").lower() for w in row_warns
    ), f"Se esperaba warning de DEM mock en todas las filas; obtuvo: {row_warns}"


# ── 15. overwrite=True reemplaza block_model.parquet ─────────────────────────

def test_overwrite_true_replaces_block_model(patched_projects_dir):
    pid, rid = "proj_o", "run_o"
    bm_path = _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )

    result = enrich_block_model_with_elevation(pid, rid, overwrite=True)

    assert result["status"] == "ok"
    assert bm_path.exists(), "block_model.parquet debe seguir existiendo"
    df = pl.read_parquet(str(bm_path))
    assert "depth_below_surface_m" in df.columns
    # Archivo enriquecido separado NO debe existir
    enriched = bm_path.parent / "block_model_enriched.parquet"
    assert not enriched.exists(), "overwrite=True no debe crear block_model_enriched.parquet"


# ── 16. overwrite=False crea block_model_enriched.parquet ────────────────────

def test_overwrite_false_creates_enriched_file(patched_projects_dir):
    pid, rid = "proj_p", "run_p"
    bm_path = _setup_run(
        patched_projects_dir, pid, rid,
        terrain_meta=TERRAIN_META_HIGH,
        dem_matrix=DEM_4x4,
    )
    original_cols = pl.read_parquet(str(bm_path)).columns

    result = enrich_block_model_with_elevation(pid, rid, overwrite=False)

    assert result["status"] == "ok"
    enriched_path = bm_path.parent / "block_model_enriched.parquet"
    assert enriched_path.exists(), "block_model_enriched.parquet debe existir"

    df_enriched = pl.read_parquet(str(enriched_path))
    assert "depth_below_surface_m" in df_enriched.columns

    # block_model.parquet original no debe tener columnas R3
    df_orig = pl.read_parquet(str(bm_path))
    assert df_orig.columns == original_cols, (
        "overwrite=False no debe modificar block_model.parquet"
    )
