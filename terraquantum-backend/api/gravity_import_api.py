import math
import uuid
from dataclasses import dataclass
import os
import shutil
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, Form, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError
from typing import Optional

from core.config import CSV_MAX_BYTES, TMP_DIR
from core.logging import get_logger
from core.utils import sanitize_nan, model_to_dict
from core.rate_limit import limiter
from services.block_model_store import (
    get_project_meta_path,
    get_run_source_gravity_csv_path,
    get_run_gravity_import_metadata_path,
    get_terrain_metadata_path,
    get_terrain_dem_matrix_path,
    save_project_meta,
    update_run_status,
)
from services.satellite_service import get_terrain_data
from services.elevation_enrichment_service import enrich_block_model_with_elevation
from services.geo_utils import compute_footprint_from_center, extract_utm_zone_safe
from schemas.geophysics_schema import GeophysicsInvertInput
from schemas.gravity_import_schema import SpatialReadiness, RegionalScalePreflight
from schemas.response_schema import GravityImportPreviewResponse, GravityImportInvertResponse
from schemas.ingest_contracts_schema import (
    AnalyzeColumnsResponse,
    EnrichPackageResponse,
    LoadPackageResponse,
    ParseRowsResponse,
)
from services.gravity_import_service import (
    import_gravity_csv_v1,
    read_csv_headers,
    read_csv_sample,
)


def _sample_rows_preview(headers, samples, limit: int = 5):
    """Primeras filas YA parseadas como lista de dicts (preview honesto F2)."""
    if not headers or not samples:
        return []
    n = min(limit, max((len(v) for v in samples.values()), default=0))
    return [
        {h: (samples.get(h) or [""] * n)[i] if i < len(samples.get(h) or []) else ""
         for h in headers}
        for i in range(n)
    ]
from services.column_mapping_service import build_column_mapping_plan
from services.regional_scale_preflight_service import build_preflight_from_import_result
from services.spatial_readiness_service import classify_from_csv_analysis
from services.geophysics_service import run_geophysics_inversion
from services.coordinate_transform_real import (
    approx_dist_km,
    compute_utm_footprint_with_pyproj,
    get_epsg_from_utm,
    parse_utm_zone_string,
)

router = APIRouter(prefix="/gravity-import", tags=["Gravity Import"])
# Flujo de datos de campo (correcciones automáticas + inversión + UBC-GIF).
# Registrado por separado en main.py para exponer /v2/gravity-import/*.
router_v2 = APIRouter(prefix="/v2/gravity-import", tags=["Gravity Import v2"])
_log = get_logger(__name__)




# ---------------------------------------------------------------------------
# R3.5-K — UTM zone extraction (consolidada en services.geo_utils)
# ---------------------------------------------------------------------------

def _effective_utm_zone(form_utm_zone: "str | None", import_result) -> "str | None":
    """
    Return effective UTM zone: form param has priority; CSV-detected zone is fallback.
    """
    if form_utm_zone and form_utm_zone.strip():
        return form_utm_zone.strip()
    return extract_utm_zone_safe(import_result)


def _extract_detected_utm_zone(import_result) -> "str | None":
    """Return the UTM zone detected from the CSV (no form override)."""
    return extract_utm_zone_safe(import_result)


def _run_r3_post_inversion_enrichment(
    project_id: str,
    run_id: str,
    georef_confidence: "str | None",
) -> dict:
    """
    Ejecuta terrain + enrichment post-inversión según georef_confidence.
    Nunca lanza excepción: errores se devuelven como warnings en el resultado.

    Retorna dict con claves:
      attempted, terrain_persisted, enrichment_attempted,
      enrichment_status, has_elevation_data, warnings.
    """
    conf = (georef_confidence or "MISSING").upper().strip()

    if conf == "MISSING":
        return {
            "attempted": False,
            "terrain_persisted": False,
            "enrichment_attempted": False,
            "enrichment_status": None,
            "has_elevation_data": False,
            "warnings": ["R3 enrichment omitido: georreferenciación ausente."],
        }

    r3_warnings: list[str] = []
    terrain_persisted = False

    # Step 1 — terrain
    try:
        get_terrain_data(project_id)
        terrain_persisted = True
    except Exception as exc:
        r3_warnings.append(
            f"get_terrain_data falló (R3): {exc}. "
            "Se intenta enrichment solo si archivos terrain ya existen."
        )

    # Step 2 — enrichment, solo si archivos DEM existen en disco
    terrain_meta_path = get_terrain_metadata_path(project_id)
    terrain_dem_path = get_terrain_dem_matrix_path(project_id)

    if not terrain_meta_path.exists() or not terrain_dem_path.exists():
        enrichment_attempted = False
        enrichment_status = "skipped"
        has_elevation_data = False
        r3_warnings.append("DEM files no disponibles; enrichment R3 omitido.")
    else:
        enrichment_attempted = True
        try:
            enrich_result = enrich_block_model_with_elevation(project_id, run_id)
            enrichment_status = enrich_result.get("status", "error")
            has_elevation_data = bool(enrich_result.get("has_elevation_data", False))
            r3_warnings.extend(enrich_result.get("warnings", []))
        except Exception as exc:
            enrichment_status = "error"
            has_elevation_data = False
            r3_warnings.append(f"enrich_block_model_with_elevation falló (R3): {exc}")

    if conf == "LOW":
        r3_warnings.append(
            "Elevación MASL calculada como contexto visual por georreferenciación baja; "
            "lat/lon por voxel no se infiere."
        )

    return {
        "attempted": True,
        "terrain_persisted": terrain_persisted,
        "enrichment_attempted": enrichment_attempted,
        "enrichment_status": enrichment_status,
        "has_elevation_data": has_elevation_data,
        "warnings": r3_warnings,
    }


def _raise_regional_scale_gate(
    preflight: RegionalScalePreflight,
    message: str,
    required_action: str,
) -> None:
    raise HTTPException(
        status_code=422,
        detail={
            "error": "REGIONAL_SCALE_PREFLIGHT",
            "scale_class": preflight.scale_class,
            "message": message,
            "required_action": required_action,
            "regional_scale_preflight": model_to_dict(preflight),
            "recommended_action": preflight.recommended_action,
            "blocked_reasons": preflight.blocked_reasons,
            "warnings": preflight.warnings,
            "allowed_outputs": preflight.allowed_outputs,
        },
    )

def parse_geo_coord(value: str, min_value: float, max_value: float) -> Optional[float]:
    try:
        coord = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(coord) or coord < min_value or coord > max_value:
        return None

    return coord

def build_auto_params_metadata(
    csv_analysis,
    coordinate_transform,
    auto_grid,
    legacy_frontend_params: dict,
) -> dict:
    csv_analysis_dict = model_to_dict(csv_analysis) if csv_analysis else {}
    coordinate_transform_dict = model_to_dict(coordinate_transform) if coordinate_transform else {}
    auto_grid_dict = model_to_dict(auto_grid) if auto_grid else {}

    return {
        "version": "auto_params_v0_1",
        "csv_analysis": {
            "quality_label": csv_analysis_dict.get("quality_label"),
            "observation_count": csv_analysis_dict.get("observation_count"),
            "warnings": csv_analysis_dict.get("warnings", []),
        },
        "coordinate_transform": {
            "input_coordinate_system": coordinate_transform_dict.get("input_coordinate_system"),
            "input_confidence": coordinate_transform_dict.get("input_confidence"),
            "method": coordinate_transform_dict.get("method"),
            "origin_strategy": coordinate_transform_dict.get("origin_strategy"),
            "x_extent_m": coordinate_transform_dict.get("x_extent_m"),
            "z_extent_m": coordinate_transform_dict.get("z_extent_m"),
            "warnings": coordinate_transform_dict.get("warnings", []),
            "precision_notes": coordinate_transform_dict.get("precision_notes", []),
        },
        "auto_grid": {
            "block_size_m": auto_grid_dict.get("block_size_m"),
            "nx": auto_grid_dict.get("nx"),
            "ny": auto_grid_dict.get("ny"),
            "nz": auto_grid_dict.get("nz"),
            "depth_m": auto_grid_dict.get("depth_m"),
            "cutoff_radius_m": auto_grid_dict.get("cutoff_radius_m"),
            "voxel_count": auto_grid_dict.get("voxel_count"),
            "r10_limit": auto_grid_dict.get("r10_limit"),
            "adjusted_for_r10": auto_grid_dict.get("adjusted_for_r10"),
            "warnings": auto_grid_dict.get("warnings", []),
            "rationale": auto_grid_dict.get("rationale", []),
            "octree_params": auto_grid_dict.get("octree_params"),
            "recommended_use_treemesh": auto_grid_dict.get("recommended_use_treemesh", False),
        },
        "legacy_frontend_params": {
            "present": True,
            "used_for_grid": False,
            "fields": legacy_frontend_params,
        },
    }

def _classify_georef_full(
    coordinate_transform,
    lat_value: "float | None",
    lon_value: "float | None",
    utm_zone_form: "str | None" = None,
) -> dict:
    """
    R2 — Retorna dict con todos los campos georef + CRS.

    Claves: confidence, type, utm_zone, warnings,
            utm_hemisphere, epsg_code, input_crs, crs_source, crs_confidence.
    """
    if coordinate_transform is None:
        return {
            "confidence": "MISSING",
            "type": "local_reference",
            "utm_zone": None,
            "warnings": ["Sin datos de transformación de coordenadas."],
            "utm_hemisphere": None,
            "epsg_code": None,
            "input_crs": "unknown",
            "crs_source": "missing",
            "crs_confidence": "MISSING",
        }

    cs = (getattr(coordinate_transform, "input_coordinate_system", None) or "unknown").lower()
    conf = (getattr(coordinate_transform, "input_confidence", None) or "low").lower()
    has_anchor = lat_value is not None and lon_value is not None
    warns: list[str] = []

    if cs == "latlon" and conf != "low":
        extent_x = getattr(coordinate_transform, "x_extent_m", 0) or 0
        extent_z = getattr(coordinate_transform, "z_extent_m", 0) or 0
        crs_latlon = {
            "utm_zone": None,
            "utm_hemisphere": None,
            "epsg_code": 4326,
            "input_crs": "EPSG:4326",
            "crs_source": "inferred",
            "crs_confidence": "HIGH",
        }
        if max(extent_x, extent_z) > 100_000:
            warns.append("Extent >100km: precisión equirectangular limitada. Usar pyproj en R2.")
            if has_anchor:
                return {"confidence": "MEDIUM", "type": "latlon", "warnings": warns, **crs_latlon}
            warns.append("Lat/lon detectado, pero sin punto central de anclaje explícito.")
            return {"confidence": "MEDIUM", "type": "latlon", "warnings": warns, **crs_latlon}
        if has_anchor:
            return {"confidence": "HIGH", "type": "latlon", "warnings": [], **crs_latlon}
        return {
            "confidence": "MEDIUM",
            "type": "latlon",
            "warnings": ["Lat/lon detectado, pero sin punto central de anclaje explícito."],
            **crs_latlon,
        }

    if cs == "utm" and conf != "low":
        utm_zone_val: "str | None" = None
        utm_hemisphere_val: "str | None" = None
        epsg_code_val: "int | None" = None
        input_crs_val = "unknown"
        crs_source_val = "missing"
        crs_confidence_val = "MISSING"

        if utm_zone_form:
            try:
                zone_num, hemi = parse_utm_zone_string(utm_zone_form)
                epsg_code_val = get_epsg_from_utm(zone_num, hemi)
                utm_zone_val = f"{zone_num}{hemi}"
                utm_hemisphere_val = hemi
                input_crs_val = f"EPSG:{epsg_code_val}"
                crs_source_val = "user_declared"
                crs_confidence_val = "HIGH"
                warns.append("Reproyección UTM→WGS84 real queda pendiente para R2.2 (pyproj).")
            except ValueError as e:
                warns.append(f"Zona UTM inválida ignorada: {e}")

        if crs_source_val == "missing":
            warns.append(
                "UTM detectado sin zona UTM verificada. "
                "Footprint derivado desde lat/lon central y extensión del CSV."
            )
            warns.append(
                "UTM detectado sin zona. Declarar zona UTM para mejorar precisión del footprint."
            )

        crs_utm = {
            "utm_zone": utm_zone_val,
            "utm_hemisphere": utm_hemisphere_val,
            "epsg_code": epsg_code_val,
            "input_crs": input_crs_val,
            "crs_source": crs_source_val,
            "crs_confidence": crs_confidence_val,
        }
        if has_anchor:
            return {"confidence": "MEDIUM", "type": "csv_utm", "warnings": warns, **crs_utm}
        warns.append("Sin lat/lon de anclaje. Footprint derivado no disponible.")
        georef_conf = "MEDIUM" if utm_zone_val else "LOW"
        return {"confidence": georef_conf, "type": "csv_utm", "warnings": warns, **crs_utm}

    if cs == "local_meters" and conf != "low":
        crs_local = {
            "utm_zone": None,
            "utm_hemisphere": None,
            "epsg_code": None,
            "input_crs": "local_meters",
            "crs_source": "missing",
            "crs_confidence": "MISSING",
        }
        if has_anchor:
            warns.append(
                "Metros locales anclados al punto central. "
                "Orientación y escala real no garantizadas."
            )
            warns.append(
                "La correspondencia entre coordenadas locales del CSV y el punto central "
                "no fue verificada matemáticamente."
            )
            return {"confidence": "LOW", "type": "local_meters_anchored", "warnings": warns, **crs_local}
        return {
            "confidence": "MISSING",
            "type": "local_reference",
            "warnings": [
                "Sin lat/lon de anclaje. Modelo en coordenadas locales sin ubicación geográfica absoluta."
            ],
            **crs_local,
        }

    # Unknown / low-confidence fallback
    crs_unknown = {
        "utm_zone": None,
        "utm_hemisphere": None,
        "epsg_code": None,
        "input_crs": "unknown",
        "crs_source": "missing",
        "crs_confidence": "MISSING",
    }
    if has_anchor:
        warns.append(
            "Sistema de coordenadas desconocido o baja confianza. "
            "Footprint estimado desde punto central."
        )
        return {"confidence": "LOW", "type": "derived", "warnings": warns, **crs_unknown}
    warns.append(
        "Sin lat/lon válidos y sistema de coordenadas desconocido. "
        "Georreferenciación no disponible."
    )
    return {"confidence": "MISSING", "type": "local_reference", "warnings": warns, **crs_unknown}


def _classify_georef(
    coordinate_transform,
    lat_value: "float | None",
    lon_value: "float | None",
    utm_zone_form: "str | None" = None,
) -> "tuple[str, str, str | None, list[str]]":
    """R1 API wrapper — retorna (confidence, type, utm_zone, warnings). Compatible con tests R1."""
    r = _classify_georef_full(coordinate_transform, lat_value, lon_value, utm_zone_form)
    return r["confidence"], r["type"], r["utm_zone"], r["warnings"]


def _build_missing_footprint(extra_warning: str = "") -> dict:
    warn = ["Sin coordenadas absolutas. Modelo sin ubicación geográfica."]
    if extra_warning:
        warn.append(extra_warning)
    return {
        "crs": "EPSG:4326",
        "type": "missing",
        "source": "missing",
        "confidence": "MISSING",
        "center_lat": None,
        "center_lon": None,
        "extent_x_m": None,
        "extent_z_m": None,
        "utm_zone": None,
        "sw": {"lat": None, "lon": None},
        "se": {"lat": None, "lon": None},
        "ne": {"lat": None, "lon": None},
        "nw": {"lat": None, "lon": None},
        "warnings": warn,
        "precision_notes": [],
    }


def _compute_spatial_readiness_for_import(
    csv_analysis: "Any",
    *,
    coordinate_system_detected: "str | None",
    utm_zone: "str | None",
    anchor_lat: "float | None",
    anchor_lon: "float | None",
) -> "SpatialReadiness":
    """
    R3.5-C — Clasifica suficiencia espacial del import.

    Nunca lanza excepción: si falla devuelve nivel conservador con warning.
    anchor_lat/lon es un punto central del usuario — NO equivale a lat/lon por estación.
    """
    from services.spatial_readiness_service import classify_spatial_readiness
    try:
        if csv_analysis is not None:
            return classify_from_csv_analysis(
                csv_analysis,
                utm_zone=utm_zone,
                anchor_lat=anchor_lat,
                anchor_lon=anchor_lon,
            )
        # Sin csv_analysis: fallback conservador según anchor
        return classify_spatial_readiness(
            coordinate_system_detected=coordinate_system_detected,
            has_station_coordinates=False,
        )
    except Exception:
        sr = classify_spatial_readiness(
            coordinate_system_detected=None,
            has_station_coordinates=False,
        )
        sr.warnings.append(
            "No fue posible clasificar completamente la suficiencia espacial."
        )
        return sr


