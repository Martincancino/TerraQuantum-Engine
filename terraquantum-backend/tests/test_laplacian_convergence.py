"""
FASE 17 — Laplacian Non-Uniform Validation (Tarea 2): Convergence Test
=======================================================================

Verifica que el Laplaciano no-uniforme converge al uniforme cuando los
tamaños de celda convergen a una constante h0:

  1. Caso exacto: hx = [h0]*N → L_nonuniform = (1/h0) * L_uniform (matemáticamente exacto)
  2. Convergencia de L: hx con pequeña perturbación → rel_err < O(eps)
  3. Inversion equivalencia: solución escalada con L_nonuniform = solución con L_uniform
  4. Convergencia de solución: grid ligeramente no-uniforme da <5% error vs uniforme

Formula validada: w_ij = 2 / (h_i + h_j)
  - Con h_i = h_j = h0: w_ij = 1/h0 → L_nonuniform = (1/h0) * L_uniform
  - L_uniform usa pesos w_ij = 1 (valor escalar sin dimensión física)

Uso:
    python -m pytest tests/test_laplacian_convergence.py -v -s
"""

from __future__ import annotations

import os
import sys

import numpy as np
import scipy.sparse.linalg as spla

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid


# ── Configuración pequeña y rápida ────────────────────────────────────────────
NX, NY, NZ = 6, 6, 6
H0 = 10.0
CUTOFF = 3.0 * H0 * max(NX, NY, NZ)


def _mini_solve(G, g_obs, L, lam: float) -> np.ndarray:
    """
    Simplified LSQR: argmin ||Gm - g_obs||² + lam² ||Lm||²

    Construye la pila [G; lam*L] y llama a lsqr directamente.
    Retorna el vector de densidades m.
    """
    import scipy.sparse as sp
    n = L.shape[0]
    A = sp.vstack([G, lam * L]).tocsr()
    b = np.concatenate([np.asarray(g_obs).ravel(), np.zeros(n)])
    result = spla.lsqr(A, b, atol=1e-8, btol=1e-8, iter_lim=500)
    return result[0]


