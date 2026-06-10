"""
Inversion Kernel Service — Fase 2 (Plan Industrial Tier 1, §2.1)

Módulo aislado con las funciones de construcción de grilla, sensores y QAQC.
Extraído de geophysics_service.py para separación de responsabilidades.
geophysics_service.py importa desde aquí y re-exporta para compatibilidad.
"""
import numpy as np

from core.logging import get_logger
from schemas.geophysics_schema import GeophysicsInvertInput

_log = get_logger(__name__)


def build_voxel_grid(params: GeophysicsInvertInput):
    nx = params.nx
    ny = params.ny
    nz = params.nz
    dx = params.block_size

    grid_x, grid_y, grid_z = np.mgrid[0:nx, 0:ny, 0:nz]

    ix = grid_x.flatten(order="F")  # order="F" para coherencia con GravimetryInversion / reshape(..., order="F")
    iy = grid_y.flatten(order="F")
    iz = grid_z.flatten(order="F")

    x_c = (ix * dx) + (dx / 2)
    y_c = (iy * dx) + (dx / 2)
    z_c = (iz * dx) + (dx / 2)

    return ix, iy, iz, x_c, y_c, z_c


def build_tensor_mesh_with_padding(
    params: GeophysicsInvertInput,
    n_pad: int = 5,
    pad_factor: float = 1.3,
) -> dict:
    """
    F0.9 — Tensor Mesh con Padding Geométrico.

    Construye una grilla 3D con un bloque CORE uniforme (nx×ny×nz celdas de tamaño dx)
    y n_pad capas de padding en cada cara (+X, -X, +Y, -Y, +Z, -Z).
    Las celdas de padding crecen geométricamente hacia afuera:
        h_{i+1} = h_i * pad_factor

    Los centros de las celdas CORE se alinean exactamente con los de build_voxel_grid:
        x_core_k = (k + 0.5) * dx  para k = 0..nx-1

    Retorna un dict con:
    ─────────────────────────────────────────────────────────────────────────
    Grilla COMPLETA (Core + Padding) — para el solver LSQR:
      x_c, y_c, z_c   : centros de TODAS las celdas, Fortran order flat
      hx, hy, hz       : arrays 1D de anchos de celda (para Laplaciano no-uniforme)
      nx_total, ny_total, nz_total : dimensiones totales

    Grilla CORE — para diagnósticos, focusing y block model:
      ix_core, iy_core, iz_core : índices 0..n-1 (Fortran order)
      x_c_core, y_c_core, z_c_core : centros de celdas core únicamente
      is_core : máscara booleana global (True para celdas Core, False para padding)
    ─────────────────────────────────────────────────────────────────────────
    """
    nx, ny, nz = params.nx, params.ny, params.nz
    dx = float(params.block_size)

    def make_padded_widths(n_core: int, h_core: float) -> np.ndarray:
        # Celdas de padding saliendo del Core:  h, h·f, h·f², …, h·f^(n_pad-1)
        pad_out = np.array([h_core * (pad_factor ** i) for i in range(n_pad)], dtype=np.float64)
        left_pad  = pad_out[::-1].copy()         # más ancha primero → más angosta en el borde core
        core_widths = np.full(n_core, h_core, dtype=np.float64)
        right_pad = pad_out.copy()               # más angosta en el borde core → más ancha afuera
        return np.concatenate([left_pad, core_widths, right_pad])

    hx = make_padded_widths(nx, dx)
    hy = make_padded_widths(ny, dx)
    hz = make_padded_widths(nz, dx)

    nx_total = len(hx)   # nx + 2*n_pad
    ny_total = len(hy)
    nz_total = len(hz)

    def cell_centers_from_widths(h: np.ndarray) -> np.ndarray:
        """Centros de celdas desde el borde izquierdo absoluto (borde = 0)."""
        edges = np.concatenate([[0.0], np.cumsum(h)])
        return 0.5 * (edges[:-1] + edges[1:])

    x_centers_raw = cell_centers_from_widths(hx)
    y_centers_raw = cell_centers_from_widths(hy)
    z_centers_raw = cell_centers_from_widths(hz)

    # Offset: alinear primer centro Core con (dx/2), igual que build_voxel_grid.
    # x_centers_raw[n_pad] = sum(left_pad_widths) + dx/2  → offset = dx/2 - x_centers_raw[n_pad]
    x_centers = x_centers_raw + (dx / 2.0 - x_centers_raw[n_pad])
    y_centers = y_centers_raw + (dx / 2.0 - y_centers_raw[n_pad])
    z_centers = z_centers_raw + (dx / 2.0 - z_centers_raw[n_pad])

    # ── Grilla 3D completa (Core + Padding), Fortran order ───────────────────
    grid_x, grid_y, grid_z = np.mgrid[0:nx_total, 0:ny_total, 0:nz_total]
    ix_full = grid_x.flatten(order="F").astype(np.int32)
    iy_full = grid_y.flatten(order="F").astype(np.int32)
    iz_full = grid_z.flatten(order="F").astype(np.int32)

    x_c_full = x_centers[ix_full]
    y_c_full = y_centers[iy_full]
    z_c_full = z_centers[iz_full]

    # ── Máscara booleana: Core = True ────────────────────────────────────────
    is_core = (
        (ix_full >= n_pad) & (ix_full < n_pad + nx) &
        (iy_full >= n_pad) & (iy_full < n_pad + ny) &
        (iz_full >= n_pad) & (iz_full < n_pad + nz)
    )

    # ── Arrays Core (sin padding) ─────────────────────────────────────────────
    ix_core   = ix_full[is_core] - n_pad    # 0..nx-1, Fortran order
    iy_core   = iy_full[is_core] - n_pad    # 0..ny-1
    iz_core   = iz_full[is_core] - n_pad    # 0..nz-1
    x_c_core  = x_c_full[is_core]
    y_c_core  = y_c_full[is_core]
    z_c_core  = z_c_full[is_core]

    total_padded = nx_total * ny_total * nz_total
    print(
        f"[F0.9 TENSOR MESH] Core: {nx}×{ny}×{nz} ({nx*ny*nz:,} celdas) | "
        f"Total c/padding: {nx_total}×{ny_total}×{nz_total} ({total_padded:,}) | "
        f"n_pad={n_pad} | factor={pad_factor}"
    )

    return {
        # Grilla completa (solver)
        "x_c":      x_c_full,
        "y_c":      y_c_full,
        "z_c":      z_c_full,
        "hx":       hx,
        "hy":       hy,
        "hz":       hz,
        "nx_total": nx_total,
        "ny_total": ny_total,
        "nz_total": nz_total,
        # Core (diagnósticos + frontend)
        "ix_core":   ix_core,
        "iy_core":   iy_core,
        "iz_core":   iz_core,
        "x_c_core":  x_c_core,
        "y_c_core":  y_c_core,
        "z_c_core":  z_c_core,
        "is_core":   is_core,
    }


