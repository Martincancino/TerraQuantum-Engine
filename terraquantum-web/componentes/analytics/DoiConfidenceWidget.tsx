"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  asRec,
  numOf,
  fmtNum,
  StatCard,
  EmptyState,
  buildHistogram,
  axisProps,
  tooltipStyle,
} from "./analyticsShared";

/**
 * DOI Confidence (Li & Oldenburg 1999): doi_raw alto ⇒ el modelo recuperado
 * depende más del modelo de referencia (menor resolución / profundidad de
 * investigación). Histograma sobre doi_raw por vóxel + percentiles del backend.
 */
export default function DoiConfidenceWidget({
  report,
  cells,
}: {
  report: Record<string, unknown> | null;
  cells: Record<string, unknown>[];
}) {
  const summary = asRec(report?.doiDiagnostics);

  // El React Compiler memoiza estos derivados; no se usa useMemo manual.
  const doiValues = cells
    .map((c) => Number(c.doi_raw))
    .filter((v) => Number.isFinite(v));

  const p50 = numOf(summary, "p50");
  const p85 = numOf(summary, "p85");
  const p95 = numOf(summary, "p95");
  const maxV = numOf(summary, "max");

  const dataMax = doiValues.length > 0 ? Math.max(...doiValues) : 0;
  const hi = dataMax > 0 ? dataMax : maxV ?? 1;
  const bins = buildHistogram(doiValues, 22, [0, hi]);

  // Confianza relativa: % de vóxeles por debajo de la mediana DOI = mejor resolución.
  const lowDoiPct =
    doiValues.length > 0 && p50 !== null
      ? (100 * doiValues.filter((v) => v <= p50).length) / doiValues.length
      : null;

  if (doiValues.length === 0 && p50 === null) {
    return (
      <EmptyState>
        DOI no disponible para esta corrida (requiere doble inversión con modelos de
        referencia).
      </EmptyState>
    );
  }

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-4 gap-1.5">
        <StatCard label="DOI p50" value={fmtNum(p50, 3)} />
        <StatCard label="DOI p85" value={fmtNum(p85, 3)} />
        <StatCard label="DOI p95" value={fmtNum(p95, 3)} />
        <StatCard label="DOI máx" value={fmtNum(maxV, 3)} />
      </div>

      {bins.length > 0 ? (
        <div className="h-[150px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins} margin={{ top: 6, right: 8, bottom: 2, left: -18 }}>
              <XAxis
                dataKey="mid"
                type="number"
                domain={[0, hi]}
                {...axisProps}
                tickFormatter={(v: number) => v.toFixed(2)}
              />
              <YAxis {...axisProps} allowDecimals={false} width={34} />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                formatter={(value) => [String(value), "vóxeles"]}
                labelFormatter={(label) => `DOI ≈ ${Number(label).toFixed(3)}`}
              />
              {p50 !== null && (
                <ReferenceLine x={p50} stroke="#22d3ee" strokeDasharray="3 3" />
              )}
              {p85 !== null && (
                <ReferenceLine x={p85} stroke="#eab308" strokeDasharray="3 3" />
              )}
              {p95 !== null && (
                <ReferenceLine x={p95} stroke="#ef4444" strokeDasharray="3 3" />
              )}
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {bins.map((b, i) => (
                  <Cell
                    key={i}
                    fill={
                      p85 !== null && b.mid > p85
                        ? "#ef4444"
                        : p50 !== null && b.mid > p50
                        ? "#eab308"
                        : "#22d3ee"
                    }
                    fillOpacity={0.75}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : null}

      <p className="text-[8px] text-white/45 leading-tight">
        DOI bajo = mayor resolución/confianza. Marcadores: p50 (cian), p85 (ámbar),
        p95 (rojo).
        {lowDoiPct !== null && (
          <>
            {" "}
            <span className="text-[#C2D8C4]">
              {lowDoiPct.toFixed(0)}% de vóxeles ≤ p50
            </span>
            .
          </>
        )}
      </p>
    </div>
  );
}
