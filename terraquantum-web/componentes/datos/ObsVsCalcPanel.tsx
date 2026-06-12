"use client";

import { useEffect, useState, useMemo } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import { getGeophysicsMisfit } from "../../lib/terraquantum/frontendApi";
import type { MisfitResponse, MisfitStationData } from "../../lib/terraquantum/frontendApi";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtSci(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toExponential(3);
}

function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function chi2Tone(chi: number): { color: string; label: string } {
  if (chi >= 0.5 && chi <= 2) return { color: "#C2D8C4", label: "AJUSTE IDEAL" };
  if (chi < 0.5) return { color: "#facc15", label: "SOBREAJUSTE" };
  if (chi <= 5) return { color: "#facc15", label: "SUBAJUSTE" };
  return { color: "#f87171", label: "AJUSTE POBRE" };
}

// Build histogram bins from residuals array
function buildHistogram(residuals: number[], nBins = 20): { label: string; count: number; center: number }[] {
  if (residuals.length === 0) return [];
  const min = Math.min(...residuals);
  const max = Math.max(...residuals);
  const range = max - min;
  if (range < 1e-30) return [{ label: "0", count: residuals.length, center: 0 }];

  const width = range / nBins;
  const bins = Array.from({ length: nBins }, (_, i) => ({
    label: (min + (i + 0.5) * width).toExponential(2),
    center: min + (i + 0.5) * width,
    count: 0,
  }));

  for (const r of residuals) {
    const idx = Math.min(Math.floor((r - min) / width), nBins - 1);
    bins[idx].count++;
  }
  return bins;
}

// Map residual magnitude to a color (blue → green → yellow → red)
function residualColor(normalized: number): string {
  // normalized in [0, 1]
  const t = Math.max(0, Math.min(1, normalized));
  if (t < 0.33) return "#C2D8C4";
  if (t < 0.66) return "#facc15";
  return "#f87171";
}

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, unit, color }: { label: string; value: string; unit?: string; color?: string }) {
  return (
    <div className="bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2">
      <p className="text-[7px] uppercase tracking-[0.2em] text-white/40 mb-0.5">{label}</p>
      <p className="text-[15px] font-mono leading-none" style={color ? { color } : undefined}>
        {value}
        {unit && <span className="text-[9px] text-white/40 ml-1">{unit}</span>}
      </p>
    </div>
  );
}

// ─── Scatter obs vs calc ───────────────────────────────────────────────────────

function ScatterObsCalc({ stations }: { stations: MisfitStationData[] }) {
  const pts = stations.map(s => ({ d_obs: s.d_obs, d_pred: s.d_pred }));

  const allObs = pts.map(p => p.d_obs);
  const allPred = pts.map(p => p.d_pred);
  const minV = Math.min(...allObs, ...allPred);
  const maxV = Math.max(...allObs, ...allPred);
  const margin = (maxV - minV) * 0.05 || 1e-10;
  const lo = minV - margin;
  const hi = maxV + margin;

  const refLine = [{ d_obs: lo, d_pred: lo }, { d_obs: hi, d_pred: hi }];

  return (
    <div>
      <p className="text-[7px] uppercase tracking-[0.2em] text-white/40 mb-2">Scatter obs vs calc</p>
      <ResponsiveContainer width="100%" height={200}>
        <ScatterChart margin={{ top: 4, right: 4, bottom: 20, left: 8 }}>
          <XAxis
            dataKey="d_obs"
            type="number"
            name="Obs"
            domain={[lo, hi]}
            tick={{ fontSize: 8, fill: "#ffffff55" }}
            tickFormatter={v => v.toExponential(1)}
            label={{ value: "d_obs (m/s²)", position: "insideBottom", offset: -12, fontSize: 8, fill: "#ffffff55" }}
          />
          <YAxis
            dataKey="d_pred"
            type="number"
            name="Calc"
            domain={[lo, hi]}
            tick={{ fontSize: 8, fill: "#ffffff55" }}
            tickFormatter={v => v.toExponential(1)}
            width={60}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3", stroke: "#ffffff33" }}
            contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 9, color: "#ccc" }}
            formatter={(v) => [Number(v).toExponential(4), ""]}
          />
          {/* 1:1 reference line as a second scatter series with line=true */}
          <Scatter
            name="1:1"
            data={refLine}
            line={{ stroke: "#ffffff33", strokeDasharray: "4 4", strokeWidth: 1 }}
            shape={() => null}
            legendType="none"
          />
          <Scatter name="Estaciones" data={pts} fill="#C2D8C4" opacity={0.7} r={3} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Residuals histogram ──────────────────────────────────────────────────────