def _enforce_spatial_readiness_gate(
    spatial_readiness: "SpatialReadiness",
    *,
    acknowledge_spatial_risk: bool,
    gravity_type: "str | None" = None,
) -> None:
    """
    R3.5-D — Hard gate industrial para inversión 3D.

    Lanza HTTPException(422) si el nivel espacial es insuficiente.
    NO bloquea si gravity_type == 'synthetic_demo'.

    Niveles bloqueados sin bypass:
      - NO_SPATIAL_DATA: sin coordenadas, imposible georreferenciar.
    Niveles bloqueados salvo acknowledgement:
      - LOCAL_UNANCHORED: coordenadas locales sin referencia geográfica.
      - LOCAL_ANCHORED_CENTER: anclaje central sin coords por estación.
      - UTM_NO_ZONE: UTM detectado pero zona desconocida.
    Niveles siempre permitidos:
      - UTM_WITH_ZONE, GEOGRAPHIC_COORDS, PROFESSIONAL_SURVEY.
    """
    if (gravity_type or "").lower() == "synthetic_demo":
        return

    level = spatial_readiness.level

    def _raise(
        message: str,
        required_acknowledgement: "str | None" = None,
        required_action: "str | None" = None,
    ) -> None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "SPATIAL_READINESS_GATE",
                "level": level,
                "message": message,
                "required_acknowledgement": required_acknowledgement,
                "missing_fields": spatial_readiness.missing_fields,
                "blocked_outputs": spatial_readiness.blocked_outputs,
                "allowed_outputs": spatial_readiness.allowed_outputs,
                "rationale": spatial_readiness.rationale,
                "required_action": required_action,
            },
        )

    if level == "NO_SPATIAL_DATA":
        _raise(
            "El CSV no contiene coordenadas espaciales. "
            "No es posible ejecutar la inversión 3D sin referencia posicional.",
            required_acknowledgement=None,
            required_action="Agregar columnas de coordenadas (x/y/z, lat/lon, o Easting/Northing) al CSV.",
        )

    # LOCAL_UNANCHORED / LOCAL_ANCHORED_CENTER: bloqueados salvo acknowledgement
    # explícito (decisión de producto 2026-06-10: datos sin georreferencia no
    # deben invertirse "sin querer"; el UI expone el checkbox de riesgo).
    if level == "LOCAL_UNANCHORED" and not acknowledge_spatial_risk:
        _raise(
            "Coordenadas locales sin anclaje geográfico. El modelo 3D no tendrá "
            "ubicación absoluta y solo es válido como ejercicio conceptual local.",
            required_acknowledgement=(
                spatial_readiness.required_acknowledgement or "ACK_LOCAL_CONCEPTUAL_ONLY"
            ),
            required_action=(
                "Confirmar acknowledge_spatial_risk=true o proporcionar anchor_lat/lon."
            ),
        )

    if level == "LOCAL_ANCHORED_CENTER" and not acknowledge_spatial_risk:
        _raise(
            "Coordenadas locales ancladas solo a un punto central declarado: "
            "orientación y escala real no verificadas.",
            required_acknowledgement=(
                spatial_readiness.required_acknowledgement or "ACK_LOCAL_ANCHORED_GEOREF"
            ),
            required_action=(
                "Confirmar acknowledge_spatial_risk=true o entregar coordenadas por estación."
            ),
        )

    if level == "UTM_NO_ZONE" and not acknowledge_spatial_risk:
        _raise(
            "Sistema UTM detectado pero zona desconocida. "
            "La conversión a coordenadas geográficas puede ser incorrecta.",
            required_acknowledgement="ACK_UTM_NO_ZONE",
            required_action="Especificar utm_zone en el formulario o confirmar acknowledge_spatial_risk=true.",
        )

    # UTM_WITH_ZONE, GEOGRAPHIC_COORDS, PROFESSIONAL_SURVEY — suficiencia completa, sin bloqueo.


@router.post("/preview", response_model=GravityImportPreviewResponse)
async def preview_gravity_csv(
    request: Request,
    file: UploadFile = File(...),
    strict: bool = Query(True),
    allow_g_raw: bool = Query(False),
    preview_limit: int = Query(20),
    data_type: str = Query("gravity"),  # Fase 9A: "magnetic" parsea columna TMI
):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if data_type not in ("gravity", "magnetic"):
        raise HTTPException(status_code=422, detail=f"data_type inválido: '{data_type}'.")

    temp_filename = f"{uuid.uuid4()}.csv"
    temp_path = Path(TMP_DIR) / temp_filename

    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo permitido: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(temp_path, "wb") as f:
            f.write(content)

        result = import_gravity_csv_v1(
            temp_path, strict=strict, allow_g_raw=allow_g_raw,
            data_kind="magnetic" if data_type == "magnetic" else "gravity",
        )

        observations_preview = result.observations[:preview_limit]
        observations_list = [model_to_dict(o) for o in observations_preview]

        # R3.5-K — use utm_zone detected from CSV as fallback for georef preview
        _preview_utm_zone = _extract_detected_utm_zone(result)

        # Georef preview — no lat/lon anchor at preview stage
        ct_obj = result.coordinate_transform
        georef_r2 = _classify_georef_full(ct_obj, None, None, utm_zone_form=_preview_utm_zone)
        georef_preview = {
            "confidence": georef_r2["confidence"],
            "type": georef_r2["type"],
            "utm_zone": georef_r2["utm_zone"],
            "utm_hemisphere": georef_r2["utm_hemisphere"],
            "epsg_code": georef_r2["epsg_code"],
            "input_crs": georef_r2["input_crs"],
            "crs_source": georef_r2["crs_source"],
            "crs_confidence": georef_r2["crs_confidence"],
            "warnings": georef_r2["warnings"],
            "note": (
                "Calculado durante preview. "
                "Puede cambiar al entregar lat/lon en inversión."
            ),
        }

        # R3.5-C / R3.5-K — Spatial readiness (preview: sin anchor lat/lon)
        cs_detected_preview = (
            getattr(ct_obj, "input_coordinate_system", None) if ct_obj else None
        )
        spatial_readiness_preview = _compute_spatial_readiness_for_import(
            result.csv_analysis,
            coordinate_system_detected=cs_detected_preview,
            utm_zone=_preview_utm_zone,
            anchor_lat=None,
            anchor_lon=None,
        )
        regional_scale_preflight = build_preflight_from_import_result(result)

        # R3.7 (restaurado 2026-06-10): el preview REPORTA la clase real
        # (incluido TOO_LARGE_SINGLE_INVERSION con sugerencias de subset/tile)
        # sin bloquear — el bloqueo ocurre en /invert.

        _auto_grid_dict = model_to_dict(result.auto_grid) if result.auto_grid else None
        _octree_params_top = (
            _auto_grid_dict.get("octree_params") if _auto_grid_dict else None
        )
        return sanitize_nan({
            "status": result.status,
            "previewCount": len(observations_preview),
            "totalObservations": len(result.observations),
            "observationsPreview": observations_list,
            "importMetadata": model_to_dict(result.import_metadata),
            "csv_analysis": model_to_dict(result.csv_analysis) if result.csv_analysis else None,
            "coordinate_transform": model_to_dict(result.coordinate_transform) if result.coordinate_transform else None,
            "auto_grid": _auto_grid_dict,
            "octree_params": _octree_params_top,
            # Fase 19 Tarea 1 — tipo de dato inferido desde columnas del CSV.
            "detected_data_type": (
                model_to_dict(result.detected_data_type)
                if result.detected_data_type else None
            ),
            "georef_preview": georef_preview,
            "spatial_readiness": model_to_dict(spatial_readiness_preview),
            "regional_scale_preflight": model_to_dict(regional_scale_preflight),
            # F2 — sniff físico (encoding/sep/decimal/preámbulo) con evidencia.
            "sniff_report": result.sniff_report,
            "warnings": result.warnings,
            "errors": result.errors
        })
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════════
# Flujo de datos de campo — POST /v2/gravity-import/invert-with-corrections
# CSV crudo → FAC+BC+TC+GRS80 automáticas → sigma por gravímetro → inversión
# W_z formal → obs vs calc → UBC-GIF (.msh + .den) → inversion_report.json
# ═════════════════════════════════════════════════════════════════════════════

_VALID_GRAVIMETERS = {"scintrex_cg6", "zls_burris", "lacoste_romberg", "unknown"}


@router_v2.post("/invert-with-corrections")
@limiter.limit("5/minute")
async def invert_with_corrections(
    request: Request,
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    run_id: Optional[str] = Form(None),
    gravimeter_type: str = Form("unknown"),
    reduction_density: float = Form(2.67),
    apply_terrain: bool = Form(True),
    terrain_radius: float = Form(22000.0),
    dem_type: str = Form("COP30"),
    noise_pct: float = Form(0.0),
    # Parámetros de inversión: 0 / no provisto = usar auto_grid del CSV
    nx: int = Form(0),
    ny: int = Form(0),
    nz: int = Form(0),
    block_size: int = Form(0),
    depth: int = Form(0),
    cutoff_radius: float = Form(0.0),
    lambda_mag: float = Form(0.0),
    alpha_spatial: float = Form(0.0),
    density_min: float = Form(0.0),
    density_max: float = Form(5.5),
    lat: Optional[str] = Form(None),
    lon: Optional[str] = Form(None),
):
    """
    Flujo completo de datos de campo reales (Plan Industrial Fase 1 + H-B2):
    correcciones geofísicas automáticas + sigma instrumental + inversión + export.

    - gravity_type crudo (g_raw/absolute_gravity) + lat/lon/elev → FAC/BC/TC/GRS80
      automáticas con reduction_density (CSV corregido persiste en el run dir).
    - gravity_type ya corregido (bouguer_anomaly, complete_bouguer_anomaly...) → tal cual.
    - sigma_i = max(noise_floor[gravimeter_type], noise_pct·|d_i|):
      scintrex_cg6=0.005 mGal, zls_burris=0.002, lacoste_romberg=0.010, unknown=0.020.
    """
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if gravimeter_type not in _VALID_GRAVIMETERS:
        raise HTTPException(
            status_code=422,
            detail=f"gravimeter_type inválido: '{gravimeter_type}'. "
                   f"Valores soportados: {sorted(_VALID_GRAVIMETERS)}.",
        )
    if not (1.0 <= reduction_density <= 4.0):
        raise HTTPException(
            status_code=422,
            detail=f"reduction_density={reduction_density} fuera de rango físico [1.0, 4.0] g/cm³.",
        )

    project_id = project_id or f"field_{uuid.uuid4().hex[:8]}"
    run_id = run_id or uuid.uuid4().hex[:16]

    temp_filename = f"{uuid.uuid4()}.csv"
    temp_path = Path(TMP_DIR) / temp_filename

    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo permitido: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(temp_path, "wb") as f:
            f.write(content)

        try:
            update_run_status(
                project_id=project_id, run_id=run_id,
                status="queued", progress=0.0, stage="queued",
                message="Flujo de datos de campo en cola (correcciones + inversión).",
            )
        except Exception:
            pass

        from services.gravity_import_service import run_field_data_inversion_with_corrections

        _overrides = {
            "nx": nx, "ny": ny, "nz": nz,
            "block_size": block_size, "depth": depth,
            "cutoff_radius": cutoff_radius,
            "lambda_mag": lambda_mag if lambda_mag > 0 else None,
            "alpha_spatial": alpha_spatial if alpha_spatial > 0 else None,
            "density_min": density_min, "density_max": density_max,
            "lat": lat, "lon": lon,
        }

        try:
            result = await run_field_data_inversion_with_corrections(
                csv_path=temp_path,
                project_id=project_id,
                run_id=run_id,
                gravimeter_type=gravimeter_type,
                reduction_density_gcc=reduction_density,
                apply_terrain=apply_terrain,
                terrain_radius_m=terrain_radius,
                dem_type=dem_type,
                noise_pct=noise_pct,
                inversion_overrides=_overrides,
            )
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FIELD_FLOW_INPUT_VALIDATION",
                    "message": str(exc),
                    "original_filename": file.filename,
                },
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            import traceback as _tb
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "FIELD_FLOW_RUNTIME_ERROR",
                    "message": str(exc),
                    "type": type(exc).__name__,
                    "traceback": _tb.format_exc()[-2000:],
                },
            ) from exc

        return sanitize_nan(result)
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass


