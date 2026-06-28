"use client";

import React, { useMemo, useState } from "react";

import {
  enrichPackage,
  analyzeColumns,
  type BuildPackageConfig,
  type ColumnMappingPlan,
  type EnrichmentStep,
  type EnrichmentSummary,
  type HelmertGeoref,
} from "../lib/terraquantum/frontendApi";

/**
 * PrepEnrichPanel — flujo SIMPLE de Preparación con enriquecimiento.
 *
 * El usuario sube gravimetría y/o magnetometría (+sondajes, vía `boreholeNode`),
 * opcionalmente declara el contexto del survey (zona UTM + gravímetro) y pulsa
 * «Generar CSV completo». El backend (/enrich-package) DERIVA con física real lo
 * que falte (DEM, correcciones, IGRF, coords, σ, calidad) y devuelve un CSV
 * descargable + un resumen de qué calculó. Este panel NO calcula física: solo
 * orquesta la subida, muestra el resumen y ofrece la descarga. Los parámetros de
 * inversión NO viven aquí (van en «Avanzado», colapsado en la vista).
 */

const GRAVIMETERS: { value: string; label: string }[] = [
  { value: "unknown", label: "Desconocido (σ adaptivo)" },
  { value: "scintrex_cg6", label: "Scintrex CG-6" },
  { value: "zls_burris", label: "ZLS Burris" },
  { value: "lacoste_romberg", label: "LaCoste & Romberg" },
];

const STATUS_META: Record<
  EnrichmentStep["status"],
  { label: string; classes: string }
> = {
  derived: { label: "Derivado", classes: "border-emerald-700 bg-emerald-950/40 text-emerald-300" },
  already_present: { label: "Ya presente", classes: "border-sky-800 bg-sky-950/40 text-sky-300" },
  skipped: { label: "No aplica", classes: "border-neutral-700 bg-neutral-900 text-neutral-400" },
  needs_context: { label: "Falta contexto", classes: "border-amber-700 bg-amber-950/40 text-amber-300" },
  not_derivable: { label: "No derivable", classes: "border-rose-800 bg-rose-950/40 text-rose-300" },
};

// FASE 19 (Caso B) — fila editable de punto de control (todo string en la UI).
type ControlPointRow = {
  localX: string;
  localY: string;
  realE: string;
  realN: string;
};

/** Filas completas y numéricas (las parciales/vacías se descartan). */
function validControlPoints(
  rows: ControlPointRow[]
): { local_x: number; local_z: number; real_e: number; real_n: number }[] {
  const out: { local_x: number; local_z: number; real_e: number; real_n: number }[] = [];
  for (const r of rows) {
    const lx = Number(r.localX);
    const lz = Number(r.localY);
    const e = Number(r.realE);
    const n = Number(r.realN);
    if (
      r.localX.trim() !== "" &&
      r.localY.trim() !== "" &&
      r.realE.trim() !== "" &&
      r.realN.trim() !== "" &&
      Number.isFinite(lx) &&
      Number.isFinite(lz) &&
      Number.isFinite(e) &&
      Number.isFinite(n)
    ) {
      out.push({ local_x: lx, local_z: lz, real_e: e, real_n: n });
    }
  }
  return out;
}

/** Serializa los puntos a helmert_control_points_json (null si <2 válidos o desactivado). */
function buildHelmertJson(enabled: boolean, rows: ControlPointRow[]): string | null {
  if (!enabled) return null;
  const pts = validControlPoints(rows);
  if (pts.length < 2) return null;
  return JSON.stringify({ points: pts });
}

type Props = {
  /** Intervalos de sondaje confirmados (se anexan al paquete como anclaje). */
  boreholes?: unknown[];
  /** Zona de carga de sondajes (BoreholeUploadPanel) renderizada por la vista. */
  boreholeNode?: React.ReactNode;
};

