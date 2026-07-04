"use client";

import { useState, useEffect, useMemo } from "react";
import {
  applyGravityCorrections,
  GravityCorrectionParams,
  GravityCorrectedStation,
  GravityCorrectionReport,
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

function detectColumn(headers: string[], aliases: Set<string>): string {
  for (const h of headers) {
    if (aliases.has(h.toLowerCase().trim())) return h;
  }
  return "";
}

// ─── CSV parsing ─────────────────────────────────────────────────────────────

function parseCsvText(text: string): {
  headers: string[];
  rows: string[][];
  separator: string;
} {
  const rawLines = text
    .split(/\r?\n/)
    .filter((l) => l.trim() && !l.trim().startsWith("#"));
  if (rawLines.length === 0) return { headers: [], rows: [], separator: "," };

  const headerLine = rawLines[0];
  const sep = headerLine.includes(";") ? ";" : ",";
  const parseRow = (line: string) =>
    line.split(sep).map((v) => v.trim().replace(/^"(.*)"$/, "$1"));

  return {
    headers: parseRow(headerLine),
    rows: rawLines.slice(1).map(parseRow),
    separator: sep,
  };
}

type ColMap = { lat: string; lon: string; elev: string; g: string; id: string };

function buildStations(
  rows: string[][],
  headers: string[],
  colMap: ColMap
): Record<string, number | string>[] {
  const idx = (col: string) => (col ? headers.indexOf(col) : -1);
  const latIdx = idx(colMap.lat);
  const lonIdx = idx(colMap.lon);
  const elevIdx = idx(colMap.elev);
  const gIdx = idx(colMap.g);
  const idIdx = idx(colMap.id);

  const result: Record<string, number | string>[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const lat = latIdx >= 0 ? parseFloat(row[latIdx] ?? "") : NaN;
    const lon = lonIdx >= 0 ? parseFloat(row[lonIdx] ?? "") : NaN;
    const g = gIdx >= 0 ? parseFloat(row[gIdx] ?? "") : NaN;
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(g)) continue;

    const station: Record<string, number | string> = {
      station_id:
        idIdx >= 0 && row[idIdx]?.trim()
          ? row[idIdx].trim()
          : `ST_${String(i).padStart(6, "0")}`,
      lat_deg: lat,
      lon_deg: lon,
      g_obs_mgal: g,
    };
    if (elevIdx >= 0 && row[elevIdx]) {
      const elev = parseFloat(row[elevIdx]);
      if (Number.isFinite(elev)) station.elev_m = elev;
    }
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

export default function GravityCorrectionWizard({ file, onComplete, onCancel }: Props) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [colMap, setColMap] = useState<ColMap>({ lat: "", lon: "", elev: "", g: "", id: "" });
  const [gravityType, setGravityType] = useState<
    "g_raw" | "free_air_anomaly" | "bouguer_anomaly" | "complete_bouguer_anomaly"
  >("g_raw");
  const [params, setParams] = useState<GravityCorrectionParams>({
    reduction_density_gcc: 2.67,
    dem_type: "COP30",
    terrain_radius_m: 22000,
    apply_lat_correction: true,
    apply_fac: true,
    apply_bouguer: true,
    apply_terrain: false,
  });

  const [previewStations, setPreviewStations] = useState<GravityCorrectedStation[] | null>(null);
  const [previewOutputType, setPreviewOutputType] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  // F2.5 (fix eslint react-hooks/set-state-in-effect): el conteo de estaciones
  // válidas es DERIVADO de rows+headers+mapa → useMemo, no estado + effect.
  const validStationCount = useMemo(
    () =>
      csvHeaders.length > 0
        ? buildStations(csvRows, csvHeaders, colMap).length
        : 0,
    [colMap, csvHeaders, csvRows]
  );

  // ─── Parse CSV on mount ──────────────────────────────────────────────────────

  useEffect(() => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = (e.target?.result as string) || "";
      const { headers, rows } = parseCsvText(text);
      if (headers.length === 0) {
        setParseError("No se pudo parsear el CSV. Verifica el formato del archivo.");
        return;
      }
      setCsvHeaders(headers);
      setCsvRows(rows);
      const detected = {
        lat: detectColumn(headers, LAT_ALIASES),
        lon: detectColumn(headers, LON_ALIASES),
        elev: detectColumn(headers, ELEV_ALIASES),
        g: detectColumn(headers, G_ALIASES),
        id: detectColumn(headers, ID_ALIASES),
      };
      setColMap(detected);
    };
    reader.onerror = () => setParseError("Error al leer el archivo CSV.");
    reader.readAsText(file);
  }, [file]);

  const canProceedStep1 = Boolean(colMap.lat && colMap.lon && colMap.g);

  function handleColSelect(field: keyof ColMap, value: string) {
    setColMap({ ...colMap, [field]: value });
  }

  // ─── Step 3 → 4: preview first 5 ────────────────────────────────────────────

  const handleStep3Continue = async () => {
    setApiError(null);
    const allStations = buildStations(csvRows, csvHeaders, colMap);
    const preview = allStations.slice(0, 5);
    if (preview.length === 0) {
      setApiError("No se pudieron extraer estaciones válidas con el mapeo actual.");
      return;
    }
    setPreviewLoading(true);
    const res = await applyGravityCorrections({
      stations: preview,
      params,
      gravity_column: "g_obs_mgal",
      gravity_type_in: gravityType,
    });
    setPreviewLoading(false);
    if (!res.ok || !res.data) {
      setApiError(res.error || "Error al calcular correcciones de vista previa.");
      return;
    }
    setPreviewStations(res.data.corrected);
    setPreviewOutputType(res.data.output_gravity_type);
    setStep(4);
  };

  // ─── Final apply ─────────────────────────────────────────────────────────────

  const handleApplyAll = async () => {
    setApiError(null);
    const allStations = buildStations(csvRows, csvHeaders, colMap);
    if (allStations.length === 0) {
      setApiError("No hay estaciones válidas para procesar.");
      return;
    }
    setApplyLoading(true);
    const res = await applyGravityCorrections({
      stations: allStations,
      params,
      gravity_column: "g_obs_mgal",
      gravity_type_in: gravityType,
    });
    setApplyLoading(false);
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

          <div className="grid grid-cols-2 gap-3">
            <ColSelect label="Latitud (°)" field="lat" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Longitud (°)" field="lon" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Elevación (m)" field="elev" required={false} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="Gravedad observada" field="g" required={true} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
            <ColSelect label="ID de estación" field="id" required={false} colMap={colMap} csvHeaders={csvHeaders} onSelect={handleColSelect} />
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
                setStep(3);
                setPreviewStations(null);
                setApiError(null);
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
