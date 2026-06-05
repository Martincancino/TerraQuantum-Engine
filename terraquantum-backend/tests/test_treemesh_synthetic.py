"""
SPRINT 3A — TreeMesh Foundation: tests de validación.
=====================================================

Valida la malla Octree adaptativa (exploration/treemesh.py) y su acoplamiento
con el FORWARD de celdas variables (GravimetryForward._build_sparse_kernel_variable):

  1. test_treemesh_vs_regular_grid
       Con max_refinement_depth=0 (sin refinar), la TreeMesh debe ser PIXEL-PERFECT
       respecto a la grilla regular:
         - centros idénticos a build_voxel_grid (mismo orden Fortran)
         - J_treemesh (ruta variable) == J_regular (ruta uniforme)   [rtol≈1e-14]

  2. test_treemesh_refinement
       Con refinamiento dirigido por sensores, n_cells > base y las celdas cerca
       de los sensores son más pequeñas. El forward de celdas variables construye
       un kernel finito sobre la malla adaptativa (la inversión completa sobre
       Octree es Sprint 3B — Laplaciano adaptativo).

  3. test_treemesh_cell_volumes
       Volúmenes positivos y suma == volumen del dominio (el split 8-way conserva
       el volumen en cualquier nivel de refinamiento).

NO reimplementa kernel, solver ni física: reutiliza GravimetryForward y
checkerboard_test.build_voxel_grid / build_sensor_grid.

Uso:
    python tests/test_treemesh_synthetic.py        # corre los 3 tests, exit(0/1)
    pytest tests/test_treemesh_synthetic.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

try:
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import GravimetryForward
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import GravimetryForward
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid


# ── Configuración pequeña y rápida (anti inverse-crime no aplica: es validación) ─
NX, NY, NZ = 3, 4, 4
BLOCK = 25.0
N_BASE = NX * NY * NZ            # 48 celdas base
CUTOFF = min(3.0 * BLOCK * max(NX, NY, NZ), 5000.0)


def _make_forward() -> GravimetryForward:
    return GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=CUTOFF)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pixel-perfect: TreeMesh sin refinar == grilla regular
# ─────────────────────────────────────────────────────────────────────────────
def test_treemesh_vs_regular_grid():
    """Sin refinamiento: centros y kernel idénticos a la grilla regular."""
    _, _, _, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, BLOCK)
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)

    mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)

    # (a) Mismo número de celdas y centros idénticos (mismo orden Fortran).
    assert mesh.n_cells == N_BASE, f"n_cells={mesh.n_cells} != {N_BASE}"
    centers = mesh.get_cell_centers()
    assert np.array_equal(centers[:, 0], x_c), "centros X difieren de build_voxel_grid"
    assert np.array_equal(centers[:, 1], y_c), "centros Y difieren de build_voxel_grid"
    assert np.array_equal(centers[:, 2], z_c), "centros Z difieren de build_voxel_grid"

    # (b) Tamaños de celda uniformes == BLOCK.
    sizes = mesh.get_cell_sizes()
    assert np.allclose(sizes, BLOCK, rtol=0, atol=1e-12), "tamaños de celda no uniformes"

    # (c) Kernel pixel-perfect: ruta uniforme vs ruta variable.
    J_regular = _make_forward().build_sparse_kernel(x_c, y_c, z_c, sensors).toarray()
    J_treemesh = _make_forward().build_kernel_from_treemesh(mesh, sensors).toarray()

    assert J_regular.shape == J_treemesh.shape == (len(sensors), N_BASE)
    max_abs = float(np.max(np.abs(J_regular - J_treemesh)))
    scale = float(np.max(np.abs(J_regular)))
    rel = max_abs / max(scale, 1e-300)
    assert rel < 1e-14, (
        f"J_treemesh != J_regular (pixel-perfect falló): "
        f"max_abs={max_abs:.3e}, rel={rel:.3e}"
    )
    print(
        f"[1] PIXEL-PERFECT OK | n_cells={mesh.n_cells} | "
        f"max|ΔJ|={max_abs:.3e} | rel={rel:.3e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Refinamiento dirigido por sensores
# ─────────────────────────────────────────────────────────────────────────────
def test_treemesh_refinement():
    """Con refinamiento: más celdas y celdas más pequeñas cerca de sensores."""
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)

    mesh = TreeMesh.from_regular_grid(
        NX, NY, NZ, BLOCK,
        max_refinement_depth=2,
        sensor_coords=sensors,
        refine_radius=2.0 * BLOCK,   # 50 m
    )

    # (a) Más celdas que la base.
    assert mesh.n_cells > N_BASE, f"n_cells={mesh.n_cells} no superó base={N_BASE}"

    # (b) Hay celdas más pequeñas que BLOCK (las refinadas).
    sizes = mesh.get_cell_sizes()
    min_size = float(sizes.min())
    assert min_size < BLOCK, f"min_size={min_size} no es menor que BLOCK={BLOCK}"

    # (c) Las celdas pequeñas están cerca de los sensores; las grandes, lejos.
    centers = mesh.get_cell_centers()
    from scipy.spatial import cKDTree
    dist, _ = cKDTree(sensors).query(centers, k=1)
    cell_min_extent = sizes.min(axis=1)
    refined = cell_min_extent < BLOCK
    coarse = ~refined
    if np.any(refined) and np.any(coarse):
        assert dist[refined].mean() < dist[coarse].mean(), (
            "las celdas refinadas no están, en promedio, más cerca de los sensores"
        )

    # (d) El forward de celdas variables construye un kernel finito sobre la malla.
    J = _make_forward().build_kernel_from_treemesh(mesh, sensors)
    assert J.shape == (len(sensors), mesh.n_cells)
    assert J.nnz > 0, "kernel TreeMesh refinado quedó vacío"
    assert np.isfinite(J.data).all(), "kernel TreeMesh refinado contiene NaN/Inf"

    print(
        f"[2] REFINAMIENTO OK | n_cells={mesh.n_cells} (>{N_BASE}) | "
        f"min_size={min_size:.2f}m | niveles={np.unique(mesh.levels).tolist()} | "
        f"J.shape={J.shape} NNZ={J.nnz:,}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Conservación de volumen
# ─────────────────────────────────────────────────────────────────────────────
def test_treemesh_cell_volumes():
    """Volúmenes positivos y suma == volumen del dominio (split conserva volumen)."""
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)

    for depth in (0, 1, 2):
        mesh = TreeMesh.from_regular_grid(
            NX, NY, NZ, BLOCK,
            max_refinement_depth=depth,
            sensor_coords=sensors if depth > 0 else None,
            refine_radius=2.0 * BLOCK,
        )
        vols = mesh.get_cell_volumes()
        assert (vols > 0).all(), f"volúmenes no positivos en depth={depth}"
        total = float(vols.sum())
        domain = mesh.domain_volume
        assert np.isclose(total, domain, rtol=1e-9), (
            f"depth={depth}: suma vols={total:.6e} != dominio={domain:.6e}"
        )
        print(
            f"[3] VOLUMEN OK (depth={depth}) | n_cells={mesh.n_cells} | "
            f"Σvol={total:.6e} == dominio={domain:.6e} m³"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Runner como script
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  SPRINT 3A — TreeMesh Foundation: validación")
    print("=" * 70)

    failed = 0
    for name, fn in (
        ("test_treemesh_vs_regular_grid", test_treemesh_vs_regular_grid),
        ("test_treemesh_refinement",      test_treemesh_refinement),
        ("test_treemesh_cell_volumes",    test_treemesh_cell_volumes),
    ):
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")

    print("-" * 70)
    if failed == 0:
        print("RESULTADO: 3/3 PASS — Sprint 3A foundation validado.")
        sys.exit(0)
    else:
        print(f"RESULTADO: {failed} test(s) fallaron.")
        sys.exit(1)
