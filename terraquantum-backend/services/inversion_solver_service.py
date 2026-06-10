"""
Inversion Solver Service — Fase 2 (Plan Industrial Tier 1, §2.1)

Módulo aislado con el wrapper del solver LSQR con heartbeat.
Extraído de geophysics_service.py para separación de responsabilidades.
geophysics_service.py importa desde aquí y re-exporta para compatibilidad.
"""
import threading

from core.block_model_store import update_run_status
from core.logging import get_logger

_log = get_logger(__name__)


def _run_lsqr_with_heartbeat(
    inversor,
    g_observed,
    kernel_sparse,          # obsoleto — pasar None; conservado para compatibilidad de firma
    y_c,
    lambda_mag: float,
    alpha_spatial: float,
    project_id,
    run_id,
    forward_model=None,     # F0.2 HPC requerido
    sensor_coords=None,     # F0.2 HPC requerido
    x_c=None,               # F0.2 HPC requerido
    z_c=None,               # F0.2 HPC requerido
    topography_elevations=None,
    # ── F0.9: Tensor Mesh — anchos de celda para Laplaciano no-uniforme ──────
    hx=None,
    hy=None,
    hz=None,
    # ── DOI: modelo de referencia (Li & Oldenburg 1999) ──────────────────────
    m_ref=None,
    # ── Bound petrofísico de densidad (t/m³) — P2: configurable desde API ────
    density_min: float = 2.6,
    density_max: float = 5.5,   # H-A0 Bug 3: cubre magnetita (5.0-5.2), cromita (4.5-4.8)
    # ── R-02: Penalización diferencial de padding (auditoría R-A1) ───────────
    padding_mask=None,     # shape=(total_voxels,) bool; True = celda de padding
    padding_kappa=1e5,     # κ = factor de penalización (1e5 post-auditoría R-A1)
    # ── FASE 8 (Q4): Anclaje por sondajes (boreholes) ─────────────────────────
    boreholes=None,        # array (n,5) [x_m, z_m, y_from_m, y_to_m, density_t_m3] o None
    anchor_kappa=1e4,      # strong soft constraint (NO 1e6: preserva cond(A))
    laplacian_relax_alpha=0.2,  # relajación de filas del Laplaciano en vóxeles anclados
    # ── Fase 2: sigma de ruido configurable por gravímetro ────────────────────
    # noise_floor en mismas unidades que g_observed (m/s² para el pipeline de import).
    # Default 0.02 activa _sigma_adaptive (equivalente al comportamiento v1).
    noise_floor: float = 0.02,
    noise_pct: float = 0.02,
    # ── Diagnósticos del solver (OUT) ─────────────────────────────────────────
    solver_meta=None,      # dict mutable; el solver escribe acond, chi2_final, etc.
):
    """Ejecuta solve_inversion_lsqr (Motor HPC F0.2 + Tensor Mesh F0.9) con heartbeat cada 5 s."""
    stop_event = threading.Event()

    def _heartbeat():
        while not stop_event.is_set():
            if project_id and run_id:
                try:
                    update_run_status(
                        project_id=project_id,
                        run_id=run_id,
                        status="running",
                        progress=0.40,
                        stage="solving_lsqr",
                        message="LSQR solver HPC F0.2 + Tensor Mesh F0.9 en progreso...",
                    )
                except Exception:
                    pass
            stop_event.wait(timeout=5.0)

    hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()
    try:
        result = inversor.solve_inversion_lsqr(
            g_observed,
            None,                       # kernel_sparse — HPC F0.2 exclusivo; no se usa
            y_c=y_c,
            lambda_mag=lambda_mag,
            alpha_spatial=alpha_spatial,
            topography_elevations=topography_elevations,
            forward_model=forward_model,
            sensor_coords=sensor_coords,
            x_c=x_c,
            z_c=z_c,
            hx=hx,                      # F0.9: Laplaciano no-uniforme
            hy=hy,
            hz=hz,
            m_ref=m_ref,                # DOI: modelo de referencia (None = sin referencia)
            density_min=density_min,    # P2: bound petrofísico configurable desde API
            density_max=density_max,
            padding_mask=padding_mask,  # R-02: penalización diferencial de padding
            padding_kappa=padding_kappa,
            boreholes=boreholes,        # FASE 8: anclaje por sondajes
            anchor_kappa=anchor_kappa,
            laplacian_relax_alpha=laplacian_relax_alpha,
            noise_floor=noise_floor,    # Fase 2: sigma configurable por gravímetro
            noise_pct=noise_pct,
            solver_meta=solver_meta,    # OUT: acond, chi2_final, saturación
        )
    finally:
        stop_event.set()
        hb_thread.join(timeout=2.0)
    return result
