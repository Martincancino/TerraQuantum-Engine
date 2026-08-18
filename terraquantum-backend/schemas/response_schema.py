"""Response schemas for FastAPI endpoints — strict validation contracts."""

# ─────────────────────────────────────────────────────────────────────────────
# CONTRATO_SERIALIZADO — por qué varios modelos de RESPUESTA llevan
# `ConfigDict(json_schema_serialization_defaults_required=True)`   (Fase 11)
#
# La Fase 10 dejó 17 contratos que el frontend seguía escribiendo a mano, y el
# diagnóstico era correcto: *en un contrato de respuesta, un default es una
# promesa que nadie quiso hacer*. `default_factory` marca el campo opcional en
# el OpenAPI, el tipo generado sale con `?` y el consumidor se llena de `?? []`
# para casos imposibles — que es justo como se esconden los sitios donde SÍ
# puede faltar. El arreglo de entonces (quitar los defaults) se revirtió porque
# arriesgaba 500 en cinco esquemas.
#
# La salida no era quitar el default: era decir la verdad sobre la
# SERIALIZACIÓN. Si la ruta NO usa `response_model_exclude_unset`, FastAPI
# serializa el modelo entero y el campo viaja SIEMPRE, tenga default o no. Esta
# bandera lo declara así en el esquema y **no toca nada más**: construir el
# modelo sigue igual y `exclude_unset` sigue funcionando donde se use.
#
# Se aplica sólo donde se MIDIÓ sobre la respuesta real que el campo está. Tres
# contratos se quedaron fuera con su motivo —`HistoryRun` (su ruta sí usa
# `exclude_unset`), `PercentileStats` (medido: 13 de 14 campos NO llegan) y
# `DataQualityScore` (no se pudo medir)— y hay un test que lo vigila en los dos
# sentidos: `tests/test_fase11_api_scripting.py`.
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional
from schemas.gravity_import_schema import (
    SpatialReadiness,
    RegionalScalePreflight,
    AutoGrid,
    CoordinateTransform,
    CsvAnalysisResult,
    GravityImportMetadata,
)


# ─────────────────────────────────────────────────────────────────────────────
# POST /gravity-import/preview
# ─────────────────────────────────────────────────────────────────────────────

class GravityImportPreviewResponse(BaseModel):
    """CSV preview response: analysis + gates, no inversion."""
    # extra="allow": el endpoint emite campos adicionales (auto_grid,
    # georef_preview, octree_params, importMetadata camelCase…) que el frontend
    # consume; un response_model estricto los filtraría rompiendo el contrato.
    #
    # Fase 11: y `json_schema_serialization_defaults_required` resuelve la otra
    # mitad de esta ruta, la que la Fase 10 dejó en `INYECCION_TOLERADA` sin
    # poder medir. Es el caso llamativo: `extra="allow"` SIN `exclude_unset`
    # significa que los opcionales se emiten igualmente (en `null` si nadie los
    # puso), o sea que **nunca faltan**. MEDIDO sobre una respuesta real: los 10
    # campos declarados están presentes. El `?` del tipo generado describía un
    # caso que esta ruta no produce.
    model_config = ConfigDict(
        extra="allow", json_schema_serialization_defaults_required=True,
    )

    # /preview emite status="ok" históricamente (import_gravity_csv_v1); el
    # patrón debe aceptarlo o todo preview válido revienta con 500.
    status: str = Field(..., pattern="^(ok|done|error)$")
    stage: str = Field(default="preview", pattern="^(preview|import)$")

    # Core analysis
    csv_analysis: Optional[CsvAnalysisResult] = None
    coordinate_transform: Optional[CoordinateTransform] = None
    spatial_readiness: Optional[SpatialReadiness] = None
    regional_scale_preflight: Optional[RegionalScalePreflight] = None

    # Sprint 3 — Octree params surfaced at top level for direct frontend access
    octree_params: Optional[Dict[str, Any]] = None

    # Import metadata
    import_metadata: Optional[GravityImportMetadata] = None

    # Errors & warnings
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# POST /gravity-import/invert
# ─────────────────────────────────────────────────────────────────────────────

