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

# FASE 22 (ACAD-13): aquí vivía `VTK_BASE_DENSITY = np.float64(2.6)`, la «densidad base
# de roca encajante» escrita a mano. La constante se BORRA en vez de corregirse porque
# el defecto no era su valor sino su existencia: la roca caja es un parámetro de la
# corrida (`base_density`, contrato 1,0–6,0 t/m³), y mientras hubiera un módulo con un
# número fijo cualquier llamador futuro podía volver a alcanzarlo sin enterarse. Ahora
# `base_density` es argumento OBLIGATORIO de `build_vtk_core_arrays` y de
# `export_core_to_vtr`: olvidarlo es un TypeError, no un sesgo silencioso.


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
    base_density: float,
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
    base_density : float    — Roca caja de la corrida (t/m³). FASE 22 (ACAD-13):
                    OBLIGATORIO y sin default a propósito. Es el mismo valor contra
                    el que la ruta canónica calcula `density_contrast_t_m3`
                    (`inversion_postprocess_service.py:105`), que es la columna que
                    consume el frontend; si aquí se usa otro, el .vtr que el cliente
                    descarga en el ZIP contradice a la pantalla que está mirando.
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
    # Celdas de aire → sentinel; celdas activas → densidad_absoluta − base_density
    # de la corrida (FASE 22, ACAD-13: antes era el literal 2.6).
    density_contrast = np.where(
        is_active,
        density_arr - np.float64(base_density),
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
    base_density: float,
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
    base_density : float — Roca caja de la corrida (t/m³). Obligatorio: ver
                   `build_vtk_core_arrays`.
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
            base_density=base_density,
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

# Fase 6 (H-13): aquí vivían `export_core_to_gslib` y `export_block_model_to_gslib`,
# un par muerto: al segundo sólo lo llamaba el primero, y al primero no lo llamaba
# nadie. El GSLIB que el producto SÍ entrega lo genera `_gslib_text()` dentro del
# bundle ZIP industrial (más abajo, vía export_api), así que borrar este par no quita
# ninguna funcionalidad prometida en README_BACKEND ni en la UI.

# ═════════════════════════════════════════════════════════════════════════════
# FASE 11 — UBC-mesh Export (estándar UBC-GIF)
# ═════════════════════════════════════════════════════════════════════════════

# ── UN SOLO escritor UBC-GIF para las DOS rutas (FASE 19, ACAD-1c) ───────────
# Había dos, y discrepaban. `gravity_import_service` (ruta de disco) permutaba a
# ejes UBC; el bundle ZIP —lo que el cliente DESCARGA— escribía `{nx} {ny} {nz}`
# crudo. Sobre una corrida 20×10×20 el fichero del disco decía «20 20 10» y el
# del ZIP «20 10 20», y 3998 de 4000 celdas caían en distinto sitio. Ahora las
# dos rutas pasan por estas tres funciones: no hay dos sitios que sincronizar.
#
#   TQ  : (nx=Este, ny=PROFUNDIDAD +abajo, nz=Norte), aplanado Fortran
#         `ix + nx·iy + nx·ny·iz` — que es como el parquet persiste el modelo
#         (medido: 1951/1951 corridas con `inputs.json` cumplen ese orden).
#   UBC : (nE, nN, nZ) con Z + hacia ARRIBA. Ver `docs/11_CONVENCION_DE_EJES.md`.

UBC_NODATA = -9999.0


def tq_flat_to_ubc_flat(values_tq, nx: int, ny: int, nz: int) -> np.ndarray:
    """Reordena de ejes TerraQuantum a ejes UBC-GIF (índice 0 del eje Z = FONDO)."""
    arr = np.asarray(values_tq, dtype=np.float64).reshape((nx, ny, nz), order="F")
    arr_ubc = np.transpose(arr, (0, 2, 1))[:, :, ::-1]          # (E, N, Z-arriba)
    return np.ascontiguousarray(arr_ubc).ravel(order="F")


def ubc_mesh_text(n_east: int, n_north: int, n_z: int,
                  d_east: float, d_north: float, d_z: float,
                  origin_east: float, origin_north: float, origin_z: float) -> str:
    """Texto del `.msh`. `origin_z` es la cota del FONDO; UBC publica la del techo.

    SIN líneas de comentario: `discretize.TensorMesh.read_UBC` y `np.loadtxt` no
    toleran headers `!`; los metadatos van en `run_manifest.json`.
    """
    ubc_origin_z = origin_z + n_z * d_z          # esquina superior-noroeste
    return (
        f"{n_east} {n_north} {n_z}\n"
        f"{origin_east:.4f} {origin_north:.4f} {ubc_origin_z:.4f}\n"
        + " ".join([f"{d_east:.4f}"] * n_east) + "\n"
        + " ".join([f"{d_north:.4f}"] * n_north) + "\n"
        + " ".join([f"{d_z:.4f}"] * n_z) + "\n"
    )


def ubc_model_text(values_ubc, active_ubc, n_east: int, n_north: int, n_z: int) -> str:
    """Texto del `.den`/`.mod`: z varía más rápido y DESDE ARRIBA, luego N, luego E."""
    vals = np.asarray(values_ubc, dtype=np.float64).reshape(
        (n_east, n_north, n_z), order="F")[:, :, ::-1]
    act = np.asarray(active_ubc, dtype=bool).reshape(
        (n_east, n_north, n_z), order="F")[:, :, ::-1]
    out: list[str] = []
    for ie in range(n_east):
        for inn in range(n_north):
            for iz in range(n_z):
                v = vals[ie, inn, iz]
                out.append(f"{v:.6f}" if (act[ie, inn, iz] and np.isfinite(v))
                           else f"{UBC_NODATA:.1f}")
    return "\n".join(out) + "\n"


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
         Celdas inactivas (aire) → `UBC_NODATA`.

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
    # .den: convención GRAV3D para modelos de densidad (compatible SimPEG/discretize).
    model_path = out_dir / f"{run_prefix}.den"

    # ── 1. Malla (.msh) y 2. modelo (.den), por el escritor COMPARTIDO ───────
    # Aquí `nx, ny, nz` YA son ejes UBC (nE, nN, nZ): el llamador permuta antes.
    mesh_path.write_text(
        ubc_mesh_text(nx, ny, nz, dx, dy, dz, origin_x, origin_y, origin_z),
        encoding="ascii",
    )
    model_path.write_text(
        ubc_model_text(density_arr, active_mask, nx, ny, nz),
        encoding="ascii",
    )

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


# Fase 6 (H-13): aquí vivían `export_core_to_gslib` y `export_block_model_to_gslib`,
# un par muerto: al segundo sólo lo llamaba el primero, y al primero no lo llamaba
# nadie. El GSLIB que el producto SÍ entrega lo genera `_gslib_text()` dentro del
# bundle ZIP industrial (más abajo, vía export_api), así que borrar este par no quita
# ninguna funcionalidad prometida en README_BACKEND ni en la UI.

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
# F5 — Block model CSV (estándar minero, desde el parquet REAL persistido)
# ═════════════════════════════════════════════════════════════════════════════

def export_block_model_to_csv(project_id: str, run_id: str) -> Optional[str]:
    """
    F5 — Exporta el block model a CSV estándar minero: X_m, Y_m, Z_m, Density_gcm3
    [, Susceptibility_SI] + columnas de diagnóstico disponibles (Sensitivity_Proxy,
    DOI_Index, Posterior_Std, Probability, Is_Active).

    A diferencia de GSLIB/UBC/VTR (que reconstruyen una grilla densa nx·ny·nz desde
    `inputs`), este export lee DIRECTAMENTE `block_model.parquet` — coherente con el
    gotcha F4 (coordenadas reales en metros, celdas dispersas, sin ix/iy/iz densos).
    Non-fatal: retorna None si el parquet no existe, falta una columna mínima, o falla.
    """
    try:
        import pandas as pd
        from services.block_model_store import RUN_BLOCK_MODEL_FILENAME, get_run_dir

        run_dir = get_run_dir(project_id, run_id)
        bm_path = run_dir / RUN_BLOCK_MODEL_FILENAME
        if not bm_path.exists():
            logger.warning("[F5] block_model.parquet no encontrado para %s/%s", project_id, run_id)
            return None

        df = pd.read_parquet(bm_path)

        # Preferir columnas v4.0 (x_m/y_m/z_m/density_t_m3); fallback a legacy (x/y/z/density).
        coord_cols = (["x_m", "y_m", "z_m"] if {"x_m", "y_m", "z_m"}.issubset(df.columns)
                      else ["x", "y", "z"])
        density_col = "density_t_m3" if "density_t_m3" in df.columns else "density"
        if not set(coord_cols).issubset(df.columns) or density_col not in df.columns:
            logger.warning(
                "[F5] block_model.parquet sin columnas mínimas x/y/z/density (%s/%s)",
                project_id, run_id,
            )
            return None

        column_map = {
            coord_cols[0]: "X_m", coord_cols[1]: "Y_m", coord_cols[2]: "Z_m",
            density_col: "Density_gcm3",
            "susceptibility_si": "Susceptibility_SI",
            "sensitivity_proxy": "Sensitivity_Proxy",
            "doi_index": "DOI_Index",
            "posterior_std": "Posterior_Std_gcm3",
            "probability": "Probability",
            "is_active": "Is_Active",
        }
        present = [c for c in column_map if c in df.columns]
        out = df[present].rename(columns=column_map)

        out_path = run_dir / "block_model.csv"
        out.to_csv(out_path, index=False, float_format="%.6f")

        size_kb = out_path.stat().st_size / 1024
        logger.info(
            "[F5] Block model CSV exportado | path=%s | filas=%d | size=%.1f KB",
            str(out_path), len(out), size_kb,
        )
        return str(out_path)
    except Exception as exc:
        logger.warning("[F5] Error en exportación CSV de block model (non-fatal): %s", exc)
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

from services.block_model_store import (
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


def base_density_of_run(inputs: "dict[str, Any]",
                        report: "dict[str, Any] | None") -> "tuple[float, str]":
    """FASE 22 (ACAD-13) — La roca caja de la corrida, leída del disco, con su fuente.

    El bundle ZIP escribe DOS contrastes de densidad (`model.vtr` y el `Density_Contrast`
    del `model.dat` ASEG-GDF2) y hasta esta fase los dos restaban el literal 2.6. Para
    dejar de mentir hay que saber contra qué se invirtió de verdad, y eso no está donde
    uno lo buscaría: `build_run_inputs_snapshot` es una lista blanca de claves escrita a
    mano y `base_density` no estaba en ella (medido: 0 de 2.089 `inputs.json` en disco la
    traían). Sí está en el reporte, dentro del bloque que publicó la Fase 20.

    Devuelve `(valor, fuente)`. La fuente viaja al manifiesto: cuando hay que asumir el
    default de contrato, el cliente tiene que poder verlo, no deducirlo.
    """
    ec = (report or {}).get("effective_contrast") or {}
    val = ec.get("base_density")
    if isinstance(val, (int, float)) and not isinstance(val, bool) and _math.isfinite(float(val)):
        return float(val), "report.effective_contrast"

    val = (inputs or {}).get("base_density")
    if isinstance(val, (int, float)) and not isinstance(val, bool) and _math.isfinite(float(val)):
        return float(val), "inputs.json"

    # Corridas anteriores a la Fase 20/22: ninguna de las dos fuentes existe. Se usa el
    # default del contrato (`schemas/geophysics_schema.py:782`) y se DECLARA como asumido.
    return 2.6, "contract_default_assumed"


def _densities_from_parquet(run_dir: Path, total: int) -> list[float]:
    """Lee densidades ABSOLUTAS del parquet persistido. Sin cálculos nuevos."""
    try:
        import pandas as pd
        bm_path = run_dir / RUN_BLOCK_MODEL_FILENAME
        if not bm_path.exists():
            return [float("nan")] * total
        df = pd.read_parquet(bm_path)
        # FASE 22: aquí el bucle recorría ("density", "density_absolute",
        # "density_contrast"). Las dos últimas se retiran por razones distintas:
        #   · `density_absolute` no la escribe nadie en todo el backend (0 de 2.684
        #     parquets de corrida en disco la tienen): era una rama muerta;
        #   · `density_contrast` sí es un nombre vivo —lo escribe el TargetingEngine en
        #     OTRO fichero— y ahí estaba el peligro: de haberse alcanzado habría
        #     entregado un CONTRASTE por el hueco de la densidad ABSOLUTA
        #     (`model.den`, `model.gslib` y la columna `Density_gcm3` del ASEG-GDF2),
        #     un error de datum del orden de la propia roca caja presentado como
        #     densidad. Es el mismo defecto que esta fase cierra, con el signo cambiado.
        # `density` está en 2.684 de 2.684: la rama viva era siempre la primera.
        if "density" in df.columns:
            vals = list(df["density"].astype(float))
            pad = total - len(vals)
            if pad > 0:
                vals.extend([float("nan")] * pad)
            return vals[:total]
    except Exception:
        pass
    # FASE 22: antes se devolvía `[2.6] * total` — un modelo uniforme de roca INVENTADO
    # que salía por `model.den`/`model.gslib`/`model.dat` con la misma cara que un
    # resultado de inversión. NaN es lo que el escritor UBC ya traduce a NODATA
    # (`ubc_model_text` filtra por `np.isfinite`): un fichero que dice «no hay dato» en
    # vez de uno que dice «hay 2,6 t/m³ en todas partes».
    return [float("nan")] * total


def run_local_origin(project_id: str, run_id: str) -> "tuple[float, float]":
    """Origen ABSOLUTO del frame local de la corrida, o (0,0) si no lo hay.

    (0,0) no es relleno: es la verdad del frame local con origen en la esquina SW
    del survey, que es el caso mayoritario medido en disco. Lo usan las DOS rutas
    de exportación UBC, para que no puedan volver a divergir por el origen.
    """
    try:
        from services.omf_export_service import load_georef
        geo = load_georef(project_id, run_id)
        if geo.is_absolute:
            return float(geo.easting0), float(geo.northing0)
    except Exception:
        pass
    return 0.0, 0.0


def _densities_to_array(densities: "list[float]") -> np.ndarray:
    return np.array([np.nan if d is None else float(d) for d in densities], dtype=np.float64)


def _ubc_msh_text(nx: int, ny: int, nz: int, bs: float,
                  origin_east: float = 0.0, origin_north: float = 0.0) -> str:
    """`nx, ny, nz` en ejes TQ (Este, PROFUNDIDAD, Norte) — los de `inputs.json`.

    FASE 19: escribía `{nx} {ny} {nz}` crudo. UBC-GIF es `(nE, nN, nZ)`, y el eje
    vertical de TQ es `ny`. Con malla cúbica el error es invisible.
    """
    return ubc_mesh_text(
        n_east=nx, n_north=nz, n_z=ny,
        d_east=bs, d_north=bs, d_z=bs,
        origin_east=origin_east, origin_north=origin_north,
        origin_z=-float(ny * bs),          # techo del modelo = superficie (0 m)
    )


def _ubc_mod_text(densities: "list[float]", nx: int, ny: int, nz: int) -> str:
    """`densities` en orden TQ Fortran (`ix + nx·iy + nx·ny·iz`), como el parquet."""
    ubc = tq_flat_to_ubc_flat(_densities_to_array(densities), nx, ny, nz)
    return ubc_model_text(ubc, np.isfinite(ubc), nx, nz, ny)


def _gslib_text(densities: list[float], nx: int, ny: int, nz: int, bs: float) -> str:
    """GSLIB / SGeMS. `X_m, Y_m, Z_m` = Este, Norte, cota (negativa hacia abajo).

    FASE 19 (ACAD-1c): escribía `Y_m = (iy+½)·bs` —e `iy` es la PROFUNDIDAD— y
    `Z_m = −(iz+½)·bs` —e `iz` es el NORTE—. Un consumidor de GSLIB lee
    X=Este / Y=Norte / Z=cota, así que el modelo entregado salía tumbado. El
    bucle NO cambia: recorre el aplanado Fortran del parquet; lo que estaba mal
    eran las coordenadas que se le adjuntan a cada celda.
    """
    hdr = [
        f"TerraQuantum Block Model {nx}x{ny}x{nz} bs={bs}m NO-JORC/NI-43-101",
        "5", "X_m", "Y_m", "Z_m", "Density_gcm3", "Is_Active",
    ]
    rows: list[str] = []
    idx = 0
    for iz in range(nz):            # iz = NORTE
        for iy in range(ny):        # iy = PROFUNDIDAD (+ abajo)
            for ix in range(nx):    # ix = ESTE
                d = densities[idx] if idx < len(densities) else None
                bad = d is None or (isinstance(d, float) and _math.isnan(d))
                rows.append(
                    f"{(ix+0.5)*bs:.2f} {(iz+0.5)*bs:.2f} {-(iy+0.5)*bs:.2f} "
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
    # FASE 21: QA de resolución y techo del veredicto, leídos de las claves que el motor
    # SÍ escribe (`checkerboard_qa`, `overall_verdict.ceiling`).
    _cb_qa_report = (report or {}).get("checkerboard_qa") or {}
    _verdict_ceiling_report = ((report or {}).get("overall_verdict") or {}).get("ceiling") or {}

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

    _bd_value, _bd_source = base_density_of_run(inputs, report)

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
        # FASE 22 (ACAD-13): el bundle entrega DOS columnas de contraste —
        # `Density_Contrast_gcm3` en `model.vtr` y `Density_Contrast` en `model.dat`— y
        # un contraste sin su referencia no es un número, es media resta. El manifiesto
        # declara ahora contra qué se calcularon, y de dónde salió ese valor: si dice
        # `contract_default_assumed`, la corrida es anterior a la Fase 20 y el dato no
        # estaba en disco. Decirlo es la diferencia entre un default y una suposición
        # disfrazada de medición.
        "density_reference": {
            "base_density_t_m3": _bd_value,
            "source": _bd_source,
            "unit_note": "1 t/m³ = 1 g/cm³; los ficheros rotulados g/cm3 llevan el mismo número.",
            "applies_to": [
                "model.vtr:Density_Contrast_gcm3",
                "model.dat:Density_Contrast",
            ],
            "absolute_density_files": ["model.den", "model.gslib", "model.csv",
                                       "model.dat:Density_gcm3"],
        },
        "fit_diagnostics": {
            "fit_level": fit_diag.get("fit_level"),
            "normalized_rmse": fit_diag.get("normalized_rmse"),
            "residual_rmse": fit_diag.get("residual_rmse"),
            "residual_mae": fit_diag.get("residual_mae"),
            "misfit_error_percent": fit_diag.get("misfit_error_percent"),
        },
        # FASE 21: este bloque leía `report["checkerboard_pearson_r"]`, una clave que NADIE
        # escribe nunca — el manifiesto del ZIP industrial declaraba un QA de resolución
        # con `pearson_r: null` y sin `status`, así que el cliente recibía el nombre del
        # diagnóstico y ninguno de sus dos números. La clave real es `checkerboard_qa`.
        # Va acompañado del techo del veredicto: decir MEDIUM sin decir que HIGH era
        # inalcanzable es la lectura errónea que la Fase 21 vino a cerrar.
        "checkerboard_qa": {
            "pearson_r": _cb_qa_report.get("pearson_r"),
            "status": _cb_qa_report.get("status") or "NOT_RUN",
            "sign_recovery_pct": _cb_qa_report.get("sign_recovery_pct"),
            "verdict_ceiling": _verdict_ceiling_report.get("max_attainable_level"),
            "verdict_ceiling_reason": _verdict_ceiling_report.get("reason"),
            "overall_level": ts.get("overall_level"),
            "fit_level": fit_diag.get("fit_level"),
        } if report else None,
        "run_manifest_provenance": _run_manifest_provenance,
        "bundle_contents": [
            {"file": "model.vtr",      "format": "VTK RectilinearGrid XML",    "software": ["ParaView", "Leapfrog Geo"]},
            {"file": "model.den",      "format": "UBC-GIF GRAV3D Density Model (.den)",  "software": ["UBC-GIF Grav3D", "SimPEG"]},
            {"file": "model.msh",      "format": "UBC-GIF Mesh Definition",    "software": ["UBC-GIF Grav3D", "SimPEG"]},
            {"file": "model.gslib",    "format": "Stanford GSLIB / SGeMS",     "software": ["SGeMS", "ISATIS"]},
            {"file": "model.dfn",      "format": "ASEG-GDF2 Definition File",  "software": ["Oasis Montaj", "Geosoft"]},
            {"file": "model.dat",      "format": "ASEG-GDF2 Data File",        "software": ["Oasis Montaj", "Geosoft"]},
            {"file": "model.csv",      "format": "CSV estándar minero (X_m,Y_m,Z_m,Density_gcm3,…)", "software": ["Excel", "Leapfrog", "Datamine"]},
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

    _origin_e, _origin_n = run_local_origin(clean_pid, clean_rid)
    msh   = _ubc_msh_text(nx, ny, nz, bs, origin_east=_origin_e, origin_north=_origin_n)
    dens  = _densities_from_parquet(run_dir, nx * ny * nz)
    mod   = _ubc_mod_text(dens, nx, ny, nz)
    gslib = _gslib_text(dens, nx, ny, nz, bs)
    mfst  = _json.dumps(manifest, indent=2, ensure_ascii=False)

    utm_zone = inputs.get("utm_zone") or inputs.get("utm_zone_detected") or "19S"
    # FASE 22 (ACAD-13): la roca caja de la corrida, no el literal 2.6. Se lee UNA vez
    # y la usan los dos ficheros ASEG-GDF2, para que la definición (.dfn) y el dato
    # (.dat) no puedan volver a divergir — la misma cura de un-solo-escritor que la
    # Fase 19 aplicó a los ejes UBC.
    _base_density, _base_density_src = base_density_of_run(inputs, report)
    aseg_dfn = _aseg_gdf2_dfn_text(nx, ny, nz, bs, str(utm_zone),
                                   base_density=_base_density)
    aseg_dat = _aseg_gdf2_dat_text(dens, nx, ny, nz, bs,
                                   base_density=_base_density)

    # F5: CSV desde el parquet REAL (coordenadas verdaderas, no re-derivadas de nx/ny/nz).
    try:
        _csv_path = export_block_model_to_csv(clean_pid, clean_rid)
        _csv_bytes = Path(_csv_path).read_bytes() if _csv_path else None
    except Exception:
        _csv_bytes = None

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
        zf.writestr("model.den", mod)
        zf.writestr("model.gslib", gslib)
        zf.writestr("model.dfn", aseg_dfn)
        zf.writestr("model.dat", aseg_dat)
        if _csv_bytes:
            zf.writestr("model.csv", _csv_bytes)
        else:
            zf.writestr("model.csv.missing.txt", f"CSV no disponible para {clean_rid}.\n")
        zf.writestr("manifest.json", mfst)

    safe = lambda s: "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in s)[:32]
    filename = f"terraquantum_bundle_{safe(clean_pid)}_{safe(clean_rid)}.zip"
    return buf.getvalue(), filename


# ═════════════════════════════════════════════════════════════════════════════
# FASE 6 — ASEG-GDF2 Export (entrega regulatoria Australia / NZ)
# ═════════════════════════════════════════════════════════════════════════════

def _aseg_gdf2_dfn_text(
    nx: int,
    ny: int,
    nz: int,
    bs: float,
    utm_zone: str,
    base_density: float,
) -> str:
    """
    FASE 6 — Genera el archivo .dfn de definición ASEG-GDF2.

    ASEG-GDF2 (Australian Society of Exploration Geophysicists — Geophysical
    Data Format version 2) es el estándar de entrega regulatoria en Australia
    y Nueva Zelanda, y ampliamente reconocido en Latinoamérica (Oasis Montaj).

    El .dfn describe los campos del .dat con tipos, anchos y metadatos de CRS.

    Datum: GDA94 (Geocentric Datum of Australia 1994) — requerido por estándar
    ASEG. Para otros sistemas de referencia, el campo DATUM debe actualizarse.
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n_total = nx * ny * nz
    fields = [
        ("X_m",                "D", "15.2", "m",       "Easting (local SW-origin)"),
        ("Y_m",                "D", "15.2", "m",       "Northing (local SW-origin)"),
        ("Z_m",                "D", "12.2", "m",       "Depth positive downward"),
        ("Density_gcm3",       "D", "12.6", "g/cm3",   "Absolute density"),
        # FASE 22 (ACAD-13): el comentario decía «minus 2.6 g/cm3 base» como texto fijo.
        # El .dfn es la DEFINICIÓN del .dat en una entrega regulatoria ASEG-GDF2: si
        # declara una base que no es la usada, el fichero es incorrecto por contrato,
        # no sólo por número.
        ("Density_Contrast",   "D", "12.6", "g/cm3",
         f"Density minus {float(base_density):.6g} g/cm3 host-rock base (run base_density)"),
        ("Sensitivity",        "D", "12.6", "",         "DOI sensitivity proxy [0,1]"),
        ("Is_Active",          "I",  "3",   "",         "1=rock 0=air"),
    ]
    lines = [
        f"! TerraQuantum ASEG-GDF2 Definition | project nx={nx} ny={ny} nz={nz} bs={bs}m | {ts}",
        "! NO-JORC/NI-43-101 EXPLORATION ONLY",
        f"! Host-rock base density (base_density) = {float(base_density):.6g} g/cm3",
        f"DEFN 1 ST=RECD,RT=; END DEFN",
        f"DEFN 2 ST=RECD,RT=; DATUM=GDA94",
        f"DEFN 3 ST=RECD,RT=; PROJECTION=UTM",
        f"DEFN 4 ST=RECD,RT=; COORDSYS_ZONE={utm_zone}",
        f"DEFN 5 ST=RECD,RT=; NROW={n_total}",
    ]
    for i, (name, typ, width, units, comment) in enumerate(fields, start=6):
        unit_str = f",{units}" if units else ""
        lines.append(f"DEFN {i} ST=RECD,RT=; {name},{typ},{width}{unit_str}  ! {comment}")
    lines.append("END DEFN")
    return "\n".join(lines) + "\n"


def _aseg_gdf2_dat_text(
    densities: "list[float]",
    nx: int,
    ny: int,
    nz: int,
    bs: float,
    base_density: float,
) -> str:
    """
    FASE 6 — Genera el archivo .dat de datos ASEG-GDF2.

    Columnas: X_m, Y_m, Z_m, Density_gcm3, Density_Contrast, Sensitivity, Is_Active
    Nodata: -9999.000000 para celdas de aire.

    FASE 22 (ACAD-13) — `Density_Contrast` se calculaba contra `BASE_DENSITY = 2.6`,
    una constante local que nadie relacionaba con el `base_density` de la corrida. Era
    la tercera copia del mismo literal (las otras dos: el `.vtr` y el TargetingEngine),
    y la más grave de las tres: ASEG-GDF2 es formato de ENTREGA REGULATORIA en
    Australia y Nueva Zelanda, y `model.dfn` declara por escrito contra qué base está
    calculada la columna. Ahora la base entra por parámetro y el `.dfn` la declara.
    """
    NODATA = -9999.0
    base_density = float(base_density)
    hdr_lines = [
        "! TerraQuantum ASEG-GDF2 Data",
        "! Columns: X_m Y_m Z_m Density_gcm3 Density_Contrast Sensitivity Is_Active",
        "! See model.dfn for field definitions and CRS metadata",
        f"! Density_Contrast = Density_gcm3 - {base_density:.6g} (run base_density)",
        "! NODATA=-9999.000000",
    ]
    rows: list[str] = list(hdr_lines)
    idx = 0
    # FASE 19 (ACAD-1c): `Y_m` se declara «Northing» en el .dfn y llevaba `iy`,
    # que es la PROFUNDIDAD; `Z_m` se declara «Depth positive downward» y llevaba
    # `iz`, que es el NORTE. Mismo defecto que el GSLIB, mismo bucle, misma cura.
    for iz in range(nz):            # iz = NORTE
        for iy in range(ny):        # iy = PROFUNDIDAD (+ abajo)
            for ix in range(nx):    # ix = ESTE
                x = (ix + 0.5) * bs     # Easting local
                y = (iz + 0.5) * bs     # Northing local
                z = (iy + 0.5) * bs     # profundidad, + hacia abajo
                d = densities[idx] if idx < len(densities) else None
                bad = d is None or (isinstance(d, float) and _math.isnan(d))
                if bad:
                    rows.append(
                        f"{x:.2f} {y:.2f} {z:.2f} "
                        f"{NODATA:.6f} {NODATA:.6f} 0.000000 0"
                    )
                else:
                    contrast = float(d) - base_density
                    rows.append(
                        f"{x:.2f} {y:.2f} {z:.2f} "
                        f"{float(d):.6f} {contrast:.6f} 1.000000 1"
                    )
                idx += 1
    return "\n".join(rows) + "\n"

