import logging
import os
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
from scipy.spatial import cKDTree  # F0.2: HPC KDTree kernel híbrido

from exploration.geophysics_weights import sigma_parametric as _shared_sigma_parametric
from exploration.potential_field_core import (
    MODEL_WEIGHT_SENSITIVITY,
    SMALLNESS_IDENTITY_IN_TILDE,
    SMALLNESS_SCALED_BY_W,
    active_cells_from_topography,
    build_model_weights,
    declare_functional,
    depth_row_weights,
    estimate_cond_from_columns,
    initial_irls_eps,
    irls_focus_weights,
    assemble_shuttle_ensemble,
    build_smoothing_operator,
    map_intervals_to_cells,
    normal_equations,
    observable_domain_mask,
    relative_misfit,
    combine_existing_and_new_data,
    inject_extra_reg_blocks,
    select_subregion,
    split_region_response,
    solve_local_region_cg,
    validate_live_update_args,
    woodbury_update_from_new_rows,
    resolve_reference_model,
    resolve_sigma,
    robust_amplitude,
)
from exploration.potential_field_core import sigma_adaptive as _shared_sigma_adaptive

logger = logging.getLogger(__name__)


# ── Red de seguridad de memoria del kernel disperso (NO un tope de vóxeles) ──────
# El kernel CSR + sus arrays transitorios (rows/cols/data antes del coalesce) cuesta
# ~24 B por no-cero como cota superior. Si la estimación supera esta fracción de la
# RAM libre se aborta con un error CLARO en vez de tumbar el proceso por OOM. El
# guard depende de la DISPERSIÓN real (geometría × cutoff), NO del conteo de celdas:
# un kernel disperso de millones de celdas pasa; uno denso de pocas celdas se detiene.
_KERNEL_BYTES_PER_NNZ = 24
_KERNEL_MEM_SAFETY_FRACTION = 0.6


def _guard_sparse_kernel_memory(tree, sensor_coords, cutoff_radius, n_active, n_obs):
    """Estima el tamaño del kernel disperso ANTES de materializarlo y aborta con un
    error accionable (SOLVER_KERNEL_TOO_DENSE) si no cabe en la RAM disponible.

    Usa ``query_ball_point(return_length=True)``: devuelve SÓLO el conteo de vecinos
    por sensor (O(n_obs) memoria), sin materializar las listas de índices — que para
    un kernel denso son justamente lo que dispara el OOM. NO limita el número de
    vóxeles; sólo protege ante un kernel patológicamente denso (cutoff desmedido).

    Retorna el NNZ estimado (para logging/tests) o None si SciPy no soporta el conteo
    rápido (degradación segura: no se estima, no se rompe nada).
    """
    try:
        counts = tree.query_ball_point(
            np.asarray(sensor_coords, dtype=np.float64),
            r=float(cutoff_radius),
            return_length=True,
        )
    except TypeError:
        # SciPy antiguo sin return_length → no estimamos (no es un fallo).
        return None

    nnz = int(np.sum(counts))
    bytes_est = nnz * _KERNEL_BYTES_PER_NNZ

    try:
        import psutil
        available = int(psutil.virtual_memory().available)
    except Exception:
        available = None

    if available is not None and bytes_est > available * _KERNEL_MEM_SAFETY_FRACTION:
        fill = nnz / max(1, int(n_active) * int(n_obs))
        from core.errors import SolverMemoryError
        raise SolverMemoryError(
            "SOLVER_KERNEL_TOO_DENSE",
            kernel_mb=round(bytes_est / 1e6, 1),
            available_mb=round(available / 1e6, 1),
            fill_pct=round(fill * 100.0, 1),
            cutoff_m=round(float(cutoff_radius), 1),
            n_active=int(n_active),
            n_obs=int(n_obs),
            technical_details={"nnz_estimate": nnz},
        )
    return nnz


def _sigma_adaptive(
    g_observed: np.ndarray,
    detect_outliers: bool = True,
) -> tuple:
    """
    R-04: Sigma calibrado a la amplitud de los datos (Li & Oldenburg / SimPEG).

    Formulación base:  sigma_i = max(0.02 * |d_obs_i|,  0.01 * data_range)

    ROBUST VERSION (FASE 18):

    Outlier detection by MAD (Median Absolute Deviation):
    - is_outlier = |g_i - median(g)| > 3 * 1.4826 * MAD
    - Outliers downweighted by 10× (permissive sigma)
    - Clean data range calculated from p5-p95 percentiles, not min-max

    CAVEAT: Downweighting by 10× is heuristic. For highly anomalous surveys
    (>10% outliers), user should inspect CSV manually or reduce threshold.

    Reference: Li & Oldenburg 1998; Hampel et al. 1986 (robust statistics).

    Returns
    -------
    sigma : np.ndarray
    is_outlier : np.ndarray[bool]  — True for sensors flagged as outliers

    FASE 7 (H-9): la aritmética vive ahora una sola vez, en
    :func:`exploration.potential_field_core.sigma_adaptive`, compartida con el motor
    magnético — que la tenía clonada línea a línea. Este wrapper conserva el defecto
    `detect_outliers=True` de gravimetría, distinto del magnético (`False`), para que
    la asimetría siga siendo visible en vez de esconderse dentro de la función común.
    """
    return _shared_sigma_adaptive(g_observed, detect_outliers=detect_outliers)


def _sigma_parametric(g_observed: np.ndarray, noise_floor: float, noise_pct: float) -> np.ndarray:
    """
    Sigma con piso instrumental explícito (flujo de datos de campo).

        sigma_i = max(noise_floor, noise_pct * |d_obs_i|)

    noise_floor es un PISO (no se suma): para anomalías de Bouguer bien
    corregidas el ruido restante es instrumental (CG-6 ≈ 0.005 mGal) y el
    término relativo solo domina cuando |d| es grande. La forma aditiva
    anterior (floor + pct·|d|) sobreestimaba sigma ~|d|/floor veces para
    datos de campo, colapsando chi²_red a ~0.

    Unidades: las mismas de g_observed (el caller convierte mGal → m/s²).

    Delega en :func:`exploration.geophysics_weights.sigma_parametric` (definición
    compartida con el motor magnético); se conserva este wrapper para no romper
    los call-sites internos.
    """
    return _shared_sigma_parametric(g_observed, noise_floor, noise_pct)


