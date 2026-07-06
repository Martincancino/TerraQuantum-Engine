"use client";

// F2B — "Sala de mapas": productos de gabinete en el dominio de la grilla.
// Separación regional-residual (gravedad/mag) y suite de realce magnético
// (RTP/1VD/THD/tilt/señal analítica/continuación). TODO el cálculo vive en el
// backend (endpoints regional-residual y mag-enhance); este panel solo pide,
// pinta la grilla con Viridis y ofrece la descarga CSV. NO calcula física.

import { useMemo, useState } from "react";
import {
  regionalResidual,
  magEnhance,
  type RegionalResidualResponse,
  type MagEnhanceResponse,
} from "../lib/terraquantum/frontendApi";

type Station = Record<string, number | string>;

type Props = {
  /** Estaciones ya parseadas (x_m/y_m + valor); vienen del flujo de preparación. */
  stations: Station[];
  /** "gravity" pinta regional-residual; "magnetic" habilita el realce. */
  dataKind: "gravity" | "magnetic";
  /** Columna del valor (g_bouguer_mgal, bouguer_anomaly, magnetic_nt...). */
  valueColumn: string;
};

// Viridis (matplotlib) — SOLO visualización; no es física ni duplica backend.
const VIRIDIS: [number, number, number][] = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142],
  [38, 130, 142], [31, 158, 137], [53, 183, 121], [110, 206, 88],
  [181, 222, 43], [253, 231, 37],
];

function viridis(t: number): string {
  const u = Math.max(0, Math.min(1, t)) * (VIRIDIS.length - 1);
  const i = Math.floor(u);
  const f = u - i;
  const a = VIRIDIS[i];
  const b = VIRIDIS[Math.min(i + 1, VIRIDIS.length - 1)];
  const r = Math.round(a[0] + (b[0] - a[0]) * f);
  const g = Math.round(a[1] + (b[1] - a[1]) * f);
  const bl = Math.round(a[2] + (b[2] - a[2]) * f);
  return `rgb(${r},${g},${bl})`;
}

// Dibuja una grilla (ny×nx) como celdas coloreadas por Viridis normalizado.
function GridImage({ grid, title }: { grid: number[][]; title: string }) {
  const { flat, min, max } = useMemo(() => {
    let mn = Infinity;
    let mx = -Infinity;
    for (const row of grid)
      for (const v of row) {
        if (Number.isFinite(v)) {
          if (v < mn) mn = v;
          if (v > mx) mx = v;
        }
      }
    return { flat: grid, min: mn, max: mx };
  }, [grid]);
  const ny = flat.length;
  const nx = ny > 0 ? flat[0].length : 0;
  if (ny === 0 || nx === 0) return null;
  const cell = Math.max(2, Math.floor(180 / Math.max(nx, ny)));
  const span = max - min || 1;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[9px] uppercase tracking-widest text-neutral-500">{title}</span>
      <svg width={nx * cell} height={ny * cell} className="border border-neutral-800">
        {flat.map((row, iy) =>
          row.map((v, ix) => (
            <rect
              key={`${iy}-${ix}`}
              // Norte arriba: fila 0 (y0) abajo.
              x={ix * cell}
              y={(ny - 1 - iy) * cell}
              width={cell}
              height={cell}
              fill={Number.isFinite(v) ? viridis((v - min) / span) : "#111"}
            />
          ))
        )}
      </svg>
      <span className="text-[8px] font-mono text-neutral-600">
        {min.toFixed(2)} … {max.toFixed(2)}
      </span>
    </div>
  );
}

const MAG_PRODUCTS: { key: string; label: string }[] = [
  { key: "tilt", label: "Tilt" },
  { key: "analytic_signal", label: "Señal analítica" },
  { key: "vd1", label: "1ª derivada vertical" },
  { key: "thd", label: "Derivada horizontal total" },
  { key: "rtp", label: "Reducción al polo" },
  { key: "upward_continuation", label: "Continuación asc." },
];

