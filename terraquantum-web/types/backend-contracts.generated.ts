// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  ARCHIVO GENERADO — NO EDITAR A MANO                                     ║
// ╚══════════════════════════════════════════════════════════════════════════╝
//
// Fase 10 (H-16). Lo produce el backend a partir del esquema OpenAPI que FastAPI
// publica, con:
//
//     cd terraquantum-backend
//     python scripts/ci/generate_frontend_types.py
//
// Si editas esto a mano, el `--check` de la CI lo revierte con un rojo. Y ése es
// el punto de la fase: **el contrato tiene un solo dueño, y es el backend**.
// Antes había 209 tipos escritos a mano en el frontend copiando esquemas
// Pydantic; cuando el backend cambiaba un campo, no fallaba nada — el usuario
// veía un dato vacío semanas después.
//
// QUÉ ES CADA COSA:
//  · Un `[key: string]: unknown` significa que el modelo Pydantic lleva
//    `extra="allow"`: el endpoint emite además campos que el contrato no fija.
//    Está declarado porque es verdad, no por comodidad.
//  · Un campo `?` es opcional EN EL CONTRATO: el backend puede no mandarlo.
//    Comprobarlo antes de usarlo no es defensivo, es leer el contrato.
//
// LO QUE ESTE ARCHIVO NO SUSTITUYE: las uniones discriminadas escritas a mano en
// `lib/terraquantum/frontendApi.ts` (p. ej. `LoadPackageResult` por `status`).
// OpenAPI no las expresa y son MÁS precisas que lo generado; un test del backend
// comprueba que sus variantes sigan existiendo aquí.

// ── Qué ruta devuelve qué ──────────────────────────────────────────────────
//
//   GET /block-model                                     → BlockModelResponse
//   GET /diagnostics/manifest                            → DiagnosticManifestResponse
//   GET /geophysics-misfit/{project_id}/{run_id}         → MisfitResponse
//   GET /geophysics-status/{project_id}/{run_id}         → GeophysicsStatusResponse
//   GET /health                                          → HealthResponse
//   GET /license/status                                  → LicenseStatusResponse
//   GET /system-status                                   → SystemStatusResponse
//   GET /system/connectivity                             → ConnectivitySummaryResponse
//   GET /v2/geophysics-convergence/{project_id}/{run_id} → ConvergenceResponse
//   GET /v2/history/runs                                 → HistoryRunsResponse
//   GET /v2/history/runs/{project_id}/{run_id}           → HistoryRunDetailResponse
//   POST /borehole/parse-csv                             → ParseBoreholeCsvResponse
//   POST /borehole/parse-csv-file                        → ParseBoreholeCsvResponse
//   POST /geophysics-invert                              → GeophysicsInversionStartResponse
//   POST /gravity-corrections/apply                      → ApplyCorrectionsResponse
//   POST /gravity-import/invert                          → GravityImportInvertResponse
//   POST /gravity-import/preview                         → GravityImportPreviewResponse
//   POST /license/activate                               → LicenseActivationResponse
//   POST /multimodal/plan                                → MultimodalPlanResponse
//   POST /v2/geophysics-invert                           → GeophysicsInversionStartResponse
//   POST /v2/gravity-import/analyze-columns              → AnalyzeColumnsResponse
//   POST /v2/gravity-import/enrich-package               → EnrichPackageResponse
//   POST /v2/gravity-import/load-package                 → LoadPackageResponse
//   POST /v2/gravity-import/parse-rows                   → ParseRowsResponse
//
// 69 tipos, cierre transitivo de 22 contratos de respuesta.

/**
 * El plan de mapeo SIN invertir ni fabricar nada: se leen encabezados, se
 * corre la detección y se re-etiquetan columnas reales.
 *
 * `sample_rows` son filas **YA parseadas por el importador**, no las líneas
 * crudas del archivo: un preview honesto muestra lo que el motor va a ver
 * (con el decimal ya resuelto), no lo que el texto aparenta.
 */