@router_v2.post("/export-clean-csv", response_class=PlainTextResponse)
@limiter.limit("10/minute")
async def export_clean_csv(
    request: Request,
    file: UploadFile = File(...),
    strict: bool = Query(True),
    allow_g_raw: bool = Query(False),
    data_type: str = Query("gravity"),  # "gravity" | "magnetic"
):
    """FASE 19 — Devuelve el CSV LIMPIO (validado + enriquecido) descargable.

    Toma el CSV sucio, lo pasa por el mismo import que la inversión
    (`import_gravity_csv_v1`: normaliza unidades, detecta coordenadas, captura
    sigma/elevación/lat-lon por estación) y serializa el resultado a un CSV con
    columnas normalizadas (`services.gravity_import_service.build_clean_csv_from_import`).
    No recalcula física: refleja exactamente lo que consumirá el solver.

    Responde `text/csv` con `Content-Disposition: attachment`. Si el import falla,
    responde 422 con los errores (mismo contrato que /invert en etapa de import).
    """
    from fastapi.responses import PlainTextResponse
    from services.gravity_import_service import build_clean_csv_from_import

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if data_type not in ("gravity", "magnetic"):
        raise HTTPException(
            status_code=422,
            detail=f"data_type inválido: '{data_type}'. Use 'gravity' o 'magnetic'.",
        )

    temp_filename = f"{uuid.uuid4()}.csv"
    temp_path = Path(TMP_DIR) / temp_filename
    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo permitido: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(temp_path, "wb") as f:
            f.write(content)

        result = import_gravity_csv_v1(
            temp_path, strict=strict, allow_g_raw=allow_g_raw,
            data_kind="magnetic" if data_type == "magnetic" else "gravity",
        )
        if result.status != "ok":
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "CSV_IMPORT_FAILED",
                    "message": "No se pudo validar el CSV para exportar la versión limpia.",
                    "errors": result.errors,
                    "warnings": result.warnings,
                },
            )

        clean_csv = build_clean_csv_from_import(
            result, data_kind="magnetic" if data_type == "magnetic" else "gravity",
        )
        _base = Path(file.filename).stem
        out_name = f"{_base}_clean.csv"
        return PlainTextResponse(
            content=clean_csv,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{out_name}"',
                "X-TQ-Clean-Rows": str(len(result.observations or [])),
                "X-TQ-Import-Warnings": str(len(result.warnings or [])),
            },
        )
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════════
# FASE R4 — Paquete CSV auto-contenido: ensamblar (build) + cargar 3D (load)
# build-package: toma grav (+mag co-localizado opcional) + sondajes + params,
#   normaliza vía el mismo import que /invert, decide el combo multimodal (Fase 21)
#   y emite UN CSV con encabezado de metadatos. load-package: lo lee y rutea al
#   solver correcto (grav/mag/joint/+sondajes) reusando run_geophysics_inversion.
# ═════════════════════════════════════════════════════════════════════════════
# FASE 10 — `response_class` y no `response_model`: esta ruta devuelve el CSV del
# paquete como **texto**, no JSON. Sin esta línea el OpenAPI declaraba
# `application/json` para un `text/csv`, y cualquier generador de tipos habría
# fabricado un objeto que nadie devuelve nunca.
@router_v2.post("/build-package", response_class=PlainTextResponse)
@limiter.limit("10/minute")
async def build_package(
    request: Request,
    file: UploadFile = File(...),
    magnetic_file: Optional[UploadFile] = File(None),
    data_type: str = Query("gravity"),
    strict: bool = Query(True),
    allow_g_raw: bool = Query(False),
    config_json: Optional[str] = Form(None),
    boreholes_json: Optional[str] = Form(None),
):
    """FASE R4 — Ensambla el paquete CSV auto-contenido (texto descargable).

    Primario = `file` (gravimetría, o magnetometría si data_type="magnetic").
    `magnetic_file` opcional: magnetometría CO-LOCALIZADA (mismas estaciones) que
    se anexa como columna para habilitar la inversión CONJUNTA. `config_json` lleva
    los parámetros físicos; `boreholes_json` los sondajes de anclaje.
    """
    from fastapi.responses import PlainTextResponse
    from services.csv_package_service import build_package_text, merge_config
    from services.multimodal_fusion_service import plan_multimodal
    from core.errors import InsufficientDataError

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if data_type not in ("gravity", "magnetic"):
        raise HTTPException(
            status_code=422,
            detail=f"data_type inválido: '{data_type}'. Use 'gravity' o 'magnetic'.",
        )

    cfg_overrides: dict = {}
    if config_json:
        try:
            cfg_overrides = json.loads(config_json) or {}
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"config_json inválido: {exc}")
    boreholes: list = []
    if boreholes_json:
        try:
            _bh = json.loads(boreholes_json)
            if isinstance(_bh, dict):
                _bh = _bh.get("boreholes") or _bh.get("intervals") or []
            boreholes = list(_bh or [])
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"boreholes_json inválido: {exc}")

    tmp_primary = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
    tmp_mag: "Optional[Path]" = None
    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(tmp_primary, "wb") as f:
            f.write(content)

        primary = import_gravity_csv_v1(
            tmp_primary, strict=strict, allow_g_raw=allow_g_raw,
            data_kind="magnetic" if data_type == "magnetic" else "gravity",
        )
        if primary.status != "ok":
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "CSV_IMPORT_FAILED",
                    "message": "No se pudo validar el CSV primario para el paquete.",
                    "errors": primary.errors,
                    "warnings": primary.warnings,
                },
            )

        magnetic_values: "Optional[list]" = None
        has_magnetic = (data_type == "magnetic")
        if magnetic_file is not None and data_type == "gravity":
            if not magnetic_file.filename.lower().endswith(".csv"):
                raise HTTPException(status_code=400, detail="magnetic_file must end with .csv")
            tmp_mag = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
            with open(tmp_mag, "wb") as f:
                f.write(await magnetic_file.read())
            mag_res = import_gravity_csv_v1(
                tmp_mag, strict=False, allow_g_raw=True, data_kind="magnetic",
            )
            if mag_res.status != "ok":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "MAGNETIC_CSV_IMPORT_FAILED",
                        "message": "No se pudo validar el CSV magnético para el joint.",
                        "errors": mag_res.errors,
                    },
                )
            mag_obs = list(mag_res.observations or [])
            # Alineación por COORDENADA (no por índice): tolera reordenamiento y
            # estaciones magnéticas sobrantes; exige co-localización real (no
            # interpola). Lanza ValueError si alguna estación grav queda sin mag.
            from services.csv_package_service import align_magnetic_to_stations
            try:
                magnetic_values = align_magnetic_to_stations(
                    list(primary.observations or []), mag_obs,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "MAGNETIC_NOT_COLOCATED", "message": str(exc)},
                )
            has_magnetic = True
        elif data_type == "gravity":
            # Magnetometría co-localizada embebida en el propio CSV gravimétrico.
            _mv = getattr(primary, "magnetic_values", None)
            if _mv and any(abs(float(v)) > 0 for v in _mv):
                has_magnetic = True

        cfg = merge_config(cfg_overrides)
        cfg["data_type"] = data_type
        cfg["strict"] = strict
        cfg["allow_g_raw"] = allow_g_raw

        # ── Gates al ENSAMBLAR (fail-fast donde el usuario prepara) ───────────
        # Mismo contrato que /invert: bloquea datos sin referencia espacial o de
        # escala regional. Garantiza que cualquier paquete que EXISTE ya pasó los
        # gates, de modo que /load-package puede confiar en él sin re-validar.
        _eff_utm = _effective_utm_zone(cfg.get("utm_zone"), primary)
        _cs_detected = (
            getattr(primary.coordinate_transform, "input_coordinate_system", None)
            if primary.coordinate_transform else None
        )
        _anchor_lat = parse_geo_coord(str(cfg.get("lat") or ""), -90.0, 90.0)
        _anchor_lon = parse_geo_coord(str(cfg.get("lon") or ""), -180.0, 180.0)
        spatial_readiness = _compute_spatial_readiness_for_import(
            primary.csv_analysis,
            coordinate_system_detected=_cs_detected,
            utm_zone=_eff_utm,
            anchor_lat=_anchor_lat,
            anchor_lon=_anchor_lon,
        )
        _enforce_spatial_readiness_gate(
            spatial_readiness,
            acknowledge_spatial_risk=bool(cfg.get("acknowledge_spatial_risk", False)),
            gravity_type=getattr(primary.import_metadata, "gravity_type", None),
        )
        regional_preflight = build_preflight_from_import_result(primary)
        if regional_preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION":
            _raise_regional_scale_gate(
                regional_preflight,
                message=(
                    "El survey excede el tamaño para una inversión única: la grilla "
                    "necesaria supera los límites por dimensión. Use un subset local "
                    "o procese por tiles."
                ),
                required_action=regional_preflight.recommended_action,
            )
        if (
            regional_preflight.scale_class == "REGIONAL_SCALE"
            and regional_preflight.requires_user_acknowledgement
            and not bool(cfg.get("acknowledge_regional_scale", False))
        ):
            _raise_regional_scale_gate(
                regional_preflight,
                message=(
                    "El dataset corresponde a escala regional. Para empaquetar debe "
                    "aceptar explícitamente las limitaciones de escala."
                ),
                required_action="Marcar acknowledge_regional_scale=true o usar un subset local.",
            )

        n_sensors = len(primary.observations or [])
        has_gravity = (data_type == "gravity")
        try:
            plan = plan_multimodal(
                has_gravity=has_gravity,
                has_magnetic=has_magnetic,
                has_borehole=bool(boreholes),
                n_sensors=n_sensors,
            ).to_dict()
        except InsufficientDataError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "INSUFFICIENT_DATA", "message": str(exc)},
            )
        # Adjunta el veredicto de gates al plan (transparencia en el encabezado).
        plan["spatial_readiness_level"] = spatial_readiness.level
        plan["regional_scale_class"] = regional_preflight.scale_class

        text = build_package_text(
            primary_result=primary,
            data_type=data_type,
            config=cfg,
            magnetic_values=magnetic_values,
            boreholes=boreholes,
            plan=plan,
        )
        out_name = f"{Path(file.filename).stem}_package.tqpkg.csv"
        return PlainTextResponse(
            content=text,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{out_name}"',
                "X-TQ-Package-Route": str(plan.get("route")),
                "X-TQ-Package-Sensors": str(n_sensors),
            },
        )
    finally:
        for _p in (tmp_primary, tmp_mag):
            if _p and _p.exists():
                try:
                    os.remove(_p)
                except Exception:
                    pass


@router_v2.post("/analyze-columns", response_model=AnalyzeColumnsResponse)
@limiter.limit("30/minute")
async def analyze_columns_endpoint(
    request: Request,
    file: UploadFile = File(...),
    data_type: str = Query("gravity"),
    column_map_json: Optional[str] = Form(None),
):
    """PILAR 1 (KEYSTONE) — Devuelve el PLAN DE MAPEO de columnas de un CSV.

    Lee SOLO los encabezados (sin invertir), corre la auto-detección fuzzy y, si la
    confianza es baja (falta algún rol requerido), reporta `needs_mapping=True` junto
    con las columnas crudas + los roles a asignar. Un `column_map_json` opcional
    sobre-escribe la auto-detección (para previsualizar un mapeo manual antes de
    enriquecer). Nada se invierte ni se fabrica: solo se re-etiquetan columnas reales.
    """
    from fastapi.responses import JSONResponse

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if data_type not in ("gravity", "magnetic"):
        raise HTTPException(
            status_code=422,
            detail=f"data_type inválido: '{data_type}'. Use 'gravity' o 'magnetic'.",
        )

    column_map: Optional[dict] = None
    if column_map_json:
        try:
            column_map = json.loads(column_map_json) or None
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"column_map_json inválido: {exc}")
        if column_map is not None and not isinstance(column_map, dict):
            raise HTTPException(status_code=422, detail="column_map debe ser un objeto {rol: columna}.")

    tmp = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(tmp, "wb") as f:
            f.write(content)

        # F2 — muestra de valores para la heurística de RANGO físico (además
        # del mapeo por nombre): permite sospechas (northing-en-y) y sugerencias.
        headers, samples = read_csv_sample(tmp)
        if not headers:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "CSV_NO_HEADERS",
                    "message": "No se pudieron leer columnas del CSV (archivo vacío o ilegible).",
                },
            )
        plan = build_column_mapping_plan(
            headers, data_kind=data_type, column_map=column_map,
            sample_values=samples or None,
        )
        # F2 — sniff físico con evidencia (encoding/sep/decimal/preámbulo/filas
        # rotas): la UI lo muestra junto al plan de mapeo para que el usuario
        # confirme lo detectado. sample_rows = primeras filas YA parseadas
        # (preview honesto: lo que el importador ve, no lo que el archivo dice).
        from services.csv_sniffer_service import sniff_csv

        sniff = sniff_csv(tmp)
        return JSONResponse(content=sanitize_nan({
            "column_mapping": plan,
            "sniff_report": sniff.to_dict(),
            "sample_rows": _sample_rows_preview(headers, samples),
        }))
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except Exception:
                pass


@router_v2.post("/parse-rows", response_model=ParseRowsResponse)
@limiter.limit("30/minute")
async def parse_rows_endpoint(
    request: Request,
    file: UploadFile = File(...),
    max_rows: int = Query(50_000, ge=1, le=200_000),
):
    """F2 cierre de deuda — filas COMPLETAS ya parseadas por el pipeline oficial.

    Para consumidores frontend que necesitan las FILAS (no solo encabezados),
    como el wizard de correcciones: parsear CSV en TypeScript duplicaría el
    sniffer y reintroduciría el bug decimal-coma (parseFloat("1,23")=1 en
    silencio). Aquí el sniffer + el lector del importador hacen el trabajo
    (encoding/separador/decimal/preámbulo/filas rotas) y los valores vuelven
    canónicos (punto decimal). Devuelve además el SniffReport (evidencia).
    """
    from fastapi.responses import JSONResponse

    _fn = (file.filename or "").lower()
    if not (_fn.endswith(".csv") or _fn.endswith(".tqpkg") or _fn.endswith(".txt")):
        raise HTTPException(status_code=400, detail="File must end with .csv/.tqpkg/.txt")

    tmp = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(tmp, "wb") as f:
            f.write(content)

        headers, samples = read_csv_sample(tmp, nrows=max_rows)
        if not headers:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "CSV_NO_HEADERS",
                    "message": "No se pudieron leer columnas del CSV (archivo vacío o ilegible).",
                },
            )
        rows = _sample_rows_preview(headers, samples, limit=max_rows)
        from services.csv_sniffer_service import sniff_csv

        return JSONResponse(content=sanitize_nan({
            "headers": headers,
            "rows": rows,
            "n_rows": len(rows),
            "truncated": len(rows) >= max_rows,
            "sniff_report": sniff_csv(tmp).to_dict(),
        }))
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except Exception:
                pass


