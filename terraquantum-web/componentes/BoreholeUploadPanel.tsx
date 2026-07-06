"use client";

// FASE 20 — Panel de carga y visualización de sondajes.
// Sube un CSV de sondajes, lo envía al backend para parsear/validar (unidades,
// columnas, litología) y muestra: resumen, tabla de preview y un mapa en planta
// (x–z) con los collares coloreados por litología, junto a los sensores de
// gravimetría si se proveen. NO calcula física ni parsea en el cliente: consume
// el endpoint /api/borehole/parse (Regla de Oro).

import { useMemo, useRef, useState } from "react";
import {
  parseBoreholeCsvFile,
  boreholeSurveyToIntervals,
  type BoreholeSurvey,
  type ParseBoreholeCsvResponse,
} from "../lib/terraquantum/frontendApi";

type SensorXZ = { x_m: number; z_m: number };

type Props = {
  /** Sensores de gravimetría (x,z) para superponer en el mapa. Opcional. */
  sensors?: SensorXZ[];
  /** Se invoca cuando el usuario confirma un survey válido. */
  onConfirm?: (
    survey: BoreholeSurvey,
    intervals: ReturnType<typeof boreholeSurveyToIntervals>
  ) => void;
};

// Paleta determinista por litología (solo visual). Las claves cubren es/en.
const LITHO_COLORS: Record<string, string> = {
  granite: "#e8b04b", granito: "#e8b04b",
  granodiorite: "#d99a3a", granodiorita: "#d99a3a",
  rhyolite: "#f0c987", riolita: "#f0c987",
  diorite: "#7fb069", diorita: "#7fb069",
  andesite: "#5f8d4e", andesita: "#5f8d4e",
  basalt: "#3a6b35", basalto: "#3a6b35",
  gabbro: "#2d5a27", gabro: "#2d5a27",
  sandstone: "#e0d6b3", arenisca: "#e0d6b3",
  limestone: "#cdd5c0", caliza: "#cdd5c0",
  magnetite: "#b23a48", magnetita: "#b23a48",
  hematite: "#8c1c13", hematita: "#8c1c13",
  pyrite: "#caa42a", pirita: "#caa42a",
  chalcopyrite: "#d98e04", calcopirita: "#d98e04",
  chromite: "#6b4226", cromita: "#6b4226",
};
const FALLBACK_PALETTE = [
  "#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444",
  "#a855f7", "#84cc16", "#ec4899", "#22d3ee", "#f97316",
];

