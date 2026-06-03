"""
R3.5-B — Spatial Readiness Service

Classifies the spatial sufficiency of a CSV import for 3D inversion.
Pure classification logic — no side effects, no API calls, no DB writes.
Does NOT connect to /invert or /preview yet (R3.5-C does that).
"""
from schemas.gravity_import_schema import (
    SPATIAL_LEVEL_MAX_FAVORABILITY,
    SPATIAL_LEVEL_MAX_PRIORITY,
    SPATIAL_LEVEL_RANKS,
    SpatialReadiness,
)


# ---------------------------------------------------------------------------
# Internal level builders
# ---------------------------------------------------------------------------

def _build_no_spatial_data(missing_fields: list[str] | None = None) -> SpatialReadiness:
    return SpatialReadiness(
        level="NO_SPATIAL_DATA",
        level_rank=SPATIAL_LEVEL_RANKS["NO_SPATIAL_DATA"],
        can_run_3d_inversion=False,
        can_run_local_conceptual_inversion=False,
        can_use_dem=False,
        can_compute_voxel_masl=False,
        can_compute_voxel_latlon=False,
        requires_user_acknowledgement=False,
        required_acknowledgement=None,
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["NO_SPATIAL_DATA"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["NO_SPATIAL_DATA"],
        missing_fields=missing_fields or ["station_coordinates"],
        warnings=[
            "El CSV no contiene coordenadas geográficas válidas por estación.",
            "Proporcione coordenadas UTM/lat-lon o un punto de anclaje para habilitar la inversión.",
        ],
        allowed_outputs=[
            "relative_model_visualization",
            "internal_quality_report",
            "anomaly_gradient_analysis",
        ],
        blocked_outputs=[
            "3d_inversion",
            "dem_coregistration",
            "voxel_masl",
            "voxel_latlon",
            "geographic_report",
        ],
        rationale=(
            "Sin coordenadas espaciales por estación, el modelo no puede ubicarse "
            "geográficamente. Solo se permite análisis interno de gradientes y "
            "visualización en espacio relativo."
        ),
    )


def _build_local_unanchored() -> SpatialReadiness:
    return SpatialReadiness(
        level="LOCAL_UNANCHORED",
        level_rank=SPATIAL_LEVEL_RANKS["LOCAL_UNANCHORED"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=False,
        can_compute_voxel_masl=False,
        can_compute_voxel_latlon=False,
        requires_user_acknowledgement=False,
        required_acknowledgement=None,
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["LOCAL_UNANCHORED"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["LOCAL_UNANCHORED"],
        missing_fields=[],
        warnings=[
            "Coordenadas locales en metros (x_m/y_m/z_m). La inversión 3D opera en espacio local.",
            "Sin anclaje geográfico: el modelo no tiene ubicación absoluta en el mapa.",
            "Para co-registro DEM y lat/lon por vóxel, proporcione anchor_lat y anchor_lon.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "local_conceptual_inversion",
            "relative_model_visualization",
            "internal_quality_report",
        ],
        blocked_outputs=[
            "dem_coregistration",
            "voxel_masl",
            "voxel_latlon",
        ],
        rationale=(
            "Coordenadas locales en metros sin anclaje geográfico. La inversión 3D es "
            "físicamente válida en espacio local. El modelo no tiene ubicación geográfica "
            "absoluta; proporcionar anchor_lat/lon para georeferenciación."
        ),
    )


def _build_local_anchored_center() -> SpatialReadiness:
    return SpatialReadiness(
        level="LOCAL_ANCHORED_CENTER",
        level_rank=SPATIAL_LEVEL_RANKS["LOCAL_ANCHORED_CENTER"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=True,
        can_compute_voxel_masl=True,
        can_compute_voxel_latlon=False,
        requires_user_acknowledgement=True,
        required_acknowledgement="ACK_LOCAL_ANCHORED_GEOREF",
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["LOCAL_ANCHORED_CENTER"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["LOCAL_ANCHORED_CENTER"],
        missing_fields=[],
        warnings=[
            "Coordenadas locales ancladas a punto central; orientación y escala real no verificadas.",
            "La georeferencia es de baja confianza. No usar para planificación de sondaje sin verificación GPS.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "dem_coregistration",
            "voxel_masl",
            "relative_model_visualization",
            "internal_quality_report",
        ],
        blocked_outputs=["voxel_latlon"],
        rationale=(
            "Coordenadas locales con anclaje al punto central declarado. Inversión 3D "
            "habilitada con georef aproximada. lat/lon por voxel no calculable porque "
            "el anclaje es un punto central, no coordenadas por estación."
        ),
    )


def _build_utm_no_zone() -> SpatialReadiness:
    return SpatialReadiness(
        level="UTM_NO_ZONE",
        level_rank=SPATIAL_LEVEL_RANKS["UTM_NO_ZONE"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=False,
        can_compute_voxel_masl=False,
        can_compute_voxel_latlon=False,
        requires_user_acknowledgement=True,
        required_acknowledgement="ACK_UTM_ZONE_MISSING",
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["UTM_NO_ZONE"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["UTM_NO_ZONE"],
        missing_fields=["utm_zone"],
        warnings=[
            "Coordenadas UTM detectadas pero zona no declarada.",
            "El offset geográfico puede superar 100 km entre zonas posibles.",
            "Declare utm_zone (ej: '19S') para habilitar co-registro DEM y lat/lon por voxel.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "relative_model_visualization",
            "anomaly_analysis",
            "internal_quality_report",
        ],
        blocked_outputs=["dem_coregistration", "voxel_masl", "voxel_latlon"],
        rationale=(
            "Coordenadas UTM detectadas por rango de valores, pero zona no declarada. "
            "La inversión 3D puede ejecutarse pero el co-registro DEM no es posible "
            "sin zona UTM confirmada. Declare utm_zone para subir a UTM_WITH_ZONE."
        ),
    )


def _build_utm_with_zone() -> SpatialReadiness:
    return SpatialReadiness(
        level="UTM_WITH_ZONE",
        level_rank=SPATIAL_LEVEL_RANKS["UTM_WITH_ZONE"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=True,
        can_compute_voxel_masl=True,
        can_compute_voxel_latlon=True,
        requires_user_acknowledgement=False,
        required_acknowledgement=None,
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["UTM_WITH_ZONE"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["UTM_WITH_ZONE"],
        missing_fields=[],
        warnings=[
            "Coordenadas UTM con zona declarada. Co-registro DEM y lat/lon por voxel habilitados.",
            "Si la zona declarada es incorrecta, el modelo puede tener un desplazamiento geográfico significativo.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "dem_coregistration",
            "voxel_masl",
            "voxel_latlon",
            "geographic_report",
        ],
        blocked_outputs=[],
        rationale=(
            "Coordenadas UTM con zona declarada. Inversión 3D completa, "
            "co-registro DEM, elevación MASL y lat/lon por voxel habilitados. "
            "Favorabilidad con cap leve (85/100) hasta verificación contra referencia absoluta."
        ),
    )


def _build_geographic_coords() -> SpatialReadiness:
    return SpatialReadiness(
        level="GEOGRAPHIC_COORDS",
        level_rank=SPATIAL_LEVEL_RANKS["GEOGRAPHIC_COORDS"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=True,
        can_compute_voxel_masl=True,
        can_compute_voxel_latlon=True,
        requires_user_acknowledgement=False,
        required_acknowledgement=None,
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["GEOGRAPHIC_COORDS"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["GEOGRAPHIC_COORDS"],
        missing_fields=[],
        warnings=[
            "Coordenadas geográficas (lat/lon) detectadas por estación. Todos los módulos habilitados.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "dem_coregistration",
            "voxel_masl",
            "voxel_latlon",
            "geographic_report",
            "full_favorability",
        ],
        blocked_outputs=[],
        rationale=(
            "Coordenadas geográficas (lat/lon) por estación. Inversión 3D completa, "
            "co-registro DEM, elevación MASL y lat/lon por voxel habilitados. "
            "Sin cap de favorabilidad."
        ),
    )


def _build_professional_survey() -> SpatialReadiness:
    return SpatialReadiness(
        level="PROFESSIONAL_SURVEY",
        level_rank=SPATIAL_LEVEL_RANKS["PROFESSIONAL_SURVEY"],
        can_run_3d_inversion=True,
        can_run_local_conceptual_inversion=True,
        can_use_dem=True,
        can_compute_voxel_masl=True,
        can_compute_voxel_latlon=True,
        requires_user_acknowledgement=False,
        required_acknowledgement=None,
        max_priority_class_allowed=SPATIAL_LEVEL_MAX_PRIORITY["PROFESSIONAL_SURVEY"],
        max_favorability_score_allowed=SPATIAL_LEVEL_MAX_FAVORABILITY["PROFESSIONAL_SURVEY"],
        missing_fields=[],
        warnings=[
            "Levantamiento profesional detectado: elevación MASL, incertidumbre, instrumento y correcciones presentes.",
            "Todos los módulos habilitados. La elevación de observación puede usarse como candidato primario para DEM.",
        ],
        allowed_outputs=[
            "3d_inversion",
            "dem_coregistration",
            "voxel_masl",
            "voxel_latlon",
            "geographic_report",
            "full_favorability",
            "observation_elevation_dem",
        ],
        blocked_outputs=[],
        rationale=(
            "Levantamiento geofísico profesional: coordenadas absolutas, elevación MASL, "
            "incertidumbre por observación, instrumento y metadata de correcciones. "
            "Todos los módulos habilitados sin restricción."
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_spatial_readiness(
    *,
    coordinate_system_detected: str | None,
    has_station_coordinates: bool,
    has_latlon_per_station: bool = False,
    has_utm_coordinates: bool = False,
    has_local_coordinates: bool = False,
    has_utm_zone: bool = False,
    has_anchor_latlon: bool = False,
    has_elevation_column: bool = False,
    has_uncertainty_column: bool = False,
    has_instrument_metadata: bool = False,
    has_corrections_metadata: bool = False,
) -> SpatialReadiness:
    """
    Classify spatial readiness from explicit coordinate flags.

    anchor_latlon is NOT the same as latlon_per_station — a central anchor
    point declared by the user does not constitute geographic coordinates
    per station.
    """
    cs = (coordinate_system_detected or "unknown").lower().strip()

    # Resolve effective coordinate type from both detected string and explicit flags
    eff_latlon = has_latlon_per_station or cs == "latlon"
    eff_utm = has_utm_coordinates or cs == "utm"
    eff_local = has_local_coordinates or cs == "local_meters"

    # No station coordinates: NO_SPATIAL_DATA
    if not has_station_coordinates:
        return _build_no_spatial_data(missing_fields=["station_coordinates"])

    # Unknown coordinate system with no explicit type: NO_SPATIAL_DATA
    if cs in ("unknown", "none", "") and not eff_latlon and not eff_utm and not eff_local:
        return _build_no_spatial_data(missing_fields=["station_coordinates", "coordinate_system"])

    # Classify by effective coordinate type (priority: latlon > utm > local)
    if eff_latlon:
        level_name = "GEOGRAPHIC_COORDS"
    elif eff_utm:
        level_name = "UTM_WITH_ZONE" if has_utm_zone else "UTM_NO_ZONE"
    elif eff_local:
        level_name = "LOCAL_ANCHORED_CENTER" if has_anchor_latlon else "LOCAL_UNANCHORED"
    else:
        return _build_no_spatial_data(missing_fields=["station_coordinates"])

    # Professional survey upgrade: requires GEOGRAPHIC_COORDS or UTM_WITH_ZONE + 4 professional fields
    if level_name in ("GEOGRAPHIC_COORDS", "UTM_WITH_ZONE") and (
        has_elevation_column
        and has_uncertainty_column
        and has_instrument_metadata
        and has_corrections_metadata
    ):
        level_name = "PROFESSIONAL_SURVEY"

    _builders = {
        "LOCAL_UNANCHORED": _build_local_unanchored,
        "LOCAL_ANCHORED_CENTER": _build_local_anchored_center,
        "UTM_NO_ZONE": _build_utm_no_zone,
        "UTM_WITH_ZONE": _build_utm_with_zone,
        "GEOGRAPHIC_COORDS": _build_geographic_coords,
        "PROFESSIONAL_SURVEY": _build_professional_survey,
    }
    return _builders[level_name]()


def _get_field(obj: object, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def classify_from_csv_analysis(
    csv_analysis: dict | object,
    *,
    utm_zone: str | None = None,
    anchor_lat: float | None = None,
    anchor_lon: float | None = None,
) -> SpatialReadiness:
    """
    Classify spatial readiness from a CsvAnalysisResult (Pydantic) or equivalent dict.

    utm_zone: zone string declared by user (e.g. "19S") — supplements or overrides
              any zone inferred in the csv analysis.
    anchor_lat/anchor_lon: central anchor provided by user for local coordinates.
                           NOT the same as lat/lon per station.
    """
    obs_count = _get_field(csv_analysis, "observation_count", 0)
    has_station_coordinates = int(obs_count or 0) > 0

    coord_sys_raw = _get_field(csv_analysis, "coordinate_system")
    if coord_sys_raw is None:
        detected = "unknown"
        cs_utm_zone = None
    elif isinstance(coord_sys_raw, dict):
        detected = coord_sys_raw.get("detected", "unknown")
        cs_utm_zone = coord_sys_raw.get("utm_zone")
    else:
        detected = getattr(coord_sys_raw, "detected", "unknown")
        cs_utm_zone = getattr(coord_sys_raw, "utm_zone", None)

    effective_utm_zone = utm_zone or cs_utm_zone

    return classify_spatial_readiness(
        coordinate_system_detected=detected,
        has_station_coordinates=has_station_coordinates,
        has_latlon_per_station=(detected == "latlon"),
        has_utm_coordinates=(detected == "utm"),
        has_local_coordinates=(detected == "local_meters"),
        has_utm_zone=bool(effective_utm_zone),
        has_anchor_latlon=(anchor_lat is not None and anchor_lon is not None),
        has_elevation_column=bool(_get_field(csv_analysis, "has_elevation_column", False)),
        has_uncertainty_column=bool(_get_field(csv_analysis, "has_uncertainty_column", False)),
        has_instrument_metadata=bool(_get_field(csv_analysis, "has_instrument_metadata", False)),
        has_corrections_metadata=bool(_get_field(csv_analysis, "has_corrections_metadata", False)),
    )
