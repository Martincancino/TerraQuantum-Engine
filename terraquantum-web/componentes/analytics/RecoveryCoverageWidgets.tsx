"use client";

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ZAxis,
} from "recharts";
import {
  asRec,
  numOf,
  strOf,
  fmtNum,
  StatCard,
  EmptyState,
  axisProps,
  tooltipStyle,
  type Tone,
} from "./analyticsShared";

// ─── Cobertura de sensores ──────────────────────────────────────────────────
export function SensorCoverageWidget({
  report,
  observations,
}: {
  report: Record<string, unknown> | null;
  observations: Record<string, unknown>[];
}) {
  const oq = asRec(report?.observationQuality);
  const sqf = asRec(report?.sensorQualityFlags);

  const coverageX = numOf(oq, "coverage_ratio_x");
  const coverageZ = numOf(oq, "coverage_ratio_z");
  const obsCount = numOf(oq, "observation_count");
  const sensorCount = numOf(sqf, "sensor_count");
  const flaggedCount = numOf(sqf, "flagged_count");
  const sensorsTotal = obsCount ?? sensorCount;

  const baseData = observations
    .map((o) => ({ x: Number(o.x_m ?? o.x), z: Number(o.z_m ?? o.z) }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.z));

  const flaggedRaw = sqf?.flagged_sensors;
  const flaggedList = Array.isArray(flaggedRaw) ? flaggedRaw : [];
  const flaggedData = flaggedList
    .map((s) => {
      const rec = asRec(s);
      return { x: Number(rec?.x_m), z: Number(rec?.z_m) };
    })
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.z));

  if (baseData.length === 0 && flaggedData.length === 0) {
    return <EmptyState>Posiciones de sensores no disponibles para esta corrida.</EmptyState>;
  }

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-4 gap-1.5">
        <StatCard label="Cov. X" value={fmtNum(coverageX, 3)} />
        <StatCard label="Cov. Z" value={fmtNum(coverageZ, 3)} />
        <StatCard
          label="Sensores"
          value={sensorsTotal !== null ? fmtNum(sensorsTotal, 0) : "—"}
        />
        <StatCard
          label="Marcados"
          value={flaggedCount !== null ? fmtNum(flaggedCount, 0) : "—"}
          tone={flaggedCount && flaggedCount > 0 ? "warn" : "good"}
        />
      </div>

      <div className="h-[170px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 10, bottom: 2, left: -14 }}>
            <XAxis
              type="number"
              dataKey="x"
              name="X"
              {...axisProps}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => v.toFixed(0)}
            />
            <YAxis
              type="number"
              dataKey="z"
              name="Z"
              {...axisProps}
              width={36}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => v.toFixed(0)}
            />
            <ZAxis range={[18, 18]} />
            <Tooltip
              contentStyle={tooltipStyle}
              cursor={{ strokeDasharray: "3 3", stroke: "#3f3f46" }}
              formatter={(value, name) => [Number(value).toFixed(1), name]}
            />
            <Scatter data={baseData} fill="#22d3ee" fillOpacity={0.45} />
            {flaggedData.length > 0 && (
              <Scatter data={flaggedData} fill="#ef4444" fillOpacity={0.95} />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[8px] text-white/40 leading-tight">
        Planta X/Z de estaciones. <span className="text-[#22d3ee]">●</span> observación ·{" "}
        <span className="text-red-400">●</span> sensor marcado (residual alto).
      </p>
    </div>
  );
}

// ─── Recuperación sintética ─────────────────────────────────────────────────
export function RecoveryWidget({
  report,
  metrics,
}: {
  report: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
}) {
  // La recuperación sintética (checkerboard / esfera) es un benchmark, no una
  // salida por corrida. Se muestra solo si el run la expone.
  const rec =
    asRec(report?.recovery) ??
    asRec(report?.syntheticRecovery) ??
    asRec(metrics?.recovery) ??
    asRec(report?.checkerboard) ??
    null;

  const pearson = numOf(rec ?? report, "pearson_r");
  const signPct = numOf(rec ?? report, "sign_recovery_pct");
  const rmsError = numOf(rec ?? report, "rms_error");
  const score = strOf(rec ?? report, "recovery_score") ?? strOf(rec ?? report, "status");

  const hasAny = pearson !== null || signPct !== null || score !== null;

  if (!hasAny) {
    return (
      <EmptyState>
        La recuperación sintética es un benchmark (checkerboard/esfera) y no se calcula
        por corrida. No hay métricas de recuperación en este run.
      </EmptyState>
    );
  }

  const scoreTone: Tone =
    score === "EXCELLENT" || score === "GOOD"
      ? "good"
      : score === "ACCEPTABLE"
      ? "warn"
      : score
      ? "bad"
      : "neutral";

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-1.5">
        <StatCard label="Pearson r" value={fmtNum(pearson, 3)} />
        <StatCard label="Signo OK" value={fmtNum(signPct, 1)} unit="%" />
        <StatCard label="RMS error" value={fmtNum(rmsError, 4)} />
      </div>
      {score && (
        <span
          className={`inline-block text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border font-bold ${
            scoreTone === "good"
              ? "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10"
              : scoreTone === "warn"
              ? "text-yellow-400 border-yellow-500/40 bg-yellow-500/10"
              : "text-red-400 border-red-500/40 bg-red-500/10"
          }`}
        >
          {score}
        </span>
      )}
    </div>
  );
}