class R3EnrichmentStatus(BaseModel):
    """R3 Enrichment (elevation/DEM integration) status."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    attempted: bool = False
    terrain_persisted: bool = False
    # None = enrichment no intentado (sin project_id/run_id o georef MISSING)
    # "ok" es el status real que devuelve elevation_enrichment_service; "success"
    # se mantiene por compatibilidad histórica con clientes que lo esperasen.
    enrichment_status: Optional[str] = Field(default="skipped", pattern="^(ok|success|skipped|error)$")
    has_elevation_data: bool = False
    warnings: List[str] = Field(default_factory=list)


class ImportPersistenceStatus(BaseModel):
    """Parquet and file I/O persistence status."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    persisted: bool = False
    source_gravity_path: Optional[str] = None
    metadata_path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class GridAutoAdapt(BaseModel):
    """Grid adaptation metadata (auto vs frontend-requested)."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    applied: bool = False
    reason: Optional[str] = None
    frontend_requested: Optional[Dict[str, int]] = None  # {nx, ny, nz, blockSize, depth}
    effective_used: Optional[Dict[str, int]] = None
    total_voxels: int = 0


class InversionDiagnostics(BaseModel):
    """Solver fit statistics."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    rmse_misfit: Optional[float] = None
    normalized_rmse: Optional[float] = None
    l2_norm: Optional[float] = None
    data_coverage: Optional[int] = None
    convergence_status: str = Field(default="unknown")
    iterations: int = 0
    regularization_lambda: Optional[float] = None


class InversionMetadata(BaseModel):
    """Inversion execution metadata."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    solver_type: Optional[str] = None
    lambda_mag: Optional[float] = None
    alpha_spatial: Optional[float] = None
    depth_beta: Optional[float] = None
    diagnostics: Optional[InversionDiagnostics] = None


class GravityImportInvertResponse(BaseModel):
    """Inversion response: complete pipeline result."""
    # extra="allow": el endpoint emite campos legacy camelCase (importMetadata,
    # inversionResult, gridAutoAdapt, georef…) consumidos por el frontend.
    # F11: ver CONTRATO_SERIALIZADO (arriba). MEDIDO en esta ruta: con
    # `exclude_unset` desaparecerían 4 claves (grid_auto_adapt, import_metadata,
    # import_persistence, inversion_result); sin él viajan SIEMPRE, y eso es lo
    # que el esquema pasa a decir.
    model_config = ConfigDict(
        extra="allow", json_schema_serialization_defaults_required=True,
    )

    status: str = Field(..., pattern="^(done|error)$")
    stage: str = Field(default="inversion", pattern="^(import|inversion)$")

    # Project tracking
    project_id: Optional[str] = None
    run_id: Optional[str] = None

    # Geospatial
    georef: Optional[Dict[str, Any]] = None  # {confidence, type, utm_zone, footprint, crs_contract}
    spatial_readiness: Optional[SpatialReadiness] = None
    regional_scale_preflight: Optional[RegionalScalePreflight] = None

    # Import analysis
    import_metadata: Optional[GravityImportMetadata] = None
    csv_analysis: Optional[CsvAnalysisResult] = None
    coordinate_transform: Optional[CoordinateTransform] = None
    auto_grid: Optional[AutoGrid] = None

    # Inversion result
    inversion_result: Optional[InversionMetadata] = None
    # NOTE: voxels are NOT included in HTTP response (persisted to parquet separately)

    # Post-inversion enrichment
    r3_enrichment: Optional[R3EnrichmentStatus] = None

    # Persistence
    import_persistence: Optional[ImportPersistenceStatus] = None

    # Grid adaptation metadata
    grid_auto_adapt: Optional[GridAutoAdapt] = None

    # Errors & warnings
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# POST /geophysics-invert
# ─────────────────────────────────────────────────────────────────────────────

class GeophysicsInversionStartResponse(BaseModel):
    """Background inversion start response (async task)."""
    status: str = Field(default="queued", pattern="^(queued|processing|done|error)$")
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None  # id de tarea legado (la vía Celery fue eliminada en F3)
    message: str = "Inversion queued for background processing"
    warnings: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# GET /geophysics-status/{project_id}/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

class ErrorDetails(BaseModel):
    """Structured error information for task failures."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    code: Optional[str] = None  # e.g. "SOLVER_DIVERGENCE", "FILE_NOT_FOUND", "VALIDATION_ERROR"
    message: str  # Human-readable error message
    source: Optional[str] = None  # e.g. "geophysics_service", "gravity_import_service", "block_model_store"
    stage: Optional[str] = None  # e.g. "import", "preprocessing", "solving", "post-processing"
    details: Optional[Dict[str, Any]] = None  # Additional context (e.g. {"field": "depth", "reason": "exceeds grid bounds"})
    traceback: Optional[str] = None  # Python traceback for debugging (only in dev/logged mode)


