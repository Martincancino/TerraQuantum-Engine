"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { previewGravityCsv, GravityCsvInvertPayload, getExplorationBlockModelForRunWithArrow, CoordinateTransformData, SpatialReadiness, RegionalScalePreflight, GravityCorrectionReport, exportCleanCsv } from "../lib/terraquantum/frontendApi";
import WarningBanner from "./WarningBanner";
import { TQErrorView } from "../lib/terraquantum/errorContract";
import { useAppStore } from "../store/useAppStore";
import GravityCorrectionWizard from "./GravityCorrectionWizard";
import { type VoxelMineralModel, type VoxelData } from "../lib/terraQuantumGeology";
import { isJsonObject, readStringField, readNumberField } from "./datos/helpers";
import { PgiParamsForm, type PgiParamsUI } from "./PgiParamsForm";
import { MagneticRemanenceForm, type MagneticRemanenceParamsUI } from "./MagneticRemanenceForm";
import { buildCsvPackage, downloadCsvPackage, type CsvPackageParams } from "../lib/terraquantum/csvPackage";

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

// ─── Fase 19: Data Quality + tipo de dato detectado helpers ───────────────

function getDataQualityColor(score: number): string {
  if (score >= 75) return "text-green-400 border-green-600/40 bg-green-900/20";
  if (score >= 50) return "text-yellow-400 border-yellow-600/40 bg-yellow-900/20";
  return "text-red-400 border-red-600/40 bg-red-900/20";
}