@router_v2.post("/enrich-package", response_model=EnrichPackageResponse)
@limiter.limit("10/minute")
async def enrich_package_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    gravity_file: Optional[UploadFile] = File(None),
    magnetic_file: Optional[UploadFile] = File(None),
    data_type: str = Query("gravity"),
    strict: bool = Query(False),
    allow_g_raw: bool = Query(True),
    enable_dem: bool = Query(True),
    config_json: Optional[str] = Form(None),
    boreholes_json: Optional[str] = Form(None),
    column_map_json: Optional[str] = Form(None),
    magnetic_column_map_json: Optional[str] = Form(None),
    helmert_control_points_json: Optional[str] = Form(None),
):
    """Preparación con ENRIQUECIMIENTO: deriva con física real lo que falte y emite
    un paquete TQPKG completo (descargable) + un resumen de qué calculó/agregó.

    PILAR 2 — contrato HONESTO por ROL. Recibe los datos por su rol, sin exigir
    gravimetría: gravity_file / magnetic_file (explícito), o file + data_type
    (legacy). Combinaciones: grav-sola, mag-sola, grav+mag (joint), y cualquiera +
    sondajes (boreholes_json, que solo anclan). Un CSV de sólo sondajes (o vacío) se
    RECHAZA con error claro (PILAR 6): no define una inversión por sí mismo.

    A diferencia de /build-package (que solo fusiona), este endpoint:
      • completa elevación faltante muestreando un DEM (opentopo),
      • reduce gravedad cruda a anomalía de Bouguer (GRS80/FAC/BC),
      • reconstruye lat/lon desde UTM (pyproj),
      • deriva σ por estación y reporta el score de calidad,
      • resuelve el IGRF si el contexto lo provee.
    Devuelve JSON {filename, package_text, enrichment_summary, plan, warnings,
    needs_context}. Nada se fabrica: lo no-derivable queda fuera + bandera.
    """
    from fastapi.responses import JSONResponse
    from services.csv_package_service import build_package_text, merge_config
    from services.csv_enrichment_service import enrich_package
    from services.multimodal_fusion_service import plan_multimodal
    from core.errors import InsufficientDataError

    if data_type not in ("gravity", "magnetic"):
        raise HTTPException(
            status_code=422,
            detail=f"data_type inválido: '{data_type}'. Use 'gravity' o 'magnetic'.",
        )

    # ── PILAR 2 — Resolución por ROL ──────────────────────────────────────────
    # Roles explícitos (gravity_file/magnetic_file) o legacy file+data_type. La
    # gravimetría manda; con solo magnetometría el primario es magnético.
    _grav_up = gravity_file
    _mag_up = magnetic_file
    if file is not None:
        if data_type == "magnetic" and _mag_up is None:
            _mag_up = file
        elif _grav_up is None:
            _grav_up = file
    if _grav_up is None and _mag_up is None:
        # Sólo sondajes / vacío → error claro (no se fabrica una inversión).
        raise HTTPException(
            status_code=422,
            detail={
                "error": "INSUFFICIENT_DATA",
                "message": (
                    "Se necesita al menos un campo potencial: gravimetría O "
                    "magnetometría. Un CSV de sólo sondajes (o vacío) no define una "
                    "inversión; cárgalo junto con gravimetría/magnetometría para "
                    "usarlo como restricción."
                ),
            },
        )
    data_type = "gravity" if _grav_up is not None else "magnetic"
    file = _grav_up if _grav_up is not None else _mag_up
    magnetic_file = _mag_up if _grav_up is not None else None

    for _up, _label in ((file, "file"), (magnetic_file, "magnetic_file")):
        if _up is not None and not (_up.filename or "").lower().endswith(".csv"):
            raise HTTPException(
                status_code=400, detail=f"{_label} must end with .csv",
            )

    cfg_overrides: dict = {}
    if config_json:
        try:
            cfg_overrides = json.loads(config_json) or {}
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"config_json inválido: {exc}")
    boreholes: list = []
    if boreholes_json:
        try:
            _bh = json.loads(boreholes_json)
            if isinstance(_bh, dict):
                _bh = _bh.get("boreholes") or _bh.get("intervals") or []
            boreholes = list(_bh or [])
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"boreholes_json inválido: {exc}")

    tmp_primary = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
    tmp_mag: "Optional[Path]" = None
    try:
        content = await file.read()
        if len(content) > CSV_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo CSV demasiado grande. Máximo: {CSV_MAX_BYTES // 1048576} MB.",
            )
        with open(tmp_primary, "wb") as f:
            f.write(content)

        # PILAR 1 — mapeo manual (opcional). column_map del form (JSON {rol: columna}).
        column_map: Optional[dict] = None
        if column_map_json:
            try:
                column_map = json.loads(column_map_json) or None
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"column_map_json inválido: {exc}")
            if column_map is not None and not isinstance(column_map, dict):
                raise HTTPException(
                    status_code=422,
                    detail="column_map debe ser un objeto {rol: columna}.",
                )

        # TAREA C — mapeo manual del 2.º archivo (magnético), independiente del
        # column_map del primario (que aplica SOLO al gravity_file). Sin esta clave
        # el magnético sigue cayendo en auto-detección (comportamiento histórico).
        magnetic_column_map: Optional[dict] = None
        if magnetic_column_map_json:
            try:
                magnetic_column_map = json.loads(magnetic_column_map_json) or None
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"magnetic_column_map_json inválido: {exc}",
                )
            if magnetic_column_map is not None and not isinstance(magnetic_column_map, dict):
                raise HTTPException(
                    status_code=422,
                    detail="magnetic_column_map debe ser un objeto {rol: columna}.",
                )

        # Si la auto-detección no resuelve los roles requeridos y el usuario NO aportó
        # mapeo → responder needs_mapping (200, sin paquete) para mostrar el MAPEO.
        # F2 — con muestra de valores: la heurística de rango puede además marcar
        # needs_confirmation (confianza MEDIA: sugiere y PREGUNTA, jamás aplica solo).
        _primary_headers, _primary_samples = read_csv_sample(tmp_primary)
        _plan = build_column_mapping_plan(
            _primary_headers, data_kind=data_type, column_map=column_map,
            sample_values=_primary_samples or None,
        )
        # F2.4 — preguntas blocking sin responder (unidad, tipo de gravedad):
        # se pregunta ANTES de importar (responder viaja por column_map_json).
        _blocking_questions = [
            q for q in _plan.get("questions", []) if q.get("blocking")
        ]
        # blocking gates SIEMPRE que sigan sin respuesta (el plan las recalcula
        # con el column_map recibido: una pregunta respondida desaparece);
        # needs_confirmation solo gatea si el usuario aún no mapeó nada.
        if (
            _plan["needs_mapping"]
            or _blocking_questions
            or (_plan.get("needs_confirmation") and not column_map)
        ):
            from services.csv_sniffer_service import sniff_csv as _sniff_csv

            _needs_conf = not _plan["needs_mapping"]
            return JSONResponse(
                content=sanitize_nan({
                    # needs_mapping=True también en el caso de confirmación:
                    # la UI existente abre el paso de mapeo prellenado y el
                    # re-envío con column_map destraba ambos gates.
                    "needs_mapping": True,
                    "needs_confirmation": _needs_conf,
                    "column_mapping": _plan,
                    # F2 — el sniff acompaña al plan: la UI muestra qué formato
                    # se detectó mientras el usuario asigna roles; sample_rows
                    # = preview de filas YA parseadas.
                    "sniff_report": _sniff_csv(tmp_primary).to_dict(),
                    "sample_rows": _sample_rows_preview(
                        _primary_headers, _primary_samples
                    ),
                    "message": (
                        (
                            "El mapeo automático detectó algo sospechoso en los "
                            "RANGOS de valores (ver 'suspicions'/'suggestions'). "
                            "Confirme o corrija el mapeo de columnas antes de continuar."
                        )
                        if _needs_conf
                        else (
                            "No se reconocieron automáticamente todas las columnas "
                            "requeridas. Asigne manualmente los roles e intente de nuevo."
                        )
                    ),
                })
            )

        # F2.4 — literal inferido con evidencia (tipo de gravedad desde el
        # nombre de la columna, patrón 60d1c56): se PRE-APLICA con aviso
        # visible, nunca en silencio. Evita que el enriquecimiento re-reduzca
        # un dato ya reducido (doble-Bouguer) cuando el header lo declara.
        _inferred = _plan.get("inferred_literals") or {}
        _inferred_notes: list = []
        if "gravity_type" in _inferred and not (column_map or {}).get("gravity_type"):
            column_map = dict(column_map or {})
            column_map["gravity_type"] = _inferred["gravity_type"]["value"]
            _inferred_notes.append(_inferred["gravity_type"]["note"])

        primary = import_gravity_csv_v1(
            tmp_primary, strict=strict, allow_g_raw=allow_g_raw,
            data_kind="magnetic" if data_type == "magnetic" else "gravity",
            column_map=column_map,
        )
        if primary.status != "ok":
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "CSV_IMPORT_FAILED",
                    "message": "No se pudo validar el CSV primario para enriquecer.",
                    "errors": primary.errors,
                    "warnings": primary.warnings,
                },
            )

        magnetic_values: "Optional[list]" = None
        has_magnetic = (data_type == "magnetic")
        if magnetic_file is not None and data_type == "gravity":
            if not magnetic_file.filename.lower().endswith(".csv"):
                raise HTTPException(status_code=400, detail="magnetic_file must end with .csv")
            tmp_mag = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
            with open(tmp_mag, "wb") as f:
                f.write(await magnetic_file.read())
            mag_res = import_gravity_csv_v1(
                tmp_mag, strict=False, allow_g_raw=True, data_kind="magnetic",
                column_map=magnetic_column_map,
            )
            if mag_res.status != "ok":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "MAGNETIC_CSV_IMPORT_FAILED",
                        "message": "No se pudo validar el CSV magnético para el joint.",
                        "errors": mag_res.errors,
                    },
                )
            from services.csv_package_service import align_magnetic_to_stations
            try:
                magnetic_values = align_magnetic_to_stations(
                    list(primary.observations or []), list(mag_res.observations or []),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "MAGNETIC_NOT_COLOCATED", "message": str(exc)},
                )
            has_magnetic = True
        elif data_type == "gravity":
            _mv = getattr(primary, "magnetic_values", None)
            if _mv and any(abs(float(v)) > 0 for v in _mv):
                has_magnetic = True

        cfg = merge_config(cfg_overrides)
        cfg["data_type"] = data_type
        cfg["strict"] = strict
        cfg["allow_g_raw"] = allow_g_raw

        # ── Pipeline de enriquecimiento (física real, nada fabricado) ─────────
        enrichment = await enrich_package(
            primary,
            data_type=data_type,
            config=cfg,
            enable_dem=enable_dem,
            reduction_density_gcc=float(cfg.get("density_reduction", 2.67) or 2.67),
        )
        # Los overrides de config derivados (IGRF, densidad de reducción) entran al
        # encabezado del paquete para trazabilidad.
        for k, v in enrichment.config_overrides.items():
            if k in cfg:
                cfg[k] = v

        n_sensors = len(primary.observations or [])
        try:
            plan = plan_multimodal(
                has_gravity=(data_type == "gravity"),
                has_magnetic=has_magnetic,
                has_borehole=bool(boreholes),
                n_sensors=n_sensors,
            ).to_dict()
        except InsufficientDataError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "INSUFFICIENT_DATA", "message": str(exc)},
            )

        text = build_package_text(
            primary_result=primary,
            data_type=data_type,
            config=cfg,
            magnetic_values=magnetic_values,
            boreholes=boreholes,
            plan=plan,
            override_elevations=enrichment.elevations,
            override_sigmas=enrichment.sigmas,
            override_latlon=enrichment.latlon,
            override_g_mgal=enrichment.g_mgal,
            gravity_type_out=enrichment.gravity_type_out,
        )
        out_name = f"{Path(file.filename).stem}_package.tqpkg.csv"
        summary = enrichment.summary()

        # ── FASE 19 (Caso B): Georef Helmert en el ENRIQUECIMIENTO ────────────
        # Cierra la asimetría con /invert: un usuario con coords LOCALES que entra
        # por «Generar CSV completo» (→/enrich-package) también obtiene georef si
        # aporta ≥2 puntos de control. Reusa el MISMO helper/schema que /invert (no
        # se duplica la matemática). Sin el param → summary byte-idéntico a hoy.
        if helmert_control_points_json:
            from schemas.gravity_import_schema import HelmertControlPointsInput
            from services.gravity_import_service import (
                georeference_stations_with_helmert,
            )

            # <2 puntos / JSON malo → 422 claro (vía ValidationError del schema),
            # igual que /invert. NO se silencia: el usuario pidió georef.
            try:
                _hc_input = HelmertControlPointsInput(**json.loads(helmert_control_points_json))
            except (ValidationError, ValueError, json.JSONDecodeError) as _hexc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "HELMERT_INPUT_INVALID",
                        "message": (
                            "helmert_control_points_json inválido (se requieren ≥2 "
                            f"puntos de control local↔real): {_hexc}"
                        ),
                    },
                )

            _cs_detected = (
                getattr(primary.coordinate_transform, "input_coordinate_system", None)
                if primary.coordinate_transform else None
            )
            _cs_local = (_cs_detected or "").lower() in ("local_meters", "local", "unknown")
            if _cs_local:
                _station_xz = [
                    (float(o.x_m), float(o.z_m)) for o in (primary.observations or [])
                ]
                _helmert_georef = georeference_stations_with_helmert(_hc_input, _station_xz)
                summary["helmert_georef"] = _helmert_georef
            else:
                summary["helmert_georef"] = {
                    "skipped": True,
                    "reason": (
                        f"Coordenadas del CSV no son locales (detectado: "
                        f"{_cs_detected}); Helmert no aplica."
                    ),
                }

        return JSONResponse(
            content=sanitize_nan({
                "filename": out_name,
                "package_text": text,
                "enrichment_summary": summary,
                "plan": plan,
                # F2.4 — los literales inferidos con evidencia SIEMPRE avisan.
                "warnings": list(primary.warnings or []) + _inferred_notes,
                "needs_context": summary["needs_context"],
                "n_stations": n_sensors,
                # F2 — sniff físico del CSV primario (evidencia de formato).
                "sniff_report": primary.sniff_report,
            })
        )
    finally:
        for _p in (tmp_primary, tmp_mag):
            if _p and _p.exists():
                try:
                    os.remove(_p)
                except Exception:
                    pass


# `exclude_unset` es OBLIGATORIO aquí: esta ruta tiene TRES respuestas
# (error/queued/done) y el modelo declara la unión de las tres. Sin él, una
# respuesta `queued` saldría con `inversionResult: null` — un campo que ese caso
# nunca tuvo y que el frontend usa para discriminar.
@router_v2.post("/load-package", response_model=LoadPackageResponse,
                response_model_exclude_unset=True)
