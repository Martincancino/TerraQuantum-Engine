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
  const _r08_t0 = performance.now();
  const data = normalizeBlockModelResponse(result.data, fallbackMode);

  if (result.ok) {
    syncVoxelTraceFromBlockModel(data);
    syncBlockModelElevationMeta(data);
    syncPercentileStats(data);
  }

  const out = { ...result, data };
  console.log(`[R08] finalizeBlockModelResult (store sync): ${(performance.now() - _r08_t0).toFixed(1)}ms`);
  return out;
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
    method: "POST",
    body: payload,
    timeoutMs: 90_000,
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
): Promise<FrontendApiResult<BlockModelResponse>> {
  const request = resolveBlockModelRequestArgs(modeOrLimit, limit);

  if (request.limit > 5000) {
    const arrowResult = await fetchBlockModelArrowForRun(projectId, runId, request.mode);
    if (arrowResult.ok) {
      console.log(`[QW-6] ${arrowResult.data?.returnedVoxels ?? 0} vóxeles via Arrow IPC`);
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

export async function getEconomicBlockModel(limit = 5000) {
  const result = await fetchInternalJson<JsonValue>({
    path: `/api/block-model?mode=economic&limit=${limit}`,
    method: "GET",
    timeoutMs: 60_000,
  });

  return finalizeBlockModelResult(result, "economic");
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
  )}&runId=${encodeURIComponent(runId)}`;
}

export function exportBundleUrl(projectId: string, runId: string) {
  return `${BACKEND_PUBLIC_URL}/export/bundle/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`;
}

export async function deleteRun(
  projectId: string,
  runId: string
): Promise<{ ok: boolean; error: string | null }> {
  const url = `${BACKEND_PUBLIC_URL}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`;
  const _apiKey = process.env.NEXT_PUBLIC_TQ_API_KEY ?? "";
  try {
    const res = await fetch(url, {
      method: "DELETE",
      headers: {
        accept: "application/json",
        ...(_apiKey ? { "X-TQ-API-Key": _apiKey } : {}),
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
  options?: { strict?: boolean; allowGRaw?: boolean; previewLimit?: number }
): Promise<FrontendApiResult<GravityImportPreviewResponse>> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.strict !== undefined) formData.append("strict", String(options.strict));
  if (options?.allowGRaw !== undefined) formData.append("allow_g_raw", String(options.allowGRaw));
  if (options?.previewLimit !== undefined) formData.append("preview_limit", String(options.previewLimit));

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
      const detailStr = typeof data?.detail === "string" ? data.detail : null;
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
  return fetchInternalJson<GeophysicsStatusResponse>({
    path: `/api/geophysics-status?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
    method: "GET",
    timeoutMs: 15_000,
  });
}

// ─────────────────────────────────────────────────────────────────────────────

export async function fetchProjectFootprint(
  projectId: string
): Promise<FrontendApiResult<ProjectFootprintResponse>> {
  const url = `${BACKEND_PUBLIC_URL}/projects/${encodeURIComponent(projectId)}/footprint`;
  const _apiKey = process.env.NEXT_PUBLIC_TQ_API_KEY ?? "";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);

  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/json",
        ...(_apiKey ? { "X-TQ-API-Key": _apiKey } : {}),
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

function _inferCellSizeFromFloat32(xs: Float32Array): number {
  // Muestrea hasta 2000 valores, ordena, busca el gap mínimo entre valores únicos.
  const sample = Array.from(xs.subarray(0, Math.min(xs.length, 2000)));
  const unique = Array.from(new Set(sample.map((v) => Math.round(v * 1000) / 1000))).sort(
    (a, b) => a - b
  );
  let minGap = Infinity;
  for (let i = 1; i < unique.length; i++) {
    const d = unique[i] - unique[i - 1];
    if (d > 0.01 && d < minGap) minGap = d;
  }
  return Number.isFinite(minGap) && minGap < Infinity ? minGap : 10;
}

