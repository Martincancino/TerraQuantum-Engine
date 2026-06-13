"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { previewGravityCsv, GravityImportPreviewResponse, invertGravityCsv, GravityCsvInvertResponse, GravityCsvInvertPayload, getExplorationBlockModelForRun, getExplorationBlockModelForRunWithArrow, CoordinateTransformData, CrsInfo, SpatialReadiness, SpatialReadinessGateError, RegionalScalePreflight, RegionalScaleGateError, GravityCorrectionReport, connectGeophysicsStatusStream } from "../lib/terraquantum/frontendApi";
import { useAppStore } from "../store/useAppStore";
import GravityCorrectionWizard from "./GravityCorrectionWizard";
import { type VoxelMineralModel, type VoxelData } from "../lib/terraQuantumGeology";
import { isJsonObject, readStringField, readNumberField } from "./datos/helpers";

// ─── Georef UX helpers (R1-FE-3) ──────────────────────────────────────────

function getGeorefBadgeLabel(confidence?: string | null): string {
  const c = (confidence ?? "MISSING").toUpperCase();
  if (c === "HIGH") return "Georreferenciación ALTA";
  if (c === "MEDIUM") return "Georreferenciación MEDIA";
  if (c === "LOW") return "Georreferenciación BAJA — contexto visual";
  return "Sin georreferenciación";
}

function getGeorefBadgeClass(confidence?: string | null): string {
  const c = (confidence ?? "MISSING").toUpperCase();
  if (c === "HIGH") return "text-green-400 border-green-600/40 bg-green-900/20";
  if (c === "MEDIUM") return "text-yellow-400 border-yellow-600/40 bg-yellow-900/20";
  if (c === "LOW") return "text-orange-400 border-orange-600/40 bg-orange-900/20";
  return "text-red-400 border-red-600/40 bg-red-900/20";
}

function getGeorefExplanation(confidence?: string | null): string {
  const c = (confidence ?? "MISSING").toUpperCase();
  if (c === "HIGH") return "El CSV tiene coordenadas geográficas directas. El footprint representa el área de observación dentro de la precisión declarada. Requiere validación profesional antes de interpretación geológica.";
  if (c === "MEDIUM") return "Coordenadas aproximadas. El footprint es plausible, pero no debe interpretarse como ubicación geográfica validada sin revisión profesional.";
  if (c === "LOW") return "Metros locales anclados a punto central o sistema de baja confianza. El terreno visible debe tratarse como contexto visual, no como topografía co-registrada con el survey.";
  return "El modelo no tiene ubicación geográfica absoluta. No es posible afirmar dónde está la anomalía en el mapa.";
}

// ─── UTM zone helpers (R2-FE) ─────────────────────────────────────────────

function normalizeUtmZone(raw: string): string {
  return raw.trim().toUpperCase();
}

function validateUtmZone(raw: string): string | null {
  const val = normalizeUtmZone(raw);
  if (!val) return null;
  if (/^\d{1,2}$/.test(val)) return "Agregar hemisferio N/S (ej: 19S)";
  if (!/^\d{1,2}[NS]$/.test(val)) return "Formato inválido. Usa ej: 19S o 19N";
  const zoneNum = parseInt(val.slice(0, -1), 10);
  if (zoneNum < 1 || zoneNum > 60) return "Zona UTM inválida (1-60)";
  return null;
}

function deriveEpsgFromUtmZone(raw: string): number | null {
  const val = normalizeUtmZone(raw);
  if (!val) return null;
  const match = val.match(/^(\d{1,2})([NS])$/);
  if (!match) return null;
  const zoneNum = parseInt(match[1], 10);
  if (zoneNum < 1 || zoneNum > 60) return null;
  return match[2] === "N" ? 32600 + zoneNum : 32700 + zoneNum;
}

// ─── Spatial Readiness helpers (R3.5-F) ──────────────────────────────────

function getSpatialReadinessColors(level?: string | null): { border: string; bg: string; text: string } {
  const l = (level ?? "").toUpperCase();
  if (l === "NO_SPATIAL_DATA")
    return { border: "border-red-600/40", bg: "bg-red-900/20", text: "text-red-400" };
  if (l === "LOCAL_UNANCHORED" || l === "LOCAL_ANCHORED_CENTER" || l === "UTM_NO_ZONE")
    return { border: "border-yellow-600/40", bg: "bg-yellow-900/20", text: "text-yellow-400" };
  if (l === "UTM_WITH_ZONE" || l === "GEOGRAPHIC_COORDS" || l === "PROFESSIONAL_SURVEY")
    return { border: "border-green-600/40", bg: "bg-green-900/20", text: "text-green-400" };
  return { border: "border-neutral-600/40", bg: "bg-neutral-900/20", text: "text-neutral-400" };
}

function boolLabel(value?: boolean): string {
  return value === true ? "Sí" : "No";
}

// ──────────────────────────────────────────────────────────────────────────

type JsonObject = Record<string, unknown>;
type BackendVoxelModel = VoxelMineralModel & { visualMode?: string };

type GeorefBadge = { label: string; classes: string; desc: string };

function getGeorefBadge(ct: CoordinateTransformData | null | undefined): GeorefBadge {
  const cs = (ct?.input_coordinate_system ?? "unknown").toLowerCase();
  const conf = (ct?.input_confidence ?? "low").toLowerCase();

  if (cs === "latlon" && conf !== "low") {
    return {
      label: "Georreferenciación ALTA",
      classes: "text-green-400 border-green-600/40 bg-green-900/20",
      desc: "El CSV tiene coordenadas geográficas directas. El footprint representa el área de observación dentro de la precisión declarada. Requiere validación profesional antes de interpretación geológica.",
    };
  }
  if (cs === "utm" && conf !== "low") {
    return {
      label: "Georreferenciación MEDIA",
      classes: "text-yellow-400 border-yellow-600/40 bg-yellow-900/20",
      desc: "Coordenadas aproximadas. El footprint es plausible, pero no debe interpretarse como ubicación geográfica validada sin revisión profesional.",
    };
  }
  if (cs === "local_meters") {
    return {
      label: "Georreferenciación BAJA — contexto visual",
      classes: "text-orange-400 border-orange-600/40 bg-orange-900/20",
      desc: "Metros locales anclados a punto central o sistema de baja confianza. El terreno visible debe tratarse como contexto visual, no como topografía co-registrada con el survey.",
    };
  }
  return {
    label: "Sin georreferenciación",
    classes: "text-red-400 border-red-600/40 bg-red-900/20",
    desc: "El modelo no tiene ubicación geográfica absoluta. No es posible afirmar dónde está la anomalía en el mapa.",
  };
}

function mapPriorityClassLabel(value: string | null | undefined): string {
  const v = String(value || "").toUpperCase().trim();
  if (v === "HIGH_RELATIVE_PRIORITY" || v === "DRILL") return "Prioridad relativa alta";
  if (v === "MEDIUM_RELATIVE_PRIORITY" || v === "OBSERVE" || v === "WAIT") return "Prioridad relativa media";
  if (v === "LOW_RELATIVE_PRIORITY") return "Prioridad relativa baja";
  if (v === "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE" || v === "UNCLASSIFIED") return "Sin clasificar";
  return v || "N/A";
}

// Parámetros de grilla: 0 = el backend usa el auto_grid calculado del CSV.
// NO enviar valores fijos aquí: desde R3.8-A el backend PRIORIZA cualquier
// valor > 0 del formulario, y una grilla fija (ej. 32×20×32 @ 25 m) rompe
// surveys reales (kernel vacío → 422) cuya extensión no calza con esa caja.
const LEGACY_INVERSION_PARAMS = { nx: 0, ny: 0, nz: 0, blockSize: 0, depth: 0 } as const;

