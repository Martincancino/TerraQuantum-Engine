"""
SYNTHETIC SPHERE RECOVERY BENCHMARK (v2 — Anti-Inverse Crime)
==============================================================
TerraQuantum — Certificado Científico de Recuperación de Anomalía Sintética.

Objetivo
--------
Demostrar cuantitativamente que el motor de inversión geofísica TerraQuantum
recupera una anomalía sintética conocida usando el kernel y solver REALES,
eliminando el "inverse crime" en dos dimensiones:

1. MALLAS DISTINTAS: el modelo verdadero y g_observed se construyen en una
   malla fina (DEFAULT_FINE_BLOCK_SIZE = 5 m); la inversión opera en una malla
   gruesa de producción (DEFAULT_BLOCK_SIZE = 15 m, mismo dominio físico).

2. OPERADOR DISTINTO: además de la diferencia de discretización, g_observed
   incluye una tendencia regional lineal leve (REGIONAL_TREND_PCT × RMS_señal)
   que el solver NO modela. Esto introduce una discrepancia de operador
   controlada y auditada.

Metodología
-----------
1. Construir malla FINA 3D con esfera de contraste de densidad conocido.
2. Calcular g_observed en malla FINA usando GravimetryForward (kernel real).
3. Añadir tendencia regional lineal (discrepancia de operador — no modelada).
4. Agregar ruido Gaussiano controlado (seed=42, 5% del RMS de señal).
5. Invertir en malla GRUESA con GravimetryInversion (LSQR + Tikhonov + depth
   weighting Li & Oldenburg 1998).
6. Mapear modelo verdadero fino → grueso (nearest-neighbor espacial).
7. Calcular métricas honestas en el espacio de la malla de inversión.
8. Exportar certificado JSON reproducible con bound_saturation_pct.

Restricción crítica
-------------------
NO reimplementa ningún kernel, solver ni física.
Reutiliza EXCLUSIVAMENTE clases y funciones de:
  - exploration/gravimetry.py       → GravimetryForward, GravimetryInversion
  - exploration/checkerboard_test.py → build_voxel_grid, build_sensor_grid

Uso
---
    python tests/synthetic_recovery_benchmark.py
    python tests/synthetic_recovery_benchmark.py --ci            # CI mode: no exit(1)
    python tests/synthetic_recovery_benchmark.py --no-lcurve --quiet

Salida
------
    tests/synthetic_recovery_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
from datetime import datetime, timezone

import numpy as np
from scipy.spatial import cKDTree

# ── Resolución de imports: soporta ejecución desde raíz backend o desde tests/
try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid

# ── Focusing MS-IRLS (experimental, opcional) ─────────────────────────────────
try:
    from exploration.focusing import run_focusing
    _FOCUSING_AVAILABLE = True
except ImportError:
    _FOCUSING_AVAILABLE = False

# ── Operating point fijo de producción ────────────────────────────────────────
# Importado de services/geophysics_service.py para garantizar que el benchmark
# usa EXACTAMENTE el mismo λ que producción. Fallback al valor numérico si las
# dependencias del servicio (FastAPI, polars) no están disponibles.
try:
    from services.geophysics_service import PRECONDITIONED_OPERATING_LAMBDA
except ImportError:
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from services.geophysics_service import PRECONDITIONED_OPERATING_LAMBDA
    except ImportError:
        PRECONDITIONED_OPERATING_LAMBDA = 3.0  # fallback — mismo valor que geophysics_service.py:58

# UTF-8 output: necesario en consolas Windows con encoding cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("terraquantum.benchmark")

# ─────────────────────────────────────────────────────────────────────────────
# Parámetros por defecto
# ─────────────────────────────────────────────────────────────────────────────

# Malla GRUESA — inversión (grilla de producción realista)
DEFAULT_NX            = 8
DEFAULT_NY            = 4
DEFAULT_NZ            = 8
DEFAULT_BLOCK_SIZE    = 15.0    # m — celda de la inversión

# Malla FINA — forward (súper-resolución para matar inverse crime de malla)
# FINE_NX = round(NX * BLOCK_SIZE / FINE_BLOCK_SIZE) — misma extensión física
DEFAULT_FINE_BLOCK_SIZE = 5.0  # m — ratio 3:1 vs bloque de inversión

DEFAULT_CONTRAST      = 0.5    # t/m³ — contraste de densidad de la esfera (+ denso)
DEFAULT_NOISE_LEVEL   = 0.05   # fracción del RMS de señal para ruido gaussiano
DEFAULT_LAMBDA_MAG    = PRECONDITIONED_OPERATING_LAMBDA  # operating point fijo de producción (services/geophysics_service.py)
DEFAULT_ALPHA_SPATIAL = 1.0
DEFAULT_LCURVE_TRIALS = 8      # trials L-curve (rápido pero diagnóstico)

# Tendencia regional leve — discrepancia de operador controlada (8% del RMS)
# El forward añade este drift lineal en X+Z; el inversor NO lo modela.
REGIONAL_TREND_PCT = 0.08

# Semilla fija — reproducibilidad absoluta (exigida por el protocolo del benchmark)
RNG_SEED = 42

# Rutas de salida (relativas al directorio de este archivo)
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_OUTPUT_JSON = os.path.join(_THIS_DIR, "synthetic_recovery_results.json")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Modelo sintético de esfera (sobre malla fina)
# ─────────────────────────────────────────────────────────────────────────────

def build_sphere_model(
    nx: int,
    ny: int,
    nz: int,
    block_size: float,
    sphere_center_m: tuple,
    sphere_radius_m: float,
    contrast: float,
) -> np.ndarray:
    """
    Genera el vector de contraste de densidad verdadero con una esfera enterrada.

    Convención Fortran (order='F'): índice plano = ix + nx * iy + nx * ny * iz.
    El eje Y es profundidad positiva hacia abajo (convención TerraQuantum).

    Parámetros
    ----------
    sphere_center_m : (cx, cy, cz) en metros; cy = profundidad del centro
    sphere_radius_m : radio de la esfera [m]
    contrast        : contraste de densidad [t/m³], positivo = cuerpo más denso

    Retorna
    -------
    true_contrast : ndarray shape=(nx*ny*nz,) float64
        +contrast dentro de la esfera, 0.0 en background.
    """
    ix_g, iy_g, iz_g = np.mgrid[0:nx, 0:ny, 0:nz]
    xc_all = (ix_g + 0.5) * block_size
    yc_all = (iy_g + 0.5) * block_size
    zc_all = (iz_g + 0.5) * block_size

    cx, cy, cz = sphere_center_m
    r2 = (xc_all - cx) ** 2 + (yc_all - cy) ** 2 + (zc_all - cz) ** 2
    inside = r2 <= sphere_radius_m ** 2

    n_sphere = int(np.sum(inside))
    sphere_volume_m3 = (4.0 / 3.0) * np.pi * sphere_radius_m ** 3
    logger.info(
        f"Esfera sintética: centro=({cx:.0f},{cy:.0f},{cz:.0f})m | "
        f"R={sphere_radius_m:.0f}m | contraste=+{contrast} t/m³ | "
        f"vóxeles finos={n_sphere} | volumen_analitico={sphere_volume_m3:.0f} m³"
    )
    if n_sphere == 0:
        logger.warning("La esfera sintética no contiene ningún vóxel. Ajustar parámetros.")

    true_contrast = np.where(inside, contrast, 0.0).ravel(order="F")
    return true_contrast.astype(np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mapeo espacial: malla fina → malla gruesa (nearest-neighbor)
# ─────────────────────────────────────────────────────────────────────────────

def map_fine_to_coarse(
    true_contrast_fine: np.ndarray,
    x_fine: np.ndarray,
    y_fine: np.ndarray,
    z_fine: np.ndarray,
    x_coarse: np.ndarray,
    y_coarse: np.ndarray,
    z_coarse: np.ndarray,
) -> np.ndarray:
    """
    Nearest-neighbor downsampling del modelo verdadero de malla fina → gruesa.

    Para cada centroide de vóxel grueso, asigna el valor del vóxel fino más
    cercano (vecino más próximo por distancia euclidiana en 3D).

    No produce NaNs si el dominio fino es co-extensivo con el grueso,
    garantizado cuando FINE_NX*BS_FINE == COARSE_NX*BS_COARSE.

    Permite calcular Pearson r y NRMSE honestos: el modelo verdadero se expresa
    en la resolución real de la inversión, no en la resolución del forward.
    """
    fine_pts   = np.column_stack([x_fine,   y_fine,   z_fine])
    coarse_pts = np.column_stack([x_coarse, y_coarse, z_coarse])
    tree = cKDTree(fine_pts)
    _, idx = tree.query(coarse_pts, k=1)
    mapped = true_contrast_fine[idx]

    # Guard: verificar ausencia de NaN (debería ser imposible si dominios coinciden)
    if not np.isfinite(mapped).all():
        logger.error("map_fine_to_coarse produjo NaN — verificar dominios fine/coarse.")
        raise RuntimeError(
            "map_fine_to_coarse: resultado contiene NaN. "
            "Asegúrate de que FINE_NX*BS_FINE == COARSE_NX*BS_COARSE."
        )
    return mapped


# ─────────────────────────────────────────────────────────────────────────────
# 3. Métricas cuantitativas de recuperación
# ─────────────────────────────────────────────────────────────────────────────

def compute_recovery_metrics(
    true_contrast: np.ndarray,
    est_density: np.ndarray,
    base_density: float = 2.6,
) -> dict:
    """
    Metricas de recuperacion en espacio de voxeles (m_true vs m_rec).

    Parametros
    ----------
    true_contrast : contraste de densidad verdadero [t/m3], shape (n_voxels,)
                    expresado en la resolución de la malla de INVERSIÓN.
    est_density   : densidad absoluta estimada por la inversion (puede tener NaN)
    base_density  : densidad base del solver [t/m3], default 2.6

    Retorna
    -------
    dict con: pearson_r, rms_error, nrmse, recovery_score, n_active, n_total
    """
    valid    = np.isfinite(est_density)
    n_active = int(np.sum(valid))
    n_total  = len(true_contrast)

    if n_active < 4:
        return {
            "pearson_r":      0.0,
            "rms_error":      float("nan"),
            "nrmse":          float("nan"),
            "recovery_score": "POOR",
            "n_active":       n_active,
            "n_total":        n_total,
            "warning":        f"n_active={n_active} < 4: resultado no fiable",
        }

    tc = true_contrast[valid]
    ec = est_density[valid] - base_density

    # ── Pearson r (correlacion lineal entre contraste verdadero y recuperado) ─
    if tc.std() < 1e-15 or ec.std() < 1e-15:
        pearson_r = 0.0
    else:
        pearson_r = float(np.corrcoef(tc, ec)[0, 1])
    if not np.isfinite(pearson_r):
        pearson_r = 0.0

    # ── RMS error en espacio de densidad [t/m3] ──────────────────────────────
    rms_error = float(np.sqrt(np.mean((tc - ec) ** 2)))

    # ── NRMSE: RMS error normalizado por el rango del contraste verdadero ────
    tc_range = float(tc.max() - tc.min())
    nrmse = rms_error / tc_range if tc_range > 1e-15 else float("nan")

    # ── Clasificacion automatica de recuperacion ──────────────────────────────
    if pearson_r >= 0.85:
        recovery_score = "EXCELLENT"
    elif pearson_r >= 0.70:
        recovery_score = "GOOD"
    elif pearson_r >= 0.50:
        recovery_score = "ACCEPTABLE"
    else:
        recovery_score = "POOR"

    return {
        "pearson_r":      round(pearson_r, 4),
        "rms_error":      round(rms_error, 6),
        "nrmse":          round(nrmse, 6) if np.isfinite(nrmse) else float("nan"),
        "recovery_score": recovery_score,
        "n_active":       n_active,
        "n_total":        n_total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pipeline principal del benchmark (dos mallas — anti inverse crime)
# ─────────────────────────────────────────────────────────────────────────────

def run_benchmark(
    nx:              int   = DEFAULT_NX,
    ny:              int   = DEFAULT_NY,
    nz:              int   = DEFAULT_NZ,
    block_size:      float = DEFAULT_BLOCK_SIZE,
    fine_block_size: float = DEFAULT_FINE_BLOCK_SIZE,
    contrast:        float = DEFAULT_CONTRAST,
    noise_level:     float = DEFAULT_NOISE_LEVEL,
    lambda_mag:      float = DEFAULT_LAMBDA_MAG,
    alpha_spatial:   float = DEFAULT_ALPHA_SPATIAL,
    use_lcurve:      bool  = False,
    use_focusing:    bool  = True,
    verbose:         bool  = True,
) -> dict:
    """
    Ejecuta el benchmark completo de recuperación de anomalía esférica sintética
    en modo anti-inverse crime (dos mallas distintas + discrepancia de operador).

    Forward  → malla FINA (fine_block_size) + tendencia regional REGIONAL_TREND_PCT
    Inverse  → malla GRUESA (block_size), mismo dominio físico

    Reutiliza EXCLUSIVAMENTE el pipeline real de TerraQuantum:
      GravimetryForward       → kernel Nagy (1966) / masa puntual
      GravimetryInversion     → LSQR + Tikhonov 3D + depth weighting (Li & Oldenburg 1998)
      select_lambda_lcurve    → selección automática de regularización (opcional)
      run_focusing            → MS-IRLS focusing (opcional, experimental)

    Parámetros
    ----------
    block_size      : tamaño de celda de INVERSIÓN [m] (malla gruesa de producción)
    fine_block_size : tamaño de celda del FORWARD [m] (malla fina)
    noise_level     : fracción del RMS de la señal usada como sigma del ruido.
                      Ejemplo: 0.05 → ruido al 5% del RMS = SNR ≈ 26 dB.

    Retorna
    -------
    dict con configuración completa, métricas y diagnósticos auditables.
    """
    ts_start = datetime.now(timezone.utc)

    # Semilla fija — reproducibilidad absoluta
    np.random.seed(RNG_SEED)

    # ── Derivar dimensiones de la malla FINA (mismo dominio físico que la gruesa) ─
    # Se usa ratio entero redondeado — dominio puede diferir en < 1 cell si no entero
    ratio = block_size / fine_block_size
    nx_fine = max(2, round(nx * ratio))
    ny_fine = max(2, round(ny * ratio))
    nz_fine = max(2, round(nz * ratio))

    # Extensión física de cada malla (para auditoría)
    domain_fine   = (nx_fine * fine_block_size, ny_fine * fine_block_size, nz_fine * fine_block_size)
    domain_coarse = (nx * block_size,            ny * block_size,            nz * block_size)

    logger.info("=" * 70)
    logger.info("  TERRAQUANTUM — SYNTHETIC SPHERE RECOVERY BENCHMARK v2")
    logger.info("  [ANTI-INVERSE CRIME: mallas y operadores distintos]")
    logger.info("=" * 70)
    logger.info(
        f"  Malla FINA  (forward): {nx_fine}×{ny_fine}×{nz_fine} | "
        f"BS={fine_block_size}m | dominio={domain_fine[0]:.0f}×{domain_fine[1]:.0f}×{domain_fine[2]:.0f}m"
    )
    logger.info(
        f"  Malla GRUESA (invers): {nx}×{ny}×{nz} | "
        f"BS={block_size}m | dominio={domain_coarse[0]:.0f}×{domain_coarse[1]:.0f}×{domain_coarse[2]:.0f}m"
    )
    logger.info(f"  Tendencia regional  : {REGIONAL_TREND_PCT*100:.0f}% del RMS de señal")
    logger.info(f"  Seed RNG            : {RNG_SEED}")

    # ─────────────────────────────────────────────────────────────────────────
    # [1/6] Malla fina + modelo verdadero
    # ─────────────────────────────────────────────────────────────────────────
    _, _, _, x_fine, y_fine, z_fine = build_voxel_grid(nx_fine, ny_fine, nz_fine, fine_block_size)

    # Esfera centrada en el dominio; radio = 4 celdas finas (resolución fina)
    cx_sphere = (nx_fine / 2.0) * fine_block_size
    cy_sphere = (ny_fine / 2.0) * fine_block_size
    cz_sphere = (nz_fine / 2.0) * fine_block_size
    sphere_radius = 4.0 * fine_block_size

    true_contrast_fine = build_sphere_model(
        nx=nx_fine, ny=ny_fine, nz=nz_fine,
        block_size=fine_block_size,
        sphere_center_m=(cx_sphere, cy_sphere, cz_sphere),
        sphere_radius_m=sphere_radius,
        contrast=contrast,
    )

    n_sphere_fine = int(np.sum(true_contrast_fine > 0))
    logger.info(
        f"[1/6] Modelo verdadero (fino): {n_sphere_fine} vóxeles anómalos | "
        f"background=0.0 t/m³ | contraste=+{contrast} t/m³"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # [2/6] Forward en malla fina (kernel REAL de TerraQuantum)
    # ─────────────────────────────────────────────────────────────────────────
    cutoff_radius = min(3.0 * fine_block_size * max(nx_fine, ny_fine, nz_fine), 5000.0)

    forward_fine = GravimetryForward(
        dx=fine_block_size, dy=fine_block_size, dz=fine_block_size,
        cutoff_radius=cutoff_radius,
    )

    # Sensores sobre el dominio coarse (misma cobertura física, menos sensores = CI rápido)
    sensor_coords = build_sensor_grid(nx, nz, block_size, sensor_elevation=0.0)
    n_sensors = len(sensor_coords)

    logger.info(
        f"[2/6] Forward FINA: {n_sensors} sensores | "
        f"malla={nx_fine}×{ny_fine}×{nz_fine} | cutoff={cutoff_radius:.0f}m"
    )

    kernel_fine = forward_fine.build_sparse_kernel(x_fine, y_fine, z_fine, sensor_coords)
    g_obs_clean = np.asarray(kernel_fine @ true_contrast_fine, dtype=np.float64)

    signal_rms = float(np.sqrt(np.mean(g_obs_clean ** 2)))
    signal_max = float(np.max(np.abs(g_obs_clean)))

    # ── Tendencia regional leve — discrepancia de operador (no modelada por inversor) ─
    # g_trend(x,z) = A * (x/domain_x + z/domain_z), con A = REGIONAL_TREND_PCT * signal_rms
    # El inversor usará un kernel coarse sin este drift → inverse crime de operador eliminado.
    domain_x = domain_coarse[0]
    domain_z = domain_coarse[2]
    trend_amplitude = REGIONAL_TREND_PCT * max(signal_rms, 1e-30)
    g_regional_trend = trend_amplitude * (
        sensor_coords[:, 0] / max(domain_x, 1.0)
        + sensor_coords[:, 2] / max(domain_z, 1.0)
    )
    g_obs_with_trend = g_obs_clean + g_regional_trend

    # ── Ruido gaussiano auto-calibrado ──────────────────────────────────────
    noise_sigma = noise_level * signal_rms
    if noise_sigma < 1e-60:
        noise_sigma = 1e-30
    g_obs = g_obs_with_trend + np.random.normal(0.0, noise_sigma, size=g_obs_with_trend.shape)

    noise_sigma_mgal = float(noise_sigma * 1e5)
    snr_db = float(10.0 * np.log10(max(signal_rms ** 2 / noise_sigma ** 2, 1e-30)))
    trend_rms = float(np.sqrt(np.mean(g_regional_trend ** 2)))

    logger.info(
        f"[2/6] Signal RMS={signal_rms:.4e} | Trend RMS={trend_rms:.4e} "
        f"({100*trend_rms/max(signal_rms,1e-30):.1f}% señal) | "
        f"Noise sigma={noise_sigma:.4e} | SNR={snr_db:.1f} dB"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # [3/6] Malla gruesa para inversión (operador distinto — vóxeles más grandes)
    # ─────────────────────────────────────────────────────────────────────────
    _, _, _, x_coarse, y_coarse, z_coarse = build_voxel_grid(nx, ny, nz, block_size)

    cutoff_coarse = min(3.0 * block_size * max(nx, ny, nz), 5000.0)
    forward_coarse = GravimetryForward(
        dx=block_size, dy=block_size, dz=block_size,
        cutoff_radius=cutoff_coarse,
    )

    inversor = GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=block_size)

    logger.info(
        f"[3/6] Malla GRUESA: {nx}×{ny}×{nz} = {nx*ny*nz} vóxeles | "
        f"BS={block_size}m | cutoff={cutoff_coarse:.0f}m"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # [4/6] Selección de lambda via L-curve (sobre malla gruesa)
    # ─────────────────────────────────────────────────────────────────────────
    lcurve_result   = None
    lambda_selected = lambda_mag
    regularization  = f"Tikhonov + operating_point_fijo (λ={PRECONDITIONED_OPERATING_LAMBDA})"

    if use_lcurve:
        logger.info(
            f"[4/6] L-Curve: {DEFAULT_LCURVE_TRIALS} trials | lambda in [1e-4, 1e2]"
        )
        try:
            lcurve_result = inversor.select_lambda_lcurve(
                g_observed=g_obs,
                y_c=y_coarse,
                forward_model=forward_coarse,
                sensor_coords=sensor_coords,
                x_c=x_coarse,
                z_c=z_coarse,
                n_trials=DEFAULT_LCURVE_TRIALS,
                lambda_min=1e-4,
                lambda_max=1e2,
                alpha_spatial=alpha_spatial,
                noise_floor=noise_sigma,
                noise_pct=0.0,
            )
            lambda_selected = lcurve_result["lambda_selected"]
            regularization  = "Tikhonov + L-Curve"
            logger.info(
                f"[4/6] λ óptimo = {lambda_selected:.2e} "
                f"(corner idx {lcurve_result['corner_index']}/"
                f"{lcurve_result['n_trials']-1})"
            )
        except Exception as exc:
            logger.warning(
                f"[4/6] L-Curve falló ({exc}) — usando λ={lambda_mag:.2e} fijo"
            )
            lambda_selected = lambda_mag
    else:
        logger.info(
            f"[4/6] L-Curve omitida. λ={lambda_selected:.2e} = PRECONDITIONED_OPERATING_LAMBDA "
            f"(operating point fijo, importado de services/geophysics_service.py)"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # [5/6] Inversión en malla gruesa — LSQR + Tikhonov + depth weighting
    # ─────────────────────────────────────────────────────────────────────────
    logger.info(
        f"[5/6] Invirtiendo (malla GRUESA): LSQR + Tikhonov | "
        f"lambda={lambda_selected:.2e} | alpha_spatial={alpha_spatial}"
    )

    solver_meta: dict = {}   # captura sat_fraction y diagnósticos numéricos

    est_density, probability, misfit_pct, sensitivity = inversor.solve_inversion_lsqr(
        g_observed=g_obs,
        kernel_sparse=None,
        y_c=y_coarse,
        lambda_mag=lambda_selected,
        alpha_spatial=alpha_spatial,
        forward_model=forward_coarse,
        sensor_coords=sensor_coords,
        x_c=x_coarse,
        z_c=z_coarse,
        noise_floor=noise_sigma,
        noise_pct=0.0,
        solver_meta=solver_meta,
    )

    sat_fraction     = float(solver_meta.get("sat_fraction", 0.0))
    bound_sat_pct    = round(sat_fraction * 100.0, 2)
    n_sat_lower      = int(solver_meta.get("n_sat_lower", 0))
    n_sat_upper      = int(solver_meta.get("n_sat_upper", 0))
    n_active_coarse  = int(solver_meta.get("n_active", nx * ny * nz))

    logger.info(
        f"[5/6] LSQR convergido | Misfit={misfit_pct:.2f}% | "
        f"est_density: min={float(np.nanmin(est_density)):.3f} "
        f"max={float(np.nanmax(est_density)):.3f} t/m³ | "
        f"Celdas saturadas: {bound_sat_pct:.1f}% "
        f"(lower={n_sat_lower}, upper={n_sat_upper})"
    )

    # ── [5b] MS-IRLS focusing (opcional, experimental) ───────────────────────
    focusing_status = "NO_RUN"
    focusing_mode   = ""

    kernel_coarse = forward_coarse.build_sparse_kernel(x_coarse, y_coarse, z_coarse, sensor_coords)

    if use_focusing and _FOCUSING_AVAILABLE:
        logger.info("[5b] MS-IRLS focusing (experimental)...")
        try:
            ms_result = run_focusing(
                kernel_sparse=kernel_coarse,
                g_obs=g_obs,
                y_c=y_coarse,
                inversor=inversor,
                est_density=est_density,
                alpha_spatial=2.0,
                lambda_mag=5e-5,
            )
            focusing_status = ms_result.scale_status
            focusing_mode   = ms_result.use_mode
            regularization  += " + MS-IRLS"
            logger.info(
                f"[5b] Focusing: status={focusing_status} | "
                f"mode={focusing_mode} | "
                f"best_iter={ms_result.best_iter}/{ms_result.total_iters}"
            )
        except Exception as exc:
            focusing_status = "ERROR"
            logger.warning(f"[5b] MS-IRLS error: {exc}")
    elif use_focusing and not _FOCUSING_AVAILABLE:
        focusing_status = "UNAVAILABLE"
        logger.info("[5b] exploration.focusing no disponible — omitiendo MS-IRLS")

    # ─────────────────────────────────────────────────────────────────────────
    # [6/6] Métricas honestas: mapear modelo fino → grueso, luego comparar
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("[6/6] Mapeando modelo verdadero fino → grueso (nearest-neighbor)...")

    true_contrast_coarse = map_fine_to_coarse(
        true_contrast_fine=true_contrast_fine,
        x_fine=x_fine, y_fine=y_fine, z_fine=z_fine,
        x_coarse=x_coarse, y_coarse=y_coarse, z_coarse=z_coarse,
    )

    n_sphere_coarse = int(np.sum(true_contrast_coarse > 0))
    logger.info(
        f"[6/6] Contraste mapeado: {n_sphere_coarse} vóxeles gruesos anómalos "
        f"(de {nx*ny*nz} total)"
    )

    metrics = compute_recovery_metrics(
        true_contrast=true_contrast_coarse,
        est_density=est_density,
        base_density=float(inversor.base_density),
    )

    # Phi_d y chi-cuadrado
    g_obs_l2    = float(np.linalg.norm(g_obs))
    residual_l2 = (misfit_pct / 100.0) * g_obs_l2
    sigma_safe  = max(noise_sigma, 1e-60)
    phi_d       = float(residual_l2 ** 2 / sigma_safe ** 2)
    chi_squared = phi_d / max(n_sensors, 1)

    metrics["phi_d"]       = round(phi_d, 6)
    metrics["chi_squared"] = round(chi_squared, 6)

    ts_end    = datetime.now(timezone.utc)
    elapsed_s = (ts_end - ts_start).total_seconds()

    # ── Reporte de auditoría en stdout ────────────────────────────────────────
    if verbose:
        _print_benchmark_report(
            metrics=metrics,
            elapsed_s=elapsed_s,
            config={
                # Mallas
                "nx": nx, "ny": ny, "nz": nz,
                "block_size": block_size,
                "nx_fine": nx_fine, "ny_fine": ny_fine, "nz_fine": nz_fine,
                "fine_block_size": fine_block_size,
                # Señal y ruido
                "n_sensors":          n_sensors,
                "n_sphere_coarse":    n_sphere_coarse,
                "n_sphere_fine":      n_sphere_fine,
                "n_total_voxels":     nx * ny * nz,
                "lambda_selected":    lambda_selected,
                "alpha_spatial":      alpha_spatial,
                "signal_rms":         signal_rms,
                "trend_rms":          trend_rms,
                "noise_sigma":        noise_sigma,
                "noise_sigma_mgal":   noise_sigma_mgal,
                "snr_db":             snr_db,
                "misfit_pct":         misfit_pct,
                "lcurve_used":        lcurve_result is not None,
                "focusing_status":    focusing_status,
                # Saturación
                "bound_saturation_pct": bound_sat_pct,
                "n_sat_lower":        n_sat_lower,
                "n_sat_upper":        n_sat_upper,
            },
        )

    # ── Resultado completo (formato JSON auditado) ────────────────────────────
    results = {
        "benchmark_type":       "synthetic_sphere_recovery_v2_anti_inverse_crime",
        "timestamp":            ts_start.strftime("%Y-%m-%dT%H:%M:%S UTC"),
        # Mallas
        "forward_mesh_shape":   [nx_fine, ny_fine, nz_fine],
        "forward_block_size_m": fine_block_size,
        "inverse_mesh_shape":   [nx, ny, nz],
        "inverse_block_size_m": block_size,
        "mesh_ratio":           round(block_size / fine_block_size, 2),
        # Backward-compat (refiere a malla gruesa de inversión)
        "mesh_shape":           [nx, ny, nz],
        "block_size_m":         block_size,
        # Esfera
        "sphere_center_m":      [cx_sphere, cy_sphere, cz_sphere],
        "sphere_radius_m":      sphere_radius,
        "n_sphere_voxels_fine": n_sphere_fine,
        "n_sphere_voxels_coarse": n_sphere_coarse,
        "n_total_voxels":       nx * ny * nz,
        "n_sensors":            n_sensors,
        # Señal
        "noise_sigma_mgal":     round(noise_sigma_mgal, 6),
        "signal_rms_si":        round(signal_rms, 8),
        "trend_rms_si":         round(trend_rms, 8),
        "regional_trend_pct":   REGIONAL_TREND_PCT,
        "snr_db":               round(snr_db, 2),
        # Inversión
        "lambda_mag":           lambda_selected,
        "alpha_spatial":        alpha_spatial,
        "misfit_percent":       round(misfit_pct, 4),
        # Métricas
        "pearson_r":            metrics["pearson_r"],
        "rms_error":            metrics["rms_error"],
        "nrmse":                metrics.get("nrmse", float("nan")),
        "phi_d":                metrics.get("phi_d", 0.0),
        "chi_squared":          metrics.get("chi_squared", 0.0),
        "recovery_score":       metrics["recovery_score"],
        # Saturación petrofísica — métrica crítica de monitoreo
        "bound_saturation_pct": bound_sat_pct,
        "n_sat_lower":          n_sat_lower,
        "n_sat_upper":          n_sat_upper,
        # Meta
        "solver":               "LSQR",
        "regularization":       regularization,
        "lcurve_used":          lcurve_result is not None,
        "focusing_status":      focusing_status,
        "elapsed_s":            round(elapsed_s, 2),
        "rng_seed":             RNG_SEED,
        "notes": [
            "v2: benchmark anti-inverse crime con mallas DISTINTAS para forward e inversión",
            f"Forward mesh: {nx_fine}×{ny_fine}×{nz_fine} @ {fine_block_size}m | "
            f"Inverse mesh: {nx}×{ny}×{nz} @ {block_size}m",
            f"Tendencia regional lineal añadida: ~{REGIONAL_TREND_PCT*100:.0f}% del RMS — no modelada por el inversor",
            "Mapeo fino→grueso: nearest-neighbor 3D (scipy.spatial.cKDTree)",
            "Kernel gravitacional: Nagy (1966) campo cercano + masa puntual campo lejano",
            "Regularización: Tikhonov 3D + depth weighting Li & Oldenburg (1998, β=2)",
            f"Ruido gaussiano fijo (seed={RNG_SEED}) — resultados 100% reproducibles",
            "bound_saturation_pct: fracción de vóxeles en el bound petrofísico [densidad_min, densidad_max]",
            f"Lambda selección: operating point fijo PRECONDITIONED_OPERATING_LAMBDA={PRECONDITIONED_OPERATING_LAMBDA} "
            f"(L-curve deshabilitada; importado de services/geophysics_service.py)",
            "CI threshold: Pearson r >= 0.85 requerido para exit(0); exit(1) si r < 0.85",
        ],
    }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reporte de auditoría en stdout
# ─────────────────────────────────────────────────────────────────────────────

def _print_benchmark_report(metrics: dict, elapsed_s: float, config: dict) -> None:
    """Imprime el reporte de auditoría técnica del benchmark en stdout."""
    r       = metrics["pearson_r"]
    score   = metrics["recovery_score"]
    verdict = {
        "EXCELLENT": "EXCELLENT — Nivel benchmark industrial",
        "GOOD":      "GOOD      — Exploración minera confiable",
        "ACCEPTABLE":"ACCEPTABLE — Recuperación parcial aceptable",
        "POOR":      "POOR      — Revisar parámetros de inversión",
    }.get(score, score)

    lcurve_label   = "SI (automático)" if config["lcurve_used"] else "NO (λ fijo)"
    focusing_label = config["focusing_status"]
    nrmse_str = f"{metrics.get('nrmse', float('nan')):.4f}" if np.isfinite(metrics.get('nrmse', float('nan'))) else "N/A"

    report = textwrap.dedent(f"""
    +========================================================================+
    |   TERRAQUANTUM - SYNTHETIC SPHERE RECOVERY BENCHMARK v2               |
    |   ANTI-INVERSE CRIME: mallas y operadores distintos                    |
    +========================================================================+

    Mallas (anti-inverse crime):
      Malla FINA (forward) : {config['nx_fine']} x {config['ny_fine']} x {config['nz_fine']}  BS={config['fine_block_size']}m
      Malla GRUESA (invers): {config['nx']} x {config['ny']} x {config['nz']}  BS={config['block_size']}m
      Ratio mallas         : {config['block_size']/config['fine_block_size']:.1f}x
      Discrepancia op.     : tendencia regional ~{100*config['trend_rms']/max(config['signal_rms'],1e-30):.1f}% de la señal

    Configuracion de inversión:
      Sensores          : {config['n_sensors']}
      Vóxeles esfera    : {config['n_sphere_coarse']} gruesos / {config['n_sphere_fine']} finos
      Total vóxeles inv.: {config['n_total_voxels']}
      Lambda Tikhonov   : {config['lambda_selected']:.2e}
      Alpha spatial     : {config['alpha_spatial']}
      L-Curve           : {lcurve_label}
      Focusing MS-IRLS  : {focusing_label}

    Diagnóstico de señal:
      Signal RMS (SI)   : {config['signal_rms']:.4e} m/s2
      Trend RMS (SI)    : {config['trend_rms']:.4e} m/s2
      Noise sigma (SI)  : {config['noise_sigma']:.4e} m/s2
      Noise sigma (mGal): {config['noise_sigma_mgal']:.4f} mGal
      SNR               : {config['snr_db']:.1f} dB
      Misfit LSQR       : {config['misfit_pct']:.2f}%

    --------------------------------------------------------------------------
    Métricas de recuperación (contraste verdadero grueso vs m_rec):
    --------------------------------------------------------------------------
      Pearson r         : {metrics['pearson_r']:.4f}
      RMS error         : {metrics['rms_error']:.6f} t/m3
      NRMSE             : {nrmse_str}
      Phi_d (misfit)    : {metrics.get('phi_d', 0.0):.6f}
      Chi-cuadrado red. : {metrics.get('chi_squared', 0.0):.6f}   (ideal ~ 1.0)
      Celdas activas    : {metrics['n_active']} / {metrics['n_total']}

    Saturación petrofísica (CRÍTICO):
      bound_saturation  : {config['bound_saturation_pct']:.2f}%
      n_sat_lower       : {config['n_sat_lower']}
      n_sat_upper       : {config['n_sat_upper']}

    Tiempo de ejecución : {elapsed_s:.2f} s

    == VEREDICTO: {verdict} ==

    Clasificación de recuperación:
      r >= 0.85 -> EXCELLENT  (benchmark industrial / paper-quality)
      r >= 0.70 -> GOOD       (exploración minera confiable)
      r >= 0.50 -> ACCEPTABLE (recuperación parcial)
      r  < 0.50 -> POOR       (ajustar lambda, grilla o cutoff_radius)

    Nota técnica (v2): Pearson r calculado entre true_contrast mapeado a la
    malla GRUESA (nearest-neighbor) y contraste estimado (est_density - 2.6).
    El benchmark es honesto: forward ≠ inverse (malla ni operador).
    """)
    print(report)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Exportación JSON
# ─────────────────────────────────────────────────────────────────────────────

def export_results(results: dict, output_path: str) -> None:
    """Guarda el certificado JSON del benchmark en disco."""
    dir_path = os.path.dirname(output_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    logger.info(f"Certificado exportado → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TerraQuantum — Synthetic Sphere Recovery Benchmark v2 (Anti-Inverse Crime)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--nx",               type=int,   default=DEFAULT_NX,
                        help="Celdas en X (malla gruesa de inversión)")
    parser.add_argument("--ny",               type=int,   default=DEFAULT_NY,
                        help="Celdas en Y — profundidad (malla gruesa)")
    parser.add_argument("--nz",               type=int,   default=DEFAULT_NZ,
                        help="Celdas en Z (malla gruesa de inversión)")
    parser.add_argument("--block_size",       type=float, default=DEFAULT_BLOCK_SIZE,
                        help="Tamaño de celda de inversión [m] (malla gruesa)")
    parser.add_argument("--fine_block_size",  type=float, default=DEFAULT_FINE_BLOCK_SIZE,
                        help="Tamaño de celda del forward [m] (malla fina, anti-inverse crime)")
    parser.add_argument("--contrast",         type=float, default=DEFAULT_CONTRAST,
                        help="Contraste de densidad de la esfera [t/m³]")
    parser.add_argument("--noise_level",      type=float, default=DEFAULT_NOISE_LEVEL,
                        help="Fracción del RMS de señal para ruido gaussiano (ej: 0.05 = 5%%)")
    parser.add_argument("--lambda_mag",       type=float, default=DEFAULT_LAMBDA_MAG,
                        help="Lambda Tikhonov fijo (usado si --no-lcurve)")
    parser.add_argument("--alpha_spatial",    type=float, default=DEFAULT_ALPHA_SPATIAL,
                        help="Peso del regularizador Laplaciano")
    parser.add_argument("--no-lcurve",       dest="use_lcurve",   action="store_false",
                        help="Omitir selección automática de λ por L-curve")
    parser.add_argument("--no-focusing",     dest="use_focusing", action="store_false",
                        help="Omitir MS-IRLS focusing experimental")
    parser.add_argument("--quiet",            action="store_true",
                        help="Suprimir reporte detallado (solo métricas JSON en stdout)")
    parser.add_argument("--output",           type=str, default=_OUTPUT_JSON,
                        help="Ruta de salida del certificado JSON")
    parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help=(
            "Modo CI: ejecutar benchmark honesto y terminar con exit(0) siempre. "
            "El umbral duro se fijará en un commit futuro cuando se conozca el baseline."
        ),
    )
    parser.set_defaults(use_lcurve=False, use_focusing=True)
    return parser.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = _parse_args()

    results = run_benchmark(
        nx=args.nx,
        ny=args.ny,
        nz=args.nz,
        block_size=args.block_size,
        fine_block_size=args.fine_block_size,
        contrast=args.contrast,
        noise_level=args.noise_level,
        lambda_mag=args.lambda_mag,
        alpha_spatial=args.alpha_spatial,
        use_lcurve=args.use_lcurve,
        use_focusing=args.use_focusing,
        verbose=not args.quiet,
    )

    export_results(results, args.output)

    if not args.quiet:
        print(f"\n[JSON] Certificado: {args.output}")
        print(json.dumps(
            {k: results[k] for k in (
                "benchmark_type", "timestamp",
                "forward_mesh_shape", "forward_block_size_m",
                "inverse_mesh_shape", "inverse_block_size_m",
                "mesh_ratio",
                "noise_sigma_mgal", "regional_trend_pct",
                "pearson_r", "rms_error", "nrmse",
                "phi_d", "chi_squared", "recovery_score",
                "bound_saturation_pct",
                "solver", "regularization", "elapsed_s",
            )},
            indent=2,
        ))

    if args.ci:
        pearson_r_ci = results.get("pearson_r", 0.0)
        score = results.get("recovery_score", "POOR")
        print(
            f"\n[CI] Benchmark completado — recovery_score={score} | "
            f"pearson_r={pearson_r_ci:.4f} | "
            f"bound_saturation_pct={results.get('bound_saturation_pct', 0.0):.2f}%"
        )
        if pearson_r_ci < 0.85:
            print(
                f"[CI] FAIL — Pearson r={pearson_r_ci:.4f} < 0.85 "
                f"(umbral requerido para operating point fijo λ={PRECONDITIONED_OPERATING_LAMBDA})"
            )
            sys.exit(1)
        print(f"[CI] PASS — Pearson r={pearson_r_ci:.4f} >= 0.85")
        sys.exit(0)
    else:
        # Modo normal: exit(1) si el benchmark falla (POOR)
        sys.exit(0 if results.get("recovery_score", "POOR") != "POOR" else 1)