export default function PrepEnrichPanel({ boreholes, boreholeNode }: Props) {
  const [gravFile, setGravFile] = useState<File | null>(null);
  const [magFile, setMagFile] = useState<File | null>(null);

  const [utmZone, setUtmZone] = useState("");
  const [gravimeterType, setGravimeterType] = useState("unknown");
  const [surveyDate, setSurveyDate] = useState("");

  // FASE 19 (Caso B) — Puntos de control Helmert. SOLO para coords LOCALES: el
  // usuario activa la sección y declara ≥2 pares (x,y local ↔ E,N real). El front
  // NO calcula nada: solo recolecta los puntos; la transformada la resuelve el backend.
  const [useHelmert, setUseHelmert] = useState(false);
  const [ctrlPoints, setCtrlPoints] = useState<ControlPointRow[]>([
    { localX: "", localY: "", realE: "", realN: "" },
    { localX: "", localY: "", realE: "", realN: "" },
  ]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // PILAR 1 — MAPEO MANUAL de columnas. `mappingPlan` no-nulo → mostrar el paso de
  // mapeo; `columnMap` (rol → columna) se persiste y se envía en cada generación.
  const [mappingPlan, setMappingPlan] = useState<ColumnMappingPlan | null>(null);
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [result, setResult] = useState<
    | {
        filename: string;
        packageText: string;
        summary: EnrichmentSummary;
        warnings: string[];
        nStations: number;
      }
    | null
  >(null);

  const utmError = useMemo(() => {
    const raw = utmZone.trim();
    if (!raw) return null;
    return /^\s*\d{1,2}\s*[NnSs]\s*$/.test(raw)
      ? null
      : "Formato de zona UTM inválido. Usa por ejemplo «19S» o «33N».";
  }, [utmZone]);

  const canGenerate = (gravFile !== null || magFile !== null) && !loading && !utmError;

  // Tipo de dato primario: gravimetría manda; solo magnética → primario magnético.
  const isMagOnly = !gravFile && !!magFile;
  const primaryFile = gravFile ?? magFile;
  const dataType: "gravity" | "magnetic" = isMagOnly ? "magnetic" : "gravity";

  // PILAR 2 — combo explícito (sin parches frágiles): lo que se enviará por rol.
  const hasBoreholes = (boreholes?.length ?? 0) > 0;
  const comboLabel =
    !gravFile && !magFile
      ? null
      : (gravFile && magFile
          ? "Gravimetría + Magnetometría → inversión conjunta"
          : gravFile
            ? "Gravimetría sola"
            : "Magnetometría sola") +
        (hasBoreholes ? " + sondajes (anclaje)" : "");

  async function handleGenerate(mapOverride?: Record<string, string>) {
    setError(null);
    setResult(null);
    if (!gravFile && !magFile) {
      setError("Sube al menos un CSV (gravimetría y/o magnetometría).");
      return;
    }
    if (utmError) {
      setError(utmError);
      return;
    }
    const map = mapOverride ?? columnMap;

    const config: BuildPackageConfig = {
      region: "norte_chile",
      gravimeter_type: gravimeterType,
      utm_zone: utmZone.trim() ? utmZone.trim().toUpperCase() : null,
      survey_date: surveyDate.trim() || null,
    };

    setLoading(true);
    try {
      const res = await enrichPackage({
        gravityFile: gravFile,
        magneticFile: magFile,
        config,
        boreholes: boreholes ?? null,
        columnMap: Object.keys(map).length > 0 ? map : null,
        helmertControlPointsJson: buildHelmertJson(useHelmert, ctrlPoints),
      });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      // El backend pide MAPEO: mostrar el paso y prellenar con lo auto-detectado.
      if (res.needsMapping) {
        setMappingPlan(res.mappingPlan);
        setColumnMap((prev) => prefillMap(res.mappingPlan, { ...prev, ...map }));
        setError(
          "No se reconocieron todas las columnas requeridas. Asigna los roles abajo y vuelve a generar."
        );
        return;
      }
      setMappingPlan(null);
      setResult({
        filename: res.filename,
        packageText: res.packageText,
        summary: res.summary,
        warnings: res.warnings,
        nStations: res.nStations,
      });
    } finally {
      setLoading(false);
    }
  }

  // Abrir el mapeo manual proactivamente (sin esperar a que el backend lo pida).
  async function handleOpenMapping() {
    setError(null);
    if (!primaryFile) {
      setError("Sube al menos un CSV para mapear sus columnas.");
      return;
    }
    setLoading(true);
    try {
      const res = await analyzeColumns({
        file: primaryFile,
        dataType,
        columnMap: Object.keys(columnMap).length > 0 ? columnMap : null,
      });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setMappingPlan(res.plan);
      setColumnMap((prev) => prefillMap(res.plan, prev));
    } finally {
      setLoading(false);
    }
  }

  function handleDownload() {
    if (!result) return;
    const blob = new Blob([result.packageText], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-col gap-6">
      {/* 3 zonas de carga (todas opcionales) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <UploadZone
          label="Gravimetría"
          hint="CSV gravimétrico (crudo o corregido)."
          file={gravFile}
          onChange={setGravFile}
        />
        <UploadZone
          label="Magnetometría"
          hint="CSV magnético (TMI nT). Co-localizado → inversión conjunta."
          file={magFile}
          onChange={setMagFile}
        />
        <div className="rounded-xl border border-neutral-800 bg-black/40 p-4">
          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2">
            Sondajes
          </div>
          {boreholeNode ?? (
            <p className="text-[11px] font-mono text-neutral-600 leading-5">
              Carga sondajes para anclar la inversión (opcional).
            </p>
          )}
        </div>
      </div>

      {/* Contexto del survey (entradas para el enriquecimiento, NO params) */}
      <div className="rounded-xl border border-neutral-800 bg-neutral-950/40 p-4">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-3">
          Contexto del survey · opcional
        </div>
        <p className="text-[11px] font-mono text-neutral-600 leading-5 mb-3">
          Ayuda al backend a georreferenciar y a fijar la incertidumbre. No son
          parámetros de inversión.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
              Zona UTM
            </label>
            <input
              type="text"
              value={utmZone}
              onChange={(e) => setUtmZone(e.target.value)}
              placeholder="ej. 19S"
              className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
            <p className="mt-1 text-[10px] font-mono text-neutral-600">
              Para derivar lat/lon y muestrear el DEM si falta elevación.
            </p>
            {utmError && (
              <p className="mt-1 text-[10px] font-mono text-amber-400">{utmError}</p>
            )}
          </div>
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
              Gravímetro
            </label>
            <select
              value={gravimeterType}
              onChange={(e) => setGravimeterType(e.target.value)}
              className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200"
            >
              {GRAVIMETERS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] font-mono text-neutral-600">
              Fija el piso de ruido (σ) por estación.
            </p>
          </div>
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
              Fecha del survey
            </label>
            <input
              type="text"
              value={surveyDate}
              onChange={(e) => setSurveyDate(e.target.value)}
              placeholder="ej. 2016 o 2016-07"
              className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
            <p className="mt-1 text-[10px] font-mono text-neutral-600">
              Para derivar el IGRF offline (magnetometría) en la ubicación + fecha.
            </p>
          </div>
        </div>
      </div>

      {/* FASE 19 (Caso B) — Puntos de control Helmert (solo coords locales) */}
      <HelmertControlSection
        enabled={useHelmert}
        rows={ctrlPoints}
        onToggle={setUseHelmert}
        onChange={setCtrlPoints}
      />

      {/* Combo detectado (PILAR 2) */}
      {comboLabel && (
        <div className="rounded-lg border border-sky-900/60 bg-sky-950/20 px-4 py-2 text-[11px] font-mono text-sky-300">
          Combo detectado: <span className="font-bold">{comboLabel}</span>
        </div>
      )}

      {/* Botones */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          onClick={() => handleGenerate()}
          disabled={!canGenerate}
          className="flex-1 rounded-xl py-4 text-sm font-black uppercase tracking-widest transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-[#C2D8C4] text-black hover:bg-white"
        >
          {loading ? "Enriqueciendo en el backend…" : "Generar CSV completo"}
        </button>
        <button
          type="button"
          onClick={handleOpenMapping}
          disabled={!primaryFile || loading}
          className="rounded-xl px-5 py-4 text-xs font-bold uppercase tracking-widest border border-neutral-700 text-neutral-300 hover:bg-neutral-900 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Mapear columnas
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-800 bg-rose-950/40 p-4 text-xs font-mono text-rose-300 leading-5">
          {error}
        </div>
      )}

      {mappingPlan && (
        <ColumnMappingStep
          plan={mappingPlan}
          columnMap={columnMap}
          dataType={dataType}
          loading={loading}
          onChange={setColumnMap}
          onApply={() => handleGenerate(columnMap)}
          onCancel={() => setMappingPlan(null)}
        />
      )}

      {result && (
        <ResultCard
          summary={result.summary}
          warnings={result.warnings}
          nStations={result.nStations}
          onDownload={handleDownload}
        />
      )}
    </div>
  );
}

// ── FASE 19 (Caso B) — Sección de puntos de control Helmert ──────────────────
function HelmertControlSection({
  enabled,
  rows,
  onToggle,
  onChange,
}: {
  enabled: boolean;
  rows: ControlPointRow[];
  onToggle: (v: boolean) => void;
  onChange: (rows: ControlPointRow[]) => void;
}) {
  const nValid = validControlPoints(rows).length;

  function setCell(idx: number, key: keyof ControlPointRow, value: string) {
    const next = rows.map((r, i) => (i === idx ? { ...r, [key]: value } : r));
    onChange(next);
  }
  function addRow() {
    onChange([...rows, { localX: "", localY: "", realE: "", realN: "" }]);
  }
  function removeRow(idx: number) {
    if (rows.length <= 2) return; // mínimo 2 para resolver Helmert
    onChange(rows.filter((_, i) => i !== idx));
  }

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950/40 p-4">
      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
          className="accent-[#C2D8C4]"
        />
        <span className="text-[10px] uppercase tracking-widest text-neutral-400">
          Georreferenciar coordenadas locales · opcional
        </span>
      </label>
      <p className="mt-2 text-[11px] font-mono text-neutral-600 leading-5">
        Solo si tu CSV usa coordenadas LOCALES (metros). Declara ≥2 puntos de control
        (x,y local ↔ Este,Norte real, en UTM). El backend resuelve la transformada de
        similitud (Helmert) y georreferencia las estaciones. Si tus coordenadas ya son
        lat/lon o UTM, deja esto desactivado.
      </p>

      {enabled && (
        <div className="mt-3 flex flex-col gap-2">
          <div className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 text-[9px] uppercase tracking-wider text-neutral-500">
            <span>X local</span>
            <span>Y local</span>
            <span>Este (E)</span>
            <span>Norte (N)</span>
            <span />
          </div>
          {rows.map((r, idx) => (
            <div key={idx} className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 items-center">
              <CoordInput value={r.localX} onChange={(v) => setCell(idx, "localX", v)} placeholder="0" />
              <CoordInput value={r.localY} onChange={(v) => setCell(idx, "localY", v)} placeholder="0" />
              <CoordInput value={r.realE} onChange={(v) => setCell(idx, "realE", v)} placeholder="500000" />
              <CoordInput value={r.realN} onChange={(v) => setCell(idx, "realN", v)} placeholder="7000000" />
              <button
                type="button"
                onClick={() => removeRow(idx)}
                disabled={rows.length <= 2}
                className="text-neutral-500 hover:text-rose-400 disabled:opacity-30 disabled:cursor-not-allowed text-xs px-2"
                title="Quitar punto"
              >
                ✕
              </button>
            </div>
          ))}
          <div className="flex items-center justify-between mt-1">
            <button
              type="button"
              onClick={addRow}
              className="text-[10px] uppercase tracking-widest text-[#C2D8C4] hover:text-white"
            >
              + Añadir punto
            </button>
            <span
              className={`text-[10px] font-mono ${
                nValid >= 2 ? "text-emerald-400" : "text-amber-400"
              }`}
            >
              {nValid} punto{nValid === 1 ? "" : "s"} válido{nValid === 1 ? "" : "s"}
              {nValid < 2 ? " (se necesitan ≥2)" : ""}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function CoordInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full bg-black/60 border border-neutral-700 rounded px-2 py-1.5 text-xs text-neutral-200 placeholder:text-neutral-600"
    />
  );
}

function UploadZone({
  label,
  hint,
  file,
  onChange,
}: {
  label: string;
  hint: string;
  file: File | null;
  onChange: (f: File | null) => void;
}) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-black/40 p-4">
      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2">
        {label}
      </div>
      <input
        type="file"
        accept=".csv"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        className="w-full max-w-full min-w-0 overflow-hidden text-xs text-neutral-400 file:mr-3 file:py-2 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-neutral-800 file:text-[#C2D8C4] hover:file:bg-neutral-700"
      />
      <p className="mt-2 text-[10px] font-mono text-neutral-600 leading-5">{hint}</p>
      {file && (
        <p className="mt-1 text-[10px] font-mono text-emerald-400 truncate">
          ✓ {file.name}
        </p>
      )}
    </div>
  );
}

