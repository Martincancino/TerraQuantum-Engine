// ─── Fase R3 — Inversión desde paquete CSV ───────────────────────────────────
//
// Orquesta la inversión a partir de un CsvPackage (subido en LoadPanel, vista 3D):
// reconstruye el File + el payload con los parámetros del paquete, llama al
// endpoint existente invertGravityCsv, y carga el block model resultante en el
// visor (store global). No hay física aquí: solo arma el payload y rutea la
// respuesta del backend. Es el camino "Cargar modelo 3D" del flujo desacoplado.
//
// La lógica replica handleInvert + loadCsvModel3DFromInversion del panel de prep.
// En una iteración posterior (R3 cleanup) el panel de prep también pasará a usar
// este orquestador para eliminar la duplicación.

import {
  invertGravityCsv,
  getExplorationBlockModelForRunWithArrow,
  connectGeophysicsStatusStream,
  type GravityCsvInvertPayload,
  type CrsInfo,
} from "./frontendApi";
import { isJsonObject, readStringField, readNumberField } from "../../componentes/datos/helpers";
import type { VoxelMineralModel, VoxelData } from "../terraQuantumGeology";
import { type CsvPackage, csvPackageToFile } from "./csvPackage";
import { useAppStore } from "../../store/useAppStore";

type JsonObject = Record<string, unknown>;
type BackendVoxelModel = VoxelMineralModel & { visualMode?: string };

// Constantes de payload heredadas del panel de prep (no físicas: el backend
// deriva cutoff/lambda/grid cuando van en 0).
const INVERT_PAYLOAD_BASE = {
  nir: 83,
  fe: 79,
  region: "norte_chile",
  cutoffRadius: 0,
  lambdaMag: 0,
  alphaSpatial: 1.0,
} as const;
const LEGACY_INVERSION_PARAMS = { nx: 0, ny: 0, nz: 0, blockSize: 0, depth: 0 } as const;

// ─── Parsing de la respuesta del backend (shape, no física) ──────────────────

function readArrayProperty(value: unknown, key: string): unknown[] {
  const obj = isJsonObject(value) ? value : null;
  const field = obj?.[key];
  return Array.isArray(field) ? field : [];
}

function readNumberProperty(value: unknown, key: string, fallback = 0): number {
  const obj = isJsonObject(value) ? value : null;
  const n = readNumberField(obj?.[key]);
  return n ?? fallback;
}

function readStringProperty(value: unknown, key: string): string | undefined {
  const obj = isJsonObject(value) ? value : null;
  return readStringField(obj?.[key]) ?? undefined;
}

function readObjectProperty(value: unknown, key: string): JsonObject | undefined {
  const obj = isJsonObject(value) ? value : null;
  const field = obj?.[key];
  return isJsonObject(field) ? field : undefined;
}

function readStringArrayProperty(value: unknown, key: string): string[] {
  return readArrayProperty(value, key).filter(
    (item): item is string => typeof item === "string"
  );
}