def test_nonuniform_laplacian_converges_to_uniform():
    """
    Convergence suite (4 partes):

    Parte 1 — Exactitud matemática: hx=[h0]*N → L_nu = (1/h0)*L_u
    Parte 2 — Convergencia de L: perturbación 2% → rel_err < 10% en L
    Parte 3 — Equivalencia de inversión con λ escalado
    Parte 4 — Solución de inversión difiere <5% con perturbación 2%
    """
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=H0)

    # ── Laplacianos ────────────────────────────────────────────────────────────
    # Uniforme (pesos = 1 en cada arista)
    L_uniform = inv._build_laplacian()

    # Constante hx = [H0]*N → pesos = 2/(H0+H0) = 1/H0
    hx_c = np.full(NX, H0)
    hy_c = np.full(NY, H0)
    hz_c = np.full(NZ, H0)
    L_const = inv._build_laplacian(hx=hx_c, hy=hy_c, hz=hz_c)

    # Parte 1: L_const = (1/H0) * L_uniform  (exacto a tolerancia numérica)
    L_u = L_uniform.toarray()
    L_c = L_const.toarray()
    max_err_exact = float(np.max(np.abs(L_c - L_u / H0)))
    assert max_err_exact < 1e-10, (
        f"Parte 1 FAIL: L_const != (1/H0)*L_uniform | "
        f"max_abs_err={max_err_exact:.2e}"
    )
    print(f"[CONVERGENCE] Parte 1 PASS: max_err_exact={max_err_exact:.2e}")

    # Parte 2: Perturbación eps=2% → rel_err < 10% en L
    eps = 0.02
    # Patrón [1-eps, 1+eps, 1-eps, 1+eps, ...] aplicado en X
    # En aristas X: half1-half1 → 2/(H0*(2-2eps))=1/(H0*(1-eps))  (2% over)
    #               half2-half2 → 2/(H0*(2+2eps))=1/(H0*(1+eps))  (2% under)
    #               boundary   → 2/(H0*(2))=1/H0                  (exact)
    rng = np.array(([1.0 - eps, 1.0 + eps] * 4)[:NX])
    hx_p = H0 * rng
    L_pert = inv._build_laplacian(hx=hx_p, hy=hy_c, hz=hz_c)

    L_p = L_pert.toarray()
    nonzero_mask = np.abs(L_c) > 1e-12
    rel_errs = np.abs(L_p[nonzero_mask] - L_c[nonzero_mask]) / np.abs(L_c[nonzero_mask])
    max_rel_err = float(np.max(rel_errs))
    # Con eps=2%, las aristas X-perturbed varían ~2% → max rel_err < 10% (holgado)
    assert max_rel_err < 0.10, (
        f"Parte 2 FAIL: max rel_err={max_rel_err:.3f} > 10% para perturbación 2%"
    )
    print(f"[CONVERGENCE] Parte 2 PASS: max_rel_err={max_rel_err:.3f} (<10%)")

    # ── Setup forward para partes 3 y 4 ──────────────────────────────────────
    _, _, _, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, H0)
    sensors = build_sensor_grid(NX, NZ, H0, sensor_elevation=0.0)
    fwd = GravimetryForward(dx=H0, dy=H0, dz=H0, cutoff_radius=CUTOFF)
    G = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)

    # Modelo verdadero: bloque denso en el centro
    n_vox = NX * NY * NZ
    cx = NX * H0 / 2.0
    cy = NY * H0 / 2.0
    cz = NZ * H0 / 2.0
    r = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    m_true = np.where(r < H0 * 1.5, 0.5, 0.0)
    g_obs = np.asarray(G @ m_true).ravel()
    assert np.isfinite(g_obs).all() and np.linalg.norm(g_obs) > 0

    # Parte 3: Equivalencia exacta con λ escalado
    # L_uniform tiene pesos=1; L_const tiene pesos=1/H0
    # Para obtener el mismo funcional: λ_u² ||L_u m||² = λ_c² ||L_c m||²
    #   → λ_c² (1/H0)² = λ_u²  → λ_c = λ_u * H0
    LAM_U = 0.1
    LAM_C = LAM_U * H0  # = 1.0 para H0=10

    rho_u = _mini_solve(G, g_obs, L_uniform, LAM_U)
    rho_c = _mini_solve(G, g_obs, L_const, LAM_C)

    err_exact_inv = float(
        np.linalg.norm(rho_u - rho_c) / max(np.linalg.norm(rho_u), 1e-10)
    )
    assert err_exact_inv < 1e-5, (
        f"Parte 3 FAIL: soluciones escaladas difieren: {err_exact_inv:.2e} "
        f"(esperado < 1e-5)"
    )
    print(f"[CONVERGENCE] Parte 3 PASS: err_exact_inv={err_exact_inv:.2e}")

    # Parte 4: Inversión con perturbación 2% da < 5% error vs constante
    rho_p = _mini_solve(G, g_obs, L_pert, LAM_C)
    err_conv_inv = float(
        np.linalg.norm(rho_c - rho_p) / max(np.linalg.norm(rho_c), 1e-10)
    )
    assert err_conv_inv < 0.05, (
        f"Parte 4 FAIL: error de convergencia {err_conv_inv:.3f} > 5% "
        f"para perturbación 2% en hx"
    )
    print(
        f"[CONVERGENCE] Parte 4 PASS: err_conv_inv={err_conv_inv:.4f} (<5%)\n"
        f"[CONVERGENCE] SUITE PASS — Laplaciano no-uniforme converge al uniforme."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runner como script
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  FASE 17 — Tarea 2: Convergence Test (non-uniform → uniform)")
    print("=" * 70)

    try:
        test_nonuniform_laplacian_converges_to_uniform()
        print("\nRESULTADO: 1/1 PASS — Convergencia validada.")
        sys.exit(0)
    except AssertionError as exc:
        print(f"\n[FAIL] test_nonuniform_laplacian_converges_to_uniform: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