function buildCsvProjectId(filename?: string | null): string {
  const rawName = filename?.replace(/\.[^.]+$/, "") || "import";
  const cleanName = rawName
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
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

function parseCsvInversionProjectRun(inversionResult: unknown): {
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

const INVERT_STAGE_LABELS: Record<string, string> = {
  queued: "En cola...",
  building_kernel: "Construyendo kernel de sensibilidad...",
  running_lsqr: "Ejecutando inversor LSQR...",
  computing_uq: "Calculando incertidumbre...",
  exporting_model: "Exportando modelo 3D...",
  running: "Ejecutando inversión...",
  done: "Inversión completa",
  completed: "Inversión completa",
  error: "Error en inversión",
};

export default function GravityCsvPreviewPanel() {
  const {
    fileGravimetry, setFileGravimetry,
    fileMagnetometry, setFileMagnetometry,
    latNorth, setLatNorth,
    latSouth, setLatSouth,
    lonEast, setLonEast,
    lonWest, setLonWest,
    gravityPreviewResult: result, setGravityPreviewResult: setResult,
    gravityInvertResult: invertResult, setGravityInvertResult: setInvertResult
  } = useAppStore();

  const file = fileGravimetry; // Retrocompatibilidad para endpoints que solo toman 'file'

  const [strict, setStrict] = useState(true);
  const [allowGRaw, setAllowGRaw] = useState(false);
  const [previewLimit, setPreviewLimit] = useState(20);

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [invertLoading, setInvertLoading] = useState(false);
  const [invertErrorMsg, setInvertErrorMsg] = useState<string | null>(null);
  const [invertStage, setInvertStage] = useState<string | null>(null);
  const [invertProgress, setInvertProgress] = useState<number>(0);

  // Fase 9A — Magnetometría: "gravity" (default) | "magnetic". Lo fija el input
  // de archivo usado; en modo magnetic la inversión rutea al motor de susceptibilidad.
  const [dataType, setDataType] = useState<"gravity" | "magnetic">("gravity");
  // Parámetros del campo geomagnético inducido (defaults norte de Chile). El backend
  // los valida; el usuario puede ajustarlos según la región del survey.
  const [inclinationDeg, setInclinationDeg] = useState<number>(-30);
  const [declinationDeg, setDeclinationDeg] = useState<number>(2);
  const [fieldIntensityNt, setFieldIntensityNt] = useState<number>(23500);
  const [suscMin, setSuscMin] = useState<string>("0.0");
  const [suscMax, setSuscMax] = useState<string>("1.0");

  const [loading3D, setLoading3D] = useState(false);
  const [load3DError, setLoad3DError] = useState<string | null>(null);
  const [load3DMessage, setLoad3DMessage] = useState<string | null>(null);

  const [showCorrectionWizard, setShowCorrectionWizard] = useState(false);
  const [correctedFile, setCorrectedFile] = useState<File | null>(null);
  const [correctionReport, setCorrectionReport] = useState<GravityCorrectionReport | null>(null);

  const [utmZone, setUtmZone] = useState<string>("");
  // Tier 1 B6 — controles físicos. El frontend solo recolecta y valida forma;
  // la física (bounds, sigma, selección de λ) la resuelve el backend.
  const [densityMin, setDensityMin] = useState<string>("0.0");
  const [densityMax, setDensityMax] = useState<string>("5.5");
  const [gravimeterType, setGravimeterType] = useState<string>("unknown");
  const [lambdaMode, setLambdaMode] = useState<"auto" | "custom">("auto");
  const [lambdaCustom, setLambdaCustom] = useState<string>("0.1");
  const [acknowledgeSpatialRisk, setAcknowledgeSpatialRisk] = useState(false);
  const [spatialGateError, setSpatialGateError] = useState<SpatialReadinessGateError | null>(null);
  const [acknowledgeRegionalScale, setAcknowledgeRegionalScale] = useState(false);
  const [regionalGateError, setRegionalGateError] = useState<RegionalScaleGateError | null>(null);

  const utmZoneError = useMemo(() => validateUtmZone(utmZone), [utmZone]);
  const derivedEpsg = useMemo(() => deriveEpsgFromUtmZone(utmZone), [utmZone]);
  const isUtmDetected = useMemo(() => {
    const type = result?.georef_preview?.type;
    const detected = result?.csv_analysis?.coordinate_system?.detected;
    return type === "csv_utm" || type === "utm" || detected === "utm";
  }, [result]);

  const setModel = useAppStore(state => state.setModel);
  const setViewMode = useAppStore(state => state.setViewMode);
  const setView = useAppStore(state => state.setView);
  const setShow3D = useAppStore(state => state.setShow3D);
  const setActiveRun = useAppStore(state => state.setActiveRun);
  const displayResolutionFactor = useAppStore(state => state.displayResolutionFactor);

  // Recarga el modelo 3D al cambiar la resolución de display (sub-muestreo
  // trilineal), sin re-invertir: solo re-pide el block model al factor nuevo.
  const prevResFactorRef = useRef(displayResolutionFactor);
  useEffect(() => {
    if (prevResFactorRef.current === displayResolutionFactor) return;
    prevResFactorRef.current = displayResolutionFactor;
    const run = useAppStore.getState().activeRun;
    const pid = run?.projectId;
    const rid = run?.runId;
    if (!pid || !rid || run?.status !== "ready") return;
    let cancelled = false;
    (async () => {
      const res = await getExplorationBlockModelForRunWithArrow(
        pid, rid, "exploration", 5000, displayResolutionFactor,
      );
      if (cancelled || !res.ok || !res.data) return;
      const m = buildVoxelModelFromBackend(res.data);
      if (m) useAppStore.getState().setModel(m);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayResolutionFactor]);
  const clearActiveRun = useAppStore(state => state.clearActiveRun);
  const setGeorefState = useAppStore(state => state.setGeorefState);

  // Se han eliminado userLat y userLon en favor del Bounding Box en Zustand
  const [geoError, setGeoError] = useState<string | null>(null);

  const [invertPayloadBase] = useState<Omit<GravityCsvInvertPayload, "nx" | "ny" | "nz" | "blockSize" | "depth" | "lat" | "lon">>({
    nir: 83,
    fe: 79,
    region: "norte_chile",
    // 0 = auto: el backend deriva cutoff_radius del auto_grid (cubre la
    // profundidad del modelo) y lambda del operating point validado.
    // Un cutoff fijo (300 m) dejaba >80% de vóxeles muertos en surveys
    // regionales, y lambda=5e-5 era el valor legacy pre-preconditioning.
    cutoffRadius: 0,
    lambdaMag: 0,
    alphaSpatial: 1.0,
  });

  // ---------------------------------------------------------------------------
  // Helpers locales — devuelven Record<string, unknown> | null, sin usar any
  // ---------------------------------------------------------------------------

  function buildObservationsSummary(
    previewData: GravityImportPreviewResponse | null
  ): Record<string, unknown> | null {
    if (!previewData) return null;
    return {
      previewCount: previewData.previewCount ?? null,
      totalObservations: previewData.totalObservations ?? null,
      warnings: previewData.warnings ?? [],
      errors: previewData.errors ?? [],
    };
  }

  function buildReportSummary(
    inversionResult: unknown
  ): Record<string, unknown> | null {
    if (!isJsonObject(inversionResult)) return null;
    const rep = isJsonObject(inversionResult.report) ? inversionResult.report : null;
    if (!rep) return null;
    // Extrae solo campos escalares seguros; deja fuera arrays grandes de datos
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

  // ---------------------------------------------------------------------------

  const validateCoords = (): string | null => {
    const fields = [
      { name: "Latitud Norte", val: latNorth },
      { name: "Latitud Sur", val: latSouth },
      { name: "Longitud Este", val: lonEast },
      { name: "Longitud Oeste", val: lonWest }
    ];
    
    let hasAny = false;
    for (const f of fields) {
      if (f.val.trim()) hasAny = true;
    }
    if (!hasAny) return null; // Coordenadas opcionales si no se ingresa ninguna
    
    for (const f of fields) {
      if (!f.val.trim()) return `Falta ${f.name} para el Bounding Box.`;
      const num = Number(f.val.trim());
      if (!Number.isFinite(num)) return `${f.name} inválida. Usa grados decimales.`;
      if (f.name.includes("Latitud") && (num < -90 || num > 90)) return `${f.name} fuera de rango.`;
      if (f.name.includes("Longitud") && (num < -180 || num > 180)) return `${f.name} fuera de rango.`;
    }
    
    if (Number(latSouth) >= Number(latNorth)) return "Latitud Sur debe ser menor a Latitud Norte.";
    if (Number(lonWest) >= Number(lonEast)) return "Longitud Oeste debe ser menor a Longitud Este.";

    return null;
  };

  const handleFileGravimetryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFileGravimetry(e.target.files[0]);
      setDataType("gravity");
      setResult(null);
      setErrorMsg(null);
      setInvertResult(null);
      setInvertErrorMsg(null);
      setLoad3DError(null);
      setLoad3DMessage(null);
      setGeoError(null);
      setUtmZone("");
      setAcknowledgeSpatialRisk(false);
      setSpatialGateError(null);
      setAcknowledgeRegionalScale(false);
      setRegionalGateError(null);
      setCorrectedFile(null);
      setCorrectionReport(null);
      setShowCorrectionWizard(false);
      clearActiveRun();
    }
  };

  const handleFileMagnetometryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFileMagnetometry(e.target.files[0]);
      setDataType("magnetic");
      setResult(null);
      setErrorMsg(null);
      setInvertResult(null);
      setInvertErrorMsg(null);
      setLoad3DError(null);
      setLoad3DMessage(null);
      setGeoError(null);
      setSpatialGateError(null);
      setRegionalGateError(null);
      setCorrectedFile(null);
      setCorrectionReport(null);
      setShowCorrectionWizard(false);
      clearActiveRun();
    }
  };

  const handleValidate = async () => {
    const isMagnetic = dataType === "magnetic";
    const valFile = isMagnetic ? fileMagnetometry : file;
    if (!valFile) {
      setErrorMsg(
        isMagnetic ? "Debes seleccionar un CSV de magnetometría." : "Debes seleccionar un archivo CSV.",
      );
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    setResult(null);
    setLoad3DError(null);
    setLoad3DMessage(null);

    const effectiveFile = isMagnetic ? valFile : (correctedFile ?? file ?? valFile);
    const res = await previewGravityCsv(effectiveFile, {
      strict: isMagnetic ? false : strict,
      allowGRaw: isMagnetic ? false : (allowGRaw || correctedFile !== null),
      previewLimit,
      dataType: isMagnetic ? "magnetic" : "gravity",
    });
    setLoading(false);

    if (!res.ok) {
      setErrorMsg(res.error || "Error al comunicarse con el backend.");
      return;
    }

    setResult(res.data);
    setAcknowledgeSpatialRisk(false);
    setSpatialGateError(null);
    setAcknowledgeRegionalScale(false);
    setRegionalGateError(null);
    setInvertResult(null);
    setInvertErrorMsg(null);
    setLoad3DError(null);
    setLoad3DMessage(null);
  };

  const loadCsvModel3DFromInversion = async (
    inversionResult: unknown,
    previewData: GravityImportPreviewResponse | null
  ): Promise<boolean> => {
    const { projectId, runId } = parseCsvInversionProjectRun(inversionResult);
    if (!projectId || !runId) {
      const errMsg = "No se detecto projectId/runId en la respuesta de inversion CSV.";
      setLoad3DError(errMsg);
      setActiveRun({ source: "csv", status: "error", error: errMsg });
      return false;
    }

    const reportSummary = buildReportSummary(inversionResult);
    const observationsSummary = buildObservationsSummary(previewData);

    // Extraer focusing antes de buildReportSummary (safeKeys no lo incluye)
    const rawReport = isJsonObject(inversionResult) && isJsonObject(inversionResult.report)
      ? inversionResult.report
      : null;
    const focusing = isJsonObject(rawReport?.focusing) ? rawReport.focusing : null;

    // Corrida identificada, iniciamos carga del modelo
    setActiveRun({
      projectId,
      runId,
      source: "csv",
      status: "loading",
      error: null,
      importMetadata: previewData?.importMetadata ?? null,
      observationsSummary,
      reportSummary,
      focusing,
    });

    setLoading3D(true);
    setLoad3DError(null);
    setLoad3DMessage(null);

    const res = await getExplorationBlockModelForRunWithArrow(projectId, runId, "exploration", 5000, displayResolutionFactor);
    setLoading3D(false);

    if (!res.ok || !res.data) {
      const errMsg = "No se pudo cargar el modelo 3D preliminar de la corrida CSV.";
      setLoad3DError(errMsg);
      setActiveRun({ projectId, runId, source: "csv", status: "error", error: errMsg });
      return false;
    }

    const backendModel = buildVoxelModelFromBackend(res.data);
    if (!backendModel) {
      const errMsg = "El modelo devuelto no tiene celdas validas.";
      setLoad3DError(errMsg);
      setActiveRun({ projectId, runId, source: "csv", status: "error", error: errMsg });
      return false;
    }

    setModel(backendModel);
    // Magnetometría: el visor colorea por susceptibilidad (no densidad).
    setViewMode(dataType === "magnetic" ? "susceptibility" : "density");
    setShow3D(true);
    setView("figura 3d");
    setLoad3DMessage("Modelo 3D cargado en el visor");

    // Corrida lista y modelo visualizable
    setActiveRun({
      projectId,
      runId,
      source: "csv",
      status: "ready",
      error: null,
      importMetadata: previewData?.importMetadata ?? null,
      observationsSummary,
      reportSummary,
      focusing,
    });

    return true;
  };

  const handleInvert = async () => {
    const isMagnetic = dataType === "magnetic";
    const invFile = isMagnetic ? fileMagnetometry : file;
    if (!invFile) {
      setInvertErrorMsg(
        isMagnetic
          ? "Debes seleccionar un CSV de magnetometría."
          : "Debes seleccionar y validar un archivo CSV.",
      );
      return;
    }

    const geoErr = validateCoords();
    if (geoErr) {
      setGeoError(geoErr);
      return;
    }
    setGeoError(null);

    if (utmZone.trim() && utmZoneError) {
      setGeoError(utmZoneError);
      return;
    }

    // Validación de forma de los controles físicos (los rangos finos los valida el backend)
    const dMinNum = Number(densityMin);
    const dMaxNum = Number(densityMax);
    if (!isMagnetic && (!Number.isFinite(dMinNum) || !Number.isFinite(dMaxNum) || dMinNum >= dMaxNum)) {
      setGeoError("Bounds de densidad inválidos: density_min debe ser un número menor que density_max.");
      return;
    }
    const lambdaValNum = lambdaMode === "custom" ? Number(lambdaCustom) : 0;
    if (lambdaMode === "custom" && (!Number.isFinite(lambdaValNum) || lambdaValNum <= 0)) {
      setGeoError("Lambda personalizado debe ser un número mayor que 0.");
      return;
    }

    setInvertLoading(true);
    setInvertErrorMsg(null);
    setSpatialGateError(null);
    setRegionalGateError(null);
    setInvertResult(null);
    setLoad3DError(null);
    setLoad3DMessage(null);
    setInvertStage("queued");
    setInvertProgress(0);

    // Señalamos inicio de inversión en activeRun
    const projectId = buildCsvProjectId(invFile.name);
    const runId = `run_csv_${new Date().toISOString().replace(/[:.]/g, "-")}`;

    setActiveRun({
      projectId,
      runId,
      source: "csv",
      status: "loading",
      error: null,
      importMetadata: result?.importMetadata ?? null,
      observationsSummary: buildObservationsSummary(result),
    });

    // SSE stream para progreso en tiempo real (§2.6)
    const closeStream = connectGeophysicsStatusStream(
      projectId,
      runId,
      (ev) => {
        setInvertStage(ev.stage ?? ev.status ?? null);
        setInvertProgress(typeof ev.progress === "number" ? ev.progress : 0);
      },
      () => {
        // terminal — nada extra; invertGravityCsv() resolverá la promesa
      },
    );

    const payloadWithFlags = {
      ...invertPayloadBase,
      projectId,
      lat: latNorth.trim(),
      lon: lonWest.trim(),
      nx: LEGACY_INVERSION_PARAMS.nx,
      ny: LEGACY_INVERSION_PARAMS.ny,
      nz: LEGACY_INVERSION_PARAMS.nz,
      blockSize: LEGACY_INVERSION_PARAMS.blockSize,
      depth: LEGACY_INVERSION_PARAMS.depth,
      // Controles físicos (B6): λ=0 dispara selección automática en backend
      // (Morozov si el gravímetro declarado hace el chi² interpretable).
      lambdaMag: lambdaValNum,
      densityMin: dMinNum,
      densityMax: dMaxNum,
      gravimeterType,
      runId,
      strict,
      allowGRaw,
      utmZone: (utmZone.trim() && !utmZoneError) ? utmZone.trim().toUpperCase() : undefined,
      acknowledgeSpatialRisk,
      acknowledgeRegionalScale,
      // Fase 9A — Magnetometría: rutea al motor de susceptibilidad.
      ...(isMagnetic
        ? {
            dataType: "magnetic" as const,
            inclinationDeg: inclinationDeg,
            declinationDeg: declinationDeg,
            fieldIntensityNt: fieldIntensityNt,
            suscMin: Number(suscMin),
            suscMax: Number(suscMax),
          }
        : {}),
    };

    const effectiveFile = isMagnetic ? invFile : (correctedFile ?? invFile);
    const res = await invertGravityCsv(effectiveFile, {
      ...payloadWithFlags,
      allowGRaw: payloadWithFlags.allowGRaw || correctedFile !== null,
    });
    closeStream();
    setInvertLoading(false);
    setInvertStage(null);
    setInvertProgress(0);

    if (!res.ok) {
      const rawData = res.data as unknown;
      if (isJsonObject(rawData)) {
        const detail = rawData.detail;
        if (isJsonObject(detail) && detail.error === "SPATIAL_READINESS_GATE") {
          setSpatialGateError(detail as unknown as SpatialReadinessGateError);
          setActiveRun({ source: "csv", status: "error", error: "SPATIAL_READINESS_GATE" });
          return;
        }
        if (isJsonObject(detail) && detail.error === "REGIONAL_SCALE_PREFLIGHT") {
          setRegionalGateError(detail as unknown as RegionalScaleGateError);
          setActiveRun({ source: "csv", status: "error", error: "REGIONAL_SCALE_PREFLIGHT" });
          return;
        }
        if (isJsonObject(detail) && detail.error === "INVERSION_RUNTIME_ERROR") {
          const msg = String((detail.message as string) || "Error interno del motor de inversión.");
          const errType = String((detail.type as string) || "Error");
          setInvertErrorMsg(`[${errType}] ${msg}`);
          setActiveRun({ source: "csv", status: "error", error: msg });
          return;
        }
      }
      const errMsg = res.error || "Error al solicitar la inversión geofísica.";
      setInvertErrorMsg(errMsg);
      setActiveRun({ source: "csv", status: "error", error: errMsg });
      return;
    }

    setInvertResult(res.data);

    // Guardar georef + CRS en store desde el response de inversión (R1-FE-3 + R2-FE)
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
      setGeorefState({
        footprint: georef.footprint ?? null,
        confidence: georef.confidence ?? null,
        warnings: georef.warnings ?? [],
        crsInfo: crsInfoFromResponse,
      });
    }

    if (!res.data) {
      const errMsg = "La inversion no devolvio una respuesta valida.";
      setInvertErrorMsg(errMsg);
      setActiveRun({ source: "csv", status: "error", error: errMsg });
      return;
    }

    if (res.data.status !== "done") {
      return;
    }

    await loadCsvModel3DFromInversion(res.data.inversionResult, result);
  };

  const handleLoadCsvModel3D = async () => {
    const { projectId, runId } = parseCsvInversionProjectRun(invertResult?.inversionResult || null);
    if (!projectId || !runId) {
      setLoad3DError("No hay projectId o runId detectables en esta corrida.");
      return;
    }

    const reportSummary = buildReportSummary(invertResult?.inversionResult ?? null);
    const observationsSummary = buildObservationsSummary(result);

    setActiveRun({
      projectId,
      runId,
      source: "csv",
      status: "loading",
      error: null,
      importMetadata: result?.importMetadata ?? null,
      observationsSummary,
      reportSummary,
    });

    setLoading3D(true);
    setLoad3DError(null);

    const res = await getExplorationBlockModelForRunWithArrow(projectId, runId, "exploration", 5000, displayResolutionFactor);
    setLoading3D(false);

    if (!res.ok || !res.data) {
      const errMsg = "No se pudo cargar el modelo 3D preliminar de la corrida CSV.";
      setLoad3DError(errMsg);
      setActiveRun({ projectId, runId, source: "csv", status: "error", error: errMsg });
      return;
    }

    try {
      const data = res.data as JsonObject;
      const parsedCells = Array.isArray(data.cells) ? data.cells as unknown as VoxelData[] : [];
      if (parsedCells.length === 0) {
        const errMsg = "El modelo devuelto no tiene celdas válidas.";
        setLoad3DError(errMsg);
        setActiveRun({ projectId, runId, source: "csv", status: "error", error: errMsg });
        return;
      }

      const domainL = typeof data.domainL === "number" ? data.domainL : 0;
      const domainH = typeof data.domainH === "number" ? data.domainH : 0;
      const domainW = typeof data.domainW === "number" ? data.domainW : 0;
      const cellSize = typeof data.cellSize === "number" ? data.cellSize : 10;

      const backendModel: BackendVoxelModel = {
        domainL,
        domainH,
        domainW,
        cellSize,
        cells: parsedCells,
        volumeM3: domainL * domainH * domainW,
        visualMode: typeof data.visualMode === "string" ? data.visualMode : undefined,
        ...readBlockModelVisualMeta(data),
      };

      setModel(backendModel);
      setViewMode(dataType === "magnetic" ? "susceptibility" : "density");
      setShow3D(true);
      setView("figura 3d");
      setLoad3DMessage("Modelo 3D cargado en el visor");

      setActiveRun({
        projectId,
        runId,
        source: "csv",
        status: "ready",
        error: null,
        importMetadata: result?.importMetadata ?? null,
        observationsSummary,
        reportSummary,
      });
    } catch {
      const errMsg = "Error al interpretar el modelo de densidad/anomalía.";
      setLoad3DError(errMsg);
      setActiveRun({ projectId, runId, source: "csv", status: "error", error: errMsg });
    }
  };

  function renderSpatialReadinessPanel(
    spatialReadiness: SpatialReadiness | null | undefined,
    className = "mt-6"
  ) {
    if (!spatialReadiness) return null;

    const sr = spatialReadiness;
    const colors = getSpatialReadinessColors(sr.level);
    const isNoSpatial = (sr.level ?? "").toUpperCase() === "NO_SPATIAL_DATA";
    const requiresAck = sr.requires_user_acknowledgement === true;

    return (
      <div className={`${className} p-4 border rounded ${colors.border} ${colors.bg}`}>
        <p className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-2">
          Contrato espacial de entrada
        </p>
        <p className={`text-[12px] font-bold uppercase tracking-wider mb-3 ${colors.text}`}>
          {sr.level ?? "N/A"}
        </p>
        <div className="grid grid-cols-2 gap-2 mb-3 text-[10px] font-mono">
          <div>
            <span className="text-neutral-500">can_run_3d_inversion:</span>{" "}
            <span className={sr.can_run_3d_inversion ? "text-green-400" : "text-red-400"}>{boolLabel(sr.can_run_3d_inversion)}</span>
          </div>
          <div>
            <span className="text-neutral-500">DEM/MASL:</span>{" "}
            <span className={sr.can_use_dem ? "text-green-400" : "text-red-400"}>{boolLabel(sr.can_use_dem)}</span>
          </div>
          <div>
            <span className="text-neutral-500">Lat/lon vóxel:</span>{" "}
            <span className={sr.can_compute_voxel_latlon ? "text-green-400" : "text-red-400"}>{boolLabel(sr.can_compute_voxel_latlon)}</span>
          </div>
          <div>
            <span className="text-neutral-500">Elev. MASL vóxel:</span>{" "}
            <span className={sr.can_compute_voxel_masl ? "text-green-400" : "text-red-400"}>{boolLabel(sr.can_compute_voxel_masl)}</span>
          </div>
          {sr.max_priority_class_allowed && (
            <div className="col-span-2">
              <span className="text-neutral-500">Máx. prioridad permitida:</span>{" "}
              <span className="text-white">{sr.max_priority_class_allowed}</span>
            </div>
          )}
          {sr.max_favorability_score_allowed !== undefined && sr.max_favorability_score_allowed !== null && (
            <div className="col-span-2">
              <span className="text-neutral-500">Máx. favorabilidad:</span>{" "}
              <span className="text-white">{sr.max_favorability_score_allowed}</span>
            </div>
          )}
        </div>
        {sr.missing_fields && sr.missing_fields.length > 0 && (
          <div className="mb-2">
            <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Campos faltantes:</p>
            <ul className="list-disc list-inside text-[10px] text-red-400/80 font-mono">
              {sr.missing_fields.map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          </div>
        )}
        {sr.blocked_outputs && sr.blocked_outputs.length > 0 && (
          <div className="mb-2">
            <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Salidas bloqueadas:</p>
            <ul className="list-disc list-inside text-[10px] text-red-400/80 font-mono">
              {sr.blocked_outputs.map((output, i) => <li key={i}>{output}</li>)}
            </ul>
          </div>
        )}
        {sr.allowed_outputs && sr.allowed_outputs.length > 0 && (
          <div className="mb-2">
            <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Salidas permitidas:</p>
            <ul className="list-disc list-inside text-[10px] text-green-400/70 font-mono">
              {sr.allowed_outputs.map((output, i) => <li key={i}>{output}</li>)}
            </ul>
          </div>
        )}
        {sr.warnings && sr.warnings.length > 0 && (
          <ul className="list-disc list-inside text-[10px] text-yellow-400/80 font-mono mb-2">
            {sr.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}
        {sr.rationale && (
          <p className="text-[9px] text-neutral-400 font-mono italic mb-2">{sr.rationale}</p>
        )}
        {isNoSpatial && (
          <div className="mt-2 p-2 border border-red-600/50 bg-red-900/30 rounded">
            <p className="text-[10px] text-red-300 font-mono">
              Este CSV no contiene coordenadas por estación; no se puede ejecutar una inversión 3D defendible.
            </p>
          </div>
        )}
        {requiresAck && (
          <div className="mt-3 p-3 border border-yellow-600/30 bg-yellow-900/20 rounded">
            <p className="text-[10px] text-yellow-400 font-mono mb-2">
              Este modelo solo puede ejecutarse como conceptual/degradado. Debes aceptar explícitamente el riesgo espacial.
            </p>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={acknowledgeSpatialRisk}
                onChange={(e) => setAcknowledgeSpatialRisk(e.target.checked)}
                disabled={isNoSpatial}
                className="accent-yellow-500 mt-0.5 shrink-0"
              />
              <div>
                <p className="text-[10px] text-white font-mono">
                  Acepto ejecutar una inversión conceptual/degradada con limitaciones espaciales.
                </p>
                <p className="text-[9px] text-neutral-400 font-mono mt-1">
                  Los resultados no deben interpretarse como ubicación absoluta ni prioridad alta. TerraQuantum limitará favorabilidad y prioridad automáticamente.
                </p>
              </div>
            </label>
          </div>
        )}
        {isNoSpatial && (
          <p className="mt-2 text-[9px] text-red-400 font-mono italic">
            No es posible continuar sin coordenadas por estación.
          </p>
        )}
      </div>
    );
  }

  function getRegionalScaleColors(scaleClass?: string | null): { border: string; bg: string; text: string } {
    const sc = (scaleClass ?? "").toUpperCase();
    if (sc === "TOO_LARGE_SINGLE_INVERSION")
      return { border: "border-red-600/40", bg: "bg-red-900/20", text: "text-red-400" };
    if (sc === "REGIONAL_SCALE")
      return { border: "border-orange-600/40", bg: "bg-orange-900/20", text: "text-orange-400" };
    if (sc === "DISTRICT_SCALE")
      return { border: "border-yellow-600/40", bg: "bg-yellow-900/20", text: "text-yellow-400" };
    if (sc === "LOCAL_SURVEY")
      return { border: "border-green-600/40", bg: "bg-green-900/20", text: "text-green-400" };
    return { border: "border-neutral-600/40", bg: "bg-neutral-900/20", text: "text-neutral-400" };
  }

  function renderRegionalScalePreflightPanel(
    preflight: RegionalScalePreflight | null | undefined,
    className = "mt-6"
  ) {
    if (!preflight) return null;

    const pf = preflight;
    const colors = getRegionalScaleColors(pf.scale_class);
    const isTooLarge = (pf.scale_class ?? "").toUpperCase() === "TOO_LARGE_SINGLE_INVERSION";
    const isRegional = (pf.scale_class ?? "").toUpperCase() === "REGIONAL_SCALE";
    const requiresAck = pf.requires_user_acknowledgement === true;

    const extentXKm = typeof pf.extent_x_m === "number" ? (pf.extent_x_m / 1000).toFixed(1) : null;
    const extentZKm = typeof pf.extent_z_m === "number" ? (pf.extent_z_m / 1000).toFixed(1) : null;
    const depthKm = typeof pf.estimated_depth_m === "number" ? (pf.estimated_depth_m / 1000).toFixed(1) : null;

    return (
      <div className={`${className} p-4 border rounded ${colors.border} ${colors.bg}`}>
        <p className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-2">
          Escala del dataset
        </p>
        <p className={`text-[12px] font-bold uppercase tracking-wider mb-3 ${colors.text}`}>
          {pf.scale_class ?? "N/A"}
        </p>

        {isTooLarge && (
          <div className="mb-3 p-2 border border-red-600/50 bg-red-900/30 rounded">
            <p className="text-[10px] text-red-300 font-mono font-bold">
              Este dataset cubre una escala demasiado grande para una inversión única. Use un recorte/subset o tileado.
            </p>
          </div>
        )}
        {isRegional && (
          <div className="mb-3 p-2 border border-orange-600/50 bg-orange-900/20 rounded">
            <p className="text-[10px] text-orange-300 font-mono">
              Este dataset corresponde a escala regional. Puede requerir aceptación explícita y no debe interpretarse como modelo minero local sin validación profesional.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 mb-3 text-[10px] font-mono">
          <div>
            <span className="text-neutral-500">can_run_single_inversion:</span>{" "}
            <span className={pf.can_run_single_inversion ? "text-green-400" : "text-red-400"}>{boolLabel(pf.can_run_single_inversion)}</span>
          </div>
          <div>
            <span className="text-neutral-500">requires_ack:</span>{" "}
            <span className={requiresAck ? "text-yellow-400" : "text-green-400"}>{boolLabel(requiresAck)}</span>
          </div>
          {extentXKm && extentZKm && (
            <div className="col-span-2">
              <span className="text-neutral-500">Extensión:</span>{" "}
              <span className="text-white">{extentXKm} km × {extentZKm} km</span>
            </div>
          )}
          {typeof pf.area_km2 === "number" && (
            <div>
              <span className="text-neutral-500">Área:</span>{" "}
              <span className="text-white">{pf.area_km2.toFixed(1)} km²</span>
            </div>
          )}
          {typeof pf.station_count === "number" && (
            <div>
              <span className="text-neutral-500">Estaciones:</span>{" "}
              <span className="text-white">{pf.station_count}</span>
            </div>
          )}
          {pf.estimated_nx != null && pf.estimated_ny != null && pf.estimated_nz != null && (
            <div className="col-span-2">
              <span className="text-neutral-500">Grilla estimada:</span>{" "}
              <span className="text-white">{pf.estimated_nx}×{pf.estimated_ny}×{pf.estimated_nz}</span>
            </div>
          )}
          {depthKm && (
            <div>
              <span className="text-neutral-500">Prof. estimada:</span>{" "}
              <span className="text-white">{depthKm} km</span>
            </div>
          )}
        </div>

        {pf.warnings && pf.warnings.length > 0 && (
          <ul className="list-disc list-inside text-[10px] text-yellow-400/80 font-mono mb-2">
            {pf.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}
        {pf.blocked_reasons && pf.blocked_reasons.length > 0 && (
          <div className="mb-2">
            <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Razones de bloqueo:</p>
            <ul className="list-disc list-inside text-[10px] text-red-400/80 font-mono">
              {pf.blocked_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}
        {pf.rationale && (
          <p className="text-[9px] text-neutral-400 font-mono italic mb-2">{pf.rationale}</p>
        )}

        {requiresAck && !isTooLarge && (
          <div className="mt-3 p-3 border border-orange-600/30 bg-orange-900/20 rounded">
            <p className="text-[10px] text-orange-400 font-mono mb-2">
              Este dataset requiere aceptación explícita de las limitaciones de escala regional.
            </p>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={acknowledgeRegionalScale}
                onChange={(e) => setAcknowledgeRegionalScale(e.target.checked)}
                className="accent-orange-500 mt-0.5 shrink-0"
              />
              <div>
                <p className="text-[10px] text-white font-mono">
                  Acepto ejecutar una inversión regional/conceptual con limitaciones de escala.
                </p>
                <p className="text-[9px] text-neutral-400 font-mono mt-1">
                  TerraQuantum documentará esta limitación en el reporte. Para análisis local se recomienda usar subset o tileado.
                </p>
              </div>
            </label>
          </div>
        )}

        {isTooLarge && (
          <p className="mt-2 text-[9px] text-red-400 font-mono italic">
            No es posible ejecutar una inversión única para este dataset. Use subset/tile.
          </p>
        )}
      </div>
    );
  }

  function renderInversionSummary(inversionResult: unknown) {
    if (!inversionResult) return null;

    const inversionObject = isJsonObject(inversionResult) ? inversionResult : null;
    if (!inversionObject) return null;

    const reportObject = isJsonObject(inversionObject.report) ? inversionObject.report : null;
    const technicalSummary = isJsonObject(reportObject?.technicalSummary) ? reportObject?.technicalSummary : null;
    const fitDiagnostics = isJsonObject(reportObject?.fitDiagnostics) ? reportObject?.fitDiagnostics : null;
    const uncertaintyDiagnostics = isJsonObject(reportObject?.uncertaintyDiagnostics) ? reportObject?.uncertaintyDiagnostics : null;
    const observationQuality = isJsonObject(reportObject?.observationQuality) ? reportObject?.observationQuality : null;
    const bestTarget = isJsonObject(inversionObject.best_target) ? inversionObject.best_target : null;

    const recommendation = readStringField(reportObject?.drill_recommendation) ?? readStringField(reportObject?.recommendation);
    const riskLevel = readStringField(reportObject?.risk_level);
    const overallLevel = readStringField(technicalSummary?.overall_level);
    const fitLevel = readStringField(fitDiagnostics?.fit_level);
    const uncertaintyLevel = readStringField(uncertaintyDiagnostics?.uncertainty_level);
    const confidenceLevel = readStringField(reportObject?.confidence_level) ?? readStringField(bestTarget?.confidence_level);
    const semanticNote = readStringField(reportObject?.semantic_note);
    const observationCount = typeof observationQuality?.observation_count === "number" ? observationQuality.observation_count : null;
    const projectId = readStringField(reportObject?.projectId);
    const runId = readStringField(reportObject?.runId);
    
    const tsSummary = readStringField(technicalSummary?.summary);
    const tsWarnings = Array.isArray(technicalSummary?.warnings) ? technicalSummary?.warnings : [];

    return (
      <div className="flex flex-col gap-4">
        {tsSummary && (
          <div className="p-3 border-l-2 border-[#C2D8C4] bg-[#C2D8C4]/10 text-[11px] text-white font-mono">
            {tsSummary}
          </div>
        )}
        
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[
            ["Project / Run", projectId && runId ? `${projectId} / ${runId}` : null],
            ["Overall Level", overallLevel],
            ["Confiabilidad técnica", riskLevel],
            ["Fit Level", fitLevel],
            ["Uncertainty Level", uncertaintyLevel],
            ["Nivel de confianza", confidenceLevel],
            ["Observations", observationCount !== null ? String(observationCount) : null],
          ].map(([label, val]) => val ? (
            <div key={label as string} className="min-w-0 border border-neutral-800 bg-neutral-900/50 rounded p-2">
              <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">{label}</p>
              <p className="text-[10px] text-white font-mono truncate">{val}</p>
            </div>
          ) : null)}
        </div>

        {bestTarget && (() => {
          const btDensity = readNumberField(bestTarget.modeled_density_index) ?? readNumberField(bestTarget.density);
          const btProb = readNumberField(bestTarget.target_score) ?? readNumberField(bestTarget.probability);
          const btAnomalyIntensity = readNumberField(bestTarget.anomaly_intensity) ?? readNumberField(bestTarget.grade);
          const btDensityAnomalyScore = readNumberField(bestTarget.density_anomaly_score);
          
          return (
            <div className="border border-purple-500/30 bg-purple-500/10 rounded p-3 mt-4">
              <p className="text-[9px] uppercase tracking-widest text-purple-400 mb-2 font-bold">Target Preliminar Destacado</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px] font-mono">
                <div><span className="text-neutral-500">X:</span> {typeof bestTarget.x_m === 'number' ? bestTarget.x_m.toFixed(1) : '-'}</div>
                <div><span className="text-neutral-500">Y:</span> {typeof bestTarget.y_m === 'number' ? bestTarget.y_m.toFixed(1) : '-'}</div>
                <div><span className="text-neutral-500">Z:</span> {typeof bestTarget.z_m === 'number' ? bestTarget.z_m.toFixed(1) : '-'}</div>
                <div><span className="text-neutral-500">Densidad modelada:</span> {typeof btDensity === 'number' ? btDensity.toFixed(2) : '-'}</div>
                <div><span className="text-neutral-500">Target score:</span> {typeof btProb === 'number' ? btProb.toFixed(2) : '-'}</div>
              </div>
              {(btAnomalyIntensity !== null || btDensityAnomalyScore !== null) && (
                <div className="grid grid-cols-2 gap-2 text-[10px] font-mono mt-2 pt-2 border-t border-purple-500/20">
                  {btAnomalyIntensity !== null && <div><span className="text-neutral-500">Intensidad de anomalía:</span> {btAnomalyIntensity.toFixed(2)}</div>}
                  {btDensityAnomalyScore !== null && <div><span className="text-neutral-500">Density Anomaly Score:</span> {btDensityAnomalyScore.toFixed(2)}</div>}
                </div>
              )}
            </div>
          );
        })()}

        {recommendation && (
          <div className="p-3 border border-purple-500/30 rounded bg-black/40 mt-4">
            <p className="text-[9px] uppercase tracking-widest text-purple-400 mb-1 font-bold">Clase de prioridad relativa</p>
            <p className="text-[10px] text-white font-mono">{mapPriorityClassLabel(recommendation)}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[8px] uppercase tracking-[0.18em] text-purple-700 font-bold">Señal Preliminar:</span>
              <span className="text-[9px] font-mono text-purple-400">{recommendation}</span>
            </div>
            <p className="text-[7px] text-purple-700 italic mt-1">Esta clase no representa una recomendación de perforación.</p>
          </div>
        )}

        {tsWarnings.length > 0 && (
          <div className="p-3 border border-yellow-600/30 bg-yellow-600/10 rounded">
            <p className="text-[9px] uppercase tracking-widest text-yellow-500 mb-1 font-bold">Advertencias Técnicas</p>
            <ul className="list-disc list-inside text-[10px] text-yellow-500/90 font-mono">
              {tsWarnings.map((w: unknown, i: number) => (
                <li key={i}>{String(w)}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-4 p-2 bg-neutral-900 border border-neutral-800 rounded text-center">
          <p className="text-[9px] text-neutral-400 font-mono italic">
            Este resultado es preliminar y debe validarse con más observaciones, QA/QC y perforación. Requiere validación.
          </p>
          {semanticNote && (
            <p className="text-[9px] text-yellow-500/80 font-mono italic mt-1">
              {semanticNote}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden border border-neutral-800 bg-black/50 p-3 rounded-xl shrink-0">
      <div className="flex flex-col gap-3 mb-4 min-w-0">
        <div className="w-full min-w-0 flex flex-col gap-3">
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-2">CSV Gravimetría</label>
            <input
              type="file"
              accept=".csv"
              onChange={handleFileGravimetryChange}
              className="w-full max-w-full min-w-0 overflow-hidden text-xs text-neutral-400 file:mr-3 file:py-2 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-neutral-800 file:text-[#C2D8C4] hover:file:bg-neutral-700"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-2">
              CSV Magnetometría{" "}
              <span className="normal-case text-[#C2D8C4] font-normal">(susceptibilidad)</span>
            </label>
            <input
              type="file"
              accept=".csv"
              onChange={handleFileMagnetometryChange}
              title="CSV con columna TMI (magnetic_nt / tmi) en nanoTesla + coordenadas."
              className="w-full max-w-full min-w-0 overflow-hidden text-xs text-neutral-400 file:mr-3 file:py-2 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-neutral-800 file:text-[#C2D8C4] hover:file:bg-neutral-700"
            />
            {dataType === "magnetic" && fileMagnetometry && (
              <p className="mt-1 text-[10px] text-[#C2D8C4]">
                Modo magnetometría: {fileMagnetometry.name} → inversión de susceptibilidad (SI).
              </p>
            )}
          </div>
        </div>
        
        {/* ── Correcciones geofísicas (H-B4) ──────────────────────────────── */}
        {file && !showCorrectionWizard && (
          <div>
            {correctionReport ? (
              <div className="flex items-start justify-between gap-2 p-2.5 border border-amber-600/30 bg-amber-900/20 rounded">
                <div className="min-w-0">
                  <p className="text-[9px] uppercase tracking-widest text-amber-400 font-bold mb-1">
                    Correcciones aplicadas
                  </p>
                  <p className="text-[10px] text-white font-mono">
                    {correctionReport.corrections_applied.join(" · ")}
                  </p>
                  <p className="text-[9px] text-neutral-400 mt-0.5">
                    {correctionReport.n_stations} estaciones — ρ={correctionReport.reduction_density_gcc} g/cm³
                    {correctionReport.fac_min_mgal !== null &&
                      correctionReport.fac_max_mgal !== null && (
                        <span>
                          {" "}— FAC [{correctionReport.fac_min_mgal.toFixed(1)}–{correctionReport.fac_max_mgal.toFixed(1)} mGal]
                        </span>
                      )}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setCorrectedFile(null);
                    setCorrectionReport(null);
                    setResult(null);
                  }}
                  className="text-[10px] text-neutral-500 hover:text-red-400 shrink-0 px-1.5 py-0.5 border border-neutral-700/40 rounded"
                  title="Quitar correcciones y volver al CSV original"
                >
                  ✕ Quitar
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowCorrectionWizard(true)}
                className="w-full text-left px-3 py-2 border border-neutral-700/40 hover:border-amber-600/40 bg-neutral-900/40 hover:bg-amber-900/10 rounded text-[11px] text-neutral-400 hover:text-amber-400 transition-colors"
              >
                <span className="font-semibold">+ Aplicar correcciones geofísicas</span>
                <span className="text-[10px] ml-2 text-neutral-600">
                  FAC · Bouguer · Terreno (GRS80)
                </span>
              </button>
            )}
          </div>
        )}

        {file && showCorrectionWizard && (
          <GravityCorrectionWizard
            file={file}
            onComplete={(corrFile, report) => {
              setCorrectedFile(corrFile);
              setCorrectionReport(report);
              setShowCorrectionWizard(false);
              setResult(null);
              setErrorMsg(null);
            }}
            onCancel={() => setShowCorrectionWizard(false)}
          />
        )}

        <div className="flex flex-col gap-2 justify-center min-w-0">
          <label className="flex items-center gap-2 text-[10px] uppercase text-neutral-400 tracking-widest cursor-pointer min-w-0">
            <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} className="accent-[#C2D8C4]" />
            <span className="min-w-0 break-words">Modo Estricto</span>
          </label>
          <label className="flex items-center gap-2 text-[10px] uppercase text-neutral-400 tracking-widest cursor-pointer min-w-0">
            <input type="checkbox" checked={allowGRaw} onChange={(e) => setAllowGRaw(e.target.checked)} className="accent-red-500" />
            <span className="min-w-0 break-words">Permitir g_raw</span>
            {allowGRaw && <span className="text-red-400 ml-1 lowercase break-words">(menor exactitud)</span>}
          </label>
        </div>

        {/* ── Parámetros físicos (Tier 1 B6) ─────────────────────────────── */}
        <div className="w-full border border-neutral-800 rounded p-2.5 flex flex-col gap-2">
          <p className="text-[9px] uppercase tracking-widest text-neutral-500 font-bold">
            Parámetros físicos de inversión
          </p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                Densidad mín (t/m³)
              </label>
              <input
                type="number"
                step="0.05"
                value={densityMin}
                onChange={(e) => setDensityMin(e.target.value)}
                title="Bound inferior absoluto. < 2.6 permite contrastes negativos (magma, sal, cavidades)."
                className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                Densidad máx (t/m³)
              </label>
              <input
                type="number"
                step="0.05"
                value={densityMax}
                onChange={(e) => setDensityMax(e.target.value)}
                title="Bound superior absoluto. 5.5 cubre magnetita/cromita/pirita masiva."
                className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              />
            </div>
          </div>
          <div>
            <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
              Gravímetro (piso de ruido σ)
            </label>
            <select
              value={gravimeterType}
              onChange={(e) => setGravimeterType(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
            >
              <option value="unknown">Desconocido (0.020 mGal, conservador)</option>
              <option value="scintrex_cg6">Scintrex CG-6 (0.005 mGal)</option>
              <option value="zls_burris">ZLS Burris (0.002 mGal)</option>
              <option value="lacoste_romberg">LaCoste &amp; Romberg (0.010 mGal)</option>
            </select>
          </div>
          <div>
            <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
              Regularización λ
            </label>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-[10px] text-neutral-400 cursor-pointer">
                <input
                  type="radio"
                  checked={lambdaMode === "auto"}
                  onChange={() => setLambdaMode("auto")}
                  className="accent-[#C2D8C4]"
                />
                <span title="El backend selecciona λ: discrepancia de Morozov (chi²→1) si declaraste gravímetro; operating point validado si no.">
                  Auto
                </span>
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-neutral-400 cursor-pointer">
                <input
                  type="radio"
                  checked={lambdaMode === "custom"}
                  onChange={() => setLambdaMode("custom")}
                  className="accent-[#C2D8C4]"
                />
                <span>Custom</span>
              </label>
              {lambdaMode === "custom" && (
                <input
                  type="number"
                  step="0.01"
                  min="0.0001"
                  value={lambdaCustom}
                  onChange={(e) => setLambdaCustom(e.target.value)}
                  className="w-24 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
                />
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-col justify-center w-full max-w-full">
          <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">Preview Limit</label>
          <input
            type="number"
            min={1}
            max={100}
            value={previewLimit}
            onChange={(e) => setPreviewLimit(Number(e.target.value))}
            className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
          />
        </div>

        <div className="flex items-end w-full min-w-0">
          <button
            onClick={handleValidate}
            disabled={loading || !(dataType === "magnetic" ? fileMagnetometry : file)}
            className="h-9 w-full justify-center px-4 bg-[#C2D8C4] text-black text-[10px] uppercase font-bold tracking-widest rounded hover:bg-[#a5bca7] disabled:opacity-50 transition-colors flex items-center"
          >
            {loading ? "Validando..." : dataType === "magnetic" ? "Validar CSV magnético" : "Validar CSV"}
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 text-red-400 text-sm font-mono rounded">
          <span className="font-bold mr-2">ERROR:</span> {errorMsg}
        </div>
      )}

      {result && result.status === "error" && result.spatial_readiness && renderSpatialReadinessPanel(result.spatial_readiness, "mb-4")}

      {result && result.status === "error" && (
        <div className="p-3 border border-red-900/50 bg-red-950/20 rounded overflow-hidden">
          <div className="flex items-center gap-3 mb-2">
            <span className="px-2 py-1 bg-red-900/30 text-red-400 border border-red-900/50 rounded text-[10px] font-bold uppercase tracking-widest">
              STATUS: ERROR
            </span>
            <span className="text-xs text-red-400 font-mono">
              {result.spatial_readiness ? "Detalle técnico de importación." : "No se puede importar el archivo."}
            </span>
          </div>
          
          {result.errors && result.errors.length > 0 && (
            <ul className="list-disc list-inside text-xs text-red-300 font-mono mt-2 space-y-1">
              {result.errors.map((err: string, i: number) => <li key={i}>{err}</li>)}
            </ul>
          )}
          
          {result.warnings && result.warnings.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] uppercase text-yellow-500 tracking-widest mb-1">Warnings:</p>
              <ul className="list-disc list-inside text-xs text-yellow-500/80 font-mono">
                {result.warnings.map((warn: string, i: number) => <li key={i}>{warn}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {result && result.status === "ok" && (
        <div className="border border-[#C2D8C4]/30 bg-[#C2D8C4]/5 rounded p-3 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="px-2 py-1 bg-[#C2D8C4]/20 text-[#C2D8C4] border border-[#C2D8C4]/50 rounded text-[10px] font-bold uppercase tracking-widest">
              STATUS: OK
            </span>
            {result.importMetadata?.is_demo && (
              <span className="px-2 py-1 bg-purple-500/20 text-purple-400 border border-purple-500/50 rounded text-[10px] font-bold uppercase tracking-widest">
                DEMO / Datos Sintéticos
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            {[
              ["Archivo", result.importMetadata?.source_file],
              ["Gravity Type", result.importMetadata?.gravity_type || "No definido"],
              ["Filas (Tot/Val/Rej)", `${result.importMetadata?.row_count} / ${result.importMetadata?.valid_rows} / ${result.importMetadata?.rejected_rows}`],
              ["Conversión", `${result.importMetadata?.unit_original || "N/A"} → ${result.importMetadata?.unit_internal}`],
            ].map(([label, val]) => (
              <div key={label} className="min-w-0">
                <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">{label}</p>
                <p className="text-[10px] text-white font-mono truncate" title={val as string}>{val}</p>
              </div>
            ))}
          </div>

          {result.warnings && result.warnings.length > 0 && (
            <div className="mb-4 p-2 border border-yellow-600/30 bg-yellow-600/10 rounded">
              <p className="text-[10px] text-yellow-500 font-mono">Hay advertencias técnicas. Revísalas en Datos o en detalle técnico.</p>
            </div>
          )}

          <details className="mb-6">
            <summary className="cursor-pointer text-[10px] uppercase text-[#C2D8C4] tracking-widest mb-2 hover:text-white outline-none">
              Ver detalle técnico del CSV
            </summary>
            <div className="pl-2 border-l border-neutral-800 mt-2">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
                {[
                  ["Versión Schema", result.importMetadata?.schema_version],
                  ["Columna Gravedad", result.importMetadata?.gravity_column_used || "N/A"],
                ].map(([label, val]) => (
                  <div key={label} className="min-w-0">
                    <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">{label}</p>
                    <p className="text-[10px] text-white font-mono truncate" title={val as string}>{val}</p>
                  </div>
                ))}
              </div>

              {result.warnings && result.warnings.length > 0 && (
                <div className="mb-4 p-3 border border-yellow-600/30 bg-yellow-600/10 rounded">
                  <p className="text-[10px] uppercase text-yellow-500 tracking-widest mb-1 font-bold">Warnings completos:</p>
                  <ul className="list-disc list-inside text-[10px] text-yellow-500/90 font-mono">
                    {result.warnings.map((warn: string, i: number) => <li key={i}>{warn}</li>)}
                  </ul>
                </div>
              )}

              {result.observationsPreview && result.observationsPreview.length > 0 && (
                <div className="min-w-0 overflow-hidden mt-4">
                  <p className="text-[10px] uppercase text-neutral-500 tracking-widest break-words mb-2">
                    Preview de observaciones ({result.previewCount}/{result.totalObservations})
                  </p>
                  <div className="overflow-x-auto border border-neutral-800 rounded">
                    <table className="w-full text-left text-[10px] font-mono min-w-max">
                      <thead className="bg-neutral-900/50 text-neutral-400 uppercase text-[9px] tracking-widest border-b border-neutral-800">
                        <tr>
                          <th className="p-2 font-normal">X (m)</th>
                          <th className="p-2 font-normal">Y (m) [Prof.]</th>
                          <th className="p-2 font-normal">Z (m)</th>
                          <th className="p-2 font-normal">Gravedad ({result.importMetadata?.unit_internal})</th>
                        </tr>
                      </thead>
                      <tbody className="text-neutral-300">
                        {result.observationsPreview.map((obs, idx) => (
                          <tr key={idx} className="border-b border-neutral-900/50 hover:bg-neutral-900/30">
                            <td className="p-2">{obs.x_m}</td>
                            <td className="p-2">{obs.y_m}</td>
                            <td className="p-2">{obs.z_m}</td>
                            <td className="p-2 text-[#C2D8C4]">{obs.g.toExponential(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </details>

          <div className="mt-6 p-4 border border-neutral-800 bg-black/40 rounded">
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-3">
              Geolocalización (coordenadas de referencia)
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div className="min-w-0">
                <label className="block text-[9px] uppercase text-neutral-600 tracking-widest mb-1">
                  Latitud Norte
                </label>
                <input
                  type="number"
                  step="any"
                  value={latNorth}
                  onChange={(e) => {
                    setLatNorth(e.target.value);
                    setGeoError(null);
                  }}
                  placeholder="-22.20"
                  className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-2 text-sm text-white outline-none focus:border-[#C2D8C4]"
                />
              </div>
              <div className="min-w-0">
                <label className="block text-[9px] uppercase text-neutral-600 tracking-widest mb-1">
                  Latitud Sur
                </label>
                <input
                  type="number"
                  step="any"
                  value={latSouth}
                  onChange={(e) => {
                    setLatSouth(e.target.value);
                    setGeoError(null);
                  }}
                  placeholder="-22.35"
                  className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-2 text-sm text-white outline-none focus:border-[#C2D8C4]"
                />
              </div>
              <div className="min-w-0">
                <label className="block text-[9px] uppercase text-neutral-600 tracking-widest mb-1">
                  Longitud Este
                </label>
                <input
                  type="number"
                  step="any"
                  value={lonEast}
                  onChange={(e) => {
                    setLonEast(e.target.value);
                    setGeoError(null);
                  }}
                  placeholder="-68.80"
                  className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-2 text-sm text-white outline-none focus:border-[#C2D8C4]"
                />
              </div>
              <div className="min-w-0">
                <label className="block text-[9px] uppercase text-neutral-600 tracking-widest mb-1">
                  Longitud Oeste
                </label>
                <input
                  type="number"
                  step="any"
                  value={lonWest}
                  onChange={(e) => {
                    setLonWest(e.target.value);
                    setGeoError(null);
                  }}
                  placeholder="-69.00"
                  className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-2 text-sm text-white outline-none focus:border-[#C2D8C4]"
                />
              </div>
            </div>
            <p className="mt-2 text-[9px] text-neutral-500 font-mono">
              Grados decimales WGS84. Opcional; si queda vacío se usará la referencia interna.
            </p>
            {geoError && (
              <p className="mt-2 text-red-400 text-[10px] font-mono">
                {geoError}
              </p>
            )}
            {/* Georef preview: prioriza georef_preview del backend, fallback a csv_analysis */}
            {result?.georef_preview ? (() => {
              const conf = result.georef_preview!.confidence;
              const badgeClass = getGeorefBadgeClass(conf);
              const label = getGeorefBadgeLabel(conf);
              const explanation = getGeorefExplanation(conf);
              const warnings = result.georef_preview!.warnings ?? [];
              const visibleWarnings = warnings.slice(0, 3);
              const hiddenCount = warnings.length - 3;
              return (
                <div className={`mt-3 px-3 py-3 border rounded text-[9px] font-mono flex flex-col gap-1.5 ${badgeClass}`}>
                  <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">Georreferenciación</span>
                  <span className="font-bold tracking-widest uppercase text-[10px]">{label}</span>
                  <span className="text-neutral-300 text-[9px] mt-0.5">{explanation}</span>
                  {visibleWarnings.map((w: string, i: number) => (
                    <span key={i} className="text-neutral-500 text-[8px]">⚠ {w}</span>
                  ))}
                  {hiddenCount > 0 && (
                    <span className="text-neutral-600 text-[8px]">+{hiddenCount} advertencias más</span>
                  )}
                </div>
              );
            })() : result?.csv_analysis?.coordinate_system ? (() => {
              const ct: CoordinateTransformData = {
                input_coordinate_system: result.csv_analysis?.coordinate_system?.detected,
                input_confidence: result.csv_analysis?.coordinate_system?.confidence ?? undefined,
              };
              const badge = getGeorefBadge(ct);
              return (
                <div className={`mt-3 px-2 py-2 border rounded text-[9px] font-mono flex flex-col gap-1 ${badge.classes}`}>
                  <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">Georreferenciación</span>
                  <span className="font-bold tracking-widest uppercase">{badge.label}</span>
                  <span className="text-neutral-400">{badge.desc}</span>
                  {(cs => cs === "local_meters" || cs === "unknown")(
                    (result.csv_analysis?.coordinate_system?.detected ?? "unknown").toLowerCase()
                  ) && (
                    <span className="text-neutral-500 mt-1">
                      El terreno satelital se mostrará como contexto visual, no como ubicación exacta del modelo.
                    </span>
                  )}
                </div>
              );
            })() : null}

            {/* UTM zone input — solo visible si se detectó sistema UTM (R2-FE) */}
            {isUtmDetected && (
              <div className="mt-3 p-3 border border-blue-600/30 bg-blue-900/10 rounded">
                <label className="block text-[9px] uppercase text-blue-400 tracking-widest mb-1 font-bold">
                  Zona UTM (opcional)
                </label>
                <input
                  type="text"
                  value={utmZone}
                  onChange={(e) => setUtmZone(e.target.value)}
                  placeholder="ej: 19S"
                  maxLength={4}
                  className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-2 text-sm text-white outline-none focus:border-blue-500 font-mono"
                />
                {utmZoneError ? (
                  <p className="mt-1 text-red-400 text-[9px] font-mono">{utmZoneError}</p>
                ) : derivedEpsg ? (
                  <p className="mt-1 text-blue-400 text-[9px] font-mono">EPSG:{derivedEpsg}</p>
                ) : (
                  <p className="mt-1 text-neutral-500 text-[9px] font-mono">
                    Se detectaron coordenadas UTM. Declara la zona para mejorar la georreferenciación.
                  </p>
                )}
              </div>
            )}
          </div>

          {renderSpatialReadinessPanel(result.spatial_readiness)}

          {renderRegionalScalePreflightPanel(result.regional_scale_preflight)}

          {/* ── SECCIÓN DE INVERSIÓN ── */}
          <div className="mt-8 border-t border-neutral-800 pt-6">
            <h4 className="text-[12px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold mb-6">
              Inversión 3D
            </h4>

            <div className="flex flex-col gap-4 mb-6">
              <button
                onClick={handleInvert}
                disabled={
                  invertLoading ||
                  loading3D ||
                  !(dataType === "magnetic" ? fileMagnetometry : file) ||
                  result.spatial_readiness?.level === "NO_SPATIAL_DATA" ||
                  (result.spatial_readiness?.requires_user_acknowledgement === true && !acknowledgeSpatialRisk) ||
                  result.regional_scale_preflight?.can_run_single_inversion === false ||
                  (result.regional_scale_preflight?.requires_user_acknowledgement === true && !acknowledgeRegionalScale)
                }
                className="h-9 w-full justify-center px-4 bg-purple-500/80 text-white text-[10px] uppercase font-bold tracking-widest rounded hover:bg-purple-500 disabled:opacity-50 transition-colors flex items-center"
              >
                {invertLoading
                  ? "Ejecutando inversion..."
                  : loading3D
                  ? "Cargando modelo 3D..."
                  : "Invertir y cargar modelo 3D"}
              </button>
              {result.spatial_readiness?.level === "NO_SPATIAL_DATA" && (
                <p className="text-[10px] text-red-400 font-mono text-center">
                  No es posible continuar sin coordenadas por estación.
                </p>
              )}
              {result.regional_scale_preflight?.can_run_single_inversion === false && (
                <p className="text-[10px] text-red-400 font-mono text-center">
                  No es posible ejecutar una inversión única para este dataset. Use subset/tile.
                </p>
              )}
            </div>

            {invertLoading && (
              <div className="mb-4">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-[9px] font-mono text-neutral-400 uppercase tracking-widest">
                    {invertStage
                      ? INVERT_STAGE_LABELS[invertStage] ?? invertStage.replace(/_/g, " ")
                      : "Preparando inversión..."}
                  </span>
                  <span className="text-[9px] font-mono text-neutral-500">
                    {invertProgress > 0 ? `${Math.round(invertProgress * 100)}%` : ""}
                  </span>
                </div>
                <div className="w-full h-1 bg-neutral-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 rounded-full transition-all duration-500"
                    style={{
                      width: invertProgress > 0 ? `${Math.round(invertProgress * 100)}%` : "30%",
                      animation: invertProgress === 0 ? "pulse 1.5s infinite" : undefined,
                    }}
                  />
                </div>
              </div>
            )}

            {load3DMessage && (
              <div className="mb-4 p-3 border border-[#C2D8C4]/40 bg-[#C2D8C4]/10 text-[#C2D8C4] text-[10px] font-mono rounded break-words">
                {load3DMessage}
              </div>
            )}

            {load3DError && (
              <div className="mb-4 p-3 border border-red-900/50 bg-red-950/20 text-red-400 text-[10px] font-mono rounded break-words">
                {load3DError}
              </div>
            )}

            {invertErrorMsg && (
              <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 text-red-400 text-sm font-mono rounded">
                <span className="font-bold mr-2">ERROR DE INVERSIÓN:</span> {invertErrorMsg}
              </div>
            )}

            {spatialGateError && (
              <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 rounded">
                <p className="text-[10px] font-bold uppercase tracking-widest text-red-400 mb-2">
                  Contrato espacial bloqueó la inversión
                </p>
                {spatialGateError.message && (
                  <p className="text-[10px] text-red-300 font-mono mb-2">{spatialGateError.message}</p>
                )}
                {spatialGateError.required_action && (
                  <p className="text-[10px] text-yellow-400 font-mono mb-2">{spatialGateError.required_action}</p>
                )}
                {spatialGateError.missing_fields && spatialGateError.missing_fields.length > 0 && (
                  <div className="mb-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Campos faltantes:</p>
                    <ul className="list-disc list-inside text-[10px] text-red-400 font-mono">
                      {spatialGateError.missing_fields.map((f: string, i: number) => <li key={i}>{f}</li>)}
                    </ul>
                  </div>
                )}
                {spatialGateError.required_acknowledgement && (
                  <p className="text-[9px] text-yellow-500/80 font-mono italic mt-1">{spatialGateError.required_acknowledgement}</p>
                )}
                {spatialGateError.blocked_outputs && spatialGateError.blocked_outputs.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Salidas bloqueadas:</p>
                    <ul className="list-disc list-inside text-[10px] text-red-400/70 font-mono">
                      {spatialGateError.blocked_outputs.map((o: string, i: number) => <li key={i}>{o}</li>)}
                    </ul>
                  </div>
                )}
                {spatialGateError.allowed_outputs && spatialGateError.allowed_outputs.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Salidas permitidas:</p>
                    <ul className="list-disc list-inside text-[10px] text-green-400/70 font-mono">
                      {spatialGateError.allowed_outputs.map((o: string, i: number) => <li key={i}>{o}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {regionalGateError && (
              <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 rounded">
                <p className="text-[10px] font-bold uppercase tracking-widest text-red-400 mb-2">
                  Preflight de escala bloqueó la inversión
                </p>
                {regionalGateError.scale_class && (
                  <p className="text-[9px] uppercase tracking-widest text-orange-400 mb-1 font-mono">
                    Clase: {regionalGateError.scale_class}
                  </p>
                )}
                {regionalGateError.message && (
                  <p className="text-[10px] text-red-300 font-mono mb-2">{regionalGateError.message}</p>
                )}
                {regionalGateError.required_action && (
                  <p className="text-[10px] text-yellow-400 font-mono mb-2">{regionalGateError.required_action}</p>
                )}
                {regionalGateError.recommended_action && regionalGateError.recommended_action !== regionalGateError.required_action && (
                  <p className="text-[9px] text-neutral-400 font-mono mb-2">{regionalGateError.recommended_action}</p>
                )}
                {regionalGateError.blocked_reasons && regionalGateError.blocked_reasons.length > 0 && (
                  <div className="mb-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Razones de bloqueo:</p>
                    <ul className="list-disc list-inside text-[10px] text-red-400 font-mono">
                      {regionalGateError.blocked_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}
                    </ul>
                  </div>
                )}
                {regionalGateError.warnings && regionalGateError.warnings.length > 0 && (
                  <div className="mb-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Advertencias:</p>
                    <ul className="list-disc list-inside text-[10px] text-yellow-400/80 font-mono">
                      {regionalGateError.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}
                {regionalGateError.allowed_outputs && regionalGateError.allowed_outputs.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[9px] uppercase text-neutral-500 tracking-widest mb-1">Salidas permitidas:</p>
                    <ul className="list-disc list-inside text-[10px] text-green-400/70 font-mono">
                      {regionalGateError.allowed_outputs.map((o: string, i: number) => <li key={i}>{o}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {invertResult && invertResult.status === "error" && (
              <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 text-red-400 text-sm font-mono rounded">
                <div className="flex items-center gap-3 mb-2">
                  <span className="px-2 py-1 bg-red-900/30 text-red-400 border border-red-900/50 rounded text-[10px] font-bold uppercase tracking-widest">
                    ERROR
                  </span>
                  <span className="text-xs text-red-400 font-mono">
                    {invertResult.stage === "import" ? "Falló al re-importar el CSV." : "Falló la inversión."}
                  </span>
                </div>
                {invertResult.errors && invertResult.errors.length > 0 && (
                  <ul className="list-disc list-inside text-xs text-red-300 font-mono mt-2 space-y-1">
                    {invertResult.errors.map((err: string, i: number) => <li key={i}>{err}</li>)}
                  </ul>
                )}
                {invertResult.warnings && invertResult.warnings.length > 0 && (
                  <div className="mt-4">
                    <p className="text-[10px] uppercase text-yellow-500 tracking-widest mb-1">Warnings:</p>
                    <ul className="list-disc list-inside text-xs text-yellow-500/80 font-mono">
                      {invertResult.warnings.map((warn: string, i: number) => <li key={i}>{warn}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {invertResult && invertResult.status === "done" && (
              <div className="border border-purple-500/30 bg-purple-500/10 rounded p-4">
                <div className="flex items-center gap-3 mb-4">
                  <span className="px-2 py-1 bg-purple-500/20 text-purple-300 border border-purple-500/50 rounded text-[10px] font-bold uppercase tracking-widest">
                    INVERSIÓN COMPLETADA
                  </span>
                  <span className="text-[9px] text-neutral-400 font-mono">
                    {invertResult.stage === "inversion" ? "Modelo preliminar / anomalía modelada generada." : "Completado."}
                  </span>
                </div>

                {invertResult.warnings && invertResult.warnings.length > 0 && (
                  <div className="mb-4 p-2 border border-yellow-600/30 bg-yellow-600/10 rounded">
                    <p className="text-[10px] text-yellow-500 font-mono">Hay advertencias técnicas. Revísalas en Datos o en detalle técnico.</p>
                  </div>
                )}
                {invertResult.georef ? (() => {
                  const conf = invertResult.georef!.confidence;
                  const badgeClass = getGeorefBadgeClass(conf);
                  const label = getGeorefBadgeLabel(conf);
                  const explanation = getGeorefExplanation(conf);
                  const warnings = invertResult.georef!.warnings ?? [];
                  const visibleWarnings = warnings.slice(0, 3);
                  const hiddenCount = warnings.length - 3;
                  return (
                    <div className={`mb-4 px-3 py-3 border rounded text-[9px] font-mono flex flex-col gap-1.5 ${badgeClass}`}>
                      <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">Georreferenciación</span>
                      <span className="font-bold tracking-widest uppercase text-[10px]">{label}</span>
                      <span className="text-neutral-300 text-[9px] mt-0.5">{explanation}</span>
                      {visibleWarnings.map((w: string, i: number) => (
                        <span key={i} className="text-neutral-500 text-[8px]">⚠ {w}</span>
                      ))}
                      {hiddenCount > 0 && (
                        <span className="text-neutral-600 text-[8px]">+{hiddenCount} advertencias más</span>
                      )}
                    </div>
                  );
                })() : (() => {
                  const badge = getGeorefBadge(invertResult.coordinate_transform);
                  return (
                    <div className={`mb-4 px-2 py-2 border rounded text-[9px] font-mono flex flex-col gap-1 ${badge.classes}`}>
                      <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">Georreferenciación</span>
                      <span className="font-bold tracking-widest uppercase">{badge.label}</span>
                      <span className="text-neutral-400">{badge.desc}</span>
                      {(badge.label.includes("BAJA") || badge.label.includes("Sin")) && (
                        <span className="text-neutral-500 mt-1">
                          El terreno satelital es contexto visual. La posición del modelo en el mapa no es precisa.
                        </span>
                      )}
                    </div>
                  );
                })()}

                {invertResult.spatial_readiness && (() => {
                  const sr = invertResult.spatial_readiness as SpatialReadiness;
                  const colors = getSpatialReadinessColors(sr.level);
                  return (
                    <div className={`mb-4 p-3 border rounded ${colors.border} ${colors.bg}`}>
                      <p className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold mb-1">Contrato espacial — resultado</p>
                      <p className={`text-[10px] font-bold uppercase ${colors.text}`}>{sr.level ?? "N/A"}</p>
                      {sr.rationale && <p className="text-[9px] text-neutral-400 font-mono italic mt-1">{sr.rationale}</p>}
                      {sr.warnings && sr.warnings.length > 0 && (
                        <ul className="list-disc list-inside text-[9px] text-yellow-400/70 font-mono mt-1">
                          {sr.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                        </ul>
                      )}
                    </div>
                  );
                })()}

                {invertResult.regional_scale_preflight && (() => {
                  const rsp = invertResult.regional_scale_preflight as RegionalScalePreflight;
                  const colors = getRegionalScaleColors(rsp.scale_class);
                  return (
                    <div className={`mb-4 p-3 border rounded ${colors.border} ${colors.bg}`}>
                      <p className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold mb-1">Escala del dataset — resultado</p>
                      <p className={`text-[10px] font-bold uppercase ${colors.text}`}>{rsp.scale_class ?? "N/A"}</p>
                      {invertResult.acknowledge_regional_scale && (
                        <p className="text-[9px] text-orange-400 font-mono mt-1">Inversión regional aceptada por usuario.</p>
                      )}
                      {rsp.rationale && <p className="text-[9px] text-neutral-400 font-mono italic mt-1">{rsp.rationale}</p>}
                      {rsp.warnings && rsp.warnings.length > 0 && (
                        <ul className="list-disc list-inside text-[9px] text-yellow-400/70 font-mono mt-1">
                          {rsp.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                        </ul>
                      )}
                    </div>
                  );
                })()}

                {invertResult.inversionResult ? (
                  <div className="text-[10px] text-white font-mono bg-black/50 p-4 rounded border border-neutral-800">
                    
                    {(() => {
                      const { projectId, runId } = parseCsvInversionProjectRun(invertResult.inversionResult || null);
                      const invObj = isJsonObject(invertResult.inversionResult) ? invertResult.inversionResult : null;
                      const rep = isJsonObject(invObj?.report) ? invObj?.report : null;
                      const bestTarget = isJsonObject(invObj?.best_target) ? invObj?.best_target : null;

                      const recommendation = readStringField(rep?.drill_recommendation) ?? readStringField(rep?.recommendation);
                      const riskLevel = readStringField(rep?.risk_level);
                      const confidenceLevel = readStringField(rep?.confidence_level) ?? readStringField(bestTarget?.confidence_level);

                      return (
                        <div className="flex flex-col gap-4">
                          {projectId && runId && (
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">Project ID</p>
                                <p className="text-[10px] text-[#C2D8C4] font-mono">{projectId}</p>
                              </div>
                              <div>
                                <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">Run ID</p>
                                <p className="text-[10px] text-[#C2D8C4] font-mono">{runId}</p>
                              </div>
                            </div>
                          )}

                          {(recommendation || riskLevel || confidenceLevel) && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                              {recommendation && (
                                <div className="col-span-1 sm:col-span-2">
                                  <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">Clase de prioridad relativa</p>
                                  <p className="text-[10px] text-white font-mono">{mapPriorityClassLabel(recommendation)}</p>
                                  <div className="flex items-center gap-2 mt-0.5">
                                    <span className="text-[8px] uppercase tracking-[0.18em] text-neutral-600 font-bold">Señal Preliminar:</span>
                                    <span className="text-[9px] font-mono text-neutral-400">{recommendation}</span>
                                  </div>
                                  <p className="text-[7px] text-neutral-600 italic mt-0.5">No representa recomendación de perforación.</p>
                                </div>
                              )}
                              {riskLevel && (
                                <div>
                                  <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">Confiabilidad técnica</p>
                                  <p className="text-[10px] text-white font-mono">{riskLevel}</p>
                                </div>
                              )}
                              {confidenceLevel && (
                                <div>
                                  <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-1">Confidence</p>
                                  <p className="text-[10px] text-white font-mono">{confidenceLevel}</p>
                                </div>
                              )}
                            </div>
                          )}
                          
                          <details className="mt-2 border-t border-neutral-800 pt-3">
                            <summary className="text-neutral-500 mb-3 cursor-pointer text-[9px] uppercase tracking-widest hover:text-[#C2D8C4] transition-colors focus:outline-none">
                              Ver resumen técnico de inversión
                            </summary>
                            
                            {invertResult.warnings && invertResult.warnings.length > 0 && (
                              <div className="mb-4 p-3 border border-yellow-600/30 bg-yellow-600/10 rounded">
                                <p className="text-[9px] uppercase tracking-widest text-yellow-500 mb-1 font-bold">Warnings de Inversión:</p>
                                <ul className="list-disc list-inside text-[10px] text-yellow-500/90 font-mono">
                                  {invertResult.warnings.map((warn: string, i: number) => <li key={i}>{warn}</li>)}
                                </ul>
                              </div>
                            )}

                            {renderInversionSummary(invertResult.inversionResult)}

                          </details>

                          <div className="mt-4 border-t border-neutral-800 pt-4 flex flex-col gap-3">
                            {projectId && runId && (
                              <>
                                <button
                                  onClick={handleLoadCsvModel3D}
                                  disabled={loading3D}
                                  className="h-9 w-full justify-center px-4 bg-purple-500/80 text-white text-[10px] uppercase font-bold tracking-widest rounded hover:bg-purple-500 disabled:opacity-50 transition-colors flex items-center"
                                >
                                  {loading3D ? "Cargando..." : "Ver modelo 3D generado desde CSV"}
                                </button>
                                {load3DError && (
                                  <p className="text-[10px] text-red-400 font-mono p-2 bg-red-900/20 rounded border border-red-900/50">
                                    {load3DError}
                                  </p>
                                )}
                              </>
                            )}
                            <button
                              onClick={() => setView("datos")}
                              className="h-9 w-full justify-center px-4 border border-neutral-700 bg-neutral-900 text-white text-[10px] uppercase font-bold tracking-widest rounded hover:bg-white hover:text-black transition-colors flex items-center"
                            >
                              Ver en Datos
                            </button>
                            {!projectId && !runId && (
                              <p className="text-[10px] text-red-400 font-mono bg-red-900/20 p-2 rounded border border-red-900/50 break-words mt-2">
                                No se detecto projectId/runId en la respuesta de inversion CSV.
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                ) : (
                  <p className="text-[10px] text-neutral-500">No hay datos de resultado de inversión para mostrar.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
