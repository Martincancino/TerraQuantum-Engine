"""
R3-BE-4 — Enriquece block_model.parquet con elevación absoluta y coordenadas geográficas.

Columnas R3 agregadas:
  lat, lon, surface_elevation_masl, depth_below_surface_m,
  voxel_elevation_masl, georef_confidence, dem_source,
  dem_sample_method, spatial_reference_warning.

Reglas:
  - depth_below_surface_m = y_m (siempre).
  - voxel_elevation_masl = surface_elevation_masl - depth_below_surface_m.
  - georef MISSING → surface/voxel/lat/lon quedan null.
  - georef LOW    → lat/lon quedan null; DEM sampling permitido.
  - terrain_metadata o dem_matrix ausentes → status "skipped".
  - Escritura atómica (.tmp → replace) cuando overwrite=True.
"""
import json
from pathlib import Path
from typing import Optional

import polars as pl

from core.block_model_store import (
    get_run_block_model_reference,
    get_run_gravity_import_metadata_path,
    load_project_meta,
    load_terrain_dem_matrix,
    load_terrain_metadata,
)
from core.geo_utils import sample_dem_elevation
from services.coordinate_transform_real import transform_utm_to_wgs84


R3_COLUMNS = [
    "lat",
    "lon",
    "surface_elevation_masl",
    "depth_below_surface_m",
    "voxel_elevation_masl",
    "georef_confidence",
    "dem_source",
    "dem_sample_method",
    "spatial_reference_warning",
]


