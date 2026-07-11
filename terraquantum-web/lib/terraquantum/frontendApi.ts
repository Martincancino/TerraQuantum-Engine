import { BackendInvertResponse } from "./geophysicsModel";
import type { TerrainResponse } from "../terraQuantumGeology";
import type { FavorabilityResult } from "../../componentes/datos/favorability_types";
import { useAppStore } from "../../store/useAppStore";
import type { BlockModelDataMode } from "../../store/useAppStore";

export const BACKEND_PUBLIC_URL =
  process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL ||
  process.env.TERRAQUANTUM_BACKEND_URL ||
  "http://127.0.0.1:8010";

// Tipo seguro para valores JSON arbitrarios
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type BlockModelResponse = {
  [key: string]: JsonValue;
  cells: JsonValue[];
  total_voxels: number | null;
  stored_voxels: number | null;
  anomaly_voxels: number | null;
  returned_voxels: number | null;
  mode: string | null;
  warnings: string[];
  totalVoxels: number | null;
  storedVoxels: number | null;
  anomalyVoxels: number | null;
  returnedVoxels: number | null;
  blockModelMode: string | null;
};

// Fase 10 v0.4.0 — Out-of-core Zarr types
export type BlockModelZarrInfo = {
  zarr_path: string;
  total_voxels: number;
  chunk_count: number;
  chunk_size_voxels: number;
  memory_footprint_mb: number;
  working_memory_mb: number;
};

export type BlockModelZarrMetadata = {
  metadata_only: boolean;
  total_voxels: number;
  chunk_count: number;
  chunk_size_voxels: number;
  bounds: {
    x_min: number; x_max: number;
    y_min: number; y_max: number;
    z_min: number; z_max: number;
  };
  project_id: string;
  run_id: string;
};

export type BlockModelZarrChunk = {
  chunk_idx: number;
  voxel_count: number;
  total_voxels: number;
  chunk_count: number;
  voxels: Array<{
    cx: number; cy: number; cz: number;
    density: number; susceptibility: number; doi_index: number;
  }>;
};

export type FrontendApiResult<T> = {
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
};

export type CompareRunsParams = {
  baseProjectId: string;
  baseRunId: string;
  compareProjectId: string;
  compareRunId: string;
};

export type SensitivitySweepPayload = unknown;

export type SensitivitySweepCase = {
  case_id?: string;
  lambda_mag?: number;
  alpha_spatial?: number;
  fit_level?: string;
  fit_quality?: number;
  normalized_rmse?: number;
  residual_rmse?: number;
  residual_mae?: number;
  residual_bias?: number;
  residual_l2?: number;
};

export type SensitivitySweepResult = {
  status: string;
  case_count: number;
  best_case: SensitivitySweepCase | null;
  cases: SensitivitySweepCase[];
  recommendation: string;
  warnings: string[];
};

// ─── R3 Elevation types ───────────────────────────────────────────────────

export type ElevationRange = {
  min_voxel_elevation_masl?: number | null;
  max_voxel_elevation_masl?: number | null;
  min_surface_elevation_masl?: number | null;
  max_surface_elevation_masl?: number | null;
  min_depth_below_surface_m?: number | null;
  max_depth_below_surface_m?: number | null;
};

export type VoxelElevationFields = {
  lat?: number | null;
  lon?: number | null;
  surface_elevation_masl?: number | null;
  depth_below_surface_m?: number | null;
  voxel_elevation_masl?: number | null;
  georef_confidence?: string | null;
  dem_source?: string | null;
  dem_sample_method?: string | null;
  spatial_reference_warning?: string | null;
};

export type BlockModelElevationMeta = {
  has_elevation_data?: boolean;
  dem_source?: string | null;
  georef_confidence?: string | null;
  elevation_range?: ElevationRange | null;
};

// ─── Percentile Stats (modelo completo, del backend) ──────────────────────

export type PercentileStats = {
  density_p2?: number | null;
  density_p5?: number | null;
  density_p50?: number | null;
  density_p85?: number | null;
  density_p90?: number | null;
  density_p95?: number | null;
  density_p98?: number | null;
  visual_score_p2?: number | null;
  visual_score_p5?: number | null;
  visual_score_p50?: number | null;
  visual_score_p85?: number | null;
  visual_score_p90?: number | null;
  visual_score_p95?: number | null;
  visual_score_p98?: number | null;
  relative_target_score_p2?: number | null;
  relative_target_score_p5?: number | null;
  relative_target_score_p50?: number | null;
  relative_target_score_p85?: number | null;
  relative_target_score_p90?: number | null;
  relative_target_score_p95?: number | null;
  relative_target_score_p98?: number | null;
  is_degenerate: boolean;
  degenerate_reason?: string | null;
  professional_threshold?: number | null;
  professional_high_threshold?: number | null;
  professional_extreme_threshold?: number | null;
};

// ─── CRS types (R2-FE) ────────────────────────────────────────────────────

export type CrsSource = "user_declared" | "csv_column" | "inferred" | "missing";
export type CrsConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING";

export type CrsInfo = {
  input_crs?: string | null;
  epsg_code?: number | null;
  crs_source?: CrsSource | string | null;
  crs_confidence?: CrsConfidence | string | null;
  utm_zone?: string | null;
  utm_hemisphere?: string | null;
};

// ─── Georef types (R1-FE-1) ────────────────────────────────────────────────

export type GeorefConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING";

export type FootprintCorner = {
  lat: number | null;
  lon: number | null;
};

export type ProjectFootprint = {
  crs: string | null;
  type: string;
  source: string;
  confidence: GeorefConfidence | string;
  center_lat?: number | null;
  center_lon?: number | null;
  extent_x_m?: number | null;
  extent_z_m?: number | null;
  utm_zone?: string | null;
  sw?: FootprintCorner | null;
  se?: FootprintCorner | null;
  ne?: FootprintCorner | null;
  nw?: FootprintCorner | null;
  warnings?: string[];
  precision_notes?: string[];
  utm_hemisphere?: string | null;
  epsg_code?: number | null;
  crs_source?: string | null;
  crs_confidence?: string | null;
};

export type GeorefSummary = {
  confidence: GeorefConfidence | string;
  type: string;
  source?: string;
  utm_zone?: string | null;
  warnings?: string[];
  footprint?: ProjectFootprint | null;
  utm_hemisphere?: string | null;
  epsg_code?: number | null;
  input_crs?: string | null;
  crs_source?: string | null;
  crs_confidence?: string | null;
};

export type ProjectFootprintResponse = {
  project_id: string;
  georef_confidence: GeorefConfidence | string;
  georef_type: string;
  footprint: ProjectFootprint | null;
  coordinate_system_detected?: string | null;
  utm_zone?: string | null;
  warnings?: string[];
  source_run_id?: string | null;
};

// ─── Regional Scale Preflight types (R3.7-C/D) ────────────────────────────

export type RegionalScalePreflight = {
  version?: string;
  scale_class?: string;
  can_run_single_inversion?: boolean;
  requires_user_acknowledgement?: boolean;
  recommended_action?: string;
  extent_x_m?: number | null;
  extent_z_m?: number | null;
  area_km2?: number | null;
  station_count?: number | null;
  estimated_nx?: number | null;
  estimated_ny?: number | null;
  estimated_nz?: number | null;
  estimated_voxel_count?: number | null;
  estimated_depth_m?: number | null;
  estimated_block_size_m?: number | null;
  max_allowed_nx?: number;
  max_allowed_ny?: number;
  max_allowed_nz?: number;
  warnings?: string[];
  blocked_reasons?: string[];
  allowed_outputs?: string[];
  suggested_tile_size_m?: number | null;
  suggested_subset_bbox?: Record<string, number> | null;
  rationale?: string;
};

export type RegionalScaleGateError = {
  error?: string;
  scale_class?: string;
  message?: string;
  required_action?: string;
  recommended_action?: string;
  blocked_reasons?: string[];
  warnings?: string[];
  allowed_outputs?: string[];
  regional_scale_preflight?: RegionalScalePreflight | null;
};

// ─── Spatial Readiness types (R3.5-F) ─────────────────────────────────────

export type SpatialReadiness = {
  version?: string;
  level?: string;
  level_rank?: number;
  can_run_3d_inversion?: boolean;
  can_run_local_conceptual_inversion?: boolean;
  can_use_dem?: boolean;
  can_compute_voxel_masl?: boolean;
  can_compute_voxel_latlon?: boolean;
  requires_user_acknowledgement?: boolean;
  required_acknowledgement?: string | null;
  max_priority_class_allowed?: string;
  max_favorability_score_allowed?: number;
  missing_fields?: string[];
  warnings?: string[];
  allowed_outputs?: string[];
  blocked_outputs?: string[];
  rationale?: string;
};

export type SpatialReadinessGateError = {
  error?: string;
  level?: string;
  message?: string;
  required_acknowledgement?: string | null;
  missing_fields?: string[];
  blocked_outputs?: string[];
  allowed_outputs?: string[];
  rationale?: string;
  required_action?: string | null;
};

// ──────────────────────────────────────────────────────────────────────────

function isJsonRecord(value: JsonValue | null): value is { [key: string]: JsonValue } {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function readNullableNumber(
  record: { [key: string]: JsonValue },
  keys: string[]
): number | null {
  for (const key of keys) {
    const value = record[key];

    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }

    if (typeof value === "string" && value.trim() !== "") {
      const n = Number(value);
      if (Number.isFinite(n)) return n;
    }
  }

  return null;
}

function readNullableString(
  record: { [key: string]: JsonValue },
  keys: string[]
): string | null {
  for (const key of keys) {
    const value = record[key];

    if (typeof value === "string" && value.trim() !== "") {
      return value;
    }
  }

  return null;
}

