from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional
from schemas.geophysics_schema import GravityObservation


class SpatialExtent(BaseModel):
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    z_min: Optional[float] = None
    z_max: Optional[float] = None
    x_span: Optional[float] = None
    y_span: Optional[float] = None
    z_span: Optional[float] = None


class SamplingStats(BaseModel):
    area_km2: float = 0.0
    mean_spacing_m: Optional[float] = None
    point_density_per_km2: Optional[float] = None


class GravityStats(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    p5: Optional[float] = None
    p95: Optional[float] = None


class DuplicateInfo(BaseModel):
    exact_count: int = 0
    near_count: int = 0
    tolerance_m: float = 1.0
    examples: List[Dict[str, Any]] = Field(default_factory=list)


class OutlierInfo(BaseModel):
    count: int = 0
    method: str = "zscore_3sigma"
    examples: List[Dict[str, Any]] = Field(default_factory=list)


class UnitDetection(BaseModel):
    declared: Optional[str] = None
    value_range_consistent: bool = True
    confidence: str = "low"
    warning: Optional[str] = None


class CoordSystemDetection(BaseModel):
    detected: str = "unknown"
    confidence: str = "low"
    warning: Optional[str] = None
    utm_zone: Optional[str] = None
    utm_hemisphere: Optional[str] = None
    epsg_code: Optional[int] = None
    crs_source: str = "missing"


class CoordinateTransform(BaseModel):
    version: str = "coord_transform_v0_1"
    input_coordinate_system: str = "unknown"
    input_confidence: str = "low"
    method: str = "identity_fallback"
    origin_strategy: str = "SW_BBOX"
    origin_input_coordinates: Dict[str, Any] = Field(default_factory=dict)
    x_min_raw: Optional[float] = None
    z_min_raw: Optional[float] = None
    x_max_raw: Optional[float] = None
    z_max_raw: Optional[float] = None
    x_extent_m: float = 0.0
    z_extent_m: float = 0.0
    transformed: bool = False
    warnings: List[str] = Field(default_factory=list)
    precision_notes: List[str] = Field(default_factory=list)
    utm_zone: Optional[str] = None
    utm_hemisphere: Optional[str] = None
    epsg_code: Optional[int] = None
    crs_source: str = "missing"
    absolute_origin: Optional[Dict[str, float]] = None


class AutoGrid(BaseModel):
    version: str = "auto_grid_v0_1"
    block_size_m: float
    nx: int
    ny: int
    nz: int
    voxel_count: int
    depth_m: float
    cutoff_radius_m: float
    lambda_mag: Optional[float] = None
    alpha_spatial: Optional[float] = None
    r10_limit: int = 200000
    adjusted_for_r10: bool = False
    voxel_count_before_r10: int
    r10_iterations: int = 0
    warnings: List[str] = Field(default_factory=list)
    rationale: List[str] = Field(default_factory=list)
    # Sprint 3 — parámetros Octree calibrados para construir un TreeMesh de producción.
    # None cuando el survey no fue analizado por compute_octree_params (legado).
    octree_params: Optional[Dict[str, Any]] = None
    # True cuando el survey es regional (>50 km) o la grilla supera 50k celdas.
    # El frontend puede usarlo para pre-seleccionar TreeMesh en la UI.
    recommended_use_treemesh: bool = False


class DataQualityScore(BaseModel):
    """
    Fase 19 Tarea 5 — Data Quality Score numérico 0–100.

    Score ponderado derivado de CsvAnalysisResult (no recalcula física):
      completeness 50% · spatial_distribution 20% · noise_level 15% ·
      resolution 10% · outlier_fraction 5%.
    Cada componente es un sub-score 0–100; `score` es la suma ponderada.
    `interpretation`: GOOD (≥75) · MEDIOCRE (≥50) · POOR (<50).
    """
    version: str = "data_quality_v0_1"
    score: float = 0.0
    interpretation: str = "POOR"
    # Sub-scores 0–100 por componente
    completeness: float = 0.0
    spatial_distribution: float = 0.0
    noise_level: float = 0.0
    resolution: float = 0.0
    outlier_fraction: float = 0.0
    # Pesos usados (transparencia / trazabilidad)
    weights: Dict[str, float] = Field(default_factory=dict)
    # Explicaciones de proxies usados por componente
    notes: List[str] = Field(default_factory=list)


class CsvAnalysisResult(BaseModel):
    version: str = "csv_analysis_v0_1"
    observation_count: int = 0
    spatial_extent: SpatialExtent
    sampling: SamplingStats
    gravity_stats: GravityStats
    duplicates: DuplicateInfo
    outliers: OutlierInfo
    units: UnitDetection
    coordinate_system: CoordSystemDetection
    coordinate_transform: Optional[CoordinateTransform] = None
    auto_grid: Optional[AutoGrid] = None
    warnings: List[str] = Field(default_factory=list)
    quality_label: str = "INSUFICIENTE"
    # Fase 19 Tarea 5 — score numérico 0–100 (complementa quality_label categórico)
    data_quality: Optional[DataQualityScore] = None
    # R3.5-I — professional survey column flags
    has_elevation_column: bool = False
    has_uncertainty_column: bool = False
    has_instrument_metadata: bool = False
    has_corrections_metadata: bool = False
    professional_columns_detected: List[str] = Field(default_factory=list)
    # R3.5-I-FIX1 — aliases confirmed with real values (subset of professional_columns_detected)
    professional_columns_with_values: List[str] = Field(default_factory=list)


class GravityImportMetadata(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    source_file: str
    schema_version: str
    unit_original: Optional[str] = None
    unit_internal: str = "m/s²"
    gravity_column_used: Optional[str] = None
    gravity_type: Optional[str] = None
    conversion_applied: bool
    row_count: int
    valid_rows: int
    rejected_rows: int
    warnings: List[str]
    errors: List[str]
    is_demo: bool
    csv_analysis: Optional[CsvAnalysisResult] = None
    coordinate_transform: Optional[CoordinateTransform] = None
    auto_grid: Optional[AutoGrid] = None
    # Fase 5: resolución real y contexto geológico honesto
    estimated_mean_spacing_m: Optional[float] = None
    estimated_depth_resolution_m: Optional[float] = None
    geological_context_hint: Optional[str] = None  # "regional" | "local_to_district" | "local_deposit"
    honesty_note: Optional[str] = None

class HelmertTransformResult(BaseModel):
    """Fase 19 Tarea 7 (Caso B) — transformada de similitud 2D (Helmert).

    Resuelve real = s·R(θ)·local + t a partir de ≥2 puntos de control, fijando
    posición + rotación + escala de coordenadas locales (x_m, z_m) a coordenadas
    reales (Easting/Northing en una zona UTM, o un sistema proyectado coherente).
    """
    version: str = "helmert_v0_1"
    n_control_points: int
    scale: float
    rotation_deg: float
    translation_e: float
    translation_n: float
    residual_rms_m: float
    max_residual_m: float
    # HIGH (≥3 ptos, residual bajo) · MEDIUM (2 ptos, ajuste exacto sin redundancia)
    # · LOW (residual alto → datos mal anclados o puntos errados)
    confidence: str
    warnings: List[str] = Field(default_factory=list)
    # Coeficientes crudos para aplicar la transformada: E = a·x − b·z + tE ...
    a: float
    b: float


class HelmertControlPoint(BaseModel):
    """Un punto de control para georef Helmert: coord local (x,z) ↔ coord real (E,N).

    `local_x`/`local_z` están en el sistema local del CSV (mismas unidades que las
    estaciones). `real_e`/`real_n` son Easting/Northing reales en una zona UTM (o un
    sistema proyectado coherente, en metros). `label` es opcional (ej. "BH-01").
    """
    local_x: float
    local_z: float
    real_e: float
    real_n: float
    label: Optional[str] = None


class HelmertControlPointsInput(BaseModel):
    """Fase 19 Caso B — contrato de entrada de puntos de control para /invert.

    Se requieren ≥2 puntos para resolver posición + rotación + escala. El motor de
    inversión lo recibe (como JSON en el form) y, si las coordenadas del CSV son
    LOCALES, georeferencia las estaciones antes de calcular el footprint del modelo.
    """
    points: List[HelmertControlPoint] = Field(default_factory=list, min_length=2)
    residual_warn_m: float = 10.0


class DataTypeDetection(BaseModel):
    """Fase 19 Tarea 1 — tipo de dato inferido desde las columnas del CSV."""
    version: str = "data_type_detection_v0_1"
    # gravity | magnetic | borehole | joint | ambiguous | unknown
    detected_type: str = "unknown"
    confidence: str = "low"  # high | medium | low
    has_gravity_column: bool = False
    has_magnetic_column: bool = False
    has_borehole_columns: bool = False
    is_joint_candidate: bool = False
    gravity_column: Optional[str] = None
    magnetic_column: Optional[str] = None
    signals: List[str] = Field(default_factory=list)
    warning: Optional[str] = None


class GravityImportResult(BaseModel):
    status: str
    observations: List[GravityObservation]
    import_metadata: GravityImportMetadata
    warnings: List[str]
    errors: List[str]
    csv_analysis: Optional[CsvAnalysisResult] = None
    coordinate_transform: Optional[CoordinateTransform] = None
    auto_grid: Optional[AutoGrid] = None
    # R3.5-C — populated by API layer after classify_from_csv_analysis
    spatial_readiness: Optional["SpatialReadiness"] = None
    # H-B2 — per-station raw lat/lon/elev captured before coord transform (latlon surveys only)
    # Shape: [{"lat_deg": float, "lon_deg": float, "elev_m": float}] or None
    raw_latlon_elev: Optional[List[Dict[str, Any]]] = None
    # Topografía activa — elevación de estación (m s.n.m.) para CUALQUIER tipo de
    # coordenada, paralela a observations. NaN donde la columna esté vacía.
    # None = el CSV no trae columna de elevación.
    station_elevations: Optional[List[float]] = None
    # Sigma por estación [mGal] desde la columna uncertainty/sigma. NaN si vacía.
    # Prioridad de sigma del solver: σ por estación > piso por gravímetro > adaptivo.
    station_uncertainties: Optional[List[float]] = None
    # Fase 9C — Inversión conjunta. Valores TMI (nT) por estación, PARALELOS a
    # observations, capturados cuando un CSV gravimétrico trae ADEMÁS una columna
    # magnética (survey co-localizado). None = no hay columna magnética → flujo
    # gravimétrico puro. Habilita el ruteo a joint cross-gradient.
    magnetic_values: Optional[List[float]] = None
    # Fase 19 Tarea 1 — auto-detección del tipo de CSV (gravity/magnetic/borehole/
    # joint/ambiguous/unknown) a partir de las columnas presentes. Informativo:
    # permite al frontend pre-seleccionar el tipo o pedir confirmación si es ambiguo.
    detected_data_type: Optional[DataTypeDetection] = None
    # F2 — SniffReport de la capa física (encoding/separador/decimal/preámbulo/
    # filas rotas, cada dimensión con confianza + evidencia + descartados).
    # Viaja al frontend para que el usuario CONFIRME lo detectado; presente
    # también en resultados de error (el usuario ve QUÉ se intentó leer).
    sniff_report: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# R3.5-A — Spatial Readiness Contract
# ─────────────────────────────────────────────────────────────────────────────

SPATIAL_LEVEL_RANKS: Dict[str, int] = {
    "NO_SPATIAL_DATA": 0,
    "LOCAL_UNANCHORED": 1,
    "LOCAL_ANCHORED_CENTER": 2,
    "UTM_NO_ZONE": 2,
    "UTM_WITH_ZONE": 3,
    "GEOGRAPHIC_COORDS": 4,
    "PROFESSIONAL_SURVEY": 5,
}

SPATIAL_LEVEL_MAX_FAVORABILITY: Dict[str, float] = {
    "NO_SPATIAL_DATA": 0.0,
    "LOCAL_UNANCHORED": 45.0,
    "LOCAL_ANCHORED_CENTER": 45.0,
    "UTM_NO_ZONE": 60.0,
    "UTM_WITH_ZONE": 85.0,
    "GEOGRAPHIC_COORDS": 100.0,
    "PROFESSIONAL_SURVEY": 100.0,
}

SPATIAL_LEVEL_MAX_PRIORITY: Dict[str, str] = {
    "NO_SPATIAL_DATA": "NONE",
    "LOCAL_UNANCHORED": "LOW_RELATIVE_PRIORITY",
    "LOCAL_ANCHORED_CENTER": "LOW_RELATIVE_PRIORITY",
    "UTM_NO_ZONE": "LOW_RELATIVE_PRIORITY",
    "UTM_WITH_ZONE": "HIGH_RELATIVE_PRIORITY",
    "GEOGRAPHIC_COORDS": "HIGH_RELATIVE_PRIORITY",
    "PROFESSIONAL_SURVEY": "HIGH_RELATIVE_PRIORITY",
}


class SpatialReadiness(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    version: str = "spatial_readiness_v0_1"
    level: str
    level_rank: int
    can_run_3d_inversion: bool
    can_run_local_conceptual_inversion: bool
    can_use_dem: bool
    can_compute_voxel_masl: bool
    can_compute_voxel_latlon: bool
    requires_user_acknowledgement: bool
    required_acknowledgement: Optional[str] = None
    max_priority_class_allowed: str
    max_favorability_score_allowed: float
    missing_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    allowed_outputs: List[str] = Field(default_factory=list)
    blocked_outputs: List[str] = Field(default_factory=list)
    rationale: str


class RegionalScalePreflight(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    version: str = "regional_scale_preflight_v0_1"
    scale_class: str
    can_run_single_inversion: bool
    requires_user_acknowledgement: bool = False
    recommended_action: str
    extent_x_m: Optional[float] = None
    extent_z_m: Optional[float] = None
    area_km2: Optional[float] = None
    station_count: Optional[int] = None
    estimated_nx: Optional[int] = None
    estimated_ny: Optional[int] = None
    estimated_nz: Optional[int] = None
    estimated_voxel_count: Optional[int] = None
    estimated_depth_m: Optional[float] = None
    estimated_block_size_m: Optional[float] = None
    max_allowed_nx: int = 80
    max_allowed_ny: int = 80
    max_allowed_nz: int = 80
    warnings: List[str] = Field(default_factory=list)
    blocked_reasons: List[str] = Field(default_factory=list)
    allowed_outputs: List[str] = Field(default_factory=list)
    suggested_tile_size_m: Optional[float] = None
    suggested_subset_bbox: Optional[Dict[str, float]] = None
    rationale: str