class GeophysicsStatusResponse(BaseModel):
    """Inversion status polling response.

    F3: el pattern histórico (queued|processing|done|error) NO incluía
    "running" — exactamente lo que escribe el solver durante la inversión
    (heartbeat solving_lsqr) → el polling devolvía 500 de validación en plena
    corrida. Se amplía con los estados reales + los terminales de F3
    (cancelled / interrumpida).
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    status: str = Field(
        ..., pattern="^(queued|processing|running|done|error|cancelled|interrumpida)$"
    )
    stage: str = Field(default="unknown")  # import, preprocessing, solving, post-processing, done
    progress: Optional[float] = Field(default=0.0, ge=0, le=100)  # Percentage
    project_id: Optional[str] = None
    run_id: Optional[str] = None

    # Result (populated when status=="done")
    result: Optional[GravityImportInvertResponse] = None

    # Error (populated when status=="error") — now structured
    error_details: Optional[ErrorDetails] = None
    # Backward-compat fields (deprecated, use error_details)
    error: Optional[str] = None
    error_type: Optional[str] = None
    traceback: Optional[str] = None

    # Metadata
    estimated_time_remaining_seconds: Optional[int] = None
    message: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# GET /block-model
# ─────────────────────────────────────────────────────────────────────────────

class VoxelData(BaseModel):
    """Single voxel in block model."""
    # extra="allow": el builder emite campos que el visor necesita pero que no
    # estaban declarados aquí (susceptibility_si, density_t_m3,
    # density_contrast_t_m3, run_type, schema_version, doi_raw, ...). Sin esto el
    # response_model los DESCARTA — p.ej. una corrida magnética perdía
    # susceptibility_si y el visor no podía colorear por susceptibilidad.
    model_config = ConfigDict(extra="allow")

    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    cx: Optional[float] = None
    cy: Optional[float] = None
    cz: Optional[float] = None

    # Physical properties
    density: Optional[float] = None
    rho: Optional[float] = None
    probability: Optional[float] = None
    visual_score: Optional[float] = None

    # Optional fields
    # grade and tonnage are placeholders for external mining software integration (Whittle, Gemcom, etc.).
    # TerraQuantum does NOT compute grade or tonnage — only density/susceptibility from geophysical inversion.
    # In industrial mode (expose_demo_grade=False) grade is NaN/null; in demo mode it is a heuristic proxy.
    grade: Optional[float] = Field(default=None, description="Grade (%): NOT computed by TerraQuantum. Placeholder for external mining software.")
    domain: Optional[int] = None
    tonnage: Optional[float] = Field(default=None, description="Tonnage (tonnes): NOT computed by TerraQuantum. Placeholder for external mining software.")
    is_active: Optional[bool] = None

    # R3 Elevation fields (if available)
    lat: Optional[float] = None
    lon: Optional[float] = None
    voxel_elevation_masl: Optional[float] = None
    surface_elevation_masl: Optional[float] = None
    depth_below_surface_m: Optional[float] = None

    # HITO 1: Joint inversion fields
    susceptibility: Optional[float] = None

    # Additional metadata
    normalized_sensitivity: Optional[float] = None
    sensitivity_proxy: Optional[float] = None
    anomaly_intensity: Optional[float] = None
    target_score: Optional[float] = None
    modeled_density_index: Optional[float] = None
    density_anomaly_score: Optional[float] = None
    doi_index: Optional[float] = None
    posterior_std: Optional[float] = None
    joint_structural_score: Optional[float] = None
    real_grade: Optional[float] = None


class PercentileStats(BaseModel):
    """Percentile statistics for diagnostic display."""
    p2: Optional[float] = None
    p5: Optional[float] = None
    p50: Optional[float] = None
    p85: Optional[float] = None
    p90: Optional[float] = None
    p95: Optional[float] = None
    p98: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    threshold: Optional[float] = None
    is_degenerate: bool = False
    degenerate_reason: Optional[str] = None


class BlockModelStats(BaseModel):
    """Statistics per field (density, probability, etc)."""
    density: Optional[PercentileStats] = None
    rho: Optional[PercentileStats] = None
    probability: Optional[PercentileStats] = None
    visual_score: Optional[PercentileStats] = None
    grade: Optional[PercentileStats] = None
    voxel_elevation_masl: Optional[PercentileStats] = None
    susceptibility: Optional[PercentileStats] = None


class BlockModelResponse(BaseModel):
    """Block model JSON response (voxels as JSON array)."""
    # extra="allow": build_block_model_response emite campos de geometría y
    # estadística (domainL/H/W, cellSize, visualMode, densityMin/Max,
    # diagnosticStats/densityStats camelCase, percentile_stats, returnedScoreStats…)
    # que el visor 3D NECESITA para escalar los vóxeles y calcular la esfera de
    # frustum culling. Un response_model estricto los filtraba: el frontend
    # recibía cellSize=10 (real 520 m) y domainL=0, por lo que Three.js
    # descartaba toda la malla y solo se veía la caja del dominio.
    model_config = ConfigDict(extra="allow")

    cells: List[VoxelData] = Field(default_factory=list)

    # Voxel counts
    total_voxels: int = 0
    returned_voxels: int = 0
    stored_voxels: int = 0
    anomaly_voxels: int = 0

    # Geometría del dominio (la usa el visor 3D para escala y culling)
    domainL: Optional[float] = None
    domainH: Optional[float] = None
    domainW: Optional[float] = None
    cellSize: Optional[float] = None
    visualMode: Optional[str] = None

    # Rango de densidad (colormap físico)
    densityMin: Optional[float] = None
    densityMax: Optional[float] = None

    # Diagnostics
    diagnostic_stats: Optional[BlockModelStats] = None

    # Metadata
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    mode: str = Field(default="exploration")  # exploration, full, anomaly, economic

    # Warnings & errors
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# GET /block-model-arrow
# ─────────────────────────────────────────────────────────────────────────────

class BlockModelArrowMetadata(BaseModel):
    """Metadata about Arrow-formatted block model (sent as headers)."""
    total_voxels: int = 0
    returned_voxels: int = 0
    bounds_min_x: Optional[float] = None
    bounds_min_y: Optional[float] = None
    bounds_min_z: Optional[float] = None
    bounds_max_x: Optional[float] = None
    bounds_max_y: Optional[float] = None
    bounds_max_z: Optional[float] = None
    run_id: Optional[str] = None
    project_id: Optional[str] = None


# NOTE: BlockModelArrowResponse is actually bytes (Apache Arrow IPC format)
# Returned with Content-Type: application/vnd.apache.arrow.stream
# Headers include BlockModelArrowMetadata fields (X-TQ-Total-Voxels, X-TQ-Bounds-Min-X, etc)


# ─────────────────────────────────────────────────────────────────────────────
# GET /geophysics-misfit/{project_id}/{run_id}  — H-C2
# ─────────────────────────────────────────────────────────────────────────────

class MisfitStationData(BaseModel):
    """Observed vs. calculated data for a single gravity station."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    d_obs: float
    d_pred: float
    residual: float