function normalizeBlockModelResponse(
  data: JsonValue | null,
  fallbackMode: string
): BlockModelResponse | null {
  if (!isJsonRecord(data)) return null;

  const cells = Array.isArray(data.cells) ? data.cells : [];
  const totalVoxels = readNullableNumber(data, ["total_voxels", "totalVoxels", "totalRows"]);
  const storedVoxels = readNullableNumber(data, ["stored_voxels", "storedVoxels", "totalRows"]);
  const anomalyVoxels = readNullableNumber(data, ["anomaly_voxels", "anomalyVoxels"]);
  const returnedVoxels =
    readNullableNumber(data, ["returned_voxels", "returnedVoxels", "returnedCells"]) ??
    cells.length;
  const blockModelMode =
    readNullableString(data, ["mode", "blockModelMode"]) || fallbackMode;
  const warnings = Array.isArray(data.warnings)
    ? data.warnings.filter((warning): warning is string => typeof warning === "string")
    : [];

  return {
    ...data,
    cells,
    total_voxels: totalVoxels,
    stored_voxels: storedVoxels,
    anomaly_voxels: anomalyVoxels,
    returned_voxels: returnedVoxels,
    mode: blockModelMode,
    warnings,
    totalVoxels,
    storedVoxels,
    anomalyVoxels,
    returnedVoxels,
    blockModelMode,
  };
}

function resolveBlockModelRequestArgs(
  modeOrLimit?: BlockModelDataMode | number,
  limit?: number
): { mode: BlockModelDataMode; limit: number } {
  if (typeof modeOrLimit === "number") {
    return { mode: "exploration", limit: modeOrLimit };
  }

  return {
    mode: modeOrLimit ?? "exploration",
    limit: limit ?? 5000,
  };
}

function syncVoxelTraceFromBlockModel(data: BlockModelResponse | null) {
  if (!data || typeof window === "undefined") return;

  useAppStore.getState().setVoxelTrace({
    totalVoxels: data.totalVoxels,
    storedVoxels: data.storedVoxels,
    anomalyVoxels: data.anomalyVoxels,
    returnedVoxels: data.returnedVoxels,
    blockModelMode: data.blockModelMode,
  });
}

function syncBlockModelElevationMeta(data: BlockModelResponse | null) {
  if (!data || typeof window === "undefined") return;

  const raw = data as Record<string, unknown>;
  const hasElevationData = raw.has_elevation_data === true;
  const demSource = typeof raw.dem_source === "string" ? raw.dem_source : null;
  const georefConfidence = typeof raw.georef_confidence === "string" ? raw.georef_confidence : null;

  let elevationRange: ElevationRange | null = null;
  if (raw.elevation_range && typeof raw.elevation_range === "object" && !Array.isArray(raw.elevation_range)) {
    elevationRange = raw.elevation_range as ElevationRange;
  }

  useAppStore.getState().setBlockModelElevationMeta({
    hasElevationData,
    demSource,
    georefConfidence,
    elevationRange,
  });
}

function syncPercentileStats(data: BlockModelResponse | null) {
  if (!data || typeof window === "undefined") return;

  const raw = data as Record<string, unknown>;
  const ps = raw.percentile_stats;

  if (!ps || typeof ps !== "object" || Array.isArray(ps)) {
    useAppStore.getState().setPercentileStats(null);
    return;
  }

  useAppStore.getState().setPercentileStats(ps as PercentileStats);
}

function finalizeBlockModelResult(
  result: FrontendApiResult<JsonValue>,
  fallbackMode: string
): FrontendApiResult<BlockModelResponse> {
  const data = normalizeBlockModelResponse(result.data, fallbackMode);

  if (result.ok && result.data) {
    // Validar schema de respuesta
    const validation = validateBlockModelResponse(result.data);
    if (!validation.valid) {
      console.warn(`[Schema Validation] BlockModelResponse: ${validation.errors.join("; ")}`);
    }

    syncVoxelTraceFromBlockModel(data);
    syncBlockModelElevationMeta(data);
    syncPercentileStats(data);
  }

  return { ...result, data };
}

// ─── Schema Validation Helpers ──────────────────────────────────────────────
function validateRequiredFields(obj: unknown, requiredFields: string[]): { valid: boolean; missing: string[] } {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    return { valid: false, missing: requiredFields };
  }

  const data = obj as Record<string, unknown>;
  const missing = requiredFields.filter((field) => !(field in data) || data[field] === undefined);

  return { valid: missing.length === 0, missing };
}

function validateBlockModelResponse(data: unknown): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    errors.push("Response must be a JSON object, not array or null");
    return { valid: false, errors };
  }

  const obj = data as Record<string, unknown>;

  // Validar campos mínimos
  const { valid, missing } = validateRequiredFields(obj, ["cells", "total_voxels"]);
  if (!valid) {
    errors.push(`Missing required fields: ${missing.join(", ")}`);
  }

  // Validar que cells sea array
  if (!Array.isArray(obj.cells)) {
    errors.push("Field 'cells' must be an array");
  }

  return { valid: errors.length === 0, errors };
}

function validateGeophysicsStatusResponse(data: unknown): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  const { valid, missing } = validateRequiredFields(data, ["status", "progress"]);
  if (!valid) {
    errors.push(`Missing required fields: ${missing.join(", ")}`);
  }

  if (typeof data === "object" && data !== null && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>;
    const validStatuses = ["queued", "processing", "done", "error"];
    if (obj.status && !validStatuses.includes(String(obj.status))) {
      errors.push(`Invalid status value: ${obj.status}. Must be one of: ${validStatuses.join(", ")}`);
    }
  }

  return { valid: errors.length === 0, errors };
}

