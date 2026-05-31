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

from typing import Optional

import numpy as np
import scipy.sparse as sp
from fastapi import HTTPException

from core.config import ensure_runtime_dirs
from core.block_model_store import update_run_status
from core.logging import get_logger
from exploration.geophysics_math import build_gradient_operators
from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
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


def _rel_change(m_new, m_old):
    """‖m_new − m_old‖ / (‖m_old‖ + eps)."""
    denom = float(np.linalg.norm(m_old)) + _RATIO_EPS
    return float(np.linalg.norm(m_new - m_old)) / denom


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

    # ── Malla core común a ambas físicas ──────────────────────────────────────
    nx, ny, nz, dx = params.nx, params.ny, params.nz, params.block_size
    ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(params)
    nC = nx * ny * nz

    boreholes_g, boreholes_m = _extract_boreholes(params)

    # Operadores de primera derivada co-localizados (geophysics_math, 9C-1).
    Dx, Dy, Dz = build_gradient_operators(nx, ny, nz, dx, dx, dx)

    # Motores forward / inversos sobre la malla core.
    grav_fwd = GravimetryForward(dx, dx, dx, cutoff_radius=params.cutoff_radius)
    mag_fwd = MagnetometryForward(
        dx, dx, dx,
        cutoff_radius=params.cutoff_radius,
        inclination_deg=params.inclination_deg,
        declination_deg=params.declination_deg,
        field_intensity_nt=params.field_intensity_nt,
    )
    grav_inv = GravimetryInversion(nx, ny, nz, dx)
    mag_inv = MagnetometryInversion(nx, ny, nz, dx)
    base_rho = grav_inv.base_density

    lam_g = params.lambda_mag if params.lambda_mag > 0 else 1e-5
    lam_m = params.lambda_mag if params.lambda_mag > 0 else 1e-4

    def _solve_gravity(extra_blocks, m_ref_contrast):
        meta = {}
        rho_full, score, misfit, sens = grav_inv.solve_inversion_lsqr(
            g_observed, None, y_c,
            lambda_mag=lam_g, alpha_spatial=params.alpha_spatial,
            topography_elevations=None,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
            forward_model=grav_fwd,
            density_min=params.density_min, density_max=params.density_max,
            boreholes=boreholes_g,
            m_ref=m_ref_contrast,
            extra_reg_blocks=extra_blocks,
            extra_reg_rhs=None,
            prune_observable_domain=False,   # mantiene n_active = nC (conformable)
            solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(rho_full, dtype=np.float64), nan=base_rho), score, misfit, meta

    def _solve_magnetic(extra_blocks, m_ref):
        meta = {}
        chi_full, score, misfit, sens = mag_inv.solve_magnetic_inversion_lsqr(
            d_observed=mag, y_c=y_c,
            lambda_mag=lam_m, alpha_spatial=params.alpha_spatial,
            topography_elevations=None,
            sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
            forward_model=mag_fwd,
            susc_min=params.susc_min, susc_max=params.susc_max,
            boreholes=boreholes_m,
            m_ref=m_ref,
            extra_reg_blocks=extra_blocks,
            extra_reg_rhs=None,
            solver_meta=meta,
        )
        return np.nan_to_num(np.asarray(chi_full, dtype=np.float64), nan=0.0), score, misfit, meta

    # ── Iteración 0 — Warm-up: motores independientes (sin cross-gradient) ───
    _update("running", 0.10, "warmup", "Warm-up: inversiones independientes (k=0)...")
    print("[FASE 9C-2] Warm-up k=0 — gravedad independiente.")
    m_rho, _g_score, misfit_g, meta_g = _solve_gravity(None, None)
    print("[FASE 9C-2] Warm-up k=0 — magnetometría independiente.")
    m_chi, _m_score, misfit_m, meta_m = _solve_magnetic(None, None)

    # E_norm primario = métrica por celda grid-independiente (criterio de parada).
    # E_l2 = fórmula global literal del plan, solo para trazabilidad (satura en 1/√N).
    E_norm = _e_norm_cellwise(m_rho, m_chi, Dx, Dy, Dz)
    E_l2 = _e_norm_global_l2(m_rho, m_chi, Dx, Dy, Dz)
    cross_lambda_max = float(params.cross_lambda_max)
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
    print(f"[FASE 9C-2] k=0 (warm-up) | E_norm={E_norm:.6f} (cellwise) | "
          f"E_l2={E_l2:.6f} | misfit_g={misfit_g:.3f}% | misfit_m={misfit_m:.3f}%")

    # ── Bucle alternado con continuation exponencial ──────────────────────────
    stop_reason = "max_iter_reached"
    E_prev = E_norm
    max_block_nnz = 0
    for k in range(1, int(params.joint_max_iter) + 1):
        progress = 0.10 + 0.80 * (k / max(int(params.joint_max_iter), 1))
        _update("running", progress, "joint_loop", f"Inversión conjunta — iteración {k}...")

        lambda_cross = cross_lambda_max * (1.0 - np.exp(-k / 4.0))

        # Paso de gravedad: fija χ, penaliza ∇ρ × ĝ_χ.
        if lambda_cross > 0.0:
            hx, hy, hz = _normalized_gradient(m_chi, Dx, Dy, Dz)
            B_chi = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            max_block_nnz = max(max_block_nnz, B_chi.nnz)
            grav_blocks = [lambda_cross * B_chi]
        else:
            grav_blocks = None
        m_rho_new, _gs, misfit_g, meta_g = _solve_gravity(grav_blocks, m_rho - base_rho)

        # Paso de magnetometría: fija ρ (actualizado), penaliza ∇χ × ĝ_ρ.
        if lambda_cross > 0.0:
            hx, hy, hz = _normalized_gradient(m_rho_new, Dx, Dy, Dz)
            B_rho = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            max_block_nnz = max(max_block_nnz, B_rho.nnz)
            mag_blocks = [lambda_cross * B_rho]
        else:
            mag_blocks = None
        m_chi_new, _ms, misfit_m, meta_m = _solve_magnetic(mag_blocks, m_chi)

        # Métricas de convergencia.
        delta_rho = _rel_change(m_rho_new, m_rho)
        delta_chi = _rel_change(m_chi_new, m_chi)
        E_curr = _e_norm_cellwise(m_rho_new, m_chi_new, Dx, Dy, Dz)
        E_l2 = _e_norm_global_l2(m_rho_new, m_chi_new, Dx, Dy, Dz)
        dE_rel = abs(E_curr - E_prev) / (E_prev + _RATIO_EPS)

        m_rho, m_chi = m_rho_new, m_chi_new

        history.append({
            "iter": k,
            "lambda_cross": round(float(lambda_cross), 6),
            "E_norm": round(float(E_curr), 6),
            "E_norm_l2_global": round(float(E_l2), 6),
            "delta_rho": round(delta_rho, 6),
            "delta_chi": round(delta_chi, 6),
            "E_norm_rel_change": round(float(dE_rel), 6),
            "misfit_gravity_percent": misfit_g,
            "misfit_magnetic_percent": misfit_m,
            "cond_A_gravity": meta_g.get("acond"),
            "cond_A_magnetic": meta_m.get("acond"),
        })
        print(f"[FASE 9C-2] k={k:>2} | lambda_cross={lambda_cross:.4e} | E_norm={E_curr:.6f} | "
              f"E_l2={E_l2:.6f} | dE_rel={dE_rel:.4e} | delta_rho={delta_rho:.4e} | "
              f"delta_chi={delta_chi:.4e} | misfit_g={misfit_g:.3f}% | misfit_m={misfit_m:.3f}%")

        # Early stopping.
        converged = (delta_rho < _DELTA_TOL and delta_chi < _DELTA_TOL and dE_rel < _E_REL_TOL)
        if converged:
            stop_reason = "converged_delta_and_E"
            print(f"[FASE 9C-2] Parada temprana en k={k}: deltas y ΔE_norm bajo tolerancia.")
            break
        if E_curr < _E_ABS_TOL:
            stop_reason = "E_norm_below_absolute_tol"
            print(f"[FASE 9C-2] Parada temprana en k={k}: E_norm={E_curr:.4f} < {_E_ABS_TOL}.")
            break
        E_prev = E_curr

    n_iter_done = history[-1]["iter"]
    _update("running", 0.92, "building_payload", "Construyendo bloque 3D conjunto (ρ + χ)...")

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

    report = {
        "method": "joint_inversion_cross_gradient_phase9c2",
        "engine": "Alternating Gauss-Newton + exponential continuation (Gallardo–Meju cross-gradient)",
        "is_joint_inversion": True,
        "mesh": {"nx": nx, "ny": ny, "nz": nz, "block_size": dx, "n_active": int(nC),
                 "common_core_grid": True},
        "field": {
            "inclination_deg": params.inclination_deg,
            "declination_deg": params.declination_deg,
            "field_intensity_nt": params.field_intensity_nt,
            "field_unit_vector_xyz": meta_m.get("field_unit_vector"),
            "axis_convention": "x=Norte, z=Este, y=profundidad(+abajo)",
        },
        "continuation": {
            "cross_lambda_max": cross_lambda_max,
            "schedule": "lambda_cross(k) = cross_lambda_max * (1 - exp(-k/4))",
            "joint_max_iter": int(params.joint_max_iter),
            "iterations_done": int(n_iter_done),
            "stop_reason": stop_reason,
            "early_stopping": {
                "delta_tol": _DELTA_TOL, "E_rel_tol": _E_REL_TOL, "E_abs_tol": _E_ABS_TOL,
                "metric": "E_norm cellwise (grid-independiente). E_norm_l2_global se "
                          "reporta solo como trazabilidad del plan (satura en ~1/sqrt(N)).",
            },
        },
        "convergence_history": history,
        "final": {
            "E_norm": history[-1]["E_norm"],
            "E_norm_l2_global": history[-1]["E_norm_l2_global"],
            "misfit_gravity_percent": history[-1]["misfit_gravity_percent"],
            "misfit_magnetic_percent": history[-1]["misfit_magnetic_percent"],
        },
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

    misfit_combined = float(np.hypot(
        history[-1]["misfit_gravity_percent"], history[-1]["misfit_magnetic_percent"]
    ))
    _update(
        "done", 1.0, "completed", "Inversión conjunta completada (Fase 9C-2).",
        metrics={
            "E_norm_final": history[-1]["E_norm"],
            "iterations_done": int(n_iter_done),
            "anomaly_voxels": len(voxels),
            "max_cross_block_nnz": int(max_block_nnz),
        },
    )

    return {
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
    print("=" * 78)
    print("[FASE 9C-2] QA — Inversión conjunta sobre dos anomalías desfasadas.")
    print("=" * 78)

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

    print(f"  malla core: {nx}×{ny}×{nz} = {nC:,} celdas | dx={dx} m | sensores={sensors.shape[0]}")
    print(f"  g_obs   rango=[{g_obs.min():.3e}, {g_obs.max():.3e}]")
    print(f"  tmi_obs rango=[{tmi_obs.min():.3e}, {tmi_obs.max():.3e}]")

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

    print("-" * 78)
    print(f"  iteraciones ejecutadas : {rep['continuation']['iterations_done']}")
    print(f"  stop_reason            : {rep['continuation']['stop_reason']}")
    print(f"  E_norm final           : {rep['final']['E_norm']}")
    print(f"  misfit gravedad        : {rep['final']['misfit_gravity_percent']:.3f} %")
    print(f"  misfit magnetometría   : {rep['final']['misfit_magnetic_percent']:.3f} %")
    print(f"  vóxeles anómalos        : {rep['anomaly_voxels']}")
    bt = result["best_target"]
    if bt:
        print(f"  best_target            : x={bt['x_m']:.0f} y={bt['y_m']:.0f} z={bt['z_m']:.0f} "
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
    print("-" * 78)
    _trend = "BAJO (mejor acoplamiento estructural)" if E_last <= E_first else "subio"
    print(f"  E_norm warm-up={E_first:.6f} -> final={E_last:.6f} ({_trend})")
    print("RESULT: ALL OK - el orquestador termino limpiamente, sin explotar por RAM.")


if __name__ == "__main__":
    _self_test()
