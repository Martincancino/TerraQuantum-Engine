"""
FASE 5.3 God-Tier — Tests del modelo categórico comprimido (Sparse Voxel DAG).

Cubre:
  - Correctitud: get_label(ix,iy,iz) == grilla original para TODOS los vóxeles.
  - Compresión: regiones homogéneas colapsan (DAG ≪ vóxeles); octree de un solo
    color = 1 nodo; checkerboard = peor caso (poca compresión).
  - Padding no-pow2: dims originales preservados, query fuera de dims = EMPTY.
  - Round-trip .npz.
  - Build desde CoRegisteredVolume (clasificación por binning).
  - Dedup: dos subárboles idénticos comparten id (n_nodes acotado).
"""

import numpy as np
import polars as pl
import pytest

from services.svdag_service import (
    EMPTY_LABEL,
    SVDAG,
    build_categorical_from_volume,
    build_svdag_from_labels,
    export_categorical_svdag,
)


def _roundtrip_correct(grid: np.ndarray, dag: SVDAG):
    nx, ny, nz = grid.shape
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                assert dag.get_label(ix, iy, iz) == int(grid[ix, iy, iz]), (
                    f"mismatch en ({ix},{iy},{iz})"
                )


def test_query_matches_original_grid():
    rng = np.random.default_rng(0)
    grid = rng.integers(0, 4, size=(8, 8, 8)).astype(np.int32)
    dag = build_svdag_from_labels(grid)
    _roundtrip_correct(grid, dag)
    assert np.array_equal(dag.to_dense(), grid)


def test_homogeneous_collapses_to_single_node():
    """Un cubo de un solo color colapsa al root = una hoja."""
    grid = np.full((16, 16, 16), 3, dtype=np.int32)
    dag = build_svdag_from_labels(grid)
    # root homogéneo → el build retorna la hoja directamente; 1 solo nodo (la hoja).
    assert dag.node_is_leaf[dag.root]
    assert dag.get_label(5, 9, 2) == 3
    st = dag.stats()
    assert st["n_dag_nodes"] == 1
    assert st["compression_vs_voxels"] > 1000  # 16³ = 4096 vóxeles en 1 nodo


def test_empty_grid_is_single_empty_leaf():
    grid = np.zeros((8, 8, 8), dtype=np.int32)
    dag = build_svdag_from_labels(grid)
    assert dag.n_nodes == 1
    assert dag.node_is_leaf[dag.root]
    assert dag.get_label(0, 0, 0) == EMPTY_LABEL


def test_compression_beats_dense_octree():
    """Modelo con un cuerpo compacto comprime mucho mejor que el octree denso."""
    grid = np.zeros((16, 16, 16), dtype=np.int32)
    grid[4:8, 4:8, 4:8] = 2  # bloque compacto homogéneo
    dag = build_svdag_from_labels(grid)
    _roundtrip_correct(grid, dag)
    st = dag.stats()
    assert st["compression_vs_octree"] > 1.0
    assert st["n_dag_nodes"] < st["dense_octree_nodes"]


def test_checkerboard_worst_case_still_correct():
    """Patrón alternado = poca compresión, pero la query DEBE seguir correcta."""
    gx, gy, gz = np.mgrid[0:8, 0:8, 0:8]
    grid = ((gx + gy + gz) % 2).astype(np.int32) + 1  # clases 1/2 alternadas (sin EMPTY)
    dag = build_svdag_from_labels(grid)
    _roundtrip_correct(grid, dag)


def test_dedup_shares_identical_subtrees():
    """Dos mitades idénticas → los subárboles se comparten (dedup)."""
    half = np.zeros((4, 8, 8), dtype=np.int32)
    half[1:3, 1:3, 1:3] = 5
    grid = np.concatenate([half, half], axis=0)  # (8,8,8), mitades idénticas
    dag = build_svdag_from_labels(grid)
    _roundtrip_correct(grid, dag)
    # El root tiene 8 hijos; los octantes de ambas mitades coinciden en pares → dedup.
    # Verificación indirecta: nodos < octree denso y query correcta (ya validada).
    assert dag.n_nodes < dag.stats()["dense_octree_nodes"]


def test_non_pow2_padding():
    """Dims no potencia de 2 → padea a cubo, preserva dims, query fuera = EMPTY."""
    rng = np.random.default_rng(1)
    grid = rng.integers(0, 3, size=(5, 6, 7)).astype(np.int32)
    dag = build_svdag_from_labels(grid)
    assert dag.dims == (5, 6, 7)
    assert dag.side == 8  # next_pow2(7)
    _roundtrip_correct(grid, dag)
    # Fuera de las dims originales → EMPTY (zona de padding).
    assert dag.get_label(7, 7, 7) == EMPTY_LABEL
    assert dag.get_label(5, 0, 0) == EMPTY_LABEL


