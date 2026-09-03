"""
FASE 11 — QA Matemático: Checkerboard Test
==========================================

Propósito (auditoría):
    Verificar si el motor de inversión gravimétrica TerraQuantum "aprende" la
    geometría de anomalías sintéticas o simplemente alucina estructura.

Metodología:
    1. Genera un volumen 3D con densidad alternante (+/- contraste) — patrón checkerboard.
    2. Calcula la gravedad sintética con GravimetryForward (kernel Nagy/PointMass).
    3. Invierte con GravimetryInversion (LSQR + Tikhonov).
    4. Compara modelo input vs output:
       - Correlación de Pearson (toda la grilla activa).
       - Recovery ratio: densidades recuperadas / densidades verdaderas.
       - Misfit de la inversión.
    5. Imprime reporte de auditoría en stdout y retorna dict de métricas.

Uso:
    python exploration/checkerboard_test.py
    python exploration/checkerboard_test.py --nx 6 --ny 4 --nz 6 --block_size 15.0

Autor: TerraQuantum Backend | Fase 11
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import datetime, timezone

import numpy as np

# ── Importar motores propios ──────────────────────────────────────────────────
try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
except ImportError:
    # Soporte para ejecución directa desde la raíz del backend
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion


# ─────────────────────────────────────────────────────────────────────────────
# Parámetros por defecto del checkerboard
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_NX         = 8       # Celdas en X
DEFAULT_NY         = 4       # Celdas en Y (profundidad)
DEFAULT_NZ         = 8       # Celdas en Z
DEFAULT_BLOCK_SIZE = 10.0    # Metros por lado de celda
DEFAULT_CONTRAST   = 0.3     # t/m³ — magnitud del contraste de densidad
DEFAULT_LAMBDA_MAG = 1e-4    # Regularización tikhonov
DEFAULT_ALPHA_SPATIAL = 1.0  # Peso espacial


# ─────────────────────────────────────────────────────────────────────────────
# 1. Generador del volumen checkerboard 3D
# ─────────────────────────────────────────────────────────────────────────────

def build_checkerboard_model(
    nx: int, ny: int, nz: int,
    contrast: float = DEFAULT_CONTRAST
) -> np.ndarray:
    """
    Genera el contraste de densidad verdadero en patrón 3D checkerboard.

    Convención Fortran (orden='F'):
        índice plano j = ix + nx * iy + nx * ny * iz

    Returns
    -------
    true_contrast : ndarray shape=(nx*ny*nz,) float64
        +contrast en celdas pares, -contrast en celdas impares.
        Valor base = 0 (se suma a base_density=2.6 en la inversión).
    """
    ix_grid, iy_grid, iz_grid = np.mgrid[0:nx, 0:ny, 0:nz]
    # Suma de índices: par → positivo, impar → negativo
    parity = (ix_grid + iy_grid + iz_grid) % 2  # 0 o 1
    sign = np.where(parity == 0, +1.0, -1.0)

    contrast_3d = sign * contrast
    return contrast_3d.ravel(order="F").astype(np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Construir grilla de vóxeles y sensores
# ─────────────────────────────────────────────────────────────────────────────

def build_voxel_grid(nx: int, ny: int, nz: int, block_size: float):
    """
    Construye coordenadas de centros de vóxeles en orden Fortran.

    Returns
    -------
    (ix, iy, iz, x_c, y_c, z_c) — todos ndarray float64/int32
    """
    ix_g, iy_g, iz_g = np.mgrid[0:nx, 0:ny, 0:nz]

    ix = ix_g.ravel(order="F").astype(np.int32)
    iy = iy_g.ravel(order="F").astype(np.int32)
    iz = iz_g.ravel(order="F").astype(np.int32)

    x_c = (ix * block_size + block_size / 2.0).astype(np.float64)
    y_c = (iy * block_size + block_size / 2.0).astype(np.float64)
    z_c = (iz * block_size + block_size / 2.0).astype(np.float64)

    return ix, iy, iz, x_c, y_c, z_c


def build_sensor_grid(
    nx: int, nz: int, block_size: float,
    sensor_elevation: float = 0.0
) -> np.ndarray:
    """
    Sensores en superficie: grilla regular de (nx-1) × (nz-1) puntos centrados.

    Returns
    -------
    sensor_coords : ndarray shape=(n_sensors, 3) — [x, y, z]
    """
    xs = np.linspace(block_size * 0.5, block_size * (nx - 0.5), max(nx - 1, 2))
    zs = np.linspace(block_size * 0.5, block_size * (nz - 0.5), max(nz - 1, 2))
    xg, zg = np.meshgrid(xs, zs, indexing="ij")
    n = len(xg.ravel())
    sensors = np.column_stack([
        xg.ravel(),
        np.full(n, sensor_elevation, dtype=np.float64),
        zg.ravel(),
    ])
    return sensors.astype(np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Métricas de QA
# ─────────────────────────────────────────────────────────────────────────────

def compute_checkerboard_metrics(
    true_contrast: np.ndarray,
    estimated_density: np.ndarray,
    base_density: float = 2.6,
) -> dict:
    """
    Calcula métricas de recuperación del checkerboard.

    Parámetros
    ----------
    true_contrast       : contraste de densidad verdadero (±contrast)
    estimated_density   : densidad absoluta estimada por la inversión (puede tener NaN)
    base_density        : densidad base usada por el solver (default 2.6 t/m³)

    Returns
    -------
    dict con claves:
        n_active, n_total, n_nan
        pearson_r           — correlación de Pearson (contraste vs contraste estimado)
        sign_recovery_pct   — % de celdas con signo correcto del contraste
        rmse_contrast       — RMSE en el espacio de contraste
        snr_db              — Signal-to-Noise Ratio en dB
        spatial_correlation_label — Clasificación cualitativa
    """
    est_contrast = estimated_density - base_density  # quita base_density

    # Máscara: solo celdas activas (no NaN)
    valid = np.isfinite(est_contrast) & np.isfinite(true_contrast)
    n_total  = len(true_contrast)
    n_active = int(np.sum(valid))
    n_nan    = n_total - n_active

    if n_active < 4:
        return {
            "n_active": n_active, "n_total": n_total, "n_nan": n_nan,
            "pearson_r": 0.0, "sign_recovery_pct": 0.0,
            "rmse_contrast": float("nan"), "snr_db": float("-inf"),
            "spatial_correlation_label": "INSUFICIENTE (n_active < 4)",
        }

    tc = true_contrast[valid]
    ec = est_contrast[valid]

    # Pearson r
    if tc.std() < 1e-15 or ec.std() < 1e-15:
        pearson_r = 0.0
    else:
        pearson_r = float(np.corrcoef(tc, ec)[0, 1])

    # Recuperación de signo
    sign_ok = np.sign(tc) == np.sign(ec)
    sign_recovery_pct = float(100.0 * np.sum(sign_ok) / n_active)

    # RMSE en espacio de contraste
    rmse_contrast = float(np.sqrt(np.mean((tc - ec) ** 2)))

    # SNR en dB: ratio entre señal verdadera y error de recuperación
    signal_power = float(np.mean(tc ** 2))
    noise_power  = float(np.mean((tc - ec) ** 2))
    if noise_power < 1e-30:
        snr_db = float("inf")
    elif signal_power < 1e-30:
        snr_db = float("-inf")
    else:
        snr_db = float(10.0 * np.log10(signal_power / noise_power))

    # Etiqueta cualitativa
    if pearson_r >= 0.7:
        label = "BUENA (r ≥ 0.7) — el solver recupera la geometría principal"
    elif pearson_r >= 0.4:
        label = "MODERADA (r ≥ 0.4) — recupera tendencia, no detalle"
    elif pearson_r >= 0.15:
        label = "DÉBIL (r ≥ 0.15) — señal parcialmente distorsionada"
    else:
        label = "POBRE (r < 0.15) — alta distorsión o aliasing"

    return {
        "n_active": n_active,
        "n_total":  n_total,
        "n_nan":    n_nan,
        "pearson_r": round(pearson_r, 4),
        "sign_recovery_pct": round(sign_recovery_pct, 2),
        "rmse_contrast": round(rmse_contrast, 6),
        "snr_db": round(snr_db, 2),
        "spatial_correlation_label": label,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pipeline completo del checkerboard test
# ─────────────────────────────────────────────────────────────────────────────

def run_checkerboard_test(
    nx: int = DEFAULT_NX,
    ny: int = DEFAULT_NY,
    nz: int = DEFAULT_NZ,
    block_size: float = DEFAULT_BLOCK_SIZE,
    contrast: float = DEFAULT_CONTRAST,
    lambda_mag: float = DEFAULT_LAMBDA_MAG,
    alpha_spatial: float = DEFAULT_ALPHA_SPATIAL,
    noise_pct: float = 0.02,
    noise_floor: float = 0.001,
    seed: int = 42,
    verbose: bool = True,
) -> dict:
    """
    Ejecuta el checkerboard test completo y retorna las métricas de QA.

    Parámetros
    ----------
    nx, ny, nz   : dimensiones de la grilla (recomendado: pequeña para rapidez)
    block_size   : tamaño de celda en metros
    contrast     : magnitud del contraste de densidad (t/m³)
    lambda_mag   : regularización Tikhonov (damp) para LSQR
    alpha_spatial: peso del Laplaciano
    noise_pct    : fracción de ruido relativo en datos sintéticos
    noise_floor  : piso de ruido absoluto en datos sintéticos

    Returns
    -------
    dict con métricas QA completas (métricas de correlación + misfit)
    """
    ts_start = datetime.now(timezone.utc)

    if verbose:
        print("\n" + "=" * 70)
        print("  TERRAQUANTUM — CHECKERBOARD TEST (QA Matemático)")
        print("=" * 70)
        print(f"  Grid: {nx}×{ny}×{nz} | block_size={block_size}m")
        print(f"  Contrast: ±{contrast} t/m³ | lambda_mag={lambda_mag:.2e}")
        print(f"  Timestamp: {ts_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("-" * 70)

    # ── 1. Grilla y modelo verdadero ─────────────────────────────────────────
    ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(nx, ny, nz, block_size)
    true_contrast = build_checkerboard_model(nx, ny, nz, contrast)

    if verbose:
        n_pos = int(np.sum(true_contrast > 0))
        n_neg = int(np.sum(true_contrast < 0))
        print(f"[1/4] Modelo checkerboard: {n_pos} celdas +, {n_neg} celdas −")

    # ── 2. Forward model (gravedad sintética) ─────────────────────────────────
    cutoff_radius = min(4.0 * block_size * max(nx, ny, nz), 3000.0)
    forward = GravimetryForward(
        dx=block_size, dy=block_size, dz=block_size,
        cutoff_radius=cutoff_radius,
    )

    sensor_coords = build_sensor_grid(nx, nz, block_size, sensor_elevation=0.0)
    n_sensors = len(sensor_coords)

    if verbose:
        print(f"[2/4] Forward model: {n_sensors} sensores | cutoff_radius={cutoff_radius:.0f}m")

    # Kernel sobre todos los vóxeles
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)

    # Gravedad = kernel @ contraste verdadero
    g_synthetic_clean = kernel @ true_contrast

    # Ruido gaussiano realista
    # FASE 26 (direccion 5): la semilla es un PARAMETRO. Estaba clavada en 42 y el
    # script publicaba un `pearson_r` como si fuera una propiedad del survey; es una
    # realizacion. Ver `tests/seed_sweep.py` y `validation/exp_resolution.py`.
    rng = np.random.default_rng(seed=int(seed))
    sigma_noise = noise_floor + noise_pct * np.abs(g_synthetic_clean)
    noise = rng.normal(scale=sigma_noise)
    g_observed = g_synthetic_clean + noise

    g_rms = float(np.sqrt(np.mean(g_observed ** 2)))
    noise_rms = float(np.sqrt(np.mean(noise ** 2)))
    if verbose:
        print(f"[2/4] g_rms={g_rms:.4e} | noise_rms={noise_rms:.4e} | "
              f"SNR_datos={10*np.log10(max(g_rms**2/max(noise_rms**2,1e-30),1e-9)):.1f} dB")

    # ── 3. Inversión ──────────────────────────────────────────────────────────
    if verbose:
        print(f"[3/4] Invirtiendo con LSQR (lambda_mag={lambda_mag:.2e}, "
              f"alpha_spatial={alpha_spatial})...")

    inversor = GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=block_size)

    est_density, probability, misfit_percent, sensitivity = inversor.solve_inversion_lsqr(
        g_observed=g_observed,
        kernel_sparse=None,          # Motor HPC F0.2 — ignorado
        y_c=y_c,
        lambda_mag=lambda_mag,
        alpha_spatial=alpha_spatial,
        forward_model=forward,
        sensor_coords=sensor_coords,
        x_c=x_c,
        z_c=z_c,
        noise_floor=noise_floor,
        noise_pct=noise_pct,
    )

    # ── 4. Métricas QA ────────────────────────────────────────────────────────
    metrics = compute_checkerboard_metrics(true_contrast, est_density, base_density=2.6)
    metrics["misfit_percent"] = round(misfit_percent, 4)
    metrics["n_sensors"] = n_sensors
    metrics["lambda_mag"] = lambda_mag
    metrics["alpha_spatial"] = alpha_spatial
    metrics["contrast_input"] = contrast
    metrics["nx"] = nx
    metrics["ny"] = ny
    metrics["nz"] = nz
    metrics["block_size"] = block_size
    metrics["seed"] = int(seed)

    ts_end = datetime.now(timezone.utc)
    elapsed_s = (ts_end - ts_start).total_seconds()
    metrics["elapsed_s"] = round(elapsed_s, 2)
    metrics["timestamp_utc"] = ts_start.strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── 5. Reporte de auditoría ────────────────────────────────────────────────
    if verbose:
        _print_qa_report(metrics)

    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reporte de salida
# ─────────────────────────────────────────────────────────────────────────────

def _print_qa_report(m: dict) -> None:
    """Imprime el reporte QA en stdout."""
    r = m["pearson_r"]
    pass_fail = "✓ PASS" if r >= 0.4 else "✗ FAIL"

    report = textwrap.dedent(f"""
    ┌─────────────────────────────────────────────────────────────────────┐
    │         CHECKERBOARD TEST — REPORTE DE AUDITORÍA QA                │
    │         TerraQuantum Backend | Fase 11 — Blindaje Industrial        │
    └─────────────────────────────────────────────────────────────────────┘

    Configuración del test:
      Grid             : {m['nx']} × {m['ny']} × {m['nz']}
      Block size       : {m['block_size']} m
      Contraste input  : ±{m['contrast_input']} t/m³
      Lambda_mag       : {m['lambda_mag']:.2e}
      Alpha_spatial    : {m['alpha_spatial']}
      Sensores         : {m['n_sensors']}

    Métricas de Recuperación Espacial:
      Celdas totales   : {m['n_total']}
      Celdas activas   : {m['n_active']}
      Celdas de aire   : {m['n_nan']}

      Correlación de Pearson (r) : {m['pearson_r']:.4f}
      Recuperación de signo      : {m['sign_recovery_pct']:.1f}%
      RMSE contraste             : {m['rmse_contrast']:.6f} t/m³
      SNR de recuperación        : {m['snr_db']:.2f} dB

    Calidad de Inversión:
      Misfit LSQR                : {m['misfit_percent']:.2f}%
      Diagnóstico espacial       : {m['spatial_correlation_label']}

    Tiempo de ejecución          : {m['elapsed_s']:.2f} s
    Timestamp                    : {m['timestamp_utc']}

    VEREDICTO QA: {pass_fail}
    ─ r ≥ 0.7 → BUENA recuperación (nivel benchmark industrial)
    ─ r ≥ 0.4 → MODERADA (aceptable para exploración conceptual)
    ─ r < 0.4 → FALLO: ajustar lambda_mag, grilla o cutoff_radius

    NOTA: Este test no garantiza exactitud absoluta. Las limitaciones del
    checkerboard son conocidas en geofísica aplicada. Un r bajo puede
    indicar regularización excesiva o escala de grilla inapropiada.
    """)
    print(report)


# ─────────────────────────────────────────────────────────────────────────────
# 6. CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TerraQuantum — Checkerboard QA Test (Fase 11)"
    )
    parser.add_argument("--nx",           type=int,   default=DEFAULT_NX)
    parser.add_argument("--ny",           type=int,   default=DEFAULT_NY)
    parser.add_argument("--nz",           type=int,   default=DEFAULT_NZ)
    parser.add_argument("--block_size",   type=float, default=DEFAULT_BLOCK_SIZE)
    parser.add_argument("--contrast",     type=float, default=DEFAULT_CONTRAST)
    parser.add_argument("--lambda_mag",   type=float, default=DEFAULT_LAMBDA_MAG)
    parser.add_argument("--alpha_spatial",type=float, default=DEFAULT_ALPHA_SPATIAL)
    parser.add_argument("--noise_pct",    type=float, default=0.02)
    parser.add_argument("--noise_floor",  type=float, default=0.001)
    parser.add_argument("--seed",         type=int,   default=42,
                        help="Realizacion de ruido. Una semilla NO es una muestra: "
                             "barrer varias es lo que dice si el numero es del survey "
                             "o de la tirada (Fase 26, direccion 5).")
    parser.add_argument("--quiet",        action="store_true",
                        help="Suprimir reporte detallado (solo métricas JSON)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    metrics = run_checkerboard_test(
        nx=args.nx,
        ny=args.ny,
        nz=args.nz,
        block_size=args.block_size,
        contrast=args.contrast,
        lambda_mag=args.lambda_mag,
        alpha_spatial=args.alpha_spatial,
        noise_pct=args.noise_pct,
        noise_floor=args.noise_floor,
        seed=args.seed,
        verbose=not args.quiet,
    )

    # Exit code: 0 si r >= 0.4, 1 si falla el QA
    if metrics.get("pearson_r", 0.0) < 0.4:
        sys.exit(1)

    sys.exit(0)