@limiter.limit("10/minute")
async def load_package(
    request: Request,
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    run_id: Optional[str] = Form(None),
    sync: bool = Form(False),
):
    """FASE R4 + F3 — Lee el paquete auto-contenido y ENCOLA la inversión ruteada.

    Separa encabezado (config + sondajes + plan) del cuerpo CSV, importa el cuerpo
    por el mismo camino que /invert, y construye GeophysicsInvertInput. El ruteo a
    grav/mag/joint/+sondajes lo decide run_geophysics_inversion según la presencia
    de señal gravimétrica/magnética y los sondajes.

    F3 (default): la inversión corre en un worker de PROCESO y este endpoint
    devuelve {status:"queued", project_id, run_id, budget} de inmediato; el
    progreso por etapas se consulta en GET /geophysics-status/{p}/{r} y se
    cancela con POST /geophysics-cancel/{p}/{r}. Con sync=true se conserva el
    comportamiento histórico bloqueante (tests de contrato / scripts).
    """
    from services.csv_package_service import parse_package_text

    _fn = (file.filename or "").lower()
    if not (_fn.endswith(".csv") or _fn.endswith(".tqpkg")):
        raise HTTPException(status_code=400, detail="File must be a .csv/.tqpkg package")

    content = await file.read()
    if len(content) > CSV_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Paquete demasiado grande. Máximo: {CSV_MAX_BYTES // 1048576} MB.",
        )
    try:
        parsed = parse_package_text(content.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "INVALID_PACKAGE", "message": str(exc)},
        )

    cfg = parsed.config
    is_magnetic = (parsed.data_type == "magnetic")

    # Fix R4 — IDs auto-generados si el cliente no los provee, para que el block
    # model SIEMPRE se persista (parquet) y el visor 3D pueda recuperarlo. El
    # cliente puede pasar los suyos para controlar el run.
    _stem = Path(file.filename or "package").stem.lower()
    _stem = "".join(c if c.isalnum() else "_" for c in _stem).strip("_")[:48] or "package"
    if not project_id:
        project_id = f"pkg_{_stem}_{uuid.uuid4().hex[:8]}"
    if not run_id:
        run_id = f"run_pkg_{uuid.uuid4().hex[:12]}"

    tmp = Path(TMP_DIR) / f"{uuid.uuid4()}.csv"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(parsed.body_csv)

        import_result = import_gravity_csv_v1(
            tmp,
            strict=bool(cfg.get("strict", True)),
            allow_g_raw=bool(cfg.get("allow_g_raw", False)),
            data_kind="magnetic" if is_magnetic else "gravity",
        )
        if import_result.status != "ok":
            return sanitize_nan({
                "status": "error",
                "stage": "import",
                "warnings": import_result.warnings,
                "errors": import_result.errors,
                "inversionResult": None,
            })

        observations = list(import_result.observations or [])
        auto_grid = import_result.auto_grid
        if auto_grid is None and import_result.csv_analysis:
            auto_grid = import_result.csv_analysis.auto_grid
        if auto_grid is None:
            raise HTTPException(status_code=500, detail="auto_grid no disponible tras importar el paquete.")

        # Grilla efectiva: usar el valor del paquete si cabe (1..80), si no el auto_grid.
        def _eff_dim(v, av):
            v = int(v or 0)
            return v if (0 < v <= 80) else int(av)

        effective_nx = _eff_dim(cfg.get("nx", 0), auto_grid.nx)
        effective_ny = _eff_dim(cfg.get("ny", 0), auto_grid.ny)
        effective_nz = _eff_dim(cfg.get("nz", 0), auto_grid.nz)
        _bs = float(cfg.get("block_size", 0) or 0)
        effective_block_size = int(math.ceil(_bs)) if _bs > 0 else int(math.ceil(auto_grid.block_size_m))
        _dp = float(cfg.get("depth", 0) or 0)
        effective_depth = int(math.ceil(_dp)) if _dp > 0 else int(math.ceil(auto_grid.depth_m))
        _cr = float(cfg.get("cutoff_radius", 0) or 0)
        effective_cutoff_radius = _cr if _cr > 0 else float(auto_grid.cutoff_radius_m)

        # Ruteo magnético/joint (espejo de /invert): magnetic mueve g→magnetic_nt;
        # gravedad con columna magnética co-localizada habilita el joint.
        magnetic_nt: "Optional[list[float]]" = None
        effective_observations = observations
        if is_magnetic:
            from schemas.geophysics_schema import GravityObservation as _GravObs
            magnetic_nt = [float(o.g) for o in observations]
            effective_observations = [
                _GravObs(x_m=o.x_m, y_m=o.y_m, z_m=o.z_m, g=0.0) for o in observations
            ]
        else:
            _mv = import_result.magnetic_values
            if (
                _mv is not None
                and len(_mv) == len(observations)
                and all(v == v and v not in (float("inf"), float("-inf")) for v in _mv)
                and any(abs(float(v)) > 0 for v in _mv)
            ):
                magnetic_nt = [float(v) for v in _mv]

        # Sondajes de anclaje desde el encabezado del paquete.
        boreholes_parsed = None
        if parsed.boreholes:
            from schemas.geophysics_schema import BoreholeInterval as _BHInterval
            try:
                boreholes_parsed = [_BHInterval(**_b) for _b in parsed.boreholes]
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "INVALID_PACKAGE_BOREHOLES", "message": str(exc)},
                )

            # F4.4: persistir los sondajes por corrida para el visor 3D. Aislado en
            # try/except → nunca rompe el load (si falla, el visor solo no los muestra).
            try:
                from services.block_model_store import get_run_dir as _get_run_dir
                _bh_dir = _get_run_dir(project_id, run_id)
                _bh_dir.mkdir(parents=True, exist_ok=True)
                (_bh_dir / "boreholes.json").write_text(
                    json.dumps(parsed.boreholes, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as _bh_persist_exc:
                print(f"[LOAD-PACKAGE] No se pudieron persistir sondajes: {_bh_persist_exc}")

        # Sigma por estación (mediana de la columna uncertainty) + topografía.
        noise_floor = None
        _unc = import_result.station_uncertainties
        if _unc:
            _fin = sorted(u for u in _unc if u == u and u > 0.0)
            if len(_fin) >= max(3, len(_unc) // 2):
                noise_floor = float(_fin[len(_fin) // 2])
        sensor_elevs = None
        _se = import_result.station_elevations
        if _se and len(_se) == len(observations):
            _se_fin = [v for v in _se if v == v]
            if len(_se_fin) == len(_se) and (max(_se_fin) - min(_se_fin)) >= 10.0:
                sensor_elevs = [float(v) for v in _se]

        # Fase 7B — params avanzados (objetos anidados en el encabezado del paquete).
        _pgi_parsed = None
        _pgi_obj = cfg.get("pgi_params")
        if isinstance(_pgi_obj, dict):
            from schemas.geophysics_schema import PgiParams as _PgiParams
            try:
                _pgi_parsed = _PgiParams(**_pgi_obj)
            except Exception:
                _pgi_parsed = None
        _rem_parsed = None
        _rem_obj = cfg.get("remanence")
        if isinstance(_rem_obj, dict):
            from schemas.geophysics_schema import MagneticRemanenceParams as _RemParams
            try:
                _rem_parsed = _RemParams(**_rem_obj)
            except Exception:
                _rem_parsed = None

        # ── FASE 14 — prior geológico implícito (φ HRBF desde los contactos) ──
        # A diferencia de los dos de arriba, un `implicit_geology` mal formado NO se
        # descarta en silencio: el usuario pidió que su geología acotara la inversión
        # y devolverle un modelo sin ella, sin decírselo, es exactamente el defecto
        # que la auditoría llama «el backend hace lo honesto y el camino del usuario
        # se detiene ahí» (H-28/H-10). Se avisa por el canal de warnings del paquete.
        _geo_parsed = None
        _geo_obj = cfg.get("implicit_geology")
        if isinstance(_geo_obj, dict):
            from schemas.geophysics_schema import ImplicitGeologyParams as _GeoParams
            try:
                _geo_parsed = _GeoParams(**_geo_obj)
            except Exception as _geo_exc:
                import_result.warnings.append(
                    f"implicit_geology del paquete es inválido y se IGNORA "
                    f"(la inversión corre sin prior geológico): {_geo_exc}"
                )
        elif _geo_obj is not None:
            import_result.warnings.append(
                "implicit_geology del paquete no es un objeto y se IGNORA "
                "(la inversión corre sin prior geológico)."
            )

        try:
            invert_input = GeophysicsInvertInput(
                project_id=project_id,
                run_id=run_id,
                depth=effective_depth,
                nir=int(cfg.get("nir", 83)),
                fe=int(cfg.get("fe", 79)),
                region=str(cfg.get("region", "norte_chile")),
                lat=cfg.get("lat"),
                lon=cfg.get("lon"),
                nx=effective_nx,
                ny=effective_ny,
                nz=effective_nz,
                block_size=effective_block_size,
                cutoff_radius=effective_cutoff_radius,
                lambda_mag=float(cfg.get("lambda_mag", 0.0)),
                alpha_spatial=float(cfg.get("alpha_spatial", 1.0)),
                observations=effective_observations,
                enable_focusing=True,
                density_min=float(cfg.get("density_min", 0.0)),
                density_max=float(cfg.get("density_max", 5.5)),
                sensor_elevations_masl=sensor_elevs,
                noise_floor_mgal=noise_floor,
                gravimeter_type=str(cfg.get("gravimeter_type", "unknown")),
                magnetic_nt=magnetic_nt,
                inclination_deg=float(cfg.get("inclination_deg", -30.0)),
                declination_deg=float(cfg.get("declination_deg", 2.0)),
                field_intensity_nt=float(cfg.get("field_intensity_nt", 23500.0)),
                susc_min=float(cfg.get("susc_min", 0.0)),
                susc_max=float(cfg.get("susc_max", 1.0)),
                boreholes=boreholes_parsed,
                pgi_params=_pgi_parsed,
                remanence=_rem_parsed,
                # FASE 14 — None = inversión byte-idéntica (sin prior geológico).
                implicit_geology=_geo_parsed,
                padding_kappa=float(cfg.get("padding_kappa", 1e5)),
                anchor_kappa=float(cfg.get("anchor_kappa", 1e4)),
                auto_kappa=bool(cfg.get("auto_kappa", True)),
                # FASE 24B/render — norma de regularización (opt-in). MEDIDO (sintético
                # v2, vía este flujo): con el auto-λ de Morozov (que baja λ para χ²≈1)
                # la norma COMPACTA AFILA EL RUIDO en focos dispersos (conc. 38% vs 70%
                # de L2). Compact solo entrega cuerpo nítido a λ alto (≈1.0 → conc 99%)
                # PERO con χ²≈3.8 (subajuste) y ese λ NO generaliza (es escala-dependiente).
                # Por eso el DEFAULT del paquete es "L2" (χ²≈1 escala-adaptivo + concentración
                # sana); la limpieza visual del halo la hace el frontend (piso relativo al
                # pico). Compact queda disponible (cfg["regularization_norm"]="compact") para
                # quien fije un λ alto y acepte el subajuste. Ver tabla en el reporte.
                regularization_norm=str(cfg.get("regularization_norm", "L2")),
                compact_max_irls=int(cfg.get("compact_max_irls", 8)),
                compact_eps=float(cfg.get("compact_eps", 0.05)),
                # Prior de profundidad opt-in (docs/05 Parte B). OFF por defecto → byte-idéntico.
                enable_depth_prior=bool(cfg.get("enable_depth_prior", False)),
                depth_prior_safety_fraction=float(cfg.get("depth_prior_safety_fraction", 0.7)),
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "PACKAGE_INPUT_VALIDATION",
                    "message": "Parámetros inválidos al construir la inversión desde el paquete.",
                    "errors": exc.errors(),
                },
            ) from exc

        # ── F3 — Presupuesto de vóxeles ANTES de encolar (aviso previo). ─────
        from services.run_queue_service import (
            estimate_inversion_budget,
            submit_package_inversion,
        )

        _route = str(parsed.plan.get("route") or "gravity_only")
        _budget = estimate_inversion_budget(
            _route, invert_input.nx * invert_input.ny * invert_input.nz
        )

        if not sync:
            # F3 — FLUJO POR DEFECTO: encolar en un worker de PROCESO y
            # devolver de inmediato. El progreso por etapas reales viaja por
            # GET /geophysics-status (mismo canal que el flujo directo); la
            # cancelación por POST /geophysics-cancel. Nunca más "error
            # interno del proxy" por una inversión larga.
            submit_package_inversion(
                invert_input.model_dump(),
                project_id, run_id,
                route=_route,
                config={k: cfg.get(k) for k in ("nx", "ny", "nz", "block_size", "depth") if k in cfg},
            )
            return sanitize_nan({
                "status": "queued",
                "stage": "queued",
                "project_id": project_id,
                "run_id": run_id,
                "route": _route,
                "multimodal_plan": parsed.plan,
                "budget": _budget,
                "warnings": (
                    list(import_result.warnings)
                    + ([_budget["warning"]] if _budget.get("warning") else [])
                ),
                "errors": [],
                "poll": {
                    "status_url": f"/geophysics-status/{project_id}/{run_id}",
                    "cancel_url": f"/geophysics-cancel/{project_id}/{run_id}",
                    "interval_ms": 1500,
                },
                "inversionResult": None,
            })

        # ── Camino SÍNCRONO (sync=true): comportamiento histórico, para tests
        # de contrato y scripts; NO es el camino del producto (proxy timeout).
        # Crea el run_dir antes de invertir (igual que /invert) para que el SSE
        # pueda conectar y el solver persista el block model (parquet).
        try:
            update_run_status(
                project_id=project_id, run_id=run_id, status="queued",
                progress=0.0, stage="queued", message="Inversión (paquete) en cola.",
            )
        except Exception:
            pass

        try:
            inversion_result = run_geophysics_inversion(invert_input)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "GEOPHYSICS_INPUT_VALIDATION", "message": str(exc)},
            ) from exc
        except Exception as exc:
            # F2 nunca-crashea: el solver del flujo de PAQUETE (el caso largo
            # joint) solo capturaba ValueError → cualquier RuntimeError/
            # MemoryError/numpy era un 500 pelado. Mismo contrato que /invert.
            import traceback as _tb

            _detail = {
                "error": "INVERSION_RUNTIME_ERROR",
                "message": str(exc),
                "type": type(exc).__name__,
                "traceback": _tb.format_exc()[-2000:],
            }
            from core.errors import TerraquantumError as _TQError

            if isinstance(exc, _TQError):
                _detail.update(exc.to_dict())
            try:
                update_run_status(
                    project_id=project_id, run_id=run_id, status="error",
                    stage="solving", message=str(exc)[:300],
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=_detail) from exc

        _inversion_dict = model_to_dict(inversion_result) if inversion_result else {}
        if isinstance(_inversion_dict, dict) and "voxels" in _inversion_dict:
            _inversion_dict.pop("voxels", None)

        return sanitize_nan({
            "status": "done",
            "stage": "inversion",
            "project_id": project_id,
            "run_id": run_id,
            "route": parsed.plan.get("route"),
            "multimodal_plan": parsed.plan,
            "warnings": import_result.warnings,
            "errors": [],
            "inversionResult": _inversion_dict,
        })
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except Exception:
                pass



# ═════════════════════════════════════════════════════════════════════════════
# FASE 8 — el handler HTTP, en su tamaño
# ═════════════════════════════════════════════════════════════════════════════
# `invert_gravity_csv` medía 927 líneas, CC 165 y **41 parámetros** — la firma
# más ancha del backend. El paso 2 de la fase pide dejar el handler en «validar,
# delegar, serializar» y agrupar esos 41 parámetros en objetos cohesivos.
#
# UNA CORRECCIÓN MEDIDA AL PLAN. La auditoría propone agruparlos en «objetos
# Pydantic» — leído literal, `Annotated[Modelo, Form()]`. Se probó, y **cambia el
# contrato HTTP**: con FastAPI 0.135 el formulario deja de tener campos planos
# (`nx`, `ny`, `lambda_mag`, …) y pasa a exigir un campo `malla` con el objeto
# dentro. El frontend actual dejaría de funcionar, y esta fase tiene prohibido
# cambiar comportamiento.
#
# Lo que SÍ conserva el contrato —comprobado campo a campo contra el endpoint
# plano, incluidos los valores por defecto y el esquema OpenAPI— es construir los
# mismos objetos con `Depends`: los `Form(...)` viven en la dependencia, FastAPI
# los sigue publicando planos, y la firma del handler baja de 41 a 9.
#
# Los modelos son `BaseModel` y no `dataclass` a propósito: así el mismo objeto
# sirve para documentar el formulario y para pasar de una etapa a otra.


class CorridaCfg(BaseModel):
    """Identidad de la corrida y banderas de importación."""
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    nir: int = 0
    fe: int = 0
    region: str = ""
    strict: bool = True
    allow_g_raw: bool = False
    pgi_params_json: Optional[str] = None
    remanence_json: Optional[str] = None
    # FASE 14 — prior geológico implícito (φ HRBF desde contactos de sondaje).
    implicit_geology_json: Optional[str] = None


class MallaCfg(BaseModel):
    """Caja de inversión pedida por el usuario (el auto-grid puede sustituirla)."""
    depth: int = 0
    nx: int = 0
    ny: int = 0
    nz: int = 0
    block_size: int = 0
    cutoff_radius: float = 0.0


class RegularizacionCfg(BaseModel):
    """λ, suavidad y norma del funcional."""
    lambda_mag: float = 0.0
    alpha_spatial: float = 1.0
    regularization_norm: str = "L2"
    compact_max_irls: int = 8
    compact_eps: float = 0.05


class AnclajeCfg(BaseModel):
    """Padding, anclaje por sondajes y ajuste automático de condicionamiento."""
    padding_kappa: float = 1e5
    anchor_kappa: float = 1e4
    auto_kappa: bool = True
    boreholes_json: Optional[str] = None


class PesosDatoCfg(BaseModel):
    """Bounds petrofísicos y el instrumento que fija el piso de σ."""
    density_min: float = 0.0
    density_max: float = 5.5
    gravimeter_type: str = "unknown"


class GeorefCfg(BaseModel):
    """Anclaje geográfico y los dos reconocimientos explícitos de riesgo."""
    lat: str = "0.0"
    lon: str = "0.0"
    utm_zone: Optional[str] = None
    acknowledge_spatial_risk: bool = False
    acknowledge_regional_scale: bool = False
    helmert_control_points_json: Optional[str] = None


class MagneticaCfg(BaseModel):
    """Ruteo a magnetometría y parámetros del campo inductor."""
    data_type: str = "gravity"
    inclination_deg: float = -30.0
    declination_deg: float = 2.0
    field_intensity_nt: float = 23500.0
    susc_min: float = 0.0
    susc_max: float = 1.0


def _cfg_corrida(
    project_id: Optional[str] = Form(None),
    run_id: Optional[str] = Form(None),
    nir: int = Form(...),
    fe: int = Form(...),
    region: str = Form(...),
    strict: bool = Form(True),
    allow_g_raw: bool = Form(False),
    pgi_params_json: Optional[str] = Form(None),
    remanence_json: Optional[str] = Form(None),
    implicit_geology_json: Optional[str] = Form(None),
) -> CorridaCfg:
    return CorridaCfg(
        project_id=project_id, run_id=run_id, nir=nir, fe=fe, region=region,
        strict=strict, allow_g_raw=allow_g_raw, pgi_params_json=pgi_params_json,
        remanence_json=remanence_json, implicit_geology_json=implicit_geology_json)


def _cfg_malla(
    depth: int = Form(...),
    nx: int = Form(...),
    ny: int = Form(...),
    nz: int = Form(...),
    block_size: int = Form(...),
    cutoff_radius: float = Form(...),
) -> MallaCfg:
    return MallaCfg(depth=depth, nx=nx, ny=ny, nz=nz, block_size=block_size,
                    cutoff_radius=cutoff_radius)


def _cfg_regularizacion(
    lambda_mag: float = Form(...),
    alpha_spatial: float = Form(...),
    # FASE 24B — /invert (flujo directo) conserva "L2" por default (puede correr a
    # escala regional donde L2 es lo apropiado); el flujo de PAQUETE usa "compact".
    regularization_norm: str = Form("L2"),
    compact_max_irls: int = Form(8),
    compact_eps: float = Form(0.05),
) -> RegularizacionCfg:
    return RegularizacionCfg(
        lambda_mag=lambda_mag, alpha_spatial=alpha_spatial,
        regularization_norm=regularization_norm,
        compact_max_irls=compact_max_irls, compact_eps=compact_eps)


def _cfg_anclaje(
    # FASE 16 — Kappas configurables y ajuste automático de condicionamiento
    padding_kappa: float = Form(1e5),
    anchor_kappa: float = Form(1e4),
    auto_kappa: bool = Form(True),
    # FASE 20 (Caso B) — Sondajes que anclan la inversión (combo grav+sondajes).
    boreholes_json: Optional[str] = Form(None),
) -> AnclajeCfg:
    return AnclajeCfg(padding_kappa=padding_kappa, anchor_kappa=anchor_kappa,
                      auto_kappa=auto_kappa, boreholes_json=boreholes_json)


def _cfg_pesos_dato(
    # Bounds petrofísicos (t/m³ absolutos; base=2.6). density_min < 2.6 permite
    # contrastes NEGATIVOS (magma, sal, cavidades). Default 0.0 = bound físico
    # mínimo (recomendación industrial v2; el clip de no-negatividad estricta
    # degrada el misfit ~35% en cuerpos compactos).
    density_min: float = Form(0.0),
    density_max: float = Form(5.5),
    # Instrumento del survey: fija el piso de sigma y habilita la selección de
    # lambda por Morozov cuando lambda_mag=0 (sigma explícito → chi² interpretable).
    gravimeter_type: str = Form("unknown"),
) -> PesosDatoCfg:
    return PesosDatoCfg(density_min=density_min, density_max=density_max,
                        gravimeter_type=gravimeter_type)


def _cfg_georef(
    lat: str = Form("0.0"),
    lon: str = Form("0.0"),
    utm_zone: Optional[str] = Form(None),
    acknowledge_spatial_risk: bool = Form(False),
    acknowledge_regional_scale: bool = Form(False),
    # FASE 19 (Caso B) — Georef Helmert: ≥2 puntos de control local↔real (JSON).
    helmert_control_points_json: Optional[str] = Form(None),
) -> GeorefCfg:
    return GeorefCfg(
        lat=lat, lon=lon, utm_zone=utm_zone,
        acknowledge_spatial_risk=acknowledge_spatial_risk,
        acknowledge_regional_scale=acknowledge_regional_scale,
        helmert_control_points_json=helmert_control_points_json)


def _cfg_magnetica(
    # data_type="magnetic" parsea una columna TMI (nT) y rutea al motor magnético
    # (inversión de susceptibilidad). "gravity" (default) = comportamiento intacto.
    data_type: str = Form("gravity"),
    inclination_deg: float = Form(-30.0),
    declination_deg: float = Form(2.0),
    field_intensity_nt: float = Form(23500.0),
    susc_min: float = Form(0.0),
    susc_max: float = Form(1.0),
) -> MagneticaCfg:
    return MagneticaCfg(
        data_type=data_type, inclination_deg=inclination_deg,
        declination_deg=declination_deg, field_intensity_nt=field_intensity_nt,
        susc_min=susc_min, susc_max=susc_max)


@dataclass
class _EstadoInvert:
    """Lo que cada etapa del endpoint deja para la siguiente."""
    import_result: object = None
    effective_utm: object = None
    cs_detected_invert: object = None
    utm_zone_mismatch_warning: object = None
    lat_value: object = None
    lon_value: object = None
    project_meta_warning: object = None
    spatial_readiness_invert: object = None
    is_magnetic_run: bool = False
    # correcciones y grilla
    effective_observations: object = None
    corrections_warnings: object = None
    corrections_meta: object = None
    auto_grid: object = None
    auto_params_metadata: object = None
    effective_nx: int = 0
    effective_ny: int = 0
    effective_nz: int = 0
    effective_block_size: int = 0
    effective_depth: int = 0
    effective_cutoff_radius: float = 0.0
    legacy_frontend_params: object = None
    regional_preflight: object = None
    x_extent: float = 0.0
    z_extent: float = 0.0
    # extras parseados
    sensor_elevs_v1: object = None
    noise_floor_from_unc: object = None
    magnetic_nt: object = None
    pgi_params_parsed: object = None
    remanence_parsed: object = None
    boreholes_parsed: object = None
    implicit_geology_parsed: object = None
    # resultado
    inversion_result: object = None
    # georef
    georef_confidence: object = None
    georef_type: object = None
    utm_zone_val: object = None
    georef_warnings: object = None
    utm_hemisphere_val: object = None
    epsg_code_val: object = None
    input_crs_val: object = None
    crs_source_val: object = None
    crs_confidence_val: object = None
    footprint_dict: object = None
    # persistencia
    persisted: bool = False
    persistence_warning: object = None
    source_csv_path_str: object = None
    metadata_path_str: object = None
    r3_enrichment_result: object = None



async def _invert_importar_y_validar(file, temp_path, corrida: CorridaCfg,
                                     georef: GeorefCfg, est: _EstadoInvert):
    """Lee el CSV, lo importa y aplica el gate espacial.

    Devuelve `None` si todo fue bien (el estado queda en `est`) o el **dict de
    respuesta** cuando la importación falla: ese `return` intermedio es el mismo
    del monolito y se conserva palabra por palabra.
    """
    strict = corrida.strict
    allow_g_raw = corrida.allow_g_raw
    utm_zone = georef.utm_zone
    lat = georef.lat
    lon = georef.lon
    acknowledge_spatial_risk = georef.acknowledge_spatial_risk
    _is_magnetic_run = est.is_magnetic_run

    content = await file.read()
    if len(content) > CSV_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo CSV demasiado grande. Máximo permitido: {CSV_MAX_BYTES // 1048576} MB.",
        )
    with open(temp_path, "wb") as f:
        f.write(content)

    import_result = import_gravity_csv_v1(
        temp_path, strict=strict, allow_g_raw=allow_g_raw,
        data_kind="magnetic" if _is_magnetic_run else "gravity",
    )

    # R3.5-K — compute effective UTM zone: form param takes priority, CSV-detected as fallback
    _effective_utm = _effective_utm_zone(utm_zone, import_result)
    _csv_detected_zone = _extract_detected_utm_zone(import_result)
    _utm_zone_mismatch_warning: "str | None" = None
    if (
        utm_zone and utm_zone.strip()
        and _csv_detected_zone
        and _csv_detected_zone != utm_zone.strip()
    ):
        _utm_zone_mismatch_warning = (
            f"Zona UTM declarada en formulario ({utm_zone.strip()}) difiere de la zona UTM "
            f"detectada en CSV ({_csv_detected_zone}); se usó la zona del formulario."
        )

    if import_result.status != "ok":
        _cs_detected_import_error = (
            getattr(import_result.coordinate_transform, "input_coordinate_system", None)
            if import_result.coordinate_transform else None
        )
        spatial_readiness_import_error = _compute_spatial_readiness_for_import(
            import_result.csv_analysis,
            coordinate_system_detected=_cs_detected_import_error,
            utm_zone=_effective_utm,
            anchor_lat=parse_geo_coord(lat, -90.0, 90.0),
            anchor_lon=parse_geo_coord(lon, -180.0, 180.0),
        )
        try:
            _rsp_import_error = model_to_dict(build_preflight_from_import_result(import_result))
        except Exception:
            _rsp_import_error = None
        return {
            "status": "error",
            "stage": "import",
            "importMetadata": model_to_dict(import_result.import_metadata) if import_result.import_metadata else None,
            "csv_analysis": model_to_dict(import_result.csv_analysis) if import_result.csv_analysis else None,
            "coordinate_transform": model_to_dict(import_result.coordinate_transform) if import_result.coordinate_transform else None,
            "auto_grid": model_to_dict(import_result.auto_grid) if import_result.auto_grid else None,
            "spatial_readiness": model_to_dict(spatial_readiness_import_error),
            "regional_scale_preflight": _rsp_import_error,
            "warnings": import_result.warnings,
            "errors": import_result.errors,
            "inversionResult": None
        }

    # R3.5-D — Parse anchor coords early (required by spatial gate before solver)
    lat_value = parse_geo_coord(lat, -90.0, 90.0)
    lon_value = parse_geo_coord(lon, -180.0, 180.0)
    project_meta_warning: Optional[str] = None
    if lat_value is None or lon_value is None:
        project_meta_warning = "Invalid lat/lon; geospatial metadata was stored as null."

    # R3.5-D — Spatial readiness must be classified before the solver call
    _cs_detected_invert = (
        getattr(import_result.coordinate_transform, "input_coordinate_system", None)
        if import_result.coordinate_transform else None
    )
    spatial_readiness_invert = _compute_spatial_readiness_for_import(
        import_result.csv_analysis,
        coordinate_system_detected=_cs_detected_invert,
        utm_zone=_effective_utm,
        anchor_lat=lat_value,
        anchor_lon=lon_value,
    )

    # R3.5-D — Hard gate: raises HTTP 422 if spatial readiness is insufficient
    _enforce_spatial_readiness_gate(
        spatial_readiness_invert,
        acknowledge_spatial_risk=acknowledge_spatial_risk,
        gravity_type=getattr(import_result.import_metadata, "gravity_type", None),
    )

    est.import_result = import_result
    est.effective_utm = _effective_utm
    est.cs_detected_invert = _cs_detected_invert
    est.utm_zone_mismatch_warning = _utm_zone_mismatch_warning
    est.lat_value = lat_value
    est.lon_value = lon_value
    est.project_meta_warning = project_meta_warning
    est.spatial_readiness_invert = spatial_readiness_invert
    return None



def _invert_corregir_gravedad(est: _EstadoInvert):
    """H-B2: GRS80 + aire libre + Bouguer cuando el dato es `g_raw` con lat/lon/elev."""
    import_result = est.import_result
    _is_magnetic_run = est.is_magnetic_run

    # H-B2 — Apply gravity corrections when data is g_raw and lat/lon/elev available.
    # Corrections (GRS80 latitude, FAC, Bouguer) are applied in-place on a new
    # observations list; the original import_result is not mutated.
    _corrections_meta: dict = {}
    _corrections_warnings: list[str] = []
    _gravity_type_raw = getattr(import_result.import_metadata, "gravity_type", None) or ""
    _effective_observations = list(import_result.observations)

    # magnetic_only: las correcciones gravimétricas (GRS80/FAC/BC/TC) NO aplican.
    _ALREADY_CORRECTED = {"bouguer_anomaly", "complete_bouguer_anomaly", "synthetic_demo", "magnetic_only"}
    if (
        not _is_magnetic_run
        and _gravity_type_raw not in _ALREADY_CORRECTED
        and import_result.raw_latlon_elev is not None
        and len(import_result.raw_latlon_elev) == len(import_result.observations)
    ):
        try:
            import numpy as _np
            from services.gravity_corrections_service import apply_all_corrections
            from schemas.geophysics_schema import GravityObservation as _GravObs

            _lats = _np.array([s["lat_deg"] for s in import_result.raw_latlon_elev])
            _lons = _np.array([s["lon_deg"] for s in import_result.raw_latlon_elev])
            _elevs_raw = _np.array([s["elev_m"] for s in import_result.raw_latlon_elev])
            _g_ms2 = _np.array([obs.g for obs in import_result.observations])
            _g_mgal = _g_ms2 * 1e5  # m/s² → mGal

            _has_elevations = (
                not _np.all(_np.isnan(_elevs_raw))
                and not _np.all(_elevs_raw == 0.0)
            )
            _elevs = _np.where(_np.isnan(_elevs_raw), 0.0, _elevs_raw)

            _g_corrected_mgal, _corr_meta = apply_all_corrections(
                lats_deg=_lats,
                lons_deg=_lons,
                elevs_m=_elevs,
                g_obs_mgal=_g_mgal,
                gravity_type_in=_gravity_type_raw if _gravity_type_raw else "g_raw",
                apply_lat=True,
                apply_fac=_has_elevations,
                apply_bouguer=_has_elevations,
                apply_terrain=False,
            )

            _effective_observations = [
                _GravObs(x_m=obs.x_m, y_m=obs.y_m, z_m=obs.z_m, g=float(gc) / 1e5)
                for obs, gc in zip(import_result.observations, _g_corrected_mgal)
            ]
            _corrections_meta = _corr_meta
            _corrections_meta["has_elevations"] = _has_elevations
            _applied = _corr_meta.get("corrections_applied", [])
            _out_type = _corr_meta.get("output_gravity_type", "unknown")
            _corrections_warnings.append(
                f"[H-B2] Correcciones aplicadas: {_applied}. "
                f"Tipo salida: {_out_type}. "
                f"{'FAC+BC aplicados.' if _has_elevations else 'Sin FAC/BC (elevación no disponible).'}"
            )
            _log.info(
                "gravity_corrections_applied",
                n_stations=len(_effective_observations),
                corrections=_applied,
                output_type=_out_type,
                has_elevations=_has_elevations,
            )
        except Exception as _corr_exc:
            _corrections_warnings.append(
                f"[H-B2] Correcciones de gravedad no aplicadas: {_corr_exc}. "
                "Inversión continúa con datos originales."
            )
            _log.warning("gravity_corrections_failed", error=str(_corr_exc))
    elif _gravity_type_raw not in _ALREADY_CORRECTED and import_result.raw_latlon_elev is None:
        _corrections_warnings.append(
            "[H-B2] Correcciones de gravedad omitidas: el CSV no es de tipo latlon "
            "o no contiene columnas de lat/lon. Para aplicar FAC/BC/TC proporcionar "
            "un CSV con columnas lat, lon y elev_m."
        )

    est.effective_observations = _effective_observations
    est.corrections_warnings = _corrections_warnings
    est.corrections_meta = _corrections_meta


def _invert_resolver_grilla(est: _EstadoInvert, malla: MallaCfg,
                            reg: RegularizacionCfg, georef: GeorefCfg):
    """Grilla efectiva (usuario vs auto-grid), gate de escala regional y metadatos."""
    import_result = est.import_result
    _effective_observations = est.effective_observations
    _corrections_meta = est.corrections_meta
    spatial_readiness_invert = est.spatial_readiness_invert
    nx = malla.nx
    ny = malla.ny
    nz = malla.nz
    block_size = malla.block_size
    depth = malla.depth
    cutoff_radius = malla.cutoff_radius
    lambda_mag = reg.lambda_mag
    alpha_spatial = reg.alpha_spatial
    acknowledge_regional_scale = georef.acknowledge_regional_scale

    xs = [obs.x_m for obs in _effective_observations]
    zs = [obs.z_m for obs in _effective_observations]
    auto_grid = import_result.auto_grid
    if auto_grid is None and import_result.csv_analysis:
        auto_grid = import_result.csv_analysis.auto_grid
    if auto_grid is None:
        raise HTTPException(status_code=500, detail="auto_grid no disponible tras importar CSV.")

    # R3.8-A — Priorizar parámetros del usuario si caben en los límites.
    # Si el usuario especificó nx/ny/nz y son ≤ 80, usarlos. Si no, usar auto_grid.
    max_grid_dim = 80  # Límite de esquema de inversión
    effective_nx = nx if (nx > 0 and nx <= max_grid_dim) else auto_grid.nx
    effective_ny = ny if (ny > 0 and ny <= max_grid_dim) else auto_grid.ny
    effective_nz = nz if (nz > 0 and nz <= max_grid_dim) else auto_grid.nz
    effective_block_size = int(math.ceil(block_size)) if block_size > 0 else int(math.ceil(auto_grid.block_size_m))
    effective_depth = int(math.ceil(depth)) if depth > 0 else int(math.ceil(auto_grid.depth_m))
    effective_cutoff_radius = float(cutoff_radius) if cutoff_radius > 0 else auto_grid.cutoff_radius_m

    # R3.7-C (restaurado 2026-06-10) — Regional scale preflight gate.
    # TOO_LARGE_SINGLE_INVERSION se evalúa sobre la EXTENSIÓN del survey
    # (auto-grid): si la grilla necesaria excede los límites por dimensión,
    # ninguna caja chica especificada por el usuario produce un modelo
    # físicamente significativo (modo de fallo "kernel vacío"). Se bloquea
    # con guía de subset/tile — sin bypass por acknowledgement.
    regional_preflight = build_preflight_from_import_result(import_result)
    if regional_preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION":
        _raise_regional_scale_gate(
            regional_preflight,
            message=(
                "El survey excede el tamaño máximo para una inversión única: "
                "la grilla necesaria supera los límites por dimensión. "
                "Use un subset local o procese por tiles."
            ),
            required_action=regional_preflight.recommended_action,
        )

    # R3.8-B — Recalcular preflight con los parámetros efectivos del usuario
    # (solo informativo/ack para clases ≤ REGIONAL_SCALE).
    if (effective_nx != auto_grid.nx or effective_ny != auto_grid.ny or
        effective_nz != auto_grid.nz or effective_depth != auto_grid.depth_m):
        from services.regional_scale_preflight_service import classify_regional_scale_preflight
        regional_preflight = classify_regional_scale_preflight(
            extent_x_m=max(xs) - min(xs) if xs else None,
            extent_z_m=max(zs) - min(zs) if zs else None,
            station_count=len(import_result.observations),
            estimated_nx=effective_nx,
            estimated_ny=effective_ny,
            estimated_nz=effective_nz,
            estimated_voxel_count=effective_nx * effective_ny * effective_nz,
            estimated_depth_m=effective_depth,
            estimated_block_size_m=effective_block_size,
            max_allowed_nx=max_grid_dim,
            max_allowed_ny=max_grid_dim,
            max_allowed_nz=max_grid_dim,
        )

    if (
        regional_preflight.scale_class == "REGIONAL_SCALE"
        and regional_preflight.requires_user_acknowledgement
    ):
        if not acknowledge_regional_scale:
            _raise_regional_scale_gate(
                regional_preflight,
                message=(
                    "El dataset corresponde a escala regional. Para continuar debe aceptar "
                    "explícitamente las limitaciones de escala."
                ),
                required_action=(
                    "Marcar acknowledge_regional_scale=true o usar un subset local."
                ),
            )
        else:
            regional_preflight.warnings.append(
                "Usuario aceptó ejecutar inversión regional/conceptual con limitaciones de escala."
            )

    x_extent = max(xs) - min(xs)
    z_extent = max(zs) - min(zs)
    legacy_frontend_params = {
        "depth": depth,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "block_size": block_size,
        "cutoff_radius": cutoff_radius,
        "lambda_mag": lambda_mag,
        "alpha_spatial": alpha_spatial,
    }
    auto_params_metadata = build_auto_params_metadata(
        csv_analysis=import_result.csv_analysis,
        coordinate_transform=import_result.coordinate_transform,
        auto_grid=auto_grid,
        legacy_frontend_params=legacy_frontend_params,
    )
    # R3.5-E — pass spatial_readiness so geophysics_service can apply caps
    auto_params_metadata["spatial_readiness"] = model_to_dict(spatial_readiness_invert)
    # R3.7-C — pass regional_scale_preflight for report persistence
    auto_params_metadata["regional_scale_preflight"] = model_to_dict(regional_preflight)
    auto_params_metadata["acknowledge_regional_scale"] = acknowledge_regional_scale
    # H-B2 — record corrections applied (empty dict = no corrections)
    auto_params_metadata["gravity_corrections"] = _corrections_meta

    est.auto_grid = auto_grid
    est.auto_params_metadata = auto_params_metadata
    est.effective_nx = effective_nx
    est.effective_ny = effective_ny
    est.effective_nz = effective_nz
    est.effective_block_size = effective_block_size
    est.effective_depth = effective_depth
    est.effective_cutoff_radius = effective_cutoff_radius
    est.legacy_frontend_params = legacy_frontend_params
    est.regional_preflight = regional_preflight
    est.x_extent = x_extent
    est.z_extent = z_extent


def _invert_extras_y_parseos(est: _EstadoInvert, corrida: CorridaCfg,
                             georef: GeorefCfg, anclas: AnclajeCfg):
    """Helmert, topografía de estación, σ del CSV, magnetometría y JSON avanzados."""
    import_result = est.import_result
    _is_magnetic_run = est.is_magnetic_run
    _effective_observations = est.effective_observations
    _corrections_warnings = est.corrections_warnings
    _cs_detected_invert = est.cs_detected_invert
    auto_params_metadata = est.auto_params_metadata
    helmert_control_points_json = georef.helmert_control_points_json
    pgi_params_json = corrida.pgi_params_json
    remanence_json = corrida.remanence_json
    implicit_geology_json = corrida.implicit_geology_json
    boreholes_json = anclas.boreholes_json

    # ── FASE 19 (Caso B): Georef Helmert con puntos de control ────────────
    # Si el usuario aportó ≥2 puntos de control y el CSV es de coordenadas
    # LOCALES, resolvemos la transformada de similitud y georeferenciamos las
    # estaciones (footprint real + validación del anclaje por residual). NO se
    # toca la grilla (opera en metros locales, invariante a traslación/rotación).
    if helmert_control_points_json:
        try:
            from schemas.gravity_import_schema import HelmertControlPointsInput
            from services.gravity_import_service import georeference_stations_with_helmert

            _hc_input = HelmertControlPointsInput(**json.loads(helmert_control_points_json))
            _cs_local = (_cs_detected_invert or "").lower() in (
                "local_meters", "local", "unknown",
            )
            if _cs_local:
                _station_xz = [(float(o.x_m), float(o.z_m)) for o in _effective_observations]
                _helmert_georef = georeference_stations_with_helmert(_hc_input, _station_xz)
                auto_params_metadata["helmert_georef"] = _helmert_georef
                _corrections_warnings.append(
                    f"[Fase 19] Georef Helmert aplicada: {_helmert_georef['n_stations']} "
                    f"estaciones, confidence={_helmert_georef['confidence']}, "
                    f"residual_rms={_helmert_georef['transform'].get('residual_rms_m')} m."
                )
                _corrections_warnings.extend(_helmert_georef.get("warnings", []))
            else:
                auto_params_metadata["helmert_georef"] = {
                    "skipped": True,
                    "reason": (
                        f"Coordenadas del CSV no son locales (detectado: "
                        f"{_cs_detected_invert}); Helmert no aplica."
                    ),
                }
                _corrections_warnings.append(
                    "[Fase 19] Puntos de control Helmert ignorados: el CSV ya trae "
                    f"coordenadas georreferenciadas ({_cs_detected_invert})."
                )
        except (ValueError, ValidationError, json.JSONDecodeError) as _hexc:
            _corrections_warnings.append(
                f"[Fase 19] Georef Helmert no aplicada (entrada inválida): {_hexc}."
            )

    # ── Topografía activa: elevaciones de estación (cualquier coord type) ──
    # Solo si todas las estaciones tienen elevación y el relieve supera 10 m
    # (bajo eso, la máscara topográfica no aporta y solo mete ruido numérico).
    _sensor_elevs_v1: "Optional[list[float]]" = None
    _se_list = import_result.station_elevations
    if _se_list and len(_se_list) == len(_effective_observations):
        _se_finite = [v for v in _se_list if v == v]  # NaN != NaN
        if len(_se_finite) == len(_se_list) and (max(_se_finite) - min(_se_finite)) >= 10.0:
            _sensor_elevs_v1 = [float(v) for v in _se_list]
            _corrections_warnings.append(
                f"Topografía activa: elevaciones de estación "
                f"({min(_se_finite):.0f}–{max(_se_finite):.0f} m) aplicadas como "
                "máscara topográfica del modelo."
            )

    # ── Sigma por estación: mediana de la columna uncertainty [mGal] ────────
    # Prioridad: σ por estación > piso por gravímetro > sentinel adaptivo.
    _noise_floor_from_unc: "Optional[float]" = None
    _unc_list = import_result.station_uncertainties
    if _unc_list:
        _unc_finite = sorted(u for u in _unc_list if u == u and u > 0.0)
        if len(_unc_finite) >= max(3, len(_unc_list) // 2):
            _noise_floor_from_unc = float(_unc_finite[len(_unc_finite) // 2])
            _corrections_warnings.append(
                f"Sigma del solver fijado desde la columna uncertainty del CSV: "
                f"piso = {_noise_floor_from_unc:.4g} mGal (mediana por estación)."
            )

    # ── Magnetometría / Joint ────────────────────────────────────────────────
    # • magnetic_run: TMI está en el slot g → se mueve a magnetic_nt y g=0
    #   (motor magnético aislado, ignora g).
    # • gravity con columna magnética co-localizada (import.magnetic_values):
    #   se conserva g real Y se pasa magnetic_nt → ruteo a inversión CONJUNTA
    #   (run_geophysics_inversion enruta a joint cuando g≠0 y magnetic_nt≠0).
    _magnetic_nt: "Optional[list[float]]" = None
    if _is_magnetic_run:
        from schemas.geophysics_schema import GravityObservation as _GravObs
        _magnetic_nt = [float(o.g) for o in _effective_observations]
        _effective_observations = [
            _GravObs(x_m=o.x_m, y_m=o.y_m, z_m=o.z_m, g=0.0)
            for o in _effective_observations
        ]
    elif import_result.magnetic_values is not None:
        _mv = import_result.magnetic_values
        _all_finite = (
            len(_mv) == len(_effective_observations)
            and all(v == v and v not in (float("inf"), float("-inf")) for v in _mv)
        )
        if _all_finite and any(abs(float(v)) > 0 for v in _mv):
            _magnetic_nt = [float(v) for v in _mv]
            _corrections_warnings.append(
                f"Survey co-localizado: columna magnética detectada en el CSV "
                f"gravimétrico ({len(_mv)} estaciones) → inversión CONJUNTA "
                "(gravedad + magnetometría, cross-gradient)."
            )
        else:
            _corrections_warnings.append(
                "Columna magnética presente pero con huecos/ceros: se ignora "
                "para el joint; se corre solo gravedad."
            )

    # Fase 7B — Parse advanced params from JSON strings
    _pgi_params_parsed = None
    if pgi_params_json:
        try:
            from schemas.geophysics_schema import PgiParams as _PgiParams
            _pgi_params_parsed = _PgiParams(**json.loads(pgi_params_json))
        except Exception as _e:
            _corrections_warnings.append(f"pgi_params_json inválido (ignorado): {_e}")

    _remanence_parsed = None
    if remanence_json:
        try:
            from schemas.geophysics_schema import MagneticRemanenceParams as _RemParams
            _remanence_parsed = _RemParams(**json.loads(remanence_json))
        except Exception as _e:
            _corrections_warnings.append(f"remanence_json inválido (ignorado): {_e}")

    # FASE 14 — prior geológico implícito. Mismo canal de aviso que sus vecinos:
    # si llega mal formado se dice, porque una inversión sin la geología que el
    # usuario pidió no es la que pidió.
    _implicit_geology_parsed = None
    if implicit_geology_json:
        try:
            from schemas.geophysics_schema import ImplicitGeologyParams as _GeoParams
            _implicit_geology_parsed = _GeoParams(**json.loads(implicit_geology_json))
        except Exception as _e:
            _corrections_warnings.append(
                f"implicit_geology_json inválido (IGNORADO; la inversión corre sin "
                f"prior geológico): {_e}")

    # FASE 20 — Sondajes (anclaje grav+sondajes). Lista de BoreholeInterval.
    _boreholes_parsed = None
    if boreholes_json:
        try:
            from schemas.geophysics_schema import BoreholeInterval as _BHInterval
            _bh_raw = json.loads(boreholes_json)
            if isinstance(_bh_raw, dict):  # tolera {"boreholes":[...]} o {"intervals":[...]}
                _bh_raw = _bh_raw.get("boreholes") or _bh_raw.get("intervals") or []
            _boreholes_parsed = [_BHInterval(**_b) for _b in _bh_raw]
            if _boreholes_parsed:
                _corrections_warnings.append(
                    f"[Fase 20] Anclaje por sondajes activo: {len(_boreholes_parsed)} "
                    "intervalos (combo grav+sondajes)."
                )
        except Exception as _e:
            _corrections_warnings.append(f"boreholes_json inválido (ignorado): {_e}")

    est.effective_observations = _effective_observations
    est.sensor_elevs_v1 = _sensor_elevs_v1
    est.noise_floor_from_unc = _noise_floor_from_unc
    est.magnetic_nt = _magnetic_nt
    est.pgi_params_parsed = _pgi_params_parsed
    est.remanence_parsed = _remanence_parsed
    est.boreholes_parsed = _boreholes_parsed
    est.implicit_geology_parsed = _implicit_geology_parsed


def _invert_ejecutar(est: _EstadoInvert, corrida: CorridaCfg, malla: MallaCfg,
                     reg: RegularizacionCfg, anclas: AnclajeCfg,
                     pesos: PesosDatoCfg, georef: GeorefCfg, mag: MagneticaCfg):
    """Construye el input validado y corre la inversión (única llamada al motor)."""
    project_id = corrida.project_id
    run_id = corrida.run_id
    nir = corrida.nir
    fe = corrida.fe
    region = corrida.region
    lat = georef.lat
    lon = georef.lon
    lambda_mag = reg.lambda_mag
    alpha_spatial = reg.alpha_spatial
    regularization_norm = reg.regularization_norm
    compact_max_irls = reg.compact_max_irls
    compact_eps = reg.compact_eps
    padding_kappa = anclas.padding_kappa
    anchor_kappa = anclas.anchor_kappa
    auto_kappa = anclas.auto_kappa
    density_min = pesos.density_min
    density_max = pesos.density_max
    gravimeter_type = pesos.gravimeter_type
    inclination_deg = mag.inclination_deg
    declination_deg = mag.declination_deg
    field_intensity_nt = mag.field_intensity_nt
    susc_min = mag.susc_min
    susc_max = mag.susc_max
    effective_depth = est.effective_depth
    effective_nx = est.effective_nx
    effective_ny = est.effective_ny
    effective_nz = est.effective_nz
    effective_block_size = est.effective_block_size
    effective_cutoff_radius = est.effective_cutoff_radius
    _effective_observations = est.effective_observations
    auto_params_metadata = est.auto_params_metadata
    _sensor_elevs_v1 = est.sensor_elevs_v1
    _noise_floor_from_unc = est.noise_floor_from_unc
    _magnetic_nt = est.magnetic_nt
    _pgi_params_parsed = est.pgi_params_parsed
    _remanence_parsed = est.remanence_parsed
    _boreholes_parsed = est.boreholes_parsed
    _implicit_geology_parsed = est.implicit_geology_parsed
    spatial_readiness_invert = est.spatial_readiness_invert

    try:
        invert_input = GeophysicsInvertInput(
            project_id=project_id,
            run_id=run_id,
            depth=effective_depth,
            nir=nir,
            fe=fe,
            region=region,
            lat=lat,
            lon=lon,
            nx=effective_nx,
            ny=effective_ny,
            nz=effective_nz,
            block_size=effective_block_size,
            cutoff_radius=effective_cutoff_radius,
            lambda_mag=lambda_mag,
            alpha_spatial=alpha_spatial,
            observations=_effective_observations,  # H-B2: corrected observations
            enable_focusing=True,
            auto_params_metadata=auto_params_metadata,
            density_min=density_min,
            density_max=density_max,
            sensor_elevations_masl=_sensor_elevs_v1,
            noise_floor_mgal=_noise_floor_from_unc,
            gravimeter_type=gravimeter_type,
            # Magnetometría (Fase 9A): activa el motor de susceptibilidad.
            magnetic_nt=_magnetic_nt,
            inclination_deg=inclination_deg,
            declination_deg=declination_deg,
            field_intensity_nt=field_intensity_nt,
            susc_min=susc_min,
            susc_max=susc_max,
            # Fase 7B — Advanced params
            pgi_params=_pgi_params_parsed,
            remanence=_remanence_parsed,
            # FASE 14 — prior geológico implícito (None = sin prior, byte-idéntico).
            implicit_geology=_implicit_geology_parsed,
            # Fase 20 — Sondajes que anclan la inversión (None = sin anclaje)
            boreholes=_boreholes_parsed,
            # FASE 16 — Kappas configurables
            padding_kappa=padding_kappa,
            anchor_kappa=anchor_kappa,
            auto_kappa=auto_kappa,
            # FASE 24B — Norma de regularización (default L2 en flujo directo).
            regularization_norm=regularization_norm,
            compact_max_irls=compact_max_irls,
            compact_eps=compact_eps,
            # compute_uncertainty queda OFF a propósito: a la λ que selecciona
            # Morozov en surveys subdeterminados (LdM: 191 estaciones), la
            # covarianza posterior está mal condicionada y σ explota (mediana
            # ~41, máx ~1e13 t/m³ — no físico). Activarla mostraría basura.
            # Requiere fijar un operating point estable (λ mayor) o regularizar
            # la UQ; es decisión de física, no un wiring. Ver nota al usuario.
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid geophysics inversion input generated from gravity import.",
                "errors": exc.errors(),
            },
        ) from exc

    # Crear run_dir inmediatamente para que el SSE stream pueda conectar
    # antes de que run_geophysics_inversion escriba el primer heartbeat.
    if project_id and run_id:
        try:
            update_run_status(
                project_id=project_id,
                run_id=run_id,
                status="queued",
                progress=0.0,
                stage="queued",
                message="Inversión en cola.",
            )
        except Exception:
            pass  # No abortar si falla la persistencia del estado

    try:
        inversion_result = run_geophysics_inversion(invert_input)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "GEOPHYSICS_INPUT_VALIDATION",
                "message": str(exc),
                "spatial_readiness": model_to_dict(spatial_readiness_invert),
                "required_action": "Corregir parámetros de entrada antes de ejecutar la inversión.",
            },
        ) from exc
    except Exception as exc:
        import traceback as _tb
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INVERSION_RUNTIME_ERROR",
                "message": str(exc),
                "type": type(exc).__name__,
                "traceback": _tb.format_exc()[-2000:],
            },
        ) from exc

    est.inversion_result = inversion_result