async function fetchInternalJson<T>(options: {
  path: string;
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
}): Promise<FrontendApiResult<T>> {
  const { path, method = "GET", body, timeoutMs = 120_000 } = options;

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(path, {
      method,
      cache: "no-store",
      headers: {
        accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const rawText = await res.text();

    let data: JsonValue;

    try {
      data = rawText ? (JSON.parse(rawText) as JsonValue) : {};
    } catch {
      return {
        ok: false,
        status: res.status || 500,
        data: null,
        error: `La ruta ${path} no devolvió JSON válido.`,
      };
    }

    if (!res.ok) {
      const dataObj =
        data !== null && typeof data === "object" && !Array.isArray(data)
          ? (data as { [key: string]: JsonValue })
          : null;

      const nestedDetail =
        dataObj?.backendDetails !== null &&
        typeof dataObj?.backendDetails === "object" &&
        !Array.isArray(dataObj?.backendDetails)
          ? (dataObj.backendDetails as { [key: string]: JsonValue })?.detail
          : undefined;

      return {
        ok: false,
        status: res.status,
        data: data as T,
        error:
          (typeof dataObj?.detail === "string" ? dataObj.detail : null) ??
          (typeof dataObj?.error === "string" ? dataObj.error : null) ??
          (typeof nestedDetail === "string" ? nestedDetail : null) ??
          `La ruta ${path} falló con status ${res.status}.`,
      };
    }

    return {
      ok: true,
      status: res.status,
      data: data as T,
      error: null,
    };
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" ||
        error.message.toLowerCase().includes("aborted"));

    const message = error instanceof Error ? error.message : "unknown error";

    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      data: null,
      error: isTimeout
        ? `Timeout: ${path} tardó más de ${timeoutMs / 1000}s en responder.`
        : `Error conectando con ${path}: ${message}`,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

export function buildBackendAssetUrl(path: string, cacheBust = true) {
  if (!path) return "";

  const baseUrl = path.startsWith("http")
    ? path
    : `${BACKEND_PUBLIC_URL}${path.startsWith("/") ? path : `/${path}`}`;

  if (!cacheBust) return baseUrl;

  const separator = baseUrl.includes("?") ? "&" : "?";

  return `${baseUrl}${separator}t=${Date.now()}`;
}

export function buildTerrainTextureProxyUrl(rawUrl: string) {
  const cleanUrl = rawUrl.trim();
  if (!cleanUrl) return "";

  const targetUrl = cleanUrl.startsWith("http")
    ? cleanUrl
    : buildBackendAssetUrl(cleanUrl, false);

  return `/api/terrain-texture?url=${encodeURIComponent(targetUrl)}`;
}

// ─── H-C3: Obs vs Calc misfit types ─────────────────────────────────────────

export type MisfitStationData = {
  x: number | null;
  y: number | null;
  z: number | null;
  d_obs: number;
  d_pred: number;
  residual: number;
};

export type MisfitResponse = {
  stations: MisfitStationData[];
  chi2_reduced: number;
  rmse: number;
  normalized_rmse: number;
  r2: number;
  n_stations: number;
};

export async function getGeophysicsMisfit(projectId: string, runId: string) {
  return fetchInternalJson<MisfitResponse>({
    path: `/api/geophysics-misfit?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 30_000,
  });
}

export async function runGeophysicsInvert(payload: unknown) {
  return fetchInternalJson<BackendInvertResponse>({
    path: "/api/geophysics-invert",
    method: "POST",
    body: payload,
    timeoutMs: 120_000,
  });
}

export async function runGeophysicsSensitivitySweep(payload: SensitivitySweepPayload) {
  return fetchInternalJson<SensitivitySweepResult>({
    path: "/api/geophysics-sensitivity-sweep",
    // El barrido corre ~9 inversiones (build de kernel + diagnósticos) y supera
    // los 90s previos -> el cliente abortaba antes que el backend respondiera.
    // 5 min para igualar el timeout de la ruta BFF.
    timeoutMs: 300_000,
    body: payload,
  });
}

export async function getExplorationBlockModel(
  modeOrLimit: BlockModelDataMode | number = "exploration",
  limit = 5000
) {
  const request = resolveBlockModelRequestArgs(modeOrLimit, limit);
  const result = await fetchInternalJson<JsonValue>({
    path: `/api/block-model?mode=${encodeURIComponent(
      request.mode
    )}&limit=${encodeURIComponent(String(request.limit))}`,
    method: "GET",
    timeoutMs: 120_000,
  });

  return finalizeBlockModelResult(result, request.mode);
}

export async function getExplorationBlockModelForRun(
  projectId: string,
  runId: string,
  modeOrLimit: BlockModelDataMode | number = "exploration",
  limit = 5000
) {
  const request = resolveBlockModelRequestArgs(modeOrLimit, limit);
  const result = await fetchInternalJson<JsonValue>({
    path: `/api/block-model?mode=${encodeURIComponent(
      request.mode
    )}&limit=${encodeURIComponent(
      String(request.limit)
    )}&project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(
      runId
    )}`,
    method: "GET",
    timeoutMs: 120_000,
  });

  return finalizeBlockModelResult(result, request.mode);
}

// ─── Arrow IPC block model transport (QW-6) ──────────────────────────────────
// Usa fetchBlockModelArrowForRun (implementación completa con TypedArrays, ya
// definida más abajo) cuando limit > 5000. Fallback a JSON si Arrow falla.

export async function getExplorationBlockModelForRunWithArrow(
  projectId: string,
  runId: string,
  modeOrLimit: BlockModelDataMode | number = "exploration",
  limit = 5000,
  displayFactor = 1,
  lod: 'far' | 'medium' | 'full' = 'full',
): Promise<FrontendApiResult<BlockModelResponse>> {
  const request = resolveBlockModelRequestArgs(modeOrLimit, limit);

  // displayFactor>1 = sub-muestreo trilineal de display (500k-2M celdas): SIEMPRE
  // por Arrow (binario), el JSON no soporta ese tamaño.
  // lod!=full: always use Arrow path (spatial LOD requires binary transport).
  if (displayFactor > 1 || request.limit > 5000 || lod !== 'full') {
    const arrowResult = await fetchBlockModelArrowForRun(projectId, runId, request.mode, displayFactor, lod);
    if (arrowResult.ok) {
      return arrowResult;
    }
    console.warn("[QW-6] Arrow falló, fallback a JSON:", arrowResult.error);
  }

  const result = await fetchInternalJson<JsonValue>({
    path: `/api/block-model?mode=${encodeURIComponent(request.mode)}&limit=${encodeURIComponent(String(request.limit))}&project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 120_000,
  });

  return finalizeBlockModelResult(result, request.mode);
}

export async function getTerrainData(projectId: string) {
  return fetchInternalJson<TerrainResponse>({
    path: `/api/terrain?project_id=${encodeURIComponent(projectId)}`,
    method: "GET",
    timeoutMs: 30_000,
  });
}

export async function getProjectRuns() {
  return fetchInternalJson<JsonValue>({
    path: "/api/project-runs",
    method: "GET",
    timeoutMs: 30_000,
  });
}

export async function getProjectRunDetail(projectId: string, runId: string) {
  return fetchInternalJson<JsonValue>({
    path: `/api/project-run-detail?project_id=${encodeURIComponent(
      projectId
    )}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 30_000,
  });
}

export async function compareRuns(params: CompareRunsParams) {
  return fetchInternalJson<JsonValue>({
    path: `/api/compare-runs?base_project_id=${encodeURIComponent(
      params.baseProjectId
    )}&base_run_id=${encodeURIComponent(
      params.baseRunId
    )}&compare_project_id=${encodeURIComponent(
      params.compareProjectId
    )}&compare_run_id=${encodeURIComponent(params.compareRunId)}`,
    method: "GET",
    timeoutMs: 30_000,
  });
}

export function exportRunUrl(projectId: string, runId: string) {
  return `/api/export-run?project_id=${encodeURIComponent(
    projectId
  )}&run_id=${encodeURIComponent(runId)}`;
}

export function exportBundleUrl(projectId: string, runId: string) {
  return `${BACKEND_PUBLIC_URL}/export/bundle/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`;
}

export async function deleteRun(
  projectId: string,
  runId: string
): Promise<{ ok: boolean; error: string | null }> {
  const url = `${BACKEND_PUBLIC_URL}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`;
  try {
    const res = await fetch(url, {
      method: "DELETE",
      headers: {
        accept: "application/json",
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return { ok: false, error: text || `HTTP ${res.status}` };
    }
    return { ok: true, error: null };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Error desconocido" };
  }
}

export async function downloadTechnicalReport(
  projectId: string,
  runId: string
): Promise<{ ok: boolean; error: string | null }> {
  const path = `/api/export-report?project_id=${encodeURIComponent(
    projectId
  )}&run_id=${encodeURIComponent(runId)}`;

  try {
    const res = await fetch(path, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "text/html",
      },
    });

    if (!res.ok) {
      let error = `La ruta ${path} falló con status ${res.status}.`;

      try {
        const data = (await res.json()) as { detail?: unknown; error?: unknown };
        error =
          (typeof data.detail === "string" ? data.detail : null) ??
          (typeof data.error === "string" ? data.error : null) ??
          error;
      } catch {
        // Keep the status-based fallback when the response is not JSON.
      }

      return { ok: false, error };
    }

    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const filename =
      res.headers
        .get("content-disposition")
        ?.match(/filename="?([^"]+)"?/)?.[1] ||
      `reporte_tecnico_${projectId}_${runId}.html`;

    try {
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }

    return { ok: true, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, error: message || "Error de red" };
  }
}

export type GravityObservationPreview = {
  x_m: number;
  y_m: number;
  z_m: number;
  g: number;
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
  // Fase 5: resolución real y contexto geológico
  estimated_mean_spacing_m?: number;
  estimated_depth_resolution_m?: number;
  geological_context_hint?: string;
  honesty_note?: string;
};

export type CoordinateSystemDetection = {
  detected?: string;
  confidence?: string;
  warning?: string | null;
};

// Fase 19 Tarea 5 — Data Quality Score numérico 0–100.
export type DataQualityScore = {
  version?: string;
  score: number;
  interpretation: "GOOD" | "MEDIOCRE" | "POOR" | string;
  completeness: number;
  spatial_distribution: number;
  noise_level: number;
  resolution: number;
  outlier_fraction: number;
  weights?: Record<string, number>;
  notes?: string[];
};

// Fase 19 Tarea 1 — tipo de dato inferido desde columnas del CSV.
export type DataTypeDetection = {
  version?: string;
  detected_type: "gravity" | "magnetic" | "borehole" | "joint" | "ambiguous" | "unknown" | string;
  confidence: "high" | "medium" | "low" | string;
  has_gravity_column: boolean;
  has_magnetic_column: boolean;
  has_borehole_columns: boolean;
  is_joint_candidate: boolean;
  gravity_column?: string | null;
  magnetic_column?: string | null;
  signals?: string[];
  warning?: string | null;
};

export type CoordinateTransformData = {
  input_coordinate_system?: string;
  input_confidence?: string;
  method?: string;
  warnings?: string[];
  x_extent_m?: number;
  z_extent_m?: number;
};

export type GravityImportPreviewResponse = {
  status: "ok" | "error";
  previewCount: number;
  totalObservations: number;
  observationsPreview: GravityObservationPreview[];
  importMetadata: GravityImportMetadata;
  warnings: string[];
  errors: string[];
  csv_analysis?: {
    coordinate_system?: CoordinateSystemDetection | null;
    quality_label?: string | null;
    data_quality?: DataQualityScore | null;
  } | null;
  coordinate_transform?: CoordinateTransformData | null;
  // Fase 19 Tarea 1 — auto-detección de tipo de CSV.
  detected_data_type?: DataTypeDetection | null;
  georef_preview?: GeorefSummary;
  spatial_readiness?: SpatialReadiness | null;
  regional_scale_preflight?: RegionalScalePreflight | null;
};

export async function previewGravityCsv(
  file: File,
  options?: { strict?: boolean; allowGRaw?: boolean; previewLimit?: number; dataType?: "gravity" | "magnetic" }
): Promise<FrontendApiResult<GravityImportPreviewResponse>> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.strict !== undefined) formData.append("strict", String(options.strict));
  if (options?.allowGRaw !== undefined) formData.append("allow_g_raw", String(options.allowGRaw));
  if (options?.previewLimit !== undefined) formData.append("preview_limit", String(options.previewLimit));
  if (options?.dataType) formData.append("data_type", options.dataType);

  try {
    const res = await fetch("/api/gravity-import/preview", {
      method: "POST",
      body: formData,
    });
    let data;
    try {
      data = await res.json();
    } catch {
      return { ok: false, status: res.status, data: null, error: "Respuesta no es JSON." };
    }
    if (!res.ok) {
      return { ok: false, status: res.status, data: null, error: data?.detail || `Error ${res.status}` };
    }
    return { ok: true, status: res.status, data: data as GravityImportPreviewResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message || "Error de red" };
  }
}

// ─── Advanced Inversion Params (Fase 7B) ──────────────────────────────────────

export type PgiParamsPayload = {
  /** Dummy components required by backend schema (ignored when fit_from_model=true). */
  components: Array<{ mean_density_t_m3: number; std_density_t_m3: number; weight: number }>;
  alpha_pgi: number;
  max_iter: number;
  convergence_tol: number;
  fit_from_model: true;
  n_components_auto: number;
};

export type MagneticRemanencePayload = {
  enabled: boolean;
  q_ratio: number;
  remanence_inc_deg: number;
  remanence_dec_deg: number;
  inversion_mode: "induced_only" | "total_field" | "amplitude";
  do_q_sweep: boolean;
};

export type GravityCsvInvertPayload = {
  projectId?: string;
  runId?: string;
  depth: number;
  nir: number;
  fe: number;
  region: string;
  lat: string;
  lon: string;
  nx: number;
  ny: number;
  nz: number;
  blockSize: number;
  cutoffRadius: number;
  lambdaMag: number;
  alphaSpatial: number;
  strict?: boolean;
  allowGRaw?: boolean;
  utmZone?: string | null;
  acknowledgeSpatialRisk?: boolean;
  acknowledgeRegionalScale?: boolean;
  // Tier 1 B6 — parámetros físicos (los valida el backend)
  densityMin?: number;
  densityMax?: number;
  gravimeterType?: string;
  // Fase 9A — Magnetometría. dataType="magnetic" rutea al motor de
  // susceptibilidad (parsea una columna TMI en nT del CSV).
  dataType?: "gravity" | "magnetic";
  inclinationDeg?: number;
  declinationDeg?: number;
  fieldIntensityNt?: number;
  suscMin?: number;
  suscMax?: number;
  // Fase 7B — Advanced params (serialized as JSON strings in FormData)
  pgiParamsJson?: string | null;
  remanenceJson?: string | null;
  // FASE 16 — Kappas configurables
  paddingKappa?: number;
  anchorKappa?: number;
  autoKappa?: boolean;
  // FASE 20 — Sondajes que anclan la inversión (combo grav+sondajes). El backend
  // los parsea desde boreholes_json e inyecta en GeophysicsInvertInput.boreholes.
  boreholes?: Array<{
    x_m: number;
    z_m: number;
    y_from_m: number;
    y_to_m: number;
    density_t_m3?: number;
    susceptibility_si?: number;
  }>;
  // FASE 19 (Caso B) — Puntos de control Helmert (georef de coords locales).
  helmertControlPointsJson?: string | null;
};

export type InversionResultPayload = {
  voxels?: Array<{
    ix: number;
    iy: number;
    iz: number;
    x_m: number;
    y_m: number;
    z_m: number;
    density: number;
    grade: number;
    tonnage: number;
    probability: number;
    domain: number;
    anomaly_intensity?: number;
    target_score?: number;
    modeled_density_index?: number;
    density_anomaly_score?: number;
  }>;
  best_target?: {
    x_m: number;
    y_m: number;
    z_m: number;
    density: number;
    grade: number;
    probability: number;
    anomaly_intensity?: number;
    target_score?: number;
    modeled_density_index?: number;
    density_anomaly_score?: number;
    confidence_level?: string;
  };
  report?: {
    projectId?: string;
    runId?: string;
    avg_grade?: number;
    recommendation?: string;
    avg_anomaly_intensity?: number;
    max_target_score?: number;
    drill_recommendation?: string;
    confidence_level?: string;
    semantic_note?: string;
    risk_level?: string;
    technicalSummary?: {
      overall_level?: string;
      summary?: string;
      warnings?: string[];
    };
    fitDiagnostics?: {
      fit_level?: string;
    };
    uncertaintyDiagnostics?: {
      uncertainty_level?: string;
    };
    observationQuality?: {
      observation_count?: number;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export type GravityCsvInvertResponse = {
  status: "done" | "error";
  stage: "inversion" | "import";
  importMetadata: GravityImportMetadata | null;
  warnings: string[];
  errors: string[];
  inversionResult: InversionResultPayload | null;
  coordinate_transform?: CoordinateTransformData | null;
  georef?: GeorefSummary;
  spatial_readiness?: SpatialReadiness | null;
  regional_scale_preflight?: RegionalScalePreflight | null;
  acknowledge_regional_scale?: boolean;
};


// FASE 19 — Descargar el "CSV limpio" (validado + enriquecido) del backend.
// Devuelve el Blob + nombre sugerido; el componente dispara la descarga (mantiene
// frontendApi sin dependencias del DOM). El backend (build_clean_csv_from_import)
// produce las columnas normalizadas; aquí NO se recalcula nada.
export type ExportCleanCsvResult = {
  ok: boolean;
  status: number;
  blob: Blob | null;
  filename: string;
  error: string | null;
};

export async function exportCleanCsv(
  file: File,
  dataType: "gravity" | "magnetic" = "gravity"
): Promise<ExportCleanCsvResult> {
  const formData = new FormData();
  formData.append("file", file);
  const base = file.name.replace(/\.csv$/i, "");
  const fallbackName = `${base}_clean.csv`;
  try {
    const res = await fetch(
      `/api/gravity-import/export-clean-csv?data_type=${encodeURIComponent(dataType)}`,
      { method: "POST", body: formData }
    );
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const d = await res.json();
        if (typeof d?.detail === "string") detail = d.detail;
        else if (d?.detail?.message) detail = String(d.detail.message);
      } catch {
        /* respuesta no-JSON: se conserva el mensaje genérico */
      }
      return { ok: false, status: res.status, blob: null, filename: fallbackName, error: detail };
    }
    const blob = await res.blob();
    // Nombre desde Content-Disposition si el backend lo envió.
    const cd = res.headers.get("content-disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/i);
    const filename = match ? match[1] : fallbackName;
    return { ok: true, status: res.status, blob, filename, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, blob: null, filename: fallbackName, error: message };
  }
}

// ─── FASE R4 — Paquete CSV auto-contenido (build + load vía backend) ─────────
// Config que viaja como config_json al backend (claves snake_case = merge_config).
export type BuildPackageConfig = {
  region?: string;
  lat?: string | null;
  lon?: string | null;
  nir?: number;
  fe?: number;
  density_min?: number;
  density_max?: number;
  lambda_mag?: number;
  alpha_spatial?: number;
  gravimeter_type?: string;
  inclination_deg?: number;
  declination_deg?: number;
  field_intensity_nt?: number;
  // Fecha del survey (año o ISO, ej. "2016" o "2016-07") — el backend deriva el
  // IGRF offline (IGRF-14) desde la ubicación + esta fecha.
  survey_date?: string | null;
  susc_min?: number;
  susc_max?: number;
  padding_kappa?: number;
  anchor_kappa?: number;
  auto_kappa?: boolean;
  utm_zone?: string | null;
  acknowledge_spatial_risk?: boolean;
  acknowledge_regional_scale?: boolean;
  // Fase 7B — params avanzados (objetos anidados; el backend los inyecta al solver).
  pgi_params?: Record<string, unknown> | null;
  remanence?: Record<string, unknown> | null;
};

export type BuildPackageResult =
  | { ok: true; status: number; blob: Blob; filename: string; route: string | null; error: null }
  | { ok: false; status: number; blob: null; filename: string; route: null; error: string };

/** Ensambla el paquete CSV auto-contenido en el backend y devuelve el blob descargable. */
export async function buildPackage(opts: {
  file: File;
  magneticFile?: File | null;
  dataType?: "gravity" | "magnetic";
  strict?: boolean;
  allowGRaw?: boolean;
  config?: BuildPackageConfig;
  boreholes?: unknown[] | null;
}): Promise<BuildPackageResult> {
  const dataType = opts.dataType ?? "gravity";
  const fd = new FormData();
  fd.append("file", opts.file);
  if (opts.magneticFile) fd.append("magnetic_file", opts.magneticFile);
  if (opts.config) fd.append("config_json", JSON.stringify(opts.config));
  if (opts.boreholes && opts.boreholes.length > 0) {
    fd.append("boreholes_json", JSON.stringify(opts.boreholes));
  }
  const base = opts.file.name.replace(/\.csv$/i, "");
  const fallbackName = `${base}_package.tqpkg.csv`;
  const qs = new URLSearchParams({
    data_type: dataType,
    strict: String(opts.strict ?? true),
    allow_g_raw: String(opts.allowGRaw ?? false),
  });
  try {
    const res = await fetch(`/api/gravity-import/build-package?${qs.toString()}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const d = await res.json();
        if (typeof d?.detail === "string") detail = d.detail;
        else if (d?.detail?.message) detail = String(d.detail.message);
      } catch {
        /* respuesta no-JSON */
      }
      return { ok: false, status: res.status, blob: null, filename: fallbackName, route: null, error: detail };
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/i);
    const filename = match ? match[1] : fallbackName;
    return {
      ok: true, status: res.status, blob, filename,
      route: res.headers.get("x-tq-package-route"), error: null,
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, blob: null, filename: fallbackName, route: null, error: message };
  }
}

// ── Preparación con ENRIQUECIMIENTO (/enrich-package) ────────────────────────
export type EnrichmentStep = {
  key: string;
  label: string;
  status:
    | "derived"
    | "already_present"
    | "skipped"
    | "needs_context"
    | "not_derivable";
  method: string | null;
  detail: string;
  n_stations: number;
};

// FASE 19 (Caso B) — resultado de la georef Helmert que el backend adjunta al
// summary cuando el usuario aporta ≥2 puntos de control sobre coords LOCALES. Toda
// la matemática (similitud + residual) vive en el backend; el front solo lo muestra.
export type HelmertGeoref =
  | {
      skipped?: false;
      version: string;
      confidence: string;
      n_stations: number;
      transform: { residual_rms_m?: number | null; scale?: number; rotation_deg?: number };
      georeferenced_center?: { e: number; n: number } | null;
      georeferenced_extent?: { e_m: number; n_m: number } | null;
      warnings?: string[];
    }
  | { skipped: true; reason: string };

export type EnrichmentSummary = {
  version: string;
  steps: EnrichmentStep[];
  needs_context: string[];
  columns_added: string[];
  nothing_fabricated: boolean;
  // Presente solo si se enviaron puntos de control Helmert (opcional).
  helmert_georef?: HelmertGeoref;
};

// PILAR 1 (KEYSTONE) — plan de MAPEO MANUAL de columnas devuelto por el backend.
export type ColumnRole =
  | "x"
  | "y"
  | "elevation"
  | "depth"
  | "gravity_value"
  | "gravity_type"
  | "magnetic_value"
  | "sigma"
  | "station_id";

// F2 — SniffReport: detección física del CSV (encoding/separador/decimal/
// preámbulo/filas rotas) CON EVIDENCIA. El backend detecta; aquí solo se muestra.
export type SniffDetection = {
  value: string;
  confidence: "high" | "medium" | "low";
  evidence: string;
  discarded: { value: string; reason: string }[];
};

export type SniffReport = {
  version: string;
  filename: string;
  encoding: SniffDetection;
  separator: SniffDetection;
  decimal: SniffDetection;
  preamble_count: number;
  preamble_lines: { line_number: number; text: string; reason: string }[];
  header_line_number: number | null;
  header_columns: string[];
  broken_rows: {
    line_number: number;
    field_count: number;
    expected_fields: number;
    excerpt: string;
  }[];
  broken_row_count: number;
  n_lines_sampled: number;
  sample_truncated: boolean;
  warnings: string[];
};

// F2.4 — pregunta ESTRUCTURADA de ingesta (dato no-derivable → se pregunta,
// jamás se adivina). La respuesta viaja como literal de column_map.
export type IngestQuestion = {
  key: string;
  target: string;
  kind: "choice" | "text";
  blocking: boolean;
  question: string;
  options: { value: string; label: string }[];
  reason: string;
};

export type ColumnMappingPlan = {
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
  confidence: "high" | "medium" | "low";
  role_labels: Record<string, string>;
  literals: Record<string, string>;
  // F2 — heurística por RANGO físico (2ª opinión sobre el mapeo por nombre).
  range_checks?: Record<string, { column: string; verdict: string; note: string | null }>;
  suspicions?: {
    role: string;
    column: string;
    kind: string;
    user_mapped: boolean;
    message: string;
    suggested_role: string | null;
  }[];
  role_confidence?: Record<string, "high" | "medium" | "low">;
  suggestions?: Record<string, { column: string; confidence: string; reason: string }>;
  needs_confirmation?: boolean;
  // F2.4 — preguntas tipadas + literales inferidos del header con evidencia.
  questions?: IngestQuestion[];
  inferred_literals?: Record<string, { value: string; source_column: string; note: string }>;
};

export type EnrichPackageResult =
  | {
      ok: true;
      needsMapping?: false;
      status: number;
      filename: string;
      packageText: string;
      summary: EnrichmentSummary;
      plan: Record<string, unknown> | null;
      warnings: string[];
      needsContext: string[];
      nStations: number;
      // F2 — sniff físico del CSV primario (evidencia de formato).
      sniffReport?: SniffReport | null;
      error: null;
    }
  | {
      ok: true;
      needsMapping: true;
      status: number;
      mappingPlan: ColumnMappingPlan;
      // F2 — media confianza: el backend SUGIERE y PREGUNTA (sospechas de
      // rango, preguntas blocking) en vez de generar en silencio.
      needsConfirmation?: boolean;
      sniffReport?: SniffReport | null;
      sampleRows?: Record<string, string>[];
      message?: string;
    }
  | { ok: false; status: number; error: string };

/**
 * Sube los CSV crudos al backend de ENRIQUECIMIENTO: deriva con física real lo que
 * falte (DEM/correcciones/IGRF/coords/σ/calidad) y devuelve el TQPKG completo
 * descargable + un resumen estructurado de qué calculó/agregó. Nada se fabrica.
 */
export async function enrichPackage(opts: {
  // PILAR 2 — los datos se envían por ROL; el backend deriva el tipo y el combo.
  gravityFile?: File | null;
  magneticFile?: File | null;
  strict?: boolean;
  allowGRaw?: boolean;
  enableDem?: boolean;
  config?: BuildPackageConfig;
  boreholes?: unknown[] | null;
  // PILAR 1 — mapeo manual de columnas (rol → columna real del CSV primario).
  columnMap?: Record<string, string> | null;
  // FASE 19 (Caso B) — puntos de control Helmert (georef de coords LOCALES). El
  // backend resuelve la transformada; aquí solo se recolectan los puntos.
  helmertControlPointsJson?: string | null;
}): Promise<EnrichPackageResult> {
  const gravityFile = opts.gravityFile ?? null;
  const magneticFile = opts.magneticFile ?? null;
  if (!gravityFile && !magneticFile) {
    return {
      ok: false,
      status: 0,
      error: "Sube al menos un CSV (gravimetría y/o magnetometría).",
    };
  }
  // Tipo primario (hint): gravimetría manda; el backend lo deriva igualmente.
  const dataType: "gravity" | "magnetic" = gravityFile ? "gravity" : "magnetic";
  const fd = new FormData();
  if (gravityFile) fd.append("gravity_file", gravityFile);
  if (magneticFile) fd.append("magnetic_file", magneticFile);
  if (opts.config) fd.append("config_json", JSON.stringify(opts.config));
  if (opts.boreholes && opts.boreholes.length > 0) {
    fd.append("boreholes_json", JSON.stringify(opts.boreholes));
  }
  if (opts.columnMap && Object.keys(opts.columnMap).length > 0) {
    fd.append("column_map_json", JSON.stringify(opts.columnMap));
  }
  if (opts.helmertControlPointsJson) {
    fd.append("helmert_control_points_json", opts.helmertControlPointsJson);
  }
  const qs = new URLSearchParams({
    data_type: dataType,
    strict: String(opts.strict ?? false),
    allow_g_raw: String(opts.allowGRaw ?? true),
    enable_dem: String(opts.enableDem ?? true),
  });
  try {
    const res = await fetch(`/api/gravity-import/enrich-package?${qs.toString()}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const d = await res.json();
        if (typeof d?.detail === "string") detail = d.detail;
        else if (d?.detail?.message) detail = String(d.detail.message);
      } catch {
        /* respuesta no-JSON */
      }
      return { ok: false, status: res.status, error: detail };
    }
    const data = await res.json();
    // El backend pide MAPEO o CONFIRMACIÓN: faltan roles, hay sospechas de
    // rango o preguntas blocking sin responder (F2: preguntar, no adivinar).
    if (data?.needs_mapping) {
      return {
        ok: true,
        needsMapping: true,
        status: res.status,
        mappingPlan: data.column_mapping as ColumnMappingPlan,
        needsConfirmation: Boolean(data.needs_confirmation),
        sniffReport: (data.sniff_report as SniffReport) ?? null,
        sampleRows: Array.isArray(data.sample_rows) ? data.sample_rows : [],
        message: typeof data.message === "string" ? data.message : undefined,
      };
    }
    return {
      ok: true,
      needsMapping: false,
      status: res.status,
      filename: String(data.filename ?? "package.tqpkg.csv"),
      packageText: String(data.package_text ?? ""),
      summary: data.enrichment_summary as EnrichmentSummary,
      plan: (data.plan as Record<string, unknown>) ?? null,
      warnings: Array.isArray(data.warnings) ? data.warnings : [],
      needsContext: Array.isArray(data.needs_context) ? data.needs_context : [],
      nStations: Number(data.n_stations ?? 0),
      sniffReport: (data.sniff_report as SniffReport) ?? null,
      error: null,
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, error: message };
  }
}

/**
 * PILAR 1 — Pide al backend el PLAN DE MAPEO de columnas de un CSV (sin invertir).
 * Útil para abrir el paso de mapeo manual proactivamente (botón «Mapear columnas»).
 */
export async function analyzeColumns(opts: {
  file: File;
  dataType?: "gravity" | "magnetic";
  columnMap?: Record<string, string> | null;
}): Promise<
  | {
      ok: true;
      plan: ColumnMappingPlan;
      // F2 — sniff físico + preview de filas YA parseadas (evidencia).
      sniffReport?: SniffReport | null;
      sampleRows?: Record<string, string>[];
    }
  | { ok: false; error: string }
> {
  const fd = new FormData();
  fd.append("file", opts.file);
  if (opts.columnMap && Object.keys(opts.columnMap).length > 0) {
    fd.append("column_map_json", JSON.stringify(opts.columnMap));
  }
  const qs = new URLSearchParams({ data_type: opts.dataType ?? "gravity" });
  try {
    const res = await fetch(`/api/gravity-import/analyze-columns?${qs.toString()}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const d = await res.json();
        if (typeof d?.detail === "string") detail = d.detail;
        else if (d?.detail?.message) detail = String(d.detail.message);
      } catch {
        /* respuesta no-JSON */
      }
      return { ok: false, error: detail };
    }
    const data = await res.json();
    return {
      ok: true,
      plan: data.column_mapping as ColumnMappingPlan,
      sniffReport: (data.sniff_report as SniffReport) ?? null,
      sampleRows: Array.isArray(data.sample_rows) ? data.sample_rows : [],
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, error: message };
  }
}