def test_npz_roundtrip(tmp_path):
    rng = np.random.default_rng(2)
    grid = rng.integers(0, 4, size=(8, 8, 8)).astype(np.int32)
    dag = build_svdag_from_labels(grid)
    p = dag.to_npz(str(tmp_path / "dag.npz"))
    dag2 = SVDAG.from_npz(p)
    assert dag2.dims == dag.dims
    assert dag2.side == dag.side
    assert dag2.root == dag.root
    _roundtrip_correct(grid, dag2)


def test_n_categories_excludes_empty():
    grid = np.zeros((8, 8, 8), dtype=np.int32)
    grid[0, 0, 0] = 1
    grid[1, 1, 1] = 2
    grid[2, 2, 2] = 2
    dag = build_svdag_from_labels(grid)
    assert dag.n_categories == 2  # clases {1,2}, EMPTY no cuenta


def test_rejects_non_integer_grid():
    with pytest.raises(ValueError, match="entero"):
        build_svdag_from_labels(np.zeros((4, 4, 4), dtype=np.float64))


# ─────────────────────────────────────────────────────────────────────────────
# Integración con el CoRegisteredVolume de 5.1/5.2
# ─────────────────────────────────────────────────────────────────────────────

def _make_volume(tmp_path):
    from services.volumetric_service import build_coregistered_volume_from_parquets
    nx, ny, nz, bs = 8, 8, 8, 10.0
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = gx.flatten(order="F"); iy = gy.flatten(order="F"); iz = gz.flatten(order="F")
    x = ix * bs + bs / 2; y = iy * bs + bs / 2; z = iz * bs + bs / 2
    n = len(ix)
    # densidad con gradiente para que el binning produzca varias clases
    density = 2.6 + (ix + iy + iz) * 0.05
    p = tmp_path / "grav.parquet"
    pl.DataFrame({
        "ix": ix.astype(int), "iy": iy.astype(int), "iz": iz.astype(int),
        "x_m": x, "y_m": y, "z_m": z,
        "density_t_m3": density.astype(float),
        "is_active": np.ones(n, dtype=bool),
    }).write_parquet(str(p))
    return build_coregistered_volume_from_parquets(gravity_path=str(p))


def test_build_categorical_from_volume(tmp_path):
    vol = _make_volume(tmp_path)
    grid, meta = build_categorical_from_volume(vol, channel="density", n_classes=4)
    assert grid.shape == vol.dims
    assert meta["channel"] == "density"
    # 4 clases activas (sin EMPTY) porque todos los vóxeles están activos
    active_classes = set(int(v) for v in np.unique(grid))
    assert EMPTY_LABEL not in active_classes or (grid == EMPTY_LABEL).sum() == 0
    assert len(active_classes - {EMPTY_LABEL}) >= 2


def test_export_pipeline_from_volume(tmp_path):
    vol = _make_volume(tmp_path)
    info = export_categorical_svdag(
        output_dir=str(tmp_path), run_prefix="model",
        volume=vol, channel="density", n_classes=4,
    )
    assert info["npz_path"].endswith("_svdag.npz")
    assert info["n_dag_nodes"] >= 1
    assert "categorization" in info
    # SVDAG reconstruido debe coincidir con la grilla clasificada
    grid, _ = build_categorical_from_volume(vol, channel="density", n_classes=4)
    dag = SVDAG.from_npz(info["npz_path"])
    _roundtrip_correct(grid, dag)


def test_export_pipeline_from_explicit_labels(tmp_path):
    """Etiquetas explícitas (p.ej. PGI predict_class / Fase 7) alimentan el SVDAG."""
    rng = np.random.default_rng(3)
    grid = rng.integers(0, 3, size=(8, 8, 8)).astype(np.int32)
    info = export_categorical_svdag(
        output_dir=str(tmp_path), run_prefix="pgi", label_grid=grid,
    )
    dag = SVDAG.from_npz(info["npz_path"])
    _roundtrip_correct(grid, dag)


def test_export_requires_a_source(tmp_path):
    with pytest.raises(ValueError, match="label_grid o volume"):
        export_categorical_svdag(output_dir=str(tmp_path), run_prefix="x")