def _invert_georef_footprint(est: _EstadoInvert):
    """Clasifica la georreferenciación y calcula el footprint (pyproj o aproximado)."""
    import_result = est.import_result
    _effective_utm = est.effective_utm
    lat_value = est.lat_value
    lon_value = est.lon_value

    # --- Georef computation ---
    # lat_value, lon_value, project_meta_warning, spatial_readiness_invert
    # already computed before gate (R3.5-D); reused here unchanged.
    # R3.5-K: use effective_utm (form param priority, CSV-detected fallback)
    georef_r2 = _classify_georef_full(
        import_result.coordinate_transform, lat_value, lon_value,
        utm_zone_form=_effective_utm,
    )
    georef_confidence = georef_r2["confidence"]
    georef_type = georef_r2["type"]
    utm_zone_val = georef_r2["utm_zone"]
    georef_warnings = georef_r2["warnings"]
    utm_hemisphere_val = georef_r2["utm_hemisphere"]
    epsg_code_val = georef_r2["epsg_code"]
    input_crs_val = georef_r2["input_crs"]
    crs_source_val = georef_r2["crs_source"]
    crs_confidence_val = georef_r2["crs_confidence"]

    ct = import_result.coordinate_transform

    # R2.3 — Compute footprint: try real pyproj UTM bbox first, then equirectangular fallback
    _pyproj_used = False
    footprint_dict = _build_missing_footprint()  # safe default

    if (
        georef_type == "csv_utm"
        and utm_zone_val is not None
        and epsg_code_val is not None
        and ct is not None
        and ct.x_min_raw is not None
        and ct.x_max_raw is not None
        and ct.z_min_raw is not None
        and ct.z_max_raw is not None
    ):
        try:
            footprint_dict = compute_utm_footprint_with_pyproj(
                min_easting=float(ct.x_min_raw),
                max_easting=float(ct.x_max_raw),
                min_northing=float(ct.z_min_raw),
                max_northing=float(ct.z_max_raw),
                epsg_code=epsg_code_val,
                crs_source=crs_source_val,
            )
            footprint_dict["utm_hemisphere"] = utm_hemisphere_val
            footprint_dict["crs_confidence"] = crs_confidence_val

            # Remove obsolete "pyproj pendiente" warning now that pyproj computed the footprint
            georef_warnings = [
                w for w in georef_warnings
                if "queda pendiente" not in w and "R2.2" not in w
            ]

            # Validate anchor lat/lon against pyproj-derived center
            if lat_value is not None and lon_value is not None:
                fp_lat = footprint_dict["center_lat"]
                fp_lon = footprint_dict["center_lon"]
                dist_km = approx_dist_km(lat_value, lon_value, fp_lat, fp_lon)
                if dist_km > 5.0:
                    georef_warnings.append(
                        f"El centro transformado desde UTM ({fp_lat:.4f}°, {fp_lon:.4f}°) "
                        f"no coincide con el lat/lon declarado ({lat_value:.4f}°, "
                        f"{lon_value:.4f}°). Diferencia: {dist_km:.1f} km. "
                        "Verificar zona UTM o anclaje."
                    )
                    georef_confidence = "MEDIUM"
                else:
                    georef_confidence = "HIGH"

            footprint_dict["confidence"] = georef_confidence
            footprint_dict["warnings"] = list(georef_warnings)
            _pyproj_used = True
        except Exception:
            # pyproj unavailable or failed — fall through to equirectangular
            pass

    if not _pyproj_used:
        if (
            lat_value is not None
            and lon_value is not None
            and ct is not None
            and ct.x_extent_m > 0
            and ct.z_extent_m > 0
        ):
            footprint_dict = compute_footprint_from_center(
                lat_value, lon_value, ct.x_extent_m, ct.z_extent_m,
                source=georef_type,
                confidence=georef_confidence,
                warnings=list(georef_warnings),
                utm_zone=utm_zone_val,
            )
            footprint_dict["utm_hemisphere"] = utm_hemisphere_val
            footprint_dict["epsg_code"] = epsg_code_val
            footprint_dict["crs_source"] = crs_source_val
            footprint_dict["crs_confidence"] = crs_confidence_val
            if georef_type == "csv_utm" and utm_zone_val is not None:
                footprint_dict["warnings"].append(
                    "Zona UTM declarada, pero no fue posible construir footprint UTM real. "
                    "Se usó aproximación por centro/extensión."
                )
        else:
            footprint_dict = _build_missing_footprint()
            footprint_dict["utm_hemisphere"] = utm_hemisphere_val
            footprint_dict["epsg_code"] = epsg_code_val
            footprint_dict["crs_source"] = crs_source_val
            footprint_dict["crs_confidence"] = crs_confidence_val

    est.georef_confidence = georef_confidence
    est.georef_type = georef_type
    est.utm_zone_val = utm_zone_val
    est.georef_warnings = georef_warnings
    est.utm_hemisphere_val = utm_hemisphere_val
    est.epsg_code_val = epsg_code_val
    est.input_crs_val = input_crs_val
    est.crs_source_val = crs_source_val
    est.crs_confidence_val = crs_confidence_val
    est.footprint_dict = footprint_dict