// F3 — presupuesto previo de la inversión (estimado orientativo del backend).
export type InversionBudget = {
  voxel_count: number;
  route_kind: string;
  estimated_seconds: number;
  estimated_minutes: number;
  warning: string | null;
};

// F2 (deuda wizard) — filas COMPLETAS parseadas por el pipeline oficial del
// backend (sniffer incluido): el cliente jamás parsea CSV (decimal-coma, etc.).
export type ParseCsvRowsResult =
  | {
      ok: true;
      headers: string[];
      rows: Record<string, string>[];
      nRows: number;
      truncated: boolean;
      sniffReport: SniffReport | null;
    }
  | { ok: false; error: string };

export async function parseCsvRows(opts: {
  file: File;
  maxRows?: number;
}): Promise<ParseCsvRowsResult> {
  const fd = new FormData();
  fd.append("file", opts.file);
  const qs = opts.maxRows ? `?max_rows=${opts.maxRows}` : "";
  try {
    const res = await fetch(`/api/gravity-import/parse-rows${qs}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const d = await res.json();
        if (typeof d?.detail === "string") detail = d.detail;
        else if (d?.detail?.message) detail = String(d.detail.message);
      } catch {
        /* respuesta no-JSON */
      }
      return { ok: false, error: detail };
    }
    const data = await res.json();
    return {
      ok: true,
      headers: Array.isArray(data.headers) ? data.headers : [],
      rows: Array.isArray(data.rows) ? data.rows : [],
      nRows: Number(data.n_rows ?? 0),
      truncated: Boolean(data.truncated),
      sniffReport: (data.sniff_report as SniffReport) ?? null,
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, error: message };
  }
}

export type LoadPackageData = {
  status?: string;
  stage?: string;
  project_id?: string;
  run_id?: string;
  route?: string | null;
  multimodal_plan?: Record<string, unknown>;
  warnings?: string[];
  errors?: string[];
  inversionResult?: unknown;
  // F3 — respuesta asíncrona (status "queued"): presupuesto + info de polling.
  budget?: InversionBudget | null;
  poll?: { status_url: string; cancel_url: string; interval_ms: number } | null;
};

export type LoadPackageResult = {
  ok: boolean;
  status: number;
  data: LoadPackageData | null;
  error: string | null;
};

/** Sube el paquete CSV al backend, que corre la inversión ruteada y persiste el modelo. */
export async function loadPackage(
  file: File,
  opts?: { projectId?: string; runId?: string }
): Promise<LoadPackageResult> {
  const fd = new FormData();
  fd.append("file", file);
  if (opts?.projectId) fd.append("project_id", opts.projectId);
  if (opts?.runId) fd.append("run_id", opts.runId);
  try {
    const res = await fetch(`/api/gravity-import/load-package`, { method: "POST", body: fd });
    let data: LoadPackageData | null = null;
    let errDetail: string | null = null;
    try {
      const j = await res.json();
      if (res.ok) {
        data = j as LoadPackageData;
      } else {
        errDetail =
          typeof j?.detail === "string" ? j.detail
          : j?.detail?.message ? String(j.detail.message)
          : `Error ${res.status}`;
      }
    } catch {
      errDetail = `Error ${res.status}`;
    }
    return { ok: res.ok, status: res.status, data, error: errDetail };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message };
  }
}

export async function getFavorability(projectId: string, runId: string) {
  return fetchInternalJson<FavorabilityResult>({
    path: `/api/favorability?project_id=${encodeURIComponent(
      projectId
    )}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 15_000,
  });
}