function colorForLithology(litho: string | null, fallbackIndex: number): string {
  if (!litho) return "#94a3b8"; // gris para sin-litología
  const key = litho.trim().toLowerCase();
  if (LITHO_COLORS[key]) return LITHO_COLORS[key];
  for (const name of Object.keys(LITHO_COLORS)) {
    if (key.includes(name)) return LITHO_COLORS[name];
  }
  return FALLBACK_PALETTE[fallbackIndex % FALLBACK_PALETTE.length];
}

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export default function BoreholeUploadPanel({ sensors, onConfirm }: Props) {
  // F2B — el archivo viaja como BYTES (multipart): el sniffer del backend
  // decide el encoding. Antes: FileReader.readAsText forzaba UTF-8 y un CSV
  // latin-1 con ñ en litologías llegaba mojibake.
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [units, setUnits] = useState<"m" | "ft" | "auto">("m");
  const [crs, setCrs] = useState<string>("local");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ParseBoreholeCsvResponse | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const readFile = (file: File) => {
    setFileName(file.name);
    setCsvFile(file);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) readFile(file);
  };

  const handleParse = async () => {
    setError(null);
    setResult(null);
    if (!csvFile) {
      setError("Carga un archivo CSV de sondajes primero.");
      return;
    }
    setLoading(true);
    const res = await parseBoreholeCsvFile({ file: csvFile, lengthUnits: units, crs });
    setLoading(false);
    if (!res.ok || !res.data) {
      setError(res.error ?? "No se pudo parsear el CSV de sondajes.");
      return;
    }
    setResult(res.data);
  };

  const survey = result?.survey ?? null;

  // Mapa de color por litología (orden estable de aparición).
  const lithoColorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (!survey) return map;
    let idx = 0;
    for (const h of survey.holes) {
      const key = (h.lithology ?? "").trim().toLowerCase();
      if (!map.has(key)) {
        map.set(key, colorForLithology(h.lithology, idx));
        idx += 1;
      }
    }
    return map;
  }, [survey]);

  // Geometría del mapa en planta (x horizontal, z vertical).
  const plan = useMemo(() => {
    if (!survey || survey.holes.length === 0) return null;
    const xs = survey.holes.map((h) => h.x_m);
    const zs = survey.holes.map((h) => h.z_m);
    if (sensors) {
      for (const s of sensors) { xs.push(s.x_m); zs.push(s.z_m); }
    }
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minZ = Math.min(...zs), maxZ = Math.max(...zs);
    const padX = (maxX - minX) * 0.08 || 10;
    const padZ = (maxZ - minZ) * 0.08 || 10;
    return { minX: minX - padX, maxX: maxX + padX, minZ: minZ - padZ, maxZ: maxZ + padZ };
  }, [survey, sensors]);

  const W = 360, H = 260;
  const toPx = (x: number, z: number) => {
    if (!plan) return { px: 0, py: 0 };
    const px = ((x - plan.minX) / (plan.maxX - plan.minX || 1)) * W;
    // z hacia arriba: invertir eje vertical
    const py = H - ((z - plan.minZ) / (plan.maxZ - plan.minZ || 1)) * H;
    return { px, py };
  };

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-700 bg-slate-900/60 p-4 text-slate-200">
      <div>
        <h3 className="text-base font-semibold text-slate-100">Sondajes (Fase 20)</h3>
        <p className="text-xs text-slate-400">
          Carga un CSV de sondajes para anclar la inversión y validar el modelo
          contra densidades medidas.
        </p>
      </div>

      {/* Zona de carga */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-6 text-center transition-colors ${
          dragOver ? "border-indigo-400 bg-indigo-500/10" : "border-slate-600 hover:border-slate-500"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); }}
        />
        <span className="text-sm text-slate-300">
          {fileName ? `📄 ${fileName}` : "Arrastra un CSV de sondajes aquí o haz clic"}
        </span>
        <span className="mt-1 text-[11px] text-slate-500">
          Columnas: hole_id, x/easting, z/northing, depth_from, depth_to, density, lithology
        </span>
      </div>

      {/* Controles */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-slate-400">
          Unidades de longitud
          <select
            value={units}
            onChange={(e) => setUnits(e.target.value as "m" | "ft" | "auto")}
            className="mt-1 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100"
          >
            <option value="m">Metros</option>
            <option value="ft">Pies</option>
            <option value="auto">Auto-detectar</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-slate-400">
          CRS
          <input
            value={crs}
            onChange={(e) => setCrs(e.target.value)}
            placeholder="local / UTM 19S"
            className="mt-1 w-32 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100"
          />
        </label>
        <button
          onClick={handleParse}
          disabled={loading || !csvFile}
          className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {loading ? "Validando…" : "Validar sondajes"}
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      {result && survey && (
        <div className="flex flex-col gap-4">
          {/* Resumen */}
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            <Stat label="Sondajes" value={String(result.n_holes)} />
            <Stat label="Muestras/tramos" value={String(result.n_samples)} />
            <Stat label="Con densidad" value={String(result.n_with_density)} />
            <Stat label="Con susceptibilidad" value={String(result.n_with_susceptibility)} />
            <Stat label="Con litología" value={String(result.n_with_lithology)} />
            <Stat label="Litologías" value={String(result.lithologies_detected.length)} />
          </div>

          {result.unrecognized_lithologies.length > 0 && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
              Litologías no reconocidas (sin prior petrofísico):{" "}
              {result.unrecognized_lithologies.join(", ")}
            </div>
          )}

          {/* Mapa en planta + leyenda */}
          {plan && (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
              <svg
                width={W}
                height={H}
                className="rounded border border-slate-700 bg-slate-950"
                role="img"
                aria-label="Mapa en planta de sondajes y sensores"
              >
                {sensors?.map((s, i) => {
                  const { px, py } = toPx(s.x_m, s.z_m);
                  return (
                    <rect
                      key={`s-${i}`}
                      x={px - 2.5}
                      y={py - 2.5}
                      width={5}
                      height={5}
                      fill="none"
                      stroke="#64748b"
                      strokeWidth={1}
                    />
                  );
                })}
                {survey.holes.map((h, i) => {
                  const { px, py } = toPx(h.x_m, h.z_m);
                  const key = (h.lithology ?? "").trim().toLowerCase();
                  const color = lithoColorMap.get(key) ?? "#94a3b8";
                  return (
                    <circle
                      key={`h-${i}`}
                      cx={px}
                      cy={py}
                      r={5}
                      fill={color}
                      stroke="#0f172a"
                      strokeWidth={1}
                    >
                      <title>
                        {h.hole_id} · {h.lithology ?? "sin litología"} · ρ=
                        {fmt(h.density_t_m3)} t/m³ · {fmt(h.depth_from_m, 0)}–
                        {fmt(h.depth_to_m, 0)} m
                      </title>
                    </circle>
                  );
                })}
              </svg>

              <div className="flex flex-col gap-1 text-[11px]">
                <span className="font-medium text-slate-300">Leyenda</span>
                {Array.from(lithoColorMap.entries()).map(([key, color]) => (
                  <div key={key} className="flex items-center gap-1.5">
                    <span
                      className="inline-block h-3 w-3 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    <span className="text-slate-300">{key || "sin litología"}</span>
                  </div>
                ))}
                {sensors && sensors.length > 0 && (
                  <div className="mt-1 flex items-center gap-1.5">
                    <span className="inline-block h-3 w-3 border border-slate-500" />
                    <span className="text-slate-400">sensores gravimetría</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Tabla de preview */}
          <div className="max-h-56 overflow-auto rounded border border-slate-700">
            <table className="w-full text-left text-[11px]">
              <thead className="sticky top-0 bg-slate-800 text-slate-300">
                <tr>
                  <th className="px-2 py-1">Sondaje</th>
                  <th className="px-2 py-1">x</th>
                  <th className="px-2 py-1">z</th>
                  <th className="px-2 py-1">Desde</th>
                  <th className="px-2 py-1">Hasta</th>
                  <th className="px-2 py-1">ρ (t/m³)</th>
                  <th className="px-2 py-1">Litología</th>
                  <th className="px-2 py-1">Tipo</th>
                </tr>
              </thead>
              <tbody>
                {survey.holes.slice(0, 50).map((h, i) => (
                  <tr key={i} className="odd:bg-slate-900/40">
                    <td className="px-2 py-1 font-medium text-slate-200">{h.hole_id}</td>
                    <td className="px-2 py-1">{fmt(h.x_m, 1)}</td>
                    <td className="px-2 py-1">{fmt(h.z_m, 1)}</td>
                    <td className="px-2 py-1">{fmt(h.depth_from_m, 1)}</td>
                    <td className="px-2 py-1">{fmt(h.depth_to_m, 1)}</td>
                    <td className="px-2 py-1">{fmt(h.density_t_m3)}</td>
                    <td className="px-2 py-1">{h.lithology ?? "—"}</td>
                    <td className="px-2 py-1 text-slate-400">{h.sample_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {survey.holes.length > 50 && (
              <div className="bg-slate-800 px-2 py-1 text-[10px] text-slate-400">
                Mostrando 50 de {survey.holes.length} tramos.
              </div>
            )}
          </div>

          {onConfirm && (
            <button
              onClick={() => onConfirm(survey, boreholeSurveyToIntervals(survey))}
              disabled={result.n_with_density === 0 && result.n_with_susceptibility === 0}
              className="self-start rounded bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
              title={
                result.n_with_density === 0 && result.n_with_susceptibility === 0
                  ? "Ningún tramo tiene densidad o susceptibilidad: no puede anclar la inversión."
                  : "Usar estos sondajes para anclar la inversión"
              }
            >
              ✓ Usar sondajes en la inversión
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-800/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}