def _invert_persistir(est: _EstadoInvert, corrida: CorridaCfg, file, temp_path):
    """Guarda CSV fuente, metadatos y `project_meta.json`; luego enriquece (R3)."""
    project_id = corrida.project_id
    run_id = corrida.run_id
    import_result = est.import_result
    auto_grid = est.auto_grid
    legacy_frontend_params = est.legacy_frontend_params
    spatial_readiness_invert = est.spatial_readiness_invert
    lat_value = est.lat_value
    lon_value = est.lon_value
    project_meta_warning = est.project_meta_warning
    georef_confidence = est.georef_confidence
    georef_type = est.georef_type
    utm_zone_val = est.utm_zone_val
    utm_hemisphere_val = est.utm_hemisphere_val
    epsg_code_val = est.epsg_code_val
    input_crs_val = est.input_crs_val
    crs_source_val = est.crs_source_val
    crs_confidence_val = est.crs_confidence_val
    footprint_dict = est.footprint_dict

    # --- Persistence ---
    persisted = False
    persistence_warning: Optional[str] = None
    source_csv_path_str: Optional[str] = None
    metadata_path_str: Optional[str] = None

    if project_id and run_id:
        try:
            source_csv_path = get_run_source_gravity_csv_path(project_id, run_id)
            metadata_path = get_run_gravity_import_metadata_path(project_id, run_id)
            source_csv_path.parent.mkdir(parents=True, exist_ok=True)

            # Always update project_meta.json — load existing or start fresh
            project_meta_path = get_project_meta_path(project_id)
            now_utc = datetime.now(timezone.utc).isoformat()

            if project_meta_path.exists():
                try:
                    with open(project_meta_path, "r", encoding="utf-8") as f:
                        existing_meta: dict = json.load(f)
                except Exception:
                    existing_meta = {}
            else:
                existing_meta = {}

            updated_meta: dict = dict(existing_meta)
            updated_meta["project_id"] = project_id
            if "crs" not in updated_meta:
                updated_meta["crs"] = "EPSG:4326"
            updated_meta["updated_at"] = now_utc
            updated_meta["source"] = "csv_import"
            # Always overwrite georef fields with current run result
            updated_meta["georef_confidence"] = georef_confidence
            updated_meta["georef_type"] = georef_type
            updated_meta["utm_zone"] = utm_zone_val
            updated_meta["footprint"] = footprint_dict
            # R2 CRS fields
            updated_meta["input_crs"] = input_crs_val
            updated_meta["epsg_code"] = epsg_code_val
            updated_meta["crs_source"] = crs_source_val
            updated_meta["utm_hemisphere"] = utm_hemisphere_val
            updated_meta["horizontal_datum"] = "WGS84" if epsg_code_val else None
            updated_meta["crs_contract"] = {
                "input_crs": input_crs_val,
                "output_crs": "EPSG:4326",
                "horizontal_datum": "WGS84" if epsg_code_val else None,
                "vertical_datum": None,
                "utm_zone": utm_zone_val,
                "utm_hemisphere": utm_hemisphere_val,
                "epsg_code": epsg_code_val,
                "crs_source": crs_source_val,
                "crs_confidence": crs_confidence_val,
            }
            # R3.5-C — persist spatial readiness in project_meta
            updated_meta["spatial_readiness"] = model_to_dict(spatial_readiness_invert)

            if lat_value is not None:
                updated_meta["latitude"] = lat_value
            elif "latitude" not in updated_meta:
                updated_meta["latitude"] = None

            if lon_value is not None:
                updated_meta["longitude"] = lon_value
            elif "longitude" not in updated_meta:
                updated_meta["longitude"] = None

            if not updated_meta.get("created_at"):
                updated_meta["created_at"] = now_utc

            save_project_meta(project_id, updated_meta)

            shutil.copyfile(temp_path, source_csv_path)

            metadata_content = {
                "schema_version": "TerraQuantum Gravity CSV v1",
                "original_filename": file.filename,
                "stored_source_file": "source_gravity.csv",
                "project_id": project_id,
                "run_id": run_id,
                "lat": lat_value,
                "lon": lon_value,
                "latitude": lat_value,
                "longitude": lon_value,
                "crs": "EPSG:4326",
                "geo_source": "csv_import_ui",
                "geo_warning": project_meta_warning,
                "stored_at_utc": datetime.now(timezone.utc).isoformat(),
                "import_metadata": model_to_dict(import_result.import_metadata),
                "csv_analysis": model_to_dict(import_result.csv_analysis) if import_result.csv_analysis else None,
                "coordinate_transform": model_to_dict(import_result.coordinate_transform) if import_result.coordinate_transform else None,
                "auto_grid": model_to_dict(auto_grid),
                "legacy_frontend_params": legacy_frontend_params,
                "warnings": import_result.warnings,
                "errors": import_result.errors,
                "spatial_readiness": model_to_dict(spatial_readiness_invert),
            }

            with open(metadata_path, "w", encoding="utf-8") as meta_f:
                json.dump(metadata_content, meta_f, indent=2, ensure_ascii=False)

            persisted = True
            source_csv_path_str = str(source_csv_path)
            metadata_path_str = str(metadata_path)
        except Exception as e:
            persistence_warning = f"Failed to persist artifacts: {str(e)}"
    else:
        persistence_warning = "project_id/run_id missing; gravity import artifacts were not persisted."
        project_meta_warning = "project_id/run_id missing; project_meta.json was not created."

    # --- R3 post-inversion enrichment ---
    r3_enrichment_result: dict = {
        "attempted": False,
        "terrain_persisted": False,
        "enrichment_attempted": False,
        "enrichment_status": None,
        "has_elevation_data": False,
        "warnings": [],
    }
    if project_id and run_id:
        r3_enrichment_result = _run_r3_post_inversion_enrichment(
            project_id, run_id, georef_confidence
        )

    est.persisted = persisted
    est.persistence_warning = persistence_warning
    est.source_csv_path_str = source_csv_path_str
    est.metadata_path_str = metadata_path_str
    est.project_meta_warning = project_meta_warning
    est.r3_enrichment_result = r3_enrichment_result