// ─── Geophysics Async Status (F0.5) ──────────────────────────────────────────

export type GeophysicsStatusResponse = {
  project_id?: string;
  run_id?: string;
  status: string;
  progress?: number | null;
  stage?: string | null;
  message?: string | null;
  heartbeat_at?: string | null;
  metrics?: Record<string, unknown> | null;
  error?: string | null;
};

export async function getGeophysicsStatus(projectId: string, runId: string) {
  const result = await fetchInternalJson<GeophysicsStatusResponse>({
    path: `/api/geophysics-status?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 15_000,
  });

  // Validar respuesta si exitosa
  if (result.ok && result.data) {
    const validation = validateGeophysicsStatusResponse(result.data);
    if (!validation.valid) {
      console.warn(`[Schema Validation] GeophysicsStatusResponse: ${validation.errors.join("; ")}`);
    }
  }

  return result;
}

// ─── SSE Status Stream (§2.6) ────────────────────────────────────────────────

export type GeophysicsStatusSSEEvent = {
  stage: string;
  progress: number;
  message: string;
  status?: string;
  elapsed_s?: number;
};

/**
 * Connects to the SSE status stream for an in-progress inversion.
 * Returns a cleanup function — call it to close the connection early.
 *
 * The stream auto-closes when a terminal status is received:
 * done | error | complete | completed | timeout
 */
export function connectGeophysicsStatusStream(
  projectId: string,
  runId: string,
  onEvent: (data: GeophysicsStatusSSEEvent) => void,
  onTerminal: () => void,
): () => void {
  const url = `/api/geophysics-status/stream?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`;
  const es = new EventSource(url);
  const terminal = new Set(["done", "error", "complete", "completed", "timeout"]);

  es.onmessage = (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data as string) as GeophysicsStatusSSEEvent;
      onEvent(data);
      if (terminal.has(data.status ?? "") || terminal.has(data.stage ?? "")) {
        es.close();
        onTerminal();
      }
    } catch {
      // ignore parse errors from malformed SSE lines
    }
  };

  es.onerror = () => {
    es.close();
    onTerminal();
  };

  return () => es.close();
}

// ─── F3 — Cancelación e historial del flujo de paquete ───────────────────────

/** Cancela una corrida del flujo de paquete (backend: bandera + terminate). */
export async function cancelGeophysicsRun(projectId: string, runId: string) {
  return fetchInternalJson<{ status: string; outcome?: string }>({
    path: `/api/geophysics-cancel?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
    method: "POST",
    timeoutMs: 25_000,
  });
}