def _validate_gravity_observations(
    g_observed: np.ndarray,
    sensor_coords,
    min_sensors: int = 5,
):
    """
    Fase 14: CSV Validator Strict — validación de observaciones antes de la inversión.

    Revisa: NaN/Inf, n_sensors mínimo, rango cero, duplicados (x,z) y outliers.
    Los sensores duplicados se promedian automáticamente (mismo x,z dentro de 1 m).

    Returns
    -------
    g_clean    : np.ndarray — observaciones validadas (duplicados promediados).
    sc_clean   : np.ndarray | None — coordenadas limpias (duplicados fusionados).
    warnings   : list[str] — avisos no-fatales para logging.

    Raises
    ------
    ValueError para errores críticos (NaN, rango cero, < min_sensors).
    """
    g = np.asarray(g_observed, dtype=np.float64)
    n = len(g)

    # 1. NaN / Inf
    if not np.isfinite(g).all():
        n_bad = int(np.sum(~np.isfinite(g)))
        raise ValueError(
            f"g_observed contiene {n_bad} valor(es) NaN o Inf. "
            "Verifica el CSV o aplica limpieza antes de la inversión."
        )

    # 2. Mínimo de sensores
    if n < min_sensors:
        raise ValueError(
            f"Se requieren al menos {min_sensors} observaciones para la inversión 3D. "
            f"Se recibieron {n}. Agrega más estaciones al CSV."
        )

    # 3. Rango cero
    data_range = float(np.ptp(g))
    if data_range < 1e-30:
        raise ValueError(
            "Rango de datos cero: todas las observaciones son idénticas. "
            "Verifica que el CSV contenga variación lateral de gravedad."
        )

    warn_list: list = []
    g_out = g.copy()
    sc_out = None if sensor_coords is None else np.asarray(sensor_coords, dtype=np.float64)

    # 4. Duplicados de sensor: mismo (x, z) dentro de 1 m → promediar + warning
    if sc_out is not None and sc_out.ndim == 2 and sc_out.shape[0] == n:
        # Columna x=0, z=2 si shape[1]>=3; o x=0, z=1 si shape[1]==2
        xz = sc_out[:, [0, 2]] if sc_out.shape[1] >= 3 else sc_out[:, :2]
        tol = 1.0  # 1 m — precisión GPS de campo
        keys = np.round(xz / tol).astype(np.int64)
        key_to_indices: dict = {}
        for i, key in enumerate(map(tuple, keys.tolist())):
            key_to_indices.setdefault(key, []).append(i)

        dup_groups = {k: v for k, v in key_to_indices.items() if len(v) > 1}
        if dup_groups:
            n_dup_sensors = sum(len(v) for v in dup_groups.values()) - len(dup_groups)
            warn_list.append(
                f"Sensores duplicados: {n_dup_sensors} posición(es) (x,z) repetida(s). "
                "Se promedian automáticamente."
            )
            keep_mask = np.ones(n, dtype=bool)
            for indices in dup_groups.values():
                g_out[indices[0]] = float(np.mean(g_out[list(indices)]))
                for i in indices[1:]:
                    keep_mask[i] = False
            g_out = g_out[keep_mask]
            sc_out = sc_out[keep_mask]

    # 5. Ruido anómalo: 1 sensor >> 10× mediana → flag (no error, solo aviso)
    n_clean = len(g_out)
    if n_clean > 1:
        median_abs = float(np.median(np.abs(g_out)))
        if median_abs > 1e-30:
            ratio = np.abs(g_out) / median_abs
            n_anomalous = int(np.sum(ratio > 10.0))
            # Sospechoso si afecta < 20 % de las estaciones (outlier aislado)
            if 0 < n_anomalous <= max(1, n_clean // 5):
                warn_list.append(
                    f"Ruido anómalo: {n_anomalous} sensor(es) con |g_i| > 10× la mediana "
                    f"({median_abs:.3e}). Considera revisar o filtrar outliers."
                )

    return g_out, sc_out, warn_list


def hutchinson_diag_inv(
    A,
    n_probes: int = 32,
    cg_maxiter: int = 300,
    cg_rtol: float = 1e-6,
    seed: int = 0,
) -> np.ndarray:
    """
    Estimador estocástico de Hutchinson de diag(A^{-1}) para A dispersa SPD.

        diag(A^{-1}) ≈ (1/N) Σ_k  z_k ⊙ (A^{-1} z_k),   z_k ~ Rademacher (±1)

    Cada A^{-1} z_k se resuelve por Gradiente Conjugado (A debe ser SPD). El
    estimador es INSESGADO: como E[z zᵀ] = I, se cumple
        E[z ⊙ (A^{-1} z)] = diag(A^{-1}).
    El error decae como O(1/√N). Es el método estándar para la diagonal de la
    covarianza posterior en problemas inversos lineales gaussianos a gran escala
    (Bekas, Kokiopoulou & Saad, 2007), sin formar A^{-1} explícitamente.

    Parameters
    ----------
    A          : scipy.sparse SPD (n×n).
    n_probes   : número de vectores sonda (más sondas → menos varianza del estimador).
    cg_maxiter : tope de iteraciones del CG por sonda.
    cg_rtol    : tolerancia relativa del CG.
    seed       : semilla RNG (reproducibilidad determinística).

    Returns
    -------
    diag_est : ndarray (n,) — estimación de diag(A^{-1}), recortada a ≥ 0.
    """
    from scipy.sparse.linalg import cg, LinearOperator

    A = A.tocsr()
    n = A.shape[0]
    if A.shape[0] != A.shape[1]:
        raise ValueError("A debe ser cuadrada para estimar diag(A^{-1}).")

    rng = np.random.default_rng(seed)

    # Preacondicionador de Jacobi (diagonal): acelera CG, no cambia el resultado.
    diag_A = A.diagonal()
    diag_A_safe = np.where(np.abs(diag_A) > 1e-30, diag_A, 1.0)
    M = LinearOperator((n, n), matvec=lambda v: v / diag_A_safe)

    acc = np.zeros(n, dtype=np.float64)
    for _ in range(int(n_probes)):
        z = rng.integers(0, 2, size=n).astype(np.float64) * 2.0 - 1.0  # Rademacher ±1
        x, _info = cg(A, z, rtol=cg_rtol, atol=0.0, maxiter=cg_maxiter, M=M)
        acc += z * x

    diag_est = acc / float(n_probes)
    return np.clip(diag_est, a_min=0.0, a_max=None)


def null_space_shuttle_directions(
    G,
    n_shuttles: int = 8,
    mu: float = 1e-3,
    smooth_op=None,
    cg_maxiter: int = 300,
    cg_rtol: float = 1e-6,
    seed: int = 0,
) -> tuple:
    """
    FASE 8.1 (peldaño 1 de la escalera de UQ) — "null-space shuttle".

    Genera direcciones de perturbación δ que viven (aprox.) en el ESPACIO NULO DE
    DATOS del operador directo escalado G: G·δ ≈ 0. Cada δ deja el misfit de datos
    esencialmente invariante → sumarla a la solución produce un MODELO ALTERNATIVO
    igualmente consistente con el dato. El abanico de alternativas cuantifica la
    NO-UNICIDAD del problema inverso, que es una cara de la incertidumbre que la
    σ posterior lineal de Hutchinson (covarianza alrededor de UN óptimo) NO ve.

    Método (Deal & Nolet 1996; Fichtner & Zunino, GJI 2018):

        δ = s − G⁺(G s),     G⁺ = (GᵀG + μ²I)⁻¹ Gᵀ   (pseudoinversa regularizada)

    donde s es una dirección aleatoria. G⁺(G s) es la COMPONENTE de s que el dato
    RESUELVE; al restarla, δ es justo la parte que el dato no restringe. Con μ→0,
    δ → proyección exacta sobre null(G); μ pequeño la estabiliza numéricamente.
    `smooth_op` (un LinearOperator, p.ej. (I+γ LᵀL)⁻¹) suaviza s ANTES de proyectar
    para que las alternativas sean geológicamente plausibles (campos correlacionados)
    y no ruido blanco — el shuttle "viaja" por modelos lisos, no por sal y pimienta.

    Cada A^{-1}-vez se resuelve matrix-free por CG (GᵀG+μ²I es SPD), sin formar nada
    denso: escala a problemas grandes igual que el estimador de Hutchinson.

    ALCANCE HONESTO: es un muestreo de la no-unicidad LINEAL alrededor de la solución
    (direcciones que el operador linealizado no ve), no un posterior bayesiano. No
    captura no-linealidad fuerte, error de modelo ni el prior completo; los peldaños
    superiores de la escalera (SVGD recocido, HMC/difusión) son R&D pendiente.

    Parameters
    ----------
    G          : operador directo escalado (n_data × n), sparse o LinearOperator.
    n_shuttles : número de direcciones de espacio nulo a generar.
    mu         : regularización de la pseudoinversa (estabiliza el CG; 0 prohibido).
    smooth_op  : LinearOperator opcional (n×n) aplicado a s para correlacionarla.
    cg_maxiter : tope de iteraciones del CG por shuttle.
    cg_rtol    : tolerancia relativa del CG.
    seed       : semilla RNG (reproducibilidad determinística).

    Returns
    -------
    directions   : (n_shuttles, n) — direcciones de espacio nulo, norma unitaria.
    preserved    : (n_shuttles,)  — ratio ‖G δ‖ / ‖G s‖ por shuttle. Idealmente ≈ 0:
                   cuanto MENOR, mejor preserva el ajuste de datos la alternativa
                   (diagnóstico de honestidad; se reporta, no se esconde).
    null_fraction: (n_shuttles,)  — ‖δ_cruda‖ / ‖s‖ ANTES de normalizar: cuánta de la
                   dirección aleatoria sobrevive a la proyección, i.e. cuánto espacio
                   nulo HAY. ≈0 ⇒ el dato lo resuelve todo (sin shuttle real); O(1) ⇒
                   gran no-unicidad. Distingue "núcleo grande" de "núcleo nulo", algo
                   que `preserved` (que es ≈0 en ambos casos) no puede.
    """
    from scipy.sparse.linalg import aslinearoperator, cg, LinearOperator

    if mu <= 0:
        raise ValueError("mu debe ser > 0: regulariza la pseudoinversa (GᵀG+μ²I SPD).")

    Glin = aslinearoperator(G)
    n_data, n = Glin.shape
    mu2 = float(mu) ** 2

    # Operador de información H = GᵀG + μ²I (SPD) como matvec, sin materializar.
    def _H_matvec(v):
        return Glin.rmatvec(Glin.matvec(v)) + mu2 * v

    H = LinearOperator((n, n), matvec=_H_matvec)
    # Preacondicionador de Jacobi barato: H_jj ≈ ‖G col j‖² + μ². Para sparse lo
    # calculamos exacto; si no, caemos a identidad (CG sigue convergiendo).
    try:
        col_sq = np.asarray(G.power(2).sum(axis=0)).ravel()
        diag_H = np.maximum(col_sq + mu2, 1e-30)
        M = LinearOperator((n, n), matvec=lambda v: v / diag_H)
    except AttributeError:
        M = None

    rng = np.random.default_rng(seed)
    directions = np.empty((int(n_shuttles), n), dtype=np.float64)
    preserved = np.empty(int(n_shuttles), dtype=np.float64)
    null_fraction = np.empty(int(n_shuttles), dtype=np.float64)

    for k in range(int(n_shuttles)):
        s = rng.standard_normal(n)
        if smooth_op is not None:
            s = smooth_op.matvec(s)
        s_norm = np.linalg.norm(s)
        if s_norm < 1e-300:
            directions[k] = 0.0
            preserved[k] = 0.0
            null_fraction[k] = 0.0
            continue
        s = s / s_norm   # ‖s‖ = 1

        # Componente resuelta por el dato: resolved = (GᵀG+μ²I)⁻¹ Gᵀ (G s).
        rhs = Glin.rmatvec(Glin.matvec(s))
        resolved, _info = cg(H, rhs, rtol=cg_rtol, atol=0.0, maxiter=cg_maxiter, M=M)
        delta = s - resolved   # parte que el dato NO ve ⇒ G·delta ≈ 0

        gs = Glin.matvec(s)
        gd = Glin.matvec(delta)
        gs_norm = float(np.linalg.norm(gs))
        preserved[k] = float(np.linalg.norm(gd)) / gs_norm if gs_norm > 0 else 0.0

        d_norm = float(np.linalg.norm(delta))   # ‖s‖=1 ⇒ esto ES la fracción de núcleo
        null_fraction[k] = d_norm
        directions[k] = delta / d_norm if d_norm > 1e-300 else delta

    return directions, preserved, null_fraction


def woodbury_low_rank_update(
    A,
    m0,
    U,
    d_new,
    cg_maxiter: int = 500,
    cg_rtol: float = 1e-8,
) -> tuple:
    """
    FASE 8.2 (Live Update local) — actualización de rango-k de Sherman–Morrison–Woodbury.

    El modelo actual m0 resuelve el sistema de información regularizado A·m0 = b0 del
    dato recogido HASTA AHORA (A = G̃ᵀG̃ + λ_s²·L̃ᵀL̃ + λ²·I en el espacio escalado;
    b0 = G̃ᵀd̃). Cuando llegan k OBSERVACIONES NUEVAS — un sondaje, una línea de vuelo o
    una corrección de dato — su aporte son k filas nuevas Ũ (k×n, forward escalado) con
    objetivos d_new (k,). El sistema aumentado es:

        A1 = A + ŨᵀŨ ,     b1 = b0 + Ũᵀ d_new

    y su solución NO requiere re-resolver desde cero ni rearmar A: por la identidad de
    Woodbury, con W = A⁻¹ Ũᵀ (k resoluciones CG contra la MISMA A, ya precondicionada) y
    la matriz de CAPACITANCIA C = I_k + Ũ W (k×k, densa y diminuta),

        m1 = m_b − W C⁻¹ (Ũ m_b) ,     m_b = m0 + W d_new .

    NO hace falta b0 explícito: b1 = A·m0 + Ũᵀ d_new se reconstruye de m0. El costo es k
    resoluciones contra A (BC global "congelado": A, su regularización y el depth
    weighting NO cambian), frente a re-correr todo el pipeline de inversión acotada.

    ALCANCE HONESTO: es la actualización EXACTA de la solución de MÍNIMOS CUADRADOS
    LINEAL regularizada con A/operadores congelados. NO honra cotas (no-negatividad,
    box): el llamador puede recortar a [min,max] DESPUÉS, lo que reintroduce un residuo
    pequeño; NO recomputa el column scaling Ws ni el σ adaptivo (un re-solve completo
    daría una solución también válida pero distinta). Propiedad clave (no-op): si d_new
    ya coincide con la predicción actual Ũ·m0, entonces m1 = m0 EXACTAMENTE.

    Parameters
    ----------
    A          : matriz de información (n×n) SPD, sparse o LinearOperator (la MISMA de
                 estimate_posterior_std / del solver, en el espacio escalado).
    m0         : (n,) solución actual A⁻¹b0 en el espacio escalado.
    U          : (k, n) filas nuevas del forward ESCALADO (Wd_new·G_new·Ws).
    d_new      : (k,) dato nuevo ESCALADO (d_new_obs / sigma_new).
    cg_maxiter : tope de iteraciones CG por fila nueva.
    cg_rtol    : tolerancia relativa del CG (estricta: la exactitud del update depende).

    Returns
    -------
    m1   : (n,) modelo actualizado, MISMO espacio que m0.
    info : dict con 'capacitance_cond' (cond de C), 'update_norm' (‖m1−m0‖), 'n_new' (k).
    """
    from scipy.sparse.linalg import aslinearoperator, cg, LinearOperator

    m0 = np.asarray(m0, dtype=np.float64).ravel()
    n = m0.shape[0]
    U = np.atleast_2d(np.asarray(U, dtype=np.float64))
    if U.shape[1] != n:
        raise ValueError(f"U debe ser (k, n={n}); tiene {U.shape}.")
    d_new = np.atleast_1d(np.asarray(d_new, dtype=np.float64)).ravel()
    k = U.shape[0]
    if d_new.shape[0] != k:
        raise ValueError(f"d_new debe tener k={k} elementos; tiene {d_new.shape[0]}.")
    if k == 0:
        return m0.copy(), {"capacitance_cond": 1.0, "update_norm": 0.0, "n_new": 0}

    Alin = aslinearoperator(A)
    # Preacondicionador de Jacobi (diag de A) si está disponible.
    try:
        diagA = np.maximum(np.abs(A.diagonal()), 1e-30)
        M = LinearOperator((n, n), matvec=lambda v: v / diagA)
    except AttributeError:
        M = None

    def _solve(rhs):
        x, _info = cg(Alin, rhs, rtol=cg_rtol, atol=0.0, maxiter=cg_maxiter, M=M)
        return x

    # W = A⁻¹ Ũᵀ  (n×k): una resolución CG por fila nueva (matrix-free).
    W = np.empty((n, k), dtype=np.float64)
    for i in range(k):
        W[:, i] = _solve(U[i])
    C = np.eye(k) + U @ W                  # capacitancia (k×k)
    m_b = m0 + W @ d_new
    z = np.linalg.solve(C, U @ m_b)        # C⁻¹ (Ũ m_b)
    m1 = m_b - W @ z

    info = {
        "capacitance_cond": float(np.linalg.cond(C)),
        "update_norm": float(np.linalg.norm(m1 - m0)),
        "n_new": int(k),
    }
    return m1, info


def rank_drill_targets(
    model,
    x,
    y,
    z,
    posterior_std=None,
    threshold=None,
    min_exceedance_prob: float = 0.5,
    exclusion_radius=None,
    top_n: int = 10,
    sense: str = "positive",
    rank_by: str = "expected_exceedance",
    lcb_k: float = 1.0,
) -> list:
    """
    FASE 8.3 (targeting probabilístico automático) — ranking 3D de BLANCOS PERFORABLES.

    Convierte un modelo invertido + su σ POSTERIOR por vóxel (de estimate_posterior_std
    Hutchinson o del ensemble null-space de 8.1) en una LISTA RANKEADA de objetivos de
    perforación discretos, cada uno con su probabilidad estadística de ser anómalo. Es
    MOTOR-AGNÓSTICO: sirve para densidad (t/m³) o susceptibilidad (SI); el llamador pasa
    el modelo y la σ en sus unidades físicas.

    Para cada vóxel j, bajo el posterior lineal-gaussiano m_j ~ N(model_j, σ_j²), con
    diff = ±(model_j − τ) (signo según `sense`; "negative" = cuerpos de BAJO contraste
    como kimberlita/sal) y d = diff/σ_j:
      - exceedance_prob       = Φ(d)                         (prob. de superar el umbral)
      - expected_exceedance   = σ_j·φ(d) + diff·Φ(d) = E[max(±(m−τ), 0)]  (forma cerrada;
        "contraste anómalo esperado sobre el umbral", análogo al expected-improvement de
        optimización bayesiana — premia magnitud Y upside exploratorio)
      - lower_confidence_bound= diff − lcb_k·σ_j             (score PESIMISTA: penaliza la
        incertidumbre; un pico fuerte pero mal resuelto cae)

    `rank_by` elige la métrica de orden (default expected_exceedance). Luego aplica
    SUPRESIÓN DE NO-MÁXIMOS 3D: candidatos con exceedance_prob ≥ min_exceedance_prob,
    ordenados por el score, seleccionados codiciosamente excluyendo todo candidato a
    < exclusion_radius (m) de un blanco ya elegido → blancos ESPACIALMENTE DISTINTOS (no
    50 celdas del mismo cuerpo), hasta top_n.

    ALCANCE HONESTO: las probabilidades son del posterior LINEAL alrededor de la solución
    regularizada (misma caveat que Hutchinson/ensemble): NO capturan no-unicidad no-lineal
    ni error de modelo. Es un ranking DEFENDIBLE de TARGETING/ESTRUCTURA ("dónde perforar"),
    NO una probabilidad de mena/ley. Si no se pasa posterior_std se estima una σ
    homoscedástica del MAD del modelo (degradado; pasar la σ real es muy preferible).

    Returns
    -------
    list[dict] ordenada por rank (1 = mejor). Cada dict: rank, x, y, z, depth (=y),
    model_value, posterior_std, exceedance_prob, expected_exceedance,
    lower_confidence_bound, score (el de rank_by), model_value_band [m−σ, m+σ],
    threshold, sense.
    """
    from scipy.special import ndtr   # Φ, función de distribución normal estándar

    valid_rank = ("expected_exceedance", "exceedance_prob", "lower_confidence_bound")
    if rank_by not in valid_rank:
        raise ValueError(f"rank_by debe ser uno de {valid_rank}.")
    if sense not in ("positive", "negative"):
        raise ValueError("sense debe ser 'positive' o 'negative'.")

    model = np.asarray(model, dtype=np.float64).ravel()
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    z = np.asarray(z, dtype=np.float64).ravel()
    n = model.shape[0]
    if not (x.shape[0] == y.shape[0] == z.shape[0] == n):
        raise ValueError("model, x, y, z deben tener el mismo largo.")

    finite = np.isfinite(model) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not finite.any() or top_n <= 0:
        return []

    # ── σ por vóxel (real preferida; si falta, homoscedástica del MAD) ────────
    if posterior_std is not None:
        sigma = np.asarray(posterior_std, dtype=np.float64).ravel()
        if sigma.shape[0] != n:
            raise ValueError("posterior_std debe tener el mismo largo que model.")
    else:
        med0 = np.median(model[finite])
        mad0 = 1.4826 * np.median(np.abs(model[finite] - med0))
        sigma = np.full(n, max(mad0, 1e-12), dtype=np.float64)

    # ── Umbral robusto si no se da (mediana ± 2·spread según el sentido) ──────
    # spread = MAD robusto; si el modelo es disperso (muchos ceros → MAD≈0) cae a la
    # desviación estándar para no fijar el umbral EN el fondo (que dejaría todo el
    # fondo en exceedance_prob=0.5 y lo volvería candidato espurio).
    mvals = model[finite]
    med = np.median(mvals)
    mad = 1.4826 * np.median(np.abs(mvals - med))
    spread = mad if mad > 1e-12 else float(np.std(mvals))
    if threshold is None:
        threshold = (med + 2.0 * spread) if sense == "positive" else (med - 2.0 * spread)
    threshold = float(threshold)

    # ── Scores probabilísticos por vóxel ─────────────────────────────────────
    sgn = 1.0 if sense == "positive" else -1.0
    diff = sgn * (model - threshold)
    sig_safe = np.where((sigma > 0) & np.isfinite(sigma), sigma, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = diff / sig_safe
    Phi = ndtr(d)
    phi = np.exp(-0.5 * d * d) / np.sqrt(2.0 * np.pi)
    exceed_prob = Phi
    expected_exceed = sig_safe * phi + diff * Phi
    # σ=0 / NaN ⇒ posterior degenerado: probabilidad de paso y expected = max(diff,0).
    degenerate = ~np.isfinite(d)
    exceed_prob = np.where(degenerate, (diff > 0).astype(np.float64), exceed_prob)
    expected_exceed = np.where(degenerate, np.maximum(diff, 0.0), expected_exceed)
    sig_pen = np.where(np.isfinite(sig_safe), sig_safe, 0.0)
    lcb = diff - float(lcb_k) * sig_pen

    # Fuera de celdas finitas: probabilidad 0 (no candidatas).
    exceed_prob = np.where(finite, exceed_prob, 0.0)

    score_map = {
        "expected_exceedance": expected_exceed,
        "exceedance_prob": exceed_prob,
        "lower_confidence_bound": lcb,
    }
    score = score_map[rank_by]

    # ── Radio de exclusión automático = 2.5 × paso de malla ──────────────────
    if exclusion_radius is None:
        def _pitch_axis(c):
            u = np.unique(np.round(c, 6))
            if u.size < 2:
                return np.inf
            dd = np.diff(u)
            dd = dd[dd > 0]
            return float(dd.min()) if dd.size else np.inf
        pitch = min(_pitch_axis(x[finite]), _pitch_axis(y[finite]), _pitch_axis(z[finite]))
        if not np.isfinite(pitch):
            pitch = 1.0
        exclusion_radius = 2.5 * pitch
    exclusion_radius = float(exclusion_radius)

    # ── Candidatos + supresión de no-máximos 3D codiciosa ────────────────────
    cand = np.where(finite & (exceed_prob >= float(min_exceedance_prob)))[0]
    if cand.size == 0:
        return []
    order = cand[np.argsort(-score[cand], kind="stable")]

    chosen = []
    chosen_xyz = []
    r2 = exclusion_radius ** 2
    for idx in order:
        if len(chosen) >= top_n:
            break
        px, py, pz = x[idx], y[idx], z[idx]
        if all((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2 >= r2
               for (cx, cy, cz) in chosen_xyz):
            chosen.append(int(idx))
            chosen_xyz.append((px, py, pz))

    targets = []
    for rank, idx in enumerate(chosen, start=1):
        s = float(sigma[idx]) if np.isfinite(sigma[idx]) else None
        targets.append({
            "rank": rank,
            "x": float(x[idx]),
            "y": float(y[idx]),
            "z": float(z[idx]),
            "depth": float(y[idx]),
            "model_value": float(model[idx]),
            "posterior_std": s,
            "exceedance_prob": float(exceed_prob[idx]),
            "expected_exceedance": float(expected_exceed[idx]),
            "lower_confidence_bound": float(lcb[idx]),
            "score": float(score[idx]),
            "model_value_band": [
                float(model[idx] - sigma[idx]) if s is not None else None,
                float(model[idx] + sigma[idx]) if s is not None else None,
            ],
            "threshold": threshold,
            "sense": sense,
        })

    logger.info(
        f"[Targeting probabilístico] sense={sense} | rank_by={rank_by} | "
        f"umbral={threshold:.4g} | candidatos={cand.size} | blancos={len(targets)} | "
        f"r_excl={exclusion_radius:.4g} m"
    )
    return targets


class GravimetryForward:
    """
    FORWARD MODEL:
    Construye el kernel gravitacional como matriz dispersa CSR.

    Convención espacial:
    - x: eje horizontal
    - y: profundidad positiva hacia abajo
    - z: eje horizontal
    - densidad de entrada de la inversión: t/m3
    """

    def __init__(self, dx=10.0, dy=10.0, dz=10.0, cutoff_radius=800.0):
        self.dx = float(dx)
        self.dy = float(dy)
        self.dz = float(dz)
        self.voxel_volume = self.dx * self.dy * self.dz
        self.G = 6.67430e-11
        self.cutoff_radius = float(cutoff_radius)
        # T3.3 — Caché de G_active de UNA entrada (la última geometría).
        # El kernel depende SOLO de la geometría (coords activas, sensores, dx/dy/dz,
        # cutoff), NO de lambda/m_ref/ruido. Dentro de un run, solve/L-curve/DOI/UQ
        # reusan la misma geometría → se evita reconstruir el KDTree. La validación es
        # por np.array_equal (sin riesgo de colisión de hash) y el uso es read-only.
        self._kernel_cache = None  # (geom_key_tuple) | None
        self._kernel_cache_mat = None
        self.kernel_build_count = 0  # diagnóstico/test: nº de construcciones reales

    @staticmethod
    def _nagy_prism_safe(dx_vec, dy_vec, dz_vec, dx, dy, dz, G_const):
        """
        F0.2: Calcula g_y (componente vertical) exacto para prismas rectangulares (Nagy, 1966).

        Anti-singularity improvements:
        - eps ajustado a la escala del vóxel (1e-10 * min_dim) en vez de eps fijo.
        - Inyección eps en el radio: r = sqrt(x²+y²+z²+eps) — evita r=0 en sensor=centroide.
        - arctan2 OBLIGATORIO: arctan2(xz, yr+eps) — evita división por cero en y=0.
        - LOG SEGURO: log(maximum(arg, eps)) — evita log(0) en lugar de abs+eps.
        - dtype float64 obligatorio.
        """
        total_g = np.zeros_like(dx_vec, dtype=np.float64)
        # eps escala con la dimensión mínima del vóxel. np.minimum soporta tanto
        # dx/dy/dz escalares (ruta uniforme, resultado idéntico a min()) como
        # arrays por-celda (ruta TreeMesh con celdas de tamaño variable).
        eps = 1e-10 * np.minimum(np.minimum(dx, dy), dz)

        for i, sign_x in enumerate([-1, 1]):
            x = dx_vec + sign_x * (dx / 2.0)
            for j, sign_y in enumerate([-1, 1]):
                y = dy_vec + sign_y * (dy / 2.0)
                for k, sign_z in enumerate([-1, 1]):
                    z = dz_vec + sign_z * (dz / 2.0)

                    sign = (-1) ** (i + j + k)

                    # Anti-singularity: inyección eps en el radio
                    r = np.sqrt(x*x + y*y + z*z + eps)
                    # Log seguro: maximum en lugar de abs+eps
                    log_zr = np.log(np.maximum(z + r, eps))
                    log_xr = np.log(np.maximum(x + r, eps))
                    # arctan2 obligatorio: evita arctan(xz/yr) con yr→0
                    atan_term = np.arctan2(x * z, y * r + eps)

                    kernel = x * log_zr + z * log_xr - y * atan_term
                    total_g += sign * kernel

        # 1000.0: conversión densidad t/m³ → kg/m³
        return G_const * 1000.0 * total_g

    def _build_sparse_kernel(self, x_c_act, y_c_act, z_c_act, sensor_coords,
                             cell_dx=None, cell_dy=None, cell_dz=None):
        """
        F0.2 HPC: Construye G_active (n_obs × n_active) DIRECTAMENTE para las celdas activas.

        Arquitectura:
        - KDTree construido ÚNICAMENTE sobre los centros de vóxeles activos.
        - Campo cercano (r ≤ threshold = 4·a_eq): Nagy exacto (_nagy_prism_safe).
        - Campo lejano  (threshold < r ≤ cutoff_radius): Masa Puntual (vectorizado).
        - Vóxeles fuera del cutoff_radius: contribución = 0, no se almacenan.
        - Acumulación por CSR triplets (rows, cols, data) — cero fancy indexing global.
        - Retorna sp.csr_matrix shape=(n_obs, n_active) dtype=float64.

        SPRINT 3A — Celdas de tamaño variable (TreeMesh):
        Si se proveen cell_dx/cell_dy/cell_dz (arrays 1D de longitud n_active con la
        extensión física de CADA celda), el kernel usa el tamaño y volumen POR CELDA
        en lugar del escalar uniforme self.dx/dy/dz. Esta ruta es ADITIVA y opt-in:
        con cell_d* = None el comportamiento es byte-idéntico a la versión uniforme
        (incluida la caché de geometría). La ruta variable omite la caché.
        """
        x_c_act = np.asarray(x_c_act, dtype=np.float64)
        y_c_act = np.asarray(y_c_act, dtype=np.float64)
        z_c_act = np.asarray(z_c_act, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        # ── SPRINT 3A: ruta de celdas variables (TreeMesh) ───────────────────
        _variable = cell_dx is not None or cell_dy is not None or cell_dz is not None
        if _variable:
            return self._build_sparse_kernel_variable(
                x_c_act, y_c_act, z_c_act, sensor_coords,
                cell_dx, cell_dy, cell_dz,
            )

        # ── T3.3: caché de UNA entrada (geometría) — kernel independiente de
        # λ/m_ref/ruido. Validación por np.array_equal (sin colisión de hash).
        geom_key = (self.dx, self.dy, self.dz, self.cutoff_radius,
                    x_c_act.shape, sensor_coords.shape)
        if (
            self._kernel_cache_mat is not None
            and self._kernel_cache is not None
            and self._kernel_cache[0] == geom_key
            and np.array_equal(self._kernel_cache[1], x_c_act)
            and np.array_equal(self._kernel_cache[2], y_c_act)
            and np.array_equal(self._kernel_cache[3], z_c_act)
            and np.array_equal(self._kernel_cache[4], sensor_coords)
        ):
            logger.debug("[FORWARD HPC] Cache HIT: G_active reutilizado (misma geometría, sin KDTree).")
            return self._kernel_cache_mat

        n_active = len(x_c_act)
        n_obs = len(sensor_coords)

        a_eq = np.sqrt(self.dx**2 + self.dy**2 + self.dz**2)
        threshold = min(4.0 * a_eq, self.cutoff_radius)

        t_start = time.perf_counter()
        max_workers = max(1, (os.cpu_count() or 2) - 1)

        logger.debug(
            f"[FORWARD HPC] KDTree Híbrido + ThreadPool({max_workers}w). "
            f"n_active={n_active:,} | n_obs={n_obs:,} | "
            f"threshold={threshold:.1f}m | cutoff={self.cutoff_radius:.0f}m"
        )

        voxel_centers = np.column_stack([x_c_act, y_c_act, z_c_act])
        tree = cKDTree(voxel_centers)

        # Red de seguridad: estima la densidad del kernel ANTES de materializar las
        # listas de vecinos; aborta con error claro si no cabe en RAM (no es un tope
        # de vóxeles, depende del cutoff/geometría). Ver _guard_sparse_kernel_memory.
        _guard_sparse_kernel_memory(tree, sensor_coords, self.cutoff_radius, n_active, n_obs)

        # Bulk query: 2 calls for ALL sensors (vs 2×n_obs calls in the serial loop)
        t_q0 = time.perf_counter()
        near_lists   = tree.query_ball_point(sensor_coords, r=threshold)
        cutoff_lists = tree.query_ball_point(sensor_coords, r=self.cutoff_radius)
        t_q1 = time.perf_counter()

        # Capture read-only refs for workers — no shared mutable state
        _x, _y, _z  = x_c_act, y_c_act, z_c_act
        _dx, _dy, _dz, _G, _vol = self.dx, self.dy, self.dz, self.G, self.voxel_volume
        _nagy = self._nagy_prism_safe  # staticmethod — thread-safe, no GIL contention

        def _sensor_row(i):
            """Returns (rows_arr, cols_arr, data_arr) for sensor i — no shared writes."""
            sx, sy, sz = sensor_coords[i]
            near_idx   = np.asarray(near_lists[i],   dtype=np.int32)
            cutoff_idx = np.asarray(cutoff_lists[i], dtype=np.int32)
            far_idx    = np.setdiff1d(cutoff_idx, near_idx, assume_unique=True)

            r_parts, c_parts, d_parts = [], [], []

            if len(far_idx) > 0:
                dxv = _x[far_idx] - sx
                dyv = _y[far_idx] - sy
                dzv = _z[far_idx] - sz
                r3  = (dxv**2 + dyv**2 + dzv**2) ** 1.5
                r_parts.append(np.full(len(far_idx), i, dtype=np.int32))
                c_parts.append(far_idx)
                d_parts.append((_G * _vol * 1000.0 * dyv) / r3)

            if len(near_idx) > 0:
                dxv = _x[near_idx] - sx
                dyv = _y[near_idx] - sy
                dzv = _z[near_idx] - sz
                r_parts.append(np.full(len(near_idx), i, dtype=np.int32))
                c_parts.append(near_idx)
                d_parts.append(_nagy(dxv, dyv, dzv, _dx, _dy, _dz, _G))

            if not r_parts:
                return (
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.float64),
                )
            return (
                np.concatenate(r_parts),
                np.concatenate(c_parts),
                np.concatenate(d_parts),
            )

        t_k0 = time.perf_counter()
        rows_chunks: list = []
        cols_chunks: list = []
        data_chunks: list = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit in index order; collect in the same order — deterministic triplets
            futures = [executor.submit(_sensor_row, i) for i in range(n_obs)]
            for fut in futures:
                r, c, d = fut.result()
                rows_chunks.append(r)
                cols_chunks.append(c)
                data_chunks.append(d)

        t_k1 = time.perf_counter()

        rows_arr = np.concatenate(rows_chunks) if rows_chunks else np.empty(0, np.int32)
        cols_arr = np.concatenate(cols_chunks) if cols_chunks else np.empty(0, np.int32)
        data_arr = np.concatenate(data_chunks) if data_chunks else np.empty(0, np.float64)

        G_active = sp.csr_matrix(
            (data_arr, (rows_arr, cols_arr)),
            shape=(n_obs, n_active),
            dtype=np.float64,
        )

        t_end = time.perf_counter()
        fill_rate = G_active.nnz / max(1, n_obs * n_active)

        logger.debug(
            f"[FORWARD HPC] G_active CSR: NNZ={G_active.nnz:,} | Fill={fill_rate:.4%} | "
            f"Sensores={n_obs:,} | ActiveCells={n_active:,} | Workers={max_workers} | "
            f"t_total={t_end-t_start:.2f}s "
            f"(query={t_q1-t_q0:.3f}s, kernel={t_k1-t_k0:.3f}s)"
        )

        if G_active.nnz == 0:
            raise ValueError(
                "El kernel G_active quedó vacío. "
                "Revisa cutoff_radius, coordenadas de sensores y active_cells."
            )

        # ── T3.3: guardar en caché (copias de las coords como clave; matriz como
        # valor read-only). Reemplaza la entrada previa (caché de UNA geometría).
        self._kernel_cache = (
            geom_key, x_c_act.copy(), y_c_act.copy(), z_c_act.copy(), sensor_coords.copy(),
        )
        self._kernel_cache_mat = G_active
        self.kernel_build_count += 1

        return G_active

    def _build_sparse_kernel_variable(
        self, x_c_act, y_c_act, z_c_act, sensor_coords,
        cell_dx, cell_dy, cell_dz,
    ):
        """
        SPRINT 3A — Kernel gravitacional para celdas de tamaño VARIABLE (TreeMesh).

        Misma física que la ruta uniforme (Nagy 1966 campo cercano + masa puntual
        campo lejano) pero con tamaño y volumen POR CELDA. La frontera near/far se
        decide por celda con su propio a_eq: una celda es campo cercano si
            r ≤ 4·a_eq_celda,   a_eq_celda = sqrt(dx²+dy²+dz²).
        Para celdas uniformes esto reproduce exactamente el split de la ruta escalar
        (pixel-perfect): todas las celdas dentro de 4·a_eq → Nagy; el resto → masa
        puntual; idéntico conjunto y valores que _build_sparse_kernel uniforme.

        No usa la caché de geometría (la caché está validada solo para la ruta
        uniforme; en 3A la malla adaptativa no está en el lazo caliente de producción).
        """
        n_active = len(x_c_act)
        n_obs = len(sensor_coords)

        # ── Validación + broadcast de tamaños por celda ──────────────────────
        def _as_cell_array(v, name):
            if v is None:
                # Si solo se dieron algunos ejes, completar con el escalar uniforme.
                return np.full(n_active, getattr(self, name), dtype=np.float64)
            arr = np.asarray(v, dtype=np.float64)
            if arr.ndim == 0:
                arr = np.full(n_active, float(arr), dtype=np.float64)
            if arr.shape[0] != n_active:
                raise ValueError(
                    f"{name} debe tener longitud n_active={n_active}, got {arr.shape[0]}."
                )
            return arr

        cdx = _as_cell_array(cell_dx, "dx")
        cdy = _as_cell_array(cell_dy, "dy")
        cdz = _as_cell_array(cell_dz, "dz")
        if not (np.isfinite(cdx).all() and np.isfinite(cdy).all() and np.isfinite(cdz).all()):
            raise ValueError("cell_dx/cell_dy/cell_dz contienen NaN o Inf.")
        if (cdx <= 0).any() or (cdy <= 0).any() or (cdz <= 0).any():
            raise ValueError("cell_dx/cell_dy/cell_dz deben ser positivos.")

        cell_vol = cdx * cdy * cdz                         # (n_active,)
        a_eq_cell = np.sqrt(cdx**2 + cdy**2 + cdz**2)      # (n_active,)
        near_thr_cell = 4.0 * a_eq_cell                    # frontera near/far por celda

        t_start = time.perf_counter()
        max_workers = max(1, (os.cpu_count() or 2) - 1)

        logger.debug(
            f"[FORWARD HPC/TreeMesh] KDTree variable-cell + ThreadPool({max_workers}w). "
            f"n_active={n_active:,} | n_obs={n_obs:,} | "
            f"cell_size∈[{cdx.min():.1f},{cdx.max():.1f}]m | cutoff={self.cutoff_radius:.0f}m"
        )

        voxel_centers = np.column_stack([x_c_act, y_c_act, z_c_act])
        tree = cKDTree(voxel_centers)

        # Red de seguridad de memoria (idéntica a la ruta uniforme): aborta con error
        # claro si el kernel disperso TreeMesh excediera la RAM disponible.
        _guard_sparse_kernel_memory(tree, sensor_coords, self.cutoff_radius, n_active, n_obs)

        cutoff_lists = tree.query_ball_point(sensor_coords, r=self.cutoff_radius)

        _x, _y, _z = x_c_act, y_c_act, z_c_act
        _G = self.G
        _nagy = self._nagy_prism_safe

        def _sensor_row(i):
            sx, sy, sz = sensor_coords[i]
            idx = np.asarray(cutoff_lists[i], dtype=np.int64)
            if len(idx) == 0:
                return (
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.float64),
                )
            dxv = _x[idx] - sx
            dyv = _y[idx] - sy
            dzv = _z[idx] - sz
            r = np.sqrt(dxv**2 + dyv**2 + dzv**2)

            near = r <= near_thr_cell[idx]
            far = ~near

            r_parts, c_parts, d_parts = [], [], []
            if np.any(far):
                fidx = idx[far]
                r3 = (dxv[far]**2 + dyv[far]**2 + dzv[far]**2) ** 1.5
                r_parts.append(np.full(len(fidx), i, dtype=np.int32))
                c_parts.append(fidx.astype(np.int32))
                d_parts.append((_G * cell_vol[fidx] * 1000.0 * dyv[far]) / r3)
            if np.any(near):
                nidx = idx[near]
                r_parts.append(np.full(len(nidx), i, dtype=np.int32))
                c_parts.append(nidx.astype(np.int32))
                d_parts.append(_nagy(
                    dxv[near], dyv[near], dzv[near],
                    cdx[nidx], cdy[nidx], cdz[nidx], _G,
                ))
            return (
                np.concatenate(r_parts),
                np.concatenate(c_parts),
                np.concatenate(d_parts),
            )

        rows_chunks, cols_chunks, data_chunks = [], [], []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_sensor_row, i) for i in range(n_obs)]
            for fut in futures:
                r, c, d = fut.result()
                rows_chunks.append(r)
                cols_chunks.append(c)
                data_chunks.append(d)

        rows_arr = np.concatenate(rows_chunks) if rows_chunks else np.empty(0, np.int32)
        cols_arr = np.concatenate(cols_chunks) if cols_chunks else np.empty(0, np.int32)
        data_arr = np.concatenate(data_chunks) if data_chunks else np.empty(0, np.float64)

        G_active = sp.csr_matrix(
            (data_arr, (rows_arr, cols_arr)),
            shape=(n_obs, n_active),
            dtype=np.float64,
        )

        fill_rate = G_active.nnz / max(1, n_obs * n_active)
        logger.debug(
            f"[FORWARD HPC/TreeMesh] G_active CSR: NNZ={G_active.nnz:,} | "
            f"Fill={fill_rate:.4%} | t_total={time.perf_counter()-t_start:.2f}s"
        )

        if G_active.nnz == 0:
            raise ValueError(
                "El kernel G_active (TreeMesh) quedó vacío. "
                "Revisa cutoff_radius, sensores y centros de celda."
            )
        return G_active

    def build_kernel_from_treemesh(self, mesh, sensor_coords):
        """
        SPRINT 3A — API pública: construye el kernel gravitacional desde una TreeMesh.

        Extrae centros y tamaños por celda de la malla adaptativa y delega en la ruta
        de celdas variables. Retorna sp.csr_matrix shape=(n_sensors, mesh.n_cells).
        """
        centers = mesh.get_cell_centers()
        sizes = mesh.get_cell_sizes()
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
        if not np.isfinite(centers).all():
            raise ValueError("Los centros de celda de la TreeMesh contienen NaN o Inf.")
        if not np.isfinite(sensor_coords).all():
            raise ValueError("Las coordenadas de sensores contienen NaN o Inf.")
        return self._build_sparse_kernel_variable(
            centers[:, 0], centers[:, 1], centers[:, 2], sensor_coords,
            sizes[:, 0], sizes[:, 1], sizes[:, 2],
        )

    def build_sparse_kernel(self, x_vox, y_vox, z_vox, sensor_coords):
        """
        API pública (backward compatible). Trata TODOS los vóxeles como activos.
        Delega internamente a _build_sparse_kernel (F0.2 KDTree + CSR triplets).
        Retorna kernel shape=(n_sensors, n_voxels) — misma firma que versiones anteriores.
        """
        logger.debug(f"[FORWARD] Construyendo Kernel Disperso CSR. Cutoff: {self.cutoff_radius} m")

        x_vox = np.asarray(x_vox, dtype=np.float64)
        y_vox = np.asarray(y_vox, dtype=np.float64)
        z_vox = np.asarray(z_vox, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        if len(x_vox) == 0:
            raise ValueError("No hay vóxeles para construir el kernel.")
        if len(sensor_coords) == 0:
            raise ValueError("No hay sensores para construir el kernel.")
        if not np.isfinite(x_vox).all() or not np.isfinite(y_vox).all() or not np.isfinite(z_vox).all():
            raise ValueError("Las coordenadas de vóxeles contienen NaN o Inf.")
        if not np.isfinite(sensor_coords).all():
            raise ValueError("Las coordenadas de sensores contienen NaN o Inf.")

        # Delegar a _build_sparse_kernel (F0.2): todos los vóxeles son "activos" aquí
        kernel_sparse = self._build_sparse_kernel(x_vox, y_vox, z_vox, sensor_coords)

        n_sensors = len(sensor_coords)
        n_voxels = len(x_vox)
        fill_rate = kernel_sparse.nnz / max(1, n_sensors * n_voxels)

        logger.debug(
            f"[FORWARD] Kernel CSR creado. "
            f"Sensores: {n_sensors:,} | Vóxeles: {n_voxels:,} | "
            f"NNZ: {kernel_sparse.nnz:,} | Fill rate: {fill_rate:.4%}"
        )

        return kernel_sparse


# ═════════════════════════════════════════════════════════════════════════════
# FASE 8 — el solver partido
# ═════════════════════════════════════════════════════════════════════════════
# `solve_inversion_lsqr` medía 1.046 líneas, CC 124 y 38 argumentos. La auditoría
# lo llama «el más delicado» de la fase y pone la condición: extraer **sin tocar
# la aritmética**. Por eso los cuerpos de los helpers son las MISMAS líneas, no
# una reescritura: un refactor que reordene una multiplicación cambia el último
# bit, y aquí el criterio de aceptación es que no cambie ninguno.
#
# `_CfgLSQR` agrupa las perillas (lo que se pide) y `_EstadoLSQR` el estado
# intermedio (lo que se va construyendo). Es la separación que pedía el paso 3
# —«los mismos objetos de configuración del paso 2»— y lo que baja la firma de 38
# argumentos a un puñado por helper.


@dataclass
class _CfgLSQR:
    """Perillas de la corrida: fijas durante todo el solve."""
    lambda_mag: float
    alpha_spatial: float
    density_min: float
    density_max: float
    noise_floor: float
    noise_pct: float
    detect_outliers: bool
    padding_kappa: float
    anchor_kappa: float
    laplacian_relax_alpha: float
    anchor_mode: str
    auto_kappa: bool
    regularization_norm: str
    compact_eps: float
    compact_max_irls: int
    compact_tol: float
    prune_observable_domain: bool
    cut_cell_topography: bool
    cutcell_min_fraction: float
    # FASE 14 — peso del prior geológico implícito en el término de smallness.
    # 0.0 = apagado = byte-idéntico al comportamiento histórico.
    geo_prior_alpha: float = 0.0


@dataclass
class _EstadoLSQR:
    """Lo que cada etapa construye para la siguiente.

    Nombres SIN guion bajo inicial: dentro de los helpers se desempaquetan a los
    locales originales (`_padding_active`, `_n_dead`, …) para que el cuerpo
    copiado siga siendo el mismo texto.
    """
    # máscara activa
    topo_depth: object = None
    active_cells: object = None
    n_active: int = 0
    cell_fraction: object = None
    cut_cell: bool = False
    padding_active: object = None
    padding_active_full: object = None
    # kernel
    G_active: object = None
    n_sensors: int = 0
    y_c_active: object = None
    x_c_arr: object = None
    z_c_arr: object = None
    # anclajes y litología
    anchor_active: object = None
    anchor_contrast_active: object = None
    litho_lb_active: object = None
    litho_ub_active: object = None
    has_anchors: bool = False
    anchor_mode: str = "soft"
    hard_anchor: bool = False
    # poda del dominio observable
    obs_in_active: object = None
    n_dead: int = 0
    n_obs_domain: int = 0
    n_active_sol: int = 0
    n_dead_core_a: int = 0
    n_dead_pad_a: int = 0
    topo_sol: object = None
    # cadena de pesos
    sigma: object = None
    d_w: object = None
    G_scaled: object = None
    L_active: object = None
    L_scaled: object = None
    Ws: object = None
    mw: object = None
    lb_tilde: object = None
    ub_tilde: object = None
    normalized_sensitivity_active: object = None
    # sistema aumentado
    G_aug: object = None
    d_aug: object = None
    lambda_spatial: float = 0.0
    lambda_mag_eff: float = 0.0
    small_target: object = None
    reg_norm: str = "l2"
    # solución
    m_tilde: object = None
    acond: float = float("nan")
    cond_A_est: object = None
    lsqr_istop: object = None
    lsqr_iters: object = None
    compact_hist: object = None
    padding_kappa_used: float = 0.0
    anchor_kappa_used: float = 0.0
    eps_floor: float = 0.0
    # despacho REAL del solver (Fase 5: lo que pasó, no lo que se pidió)
    solver_path_usado: object = None
    bounded_usado: bool = False
    bounded_pedido: bool = False
    lsmr_usado: bool = False
    proyectado_usado: bool = False
    #: `solver_meta` del caller: el bucle IRLS escribe ahí el diagnóstico de FISTA
    solver_meta_ref: object = None


class GravimetryInversion:
    """
    INVERSE MODEL:
    Inversión gravimétrica con LSQR + regularización espacial tipo Tikhonov 3D.

    Convención de memoria:
    - TODO el backend usa order='F'
    - índice plano = ix + nx * iy + nx * ny * iz
    """

    def __init__(self, nx=100, ny=50, nz=100, block_size=10.0, base_density=2.6):
        self.nx = int(nx)
        self.ny = int(ny)
        self.nz = int(nz)
        self.dx = float(block_size)
        self.dy = float(block_size)
        self.dz = float(block_size)
        self.base_density = float(base_density)   # FASE 16: configurable desde params
        self.total_voxels = self.nx * self.ny * self.nz

        if self.nx <= 0 or self.ny <= 0 or self.nz <= 0:
            raise ValueError("nx, ny y nz deben ser mayores que 0.")

        if self.dx <= 0:
            raise ValueError("block_size debe ser mayor que 0.")

    @property
    def supports_nonuniform_mesh(self) -> bool:
        """FASE 17 VALIDATED — malla tensor no-uniforme soportada vía hx/hy/hz."""
        return True

    def _build_laplacian(self, hx=None, hy=None, hz=None):
        """
        Laplaciano 3D puro (sin depth weighting) como CSR. Orden F.

        Para grillas uniformes (hx=hy=hz=None): w_ij = 1 en cada arista.
        Para grillas no-uniformes (hx/hy/hz provistos): w_ij = 2 / (h_i + h_j),
        donde (h_i + h_j)/2 es la distancia real entre centros de celdas adyacentes.

        Equivalencia escalar: hx = [h0]*N → L_nu = (1/h0) * L_uniform (exacto).
        Con λ_nu = λ_u * h0 las inversiones son idénticas.

        Convención de signos (L = W − D):
          - off-diagonal L[i,j] = w_ij ≥ 0  (peso de la arista)
          - diagonal     L[i,i] = −∑_j w_ij  (negativa)
        Regularización ||λ L m||² = λ² m^T L² m es equivalente al Laplaciano
        estándar (D − W) porque L² = (−L_std)² = L_std².

        VALIDATED (FASE 17):
          ✅ Convergencia: L_nu → (1/h0) L_u cuando hx → h0 (error < 1e-10)
          ✅ Equivalencia de inversión con λ escalado (error < 1e-5)
          ✅ Propiedades M-matriz (simetría, suma filas ≈ 0, signos correctos)
          ✅ Fórmula por arista verificada: w_ij = 2/(h_i+h_j) exacto
          ✅ Anisotropía reflejada: pesos X ≠ Y cuando hx ≠ hy
          ✅ TreeMesh: Laplaciano octree converge en ≤20 iteraciones LSQR

        Referencias:
          - SimPEG discretize (Robin et al. 2020) — FVM tensor mesh
          - Li & Oldenburg 1998 — depth weighting
          - FASE 17: suite de validación completa (test_laplacian_*.py)
        """
        logger.info(
            "[INVERSIÓN] Construyendo Laplaciano 3D sin wrap-around. Orden F. "
            f"Malla {'no-uniforme (F0.9 Tensor Mesh)' if hx is not None else 'uniforme'}."
        )

        idx_grid = np.arange(self.total_voxels, dtype=np.int64).reshape(
            (self.nx, self.ny, self.nz),
            order="F"
        )

        row_parts  = []
        col_parts  = []
        data_parts = []

        def add_edges(a_idx, b_idx, weights):
            """Aristas bidireccionales con peso w_ij (simétrico)."""
            a = a_idx.ravel(order="F")
            b = b_idx.ravel(order="F")
            # F-order OBLIGATORIO: a y b se ravelan en F, los pesos deben
            # seguir el mismo orden para que w[k] corresponda a la arista k.
            w = weights.ravel(order="F")
            row_parts.append(a);  col_parts.append(b);  data_parts.append(w)
            row_parts.append(b);  col_parts.append(a);  data_parts.append(w)

        # ── X direction ──────────────────────────────────────────────────────
        if self.nx > 1:
            if hx is not None:
                # w_ij = 1 / dist_centros = 2 / (hx[i] + hx[i+1])
                wx_1d = 2.0 / (hx[:-1] + hx[1:])              # (nx-1,)
                wx = np.broadcast_to(
                    wx_1d[:, np.newaxis, np.newaxis],
                    (self.nx - 1, self.ny, self.nz)
                ).copy()
            else:
                wx = np.ones((self.nx - 1, self.ny, self.nz), dtype=np.float64)
            add_edges(idx_grid[:-1, :, :], idx_grid[1:, :, :], wx)

        # ── Y direction ──────────────────────────────────────────────────────
        if self.ny > 1:
            if hy is not None:
                wy_1d = 2.0 / (hy[:-1] + hy[1:])              # (ny-1,)
                wy = np.broadcast_to(
                    wy_1d[np.newaxis, :, np.newaxis],
                    (self.nx, self.ny - 1, self.nz)
                ).copy()
            else:
                wy = np.ones((self.nx, self.ny - 1, self.nz), dtype=np.float64)
            add_edges(idx_grid[:, :-1, :], idx_grid[:, 1:, :], wy)

        # ── Z direction ──────────────────────────────────────────────────────
        if self.nz > 1:
            if hz is not None:
                wz_1d = 2.0 / (hz[:-1] + hz[1:])              # (nz-1,)
                wz = np.broadcast_to(
                    wz_1d[np.newaxis, np.newaxis, :],
                    (self.nx, self.ny, self.nz - 1)
                ).copy()
            else:
                wz = np.ones((self.nx, self.ny, self.nz - 1), dtype=np.float64)
            add_edges(idx_grid[:, :, :-1], idx_grid[:, :, 1:], wz)

        if not row_parts:
            raise ValueError("No se pudo construir regularizador espacial: grilla demasiado pequeña.")

        rows = np.concatenate(row_parts)
        cols = np.concatenate(col_parts)
        data = np.concatenate(data_parts)

        off_diag = sp.coo_matrix(
            (data, (rows, cols)),
            shape=(self.total_voxels, self.total_voxels)
        )

        diag_data = -np.asarray(off_diag.sum(axis=1)).ravel()
        diag_mat  = sp.diags(diag_data, 0, dtype=np.float64)

        L = (off_diag + diag_mat).tocsr()
        logger.info(f"[INVERSIÓN] Laplaciano CSR creado. NNZ: {L.nnz:,}")
        return L

    def _build_spatial_regularizer(self, x_c=None, y_c=None, z_c=None):
        """
        Mantiene compatibilidad: Laplaciano uniforme + depth weighting sobre grilla completa.
        Si y_c es None (llamada sin args desde focusing.py), usa pesos uniformes
        — el módulo de focusing aplica su propio depth weighting vía _depth_weights().
        """
        L  = self._build_laplacian()     # siempre uniforme en esta ruta legado
        z0 = self.dy / 2.0
        if y_c is not None:
            # Ruta legado: la profundidad es y_c crudo (sin restar topografía ni recortar).
            w_reg = depth_row_weights(np.asarray(y_c, dtype=np.float64), z0, beta=2.0)
        else:
            w_reg = np.ones(self.total_voxels, dtype=np.float64)
        return sp.diags(w_reg) @ L

    def select_lambda_lcurve(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        n_trials: int = 20,
        lambda_min: float = 1e-4,
        lambda_max: float = 1e2,
        alpha_spatial: float = 1.0,
        noise_floor: float = 0.02,
        noise_pct: float = 0.02,
        topography_elevations=None,
        hx=None, hy=None, hz=None,
    ) -> dict:
        """
        FASE 11 — L-Curve: Selección Automática de lambda_mag.

        Ejecuta n_trials soluciones LSQR con lambdas logarítmicamente espaciados
        entre lambda_min y lambda_max.  Para cada lambda mide:
          - ||d - G*m||₂  (misfit / fidelidad a datos)
          - ||L*m||₂       (roughness / regularización)

        El "corner" de la L-curve es el lambda que maximiza la curvatura
        (aproximación discreta: punto más alejado de la línea que une los extremos).

        Parameters
        ----------
        g_observed : array-like  — datos de gravedad observados
        y_c        : array-like  — profundidades de centros de vóxeles
        forward_model : GravimetryForward
        sensor_coords : ndarray shape=(n_obs, 3)
        x_c, z_c   : coordenadas horizontales de vóxeles
        n_trials    : número de lambdas a probar (default 5)
        lambda_min  : límite inferior del barrido
        lambda_max  : límite superior del barrido
        alpha_spatial, noise_floor, noise_pct : igual que solve_inversion_lsqr

        Returns
        -------
        dict con claves:
            lambda_selected  : float — lambda óptimo elegido
            selection_method : str   — siempre "L-Curve"
            trials           : list  — [{lambda, misfit_norm, roughness_norm}, ...]
            summary          : str   — línea para incluir en el reporte del run
        """
        import scipy.sparse as _sp

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c        = np.asarray(y_c,        dtype=np.float64)

        # ── Máscara de celdas activas ─────────────────────────────────────────
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)

        voxel_top   = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active     = int(np.sum(active_cells))

        if n_active == 0:
            raise ValueError("[L-Curve] No hay celdas activas. Revisa topografía y grilla.")

        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)
        y_c_active = y_c[active_cells]

        # ── Construir G_active UNA sola vez ──────────────────────────────────
        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── Formal data weighting Wd — R-04: sigma adaptivo ──────────────────
        # Si el caller pasa valores distintos al default problemático, se respetan.
        sigma = resolve_sigma(g_observed, noise_floor, noise_pct, detect_outliers=False)
        Wd    = _sp.diags(1.0 / sigma)
        G_w   = Wd @ G_active
        d_w   = Wd @ g_observed

        # ── Column scaling Ws ─────────────────────────────────────────────────
        _mw       = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        col_norms = 1.0 / _mw.diag
        Ws        = _mw.W
        G_scaled  = G_w @ Ws

        # ── Laplaciano reducido a celdas activas ──────────────────────────────
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        L_scaled = L_active @ Ws

        n_sensors      = len(g_observed)
        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── FASE 7: el trial usa EL funcional que `solve_inversion_lsqr` resuelve ─
        # Aquí vivía el bloque «H3 (causa J)», que alineaba el trial a la smallness
        # `diag(lam·w_reg)·Ws` del solver *de entonces*. La Fase 4 la sustituyó por
        # identidad en m̃ y este escáner se quedó atrás — el mismo desfase medido en
        # `select_lambda_chi2_target` (ratio χ² de 23× a 12.700× según profundidad,
        # `scripts/validation/fase7_lambda_identity_probe.py`).
        #
        # Con la smallness ya en identidad, la parte fija del sistema pasa a incluir
        # datos y suavidad, y cada trial sólo apila `λ_eff·I` — con la calibración
        # N_CALIB=256 que el solver aplica y este escáner ignoraba.
        _N_CALIB_SCAN = 256
        _G_fixed = _sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        _d_fixed = np.concatenate([d_w, np.zeros(n_active, dtype=np.float64)])
        _eye_n   = _sp.identity(n_active, format="csr", dtype=np.float64)

        # ── Barrido logarítmico de lambdas ────────────────────────────────────
        lambdas = np.logspace(
            np.log10(lambda_min), np.log10(lambda_max), num=n_trials
        )

        logger.info(
            f"[L-CURVE] Barrido de {n_trials} lambdas: "
            f"{lambda_min:.2e} → {lambda_max:.2e}"
        )

        trials = []
        for lam in lambdas:
            _lam_eff = float(lam) * np.sqrt(float(n_active) / _N_CALIB_SCAN)
            G_aug = _sp.vstack([_G_fixed, _lam_eff * _eye_n]).tocsr()
            d_aug = np.concatenate([_d_fixed, np.zeros(n_active, dtype=np.float64)])

            res = lsqr(G_aug, d_aug, damp=0.0, iter_lim=150, show=False)
            m_tilde = res[0]
            m_phys  = Ws @ m_tilde

            # Misfit en espacio de datos originales
            g_pred       = G_active @ m_phys
            misfit_norm  = float(np.linalg.norm(g_observed - g_pred))

            # Roughness = seminorma del término que lam penaliza. Debe seguir al
            # funcional: la smallness es identidad en m̃, y m̃ = diag(‖col_j‖)·m, así
            # que en espacio físico el término penalizado es ‖col_j(W_d·G)‖·m_j — la
            # ponderación por sensibilidad que la Fase 4 midió. Antes se medía
            # ‖diag(w_reg)·m‖, coherente con un funcional que el solver ya no usa;
            # y antes de eso, ‖L·m‖, penalizada por un λ_spatial FIJO que el barrido
            # no varía. La esquina de la L-curve sólo significa algo si la seminorma
            # es la del parámetro que se está moviendo.
            roughness_norm = float(np.linalg.norm(col_norms * m_phys))

            logger.info(
                f"  lambda={lam:.2e} | misfit={misfit_norm:.4e} | roughness={roughness_norm:.4e}"
            )
            trials.append({
                "lambda":         float(lam),
                "misfit_norm":    misfit_norm,
                "roughness_norm": roughness_norm,
            })

        # ── Encontrar el "corner" de la L-curve ──────────────────────────────
        lm_arr = np.log10(np.array([t["misfit_norm"]    for t in trials]) + 1e-30)
        lr_arr = np.log10(np.array([t["roughness_norm"] for t in trials]) + 1e-30)

        def _perpendicular_corner(lm, lr):
            """Fallback: índice de máxima distancia perpendicular a la línea extremos."""
            p0 = np.array([lm[0],  lr[0]])
            p1 = np.array([lm[-1], lr[-1]])
            line_vec = p1 - p0
            line_len = np.linalg.norm(line_vec)
            if line_len < 1e-12:
                return len(lm) // 2
            distances = np.array([
                np.abs(np.cross(line_vec, np.array([lm[i], lr[i]]) - p0)) / line_len
                for i in range(len(lm))
            ])
            return int(np.argmax(distances))

        def _menger_corner(lm, lr):
            """
            Curvatura de Menger sobre tríos consecutivos en el plano log-log
            (Hansen 2010, método estándar para la esquina de la L-curve).

            Para tres puntos P_{i-1}, P_i, P_{i+1}:
                κ_i = 4·A / (|P_{i-1}P_i|·|P_iP_{i+1}|·|P_{i+1}P_{i-1}|)
            con A = área del triángulo. Es más robusta que la curvatura por
            diferencias finitas (np.gradient) cuando el espaciado en el eje de
            misfit es muy no-uniforme, caso en que la 2ª derivada discreta degenera.
            La esquina = punto interior de máxima κ.

            Los ejes se normalizan a [0,1] (la curvatura es sensible a la escala
            de cada eje) y se descartan tríos con algún lado despreciable: cuando
            el misfit apenas cambia, varios puntos quedan casi coincidentes y su
            κ es ruido numérico (denominador → 0). Esos tríos no representan una
            esquina real y deben ignorarse.
            """
            n = len(lm)
            if n < 3:
                return n // 2

            def _norm(v):
                v = np.asarray(v, dtype=np.float64)
                span = float(v.max() - v.min())
                return (v - v.min()) / span if span > 1e-30 else np.zeros_like(v)

            pts = np.column_stack([_norm(lm), _norm(lr)])
            min_seg = 1e-3   # lado mínimo (en ejes normalizados) para considerar un trío
            kappa = np.zeros(n, dtype=np.float64)
            for i in range(1, n - 1):
                a, b, c = pts[i - 1], pts[i], pts[i + 1]
                d_ab = np.linalg.norm(b - a)
                d_bc = np.linalg.norm(c - b)
                d_ca = np.linalg.norm(a - c)
                if min(d_ab, d_bc, d_ca) < min_seg:
                    continue
                denom = d_ab * d_bc * d_ca
                # 2·área con signo (producto cruz 2D); |·| = 2·A  ⇒  κ = 2|cross|/denom
                cross = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
                kappa[i] = 2.0 * abs(cross) / denom
            kappa = np.nan_to_num(kappa, nan=0.0, posinf=0.0, neginf=0.0)
            if not np.any(kappa > 0):
                return None
            return int(np.argmax(kappa))

        corner_idx = None
        if len(lr_arr) >= 3:
            try:
                corner_idx = _menger_corner(lm_arr, lr_arr)
                if corner_idx is not None:
                    logger.info(
                        f"L-curve selected lambda={trials[corner_idx]['lambda']:.6g} "
                        f"using Menger-curvature corner detection"
                    )
            except Exception as _exc:
                logger.info(f"L-curve Menger curvature failed ({_exc}); using fallback")
                corner_idx = None

        if corner_idx is None:
            corner_idx = _perpendicular_corner(lm_arr, lr_arr)
            logger.info(
                f"L-curve selected lambda={trials[corner_idx]['lambda']:.6g} "
                f"using perpendicular-distance fallback"
            )

        lambda_selected = trials[corner_idx]["lambda"]
        summary = (
            f"Lambda_mag: {lambda_selected:.2e} "
            f"(Seleccionado via L-Curve, {n_trials} pruebas, "
            f"rango {lambda_min:.0e}–{lambda_max:.0e})"
        )

        logger.info(f"[L-CURVE] Lambda óptimo: {lambda_selected:.2e} (índice {corner_idx}/{n_trials-1})")
        logger.info(f"[L-CURVE] {summary}")

        return {
            "lambda_selected":  lambda_selected,
            "selection_method": "L-Curve",
            "corner_index":     corner_idx,
            "n_trials":         n_trials,
            "trials":           trials,
            "summary":          summary,
        }

    def select_lambda_chi2_target(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        lambda_candidates=None,
        chi2_target: float = 1.0,
        cond_max: float = 1e12,
        alpha_spatial: float = 1.0,
        topography_elevations=None,
        hx=None, hy=None, hz=None,
        padding_mask=None,
        padding_kappa: float = 1e5,
        # ── FASE 7: el sigma dejó de estar cableado ──────────────────────────
        # El escáner llamaba a `_sigma_adaptive` sin pasar por los parámetros de
        # ruido, así que su chi² se calculaba con un sigma distinto del que usa el
        # solve — y chi² es literalmente `Σ(r/σ)²/n`. Los defaults son el centinela
        # histórico `(0.02, 0.02)`, de modo que quien no los pase obtiene el sigma
        # adaptativo de siempre; quien declare su ruido obtiene el mismo sigma que
        # el solver, que es la condición para que los dos chi² sean comparables.
        noise_floor: float = 0.02,
        noise_pct: float = 0.02,
        detect_outliers: bool = False,
    ) -> dict:
        """
        R-A2 — Selección de lambda por target chi² (post-auditoría).

        Escanea lambda_candidates y selecciona el lambda que minimice
        |log10(chi²_final) - log10(chi2_target)| sujeto a cond(A) < cond_max.

        Candidatos por defecto (rango post-auditoría):
            [1e-3, 5e-4, 1e-4, 5e-5, 1e-5, 5e-6, 1e-6]

        Equivalente a la búsqueda por Discrepancy Principle de Morozov, pero
        usando el estimador de cond(A) de LSQR para la restricción de estabilidad.
        """
        import scipy.sparse as _sp

        if lambda_candidates is None:
            lambda_candidates = [1e-3, 5e-4, 1e-4, 5e-5, 1e-5, 5e-6, 1e-6]

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c        = np.asarray(y_c,        dtype=np.float64)

        # ── Máscara de celdas activas ─────────────────────────────────────────
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
        voxel_top    = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active     = int(np.sum(active_cells))
        if n_active == 0:
            raise ValueError("[chi2-scan] No hay celdas activas.")

        n_sensors  = len(g_observed)
        x_c_arr    = np.asarray(x_c, dtype=np.float64)
        z_c_arr    = np.asarray(z_c, dtype=np.float64)
        y_c_active = y_c[active_cells]

        # ── Construir G_active UNA vez (se almacena en caché del forward) ─────
        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── R-05: Observable Domain (mismo filtro que solve_inversion_lsqr) ──
        _obs_in_active = observable_domain_mask(G_active)
        _n_obs_domain  = int(np.sum(_obs_in_active))
        _n_dead        = n_active - _n_obs_domain
        if _n_dead > 0:
            G_active    = G_active[:, _obs_in_active]
            y_c_active  = y_c_active[_obs_in_active]
            _topo_sol   = topo_depth[active_cells][_obs_in_active]
            _n_active_sol = _n_obs_domain
        else:
            _topo_sol     = topo_depth[active_cells]
            _n_active_sol = n_active

        # ── Data weighting — R-04 sigma adaptivo ─────────────────────────────
        sigma   = resolve_sigma(g_observed, noise_floor, noise_pct,
                                detect_outliers=detect_outliers)
        Wd      = _sp.diags(1.0 / sigma)
        G_w     = Wd @ G_active
        d_w     = Wd @ g_observed

        # ── Column scaling ────────────────────────────────────────────────────
        _mw       = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        col_norms = 1.0 / _mw.diag
        Ws        = _mw.W
        G_scaled  = G_w @ Ws

        # ── Laplaciano reducido a activas/observables ─────────────────────────
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        if _n_dead > 0:
            L_active = L_active.tocsr()[_obs_in_active, :][:, _obs_in_active]
        L_scaled     = L_active @ Ws

        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)
        G_aug = _sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        d_aug = np.concatenate([d_w, np.zeros(_n_active_sol, dtype=np.float64)])

        # ── Máscara de padding (para smallness diferencial) ───────────────────
        _padding_active = None
        if padding_mask is not None:
            _pm = np.asarray(padding_mask, dtype=bool)
            _padding_active = _pm[active_cells]
            if _n_dead > 0:
                _padding_active = _padding_active[_obs_in_active]

        logger.info(
            f"[chi2-scan] Escaneando {len(lambda_candidates)} lambdas | "
            f"chi²_target={chi2_target:.1f} | cond_max={cond_max:.0e}"
        )

        # ── FASE 7: el escáner escanea EL funcional que el solver resuelve ────
        # Aquí vivía el bloque «H3b (causa J)», que alineaba el trial a la smallness
        # `diag(lam·w_reg)·Ws` del solver *de entonces* y dejaba escrito que sin esa
        # alineación «el χ² del trial divergía ~700× del χ² real del solve».
        #
        # La Fase 4 quitó `w_reg` del solver —midió que ahí `Ws` cancelaba el peso—
        # y NADIE actualizó este escáner: el desajuste que ese comentario documenta
        # haber arreglado había vuelto, callado, por el mismo mecanismo.
        #
        # [MEDIDO, `scripts/validation/fase7_lambda_identity_probe.py`] antes de este
        # cambio, con cuerpo sintético y Morozov re-eligiendo λ en cada profundidad:
        #
        #     prof     χ² prometido   χ² real del solve      ratio
        #     150 m       2,084             48,53             23×
        #     350 m       0,444            128,5             289×
        #     550 m       0,0724           165,7           2.290×
        #     750 m       0,0161           204,5          12.700×
        #
        # y en 0 de 4 casos el λ elegido fue el que el solver real habría elegido.
        # El error CRECE con la profundidad, que es justo donde los dos funcionales
        # más difieren — el mecanismo que §9D.2 planteó como hipótesis no descartada.
        #
        # Ahora el trial arma exactamente los tres bloques de `solve_inversion_lsqr`:
        # datos `Wd·G·Ws`, suavidad `λ_sp·L·Ws` (sin `w_reg`) y smallness IDENTIDAD
        # en m̃ con `λ_eff = λ·√(n/256)` — incluida la calibración N_CALIB, que el
        # escáner tampoco aplicaba. `padding` conserva su peso absoluto `κ·λ_eff`.
        #
        # NOTA DE ALCANCE: producción NO usa este selector (lo rodea desde Tier 1 A2,
        # escaneando con el solver real). Esto arregla el INSTRUMENTO DE DIAGNÓSTICO,
        # que es lo que H-25 dejó abierto: un instrumento que mide con el operador
        # equivocado es una trampa, no un instrumento.
        _N_CALIB_SCAN = 256
        trials = []
        for lam in lambda_candidates:
            _lam_eff = float(lam) * np.sqrt(float(_n_active_sol) / _N_CALIB_SCAN)
            _w_sm = np.full(_n_active_sol, _lam_eff, dtype=np.float64)
            if _padding_active is not None:
                _w_sm = np.where(_padding_active, float(padding_kappa) * _lam_eff, _w_sm)
            _sb   = _sp.diags(_w_sm)
            A_sys = _sp.vstack([G_aug, _sb]).tocsr()
            b_sys = np.concatenate([d_aug, np.zeros(_n_active_sol, dtype=np.float64)])
            res   = lsqr(A_sys, b_sys, damp=0.0,
                         iter_lim=500, atol=1e-8, btol=1e-8, show=False)

            m_tilde = res[0]
            acond   = float(res[6])
            m_phys  = Ws @ m_tilde
            residual = g_observed - G_active @ m_phys
            phi_d    = float(np.sum((residual / sigma) ** 2))
            chi2     = phi_d / n_sensors

            log_err  = abs(np.log10(max(chi2, 1e-30)) - np.log10(max(chi2_target, 1e-30)))
            feasible = bool(acond < cond_max)
            status   = "OK" if feasible else "COND_FAIL"
            logger.info(
                f"  lambda={lam:.1e} | chi2={chi2:.4f} | cond(A)~{acond:.2e} | "
                f"|Dlog10(chi2)|={log_err:.4f} | {status}"
            )
            trials.append({
                "lambda":         float(lam),
                "chi2_final":     float(chi2),
                "cond_A":         float(acond),
                "log_chi2_error": float(log_err),
                "feasible":       feasible,
            })

        # ── Selección: minimizar |Δlog10(chi²)| entre lambdas factibles ───────
        feasible_trials = [t for t in trials if t["feasible"]]
        pool = feasible_trials if feasible_trials else trials
        if not feasible_trials:
            logger.info(f"[chi2-scan] WARN: Ningun lambda con cond(A) < {cond_max:.0e}. Usando menor Dlog10.")
        best = min(pool, key=lambda t: t["log_chi2_error"])

        logger.info(
            f"[chi2-scan] OK lambda_opt={best['lambda']:.2e} | "
            f"chi2={best['chi2_final']:.4f} | cond(A)~{best['cond_A']:.2e}"
        )
        return {
            "lambda_selected":  best["lambda"],
            "selection_method": "chi2_target",
            "chi2_target":      float(chi2_target),
            "chi2_achieved":    best["chi2_final"],
            "cond_A_achieved":  best["cond_A"],
            "cond_max":         float(cond_max),
            "feasible":         bool(best["feasible"]),
            "trials":           trials,
            "summary": (
                f"lambda={best['lambda']:.2e} | chi2={best['chi2_final']:.4f} | "
                f"cond(A)~{best['cond_A']:.2e} ({'OK' if best['feasible'] else 'COND_FAIL'})"
            ),
        }


    def _lsqr_mascara_activa(self, cfg: "_CfgLSQR", est: "_EstadoLSQR", y_c,
                             topography_elevations, kernel_sparse, sensor_coords,
                             padding_mask):
        """Topografía → celdas activas (binaria o cut-cell) y máscara de padding."""
        cut_cell_topography = cfg.cut_cell_topography
        cutcell_min_fraction = cfg.cutcell_min_fraction
        padding_kappa = cfg.padding_kappa

        # ── Máscara de celdas activas (topografía F0.8) ───────────────────────
        if topography_elevations is None:
            # Topografía plana en y=0: todas las celdas son subsuperficie
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
            if topo_depth.shape[0] != self.total_voxels:
                raise ValueError(
                    f"topography_elevations debe tener {self.total_voxels} elementos, "
                    f"got {topo_depth.shape[0]}."
                )

        # y positivo hacia abajo: TECHO del vóxel = y_center - dy/2
        # Activo (binario) = techo del vóxel a la misma profundidad o bajo la superficie.
        voxel_top = y_c - (self.dy / 2.0)
        _cut_cell = (
            bool(cut_cell_topography)
            and topography_elevations is not None
            and kernel_sparse is None
        )
        cell_fraction = None
        if _cut_cell:
            # FASE 24B Tarea 4: topografía fraccionaria (cut-cell, anti-staircase).
            # frac = porción del volumen de la celda que queda BAJO la superficie ∈[0,1].
            # Interior (frac=1) idéntico al caso binario; celdas de borde (0<frac<1)
            # entran como activas con peso parcial (antes eran 100% aire o 100% roca).
            voxel_bottom = y_c + (self.dy / 2.0)
            frac = np.clip((voxel_bottom - topo_depth) / float(self.dy), 0.0, 1.0)
            active_cells = frac > float(cutcell_min_fraction)
            cell_fraction = frac
        else:
            active_cells = voxel_top >= topo_depth
        n_active = int(np.sum(active_cells))
        n_air = self.total_voxels - n_active

        if n_active == 0:
            raise ValueError(
                "Ningún vóxel activo bajo la topografía dada. "
                "Revisa topography_elevations y la grilla."
            )

        # ── Fase 14: Sensores dentro de la malla (solo celdas activas) ──────────
        # sensor_coords[:, 1] es la profundidad Y del sensor (positiva hacia abajo).
        # Si y_sensor > (min_voxel_top + dy) el sensor está debajo del fondo de la
        # capa más superficial → está claramente dentro del dominio → error.
        # Umbral = top + dy (= fondo de la primera capa) para evitar falsos positivos
        # cuando los sensores están al mismo nivel que el centro de la primera celda.
        _sc_chk = np.asarray(sensor_coords, dtype=np.float64)
        if _sc_chk.ndim == 2 and _sc_chk.shape[1] >= 3 and n_active > 0:
            _sy = _sc_chk[:, 1]
            _min_active_top = float(np.min(voxel_top[active_cells]))
            _inside_thr = _min_active_top + float(self.dy)  # = fondo de primera capa
            _n_inside = int(np.sum(_sy > _inside_thr))
            if _n_inside > 0:
                raise ValueError(
                    f"{_n_inside} sensor(es) tienen coordenada Y "
                    f"({float(np.max(_sy[_sy > _inside_thr])):.1f} m) "
                    f"mayor que el fondo de la primera capa activa ({_inside_thr:.1f} m). "
                    "Los sensores deben estar en la superficie, sobre la malla."
                )

        logger.info(
            f"[INVERSIÓN F0.2] Active cells: {n_active:,} / {self.total_voxels:,} "
            f"({100.0 * n_active / self.total_voxels:.1f}% activo, "
            f"{n_air:,} celdas de aire enmascaradas)"
        )

        # ── R-02: Máscara de celdas de padding activas ───────────────────────
        _padding_active = None
        if padding_mask is not None:
            _pm = np.asarray(padding_mask, dtype=bool)
            if _pm.shape[0] != self.total_voxels:
                raise ValueError(
                    f"padding_mask debe tener longitud {self.total_voxels}, "
                    f"got {_pm.shape[0]}."
                )
            _padding_active = _pm[active_cells]   # shape=(n_active,)
            _n_pad_active  = int(np.sum(_padding_active))
            _n_core_active = n_active - _n_pad_active
            logger.info(
                f"[R-02] Penalización diferencial padding: "
                f"core={_n_core_active:,} | padding={_n_pad_active:,} | kappa={padding_kappa:.0e}"
            )

        est.topo_depth = topo_depth
        est.active_cells = active_cells
        est.n_active = n_active
        est.cell_fraction = cell_fraction
        est.cut_cell = _cut_cell
        est.padding_active = _padding_active

    def _lsqr_kernel_activo(self, est: "_EstadoLSQR", g_observed, y_c, x_c, z_c,
                            kernel_sparse, forward_model, sensor_coords):
        """G sobre celdas activas: kernel cacheado (joint) o construido con KDTree."""
        active_cells = est.active_cells
        cell_fraction = est.cell_fraction

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]

        # ── F0.2 HPC: G_active directamente sobre celdas activas ─────────────
        # KDTree construido SOLO sobre celdas activas — sin fancy indexing global
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)
        if kernel_sparse is not None:
            G_active = kernel_sparse
            # FASE 23: el kernel cacheado (único llamador: la inversión conjunta) vive en el
            # espacio de las celdas ACTIVAS. Se aceptaba sin mirar su forma, así que un
            # kernel de malla completa entrando en una corrida CON topografía habría
            # emparejado columna k con celda k equivocada — un modelo desplazado, no un
            # error. El motor magnético ya comprobaba esto (`override_kernel`); ahora los dos.
            if G_active.shape != (n_sensors, est.n_active):
                raise ValueError(
                    f"kernel_sparse con forma {G_active.shape} no coincide con "
                    f"(n_obs={n_sensors}, n_active={est.n_active}). El kernel cacheado debe "
                    "construirse sobre las celdas activas bajo la topografía."
                )
            logger.debug("[GRAV] Usando kernel cacheado (sin reconstrucción).")
        else:
            G_active = forward_model._build_sparse_kernel(
                x_c_arr[active_cells],
                y_c_active,
                z_c_arr[active_cells],
                np.asarray(sensor_coords, dtype=np.float64),
            )
            if cell_fraction is not None:
                # Cut-cell: cada columna del kernel se pondera por la fracción de
                # volumen rocoso de su celda (la celda aporta proporcional a su masa).
                _frac_active = cell_fraction[active_cells]
                G_active = (G_active @ sp.diags(_frac_active)).tocsr()
                _n_partial = int(np.sum((_frac_active > 0.0) & (_frac_active < 1.0)))
                logger.info(f"[FASE 24B T4] cut-cell activo: {_n_partial:,} celdas fraccionarias ponderadas.")

        est.n_sensors = n_sensors
        est.y_c_active = y_c_active
        est.x_c_arr = x_c_arr
        est.z_c_arr = z_c_arr
        est.G_active = G_active

    def _lsqr_mapear_intervalos(self, est: "_EstadoLSQR", y_c, boreholes,
                                lithology_bounds):
        """Sondajes → celdas ancladas; litología → box por unidad. Mismo mapeo."""
        active_cells = est.active_cells
        x_c_arr = est.x_c_arr
        z_c_arr = est.z_c_arr

        # ── FASE 8 (Q4): Mapeo de vóxeles anclados por sondaje (full → active) ─
        # Para cada intervalo se localiza la COLUMNA (x,z) cuyos centros caen dentro
        # de la huella del vóxel (tolerancia dx/2) y luego el SEGMENTO vertical cuyos
        # centros y_c ∈ [y_from, y_to]. Si el intervalo es más corto que dy (ningún
        # centro cae dentro), se selecciona el vóxel de la columna más cercano al punto
        # medio del intervalo (garantiza ≥1 vóxel anclado por intervalo válido).
        _anchor_active = None
        _anchor_contrast_active = None
        if boreholes is not None and len(boreholes) > 0:
            _bh = np.asarray(boreholes, dtype=np.float64)
            if _bh.ndim != 2 or _bh.shape[1] != 5:
                raise ValueError(
                    "boreholes debe tener shape (n,5): "
                    "[x_m, z_m, y_from_m, y_to_m, density_t_m3]."
                )
            _anchor_mask_full     = np.zeros(self.total_voxels, dtype=bool)
            _anchor_contrast_full = np.zeros(self.total_voxels, dtype=np.float64)
            for _seg, _val in map_intervals_to_cells(
                boreholes, x_c_arr, y_c, z_c_arr,
                total_voxels=self.total_voxels, tol_xz=self.dx / 2.0, n_cols=5,
                nombre="boreholes",
                mensaje_shape=("boreholes debe tener shape (n,5): "
                               "[x_m, z_m, y_from_m, y_to_m, density_t_m3]."),
            ):
                _anchor_mask_full[_seg] = True
                _anchor_contrast_full[_seg] = float(_val[0]) - self.base_density
            _anchor_active          = _anchor_mask_full[active_cells]
            _anchor_contrast_active = _anchor_contrast_full[active_cells]

        # ── FASE 2.3: mapear bounds litológicos por unidad a celdas ───────────
        # Espeja el mapeo de boreholes (misma tolerancia de columna + segmento
        # vertical + fallback al vóxel más cercano). NaN = celda sin restricción
        # litológica (usa el bound escalar global).
        _litho_lb_active = None
        _litho_ub_active = None
        if lithology_bounds is not None and len(lithology_bounds) > 0:
            _lba = np.asarray(lithology_bounds, dtype=np.float64)
            if _lba.ndim != 2 or _lba.shape[1] != 6:
                raise ValueError(
                    "lithology_bounds debe tener shape (n,6): "
                    "[x_m, z_m, y_from_m, y_to_m, dens_min, dens_max]."
                )
            _litho_lb_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
            _litho_ub_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
            for _seg, _val in map_intervals_to_cells(
                lithology_bounds, x_c_arr, y_c, z_c_arr,
                total_voxels=self.total_voxels, tol_xz=self.dx / 2.0, n_cols=6,
                nombre="lithology_bounds",
                mensaje_shape=("lithology_bounds debe tener shape (n,6): "
                               "[x_m, z_m, y_from_m, y_to_m, dens_min, dens_max]."),
            ):
                _pmin, _pmax = float(_val[0]), float(_val[1])
                if _pmax < _pmin:
                    _pmin, _pmax = _pmax, _pmin
                _litho_lb_full[_seg] = _pmin
                _litho_ub_full[_seg] = _pmax
            _litho_lb_active = _litho_lb_full[active_cells]
            _litho_ub_active = _litho_ub_full[active_cells]

        est.anchor_active = _anchor_active
        est.anchor_contrast_active = _anchor_contrast_active
        est.litho_lb_active = _litho_lb_active
        est.litho_ub_active = _litho_ub_active

    def _lsqr_podar_dominio(self, cfg: "_CfgLSQR", est: "_EstadoLSQR"):
        """R-05: fuera las celdas con sensibilidad cero para TODOS los sensores."""
        prune_observable_domain = cfg.prune_observable_domain
        G_active = est.G_active
        n_active = est.n_active
        y_c_active = est.y_c_active
        topo_depth = est.topo_depth
        active_cells = est.active_cells
        _padding_active = est.padding_active
        _anchor_active = est.anchor_active
        _anchor_contrast_active = est.anchor_contrast_active
        _litho_lb_active = est.litho_lb_active
        _litho_ub_active = est.litho_ub_active

        # ── Solver Sanity Check ───────────────────────────────────────────────
        if G_active.nnz == 0:
            raise ValueError(
                "Kernel vacío. Ningún vóxel activo tiene sensibilidad a los sensores. "
                "Revisa el Bounding Box o la Topografía."
            )

        # ── R-05: Observable Domain — excluir vóxeles con sensibilidad cero ──
        # Vóxeles más allá del cutoff_radius para TODOS los sensores tienen columnas
        # cero en G_active. Incluirlos produce plateau de chi² por mínima norma y
        # saturación espuria en density_min (confirmado auditoría R-05).
        _col_sens_r05  = np.asarray(G_active.power(2).sum(axis=0)).ravel()
        _sens_thr_r05  = 1e-6 * max(float(np.max(_col_sens_r05)), 1e-30)
        if prune_observable_domain:
            _obs_in_active = _col_sens_r05 > _sens_thr_r05    # (n_active,)
        else:
            # FASE 9C-1: poda desactivada (inversión conjunta). Toda celda activa se
            # considera observable, de modo que el modelo conserva el tamaño completo
            # de la malla activa y los bloques cross-gradient (sized a n_active) conforman.
            _obs_in_active = np.ones(n_active, dtype=bool)
        _dead_in_active = ~_obs_in_active
        _n_obs_domain   = int(np.sum(_obs_in_active))
        _n_dead         = n_active - _n_obs_domain

        # Preservar máscara de padding COMPLETA para diagnóstico de saturación post-solver
        _padding_active_full = _padding_active.copy() if _padding_active is not None else None
        if _n_dead > 0:
            # Conteo de muertos por zona (para solver_meta)
            if _padding_active is not None:
                _n_dead_core_a = int(np.sum(_dead_in_active & ~_padding_active))
                _n_dead_pad_a  = int(np.sum(_dead_in_active &  _padding_active))
            else:
                _n_dead_core_a = _n_dead
                _n_dead_pad_a  = 0
            logger.info(
                f"[R-05] Observable Domain: {_n_obs_domain:,}/{n_active:,} "
                f"({100.0*_n_obs_domain/n_active:.1f}%) | "
                f"Muertos (sens=0): {_n_dead:,} ({100.0*_n_dead/n_active:.1f}%) -> excluidos del solver"
            )
            G_active        = G_active[:, _obs_in_active]
            y_c_active      = y_c_active[_obs_in_active]
            _topo_sol       = topo_depth[active_cells][_obs_in_active]
            if _padding_active is not None:
                _padding_active = _padding_active[_obs_in_active]
            if _anchor_active is not None:
                _anchor_active          = _anchor_active[_obs_in_active]
                _anchor_contrast_active = _anchor_contrast_active[_obs_in_active]
            if _litho_lb_active is not None:
                _litho_lb_active = _litho_lb_active[_obs_in_active]
                _litho_ub_active = _litho_ub_active[_obs_in_active]
            _n_active_sol   = _n_obs_domain
        else:
            _n_dead_core_a  = 0
            _n_dead_pad_a   = 0
            _topo_sol       = topo_depth[active_cells]
            _n_active_sol   = n_active

        est.G_active = G_active
        est.y_c_active = y_c_active
        est.topo_sol = _topo_sol
        est.padding_active = _padding_active
        est.padding_active_full = _padding_active_full
        est.anchor_active = _anchor_active
        est.anchor_contrast_active = _anchor_contrast_active
        est.litho_lb_active = _litho_lb_active
        est.litho_ub_active = _litho_ub_active
        est.obs_in_active = _obs_in_active
        est.n_dead = _n_dead
        est.n_obs_domain = _n_obs_domain
        est.n_active_sol = _n_active_sol
        est.n_dead_core_a = _n_dead_core_a
        est.n_dead_pad_a = _n_dead_pad_a

    def _lsqr_cadena_de_pesos(self, cfg: "_CfgLSQR", est: "_EstadoLSQR", g_observed,
                              hx, hy, hz):
        """σ → W_d → peso de modelo → Laplaciano → bounds. La cadena que la Fase 4 midió."""
        noise_floor = cfg.noise_floor
        noise_pct = cfg.noise_pct
        detect_outliers = cfg.detect_outliers
        density_min = cfg.density_min
        density_max = cfg.density_max
        laplacian_relax_alpha = cfg.laplacian_relax_alpha
        G_active = est.G_active
        n_active = est.n_active
        active_cells = est.active_cells
        _n_dead = est.n_dead
        _obs_in_active = est.obs_in_active
        _has_anchors = est.has_anchors
        _n_active_sol = est.n_active_sol
        _anchor_active = est.anchor_active
        _litho_lb_active = est.litho_lb_active
        _litho_ub_active = est.litho_ub_active

        # ── Formal Data Weighting Wd — R-04: Sigma Adaptivo ─────────────────
        # noise_floor=0.02 en SI (m/s²) ≈ 2000 mGal >> señal típica (0.001–0.1 mGal).
        # Se reemplaza por sigma_i = max(0.02·|d_i|, 0.01·data_range) — invariante
        # de escala, basado en Li & Oldenburg 1998 / SimPEG noise_floor+relative_error.
        # FASE 18: detect_outliers activa MAD; solo en el path sentinel (adaptive).
        # Se respetan valores explícitos del caller (benchmark, L-curve) para backward compat.
        if noise_floor == 0.02 and noise_pct == 0.02:
            sigma, _is_outlier = _sigma_adaptive(g_observed, detect_outliers=detect_outliers)
            if detect_outliers and _is_outlier.any():
                logger.info(
                    f"[SIGMA] Detected {int(_is_outlier.sum())} outliers "
                    f"(MAD > 3σ). Downweighting by 10×"
                )
        else:
            sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
        Wd    = sp.diags(1.0 / sigma)
        G_w   = Wd @ G_active
        d_w   = Wd @ g_observed

        # ── Sensitivity DOI proxy (solo celdas observables) ─────────────────
        _sensitivity_obs = np.sqrt(G_w.power(2).sum(axis=0)).A1   # shape (_n_active_sol,)
        max_sens = float(np.max(_sensitivity_obs)) if len(_sensitivity_obs) > 0 else 0.0
        _norm_sens_obs = _sensitivity_obs / max_sens if max_sens > 0 else np.zeros_like(_sensitivity_obs)
        if _n_dead > 0:
            sensitivity_active = np.zeros(n_active, dtype=np.float64)
            sensitivity_active[_obs_in_active] = _sensitivity_obs
            normalized_sensitivity_active = np.zeros(n_active, dtype=np.float64)
            normalized_sensitivity_active[_obs_in_active] = _norm_sens_obs
        else:
            sensitivity_active = _sensitivity_obs
            normalized_sensitivity_active = _norm_sens_obs

        # ── Laplaciano no-uniforme reducido a celdas activas — F0.9 ──────────
        # Si hx/hy/hz provienen del tensor mesh, los pesos reales de arista
        # se propagan al Laplaciano, disipando correctamente en el padding.
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        if _n_dead > 0:
            L_active = L_active.tocsr()[_obs_in_active, :][:, _obs_in_active]

        # ── FASE 8: relajación local del Laplaciano en vóxeles anclados ───────
        # Escalar las FILAS de los vóxeles anclados por alpha (<1) reduce el
        # acoplamiento de suavidad que imponen sobre sus vecinos, mitigando halos /
        # bullseyes; el valor del sondaje queda fijado por el strong soft constraint
        # (smallness × kappa), no por el suavizado. row-scaling diagonal: diag(s)·L
        # conserva la estructura CSR y no altera cond(A) materialmente.
        if _has_anchors:
            _lap_row_scale = np.ones(_n_active_sol, dtype=np.float64)
            _lap_row_scale[_anchor_active] = float(laplacian_relax_alpha)
            L_active = (sp.diags(_lap_row_scale) @ L_active).tocsr()

        # ── Peso de modelo: ponderación por SENSIBILIDAD ─────────────────────────
        # Aquí vivía un bloque titulado "H-A0 Bug 1: W_z formal (Li & Oldenburg 1998)"
        # que decía implementar el depth weighting estándar con el parámetro
        # `depth_beta`. La FASE 4 (auditoría 06 §10, hallazgo H-1) midió que no lo
        # implementaba, y por qué. Esta es la demostración, en tres líneas:
        #
        #     Wz_inv   = diag((z+z0)^{+β/2})                     ← "depth weighting"
        #     Ws       = diag(1/‖col_j(G_w·Wz_inv)‖)             ← se calculaba DESPUÉS
        #              = diag(1/(w_j·‖col_j(G_w)‖))
        #     Wz_inv·Ws = diag(1/‖col_j(G_w)‖)                   ← w_j se cancela
        #
        # `Ws` se computaba sobre el kernel YA pesado por `Wz`, así que deshacía
        # exactamente lo que `Wz` acababa de hacer: la columna j del sistema quedaba en
        # g_j/‖g_j‖, sin rastro de β. También los bounds: (d−base)/w_j · w_j‖g_j‖.
        # Medido a precisión de máquina (1,7e-16) y luego E2E: mover β de 0 a 4 cambiaba
        # la solución 2,5e-04 con TRF y 5,2e-06 con LSQR+GPCG — es decir, un residuo de
        # PARADA TEMPRANA (depende del solver), no un efecto físico.
        #
        # LO QUE EL CÓDIGO APLICA DE VERDAD, y que este comentario ahora sí describe:
        # el bloque de smallness penaliza ‖m̃‖² con m̃ = diag(‖col_j(W_d·G)‖)·m, o sea
        #
        #     φ_smallness = λ_eff² · Σ_j ( ‖col_j(W_d·G)‖ · m_j )²
        #
        # una ponderación por SENSIBILIDAD. Medida sobre la malla del producto, esa
        # norma de columna resulta ser una ley de potencia limpia (desviación máx 5,3 %)
        # equivalente a un Li & Oldenburg de **β ≈ 2,63** — la misma familia que el
        # estándar industrial β=2, algo más agresiva. El problema que H-1 nombra no es
        # que el peso tenga mala forma: es que **no es ajustable y no está declarado**,
        # lo fija el kernel y no una decisión.
        #
        # `Ws` conserva además su papel algebraico legítimo: sin él λ=3.0 domina los
        # datos ~14 000× (magnitudes SI) y se pierde la calibración N_CALIB=256.
        # m̃ NO tiene interpretación física directa: m = Ws @ m̃.
        #
        # La Fase 4 midió la alternativa (separar `Ws` como precondicionador global y
        # meter `(z+z0)^{−β/2}` como peso explícito) en 576 inversiones con Morozov
        # re-eligiendo λ en cada brazo, y decidió NO cablearla — ver el registro de la
        # fase. Instrumento: scripts/validation/wz_separation_probe.py.
        # Invariante ejecutable: tests/test_fase4_depth_weighting.py.
        _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        _col_norms_wz = 1.0 / _mw.diag              # ‖col_j(W_d·G)‖, acotada a 1e-12
        Ws        = _mw.W                           # m = Ws @ m_tilde
        G_scaled  = G_w @ Ws
        L_scaled  = L_active @ Ws
        # Bounds: el box físico [density_min, density_max] llevado a m̃ con la MISMA
        # biyección que recupera la densidad (m̃_j = ‖col_j‖ · m_j). Es exacta.
        _lb_tilde = (float(density_min) - self.base_density) * _col_norms_wz
        _ub_tilde = (float(density_max) - self.base_density) * _col_norms_wz

        # ── FASE 2.3: override de bounds por unidad litológica (membership dura) ─
        # En las celdas con litología conocida, reemplaza el box escalar global por
        # el box [dens_min, dens_max] de su unidad, transformado al espacio m_tilde
        # con la MISMA transformación que el bound global. El solver con bounds
        # (TRF/FISTA proyectado) lo impone satisfaciendo KKT por celda.
        if _litho_lb_active is not None:
            _ml = np.isfinite(_litho_lb_active)
            if _ml.any():
                _cn_l = _col_norms_wz[_ml]
                _lb_tilde[_ml] = (_litho_lb_active[_ml] - self.base_density) * _cn_l
                _ub_tilde[_ml] = (_litho_ub_active[_ml] - self.base_density) * _cn_l
                logger.info(
                    f"[FASE 2.3] Bounds litológicos por unidad aplicados a "
                    f"{int(_ml.sum()):,} celda(s) (membership dura, KKT)."
                )

        est.sigma = sigma
        est.d_w = d_w
        est.normalized_sensitivity_active = normalized_sensitivity_active
        est.L_active = L_active
        est.mw = _mw
        est.Ws = Ws
        est.G_scaled = G_scaled
        est.L_scaled = L_scaled
        est.lb_tilde = _lb_tilde
        est.ub_tilde = _ub_tilde

    def _lsqr_ensamblar_sistema(self, cfg: "_CfgLSQR", est: "_EstadoLSQR", m_ref,
                                extra_reg_blocks, extra_reg_rhs):
        """G_aug / d_aug: datos + suavidad + bloques externos + anclaje duro."""
        alpha_spatial = cfg.alpha_spatial
        lambda_mag = cfg.lambda_mag
        regularization_norm = cfg.regularization_norm
        n_sensors = est.n_sensors
        n_active = est.n_active
        active_cells = est.active_cells
        _obs_in_active = est.obs_in_active
        _n_dead = est.n_dead
        _has_anchors = est.has_anchors
        _hard_anchor = est.hard_anchor
        _anchor_active = est.anchor_active
        _anchor_contrast_active = est.anchor_contrast_active
        _n_active_sol = est.n_active_sol
        L_active = est.L_active
        G_scaled = est.G_scaled
        L_scaled = est.L_scaled
        d_w = est.d_w
        _mw = est.mw
        Ws = est.Ws

        # ── Sistema augmentado ────────────────────────────────────────────────
        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── Modelo de referencia m_ref (Li & Oldenburg 1999) ──────────────────
        # L_scaled = L_active @ Ws; m = Ws @ m_tilde.
        # Residual de regularización: λ_spatial · L_active · (m − m_ref).
        # RHS de las filas de regularización: λ_spatial · L_active · m_ref.
        # m_ref is None → d_reg = 0 → idéntico al solver sin referencia.
        # m_ref_sol vive en espacio observable (densidad contraste).
        m_ref_sol = resolve_reference_model(
            m_ref, total_voxels=self.total_voxels, n_active=n_active,
            active_cells=active_cells, obs_in_active=_obs_in_active, n_dead=_n_dead)

        # FASE 8: inyectar anclajes de sondaje en la referencia (override por celda).
        #   m_ref[j] = densidad_sondaje - base_density  para los vóxeles anclados.
        # Esto desplaza el RHS de la regularización (suavidad) hacia el valor del
        # sondaje; el smallness con κ (abajo) lo fija con fuerza.
        if _has_anchors:
            if m_ref_sol is None:
                m_ref_sol = np.zeros(_n_active_sol, dtype=np.float64)
            else:
                m_ref_sol = m_ref_sol.copy()
            m_ref_sol[_anchor_active] = _anchor_contrast_active[_anchor_active]

        if m_ref_sol is None:
            d_reg = np.zeros(_n_active_sol, dtype=np.float64)
        else:
            d_reg = lambda_spatial * (L_active @ m_ref_sol)

        # ── FASE 14: el modelo de referencia también en el término de SMALLNESS ──
        # Por qué existe esta rama, medido y no supuesto (docs/06 §FASE 14):
        # el `m_ref` de arriba entra SÓLO en la suavidad, ‖L·(m − m_ref)‖², y `L` es
        # un Laplaciano de grafo, así que sólo actúa en la CURVATURA del contacto
        # mientras el smallness sigue tirando de cada celda hacia base_density — es
        # decir, contra el prior. Li & Oldenburg 1999, a quien cita el llamador, pone
        # `m_ref` en el smallness. Sobre el dique inclinado con anti-inverse-crime ×3
        # y semillas pareadas, la diferencia no es de matiz: por la suavidad el prior
        # EMPEORA la recuperación (PR-AUC 0/25 semillas); por el smallness la MEJORA
        # en las cuatro métricas y en todas las semillas, y su control con geología
        # FALSA pasa a ser el PEOR brazo de todos — que es la firma de una restricción
        # que de verdad transporta información geológica.
        #
        # Se añade como bloque ADITIVO —α‖m − m_ref‖² ENCIMA del smallness hacia 0—
        # porque es exactamente la forma que se midió, y por el canal que el motor ya
        # tiene para esto (el mismo que usan PGI y cross-gradient). `m_ref_sol` ya está
        # mapeado al espacio de solución por `resolve_reference_model`, así que no hay
        # que repetir la reducción activas/podadas.
        # alpha = 0 → no se apila nada → byte-idéntico al comportamiento histórico.
        _geo_alpha = float(getattr(cfg, "geo_prior_alpha", 0.0) or 0.0)
        if _geo_alpha > 0.0 and m_ref_sol is not None:
            _sqrt_a = float(np.sqrt(_geo_alpha))
            extra_reg_blocks = list(extra_reg_blocks or []) + [
                sp.eye(_n_active_sol, format="csr") * _sqrt_a
            ]
            extra_reg_rhs = list(extra_reg_rhs or []) + [
                _sqrt_a * np.asarray(m_ref_sol, dtype=np.float64)
            ]
            logger.info(
                f"[FASE 14] Prior geológico en smallness: alpha={_geo_alpha:.3g} "
                f"sobre {_n_active_sol} celdas de solución."
            )

        G_aug = sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        d_aug = np.concatenate([d_w, d_reg])

        # ── FASE 9C-1: inyección de regularización externa (cross-gradient) ───
        # Los bloques llegan en ESPACIO FÍSICO del modelo (m); el solver trabaja en
        # la variable escalada m_tilde con m = Ws·m_tilde, de modo que cada bloque B
        # se convierte vía B·Ws (igual que L_scaled = L_active·Ws). El RHS se apila tal
        # cual (vive en el espacio de residual del bloque). Joint v1.1: el caller
        # recorta B[:, obs_mask] antes de pasar → B.shape[1] = n_active_sol (post-poda).
        if extra_reg_blocks:
            G_aug, d_aug = inject_extra_reg_blocks(
                G_aug, d_aug, extra_reg_blocks, extra_reg_rhs, _mw,
                hint_mask="obs_mask_g")
            logger.info(f"[FASE 9C-1] Inyectados {len(extra_reg_blocks)} bloque(s) cross-gradient en G_aug.")

        # H-A0 Bug 2: lambda scaling con n_active (calibrado a N_CALIB=256).
        # La smallness es uniforme en m_tilde; solo se escala la magnitud.
        _N_CALIB = 256
        lambda_mag_eff = float(lambda_mag) * np.sqrt(float(_n_active_sol) / _N_CALIB)

        logger.info(
            f"[INVERSIÓN F0.2] Ejecutando LSQR. "
            f"lambda_mag={lambda_mag:.2e} | lambda_mag_eff={lambda_mag_eff:.2e} "
            f"| lambda_spatial={lambda_spatial:.2e}"
        )

        # ── Regularización compuesta ─────────────────────────────────────────
        #   φ_m = ‖ lambda_spatial · L_active · Ws · (m_tilde − m_ref_tilde) ‖²   (suavidad)
        #       + ‖ diag(lambda_mag_eff) · m_tilde ‖²   (smallness en espacio transformado)
        # La suavidad opera sobre el contraste FÍSICO (L_active·Ws·m̃ = L_active·m).
        # La smallness es identidad en m̃, que en espacio físico equivale a pesar por
        # ‖col_j(W_d·G)‖ — la ponderación por sensibilidad descrita arriba.
        # padding (R-02) y anclajes (FASE 8) usan RHS en espacio m_tilde.
        # RHS de smallness: 0 (core/padding → hacia base_density) excepto celdas
        # ancladas, que apuntan al contraste medido del sondaje. El residual de la
        # fila i es w_i·(contraste_i − target_i), por lo que d_small_i = w_i·target_i.
        _small_target = np.zeros(_n_active_sol, dtype=np.float64)
        if _has_anchors:
            # FASE 25B: el target de anclaje vive en CONTRASTE FÍSICO (t/m³), pero el
            # bloque smallness opera en m_tilde con  m = base_density + Ws·m_tilde.
            # Para que la densidad recuperada en la celda anclada sea
            #   base_density + contraste_medido
            # el target en m_tilde debe ser  contraste / diag(Ws)  usando el MISMO
            # Ws que mapea m_tilde→m. Es exactamente la misma transformación que los
            # bounds de arriba: bound_tilde = (densidad − base) · ‖col_j‖. Sin ella,
            # anclar m_tilde→contraste deja la densidad en base + diag·contraste ≈ base
            # — el bug medido E2E en Fase 25.
            # NOTA: NO se toca m_ref_sol: la suavidad opera como
            # L_active·(Ws·m_tilde − m_ref) = L_active·(m_phys − m_ref), por lo que
            # ahí el contraste físico es el espacio CORRECTO.
            _ws_diag = np.asarray(Ws.diagonal(), dtype=np.float64)
            # Protección contra división por cero: diag(Ws) = 1/‖col_j‖ es estrictamente
            # > 0 por construcción (‖col‖ está acotada a 1e-12), pero se blinda igual.
            _wz_safe = np.where(np.abs(_ws_diag) < 1e-12, 1e-12, _ws_diag)
            _small_target[_anchor_active] = (
                _anchor_contrast_active[_anchor_active] / _wz_safe[_anchor_active]
            )

        # ── FASE 2.1: Anclaje DURO (hard constraint por eliminación de variables) ─
        # En modo "hard" las celdas ancladas se FIJAN exactamente a su valor de
        # sondaje: el valor objetivo en m_tilde es _small_target (= contraste/diag(Ws),
        # de modo que Ws·m_tilde = contraste exacto). Se elimina la celda del sistema
        # moviendo su contribución G_aug[:,j]·target al RHS y anulando la columna j; tras
        # resolver se reinyecta el valor exacto. Sin error residual de smallness (~2% soft).
        if _hard_anchor:
            _anchor_idx = np.where(_anchor_active)[0]
            _t_fix = _small_target[_anchor_idx]
            d_aug = d_aug - np.asarray(G_aug[:, _anchor_idx] @ _t_fix).ravel()
            _keep_cols = sp.diags((~_anchor_active).astype(np.float64))
            G_aug = (G_aug @ _keep_cols).tocsr()
            logger.info(
                f"[FASE 2.1] Anclaje DURO: {_anchor_idx.size:,} celda(s) eliminada(s) "
                f"del sistema (valor exacto del sondaje, sin smallness soft)."
            )

        # ── FASE 24B Tarea 1: control de norma de regularización ──────────────
        # L2 → un único solve idéntico al motor histórico (n_irls=1, focus=None).
        # compact/mixed → bucle IRLS de minimum support sobre la smallness.
        _reg_norm = str(regularization_norm).lower()
        if _reg_norm not in ("l2", "compact", "mixed"):
            raise ValueError(
                f"regularization_norm inválido: {regularization_norm!r}. "
                f"Use 'L2', 'compact' o 'mixed'."
            )

        est.lambda_spatial = lambda_spatial
        est.G_aug = G_aug
        est.d_aug = d_aug
        est.lambda_mag_eff = lambda_mag_eff
        est.small_target = _small_target
        est.reg_norm = _reg_norm

    def _lsqr_despachar_solver(self, cfg: "_CfgLSQR", est: "_EstadoLSQR",
                               _G_aug_sm, _d_aug_sm, _flags, _irls_it,
                               _lsqr_istop, _lsqr_iters):
        """Elige y corre el solver: TRF/bounded, LSMR o LSQR+clip, y luego FISTA.

        Vive aparte porque es la única parte del bucle IRLS que decide ALGO: qué
        maquinaria resuelve. `_lsqr_istop`/`_lsqr_iters` entran y salen como
        parámetros —y no por el contenedor— porque en el original persisten entre
        iteraciones del IRLS: sólo la rama LSQR los escribe, y las otras conservan
        el valor anterior. Sembrarlos con `None` en cada vuelta habría cambiado el
        `lsqr_converged` que publica la corrida.
        """
        _USE_BC, _USE_LSMR, _LSMR_THRESH, _USE_PGD = _flags
        _n_active_sol = est.n_active_sol
        _reg_norm = est.reg_norm
        lambda_mag_eff = est.lambda_mag_eff
        _lb_tilde = est.lb_tilde
        _ub_tilde = est.ub_tilde
        solver_meta = est.solver_meta_ref
        _proyectado_usado = False

        # Benchmark empírico (2026-06-01): TRF+LSMR ~40s con NNZ≈213K y n_active≈14K;
        # LSQR <0.1s. Umbral 8000 (HITO 5): demo (~800), medium CSV (~5K) y DOI test
        # (~5K) usan TRF bounded; auto_grid (>8K) usa LSQR+clip como fallback.
        # Fase 10: LSMR para n_active > 50K (mejor convergencia en sistemas mal condicionados).
        _use_trf = _USE_BC and _n_active_sol <= 8_000
        _use_lsmr = (not _use_trf) and _USE_LSMR and (_n_active_sol > _LSMR_THRESH)
        if _use_trf:
            _solver_label = "TRF/bounded"
        elif _use_lsmr:
            _solver_label = f"LSMR (Fase10, n>{_LSMR_THRESH:,})"
        else:
            _solver_label = "LSQR+clip"
        # Fase 5 (H-11): recordar el despacho REAL para publicarlo abajo.
        # El reporte del servicio traía `bounded_solver_active` calculado con
        # `os.getenv("USE_BOUNDED_SOLVER")`, que es lo que se PIDIÓ. Medido con
        # 8.712 celdas activas y la variable sin tocar: el solver despachó
        # `LSQR+clip` y el reporte afirmaba `true`. Y no es un caso de borde —
        # el umbral son 8.000 celdas y el producto declara mallas de 30k-100k
        # vóxeles, así que en el régimen normal el campo estaba SIEMPRE mal.
        # `validation/runner.py` lo lee para caracterizar cada corrida: era
        # evidencia de validación contaminada.
        #
        # Se anota en LOCALES, no en `solver_meta` aquí: un `if solver_meta is
        # not None` en este punto añadía una rama a `solve_inversion_lsqr`, que
        # ya tiene CC=143 y es la función que la Fase 8 tiene que partir. El
        # bloque de más abajo ya está guardado; escribir allí cuesta cero ramas.
        # (El bucle IRLS corre siempre al menos una vez —`_n_irls = max(1, …)`—
        # así que estos nombres existen después, con el despacho de la última
        # iteración, que es el que produjo el modelo que se devuelve.)
        _solver_path_usado   = _solver_label
        _bounded_usado       = bool(_use_trf)
        _bounded_pedido      = bool(_USE_BC)
        _lsmr_usado          = bool(_use_lsmr)
        _proyectado_usado    = False   # FISTA corre después del solve; lo pone a True
        _norm_tag = f"norm={_reg_norm}" + (f"/irls{_irls_it}" if _reg_norm != "l2" else "")
        logger.info(
            f"[SOLVER] G_aug=({_G_aug_sm.shape[0]:,}×{_G_aug_sm.shape[1]:,}) "
            f"n_active_sol={_n_active_sol:,} NNZ={_G_aug_sm.nnz:,} "
            f"smallness=sensibilidad(||col_j||) lambda_eff={lambda_mag_eff:.2e} "
            f"{_norm_tag} -> {_solver_label}"
        )
        _t_solve = time.perf_counter()
        if _use_trf:
            from scipy.optimize import lsq_linear as _lsq_linear
            _bc = _lsq_linear(
                _G_aug_sm, _d_aug_sm,
                bounds=(_lb_tilde, _ub_tilde),
                method='trf', lsq_solver='lsmr', tol=1e-6, max_iter=300,
            )
            m_tilde = _bc.x
            _acond = float('nan')
            logger.info(f"[SOLVER] TRF finalizado en {time.perf_counter()-_t_solve:.1f}s.")
        else:
            # Fase 6 (H-2): aquí vivía el path `USE_SPARSE_DIRECT` (SuperLU sobre
            # ecuaciones normales, Sprint 5A). Llamaba a `solve_sparse_normal_equations`,
            # un símbolo que NO existe en el repositorio: con el flag en true la
            # inversión abortaba con NameError después de construir el kernel.
            # Se borró en vez de repararse: formar A^T A eleva cond(A) al cuadrado
            # (la "lección Sprint 5A" que el propio comentario de LSMR cita más abajo).
            if _use_lsmr:
                # Fase 10: LSMR para n_active > 50K.
                # Fong & Saunders (2011): residuo ||r|| monotónicamente decreciente,
                # mejor estabilidad numérica que LSQR para sistemas mal condicionados.
                # NO forma A^T A explícitamente (lección Sprint 5A).
                from exploration.solver_preconditioned import solve_inversion_lsmr as _lsmr_solve
                m_tilde, _acond = _lsmr_solve(
                    _G_aug_sm, _d_aug_sm, _lb_tilde, _ub_tilde,
                    maxiter=1000, tol=1e-8,
                )
                logger.info(
                    f"[SOLVER] LSMR (Fase 10) convergido en "
                    f"{time.perf_counter()-_t_solve:.1f}s. "
                    f"cond(A)~{_acond:.2e}"
                )
            else:
                result = lsqr(
                    _G_aug_sm, _d_aug_sm,
                    damp=0.0,
                    iter_lim=500, atol=1e-8, btol=1e-8, show=False,
                )
                m_tilde = np.clip(result[0], _lb_tilde, _ub_tilde)
                _acond = result[6]
                # FASE 7: `istop`/`itn` se tiraban. `istop=7` = se agoto el limite
                # de iteraciones, o sea una corrida que NO convergio; publicarlo es
                # la diferencia entre "el solver llego" y "el solver se rindio".
                _lsqr_istop, _lsqr_iters = int(result[1]), int(result[2])
                logger.info(
                    f"[SOLVER] LSQR convergido en {time.perf_counter()-_t_solve:.1f}s. "
                    f"cond(A)~{_acond:.2e}"
                )

            # ── Tier 1 A1: FISTA proyectado (bounds reales para n>8K) ─────
            # El clip post-hoc descarta masa fuera del box sin redistribuir
            # (misfit degradado ~35% en cuerpos compactos). FISTA parte del
            # clip como warm start → el objetivo solo puede mejorar; rollback
            # exacto con USE_PROJECTED_SOLVER=false.
            if _USE_PGD:
                from exploration.solver_preconditioned import solve_inversion_pgd_fista
                _t_pgd = time.perf_counter()
                m_tilde, _pgd_info = solve_inversion_pgd_fista(
                    _G_aug_sm, _d_aug_sm, _lb_tilde, _ub_tilde, x0=m_tilde,
                )
                logger.info(
                    f"[SOLVER] FISTA proyectado en {time.perf_counter()-_t_pgd:.1f}s "
                    f"(post-{'LSMR' if _use_lsmr else 'LSQR'}+warm-start)."
                )
                _proyectado_usado = True   # Fase 5: lo que PASÓ, no lo que se pidió
                if solver_meta is not None:
                    solver_meta["pgd"] = _pgd_info

        return (m_tilde, _acond, _lsqr_istop, _lsqr_iters, _solver_path_usado,
                _bounded_usado, _bounded_pedido, _lsmr_usado, _proyectado_usado)


    def _lsqr_resolver_irls(self, cfg: "_CfgLSQR", est: "_EstadoLSQR"):
        """Bucle IRLS + despacho del solver (TRF / LSMR / LSQR+clip → FISTA).

        Las closures `_mk_small` y `_assemble` se quedan CON el bucle a propósito:
        leen `_focus_w` del scope y el bucle lo reasigna en cada reponderación.
        Sacarlas obligaría a parametrizarlas — o sea, a reescribir el ensamblado,
        que es justo lo que esta fase no puede hacer.
        """
        padding_kappa = cfg.padding_kappa
        anchor_kappa = cfg.anchor_kappa
        auto_kappa = cfg.auto_kappa
        compact_eps = cfg.compact_eps
        compact_tol = cfg.compact_tol
        compact_max_irls = cfg.compact_max_irls
        lambda_mag = cfg.lambda_mag
        density_min = cfg.density_min
        density_max = cfg.density_max
        solver_meta = est.solver_meta_ref
        _n_active_sol = est.n_active_sol
        _padding_active = est.padding_active
        _has_anchors = est.has_anchors
        _hard_anchor = est.hard_anchor
        _anchor_active = est.anchor_active
        lambda_spatial = est.lambda_spatial
        lambda_mag_eff = est.lambda_mag_eff
        L_scaled = est.L_scaled
        G_aug = est.G_aug
        d_aug = est.d_aug
        _small_target = est.small_target
        _reg_norm = est.reg_norm
        _lb_tilde = est.lb_tilde
        _ub_tilde = est.ub_tilde
        Ws = est.Ws

        _n_irls = 1 if _reg_norm == "l2" else max(1, int(compact_max_irls))

        # Celdas "libres" del núcleo: el foco minimum-support se aplica SOLO aquí.
        # Padding (R-02) y anclajes (FASE 8) conservan su rol de restricción fuerte L2.
        _free_mask = np.ones(_n_active_sol, dtype=bool)
        if _padding_active is not None:
            _free_mask &= ~_padding_active
        if _has_anchors:
            _free_mask &= ~_anchor_active

        # Operador de suavidad para edge-focusing en modo "mixed".
        _smooth_op_mixed = (lambda_spatial * L_scaled).tocsr()

        _focus_w = None      # foco minimum-support (smallness); None ≡ L2
        _srw     = None      # peso edge-preserving de suavidad (solo "mixed")
        _eps     = None
        _eps_floor = max(float(compact_eps), 1e-3)

        def _mk_small(_pk, _ak):
            """Smallness en m_tilde: lambda_mag_eff con kappas y foco IRLS.
            Lee _focus_w del scope (se reasigna por iteración)."""
            w = np.full(_n_active_sol, lambda_mag_eff, dtype=np.float64)
            if _padding_active is not None:
                w = np.where(_padding_active, float(_pk) * lambda_mag_eff, w)
            if _has_anchors:
                # FASE 2.1: en modo hard la celda anclada ya fue eliminada (columna
                # nula); su smallness debe ser 0 (no penalizar un DOF inexistente).
                _aw = 0.0 if _hard_anchor else float(_ak) * lambda_mag_eff
                w = np.where(_anchor_active, _aw, w)
            if _focus_w is not None:
                w = np.where(_free_mask, w * _focus_w, w)
            return w

        def _assemble(_pk, _ak):
            """Ensambla (_G_aug_sm, _d_aug_sm) con smallness + (mixed) suavidad enfocada."""
            _ws = _mk_small(_pk, _ak)
            _stack = [G_aug, sp.diags(_ws)]
            _rhs   = [d_aug, _ws * _small_target]
            if _reg_norm == "mixed" and _srw is not None:
                # Edge-preserving (experimental): refuerza la suavidad donde el modelo
                # es plano y la relaja en los bordes. Factor 0.5 evita sobre-suavizar
                # (la suavidad base ya vive en G_aug). RHS = 0 (rugosidad → 0).
                _stack.append(0.5 * (sp.diags(_srw) @ _smooth_op_mixed))
                _rhs.append(np.zeros(_smooth_op_mixed.shape[0], dtype=np.float64))
            return sp.vstack(_stack).tocsr(), np.concatenate(_rhs), _ws

        # ── FASE 8, paso 4: la configuración se resuelve UNA VEZ, aquí arriba ──
        # Antes estos tres `from core.config import ...` vivían DENTRO del bucle
        # IRLS: se re-ejecutaban en cada reponderación y ataban el despacho del
        # solver a un import escondido a 700 líneas de la firma.
        #
        # No suben a nivel de MÓDULO, y no es olvido: `wz_separation_probe.py`,
        # `wz_beta_liveness_gravimetry.py`, `fase7_byte_identity.py`,
        # `tests/generate_validation_report.py` y `test_benchmark_checkerboard.py`
        # fijan estas perillas escribiendo el ATRIBUTO de `core.config` justo antes
        # de llamar (uno de ellos hasta lo documenta: «gravimetry lo importa dentro
        # del bucle»). Un import a nivel de módulo congelaría el valor en el
        # arranque y esas sondas medirían en silencio la configuración equivocada
        # — el mismo modo de fallo que la Fase 5 encontró en `bounded_solver_active`.
        # Leerlo una vez por llamada conserva ese contrato y saca el import del
        # interior del solver, que es lo que pedía la fase.
        from core.config import USE_BOUNDED_SOLVER as _USE_BC
        from core.config import USE_LSMR_LARGE as _USE_LSMR, LSMR_THRESHOLD_N_ACTIVE as _LSMR_THRESH
        from core.config import USE_PROJECTED_SOLVER as _USE_PGD

        # Diagnósticos de la última iteración (expuestos vía solver_meta).
        _padding_kappa_used = float(padding_kappa)
        _anchor_kappa_used  = float(anchor_kappa)
        cond_A_est          = None
        _lsqr_istop         = None
        _lsqr_iters         = None
        m_tilde             = None
        _acond              = float("nan")
        _compact_hist: list = []

        for _irls_it in range(_n_irls):
            _G_aug_sm, _d_aug_sm, _w_small = _assemble(padding_kappa, anchor_kappa)

            # ── FASE 16: Dynamic Kappa Adaptation ─────────────────────────────
            # Estima cond(A) por ratio max/min de normas-columna al cuadrado
            # (O(nnz), sin SVD). Si cond > 1e12 y auto_kappa=True, escala kappas.
            _padding_kappa_used = float(padding_kappa)
            _anchor_kappa_used  = float(anchor_kappa)
            cond_A_est          = None
            cond_A_est = estimate_cond_from_columns(_G_aug_sm)
            if auto_kappa and cond_A_est is not None and cond_A_est > 1e12:
                _scale = 1e12 / cond_A_est
                _padding_kappa_used = float(padding_kappa) * _scale
                _anchor_kappa_used  = float(anchor_kappa) * _scale
                logger.info(
                    f"[FASE 16] cond(A)~{cond_A_est:.2e} > 1e12: "
                    f"kappas escalados ×{_scale:.2e} "
                    f"(padding {padding_kappa:.0e}→{_padding_kappa_used:.2e}, "
                    f"anchor {anchor_kappa:.0e}→{_anchor_kappa_used:.2e})"
                )
                _G_aug_sm, _d_aug_sm, _w_small = _assemble(
                    _padding_kappa_used, _anchor_kappa_used
                )

            (m_tilde, _acond, _lsqr_istop, _lsqr_iters, _solver_path_usado,
             _bounded_usado, _bounded_pedido, _lsmr_usado,
             _proyectado_usado) = self._lsqr_despachar_solver(
                cfg, est, _G_aug_sm, _d_aug_sm,
                (_USE_BC, _USE_LSMR, _LSMR_THRESH, _USE_PGD), _irls_it,
                _lsqr_istop, _lsqr_iters)
            # FASE 2.1: reinyecta el valor EXACTO en las celdas de anclaje duro.
            # Sus columnas fueron eliminadas → el solver las dejó en 0; se restaura
            # m_tilde[j] = target para que Ws·m_tilde = contraste medido exacto
            # (también antes del reweighting IRLS, que lee Ws·m_tilde).
            if _hard_anchor:
                m_tilde[_anchor_active] = _small_target[_anchor_active]

            # ── Reponderación IRLS minimum-support (compact/mixed) ─────────────
            # Foco sobre el CONTRASTE FÍSICO c = Ws·m_tilde (t/m³). Peso
            # f_i = 1/sqrt(c_i² + ε²) normalizado a media 1 sobre celdas libres:
            # concentra la penalización donde c≈0 (vacía el fondo) y la relaja
            # donde hay cuerpo (lo deja crecer) → cuerpos compactos y nítidos.
            # La normalización media-1 conserva la magnitud global de la
            # regularización → no degrada el misfit, solo redistribuye el foco.
            # ε se enfría por iteración para endurecer progresivamente el foco.
            if _reg_norm == "l2":
                break
            _c = Ws @ m_tilde
            _c_free = np.abs(_c[_free_mask]) if _free_mask.any() else np.abs(_c)
            if _eps is None:
                _eps = initial_irls_eps(_c_free, _eps_floor)
            _fw_new = irls_focus_weights(_c, _free_mask, _eps)
            _delta = (
                float(np.linalg.norm(_fw_new - _focus_w) / max(np.linalg.norm(_fw_new), 1e-12))
                if _focus_w is not None else 1.0
            )
            _focus_w = _fw_new
            if _reg_norm == "mixed":
                _g = _smooth_op_mixed @ m_tilde
                _rraw = 1.0 / np.sqrt(_g ** 2 + _eps ** 2)
                _rden = float(np.mean(_rraw)) or 1.0
                _srw = np.clip(_rraw / (_rden if _rden > 1e-12 else 1.0), 0.05, 20.0)
            _compact_hist.append({"iter": _irls_it, "eps": float(_eps), "focus_delta": _delta})
            _eps = max(_eps * 0.7, _eps_floor)
            if _irls_it > 0 and _delta < float(compact_tol):
                break

        if _reg_norm != "l2":
            logger.info(
                f"[FASE 24B] norma '{_reg_norm}': {len(_compact_hist)} iter IRLS, "
                f"delta_focus_final={_compact_hist[-1]['focus_delta']:.2e} "
                f"eps_floor={_eps_floor:.3f}"
            )
        if np.isfinite(_acond) and _acond > 1e12:
            logger.info(
                f"[SOLVER] WARN cond(A)={_acond:.2e} > 1e12. "
                f"Revisar padding_kappa={padding_kappa:.0e}, anchor_kappa={anchor_kappa:.0e} "
                f"o lambda_mag={lambda_mag:.2e}."
            )

        est.m_tilde = m_tilde
        est.acond = _acond
        est.cond_A_est = cond_A_est
        est.lsqr_istop = _lsqr_istop
        est.lsqr_iters = _lsqr_iters
        est.compact_hist = _compact_hist
        est.padding_kappa_used = _padding_kappa_used
        est.anchor_kappa_used = _anchor_kappa_used
        est.eps_floor = _eps_floor
        est.solver_path_usado = _solver_path_usado
        est.bounded_usado = _bounded_usado
        est.bounded_pedido = _bounded_pedido
        est.lsmr_usado = _lsmr_usado
        est.proyectado_usado = _proyectado_usado

    def _lsqr_reconstruir_salida(self, cfg: "_CfgLSQR", est: "_EstadoLSQR",
                                 g_observed, solver_meta, sensor_coords):
        """De m̃ a densidad física: bounds, misfit, score, χ² y `solver_meta`."""
        lambda_mag = cfg.lambda_mag
        density_min = cfg.density_min
        density_max = cfg.density_max
        padding_kappa = cfg.padding_kappa
        anchor_kappa = cfg.anchor_kappa
        auto_kappa = cfg.auto_kappa
        laplacian_relax_alpha = cfg.laplacian_relax_alpha
        anchor_mode = cfg.anchor_mode
        active_cells = est.active_cells
        n_active = est.n_active
        _cut_cell = est.cut_cell
        _n_dead = est.n_dead
        _n_obs_domain = est.n_obs_domain
        _n_active_sol = est.n_active_sol
        _n_dead_core_a = est.n_dead_core_a
        _n_dead_pad_a = est.n_dead_pad_a
        _obs_in_active = est.obs_in_active
        _padding_active_full = est.padding_active_full
        _anchor_active = est.anchor_active
        _anchor_mode = est.anchor_mode
        _has_anchors = est.has_anchors
        _hard_anchor = est.hard_anchor
        _litho_lb_active = est.litho_lb_active
        G_active = est.G_active
        Ws = est.Ws
        _mw = est.mw
        m_tilde = est.m_tilde
        _acond = est.acond
        cond_A_est = est.cond_A_est
        _lsqr_istop = est.lsqr_istop
        _lsqr_iters = est.lsqr_iters
        _compact_hist = est.compact_hist
        _padding_kappa_used = est.padding_kappa_used
        _anchor_kappa_used = est.anchor_kappa_used
        _eps_floor = est.eps_floor
        _reg_norm = est.reg_norm
        lambda_mag_eff = est.lambda_mag_eff
        normalized_sensitivity_active = est.normalized_sensitivity_active
        sigma = est.sigma
        y_c_active = est.y_c_active
        _topo_sol = est.topo_sol
        _solver_path_usado = est.solver_path_usado
        _bounded_usado = est.bounded_usado
        _bounded_pedido = est.bounded_pedido
        _lsmr_usado = est.lsmr_usado
        _proyectado_usado = est.proyectado_usado

        density_contrast_active = Ws @ m_tilde

        if len(density_contrast_active) != _n_active_sol:
            raise RuntimeError("LSQR devolvió un vector de densidad activo con tamaño incorrecto.")
        if not np.isfinite(density_contrast_active).all():
            raise RuntimeError("LSQR devolvió densidades no finitas.")

        # R-05: expandir contraste desde espacio observable al espacio activo completo.
        # Vóxeles muertos reciben contraste=0 → density=base_density (no D_min por bound).
        if _n_dead > 0:
            _contrast_sol = density_contrast_active
            density_contrast_active = np.zeros(n_active, dtype=np.float64)
            density_contrast_active[_obs_in_active] = _contrast_sol

        # ── Reconstrucción física: NaN para celdas de aire ────────────────────
        # Bound petrofísico EXPLÍCITO [density_min, density_max]. Diagnóstico de
        # saturación: si una fracción alta de celdas toca el bound, el dato "quería"
        # salir del rango y la restricción está enmascarando contraste real → señal
        # de que el bound debe revisarse para el depósito en cuestión (no es silencioso).
        density_raw = self.base_density + density_contrast_active
        _sat_lower_active = density_raw < density_min
        _sat_upper_active = density_raw > density_max
        n_sat_lower = int(np.sum(_sat_lower_active))
        n_sat_upper = int(np.sum(_sat_upper_active))
        n_clipped = n_sat_lower + n_sat_upper
        clip_fraction = n_clipped / max(1, n_active)
        estimated_density_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        estimated_density_full[active_cells] = np.clip(density_raw, density_min, density_max)
        if clip_fraction > 0.0:
            logger.info(
                f"[INVERSION F0.2] Bound petrofisico [{density_min:.2f}, {density_max:.2f}] t/m3: "
                f"{n_clipped:,}/{n_active:,} saturadas (low={n_sat_lower} high={n_sat_upper}) "
                f"= {clip_fraction:.1%}."
                + (" WARN alta saturacion: revisar lambda/kappa." if clip_fraction > 0.10 else "")
            )

        normalized_sensitivity = np.full(self.total_voxels, np.nan, dtype=np.float64)
        normalized_sensitivity[active_cells] = normalized_sensitivity_active

        # ── Misfit (F0.2: G_active cubre solo celdas observables) ────────────
        # Usar [_obs_in_active] garantiza shapes consistentes cuando n_dead > 0:
        # G_active es (n_obs, _n_obs_domain); density_contrast_active es (n_active,).
        g_model = G_active @ density_contrast_active[_obs_in_active]
        residual_sensor = g_observed - g_model
        _voxel_err_obs = np.abs(G_active.T @ residual_sensor)   # shape (_n_obs_domain,)
        if _n_dead > 0:
            voxel_error_active = np.zeros(n_active, dtype=np.float64)
            voxel_error_active[_obs_in_active] = _voxel_err_obs
        else:
            voxel_error_active = _voxel_err_obs

        residual_error = float(np.linalg.norm(residual_sensor))
        observed_norm = float(np.linalg.norm(g_observed))
        if observed_norm <= 0 or not np.isfinite(observed_norm):
            # Datos degenerados (vacíos o planos): reportar NaN en vez de fingir ajuste perfecto.
            misfit_percent = float("nan")
        else:
            misfit_percent = float((residual_error / observed_norm) * 100.0)

        # ── Score relativo de objetivo por vóxel (solo celdas activas) ────────
        # ADVERTENCIA: esto NO es una probabilidad estadística. Es un score de
        # ranking normalizado [0,1] derivado del residual proyectado al modelo:
        #     score_j = 1 − |Gᵀ·residual|_j / max_j |Gᵀ·residual|
        # Mide cuán bien explicado queda cada vóxel por el ajuste, relativo al peor
        # vóxel; sirve para ordenar objetivos, no para afirmar confianza estadística.
        # La incertidumbre estadística real (posterior) es el upgrade de la Fase 3
        # (estimador de Hutchinson). El segundo elemento del retorno se mapea en la
        # capa de servicio tanto a `relative_target_score` (canónico) como a
        # `probability` (clave legada, conservada por compatibilidad de front-end).
        max_voxel_error = float(np.max(voxel_error_active)) if n_active > 0 else 0.0

        relative_score_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        if max_voxel_error <= 0 or not np.isfinite(max_voxel_error):
            # Datos degenerados: NaN en vez de score=1.0 que finge calidad máxima.
            relative_score_full[active_cells] = np.nan
        else:
            relative_active = 1.0 - (voxel_error_active / max_voxel_error)
            relative_score_full[active_cells] = np.clip(relative_active, 0.0, 1.0)

        # ── chi² reducido final ────────────────────────────────────────────────
        # Reusa sigma ya computado (con outlier detection si aplica).
        _phi_d = float(np.sum((residual_sensor / sigma) ** 2))
        _chi2_final = _phi_d / max(len(g_observed), 1)

        logger.info(
            f"[INVERSION F0.2] Convergencia alcanzada. "
            f"Error residual L2: {residual_error:.4e} | Misfit: {misfit_percent:.2f}% | "
            f"chi2_final={_chi2_final:.4f} | cond(A)~{_acond:.2e}"
        )

        # ── Exponer diagnósticos numéricos al caller vía solver_meta ──────────
        if solver_meta is not None:
            solver_meta["acond"]         = float(_acond)
            solver_meta["chi2_final"]    = float(_chi2_final)
            # Fase 5 (H-11): qué solver corrió DE VERDAD, frente a cuál se pidió.
            solver_meta["solver_path"]               = _solver_path_usado
            solver_meta["bounded_solver_used"]       = _bounded_usado
            solver_meta["bounded_solver_requested"]  = _bounded_pedido
            solver_meta["lsmr_used"]                 = _lsmr_usado
            solver_meta["projected_solver_used"]     = _proyectado_usado
            # FASE 24B: norma de regularización usada + diagnóstico IRLS compacto
            # ── FASE 7, criterio (d): la corrida DECLARA su funcional ─────────
            # Aquí la smallness es SIEMPRE identidad en `m̃` (`sp.diags(_ws)`, sin
            # `Ws`), así que el peso de modelo entra en el funcional: la corrida
            # penaliza ‖col_j(W_d·G)‖·m_j — ponderación por SENSIBILIDAD, no un
            # depth weighting ajustable (H-1, medido en la Fase 4). La declaración
            # incluye a qué Li & Oldenburg equivale ESA malla (la Fase 4 midió
            # β≈2,63 una vez, a mano; ahora lo mide cada corrida sobre su propia
            # geometría y publica también cuán limpia es la ley de potencia).
            solver_meta["regularization_functional"] = declare_functional(
                _mw,
                smallness=SMALLNESS_IDENTITY_IN_TILDE,
                depths=y_c_active - _topo_sol,
                depth_beta_solicitado=None,
                smoothness_row_weight=False,
                lsqr_istop=_lsqr_istop, lsqr_iters=_lsqr_iters,
            )
            solver_meta["lsqr_istop"] = _lsqr_istop
            solver_meta["lsqr_iters"] = _lsqr_iters
            solver_meta["lsqr_converged"] = (
                None if _lsqr_istop is None else int(_lsqr_istop) not in (3, 7)
            )
            solver_meta["regularization_norm"] = _reg_norm
            solver_meta["compact_irls_iters"]  = len(_compact_hist)
            solver_meta["compact_eps_floor"]   = float(_eps_floor) if _reg_norm != "l2" else None
            solver_meta["cut_cell_topography"] = bool(_cut_cell)
            solver_meta["n_sat_lower"]   = n_sat_lower
            solver_meta["n_sat_upper"]   = n_sat_upper
            solver_meta["n_sat_total"]   = n_clipped
            solver_meta["n_active"]      = n_active
            solver_meta["sat_fraction"]  = float(clip_fraction)
            solver_meta["density_min"]   = float(density_min)
            solver_meta["density_max"]   = float(density_max)
            # R-05: campos de dominio observable (para diagnóstico en el servicio)
            solver_meta["n_dead_voxels"]      = _n_dead
            solver_meta["n_dead_core_active"] = _n_dead_core_a
            solver_meta["n_dead_pad_active"]  = _n_dead_pad_a
            solver_meta["n_observable"]       = _n_obs_domain
            solver_meta["observable_ratio"]   = round(float(_n_obs_domain) / max(n_active, 1), 4)
            # Si padding_mask está activo, desglosar saturación por core/padding
            # Usa _padding_active_full (n_active) en lugar de _padding_active (n_active_sol)
            if _padding_active_full is not None:
                solver_meta["n_sat_lower_core"] = int(np.sum(_sat_lower_active & ~_padding_active_full))
                solver_meta["n_sat_lower_pad"]  = int(np.sum(_sat_lower_active & _padding_active_full))
                solver_meta["n_sat_upper_core"] = int(np.sum(_sat_upper_active & ~_padding_active_full))
                solver_meta["n_sat_upper_pad"]  = int(np.sum(_sat_upper_active & _padding_active_full))
            # FASE 8: anclajes de sondaje aplicados
            solver_meta["n_anchored_voxels"]    = int(np.sum(_anchor_active)) if _anchor_active is not None else 0
            solver_meta["anchor_mode"]          = _anchor_mode if _has_anchors else None
            solver_meta["anchor_kappa"]         = float(anchor_kappa) if (_has_anchors and not _hard_anchor) else None
            solver_meta["laplacian_relax_alpha"] = float(laplacian_relax_alpha) if _has_anchors else None
            solver_meta["n_lithology_bounded"]  = (
                int(np.sum(np.isfinite(_litho_lb_active))) if _litho_lb_active is not None else 0
            )
            solver_meta["lambda_effective"]      = float(lambda_mag_eff)
            # FASE 16: diagnósticos de kappa adaptation
            solver_meta["cond_a_estimated"]     = float(cond_A_est) if cond_A_est is not None else None
            solver_meta["padding_kappa_used"]   = _padding_kappa_used
            solver_meta["anchor_kappa_used"]    = _anchor_kappa_used
            solver_meta["auto_kappa_adjusted"]  = (
                auto_kappa
                and cond_A_est is not None
                and cond_A_est > 1e12
            )
            # H-C1: datos observed vs calculated para persistir en obs_vs_calc.parquet
            solver_meta["d_obs"]          = g_observed
            solver_meta["d_pred"]         = g_model
            solver_meta["residuals"]      = residual_sensor
            solver_meta["rmse"]           = float(np.sqrt(np.mean(residual_sensor ** 2)))
            solver_meta["station_coords"] = sensor_coords  # (n_sensors, 3) or None

        return estimated_density_full, relative_score_full, misfit_percent, normalized_sensitivity

    def solve_inversion_lsqr(
        self,
        g_observed,
        kernel_sparse,          # Caché del kernel disperso (joint mode). Si no-None: se usa como G_active.
        y_c,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        sensor_coords=None,
        x_c=None,
        z_c=None,
        forward_model=None,
        # ── F0.9: Formal Data Weighting ──────────────────────────────────────
        noise_floor=0.02,       # Nivel de ruido absoluto (mismas unidades que g_observed)
        noise_pct=0.02,         # Fracción porcentual del ruido: 2% de |d_obs|
        # ── F0.9: Tensor Mesh — Laplaciano No-Uniforme ───────────────────────
        hx=None,                # Anchos 1D de celda en X (core + padding)
        hy=None,                # Anchos 1D de celda en Y
        hz=None,                # Anchos 1D de celda en Z
        # ── DOI: Modelo de Referencia (Li & Oldenburg 1999) ──────────────────
        m_ref: Optional[np.ndarray] = None,
        # ── FASE 14: peso del prior geológico implícito en el SMALLNESS ──────
        # m_ref entra siempre en la suavidad; con geo_prior_alpha > 0 entra ADEMÁS
        # como α‖m − m_ref‖². MEDIDO: por la suavidad sola el prior geológico
        # empeora la recuperación; con este término la mejora. Ver docs/06 §FASE 14
        # y scripts/validation/f14_implicit_geology_experiment.py.
        # 0.0 → no se apila nada → byte-idéntico. El DOI SÍ tiene que pasarlo: su
        # inversión 1 es la corrida principal, y si la 2 cambiara de funcional el
        # índice mediría dos cosas a la vez.
        geo_prior_alpha: float = 0.0,
        # ── Bound petrofísico EXPLÍCITO sobre la densidad recuperada (t/m³) ───
        # H-A0 Bug 3: density_max subido a 5.5 para cubrir magnetita (5.0-5.2),
        # cromita (4.5-4.8) y pirita masiva (4.5-5.0) — minerales objetivo en Chile.
        density_min: float = 2.6,
        density_max: float = 5.5,
        # ── R-02: Penalización diferencial de celdas de padding ──────────────
        # padding_mask: array bool (total_voxels,); True = celda de padding.
        # κ = 10^5 penaliza la smallness del padding 10^5 veces más que el core,
        # sin eliminar el grado de libertad (soft constraint). Ver auditoría R-A1.
        padding_mask: Optional[np.ndarray] = None,
        padding_kappa: float = 1e5,
        # ── FASE 8 (Q4): Anclaje por sondajes (boreholes) ────────────────────
        # boreholes: array (n,5) [x_m, z_m, y_from_m, y_to_m, density_t_m3] o None.
        # Soporta SOLO pozos verticales por ahora (intervalo en Y a (x,z) constante);
        # la arquitectura (mapeo por columna + segmento vertical) admite extensión
        # futura a polilíneas 3D. Para cada intervalo se ancla la densidad medida vía
        # strong soft constraint (smallness × anchor_kappa) + relajación local del
        # Laplaciano (filas × laplacian_relax_alpha) para mitigar halos/bullseyes.
        boreholes: Optional[np.ndarray] = None,
        anchor_kappa: float = 1e4,           # NO usar 1e6: destruiría cond(A)
        laplacian_relax_alpha: float = 0.2,
        # ── FASE 2.1: modo de anclaje ────────────────────────────────────────
        # "soft" (default, histórico) = strong soft constraint (smallness×anchor_kappa),
        #   error residual ~2% en la celda anclada (κ finito).
        # "hard" = restricción EXACTA por eliminación de variables: la celda anclada
        #   se elimina del sistema (contribución → RHS) y se reinyecta el valor del
        #   sondaje sin error. anchor_kappa y laplacian_relax_alpha se ignoran.
        anchor_mode: str = "soft",
        # ── FASE 2.3: bounds petrofísicos por UNIDAD litológica (membership dura) ─
        # lithology_bounds: array (n,6) [x_m, z_m, y_from_m, y_to_m, dens_min, dens_max]
        # o None. Cada intervalo asigna a sus celdas el BOX [dens_min, dens_max] de su
        # unidad geológica (de la litología del sondaje), sustituyendo el bound escalar
        # global SOLO en esas celdas. El solver con bounds (TRF/FISTA proyectado) impone
        # estas cajas satisfaciendo las condiciones KKT por unidad. Permite restringir
        # celdas con litología CONOCIDA (aunque no tengan densidad puntual medida) al
        # rango petrofísico de su unidad → membership dura sin anclar un valor único.
        lithology_bounds: Optional[np.ndarray] = None,
        # ── OUT: dict mutable donde el solver escribe diagnósticos numéricos ──
        # Si no es None, escribe: acond, chi2_final, n_sat_lower, n_sat_upper.
        solver_meta: Optional[dict] = None,
        # ── FASE 9C-1: Inversión Conjunta (cross-gradient) ───────────────────
        # extra_reg_blocks: lista de matrices sparse (k_i, n_modelo) en ESPACIO
        # FÍSICO del modelo activo; el motor las escala internamente con Ws y las
        # apila en G_aug. extra_reg_rhs: lista de vectores RHS (k_i,) por bloque
        # (None → ceros). Joint v1.1: el caller debe recortar las columnas al
        # dominio observable antes de pasar el bloque (B[:, obs_mask]) cuando
        # prune_observable_domain=True; ver _obs_mask_from_kernel en joint_inversion.py.
        extra_reg_blocks: Optional[list] = None,
        extra_reg_rhs: Optional[list] = None,
        prune_observable_domain: bool = True,
        # ── FASE 4: aquí vivía `depth_beta` (AUDIT H-A4). Se eliminó porque NO
        # HACÍA NADA: la normalización de columnas lo cancelaba exactamente.
        # La demostración, el número y la decisión están abajo, en el bloque
        # "Peso de modelo", y el invariante en tests/test_fase4_depth_weighting.py.
        # El solver Octree (`solve_inversion_treemesh`) SÍ tiene un depth weighting
        # vivo y conserva su `depth_beta`: son dos funcionales distintos.
        # ── FASE 16: Ajuste automático de kappas ─────────────────────────────
        # Si True, escala padding_kappa y anchor_kappa cuando cond(A) > 1e12
        # (estimado por ratio de normas-columna de _G_aug_sm, O(nnz), sin SVD).
        auto_kappa: bool = True,
        # ── FASE 18: Robust sigma (MAD outlier detection) ────────────────────
        # Si True, detecta outliers |g_i - median| > 3·MAD y los downpesa 10×.
        # Default False para backward compat con calls directos (tests, benchmarks).
        # El path de producción (geophysics_service) lo activa vía params.robust_sigma.
        detect_outliers: bool = False,
        # ── FASE 24B Tarea 1: Normas compactas (minimum-support IRLS) ─────────
        # "L2" (default)  = Tikhonov suave actual (backward-compat exacto byte-a-byte).
        # "compact"       = minimum support sobre la smallness (Last & Kubik 1983,
        #                   Portniaguine & Zhdanov 1999): cuerpos nítidos y bien
        #                   delimitados → mejor error de profundidad/localización.
        # "mixed"         = compact smallness + suavidad reponderada por bordes
        #                   (edge-preserving). Experimental.
        # El foco se aplica SOLO a celdas libres del núcleo (no padding, no anclaje):
        # esos términos conservan su rol de restricción fuerte L2.
        regularization_norm: str = "L2",
        compact_eps: float = 0.05,        # piso de foco (t/m³); estabiliza el IRLS
        compact_max_irls: int = 8,        # nº de reponderaciones IRLS (compact/mixed)
        compact_tol: float = 1e-2,        # tol convergencia del foco (||Δfocus||/||focus||)
        # ── FASE 24B Tarea 4: Topografía fraccionaria (cut-cell, anti-staircase) ─
        # OFF (default) = máscara de aire BINARIA (comportamiento histórico exacto).
        # ON = celdas parcialmente bajo el DEM ponderan por su fracción de volumen
        #   rocoso (densidad_efectiva = fracción · densidad) → elimina el "efecto
        #   escalera" en terreno rugoso (AUDIT GEMINI P0). Solo aplica al construir el
        #   kernel fresco (kernel_sparse=None); en modo cacheado/joint se ignora.
        cut_cell_topography: bool = False,
        cutcell_min_fraction: float = 0.05,   # fracción mínima para activar la celda
    ):
        """
        LSQR + Tikhonov 3D. Motor HPC F0.2 EXCLUSIVO.

        Requiere forward_model, sensor_coords, x_c, z_c.
        La ruta legacy (column slicing kernel_sparse[:, active_cells]) ha sido eliminada.

        topography_elevations: array 1D de longitud total_voxels.
            Cada elemento es la coordenada Y (profundidad, positivo hacia abajo)
            de la superficie topográfica en la columna (x,z) del vóxel j.
            None → topografía plana en y=0 (todos los vóxeles son subsuperficie).

        m_ref: modelo de referencia opcional (contraste de densidad t/m³) para el
            funcional de regularización tipo Li & Oldenburg (1999). El término de
            modelo penaliza la rugosidad de (m - m_ref) en lugar de m. Se acepta de
            longitud total_voxels (grilla completa, se enmascara con active_cells) o
            de longitud n_active (ya reducido a celdas activas).
            m_ref is None → comportamiento idéntico al solver actual (RHS reg = 0).

        Devuelve una tupla (longitud total_voxels, NaN en celdas de aire):
            estimated_density_full : densidad recuperada (t/m³).
            relative_score_full    : score de ranking de objetivo [0,1]. NO es una
                                     probabilidad estadística (ver nota interna);
                                     la capa de servicio lo expone como
                                     `relative_target_score` (y `probability` legado).
            misfit_percent         : ‖d−Gm‖ / ‖d‖ × 100.
            normalized_sensitivity : proxy de sensibilidad (columna de G) normalizado.
        """
        logger.info("[INVERSIÓN F0.2] Preparando solver LSQR + Tikhonov (Motor HPC Exclusivo).")

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        # ── Validación F0.2: parámetros HPC requeridos ────────────────────────
        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "Motor HPC F0.2 exclusivo: se requieren forward_model, sensor_coords, x_c, z_c. "
                "La ruta legacy (kernel_sparse[:, active_cells]) ha sido eliminada."
            )

        # ── Fase 14: CSV Validator Strict ─────────────────────────────────────
        # Valida NaN/Inf, rango cero, n_sensors mínimo, duplicados y outliers.
        # Los duplicados se promedian aquí; el resto eleva ValueError con mensaje claro.
        g_observed, sensor_coords, _val_warnings = _validate_gravity_observations(
            g_observed, sensor_coords
        )
        for _w in _val_warnings:
            logger.info(f"[VALIDACIÓN F14] {_w}")

        if lambda_mag <= 0:
            raise ValueError("lambda_mag debe ser mayor que 0.")
        if alpha_spatial < 0:
            raise ValueError("alpha_spatial no puede ser negativo.")

        # ── FASE 8: la corrida se cuenta en etapas con nombre ─────────────────
        cfg = _CfgLSQR(
            lambda_mag=lambda_mag, alpha_spatial=alpha_spatial,
            density_min=density_min, density_max=density_max,
            noise_floor=noise_floor, noise_pct=noise_pct,
            detect_outliers=detect_outliers, padding_kappa=padding_kappa,
            anchor_kappa=anchor_kappa,
            laplacian_relax_alpha=laplacian_relax_alpha, anchor_mode=anchor_mode,
            auto_kappa=auto_kappa, regularization_norm=regularization_norm,
            compact_eps=compact_eps, compact_max_irls=compact_max_irls,
            compact_tol=compact_tol,
            prune_observable_domain=prune_observable_domain,
            cut_cell_topography=cut_cell_topography,
            cutcell_min_fraction=cutcell_min_fraction,
            geo_prior_alpha=geo_prior_alpha,
        )
        est = _EstadoLSQR()
        est.solver_meta_ref = solver_meta

        self._lsqr_mascara_activa(cfg, est, y_c, topography_elevations,
                                  kernel_sparse, sensor_coords, padding_mask)
        self._lsqr_kernel_activo(est, g_observed, y_c, x_c, z_c, kernel_sparse,
                                 forward_model, sensor_coords)
        self._lsqr_mapear_intervalos(est, y_c, boreholes, lithology_bounds)
        self._lsqr_podar_dominio(cfg, est)

        # FASE 8: ¿hay vóxeles anclados observables tras las reducciones?
        _anchor_active = est.anchor_active
        _has_anchors = _anchor_active is not None and bool(np.any(_anchor_active))
        # FASE 2.1: modo de anclaje (soft histórico / hard por eliminación).
        _anchor_mode = str(anchor_mode).lower()
        if _anchor_mode not in ("soft", "hard"):
            raise ValueError(
                f"anchor_mode inválido: {anchor_mode!r}. Use 'soft' o 'hard'."
            )
        _hard_anchor = _has_anchors and _anchor_mode == "hard"
        if _has_anchors:
            logger.info(
                f"[FASE 8] Anclaje sondajes: {int(np.sum(_anchor_active)):,} voxeles | "
                f"modo={_anchor_mode} | "
                f"kappa={anchor_kappa:.0e} | lap_relax={laplacian_relax_alpha}"
            )
        est.has_anchors = _has_anchors
        est.anchor_mode = _anchor_mode
        est.hard_anchor = _hard_anchor

        self._lsqr_cadena_de_pesos(cfg, est, g_observed, hx, hy, hz)
        self._lsqr_ensamblar_sistema(cfg, est, m_ref, extra_reg_blocks,
                                     extra_reg_rhs)
        self._lsqr_resolver_irls(cfg, est)
        return self._lsqr_reconstruir_salida(cfg, est, g_observed, solver_meta,
                                             sensor_coords)


    def estimate_posterior_std(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        noise_floor=0.02,
        noise_pct=0.02,
        hx=None, hy=None, hz=None,
        n_probes: int = 32,
        cg_maxiter: int = 300,
        cg_rtol: float = 1e-6,
        seed: int = 0,
    ):
        """
        FASE 3 (Track 3) — Incertidumbre posterior por vóxel (estimador de Hutchinson).

        Bajo el modelo lineal gaussiano del problema inverso regularizado, la matriz
        de covarianza posterior del contraste de densidad (en el espacio escalado por
        columnas, m = Ws·m_tilde) es:

            C_tilde = ( Gsᵀ Gs + λ_spatial² · Lsᵀ Ls + λ_mag² · I )⁻¹

        donde Gs = Wd·G·Ws y Ls = W_m·Ws son EXACTAMENTE los operadores que arma
        solve_inversion_lsqr (mismos Wd, Ws, depth weighting Li&Oldenburg β=2,
        Laplaciano no-uniforme, λ_spatial = alpha_spatial·(n_sensores/n_activas) y el
        damping λ_mag). Se estima diag(C_tilde) por Hutchinson y se devuelve la
        desviación estándar EN UNIDADES FÍSICAS deshaciendo el column scaling:

            σ_phys_j = Ws_jj · sqrt( diag(C_tilde)_j )

        Es incertidumbre estadística defendible (1σ por vóxel), a diferencia del score
        de ranking heurístico. ALCANCE HONESTO: es la covarianza posterior LINEAL
        alrededor de la solución regularizada; NO captura la no-unicidad no-lineal, ni
        errores de modelo/topografía, ni el sesgo de profundidad inherente. Debe
        reportarse como "σ posterior lineal", no como verdad absoluta.

        Método de SOLO LECTURA: no altera la solución ni el estado del solver.
        Devuelve un array (total_voxels,) con NaN en celdas de aire.
        """
        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "estimate_posterior_std requiere forward_model, sensor_coords, x_c, z_c."
            )
        if lambda_mag <= 0:
            raise ValueError(
                "lambda_mag debe ser > 0: garantiza que C sea definida positiva (SPD)."
            )

        # ── Máscara de celdas activas (idéntica a solve_inversion_lsqr) ───────
        topo_depth, active_cells, n_active = active_cells_from_topography(
            y_c, self.dy, self.total_voxels, topography_elevations, contexto="[UQ] ")

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)

        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── Data weighting Wd + column scaling Ws (igual que el solver) — R-04 ─
        sigma = resolve_sigma(g_observed, noise_floor, noise_pct, detect_outliers=False)
        Wd = sp.diags(1.0 / sigma)
        G_w = Wd @ G_active
        _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        ws_diag = _mw.diag
        Ws = _mw.W
        G_scaled = (G_w @ Ws).tocsr()

        # ── Laplaciano + depth weighting, reducido a activas y escalado ───────
        L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        z0 = self.dy / 2.0
        true_depth = np.clip(y_c_active - topo_depth[active_cells], a_min=1.0, a_max=None)
        w_reg = depth_row_weights(true_depth, z0, beta=2.0)   # Li & Oldenburg 1998: β=2
        L_scaled = ((sp.diags(w_reg) @ L_active) @ Ws).tocsr()

        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── Matriz de información posterior (SPD por el término λ_mag²·I) ─────
        A = normal_equations(G_scaled, L_scaled, lambda_spatial, lambda_mag, n_active)

        diag_C = hutchinson_diag_inv(
            A, n_probes=n_probes, cg_maxiter=cg_maxiter, cg_rtol=cg_rtol, seed=seed
        )
        std_active = ws_diag * np.sqrt(diag_C)   # deshace el column scaling → t/m³

        posterior_std_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        posterior_std_full[active_cells] = std_active

        logger.info(
            f"[UQ Hutchinson] sigma posterior: n_probes={n_probes} | "
            f"sigma_med={float(np.median(std_active)):.4g} t/m3 | "
            f"sigma_p95={float(np.percentile(std_active, 95)):.4g} t/m3"
        )
        return posterior_std_full

    def null_space_shuttle_ensemble(
        self,
        m0,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        noise_floor=0.02,
        noise_pct=0.02,
        hx=None, hy=None, hz=None,
        n_shuttles: int = 12,
        shuttle_scale: float = 0.5,
        smooth_strength: float = 5.0,
        density_min=None,
        density_max=None,
        mu: float = 1e-3,
        cg_maxiter: int = 300,
        cg_rtol: float = 1e-6,
        seed: int = 0,
    ):
        """
        FASE 8.1 (peldaño 1) — Ensemble de modelos por "null-space shuttle".

        Toma la solución invertida `m0` (densidad por vóxel, t/m³) y genera
        `n_shuttles` MODELOS ALTERNATIVOS que ajustan el dato esencialmente igual de
        bien, perturbándola a lo largo de direcciones del espacio nulo de datos del
        operador directo escalado (mismos Wd/Ws/L que solve_inversion_lsqr y que
        estimate_posterior_std). El abanico mide la NO-UNICIDAD: dónde el dato fija
        la densidad (modelos coinciden, σ_ens baja) y dónde no (modelos divergen,
        σ_ens alta) — complementa la σ posterior lineal de Hutchinson.

        Las direcciones se generan en el espacio ESCALADO (m̃ = Ws⁻¹·m) y se devuelven
        a unidades físicas multiplicando por Ws (col scaling), igual que la σ posterior.
        Se suavizan con (I + smooth_strength·LᵀL) para que las alternativas sean lisas
        (campos correlacionados, plausibles), no ruido blanco. La amplitud de cada
        shuttle se fija a `shuttle_scale · (escala robusta de m0)` y, si se dan, los
        modelos se recortan a [density_min, density_max] (el clip puede reintroducir un
        residuo de dato pequeño; por eso se reporta data_fit_preserved SIN clip).

        Método de SOLO LECTURA: no altera la solución ni el estado del solver.

        Returns
        -------
        dict con:
          ensemble        : (n_shuttles, total_voxels) — modelos alternativos (aire=NaN).
          ensemble_std    : (total_voxels,) — σ del ensemble por vóxel (aire=NaN).
          ensemble_mean   : (total_voxels,) — media del ensemble por vóxel (aire=NaN).
          data_fit_preserved : float — ratio medio ‖Gδ‖/‖Gs‖ (↓ mejor; honestidad).
          n_shuttles      : int.
        """
        m0 = np.asarray(m0, dtype=np.float64)
        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "null_space_shuttle_ensemble requiere forward_model, sensor_coords, x_c, z_c."
            )
        if m0.shape[0] != self.total_voxels:
            raise ValueError(
                f"m0 debe tener total_voxels={self.total_voxels} elementos, tiene {m0.shape[0]}."
            )

        # ── Máscara de celdas activas (idéntica a estimate_posterior_std) ─────
        topo_depth, active_cells, n_active = active_cells_from_topography(
            y_c, self.dy, self.total_voxels, topography_elevations, contexto="[UQ shuttle] ")

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)

        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── Wd + column scaling Ws (igual que el solver / la σ posterior) ─────
        sigma = resolve_sigma(g_observed, noise_floor, noise_pct, detect_outliers=False)
        Wd = sp.diags(1.0 / sigma)
        G_w = Wd @ G_active
        _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        ws_diag = _mw.diag
        Ws = _mw.W
        G_scaled = (G_w @ Ws).tocsr()

        # ── Operador de suavizado (I + γ LᵀL) reducido a activas y escalado ───
        from scipy.sparse.linalg import cg as _cg, LinearOperator as _LO
        smooth_op = None
        if smooth_strength and smooth_strength > 0:
            L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
            L_active = L_full.tocsr()[active_cells, :][:, active_cells]
            smooth_op = build_smoothing_operator(
                L_active, _mw, smooth_strength, n_active, cg_maxiter)

        # ── Direcciones de espacio nulo (matrix-free, reproducibles) ──────────
        directions, preserved, null_fraction = null_space_shuttle_directions(
            G_scaled, n_shuttles=n_shuttles, mu=mu, smooth_op=smooth_op,
            cg_maxiter=cg_maxiter, cg_rtol=cg_rtol, seed=seed,
        )

        # ── Amplitud física por shuttle y construcción de alternativas ────────
        m0_active = m0[active_cells]
        # Escala robusta de la solución: MAD→σ, con piso por si el modelo es ~plano.
        amp = robust_amplitude(m0_active, shuttle_scale)

        ensemble, ensemble_std, ensemble_mean = assemble_shuttle_ensemble(
            m0_active, directions, _mw, amp, total_voxels=self.total_voxels,
            active_cells=active_cells, lo=density_min, hi=density_max)
        std_active = ensemble_std[active_cells]

        preserved_mean = float(np.mean(preserved))
        null_fraction_mean = float(np.mean(null_fraction))
        logger.info(
            f"[UQ null-space shuttle] n={n_shuttles} | "
            f"sigma_ens_med={float(np.median(std_active)):.4g} t/m3 | "
            f"sigma_ens_p95={float(np.percentile(std_active, 95)):.4g} t/m3 | "
            f"data_fit_preserved={preserved_mean:.3g} (‖Gδ‖/‖Gs‖, ↓ mejor) | "
            f"null_fraction={null_fraction_mean:.3g} (núcleo presente; ↑ más no-unicidad)"
        )
        return {
            "ensemble": ensemble,
            "ensemble_std": ensemble_std,
            "ensemble_mean": ensemble_mean,
            "data_fit_preserved": preserved_mean,
            "null_fraction": null_fraction_mean,
            "n_shuttles": int(n_shuttles),
        }

    def live_update_add_data(
        self,
        m0,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        new_sensor_coords,
        new_g_observed,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        noise_floor=0.02,
        noise_pct=0.02,
        hx=None, hy=None, hz=None,
        density_min=None,
        density_max=None,
        cg_maxiter: int = 500,
        cg_rtol: float = 1e-8,
    ):
        """
        FASE 8.2 (Live Update local) — incorpora k OBSERVACIONES NUEVAS a una solución ya
        invertida `m0` SIN re-correr el pipeline completo, vía actualización de Woodbury
        rango-k (helper woodbury_low_rank_update). Pensado para el flujo interactivo:
        llega un sondaje/línea de vuelo o se corrige un dato → el modelo se refresca con
        una corrección LOCAL barata, con el "BC global congelado" (la matriz de
        información A, su regularización, el depth weighting y el column scaling Ws se
        reconstruyen IDÉNTICOS a estimate_posterior_std / al solver y NO se recomputan).

        La A frozen y el Ws salen del dato EXISTENTE (g_observed). Las filas nuevas se
        ponderan con σ paramétrico (floor+pct) del dato nuevo y se llevan al mismo
        espacio escalado m̃ = Ws⁻¹·m. Tras el update se vuelve a unidades físicas y, si se
        dan, se recorta a [density_min, density_max] (el clip reintroduce un residuo
        pequeño; por eso se reportan los misfits SIN clip del dato nuevo).

        ALCANCE HONESTO: actualización EXACTA de la solución de mínimos cuadrados LINEAL
        regularizada con operadores congelados; NO es un re-solve acotado desde cero (que
        recomputaría Ws/σ y daría otra solución también válida), NO re-localiza por
        sub-octree (eso es trabajo futuro de 8.2), NO honra cotas salvo por el clip final.
        Método de SOLO LECTURA sobre el estado del solver; devuelve un modelo nuevo.

        Returns
        -------
        dict con:
          model            : (total_voxels,) — densidad actualizada (aire = como en m0).
          update_norm      : float — ‖m1−m0‖ en el espacio escalado (tamaño de la corrección).
          capacitance_cond : float — número de condición de la capacitancia (salud del update).
          new_data_misfit_before / _after : float — ‖G_new·m − d_new‖/‖d_new‖ ANTES/DESPUÉS
                             (debe BAJAR: el modelo se acerca al dato nuevo).
          n_new            : int — número de observaciones nuevas incorporadas.
        """
        m0 = np.asarray(m0, dtype=np.float64)
        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)
        new_sensor_coords = np.atleast_2d(np.asarray(new_sensor_coords, dtype=np.float64))
        new_g_observed = np.atleast_1d(np.asarray(new_g_observed, dtype=np.float64)).ravel()

        k = validate_live_update_args(
            m0, total_voxels=self.total_voxels, forward_model=forward_model,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c, lambda_mag=lambda_mag,
            nombre="live_update_add_data", new_sensor_coords=new_sensor_coords,
            new_obs=new_g_observed)

        # ── Máscara de celdas activas (idéntica a estimate_posterior_std) ─────
        topo_depth, active_cells, n_active = active_cells_from_topography(
            y_c, self.dy, self.total_voxels, topography_elevations, contexto="[Live update] ")

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]
        x_c_arr = np.asarray(x_c, dtype=np.float64)[active_cells]
        z_c_arr = np.asarray(z_c, dtype=np.float64)[active_cells]

        # ── A congelada (Wd, Ws, L_scaled, λ_spatial) IDÉNTICA a la σ posterior ─
        G_active = forward_model._build_sparse_kernel(
            x_c_arr, y_c_active, z_c_arr, np.asarray(sensor_coords, dtype=np.float64),
        )
        sigma = resolve_sigma(g_observed, noise_floor, noise_pct, detect_outliers=False)
        Wd = sp.diags(1.0 / sigma)
        G_w = Wd @ G_active
        _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
        ws_diag = _mw.diag
        Ws = _mw.W
        G_scaled = (G_w @ Ws).tocsr()

        L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        z0 = self.dy / 2.0
        true_depth = np.clip(y_c_active - topo_depth[active_cells], a_min=1.0, a_max=None)
        w_reg = depth_row_weights(true_depth, z0, beta=2.0)
        L_scaled = ((sp.diags(w_reg) @ L_active) @ Ws).tocsr()

        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)
        A = normal_equations(G_scaled, L_scaled, lambda_spatial, lambda_mag, n_active)

        # ── m0 físico → m̃0 escalado (m = Ws·m̃ ⇒ m̃ = m / ws_diag) ───────────
        m0_active = m0[active_cells]

        # ── Filas nuevas: mismo W que produjo A (por eso A queda congelada) ───
        G_new = forward_model._build_sparse_kernel(
            x_c_arr, y_c_active, z_c_arr, new_sensor_coords,
        )                                                  # (k, n_active), física
        m1_active, info, misfit_before, misfit_after = woodbury_update_from_new_rows(
            A, m0_active, _mw, G_new, new_g_observed,
            noise_floor=noise_floor, noise_pct=noise_pct,
            cg_maxiter=cg_maxiter, cg_rtol=cg_rtol, lo=density_min, hi=density_max,
            woodbury_fn=woodbury_low_rank_update,
        )

        model_full = np.array(m0, dtype=np.float64, copy=True)
        model_full[active_cells] = m1_active

        logger.info(
            f"[Live update Woodbury] n_new={k} | "
            f"update_norm={info['update_norm']:.4g} | cap_cond={info['capacitance_cond']:.3g} | "
            f"misfit dato nuevo {misfit_before:.3g} → {misfit_after:.3g} (↓ mejor)"
        )
        return {
            "model": model_full,
            "update_norm": info["update_norm"],
            "capacitance_cond": info["capacitance_cond"],
            "new_data_misfit_before": misfit_before,
            "new_data_misfit_after": misfit_after,
            "n_new": int(k),
        }

    def live_update_suboctree(
        self,
        m0,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        region_center=None,
        region_radius=None,
        region_mask=None,
        new_sensor_coords=None,
        new_g_observed=None,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        anchor_strength=1.0,
        topography_elevations=None,
        noise_floor=0.02,
        noise_pct=0.02,
        hx=None, hy=None, hz=None,
        density_min=None,
        density_max=None,
        cg_maxiter: int = 500,
        cg_rtol: float = 1e-8,
    ):
        """
        FASE 8.2c (Live Update local — RE-SOLVE POR SUB-OCTREE) — refina SOLO una
        sub-región local del modelo (las celdas cerca de un dato/sondaje nuevo) con el
        resto del modelo CONGELADO como condición de frontera, en vez de actualizar todo
        el volumen. Complementa el update global de Woodbury (live_update_add_data): la
        corrección de sub-octree es la versión ESPACIALMENTE LOCALIZADA — geológicamente
        sensata (un sondaje informa sobre todo su vecindad) y barata cuando |S| ≪ n.

        Sea S el conjunto de celdas activas de la sub-región (por `region_mask`, o por
        `region_center`+`region_radius`). El fondo S^c queda fijo en m0; su respuesta
        d_bg = G_{S^c}·m0_{S^c} se RESTA del dato (existente + nuevo), y se re-resuelve un
        problema inverso PEQUEÑO solo en S contra el residuo d_res = d − d_bg:

            min_S ‖Wd(G_S m_S − d_res)‖² + λ_s²‖L̃_S m_S‖² + λ_anchor²‖m̃_S − m̃0_S‖²

        en el espacio escalado (mismos Wd/Ws/L/depth-weighting que el solver). El ancla
        λ_anchor (anchor_strength) sujeta las celdas de S a su valor previo donde el dato
        no manda (evita que la sub-región derive). Se resuelve por CG sobre la normal SPD.

        ALCANCE HONESTO: re-solve LINEAL (un paso Tikhonov/Gauss-Newton) con fondo
        congelado — el fondo NO se reajusta (aproximación: ignora que celdas fuera de S
        podrían también moverse); NO recomputa Ws/σ globales; honra cotas solo por el clip
        final. Método de SOLO LECTURA; devuelve un modelo nuevo. Las celdas FUERA de S
        quedan BYTE-IDÉNTICAS a m0 (propiedad clave del sub-octree).

        Returns
        -------
        dict con:
          model              : (total_voxels,) — densidad actualizada (S refinado, resto = m0).
          region_size        : int — nº de celdas activas en S.
          region_misfit_before / _after : float — ‖Wd(G·m − d)‖/‖Wd·d‖ del dato (exist.+nuevo)
                               ANTES/DESPUÉS (debe bajar; mide la ganancia local).
          update_norm        : float — ‖m_S_new − m0_S‖ (tamaño de la corrección local).
        """
        m0 = np.asarray(m0, dtype=np.float64)
        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        validate_live_update_args(
            m0, total_voxels=self.total_voxels, forward_model=forward_model,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c, lambda_mag=lambda_mag,
            nombre="live_update_suboctree", exigir_region=True,
            region_mask=region_mask, region_center=region_center,
            region_radius=region_radius)

        # ── Máscara de celdas activas (idéntica a estimate_posterior_std) ─────
        topo_depth, active_cells, n_active = active_cells_from_topography(
            y_c, self.dy, self.total_voxels, topography_elevations, contexto="[Sub-octree] ")

        x_arr = np.asarray(x_c, dtype=np.float64)
        z_arr = np.asarray(z_c, dtype=np.float64)
        x_a = x_arr[active_cells]
        y_a = y_c[active_cells]
        z_a = z_arr[active_cells]

        # ── Sub-región S (en índices LOCALES dentro de las activas) ───────────
        S_local, n_S = select_subregion(
            region_mask, region_center, region_radius, x_a=x_a, y_a=y_a, z_a=z_a,
            active_cells=active_cells, total_voxels=self.total_voxels, contexto="[Sub-octree] ")

        # ── Dato combinado (existente + nuevo) y geometría de sensores ────────
        sensors, data = combine_existing_and_new_data(
            sensor_coords, g_observed, new_sensor_coords, new_g_observed)

        # ── Kernel sobre TODAS las activas, columnas S vs fondo ───────────────
        G_all = forward_model._build_sparse_kernel(x_a, y_a, z_a, sensors).tocsc()
        m0_active = m0[active_cells]
        G_S, d_res = split_region_response(G_all, S_local, m0_active, data)

        # ── Wd + column scaling Ws (frozen, local a S) ────────────────────────
        sigma = resolve_sigma(data, noise_floor, noise_pct, detect_outliers=False)
        Wd = sp.diags(1.0 / sigma)
        G_Sw = Wd @ G_S
        _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_Sw)
        ws_diag = _mw.diag
        Ws = _mw.W
        G_scaled = (G_Sw @ Ws).tocsr()

        # ── Laplaciano restringido a S + depth weighting, escalado ────────────
        L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        L_S = L_active[S_local, :][:, S_local]
        z0 = self.dy / 2.0
        true_depth = np.clip(y_a[S_local] - topo_depth[active_cells][S_local],
                             a_min=1.0, a_max=None)
        w_reg = depth_row_weights(true_depth, z0, beta=2.0)
        L_scaled = ((sp.diags(w_reg) @ L_S) @ Ws).tocsr()

        lambda_spatial = float(alpha_spatial) * (len(data) / n_S)
        lambda_anchor = float(anchor_strength) * float(lambda_mag) ** 0.5 + float(lambda_mag)

        # ── Normal SPD pequeña en S + término de ancla hacia m0_S ─────────────
        m_tilde0_S = m0_active[S_local] / ws_diag        # prior en espacio escalado
        A_S = normal_equations(G_scaled, L_scaled, lambda_spatial, lambda_anchor, n_S)
        b_S = (
            G_scaled.T @ (Wd @ d_res)
            + (lambda_anchor ** 2) * m_tilde0_S
        )

        m1_S = solve_local_region_cg(
            A_S, b_S, _mw, n_S, cg_rtol=cg_rtol, cg_maxiter=cg_maxiter,
            lo=density_min, hi=density_max)

        # ── Misfit ponderado del dato (exist.+nuevo) antes/después ────────────
        misfit_before = relative_misfit(G_all @ m0_active, data, weight=Wd)
        m1_active = m0_active.copy()
        m1_active[S_local] = m1_S
        misfit_after = relative_misfit(G_all @ m1_active, data, weight=Wd)

        model_full = np.array(m0, dtype=np.float64, copy=True)
        # Solo S cambia; el resto queda BYTE-IDÉNTICO a m0 (incluidas celdas de aire).
        full_S = np.zeros(self.total_voxels, dtype=bool)
        full_S[np.where(active_cells)[0][S_local]] = True
        model_full[full_S] = m1_S

        update_norm = float(np.linalg.norm(m1_S - m0_active[S_local]))
        logger.info(
            f"[Live update sub-octree] |S|={n_S}/{n_active} activas | "
            f"update_norm={update_norm:.4g} | "
            f"misfit dato {misfit_before:.3g} → {misfit_after:.3g} (↓ mejor)"
        )
        return {
            "model": model_full,
            "region_size": n_S,
            "region_misfit_before": misfit_before,
            "region_misfit_after": misfit_after,
            "update_norm": update_norm,
        }


