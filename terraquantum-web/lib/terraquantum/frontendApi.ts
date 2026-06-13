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
): Promise<FrontendApiResult<BlockModelResponse>> {
  const request = resolveBlockModelRequestArgs(modeOrLimit, limit);

  // displayFactor>1 = sub-muestreo trilineal de display (500k-2M celdas): SIEMPRE
  // por Arrow (binario), el JSON no soporta ese tamaño.
  if (displayFactor > 1 || request.limit > 5000) {
    const arrowResult = await fetchBlockModelArrowForRun(projectId, runId, request.mode, displayFactor);
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
};

export type CoordinateSystemDetection = {
  detected?: string;
  confidence?: string;
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
  } | null;
  coordinate_transform?: CoordinateTransformData | null;
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

export async function invertGravityCsv(
  file: File,
  payload: GravityCsvInvertPayload
): Promise<FrontendApiResult<GravityCsvInvertResponse>> {
  const formData = new FormData();
  formData.append("file", file);
  
  if (payload.projectId) formData.append("project_id", payload.projectId);
  if (payload.runId) formData.append("run_id", payload.runId);
  
  formData.append("depth", String(payload.depth));
  formData.append("nir", String(payload.nir));
  formData.append("fe", String(payload.fe));
  formData.append("region", payload.region);
  formData.append("lat", payload.lat);
  formData.append("lon", payload.lon);
  formData.append("nx", String(payload.nx));
  formData.append("ny", String(payload.ny));
  formData.append("nz", String(payload.nz));
  formData.append("block_size", String(payload.blockSize));
  formData.append("cutoff_radius", String(payload.cutoffRadius));
  formData.append("lambda_mag", String(payload.lambdaMag));
  formData.append("alpha_spatial", String(payload.alphaSpatial));
  
  if (payload.strict !== undefined) formData.append("strict", String(payload.strict));
  if (payload.allowGRaw !== undefined) formData.append("allow_g_raw", String(payload.allowGRaw));
  if (payload.utmZone && payload.utmZone.trim()) {
    formData.append("utm_zone", payload.utmZone.trim().toUpperCase());
  }
  if (payload.acknowledgeSpatialRisk === true) {
    formData.append("acknowledge_spatial_risk", "true");
  }
  if (payload.acknowledgeRegionalScale === true) {
    formData.append("acknowledge_regional_scale", "true");
  }
  // Tier 1 B6 — parámetros físicos opcionales
  if (payload.densityMin !== undefined) formData.append("density_min", String(payload.densityMin));
  if (payload.densityMax !== undefined) formData.append("density_max", String(payload.densityMax));
  if (payload.gravimeterType) formData.append("gravimeter_type", payload.gravimeterType);
  // Fase 9A — Magnetometría
  if (payload.dataType) formData.append("data_type", payload.dataType);
  if (payload.inclinationDeg !== undefined) formData.append("inclination_deg", String(payload.inclinationDeg));
  if (payload.declinationDeg !== undefined) formData.append("declination_deg", String(payload.declinationDeg));
  if (payload.fieldIntensityNt !== undefined) formData.append("field_intensity_nt", String(payload.fieldIntensityNt));
  if (payload.suscMin !== undefined) formData.append("susc_min", String(payload.suscMin));
  if (payload.suscMax !== undefined) formData.append("susc_max", String(payload.suscMax));

  try {
    const res = await fetch("/api/gravity-import/invert", {
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
      const detail = data?.detail;
      const detailStr = typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null
          ? (detail as Record<string, unknown>).message as string ?? JSON.stringify(detail)
          : null;
      return { ok: false, status: res.status, data: data as GravityCsvInvertResponse, error: detailStr ?? `Error ${res.status}` };
    }
    return { ok: true, status: res.status, data: data as GravityCsvInvertResponse, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error de red";
    return {
      ok: false,
      status: 500,
      data: null,
      error: message || "Error de red",
    };
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

// ─── Celery Async Inversion (§2.5) ───────────────────────────────────────────

export type AsyncInvertResponse = {
  task_id: string;
  run_id: string;
  project_id: string;
  status: string;
  status_url: string;
};

export type CeleryTaskStatusResponse = {
  task_id: string;
  celery_state: string;
  project_id?: string | null;
  run_id?: string | null;
  stage?: string | null;
  progress?: number | null;
  error?: string | null;
};

export async function enqueueGeophysicsInversion(
  params: Record<string, unknown>
): Promise<FrontendApiResult<AsyncInvertResponse>> {
  return fetchInternalJson<AsyncInvertResponse>({
    path: "/api/async/invert",
    method: "POST",
    body: params,
    timeoutMs: 10_000,
  });
}

export async function getCeleryTaskStatus(
  taskId: string
): Promise<FrontendApiResult<CeleryTaskStatusResponse>> {
  return fetchInternalJson<CeleryTaskStatusResponse>({
    path: `/api/async/tasks/${encodeURIComponent(taskId)}`,
    method: "GET",
    timeoutMs: 10_000,
  });
}

export function pollInversionStatus(
  taskId: string,
  onProgress: (stage: string, progress: number) => void,
  intervalMs = 3_000
): { promise: Promise<CeleryTaskStatusResponse>; cancel: () => void } {
  let intervalId: ReturnType<typeof setInterval> | null = null;
  let cancelled = false;

  const promise = new Promise<CeleryTaskStatusResponse>((resolve, reject) => {
    intervalId = setInterval(async () => {
      if (cancelled) return;
      const res = await getCeleryTaskStatus(taskId);
      if (!res.ok || !res.data) {
        if (intervalId !== null) clearInterval(intervalId);
        reject(new Error(res.error ?? "Error polling task status"));
        return;
      }
      const data = res.data;
      onProgress(data.stage ?? data.celery_state ?? "running", data.progress ?? 0);
      const terminal = ["SUCCESS", "FAILURE", "REVOKED"];
      if (terminal.includes(data.celery_state)) {
        if (intervalId !== null) clearInterval(intervalId);
        resolve(data);
      }
    }, intervalMs);
  });

  const cancel = () => {
    cancelled = true;
    if (intervalId !== null) clearInterval(intervalId);
  };

  return { promise, cancel };
}

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
  displayFactor = 1
): Promise<FrontendApiResult<BlockModelResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);

  try {
    const url =
      `/api/block-model?format=arrow` +
      `&mode=${encodeURIComponent(mode)}` +
      `&project_id=${encodeURIComponent(projectId)}` +
      `&run_id=${encodeURIComponent(runId)}` +
      (displayFactor > 1 ? `&display_factor=${encodeURIComponent(String(displayFactor))}` : "");

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
};

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