function readBlockModelVisualMeta(value: unknown): Partial<BackendVoxelModel> {
  const obj = isJsonObject(value) ? value : null;
  if (!obj) return {};

  const densityMin = readNumberProperty(obj, "densityMin", Number.NaN);
  const densityMax = readNumberProperty(obj, "densityMax", Number.NaN);
  const scoreStats = readObjectProperty(obj, "scoreStats") as BackendVoxelModel["scoreStats"];
  const visualScoreStats = readObjectProperty(obj, "visualScoreStats") as BackendVoxelModel["visualScoreStats"];
  const densityStats = readObjectProperty(obj, "densityStats") as BackendVoxelModel["densityStats"];
  const rhoStats = readObjectProperty(obj, "rhoStats") as BackendVoxelModel["rhoStats"];
  const probabilityStats = readObjectProperty(obj, "probabilityStats") as BackendVoxelModel["probabilityStats"];
  const returnedScoreStats = readObjectProperty(obj, "returnedScoreStats") as BackendVoxelModel["returnedScoreStats"];
  const diagnosticStats = readObjectProperty(obj, "diagnosticStats") as BackendVoxelModel["diagnosticStats"];
  const returnedDiagnosticStats = readObjectProperty(obj, "returnedDiagnosticStats") as BackendVoxelModel["returnedDiagnosticStats"];
  const warnings = readStringArrayProperty(obj, "warnings");
  const isDegenerate = obj.isDegenerate === true || obj.is_degenerate === true;

  return {
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

function isVoxelData(value: unknown): value is VoxelData {
  return isJsonObject(value);
}

function buildVoxelModelFromBackend(data: unknown): BackendVoxelModel | null {
  const obj = isJsonObject(data) ? data : null;
  if (!obj) return null;

  const parsedCells = readArrayProperty(obj, "cells").filter(isVoxelData);
  if (parsedCells.length === 0) return null;

  const domainL = readNumberProperty(obj, "domainL");
  const domainH = readNumberProperty(obj, "domainH");
  const domainW = readNumberProperty(obj, "domainW");
  const cellSize = readNumberProperty(obj, "cellSize", 10);
  const visualMode = readStringProperty(obj, "visualMode");

  return {
    domainL,
    domainH,
    domainW,
    cellSize,
    cells: parsedCells,
    volumeM3: domainL * domainH * domainW,
    ...(visualMode ? { visualMode } : {}),
    ...readBlockModelVisualMeta(obj),
  };
}

function parseProjectRun(inversionResult: unknown): {
  projectId: string | null;
  runId: string | null;
} {
  const obj = isJsonObject(inversionResult) ? inversionResult : null;
  const rep = obj && isJsonObject(obj.report) ? obj.report : null;
  return {
    projectId:
      readStringField(obj?.project_id) ??
      readStringField(obj?.projectId) ??
      readStringField(rep?.project_id) ??
      readStringField(rep?.projectId),
    runId:
      readStringField(obj?.run_id) ??
      readStringField(obj?.runId) ??
      readStringField(rep?.run_id) ??
      readStringField(rep?.runId),
  };
}

function buildReportSummary(inversionResult: unknown): Record<string, unknown> | null {
  if (!isJsonObject(inversionResult)) return null;
  const rep = isJsonObject(inversionResult.report) ? inversionResult.report : null;
  if (!rep) return null;
  const out: Record<string, unknown> = {};
  const safeKeys = [
    "project_id", "projectId", "run_id", "runId",
    "overall_level", "risk_level", "fit_level", "uncertainty_level",
    "confidence_level", "recommendation", "drill_recommendation",
    "semantic_note", "avg_anomaly_intensity", "avg_grade",
  ];
  for (const k of safeKeys) {
    if (k in rep) out[k] = rep[k];
  }
  return Object.keys(out).length > 0 ? out : null;
}

// ─── Construcción del project/run id (mismo formato que el panel de prep) ─────

function buildCsvProjectId(filename?: string | null): string {
  const rawName = filename?.replace(/\.[^.]+$/, "") || "import";
  const cleanName = rawName
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 72);
  const projectName = cleanName || "import";
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const timestamp = [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`,
  ].join("_");
  const collisionSuffix =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? `_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`
      : "";

  return `csv_${projectName}_${timestamp}${collisionSuffix}`;
}

// ─── Payload de inversión a partir del paquete ───────────────────────────────

function buildInvertPayloadFromPackage(
  pkg: CsvPackage,
  projectId: string,
  runId: string,
): GravityCsvInvertPayload {
  const p = pkg.params;
  const isMagnetic = pkg.dataType === "magnetic";
  const lambdaValNum = p.lambdaMode === "custom" ? Number(p.lambdaCustom) : 0;

  return {
    ...INVERT_PAYLOAD_BASE,
    projectId,
    lat: p.latNorth?.trim?.() ?? "",
    lon: p.lonWest?.trim?.() ?? "",
    nx: LEGACY_INVERSION_PARAMS.nx,
    ny: LEGACY_INVERSION_PARAMS.ny,
    nz: LEGACY_INVERSION_PARAMS.nz,
    blockSize: LEGACY_INVERSION_PARAMS.blockSize,
    depth: LEGACY_INVERSION_PARAMS.depth,
    lambdaMag: lambdaValNum,
    densityMin: Number(p.densityMin),
    densityMax: Number(p.densityMax),
    gravimeterType: p.gravimeterType,
    runId,
    strict: p.strict,
    allowGRaw: p.allowGRaw,
    utmZone: p.utmZone.trim() ? p.utmZone.trim().toUpperCase() : undefined,
    acknowledgeSpatialRisk: p.acknowledgeSpatialRisk,
    acknowledgeRegionalScale: p.acknowledgeRegionalScale,
    ...(isMagnetic
      ? {
          dataType: "magnetic" as const,
          inclinationDeg: p.inclinationDeg,
          declinationDeg: p.declinationDeg,
          fieldIntensityNt: p.fieldIntensityNt,
          suscMin: Number(p.suscMin),
          suscMax: Number(p.suscMax),
        }
      : {}),
    pgiParamsJson: pkg.pgiParams?.enabled
      ? JSON.stringify({
          components: [
            { mean_density_t_m3: 2.6, std_density_t_m3: 0.2, weight: 0.5 },
            { mean_density_t_m3: 3.0, std_density_t_m3: 0.2, weight: 0.5 },
          ],
          alpha_pgi: pkg.pgiParams.alpha_pgi,
          max_iter: pkg.pgiParams.max_iter,
          convergence_tol: 0.001,
          fit_from_model: true,
          n_components_auto: pkg.pgiParams.n_components_auto,
        })
      : null,
    remanenceJson: pkg.remanenceParams?.enabled && isMagnetic
      ? JSON.stringify({
          enabled: pkg.remanenceParams.enabled,
          q_ratio: pkg.remanenceParams.q_ratio,
          remanence_inc_deg: pkg.remanenceParams.remanence_inc_deg,
          remanence_dec_deg: pkg.remanenceParams.remanence_dec_deg,
          inversion_mode: pkg.remanenceParams.inversion_mode,
          do_q_sweep: pkg.remanenceParams.do_q_sweep,
        })
      : null,
    paddingKappa: Math.pow(10, p.paddingKappaLog),
    anchorKappa: Math.pow(10, p.anchorKappaLog),
    autoKappa: p.autoKappa,
    ...(pkg.boreholes && pkg.boreholes.length > 0 ? { boreholes: pkg.boreholes } : {}),
  };
}

// ─── Orquestador público ─────────────────────────────────────────────────────

export type InvertFromPackageHandlers = {
  onStage?: (stage: string | null) => void;
  onProgress?: (progress: number) => void;
};

export type InvertFromPackageResult =
  | { ok: true }
  | {
      ok: false;
      error: string;
      kind?: "spatial_gate" | "regional_gate" | "runtime" | "generic";
      detail?: unknown;
    };

/**
 * Corre la inversión a partir del paquete y carga el block model en el visor.
 * Maneja directamente el store global (activeRun, model, viewMode, show3D, view,
 * georef). Devuelve el resultado para que la UI muestre errores/gates.
 */
export async function invertFromPackage(
  pkg: CsvPackage,
  handlers: InvertFromPackageHandlers = {},
  displayResolutionFactor = 1,
): Promise<InvertFromPackageResult> {
  const store = useAppStore.getState();
  const isMagnetic = pkg.dataType === "magnetic";

  const projectId = buildCsvProjectId(pkg.csv.filename);
  const runId = `run_csv_${new Date().toISOString().replace(/[:.]/g, "-")}`;

  store.setActiveRun({
    projectId,
    runId,
    source: "csv",
    status: "loading",
    error: null,
  });

  handlers.onStage?.("queued");
  handlers.onProgress?.(0);

  const closeStream = connectGeophysicsStatusStream(
    projectId,
    runId,
    (ev) => {
      handlers.onStage?.(ev.stage ?? ev.status ?? null);
      handlers.onProgress?.(typeof ev.progress === "number" ? ev.progress : 0);
    },
    () => {},
  );

  const payload = buildInvertPayloadFromPackage(pkg, projectId, runId);
  const file = csvPackageToFile(pkg);

  const res = await invertGravityCsv(file, payload);
  closeStream();
  handlers.onStage?.(null);
  handlers.onProgress?.(0);

  if (!res.ok) {
    const rawData = res.data as unknown;
    if (isJsonObject(rawData)) {
      const detail = rawData.detail;
      if (isJsonObject(detail) && detail.error === "SPATIAL_READINESS_GATE") {
        store.setActiveRun({ source: "csv", status: "error", error: "SPATIAL_READINESS_GATE" });
        return { ok: false, error: "El backend exige reconocimiento del riesgo espacial.", kind: "spatial_gate", detail };
      }
      if (isJsonObject(detail) && detail.error === "REGIONAL_SCALE_PREFLIGHT") {
        store.setActiveRun({ source: "csv", status: "error", error: "REGIONAL_SCALE_PREFLIGHT" });
        return { ok: false, error: "El dataset no permite una inversión única (escala regional).", kind: "regional_gate", detail };
      }
      if (isJsonObject(detail) && detail.error === "INVERSION_RUNTIME_ERROR") {
        const msg = String((detail.message as string) || "Error interno del motor de inversión.");
        const errType = String((detail.type as string) || "Error");
        store.setActiveRun({ source: "csv", status: "error", error: msg });
        return { ok: false, error: `[${errType}] ${msg}`, kind: "runtime", detail };
      }
    }
    const errMsg = res.error || "Error al solicitar la inversión geofísica.";
    store.setActiveRun({ source: "csv", status: "error", error: errMsg });
    return { ok: false, error: errMsg, kind: "generic", detail: rawData };
  }

  if (res.data?.georef) {
    const georef = res.data.georef;
    const crsInfoFromResponse: CrsInfo = {
      input_crs: georef.input_crs ?? null,
      epsg_code: georef.epsg_code ?? null,
      crs_source: georef.crs_source ?? null,
      crs_confidence: georef.crs_confidence ?? null,
      utm_zone: georef.utm_zone ?? null,
      utm_hemisphere: georef.utm_hemisphere ?? null,
    };
    store.setGeorefState({
      footprint: georef.footprint ?? null,
      confidence: georef.confidence ?? null,
      warnings: georef.warnings ?? [],
      crsInfo: crsInfoFromResponse,
    });
  }

  if (!res.data) {
    const errMsg = "La inversión no devolvió una respuesta válida.";
    store.setActiveRun({ source: "csv", status: "error", error: errMsg });
    return { ok: false, error: errMsg, kind: "generic" };
  }

  if (res.data.status !== "done") {
    return { ok: false, error: "La inversión no finalizó correctamente.", kind: "generic" };
  }

  // Cargar el block model resultante en el visor.
  const inversionResult = res.data.inversionResult;
  const { projectId: pid, runId: rid } = parseProjectRun(inversionResult);
  if (!pid || !rid) {
    const errMsg = "No se detectó projectId/runId en la respuesta de inversión.";
    store.setActiveRun({ source: "csv", status: "error", error: errMsg });
    return { ok: false, error: errMsg, kind: "generic" };
  }

  const reportSummary = buildReportSummary(inversionResult);

  store.setActiveRun({
    projectId: pid,
    runId: rid,
    source: "csv",
    status: "loading",
    error: null,
    reportSummary,
  });

  const blockRes = await getExplorationBlockModelForRunWithArrow(
    pid, rid, "exploration", 5000, displayResolutionFactor,
  );

  if (!blockRes.ok || !blockRes.data) {
    const errMsg = "No se pudo cargar el modelo 3D preliminar de la corrida.";
    store.setActiveRun({ projectId: pid, runId: rid, source: "csv", status: "error", error: errMsg });
    return { ok: false, error: errMsg, kind: "generic" };
  }

  const backendModel = buildVoxelModelFromBackend(blockRes.data);
  if (!backendModel) {
    const errMsg = "El modelo devuelto no tiene celdas válidas.";
    store.setActiveRun({ projectId: pid, runId: rid, source: "csv", status: "error", error: errMsg });
    return { ok: false, error: errMsg, kind: "generic" };
  }

  store.setModel(backendModel);
  store.setViewMode(isMagnetic ? "susceptibility" : "density");
  store.setShow3D(true);
  store.setView("figura 3d");
  store.setActiveRun({
    projectId: pid,
    runId: rid,
    source: "csv",
    status: "ready",
    error: null,
    reportSummary,
  });

  return { ok: true };
}