def compute_jacobian_dask(
    sensor_coords: np.ndarray,
    voxel_centers: np.ndarray,
    forward_model: "GravimetryForward",
    batch_size: int = 500,
) -> tuple:
    """
    Compute Jacobian (sensitivity) matrix in sensor batches using Dask, write to Zarr.

    Splits sensors into batches of `batch_size`, schedules each batch as a
    dask.delayed task, and streams results to a Zarr store — the full dense
    matrix never lives in RAM simultaneously.

    Parameters
    ----------
    sensor_coords : (n_sensors, 3) float64 — x/y/z of measurement points.
    voxel_centers : (n_voxels, 3) float64 — x/y/z of model cell centres.
    forward_model : GravimetryForward — provides dx/dy/dz and cutoff_radius.
    batch_size    : sensors per Dask task (tune for RAM vs. parallelism).

    Returns
    -------
    (zarr_path, (n_sensors, n_voxels))
    """
    import tempfile
    import dask
    from exploration.storage import save_jacobian_zarr as _save_zarr

    sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
    voxel_centers = np.asarray(voxel_centers, dtype=np.float64)
    n_sensors = sensor_coords.shape[0]
    n_voxels  = voxel_centers.shape[0]

    x_c = voxel_centers[:, 0]
    y_c = voxel_centers[:, 1]
    z_c = voxel_centers[:, 2]

    # Forward model parameters (captured by value — safe to use in Dask workers).
    _dx = forward_model.dx
    _dy = forward_model.dy
    _dz = forward_model.dz
    _cr = forward_model.cutoff_radius

    # Each delayed task builds the kernel for one sensor batch and returns a
    # dense (batch, n_voxels) array. A fresh GravimetryForward per task avoids
    # cache contention between concurrent workers.
    @dask.delayed
    def _batch_kernel(start: int, end: int) -> np.ndarray:
        fm = GravimetryForward(dx=_dx, dy=_dy, dz=_dz, cutoff_radius=_cr)
        G_batch = fm._build_sparse_kernel(
            x_c, y_c, z_c,
            sensor_coords[start:end],
        )
        return G_batch.toarray()   # (end-start, n_voxels)

    # Build batch index list and schedule all tasks.
    batch_ranges = [
        (s, min(s + batch_size, n_sensors))
        for s in range(0, n_sensors, batch_size)
    ]
    delayed_batches = [_batch_kernel(s, e) for s, e in batch_ranges]

    # Fase 10 §10.4 — Out-of-core: cada batch se escribe DIRECTAMENTE a Zarr
    # sin materializar la matriz completa en RAM.
    # Peak RAM = batch_size × n_voxels × 8 bytes (un batch float64 a la vez).
    # En disco: float32 (4 bytes) → 50% menos espacio vs Sprint 2 float64.
    zarr_path = os.path.join(
        tempfile.gettempdir(),
        f"tq_jacobian_{n_sensors}x{n_voxels}.zarr",
    )
    import zarr as _zarr
    z = _zarr.open_array(
        zarr_path,
        mode="w",
        shape=(n_sensors, n_voxels),
        dtype="float32",
        chunks=(min(batch_size, n_sensors), n_voxels),
    )
    for _i, (s, e) in enumerate(batch_ranges):
        # Computa un batch a la vez (synchronous = sin pool anidado)
        batch_result = dask.compute(delayed_batches[_i], scheduler="synchronous")[0]
        z[s:e, :] = batch_result.astype(np.float32)
        del batch_result   # libera inmediatamente

    disk_mb = n_sensors * n_voxels * 4 / 1e6
    logger.info(
        f"[JACOBIAN DASK/OOC] shape=({n_sensors},{n_voxels}) | "
        f"batches={len(batch_ranges)} | batch_size={batch_size} | "
        f"disco={disk_mb:.1f} MB (float32) | zarr={zarr_path}"
    )
    return zarr_path, (n_sensors, n_voxels)


