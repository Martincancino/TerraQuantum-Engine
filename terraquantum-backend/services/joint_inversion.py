"""
FASE 9C-2 — Orquestador de Inversión Conjunta (Joint Inversion / Cross-Gradient).

Implementa un esquema de Gauss-Newton ALTERNADO (sequential / Gallardo–Meju) con
"Continuation Strategy" exponencial sobre el peso del acoplamiento cross-gradient.

Idea física
───────────
El cross-gradient  t = ∇m_ρ × ∇m_χ  se anula cuando los gradientes de densidad y
susceptibilidad son PARALELOS, es decir cuando ambos modelos comparten ESTRUCTURA
(bordes en los mismos lugares) sin imponer ninguna relación petrofísica entre los
VALORES. Linealizamos fijando un modelo y penalizando el del otro:

    minimizar  ‖ ∇m_ρ × ĝ_χ ‖   (paso de gravedad, ĝ_χ = dirección unitaria de ∇m_χ)
    minimizar  ‖ ∇m_χ × ĝ_ρ ‖   (paso de magnetometría, ĝ_ρ = dirección unitaria de ∇m_ρ)

Cada penalización es un bloque sparse B (3·nC, nC) inyectado en el motor respectivo
vía su hook `extra_reg_blocks` (FASE 9C-1). El motor lo escala internamente con su
acondicionamiento (Ws en gravedad, Wz_inv en magnetometría) y lo apila en G_aug.

Malla común
───────────
Backend-only / álgebra lineal. Ambos motores se corren sobre la MISMA malla core
(build_voxel_grid) con topografía plana → todas las celdas activas → n_active = nC =
nx·ny·nz en orden Fortran idéntico al de los operadores de gradiente. Así los bloques
cross-gradient son conformables con ambos solvers SIN remapeo entre mallas, y el bloque
3D final lleva densidad y susceptibilidad sobre exactamente la misma malla activa.

NO se calcula física nueva aquí: se orquestan los dos motores existentes
(GravimetryInversion / MagnetometryInversion) y los operadores de geophysics_math.
"""

import subprocess
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import polars as pl
import scipy.sparse as sp
from fastapi import HTTPException

from core.config import ensure_runtime_dirs, RUN_BLOCK_MODEL_FILENAME
from services.block_model_store import (
    RUN_SOURCE_GRAVITY_FILENAME,
    get_run_block_model_reference,
    sha256_file,
    update_run_status,
    validate_parquet_schema,
    write_run_manifest,
)
from core.logging import get_logger
from exploration.clustering import extract_geological_bodies
from exploration.geophysics_math import build_gradient_operators
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from exploration.pgi_engine import gmm_responsibilities_2d, niw_map_update_2d
from schemas.geophysics_schema import GeophysicsInvertInput

_log = get_logger(__name__)

# Epsilon de normalización (dentro del radicando, como exige el plan 9C-2) y de razón.
_NORM_EPS = 1e-12
_RATIO_EPS = 1e-12

# Criterios de Early Stopping (plan 9C-2).
_DELTA_TOL = 1e-3       # cambio relativo de cada modelo
_E_REL_TOL = 1e-2       # cambio relativo de E_norm global
_E_ABS_TOL = 0.10       # E_norm absoluto (estructuras ya alineadas)


# ─────────────────────────────────────────────────────────────────────────────
# Álgebra del cross-gradient (operadores ya construidos por geophysics_math).
# ─────────────────────────────────────────────────────────────────────────────
def _normalized_gradient(m, Dx, Dy, Dz):
    """Dirección unitaria local del gradiente de ``m``.

    ĝ = ∇m / sqrt(gx² + gy² + gz² + eps), componente a componente. Es adimensional
    y escala-invariante: por eso el acoplamiento no depende de que ρ (~t/m³) y χ
    (~SI) tengan magnitudes muy distintas.
    """
    gx = Dx @ m
    gy = Dy @ m
    gz = Dz @ m
    denom = np.sqrt(gx * gx + gy * gy + gz * gz + _NORM_EPS)
    return gx / denom, gy / denom, gz / denom


def _fixed_gradient_dirs(m, Dx, Dy, Dz, kind):
    """Componentes del gradiente del modelo FIJO que entran al bloque estructural.

    kind='cross_gradient' → dirección UNITARIA ĝ (Gallardo–Meju): escala-invariante,
        cada borde pesa igual sin importar la magnitud del contraste.
    kind='gramian' → gradiente CRUDO ∇m (Gramian de Zhdanov): el acoplamiento queda
        ponderado por la magnitud del gradiente del modelo fijo, de modo que el
        producto cruzado ‖∇m_ρ × ∇m_χ‖ enfatiza el alineamiento donde el contraste
        fijo es FUERTE (bordes nítidos) y lo relaja donde es plano. Sparse, mismo
        patrón que el cross-gradient — distinto solo en la normalización.
    """
    if kind == "gramian":
        return Dx @ m, Dy @ m, Dz @ m
    return _normalized_gradient(m, Dx, Dy, Dz)


def _build_cross_gradient_block(hat_x, hat_y, hat_z, Dx, Dy, Dz):
    """Matriz rala B (3·nC, nC) tal que  B @ m = ∇m × ĝ  (producto cruz por celda).

    Componentes del producto cruzado  t = ∇m × ĝ :
        t_x = (∂y m)·ĝz − (∂z m)·ĝy
        t_y = (∂z m)·ĝx − (∂x m)·ĝz
        t_z = (∂x m)·ĝy − (∂y m)·ĝx
    ⇒  B_x = diag(ĝz)·Dy − diag(ĝy)·Dz, etc. ĝ es la dirección FIJA del otro modelo.
    """
    Bx = sp.diags(hat_z) @ Dy - sp.diags(hat_y) @ Dz
    By = sp.diags(hat_x) @ Dz - sp.diags(hat_z) @ Dx
    Bz = sp.diags(hat_y) @ Dx - sp.diags(hat_x) @ Dy
    return sp.vstack([Bx, By, Bz]).tocsr()


def _cross_components(m_rho, m_chi, Dx, Dy, Dz):
    """Componentes del producto cruzado por celda y magnitudes de cada gradiente."""
    grx, gry, grz = Dx @ m_rho, Dy @ m_rho, Dz @ m_rho
    gcx, gcy, gcz = Dx @ m_chi, Dy @ m_chi, Dz @ m_chi
    cx = gry * gcz - grz * gcy
    cy = grz * gcx - grx * gcz
    cz = grx * gcy - gry * gcx
    cross_mag = np.sqrt(cx * cx + cy * cy + cz * cz)
    rho_mag = np.sqrt(grx * grx + gry * gry + grz * grz)
    chi_mag = np.sqrt(gcx * gcx + gcy * gcy + gcz * gcz)
    return cross_mag, rho_mag, chi_mag


def _e_norm_global_l2(m_rho, m_chi, Dx, Dy, Dz):
    """Fórmula LITERAL del plan 9C-2 (referencia/diagnóstico):

        E_l2 = ‖∇m_ρ × ∇m_χ‖₂ / (‖∇m_ρ‖₂·‖∇m_χ‖₂ + eps).

    OJO: para campos distribuidos sobre N celdas esta razón satura en ≈1/√N
    (verificado: gradientes ortogonales en TODA celda → E_l2 = 1/√N), porque el
    denominador multiplica las energías TOTALES de cada campo (términos cruzados
    entre celdas lejanas) mientras el numerador solo suma productos LOCALES. Por
    eso NO se usa como criterio de parada (un umbral absoluto sería dependiente de
    la malla); se conserva solo para trazabilidad con el plan.
    """
    cross_mag, rho_mag, chi_mag = _cross_components(m_rho, m_chi, Dx, Dy, Dz)
    num = float(np.sqrt(np.sum(cross_mag * cross_mag)))
    den = float(np.sqrt(np.sum(rho_mag * rho_mag))) * float(np.sqrt(np.sum(chi_mag * chi_mag)))
    return num / (den + _RATIO_EPS)


def _e_norm_cellwise(m_rho, m_chi, Dx, Dy, Dz):
    """Métrica de disimilitud estructural GRID-INDEPENDIENTE (criterio de parada).

        E_cell = Σ‖∇m_ρ × ∇m_χ‖ / Σ(‖∇m_ρ‖·‖∇m_χ‖ + eps)

    Es el análogo LOCAL de la fórmula del plan (mismo numerador de producto cruz),
    pero con el denominador como suma de productos PUNTUALES → media ponderada por
    magnitud de sin(ángulo) entre los gradientes. Rango real [0, 1] independiente de
    N: 0 = gradientes paralelos en todas las celdas (misma estructura); 1 =
    ortogonales en todas. Las celdas planas (gradiente ~0) pesan ~0 de forma natural.
    """
    cross_mag, rho_mag, chi_mag = _cross_components(m_rho, m_chi, Dx, Dy, Dz)
    num = float(np.sum(cross_mag))
    den = float(np.sum(rho_mag * chi_mag))
    return num / (den + _RATIO_EPS)