// F3 — corrida del historial SQLite (estado real que sobrevive reinicios).
export type HistoryRun = {
  project_id: string;
  run_id: string;
  status: string;          // queued|running|done|error|cancelled|interrumpida
  source?: string | null;
  route?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
};

export async function getHistoryRuns(projectId?: string) {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return fetchInternalJson<{ runs: HistoryRun[]; count: number }>({
    path: `/api/history/runs${qs}`,
    method: "GET",
    timeoutMs: 15_000,
  });
}

// F3: los helpers de la vía Celery (§2.5: enqueueGeophysicsInversion,
// getCeleryTaskStatus, pollInversionStatus) fueron ELIMINADOS — 0 llamadores
// UI (grep). La vía asíncrona del producto es loadModelFromPackage (encolar
// nativo + poll de getGeophysicsStatus) en packageInversion.ts.

// ─────────────────────────────────────────────────────────────────────────────

export async function fetchProjectFootprint(
  projectId: string
): Promise<FrontendApiResult<ProjectFootprintResponse>> {
  const url = `${BACKEND_PUBLIC_URL}/projects/${encodeURIComponent(projectId)}/footprint`;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);

  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/json",
      },
      signal: controller.signal,
    });

    const rawText = await res.text();
    let data: unknown;
    try {
      data = rawText ? JSON.parse(rawText) : {};
    } catch {
      return { ok: false, status: res.status || 500, data: null, error: "Respuesta no es JSON." };
    }

    if (!res.ok) {
      const d =
        data !== null && typeof data === "object" && !Array.isArray(data)
          ? (data as { [key: string]: unknown })
          : null;
      return {
        ok: false,
        status: res.status,
        data: null,
        error:
          (typeof d?.detail === "string" ? d.detail : null) ??
          `Error ${res.status} al cargar footprint.`,
      };
    }

    return { ok: true, status: res.status, data: data as ProjectFootprintResponse, error: null };
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" || error.message.toLowerCase().includes("aborted"));
    const message = error instanceof Error ? error.message : "Error de red";
    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      data: null,
      error: isTimeout ? "Timeout al cargar footprint del proyecto." : `Error: ${message}`,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

// ─── Arrow IPC Transport (R07) ────────────────────────────────────────────────
// Fase 3+4: loader Arrow + adaptador temporal TypedArrays→objetos para Scene3D.
// Pipeline: fetch ArrayBuffer → tableFromIPC → TypedArrays → cells[] → BlockModelResponse

// _inferCellSizeFromFloat32 eliminado en Fase 3B: el backend emite X-TQ-Cell-Size.

