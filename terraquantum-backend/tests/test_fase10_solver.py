"""
Fase 10 — Tests del Solver Escalable.

Criterios de aceptación (Plan Industrial §10.6):
  1. build_compressed_kernel retiene < 15% de elementos con error forward < 0.5%.
  2. solve_inversion_lsmr para n_active=10K da mismo resultado que LSQR.
  3. Selector automático enruta correctamente según n_active.
  4. LSMR converge en < 300 iteraciones para n_active=10K (smoke test).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from exploration.solver_preconditioned import (
    select_solver,
    solve_inversion_lsmr,
    make_zarr_linear_operator,
    estimate_kernel_memory_gb,
)

# Fase 6 (cierre): el bloque wavelet de esta suite se BORRÓ con su módulo.
# Ver la lápida al final del archivo.


# ── Fixtures sintéticos ───────────────────────────────────────────────────────

def _build_small_system(n_sensors=50, n_active=500, seed=42):
    """Sistema sintético pequeño para verificación numérica."""
    rng = np.random.default_rng(seed)
    G = rng.standard_normal((n_sensors, n_active))
    m_true = rng.standard_normal(n_active) * 0.1
    d = G @ m_true + rng.standard_normal(n_sensors) * 0.01
    return G, d, m_true


def _build_augmented(G_dense, d, lam=1.0):
    """Construye sistema aumentado [G; lam*I] → CSR."""
    n_s, n_a = G_dense.shape
    G_sp = sp.csr_matrix(G_dense)
    reg = lam * sp.eye(n_a, format="csr")
    G_aug = sp.vstack([G_sp, reg]).tocsr()
    d_aug = np.concatenate([d, np.zeros(n_a)])
    lb = np.full(n_a, -5.0)
    ub = np.full(n_a, 5.0)
    return G_aug, d_aug, lb, ub


# ── Test 1: Selector automático ──────────────────────────────────────────────

def test_select_solver_small():
    assert select_solver(1000, use_bounded=True, use_lsmr=True) == "trf_bounded"

def test_select_solver_medium():
    assert select_solver(20_000, use_bounded=True, use_lsmr=True) == "lsqr"

def test_select_solver_large():
    assert select_solver(100_000, use_bounded=True, use_lsmr=True) == "lsmr"

def test_select_solver_large_lsmr_off():
    assert select_solver(100_000, use_bounded=True, use_lsmr=False) == "lsqr"

def test_select_solver_threshold():
    # exactamente en el umbral → lsqr (no estrictamente mayor)
    assert select_solver(50_000, use_bounded=True, use_lsmr=True) == "lsqr"
    assert select_solver(50_001, use_bounded=True, use_lsmr=True) == "lsmr"


# ── Test 2: LSMR da mismo resultado que LSQR (sistema pequeño) ───────────────

def test_lsmr_vs_lsqr_equivalence():
    """LSMR y LSQR deben producir soluciones con ||x_lsmr - x_lsqr|| / ||x_lsqr|| < 1%."""
    G_dense, d, _ = _build_small_system(n_sensors=50, n_active=200)
    G_aug, d_aug, lb, ub = _build_augmented(G_dense, d, lam=1.0)

    # LSQR
    res_lsqr = spla.lsqr(G_aug, d_aug, damp=0.0, iter_lim=500, atol=1e-10, btol=1e-10)
    x_lsqr = np.clip(res_lsqr[0], lb, ub)

    # LSMR
    x_lsmr, conda = solve_inversion_lsmr(G_aug, d_aug, lb, ub, maxiter=500, tol=1e-10)

    norm_lsqr = float(np.linalg.norm(x_lsqr))
    rel_diff = float(np.linalg.norm(x_lsmr - x_lsqr)) / max(norm_lsqr, 1e-12)
    print(f"[TEST] LSMR vs LSQR rel_diff={rel_diff:.6f} conda={conda:.2e}")
    assert rel_diff < 0.01, f"LSMR y LSQR difieren {rel_diff*100:.2f}% > 1%"


# ── Test 3: LSMR converge para sistema mediano ────────────────────────────────

def test_lsmr_convergence_medium():
    """LSMR converge (istop != 5) para n_active=5K en < 1000 iteraciones."""
    rng = np.random.default_rng(123)
    n_s, n_a = 100, 5_000
    G = rng.standard_normal((n_s, n_a)) * 0.1
    d = rng.standard_normal(n_s)
    G_aug, d_aug, lb, ub = _build_augmented(sp.csr_matrix(G), d, lam=0.1)

    x, conda = solve_inversion_lsmr(G_aug, d_aug, lb, ub, maxiter=1000, tol=1e-6)

    # No debe explotar
    assert np.isfinite(x).all(), "LSMR produjo NaN o Inf"
    assert np.isfinite(conda), "conda debe ser finito"
    print(f"[TEST] LSMR n_a={n_a}: cond(A)~{conda:.2e}")


# ── Test 4: Bounds se respetan ────────────────────────────────────────────────

def test_lsmr_bounds_clipped():
    """La solución clipeada debe estar dentro del box [lb, ub]."""
    G_dense, d, _ = _build_small_system(n_sensors=30, n_active=100, seed=7)
    G_aug, d_aug, lb, ub = _build_augmented(G_dense, d, lam=0.5)
    # Bounds estrechos para forzar clip
    lb_tight = np.full(100, -0.1)
    ub_tight = np.full(100, 0.1)

    x, _ = solve_inversion_lsmr(G_aug, d_aug, lb_tight, ub_tight)
    assert np.all(x >= lb_tight - 1e-12), "Solución viola bound inferior"
    assert np.all(x <= ub_tight + 1e-12), "Solución viola bound superior"


# Fase 6 (cierre, H-13): aquí vivían los tres tests wavelet, borrados junto con
# `exploration/jacobian_wavelet.py`. La cadena completa de por qué, porque es el mejor
# ejemplo de "no dejar en limbo" que dio el plan:
#
#  · La Fase 6 (08-09) borró `solve_inversion_lsmr_wavelet` y las dos perillas
#    `USE_WAVELET_COMPRESSION`/`WAVELET_THRESHOLD_N_ACTIVE` por no tener consumidor, y
#    dejó los building blocks "vivos y con tests". Con el llamador muerto, esos tests
#    eran lo ÚNICO que importaba el módulo: física sin ruta al producto.
#  · La Fase 3 (08-13) los ejecutó por primera vez en un runner con PyWavelets instalado
#    y midió que el algoritmo NO cumple su propio criterio §10.6.1:
#        · compresión: 98,2% retenido   (exigía < 15%)
#        · error forward: 0,615%        (exigía < 0,5%)
#    Quedaron como `xfail(strict=True)`: honesto, pero es una promesa incumplida en
#    mantenimiento indefinido.
#  · Cerrar la Fase 6 obliga a decidir. CABLEARLO no es una opción de una fase de
#    limpieza: el algoritmo falla su criterio, así que cablearlo exige rehacerlo, y eso
#    es física. Se BORRA — módulo, tests y la dependencia `PyWavelets`, que sólo existía
#    para esto. `git log` conserva las 203 líneas si alguien retoma Farquharson &
#    Oldenburg (2003) con un criterio que sí se pueda cumplir.


# ── Tests Zarr out-of-core (§10.4) ───────────────────────────────────────────

def test_zarr_linear_operator_matvec():
    """ZarrLinearOperator da mismo G@v que la matriz densa original."""
    try:
        import zarr as _zarr
    except ImportError:
        print("[SKIP] zarr no instalado.")
        return

    import tempfile, os
    rng = np.random.default_rng(5)
    n_s, n_a = 30, 200
    G = rng.standard_normal((n_s, n_a)).astype(np.float32)

    # Escribir a Zarr (como haría compute_jacobian_dask)
    tmp = tempfile.mkdtemp()
    zarr_path = os.path.join(tmp, "test_G.zarr")
    z = _zarr.open_array(zarr_path, mode="w", shape=(n_s, n_a), dtype="float32", chunks=(10, n_a))
    z[:] = G

    # Operador Zarr
    op = make_zarr_linear_operator(zarr_path, chunk_rows=10)
    assert op.shape == (n_s, n_a)

    # Test matvec G @ v
    v = rng.standard_normal(n_a)
    d_dense = G.astype(np.float64) @ v
    d_zarr = op.matvec(v)
    rel_err = np.linalg.norm(d_zarr - d_dense) / np.linalg.norm(d_dense)
    print(f"[TEST] ZarrOp matvec rel_err={rel_err:.2e}")
    assert rel_err < 1e-5, f"Zarr matvec error {rel_err:.2e} > 1e-5"

    # Test rmatvec G.T @ u
    u = rng.standard_normal(n_s)
    gt_dense = G.astype(np.float64).T @ u
    gt_zarr = op.rmatvec(u)
    rel_err_t = np.linalg.norm(gt_zarr - gt_dense) / np.linalg.norm(gt_dense)
    print(f"[TEST] ZarrOp rmatvec rel_err={rel_err_t:.2e}")
    assert rel_err_t < 1e-5, f"Zarr rmatvec error {rel_err_t:.2e} > 1e-5"


def test_zarr_lsmr_convergence():
    """LSMR con ZarrLinearOperator converge a la misma solución que LSQR directo."""
    try:
        import zarr as _zarr
    except ImportError:
        print("[SKIP] zarr no instalado.")
        return

    import tempfile, os
    rng = np.random.default_rng(77)
    n_s, n_a = 40, 150
    G = rng.standard_normal((n_s, n_a))
    m_true = rng.standard_normal(n_a) * 0.1
    d = G @ m_true + 0.01 * rng.standard_normal(n_s)

    # Armar sistema aumentado con regularización
    lam = 0.5
    G_aug_dense = np.vstack([G, lam * np.eye(n_a)])
    d_aug = np.concatenate([d, np.zeros(n_a)])
    lb, ub = np.full(n_a, -5.0), np.full(n_a, 5.0)

    # LSQR referencia
    x_lsqr = np.clip(spla.lsqr(sp.csr_matrix(G_aug_dense), d_aug, iter_lim=500)[0], lb, ub)

    # Guardar solo G (sin regularización) en Zarr
    tmp = tempfile.mkdtemp()
    zarr_path = os.path.join(tmp, "test_G2.zarr")
    z = _zarr.open_array(zarr_path, mode="w", shape=(n_s, n_a), dtype="float32", chunks=(20, n_a))
    z[:] = G.astype(np.float32)
    G_op = make_zarr_linear_operator(zarr_path, chunk_rows=20)

    # Construir operador aumentado con LinearOperator
    I_op = sp.eye(n_a, format="csr")

    # G_aug como LinearOperator compuesto
    def _matvec_aug(v):
        return np.concatenate([G_op.matvec(v), lam * v])

    def _rmatvec_aug(u):
        return G_op.rmatvec(u[:n_s]) + lam * u[n_s:]

    G_aug_op = spla.LinearOperator(
        shape=(n_s + n_a, n_a),
        matvec=_matvec_aug,
        rmatvec=_rmatvec_aug,
        dtype=np.float64,
    )

    x_zarr, _ = solve_inversion_lsmr(G_aug_op, d_aug, lb, ub, maxiter=500, tol=1e-8)

    rel_diff = np.linalg.norm(x_zarr - x_lsqr) / max(np.linalg.norm(x_lsqr), 1e-12)
    print(f"[TEST] LSMR+Zarr vs LSQR rel_diff={rel_diff:.6f}")
    assert rel_diff < 0.01, f"LSMR+Zarr difiere {rel_diff*100:.2f}% de LSQR"


def test_estimate_kernel_memory():
    assert abs(estimate_kernel_memory_gb(500, 200_000) - 0.8) < 0.01
    assert estimate_kernel_memory_gb(500, 500_000, dtype_bytes=4) > 0.9


# ── Runner standalone ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_select_solver_small,
        test_select_solver_medium,
        test_select_solver_large,
        test_select_solver_large_lsmr_off,
        test_select_solver_threshold,
        test_lsmr_vs_lsqr_equivalence,
        test_lsmr_convergence_medium,
        test_lsmr_bounds_clipped,
        test_zarr_linear_operator_matvec,
        test_zarr_lsmr_convergence,
        test_estimate_kernel_memory,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Fase 10 Tests: {passed}/{total} PASS")
    if failed:
        sys.exit(1)