function getDataQualityBarColor(score: number): string {
  if (score >= 75) return "bg-green-500";
  if (score >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

function getDataTypeLabel(t?: string | null): string {
  switch ((t ?? "unknown").toLowerCase()) {
    case "gravity": return "Gravimetría";
    case "magnetic": return "Magnetometría";
    case "joint": return "Gravimetría + Magnetometría (joint)";
    case "borehole": return "Sondajes";
    case "ambiguous": return "Ambiguo — confirmar tipo";
    default: return "Desconocido — confirmar tipo";
  }
}

function getDataTypeBadgeClass(confidence?: string | null): string {
  const c = (confidence ?? "low").toLowerCase();
  if (c === "high") return "text-green-400 border-green-600/40 bg-green-900/20";
  if (c === "medium") return "text-yellow-400 border-yellow-600/40 bg-yellow-900/20";
  return "text-orange-400 border-orange-600/40 bg-orange-900/20";
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

// ─── Fase 14: Client-side CSV Validation ─────────────────────────────────

type CsvIssue = { type: "error" | "warning"; message: string };

interface CsvValidationResult {
  status: "ok" | "warning" | "invalid";
  issues: CsvIssue[];
  n_sensors: number;
  can_invert: boolean;
}

function parseCsvForValidation(text: string): CsvValidationResult {
  const issues: CsvIssue[] = [];
  const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"));
  if (lines.length < 2) {
    return { status: "invalid", issues: [{ type: "error", message: "CSV vacío o sin datos." }], n_sensors: 0, can_invert: false };
  }

  const header = lines[0].split(/[,;\t]/).map((h) => h.trim().toLowerCase());
  const dataLines = lines.slice(1).filter((l) => l.trim());

  // Detectar columna de gravedad
  const gCandidates = ["gravity_mgal", "g_mgal", "bouguer", "free_air", "gravity", "g", "tmi", "magnetic_nt"];
  const gIdx = gCandidates.map((c) => header.indexOf(c)).find((i) => i >= 0) ?? -1;

  // Detectar columnas de posición
  const xCandidates = ["x_m", "x", "easting", "longitude", "lon"];
  const zCandidates = ["z_m", "z", "northing", "latitude", "lat"];
  const xIdx = xCandidates.map((c) => header.indexOf(c)).find((i) => i >= 0) ?? -1;
  const zIdx = zCandidates.map((c) => header.indexOf(c)).find((i) => i >= 0) ?? -1;

  if (gIdx < 0) {
    issues.push({ type: "error", message: "No se detectó columna de gravedad (gravity_mgal, g_mgal, tmi, etc.)." });
    return { status: "invalid", issues, n_sensors: 0, can_invert: false };
  }

  const gValues: number[] = [];
  const positions: Array<[number, number]> = [];

  for (const line of dataLines) {
    const cols = line.split(/[,;\t]/);
    const gRaw = parseFloat(cols[gIdx]);
    if (Number.isFinite(gRaw)) gValues.push(gRaw);
    if (xIdx >= 0 && zIdx >= 0) {
      const xv = parseFloat(cols[xIdx]);
      const zv = parseFloat(cols[zIdx]);
      if (Number.isFinite(xv) && Number.isFinite(zv)) positions.push([xv, zv]);
    }
  }

  const n = gValues.length;

  // 1. Mínimo de sensores
  if (n < 5) {
    issues.push({ type: "error", message: `Solo ${n} observación(es) válidas. Se requieren ≥ 5.` });
  }

  // 2. Rango cero
  if (n > 0) {
    const gMin = Math.min(...gValues);
    const gMax = Math.max(...gValues);
    if (gMax - gMin < 1e-10) {
      issues.push({ type: "error", message: "Rango cero: todas las observaciones son idénticas." });
    }
  }

  // 3. Duplicados de posición
  if (positions.length === n && n > 1) {
    const tol = 1.0;
    const keySet = new Set<string>();
    let nDup = 0;
    for (const [xv, zv] of positions) {
      const key = `${Math.round(xv / tol)}_${Math.round(zv / tol)}`;
      if (keySet.has(key)) nDup++;
      else keySet.add(key);
    }
    if (nDup > 0) {
      issues.push({ type: "warning", message: `${nDup} sensor(es) duplicados (misma posición x,z). Se promediarán en el backend.` });
    }
  }

  // 4. Outlier anómalo (|g| > 10× mediana)
  if (n > 1) {
    const sorted = [...gValues.map(Math.abs)].sort((a, b) => a - b);
    const medianAbs = n % 2 === 0 ? (sorted[n / 2 - 1] + sorted[n / 2]) / 2 : sorted[Math.floor(n / 2)];
    if (medianAbs > 1e-10) {
      const nOutliers = gValues.filter((g) => Math.abs(g) / medianAbs > 10).length;
      if (nOutliers > 0 && nOutliers <= Math.max(1, Math.floor(n / 5))) {
        issues.push({ type: "warning", message: `${nOutliers} valor(es) anómalo(s) detectados (|g| > 10× mediana). Revisa antes de invertir.` });
      }
    }
  }

  const hasErrors = issues.some((i) => i.type === "error");
  const hasWarnings = issues.some((i) => i.type === "warning");

  return {
    status: hasErrors ? "invalid" : hasWarnings ? "warning" : "ok",
    issues,
    n_sensors: n,
    can_invert: !hasErrors,
  };
}

// ─── Fin Fase 14 ──────────────────────────────────────────────────────────

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

type PrepPanelProps = {
  // FASE 20 — Sondajes que anclan la inversión (combo grav+sondajes). Vienen del
  // BoreholeUploadPanel (vista «Preparación»). Se empaquetan en el paquete CSV.
  boreholes?: GravityCsvInvertPayload["boreholes"];
};

// PrepPanel (ex GravityCsvPreviewPanel) — vista «Preparación». Importa/valida el
// survey, recolecta parámetros y genera el paquete CSV. NO invierte: la inversión
// ocurre en LoadPanel (vista 3D).
export default function PrepPanel({ boreholes }: PrepPanelProps = {}) {
  const {
    fileGravimetry, setFileGravimetry,
    fileMagnetometry, setFileMagnetometry,
    latNorth, setLatNorth,
    latSouth, setLatSouth,
    lonEast, setLonEast,
    lonWest, setLonWest,
    gravityPreviewResult: result, setGravityPreviewResult: setResult
  } = useAppStore();

  const file = fileGravimetry; // Retrocompatibilidad para endpoints que solo toman 'file'

  const [strict, setStrict] = useState(true);
  const [allowGRaw, setAllowGRaw] = useState(false);
  const [previewLimit, setPreviewLimit] = useState(20);

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // FASE 19 — Descarga de "CSV limpio".
  const [cleanCsvLoading, setCleanCsvLoading] = useState(false);
  const [cleanCsvError, setCleanCsvError] = useState<string | null>(null);
  // FASE R3 — Generación del "paquete CSV" (CSV limpio + parámetros) para LoadPanel.
  const [packageError, setPackageError] = useState<string | null>(null);
  const [packageMessage, setPackageMessage] = useState<string | null>(null);
  // FASE 19 — Contexto del survey (alimenta el ruteo multimodal / interpretación).
  const [expectedRock, setExpectedRock] = useState<string>("");
  const [expectedDepth, setExpectedDepth] = useState<string>("");

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

  const [showCorrectionWizard, setShowCorrectionWizard] = useState(false);
  const [correctedFile, setCorrectedFile] = useState<File | null>(null);
  const [correctionReport, setCorrectionReport] = useState<GravityCorrectionReport | null>(null);

  // Fase 7B — Advanced inversion params
  const [showPgiModal, setShowPgiModal] = useState(false);
  const [pgiParams, setPgiParams] = useState<PgiParamsUI | null>(null);
  const [showRemanenceModal, setShowRemanenceModal] = useState(false);
  const [remanenceParams, setRemanenceParams] = useState<MagneticRemanenceParamsUI | null>(null);

  // Fase 14: client-side CSV validation
  const [csvValidation, setCsvValidation] = useState<CsvValidationResult | null>(null);

  // Ejecutar validación local cuando cambia el archivo activo
  useEffect(() => {
    const activeFile = dataType === "magnetic" ? fileMagnetometry : (correctedFile ?? file);
    if (!activeFile) { setCsvValidation(null); return; }
    let cancelled = false;
    activeFile.text().then((text) => {
      if (!cancelled) setCsvValidation(parseCsvForValidation(text));
    }).catch(() => {
      if (!cancelled) setCsvValidation(null);
    });
    return () => { cancelled = true; };
  }, [file, fileMagnetometry, correctedFile, dataType]);

  const [utmZone, setUtmZone] = useState<string>("");
  // Tier 1 B6 — controles físicos. El frontend solo recolecta y valida forma;
  // la física (bounds, sigma, selección de λ) la resuelve el backend.
  const [densityMin, setDensityMin] = useState<string>("0.0");
  const [densityMax, setDensityMax] = useState<string>("5.5");
  const [densityPreset, setDensityPreset] = useState<"granite" | "magnetite" | "copper" | "custom">("custom");
  const [gravimeterType, setGravimeterType] = useState<string>("unknown");
  const [lambdaMode, setLambdaMode] = useState<"auto" | "custom">("auto");
  const [lambdaCustom, setLambdaCustom] = useState<string>("0.1");
  // FASE 16 — Kappas configurables (sliders en escala log, ocultos por defecto)
  const [showAdvancedKappas, setShowAdvancedKappas] = useState(false);
  const [paddingKappaLog, setPaddingKappaLog] = useState<number>(5); // log10(1e5)
  const [anchorKappaLog, setAnchorKappaLog] = useState<number>(4);   // log10(1e4)
  const [autoKappa, setAutoKappa] = useState(true);
  const [acknowledgeSpatialRisk, setAcknowledgeSpatialRisk] = useState(false);
  const [acknowledgeRegionalScale, setAcknowledgeRegionalScale] = useState(false);

  // FASE 16 — Aplica preset de bounds de densidad según litología
  const applyDensityPreset = (preset: "granite" | "magnetite" | "copper" | "custom") => {
    setDensityPreset(preset);
    if (preset === "granite")   { setDensityMin("2.6"); setDensityMax("3.0"); }
    if (preset === "magnetite") { setDensityMin("4.5"); setDensityMax("5.5"); }
    if (preset === "copper")    { setDensityMin("4.3"); setDensityMax("4.8"); }
  };

  const utmZoneError = useMemo(() => validateUtmZone(utmZone), [utmZone]);
  const derivedEpsg = useMemo(() => deriveEpsgFromUtmZone(utmZone), [utmZone]);
  const isUtmDetected = useMemo(() => {
    const type = result?.georef_preview?.type;
    const detected = result?.csv_analysis?.coordinate_system?.detected;
    return type === "csv_utm" || type === "utm" || detected === "utm";
  }, [result]);

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

  // Se han eliminado userLat y userLon en favor del Bounding Box en Zustand
  const [geoError, setGeoError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Helpers locales — devuelven Record<string, unknown> | null, sin usar any
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
      setPackageError(null);
      setPackageMessage(null);
      setGeoError(null);
      setUtmZone("");
      setAcknowledgeSpatialRisk(false);
      setAcknowledgeRegionalScale(false);
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
      setPackageError(null);
      setPackageMessage(null);
      setGeoError(null);
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
    setPackageError(null);
    setPackageMessage(null);

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
    setAcknowledgeRegionalScale(false);
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

  // FASE 19 — Descargar el CSV limpio (validado + enriquecido) del backend.
  async function handleDownloadCleanCsv() {
    if (!file) return;
    setCleanCsvError(null);
    setCleanCsvLoading(true);
    try {
      const res = await exportCleanCsv(file, dataType);
      if (!res.ok || !res.blob) {
        setCleanCsvError(res.error || "No se pudo generar el CSV limpio.");
        return;
      }
      const url = URL.createObjectURL(res.blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.filename;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setCleanCsvLoading(false);
    }
  }

  // FASE R3 — Genera y descarga el "paquete CSV" (CSV limpio/corregido + todos
  // los parámetros de inversión). LoadPanel (vista 3D) lo sube y corre la
  // inversión. No invierte aquí: solo empaqueta el dato preparado.
  const handleGeneratePackage = async () => {
    setPackageError(null);
    setPackageMessage(null);

    const isMagnetic = dataType === "magnetic";
    const sourceFile = isMagnetic ? fileMagnetometry : (correctedFile ?? file);
    if (!sourceFile) {
      setPackageError(
        isMagnetic
          ? "Selecciona un CSV de magnetometría antes de generar el paquete."
          : "Selecciona y valida un CSV antes de generar el paquete.",
      );
      return;
    }

    const geoErr = validateCoords();
    if (geoErr) {
      setPackageError(geoErr);
      return;
    }
    if (utmZone.trim() && utmZoneError) {
      setPackageError(utmZoneError);
      return;
    }

    let csvText: string;
    try {
      csvText = await sourceFile.text();
    } catch {
      setPackageError("No se pudo leer el contenido del CSV.");
      return;
    }

    const params: CsvPackageParams = {
      strict,
      allowGRaw: allowGRaw || correctedFile !== null,
      densityMin,
      densityMax,
      densityPreset,
      gravimeterType,
      lambdaMode,
      lambdaCustom,
      paddingKappaLog,
      anchorKappaLog,
      autoKappa,
      utmZone,
      acknowledgeSpatialRisk,
      acknowledgeRegionalScale,
      expectedRock,
      expectedDepth,
      inclinationDeg,
      declinationDeg,
      fieldIntensityNt,
      suscMin,
      suscMax,
    };

    const pkg = buildCsvPackage({
      dataType,
      csvFilename: sourceFile.name,
      csvText,
      corrected: !isMagnetic && correctedFile !== null,
      params,
      pgiParams,
      remanenceParams,
      boreholes,
    });

    downloadCsvPackage(pkg);
    setPackageMessage(
      "Paquete CSV generado. Súbelo en la vista 3D para cargar el modelo.",
    );
  };

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
          {/* FASE 16 — Preset de bounds de densidad */}
          {dataType !== "magnetic" && (
            <div>
              <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                Litología objetivo (bounds de densidad)
              </label>
              <select
                value={densityPreset}
                onChange={(e) => applyDensityPreset(e.target.value as "granite" | "magnetite" | "copper" | "custom")}
                className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
                title="Selecciona un preset para fijar density_min/max automáticamente."
              >
                <option value="granite">Granito (2.6–3.0 t/m³)</option>
                <option value="magnetite">Magnetita (4.5–5.5 t/m³)</option>
                <option value="copper">Cobre porfírico (4.3–4.8 t/m³)</option>
                <option value="custom">Personalizado</option>
              </select>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                Densidad mín (t/m³)
              </label>
              <input
                type="number"
                step="0.05"
                value={densityMin}
                onChange={(e) => { setDensityMin(e.target.value); setDensityPreset("custom"); }}
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
                onChange={(e) => { setDensityMax(e.target.value); setDensityPreset("custom"); }}
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
          {/* FASE 16 — Advanced: Soft Constraints (kappas, hidden by default) */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvancedKappas(v => !v)}
              className="text-[9px] uppercase text-neutral-500 tracking-widest hover:text-neutral-300 flex items-center gap-1"
            >
              <span>{showAdvancedKappas ? "▾" : "▸"}</span>
              Avanzado: Soft Constraints (kappas)
            </button>
            {showAdvancedKappas && (
              <div className="mt-2 flex flex-col gap-2 pl-2 border-l border-neutral-700">
                <div>
                  <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                    Padding Kappa (10^{paddingKappaLog} = {Math.pow(10, paddingKappaLog).toExponential(0)})
                  </label>
                  <input
                    type="range"
                    min={2} max={8} step={0.5}
                    value={paddingKappaLog}
                    onChange={(e) => setPaddingKappaLog(Number(e.target.value))}
                    title="Peso soft constraint para celdas de borde (padding). Aumentar si cond(A) < 1e6."
                    className="w-full accent-[#C2D8C4]"
                  />
                  <div className="flex justify-between text-[8px] text-neutral-600">
                    <span>1e2</span><span>1e5 (default)</span><span>1e8</span>
                  </div>
                </div>
                <div>
                  <label className="block text-[9px] uppercase text-neutral-500 tracking-widest mb-1">
                    Anchor Kappa (10^{anchorKappaLog} = {Math.pow(10, anchorKappaLog).toExponential(0)})
                  </label>
                  <input
                    type="range"
                    min={2} max={8} step={0.5}
                    value={anchorKappaLog}
                    onChange={(e) => setAnchorKappaLog(Number(e.target.value))}
                    title="Peso soft constraint para vóxeles anclados por sondaje. NO superar 1e6."
                    className="w-full accent-[#C2D8C4]"
                  />
                  <div className="flex justify-between text-[8px] text-neutral-600">
                    <span>1e2</span><span>1e4 (default)</span><span>1e8</span>
                  </div>
                </div>
                <label className="flex items-center gap-2 text-[10px] text-neutral-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoKappa}
                    onChange={(e) => setAutoKappa(e.target.checked)}
                    className="accent-[#C2D8C4]"
                  />
                  Ajuste automático si cond(A) &gt; 1e12
                </label>
              </div>
            )}
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

        {/* ── Fase 14: CSV Validation Badge ───────────────────────────────── */}
        {csvValidation && (
          <div className={`p-2.5 border rounded text-[10px] font-mono ${
            csvValidation.status === "ok"
              ? "border-green-600/40 bg-green-900/20 text-green-300"
              : csvValidation.status === "warning"
              ? "border-yellow-600/40 bg-yellow-900/20 text-yellow-300"
              : "border-red-600/40 bg-red-900/20 text-red-300"
          }`}>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold text-[11px]">
                {csvValidation.status === "ok" && "✓ CSV limpio"}
                {csvValidation.status === "warning" && `⚠ CSV con avisos (${csvValidation.issues.filter(i => i.type === "warning").length})`}
                {csvValidation.status === "invalid" && `✗ CSV inválido (${csvValidation.issues.filter(i => i.type === "error").length} error(es))`}
              </span>
              <span className="text-neutral-500">{csvValidation.n_sensors} sensor(es)</span>
            </div>
            {csvValidation.issues.length > 0 && (
              <ul className="list-none space-y-0.5 mt-1">
                {csvValidation.issues.map((issue, i) => (
                  <li key={i} className={issue.type === "error" ? "text-red-400" : "text-yellow-400"}>
                    {issue.type === "error" ? "✗" : "⚠"} {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex items-end w-full min-w-0">
          <button
            onClick={handleValidate}
            disabled={loading || !(dataType === "magnetic" ? fileMagnetometry : file) || csvValidation?.can_invert === false}
            title={csvValidation?.can_invert === false ? "Corrige los errores del CSV antes de continuar." : undefined}
            className="h-9 w-full justify-center px-4 bg-[#C2D8C4] text-black text-[10px] uppercase font-bold tracking-widest rounded hover:bg-[#a5bca7] disabled:opacity-50 transition-colors flex items-center"
          >
            {loading ? "Validando..." : dataType === "magnetic" ? "Validar CSV magnético" : "Validar CSV"}
          </button>
        </div>

        {/* FASE 19 — Descargar CSV limpio (validado + enriquecido por el backend) */}
        {file && (
          <div className="flex flex-col gap-1">
            <button
              onClick={handleDownloadCleanCsv}
              disabled={cleanCsvLoading}
              title="Descarga el CSV normalizado (unidades, coordenadas, sigma, elevación) que consumirá la inversión."
              className="h-8 w-full justify-center px-4 border border-[#C2D8C4]/40 text-[#C2D8C4] text-[10px] uppercase font-bold tracking-widest rounded hover:bg-[#C2D8C4]/10 disabled:opacity-50 transition-colors flex items-center"
            >
              {cleanCsvLoading ? "Generando..." : "↓ Descargar CSV limpio"}
            </button>
            {cleanCsvError && (
              <span className="text-[9px] text-red-400 font-mono">{cleanCsvError}</span>
            )}
          </div>
        )}
      </div>

      {errorMsg && (
        <div className="mb-4 p-4 border border-red-900/50 bg-red-950/20 text-red-400 text-sm font-mono rounded">
          <span className="font-bold mr-2">ERROR:</span> {errorMsg}
        </div>
      )}

      {/* FASE 23 — Avisos no bloqueantes del backend (validación / inversión) */}
      {(() => {
        const backendWarnings: string[] = [
          ...((result?.warnings as string[] | undefined) ?? []),
        ].filter((w): w is string => typeof w === "string" && w.trim().length > 0);
        if (backendWarnings.length === 0) return null;
        const views: TQErrorView[] = backendWarnings.slice(0, 12).map((msg, i) => ({
          code: `BACKEND_WARNING_${i}`,
          severity: "warning",
          userMessage: msg,
          suggestedAction: "",
          technicalDetails: {},
        }));
        return (
          <div className="mb-4">
            <WarningBanner warnings={views} showAction={false} />
          </div>
        );
      })()}

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

          {/* ── Fase 19: Validación del CSV — tipo detectado + Data Quality ── */}
          {(result.detected_data_type || result.csv_analysis?.data_quality) && (
            <div className="mb-4 p-3 border border-neutral-700 bg-black/40 rounded">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[#C2D8C4] mb-3">
                Validación del CSV
              </p>

              {result.detected_data_type && (
                <div className="mb-3">
                  <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">
                    Tipo de dato detectado
                  </span>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    <span className={`px-2 py-1 border rounded text-[10px] font-bold uppercase tracking-wider ${getDataTypeBadgeClass(result.detected_data_type.confidence)}`}>
                      {getDataTypeLabel(result.detected_data_type.detected_type)}
                    </span>
                    <span className="text-[9px] text-neutral-500 font-mono">
                      confianza: {result.detected_data_type.confidence}
                    </span>
                  </div>
                  {result.detected_data_type.warning && (
                    <p className="mt-1 text-[9px] text-yellow-400/80 font-mono">
                      ⚠ {result.detected_data_type.warning}
                    </p>
                  )}
                </div>
              )}

              {result.csv_analysis?.data_quality && (() => {
                const dq = result.csv_analysis!.data_quality!;
                const comps: Array<[string, number]> = [
                  ["Completitud", dq.completeness],
                  ["Distribución espacial", dq.spatial_distribution],
                  ["Nivel de ruido", dq.noise_level],
                  ["Resolución", dq.resolution],
                  ["Outliers", dq.outlier_fraction],
                ];
                return (
                  <div className={`p-3 border rounded ${getDataQualityColor(dq.score)}`}>
                    <div className="flex items-baseline gap-2 mb-2">
                      <span className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">
                        Data Quality
                      </span>
                      <span className="text-2xl font-bold">{dq.score.toFixed(0)}</span>
                      <span className="text-[10px] text-neutral-400">/100</span>
                      <span className="text-[11px] font-bold uppercase tracking-wider ml-1">
                        {dq.interpretation}
                      </span>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {comps.map(([label, val]) => (
                        <div key={label} className="flex items-center gap-2">
                          <span className="text-[9px] text-neutral-400 w-32 shrink-0">{label}</span>
                          <div className="flex-1 h-1.5 bg-neutral-800 rounded overflow-hidden">
                            <div
                              className={`h-full ${getDataQualityBarColor(val)}`}
                              style={{ width: `${Math.max(0, Math.min(100, val))}%` }}
                            />
                          </div>
                          <span className="text-[9px] font-mono text-neutral-400 w-8 text-right">
                            {val.toFixed(0)}
                          </span>
                        </div>
                      ))}
                    </div>
                    {dq.notes && dq.notes.length > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-[8px] uppercase tracking-widest text-neutral-500 hover:text-neutral-300 outline-none">
                          Cómo se calcula
                        </summary>
                        <ul className="list-disc list-inside text-[8px] text-neutral-500 font-mono mt-1 space-y-0.5">
                          {dq.notes.map((n, i) => <li key={i}>{n}</li>)}
                        </ul>
                      </details>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

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

          {/* ── Fase 5: Resolución real + contexto geológico honesto ───────── */}
          {result.importMetadata?.estimated_mean_spacing_m != null && (
            <div className="mb-4 p-3 border border-yellow-600/40 bg-yellow-900/20 rounded">
              <p className="text-[10px] font-bold uppercase tracking-widest text-yellow-400 mb-2">
                Resolución &amp; Contexto Geológico
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-2 text-[10px] font-mono">
                <div>
                  <span className="text-neutral-500">Espaciado medio:</span>{" "}
                  <span className="text-white">{result.importMetadata.estimated_mean_spacing_m.toFixed(1)} m</span>
                </div>
                <div>
                  <span className="text-neutral-500">Prof. resoluble (Li &amp; Oldenburg):</span>{" "}
                  <span className="text-white">
                    {result.importMetadata.estimated_depth_resolution_m != null
                      ? `${result.importMetadata.estimated_depth_resolution_m.toFixed(1)} m`
                      : "N/A"}
                  </span>
                </div>
                <div>
                  <span className="text-neutral-500">Escala survey:</span>{" "}
                  <span className="text-yellow-300 uppercase">
                    {result.importMetadata.geological_context_hint?.replace(/_/g, " ") ?? "—"}
                  </span>
                </div>
              </div>
              <p className="text-[10px] text-yellow-200/70 italic">
                Este modelo invertido es geofísicamente válido a su escala, pero{" "}
                <strong className="text-yellow-300">no emite ley, tonelaje ni indicadores mineros</strong>.
                Solo proporciona densidad / susceptibilidad recuperadas. Para interpretación
                minera o de viabilidad, consultar sondajes, análisis de rentabilidad y
                restricciones geológicas independientes.
              </p>
            </div>
          )}

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

            {/* FASE 19 — Contexto del survey (roca/profundidad esperadas) + estado
                de sondajes. La roca/profundidad esperadas guían la interpretación;
                los sondajes anclados ALIMENTAN el ruteo multimodal (panel Fase 21). */}
            <div className="mb-5 p-3 border border-neutral-800 bg-neutral-900/40 rounded">
              <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-2">
                Contexto del survey (Fase 19)
              </p>
              <div className="grid grid-cols-2 gap-2 mb-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[8px] uppercase text-neutral-500">Roca esperada</span>
                  <select
                    value={expectedRock}
                    onChange={(e) => setExpectedRock(e.target.value)}
                    className="bg-neutral-800 border border-neutral-700 rounded text-[10px] text-neutral-300 px-2 py-1"
                  >
                    <option value="">—</option>
                    <option value="granito">Granito</option>
                    <option value="magnetita">Magnetita</option>
                    <option value="cobre">Cobre / pórfido</option>
                    <option value="diorita">Diorita</option>
                    <option value="otra">Otra</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[8px] uppercase text-neutral-500">Profundidad esperada</span>
                  <select
                    value={expectedDepth}
                    onChange={(e) => setExpectedDepth(e.target.value)}
                    className="bg-neutral-800 border border-neutral-700 rounded text-[10px] text-neutral-300 px-2 py-1"
                  >
                    <option value="">—</option>
                    <option value="100-500">100–500 m</option>
                    <option value="500-2000">500 m – 2 km</option>
                    <option value=">2000">&gt; 2 km</option>
                  </select>
                </label>
              </div>
              <div className="text-[9px] font-mono">
                {boreholes && boreholes.length > 0 ? (
                  <span className="text-[#C2D8C4]">
                    ✓ {boreholes.length} sondaje(s) anclado(s) → combo grav+sondajes
                  </span>
                ) : (
                  <span className="text-neutral-500">
                    Sin sondajes cargados → gravimetría sola (carga sondajes en el panel Fase 20)
                  </span>
                )}
              </div>
            </div>

            {/* Fase 7B — Botones de parámetros avanzados */}
            <div className="flex gap-2 mb-4 flex-wrap">
              <button
                onClick={() => setShowPgiModal(true)}
                className={`px-3 py-1.5 text-[9px] uppercase tracking-widest font-bold rounded border transition-colors ${
                  pgiParams?.enabled
                    ? "bg-purple-600/30 border-purple-500 text-purple-300"
                    : "bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-neutral-500"
                }`}
              >
                PGI {pgiParams?.enabled ? `(K=${pgiParams.n_components_auto})` : ""}
              </button>
              {dataType === "magnetic" && (
                <button
                  onClick={() => setShowRemanenceModal(true)}
                  className={`px-3 py-1.5 text-[9px] uppercase tracking-widest font-bold rounded border transition-colors ${
                    remanenceParams?.enabled
                      ? "bg-orange-600/30 border-orange-500 text-orange-300"
                      : "bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-neutral-500"
                  }`}
                >
                  Remanencia {remanenceParams?.enabled ? `(Q=${remanenceParams.q_ratio.toFixed(1)})` : ""}
                </button>
              )}
            </div>

            {/* Modals */}
            {showPgiModal && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowPgiModal(false)}>
                <div onClick={(e) => e.stopPropagation()}>
                  <PgiParamsForm
                    initialParams={pgiParams ?? undefined}
                    onSubmit={(p) => { setPgiParams(p); setShowPgiModal(false); }}
                    onCancel={() => setShowPgiModal(false)}
                  />
                </div>
              </div>
            )}
            {showRemanenceModal && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowRemanenceModal(false)}>
                <div onClick={(e) => e.stopPropagation()}>
                  <MagneticRemanenceForm
                    initialParams={remanenceParams ?? undefined}
                    onSubmit={(p) => { setRemanenceParams(p); setShowRemanenceModal(false); }}
                    onCancel={() => setShowRemanenceModal(false)}
                  />
                </div>
              </div>
            )}

            <div className="flex flex-col gap-4 mb-6">
              {/* FASE R3 — El prep solo genera el paquete CSV; la inversión y la
                  carga del modelo 3D ocurren en la vista 3D (LoadPanel). */}
              <button
                onClick={handleGeneratePackage}
                disabled={
                  !(dataType === "magnetic" ? fileMagnetometry : file) ||
                  csvValidation?.can_invert === false ||
                  result.spatial_readiness?.level === "NO_SPATIAL_DATA" ||
                  (result.spatial_readiness?.requires_user_acknowledgement === true && !acknowledgeSpatialRisk) ||
                  result.regional_scale_preflight?.can_run_single_inversion === false ||
                  (result.regional_scale_preflight?.requires_user_acknowledgement === true && !acknowledgeRegionalScale)
                }
                className="h-9 w-full justify-center px-4 bg-[#C2D8C4] text-black text-[10px] uppercase font-bold tracking-widest rounded hover:bg-white disabled:opacity-50 transition-colors flex items-center"
              >
                ↓ Generar paquete CSV
              </button>
              {packageMessage && (
                <p className="text-[10px] text-emerald-400 font-mono text-center">
                  {packageMessage}
                </p>
              )}
              {packageError && (
                <p className="text-[10px] text-red-400 font-mono text-center">
                  {packageError}
                </p>
              )}
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

          </div>
        </div>
      )}
    </div>
  );
}
