"""
FASE 10 — Exportación Industrial VTK (formato .vtr — Rectilinear Grid)
FASE 11 — Exportación Industrial GSLIB y UBC-mesh (Interoperabilidad)
=======================================================================

Exporta el Block Model de inversión gravimétrica TerraQuantum a formato
VTR (XML Rectilinear Grid) usando pyevtk. Compatible con:
  - ParaView (filtro Threshold en Is_Active=1 para descartar aire)
  - Leapfrog Geo / Vulcan (importación directa de VTK Rectilinear Grid)
  - GOCAD / Petrel (con conversión VTK→SGEMS)

Reglas de diseño:
  - Solo exporta zona CORE (sin celdas de Padding del Tensor Mesh).
  - Celdas de aire (is_active=False) guardan VTK_AIR_SENTINEL en densidad
    y 0 en sensibilidad; Is_Active=0 permite filtrarlas en ParaView.
  - Non-fatal: si pyevtk no está instalado, loguea un warning y retorna None.

Autor: TerraQuantum Backend | Fase 10
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Sentinels ────────────────────────────────────────────────────────────────
VTK_AIR_SENTINEL = np.float64(-9999.0)   # Valor dummy para celdas de aire
VTK_BASE_DENSITY = np.float64(2.6)       # g/cm³ — densidad base de roca encajante


# ─────────────────────────────────────────────────────────────────────────────
# 1. Función principal de exportación
# ─────────────────────────────────────────────────────────────────────────────

def export_block_model_to_vtr(
    filename_prefix: str,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
    data_dict: dict,
) -> Optional[str]:
    """
    Exporta el Block Model a formato .vtr (VTK Rectilinear Grid XML).

    Parámetros
    ──────────
    filename_prefix : str
        Ruta + prefijo SIN extensión. pyevtk agrega ".vtr" automáticamente.
        Ej.: "/data/projects/p1/runs/r1/block_model_core"

    x_edges, y_edges, z_edges : np.ndarray 1D float64
        Bordes de celdas (N+1 valores para N celdas en cada eje).
        x_edges.shape = (nx+1,)  ·  y_edges.shape = (ny+1,)  ·  z_edges.shape = (nz+1,)

    data_dict : dict[str, np.ndarray]
        Arrays 3D con shape (nx, ny, nz) en orden Fortran (x varía más rápido).
        Claves OBLIGATORIAS:
          "Density_Contrast_gcm3" : float64  — contraste respecto a 2.6 g/cm³
          "Sensitivity_Proxy"     : float64  — DOI normalizado [0, 1]
          "Is_Active"             : int32    — 1=roca, 0=aire (para Threshold en ParaView)

    Retorna
    ───────
    str : Ruta completa del .vtr generado, o None si pyevtk no está disponible.
    """
    # ── Resolver función de escritura (compatibilidad pyevtk v1.x y v2.x) ────
    _write_fn = None
    try:
        from pyevtk.hl import gridToVTK as _write_fn          # pyevtk >= 1.0 (PyPI)
    except ImportError:
        pass

    if _write_fn is None:
        try:
            from pyevtk.hl import rectilinearToVTK as _write_fn   # pyevtk legacy
        except ImportError:
            pass

    if _write_fn is None:
        logger.warning(
            "[FASE 10] pyevtk no instalado — exportación VTR omitida. "
            "Instala con: pip install pyevtk"
        )
        return None

    # ── Validar dimensiones ──────────────────────────────────────────────────
    nx = int(len(x_edges) - 1)
    ny = int(len(y_edges) - 1)
    nz = int(len(z_edges) - 1)

    if nx <= 0 or ny <= 0 or nz <= 0:
        raise ValueError(
            f"[FASE 10] Dimensiones de grilla inválidas: nx={nx}, ny={ny}, nz={nz}. "
            "Verifica que los edges tengan al menos 2 valores."
        )

    required_keys = {"Density_Contrast_gcm3", "Sensitivity_Proxy", "Is_Active"}
    missing = required_keys - set(data_dict.keys())
    if missing:
        raise ValueError(f"[FASE 10] data_dict le faltan las claves: {missing}")

    # ── Preparar edges: float64 C-contiguous ────────────────────────────────
    x_e = np.ascontiguousarray(x_edges, dtype=np.float64)
    y_e = np.ascontiguousarray(y_edges, dtype=np.float64)
    z_e = np.ascontiguousarray(z_edges, dtype=np.float64)

    # ── Preparar cell data: shape (nx, ny, nz) Fortran-contiguous ───────────
    vtk_cell_data: dict[str, np.ndarray] = {}
    for key, arr in data_dict.items():
        a = np.asarray(arr)
        if a.shape != (nx, ny, nz):
            raise ValueError(
                f"[FASE 10] Array '{key}' tiene shape {a.shape}, "
                f"se esperaba ({nx}, {ny}, {nz})."
            )
        if key == "Is_Active":
            vtk_cell_data[key] = np.asfortranarray(a.astype(np.int32))
        else:
            vtk_cell_data[key] = np.asfortranarray(a.astype(np.float64))

    # ── Crear directorio destino ─────────────────────────────────────────────
    out_dir = Path(filename_prefix).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Escribir VTR ─────────────────────────────────────────────────────────
    _write_fn(
        str(filename_prefix),
        x_e, y_e, z_e,
        cellData=vtk_cell_data,
        pointData=None,
    )

    vtr_path = str(filename_prefix) + ".vtr"
    size_kb = Path(vtr_path).stat().st_size / 1024 if Path(vtr_path).exists() else 0
    logger.info(
        "[FASE 10] VTR generado | path=%s | nx=%d ny=%d nz=%d | size=%.1f KB",
        vtr_path, nx, ny, nz, size_kb,
    )
    return vtr_path


# ─────────────────────────────────────────────────────────────────────────────
# 2. Helper: construir arrays VTK desde arrays Core del servicio de inversión
# ─────────────────────────────────────────────────────────────────────────────

def build_vtk_core_arrays(
    nx: int,
    ny: int,
    nz: int,
    dx: float,
    est_density: np.ndarray,
    sensitivity: np.ndarray,
    is_active_flat: Optional[np.ndarray] = None,
) -> tuple:
    """
    Construye edges y data_dict listos para export_block_model_to_vtr.

    Parámetros
    ──────────
    nx, ny, nz : int        — Dimensiones del bloque Core
    dx         : float      — Tamaño de celda en metros (celdas cúbicas)
    est_density : 1D array  — Densidad absoluta en Fortran order (nx*ny*nz,)
    sensitivity : 1D array  — Sensibilidad/DOI normalizado en Fortran order
    is_active_flat : 1D bool array opcional — True = roca, False = aire.
                    Si None, se infiere de np.isfinite(est_density).

    Retorna
    ───────
    (x_edges, y_edges, z_edges, data_dict)
        - x/y/z_edges: arrays 1D de N+1 bordes de celda
        - data_dict  : dict con los 3 arrays 3D en Fortran order
    """
    n_core = nx * ny * nz
    density_arr = np.asarray(est_density, dtype=np.float64)
    sens_arr    = np.asarray(sensitivity,  dtype=np.float64)

    if len(density_arr) != n_core:
        raise ValueError(
            f"[FASE 10] est_density tiene {len(density_arr)} elementos, "
            f"esperado {n_core} (nx={nx} × ny={ny} × nz={nz})."
        )
    if len(sens_arr) != n_core:
        raise ValueError(
            f"[FASE 10] sensitivity tiene {len(sens_arr)} elementos, "
            f"esperado {n_core}."
        )

    # ── Bordes de celdas Core: uniformes, alineados en 0 ────────────────────
    # Para N celdas de tamaño dx, se necesitan N+1 bordes: 0, dx, 2dx, ..., N·dx
    x_edges = np.linspace(0.0, nx * dx, nx + 1, dtype=np.float64)
    y_edges = np.linspace(0.0, ny * dx, ny + 1, dtype=np.float64)
    z_edges = np.linspace(0.0, nz * dx, nz + 1, dtype=np.float64)

    # ── Máscara de celdas activas ────────────────────────────────────────────
    if is_active_flat is None:
        is_active = np.isfinite(density_arr)
    else:
        is_active = np.asarray(is_active_flat, dtype=bool)
        if len(is_active) != n_core:
            raise ValueError(
                f"[FASE 10] is_active_flat tiene {len(is_active)} elementos, "
                f"esperado {n_core}."
            )

    # ── Calcular contraste de densidad ───────────────────────────────────────
    # Celdas de aire → sentinel; celdas activas → densidad_absoluta - 2.6
    density_contrast = np.where(
        is_active,
        density_arr - VTK_BASE_DENSITY,
        VTK_AIR_SENTINEL,
    )

    # ── Sensibilidad (DOI proxy): celdas de aire → 0.0 ──────────────────────
    sens_clean = np.where(is_active, np.nan_to_num(sens_arr, nan=0.0), 0.0)

    # ── Reshape 1D → 3D en Fortran order ────────────────────────────────────
    # El solver usa Fortran order (x varía más rápido), que es el mismo que
    # usa build_voxel_grid y build_tensor_mesh_with_padding.
    density_3d   = density_contrast.reshape((nx, ny, nz), order="F")
    sens_3d      = sens_clean.reshape((nx, ny, nz), order="F")
    is_active_3d = is_active.astype(np.int32).reshape((nx, ny, nz), order="F")

    data_dict = {
        "Density_Contrast_gcm3": density_3d,
        "Sensitivity_Proxy":     sens_3d,
        "Is_Active":             is_active_3d,
    }

    return x_edges, y_edges, z_edges, data_dict


# ─────────────────────────────────────────────────────────────────────────────
# 3. Función de alto nivel: pipeline completo desde arrays Core
# ─────────────────────────────────────────────────────────────────────────────

def export_core_to_vtr(
    output_dir: str,
    run_prefix: str,
    nx: int,
    ny: int,
    nz: int,
    dx: float,
    est_density: np.ndarray,
    sensitivity: np.ndarray,
    is_active_flat: Optional[np.ndarray] = None,
) -> Optional[str]:
    """
    Pipeline completo: build_vtk_core_arrays → export_block_model_to_vtr.

    Parámetros
    ──────────
    output_dir   : str  — Directorio donde guardar el .vtr
    run_prefix   : str  — Prefijo del nombre de archivo (ej. "block_model_core")
    nx, ny, nz   : int  — Dimensiones Core
    dx           : float — Tamaño de celda en metros
    est_density  : 1D array — Densidades absolutas en Fortran order
    sensitivity  : 1D array — DOI normalizado en Fortran order
    is_active_flat: 1D bool array opcional

    Retorna
    ───────
    str : ruta del .vtr generado, o None si pyevtk no está disponible.
    """
    try:
        x_edges, y_edges, z_edges, data_dict = build_vtk_core_arrays(
            nx=nx, ny=ny, nz=nz, dx=dx,
            est_density=est_density,
            sensitivity=sensitivity,
            is_active_flat=is_active_flat,
        )

        filename_prefix = str(Path(output_dir) / run_prefix)

        return export_block_model_to_vtr(
            filename_prefix=filename_prefix,
            x_edges=x_edges,
            y_edges=y_edges,
            z_edges=z_edges,
            data_dict=data_dict,
        )

    except ImportError:
        return None  # pyevtk no instalado — ya logueado en export_block_model_to_vtr

    except Exception as exc:
        logger.warning(
            "[FASE 10] Error en exportación VTR (non-fatal): %s", exc
        )
        return None


# ═════════════════════════════════════════════════════════════════════════════
# FASE 11 — GSLIB Export (interoperabilidad con software minero industrial)
# ═════════════════════════════════════════════════════════════════════════════

def export_block_model_to_gslib(
    output_path: str,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    density: np.ndarray,
    density_contrast: np.ndarray,
    sensitivity: np.ndarray,
    is_active: np.ndarray,
    project_id: str = "unknown",
    run_id: str = "unknown",
) -> str:
    """
    FASE 11 — Exporta el Block Model a formato GSLIB (ASCII).

    El formato GSLIB es un estándar de texto plano legible por:
      - SGeMS, GSLIB (Stanford Geostatistical Library)
      - Leapfrog, Surpac, Minesight, Datamine
      - Cualquier parser de texto simple

    Estructura del archivo:
        Línea 1  : título descriptivo
        Línea 2  : número de variables (N)
        Líneas 3..N+2 : nombre de cada variable
        Líneas N+3... : valores numéricos, una fila por vóxel, espacio separado

    Los vóxeles de aire (is_active=0) se exportan con NODATA_VALUE=-9999.0.

    Parámetros
    ----------
    output_path      : ruta completa del archivo de salida (.gslib o .dat)
    x_c, y_c, z_c   : coordenadas de centros de vóxeles (1D arrays)
    density          : densidad absoluta (t/m³) — NaN para aire
    density_contrast : densidad - base_density
    sensitivity      : DOI proxy normalizado [0, 1]
    is_active        : 1=roca, 0=aire

    Retorna
    -------
    str : ruta del archivo generado
    """
    NODATA = -9999.0
    VARIABLES = ["X", "Y", "Z", "Density_gcm3", "Density_Contrast_gcm3",
                 "Sensitivity_Proxy", "Is_Active"]
    N_VARS = len(VARIABLES)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    x_arr  = np.asarray(x_c,            dtype=np.float64)
    y_arr  = np.asarray(y_c,            dtype=np.float64)
    z_arr  = np.asarray(z_c,            dtype=np.float64)
    d_arr  = np.where(np.isfinite(np.asarray(density,          dtype=np.float64)),
                      np.asarray(density,          dtype=np.float64), NODATA)
    dc_arr = np.where(np.isfinite(np.asarray(density_contrast, dtype=np.float64)),
                      np.asarray(density_contrast, dtype=np.float64), NODATA)
    s_arr  = np.where(np.isfinite(np.asarray(sensitivity,      dtype=np.float64)),
                      np.asarray(sensitivity,      dtype=np.float64), 0.0)
    a_arr  = np.asarray(is_active, dtype=np.int32)

    n_voxels = len(x_arr)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="ascii") as f:
        # Header GSLIB
        f.write(
            f"TerraQuantum Block Model | project={project_id} run={run_id} "
            f"| {ts} | NODATA={NODATA}\n"
        )
        f.write(f"{N_VARS}\n")
        for var in VARIABLES:
            f.write(f"{var}\n")

        # Data rows
        for i in range(n_voxels):
            f.write(
                f"{x_arr[i]:.4f} {y_arr[i]:.4f} {z_arr[i]:.4f} "
                f"{d_arr[i]:.6f} {dc_arr[i]:.6f} "
                f"{s_arr[i]:.6f} {a_arr[i]}\n"
            )

    size_kb = out_path.stat().st_size / 1024
    logger.info(
        "[FASE 11] GSLIB exportado | path=%s | vóxeles=%d | size=%.1f KB",
        str(out_path), n_voxels, size_kb,
    )
    return str(out_path)


# ═════════════════════════════════════════════════════════════════════════════
# FASE 11 — UBC-mesh Export (estándar UBC-GIF)
# ═════════════════════════════════════════════════════════════════════════════

def export_block_model_to_ubc(
    output_dir: str,
    run_prefix: str,
    nx: int,
    ny: int,
    nz: int,
    dx: float,
    dy: float,
    dz: float,
    origin_x: float,
    origin_y: float,
    origin_z: float,
    density: np.ndarray,
    is_active: Optional[np.ndarray] = None,
    project_id: str = "unknown",
    run_id: str = "unknown",
) -> dict:
    """
    FASE 11 — Exporta el Block Model a formato UBC-mesh (estándar UBC-GIF).

    El formato UBC-GIF es el estándar de la industria para inversion software:
      - UBC-GIF (MAG3D, GRAV3D, IP3D, DC3D)
      - SimPEG (Python open source)
      - EarthImager, Oasis Montaj

    Genera DOS archivos:
      1. <prefix>.msh  — Archivo de malla (mesh file)
         Línea 1: nE nN nZ (celdas en E, N, Z — UBC usa orden y-primero)
         Línea 2: Emin Nmax Zmax (origen = esquina superior-noroeste)
         Línea 3: hE hE ... (anchos de celda en Este — nx valores)
         Línea 4: hN hN ... (anchos de celda en Norte — ny valores)
         Línea 5: hZ hZ ... (anchos de celda en Z/profundidad — nz valores)

      2. <prefix>.mod  — Archivo de modelo de propiedades
         Un valor por línea, en orden UBC-GIF:
         z varía más rápido, luego y (N-S), luego x (E-W).
         Celdas inactivas (aire) → NODATA_VALUE.

    Convención UBC-GIF:
      - Eje Z positivo hacia ARRIBA (opuesto a la convención interna de TerraQuantum).
      - Origin = esquina NW-superior del volumen.
      - El archivo .mod tiene n_cells líneas (sin header).

    Parámetros
    ----------
    output_dir   : directorio de salida
    run_prefix   : prefijo del nombre de archivo (ej. "block_model_core")
    nx, ny, nz   : número de celdas en E, N, Z
    dx, dy, dz   : tamaño de celda en cada eje (metros) — puede ser diferente
    origin_x/y/z : coordenadas de la esquina superior-izquierda del volumen
    density      : array 1D flat de densidades absolutas (Fortran order interno)
    is_active    : array 1D bool — True=roca, False=aire. Si None, infiere de isfinite(density).

    Retorna
    -------
    dict con claves "mesh_path", "model_path", "n_cells"
    """
    from datetime import datetime, timezone
    NODATA = -9999.0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    density_arr = np.asarray(density, dtype=np.float64)
    n_cells = nx * ny * nz

    if len(density_arr) != n_cells:
        raise ValueError(
            f"[FASE 11 UBC] density tiene {len(density_arr)} elementos, "
            f"esperado {n_cells} (nx={nx}×ny={ny}×nz={nz})."
        )

    if is_active is None:
        active_mask = np.isfinite(density_arr)
    else:
        active_mask = np.asarray(is_active, dtype=bool)
        if len(active_mask) != n_cells:
            raise ValueError(
                f"[FASE 11 UBC] is_active tiene {len(active_mask)} elementos, esperado {n_cells}."
            )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mesh_path  = out_dir / f"{run_prefix}.msh"
    model_path = out_dir / f"{run_prefix}.mod"

    # ── 1. Archivo de malla (.msh) ───────────────────────────────────────────
    # UBC-GIF: nE nN nZ en primera línea; origin NW-superior; hE hN hZ
    with mesh_path.open("w", encoding="ascii") as f:
        f.write(f"! TerraQuantum UBC-mesh | project={project_id} run={run_id} | {ts}\n")
        f.write(f"{nx} {ny} {nz}\n")
        # Origen UBC: esquina superior-noroeste
        # Z UBC = positivo hacia arriba → origin_z + nz*dz es la cota más alta
        ubc_origin_z = origin_z + nz * dz
        f.write(f"{origin_x:.4f} {origin_y:.4f} {ubc_origin_z:.4f}\n")
        # Anchos de celda (valores repetidos para grilla uniforme)
        f.write(" ".join([f"{dx:.4f}"] * nx) + "\n")
        f.write(" ".join([f"{dy:.4f}"] * ny) + "\n")
        f.write(" ".join([f"{dz:.4f}"] * nz) + "\n")

    # ── 2. Archivo de modelo (.mod) ───────────────────────────────────────────
    # Orden UBC-GIF (z varía más rápido, luego y, luego x):
    # El modelo interno TerraQuantum usa Fortran order (x varía más rápido).
    # Necesitamos reordenar: flatten en orden C luego transponer ejes.

    # Reshape de Fortran 1D → 3D (nx, ny, nz) en orden F
    density_3d = density_arr.reshape((nx, ny, nz), order="F")
    active_3d  = active_mask.reshape((nx, ny, nz), order="F")

    # UBC-GIF orden: ix varía más lento, iy varía, iz varía más rápido
    # → iterar en ix(E), iy(N), iz(Z desde arriba)
    # Z en UBC es positivo hacia arriba → invertimos el eje Z
    density_ubc = density_3d[:, :, ::-1]   # flip Z
    active_ubc  = active_3d[:,  :, ::-1]

    with model_path.open("w", encoding="ascii") as f:
        f.write(f"! TerraQuantum UBC-model | project={project_id} run={run_id} | {ts}\n")
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    val = density_ubc[ix, iy, iz]
                    if active_ubc[ix, iy, iz] and np.isfinite(val):
                        f.write(f"{val:.6f}\n")
                    else:
                        f.write(f"{NODATA:.1f}\n")

    mesh_kb  = mesh_path.stat().st_size  / 1024
    model_kb = model_path.stat().st_size / 1024

    logger.info(
        "[FASE 11] UBC-mesh exportado | mesh=%s (%.1f KB) | model=%s (%.1f KB) | n_cells=%d",
        str(mesh_path), mesh_kb, str(model_path), model_kb, n_cells,
    )

    return {
        "mesh_path":  str(mesh_path),
        "model_path": str(model_path),
        "n_cells":    n_cells,
        "mesh_kb":    round(mesh_kb, 2),
        "model_kb":   round(model_kb, 2),
    }


def export_core_to_gslib(
    output_dir: str,
    run_prefix: str,
    nx: int,
    ny: int,
    nz: int,
    dx: float,
    est_density: np.ndarray,
    sensitivity: np.ndarray,
    is_active_flat: Optional[np.ndarray] = None,
    project_id: str = "unknown",
    run_id: str = "unknown",
) -> Optional[str]:
    """
    Pipeline de alto nivel: construye coordenadas de centros y exporta a GSLIB.

    Retorna la ruta del archivo generado, o None si ocurre un error.
    """
    try:
        n_core = nx * ny * nz
        density_arr = np.asarray(est_density, dtype=np.float64)
        sens_arr    = np.asarray(sensitivity,  dtype=np.float64)

        if is_active_flat is None:
            is_active = np.isfinite(density_arr)
        else:
            is_active = np.asarray(is_active_flat, dtype=bool)

        # Centros de vóxeles (Fortran order)
        ix_g, iy_g, iz_g = np.mgrid[0:nx, 0:ny, 0:nz]
        x_c = (ix_g.ravel(order="F") * dx + dx / 2.0).astype(np.float64)
        y_c = (iy_g.ravel(order="F") * dx + dx / 2.0).astype(np.float64)
        z_c = (iz_g.ravel(order="F") * dx + dx / 2.0).astype(np.float64)

        density_contrast = np.where(
            is_active,
            density_arr - VTK_BASE_DENSITY,
            np.nan,
        )

        out_path = str(Path(output_dir) / f"{run_prefix}.gslib")
        return export_block_model_to_gslib(
            output_path=out_path,
            x_c=x_c, y_c=y_c, z_c=z_c,
            density=density_arr,
            density_contrast=density_contrast,
            sensitivity=sens_arr,
            is_active=is_active.astype(np.int32),
            project_id=project_id,
            run_id=run_id,
        )
    except Exception as exc:
        logger.warning("[FASE 11] Error en exportación GSLIB (non-fatal): %s", exc)
        return None


def export_core_to_ubc(
    output_dir: str,
    run_prefix: str,
    nx: int,
    ny: int,
    nz: int,
    dx: float,
    est_density: np.ndarray,
    is_active_flat: Optional[np.ndarray] = None,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    project_id: str = "unknown",
    run_id: str = "unknown",
) -> Optional[dict]:
    """
    Pipeline de alto nivel para UBC-mesh export.

    Retorna dict {"mesh_path", "model_path", "n_cells"} o None si hay error.
    """
    try:
        return export_block_model_to_ubc(
            output_dir=output_dir,
            run_prefix=run_prefix,
            nx=nx, ny=ny, nz=nz,
            dx=dx, dy=dx, dz=dx,
            origin_x=origin_x,
            origin_y=origin_y,
            origin_z=origin_z,
            density=est_density,
            is_active=is_active_flat,
            project_id=project_id,
            run_id=run_id,
        )
    except Exception as exc:
        logger.warning("[FASE 11] Error en exportación UBC-mesh (non-fatal): %s", exc)
        return None


# ═════════════════════════════════════════════════════════════════════════════
# FASE 11 — Bundle ZIP industrial + QA Diagnostics
# (Lee datos persistidos en disco — NO ejecuta física nueva)
# ═════════════════════════════════════════════════════════════════════════════

import hashlib
import io
import json as _json
import math as _math
import zipfile
from datetime import datetime, timezone
from typing import Any

from core.block_model_store import (
    RUN_BLOCK_MODEL_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_SOURCE_GRAVITY_FILENAME,
    RUN_VTK_FILENAME,
    clean_trace_context,
    get_run_dir,
    get_run_inputs_path,
    get_run_report_path,
    sha256_file,
)
from core.config import APP_VERSION

# Claves físicas auditadas (mismo set que reporting/report_generator.py)
_AUDIT_KEYS: list[str] = [
    "nx", "ny", "nz", "block_size", "cutoff_radius",
    "lambda_mag", "alpha_spatial", "depth", "nir", "fe",
    "enable_focusing", "noise_floor", "noise_pct",
]


def _cfg_hash(inputs: dict[str, Any]) -> str:
    """SHA-256[:16] de los parámetros físicos — audit trail Fase 11."""
    stable = {k: inputs.get(k) for k in _AUDIT_KEYS if k in inputs}
    payload = _json.dumps(stable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16].upper()


def _read_json(path: "Path | None") -> "dict[str, Any] | None":
    if path is None or not path.exists():
        return None
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _densities_from_parquet(run_dir: Path, total: int) -> list[float]:
    """Lee densidades del parquet persistido. Sin cálculos nuevos."""
    try:
        import pandas as pd
        bm_path = run_dir / RUN_BLOCK_MODEL_FILENAME
        if not bm_path.exists():
            return [2.6] * total
        df = pd.read_parquet(bm_path)
        for col in ("density", "density_absolute", "density_contrast"):
            if col in df.columns:
                vals = list(df[col].astype(float))
                pad = total - len(vals)
                if pad > 0:
                    vals.extend([float("nan")] * pad)
                return vals[:total]
    except Exception:
        pass
    return [2.6] * total


def _ubc_msh_text(nx: int, ny: int, nz: int, bs: float) -> str:
    dx = " ".join(f"{bs:.2f}" for _ in range(nx))
    dy = " ".join(f"{bs:.2f}" for _ in range(ny))
    dz = " ".join(f"{bs:.2f}" for _ in range(nz))
    return f"{nx} {ny} {nz}\n0.00 0.00 0.00\n{dx}\n{dy}\n{dz}\n"


def _ubc_mod_text(densities: list[float]) -> str:
    lines = []
    for d in densities:
        lines.append("1e8" if (d is None or (isinstance(d, float) and _math.isnan(d))) else f"{float(d):.6f}")
    return "\n".join(lines) + "\n"


def _gslib_text(densities: list[float], nx: int, ny: int, nz: int, bs: float) -> str:
    hdr = [
        f"TerraQuantum Block Model {nx}x{ny}x{nz} bs={bs}m NO-JORC/NI-43-101",
        "5", "X_m", "Y_m", "Z_m", "Density_gcm3", "Is_Active",
    ]
    rows: list[str] = []
    idx = 0
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                d = densities[idx] if idx < len(densities) else None
                bad = d is None or (isinstance(d, float) and _math.isnan(d))
                rows.append(
                    f"{(ix+0.5)*bs:.2f} {(iy+0.5)*bs:.2f} {-(iz+0.5)*bs:.2f} "
                    f"{'-9999.000000' if bad else f'{float(d):.6f}'} {'0' if bad else '1'}"
                )
                idx += 1
    return "\n".join(hdr + rows) + "\n"


def _build_bundle_manifest(
    pid: str, rid: str, inputs: dict[str, Any],
    report: "dict[str, Any] | None", cfg_hash: str,
) -> dict[str, Any]:
    fit_diag = (report or {}).get("fitDiagnostics") or {}
    ts = report.get("technicalSummary") or {} if report else {}

    _run_dir_bm = get_run_dir(pid, rid)
    _parquet_path_bm = _run_dir_bm / RUN_BLOCK_MODEL_FILENAME
    _csv_path_bm = _run_dir_bm / RUN_SOURCE_GRAVITY_FILENAME
    try:
        _sha256_parquet = sha256_file(_parquet_path_bm) if _parquet_path_bm.exists() else None
    except Exception:
        _sha256_parquet = None
    try:
        _sha256_csv = sha256_file(_csv_path_bm) if _csv_path_bm.exists() else None
    except Exception:
        _sha256_csv = None

    # HITO 2: Read run_manifest.json if available and prefer its hashes (computed at inversion time).
    _run_manifest_provenance: "dict | None" = None
    try:
        _run_manifest_path = _run_dir_bm / RUN_MANIFEST_FILENAME
        if _run_manifest_path.exists():
            _run_manifest_provenance = _json.loads(_run_manifest_path.read_text(encoding="utf-8"))
            if _run_manifest_provenance.get("sha256_parquet"):
                _sha256_parquet = _run_manifest_provenance["sha256_parquet"]
            if _run_manifest_provenance.get("sha256_csv"):
                _sha256_csv = _run_manifest_provenance["sha256_csv"]
    except Exception:
        _run_manifest_provenance = None

    return {
        "schema_version": "11.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "terraquantum_version": APP_VERSION,
        "project_id": pid,
        "run_id": rid,
        "config_hash": f"SHA256[:{cfg_hash}]",
        "config_hash_raw": cfg_hash,
        "sha256_parquet": _sha256_parquet,
        "sha256_csv": _sha256_csv,
        "audit_keys_used": _AUDIT_KEYS,
        "inversion_params": {k: inputs.get(k) for k in _AUDIT_KEYS if k in inputs},
        "grid": {
            "nx": inputs.get("nx"), "ny": inputs.get("ny"), "nz": inputs.get("nz"),
            "block_size_m": inputs.get("block_size"),
        },
        "fit_diagnostics": {
            "fit_level": fit_diag.get("fit_level"),
            "normalized_rmse": fit_diag.get("normalized_rmse"),
            "residual_rmse": fit_diag.get("residual_rmse"),
            "residual_mae": fit_diag.get("residual_mae"),
            "misfit_error_percent": fit_diag.get("misfit_error_percent"),
        },
        "checkerboard_qa": {
            "pearson_r": (report or {}).get("checkerboard_pearson_r"),
            "overall_level": ts.get("overall_level"),
            "fit_level": fit_diag.get("fit_level"),
        } if report else None,
        "run_manifest_provenance": _run_manifest_provenance,
        "bundle_contents": [
            {"file": "model.vtr",      "format": "VTK RectilinearGrid XML",    "software": ["ParaView", "Leapfrog Geo"]},
            {"file": "model.mod",      "format": "UBC-GIF Density Model",      "software": ["UBC-GIF Grav3D", "SimPEG"]},
            {"file": "model.msh",      "format": "UBC-GIF Mesh Definition",    "software": ["UBC-GIF Grav3D", "SimPEG"]},
            {"file": "model.gslib",    "format": "Stanford GSLIB / SGeMS",     "software": ["SGeMS", "ISATIS"]},
            {"file": "manifest.json",  "format": "Audit Trail JSON Fase 11",   "note": "Trazabilidad completa"},
            {"file": "run_manifest.json", "format": "Run Provenance HITO 2",   "note": "SHA-256 parquet+CSV, solver_stats, schema_version"},
        ],
        "disclaimer": (
            "NO-JORC / NI 43-101 — EXPLORATION ONLY. "
            "Este bundle NO constituye declaración de Recursos ni Reservas Minerales. "
            "Requiere validación profesional por Persona Competente certificada."
        ),
        "legal_compliance": {
            "jorc_code_2012": "NOT_COMPLIANT — Modelo conceptual preliminar",
            "ni_43_101":      "NOT_COMPLIANT — Requiere QP/CP certificado",
            "samrec":         "NOT_COMPLIANT — Solo exploración preliminar",
        },
    }


def create_run_bundle_zip(project_id: str, run_id: str) -> "tuple[bytes, str]":
    """
    FASE 11 — Compila el bundle ZIP industrial para un run.

    Contenido: model.vtr, model.mod, model.msh, model.gslib, manifest.json.
    Lee únicamente datos persistidos — NO ejecuta inversión.

    Returns (zip_bytes, filename).
    """
    clean_pid, clean_rid = clean_trace_context(project_id, run_id)
    if not clean_pid or not clean_rid:
        raise ValueError("project_id y run_id son requeridos.")

    run_dir = get_run_dir(clean_pid, clean_rid)
    if not run_dir.exists():
        raise ValueError(f"Run no encontrada: {clean_pid}/{clean_rid}")

    inputs = _read_json(get_run_inputs_path(clean_pid, clean_rid)) or {}
    report = _read_json(get_run_report_path(clean_pid, clean_rid))

    nx = max(int(inputs.get("nx") or 8), 1)
    ny = max(int(inputs.get("ny") or 8), 1)
    nz = max(int(inputs.get("nz") or 8), 1)
    bs = max(float(inputs.get("block_size") or 100.0), 1.0)

    cfg_hash = _cfg_hash(inputs)
    manifest = _build_bundle_manifest(clean_pid, clean_rid, inputs, report, cfg_hash)

    msh   = _ubc_msh_text(nx, ny, nz, bs)
    dens  = _densities_from_parquet(run_dir, nx * ny * nz)
    mod   = _ubc_mod_text(dens)
    gslib = _gslib_text(dens, nx, ny, nz, bs)
    mfst  = _json.dumps(manifest, indent=2, ensure_ascii=False)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        vtr_path = run_dir / RUN_VTK_FILENAME
        if vtr_path.exists():
            zf.write(vtr_path, arcname="model.vtr")
        else:
            zf.writestr(
                "model.vtr.missing.txt",
                f"VTK no disponible para {clean_rid}. Ejecutar con export_vtk=true.\n",
            )
        zf.writestr("model.msh", msh)
        zf.writestr("model.mod", mod)
        zf.writestr("model.gslib", gslib)
        zf.writestr("manifest.json", mfst)

    safe = lambda s: "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in s)[:32]
    filename = f"terraquantum_bundle_{safe(clean_pid)}_{safe(clean_rid)}.zip"
    return buf.getvalue(), filename


def get_run_qa_diagnostics(project_id: str, run_id: str) -> "dict[str, Any]":
    """
    FASE 11 — Retorna datos de diagnóstico QA para el DiagnosticPanel del frontend.

    Lee únicamente datos persistidos (inputs.json + report.json).
    NO ejecuta inversión ni cálculos físicos nuevos.
    """
    clean_pid, clean_rid = clean_trace_context(project_id, run_id)
    if not clean_pid or not clean_rid:
        raise ValueError("project_id y run_id son requeridos.")

    inputs = _read_json(get_run_inputs_path(clean_pid, clean_rid)) or {}
    report = _read_json(get_run_report_path(clean_pid, clean_rid)) or {}
    fit_diag = report.get("fitDiagnostics") or {}
    cfg_hash = _cfg_hash(inputs)

    # ── L-Curve ───────────────────────────────────────────────────────────────
    l_curve_real: list[dict[str, Any]] = report.get("l_curve_trials") or []
    is_real_lcurve = bool(l_curve_real)
    if not is_real_lcurve:
        # Curva ilustrativa 5-puntos basada en métricas persistidas del run.
        base_m = float(fit_diag.get("residual_l2") or 1.0)
        base_r = float(fit_diag.get("normalized_rmse") or 0.5)
        lam0   = float(inputs.get("lambda_mag") or 1.0)
        factors = [0.01, 0.1, 1.0, 10.0, 100.0]
        l_curve_real = []
        for f in factors:
            log_f = _math.log10(max(f, 1e-10))
            m = max(base_m / (1.0 + log_f * 0.3 + 1.0), 1e-6)
            r = max(base_r * (1.0 + log_f * 0.4 + 0.2), 1e-6)
            l_curve_real.append({
                "lambda": round(lam0 * f, 8),
                "misfit_norm": round(m, 6),
                "roughness_norm": round(r, 6),
                "is_optimal": (f == 1.0),
            })

    # ── Checkerboard QA ────────────────────────────────────────────────────────
    pearson_raw = report.get("checkerboard_pearson_r")
    fit_level   = fit_diag.get("fit_level", "UNKNOWN")
    is_real_qa  = pearson_raw is not None
    r_val = float(pearson_raw) if is_real_qa else {"GOOD": 0.82, "MEDIUM": 0.64, "LOW": 0.38}.get(
        str(fit_level).upper(), 0.50
    )
    cb_status = "PASS" if r_val >= 0.8 else ("MARGINAL" if r_val >= 0.6 else "FAIL")
    cb_color  = "green" if r_val >= 0.8 else ("yellow" if r_val >= 0.6 else "red")
    if not is_real_qa:
        cb_status += " (estimado)"

    return {
        "project_id":           clean_pid,
        "run_id":               clean_rid,
        "config_hash":          cfg_hash,
        "config_hash_display":  f"SHA256[:{cfg_hash}]",
        "terraquantum_version": APP_VERSION,
        "audit_keys":           _AUDIT_KEYS,
        "inversion_params_snapshot": {k: inputs.get(k) for k in _AUDIT_KEYS if k in inputs},
        "l_curve": {
            "points":           l_curve_real,
            "is_real":          is_real_lcurve,
            "optimal_lambda":   inputs.get("lambda_mag"),
            "selection_method": inputs.get("lambda_selected_via", "manual"),
            "note": (
                "Puntos reales del barrido λ calculados durante la inversión."
                if is_real_lcurve else
                "Curva ilustrativa derivada de métricas de fit del run. "
                "Para L-curve real ejecutar con lambda_selection_method='l_curve'."
            ),
        },
        "checkerboard_qa": {
            "pearson_r":       round(r_val, 4),
            "status":          cb_status,
            "color":           cb_color,
            "threshold_pass":  0.8,
            "threshold_fail":  0.6,
            "is_real":         is_real_qa,
            "note": (
                "Resultado real del checkerboard test."
                if is_real_qa else
                "Estimado desde fit_level (sin test explícito)."
            ),
        },
        "fit_diagnostics": {
            "fit_level":            fit_level,
            "normalized_rmse":      fit_diag.get("normalized_rmse"),
            "residual_rmse":        fit_diag.get("residual_rmse"),
            "residual_l2":          fit_diag.get("residual_l2"),
            "misfit_error_percent": (
                fit_diag.get("misfit_error_percent") or report.get("misfit_error_percent")
            ),
        },
    }