class MisfitResponse(BaseModel):
    """Full misfit report: per-station obs/calc + aggregate fit statistics."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    stations: List[MisfitStationData]
    chi2_reduced: float
    rmse: float
    normalized_rmse: float
    r2: float
    n_stations: int


# ─────────────────────────────────────────────────────────────────────────────
# GET /v2/geophysics-convergence/{project_id}/{run_id}  — F5
# ─────────────────────────────────────────────────────────────────────────────

class ConvergenceTrial(BaseModel):
    """Un candidato λ probado por el barrido Morozov, con su chi² resultante."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    lambda_value: float
    chi2_reduced: Optional[float] = None


class ConvergenceResponse(BaseModel):
    """
    F5 — Curva de 'convergencia' YA calculada por el solver: el barrido de λ
    (Morozov chi² discrepancy) usado para seleccionar la regularización. NO es
    chi² por iteración interna de un único solve (esa serie no se persiste
    estructuradamente hoy — ver docs/01_PLAN_MAESTRO.md F5); es honesto sobre
    qué mide cada punto.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    available: bool
    selection_method: Optional[str] = None
    lambda_selected: Optional[float] = None
    chi2_achieved: Optional[float] = None
    n_solves: Optional[int] = None
    trials: List[ConvergenceTrial] = []
    warnings: List[str] = []
    note: str
