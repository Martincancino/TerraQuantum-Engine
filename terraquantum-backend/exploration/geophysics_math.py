"""
FASE 9C-1 — Operadores diferenciales discretos para inversión conjunta.

Construye los operadores de PRIMERA DERIVADA (gradiente) por diferencias finitas
Dx, Dy, Dz como tres matrices dispersas CSR INDEPENDIENTES sobre una malla regular
3D. Son los ladrillos algebraicos del acoplamiento cross-gradient entre los modelos
de gravedad (densidad) y magnetometría (susceptibilidad) en la Fase 9C.

Backend-only / álgebra lineal pura: AQUÍ NO se calcula física, unidades ni geología.
Las matrices las consume el orquestador (9C-2) para armar el término cross-gradient
y se inyectan en los motores vía su hook `extra_reg_blocks`.

Convención de malla (idéntica a gravimetry/magnetometry `_build_laplacian`):
  • índice plano (orden Fortran):  idx = ix + nx*iy + nx*ny*iz
  • mismo recorrido de vecinos (idx_grid + add_edges) que el Laplaciano, pero para
    la primera derivada en lugar de la segunda.

Diseño de los operadores:
  • Cada Dx/Dy/Dz es CENTRADO EN CELDA y CO-LOCALIZADO (shape (nC, nC)), de modo que
    las tres derivadas direccionales se evalúan en las MISMAS celdas. Esto es lo que
    exige un término cross-gradient t = grad(m1) x grad(m2): el producto cruz solo
    está definido si las componentes comparten malla.
  • Celdas interiores: diferencia central  (m[i+1] - m[i-1]) / (x[i+1] - x[i-1]).
  • Celdas de borde: diferencia lateral de primer orden (forward/backward).
  • Eje con una sola celda (n=1): operador nulo en esa dirección.
  • Soporta espaciado uniforme (escalar o None→1.0) y no-uniforme (array 1D de anchos
    de celda, como el tensor mesh hx/hy/hz de los motores).
"""

from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import scipy.sparse as sp

Spacing = Union[float, np.ndarray, None]


def _cell_centers(n: int, h: Spacing) -> np.ndarray:
    """Coordenadas de los centros de celda a lo largo de un eje de tamaño ``n``.

    ``h`` puede ser None (espaciado unitario), un escalar (uniforme) o un array 1D
    de anchos de celda (no-uniforme, longitud ``n``)."""
    if h is None:
        widths = np.ones(n, dtype=np.float64)
    elif np.isscalar(h):
        widths = np.full(n, float(h), dtype=np.float64)
    else:
        widths = np.asarray(h, dtype=np.float64).ravel()
        if widths.shape[0] != n:
            raise ValueError(
                f"El array de anchos tiene {widths.shape[0]} elementos; se esperaban {n}."
            )
    if np.any(widths <= 0):
        raise ValueError("Los anchos de celda deben ser positivos.")
    # centro_i = suma de anchos previos + medio ancho propio
    return np.cumsum(widths) - 0.5 * widths


def _build_directional_derivative(
    idx_grid: np.ndarray,
    axis: int,
    centers: np.ndarray,
) -> sp.csr_matrix:
    """Operador de primera derivada centrado en celda a lo largo de un eje.

    Replica el recorrido de vecinos del Laplaciano (idx_grid en orden F + filas
    tipo add_edges), pero ensambla la primera derivada. Devuelve CSR (nC, nC)."""
    nx, ny, nz = idx_grid.shape
    nC = nx * ny * nz
    n_axis = idx_grid.shape[axis]

    if n_axis < 2:
        # Sin derivada definida en un eje de una sola celda.
        return sp.csr_matrix((nC, nC), dtype=np.float64)

    rows_parts: list = []
    cols_parts: list = []
    data_parts: list = []

    def _plane(i: int) -> np.ndarray:
        """Índices planos del 'plano' perpendicular al eje en la posición i."""
        return np.take(idx_grid, i, axis=axis).ravel(order="F")

    def add_edges(center_rows: np.ndarray, neighbor_cols: np.ndarray, weight: float) -> None:
        """Una contribución de fila tipo Laplaciano: fila=center, col=vecino, valor=peso."""
        rows_parts.append(center_rows)
        cols_parts.append(neighbor_cols)
        data_parts.append(np.full(center_rows.shape[0], weight, dtype=np.float64))

    for i in range(n_axis):
        center = _plane(i)
        if 0 < i < n_axis - 1:
            # Diferencia central: (m[i+1] - m[i-1]) / (x[i+1] - x[i-1])
            denom = float(centers[i + 1] - centers[i - 1])
            add_edges(center, _plane(i - 1), -1.0 / denom)
            add_edges(center, _plane(i + 1), +1.0 / denom)
        elif i == 0:
            # Borde inferior: diferencia forward (m[1] - m[0]) / (x[1] - x[0])
            denom = float(centers[1] - centers[0])
            add_edges(center, center, -1.0 / denom)
            add_edges(center, _plane(1), +1.0 / denom)
        else:
            # Borde superior: diferencia backward (m[n-1] - m[n-2]) / (x[n-1] - x[n-2])
            denom = float(centers[n_axis - 1] - centers[n_axis - 2])
            add_edges(center, _plane(n_axis - 2), -1.0 / denom)
            add_edges(center, center, +1.0 / denom)

    rows = np.concatenate(rows_parts)
    cols = np.concatenate(cols_parts)
    data = np.concatenate(data_parts)
    return sp.csr_matrix((data, (rows, cols)), shape=(nC, nC), dtype=np.float64)


