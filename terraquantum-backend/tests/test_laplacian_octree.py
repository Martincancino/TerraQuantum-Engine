"""
SPRINT 3B — Laplaciano Octree + solver TreeMesh: tests de validación.
=====================================================================

Valida la regularización adaptativa (TreeMesh.build_laplacian_octree) y el solver
paralelo mínimo (gravimetry.solve_inversion_treemesh), SIN tocar el solver de
grilla regular (GravimetryInversion.solve_inversion_lsqr permanece intacto).

  1. test_laplacian_octree_structure
       Propiedades del operador de difusión:
         - Simétrico (L == L.T)
         - Diagonal negativa (self-coupling)
         - Suma de filas ≈ 0 (operador de masa)

  2. test_laplacian_regular_grid_recovery
       Sin refinamiento (max_refinement_depth=0), el Laplaciano Octree debe ser
       IDÉNTICO al Laplaciano de la grilla regular en su ruta tensor-mesh
       (_build_laplacian con hx=hy=hz constantes), mismo orden Fortran → la
       convención w_ij = 2/(h_i+h_j) reproduce la grilla regular pixel-perfect.

  3. test_inversion_with_treemesh
       End-to-end: datos sintéticos de un bloque denso + inversión sobre TreeMesh
       refinada. El solver debe converger (misfit y chi² razonables), no producir
       NaN y recuperar contraste positivo donde está la anomalía.

Uso:
    python tests/test_laplacian_octree.py        # corre los 3 tests, exit(0/1)
    pytest tests/test_laplacian_octree.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

try:
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import (
        GravimetryForward,
        GravimetryInversion,
        solve_inversion_treemesh,
    )
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import (
        GravimetryForward,
        GravimetryInversion,
        solve_inversion_treemesh,
    )
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid


# ── Configuración pequeña y rápida ────────────────────────────────────────────
NX, NY, NZ = 4, 4, 4
BLOCK = 50.0
N_BASE = NX * NY * NZ
CUTOFF = min(3.0 * BLOCK * max(NX, NY, NZ), 5000.0)
BASE_DENSITY = 2.6


def _make_forward() -> GravimetryForward:
    return GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=CUTOFF)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Propiedades estructurales del Laplaciano Octree
# ─────────────────────────────────────────────────────────────────────────────
def test_laplacian_octree_structure():
    """Simétrico, diagonal negativa, suma de filas ≈ 0 (con y sin refinamiento)."""
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)

    for depth in (0, 2):
        mesh = TreeMesh.from_regular_grid(
            NX, NY, NZ, BLOCK,
            max_refinement_depth=depth,
            sensor_coords=sensors if depth > 0 else None,
            refine_radius=2.0 * BLOCK,
        )
        L = mesh.build_laplacian_octree()
        Ld = L.toarray()

        assert L.shape == (mesh.n_cells, mesh.n_cells), "shape del Laplaciano incorrecta"
        # Simétrico
        asym = float(np.max(np.abs(Ld - Ld.T)))
        assert asym < 1e-12, f"depth={depth}: Laplaciano no simétrico (max|L-Lᵀ|={asym:.3e})"
        # Diagonal negativa (toda celda tiene ≥1 vecino en estas mallas)
        diag = np.diag(Ld)
        assert np.all(diag < 0), f"depth={depth}: hay diagonales no negativas"
        # Suma de filas ≈ 0
        row_sums = np.abs(Ld.sum(axis=1))
        assert float(np.max(row_sums)) < 1e-9, (
            f"depth={depth}: suma de filas no nula (max={float(np.max(row_sums)):.3e})"
        )
        # Off-diagonales no negativas (acoplamiento difusivo)
        off = Ld - np.diag(diag)
        assert float(np.min(off)) >= -1e-15, f"depth={depth}: off-diagonal negativa"

        print(
            f"[1] ESTRUCTURA OK (depth={depth}) | n_cells={mesh.n_cells} | "
            f"NNZ={L.nnz:,} | max|L-Lᵀ|={asym:.1e} | max|Σfila|={float(np.max(row_sums)):.1e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Recuperación pixel-perfect de la grilla regular (sin refinar)
# ─────────────────────────────────────────────────────────────────────────────
def test_laplacian_regular_grid_recovery():
    """max_refinement_depth=0 → Laplaciano idéntico a la ruta tensor-mesh regular."""
    mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)
    assert mesh.n_cells == N_BASE, f"n_cells={mesh.n_cells} != {N_BASE}"

    L_octree = mesh.build_laplacian_octree().toarray()

    # Laplaciano regular en su ruta tensor-mesh con anchos constantes == BLOCK.
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)
    hx = np.full(NX, BLOCK, dtype=np.float64)
    hy = np.full(NY, BLOCK, dtype=np.float64)
    hz = np.full(NZ, BLOCK, dtype=np.float64)
    L_regular = inv._build_laplacian(hx=hx, hy=hy, hz=hz).toarray()

    assert L_octree.shape == L_regular.shape == (N_BASE, N_BASE)
    max_abs = float(np.max(np.abs(L_octree - L_regular)))
    scale = float(np.max(np.abs(L_regular)))
    rel = max_abs / max(scale, 1e-300)
    assert rel < 1e-12, (
        f"Laplaciano Octree != regular (recovery falló): "
        f"max_abs={max_abs:.3e}, rel={rel:.3e}"
    )
    print(
        f"[2] RECOVERY OK | n_cells={mesh.n_cells} | "
        f"max|ΔL|={max_abs:.3e} | rel={rel:.3e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Inversión end-to-end sobre TreeMesh refinada
# ─────────────────────────────────────────────────────────────────────────────
def test_inversion_with_treemesh():
    """Datos sintéticos de un bloque denso → inversión Octree converge sin NaN."""
    _, _, _, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, BLOCK)
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)

    # Modelo verdadero: bloque denso (+0.8 t/m³) en el cuadrante central, a media
    # profundidad. Contraste sobre la grilla regular (orden Fortran).
    contrast_true = np.zeros(N_BASE, dtype=np.float64)
    cx, cz = NX * BLOCK * 0.5, NZ * BLOCK * 0.5
    block = (
        (np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
        & (y_c >= BLOCK) & (y_c <= 3.0 * BLOCK)
    )
    contrast_true[block] = 0.8
    assert block.any(), "el bloque sintético quedó vacío"

    # Datos sintéticos: forward de la grilla regular (consistente con la malla base).
    G_true = _make_forward().build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = np.asarray(G_true @ contrast_true).ravel()
    assert np.isfinite(g_obs).all() and np.linalg.norm(g_obs) > 0, "datos sintéticos degenerados"

    # Malla Octree refinada cerca de los sensores.
    mesh = TreeMesh.from_regular_grid(
        NX, NY, NZ, BLOCK,
        max_refinement_depth=2,
        sensor_coords=sensors,
        refine_radius=2.0 * BLOCK,
    )
    assert mesh.n_cells > N_BASE, "la malla no se refinó"

    meta: dict = {}
    est_density, rel_score, misfit = solve_inversion_treemesh(
        mesh=mesh,
        g_observed=g_obs,
        sensor_coords=sensors,
        forward_model=_make_forward(),
        lambda_mag=3.0,
        alpha_spatial=1.0,
        depth_beta=2.0,
        base_density=BASE_DENSITY,
        density_min=2.6,
        density_max=4.2,
        solver_meta=meta,
    )

    # (a) Sin NaN/Inf y dentro de bounds.
    assert est_density.shape == (mesh.n_cells,)
    assert np.isfinite(est_density).all(), "densidad estimada contiene NaN/Inf"
    assert est_density.min() >= 2.6 - 1e-9 and est_density.max() <= 4.2 + 1e-9, "fuera de bounds"

    # (b) Convergencia razonable: el ajuste reduce sustancialmente el misfit frente
    # al modelo nulo (m=0 → misfit=100%). NOTA: con λ=3.0 fijo sobre datos SIN ruido
    # el χ² reducido es alto por construcción (la regularización impide el ajuste
    # exacto); el χ²≈1 sólo aplica con ruido calibrado. Por eso aquí sólo exigimos
    # que χ² sea finito y que el misfit caiga bien por debajo del 100% nulo.
    assert np.isfinite(misfit), "misfit no finito"
    assert misfit < 60.0, f"misfit demasiado alto (no fitea): {misfit:.1f}%"
    assert np.isfinite(meta["chi2_final"]), "chi2 no finito"
    assert np.isfinite(meta["acond"]) and meta["acond"] < 1e12, (
        f"cond(A) mal acondicionado: {meta['acond']:.2e}"
    )

    # (c) Recupera contraste positivo (densidad sobre la base en alguna celda).
    contrast_est = est_density - BASE_DENSITY
    assert contrast_est.max() > 0.05, (
        f"no se recuperó contraste positivo (max={contrast_est.max():.3f} t/m³)"
    )

    print(
        f"[3] INVERSIÓN OK | n_cells={mesh.n_cells} | misfit={misfit:.2f}% | "
        f"chi2={meta['chi2_final']:.3f} | cond(A)~{meta['acond']:.2e} | "
        f"max contraste recuperado={contrast_est.max():.3f} t/m³"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runner como script
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  SPRINT 3B — Laplaciano Octree + solver TreeMesh: validación")
    print("=" * 70)

    failed = 0
    for name, fn in (
        ("test_laplacian_octree_structure",       test_laplacian_octree_structure),
        ("test_laplacian_regular_grid_recovery",  test_laplacian_regular_grid_recovery),
        ("test_inversion_with_treemesh",          test_inversion_with_treemesh),
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
        print("RESULTADO: 3/3 PASS — Sprint 3B (Laplaciano Octree + solver) validado.")
        sys.exit(0)
    else:
        print(f"RESULTADO: {failed} test(s) fallaron.")
        sys.exit(1)
