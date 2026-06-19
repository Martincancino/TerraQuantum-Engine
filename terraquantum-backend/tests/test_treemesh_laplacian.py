"""
FASE 17 - Laplacian Non-Uniform Validation (Tarea 4): TreeMesh Integration
===========================================================================

Valida que el Laplaciano octree adaptativo (TreeMesh.build_laplacian_octree)
y el solver TreeMesh completo producen resultados sensatos.

  1. test_treemesh_laplacian_builds
       - Crear TreeMesh coarse/refinado cerca de sensores
       - Construir L_treemesh via mesh.build_laplacian_octree()
       - Verificar: shape = (n_cells, n_cells)
       - Verificar: simetrico (max|L-Lt| < 1e-12)
       - Verificar: SPSD (positive semi-definite):
           * Diagonal NEGATIVA (convencion TQ: L = W - D)
           * Suma de filas ~ 0 (espacio nulo = [1,...,1])
           * off-diagonales >= 0

  2. test_treemesh_inversion_converges
       - Grid base 4x4x4 sin refinamiento (64 celdas, problema pequeno)
       - Inversión con solve_inversion_treemesh
       - Verificar que iter_lim=20 da <5% error vs iter_lim=500
         (para 64 celdas LSQR converge en pocas iteraciones)
       - Verificar: sin NaN, dentro de bounds, misfit razonable

Nota: test_laplacian_octree.py (Sprint 3B) cubre la regularidad estructural y
pixel-perfect recovery. Este archivo se enfoca en SPD y convergencia rapida.

Uso:
    python -m pytest tests/test_treemesh_laplacian.py -v
"""

from __future__ import annotations

import os
import sys

import numpy as np
import scipy.sparse as sp

try:
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import (
        GravimetryForward,
        solve_inversion_treemesh,
    )
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import (
        GravimetryForward,
        solve_inversion_treemesh,
    )
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid


# -- Configuracion compartida -------------------------------------------------
NX, NY, NZ = 4, 4, 4
BLOCK = 50.0
N_BASE = NX * NY * NZ
CUTOFF = min(3.0 * BLOCK * max(NX, NY, NZ), 5000.0)
BASE_DENSITY = 2.6


def _make_sensors():
    return build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)


def _make_forward():
    return GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=CUTOFF)


# -----------------------------------------------------------------------------
# 1. El Laplaciano TreeMesh se construye correctamente (shape + SPSD)
# -----------------------------------------------------------------------------
def test_treemesh_laplacian_builds():
    """
    TreeMesh (coarse + refinado) construye Laplaciano con propiedades SPSD:
      - shape (n_cells, n_cells)
      - Simetrico: max|L-Lt| < 1e-12
      - Diagonal negativa (convencion TQ)
      - off-diagonales >= 0
      - Suma de filas ~ 0 (espacio nulo = ones)
    """
    sensors = _make_sensors()

    for depth in (0, 2):
        mesh = TreeMesh.from_regular_grid(
            NX, NY, NZ, BLOCK,
            max_refinement_depth=depth,
            sensor_coords=sensors if depth > 0 else None,
            refine_radius=2.0 * BLOCK,
        )
        L = mesh.build_laplacian_octree()
        Ld = L.toarray()
        n = mesh.n_cells

        # Shape
        assert L.shape == (n, n), f"depth={depth}: shape={L.shape} != ({n},{n})"

        # Simetria
        asym = float(np.max(np.abs(Ld - Ld.T)))
        assert asym < 1e-12, f"depth={depth}: max|L-Lt|={asym:.2e} > 1e-12"

        # Diagonal negativa
        diag = np.diag(Ld)
        assert np.all(diag < 0), f"depth={depth}: hay entradas diagonales >= 0"

        # off-diagonal >= 0
        off = Ld.copy()
        np.fill_diagonal(off, 0.0)
        assert float(np.min(off)) >= -1e-15, f"depth={depth}: off-diagonal negativa"

        # Suma de filas ~ 0 (espacio nulo = [1,...,1])
        row_sums = np.abs(Ld.sum(axis=1))
        max_row_sum = float(np.max(row_sums))
        assert max_row_sum < 1e-9, (
            f"depth={depth}: max|row_sum|={max_row_sum:.2e} > 1e-9"
        )

        print(
            f"[TREEMESH 1] depth={depth} | n_cells={n} | NNZ={L.nnz:,} | "
            f"max|L-Lt|={asym:.1e} | max|row_sum|={max_row_sum:.1e} PASS"
        )


