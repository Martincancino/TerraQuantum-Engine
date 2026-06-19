"""
FASE 17 — Laplacian Non-Uniform Validation (Tarea 3): Weight Matrix Tests
==========================================================================

Verifica las propiedades matemáticas de la matriz de pesos L generada por
GravimetryInversion._build_laplacian() para mallas no-uniformes.

  1. test_laplacian_matrix_properties
       - Simétrico (L = L.T)
       - Espacio nulo = [1,1,...,1] → suma por filas ≈ 0
       - Convención: diagonal NEGATIVA, off-diagonales NO-NEGATIVAS
         (L = W - D, donde W es la matriz de pesos, D la diagonal de grado)

  2. test_weight_edge_formula
       - Para cada arista (i, j) adyacente: L[i,j] = 2 / (h_i + h_j)
       - Para hx uniforme h0: L[i,j] = 1/h0 (exacto)
       - Conservación: suma por fila = 0 (⟺ espacio nulo = ones)

  3. test_laplacian_anisotropic
       - Grid con hx ≠ hy: pesos en X deben diferir de pesos en Y
       - Verificar que la anisotropía se refleja correctamente

Uso:
    python -m pytest tests/test_laplacian_weights.py -v
"""

from __future__ import annotations

import os
import sys

import numpy as np
import scipy.sparse as sp

try:
    from exploration.gravimetry import GravimetryInversion
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryInversion


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_inv(nx, ny, nz, block=10.0) -> GravimetryInversion:
    return GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=block)


def _offdiag_weights(L_arr: np.ndarray) -> np.ndarray:
    """Extrae los valores únicos de off-diagonal (positivos) de L."""
    n = L_arr.shape[0]
    mask = ~np.eye(n, dtype=bool)
    return L_arr[mask]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Propiedades de la matriz
