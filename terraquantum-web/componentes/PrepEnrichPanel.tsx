"use client";

import React, { useMemo, useState } from "react";

import {
  enrichPackage,
  analyzeColumns,
  type BuildPackageConfig,
  type ColumnMappingPlan,
  type EnrichmentStep,
  type EnrichmentSummary,
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
    const primary = primaryFile as File;
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
        file: primary,
        magneticFile: isMagOnly ? null : magFile,
        dataType,
        config,
        boreholes: boreholes ?? null,
        columnMap: Object.keys(map).length > 0 ? map : null,
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

const GRAVITY_UNITS = ["mGal", "µGal", "m/s2"];
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

const NEEDS_CONTEXT_LABEL: Record<string, string> = {
  utm_zone: "Zona UTM del survey (para georreferenciar y muestrear el DEM).",
  survey_date:
    "Fecha del survey (año o ISO) — para derivar el IGRF offline en magnetometría.",
  opentopo_api_key:
    "Clave OPENTOPO_API_KEY en el backend (para descargar el DEM y completar la elevación).",
};