# -----------------------------------------------------------------------------
# 2. La inversion sobre TreeMesh converge en pocas iteraciones LSQR
# -----------------------------------------------------------------------------
def test_treemesh_inversion_converges():
    """
    Para grid base 4x4x4 sin refinamiento (64 celdas), el solver LSQR
    converge rapidamente: solucion iter_lim=20 difiere <5% de iter_lim=500.

    Tambien verifica:
      - Sin NaN/Inf en la densidad recuperada
      - Dentro de bounds [density_min, density_max]
      - Misfit < 60%
      - Contraste positivo recuperado cerca de la anomalia sintetica

    Nota: grillas grandes (depth=2, ~2052 celdas) necesitan mas iteraciones;
    esa cobertura esta en test_laplacian_octree.py::test_inversion_with_treemesh.
    """
    _, _, _, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, BLOCK)
    sensors = _make_sensors()

    # Modelo verdadero: bloque denso en el cuadrante central
    contrast_true = np.zeros(N_BASE, dtype=np.float64)
    cx = NX * BLOCK * 0.5
    cz = NZ * BLOCK * 0.5
    block_mask = (
        (np.abs(x_c - cx) <= BLOCK)
        & (np.abs(z_c - cz) <= BLOCK)
        & (y_c >= BLOCK) & (y_c <= 3.0 * BLOCK)
    )
    contrast_true[block_mask] = 0.8
    assert block_mask.any(), "bloque sintetico vacio"

    # Datos sinteticos en grilla regular
    G_true = _make_forward().build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = np.asarray(G_true @ contrast_true).ravel()
    assert np.isfinite(g_obs).all() and np.linalg.norm(g_obs) > 0

    # Malla TreeMesh SIN refinamiento: 64 celdas = problema pequeno y bien cond
    mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)
    assert mesh.n_cells == N_BASE, f"esperado {N_BASE} celdas, obtenido {mesh.n_cells}"

    # Solucion de referencia (iter_lim=500, convergencia completa)
    meta_ref = {}
    dens_ref, _, misfit_ref = solve_inversion_treemesh(
        mesh=mesh,
        g_observed=g_obs,
        sensor_coords=sensors,
        forward_model=_make_forward(),
        lambda_mag=3.0,
        alpha_spatial=1.0,
        depth_beta=2.0,
        base_density=BASE_DENSITY,
        density_min=BASE_DENSITY,
        density_max=4.2,
        solver_meta=meta_ref,
        iter_lim=500,
    )

    # Solucion con iter_lim=20 (test de convergencia rapida)
    meta_fast = {}
    dens_fast, _, misfit_fast = solve_inversion_treemesh(
        mesh=mesh,
        g_observed=g_obs,
        sensor_coords=sensors,
        forward_model=_make_forward(),
        lambda_mag=3.0,
        alpha_spatial=1.0,
        depth_beta=2.0,
        base_density=BASE_DENSITY,
        density_min=BASE_DENSITY,
        density_max=4.2,
        solver_meta=meta_fast,
        iter_lim=20,
    )

    # (a) Solucion de referencia valida
    assert np.isfinite(dens_ref).all(), "dens_ref contiene NaN/Inf"
    assert dens_ref.min() >= BASE_DENSITY - 1e-9, "dens_ref fuera de bounds_min"
    assert dens_ref.max() <= 4.2 + 1e-9, "dens_ref fuera de bounds_max"
    assert misfit_ref < 60.0, f"misfit_ref alto: {misfit_ref:.1f}%"
    assert (dens_ref - BASE_DENSITY).max() > 0.05, "dens_ref sin contraste positivo"

    # (b) Solucion rapida valida
    assert np.isfinite(dens_fast).all(), "dens_fast contiene NaN/Inf"
    assert dens_fast.min() >= BASE_DENSITY - 1e-9, "dens_fast fuera de bounds_min"
    assert dens_fast.max() <= 4.2 + 1e-9, "dens_fast fuera de bounds_max"

    # (c) Convergencia: para 64 celdas, 20 iters es suficiente
    err_fast = float(
        np.linalg.norm(dens_ref - dens_fast) / max(np.linalg.norm(dens_ref), 1e-10)
    )
    assert err_fast < 0.05, (
        f"iter_lim=20 difiere {err_fast:.3f} > 5% vs iter_lim=500 "
        f"para {N_BASE} celdas"
    )

    print(
        f"[TREEMESH 2] convergence PASS | n_cells={mesh.n_cells} | "
        f"misfit_ref={misfit_ref:.2f}% | misfit_fast={misfit_fast:.2f}% | "
        f"err(20vs500)={err_fast:.4f} (<5%)"
    )


# -----------------------------------------------------------------------------
# Runner como script
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  FASE 17 - Tarea 4: TreeMesh Laplacian Integration Test")
    print("=" * 70)

    failed = 0
    for name, fn in (
        ("test_treemesh_laplacian_builds",    test_treemesh_laplacian_builds),
        ("test_treemesh_inversion_converges", test_treemesh_inversion_converges),
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
        print("RESULTADO: 2/2 PASS - TreeMesh Laplaciano validado.")
        sys.exit(0)
    else:
        print(f"RESULTADO: {failed} test(s) fallaron.")
        sys.exit(1)
