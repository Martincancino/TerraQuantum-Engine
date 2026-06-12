import type { VoxelData } from "../../lib/terraQuantumGeology";
import type { JsonValue } from "../../lib/terraquantum/frontendApi";
import type {
  RunFiles,
  JsonObject,
  BackendVoxelModel,
  ProjectRunsViewData,
  ProjectRunDetail,
  CompareResult,
  ResidualPoint,
} from "./types";

// Acepta unknown: un type guard debe poder examinar cualquier valor (los
// payloads del backend llegan tipados como unknown antes de validarse).
export function isJsonObject(value: unknown): value is JsonObject {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function fmtNum(v: unknown, decimals = 4): string {
  if (typeof v === "number" && Number.isFinite(v)) return v.toFixed(decimals);
  return "—";
}

export function fmtSci(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return v.toExponential(3);
  return "—";
}

export function levelCls(level: string | undefined): string {
  if (level === "GOOD") return "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  if (level === "MEDIUM") return "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  return "text-red-400 border-red-500/40 bg-red-500/10";
}

export function residualLevelCls(level: string | undefined): string {
  if (level === "LOW") return "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  if (level === "MEDIUM") return "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  return "text-red-400 border-red-500/40 bg-red-500/10";
}

export function uncertaintyLevelCls(level: string | undefined): string {
  if (level === "LOW") return "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  if (level === "MEDIUM") return "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  return "text-red-400 border-red-500/40 bg-red-500/10";
}

export function sensorFlagLevelCls(level: string | undefined): string {
  if (level === "LOW") return "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  if (level === "MEDIUM") return "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  return "text-red-400 border-red-500/40 bg-red-500/10";
}

export function readBoolean(value: JsonValue | undefined) {
  return value === true;
}

export function readNumber(value: JsonValue | undefined, fallback: number) {
  return typeof value === "number" ? value : fallback;
}

export function safeNumber(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function safeString(value: unknown, fallback = "N/A"): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

export function safeArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

export function readArrayLength(value: unknown): number | null {
  return Array.isArray(value) ? value.length : null;
}

export function readText(value: JsonValue | undefined) {
  if (typeof value === "string" && value.trim() !== "") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "No disponible";
}

export function parseProjectRuns(data: JsonValue | null): ProjectRunsViewData | null {
  if (!isJsonObject(data)) {
    return null;
  }

  const projectsRaw = Array.isArray(data.projects) ? data.projects : [];

  return {
    totalProjects: typeof data.totalProjects === "number" ? data.totalProjects : 0,
    totalRuns: typeof data.totalRuns === "number" ? data.totalRuns : 0,
    projects: projectsRaw.filter(isJsonObject).map((project) => {
      const runsRaw = Array.isArray(project.runs) ? project.runs : [];

      return {
        projectId: typeof project.projectId === "string" ? project.projectId : "sin_project_id",
        runs: runsRaw.filter(isJsonObject).map((run) => {
          const files = isJsonObject(run.files) ? run.files : {};

          return {
            runId: typeof run.runId === "string" ? run.runId : "sin_run_id",
            exists: readBoolean(run.exists),
            files: {
              block_model: readBoolean(files.block_model),
              inputs: readBoolean(files.inputs),
              observations: readBoolean(files.observations),
              report: readBoolean(files.report),
              metrics: readBoolean(files.metrics),
              schedule: readBoolean(files.schedule),
            },
          };
        }),
      };
    }),
  };
}

export function parseProjectRunDetail(data: JsonValue | null): ProjectRunDetail | null {
  if (!isJsonObject(data)) {
    return null;
  }

  const files = isJsonObject(data.files) ? data.files : {};
  const scheduleRaw = Array.isArray(data.schedule) ? data.schedule : [];

  return {
    projectId: typeof data.projectId === "string" ? data.projectId : "No disponible",
    runId: typeof data.runId === "string" ? data.runId : "No disponible",
    files: {
      block_model: readBoolean(files.block_model),
      inputs: readBoolean(files.inputs),
      observations: readBoolean(files.observations),
      report: readBoolean(files.report),
      metrics: readBoolean(files.metrics),
      schedule: readBoolean(files.schedule),
    },
    inputs: isJsonObject(data.inputs) ? data.inputs : null,
    report: isJsonObject(data.report) ? data.report : null,
    metrics: isJsonObject(data.metrics) ? data.metrics : null,
    schedule: scheduleRaw.filter(isJsonObject),
    observations: Array.isArray(data.observations) ? data.observations.filter(isJsonObject) : [],
  };
}

export function parseCompareResult(data: JsonValue | null): CompareResult | null {
  if (!isJsonObject(data)) {
    return null;
  }

  const baseRun = isJsonObject(data.baseRun) ? data.baseRun : {};
  const compareRun = isJsonObject(data.compareRun) ? data.compareRun : {};
  const deltas = isJsonObject(data.deltas) ? data.deltas : {};

  return {
    baseProjectId: readText(baseRun.projectId),
    baseRunId: readText(baseRun.runId),
    compareProjectId: readText(compareRun.projectId),
    compareRunId: readText(compareRun.runId),
    deltas,
  };
}

export function parseBlockModel(data: JsonValue | null): BackendVoxelModel | null {
  if (!isJsonObject(data) || !Array.isArray(data.cells) || data.cells.length === 0) {
    return null;
  }

  const cells = data.cells.filter(isJsonObject).map((cell) => ({ ...cell })) as VoxelData[];

  if (cells.length === 0) {
    return null;
  }

  const densityMin = readNumber(data.densityMin, Number.NaN);
  const densityMax = readNumber(data.densityMax, Number.NaN);
  const scoreStats = (isJsonObject(data.scoreStats) ? data.scoreStats : undefined) as BackendVoxelModel["scoreStats"];
  const visualScoreStats = (isJsonObject(data.visualScoreStats) ? data.visualScoreStats : undefined) as BackendVoxelModel["visualScoreStats"];
  const densityStats = (isJsonObject(data.densityStats) ? data.densityStats : undefined) as BackendVoxelModel["densityStats"];
  const rhoStats = (isJsonObject(data.rhoStats) ? data.rhoStats : undefined) as BackendVoxelModel["rhoStats"];
  const probabilityStats = (isJsonObject(data.probabilityStats) ? data.probabilityStats : undefined) as BackendVoxelModel["probabilityStats"];
  const returnedScoreStats = (isJsonObject(data.returnedScoreStats) ? data.returnedScoreStats : undefined) as BackendVoxelModel["returnedScoreStats"];
  const diagnosticStats = (isJsonObject(data.diagnosticStats) ? data.diagnosticStats : undefined) as BackendVoxelModel["diagnosticStats"];
  const returnedDiagnosticStats = (isJsonObject(data.returnedDiagnosticStats) ? data.returnedDiagnosticStats : undefined) as BackendVoxelModel["returnedDiagnosticStats"];
  const warnings = Array.isArray(data.warnings)
    ? data.warnings.filter((warning): warning is string => typeof warning === "string")
    : [];
  const isDegenerate = data.isDegenerate === true || data.is_degenerate === true;

  return {
    domainL: readNumber(data.domainL, 0),
    domainH: readNumber(data.domainH, 0),
    domainW: readNumber(data.domainW, 0),
    cellSize: readNumber(data.cellSize, 10),
    cells,
    volumeM3:
      readNumber(data.domainL, 0) *
      readNumber(data.domainH, 0) *
      readNumber(data.domainW, 0),
    ...(typeof data.visualMode === "string" ? { visualMode: data.visualMode } : {}),
    ...(typeof data.mode === "string" ? { mode: data.mode } : {}),
    ...(Number.isFinite(densityMin) ? { densityMin } : {}),
    ...(Number.isFinite(densityMax) ? { densityMax } : {}),
    ...(scoreStats ? { scoreStats } : {}),
    ...(visualScoreStats ? { visualScoreStats } : {}),
    ...(densityStats ? { densityStats } : {}),
    ...(rhoStats ? { rhoStats } : {}),
    ...(probabilityStats ? { probabilityStats } : {}),
    ...(returnedScoreStats ? { returnedScoreStats } : {}),
    ...(diagnosticStats ? { diagnosticStats } : {}),
    ...(returnedDiagnosticStats ? { returnedDiagnosticStats } : {}),
    ...(warnings.length > 0 ? { warnings } : {}),
    ...(isDegenerate ? { isDegenerate: true, is_degenerate: true } : {}),
  };
}

export function buildRunKey(projectId: string, runId: string) {
  return `${projectId}/${runId}`;
}

export function hasRunFiles(files: RunFiles) {
  return Object.values(files).some(Boolean);
}

export const projectRunFileLabels: Array<{ key: keyof RunFiles; label: string }> = [
  { key: "block_model", label: "block_model" },
  { key: "inputs", label: "inputs" },
  { key: "observations", label: "observations" },
  { key: "report", label: "report" },
  { key: "metrics", label: "metrics" },
  { key: "schedule", label: "schedule" },
];

export const inputDetailFields = [
  "depth",
  "nx",
  "ny",
  "nz",
  "block_size",
  "region",
  "nir",
  "fe",
];

export const reportDetailFields = [
  "priority_class",
  "model_reliability_level",
  "avg_grade",
  "relative_target_score",
  "estimated_total_tonnage",
];

export const metricsDetailFields = ["npv", "tonnage", "avg_grade", "lom_years"];
export const scheduleDetailFields = ["year", "cf", "ore", "waste", "m_cap_used"];
export const compareDeltaFields = [
  "npv_delta",
  "tonnage_delta",
  "avg_grade_delta",
  "lom_years_delta",
  "estimated_total_tonnage_delta",
  "avg_geophysics_grade_delta",
  "relative_target_score_delta",
];

// ─── QA Badge helpers — centralized, used by GeoDashboard & GravityCsvPreviewPanel ──

export function qaStatusBadgeClass(status: string | null | undefined): string {
  const s = (status ?? "").toUpperCase();
  if (s === "PASS" || s.startsWith("PASS")) return "border-green-600/40 bg-green-900/20 text-green-300";
  if (s === "WARNING" || s.startsWith("WARN")) return "border-yellow-600/40 bg-yellow-900/20 text-yellow-300";
  if (s === "FAIL" || s.startsWith("FAIL")) return "border-red-600/40 bg-red-900/20 text-red-300";
  return "border-neutral-700 bg-neutral-900/30 text-neutral-400";
}

export function qaStatusIcon(status: string | null | undefined): string {
  const s = (status ?? "").toUpperCase();
  if (s === "PASS" || s.startsWith("PASS")) return "✓";
  if (s === "FAIL" || s.startsWith("FAIL")) return "✗";
  return "⚠";
}

// Needed for ResidualPoint type guard in helpers
export function isResidualPoint(p: unknown): p is ResidualPoint {
  return typeof p === "object" && p !== null;
}

export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function readFiniteRecordNumber(
  record: Record<string, unknown> | null | undefined,
  key: string,
  fallback: number
): number {
  const value = Number(record?.[key]);
  return Number.isFinite(value) ? value : fallback;
}

export function readNumberField(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function readStringField(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}