def build_gradient_operators(
    nx: int,
    ny: int,
    nz: int,
    hx: Spacing = None,
    hy: Spacing = None,
    hz: Spacing = None,
) -> Tuple[sp.csr_matrix, sp.csr_matrix, sp.csr_matrix]:
    """Construye los tres operadores de primera derivada de la malla.

    Parameters
    ----------
    nx, ny, nz :
        Dimensiones de la malla. nC = nx*ny*nz.
    hx, hy, hz :
        Espaciado por eje: None (unitario), escalar (uniforme) o array 1D de anchos
        de celda (no-uniforme), igual que el tensor mesh de los motores.

    Returns
    -------
    (Dx, Dy, Dz) :
        Operadores CSR independientes, cada uno (nC, nC), co-localizados en los
        centros de celda, que aproximan ∂/∂x, ∂/∂y, ∂/∂z respectivamente.
    """
    nx, ny, nz = int(nx), int(ny), int(nz)
    if nx <= 0 or ny <= 0 or nz <= 0:
        raise ValueError("nx, ny y nz deben ser mayores que 0.")

    # idx_grid en orden Fortran: idx = ix + nx*iy + nx*ny*iz (idéntico a _build_laplacian).
    idx_grid = np.arange(nx * ny * nz, dtype=np.int64).reshape((nx, ny, nz), order="F")

    cx = _cell_centers(nx, hx)
    cy = _cell_centers(ny, hy)
    cz = _cell_centers(nz, hz)

    Dx = _build_directional_derivative(idx_grid, axis=0, centers=cx)
    Dy = _build_directional_derivative(idx_grid, axis=1, centers=cy)
    Dz = _build_directional_derivative(idx_grid, axis=2, centers=cz)
    return Dx, Dy, Dz


# Fase 6 (H-13): aquí vivía `build_gradient_operators_from_mesh`, azúcar de 9 líneas
# sobre `build_gradient_operators` (que SÍ se usa: joint_inversion, do27_harness,
# tests). El envoltorio nunca tuvo un solo llamador.

# --------------------------------------------------------------------------- #
# Self-test independiente                                                      #
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    """Valida los operadores sobre campos lineales, donde la derivada es exacta
    (gradiente constante) incluso en los bordes de primer orden."""
    print("[geophysics_math] Self-test de operadores de gradiente (cross-gradient prep).")

    ok = True
    for (nx, ny, nz, hx, hy, hz, tag) in (
        (6, 5, 4, 10.0, 20.0, 30.0, "uniforme (escalar)"),
        (7, 6, 5, None, None, None, "unitario (None)"),
        (8, 4, 6, np.linspace(5.0, 15.0, 8), np.full(4, 12.0), np.linspace(8.0, 20.0, 6), "no-uniforme (array)"),
    ):
        Dx, Dy, Dz = build_gradient_operators(nx, ny, nz, hx, hy, hz)
        nC = nx * ny * nz
        idx = np.arange(nC, dtype=np.int64).reshape((nx, ny, nz), order="F")

        cx = _cell_centers(nx, hx)
        cy = _cell_centers(ny, hy)
        cz = _cell_centers(nz, hz)
        xs = np.empty(nC); ys = np.empty(nC); zs = np.empty(nC)
        for iz in range(nz):
            for iy in range(ny):
                for ix in range(nx):
                    c = idx[ix, iy, iz]
                    xs[c] = cx[ix]; ys[c] = cy[iy]; zs[c] = cz[iz]

        # Campo lineal f = 3x - 2y + 5z  →  df/dx=3, df/dy=-2, df/dz=5 en toda celda.
        f = 3.0 * xs - 2.0 * ys + 5.0 * zs
        for label, D, expected in (("Dx", Dx, 3.0), ("Dy", Dy, -2.0), ("Dz", Dz, 5.0)):
            err = float(np.max(np.abs((D @ f) - expected)))
            passed = err < 1e-6
            ok = ok and passed
            print(f"  [{tag}] {label} shape={D.shape} max|err|={err:.3e} -> {'OK' if passed else 'FAIL'}")

    # Eje singleton → operador nulo.
    Dx1, Dy1, Dz1 = build_gradient_operators(1, 5, 5)
    singleton_ok = (Dx1.nnz == 0)
    ok = ok and singleton_ok
    print(f"  [singleton] Dx(nx=1) nnz={Dx1.nnz} -> {'OK' if singleton_ok else 'FAIL'}")

    print("RESULT:", "ALL OK" if ok else "FAILURES DETECTED")


if __name__ == "__main__":
    _self_test()
