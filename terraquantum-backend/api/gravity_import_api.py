import math
import uuid
import os
import shutil
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form, Request
from pydantic import ValidationError
from typing import Optional

from core.config import CSV_MAX_BYTES, TMP_DIR
from core.rate_limit import limiter
from core.block_model_store import (
    get_project_meta_path,
    get_run_source_gravity_csv_path,
    get_run_gravity_import_metadata_path,
    get_terrain_metadata_path,
    get_terrain_dem_matrix_path,
    save_project_meta,
)
from services.satellite_service import get_terrain_data
from services.elevation_enrichment_service import enrich_block_model_with_elevation
from core.geo_utils import compute_footprint_from_center
from schemas.geophysics_schema import GeophysicsInvertInput
from schemas.gravity_import_schema import SpatialReadiness, RegionalScalePreflight
from services.gravity_import_service import import_gravity_csv_v1
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


def _sanitize_nan(obj):
    """Reemplaza float NaN/Inf por None recursivamente para emitir JSON válido."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# R3.5-K — UTM zone extraction helpers
# ---------------------------------------------------------------------------

def _safe_get(obj, key: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_detected_utm_zone(import_result) -> "str | None":
    """
    Extract utm_zone detected in CSV from import_result, trying three paths safely.
    Returns stripped non-empty string or None.
    """
    # 1. coordinate_transform.utm_zone (most authoritative — set by _utm_to_local_meters)
    ct = _safe_get(import_result, "coordinate_transform")
    v = _safe_get(ct, "utm_zone")
    if v and str(v).strip():
        return str(v).strip()

    # 2. csv_analysis.coordinate_system.utm_zone
    ca = _safe_get(import_result, "csv_analysis")
    cs = _safe_get(ca, "coordinate_system")
    v = _safe_get(cs, "utm_zone")
    if v and str(v).strip():
        return str(v).strip()

    # 3. import_metadata.coordinate_transform.utm_zone
    im = _safe_get(import_result, "import_metadata")
    ct2 = _safe_get(im, "coordinate_transform")
    v = _safe_get(ct2, "utm_zone")
    if v and str(v).strip():
        return str(v).strip()

    return None


def _effective_utm_zone(form_utm_zone: "str | None", import_result) -> "str | None":
    """
    Return effective UTM zone: form param has priority; CSV-detected zone is fallback.
    """
    if form_utm_zone and form_utm_zone.strip():
        return form_utm_zone.strip()
    return _extract_detected_utm_zone(import_result)


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

def model_to_dict(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _sanitize_nan(obj):
    """Recursively replace NaN/Inf floats with None so json.dumps never crashes."""
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float) and (obj != obj or obj == float("inf") or obj == float("-inf")):
        return None
    return obj


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

    if level == "LOCAL_UNANCHORED" and not acknowledge_spatial_risk:
        _raise(
            "Coordenadas locales sin anclaje geográfico. "
            "El modelo resultante no tendrá ubicación absoluta en el mapa.",
            required_acknowledgement="ACK_LOCAL_CONCEPTUAL_ONLY",
            required_action="Confirmar acknowledge_spatial_risk=true para continuar en modo conceptual.",
        )

    if level == "LOCAL_ANCHORED_CENTER" and not acknowledge_spatial_risk:
        _raise(
            "Anclaje solo en el centro; sin coordenadas por estación. "
            "La georef del modelo será imprecisa.",
            required_acknowledgement="ACK_LOCAL_ANCHORED_CENTER",
            required_action="Confirmar acknowledge_spatial_risk=true para continuar.",
        )

    if level == "UTM_NO_ZONE" and not acknowledge_spatial_risk:
        _raise(
            "Sistema UTM detectado pero zona desconocida. "
            "La conversión a coordenadas geográficas puede ser incorrecta.",
            required_acknowledgement="ACK_UTM_NO_ZONE",
            required_action="Especificar utm_zone en el formulario o confirmar acknowledge_spatial_risk=true.",
        )

    # UTM_WITH_ZONE, GEOGRAPHIC_COORDS, PROFESSIONAL_SURVEY — suficiencia completa, sin bloqueo.


@router.post("/preview")
async def preview_gravity_csv(
    request: Request,
    file: UploadFile = File(...),
    strict: bool = Query(True),
    allow_g_raw: bool = Query(False),
    preview_limit: int = Query(20)
):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must end with .csv")

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

        result = import_gravity_csv_v1(temp_path, strict=strict, allow_g_raw=allow_g_raw)

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

        return _sanitize_nan({
            "status": result.status,
            "previewCount": len(observations_preview),
            "totalObservations": len(result.observations),
            "observationsPreview": observations_list,
            "importMetadata": model_to_dict(result.import_metadata),
            "csv_analysis": model_to_dict(result.csv_analysis) if result.csv_analysis else None,
            "coordinate_transform": model_to_dict(result.coordinate_transform) if result.coordinate_transform else None,
            "auto_grid": model_to_dict(result.auto_grid) if result.auto_grid else None,
            "georef_preview": georef_preview,
            "spatial_readiness": model_to_dict(spatial_readiness_preview),
            "regional_scale_preflight": model_to_dict(regional_scale_preflight),
            "warnings": result.warnings,
            "errors": result.errors
        })
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass

@router.post("/invert")
@limiter.limit("10/minute")
async def invert_gravity_csv(
    request: Request,
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    run_id: Optional[str] = Form(None),
    depth: int = Form(...),
    nir: int = Form(...),
    fe: int = Form(...),
    region: str = Form(...),
    lat: str = Form(...),
    lon: str = Form(...),
    nx: int = Form(...),
    ny: int = Form(...),
    nz: int = Form(...),
    block_size: int = Form(...),
    cutoff_radius: float = Form(...),
    lambda_mag: float = Form(...),
    alpha_spatial: float = Form(...),
    strict: bool = Form(True),
    allow_g_raw: bool = Form(False),
    utm_zone: Optional[str] = Form(None),
    acknowledge_spatial_risk: bool = Form(False),
    acknowledge_regional_scale: bool = Form(False),
):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must end with .csv")

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

        import_result = import_gravity_csv_v1(temp_path, strict=strict, allow_g_raw=allow_g_raw)

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

        # R3.7-C — Regional scale preflight gate
        regional_preflight = build_preflight_from_import_result(import_result)

        if regional_preflight.scale_class == "TOO_LARGE_SINGLE_INVERSION":
            _raise_regional_scale_gate(
                regional_preflight,
                message=(
                    "El dataset cubre una escala regional o genera una grilla mayor al límite "
                    "de inversión única. Use un recorte/subset o tileado."
                ),
                required_action=(
                    "Crear un subset espacial o usar un flujo de tileado antes de ejecutar la inversión."
                ),
            )
        elif (
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

        xs = [obs.x_m for obs in import_result.observations]
        zs = [obs.z_m for obs in import_result.observations]
        auto_grid = import_result.auto_grid
        if auto_grid is None and import_result.csv_analysis:
            auto_grid = import_result.csv_analysis.auto_grid
        if auto_grid is None:
            raise HTTPException(status_code=500, detail="auto_grid no disponible tras importar CSV.")

        effective_nx = auto_grid.nx
        effective_ny = auto_grid.ny
        effective_nz = auto_grid.nz
        effective_block_size = int(math.ceil(auto_grid.block_size_m))
        effective_depth = int(math.ceil(auto_grid.depth_m))
        effective_cutoff_radius = auto_grid.cutoff_radius_m

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
                observations=import_result.observations,
                enable_focusing=True,
                auto_params_metadata=auto_params_metadata,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Invalid geophysics inversion input generated from gravity import.",
                    "errors": exc.errors(),
                },
            ) from exc

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

        regional_warnings: list[str] = []
        x_span_km = x_extent / 1000.0
        z_span_km = z_extent / 1000.0
        if x_span_km > 10 or z_span_km > 10:
            regional_warnings.append(
                f"Dataset regional detectado ({x_span_km:.0f}km × {z_span_km:.0f}km). "
                "La inversión modela distribución de densidades a escala regional. "
                "El pit design conceptual opera sobre una subgrilla normalizada."
            )
        all_warnings = (
            import_result.warnings
            + regional_warnings
            + georef_warnings
            + r3_enrichment_result.get("warnings", [])
        )
        if _utm_zone_mismatch_warning:
            all_warnings.append(_utm_zone_mismatch_warning)
        if project_meta_warning:
            all_warnings.append(project_meta_warning)

        # Strip voxels from the HTTP response — they are already persisted to parquet
        # and the frontend loads them via the /block-model API. Sending 100k+ voxels
        # as JSON would produce a 50-100 MB payload that kills the Next.js proxy.
        _inversion_dict = (
            model_to_dict(inversion_result)
            if hasattr(inversion_result, "model_dump") or hasattr(inversion_result, "dict")
            else inversion_result
        )
        if isinstance(_inversion_dict, dict):
            _inversion_dict = {k: v for k, v in _inversion_dict.items() if k != "voxels"}

        return _sanitize_nan({
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
                "totalVoxels": auto_grid.voxel_count,
                "extentXm": x_extent,
                "extentZm": z_extent
            }
        })
    finally:
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass
