"use client";

import { useEffect, useMemo, useReducer } from "react";
import {
  applyGravityCorrections,
  nettletonAnalysis,
  parseCsvRows,
  GravityCorrectionParams,
  GravityCorrectedStation,
  GravityCorrectionReport,
  type NettletonResult,
  type SniffReport,
} from "../lib/terraquantum/frontendApi";

// ─── Column auto-detection ────────────────────────────────────────────────────

const LAT_ALIASES = new Set(["lat", "latitude", "lat_deg", "latitud", "y_lat"]);
const LON_ALIASES = new Set(["lon", "longitude", "long", "lon_deg", "longitud", "lng", "x_lon"]);
const ELEV_ALIASES = new Set([
  "elevation", "elevation_m", "elev", "elev_m", "rl", "rl_m",
  "altitude", "altitude_m", "height", "height_m", "cota", "cota_m", "z",
]);
const G_ALIASES = new Set([
  "gravity_anomaly", "g_corrected", "complete_bouguer_anomaly", "bouguer_anomaly",
  "free_air_anomaly", "cba", "faa", "gravity_mgal", "g_mgal", "observed_gravity",
  "g", "g_raw", "gravity", "gz", "g_obs", "g_obs_mgal",
]);
const ID_ALIASES = new Set(["station_id", "station", "sta", "id", "name", "estacion", "punto"]);
// F2B — hora de lectura (para marea Longman y deriva por cierres de base).
const TIME_ALIASES = new Set([
  "time_utc", "time", "timestamp", "datetime", "date_time", "fecha_hora",
  "hora", "hora_utc", "fecha",
]);

function detectColumn(headers: string[], aliases: Set<string>): string {
  for (const h of headers) {
    if (aliases.has(h.toLowerCase().trim())) return h;
  }
  return "";
}

// ─── Marshaling de filas YA parseadas por el backend ─────────────────────────
// F2 (cierre de deuda): el CSV se parsea en el BACKEND (POST parse-rows, con
// el sniffer: encoding/separador/decimal/preámbulo). Aquí llegan filas como
// Record<col, string> con valores canónicos (punto decimal) — parseFloat es
// seguro. Este componente solo re-etiqueta columnas y arma el payload.

type ColMap = { lat: string; lon: string; elev: string; g: string; id: string; time: string };
type CsvRow = Record<string, string>;

function buildStations(
  rows: CsvRow[],
  colMap: ColMap
): Record<string, number | string>[] {
  // Number() y no parseFloat: si el contrato canónico del backend se violara
  // alguna vez ("1234,5"), Number() da NaN RUIDOSO (fila descartada) mientras
  // parseFloat truncaría a 1234 en silencio (observación del reviewer F2).
  const num = (col: string, row: CsvRow) => {
    const raw = col ? (row[col] ?? "").trim() : "";
    return raw === "" ? NaN : Number(raw);
  };

  const result: Record<string, number | string>[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const lat = num(colMap.lat, row);
    const lon = num(colMap.lon, row);
    const g = num(colMap.g, row);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(g)) continue;

    const idRaw = colMap.id ? (row[colMap.id] ?? "").trim() : "";
    const station: Record<string, number | string> = {
      station_id: idRaw || `ST_${String(i).padStart(6, "0")}`,
      lat_deg: lat,
      lon_deg: lon,
      g_obs_mgal: g,
    };
    const elev = num(colMap.elev, row);
    if (Number.isFinite(elev)) station.elev_m = elev;
    // F2B — la hora viaja como STRING tal cual; el backend la parsea
    // (todo-o-nada) para marea Longman y deriva.
    const timeRaw = colMap.time ? (row[colMap.time] ?? "").trim() : "";
    if (timeRaw) station.time_utc = timeRaw;
    result.push(station);
  }
  return result;
}

function outputGravityColName(outputType: string): string {
  if (outputType === "complete_bouguer_anomaly") return "complete_bouguer_anomaly";
  if (outputType === "bouguer_anomaly") return "bouguer_anomaly";
  if (outputType === "free_air_anomaly") return "free_air_anomaly";
  return "g_corrected";
}

function buildCorrectedCsv(
  corrected: GravityCorrectedStation[],
  outputType: string,
  report: GravityCorrectionReport
): string {
  const col = outputGravityColName(outputType);
  const lines: string[] = [
    "# Corrected gravity CSV — MCVoxel TerraQuantum",
    `# corrections_applied: ${report.corrections_applied.join(", ")}`,
    `# reduction_density_gcc: ${report.reduction_density_gcc}`,
  ];
  if (report.dem_source) lines.push(`# dem_source: ${report.dem_source}`);
  lines.push(`station_id,lat_deg,lon_deg,elev_m,${col},uncertainty_mgal`);
  for (const s of corrected) {
    lines.push(
      [s.station_id, s.lat_deg, s.lon_deg, s.elev_m, s.g_bouguer_mgal, s.uncertainty_mgal].join(",")
    );
  }
  return lines.join("\n");
}

// ─── Gravity type options ─────────────────────────────────────────────────────

const GRAVITY_TYPE_OPTIONS = [
  {
    value: "g_raw" as const,
    label: "g_raw — Lectura cruda del gravímetro",
    desc: "Sin correcciones aplicadas. Se aplicarán GRS80, FAC, BC y opcionalmente TC.",
  },
  {
    value: "free_air_anomaly" as const,
    label: "Anomalía Free-Air — solo FAC ya aplicado",
    desc: "La corrección Free-Air ya fue aplicada. Se aplicará BC y opcionalmente TC.",
  },
  {
    value: "bouguer_anomaly" as const,
    label: "Anomalía de Bouguer — FAC + BC ya aplicados",
    desc: "FAC y BC ya aplicados. Solo se aplicará TC si se solicita.",
  },
  {
    value: "complete_bouguer_anomaly" as const,
    label: "Anomalía de Bouguer Completa — todas las correcciones ya aplicadas",
    desc: "Datos completamente reducidos. No se aplicará ninguna corrección adicional.",
  },
] as const;

// ─── Props ────────────────────────────────────────────────────────────────────

type Props = {
  file: File;
  onComplete: (correctedFile: File, report: GravityCorrectionReport) => void;
  onCancel: () => void;
};

// ─── Component ────────────────────────────────────────────────────────────────

// F2.5 (fix eslint react-hooks/static-components): ColSelect vive FUERA del
// componente (definirlo durante el render recreaba el componente y reseteaba
// su estado en cada render). Recibe todo por props.
function ColSelect({
  label,
  field,
  required,
  colMap,
  csvHeaders,
  onSelect,
}: {
  label: string;
  field: keyof ColMap;
  required: boolean;
  colMap: ColMap;
  csvHeaders: string[];
  onSelect: (field: keyof ColMap, value: string) => void;
}) {
  return (
    <div>
      <label className="block text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-1">
        {label}
        {required && <span className="text-red-400 ml-1">*</span>}
      </label>
      <select
        value={colMap[field]}
        onChange={(e) => onSelect(field, e.target.value)}
        className="w-full bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1.5 text-[11px] text-white focus:outline-none focus:border-neutral-500"
      >
        <option value="">— Sin asignar —</option>
        {csvHeaders.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
    </div>
  );
}

// F2B — mini-gráfico del barrido de Nettleton (correlación vs densidad).
// Display-only: los puntos vienen del backend; aquí solo se dibuja el SVG.
function NettletonSweepChart({ result }: { result: NettletonResult }) {
  const { densities_gcc: xs, correlations: ys, best_density_gcc } = result;
  if (xs.length < 2) return null;
  const w = 240;
  const h = 70;
  const pad = 6;
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const absYs = ys.map((v) => Math.abs(v));
  const ymax = Math.max(...absYs, 1e-6);
  const px = (x: number) => pad + ((x - xmin) / (xmax - xmin || 1)) * (w - 2 * pad);
  const py = (v: number) => h - pad - (Math.abs(v) / ymax) * (h - 2 * pad);
  const path = xs.map((x, i) => `${i === 0 ? "M" : "L"}${px(x).toFixed(1)},${py(ys[i]).toFixed(1)}`).join(" ");
  const bx = px(best_density_gcc);
  return (
    <svg width={w} height={h} className="block">
      <line x1={bx} y1={pad} x2={bx} y2={h - pad} stroke="#f59e0b" strokeWidth={1} strokeDasharray="3 2" />
      <path d={path} fill="none" stroke="#93c5fd" strokeWidth={1.5} />
      <text x={pad} y={h - 1} className="fill-neutral-500" style={{ fontSize: 7 }}>
        {xmin.toFixed(1)}
      </text>
      <text x={w - pad - 12} y={h - 1} className="fill-neutral-500" style={{ fontSize: 7 }}>
        {xmax.toFixed(1)} g/cm³
      </text>
      <text x={pad} y={9} className="fill-neutral-500" style={{ fontSize: 7 }}>
        |corr| ↓ (mínimo = óptima)
      </text>
    </svg>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// FASE 10 — Estado del asistente de correcciones.
// Cada paso PRODUCE algo; avanzar y guardar lo producido es una sola transición,
// para que no exista «paso 4 con la vista previa del mapeo anterior».
// ─────────────────────────────────────────────────────────────────────────────

type AsistenteState = {
  step: 1 | 2 | 3 | 4;
  csvHeaders: string[];
  csvRows: CsvRow[];
  sniff: SniffReport | null;
  parseError: string | null;
  colMap: ColMap;
  gravityType: "g_raw" | "free_air_anomaly" | "bouguer_anomaly" | "complete_bouguer_anomaly";
  params: GravityCorrectionParams;
  nettleton: NettletonResult | null;
  nettletonLoading: boolean;
  nettletonError: string | null;
  previewStations: GravityCorrectedStation[] | null;
  previewOutputType: string;
  previewLoading: boolean;
  applyLoading: boolean;
  apiError: string | null;
};

type AsistenteAction =
  | { type: "CAMPO"; campo: keyof AsistenteState; valor: AsistenteState[keyof AsistenteState] }
  | { type: "CSV_PARSEADO"; headers: string[]; rows: CsvRow[]; sniff: SniffReport | null }
  | { type: "CSV_FALLO"; mensaje: string }
  | { type: "VISTA_PREVIA_PEDIDA" }
  | { type: "VISTA_PREVIA_OK"; estaciones: GravityCorrectedStation[]; tipoSalida: string }
  | { type: "VISTA_PREVIA_FALLO"; mensaje: string }
  | { type: "VISTA_PREVIA_DESCARTADA" }
  | { type: "NETTLETON_PEDIDO" }
  | { type: "NETTLETON_OK"; resultado: NettletonResult }
  | { type: "NETTLETON_FALLO"; mensaje: string }
  | { type: "APLICACION_PEDIDA" }
  | { type: "APLICACION_TERMINADA" }
  | { type: "OPERACION_FALLO"; mensaje: string }
  | { type: "ERROR_DESCARTADO" };

function asistenteReducer(estado: AsistenteState, accion: AsistenteAction): AsistenteState {
  switch (accion.type) {
    case "CAMPO":
      return { ...estado, [accion.campo]: accion.valor };
    case "CSV_PARSEADO":
      return { ...estado, csvHeaders: accion.headers, csvRows: accion.rows,
               sniff: accion.sniff, parseError: null };
    case "CSV_FALLO":
      return { ...estado, parseError: accion.mensaje };
    case "VISTA_PREVIA_PEDIDA":
      return { ...estado, previewLoading: true, apiError: null };
    case "VISTA_PREVIA_OK":
      // Avanzar al paso 4 va JUNTO a guardar el resultado: era la secuencia de
      // tres `setState` donde podía colarse un paso 4 con datos viejos.
      return { ...estado, previewLoading: false, previewStations: accion.estaciones,
               previewOutputType: accion.tipoSalida, step: 4, apiError: null };
    case "VISTA_PREVIA_FALLO":
      return { ...estado, previewLoading: false, apiError: accion.mensaje };
    case "VISTA_PREVIA_DESCARTADA":
      // Volver a tocar los parámetros invalida la vista previa que produjeron.
      return { ...estado, step: 3, previewStations: null, apiError: null };
    case "NETTLETON_PEDIDO":
      return { ...estado, nettletonLoading: true, nettletonError: null, nettleton: null };
    case "NETTLETON_OK":
      return { ...estado, nettletonLoading: false, nettleton: accion.resultado };
    case "NETTLETON_FALLO":
      return { ...estado, nettletonLoading: false, nettletonError: accion.mensaje };
    case "APLICACION_PEDIDA":
      return { ...estado, applyLoading: true, apiError: null };
    case "APLICACION_TERMINADA":
      return { ...estado, applyLoading: false };
    case "OPERACION_FALLO":
      return { ...estado, apiError: accion.mensaje };
    case "ERROR_DESCARTADO":
      return { ...estado, apiError: null };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}

export default function GravityCorrectionWizard({ file, onComplete, onCancel }: Props) {
  // ── FASE 10 (H-16) — 16 `useState` → una máquina con transiciones con nombre ──
  //
  // Un asistente por pasos es el caso de libro: `step` y los datos que cada paso
  // produce estaban sueltos, así que nada impedía llegar al paso 4 con la vista
  // previa del mapeo ANTERIOR. Ahora avanzar de paso y guardar lo que ese paso
  // produjo es una sola transición.
  const [ui, dispatch] = useReducer(asistenteReducer, {
    step: 1,
    csvHeaders: [], csvRows: [], sniff: null, parseError: null,
    colMap: {
    lat: "", lon: "", elev: "", g: "", id: "", time: "",
  },
    gravityType: "g_raw",
    params: {
    reduction_density_gcc: 2.67,
    dem_type: "COP30",
    terrain_radius_m: 22000,
    apply_lat_correction: true,
    apply_fac: true,
    apply_bouguer: true,
    apply_terrain: false,
    // F2B — pre-reducciones de campo (solo g_raw).
    apply_tide: false,
    apply_drift: false,
    drift_method: "linear",
    base_station_id: "",
  },
    nettleton: null, nettletonLoading: false, nettletonError: null,
    previewStations: null, previewOutputType: "", previewLoading: false,
    applyLoading: false, apiError: null,
  });
  const {
    step, csvHeaders, csvRows, sniff, parseError, colMap, gravityType, params,
    nettleton, nettletonLoading, nettletonError,
    previewStations, previewOutputType, previewLoading, applyLoading, apiError,
  } = ui;
  const setStep = (valor: 1 | 2 | 3 | 4) => dispatch({ type: "CAMPO", campo: "step", valor });
  const setColMap = (valor: ColMap) => dispatch({ type: "CAMPO", campo: "colMap", valor });
  const setGravityType = (valor: "g_raw" | "free_air_anomaly" | "bouguer_anomaly" | "complete_bouguer_anomaly") =>
    dispatch({ type: "CAMPO", campo: "gravityType", valor });
  const setParams = (valor: GravityCorrectionParams) =>
    dispatch({ type: "CAMPO", campo: "params", valor });
  const setApiError = (mensaje: string | null) =>
    dispatch(mensaje === null ? { type: "ERROR_DESCARTADO" } : { type: "OPERACION_FALLO", mensaje });
  // F2.5 (fix eslint react-hooks/set-state-in-effect): el conteo de estaciones
  // válidas es DERIVADO de rows+headers+mapa → useMemo, no estado + effect.
  const validStationCount = useMemo(
    () => (csvHeaders.length > 0 ? buildStations(csvRows, colMap).length : 0),
    [colMap, csvHeaders, csvRows]
  );

  // ─── Parse CSV on mount — EN EL BACKEND (F2, cierre de deuda) ────────────────
  // Antes: FileReader + split/parseFloat locales → con decimal-coma,
  // parseFloat("362472,4")=362472 EN SILENCIO (misma clase que e7d2858).
  // Ahora: POST parse-rows entrega filas canónicas del pipeline oficial.
  useEffect(() => {
    let cancelled = false;
    parseCsvRows({ file }).then((res) => {
      if (cancelled) return;
      if (!res.ok) {
        dispatch({ type: "CSV_FALLO", mensaje: res.error || "No se pudo parsear el CSV en el backend." });
        return;
      }
      if (res.headers.length === 0 || res.rows.length === 0) {
        dispatch({ type: "CSV_FALLO", mensaje: "El CSV no tiene columnas o filas legibles. Verifica el formato." });
        return;
      }
      dispatch({ type: "CSV_PARSEADO", headers: res.headers, rows: res.rows, sniff: res.sniffReport });
      const detected = {
        lat: detectColumn(res.headers, LAT_ALIASES),
        lon: detectColumn(res.headers, LON_ALIASES),
        elev: detectColumn(res.headers, ELEV_ALIASES),
        g: detectColumn(res.headers, G_ALIASES),
        id: detectColumn(res.headers, ID_ALIASES),
        time: detectColumn(res.headers, TIME_ALIASES),
      };
      setColMap(detected);
    });
    return () => {
      cancelled = true;
    };
  }, [file]);

  const canProceedStep1 = Boolean(colMap.lat && colMap.lon && colMap.g);

  function handleColSelect(field: keyof ColMap, value: string) {
    setColMap({ ...colMap, [field]: value });
  }

  // ─── Step 3 → 4: preview first 5 ────────────────────────────────────────────

  const handleStep3Continue = async () => {
    setApiError(null);
    const allStations = buildStations(csvRows, colMap);
    const preview = allStations.slice(0, 5);
    if (preview.length === 0) {
      setApiError("No se pudieron extraer estaciones válidas con el mapeo actual.");
      return;
    }
    dispatch({ type: "VISTA_PREVIA_PEDIDA" });
    const res = await applyGravityCorrections({
      stations: preview,
      params,
      gravity_column: "g_obs_mgal",
      gravity_type_in: gravityType,
    });
    if (!res.ok || !res.data) {
      dispatch({ type: "VISTA_PREVIA_FALLO", mensaje: res.error || "Error al calcular correcciones de vista previa." });
      return;
    }
    dispatch({ type: "VISTA_PREVIA_OK", estaciones: res.data.corrected,
               tipoSalida: res.data.output_gravity_type });
  };

  // ─── F2B: Nettleton (el barrido lo hace el backend) ──────────────────────────
  const handleNettleton = async () => {

    const stations = buildStations(csvRows, colMap);
    if (stations.length === 0) {
      dispatch({ type: "NETTLETON_FALLO", mensaje: "No hay estaciones válidas con el mapeo actual." });
      return;
    }
    dispatch({ type: "NETTLETON_PEDIDO" });
    const res = await nettletonAnalysis(stations);
    if (!res.ok || !res.data) {
      dispatch({ type: "NETTLETON_FALLO", mensaje: res.error ?? "No se pudo correr el análisis de Nettleton." });
      return;
    }
    dispatch({ type: "NETTLETON_OK", resultado: res.data });
  };

  // ─── Final apply ─────────────────────────────────────────────────────────────

  const handleApplyAll = async () => {
    setApiError(null);
    const allStations = buildStations(csvRows, colMap);
    if (allStations.length === 0) {
      setApiError("No hay estaciones válidas para procesar.");
      return;
    }
    dispatch({ type: "APLICACION_PEDIDA" });
    const res = await applyGravityCorrections({
      stations: allStations,
      params,
      gravity_column: "g_obs_mgal",
      gravity_type_in: gravityType,
    });
    dispatch({ type: "APLICACION_TERMINADA" });
    if (!res.ok || !res.data) {
      setApiError(res.error || "Error al aplicar correcciones a las estaciones.");
      return;
    }
    const { corrected, report, output_gravity_type } = res.data;
    const csvString = buildCorrectedCsv(corrected, output_gravity_type, report);
    const blob = new Blob([csvString], { type: "text/csv" });
    const correctedFile = new File([blob], `corrected_${file.name}`, { type: "text/csv" });
    onComplete(correctedFile, report);
  };

  // ─── Error state ─────────────────────────────────────────────────────────────

  if (parseError) {
    return (
      <div className="p-4 border border-red-600/40 bg-red-900/20 rounded text-[11px] text-red-400">
        {parseError}
        <button onClick={onCancel} className="ml-3 text-neutral-400 underline">
          Cancelar
        </button>
      </div>
    );
  }

  if (csvHeaders.length === 0) {
    return (
      <div className="p-4 text-[11px] text-neutral-500 animate-pulse">
        Leyendo archivo CSV...
      </div>
    );
  }

  // ─── Main render ─────────────────────────────────────────────────────────────

  const STEP_LABELS = [
    "Mapeo de columnas",
    "Tipo de dato",
    "Parámetros de reducción",
    "Vista previa y aplicar",
  ];

  return (
    <div className="border border-neutral-700/40 bg-neutral-900/60 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold">
            Correcciones Geofísicas de Gravedad
          </p>
          <p className="text-[12px] text-white font-semibold mt-0.5">
            Paso {step}/4 — {STEP_LABELS[step - 1]}
          </p>
        </div>
        <button
          onClick={onCancel}
          className="text-[10px] text-neutral-500 hover:text-neutral-300 px-2 py-1 border border-neutral-700/40 rounded shrink-0"
        >
          Cancelar
        </button>
      </div>

      {/* Progress bar */}
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((s) => (
          <div
            key={s}
            className={`h-0.5 flex-1 rounded-full transition-colors ${
              s <= step ? "bg-amber-500" : "bg-neutral-700"
            }`}
          />
        ))}
      </div>

      {/* ── STEP 1: Column mapping ── */}
      {step === 1 && (
        <div className="space-y-3">
          <p className="text-[10px] text-neutral-400">
            Se detectaron <span className="text-white">{csvHeaders.length}</span> columnas y{" "}
            <span className="text-white">{csvRows.length}</span> filas.{" "}
            {validStationCount < csvRows.length && (
              <span className="text-amber-400">
                ({validStationCount} filas con datos numéricos válidos)
              </span>
            )}
          </p>

          {/* F2 — formato detectado por el sniffer del backend (evidencia) */}
          {sniff && (
            <p className="text-[9px] font-mono text-neutral-500" title={sniff.separator.evidence}>
              Formato detectado: {sniff.encoding.value} · separador{" "}
              {sniff.separator.value === "\t" ? "tabulador" : `'${sniff.separator.value}'`} ·
              decimal {`'${sniff.decimal.value}'`}
              {sniff.preamble_count > 0 && ` · ${sniff.preamble_count} línea(s) de preámbulo omitidas`}
              {sniff.broken_row_count > 0 && (
                <span className="text-amber-400"> · {sniff.broken_row_count} fila(s) rotas omitidas</span>
              )}
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <ColSelect label="Latitud (°)" field="lat" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Longitud (°)" field="lon" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Elevación (m)" field="elev" required={false} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Gravedad observada" field="g" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="ID de estación" field="id" required={false} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Hora de lectura (UTC)" field="time" required={false} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
          </div>

          {!colMap.elev && (params.apply_fac || params.apply_bouguer || params.apply_terrain) && (
            <p className="text-[10px] text-amber-400 border border-amber-600/30 bg-amber-900/20 p-2 rounded">
              Sin elevación no se pueden calcular FAC, BC ni TC. Asigna la columna de elevación o
              deshabilita esas correcciones en el paso 3.
            </p>
          )}

          {!canProceedStep1 && (
            <p className="text-[10px] text-neutral-500">
              Latitud, Longitud y Gravedad son campos obligatorios.
            </p>
          )}

          <button
            onClick={() => setStep(2)}
            disabled={!canProceedStep1}
            className="px-3 py-1.5 text-[11px] rounded bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-semibold"
          >
            Siguiente →
          </button>
        </div>
      )}

      {/* ── STEP 2: Gravity type ── */}
      {step === 2 && (
        <div className="space-y-3">
          <p className="text-[10px] text-neutral-400">
            Indica qué correcciones ya están incluidas en los datos del CSV.
          </p>

          <div className="space-y-2">
            {GRAVITY_TYPE_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex gap-3 p-2.5 rounded border cursor-pointer transition-colors ${
                  gravityType === opt.value
                    ? "border-amber-500/60 bg-amber-900/20"
                    : "border-neutral-700/40 hover:border-neutral-600/60"
                }`}
              >
                <input
                  type="radio"
                  name="gravityType"
                  value={opt.value}
                  checked={gravityType === opt.value}
                  onChange={() => setGravityType(opt.value)}
                  className="mt-0.5 accent-amber-500 shrink-0"
                />
                <div>
                  <p className="text-[11px] text-white font-semibold">{opt.label}</p>
                  <p className="text-[10px] text-neutral-400 mt-0.5">{opt.desc}</p>
                </div>
              </label>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setStep(1)}
              className="px-3 py-1.5 text-[11px] rounded bg-neutral-700 hover:bg-neutral-600 text-white"
            >
              ← Atrás
            </button>
            <button
              onClick={() => setStep(3)}
              className="px-3 py-1.5 text-[11px] rounded bg-amber-600 hover:bg-amber-500 text-white font-semibold"
            >
              Siguiente →
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 3: Reduction params ── */}
      {step === 3 && (
        <div className="space-y-4">
          {/* F2B — pre-reducciones de CAMPO (solo lecturas crudas g_raw) */}
          {gravityType === "g_raw" && (
            <div className="p-3 border border-neutral-700/40 rounded space-y-2">
              <p className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold">
                Pre-reducciones de campo (lecturas crudas)
              </p>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(params.apply_tide)}
                  onChange={(e) => setParams({ ...params, apply_tide: e.target.checked })}
                  className="accent-amber-500"
                />
                <span className="text-[11px] text-neutral-300">
                  Marea terrestre (Longman 1959, offline) — requiere columna de hora
                </span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(params.apply_drift)}
                  onChange={(e) => setParams({ ...params, apply_drift: e.target.checked })}
                  className="accent-amber-500"
                />
                <span className="text-[11px] text-neutral-300">
                  Deriva instrumental (cierres a estación base) — requiere hora + base
                </span>
              </label>
              {(params.apply_tide || params.apply_drift) && !colMap.time && (
                <p className="text-[10px] text-amber-400 border border-amber-600/30 bg-amber-900/20 p-2 rounded">
                  Asigna la columna «Hora de lectura (UTC)» en el paso 1: sin la hora
                  el backend rechazará la corrección (no adivina).
                </p>
              )}
              {params.apply_drift && (
                <div className="pl-4 border-l border-neutral-700/40 space-y-2">
                  <div className="flex items-center gap-2">
                    <label className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold">
                      Método
                    </label>
                    <select
                      value={params.drift_method ?? "linear"}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          drift_method: e.target.value as "linear" | "piecewise",
                        })
                      }
                      className="bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1 text-[11px] text-white"
                    >
                      <option value="linear">Lineal (tasa única)</option>
                      <option value="piecewise">Por tramos (entre cierres)</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold">
                      ID estación base
                    </label>
                    <input
                      type="text"
                      value={params.base_station_id ?? ""}
                      onChange={(e) => setParams({ ...params, base_station_id: e.target.value })}
                      placeholder="ej. BASE"
                      className="w-32 bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1 text-[11px] text-white placeholder:text-neutral-600"
                    />
                    <span className="text-[9px] text-neutral-500">
                      Si lo dejas vacío, el backend te sugerirá la candidata detectada.
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Density */}
          <div>
            <label className="block text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-1">
              Densidad de reducción Bouguer [g/cm³]
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                step="0.01"
                min="1.5"
                max="4.0"
                value={params.reduction_density_gcc}
                onChange={(e) =>
                  setParams({
                    ...params,
                    reduction_density_gcc: parseFloat(e.target.value) || 2.67,
                  })
                }
                className="w-20 bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1 text-[11px] text-white focus:outline-none"
              />
              <span className="text-[10px] text-neutral-500">
                Estándar: 2.67 g/cm³ (corteza continental). Chile andino volcánico: 2.70–2.80.
              </span>
            </div>

            {/* F2B — Nettleton: el backend barre densidades; el usuario CONFIRMA */}
            <div className="mt-2 space-y-2">
              <button
                type="button"
                onClick={handleNettleton}
                disabled={nettletonLoading || !colMap.elev}
                className="px-2 py-1 text-[10px] rounded border border-neutral-600 text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
              >
                {nettletonLoading ? "Analizando…" : "Sugerir densidad (Nettleton)"}
              </button>
              {!colMap.elev && (
                <span className="ml-2 text-[9px] text-neutral-500">
                  Requiere columna de elevación (paso 1).
                </span>
              )}
              {nettletonError && (
                <p className="text-[10px] text-red-400">{nettletonError}</p>
              )}
              {nettleton && (
                <div className="p-2 border border-neutral-700/40 rounded space-y-1">
                  <NettletonSweepChart result={nettleton} />
                  <p className="text-[10px] text-neutral-300">
                    Óptima: <span className="text-amber-400 font-bold">
                      {nettleton.best_density_gcc.toFixed(2)} g/cm³
                    </span>{" "}
                    (correlación Bouguer-topografía r={nettleton.best_r.toFixed(3)})
                  </p>
                  {nettleton.warning && (
                    <p className="text-[9px] text-amber-400">{nettleton.warning}</p>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      setParams({
                        ...params,
                        reduction_density_gcc: Number(
                          nettleton.best_density_gcc.toFixed(2)
                        ),
                      })
                    }
                    className="px-2 py-1 text-[10px] rounded bg-amber-600 hover:bg-amber-500 text-white font-semibold"
                  >
                    Usar {nettleton.best_density_gcc.toFixed(2)} g/cm³
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Correction toggles */}
          <div>
            <p className="text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-2">
              Correcciones a aplicar
            </p>
            <div className="space-y-2">
              {(
                [
                  {
                    key: "apply_lat_correction" as const,
                    label: "Gravedad normal GRS80 (corrección de latitud)",
                  },
                  { key: "apply_fac" as const, label: "Corrección Free-Air (FAC) — 0.3087 mGal/m" },
                  {
                    key: "apply_bouguer" as const,
                    label: "Corrección Bouguer simple (BC) — placa infinita",
                  },
                ] as const
              ).map(({ key, label }) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={params[key] as boolean}
                    onChange={(e) => setParams({ ...params, [key]: e.target.checked })}
                    className="accent-amber-500"
                  />
                  <span className="text-[11px] text-neutral-300">{label}</span>
                </label>
              ))}

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.apply_terrain}
                  onChange={(e) => setParams({ ...params, apply_terrain: e.target.checked })}
                  className="accent-amber-500"
                />
                <span className="text-[11px] text-neutral-300">
                  Corrección de Terreno (TC) — requiere{" "}
                  <span className="font-mono text-amber-400 text-[10px]">OPENTOPO_API_KEY</span>
                </span>
              </label>
            </div>
          </div>

          {/* TC options */}
          {params.apply_terrain && (
            <div className="pl-4 border-l border-neutral-700/40 space-y-3">
              <div className="p-2 border border-amber-600/30 bg-amber-900/20 rounded text-[10px] text-amber-400">
                La corrección de terreno descarga un DEM de OpenTopography (200 llamadas/día en
                cuenta académica). Requiere que el servidor tenga{" "}
                <span className="font-mono">OPENTOPO_API_KEY</span> configurado.
              </div>

              <div>
                <label className="block text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-1">
                  Tipo de DEM
                </label>
                <select
                  value={params.dem_type}
                  onChange={(e) =>
                    setParams({
                      ...params,
                      dem_type: e.target.value as GravityCorrectionParams["dem_type"],
                    })
                  }
                  className="bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1.5 text-[11px] text-white focus:outline-none"
                >
                  <option value="COP30">COP30 — Copernicus GLO-30 30m (recomendado)</option>
                  <option value="SRTM30">SRTM30 — 30m global</option>
                  <option value="SRTM90">SRTM90 — 90m global, más rápido</option>
                  <option value="ALOS">ALOS — AW3D30 30m, mejor en zonas forestadas</option>
                  <option value="NASADEM">NASADEM — SRTM reprocesado mejorado</option>
                </select>
              </div>

              <div>
                <label className="block text-[9px] uppercase tracking-widest text-neutral-400 font-bold mb-1">
                  Radio de integración [m]
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    step="1000"
                    min="1000"
                    max="200000"
                    value={params.terrain_radius_m}
                    onChange={(e) =>
                      setParams({
                        ...params,
                        terrain_radius_m: parseFloat(e.target.value) || 22000,
                      })
                    }
                    className="w-24 bg-neutral-800 border border-neutral-600/40 rounded px-2 py-1 text-[11px] text-white focus:outline-none"
                  />
                  <span className="text-[10px] text-neutral-500">
                    Hammer zones A-M = 22,000 m (estándar exploración)
                  </span>
                </div>
              </div>
            </div>
          )}

          {apiError && (
            <p className="text-[10px] text-red-400 border border-red-600/30 bg-red-900/20 p-2 rounded">
              {apiError}
            </p>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => setStep(2)}
              className="px-3 py-1.5 text-[11px] rounded bg-neutral-700 hover:bg-neutral-600 text-white"
            >
              ← Atrás
            </button>
            <button
              onClick={handleStep3Continue}
              disabled={previewLoading}
              className="px-3 py-1.5 text-[11px] rounded bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-semibold"
            >
              {previewLoading ? "Calculando vista previa..." : "Ver vista previa →"}
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 4: Preview + Apply ── */}
      {step === 4 && previewStations && (
        <div className="space-y-4">
          <div>
            <p className="text-[10px] text-neutral-400 mb-1">
              Vista previa — primeras {previewStations.length} estaciones. Tipo de salida:{" "}
              <span className="font-mono text-amber-400">{previewOutputType}</span>
            </p>

            <div className="overflow-x-auto border border-neutral-800 rounded">
              <table className="w-full text-[10px] font-mono border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900">
                    <th className="text-left text-neutral-500 py-1.5 px-2">Estación</th>
                    <th className="text-right text-neutral-500 py-1.5 px-2">g_obs</th>
                    {previewStations[0]?.gamma_mgal !== null && (
                      <th className="text-right text-neutral-500 py-1.5 px-2">−γ</th>
                    )}
                    {previewStations[0]?.fac_mgal !== null && (
                      <th className="text-right text-neutral-500 py-1.5 px-2">+FAC</th>
                    )}
                    {previewStations[0]?.bc_mgal !== null && (
                      <th className="text-right text-neutral-500 py-1.5 px-2">−BC</th>
                    )}
                    {previewStations[0]?.tc_mgal !== null && (
                      <th className="text-right text-neutral-500 py-1.5 px-2">+TC</th>
                    )}
                    <th className="text-right text-amber-400 py-1.5 px-2">g_out</th>
                  </tr>
                </thead>
                <tbody>
                  {previewStations.map((s) => (
                    <tr
                      key={s.station_id}
                      className="border-b border-neutral-800/60 hover:bg-neutral-800/30"
                    >
                      <td className="py-1 px-2 text-neutral-400 max-w-[80px] truncate">
                        {s.station_id}
                      </td>
                      <td className="py-1 px-2 text-right text-neutral-300">
                        {s.g_obs_mgal.toFixed(3)}
                      </td>
                      {s.gamma_mgal !== null && (
                        <td className="py-1 px-2 text-right text-neutral-500">
                          {(-s.gamma_mgal).toFixed(3)}
                        </td>
                      )}
                      {s.fac_mgal !== null && (
                        <td className="py-1 px-2 text-right text-green-400/80">
                          {s.fac_mgal.toFixed(3)}
                        </td>
                      )}
                      {s.bc_mgal !== null && (
                        <td className="py-1 px-2 text-right text-orange-400/80">
                          {(-s.bc_mgal).toFixed(3)}
                        </td>
                      )}
                      {s.tc_mgal !== null && (
                        <td className="py-1 px-2 text-right text-blue-400/80">
                          {s.tc_mgal.toFixed(4)}
                        </td>
                      )}
                      <td className="py-1 px-2 text-right font-bold text-amber-400">
                        {s.g_bouguer_mgal.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[9px] text-neutral-600 mt-1">Valores en mGal.</p>
          </div>

          {apiError && (
            <p className="text-[10px] text-red-400 border border-red-600/30 bg-red-900/20 p-2 rounded">
              {apiError}
            </p>
          )}

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => {
                dispatch({ type: "VISTA_PREVIA_DESCARTADA" });
              }}
              disabled={applyLoading}
              className="px-3 py-1.5 text-[11px] rounded bg-neutral-700 hover:bg-neutral-600 disabled:opacity-50 text-white"
            >
              ← Atrás
            </button>
            <button
              onClick={handleApplyAll}
              disabled={applyLoading}
              className="px-3 py-1.5 text-[11px] rounded bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-semibold"
            >
              {applyLoading
                ? `Aplicando correcciones (${validStationCount} est.)...`
                : `Aplicar a ${validStationCount} estaciones`}
            </button>
          </div>

          {applyLoading && params.apply_terrain && (
            <p className="text-[10px] text-neutral-500 italic">
              Descargando DEM de OpenTopography y calculando TC por estación. Esto puede tardar
              30–60 segundos...
            </p>
          )}
        </div>
      )}
    </div>
  );
}