def _read_json_safe(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_utm_origin(
    gim: Optional[dict],
) -> tuple[Optional[float], Optional[float], Optional[int], Optional[str]]:
    """
    Extrae (x_min_raw, z_min_raw, epsg_code, utm_zone) de gravity_import_metadata.
    Prioridad: top-level coordinate_transform > import_metadata.coordinate_transform.
    """
    if not gim:
        return None, None, None, None

    ct = gim.get("coordinate_transform")
    if not ct:
        ct = (gim.get("import_metadata") or {}).get("coordinate_transform")
    if not ct:
        return None, None, None, None

    x_min_raw = ct.get("x_min_raw")
    z_min_raw = ct.get("z_min_raw")
    epsg_code = ct.get("epsg_code")
    utm_zone = ct.get("utm_zone")

    x_min_raw = float(x_min_raw) if isinstance(x_min_raw, (int, float)) else None
    z_min_raw = float(z_min_raw) if isinstance(z_min_raw, (int, float)) else None
    epsg_code = int(epsg_code) if isinstance(epsg_code, int) else None
    utm_zone = str(utm_zone) if isinstance(utm_zone, str) else None

    return x_min_raw, z_min_raw, epsg_code, utm_zone


def _first_col(df: pl.DataFrame, candidates: list[str]) -> Optional[str]:
    """Retorna el primer nombre de columna de candidates que existe en df."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def enrich_block_model_with_elevation(
    project_id: str,
    run_id: str,
    *,
    sample_method: str = "bilinear",
    overwrite: bool = True,
) -> dict:
    """
    Enriquece block_model.parquet con columnas R3 de elevación absoluta y coordenadas.

    Returns dict:
        status: "ok" | "skipped" | "error"
        project_id, run_id
        rows_processed: int
        has_elevation_data: bool
        columns_added: list[str]
        warnings: list[str]
        output_path: str  (solo si status="ok")
    """
    warnings: list[str] = []

    # ── 1. Resolver path de block_model.parquet ───────────────────────────────
    bm_ref = get_run_block_model_reference(project_id, run_id)
    bm_path: Path = bm_ref.path

    if not bm_path.exists():
        raise FileNotFoundError(
            f"block_model.parquet no encontrado: {bm_path}"
        )

    # ── 2. Cargar terrain data — cualquiera ausente → skipped ─────────────────
    terrain_meta = load_terrain_metadata(project_id)
    dem_matrix = load_terrain_dem_matrix(project_id)

    if terrain_meta is None or dem_matrix is None:
        warnings.append("DEM no disponible; no se puede enriquecer block_model.")
        return {
            "status": "skipped",
            "project_id": project_id,
            "run_id": run_id,
            "rows_processed": 0,
            "has_elevation_data": False,
            "columns_added": [],
            "warnings": warnings,
        }

    # ── 3. Leer parquet ────────────────────────────────────────────────────────
    df = pl.read_parquet(str(bm_path))
    rows_original = df.height

    # ── 4. Detectar nombres de columnas (legacy x/y/z o x_m/y_m/z_m) ─────────
    x_col = _first_col(df, ["x_m", "x"])
    y_col = _first_col(df, ["y_m", "y"])
    z_col = _first_col(df, ["z_m", "z"])

    if x_col is None or y_col is None or z_col is None:
        return {
            "status": "error",
            "project_id": project_id,
            "run_id": run_id,
            "rows_processed": 0,
            "has_elevation_data": False,
            "columns_added": [],
            "warnings": ["block_model.parquet no tiene columnas x/y/z ni x_m/y_m/z_m."],
        }

    # ── 5. Extraer campos de georef y DEM ─────────────────────────────────────
    georef_confidence = str(terrain_meta.get("georef_confidence") or "MISSING")
    dem_source = str(terrain_meta.get("source") or "")
    model_extent_x_m = terrain_meta.get("extent_x_m")
    model_extent_z_m = terrain_meta.get("extent_z_m")

    # ── 6. Cargar UTM origin de gravity_import_metadata ───────────────────────
    gim_path = get_run_gravity_import_metadata_path(project_id, run_id)
    gim = _read_json_safe(gim_path)
    x_min_raw, z_min_raw, epsg_code, utm_zone = _extract_utm_origin(gim)

    # Fallback a project_meta para EPSG/UTM
    project_meta = load_project_meta(project_id) or {}
    if epsg_code is None:
        pm_epsg = project_meta.get("epsg_code")
        if isinstance(pm_epsg, int):
            epsg_code = pm_epsg
    if utm_zone is None:
        pm_zone = project_meta.get("utm_zone")
        if isinstance(pm_zone, str):
            utm_zone = pm_zone

    # ── 7. Determinar capacidades ─────────────────────────────────────────────
    can_sample_dem = (
        georef_confidence != "MISSING"
        and isinstance(model_extent_x_m, (int, float))
        and isinstance(model_extent_z_m, (int, float))
        and float(model_extent_x_m) > 0
        and float(model_extent_z_m) > 0
    )
    can_latlon = (
        georef_confidence not in ("MISSING", "LOW")
        and (epsg_code is not None or utm_zone is not None)
        and x_min_raw is not None
        and z_min_raw is not None
    )

    if georef_confidence == "MISSING":
        warnings.append("Georef MISSING: surface_elevation y voxel_elevation dejados en null.")
        warnings.append("Georef MISSING: lat/lon dejados en null.")
    elif georef_confidence == "LOW":
        warnings.append("Lat/lon por voxel no calculado para georreferenciación LOW.")
    elif not can_latlon:
        if x_min_raw is None or z_min_raw is None:
            warnings.append(
                "No se encontró raw UTM origin para calcular lat/lon por voxel."
            )
        elif epsg_code is None and utm_zone is None:
            warnings.append("Sin EPSG ni utm_zone: lat/lon no calculados.")

    # ── 8. Eliminar columnas R3 existentes para evitar duplicados ─────────────
    cols_to_drop = [c for c in R3_COLUMNS if c in df.columns]
    if cols_to_drop:
        df = df.drop(cols_to_drop)

    # ── 9. Calcular columnas nuevas ────────────────────────────────────────────
    x_vals = df[x_col].to_list()
    y_vals = df[y_col].to_list()
    z_vals = df[z_col].to_list()

    lats: list[Optional[float]] = []
    lons: list[Optional[float]] = []
    surface_elevs: list[Optional[float]] = []
    depths: list[float] = []
    voxel_elevs: list[Optional[float]] = []
    row_warnings: list[str] = []

    ext_x = float(model_extent_x_m) if can_sample_dem else 0.0
    ext_z = float(model_extent_z_m) if can_sample_dem else 0.0

    for x_val, y_val, z_val in zip(x_vals, y_vals, z_vals):
        x_f = float(x_val) if x_val is not None else 0.0
        y_f = float(y_val) if y_val is not None else 0.0
        z_f = float(z_val) if z_val is not None else 0.0

        # depth_below_surface_m = y_m (siempre)
        depths.append(y_f)

        # surface_elevation_masl via DEM sampling
        surf_elev: Optional[float] = None
        sample_warn = ""
        if can_sample_dem:
            surf_elev, sample_warn = sample_dem_elevation(
                dem_matrix,
                terrain_meta,
                x_f,
                z_f,
                ext_x,
                ext_z,
                method=sample_method,
            )
        surface_elevs.append(surf_elev)

        # voxel_elevation_masl = surface_elevation_masl - depth_below_surface_m
        voxel_elevs.append(surf_elev - y_f if surf_elev is not None else None)

        # lat / lon por voxel
        if can_latlon:
            try:
                voxel_easting = float(x_min_raw) + x_f
                voxel_northing = float(z_min_raw) + z_f
                lat_v, lon_v = transform_utm_to_wgs84(
                    voxel_easting,
                    voxel_northing,
                    utm_zone=utm_zone,
                    epsg_code=epsg_code,
                )
                lats.append(lat_v)
                lons.append(lon_v)
            except Exception as exc:
                lats.append(None)
                lons.append(None)
                extra = f"Error UTM→WGS84: {exc}"
                sample_warn = f"{sample_warn}; {extra}" if sample_warn else extra
        else:
            lats.append(None)
            lons.append(None)

        row_warnings.append(sample_warn)

    # ── 10. Agregar columnas al DataFrame ─────────────────────────────────────
    df = df.with_columns([
        pl.Series("lat", lats, dtype=pl.Float64),
        pl.Series("lon", lons, dtype=pl.Float64),
        pl.Series("surface_elevation_masl", surface_elevs, dtype=pl.Float64),
        pl.Series("depth_below_surface_m", depths, dtype=pl.Float64),
        pl.Series("voxel_elevation_masl", voxel_elevs, dtype=pl.Float64),
        pl.lit(georef_confidence).alias("georef_confidence"),
        pl.lit(dem_source).alias("dem_source"),
        pl.lit(sample_method).alias("dem_sample_method"),
        pl.Series("spatial_reference_warning", row_warnings),
    ])

    # ── 11. Escritura segura ───────────────────────────────────────────────────
    if overwrite:
        tmp_path = bm_path.parent / (bm_path.name + ".tmp")
        try:
            df.write_parquet(str(tmp_path))
            tmp_path.replace(bm_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        out_path = bm_path
    else:
        out_path = bm_path.parent / "block_model_enriched.parquet"
        df.write_parquet(str(out_path))

    columns_added = [c for c in R3_COLUMNS if c in df.columns]

    return {
        "status": "ok",
        "project_id": project_id,
        "run_id": run_id,
        "rows_processed": rows_original,
        "has_elevation_data": True,
        "columns_added": columns_added,
        "warnings": warnings,
        "output_path": str(out_path),
    }
