"""
Fase 10 — Solver Escalable: LSMR + Selector Automático.

Para surveys grandes (n_active > 50K), LSMR tiene mejor convergencia que LSQR:
- Residuo ||r|| monotónicamente decreciente (LSQR puede oscilar en sistemas mal condicionados)
- Estimación de cond(A) más robusta
- Convergencia O(sqrt(kappa)) igual que LSQR, pero más estable numéricamente

El selector automático enruta según el tamaño del problema:
  n_active ≤ 8K   → TRF bounded (solve_inversion_lsqr path existente)
  8K < n_active ≤ 50K → LSQR (ruta existente)
  n_active > 50K  → LSMR (esta ruta)

El precondicionamiento está dado por el cambio de variable W_z formal
(Li & Oldenburg 1998, H-A0) ya aplicado en G_aug antes de llamar aquí.
No se forma A^T A explícitamente (lección Sprint 5A: fill-in explosivo).

Referencia: Fong & Saunders (2011), "LSMR: An iterative algorithm for
sparse least-squares problems", SIAM J. Sci. Comput. 33(5).
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# ── Constantes de umbral ──────────────────────────────────────────────────────
_SMALL_SOLVER_THRESH = 8_000    # ≤ usar TRF bounded
_LSMR_THRESH_DEFAULT = 50_000  # > usar LSMR si USE_LSMR_LARGE=True


def select_solver(
    n_active: int,
    use_bounded: bool = True,
    use_lsmr: bool = True,
    lsmr_threshold: int = _LSMR_THRESH_DEFAULT,
) -> str:
    """
    Selector automático de solver por escala.

    Returns:
        "trf_bounded"       n_active ≤ 8K y use_bounded=True
        "lsmr"              n_active > lsmr_threshold y use_lsmr=True
        "lsqr"              en cualquier otro caso
    """
    if use_bounded and n_active <= _SMALL_SOLVER_THRESH:
        return "trf_bounded"
    if use_lsmr and n_active > lsmr_threshold:
        return "lsmr"
    return "lsqr"


def solve_inversion_lsmr(
    G_aug: sp.csr_matrix,
    d_aug: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
    maxiter: int = 1000,
    tol: float = 1e-8,
) -> tuple[np.ndarray, float]:
    """
    LSMR solver para el sistema de inversión aumentado (Fase 10).

    Resuelve min ||G_aug @ m_tilde - d_aug||² con clip final al box [lb, ub].

    El sistema ya tiene el depth weighting formal W_z aplicado (idéntico al
    motor magnético post-commit ae4ab94), por lo que no se requiere un
    precondicionador explícito adicional.

    Args:
        G_aug: sistema aumentado CSR float64, shape (n_rows, n_active).
        d_aug: RHS float64, shape (n_rows,).
        lb: bound inferior para m_tilde, shape (n_active,).
        ub: bound superior para m_tilde, shape (n_active,).
        maxiter: máximo de iteraciones LSMR (default 1000, ~2× LSQR).
        tol: tolerancia atol=btol (default 1e-8).

    Returns:
        (m_tilde, conda)
        m_tilde: solución clipeada al box petrofísico, shape (n_active,).
        conda: estimación de cond(A) provista por LSMR.
    """
    result = spla.lsmr(
        G_aug,
        d_aug,
        damp=0.0,
        atol=tol,
        btol=tol,
        conlim=1e10,
        maxiter=maxiter,
        show=False,
    )
    # lsmr returns: (x, istop, itn, normr, normar, norma, conda, normx)
    m_raw = result[0]
    istop = result[1]
    itn = result[2]
    conda = float(result[6])

    _ISTOP_MSGS = {
        0: "no convergido",
        1: "||Ax-b|| pequeño",
        2: "solución exacta x",
        3: "A^T r pequeño",
        4: "cond(A) grande",
        5: "máx iteraciones",
        6: "damp grande",
        7: "||b|| pequeño",
    }
    print(
        f"[LSMR] itn={itn} istop={istop}({_ISTOP_MSGS.get(istop,'?')}) "
        f"cond(A)~{conda:.2e}"
    )
    if istop in (4, 5):
        print(
            f"[LSMR] WARN: istop={istop} — "
            + (
                "cond(A) alto, considerar revisar regularización."
                if istop == 4
                else f"alcanzó maxiter={maxiter}, solución puede ser no óptima."
            )
        )

    m_tilde = np.clip(m_raw, lb, ub)
    return m_tilde, conda


def solve_inversion_lsmr_wavelet(
    G_dense: np.ndarray,
    d_obs_weighted: np.ndarray,
    Wd: sp.dia_matrix,
    reg_blocks: list[sp.csr_matrix],
    reg_rhs: list[np.ndarray],
    lb: np.ndarray,
    ub: np.ndarray,
    wavelet: str = "db4",
    level: int = 4,
    threshold_frac: float = 0.01,
    maxiter: int = 1000,
    tol: float = 1e-8,
) -> tuple[np.ndarray, float, dict]:
    """
    LSMR con compresión wavelet del Jacobiano (Fase 10 — ruta grande).

    Para n_active > 200K donde G_dense > 400 MB. Comprime G antes de
    construir G_aug, reduciendo el footprint de memoria ~85-90%.

    Args:
        G_dense: kernel de sensibilidad sin comprimir, (n_sensors, n_active).
        d_obs_weighted: Wd @ d_obs, shape (n_sensors,).
        Wd: matriz de pesos de datos diagonal.
        reg_blocks: lista de bloques de regularización (ya escalados).
        reg_rhs: lista de RHS de regularización.
        lb, ub: bounds del box petrofísico.
        wavelet, level, threshold_frac: parámetros wavelet.

    Returns:
        (m_tilde, conda, compression_stats)
    """
    from exploration.jacobian_wavelet import build_compressed_kernel, wavelet_forward_error

    n_sensors, n_active = G_dense.shape
    size_gb = n_sensors * n_active * 8 / 1e9
    print(
        f"[WAVELET+LSMR] G_dense={n_sensors}×{n_active} ({size_gb:.2f} GB) "
        f"— iniciando compresión wavelet..."
    )

    G_csr = build_compressed_kernel(G_dense, wavelet, level, threshold_frac)

    # Verificar error de compresión
    err_stats = wavelet_forward_error(G_dense, G_csr, n_test=10)
    print(
        f"[WAVELET+LSMR] Error forward: mean={err_stats['error_mean']*100:.3f}% "
        f"max={err_stats['error_max']*100:.3f}%"
    )
    if err_stats["error_mean"] > 0.005:
        print(
            f"[WAVELET+LSMR] WARN: error forward {err_stats['error_mean']*100:.2f}% > 0.5%. "
            f"Considerar reducir threshold_frac."
        )

    # Construir G_aug con kernel comprimido
    G_data = Wd @ G_csr
    blocks = [G_data] + reg_blocks
    G_aug = sp.vstack(blocks).tocsr()
    d_rhs = [d_obs_weighted] + reg_rhs
    d_aug = np.concatenate(d_rhs)

    m_tilde, conda = solve_inversion_lsmr(G_aug, d_aug, lb, ub, maxiter, tol)

    compression_stats = {
        "original_nnz": n_sensors * n_active,
        "compressed_nnz": G_csr.nnz,
        "compression_ratio": 1.0 - G_csr.nnz / (n_sensors * n_active),
        **err_stats,
    }
    return m_tilde, conda, compression_stats


# ── Zarr Out-of-Core (Fase 10 §10.4) ─────────────────────────────────────────

def make_zarr_linear_operator(
    zarr_path: str,
    chunk_rows: int = 200,
) -> "sp.linalg.LinearOperator":
    """
    Crea un scipy LinearOperator respaldado por un Zarr array en disco.

    Permite pasar matrices G > 4 GB a LSMR sin cargarlas en RAM completas.
    Lee la Zarr en chunks de `chunk_rows` sensores durante cada MVP.

    Args:
        zarr_path: ruta al .zarr escrito por compute_jacobian_dask().
        chunk_rows: sensores por chunk durante matvec/rmatvec.

    Returns:
        LinearOperator (n_sensors, n_active) que delega a disco.
    """
    import zarr as _zarr

    z = _zarr.open_array(zarr_path, mode="r")
    n_sensors, n_active = z.shape

    def _matvec(v: np.ndarray) -> np.ndarray:
        """G @ v — lee en chunks, nunca carga G completa."""
        result = np.zeros(n_sensors, dtype=np.float64)
        v64 = np.asarray(v, dtype=np.float64)
        for i in range(0, n_sensors, chunk_rows):
            chunk = z[i : i + chunk_rows, :].astype(np.float64)
            result[i : i + chunk_rows] = chunk @ v64
        return result

    def _rmatvec(v: np.ndarray) -> np.ndarray:
        """G.T @ v — acumula contribución de cada chunk."""
        result = np.zeros(n_active, dtype=np.float64)
        v64 = np.asarray(v, dtype=np.float64)
        for i in range(0, n_sensors, chunk_rows):
            chunk = z[i : i + chunk_rows, :].astype(np.float64)
            result += chunk.T @ v64[i : i + chunk_rows]
        return result

    return spla.LinearOperator(
        shape=(n_sensors, n_active),
        matvec=_matvec,
        rmatvec=_rmatvec,
        dtype=np.float64,
    )


def estimate_kernel_memory_gb(n_sensors: int, n_active: int, dtype_bytes: int = 8) -> float:
    """Estima memoria de la matriz G densa en GB."""
    return n_sensors * n_active * dtype_bytes / 1e9