def build_sensor_arrays(params: GeophysicsInvertInput):
    sensor_coords = np.array(
        [[obs.x_m, obs.y_m, obs.z_m] for obs in params.observations],
        dtype=float,
    )

    g_observed = np.array(
        [obs.g for obs in params.observations],
        dtype=float,
    )

    if not np.isfinite(sensor_coords).all():
        raise ValueError(
            "Las coordenadas de sensores contienen valores inválidos: NaN o Inf."
        )

    if not np.isfinite(g_observed).all():
        raise ValueError(
            "Las observaciones gravimétricas contienen valores inválidos: NaN o Inf."
        )

    if np.allclose(g_observed, 0.0):
        raise ValueError(
            "Las observaciones gravimétricas son todas cercanas a cero. No hay señal suficiente para invertir."
        )

    # Separación regional-residual (opcional, OFF por defecto → comportamiento intacto).
    # Gap industrial #2: resta una tendencia regional polinómica antes de invertir.
    if getattr(params, "remove_regional", False):
        from services.gravity_preprocessing_service import separate_regional_residual

        g_observed, regional_meta = separate_regional_residual(
            sensor_coords, g_observed, order=getattr(params, "regional_order", 2)
        )
        _log.info(
            "[INVERSIÓN] Regional-residual aplicado (poly-%d): residual std=%.4g",
            regional_meta["regional_order"], regional_meta["residual_std"],
        )

    return sensor_coords, g_observed


def build_observation_qaqc_report(params: GeophysicsInvertInput, sensor_coords: np.ndarray, g_observed: np.ndarray):
    x = sensor_coords[:, 0]
    y = sensor_coords[:, 1]
    z = sensor_coords[:, 2]

    observation_count = len(g_observed)

    x_min, x_max = float(np.min(x)), float(np.max(x))
    y_min, y_max = float(np.min(y)), float(np.max(y))
    z_min, z_max = float(np.min(z)), float(np.max(z))
    g_min, g_max = float(np.min(g_observed)), float(np.max(g_observed))

    g_mean = float(np.mean(g_observed))
    g_std = float(np.std(g_observed))
    g_rms = float(np.sqrt(np.mean(g_observed**2)))

    domain_x = float(params.nx * params.block_size)
    domain_y = float(params.ny * params.block_size)
    domain_z = float(params.nz * params.block_size)

    span_x = float(x_max - x_min)
    span_y = float(y_max - y_min)
    span_z = float(z_max - z_min)

    coverage_ratio_x = float(span_x / max(domain_x, 1e-9))
    coverage_ratio_z = float(span_z / max(domain_z, 1e-9))

    signal_dynamic_range = float(g_max - g_min)

    warnings = []

    if coverage_ratio_x < 0.35:
        warnings.append("Cobertura espacial baja en X.")
    if coverage_ratio_z < 0.35:
        warnings.append("Cobertura espacial baja en Z.")

    if signal_dynamic_range <= 1e-6:
        warnings.append("Señal gravimétrica con bajo rango dinámico.")

    if observation_count < 20:
        warnings.append("Cantidad mínima de observaciones: resultado sensible al ruido.")

    if coverage_ratio_x < 0.2 and coverage_ratio_z < 0.2:
        warnings.append("Observaciones concentradas en una zona pequeña del dominio.")

    if len(warnings) == 0:
        quality_level = "GOOD"
        quality_score = 1.0
    elif len(warnings) <= 2:
        quality_level = "MEDIUM"
        quality_score = 0.6
    else:
        quality_level = "LOW"
        quality_score = 0.3

    return {
        "observation_count": observation_count,
        "x_min": x_min, "x_max": x_max,
        "y_min": y_min, "y_max": y_max,
        "z_min": z_min, "z_max": z_max,
        "g_min": g_min, "g_max": g_max,
        "g_mean": g_mean, "g_std": g_std, "g_rms": g_rms,
        "spatial_span_x": span_x,
        "spatial_span_y": span_y,
        "spatial_span_z": span_z,
        "domain_x": domain_x,
        "domain_y": domain_y,
        "domain_z": domain_z,
        "coverage_ratio_x": coverage_ratio_x,
        "coverage_ratio_z": coverage_ratio_z,
        "signal_dynamic_range": signal_dynamic_range,
        "quality_score": quality_score,
        "quality_level": quality_level,
        "warnings": warnings,
    }
