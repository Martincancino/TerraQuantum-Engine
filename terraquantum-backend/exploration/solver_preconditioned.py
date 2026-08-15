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


# ── FASE A1 (Tier 1) — FISTA proyectado: bounds reales a cualquier escala ─────
#
# Problema: LSQR/LSMR + clip NO es un solver bound-constrained: el clip
# post-hoc descarta los lóbulos fuera del box sin redistribuir la masa,
# degradando el misfit ~35% en cuerpos compactos con no-negatividad estricta
# (medido 2026-06-10, esfera sintética density_min=2.6). TRF (lsq_linear) sí
# respeta bounds pero solo escala hasta n_active ≈ 8K.
#
# Solución: FISTA (Beck & Teboulle 2009) sobre  min ½‖G_aug·m − d_aug‖²
# s.a. m ∈ [lb, ub]. La proyección sobre la caja es separable y exacta
# (np.clip, O(n)). Con warm start desde la solución LSQR/LSMR clippeada, el
# objetivo solo puede MEJORAR respecto al comportamiento actual.
# Restart adaptativo de O'Donoghue & Candès (2015) para evitar la oscilación
# del momentum en sistemas mal condicionados.

def _estimate_lipschitz(G_aug, n: int, n_iter: int = 20, seed: int = 0) -> float:
    """L = σ_max(G_aug)² por power iteration sobre GᵀG (sin formar GᵀG)."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(n)
    v /= np.linalg.norm(v)
    lam = 1.0
    for _ in range(n_iter):
        u = G_aug.T @ (G_aug @ v)
        lam = float(np.linalg.norm(u))
        if lam <= 0.0:
            return 1.0
        v = u / lam
    return lam


def solve_inversion_pgd_fista(
    G_aug,
    d_aug: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
    x0: "np.ndarray | None" = None,
    max_iter: int = 500,
    tol_pg: float = 1e-4,
    tol_rel: float = 1e-9,
) -> tuple[np.ndarray, dict]:
    """
    FISTA proyectado en caja para el sistema aumentado de inversión.

    Args:
        G_aug: matriz sparse CSR o LinearOperator (n_rows, n) con @ y .T @.
        d_aug: RHS (n_rows,).
        lb, ub: bounds del box petrofísico en espacio m_tilde.
        x0: warm start (típicamente la solución LSQR/LSMR clippeada). None → 0.
        max_iter: tope de iteraciones (2 matvecs por iteración).
        tol_pg: criterio KKT RELATIVO — parar cuando la norma ∞ del gradiente
            proyectado cae a tol_pg × su valor en el primer chequeo (k=10).
            Es scale-free: un umbral absoluto falla cuando los bounds en m̃
            vienen escalados por col_norms (~1e6) y el paso 1/L es minúsculo.
        tol_rel: cambio relativo mínimo de x entre iteraciones (3 consecutivas).

    Returns:
        (x, info) — info: n_iter, n_restarts, pg_norm, obj_warmstart, obj_final,
        frac_lb_active, frac_ub_active, lipschitz, converged_by.
    """
    n = lb.shape[0]
    lb = np.asarray(lb, dtype=np.float64)
    ub = np.asarray(ub, dtype=np.float64)

    L = _estimate_lipschitz(G_aug, n) * 1.05  # margen: power-iter subestima σ_max
    step = 1.0 / L

    def _obj(x: np.ndarray) -> float:
        r = G_aug @ x - d_aug
        return 0.5 * float(r @ r)

    x = np.clip(np.zeros(n) if x0 is None else np.asarray(x0, dtype=np.float64), lb, ub)
    obj_warmstart = _obj(x)
    obj_best = obj_warmstart
    x_best = x.copy()

    # FISTA puro converge en O(√κ) iteraciones — inviable con cond(GᵀG) ~ 1e11
    # del sistema aumentado real. Esquema GPCG (Moré & Toraldo 1991): fases de
    # gradiente proyectado para IDENTIFICAR el active-set, alternadas con un
    # solve LSQR (Krylov) en el SUBESPACIO LIBRE, que sí maneja el mal
    # condicionamiento. El subspace-solve requiere slicing de columnas → solo
    # disponible con matrices sparse; con LinearOperator se degrada a FISTA puro.
    _can_subspace = hasattr(G_aug, "tocsr") or sp.issparse(G_aug)

    n_restarts = 0
    pg_norm = np.inf
    pg_norm0: "float | None" = None
    converged_by = "max_outer"
    total_pg_iters = 0
    n_subspace_solves = 0

    def _pg_phase(x_in: np.ndarray, n_iters: int) -> np.ndarray:
        """FISTA proyectado con restart adaptativo (O'Donoghue & Candès 2015)."""
        nonlocal n_restarts, total_pg_iters
        xx = x_in.copy()
        yy = xx.copy()
        xx_prev = xx.copy()
        tt = 1.0
        for _ in range(n_iters):
            grad = G_aug.T @ (G_aug @ yy - d_aug)
            xx = np.clip(yy - step * grad, lb, ub)
            if float((yy - xx) @ (xx - xx_prev)) > 0.0:
                tt = 1.0
                yy = xx.copy()
                n_restarts += 1
            else:
                tt_next = (1.0 + np.sqrt(1.0 + 4.0 * tt * tt)) / 2.0
                yy = xx + ((tt - 1.0) / tt_next) * (xx - xx_prev)
                tt = tt_next
            xx_prev = xx
            total_pg_iters += 1
        return xx

    max_outer = 6
    pg_iters_per_phase = max(20, min(60, max_iter // max_outer))
    prev_free: "np.ndarray | None" = None

    for outer in range(1, max_outer + 1):
        # ── Fase 1: gradiente proyectado para asentar el active-set ──────────
        x = _pg_phase(x, pg_iters_per_phase)
        obj_now = _obj(x)
        if obj_now < obj_best:
            obj_best, x_best = obj_now, x.copy()

        # ── KKT + conjunto libre ──────────────────────────────────────────────
        grad_x = G_aug.T @ (G_aug @ x - d_aug)
        pg = x - np.clip(x - step * grad_x, lb, ub)
        pg_norm = float(np.max(np.abs(pg)))
        if pg_norm0 is None:
            pg_norm0 = max(pg_norm, 1e-300)
        if pg_norm < tol_pg * pg_norm0:
            converged_by = "kkt_projected_gradient"
            break

        # Libre = interior estricto, o en bound con gradiente apuntando adentro
        eps = 1e-12 * np.maximum(np.abs(ub - lb), 1.0)
        at_lb = x <= lb + eps
        at_ub = x >= ub - eps
        free = (~at_lb & ~at_ub) | (at_lb & (grad_x < 0.0)) | (at_ub & (grad_x > 0.0))
        n_free = int(np.sum(free))

        if not _can_subspace or n_free == 0:
            continue  # solo fases PG (LinearOperator / todo activo)

        # ── Fase 2: solve Krylov en el subespacio libre (Moré-Toraldo) ───────
        # min ‖G_F·δ − r‖ con r = d − G·x; luego x_F ← clip(x_F + δ).
        G_csr = G_aug.tocsr() if not sp.isspmatrix_csr(G_aug) else G_aug
        G_free = G_csr[:, np.flatnonzero(free)]
        r_cur = d_aug - G_csr @ x
        delta = spla.lsqr(G_free, r_cur, iter_lim=200, atol=1e-8, btol=1e-8)[0]
        x_trial = x.copy()
        x_trial[free] = np.clip(x[free] + delta, lb[free], ub[free])
        n_subspace_solves += 1

        obj_trial = _obj(x_trial)
        if obj_trial < obj_best:
            obj_best, x_best = obj_trial, x_trial.copy()
            # Mejora relativa marginal + active-set estable → terminamos
            if prev_free is not None and np.array_equal(free, prev_free) and \
                    (obj_now - obj_trial) < tol_rel * max(obj_now, 1e-300):
                x = x_trial
                converged_by = "active_set_stable"
                break
            x = x_trial
        else:
            # El paso de subespacio no mejoró (active-set aún cambiando):
            # seguir solo con fases PG desde el mejor punto conocido.
            x = x_best.copy()
        prev_free = free

    obj_final = _obj(x)
    if obj_final > obj_best:
        # Garantía estructural: nunca peor que el mejor iterado (≥ warm start).
        x = x_best
        obj_final = obj_best
    k = total_pg_iters

    info = {
        "n_iter": int(k),
        "n_subspace_solves": int(n_subspace_solves),
        "n_restarts": int(n_restarts),
        "pg_norm": float(pg_norm),
        "obj_warmstart": float(obj_warmstart),
        "obj_final": float(obj_final),
        "frac_lb_active": float(np.mean(np.isclose(x, lb, atol=1e-12))),
        "frac_ub_active": float(np.mean(np.isclose(x, ub, atol=1e-12))),
        "lipschitz": float(L),
        "converged_by": converged_by,
    }
    print(
        f"[GPCG] pg_iters={info['n_iter']} subspace_solves={n_subspace_solves} "
        f"restarts={info['n_restarts']} obj {obj_warmstart:.6e} -> {obj_final:.6e} "
        f"({converged_by}) bounds activos lb={info['frac_lb_active']*100:.1f}% "
        f"ub={info['frac_ub_active']*100:.1f}%"
    )
    return x, info


# Fase 6 (H-13): aquí vivía `solve_inversion_lsmr_wavelet` (72 líneas), con cero
# llamadores — el envoltorio que nadie cableó nunca, junto con las dos perillas de
# config que lo prometían.
#
# CIERRE 2026-08-14: `exploration/jacobian_wavelet.py` se borró también. Aquella pasada
# dejó los building blocks "vivos y con tests", pero sin llamador sus únicos
# importadores eran esos tests, y la Fase 3 midió en el runner que el algoritmo NO
# cumple su criterio §10.6.1 (98,2% retenido, exigiendo <15%). Retomar Farquharson &
# Oldenburg (2003) es física nueva en el camino crítico: exige medición, no un import.

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