function ResultCard({
  summary,
  warnings,
  nStations,
  onDownload,
}: {
  summary: EnrichmentSummary;
  warnings: string[];
  nStations: number;
  onDownload: () => void;
}) {
  return (
    <div className="rounded-2xl border border-emerald-900/60 bg-emerald-950/10 p-5 flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-lg font-black text-white">CSV completo listo</h3>
          <p className="text-[11px] font-mono text-neutral-500 mt-1">
            {nStations} estaciones · {summary.columns_added.length} columnas derivadas
          </p>
        </div>
        <button
          type="button"
          onClick={onDownload}
          className="rounded-lg px-5 py-3 text-xs font-black uppercase tracking-widest bg-[#C2D8C4] text-black hover:bg-white"
        >
          Descargar CSV completo
        </button>
      </div>

      {/* Qué calculé y agregué */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-3">
          Qué calculé y agregué
        </div>
        <ul className="flex flex-col gap-2">
          {summary.steps.map((s) => {
            const meta = STATUS_META[s.status];
            return (
              <li
                key={s.key}
                className="rounded-lg border border-neutral-800 bg-black/40 p-3 flex flex-col gap-1"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded border ${meta.classes}`}
                  >
                    {meta.label}
                  </span>
                  <span className="text-xs font-semibold text-neutral-200">
                    {s.label}
                  </span>
                  {s.method && (
                    <span className="text-[10px] font-mono text-neutral-600">
                      {s.method}
                    </span>
                  )}
                </div>
                {s.detail && (
                  <p className="text-[11px] font-mono text-neutral-500 leading-5">
                    {s.detail}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[10px] font-mono text-neutral-600">
          Nada se inventó: cada columna proviene de física/matemática real; lo no
          derivable queda fuera y marcado.
        </p>
      </div>

      {/* FASE 19 (Caso B) — resultado de la georef Helmert (si se aportaron puntos) */}
      {summary.helmert_georef && <HelmertResult georef={summary.helmert_georef} />}

      {summary.needs_context.length > 0 && (
        <div className="rounded-lg border border-amber-800 bg-amber-950/30 p-3">
          <div className="text-[10px] uppercase tracking-widest text-amber-400 mb-1">
            Falta contexto para derivar más
          </div>
          <ul className="list-disc list-inside text-[11px] font-mono text-amber-300/90 leading-5">
            {summary.needs_context.map((c) => (
              <li key={c}>{NEEDS_CONTEXT_LABEL[c] ?? c}</li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="rounded-lg border border-neutral-700 bg-neutral-900/40 p-3">
          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-1">
            Avisos del import
          </div>
          <ul className="list-disc list-inside text-[11px] font-mono text-neutral-400 leading-5">
            {warnings.slice(0, 8).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── PILAR 1 — Paso de MAPEO MANUAL de columnas ───────────────────────────────

/** Prefija el mapa con lo que el backend ya resolvió (las elecciones previas mandan). */
function prefillMap(
  plan: ColumnMappingPlan,
  existing: Record<string, string>
): Record<string, string> {
  const out: Record<string, string> = { ...existing };
  for (const role of [...plan.required_roles, ...plan.optional_roles]) {
    if (!out[role] && plan.roles[role]) out[role] = plan.roles[role] as string;
  }
  for (const k of ["unit", "coordinate_system"]) {
    if (!out[k] && plan.literals[k]) out[k] = plan.literals[k];
  }
  return out;
}

const GRAVITY_UNITS = ["mGal", "µGal", "Gal", "m/s2"];
const COORD_SYSTEMS: { value: string; label: string }[] = [
  { value: "", label: "(auto-detectar)" },
  { value: "latlon", label: "Lat/Lon (WGS84)" },
  { value: "utm", label: "UTM (este/norte)" },
  { value: "local", label: "Local (metros)" },
];

function ColumnMappingStep({
  plan,
  columnMap,
  dataType,
  loading,
  onChange,
  onApply,
  onCancel,
}: {
  plan: ColumnMappingPlan;
  columnMap: Record<string, string>;
  dataType: "gravity" | "magnetic";
  loading: boolean;
  onChange: (m: Record<string, string>) => void;
  onApply: () => void;
  onCancel: () => void;
}) {
  function setField(key: string, value: string) {
    const next = { ...columnMap };
    if (value) next[key] = value;
    else delete next[key];
    onChange(next);
  }

  const requiredOk = plan.required_roles.every((r) => columnMap[r]);
  const invalid = Object.entries(plan.invalid_overrides ?? {});

  return (
    <div className="rounded-2xl border border-amber-900/60 bg-amber-950/10 p-5 flex flex-col gap-5">
      <div>
        <h3 className="text-base font-black text-white">Mapeo manual de columnas</h3>
        <p className="text-[11px] font-mono text-neutral-500 mt-1 leading-5">
          Asigna qué columna del archivo cumple cada rol. Los roles con{" "}
          <span className="text-amber-400">*</span> son obligatorios. Nada se inventa:
          solo se re-etiquetan columnas que ya existen en tu CSV.
        </p>
      </div>

      {invalid.length > 0 && (
        <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-[11px] font-mono text-rose-300 leading-5">
          Columnas no encontradas en el archivo:{" "}
          {invalid.map(([role, col]) => `${role}="${col}"`).join(", ")}.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {plan.required_roles.map((role) => (
          <RoleSelect
            key={role}
            role={role}
            required
            label={plan.role_labels[role] ?? role}
            columns={plan.raw_columns}
            value={columnMap[role] ?? ""}
            onChange={(v) => setField(role, v)}
          />
        ))}
        {plan.optional_roles.map((role) => (
          <RoleSelect
            key={role}
            role={role}
            label={plan.role_labels[role] ?? role}
            columns={plan.raw_columns}
            value={columnMap[role] ?? ""}
            onChange={(v) => setField(role, v)}
          />
        ))}
      </div>

      {/* Literales (no son columnas): unidad gravimétrica + sistema de coordenadas */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {dataType === "gravity" && (
          <div>
            <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
              Unidad gravimétrica
            </label>
            <select
              value={columnMap.unit ?? ""}
              onChange={(e) => setField("unit", e.target.value)}
              className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200"
            >
              <option value="">(desde columna «unit» o nT)</option>
              {GRAVITY_UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] font-mono text-neutral-600">
              Úsala si el archivo no trae columna de unidad.
            </p>
          </div>
        )}
        <div>
          <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
            Sistema de coordenadas
          </label>
          <select
            value={columnMap.coordinate_system ?? ""}
            onChange={(e) => setField("coordinate_system", e.target.value)}
            className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200"
          >
            {COORD_SYSTEMS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          onClick={onApply}
          disabled={!requiredOk || loading}
          className="flex-1 rounded-xl py-3 text-xs font-black uppercase tracking-widest bg-[#C2D8C4] text-black hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? "Generando…" : "Aplicar mapeo y generar"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="rounded-xl px-5 py-3 text-xs font-bold uppercase tracking-widest border border-neutral-700 text-neutral-300 hover:bg-neutral-900 disabled:opacity-40"
        >
          Cerrar
        </button>
      </div>
      {!requiredOk && (
        <p className="text-[10px] font-mono text-amber-400">
          Asigna todos los roles obligatorios (*) para continuar.
        </p>
      )}
    </div>
  );
}

function RoleSelect({
  role,
  label,
  columns,
  value,
  onChange,
  required,
}: {
  role: string;
  label: string;
  columns: string[];
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
}) {
  return (
    <div>
      <label className="block text-[10px] uppercase text-neutral-500 tracking-widest mb-1">
        {label} {required && <span className="text-amber-400">*</span>}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-black/60 border border-neutral-700 rounded px-3 py-2 text-xs text-neutral-200"
        data-role={role}
      >
        <option value="">— sin asignar —</option>
        {columns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── FASE 19 (Caso B) — tarjeta de resultado Helmert dentro de «Qué calculé» ──
function HelmertResult({ georef }: { georef: HelmertGeoref }) {
  if (georef.skipped) {
    return (
      <div className="rounded-lg border border-neutral-700 bg-neutral-900/40 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-1">
          Georef Helmert
        </div>
        <p className="text-[11px] font-mono text-neutral-400 leading-5">
          No aplicada: {georef.reason}
        </p>
      </div>
    );
  }
  const rms = georef.transform?.residual_rms_m;
  const rmsLabel = typeof rms === "number" ? `${rms.toFixed(2)} m` : "—";
  return (
    <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3">
      <div className="text-[10px] uppercase tracking-widest text-emerald-400 mb-1">
        Georef Helmert aplicada
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] font-mono text-emerald-200/90 leading-5">
        <span>
          Confianza: <span className="font-bold">{georef.confidence}</span>
        </span>
        <span>
          Residual RMS: <span className="font-bold">{rmsLabel}</span>
        </span>
        <span>Estaciones georreferenciadas: {georef.n_stations}</span>
      </div>
      {georef.georeferenced_center && (
        <p className="mt-1 text-[10px] font-mono text-neutral-500">
          Centro (E,N): {georef.georeferenced_center.e.toFixed(1)},{" "}
          {georef.georeferenced_center.n.toFixed(1)}
        </p>
      )}
    </div>
  );
}

const NEEDS_CONTEXT_LABEL: Record<string, string> = {
  utm_zone: "Zona UTM del survey (para georreferenciar y muestrear el DEM).",
  survey_date:
    "Fecha del survey (año o ISO) — para derivar el IGRF offline en magnetometría.",
  opentopo_api_key:
    "Clave OPENTOPO_API_KEY en el backend (para descargar el DEM y completar la elevación).",
};