async function _buildBlockModelResponseFromArrow(
  buffer: ArrayBuffer,
  headers: Headers,
  fallbackMode: string
): Promise<FrontendApiResult<BlockModelResponse>> {
  const _r08_fn_start = performance.now();
  // Dynamic import para evitar incompatibilidades SSR
  const { tableFromIPC } = await import("apache-arrow");
  const _r08_ipc_start = performance.now();
  const table = tableFromIPC(buffer);
  const _r08_ipc_end = performance.now();

  const n = table.numRows;
  if (n === 0) {
    return { ok: false, status: 200, data: null, error: "Arrow payload vacío (0 vóxeles)." };
  }

  const getF32 = (name: string): Float32Array => {
    const col = table.getChild(name);
    if (!col) return new Float32Array(n);
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

  // Bounds para domainL/H/W — single pass
  let xMin = Infinity, xMax = -Infinity;
  let yMin = Infinity, yMax = -Infinity;
  let zMin = Infinity, zMax = -Infinity;
  let densityMin = Infinity, densityMax = -Infinity;

  for (let i = 0; i < n; i++) {
    if (xs[i] < xMin) xMin = xs[i]; if (xs[i] > xMax) xMax = xs[i];
    if (ys[i] < yMin) yMin = ys[i]; if (ys[i] > yMax) yMax = ys[i];
    if (zs[i] < zMin) zMin = zs[i]; if (zs[i] > zMax) zMax = zs[i];
    if (densities[i] < densityMin) densityMin = densities[i];
    if (densities[i] > densityMax) densityMax = densities[i];
  }

  const domainL = xMax - xMin;
  const domainH = yMax - yMin;
  const domainW = zMax - zMin;
  const cellSize = _inferCellSizeFromFloat32(xs);

  // Adaptador Fase 4: TypedArrays → objetos JS (Scene3D require objects por vóxel)
  const _r08_cells_start = performance.now();
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
  const _r08_cells_end = performance.now();
  console.log(
    `[R08] _buildBlockModelResponseFromArrow | n=${n} | buf=${(buffer.byteLength / 1024).toFixed(0)}KB` +
    ` | import=${(_r08_ipc_start - _r08_fn_start).toFixed(1)}ms` +
    ` | ipc_decode=${(_r08_ipc_end - _r08_ipc_start).toFixed(1)}ms` +
    ` | cells_build=${(_r08_cells_end - _r08_cells_start).toFixed(1)}ms`
  );

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

  // Leer metadata de headers HTTP
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
    densityMin: Number.isFinite(densityMin) ? densityMin : 0,
    densityMax: Number.isFinite(densityMax) ? densityMax : 1,
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

  const _r08_out = finalizeBlockModelResult(result, fallbackMode);
  console.log(`[R08] _buildBlockModelResponseFromArrow total: ${(performance.now() - _r08_fn_start).toFixed(1)}ms`);
  return _r08_out;
}

export async function fetchBlockModelArrow(
  mode: BlockModelDataMode = "exploration"
): Promise<FrontendApiResult<BlockModelResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);

  try {
    const _r08_fetch_start = performance.now();
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
    const _r08_buf_end = performance.now();
    const result = await _buildBlockModelResponseFromArrow(buffer, res.headers, mode);
    console.log(
      `[R08] fetchBlockModelArrow | fetch+buffer=${(_r08_buf_end - _r08_fetch_start).toFixed(1)}ms` +
      ` | processing=${(performance.now() - _r08_buf_end).toFixed(1)}ms` +
      ` | total=${(performance.now() - _r08_fetch_start).toFixed(1)}ms`
    );
    return result;
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
  mode: BlockModelDataMode = "exploration"
): Promise<FrontendApiResult<BlockModelResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);

  try {
    const url =
      `/api/block-model?format=arrow` +
      `&mode=${encodeURIComponent(mode)}` +
      `&project_id=${encodeURIComponent(projectId)}` +
      `&run_id=${encodeURIComponent(runId)}`;

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