# ─────────────────────────────────────────────────────────────────────────────
# FASE 3.1 — PGI CONJUNTO DINÁMICO (acoplamiento petrofísico, GMM 2D ρ-χ).
# ─────────────────────────────────────────────────────────────────────────────
# A diferencia del cross-gradient (que acopla solo la ESTRUCTURA: bordes en los
# mismos lugares), el PGI conjunto acopla los VALORES: una mixtura Gaussiana 2D en
# el plano (densidad, susceptibilidad) cuyas clases tienen centroides correlacionados
# (p.ej. magnetita = alta ρ Y alta χ). En cada iteración, cada celda se asigna (MAP)
# a su clase 2D y se la empuja con un término smallness hacia el centroide de esa
# clase EN AMBAS físicas a la vez — así recuperar χ alto donde ρ es alto, y viceversa.
# Es la formulación de Astic & Oldenburg 2021 (GMM dinámico conjunto). El bloque
# smallness reutiliza el hook extra_reg_blocks: A_pgi = √α·I (espacio físico) con
# RHS √α·m_ref → residual √α·(m_phys − m_ref) tras el escalado interno B·Wz_inv.
_GMM_SPD_FLOOR = 1e-9


def _build_joint_padded_grid(nx, ny, nz, dx, n_pad=5, pad_factor=1.3):
    """Malla compartida con padding para el joint, padded en ±X, ±Z y +Y (profundidad).

    A diferencia de build_padded_tensor_grid (que padea simétricamente las 6 caras), aquí
    NO se padea la cara -Y (arriba de la superficie de observación): en campos potenciales
    no hay tierra sobre el survey, y esas celdas las enmascararía el solver como aire,
    rompiendo la co-localización malla-completa que exigen los operadores de gradiente y
    el kernel forward compartidos. Padding lateral (±X, ±Z) y hacia abajo (+Y) = la BC
    física correcta. Los centros del core se alinean a (k+0.5)·dx como build_voxel_grid.

    Devuelve el mismo contrato que build_padded_tensor_grid (claves x_c/y_c/z_c, hx/hy/hz,
    nx_total/ny_total/nz_total, ix_core/iy_core/iz_core, x_c_core/..., is_core).
    """
    nx, ny, nz = int(nx), int(ny), int(nz)
    dx = float(dx)
    n_pad = int(n_pad)
    pad_factor = float(pad_factor)
    if n_pad < 1:
        raise ValueError("n_pad debe ser >= 1.")
    if pad_factor < 1.0:
        raise ValueError("pad_factor debe ser >= 1.0.")

    _pad_out = np.array([dx * (pad_factor ** i) for i in range(n_pad)], dtype=np.float64)

    def _sym(n_core):  # left_pad (decreciente hacia el core) + core + right_pad
        return np.concatenate([_pad_out[::-1], np.full(n_core, dx), _pad_out])

    hx = _sym(nx)
    hz = _sym(nz)
    hy = np.concatenate([np.full(ny, dx), _pad_out])   # +Y (abajo) solamente

    nx_total, ny_total, nz_total = len(hx), len(hy), len(hz)

    def _centers(h):
        edges = np.concatenate([[0.0], np.cumsum(h)])
        return 0.5 * (edges[:-1] + edges[1:])

    xc1, yc1, zc1 = _centers(hx), _centers(hy), _centers(hz)
    # Alinear primer centro CORE con dx/2. En X/Z el core arranca en n_pad; en Y en 0.
    xc1 = xc1 + (dx / 2.0 - xc1[n_pad])
    zc1 = zc1 + (dx / 2.0 - zc1[n_pad])
    yc1 = yc1 + (dx / 2.0 - yc1[0])

    gx, gy, gz = np.mgrid[0:nx_total, 0:ny_total, 0:nz_total]
    ix_f = gx.flatten(order="F").astype(np.int32)
    iy_f = gy.flatten(order="F").astype(np.int32)
    iz_f = gz.flatten(order="F").astype(np.int32)

    is_core = (
        (ix_f >= n_pad) & (ix_f < n_pad + nx) &
        (iy_f < ny) &
        (iz_f >= n_pad) & (iz_f < n_pad + nz)
    )
    return {
        "x_c": xc1[ix_f], "y_c": yc1[iy_f], "z_c": zc1[iz_f],
        "hx": hx, "hy": hy, "hz": hz,
        "nx_total": nx_total, "ny_total": ny_total, "nz_total": nz_total,
        "ix_core": ix_f[is_core] - n_pad,
        "iy_core": iy_f[is_core],
        "iz_core": iz_f[is_core] - n_pad,
        "x_c_core": xc1[ix_f][is_core],
        "y_c_core": yc1[iy_f][is_core],
        "z_c_core": zc1[iz_f][is_core],
        "is_core": is_core,
    }


def _fit_joint_gmm_2d(rho_abs, chi, n_classes):
    """Bootstrap de la mixtura 2D (ρ, χ) desde los modelos warm-up independientes.

    Estandariza cada eje (ρ ~ O(1) t/m³, χ ~ O(0.01) SI tienen escalas dispares) antes
    de ajustar con sklearn, y vuelve a transformar medias/covarianzas al espacio físico.
    El resultado es la mixtura PRIOR (conocimiento data-driven del warm-up) hacia la que
    el refit NIW dinámico regulariza. Devuelve (means (K,2), covs (K,2,2), weights (K,)).
    """
    from sklearn.mixture import GaussianMixture  # noqa: PLC0415

    X = np.column_stack([
        np.asarray(rho_abs, dtype=np.float64),
        np.asarray(chi, dtype=np.float64),
    ])
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    Xs = (X - mu) / sd
    gm = GaussianMixture(
        n_components=int(n_classes),
        covariance_type="full",
        init_params="k-means++",
        n_init=3,
        reg_covar=1e-6,
        random_state=42,
    )
    gm.fit(Xs)
    D = np.diag(sd)
    means = gm.means_ * sd + mu                                  # (K, 2)
    covs = np.einsum("ij,kjl,lm->kim", D, gm.covariances_, D)    # (K, 2, 2)
    # Blindaje SPD tras el back-transform (simetriza + piso diagonal).
    for k in range(covs.shape[0]):
        covs[k] = 0.5 * (covs[k] + covs[k].T) + _GMM_SPD_FLOOR * np.eye(2)
    return means, covs, np.asarray(gm.weights_, dtype=np.float64)


def _joint_pgi_class_means(rho_abs, chi, means, covs, weights):
    """Centroide de clase 2D (MAP) por celda. Devuelve (rho_ref_abs (n,), chi_ref (n,))."""
    X = np.column_stack([
        np.asarray(rho_abs, dtype=np.float64),
        np.asarray(chi, dtype=np.float64),
    ])
    resp = gmm_responsibilities_2d(X, means, covs, weights)     # (K, n)
    cls = np.argmax(resp, axis=0)                               # (n,)
    return means[cls, 0], means[cls, 1]


def _obs_mask_from_kernel(k):
    """Máscara booleana de celdas observables (misma lógica R-05 de gravimetry.py).

    Columnas con norma² < 1e-6 * max son muertos: sensibilidad cero para todos los
    sensores → solver no las necesita. Pre-computada en joint para poder recortar
    los bloques cross-gradient ANTES de pasarlos al motor.
    """
    col_sens = np.asarray(k.power(2).sum(axis=0)).ravel()
    return col_sens > 1e-6 * max(float(np.max(col_sens)), 1e-30)


def _rel_change(m_new, m_old):
    """‖m_new − m_old‖ / (‖m_old‖ + eps)."""
    denom = float(np.linalg.norm(m_old)) + _RATIO_EPS
    return float(np.linalg.norm(m_new - m_old)) / denom


def _weighted_centroid(x_c, y_c, z_c, weights):
    """Centro de masa espacial ponderado de un campo ya recuperado (NO es física nueva).

    Promedio de las coordenadas de celda ponderado por ``weights`` (exceso de densidad
    para el centroide de masa; susceptibilidad para el de χ). Es un estadístico DESCRIPTIVO
    sobre el modelo ya invertido, calculado solo para empaquetar evidencia numérica en el
    reporte. Devuelve None si el peso total es ~0 (campo plano → centroide indefinido).
    """
    w = np.clip(np.asarray(weights, dtype=np.float64), 0.0, None)
    total = float(np.sum(w))
    if total <= _RATIO_EPS:
        return None
    return {
        "x_m": float(np.sum(w * x_c) / total),
        "y_m": float(np.sum(w * y_c) / total),
        "z_m": float(np.sum(w * z_c) / total),
        "total_weight": round(total, 6),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Extracción de anclajes de sondajes (idéntica semántica a los motores aislados).
# ─────────────────────────────────────────────────────────────────────────────
def _extract_boreholes(params: GeophysicsInvertInput):
    """Devuelve (gravity_arr, magnetic_arr): arrays (n,5) [x,z,y_from,y_to,valor] o None.

    Gravedad lee density_t_m3; magnetometría lee susceptibility_si. Cada motor salta
    los intervalos sin su propiedad. Bounds validados con 422 (igual que 9A/9B).
    """
    bh_list = getattr(params, "boreholes", None) or []
    g_rows, m_rows = [], []
    for i, bh in enumerate(bh_list):
        if bh.density_t_m3 is not None:
            if bh.density_t_m3 < params.density_min or bh.density_t_m3 > params.density_max:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Borehole density fuera de bounds (intervalo {i}: {bh.density_t_m3} t/m3 "
                        f"no en [{params.density_min}, {params.density_max}] t/m3)."
                    ),
                )
            g_rows.append([bh.x_m, bh.z_m, bh.y_from_m, bh.y_to_m, bh.density_t_m3])
        if bh.susceptibility_si is not None:
            if bh.susceptibility_si < params.susc_min or bh.susceptibility_si > params.susc_max:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Borehole susceptibility fuera de bounds (intervalo {i}: "
                        f"{bh.susceptibility_si} SI no en [{params.susc_min}, {params.susc_max}] SI)."
                    ),
                )
            m_rows.append([bh.x_m, bh.z_m, bh.y_from_m, bh.y_to_m, bh.susceptibility_si])
    g_arr = np.asarray(g_rows, dtype=np.float64) if g_rows else None
    m_arr = np.asarray(m_rows, dtype=np.float64) if m_rows else None
    return g_arr, m_arr


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia Parquet (Fase 10 - Parte 2: cierre del Transport Gap).
# ─────────────────────────────────────────────────────────────────────────────
_RUN_JOINT_FILENAME = "block_model_joint.parquet"