export default function MapRoomPanel({ stations, dataKind, valueColumn }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rr, setRr] = useState<RegionalResidualResponse | null>(null);
  const [mag, setMag] = useState<MagEnhanceResponse | null>(null);
  const [method, setMethod] = useState<"polynomial" | "upward_continuation">("polynomial");
  const [order, setOrder] = useState(1);
  const [magProducts, setMagProducts] = useState<string[]>(["tilt", "analytic_signal"]);
  const [inc, setInc] = useState(-30);
  const [dec, setDec] = useState(0);

  const runRegional = async () => {
    setError(null);
    setRr(null);
    setLoading(true);
    const res = await regionalResidual({
      stations,
      method,
      order,
      value_column: valueColumn,
      include_grids: true,
    });
    setLoading(false);
    if (!res.ok || !res.data) {
      setError(res.error ?? "No se pudo separar regional-residual.");
      return;
    }
    setRr(res.data);
  };

  const runMag = async () => {
    setError(null);
    setMag(null);
    setLoading(true);
    const res = await magEnhance({
      stations,
      products: magProducts,
      tmi_column: valueColumn,
      inclination_deg: inc,
      declination_deg: dec,
    });
    setLoading(false);
    if (!res.ok || !res.data) {
      setError(res.error ?? "No se pudo correr el realce magnético.");
      return;
    }
    setMag(res.data);
  };

  const warnings: string[] = [
    ...((rr?.report?.warnings as string[]) ?? []),
    ...((mag?.report?.warnings as string[]) ?? []),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="text-[10px] uppercase tracking-widest text-neutral-500">
        Sala de mapas · productos de gabinete
      </div>

      {/* Regional-residual (ambos tipos) */}
      <div className="rounded-lg border border-neutral-800 bg-black/30 p-3 flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-bold text-neutral-300">Regional / residual</span>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as typeof method)}
            className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-[10px] text-white"
          >
            <option value="polynomial">Tendencia polinomial</option>
            <option value="upward_continuation">Continuación ascendente</option>
          </select>
          {method === "polynomial" && (
            <select
              value={order}
              onChange={(e) => setOrder(Number(e.target.value))}
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-[10px] text-white"
            >
              <option value={1}>Orden 1 (plano)</option>
              <option value={2}>Orden 2</option>
              <option value={3}>Orden 3</option>
            </select>
          )}
          <button
            type="button"
            onClick={runRegional}
            disabled={loading || stations.length < 8}
            className="px-2 py-1 text-[10px] rounded bg-[#C2D8C4] text-black font-bold hover:bg-white disabled:opacity-40"
          >
            {loading ? "Calculando…" : "Separar"}
          </button>
        </div>
        {rr?.grids && (
          <div className="flex gap-3 flex-wrap">
            <GridImage grid={rr.grids.observed} title="Observado" />
            <GridImage grid={rr.grids.regional} title="Regional" />
            <GridImage grid={rr.grids.residual} title="Residual" />
          </div>
        )}
      </div>

      {/* Realce magnético (solo magnetometría) */}
      {dataKind === "magnetic" && (
        <div className="rounded-lg border border-neutral-800 bg-black/30 p-3 flex flex-col gap-2">
          <span className="text-[10px] font-bold text-neutral-300">Realce magnético</span>
          <div className="flex items-center gap-2 flex-wrap">
            {MAG_PRODUCTS.map((p) => (
              <label key={p.key} className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={magProducts.includes(p.key)}
                  onChange={(e) =>
                    setMagProducts((prev) =>
                      e.target.checked ? [...prev, p.key] : prev.filter((k) => k !== p.key)
                    )
                  }
                  className="accent-amber-500"
                />
                <span className="text-[10px] text-neutral-300">{p.label}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center gap-2 flex-wrap text-[10px] text-neutral-400">
            <label className="flex items-center gap-1">
              Inc°
              <input
                type="number"
                value={inc}
                onChange={(e) => setInc(Number(e.target.value))}
                className="w-16 bg-neutral-800 border border-neutral-700 rounded px-1 py-0.5 text-white"
              />
            </label>
            <label className="flex items-center gap-1">
              Dec°
              <input
                type="number"
                value={dec}
                onChange={(e) => setDec(Number(e.target.value))}
                className="w-16 bg-neutral-800 border border-neutral-700 rounded px-1 py-0.5 text-white"
              />
            </label>
            <button
              type="button"
              onClick={runMag}
              disabled={loading || magProducts.length === 0}
              className="px-2 py-1 text-[10px] rounded bg-[#C2D8C4] text-black font-bold hover:bg-white disabled:opacity-40"
            >
              {loading ? "Calculando…" : "Generar mapas"}
            </button>
          </div>
          {mag && (
            <div className="flex gap-3 flex-wrap">
              {Object.entries(mag.products).map(([name, grid]) => (
                <GridImage
                  key={name}
                  grid={grid}
                  title={MAG_PRODUCTS.find((p) => p.key === name)?.label ?? name}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded border border-rose-800 bg-rose-950/30 p-2 text-[10px] text-rose-300 font-mono">
          {error}
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="text-[9px] font-mono text-amber-400/80 list-disc list-inside">
          {warnings.slice(0, 6).map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