def solve_inversion_treemesh(
    mesh,
    g_observed,
    sensor_coords,
    forward_model,
    lambda_mag: float = 3.0,
    alpha_spatial: float = 1.0,
    depth_beta: float = 2.0,
    base_density: float = 2.6,
    density_min: float = 2.6,
    density_max: float = 5.5,
    noise_floor: float = 0.02,
    noise_pct: float = 0.02,
    solver_meta: Optional[dict] = None,
    iter_lim: int = 500,
    atol: float = 1e-8,
):
    """
    SPRINT 3B — Solver de inversión gravimétrica MÍNIMO sobre malla Octree.

    Ruta PARALELA y autocontenida: NO toca GravimetryInversion.solve_inversion_lsqr
    (el solver de grilla regular validado por el certificado de recuperación sintética
    permanece intacto). Reproduce SOLO el núcleo físico común a la ruta regular:

        φ(m) = ‖Wd (G m − d)‖²
             + ‖ λ_spatial · diag(w_reg) · L · m ‖²        (suavidad, depth-weighted)
             + ‖ diag(λ_mag · w_reg) · m ‖²                 (smallness, depth-weighted H2)

    con column-scaling (Ws) idéntico, depth weighting Li & Oldenburg
    w_reg = 1/(profundidad + z0)^β normalizado, y bounds petrofísicos en espacio escalado.

    NO incluye (por diseño minimal): topografía/active-cells, padding, anclajes por
    sondaje, m_ref, poda R-05, ni cross-gradient. Esas extensiones viven en el solver
    regular; aquí el dominio es la malla Octree completa (todas las celdas activas).

    Parameters
    ----------
    mesh : TreeMesh
        Malla Octree adaptativa. Provee centros, profundidades, tamaños y el
        Laplaciano adaptativo (mesh.build_laplacian_octree()).
    g_observed : (n_sensors,) array
        Anomalía gravimétrica observada (mismas unidades que el forward).
    sensor_coords : (n_sensors, 3) array
        Coordenadas [x, y, z] de los sensores.
    forward_model : GravimetryForward
        Motor forward; se usa build_kernel_from_treemesh(mesh, sensors).

    Returns
    -------
    estimated_density : (n_cells,) array
        Densidad recuperada por celda (t/m³), bounded a [density_min, density_max].
    relative_score : (n_cells,) array
        Score de ranking de objetivo [0,1] (NO probabilidad estadística), idéntico
        en definición al solver regular: 1 − |Gᵀr|_j / max_j |Gᵀr|.
    misfit_percent : float
        ‖d − Gm‖ / ‖d‖ × 100.
    """
    g_observed = np.asarray(g_observed, dtype=np.float64)
    sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
    if not np.isfinite(g_observed).all():
        raise ValueError("g_observed contiene NaN o Inf.")
    if lambda_mag <= 0:
        raise ValueError("lambda_mag debe ser mayor que 0.")
    if alpha_spatial < 0:
        raise ValueError("alpha_spatial no puede ser negativo.")

    n_cells = mesh.n_cells
    n_sensors = len(g_observed)

    # ── Forward sobre la malla Octree ─────────────────────────────────────────
    G = forward_model.build_kernel_from_treemesh(mesh, sensor_coords)   # (n_sensors, n_cells)
    if G.nnz == 0:
        raise ValueError("Kernel TreeMesh vacío: ninguna celda tiene sensibilidad a los sensores.")

    # ── Data weighting (R-04 sigma adaptativo, idéntico al solver regular) ────
    if noise_floor == 0.02 and noise_pct == 0.02:
        sigma, _ = _sigma_adaptive(g_observed, detect_outliers=False)
    else:
        sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
    Wd = sp.diags(1.0 / sigma)
    d_w = Wd @ g_observed
    G_w = (Wd @ G).tocsr()

    # ── Peso de modelo (FASE 7: el mismo constructor que el resto del motor) ──
    _mw = build_model_weights(MODEL_WEIGHT_SENSITIVITY, G_w=G_w)
    col_norms = 1.0 / _mw.diag
    Ws = _mw.W
    G_scaled = G_w @ Ws

    _lb_tilde = (float(density_min) - float(base_density)) * col_norms
    _ub_tilde = (float(density_max) - float(base_density)) * col_norms

    # ── Depth weighting (Li & Oldenburg) sobre la malla Octree ────────────────
    depths = mesh.get_cell_depths()
    sizes = mesh.get_cell_sizes()
    # z0 = media de la semi-altura de celda en profundidad (análogo a dy/2 regular,
    # robusto a celdas variables).
    z0 = 0.5 * float(np.mean(sizes[:, 1]))
    # Peso de FILA por profundidad. A diferencia del solver de grilla regular, aquí
    # `w_reg` NO se cancela: se aplica sólo a la smallness y a la suavidad, no al
    # bloque de datos, así que `depth_beta` está VIVO (la Fase 4 lo midió: 8.125×).
    # Producción conmuta a este solver SOLA con >50.000 celdas o >50 km de survey.
    true_depth = np.clip(depths, a_min=1.0, a_max=None)
    w_reg = depth_row_weights(true_depth, z0, beta=depth_beta)

    # ── Smallness (depth-weighted, H2) ────────────────────────────────────────
    _w_small = float(lambda_mag) * w_reg
    _small_block = sp.diags(_w_small) @ Ws

    # ── Laplaciano adaptativo (omitido cuando alpha_spatial=0) ────────────────
    # NOTE: build_laplacian_octree usa face_map con clave 1D → O(n·ny·nz) para
    # grillas grandes (bug de escala regional). Omitir cuando alpha_spatial=0 es
    # el workaround del gate test; el fix vectorizado es Sprint 3C.
    lambda_spatial = float(alpha_spatial) * (n_sensors / max(n_cells, 1))
    if alpha_spatial > 0:
        L = mesh.build_laplacian_octree()
        W_m = sp.diags(w_reg) @ L
        L_scaled = W_m @ Ws
        G_aug = sp.vstack([G_scaled, lambda_spatial * L_scaled, _small_block]).tocsr()
        d_aug = np.concatenate([
            d_w,
            np.zeros(n_cells, dtype=np.float64),
            np.zeros(n_cells, dtype=np.float64),
        ])
    else:
        G_aug = sp.vstack([G_scaled, _small_block]).tocsr()
        d_aug = np.concatenate([
            d_w,
            np.zeros(n_cells, dtype=np.float64),
        ])

    logger.info(
        f"[TREEMESH SOLVER] n_cells={n_cells:,} n_sensors={n_sensors:,} "
        f"G_aug=({G_aug.shape[0]:,}×{G_aug.shape[1]:,}) NNZ={G_aug.nnz:,} "
        f"lambda_mag={lambda_mag:.2e} lambda_spatial={lambda_spatial:.2e} beta={depth_beta}"
    )

    # Paridad de escalabilidad con el path regular (Fase 10): para mallas grandes el
    # sistema mal condicionado converge mejor con LSMR (Fong & Saunders 2011) que con
    # LSQR. Gateado por LSMR_THRESHOLD_N_ACTIVE → las mallas pequeñas siguen usando
    # LSQR (byte-idéntico al comportamiento previo; sin regresión en tests existentes).
    from core.config import USE_LSMR_LARGE as _USE_LSMR, LSMR_THRESHOLD_N_ACTIVE as _LSMR_THRESH
    _itn = 0
    if _USE_LSMR and n_cells > _LSMR_THRESH:
        from exploration.solver_preconditioned import solve_inversion_lsmr as _lsmr_solve
        m_tilde, _acond = _lsmr_solve(
            G_aug, d_aug, _lb_tilde, _ub_tilde, maxiter=max(1000, iter_lim), tol=atol,
        )
        _itn = -1   # LSMR no expone el conteo de iteraciones de forma compatible
        logger.info(f"[TREEMESH SOLVER] LSMR (Fase 10, n>{_LSMR_THRESH:,}) cond(A)~{_acond:.2e}")
    else:
        result = lsqr(G_aug, d_aug, damp=0.0, iter_lim=iter_lim, atol=atol, btol=atol, show=False)
        m_tilde = np.clip(result[0], _lb_tilde, _ub_tilde)
        _acond = result[6]
        _itn = int(result[2])

    density_contrast = Ws @ m_tilde
    if not np.isfinite(density_contrast).all():
        raise RuntimeError("LSQR (TreeMesh) devolvió densidades no finitas.")

    density_raw = float(base_density) + density_contrast
    estimated_density = np.clip(density_raw, density_min, density_max)

    # ── Misfit y score relativo (definición idéntica al solver regular) ───────
    g_model = G @ density_contrast
    residual_sensor = g_observed - g_model
    residual_error = float(np.linalg.norm(residual_sensor))
    observed_norm = float(np.linalg.norm(g_observed))
    misfit_percent = (float("nan") if observed_norm <= 0 or not np.isfinite(observed_norm)
                      else float((residual_error / observed_norm) * 100.0))

    voxel_error = np.abs(G.T @ residual_sensor)
    max_voxel_error = float(np.max(voxel_error)) if n_cells > 0 else 0.0
    if max_voxel_error <= 0 or not np.isfinite(max_voxel_error):
        relative_score = np.full(n_cells, np.nan, dtype=np.float64)
    else:
        relative_score = np.clip(1.0 - (voxel_error / max_voxel_error), 0.0, 1.0)

    _phi_d = float(np.sum((residual_sensor / sigma) ** 2))
    _chi2_final = _phi_d / max(n_sensors, 1)

    n_sat_lower = int(np.sum(density_raw < density_min))
    n_sat_upper = int(np.sum(density_raw > density_max))

    logger.info(
        f"[TREEMESH SOLVER] Misfit={misfit_percent:.2f}% chi2={_chi2_final:.4f} "
        f"cond(A)~{_acond:.2e} sat=({n_sat_lower}+{n_sat_upper})/{n_cells:,}"
    )

    if solver_meta is not None:
        solver_meta["acond"] = float(_acond)
        solver_meta["itn"] = int(_itn)
        solver_meta["chi2_final"] = float(_chi2_final)
        solver_meta["misfit_percent"] = misfit_percent
        # ── FASE 7, criterio (d): también este solver declara su funcional ────
        # La auditoría (§9.1884) señaló que producción conmuta a Octree SOLA con
        # >50.000 celdas o >50 km de survey, de modo que «la misma configuración
        # nominal aplica un depth weighting o ninguno según el tamaño del
        # levantamiento, y nada en la salida lo declara». Ahora sí: aquí el peso de
        # profundidad `w_reg` va SÓLO en la smallness y la suavidad, no en el bloque
        # de datos, así que `depth_beta` está VIVO — al revés que en el solver de
        # grilla regular. Que las dos corridas lo digan es lo que hace comparables
        # dos resultados del mismo producto.
        solver_meta["regularization_functional"] = declare_functional(
            _mw,
            smallness=SMALLNESS_SCALED_BY_W,   # el bloque es diags(λ·w_reg)·Ws
            depths=depths,
            depth_beta_solicitado=float(depth_beta),
            smoothness_row_weight=bool(alpha_spatial > 0),
        ) | {
            # El peso de PROFUNDIDAD de este solver no es el peso de modelo `Ws`:
            # es un peso de fila independiente que NO se cancela. Se declara aparte
            # para no forzar la regla general a describir un tercer caso.
            "depth_row_weight_kind": "inverse_depth_row",
            "depth_beta_declared": float(depth_beta),
            "depth_beta_has_effect": True,
            "depth_weighting_active": True,
            "effect_mechanism": "row_weight_on_smallness_and_smoothness",
            "explanation_es": (
                f"Solver Octree: el peso de profundidad (beta={depth_beta}) se aplica "
                f"como peso de FILA sobre la smallness y la suavidad, no sobre el "
                f"bloque de datos, asi que NO se cancela y beta esta VIVO (medido en "
                f"la Fase 4: 8.125x). Es el funcional opuesto al del solver de grilla "
                f"regular, y produccion elige entre los dos por TAMANO de la malla "
                f"(>50.000 celdas o >50 km), no por decision del usuario."
            ),
        }
        solver_meta["n_cells"] = n_cells
        solver_meta["n_sat_lower"] = n_sat_lower
        solver_meta["n_sat_upper"] = n_sat_upper
        solver_meta["mesh_info"] = {
            "n_cells": n_cells,
            "n_levels": int(mesh.max_refinement_depth) + 1,
            "min_cell_size": float(sizes.min()),
        }

    return estimated_density, relative_score, misfit_percent