def _persist_joint_parquet(
    params: GeophysicsInvertInput,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    m_rho: np.ndarray,
    rho_contrast: np.ndarray,
    m_chi: np.ndarray,
    combined: np.ndarray,
    kept_idx: np.ndarray,
) -> str:
    """Escribe el bloque conjunto en Parquet y devuelve la ruta del archivo.

    Columnas exportadas (schema v3.0):
        x_c, y_c, z_c          — coordenadas de centro del vóxel (m)
        x_m, y_m, z_m          — alias estándar para el frontend
        density_t_m3            — densidad absoluta recuperada
        density_contrast_t_m3  — contraste respecto a densidad base
        susceptibility_si       — susceptibilidad magnética recuperada
        joint_structural_score  — score combinado normalizado ρ+χ ∈ [0,1]
        run_type                — "joint" (schema v3.0)
        schema_version          — "v3.0"

    Solo se persisten los vóxeles en ``kept_idx`` (zona anómala filtrada).
    NUNCA sobreescribe DEFAULT_BLOCK_MODEL_PATH (B-10 fix, HITO 1).
    """
    x_kept = x_c[kept_idx]
    y_kept = y_c[kept_idx]
    z_kept = z_c[kept_idx]
    rho_kept = m_rho[kept_idx]
    contrast_kept = rho_contrast[kept_idx]
    chi_kept = m_chi[kept_idx]
    score_kept = combined[kept_idx]

    n = len(x_kept)
    df = pl.DataFrame({
        "x_c": x_kept.tolist(),
        "y_c": y_kept.tolist(),
        "z_c": z_kept.tolist(),
        "x_m": x_kept.tolist(),
        "y_m": y_kept.tolist(),
        "z_m": z_kept.tolist(),
        # Aliases required by block_model_service.get_index_columns() and ensure_visual_columns()
        "x": x_kept.tolist(),
        "y": y_kept.tolist(),
        "z": z_kept.tolist(),
        "density": rho_kept.tolist(),
        "density_t_m3": rho_kept.tolist(),
        "density_contrast_t_m3": contrast_kept.tolist(),
        "susceptibility_si": chi_kept.tolist(),
        "joint_structural_score": score_kept.tolist(),
        "run_type": ["joint"] * n,
        "schema_version": ["v4.0"] * n,
    })

    joint_ref = get_run_block_model_reference(
        project_id=params.project_id,
        run_id=params.run_id,
        filename=_RUN_JOINT_FILENAME,
    )
    joint_ref.path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(joint_ref.path))

    validation = validate_parquet_schema(joint_ref.path, expected_run_type="joint")
    if not validation["valid"]:
        import logging as _log_mod
        _log_mod.getLogger(__name__).warning(
            "joint_parquet_schema_invalid run=%s errors=%s",
            getattr(params, "run_id", "unknown"),
            validation["errors"],
        )

    # También escribir a block_model.parquet (ruta estándar de /block-model) para que
    # el visor 3D sirva los datos joint sin cambios en el frontend ni en la API.
    std_ref = get_run_block_model_reference(
        project_id=params.project_id,
        run_id=params.run_id,
        filename=RUN_BLOCK_MODEL_FILENAME,
    )
    df.write_parquet(str(std_ref.path))

    return str(joint_ref.path)


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador principal.
# ─────────────────────────────────────────────────────────────────────────────
def run_joint_inversion(params: GeophysicsInvertInput):
    """FASE 9C-2 — Inversión conjunta Gauss-Newton alternada con continuation.

    Activado por run_geophysics_inversion cuando el input trae señal gravimétrica
    real (g≠0) Y magnética (magnetic_nt≠0). Devuelve el mismo contrato que los demás
    motores: {voxels, best_target, report, misfit_error_percent}.
    """
    from services.geophysics_service import build_voxel_grid, write_run_report_snapshot

    project_id = params.project_id
    run_id = params.run_id

    def _update(status, progress, stage, message, metrics=None, error=None):
        if project_id and run_id:
            try:
                update_run_status(project_id, run_id, status, progress, stage, message, metrics, error)
            except Exception:
                pass

    _log.info("joint_inversion_start", project_id=project_id, run_id=run_id)
    _joint_start_utc = datetime.now(timezone.utc)
    ensure_runtime_dirs()
    _update("running", 0.0, "loading_data", "Validando input de inversión conjunta (Fase 9C-2)...")

    # ── Validación cruzada de las dos físicas ────────────────────────────────
    obs = params.observations
    g_observed = np.asarray([o.g for o in obs], dtype=np.float64)
    mag = np.asarray(params.magnetic_nt, dtype=np.float64)
    sensor_coords = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=np.float64)

    if len(mag) != len(obs):
        raise HTTPException(
            status_code=422,
            detail=f"magnetic_nt (len={len(mag)}) debe tener el mismo largo que observations (len={len(obs)}).",
        )
    if not np.isfinite(mag).all() or not np.isfinite(g_observed).all():
        raise HTTPException(status_code=422, detail="Observaciones (g / magnetic_nt) con NaN/Inf.")
    if not np.isfinite(sensor_coords).all():
        raise HTTPException(status_code=422, detail="Coordenadas de sensores con NaN/Inf.")
    if np.allclose(g_observed, 0.0) or np.allclose(mag, 0.0):
        raise HTTPException(
            status_code=422,
            detail="Inversión conjunta requiere señal NO nula en ambas físicas (gravedad y magnetometría).",
        )
    if params.density_max <= params.density_min:
        raise HTTPException(status_code=422, detail="density_max debe ser mayor que density_min.")
    if params.susc_max <= params.susc_min:
        raise HTTPException(status_code=422, detail="susc_max debe ser mayor que susc_min.")

    total_voxels = params.nx * params.ny * params.nz
    if total_voxels > 200_000:
        raise HTTPException(status_code=422, detail=f"Modelo demasiado grande (nx*ny*nz>200000): {total_voxels} voxels.")
    if params.cutoff_radius < params.block_size:
        raise HTTPException(status_code=422, detail="cutoff_radius no puede ser menor que block_size.")

    # ── Malla compartida a ambas físicas (core, o core+padding en Fase 3.3) ──
    # FASE 3.3: opt-in joint_padding extiende la malla con padding geométrico (BC física
    # de campos potenciales), COMPARTIDO por ambas físicas. Los operadores de gradiente,
    # el kernel forward, los bloques de acoplamiento y el Laplaciano se definen sobre la
    # malla extendida (no-uniforme vía hx/hy/hz); las celdas de padding se anclan al fondo
    # con padding_kappa. Al final se REDUCE al core (is_core) para el bloque 3D de salida.
    # Default False = malla core pelada (histórico byte-idéntico): _hx/_hy/_hz=None en el
    # solver, espaciado escalar dx en los operadores de gradiente, sin padding_mask.
    nx, ny, nz, dx = params.nx, params.ny, params.nz, params.block_size
    _pad_on = bool(getattr(params, "joint_padding", False))
    _padding_kappa = float(getattr(params, "joint_padding_kappa", 1e5))
    if _pad_on:
        _n_pad = int(getattr(params, "joint_n_pad", 5))
        _pad_factor = float(getattr(params, "joint_pad_factor", 1.3))
        # Padding ±X, ±Z y +Y (NO -Y/aire) → co-localización malla-completa preservada.
        _mesh = _build_joint_padded_grid(nx, ny, nz, float(dx), n_pad=_n_pad, pad_factor=_pad_factor)
        nx_w, ny_w, nz_w = _mesh["nx_total"], _mesh["ny_total"], _mesh["nz_total"]
        x_c, y_c, z_c = _mesh["x_c"], _mesh["y_c"], _mesh["z_c"]
        _hx, _hy, _hz = _mesh["hx"], _mesh["hy"], _mesh["hz"]
        is_core = np.asarray(_mesh["is_core"], dtype=bool)
        _padding_mask = ~is_core
        _grad_hx, _grad_hy, _grad_hz = _hx, _hy, _hz       # gradiente no-uniforme
        _solve_hx, _solve_hy, _solve_hz = _hx, _hy, _hz    # Laplaciano no-uniforme
        ix_out, iy_out, iz_out = _mesh["ix_core"], _mesh["iy_core"], _mesh["iz_core"]
    else:
        nx_w, ny_w, nz_w = nx, ny, nz
        ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(params)
        is_core = np.ones(nx * ny * nz, dtype=bool)
        _padding_mask = None
        _grad_hx, _grad_hy, _grad_hz = dx, dx, dx          # uniforme (byte-idéntico)
        _solve_hx, _solve_hy, _solve_hz = None, None, None
        ix_out, iy_out, iz_out = ix, iy, iz
    nC = nx_w * ny_w * nz_w
    nC_core = int(np.sum(is_core))
    if nC > 400_000:
        raise HTTPException(
            status_code=422,
            detail=f"Malla conjunta con padding demasiado grande (nC={nC}>400000). Reduce nx/ny/nz o joint_n_pad.",
        )

    boreholes_g, boreholes_m = _extract_boreholes(params)

    # Operadores de primera derivada co-localizados (geophysics_math, 9C-1).
    Dx, Dy, Dz = build_gradient_operators(nx_w, ny_w, nz_w, _grad_hx, _grad_hy, _grad_hz)

    # Motores forward / inversos sobre la malla (core o core+padding).
    grav_fwd = GravimetryForward(dx, dx, dx, cutoff_radius=params.cutoff_radius)
    mag_fwd = MagnetometryForward(
        dx, dx, dx,
        cutoff_radius=params.cutoff_radius,
        inclination_deg=params.inclination_deg,
        declination_deg=params.declination_deg,
        field_intensity_nt=params.field_intensity_nt,
    )
    _base_density = float(getattr(params, "base_density", 2.6))
    grav_inv = GravimetryInversion(nx_w, ny_w, nz_w, dx, base_density=_base_density)
    mag_inv = MagnetometryInversion(nx_w, ny_w, nz_w, dx)
    base_rho = grav_inv.base_density

    lam_g = params.lambda_mag if params.lambda_mag > 0 else 1e-5
    lam_m = params.lambda_mag if params.lambda_mag > 0 else 1e-4

    def _solve_gravity(extra_blocks, m_ref_contrast, kernel_cache=None, extra_rhs=None):
        meta = {}
        rho_full, score, misfit, sens = grav_inv.solve_inversion_lsqr(
            g_observed, kernel_cache, y_c,
            lambda_mag=lam_g, alpha_spatial=params.alpha_spatial,
            topography_elevations=None,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
            forward_model=grav_fwd,
            hx=_solve_hx, hy=_solve_hy, hz=_solve_hz,
            padding_mask=_padding_mask, padding_kappa=_padding_kappa,
            density_min=params.density_min, density_max=params.density_max,
            boreholes=boreholes_g,
            m_ref=m_ref_contrast,
            extra_reg_blocks=extra_blocks,
            extra_reg_rhs=extra_rhs,
            prune_observable_domain=_do_prune,  # Joint v1.1: R-05 compatible vía dimensión reducida
            solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(rho_full, dtype=np.float64), nan=base_rho), score, misfit, meta

    def _solve_magnetic(extra_blocks, m_ref, kernel_cache=None, extra_rhs=None):
        meta = {}
        chi_full, score, misfit, sens = mag_inv.solve_magnetic_inversion_lsqr(
            d_observed=mag, override_kernel=kernel_cache, y_c=y_c,
            lambda_mag=lam_m, alpha_spatial=params.alpha_spatial,
            topography_elevations=None,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
            forward_model=mag_fwd,
            hx=_solve_hx, hy=_solve_hy, hz=_solve_hz,
            padding_mask=_padding_mask, padding_kappa=_padding_kappa,
            susc_min=params.susc_min, susc_max=params.susc_max,
            boreholes=boreholes_m,
            m_ref=m_ref,
            extra_reg_blocks=extra_blocks,
            extra_reg_rhs=extra_rhs,
            solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(chi_full, dtype=np.float64), nan=0.0), score, misfit, meta

    # ── CACHÉ KERNEL: construir G_active una sola vez (geometría invariante) ────
    # En joint mode (topo=None, prune=False) todos los vóxeles son activos en
    # cada llamada → kernel idéntico en toda iteración; cachear evita ~14-30
    # reconstrucciones costosas de KDTree + prism loops.
    _x_c_arr   = np.asarray(x_c, dtype=np.float64)
    _z_c_arr   = np.asarray(z_c, dtype=np.float64)
    _sensor_arr = np.asarray(sensor_coords, dtype=np.float64)
    grav_fwd_kernel_cache = grav_fwd._build_sparse_kernel(
        _x_c_arr, y_c, _z_c_arr, _sensor_arr,
    )
    mag_fwd_kernel_cache = mag_fwd._build_sparse_kernel(
        _x_c_arr, y_c, _z_c_arr, _sensor_arr,
    )
    _log.info(
        f"[CACHÉ KERNEL] G_gravity: {grav_fwd_kernel_cache.shape} ({grav_fwd_kernel_cache.nnz:,} NNZ) | "
        f"G_magnetic: {mag_fwd_kernel_cache.shape} ({mag_fwd_kernel_cache.nnz:,} NNZ)"
    )

    # ── Joint v1.1: Observable pruning (R-05 compatible) ─────────────────────
    # Pre-computar la máscara de dominio observable gravitacional desde el kernel
    # cacheado (misma lógica que R-05 interno de solve_inversion_lsqr). Al pasar
    # B_chi[:, _obs_mask_g] al motor de gravedad, los bloques cross-gradient
    # conforman con el espacio post-poda sin remapeo: B.shape[1] = n_obs_g = Wz.shape[0].
    # El motor magnético no tiene poda (prune_observable_domain no existe en magnetometry.py)
    # y opera siempre sobre n_active = nC → no requiere slicing.
    _do_prune = bool(getattr(params, 'joint_observable_pruning', True))
    _obs_mask_g = _obs_mask_from_kernel(grav_fwd_kernel_cache)
    _n_obs_g = int(np.sum(_obs_mask_g))
    _n_dead_g = nC - _n_obs_g
    _log.info(
        f"[JOINT R-05] Dominio observable (gravedad): {_n_obs_g:,}/{nC:,} "
        f"({100.0 * _n_obs_g / nC:.1f}%) | muertos: {_n_dead_g:,} | "
        f"poda={'ON' if _do_prune else 'OFF (joint_observable_pruning=False)'}"
    )

    # ── Iteración 0 — Warm-up: motores independientes (sin cross-gradient) ───
    _update("running", 0.10, "warmup", "Warm-up: inversiones independientes (k=0)...")
    _log.info("[FASE 9C-2] Warm-up k=0 — gravedad independiente.")
    m_rho, _g_score, misfit_g, meta_g = _solve_gravity(None, None, grav_fwd_kernel_cache)
    _log.info("[FASE 9C-2] Warm-up k=0 — magnetometría independiente.")
    m_chi, _m_score, misfit_m, meta_m = _solve_magnetic(None, None, mag_fwd_kernel_cache)

    # E_norm primario = métrica por celda grid-independiente (criterio de parada).
    # E_l2 = fórmula global literal del plan, solo para trazabilidad (satura en 1/√N).
    E_norm = _e_norm_cellwise(m_rho, m_chi, Dx, Dy, Dz)
    E_l2 = _e_norm_global_l2(m_rho, m_chi, Dx, Dy, Dz)
    cross_beta = (
        float(params.cross_lambda_beta) if hasattr(params, 'cross_lambda_beta')
        else float(getattr(params, 'cross_lambda_max', 1e4)) / 1e4
    )
    # Proxy para ‖G_scaled‖_F: tras la col-norm de gravimetry.py cada columna tiene
    # norma unitaria, por lo tanto ‖G_scaled‖_F = sqrt(nC).
    G_norm = float(np.sqrt(nC))
    history = [{
        "iter": 0,
        "lambda_cross": 0.0,
        "E_norm": round(E_norm, 6),
        "E_norm_l2_global": round(E_l2, 6),
        "delta_rho": None,
        "delta_chi": None,
        "misfit_gravity_percent": misfit_g,
        "misfit_magnetic_percent": misfit_m,
        "cond_A_gravity": meta_g.get("acond"),
        "cond_A_magnetic": meta_m.get("acond"),
    }]
    _log.info(f"[FASE 9C-2] k=0 (warm-up) | E_norm={E_norm:.6f} (cellwise) | "
          f"E_l2={E_l2:.6f} | misfit_g={misfit_g:.3f}% | misfit_m={misfit_m:.3f}%")

    # ── FASE 3.1/3.2: setup del acoplamiento conjunto ────────────────────────
    # cross_gradient (default) | gramian | pgi_dynamic | pgi+cross.
    _coupling_mode = getattr(params, "joint_coupling_mode", "cross_gradient")
    # Bloque estructural sparse (cross-gradient unitario o Gramian de Zhdanov crudo).
    _use_struct = _coupling_mode in ("cross_gradient", "gramian", "pgi+cross")
    _struct_kind = "gramian" if _coupling_mode == "gramian" else "cross_gradient"
    _use_pgi = _coupling_mode in ("pgi_dynamic", "pgi+cross")
    _pgi_alpha = float(getattr(params, "joint_pgi_alpha", 0.1))
    _pgi_dynamic = bool(getattr(params, "joint_pgi_dynamic", True))
    _pgi_n_classes = int(getattr(params, "joint_pgi_n_classes", 3))
    _pgi_prior_strength = float(getattr(params, "joint_pgi_prior_strength", 10.0))
    _sqrt_pgi_alpha = float(np.sqrt(max(_pgi_alpha, 0.0)))

    # Bootstrap de la mixtura 2D ρ-χ desde el warm-up independiente. La mixtura prior
    # es INMUTABLE (centro del refit NIW); means/covs/weights mutan en cada iteración.
    _gmm_means = _gmm_covs = _gmm_weights = None
    _prior_means = _prior_covs = _prior_weights = None
    _pgi_disabled_reason = None
    if _use_pgi and _pgi_alpha > 0.0:
        try:
            # Bootstrap sobre celdas CORE (excluye el padding ~background → no sesga el GMM).
            _gmm_means, _gmm_covs, _gmm_weights = _fit_joint_gmm_2d(
                m_rho[is_core], m_chi[is_core], _pgi_n_classes
            )
            _prior_means = _gmm_means.copy()
            _prior_covs = _gmm_covs.copy()
            _prior_weights = _gmm_weights.copy()
            _log.info(
                f"[FASE 3.1 PGI] GMM 2D bootstrap (K={_pgi_n_classes}) | "
                f"means_rho={np.round(_gmm_means[:, 0], 3).tolist()} | "
                f"means_chi={np.round(_gmm_means[:, 1], 4).tolist()} | dynamic={_pgi_dynamic}"
            )
        except Exception as _gmm_exc:  # sklearn ausente / ajuste degenerado → degradar
            _use_pgi = False
            _pgi_disabled_reason = f"{type(_gmm_exc).__name__}: {_gmm_exc}"
            _log.warning(f"[FASE 3.1 PGI] GMM 2D no disponible, PGI desactivado: {_pgi_disabled_reason}")
    _log.info(
        f"[FASE 3] coupling_mode={_coupling_mode} | use_struct={_use_struct} "
        f"(kind={_struct_kind}) | use_pgi={_use_pgi} | pgi_alpha={_pgi_alpha} | "
        f"pgi_prior_strength={_pgi_prior_strength}"
    )

    # ── Bucle alternado con continuation exponencial ──────────────────────────
    stop_reason = "max_iter_reached"
    E_prev = E_norm
    max_block_nnz = 0
    _pgi_mean_shift = None
    for k in range(1, int(params.joint_max_iter) + 1):
        progress = 0.10 + 0.80 * (k / max(int(params.joint_max_iter), 1))
        _update("running", progress, "joint_loop", f"Inversión conjunta — iteración {k}...")

        # k=1: warm-up sin coupling. k≥2: ramp-up del peso cross-gradient.
        #   'step'  → escalón binario histórico (1.0 fijo).
        #   'log'   → homotopía log-exponencial 0.01→1.0 (cumple el docstring
        #             "continuation exponencial"; evita el salto brusco de misfit).
        # lambda_cross multiplica el peso efectivo abajo (en 'step'=1.0 es byte-idéntico).
        _cont_mode = getattr(params, "joint_continuation_mode", "log")
        if k < 2:
            lambda_cross = 0.0
        elif _cont_mode == "step":
            lambda_cross = 1.0
        else:
            frac = (k - 1) / max(int(params.joint_max_iter) - 1, 1)
            lambda_cross = (1e-2) ** (1.0 - frac)

        # ── FASE 3.1: refit del GMM 2D + referencias PGI por clase (k≥2) ──────
        # Una pasada NIW MAP por iteración (regularizada hacia el prior bootstrap)
        # mueve las clases hacia el dato sin colapsar. La referencia de cada física
        # = centroide 2D de la clase MAP de la celda → smallness petrofísica.
        _pgi_on = _use_pgi and lambda_cross >= 0.0 and k >= 2
        rho_ref_abs = chi_ref = None
        if _pgi_on:
            X_cur = np.column_stack([m_rho, m_chi])
            if _pgi_dynamic:
                resp = gmm_responsibilities_2d(X_cur, _gmm_means, _gmm_covs, _gmm_weights)
                _gmm_means, _gmm_covs, _gmm_weights = niw_map_update_2d(
                    X_cur, resp, _prior_means, _prior_covs, _prior_weights,
                    prior_kappa=_pgi_prior_strength, prior_nu=_pgi_prior_strength,
                )
                _pgi_mean_shift = float(
                    np.linalg.norm(_gmm_means - _prior_means)
                    / max(np.linalg.norm(_prior_means), 1e-12)
                )
            rho_ref_abs, _ = _joint_pgi_class_means(m_rho, m_chi, _gmm_means, _gmm_covs, _gmm_weights)

        # Paso de gravedad: fija χ, penaliza ∇ρ × ∇χ (estructural) y/o ρ → centroide 2D (PGI).
        lambda_cross_eff_g = 0.0
        grav_blocks, grav_rhs = [], []
        if _use_struct and lambda_cross > 0.0:
            hx, hy, hz = _fixed_gradient_dirs(m_chi, Dx, Dy, Dz, _struct_kind)
            B_chi = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            max_block_nnz = max(max_block_nnz, B_chi.nnz)
            B_chi_norm = float(np.sqrt(B_chi.power(2).sum()))
            lambda_cross_eff_g = lambda_cross * cross_beta * G_norm / max(B_chi_norm, 1e-12)
            # Joint v1.1: recortar columnas al dominio observable → B.shape[1] = n_obs_g
            _B_chi_g = B_chi[:, _obs_mask_g] if _do_prune else B_chi
            grav_blocks.append(lambda_cross_eff_g * _B_chi_g)
            grav_rhs.append(np.zeros(_B_chi_g.shape[0], dtype=np.float64))
        if _pgi_on and rho_ref_abs is not None:
            _ref_g = (rho_ref_abs - base_rho)
            _ref_g = _ref_g[_obs_mask_g] if _do_prune else _ref_g
            _n_g = _ref_g.shape[0]
            grav_blocks.append(_sqrt_pgi_alpha * sp.eye(_n_g, format="csr", dtype=np.float64))
            grav_rhs.append(_sqrt_pgi_alpha * _ref_g)
        # Sin bloques → None (path histórico byte-idéntico, extra_reg_rhs ignorado).
        _gb = grav_blocks or None
        _grhs = grav_rhs if grav_blocks else None
        m_rho_new, _gs, misfit_g, meta_g = _solve_gravity(
            _gb, m_rho - base_rho, grav_fwd_kernel_cache, extra_rhs=_grhs
        )

        # Referencia PGI de χ recomputada con ρ ACTUALIZADO (esquema alternado).
        if _pgi_on:
            _, chi_ref = _joint_pgi_class_means(m_rho_new, m_chi, _gmm_means, _gmm_covs, _gmm_weights)

        # Paso de magnetometría: fija ρ (actualizado), penaliza ∇χ × ∇ρ (estructural) y/o χ → centroide 2D (PGI).
        lambda_cross_eff_m = 0.0
        mag_blocks, mag_rhs = [], []
        if _use_struct and lambda_cross > 0.0:
            hx, hy, hz = _fixed_gradient_dirs(m_rho_new, Dx, Dy, Dz, _struct_kind)
            B_rho = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            max_block_nnz = max(max_block_nnz, B_rho.nnz)
            B_rho_norm = float(np.sqrt(B_rho.power(2).sum()))
            lambda_cross_eff_m = lambda_cross * cross_beta * G_norm / max(B_rho_norm, 1e-12)
            mag_blocks.append(lambda_cross_eff_m * B_rho)
            mag_rhs.append(np.zeros(B_rho.shape[0], dtype=np.float64))
        if _pgi_on and chi_ref is not None:
            mag_blocks.append(_sqrt_pgi_alpha * sp.eye(nC, format="csr", dtype=np.float64))
            mag_rhs.append(_sqrt_pgi_alpha * np.asarray(chi_ref, dtype=np.float64))
        _mb = mag_blocks or None
        _mrhs = mag_rhs if mag_blocks else None
        m_chi_new, _ms, misfit_m, meta_m = _solve_magnetic(
            _mb, m_chi, mag_fwd_kernel_cache, extra_rhs=_mrhs
        )

        # Métricas de convergencia.
        delta_rho = _rel_change(m_rho_new, m_rho)
        delta_chi = _rel_change(m_chi_new, m_chi)
        E_curr = _e_norm_cellwise(m_rho_new, m_chi_new, Dx, Dy, Dz)
        E_l2 = _e_norm_global_l2(m_rho_new, m_chi_new, Dx, Dy, Dz)
        dE_rel = abs(E_curr - E_prev) / (E_prev + _RATIO_EPS)

        m_rho, m_chi = m_rho_new, m_chi_new

        history.append({
            "iter": k,
            "lambda_cross_raw": round(float(lambda_cross), 6),
            "lambda_cross": round(float(lambda_cross_eff_g), 6),
            "lambda_cross_eff_m": round(float(lambda_cross_eff_m), 6),
            "E_norm": round(float(E_curr), 6),
            "E_norm_l2_global": round(float(E_l2), 6),
            "delta_rho": round(delta_rho, 6),
            "delta_chi": round(delta_chi, 6),
            "E_norm_rel_change": round(float(dE_rel), 6),
            "misfit_gravity_percent": misfit_g,
            "misfit_magnetic_percent": misfit_m,
            "cond_A_gravity": meta_g.get("acond"),
            "cond_A_magnetic": meta_m.get("acond"),
            "pgi_active": bool(_pgi_on),
            "pgi_mean_shift": round(float(_pgi_mean_shift), 6) if (_pgi_on and _pgi_mean_shift is not None) else None,
        })
        _log.info(f"[FASE 9C-2] k={k:>2} | lambda_eff_g={lambda_cross_eff_g:.4e} | "
              f"lambda_eff_m={lambda_cross_eff_m:.4e} | E_norm={E_curr:.6f} | "
              f"E_l2={E_l2:.6f} | dE_rel={dE_rel:.4e} | delta_rho={delta_rho:.4e} | "
              f"delta_chi={delta_chi:.4e} | misfit_g={misfit_g:.3f}% | misfit_m={misfit_m:.3f}%")

        # Early stopping.
        converged = (delta_rho < _DELTA_TOL and delta_chi < _DELTA_TOL and dE_rel < _E_REL_TOL)
        if converged:
            stop_reason = "converged_delta_and_E"
            _log.info(f"[FASE 9C-2] Parada temprana en k={k}: deltas y dE_norm bajo tolerancia.")
            break
        if E_curr < _E_ABS_TOL:
            stop_reason = "E_norm_below_absolute_tol"
            _log.info(f"[FASE 9C-2] Parada temprana en k={k}: E_norm={E_curr:.4f} < {_E_ABS_TOL}.")
            break
        E_prev = E_curr

    n_iter_done = history[-1]["iter"]
    _update("running", 0.92, "building_payload", "Construyendo bloque 3D conjunto (ρ + χ)...")

    # ── FASE 3.3: reducir al CORE para la salida (descarta celdas de padding) ─
    # El solver y el acoplamiento operaron sobre la malla extendida; el bloque 3D, el
    # clustering y los centroides se calculan SOLO sobre el core (is_core). En el path
    # histórico (sin padding) is_core es todo True → no-op byte-idéntico.
    if _pad_on:
        m_rho = m_rho[is_core]
        m_chi = m_chi[is_core]
        x_c = x_c[is_core]
        y_c = y_c[is_core]
        z_c = z_c[is_core]
    ix, iy, iz = ix_out, iy_out, iz_out

    # ── Empaquetado: densidad y susceptibilidad en la MISMA malla activa ─────
    rho_contrast = m_rho - base_rho
    abs_contrast = np.abs(rho_contrast)
    rho_cut = max(0.02, 0.02 * float(np.max(abs_contrast)) if abs_contrast.size else 0.02)
    susc_cut = max(1e-6, 0.01 * float(np.max(m_chi)) if m_chi.size else 1e-6)
    keep = (abs_contrast >= rho_cut) | (m_chi >= susc_cut)

    # Score combinado normalizado para ranking (estructural, sin física inventada).
    def _norm01(v):
        v = np.asarray(v, dtype=np.float64)
        vmax = float(np.max(v)) if v.size else 0.0
        return v / vmax if vmax > 0 else np.zeros_like(v)

    combined = 0.5 * _norm01(abs_contrast) + 0.5 * _norm01(m_chi)
    kept_idx = np.where(keep)[0]
    kept_idx = kept_idx[np.argsort(-combined[kept_idx])][:8000]

    voxels = []
    for j in kept_idx:
        voxels.append({
            "ix": int(ix[j]), "iy": int(iy[j]), "iz": int(iz[j]),
            "x_m": float(x_c[j]), "y_m": float(y_c[j]), "z_m": float(z_c[j]),
            "density_t_m3": float(m_rho[j]),
            "density_contrast_t_m3": float(rho_contrast[j]),
            "susceptibility_si": float(m_chi[j]),
            "joint_structural_score": round(float(combined[j]), 6),
            "is_active": True,
        })

    best_target = None
    if voxels:
        b = voxels[0]
        best_target = {
            "x_m": b["x_m"], "y_m": b["y_m"], "z_m": b["z_m"],
            "density_t_m3": b["density_t_m3"],
            "susceptibility_si": b["susceptibility_si"],
            "joint_structural_score": b["joint_structural_score"],
        }

    # ── Métricas conjuntas (Fase 10): evidencia numérica de convergencia ─────
    # Centroide de masa: ponderado por el EXCESO de densidad (mass excess, contraste≥0).
    # Centroide de susceptibilidad: ponderado por χ (≥0 por bound). La separación entre
    # ambos cuantifica el desfase estructural ρ↔χ que el cross-gradient intenta alinear.
    centroid_mass = _weighted_centroid(x_c, y_c, z_c, np.clip(rho_contrast, 0.0, None))
    centroid_susc = _weighted_centroid(x_c, y_c, z_c, m_chi)
    centroid_separation_m = None
    if centroid_mass is not None and centroid_susc is not None:
        centroid_separation_m = float(np.sqrt(
            (centroid_mass["x_m"] - centroid_susc["x_m"]) ** 2 +
            (centroid_mass["y_m"] - centroid_susc["y_m"]) ** 2 +
            (centroid_mass["z_m"] - centroid_susc["z_m"]) ** 2
        ))

    joint_metrics = {
        "E_norm_final": history[-1]["E_norm"],
        "E_norm_l2_global_final": history[-1]["E_norm_l2_global"],
        "iterations_done": int(n_iter_done),
        "stop_reason": stop_reason,
        "centroid_mass_m": centroid_mass,
        "centroid_susceptibility_m": centroid_susc,
        "centroid_separation_m": round(centroid_separation_m, 4) if centroid_separation_m is not None else None,
        "note": (
            "E_norm_final = disimilitud estructural cellwise en [0,1] (0 = gradientes de ρ y "
            "χ alineados → misma estructura). centroid_mass_m pondera por exceso de densidad; "
            "centroid_susceptibility_m pondera por susceptibilidad. centroid_separation_m (m) "
            "es el desfase espacial ρ↔χ. Estadísticos descriptivos del modelo ya invertido; "
            "no imponen relación petrofísica ni emiten ley/tonelaje."
        ),
    }

    report = {
        "method": "joint_inversion_cross_gradient_phase9c2",
        "engine": "Alternating Gauss-Newton + exponential continuation (Gallardo–Meju cross-gradient)",
        "is_joint_inversion": True,
        "mesh": {"nx": nx, "ny": ny, "nz": nz, "block_size": dx, "n_active": int(nC_core),
                 "common_core_grid": True,
                 "padding": {
                     "active": bool(_pad_on),
                     "n_pad": int(getattr(params, "joint_n_pad", 5)) if _pad_on else 0,
                     "pad_factor": float(getattr(params, "joint_pad_factor", 1.3)) if _pad_on else None,
                     "padding_kappa": _padding_kappa if _pad_on else None,
                     "n_total_cells": int(nC),
                     "n_core_cells": int(nC_core),
                     "note": ("Fase 3.3: malla compartida con padding (BC física) para ambas "
                              "físicas; reducida al core para el bloque 3D." if _pad_on
                              else "Malla core pelada (sin padding, histórico)."),
                 }},
        "field": {
            "inclination_deg": params.inclination_deg,
            "declination_deg": params.declination_deg,
            "field_intensity_nt": params.field_intensity_nt,
            "field_unit_vector_xyz": meta_m.get("field_unit_vector"),
            "axis_convention": "x=Norte, z=Este, y=profundidad(+abajo)",
        },
        "continuation": {
            "cross_lambda_beta": cross_beta,
            "G_norm_proxy": round(G_norm, 4),
            "schedule": "step: no coupling k=1, coupling activo k>=2; lambda_eff = beta * G_norm / B_norm",
            "joint_max_iter": int(params.joint_max_iter),
            "iterations_done": int(n_iter_done),
            "stop_reason": stop_reason,
            "early_stopping": {
                "delta_tol": _DELTA_TOL, "E_rel_tol": _E_REL_TOL, "E_abs_tol": _E_ABS_TOL,
                "metric": "E_norm cellwise (grid-independiente). E_norm_l2_global se "
                          "reporta solo como trazabilidad del plan (satura en ~1/sqrt(N)).",
            },
        },
        # ── FASE 3.1: acoplamiento conjunto (cross-gradient / PGI dinámico 2D) ──
        "coupling": {
            "mode": _coupling_mode,
            "use_structural": bool(_use_struct),
            "structural_kind": _struct_kind if _use_struct else None,
            "use_cross_gradient": bool(_use_struct and _struct_kind == "cross_gradient"),
            "use_gramian": bool(_use_struct and _struct_kind == "gramian"),
            "use_pgi": bool(_use_pgi),
            "pgi_alpha": _pgi_alpha,
            "pgi_dynamic": bool(_pgi_dynamic),
            "pgi_n_classes": int(_pgi_n_classes) if _use_pgi else None,
            "pgi_prior_strength": _pgi_prior_strength if _use_pgi else None,
            "pgi_disabled_reason": _pgi_disabled_reason,
            "pgi_gmm_means_rho_chi": (
                np.round(_gmm_means, 5).tolist() if (_use_pgi and _gmm_means is not None) else None
            ),
            "note": (
                "cross_gradient acopla ESTRUCTURA con dirección unitaria (escala-invariante); "
                "gramian (Zhdanov) usa el gradiente CRUDO del modelo fijo → pondera por la "
                "magnitud del contraste. pgi_dynamic acopla PETROFÍSICA (centroide 2D ρ-χ por "
                "clase, smallness). El PGI NO impone una relación ρ-χ fija: la mixtura se "
                "bootstrapea del warm-up y se refina con prior NIW; no emite ley ni tonelaje."
            ),
        },
        "convergence_history": history,
        "final": {
            "E_norm": history[-1]["E_norm"],
            "E_norm_l2_global": history[-1]["E_norm_l2_global"],
            "misfit_gravity_percent": history[-1]["misfit_gravity_percent"],
            "misfit_magnetic_percent": history[-1]["misfit_magnetic_percent"],
        },
        # Resumen estadístico conjunto que consumen Gemini y el frontend (Fase 10).
        "joint_metrics": joint_metrics,
        "density_bounds_t_m3": [params.density_min, params.density_max],
        "susceptibility_bounds_si": [params.susc_min, params.susc_max],
        "observation_count": int(len(obs)),
        "anomaly_voxels": len(voxels),
        "disclaimer": (
            "Inversión conjunta (Fase 9C-2): densidad y susceptibilidad recuperadas sobre "
            "la misma malla por acoplamiento ESTRUCTURAL (cross-gradient). El acoplamiento "
            "NO impone relación petrofísica entre ρ y χ; no se emite ley ni tonelaje. "
            "Resolución en profundidad limitada (campos potenciales)."
        ),
    }

    try:
        write_run_report_snapshot(params, report)
    except Exception as _exc:
        _log.warning("joint_report_snapshot_nonfatal", error=str(_exc))

    # ── FASE 10 Parte 2: Cierre del Transport Gap — persistir Parquet ────────
    joint_parquet_path: str | None = None
    try:
        joint_parquet_path = _persist_joint_parquet(
            params=params,
            x_c=x_c, y_c=y_c, z_c=z_c,
            m_rho=m_rho, rho_contrast=rho_contrast, m_chi=m_chi,
            combined=combined, kept_idx=kept_idx,
        )
        report["joint_parquet_path"] = joint_parquet_path
        _log.info("joint_parquet_written", path=joint_parquet_path, voxels=len(kept_idx))
    except Exception as _pq_exc:
        _log.warning("joint_parquet_nonfatal", error=str(_pq_exc))

    # ── HITO 2: Run Manifest joint (provenance audit trail) ───────────────────
    try:
        from pathlib import Path as _Path

        def _git_hash_short() -> str:
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL, timeout=2,
                ).decode().strip()
            except Exception:
                return "unknown"

        _joint_ref = get_run_block_model_reference(
            project_id=params.project_id, run_id=params.run_id
        )
        _joint_run_dir = _joint_ref.path.parent
        _csv_path_joint = _joint_run_dir / RUN_SOURCE_GRAVITY_FILENAME
        _last_hist = history[-1] if history else {}
        write_run_manifest(_joint_run_dir, {
            "schema_version": "v3.0",
            "run_type": "joint",
            "code_version": _git_hash_short(),
            "rng_seed": None,
            "timestamp_utc_start": _joint_start_utc.isoformat(),
            "timestamp_utc_end": datetime.now(timezone.utc).isoformat(),
            "sha256_parquet": sha256_file(_Path(joint_parquet_path)) if joint_parquet_path else None,
            "sha256_csv": sha256_file(_csv_path_joint) if _csv_path_joint.exists() else None,
            "inversion_params": {
                "nx": params.nx, "ny": params.ny, "nz": params.nz,
                "block_size": params.block_size,
                "lambda_mag": params.lambda_mag,
                "alpha_spatial": params.alpha_spatial,
                "cutoff_radius": params.cutoff_radius,
                "joint_max_iter": getattr(params, "joint_max_iter", None),
                "cross_lambda_max": getattr(params, "cross_lambda_max", None),
            },
            "solver_stats": {
                "iterations_done": int(n_iter_done),
                "E_norm_final": float(_last_hist.get("E_norm", float("nan"))),
                "misfit_gravity_percent": float(_last_hist.get("misfit_gravity_percent", float("nan"))),
                "misfit_magnetic_percent": float(_last_hist.get("misfit_magnetic_percent", float("nan"))),
                "n_geological_bodies": None,
            },
        })
    except Exception as _jmfst_exc:
        _log.warning("joint_run_manifest_nonfatal", error=str(_jmfst_exc))
    # ── Fin HITO 2 ────────────────────────────────────────────────────────────

    # ── FASE 10 Parte 3: Clustering — extracción de cuerpos geológicos ───────
    # Llama al módulo de clustering sobre el campo COMPLETO (nC vóxeles) para
    # obtener anomalías discretas compactas listas para el prompt de Gemini.
    anomalies_payload: list = []
    try:
        anomalies_payload = extract_geological_bodies(
            x=x_c, y=y_c, z=z_c,
            density=m_rho,
            susceptibility=m_chi,
            dx=dx, dy=dx, dz=dx,
            threshold=0.45,
            min_voxels=3,
        )
        report["anomalies_payload"] = anomalies_payload
        _log.info("geological_bodies_extracted", n_bodies=len(anomalies_payload))
        _log.info(f"[FASE 10-P3] Cuerpos geológicos detectados: {len(anomalies_payload)}")
        for a in anomalies_payload:
            _log.info(
                f"  {a['anomaly_id']}: {a['voxel_count']} vóxeles | "
                f"vol={a['volume_m3']:.0f} m³ | "
                f"centroide=({a['centroid']['x_m']:.0f}, {a['centroid']['y_m']:.0f}, "
                f"{a['centroid']['z_m']:.0f}) m | "
                f"ρ_mean={a['density_mean']:.3f} t/m³ | "
                f"χ_mean={a['susceptibility_mean']:.5f} SI | "
                f"corr(ρ,χ)={a['density_susceptibility_correlation']}"
            )
    except Exception as _cl_exc:
        _log.warning("geological_bodies_nonfatal", error=str(_cl_exc))
        report["anomalies_payload"] = []

    # ── FASE 10 Parte 4: Interpretación Gemini ────────────────────────────────
    # Llamada LLM bloqueante (~100s, puede reintentar). NO produce el modelo 3D —
    # es interpretación geológica opcional. Por defecto OFF para que el joint
    # devuelva el modelo rápido; activar con JOINT_ENABLE_GEMINI=true.
    # Fase 5 (H-11): era `_os_jg.getenv(...).lower() != "true"`, así que
    # `JOINT_ENABLE_GEMINI=1` NO la encendía y no lo decía. Ahora el vocabulario
    # booleano es uno solo en todo el backend, y un valor ininteligible se queja.
    # (sin alias a propósito: el inventario de la Fase 5 rastrea la variable por el
    # NOMBRE de la función lectora, y un alias la sacaría del censo en silencio.)
    from core.config import env_bool  # noqa: PLC0415
    if not env_bool("JOINT_ENABLE_GEMINI", False):
        report["gemini_interpretation"] = {
            "skipped": True,
            "note": "Interpretación Gemini omitida (JOINT_ENABLE_GEMINI!=true) para "
                    "devolver el modelo 3D sin la latencia del LLM.",
        }
        _log.info("[FASE 10-P4] Gemini: omitido (JOINT_ENABLE_GEMINI!=true).")
    else:
        from services.gemini_agent import request_gemini_interpretation  # noqa: PLC0415
        try:
            gemini_result: dict = request_gemini_interpretation(report)
            report["gemini_interpretation"] = gemini_result
            n_anomalies = len(gemini_result.get("anomalies", []))
            has_error = "error" in gemini_result
            _log.info("gemini_interpretation_done", n_anomalies=n_anomalies, has_error=has_error)
            _log.info(f"[FASE 10-P4] Gemini: interpretación completada "
                  f"({n_anomalies} anomalías, has_error={has_error}).")
        except Exception as _gem_exc:
            _log.warning("gemini_interpretation_nonfatal", error=str(_gem_exc))
            report["gemini_interpretation"] = {
                "error": f"Gemini interpretation unavailable: {_gem_exc}",
                "executive_summary": "",
                "anomalies": [],
                "overall_assessment": "",
                "limitations": "",
            }

    # Escribe el report.json FINAL con anomalies_payload + gemini_interpretation.
    try:
        write_run_report_snapshot(params, report)
    except Exception as _rpt_exc:
        _log.warning("final_report_snapshot_nonfatal", error=str(_rpt_exc))

    misfit_combined = float(np.hypot(
        history[-1]["misfit_gravity_percent"], history[-1]["misfit_magnetic_percent"]
    ))
    _update(
        "done", 1.0, "completed", "Inversión conjunta completada (Fase 9C-2).",
        metrics={
            "E_norm_final": history[-1]["E_norm"],
            "iterations_done": int(n_iter_done),
            "anomaly_voxels": len(voxels),
            "n_geological_bodies": len(anomalies_payload),
            "max_cross_block_nnz": int(max_block_nnz),
        },
    )

    return {
        # projectId/runId al nivel superior: el frontend los necesita para cargar
        # el block model (igual que gravedad/magnético).
        "project_id": params.project_id,
        "run_id": params.run_id,
        "projectId": params.project_id,
        "runId": params.run_id,
        "voxels": voxels,
        "best_target": best_target,
        "report": report,
        "misfit_error_percent": misfit_combined,
    }