export type AnalyzeColumnsResponse = {
  column_mapping: ColumnMappingPlanContract;
  sniff_report: SniffReportContract;
  sample_rows: Record<string, unknown>[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type ApplyCorrectionsResponse = {
  corrected: CorrectedStation[];
  report: CorrectionReport;
  output_gravity_type: "free_air_anomaly" | "bouguer_anomaly" | "complete_bouguer_anomaly";
};

export type AutoGrid = {
  version: string;
  block_size_m: number;
  nx: number;
  ny: number;
  nz: number;
  voxel_count: number;
  depth_m: number;
  cutoff_radius_m: number;
  lambda_mag: number | null;
  alpha_spatial: number | null;
  r10_limit: number;
  adjusted_for_r10: boolean;
  voxel_count_before_r10: number;
  r10_iterations: number;
  warnings: string[];
  rationale: string[];
  octree_params: Record<string, unknown> | null;
  recommended_use_treemesh: boolean;
};

/** Block model JSON response (voxels as JSON array). */
export type BlockModelResponse = {
  cells?: VoxelData[];
  total_voxels?: number;
  returned_voxels?: number;
  stored_voxels?: number;
  anomaly_voxels?: number;
  domainL?: number | null;
  domainH?: number | null;
  domainW?: number | null;
  cellSize?: number | null;
  visualMode?: string | null;
  densityMin?: number | null;
  densityMax?: number | null;
  diagnostic_stats?: BlockModelStats | null;
  project_id?: string | null;
  run_id?: string | null;
  mode?: string;
  warnings?: string[];
  errors?: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Statistics per field (density, probability, etc). */
export type BlockModelStats = {
  density?: PercentileStats | null;
  rho?: PercentileStats | null;
  probability?: PercentileStats | null;
  visual_score?: PercentileStats | null;
  grade?: PercentileStats | null;
  voxel_elevation_masl?: PercentileStats | null;
  susceptibility?: PercentileStats | null;
};

/**
 * Una muestra/tramo de sondaje VERTICAL con propiedades petrofísicas medidas.
 *
 * El sondaje se asume vertical: collar en (x_m, z_m) local y el tramo cubre
 * [depth_from_m, depth_to_m] en profundidad (+ hacia abajo). density_t_m3 y/o
 * susceptibility_si anclan respectivamente la inversión gravimétrica/magnética;
 * al menos una debe estar presente (igual semántica que BoreholeInterval).
 */
export type BoreholeSample = {
  /** Identificador del sondaje, p.ej. 'BH01'. */
  hole_id: string;
  /** Coordenada local X del collar (m). Pozo vertical. */
  x_m: number;
  /** Coordenada local Z del collar (m). Pozo vertical. */
  z_m: number;
  /** Profundidad inicial del tramo (m, + hacia abajo). */
  depth_from_m: number;
  /** Profundidad final del tramo (m, + hacia abajo). */
  depth_to_m: number;
  /** Tipo de muestra: testigo, detritus, registro de densidad/susc en pozo, etc. */
  sample_type: "core" | "cuttings" | "downhole_density" | "downhole_susc" | "other";
  /** Densidad medida del tramo (t/m³). Ancla la inversión gravimétrica. */
  density_t_m3: number | null;
  /** Incertidumbre fraccional de la densidad de muestreo (0.15 = 15%). */
  density_uncertainty: number;
  /** Litología registrada (p.ej. 'granite', 'magnetite', 'diorite'). Alimenta priors PGI. */
  lithology: string | null;
  /** Susceptibilidad magnética medida (SI). Ancla la inversión magnética. */
  susceptibility_si: number | null;
  /** Comentario libre (trazabilidad). */
  comment: string;
};

/** Conjunto de sondajes con metadatos de georreferencia (capa de carga FASE 20). */
export type BoreholeSurvey = {
  /** Muestras/tramos de sondaje. */
  holes: BoreholeSample[];
  /** Sistema de referencia, p.ej. 'UTM 19S' o 'local'. */
  crs: string;
  /** Elevación del datum local (m s.n.m.) para referencia vertical. */
  datum_elevation_m: number;
};

/**
 * Espejo de `services.column_mapping_service.build_column_mapping_plan()`.
 *
 * `needs_mapping` (falta un rol REQUERIDO) y `needs_confirmation` (están todos
 * pero la confianza es baja) son estados distintos y el frontend los trata
 * distinto: colapsarlos convertiría una duda en una certeza.
 */
export type ColumnMappingPlanContract = {
  data_kind: string;
  raw_columns: string[];
  auto_detected: Record<string, string | null>;
  roles: Record<string, string | null>;
  overridden: Record<string, string>;
  invalid_overrides: Record<string, string>;
  required_roles: string[];
  optional_roles: string[];
  missing_required: string[];
  needs_mapping: boolean;
  /**
   * `high` | `medium` | `low`. Va como cadena y no como enumerado a propósito: el backend
   * NO lo valida contra un dominio cerrado, y cerrarlo aquí convertiría un valor
   * inesperado en un HTTP 500 en plena ingesta. Se estrecha al pintarlo, no al
   * transportarlo.
   */
  confidence: string;
  role_labels: Record<string, string>;
  literals: Record<string, string>;
  range_checks: Record<string, ColumnRangeCheck>;
  suspicions: ColumnSuspicion[];
  role_confidence: Record<string, string>;
  suggestions: Record<string, ColumnSuggestion>;
  needs_confirmation: boolean;
  questions: IngestQuestion[];
  inferred_literals: Record<string, InferredLiteral>;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type ColumnRangeCheck = {
  column: string;
  verdict: string;
  note?: string | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type ColumnSuggestion = {
  column: string;
  confidence: string;
  reason: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Segunda opinión por RANGO físico sobre el mapeo por nombre: es lo que caza
 * el clásico northing metido en `y` cuando `y` era profundidad.
 */
export type ColumnSuspicion = {
  role: string;
  column: string;
  kind: string;
  user_mapped: boolean;
  message: string;
  suggested_role?: string | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Una función que puede necesitar internet, tal como la declara el backend. */
export type ConnectivityFeature = {
  name: string;
  key: string;
  requires_internet: boolean;
  required_for_golden_path: boolean;
  /**
   * ¿Está lista para usarse? OJO: para el copiloto la clave la pone el usuario (BYO-key),
   * así que `configured:false` NO significa «no disponible» — hay que mirar
   * `user_supplied_key`.
   */
  configured: boolean;
  /** Hay una alternativa local que no necesita internet. */
  local_fallback: boolean;
  message: string;
  /**
   * La clave la aporta el usuario desde la interfaz. Sin este campo, `configured:false` se
   * lee como «no disponible», que es falso.
   */
  user_supplied_key?: boolean | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Honestidad offline. `probed` es SIEMPRE `false`: el resumen no toca la red.
 *
 * La Fase 9 midió que este endpoint devolvía `probed: true` sin haber abierto
 * jamás un socket. No se implementó el sondeo —meter red en el servicio que
 * certifica que el producto es offline es contradictorio—: se dice la verdad,
 * y `probe_requested` + `probe_note` explican por qué cuando alguien pide
 * `?probe=true`.
 */
export type ConnectivitySummaryResponse = {
  /** El camino dorado (ingesta→inversión→3D→export) funciona sin conexión. */
  golden_path_offline: boolean;
  golden_path_note: string;
  /**
   * SIEMPRE `false`: este resumen no abre un socket jamás. Antes devolvía `true` sin tocar
   * la red (defecto medido en la Fase 9).
   */
  probed: boolean;
  /** El cliente pidió `?probe=true`. */
  probe_requested: boolean | null;
  /** Por qué no se sondeó pese a pedirlo. */
  probe_note: string | null;
  online_features: ConnectivityFeature[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * F5 — Curva de 'convergencia' YA calculada por el solver: el barrido de λ
 * (Morozov chi² discrepancy) usado para seleccionar la regularización. NO es
 * chi² por iteración interna de un único solve (esa serie no se persiste
 * estructuradamente hoy — ver docs/01_PLAN_MAESTRO.md F5); es honesto sobre
 * qué mide cada punto.
 */
export type ConvergenceResponse = {
  available: boolean;
  selection_method: string | null;
  lambda_selected: number | null;
  chi2_achieved: number | null;
  n_solves: number | null;
  trials: ConvergenceTrial[];
  warnings: string[];
  note: string;
};

/** Un candidato λ probado por el barrido Morozov, con su chi² resultante. */
export type ConvergenceTrial = {
  lambda_value: number;
  chi2_reduced: number | null;
};

export type CoordSystemDetection = {
  detected: string;
  confidence: string;
  warning: string | null;
  utm_zone: string | null;
  utm_hemisphere: string | null;
  epsg_code: number | null;
  crs_source: string;
};

export type CoordinateTransform = {
  version: string;
  input_coordinate_system: string;
  input_confidence: string;
  method: string;
  origin_strategy: string;
  origin_input_coordinates: Record<string, unknown>;
  x_min_raw: number | null;
  z_min_raw: number | null;
  x_max_raw: number | null;
  z_max_raw: number | null;
  x_extent_m: number;
  z_extent_m: number;
  transformed: boolean;
  warnings: string[];
  precision_notes: string[];
  utm_zone: string | null;
  utm_hemisphere: string | null;
  epsg_code: number | null;
  crs_source: string;
  absolute_origin: Record<string, number> | null;
};

export type CorrectedStation = {
  station_id: string;
  lat_deg: number;
  lon_deg: number;
  elev_m: number;
  g_obs_mgal: number;
  gamma_mgal: number | null;
  fac_mgal: number | null;
  bc_mgal: number | null;
  tc_mgal: number | null;
  g_bouguer_mgal: number;
  uncertainty_mgal: number;
  gravity_type: string;
};

export type CorrectionReport = {
  n_stations: number;
  corrections_applied: string[];
  reduction_density_gcc: number;
  dem_source: string | null;
  terrain_radius_m: number | null;
  fac_min_mgal: number | null;
  fac_max_mgal: number | null;
  bc_min_mgal: number | null;
  bc_max_mgal: number | null;
  tc_min_mgal: number | null;
  tc_max_mgal: number | null;
  g_bouguer_min_mgal: number | null;
  g_bouguer_max_mgal: number | null;
  tide_min_mgal: number | null;
  tide_max_mgal: number | null;
  drift_rate_mgal_per_day: number | null;
  drift_closure_mgal: number | null;
  drift_n_base: number | null;
  warnings: string[];
};

export type CsvAnalysisResult = {
  version: string;
  observation_count: number;
  spatial_extent: SpatialExtent;
  sampling: SamplingStats;
  gravity_stats: GravityStats;
  duplicates: DuplicateInfo;
  outliers: OutlierInfo;
  units: UnitDetection;
  coordinate_system: CoordSystemDetection;
  coordinate_transform: CoordinateTransform | null;
  auto_grid: AutoGrid | null;
  warnings: string[];
  quality_label: string;
  data_quality: DataQualityScore | null;
  has_elevation_column: boolean;
  has_uncertainty_column: boolean;
  has_instrument_metadata: boolean;
  has_corrections_metadata: boolean;
  professional_columns_detected: string[];
  professional_columns_with_values: string[];
};

/**
 * Fase 19 Tarea 5 — Data Quality Score numérico 0–100.
 *
 * Score ponderado derivado de CsvAnalysisResult (no recalcula física):
 *   completeness 50% · spatial_distribution 20% · noise_level 15% ·
 *   resolution 10% · outlier_fraction 5%.
 * Cada componente es un sub-score 0–100; `score` es la suma ponderada.
 * `interpretation`: GOOD (≥75) · MEDIOCRE (≥50) · POOR (<50).
 */
export type DataQualityScore = {
  version: string;
  score: number;
  interpretation: string;
  completeness: number;
  spatial_distribution: number;
  noise_level: number;
  resolution: number;
  outlier_fraction: number;
  weights: Record<string, number>;
  notes: string[];
};

/**
 * Lo que va DENTRO del ZIP de diagnóstico, para poder mirarlo antes de
 * descargarlo: es lo que hace comprobable la promesa de que no sale ningún
 * dato de survey.
 *
 * `system`, `packages` y `config_sanitized` son mapas abiertos a propósito: su
 * contenido depende de la máquina y de las variables presentes, y tabularlo
 * aquí sería una lista que se queda vieja sin que nadie se entere.
 */
export type DiagnosticManifestResponse = {
  system: Record<string, unknown>;
  packages: Record<string, string>;
  config_sanitized: Record<string, unknown>;
  connectivity: ConnectivitySummaryResponse;
  license: Record<string, unknown>;
  recent_errors: Record<string, unknown>[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type DuplicateInfo = {
  exact_count: number;
  near_count: number;
  tolerance_m: number;
  examples: Record<string, unknown>[];
};

/**
 * DOS respuestas distintas por la misma puerta, y el discriminante es
 * `needs_mapping`:
 *
 * * `needs_mapping: true` → **no se enriqueció nada**; vienen `column_mapping`
 *   y `sniff_report` para que el usuario asigne roles o conteste las preguntas
 *   bloqueantes, y `package_text` NO existe.
 * * ausente/`false` → vino el paquete: `package_text` + `enrichment_summary`.
 *
 * Un modelo único con todo opcional es lo máximo que OpenAPI expresa aquí sin
 * mentir; el frontend conserva la unión discriminada, que es MÁS precisa, y un
 * test comprueba que sus dos variantes existen en este contrato.
 */
export type EnrichPackageResponse = {
  needs_mapping?: boolean | null;
  needs_confirmation?: boolean | null;
  column_mapping?: ColumnMappingPlanContract | null;
  sample_rows?: Record<string, unknown>[] | null;
  filename?: string | null;
  package_text?: string | null;
  enrichment_summary?: Record<string, unknown> | null;
  plan?: Record<string, unknown> | null;
  needs_context?: Record<string, unknown>[] | null;
  n_stations?: number | null;
  sniff_report?: SniffReportContract | null;
  warnings: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Structured error information for task failures. */
export type ErrorDetails = {
  code: string | null;
  message: string;
  source: string | null;
  stage: string | null;
  details: Record<string, unknown> | null;
  traceback: string | null;
};

/** Background inversion start response (async task). */
export type GeophysicsInversionStartResponse = {
  status?: string;
  project_id?: string | null;
  run_id?: string | null;
  task_id?: string | null;
  message?: string;
  warnings?: string[];
};

/**
 * Inversion status polling response.
 *
 * F3: el pattern histórico (queued|processing|done|error) NO incluía
 * "running" — exactamente lo que escribe el solver durante la inversión
 * (heartbeat solving_lsqr) → el polling devolvía 500 de validación en plena
 * corrida. Se amplía con los estados reales + los terminales de F3
 * (cancelled / interrumpida).
 */
export type GeophysicsStatusResponse = {
  status: string;
  stage: string;
  progress: number | null;
  project_id: string | null;
  run_id: string | null;
  result: GravityImportInvertResponse | null;
  error_details: ErrorDetails | null;
  error: string | null;
  error_type: string | null;
  traceback: string | null;
  estimated_time_remaining_seconds: number | null;
  message: string | null;
};

/** Inversion response: complete pipeline result. */
export type GravityImportInvertResponse = {
  status: string;
  stage: string;
  project_id: string | null;
  run_id: string | null;
  georef: Record<string, unknown> | null;
  spatial_readiness: SpatialReadiness | null;
  regional_scale_preflight: RegionalScalePreflight | null;
  import_metadata: GravityImportMetadata | null;
  csv_analysis: CsvAnalysisResult | null;
  coordinate_transform: CoordinateTransform | null;
  auto_grid: AutoGrid | null;
  inversion_result: InversionMetadata | null;
  r3_enrichment: R3EnrichmentStatus | null;
  import_persistence: ImportPersistenceStatus | null;
  grid_auto_adapt: GridAutoAdapt | null;
  errors: string[];
  warnings: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type GravityImportMetadata = {
  source_file: string;
  schema_version: string;
  unit_original: string | null;
  unit_internal: string;
  gravity_column_used: string | null;
  gravity_type: string | null;
  conversion_applied: boolean;
  row_count: number;
  valid_rows: number;
  rejected_rows: number;
  warnings: string[];
  errors: string[];
  is_demo: boolean;
  csv_analysis: CsvAnalysisResult | null;
  coordinate_transform: CoordinateTransform | null;
  auto_grid: AutoGrid | null;
  estimated_mean_spacing_m: number | null;
  estimated_depth_resolution_m: number | null;
  geological_context_hint: string | null;
  honesty_note: string | null;
};

/** CSV preview response: analysis + gates, no inversion. */
export type GravityImportPreviewResponse = {
  status: string;
  stage: string;
  csv_analysis: CsvAnalysisResult | null;
  coordinate_transform: CoordinateTransform | null;
  spatial_readiness: SpatialReadiness | null;
  regional_scale_preflight: RegionalScalePreflight | null;
  octree_params: Record<string, unknown> | null;
  import_metadata: GravityImportMetadata | null;
  errors: string[];
  warnings: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type GravityStats = {
  min: number | null;
  max: number | null;
  mean: number | null;
  std: number | null;
  p5: number | null;
  p95: number | null;
};

/** Grid adaptation metadata (auto vs frontend-requested). */
export type GridAutoAdapt = {
  applied: boolean;
  reason: string | null;
  frontend_requested: Record<string, number> | null;
  effective_used: Record<string, number> | null;
  total_voxels: number;
};

/**
 * Latido + IDENTIDAD del proceso (Fase 2, H-19).
 *
 * `instance_token` se OMITE cuando el proceso no recibió token por entorno —
 * nunca se inventa. Por eso es opcional y no `""`.
 */
export type HealthResponse = {
  status?: string;
  service: string;
  version: string;
  pid: number;
  instance_token?: string | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Una corrida registrada en SQLite (`services/project_store`).
 *
 * Sobrevive a reinicios del backend, a diferencia de `GET /project-runs` que
 * escanea disco. `status` distingue `done` / `error` / `cancelled` / la corrida
 * interrumpida por un cierre del proceso.
 */
export type HistoryRun = {
  project_id: string;
  run_id: string;
  /**
   * `done` | `error` | `cancelled`, y también la corrida interrumpida por un cierre del
   * proceso: sobrevive a reinicios del backend.
   */
  status: string;
  source?: string | null;
  route?: string | null;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  config?: Record<string, unknown> | null;
  artifacts?: Record<string, unknown> | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * `found:false` con `run:null` es una respuesta LEGÍTIMA (HTTP 200), no un
 * error: preguntar por una corrida que no existe no es fallar.
 */
export type HistoryRunDetailResponse = {
  run: HistoryRun | null;
  found: boolean;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type HistoryRunsResponse = {
  runs: HistoryRun[];
  count: number;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Parquet and file I/O persistence status. */
export type ImportPersistenceStatus = {
  persisted: boolean;
  source_gravity_path: string | null;
  metadata_path: string | null;
  warnings: string[];
};

export type InferredLiteral = {
  value: string;
  source_column: string;
  note: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Pregunta ESTRUCTURADA (F2.4): un dato no-derivable se pregunta, jamás se
 * adivina. `blocking` es la diferencia entre «avísame» y «no sigo sin esto».
 */
export type IngestQuestion = {
  key: string;
  target: string;
  kind: string;
  blocking: boolean;
  question: string;
  options: IngestQuestionOption[];
  reason: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Una opción de respuesta. El backend las emite como `{value, label}`. */
export type IngestQuestionOption = {
  value: string;
  label: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Solver fit statistics. */
export type InversionDiagnostics = {
  rmse_misfit: number | null;
  normalized_rmse: number | null;
  l2_norm: number | null;
  data_coverage: number | null;
  convergence_status: string;
  iterations: number;
  regularization_lambda: number | null;
};

/** Inversion execution metadata. */
export type InversionMetadata = {
  solver_type: string | null;
  lambda_mag: number | null;
  alpha_spatial: number | null;
  depth_beta: number | null;
  diagnostics: InversionDiagnostics | null;
};

/**
 * `POST /license/activate`.
 *
 * Es el estado de licencia **sin `mode`** (medido: `activate_license()` no lo
 * añade) y **con `activated`**. Y `activated` es la única condición de éxito:
 * un token inválido responde **HTTP 200**, y existe el caso real
 * `valid:true` + `activated:false` (licencia buena que no se pudo escribir en
 * disco, con `reason` sobreescrito por el motivo).
 */
export type LicenseActivationResponse = {
  valid: boolean;
  tier: string;
  reason: string;
  licensee: string | null;
  product: string | null;
  issued_at: string | null;
  expires_at: string | null;
  expired: boolean;
  source: string;
  effective_tier: string;
  limits: LicenseLimits | null;
  /**
   * LA condición de éxito. Un token inválido responde HTTP 200 con `activated:false`, así
   * que mirar el código de estado no basta. Y existe `valid:true` + `activated:false`:
   * licencia buena que no se pudo escribir en disco, con `reason` sobreescrito por el
   * motivo.
   */
  activated: boolean;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Límites tabulados del tier efectivo.
 *
 * OJO — `max_voxels` lo DECLARA el token; hoy **ninguna inversión lo
 * comprueba** (`check_voxel_budget` no tiene llamador de producción, medido en
 * la Fase 9). El panel lo rotula así; el contrato no promete un tope que no
 * existe.
 */
export type LicenseLimits = {
  /**
   * Lo DECLARA el token; hoy ninguna inversión lo comprueba (`check_voxel_budget` no tiene
   * llamador de producción, medido en la Fase 9). No prometer un tope que no se aplica.
   */
  max_voxels?: number | null;
  watermark?: boolean;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * `GET /license/status`.
 *
 * `tier` es cadena LIBRE dentro del token firmado: `license_service` no la
 * valida contra un enumerado y sólo hay límites tabulados para
 * `local`/`pro`/`free`. Cerrarla aquí sería inventar un contrato.
 */
export type LicenseStatusResponse = {
  valid: boolean;
  /**
   * Cadena LIBRE dentro del token firmado: el backend no la valida contra un enumerado y
   * sólo hay límites tabulados para `local`/`pro`/`free`. Cerrarla en el cliente sería
   * inventar.
   */
  tier: string;
  /** Motivo en español escrito por el backend: la única explicación del estado. */
  reason: string;
  licensee: string | null;
  product: string | null;
  issued_at: string | null;
  /** ISO-8601, o `null` = licencia perpetua. */
  expires_at: string | null;
  expired: boolean;
  /**
   * De dónde salió el token vigente: `env` | `file` | `none`. `env` GANA sobre el archivo
   * que escribe /license/activate, así que activar desde la UI puede quedar anulado en
   * silencio — el panel lo avisa.
   */
  source: string;
  effective_tier: string;
  limits: LicenseLimits | null;
  /** `licensed` | `local_free`. SÓLO en /status: /license/activate no devuelve este campo. */
  mode: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type LoadPackagePoll = {
  status_url?: string | null;
  cancel_url?: string | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * TRES respuestas por la misma puerta, discriminadas por `status`:
 *
 * * `error`   → falló la importación; `stage:"import"`, `errors` poblado.
 * * `queued`  → **el camino por defecto**. La inversión se encoló en un worker
 *   de proceso y el progreso viaja por `GET /geophysics-status`. Se hizo así
 *   porque una inversión larga por HTTP síncrono acababa en «error interno del
 *   proxy» — el fallo se veía como un bug y era un timeout.
 * * `done`    → ruta síncrona; trae `inversionResult` **sin `voxels`** (el
 *   modelo se pide aparte por Arrow/JSON, no cabe en esta respuesta).
 */
export type LoadPackageResponse = {
  status: string;
  stage?: string | null;
  project_id?: string | null;
  run_id?: string | null;
  route?: string | null;
  multimodal_plan?: Record<string, unknown> | null;
  budget?: Record<string, unknown> | null;
  poll?: LoadPackagePoll | null;
  inversionResult?: Record<string, unknown> | null;
  warnings: string[];
  errors: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Full misfit report: per-station obs/calc + aggregate fit statistics. */
export type MisfitResponse = {
  stations: MisfitStationData[];
  chi2_reduced: number;
  rmse: number;
  normalized_rmse: number;
  r2: number;
  n_stations: number;
};

/** Observed vs. calculated data for a single gravity station. */
export type MisfitStationData = {
  x: number | null;
  y: number | null;
  z: number | null;
  d_obs: number;
  d_pred: number;
  residual: number;
};

export type MultimodalPlanResponse = {
  has_gravity: boolean;
  has_magnetic: boolean;
  has_borehole: boolean;
  n_sensors: number;
  plan: Record<string, unknown> | null;
  insufficient_reason: string | null;
};

export type OutlierInfo = {
  count: number;
  method: string;
  examples: Record<string, unknown>[];
};

export type ParseBoreholeCsvResponse = {
  survey: BoreholeSurvey;
  n_holes: number;
  n_samples: number;
  n_with_density: number;
  n_with_susceptibility: number;
  n_with_lithology: number;
  lithologies_detected: string[];
  unrecognized_lithologies: string[];
};

/**
 * Filas COMPLETAS ya parseadas por el pipeline oficial.
 *
 * Existe para que el frontend NO parsee CSV en TypeScript: hacerlo duplicaría
 * el sniffer y reintroduciría el bug decimal-coma (`parseFloat("1,23")` = 1, en
 * silencio) que ya costó una corrupción de datos medida.
 */
export type ParseRowsResponse = {
  headers: string[];
  rows: Record<string, unknown>[];
  n_rows: number;
  truncated: boolean;
  sniff_report: SniffReportContract;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/** Percentile statistics for diagnostic display. */
export type PercentileStats = {
  p2?: number | null;
  p5?: number | null;
  p50?: number | null;
  p85?: number | null;
  p90?: number | null;
  p95?: number | null;
  p98?: number | null;
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  std?: number | null;
  threshold?: number | null;
  is_degenerate?: boolean;
  degenerate_reason?: string | null;
};

/** R3 Enrichment (elevation/DEM integration) status. */
export type R3EnrichmentStatus = {
  attempted: boolean;
  terrain_persisted: boolean;
  enrichment_status: string | null;
  has_elevation_data: boolean;
  warnings: string[];
};

export type RegionalScalePreflight = {
  version: string;
  scale_class: string;
  can_run_single_inversion: boolean;
  requires_user_acknowledgement: boolean;
  recommended_action: string;
  extent_x_m: number | null;
  extent_z_m: number | null;
  area_km2: number | null;
  station_count: number | null;
  estimated_nx: number | null;
  estimated_ny: number | null;
  estimated_nz: number | null;
  estimated_voxel_count: number | null;
  estimated_depth_m: number | null;
  estimated_block_size_m: number | null;
  max_allowed_nx: number;
  max_allowed_ny: number;
  max_allowed_nz: number;
  warnings: string[];
  blocked_reasons: string[];
  allowed_outputs: string[];
  suggested_tile_size_m: number | null;
  suggested_subset_bbox: Record<string, number> | null;
  rationale: string;
};

export type SamplingStats = {
  area_km2?: number;
  mean_spacing_m?: number | null;
  point_density_per_km2?: number | null;
};

export type SniffBrokenRow = {
  line_number: number;
  field_count: number;
  expected_fields: number;
  excerpt: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Una detección CON EVIDENCIA. `evidence` es texto para el usuario: es lo
 * que convierte «detecté coma decimal» en algo que se puede contradecir.
 */
export type SniffDetection = {
  value: string;
  confidence: string;
  evidence: string;
  discarded: SniffDiscarded[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type SniffDiscarded = {
  value: string;
  reason: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type SniffPreambleLine = {
  line_number: number;
  text: string;
  reason: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

/**
 * Espejo de `services.csv_sniffer_service.SniffReport.to_dict()`.
 *
 * El sufijo `Contract` evita que el nombre choque con la `@dataclass` del
 * servicio: son dos cosas distintas —una calcula, la otra describe el cable— y
 * confundirlas fue lo que multiplicó las declaraciones que H-16 contó.
 */
export type SniffReportContract = {
  version: string;
  filename: string;
  encoding: SniffDetection;
  separator: SniffDetection;
  decimal: SniffDetection;
  preamble_count: number;
  preamble_lines: SniffPreambleLine[];
  header_line_number: number | null;
  header_columns: string[];
  broken_rows: SniffBrokenRow[];
  broken_row_count: number;
  n_lines_sampled: number;
  sample_truncated: boolean;
  warnings: string[];
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type SpatialExtent = {
  x_min: number | null;
  x_max: number | null;
  y_min: number | null;
  y_max: number | null;
  z_min: number | null;
  z_max: number | null;
  x_span: number | null;
  y_span: number | null;
  z_span: number | null;
};

export type SpatialReadiness = {
  version: string;
  level: string;
  level_rank: number;
  can_run_3d_inversion: boolean;
  can_run_local_conceptual_inversion: boolean;
  can_use_dem: boolean;
  can_compute_voxel_masl: boolean;
  can_compute_voxel_latlon: boolean;
  requires_user_acknowledgement: boolean;
  required_acknowledgement: string | null;
  max_priority_class_allowed: string;
  max_favorability_score_allowed: number;
  missing_fields: string[];
  warnings: string[];
  allowed_outputs: string[];
  blocked_outputs: string[];
  rationale: string;
};

export type SystemPaths = {
  data_dir: string;
  projects_dir: string;
  tmp_dir: string;
  models_dir: string;
  block_model: string;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type SystemPathsExist = {
  data_dir: boolean;
  projects_dir: boolean;
  tmp_dir: boolean;
  models_dir: boolean;
  block_model: boolean;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type SystemStatusResponse = {
  status?: string;
  service: string;
  version: string;
  host: string;
  port: number;
  paths: SystemPaths;
  exists: SystemPathsExist;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};

export type UnitDetection = {
  declared: string | null;
  value_range_consistent: boolean;
  confidence: string;
  warning: string | null;
};

/** Single voxel in block model. */
export type VoxelData = {
  x?: number | null;
  y?: number | null;
  z?: number | null;
  cx?: number | null;
  cy?: number | null;
  cz?: number | null;
  density?: number | null;
  rho?: number | null;
  probability?: number | null;
  visual_score?: number | null;
  /** Grade (%): NOT computed by TerraQuantum. Placeholder for external mining software. */
  grade?: number | null;
  domain?: number | null;
  /** Tonnage (tonnes): NOT computed by TerraQuantum. Placeholder for external mining software. */
  tonnage?: number | null;
  is_active?: boolean | null;
  lat?: number | null;
  lon?: number | null;
  voxel_elevation_masl?: number | null;
  surface_elevation_masl?: number | null;
  depth_below_surface_m?: number | null;
  susceptibility?: number | null;
  normalized_sensitivity?: number | null;
  sensitivity_proxy?: number | null;
  anomaly_intensity?: number | null;
  target_score?: number | null;
  modeled_density_index?: number | null;
  density_anomaly_score?: number | null;
  doi_index?: number | null;
  posterior_std?: number | null;
  joint_structural_score?: number | null;
  real_grade?: number | null;
  /** `extra="allow"`: el endpoint emite además campos que el contrato no fija. */
  [key: string]: unknown;
};
