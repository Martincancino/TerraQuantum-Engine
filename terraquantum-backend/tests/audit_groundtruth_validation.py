"""
AUDIT — VALIDACIÓN CONTRA VERDAD-TERRENO ANALÍTICA (sin inverse crime)
=====================================================================
Artefacto de AUDITORÍA INDUSTRIAL. NO reimplementa física: usa EXCLUSIVAMENTE
el motor real (exploration/gravimetry.py).

Objetivo
--------
Validar el motor gravimétrico de TerraQuantum contra una solución ANALÍTICA
EXACTA (no contra sí mismo). Una esfera homogénea genera, fuera de su volumen,
un campo gravitatorio IDÉNTICO al de una masa puntual en su centro
(teorema de la capa esférica de Newton). Esa es la verdad-terreno.

Dos pruebas:
  PARTE A — Validación del OPERADOR FORWARD (kernel Nagy + ensamblaje + unidades)
           contra la fórmula analítica de la esfera. Pass/fail objetivo.
  PARTE B — Validación de la INVERSIÓN. Los datos observados se generan con la
           fórmula ANALÍTICA (no con el kernel del motor) → evita "inverse crime".
           Se mide recuperación de posición, profundidad, masa anómala y forma.

Convención de unidades del motor (verificada en gravimetry.py):
  g [m/s² SI] = G(6.67430e-11) * 1000 * (densidad t/m³) * geometría
  mGal = g * 1e5

Uso:
  python tests/audit_groundtruth_validation.py
"""
from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime, timezone

import numpy as np

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("audit.groundtruth")

# Constante gravitacional — DEBE coincidir con la del motor para comparar peras con peras
G_SI = 6.67430e-11
RNG_SEED = 42

# ── Geometría del experimento ───────────────────────────────────────────────
NX, NY, NZ   = 20, 12, 20           # 4800 vóxeles
BLOCK        = 25.0                  # m por celda → dominio 500 x 300(prof) x 500 m
CONTRAST     = 0.6                   # t/m³ (cuerpo denso; dentro del clip [2.6,4.2])
SPH_CENTER   = (250.0, 140.0, 250.0)  # (x, y=profundidad, z) en m
SPH_RADIUS   = 70.0                  # m
NOISE_PCT    = 0.03                  # 3% del RMS de señal (ruido gaussiano realista)
CUTOFF       = 1500.0                # m (mayor que el dominio → sin truncamiento espurio)


def build_sphere_contrast(x_c, y_c, z_c, center, radius, contrast):
    """Vector de contraste verdadero: contrast dentro de la esfera, 0 fuera."""
    cx, cy, cz = center
    dist = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    m = np.zeros_like(x_c, dtype=np.float64)
    m[dist <= radius] = contrast
    return m


def analytic_sphere_gravity(sensor_coords, center, radius, contrast):
    """
    Gravedad vertical (componente y, hacia abajo) EXACTA de una esfera homogénea,
    válida para sensores FUERA de la esfera (Newton). Misma convención que el motor:
        g = G * 1000 * Δρ[t/m³] * V[m³] * Δy / r³     [m/s² SI]
    """
    cx, cy, cz = center
    V = (4.0 / 3.0) * np.pi * radius ** 3            # volumen [m³]
    xs, ys, zs = sensor_coords[:, 0], sensor_coords[:, 1], sensor_coords[:, 2]
    dx = xs - cx
    dy = cy - ys                                      # profundidad de la masa bajo el sensor (+)
    dz = zs - cz
    r = np.sqrt(dx ** 2 + (ys - cy) ** 2 + dz ** 2)
    g = G_SI * 1000.0 * contrast * V * dy / (r ** 3)
    return g.astype(np.float64)


def center_of_mass(contrast_full, x_c, y_c, z_c):
    """Centro de masa ponderado por contraste positivo (solo celdas finitas)."""
    w = np.nan_to_num(contrast_full, nan=0.0)
    w = np.clip(w, 0.0, None)
    tot = w.sum()
    if tot <= 0:
        return None, 0.0
    cm = (float((w * x_c).sum() / tot),
          float((w * y_c).sum() / tot),
          float((w * z_c).sum() / tot))
    return cm, float(tot)