# ─────────────────────────────────────────────────────────────────────────────
# QA — Test sintético: dos anomalías DESFASADAS (densidad vs susceptibilidad).
# ─────────────────────────────────────────────────────────────────────────────
def _self_test() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _log.info("=" * 78)
    _log.info("[FASE 9C-2] QA — Inversión conjunta sobre dos anomalías desfasadas.")
    _log.info("=" * 78)

    rng = np.random.default_rng(20260531)

    nx, ny, nz, dx = 14, 12, 14, 50.0
    nC = nx * ny * nz

    ix, iy, iz = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = ix.flatten(order="F"); iy = iy.flatten(order="F"); iz = iz.flatten(order="F")
    x_c = (ix * dx) + dx / 2.0
    y_c = (iy * dx) + dx / 2.0
    z_c = (iz * dx) + dx / 2.0

    # Dos CRESTAS (ridges) que se CRUZAN: la de densidad corre a lo largo de X
    # (gradiente en el plano Y-Z); la de susceptibilidad corre a lo largo de Y
    # (gradiente en el plano X-Z). En la zona de cruce sus gradientes son casi
    # ORTOGONALES → cross-gradient alto al inicio. Es el escenario "desfasado" que
    # obliga al acoplamiento estructural a iterar para alinear los bordes.
    def _ridge(axis, ca, cb, radius, amp):
        # axis="x": cresta a lo largo de X (varía en Y,Z); axis="y": a lo largo de Y.
        if axis == "x":
            d2 = (y_c - ca) ** 2 + (z_c - cb) ** 2
        else:
            d2 = (x_c - ca) ** 2 + (z_c - cb) ** 2
        return amp * np.exp(-d2 / (2.0 * radius ** 2))

    rho_true = 2.6 + _ridge("x", ny * dx * 0.45, nz * dx * 0.50, radius=1.3 * dx, amp=0.8)
    susc_true = _ridge("y", nx * dx * 0.55, nz * dx * 0.50, radius=1.3 * dx, amp=0.6)

    # Sensores: malla 7×7 sobre la superficie (1 celda por encima del techo).
    sx = np.linspace(0.5 * dx, (nx - 0.5) * dx, 7)
    sz = np.linspace(0.5 * dx, (nz - 0.5) * dx, 7)
    SX, SZ = np.meshgrid(sx, sz)
    sensors = np.column_stack([SX.ravel(), np.full(SX.size, -dx), SZ.ravel()])

    cutoff = (nx + nz) * dx
    grav_fwd = GravimetryForward(dx, dx, dx, cutoff_radius=cutoff)
    mag_fwd = MagnetometryForward(dx, dx, dx, cutoff_radius=cutoff,
                                  inclination_deg=-30.0, declination_deg=2.0,
                                  field_intensity_nt=23500.0)

    Kg = grav_fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    Km = mag_fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_clean = Kg @ (rho_true - 2.6)
    tmi_clean = Km @ susc_true

    # Ruido 1.5% del rango dinámico — para que el ajuste no sea trivialmente exacto.
    g_obs = g_clean + 0.015 * (g_clean.max() - g_clean.min()) * rng.standard_normal(g_clean.size)
    tmi_obs = tmi_clean + 0.015 * (tmi_clean.max() - tmi_clean.min()) * rng.standard_normal(tmi_clean.size)

    _log.info(f"  malla core: {nx}×{ny}×{nz} = {nC:,} celdas | dx={dx} m | sensores={sensors.shape[0]}")
    _log.info(f"  g_obs   rango=[{g_obs.min():.3e}, {g_obs.max():.3e}]")
    _log.info(f"  tmi_obs rango=[{tmi_obs.min():.3e}, {tmi_obs.max():.3e}]")

    observations = [
        {"x_m": float(sensors[i, 0]), "y_m": float(sensors[i, 1]),
         "z_m": float(sensors[i, 2]), "g": float(g_obs[i])}
        for i in range(sensors.shape[0])
    ]

    params = GeophysicsInvertInput(
        depth=int(ny * dx // 2), nir=50, fe=50, region="norte_chile",
        lat="-23.5", lon="-69.0",
        nx=nx, ny=ny, nz=nz, block_size=int(dx),
        cutoff_radius=float(cutoff), lambda_mag=1e-3, alpha_spatial=1.0,
        observations=observations,
        magnetic_nt=[float(v) for v in tmi_obs],
        inclination_deg=-30.0, declination_deg=2.0, field_intensity_nt=23500.0,
        susc_min=0.0, susc_max=1.0,
        density_min=2.6, density_max=4.2,
        joint_max_iter=15, cross_lambda_max=1e4,
    )

    result = run_joint_inversion(params)
    rep = result["report"]

    _log.info("-" * 78)
    _log.info(f"  iteraciones ejecutadas : {rep['continuation']['iterations_done']}")
    _log.info(f"  stop_reason            : {rep['continuation']['stop_reason']}")
    _log.info(f"  E_norm final           : {rep['final']['E_norm']}")
    _log.info(f"  misfit gravedad        : {rep['final']['misfit_gravity_percent']:.3f} %")
    _log.info(f"  misfit magnetometría   : {rep['final']['misfit_magnetic_percent']:.3f} %")
    _log.info(f"  vóxeles anómalos        : {rep['anomaly_voxels']}")
    bt = result["best_target"]
    if bt:
        _log.info(f"  best_target            : x={bt['x_m']:.0f} y={bt['y_m']:.0f} z={bt['z_m']:.0f} "
              f"| rho={bt['density_t_m3']:.3f} t/m3 | chi={bt['susceptibility_si']:.4f} SI")

    # ── Aserciones de salud (no explota, converge, malla común) ──────────────
    assert rep["is_joint_inversion"] is True
    assert rep["mesh"]["n_active"] == nC
    E_first = rep["convergence_history"][0]["E_norm"]
    E_last = rep["final"]["E_norm"]
    assert np.isfinite(E_last)
    assert len(result["voxels"]) > 0, "El bloque conjunto no debe quedar vacío."
    for v in result["voxels"][:5]:
        assert "density_t_m3" in v and "susceptibility_si" in v

    # ── Aserciones de clustering (Fase 10-P3) ────────────────────────────────
    bodies = rep.get("anomalies_payload", [])
    assert isinstance(bodies, list), "anomalies_payload debe ser una lista."
    assert len(bodies) >= 1, (
        f"Se esperaba >= 1 cuerpo geológico detectado; se obtuvo {len(bodies)}. "
        "Revisar threshold o datos sintéticos."
    )
    for body in bodies:
        assert "anomaly_id" in body
        assert body["voxel_count"] >= 1  # función ya aplica min_voxels internamente
        assert body["volume_m3"] > 0
        assert "centroid" in body and "x_m" in body["centroid"]
        assert np.isfinite(body["density_mean"])
        assert np.isfinite(body["susceptibility_mean"])

    _log.info("-" * 78)
    _log.info(f"  Cuerpos geologicos detectados: {len(bodies)}")
    for body in bodies:
        _log.info(
            f"    {body['anomaly_id']}: {body['voxel_count']} vox | "
            f"vol={body['volume_m3']:.0f} m3 | "
            f"centroide=({body['centroid']['x_m']:.0f}, {body['centroid']['y_m']:.0f}, "
            f"{body['centroid']['z_m']:.0f}) m | "
            f"rho_mean={body['density_mean']:.3f} | chi_mean={body['susceptibility_mean']:.5f}"
        )
    _trend = "BAJO (mejor acoplamiento estructural)" if E_last <= E_first else "subio"
    _log.info(f"  E_norm warm-up={E_first:.6f} -> final={E_last:.6f} ({_trend})")
    _log.info("RESULT: ALL OK - clustering y orquestador terminaron limpiamente.")


if __name__ == "__main__":
    _self_test()
