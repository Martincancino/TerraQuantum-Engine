"""
Sprint 5A — Direct Sparse Solver (SuperLU on Normal Equations)
==============================================================
Validates that solve_sparse_normal_equations() solves the SAME least-squares
problem as LSQR, agreeing to rtol=1e-8 on the solution vector.

Why rtol=1e-8 (not 1e-10): forming the normal equations AᵀA squares the
condition number, so the achievable precision is ~cond(AᵀA)·eps. The iterative
refinement step recovers the digits lost in forming AᵀA; 1e-8 is the honest,
reproducible gate. See the docstring of solve_sparse_normal_equations().

The structure of each test problem mirrors the production inversion system:
a sparse (truncated) "kernel" block stacked with a regularization block that
guarantees full column rank → AᵀA is SPD → SuperLU factorizes it stably.

Run:
    cd terraquantum-backend
    python tests/test_sparse_solver.py
    # or
    python -m pytest tests/test_sparse_solver.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

# ── Import resolution: supports execution from repo root or tests/ dir ────────
try:
    from exploration.gravimetry import solve_sparse_normal_equations
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import solve_sparse_normal_equations


def _make_regularized_system(n_cells, n_sensors, lam, nnz_per_col, seed):
    """
    Build a tall sparse least-squares system that mimics the inversion structure:

        A = [        G_sparse        ]      (n_sensors × n_cells, truncated kernel)
            [ lam · I_regularization ]      (n_cells   × n_cells, full column rank)

    The regularization block guarantees rank(A) = n_cells, so AᵀA is SPD.
    Returns (A_csr, b).
    """
    rng = np.random.default_rng(seed)

    # Sparse "kernel": each sensor sees ~nnz_per_col cells (local truncated support).
    rows, cols, vals = [], [], []
    for s in range(n_sensors):
        touched = rng.choice(n_cells, size=min(nnz_per_col, n_cells), replace=False)
        rows.extend([s] * len(touched))
        cols.extend(touched.tolist())
        vals.extend(rng.standard_normal(len(touched)).tolist())
    G = sp.csr_matrix(
        (vals, (rows, cols)), shape=(n_sensors, n_cells), dtype=np.float64
    )

    reg = lam * sp.eye(n_cells, format="csr", dtype=np.float64)
    A = sp.vstack([G, reg]).tocsr()

    # RHS from a known model + noise → a genuine (inconsistent) least-squares problem.
    x_true = rng.standard_normal(n_cells)
    b_top = G @ x_true + 0.01 * rng.standard_normal(n_sensors)
    b = np.concatenate([b_top, np.zeros(n_cells)])
    return A, b


class TestSparseDirectSolver(unittest.TestCase):
    RTOL = 1e-8

    def _assert_matches_lsqr(self, A, b, msg=""):
        x_direct, info = solve_sparse_normal_equations(A, b)
        # LSQR with tight tolerances → reference least-squares solution.
        res = lsqr(A, b, damp=0.0, atol=1e-13, btol=1e-13, iter_lim=20000, show=False)
        x_lsqr = res[0]

        # Solution-vector agreement (the accuracy gate chosen for Sprint 5A).
        np.testing.assert_allclose(
            x_direct, x_lsqr, rtol=self.RTOL, atol=1e-10,
            err_msg=f"{msg}: direct vs LSQR solution mismatch",
        )

        # The direct solver's residual must not be worse than LSQR's (it solves the
        # exact normal equations, so it should be at least as good).
        r_direct = info["residual_norm"]
        r_lsqr = float(np.linalg.norm(A @ x_lsqr - b))
        self.assertLessEqual(
            r_direct, r_lsqr * (1.0 + 1e-6),
            f"{msg}: direct residual {r_direct:.3e} worse than LSQR {r_lsqr:.3e}",
        )
        return x_direct, info

    def test_small_well_conditioned(self):
        """Small system, strong regularization → AᵀA well conditioned."""
        A, b = _make_regularized_system(
            n_cells=200, n_sensors=120, lam=0.5, nnz_per_col=15, seed=1
        )
        self._assert_matches_lsqr(A, b, "small")

    def test_medium_weaker_regularization(self):
        """Larger system, weaker reg → cond(AᵀA) higher but still within 1e-8."""
        A, b = _make_regularized_system(
            n_cells=1500, n_sensors=900, lam=0.05, nnz_per_col=20, seed=7
        )
        x, info = self._assert_matches_lsqr(A, b, "medium")
        self.assertEqual(info["method"], "superlu-normal-eq")
        self.assertGreater(info["fill_nnz"], 0)

    def test_refinement_improves_residual(self):
        """Iterative refinement should not worsen — and typically improves — accuracy."""
        A, b = _make_regularized_system(
            n_cells=800, n_sensors=500, lam=0.02, nnz_per_col=18, seed=3
        )
        _, info_ref = solve_sparse_normal_equations(A, b, refine=True)
        _, info_raw = solve_sparse_normal_equations(A, b, refine=False)
        self.assertLessEqual(
            info_ref["residual_norm"], info_raw["residual_norm"] * (1.0 + 1e-9),
            "refinement worsened the residual",
        )

    def test_rejects_underdetermined(self):
        """Wide matrix (m<n) → no SPD normal equations → must raise."""
        A = sp.random(50, 200, density=0.1, format="csr", random_state=0)
        b = np.zeros(50)
        with self.assertRaises(ValueError):
            solve_sparse_normal_equations(A, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