class TargetingEngine:
    """
    Conecta la inversión geofísica con el modelo económico.

    Importante:
    - Exporta block model COMPLETO a data/block_model_001.parquet.
    - Incluye ix, iy, iz para que main.py pueda hacer reshape correctamente.
    - Devuelve df_anomaly filtrado para la respuesta del endpoint.
    """

    @staticmethod
    def extract_and_export(
        x,
        y,
        z,
        density,
        probability,
        ix=None,
        iy=None,
        iz=None,
        block_size=10.0,
        cutoff_density=2.75,
        export_path="data/block_model_001.parquet",
        posterior_std=None,
        base_density=2.6,
    ):
        """FASE 22 — `base_density` deja de ser el literal 2.6 (ACAD-13).

        El contraste que esta exportación escribía se calculaba contra `2.6` escrito a
        mano mientras el motor invierte contra `base_density`, que el contrato declara
        configurable (`schemas/geophysics_schema.py:782`, rango 1.0–6.0). Con la roca
        caja en 4,5 t/m³ la columna quedaba desfasada en 1,9 t/m³ — más que casi
        cualquier contraste de interés. El default 2.6 se conserva sólo para que la
        firma siga siendo llamable desde un script suelto; producción pasa el valor
        efectivo de la corrida.
        """
        logger.info("[TARGETING] Modelando clases geometalúrgicas y exportando block model.")

        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        density = np.asarray(density, dtype=np.float64)
        probability = np.asarray(probability, dtype=np.float64)

        n = len(density)

        if not (len(x) == len(y) == len(z) == len(probability) == n):
            raise ValueError("x, y, z, density y probability deben tener el mismo largo.")

        if ix is None:
            ix = np.floor(x / block_size).astype(np.int32)
        else:
            ix = np.asarray(ix, dtype=np.int32)

        if iy is None:
            iy = np.floor(y / block_size).astype(np.int32)
        else:
            iy = np.asarray(iy, dtype=np.int32)

        if iz is None:
            iz = np.floor(z / block_size).astype(np.int32)
        else:
            iz = np.asarray(iz, dtype=np.int32)

        if not (len(ix) == len(iy) == len(iz) == n):
            raise ValueError("ix, iy e iz deben tener el mismo largo que density.")

        if not np.isfinite(density).all():
            raise ValueError("density contiene NaN o Inf.")

        if not np.isfinite(probability).all():
            raise ValueError("probability contiene NaN o Inf.")

        block_size = float(block_size)
        # FASE 22 (ACAD-12) — aquí vivía `MAX_BLOCK_VOLUME_M3 = 1_000_000` y
        # `block_volume = min(block_size**3, MAX_BLOCK_VOLUME_M3)`: un tope SILENCIOSO
        # de 100 m de arista. Sobre los `block_size` reales medidos en disco (2.089
        # corridas) recortaba el volumen sin decirlo — con dx=520 m el tope declaraba
        # 1e6 m³ donde la celda mide 1,4e8. La ruta canónica nunca tuvo ese tope:
        # `inversion_postprocess_service.py:90` usa `dx*dx*dx` a secas, y ésta ahora
        # coincide con ella, que es lo que permite compararlas en el gate.
        block_volume = block_size ** 3

        density_contrast = density - float(base_density)
        # FASE 22 (ACAD-12) — `tonnage` está en TONELADAS: m³ × t/m³. La columna se
        # llamaba `bulk_rock_mass_kg` y había un factor 1.000 entre el nombre y el
        # valor. Se renombra en vez de multiplicar porque el número en kg no lo pide
        # nadie: cero lectores en backend, frontend, scripts y notebooks.
        bulk_rock_mass_tonnes = block_volume * density

        targeting_score = density * probability
        target_idx = int(np.argmax(targeting_score))
        target_coords = (
            float(x[target_idx]),
            float(y[target_idx]),
            float(z[target_idx])
        )

        # Normalize posterior_std: None → array de NaN (esquema Arrow estable)
        if posterior_std is not None:
            _std_arr = np.asarray(posterior_std, dtype=np.float64)
            if len(_std_arr) != n:
                _std_arr = np.full(n, np.nan, dtype=np.float64)
        else:
            _std_arr = np.full(n, np.nan, dtype=np.float64)

        # FASE 7 (Q4): nombres de columna no-mineros/compliance-safe en el Parquet.
        #   tonnage         -> bulk_rock_mass_kg   (FASE 22: -> bulk_rock_mass_tonnes)
        #   probability     -> relative_target_score
        #   targeting_score -> exploration_index
        # Las variables internas (tonnage/targeting_score) se conservan; solo cambian
        # los nombres exportados y las expresiones de filtrado que los referencian.
        #
        # FASE 22 (ACAD-12): el renombrado «compliance-safe» de la Fase 7 acertó al
        # quitar la palabra `tonnage` —invita a leerse como tonelaje de RECURSO, y
        # esto es masa de roca— y erró en el sufijo: puso `_kg` sobre un valor en
        # toneladas. Se corrige por el mismo camino que ya se usó en la ruta canónica
        # (commit d424c7c: `modeled_rock_mass_kg` -> `modeled_rock_mass_tonnes`), y con
        # la misma palabra, para que las dos columnas de masa del producto se llamen
        # igual y puedan compararse.
        df = pl.DataFrame(
            {
                "ix": ix,
                "iy": iy,
                "iz": iz,
                "x": x,
                "y": y,
                "z": z,
                "density": density,
                "density_contrast": density_contrast,
                "bulk_rock_mass_tonnes": bulk_rock_mass_tonnes,
                "relative_target_score": probability,
                "exploration_index": targeting_score,
                "posterior_std": _std_arr,
            }
        )

        # El filtrado de anomalías sigue la señal primaria de densidad (sin cambios
        # de lógica); solo se actualiza el nombre de columna renombrado.
        df_anomaly = df.filter(pl.col("density") >= cutoff_density)

        os.makedirs(os.path.dirname(export_path), exist_ok=True)

        # OJO: se exporta el modelo completo, no solo anomalías.
        # Esto es necesario para que /generate y /scenario-sweep puedan hacer reshape.
        df.write_parquet(export_path)

        anomaly_path = export_path.replace(".parquet", "_anomaly.parquet")
        df_anomaly.write_parquet(anomaly_path)

        logger.info(
            f"[TARGETING] Target sugerido: {target_coords} | "
            f"Densidad: {density[target_idx]:.3f} t/m3 | "
            f"Probabilidad: {probability[target_idx]:.1%}"
        )

        logger.info(
            f"[TARGETING] Block model completo exportado: {export_path} | "
            f"Bloques totales: {len(df):,} | "
            f"Anomalías: {len(df_anomaly):,}"
        )

        return df_anomaly, target_coords