async function _buildBlockModelResponseFromArrow(
  buffer: ArrayBuffer,
  headers: Headers,
  fallbackMode: string
): Promise<FrontendApiResult<BlockModelResponse>> {
  // Dynamic import para evitar incompatibilidades SSR
  const { tableFromIPC } = await import("apache-arrow");
  const table = tableFromIPC(buffer);

  const n = table.numRows;
  if (n === 0) {
    return { ok: false, status: 200, data: null, error: "Arrow payload vacío (0 vóxeles)." };
  }

  const getF32 = (name: string): Float32Array => {
    const col = table.getChild(name);
    if (!col) {
      // Columna física ausente: NaN en vez de ceros para que la UI no pinte datos inventados.
      const arr = new Float32Array(n);
      arr.fill(NaN);
      return arr;
    }
    return col.toArray() as Float32Array;
  };
  const getI32 = (name: string): Int32Array => {
    const col = table.getChild(name);
    if (!col) return new Int32Array(n);
    return col.toArray() as Int32Array;
  };
  const hasCol = (name: string) => table.schema.fields.some((f) => f.name === name);

  const xs = getF32("x");
  const ys = getF32("y");
  const zs = getF32("z");
  const densities = getF32("density");
  const probabilities = getF32("probability");
  const visualScores = getF32("visual_score");
  const ixs = getI32("ix");
  const iys = getI32("iy");
  const izs = getI32("iz");

  // Columnas R3 opcionales
  const voxelElevs = hasCol("voxel_elevation_masl") ? getF32("voxel_elevation_masl") : null;
  const surfaceElevs = hasCol("surface_elevation_masl") ? getF32("surface_elevation_masl") : null;
  const lats = hasCol("lat") ? getF32("lat") : null;
  const lons = hasCol("lon") ? getF32("lon") : null;

  // Columnas multi-física (schema v3.0 — magnetic + joint)
  const susceptibilitySi = hasCol("susceptibility_si") ? getF32("susceptibility_si") : null;
  const jointStructuralScores = hasCol("joint_structural_score") ? getF32("joint_structural_score") : null;
  const densityT = hasCol("density_t_m3") ? getF32("density_t_m3") : null;
  const densityContrast = hasCol("density_contrast_t_m3") ? getF32("density_contrast_t_m3") : null;

  // FASE 20C — MVI: dirección de magnetización recuperada por celda (sólo presente en
  // parquets de inversión vectorial). NaN en celdas de aire. El FE sólo las muestra.
  const magInc = hasCol("magnetization_inc_deg") ? getF32("magnetization_inc_deg") : null;
  const magDec = hasCol("magnetization_dec_deg") ? getF32("magnetization_dec_deg") : null;

  // Headers autoritativos del backend (emitidos sobre el modelo COMPLETO, no el subconjunto).
  // El FE los consume directamente en vez de re-inferir física desde coordenadas parciales.
  const hCellSize = parseFloat(headers.get("x-tq-cell-size")  ?? "");
  const hDomainL  = parseFloat(headers.get("x-tq-domain-l")   ?? "");
  const hDomainH  = parseFloat(headers.get("x-tq-domain-h")   ?? "");
  const hDomainW  = parseFloat(headers.get("x-tq-domain-w")   ?? "");
  const hDensMin  = parseFloat(headers.get("x-tq-density-min") ?? "");
  const hDensMax  = parseFloat(headers.get("x-tq-density-max") ?? "");

  // Fallback de densidad desde celdas (si header ausente).
  // NaN en densities (columna faltante) no actualiza min/max — se detecta como degenerado.
  let densityMinFromCells = Infinity, densityMaxFromCells = -Infinity;
  for (let i = 0; i < n; i++) {
    if (densities[i] < densityMinFromCells) densityMinFromCells = densities[i];
    if (densities[i] > densityMaxFromCells) densityMaxFromCells = densities[i];
  }

  // Fallback de dominio desde coords del subconjunto (menos preciso que el header).
  // Solo se computa si los headers de dominio están ausentes.
  let xMin = Infinity, xMax = -Infinity;
  let yMin = Infinity, yMax = -Infinity;
  let zMin = Infinity, zMax = -Infinity;
  if (!Number.isFinite(hDomainL) || !Number.isFinite(hDomainH) || !Number.isFinite(hDomainW)) {
    for (let i = 0; i < n; i++) {
      if (xs[i] < xMin) xMin = xs[i]; if (xs[i] > xMax) xMax = xs[i];
      if (ys[i] < yMin) yMin = ys[i]; if (ys[i] > yMax) yMax = ys[i];
      if (zs[i] < zMin) zMin = zs[i]; if (zs[i] > zMax) zMax = zs[i];
    }
  }

  const cellSize   = Number.isFinite(hCellSize) ? hCellSize : 10;
  const domainL    = Number.isFinite(hDomainL)  ? hDomainL  : (xMax - xMin);
  const domainH    = Number.isFinite(hDomainH)  ? hDomainH  : (yMax - yMin);
  const domainW    = Number.isFinite(hDomainW)  ? hDomainW  : (zMax - zMin);
  const densityMin = Number.isFinite(hDensMin)  ? hDensMin
    : (Number.isFinite(densityMinFromCells)      ? densityMinFromCells : null);
  const densityMax = Number.isFinite(hDensMax)  ? hDensMax
    : (Number.isFinite(densityMaxFromCells)      ? densityMaxFromCells : null);
  const isDensityDegraded = densityMin === null || densityMax === null
    || densityMin === densityMax;

  // Adaptador Fase 4: TypedArrays → objetos JS (Scene3D require objects por vóxel)
  const cells: JsonValue[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const cell: { [key: string]: JsonValue } = {
      x: xs[i],
      y: ys[i],
      z: zs[i],
      density: densities[i],
      probability: probabilities[i],
      visual_score: visualScores[i],
      ix: ixs[i],
      iy: iys[i],
      iz: izs[i],
    };
    if (voxelElevs) cell.voxel_elevation_masl = voxelElevs[i];
    if (surfaceElevs) cell.surface_elevation_masl = surfaceElevs[i];
    if (lats) cell.lat = lats[i];
    if (lons) cell.lon = lons[i];
    if (susceptibilitySi) cell.susceptibility_si = susceptibilitySi[i];
    if (jointStructuralScores) cell.joint_structural_score = jointStructuralScores[i];
    if (densityT) cell.density_t_m3 = densityT[i];
    if (densityContrast) cell.density_contrast_t_m3 = densityContrast[i];
    if (magInc) cell.magnetization_inc_deg = magInc[i];
    if (magDec) cell.magnetization_dec_deg = magDec[i];
    cells[i] = cell;
  }

  // Metadata de elevación
  const hasElevationData = voxelElevs !== null;
  let elevationRange: {
    min_voxel_elevation_masl: number | null;
    max_voxel_elevation_masl: number | null;
    min_surface_elevation_masl: number | null;
    max_surface_elevation_masl: number | null;
    min_depth_below_surface_m: number | null;
    max_depth_below_surface_m: number | null;
  } | null = null;

  if (hasElevationData && voxelElevs) {
    let voxElevMin = Infinity, voxElevMax = -Infinity;
    let surfElevMin = Infinity, surfElevMax = -Infinity;
    for (let i = 0; i < n; i++) {
      const e = voxelElevs[i];
      if (Number.isFinite(e)) {
        if (e < voxElevMin) voxElevMin = e;
        if (e > voxElevMax) voxElevMax = e;
      }
      if (surfaceElevs) {
        const se = surfaceElevs[i];
        if (Number.isFinite(se)) {
          if (se < surfElevMin) surfElevMin = se;
          if (se > surfElevMax) surfElevMax = se;
        }
      }
    }
    elevationRange = {
      min_voxel_elevation_masl: Number.isFinite(voxElevMin) ? voxElevMin : null,
      max_voxel_elevation_masl: Number.isFinite(voxElevMax) ? voxElevMax : null,
      min_surface_elevation_masl: Number.isFinite(surfElevMin) ? surfElevMin : null,
      max_surface_elevation_masl: Number.isFinite(surfElevMax) ? surfElevMax : null,
      min_depth_below_surface_m: null,
      max_depth_below_surface_m: null,
    };
  }

  const totalVoxels = parseInt(headers.get("x-tq-total-voxels") ?? String(n), 10);

  // Construir BlockModelResponse compatible con parseBackendVoxelModel()
  const data = {
    cells,
    mode: fallbackMode,
    visualMode: "density_probability",
    domainL,
    domainH,
    domainW,
    cellSize,
    densityMin: densityMin ?? 0,
    densityMax: densityMax ?? 1,
    degraded: isDensityDegraded,
    warnings: [] as string[],
    total_voxels: totalVoxels,
    stored_voxels: totalVoxels,
    anomaly_voxels: null,
    returned_voxels: n,
    returnedCells: n,
    totalVoxels,
    storedVoxels: totalVoxels,
    anomalyVoxels: null,
    returnedVoxels: n,
    blockModelMode: fallbackMode,
    has_elevation_data: hasElevationData,
    dem_source: null,
    georef_confidence: null,
    elevation_range: elevationRange,
  } as unknown as BlockModelResponse;

  const result: FrontendApiResult<JsonValue> = {
    ok: true,
    status: 200,
    data: data as unknown as JsonValue,
    error: null,
  };

  return finalizeBlockModelResult(result, fallbackMode);
}

export async function fetchBlockModelArrow(
  mode: BlockModelDataMode = "exploration"
): Promise<FrontendApiResult<BlockModelResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);

  try {
    const url = `/api/block-model?format=arrow&mode=${encodeURIComponent(mode)}`;
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: { accept: "application/vnd.apache.arrow.stream" },
      signal: controller.signal,
    });

    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        data: null,
        error: `Arrow block-model falló con status ${res.status}.`,
      };
    }

    const buffer = await res.arrayBuffer();
    return await _buildBlockModelResponseFromArrow(buffer, res.headers, mode);
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" || error.message.toLowerCase().includes("aborted"));
    const message = error instanceof Error ? error.message : "unknown error";
    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      data: null,
      error: isTimeout
        ? `Timeout: /api/block-model?format=arrow tardó más de 120s.`
        : `Error Arrow block-model: ${message}`,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function fetchBlockModelArrowForRun(
  projectId: string,
  runId: string,
  mode: BlockModelDataMode = "exploration",
  displayFactor = 1,
  lod: 'far' | 'medium' | 'full' = 'full',
): Promise<FrontendApiResult<BlockModelResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);

  try {
    const url =
      `/api/block-model?format=arrow` +
      `&mode=${encodeURIComponent(mode)}` +
      `&project_id=${encodeURIComponent(projectId)}` +
      `&run_id=${encodeURIComponent(runId)}` +
      (displayFactor > 1 ? `&display_factor=${encodeURIComponent(String(displayFactor))}` : "") +
      (lod !== 'full' ? `&lod=${encodeURIComponent(lod)}` : "");

    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: { accept: "application/vnd.apache.arrow.stream" },
      signal: controller.signal,
    });

    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        data: null,
        error: `Arrow block-model falló con status ${res.status}.`,
      };
    }

    const buffer = await res.arrayBuffer();
    return _buildBlockModelResponseFromArrow(buffer, res.headers, mode);
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" || error.message.toLowerCase().includes("aborted"));
    const message = error instanceof Error ? error.message : "unknown error";
    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      data: null,
      error: isTimeout
        ? `Timeout: Arrow block-model tardó más de 120s.`
        : `Error Arrow block-model: ${message}`,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

// ─── Gravity Corrections (H-B4) ──────────────────────────────────────────────

export type GravityCorrectionParams = {
  reduction_density_gcc?: number;
  dem_type?: "COP30" | "SRTM30" | "SRTM90" | "ALOS" | "NASADEM";
  terrain_radius_m?: number;
  apply_lat_correction?: boolean;
  apply_fac?: boolean;
  apply_bouguer?: boolean;
  apply_terrain?: boolean;
  // F2B — pre-reducciones de CAMPO (solo g_raw): marea Longman y deriva por
  // cierres de base. Requieren time_utc por estación; la deriva además el id
  // de la estación base (el backend sugiere la candidata si falta).
  apply_tide?: boolean;
  apply_drift?: boolean;
  drift_method?: "linear" | "piecewise";
  base_station_id?: string | null;
};

// ── F2B — Gabinete del consultor: Nettleton / regional-residual / realce mag ─

export type NettletonResult = {
  densities_gcc: number[];
  correlations: number[];
  best_density_gcc: number;
  best_r: number;
  warning?: string | null;
};