# ─────────────────────────────────────────────────────────────────────────────
def test_laplacian_matrix_properties():
    """
    Simetría, espacio nulo y convención de signos para malla 4×4×4 no-uniforme.

    Convención TerraQuantum: L = W - D
      - off-diagonal L[i,j] = w_ij ≥ 0  (peso de la arista)
      - diagonal     L[i,i] = -∑_j w_ij  (suma negativa)
    Esta es la convención del Laplaciano NEGATIVO; ||Lm||² = ||L_std m||² al
    ser cuadrada (L² = L_std²), así que la regularización es equivalente.
    """
    NX, NY, NZ, H = 4, 4, 4, 10.0
    inv = _make_inv(NX, NY, NZ, H)

    # Caso 1: malla uniforme (hx=None)
    L_uni = inv._build_laplacian()
    Ld_uni = L_uni.toarray()

    # Simetría
    asym = float(np.max(np.abs(Ld_uni - Ld_uni.T)))
    assert asym < 1e-12, f"L uniforme no simétrico: max|L-Lᵀ|={asym:.2e}"

    # Espacio nulo = [1,...,1]: L @ ones ≈ 0
    ones = np.ones(NX * NY * NZ)
    null_res = float(np.max(np.abs(Ld_uni @ ones)))
    assert null_res < 1e-9, f"L @ ones ≠ 0: max|L·1|={null_res:.2e}"

    # Diagonal NEGATIVA, off-diagonal NO-NEGATIVA (convención TQ)
    diag = np.diag(Ld_uni)
    assert np.all(diag < 0), "Hay entradas diagonales no-negativas (violación de convención)"
    off = Ld_uni.copy()
    np.fill_diagonal(off, 0.0)
    assert float(np.min(off)) >= -1e-15, "Hay off-diagonales negativas en L"

    # Caso 2: malla no-uniforme hx=[10,10,5,5] (2:1 ratio)
    hx_nu = np.array([10.0, 10.0, 5.0, 5.0])
    hy_nu = np.full(NY, 10.0)
    hz_nu = np.full(NZ, 10.0)
    L_nu = inv._build_laplacian(hx=hx_nu, hy=hy_nu, hz=hz_nu)
    Ld_nu = L_nu.toarray()

    # Las mismas propiedades deben valer para malla no-uniforme
    asym_nu = float(np.max(np.abs(Ld_nu - Ld_nu.T)))
    assert asym_nu < 1e-12, f"L no-uniforme no simétrico: max|L-Lᵀ|={asym_nu:.2e}"

    null_nu = float(np.max(np.abs(Ld_nu @ ones)))
    assert null_nu < 1e-9, f"L_nu @ ones ≠ 0: max|L·1|={null_nu:.2e}"

    diag_nu = np.diag(Ld_nu)
    assert np.all(diag_nu < 0), "L_nu: hay diagonales no-negativas"
    off_nu = Ld_nu.copy()
    np.fill_diagonal(off_nu, 0.0)
    assert float(np.min(off_nu)) >= -1e-15, "L_nu: off-diagonal negativa detectada"

    print(
        f"[WEIGHTS 1] matrix_properties PASS | "
        f"uniforme: max|L-Lt|={asym:.1e}, max|L*1|={null_res:.1e} | "
        f"no-uniforme: max|L-Lt|={asym_nu:.1e}, max|L*1|={null_nu:.1e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Formula w_ij = 2/(h_i + h_j) por arista
# ─────────────────────────────────────────────────────────────────────────────
def test_weight_edge_formula():
    """
    Verifica la fórmula exacta w_ij = 2/(h_i + h_j) para cada arista.

    Para malla 3×1×1 con hx=[a, b, c]:
      - Arista (0→1): w = 2/(a+b)
      - Arista (1→2): w = 2/(b+c)
    Los valores del off-diagonal de L deben coincidir con estas fórmulas.
    """
    # Grid 3×1×1 para control preciso de aristas X
    inv = _make_inv(nx=3, ny=1, nz=1, block=10.0)
    a, b, c = 8.0, 12.0, 6.0
    hx = np.array([a, b, c])
    hy = np.array([10.0])
    hz = np.array([10.0])

    L = inv._build_laplacian(hx=hx, hy=hy, hz=hz)
    Ld = L.toarray()  # shape (3,3) para nx=ny=nz=1 → 3 celdas

    # En orden Fortran con ny=nz=1, índice = ix + 0 + 0 = ix
    # Arista (0,1): L[0,1] = L[1,0] = 2/(a+b)
    # Arista (1,2): L[1,2] = L[2,1] = 2/(b+c)
    w01_expected = 2.0 / (a + b)
    w12_expected = 2.0 / (b + c)

    w01_actual = float(Ld[0, 1])
    w12_actual = float(Ld[1, 2])

    assert abs(w01_actual - w01_expected) < 1e-14, (
        f"Arista (0,1): esperado {w01_expected:.6f}, obtenido {w01_actual:.6f}"
    )
    assert abs(w12_actual - w12_expected) < 1e-14, (
        f"Arista (1,2): esperado {w12_expected:.6f}, obtenido {w12_actual:.6f}"
    )

    # Simetría de aristas
    assert abs(float(Ld[1, 0]) - w01_expected) < 1e-14, "Arista (1,0) no simétrica"
    assert abs(float(Ld[2, 1]) - w12_expected) < 1e-14, "Arista (2,1) no simétrica"

    # Conservación: suma de cada fila = 0
    row_sums = Ld.sum(axis=1)
    assert float(np.max(np.abs(row_sums))) < 1e-12, (
        f"Suma de filas ≠ 0: {row_sums}"
    )

    # Caso especial uniforme: w_ij = 1/h0
    h0 = 10.0
    inv_u = _make_inv(nx=4, ny=1, nz=1, block=h0)
    hx_u = np.full(4, h0)
    L_u = inv_u._build_laplacian(hx=hx_u, hy=np.array([h0]), hz=np.array([h0]))
    Lu = L_u.toarray()
    # Todas las aristas deben tener w = 1/h0
    off_vals = Lu[~np.eye(4, dtype=bool)]
    positive_offs = off_vals[off_vals > 1e-15]
    assert np.allclose(positive_offs, 1.0 / h0, atol=1e-14), (
        f"Aristas uniformes ≠ 1/h0: {positive_offs}"
    )

    print(
        f"[WEIGHTS 2] edge_formula PASS | "
        f"w(0,1)={w01_actual:.6f} (esperado {w01_expected:.6f}) | "
        f"w(1,2)={w12_actual:.6f} (esperado {w12_expected:.6f})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Anisotropía: hx ≠ hy → pesos X ≠ pesos Y
# ─────────────────────────────────────────────────────────────────────────────
def test_laplacian_anisotropic():
    """
    Con hx=[10,10,5,5] en X e hy=[10]*4 en Y, los pesos en X deben diferir
    de los pesos en Y. Verifica que la anisotropía se refleja en L.
    """
    NX, NY, NZ = 4, 4, 1
    inv = _make_inv(NX, NY, NZ, block=10.0)

    hx = np.array([10.0, 10.0, 5.0, 5.0])
    hy = np.full(NY, 10.0)
    hz = np.full(NZ, 10.0)

    L = inv._build_laplacian(hx=hx, hy=hy, hz=hz)
    Ld = L.toarray()
    n = NX * NY * NZ  # 16

    # Reconstruir manualmente los pesos X en dirección i→i+1 para iy=0, iz=0
    # Índice en orden F: idx(ix, iy, iz) = ix + NX*iy + NX*NY*iz
    def idx(ix, iy, iz):
        return ix + NX * iy + NX * NY * iz

    # Aristas X en iy=0, iz=0
    x_weights_actual = np.array([Ld[idx(ix, 0, 0), idx(ix + 1, 0, 0)] for ix in range(NX - 1)])
    x_weights_expected = np.array([2.0 / (hx[ix] + hx[ix + 1]) for ix in range(NX - 1)])

    assert np.allclose(x_weights_actual, x_weights_expected, atol=1e-14), (
        f"Pesos X no coinciden con fórmula:\n"
        f"  actual:   {x_weights_actual}\n"
        f"  esperado: {x_weights_expected}"
    )

    # Aristas Y en ix=0, iz=0
    y_weights_actual = np.array([Ld[idx(0, iy, 0), idx(0, iy + 1, 0)] for iy in range(NY - 1)])
    y_weight_expected = 2.0 / (hy[0] + hy[1])  # uniforme en Y

    assert np.allclose(y_weights_actual, y_weight_expected, atol=1e-14), (
        f"Pesos Y no uniformes cuando hy es constante: {y_weights_actual}"
    )

    # Anisotropía: los pesos en X varían (no todos iguales a y_weight_expected)
    assert not np.allclose(x_weights_actual, y_weight_expected, atol=1e-6), (
        "X e Y tienen los mismos pesos, pero hx ≠ hy — falta anisotropía"
    )

    # Pesos X en la región refinada (ix=2,3: h=5) deben ser mayores que en (ix=0,1: h=10)
    # w(1→2): 2/(10+5) = 0.1333 > w(0→1): 2/(10+10) = 0.1
    w_coarse = float(x_weights_expected[0])   # 2/(10+10) = 0.1
    w_boundary = float(x_weights_expected[1]) # 2/(10+5)  = 0.133...
    w_fine = float(x_weights_expected[2])     # 2/(5+5)   = 0.2
    assert w_fine > w_boundary > w_coarse, (
        f"Orden de pesos incorrecto: {w_coarse:.4f} < {w_boundary:.4f} < {w_fine:.4f}"
    )

    print(
        f"[WEIGHTS 3] anisotropic PASS | "
        f"X weights={x_weights_actual.round(4)} | "
        f"Y weight (uniforme)={y_weight_expected:.4f} | "
        f"w_coarse={w_coarse:.4f} < w_bnd={w_boundary:.4f} < w_fine={w_fine:.4f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runner como script
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  FASE 17 — Tarea 3: Weight Matrix Validation")
    print("=" * 70)

    failed = 0
    for name, fn in (
        ("test_laplacian_matrix_properties", test_laplacian_matrix_properties),
        ("test_weight_edge_formula",         test_weight_edge_formula),
        ("test_laplacian_anisotropic",        test_laplacian_anisotropic),
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
        print("RESULTADO: 3/3 PASS — Propiedades de la matriz de pesos validadas.")
        sys.exit(0)
    else:
        print(f"RESULTADO: {failed} test(s) fallaron.")
        sys.exit(1)