if __name__ == "__main__":
    NX, NY, NZ = 8, 4, 8
    BLOCK_SIZE = 10.0

    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]

    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)

    x_c = (ix * BLOCK_SIZE) + (BLOCK_SIZE / 2)
    y_c = (iy * BLOCK_SIZE) + (BLOCK_SIZE / 2)
    z_c = (iz * BLOCK_SIZE) + (BLOCK_SIZE / 2)

    sensor_coords = np.array(
        [
            [5, 0, 5],
            [15, 0, 5],
            [25, 0, 5],
            [35, 0, 5],
            [45, 0, 5],
            [55, 0, 5],
            [65, 0, 5],
            [75, 0, 5],
            [35, 0, 35],
            [45, 0, 35],
        ],
        dtype=np.float64
    )

    logger.info(f"[GEOFÍSICA] Test local con {len(sensor_coords)} sensores.")

    forward = GravimetryForward(
        BLOCK_SIZE,
        BLOCK_SIZE,
        BLOCK_SIZE,
        cutoff_radius=120.0
    )

    kernel_sparse = forward.build_sparse_kernel(
        x_c,
        y_c,
        z_c,
        sensor_coords
    )

    true_density_contrast = np.zeros(len(x_c), dtype=np.float64)
    anomaly_mask = (
        (x_c - 40.0) ** 2
        + (y_c - 20.0) ** 2
        + (z_c - 40.0) ** 2
    ) < 25.0 ** 2

    true_density_contrast[anomaly_mask] = 0.8

    g_observed = kernel_sparse @ true_density_contrast

    inversor = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE)

    est_density, prob, _misfit_percent, _normalized_sensitivity = inversor.solve_inversion_lsqr(
        g_observed,
        None,               # kernel_sparse obsoleto — Motor HPC F0.2 exclusivo
        y_c,
        lambda_mag=5e-5,
        alpha_spatial=1.5,
        forward_model=forward,
        sensor_coords=sensor_coords,
        x_c=x_c,
        z_c=z_c,
    )

    TargetingEngine.extract_and_export(
        x_c,
        y_c,
        z_c,
        est_density,
        prob,
        ix=ix,
        iy=iy,
        iz=iz,
        block_size=BLOCK_SIZE,
        cutoff_density=2.75
    )