/** Barrido de Nettleton (el CÁLCULO vive en el backend; aquí solo POST). */
export async function nettletonAnalysis(
  stations: Record<string, unknown>[],
  opts?: { densityMin?: number; densityMax?: number; densityStep?: number }
): Promise<FrontendApiResult<NettletonResult>> {
  const qs = new URLSearchParams();
  if (opts?.densityMin != null) qs.set("density_min", String(opts.densityMin));
  if (opts?.densityMax != null) qs.set("density_max", String(opts.densityMax));
  if (opts?.densityStep != null) qs.set("density_step", String(opts.densityStep));
  return fetchInternalJson<NettletonResult>({
    path: `/api/gravity-corrections/nettleton${qs.size ? `?${qs}` : ""}`,
    method: "POST",
    body: stations,
    timeoutMs: 60_000,
  });
}

export type GridMeta = {
  nx: number;
  ny: number;
  x0: number;
  y0: number;
  dx: number;
  dy: number;
  outside_hull_fraction: number;
  warnings: string[];
};

export type RegionalResidualResponse = {
  method: string;
  report: Record<string, unknown> & { warnings?: string[] };
  stations: Record<string, number | string>[];
  grids?: GridMeta & {
    observed: number[][];
    regional: number[][];
    residual: number[][];
  };
};

export async function regionalResidual(payload: {
  stations: Record<string, unknown>[];
  method: "polynomial" | "upward_continuation";
  order?: number;
  height_m?: number;
  value_column?: string;
  include_grids?: boolean;
}): Promise<FrontendApiResult<RegionalResidualResponse>> {
  return fetchInternalJson<RegionalResidualResponse>({
    path: "/api/gravity-corrections/regional-residual",
    method: "POST",
    body: payload,
    timeoutMs: 120_000,
  });
}

export type MagEnhanceResponse = {
  report: Record<string, unknown> & { warnings?: string[] };
  grid_meta: GridMeta;
  observed_tmi: number[][];
  products: Record<string, number[][]>;
};

export async function magEnhance(payload: {
  stations: Record<string, unknown>[];
  products: string[];
  tmi_column?: string;
  inclination_deg?: number;
  declination_deg?: number;
  uc_height_m?: number;
}): Promise<FrontendApiResult<MagEnhanceResponse>> {
  return fetchInternalJson<MagEnhanceResponse>({
    path: "/api/mag-enhance",
    method: "POST",
    body: payload,
    timeoutMs: 120_000,
  });
}

export type GravityCorrectedStation = {
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

export type GravityCorrectionReport = {
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
  warnings: string[];
};

export type ApplyCorrectionsRequest = {
  stations: Record<string, number | string>[];
  params?: GravityCorrectionParams;
  gravity_column?: string;
  gravity_type_in?: "g_raw" | "free_air_anomaly" | "bouguer_anomaly" | "complete_bouguer_anomaly";
};

export type ApplyCorrectionsResponse = {
  corrected: GravityCorrectedStation[];
  report: GravityCorrectionReport;
  output_gravity_type: string;
};

export async function applyGravityCorrections(
  request: ApplyCorrectionsRequest
): Promise<FrontendApiResult<ApplyCorrectionsResponse>> {
  try {
    const res = await fetch("/api/gravity-corrections/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      return { ok: false, status: res.status, data: null, error: "Respuesta no es JSON." };
    }
    if (!res.ok) {
      const d = data !== null && typeof data === "object" && !Array.isArray(data)
        ? (data as Record<string, unknown>)
        : null;
      return {
        ok: false,
        status: res.status,
        data: null,
        error: (typeof d?.detail === "string" ? d.detail : null) ?? `Error ${res.status}`,
      };
    }
    return { ok: true, status: res.status, data: data as ApplyCorrectionsResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message };
  }
}

// ── FASE 20 — Sondajes (Borehole Integration) ───────────────────────────────
// Espejo del schema backend BoreholeSample / BoreholeSurvey. El frontend NO
// parsea ni valida: envía el texto del CSV y consume lo que devuelve el backend.
export type BoreholeSample = {
  hole_id: string;
  x_m: number;
  z_m: number;
  depth_from_m: number;
  depth_to_m: number;
  sample_type: string;
  density_t_m3: number | null;
  density_uncertainty: number;
  lithology: string | null;
  susceptibility_si: number | null;
  comment: string;
};

export type BoreholeSurvey = {
  holes: BoreholeSample[];
  crs: string;
  datum_elevation_m: number;
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

export type ParseBoreholeCsvRequest = {
  csv_text: string;
  length_units?: "m" | "ft" | "auto";
  crs?: string;
  datum_elevation_m?: number;
};

/** F2B — variante MULTIPART: los bytes viajan intactos y el sniffer del
 * backend decide el encoding (un CSV latin-1 con ñ ya no llega mojibake). */
export async function parseBoreholeCsvFile(opts: {
  file: File;
  lengthUnits?: "m" | "ft" | "auto";
  crs?: string;
  datumElevationM?: number;
}): Promise<FrontendApiResult<ParseBoreholeCsvResponse>> {
  const fd = new FormData();
  fd.append("file", opts.file);
  fd.append("length_units", opts.lengthUnits ?? "m");
  fd.append("crs", opts.crs ?? "local");
  fd.append("datum_elevation_m", String(opts.datumElevationM ?? 0));
  try {
    const res = await fetch("/api/borehole/parse-file", { method: "POST", body: fd });
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const detail =
        (data as { detail?: unknown })?.detail;
      return {
        ok: false, status: res.status, data: null,
        error: typeof detail === "string"
          ? detail
          : (detail as { message?: string })?.message ?? `Error ${res.status}`,
      };
    }
    return { ok: true, status: res.status, data: data as ParseBoreholeCsvResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message };
  }
}

export async function parseBoreholeCsv(
  request: ParseBoreholeCsvRequest
): Promise<FrontendApiResult<ParseBoreholeCsvResponse>> {
  try {
    const res = await fetch("/api/borehole/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      return { ok: false, status: res.status, data: null, error: "Respuesta no es JSON." };
    }
    if (!res.ok) {
      const d = data !== null && typeof data === "object" && !Array.isArray(data)
        ? (data as Record<string, unknown>)
        : null;
      return {
        ok: false,
        status: res.status,
        data: null,
        error: (typeof d?.detail === "string" ? d.detail : null) ?? `Error ${res.status}`,
      };
    }
    return { ok: true, status: res.status, data: data as ParseBoreholeCsvResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message };
  }
}

// Convierte un BoreholeSurvey al formato `boreholes` que consume /geophysics-invert
// (BoreholeInterval: x_m, z_m, y_from_m, y_to_m, density_t_m3, susceptibility_si,
//  lithology). Solo incluye muestras con al menos una propiedad física.
// F4.4: se conserva `lithology` para colorear los sondajes por unidad geológica
// en el visor 3D (el backend ya la acepta y la usa para bounds por litología).
export function boreholeSurveyToIntervals(
  survey: BoreholeSurvey
): Array<{
  x_m: number;
  z_m: number;
  y_from_m: number;
  y_to_m: number;
  density_t_m3?: number;
  susceptibility_si?: number;
  lithology?: string;
}> {
  return survey.holes
    .filter((h) => h.density_t_m3 != null || h.susceptibility_si != null)
    .map((h) => ({
      x_m: h.x_m,
      z_m: h.z_m,
      y_from_m: h.depth_from_m,
      y_to_m: h.depth_to_m,
      ...(h.density_t_m3 != null ? { density_t_m3: h.density_t_m3 } : {}),
      ...(h.susceptibility_si != null ? { susceptibility_si: h.susceptibility_si } : {}),
      ...(h.lithology != null ? { lithology: h.lithology } : {}),
    }));
}

// ── FASE 21 — Estrategia de Fusión Multimodal ─────────────────────────────────
// El frontend manda los CONTEOS de datos disponibles; el backend devuelve qué
// combo se usaría, su confianza y el error de profundidad esperado. El frontend
// NO calcula confianza ni física (Regla de Oro): sólo muestra la decisión.
export type MultimodalPlan = {
  route: string;
  has_gravity: boolean;
  has_magnetic: boolean;
  has_borehole: boolean;
  n_sensors: number;
  base_confidence: number;
  confidence: number;
  confidence_pct: number;
  error_depth_m: number;
  coverage_pct: number;
  data_quality: number | null;
  resolution_priority: string[];
  warnings: string[];
  notes: string[];
};

export type MultimodalPlanResponse = {
  has_gravity: boolean;
  has_magnetic: boolean;
  has_borehole: boolean;
  n_sensors: number;
  plan: MultimodalPlan | null;
  insufficient_reason: string | null;
};

export type MultimodalPlanRequest = {
  n_gravity_sensors?: number;
  n_magnetic_sensors?: number;
  n_boreholes_with_density?: number;
  data_quality?: number | null;
  coverage_pct?: number;
};

// Etiquetas legibles por ruta (solo presentación; la ruta canónica viene del backend).
export const MULTIMODAL_ROUTE_LABELS: Record<string, string> = {
  gravity_only: "Gravimetría sola",
  magnetic_only: "Magnetometría sola",
  gravity_magnetic_joint: "Gravimetría + Magnetometría (conjunta)",
  gravity_with_constraints: "Gravimetría + Sondajes",
  joint_with_constraints: "Gravimetría + Magnetometría + Sondajes",
};

export async function getMultimodalPlan(
  request: MultimodalPlanRequest
): Promise<FrontendApiResult<MultimodalPlanResponse>> {
  try {
    const res = await fetch("/api/multimodal/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      return { ok: false, status: res.status, data: null, error: "Respuesta no es JSON." };
    }
    if (!res.ok) {
      const d =
        data !== null && typeof data === "object" && !Array.isArray(data)
          ? (data as Record<string, unknown>)
          : null;
      return {
        ok: false,
        status: res.status,
        data: null,
        error: (typeof d?.detail === "string" ? d.detail : null) ?? `Error ${res.status}`,
      };
    }
    return { ok: true, status: res.status, data: data as MultimodalPlanResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return { ok: false, status: 500, data: null, error: message };
  }
}