function ResidualHistogram({ residuals }: { residuals: number[] }) {
  const bins = useMemo(() => buildHistogram(residuals), [residuals]);
  const maxCount = Math.max(...bins.map(b => b.count), 1);

  return (
    <div>
      <p className="text-[7px] uppercase tracking-[0.2em] text-white/40 mb-2">Histograma residuales</p>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={bins} margin={{ top: 4, right: 4, bottom: 20, left: 8 }}>
          <XAxis
            dataKey="label"
            tick={{ fontSize: 7, fill: "#ffffff55" }}
            interval={Math.floor(bins.length / 5)}
            label={{ value: "Residual (m/s²)", position: "insideBottom", offset: -12, fontSize: 8, fill: "#ffffff55" }}
          />
          <YAxis tick={{ fontSize: 7, fill: "#ffffff55" }} width={28} />
          <Tooltip
            contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 9, color: "#ccc" }}
            formatter={(v) => [Number(v), "count"]}
          />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {bins.map((b, i) => (
              <Cell key={i} fill={residualColor(b.count / maxCount)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Spatial residuals map (SVG) ──────────────────────────────────────────────

function SpatialResidualsMap({ stations }: { stations: MisfitStationData[] }) {
  const validStations = stations.filter(
    s => s.x !== null && s.z !== null && Number.isFinite(s.x!) && Number.isFinite(s.z!)
  );

  if (validStations.length === 0) {
    return (
      <div>
        <p className="text-[7px] uppercase tracking-[0.2em] text-white/40 mb-2">Mapa residuales</p>
        <p className="text-[9px] text-white/30 italic">Sin coordenadas espaciales disponibles.</p>
      </div>
    );
  }

  const xs = validStations.map(s => s.x!);
  const zs = validStations.map(s => s.z!);
  const absResiduals = validStations.map(s => Math.abs(s.residual));

  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const zMin = Math.min(...zs);
  const zMax = Math.max(...zs);
  const rMax = Math.max(...absResiduals, 1e-30);

  const W = 280, H = 140, PAD = 12;

  function scaleX(x: number) {
    return PAD + ((x - xMin) / Math.max(xMax - xMin, 1e-10)) * (W - 2 * PAD);
  }
  function scaleY(z: number) {
    return PAD + (1 - (z - zMin) / Math.max(zMax - zMin, 1e-10)) * (H - 2 * PAD);
  }

  return (
    <div>
      <p className="text-[7px] uppercase tracking-[0.2em] text-white/40 mb-2">Mapa espacial residuales</p>
      <svg width={W} height={H} className="block">
        <rect width={W} height={H} fill="transparent" />
        {validStations.map((s, i) => {
          const norm = absResiduals[i] / rMax;
          return (
            <circle
              key={i}
              cx={scaleX(s.x!)}
              cy={scaleY(s.z!)}
              r={4}
              fill={residualColor(norm)}
              opacity={0.75}
            >
              <title>{`x=${s.x?.toFixed(1)} z=${s.z?.toFixed(1)} res=${s.residual.toExponential(3)}`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="flex items-center gap-2 mt-1">
        <div className="flex gap-1 items-center">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: "#C2D8C4" }} />
          <span className="text-[7px] text-white/40">Bajo</span>
        </div>
        <div className="flex gap-1 items-center">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: "#facc15" }} />
          <span className="text-[7px] text-white/40">Medio</span>
        </div>
        <div className="flex gap-1 items-center">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: "#f87171" }} />
          <span className="text-[7px] text-white/40">Alto</span>
        </div>
        <span className="text-[7px] text-white/25 ml-auto">|residual|</span>
      </div>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

type Tab = "scatter" | "histogram" | "spatial";

export default function ObsVsCalcPanel({
  projectId,
  runId,
}: {
  projectId: string;
  runId: string;
}) {
  const [data, setData] = useState<MisfitResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("scatter");

  useEffect(() => {
    if (!projectId || !runId) return;
    setLoading(true);
    setError(null);
    setData(null);

    getGeophysicsMisfit(projectId, runId).then(result => {
      setLoading(false);
      if (!result.ok || !result.data) {
        setError(result.error ?? "Error leyendo datos de ajuste.");
        return;
      }
      setData(result.data);
    });
  }, [projectId, runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4">
        <div className="w-3 h-3 rounded-full border-2 border-white/20 border-t-white/60 animate-spin" />
        <span className="text-[9px] text-white/40">Cargando obs vs calc…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-neutral-800 bg-neutral-950/60 px-4 py-3">
        <p className="text-[8px] uppercase tracking-widest text-white/30 mb-1">Ajuste obs vs calc</p>
        <p className="text-[9px] text-white/40 font-mono">{error}</p>
        <p className="text-[8px] text-white/20 mt-1">
          El parquet obs_vs_calc puede no existir si la inversión se realizó antes de H-C1.
        </p>
      </div>
    );
  }

  if (!data) return null;

  const { chi2_reduced, rmse, normalized_rmse, r2, n_stations, stations } = data;
  const residuals = stations.map(s => s.residual);
  const { color: chi2Color, label: chi2Label } = chi2Tone(chi2_reduced);

  const TABS: { key: Tab; label: string }[] = [
    { key: "scatter", label: "Scatter" },
    { key: "histogram", label: "Histograma" },
    { key: "spatial", label: "Mapa" },
  ];

  return (
    <div className="space-y-3">
      {/* Aggregate stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatCard label="χ² reducido" value={fmtNum(chi2_reduced, 3)} color={chi2Color} />
        <StatCard label="RMSE" value={fmtSci(rmse)} unit="m/s²" />
        <StatCard label="NRMSE" value={fmtNum(normalized_rmse, 4)} />
        <StatCard label="R²" value={fmtNum(r2, 4)} />
      </div>

      {/* chi² interpretation */}
      <div
        className="rounded-lg border px-3 py-1.5 flex items-center justify-between"
        style={{ borderColor: `${chi2Color}44`, background: `${chi2Color}08` }}
      >
        <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: chi2Color }}>
          {chi2Label}
        </span>
        <span className="text-[8px] text-white/40">
          {n_stations} estaciones · χ² objetivo ≈ 1.0
        </span>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1">
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-3 py-1 rounded text-[8px] uppercase tracking-widest font-bold transition-colors ${
              tab === t.key
                ? "bg-white/10 text-white border border-white/20"
                : "text-white/30 border border-transparent hover:text-white/60"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Charts */}
      <div className="bg-neutral-950/40 border border-neutral-800 rounded-xl p-4">
        {tab === "scatter" && <ScatterObsCalc stations={stations} />}
        {tab === "histogram" && <ResidualHistogram residuals={residuals} />}
        {tab === "spatial" && <SpatialResidualsMap stations={stations} />}
      </div>
    </div>
  );
}