def main():
    np.random.seed(RNG_SEED)
    t0 = datetime.now(timezone.utc)
    log.info("=" * 70)
    log.info("AUDITORÍA — Validación contra verdad-terreno analítica (esfera)")
    log.info("=" * 70)

    # ── Malla y sensores (helpers reales del motor) ─────────────────────────
    _, _, _, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, BLOCK)
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)
    log.info(f"Malla: {NX}x{NY}x{NZ} = {NX*NY*NZ} vóxeles | sensores: {len(sensors)}")

    true_contrast = build_sphere_contrast(x_c, y_c, z_c, SPH_CENTER, SPH_RADIUS, CONTRAST)
    n_in = int((true_contrast > 0).sum())
    true_mass_t = CONTRAST * (4.0/3.0) * np.pi * SPH_RADIUS**3        # masa anómala analítica [t]
    log.info(f"Esfera: centro={SPH_CENTER} R={SPH_RADIUS}m Δρ={CONTRAST} t/m³ | "
             f"{n_in} vóxeles dentro | masa anómala analítica ~ {true_mass_t:,.0f} t")

    # =====================================================================
    # PARTE A — VALIDACIÓN DEL OPERADOR FORWARD vs ANALÍTICO
    # =====================================================================
    log.info("-" * 70)
    log.info("PARTE A — Forward del motor (kernel Nagy + masa puntual) vs analítico")
    forward = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=CUTOFF)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)

    g_engine = np.asarray(kernel @ true_contrast, dtype=np.float64)   # esfera discretizada
    g_analytic = analytic_sphere_gravity(sensors, SPH_CENTER, SPH_RADIUS, CONTRAST)

    rel = np.abs(g_engine - g_analytic) / np.maximum(np.abs(g_analytic), 1e-30)
    rms_rel = float(np.sqrt(np.mean(((g_engine - g_analytic) / np.maximum(np.abs(g_analytic), 1e-30)) ** 2)))
    max_rel = float(np.max(rel))
    corr = float(np.corrcoef(g_engine, g_analytic)[0, 1])
    log.info(f"[A] g_analytic: max={np.max(np.abs(g_analytic))*1e5:.4f} mGal")
    log.info(f"[A] g_engine  : max={np.max(np.abs(g_engine))*1e5:.4f} mGal")
    log.info(f"[A] Error relativo  RMS={rms_rel*100:.3f}%  máx={max_rel*100:.3f}%  | corr={corr:.6f}")
    forward_pass = (corr > 0.999) and (rms_rel < 0.08)
    log.info(f"[A] RESULTADO FORWARD: {'PASS' if forward_pass else 'FAIL'} "
             f"(criterio: corr>0.999 y RMS_rel<8%)")

    # =====================================================================
    # PARTE B — INVERSIÓN desde datos ANALÍTICOS (sin inverse crime)
    # =====================================================================
    log.info("-" * 70)
    log.info("PARTE B — Inversión desde datos ANALÍTICOS (independientes del kernel)")
    signal_rms = float(np.sqrt(np.mean(g_analytic ** 2)))
    noise_sigma = NOISE_PCT * signal_rms
    g_obs = g_analytic + np.random.normal(0.0, noise_sigma, size=g_analytic.shape)
    snr_db = 10.0 * np.log10(max(signal_rms**2 / noise_sigma**2, 1e-30))
    log.info(f"[B] Señal RMS={signal_rms*1e5:.4f} mGal | ruido σ={noise_sigma*1e5:.4f} mGal "
             f"({NOISE_PCT*100:.0f}%) | SNR={snr_db:.1f} dB")

    inversor = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)

    lam = 1e-4
    try:
        lc = inversor.select_lambda_lcurve(
            g_observed=g_obs, y_c=y_c, forward_model=forward, sensor_coords=sensors,
            x_c=x_c, z_c=z_c, n_trials=8, lambda_min=1e-6, lambda_max=1e-1,
            alpha_spatial=1.0, noise_floor=noise_sigma, noise_pct=0.0,
        )
        lam = lc["lambda_selected"]
        log.info(f"[B] L-Curve λ óptimo = {lam:.3e} (corner {lc['corner_index']}/{lc['n_trials']-1})")
    except Exception as e:
        log.warning(f"[B] L-Curve falló ({e}); uso λ={lam:.1e}")

    est_density, probability, misfit_pct, sensitivity = inversor.solve_inversion_lsqr(
        g_observed=g_obs, kernel_sparse=None, y_c=y_c, lambda_mag=lam, alpha_spatial=1.0,
        forward_model=forward, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        noise_floor=noise_sigma, noise_pct=0.0,
    )

    est_contrast = est_density - inversor.base_density            # quitar densidad base
    # Chi² reducido (convención del motor: φ_d / N)
    g_pred = analytic_sphere_gravity  # no usado; misfit ya viene del solver
    chi2_red = float(np.sum(((g_obs - (kernel @ np.nan_to_num(est_contrast, nan=0.0)))/noise_sigma)**2) / len(g_obs))

    # Métricas de recuperación
    cm_true, _ = center_of_mass(true_contrast, x_c, y_c, z_c)
    cm_est, mass_w = center_of_mass(est_contrast, x_c, y_c, z_c)
    depth_err = abs(cm_est[1] - cm_true[1]) if cm_est else float("nan")
    horiz_err = (np.hypot(cm_est[0]-cm_true[0], cm_est[2]-cm_true[2]) if cm_est else float("nan"))

    # Masa anómala recuperada: Σ contraste * volumen de celda
    vox_vol = BLOCK ** 3
    est_mass_t = float(np.nansum(np.clip(est_contrast, 0.0, None)) * vox_vol)
    mass_ratio = est_mass_t / true_mass_t if true_mass_t else float("nan")

    # Correlación forma recuperada vs verdad (sobre celdas finitas)
    finite = np.isfinite(est_contrast)
    shape_corr = float(np.corrcoef(np.nan_to_num(est_contrast[finite]), true_contrast[finite])[0, 1])

    log.info("-" * 70)
    log.info(f"[B] Misfit datos        : {misfit_pct:.2f}%   | chi²_red={chi2_red:.3f} (ideal≈1)")
    log.info(f"[B] Centro VERDAD (x,y,z): ({cm_true[0]:.0f}, {cm_true[1]:.0f}, {cm_true[2]:.0f}) m")
    log.info(f"[B] Centro RECUPERADO    : ({cm_est[0]:.0f}, {cm_est[1]:.0f}, {cm_est[2]:.0f}) m")
    log.info(f"[B] Error PROFUNDIDAD    : {depth_err:.1f} m  ({depth_err/SPH_CENTER[1]*100:.1f}% de la prof. real)")
    log.info(f"[B] Error HORIZONTAL     : {horiz_err:.1f} m")
    log.info(f"[B] Masa anómala verdad  : {true_mass_t:,.0f} t")
    log.info(f"[B] Masa anómala recup.  : {est_mass_t:,.0f} t  (ratio={mass_ratio:.2f})")
    log.info(f"[B] Correlación de forma : r={shape_corr:.3f}")

    invert_pass = (depth_err < 1.5*BLOCK) and (horiz_err < 1.5*BLOCK) and (shape_corr > 0.4)
    log.info(f"[B] RESULTADO INVERSIÓN  : {'PASS' if invert_pass else 'FAIL'} "
             f"(criterio: errores < 1.5 celdas y corr_forma > 0.4)")

    # ── Certificado JSON ────────────────────────────────────────────────────
    cert = {
        "audit": "groundtruth_analytic_sphere",
        "timestamp_utc": t0.isoformat(),
        "engine": "exploration/gravimetry.py (no reimplementation)",
        "inverse_crime": False,
        "geometry": {"nx": NX, "ny": NY, "nz": NZ, "block_m": BLOCK,
                     "sphere_center_m": SPH_CENTER, "sphere_radius_m": SPH_RADIUS,
                     "contrast_t_m3": CONTRAST},
        "part_A_forward": {"corr": corr, "rms_rel_pct": rms_rel*100,
                           "max_rel_pct": max_rel*100, "pass": forward_pass},
        "part_B_inversion": {"lambda": lam, "snr_db": snr_db, "misfit_pct": misfit_pct,
                             "chi2_reduced": chi2_red, "depth_error_m": depth_err,
                             "horiz_error_m": horiz_err, "mass_ratio": mass_ratio,
                             "shape_corr": shape_corr, "pass": invert_pass},
        "overall_pass": bool(forward_pass and invert_pass),
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_groundtruth_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cert, f, indent=2, ensure_ascii=False)
    log.info("=" * 70)
    log.info(f"VEREDICTO GLOBAL: {'PASS ✓' if cert['overall_pass'] else 'FAIL ✗'}")
    log.info(f"Certificado: {out}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