def _invert_respuesta(est: _EstadoInvert, corrida: CorridaCfg, malla: MallaCfg,
                      georef: GeorefCfg):
    """Avisos de degradación honestos + el JSON que ve el frontend."""
    project_id = corrida.project_id
    run_id = corrida.run_id
    nx = malla.nx
    ny = malla.ny
    nz = malla.nz
    block_size = malla.block_size
    acknowledge_regional_scale = georef.acknowledge_regional_scale
    import_result = est.import_result
    inversion_result = est.inversion_result
    x_extent = est.x_extent
    z_extent = est.z_extent
    _corrections_warnings = est.corrections_warnings
    georef_warnings = est.georef_warnings
    r3_enrichment_result = est.r3_enrichment_result
    _utm_zone_mismatch_warning = est.utm_zone_mismatch_warning
    project_meta_warning = est.project_meta_warning
    legacy_frontend_params = est.legacy_frontend_params
    spatial_readiness_invert = est.spatial_readiness_invert
    regional_preflight = est.regional_preflight
    georef_confidence = est.georef_confidence
    georef_type = est.georef_type
    utm_zone_val = est.utm_zone_val
    utm_hemisphere_val = est.utm_hemisphere_val
    epsg_code_val = est.epsg_code_val
    input_crs_val = est.input_crs_val
    crs_source_val = est.crs_source_val
    crs_confidence_val = est.crs_confidence_val
    footprint_dict = est.footprint_dict
    auto_grid = est.auto_grid
    persisted = est.persisted
    source_csv_path_str = est.source_csv_path_str
    metadata_path_str = est.metadata_path_str
    persistence_warning = est.persistence_warning
    effective_nx = est.effective_nx
    effective_ny = est.effective_ny
    effective_nz = est.effective_nz
    effective_block_size = est.effective_block_size
    effective_depth = est.effective_depth
    effective_cutoff_radius = est.effective_cutoff_radius

    regional_warnings: list[str] = []
    x_span_km = x_extent / 1000.0
    z_span_km = z_extent / 1000.0
    if x_span_km > 10 or z_span_km > 10:
        regional_warnings.append(
            f"Dataset regional detectado ({x_span_km:.0f}km × {z_span_km:.0f}km). "
            "La inversión modela distribución de densidades a escala regional. "
            "El pit design conceptual opera sobre una subgrilla normalizada."
        )
    # ── Guard de degradación: el 3D no debe verse "presentable" en silencio ──
    # cuando el ajuste es malo o la mayoría de la malla no fue sensada.
    _degradation_warnings: list[str] = []
    try:
        _mis_g = (inversion_result or {}).get("misfit_error_percent")
        if _mis_g is not None and float(_mis_g) > 50.0:
            _degradation_warnings.append(
                f"MODELO DEGRADADO: misfit {float(_mis_g):.0f}% — el modelo explica menos de "
                "la mitad de la señal observada. NO usar para interpretación. Revisar "
                "cutoff_radius, lambda, bounds de densidad y correcciones."
            )
        _r05_g = ((inversion_result or {}).get("report") or {}).get("r05_geometry_audit") or {}
        _obs_ratio_g = _r05_g.get("observable_ratio")
        if _obs_ratio_g is not None and float(_obs_ratio_g) < 0.5:
            _degradation_warnings.append(
                f"COBERTURA INSUFICIENTE: solo {float(_obs_ratio_g) * 100:.0f}% de los vóxeles "
                "activos es sensado por las estaciones (cutoff_radius demasiado pequeño "
                "para el espaciamiento del survey)."
            )
    except Exception:
        pass

    all_warnings = (
        import_result.warnings
        + regional_warnings
        + georef_warnings
        + r3_enrichment_result.get("warnings", [])
        + _corrections_warnings
        + _degradation_warnings
    )
    if _utm_zone_mismatch_warning:
        all_warnings.append(_utm_zone_mismatch_warning)
    if project_meta_warning:
        all_warnings.append(project_meta_warning)

    # Strip voxels from the HTTP response — they are already persisted to parquet
    # and the frontend loads them via the /block-model API.
    _inversion_dict = model_to_dict(inversion_result) if inversion_result else {}
    if isinstance(_inversion_dict, dict) and "voxels" in _inversion_dict:
        _inversion_dict.pop("voxels", None)

    return sanitize_nan({
        "status": "done",
        "stage": "inversion",
        "project_id": project_id,
        "run_id": run_id,
        "r3_enrichment": r3_enrichment_result,
        "spatial_readiness": model_to_dict(spatial_readiness_invert),
        "regional_scale_preflight": model_to_dict(regional_preflight),
        "acknowledge_regional_scale": acknowledge_regional_scale,
        "georef": {
            "confidence": georef_confidence,
            "type": georef_type,
            "utm_zone": utm_zone_val,
            "utm_hemisphere": utm_hemisphere_val,
            "epsg_code": epsg_code_val,
            "input_crs": input_crs_val,
            "crs_source": crs_source_val,
            "crs_confidence": crs_confidence_val,
            "warnings": georef_warnings,
            "footprint": footprint_dict,
        },
        "importMetadata": model_to_dict(import_result.import_metadata),
        "csv_analysis": model_to_dict(import_result.csv_analysis) if import_result.csv_analysis else None,
        "coordinate_transform": model_to_dict(import_result.coordinate_transform) if import_result.coordinate_transform else None,
        "auto_grid": model_to_dict(auto_grid),
        "legacy_frontend_params": legacy_frontend_params,
        "warnings": all_warnings,
        "errors": [],
        "inversionResult": _inversion_dict,
        "importPersistence": {
            "persisted": persisted,
            "sourceGravityPath": source_csv_path_str,
            "metadataPath": metadata_path_str,
            "warning": persistence_warning,
            "projectMetaWarning": project_meta_warning
        },
        "gridAutoAdapt": {
            "applied": True,
            "reason": "auto_grid_v0_1",
            "frontendRequested": {
                "nx": nx,
                "ny": ny,
                "nz": nz,
                "block_size": block_size
            },
            "effectiveUsed": {
                "nx": effective_nx,
                "ny": effective_ny,
                "nz": effective_nz,
                "block_size": effective_block_size,
                "depth": effective_depth,
                "cutoff_radius": effective_cutoff_radius
            },
            "totalVoxels": effective_nx * effective_ny * effective_nz,
            "extentXm": x_extent,
            "extentZm": z_extent
        }
    })


@router.post("/invert", response_model=GravityImportInvertResponse)
@limiter.limit("10/minute")
async def invert_gravity_csv(
    request: Request,
    file: UploadFile = File(...),
    corrida: CorridaCfg = Depends(_cfg_corrida),
    malla: MallaCfg = Depends(_cfg_malla),
    reg: RegularizacionCfg = Depends(_cfg_regularizacion),
    anclas: AnclajeCfg = Depends(_cfg_anclaje),
    pesos: PesosDatoCfg = Depends(_cfg_pesos_dato),
    georef: GeorefCfg = Depends(_cfg_georef),
    mag: MagneticaCfg = Depends(_cfg_magnetica),
):
    """Importa un CSV gravimétrico/magnético, invierte y devuelve el reporte.

    FASE 8: validar, delegar, serializar. Los 41 `Form(...)` siguen viajando
    planos por el cable (los declaran las dependencias `_cfg_*`); lo que cambió
    es que aquí ya no se leen de a uno.
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must end with .csv")
    if mag.data_type not in ("gravity", "magnetic"):
        raise HTTPException(
            status_code=422,
            detail=f"data_type inválido: '{mag.data_type}'. Use 'gravity' o 'magnetic'.",
        )
    if pesos.gravimeter_type not in _VALID_GRAVIMETERS:
        raise HTTPException(
            status_code=422,
            detail=f"gravimeter_type inválido: '{pesos.gravimeter_type}'. "
                   f"Valores soportados: {sorted(_VALID_GRAVIMETERS)}.",
        )

    est = _EstadoInvert(is_magnetic_run=(mag.data_type == "magnetic"))
    temp_filename = f"{uuid.uuid4()}.csv"
    temp_path = Path(TMP_DIR) / temp_filename

    try:
        respuesta_error = await _invert_importar_y_validar(
            file, temp_path, corrida, georef, est)
        if respuesta_error is not None:
            return respuesta_error

        _invert_corregir_gravedad(est)
        _invert_resolver_grilla(est, malla, reg, georef)
        _invert_extras_y_parseos(est, corrida, georef, anclas)
        _invert_ejecutar(est, corrida, malla, reg, anclas, pesos, georef, mag)
        _invert_georef_footprint(est)
        _invert_persistir(est, corrida, file, temp_path)
        return _invert_respuesta(est, corrida, malla, georef)
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass


