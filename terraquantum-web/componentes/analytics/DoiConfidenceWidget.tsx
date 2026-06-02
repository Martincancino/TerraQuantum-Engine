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
  type Tone,
} from "./analyticsShared";
import { classifyDoiPercentile, qaGatedValue } from "../../lib/terraquantum/qaStatus";

function qaToTone(status: string): Tone {
  if (status === "PASS") return "neutral";
  if (status === "WARN") return "warn";
  return "bad";
}

/**
 * DOI Confidence (Li & Oldenburg 1999): doi_raw alto ⇒ el modelo recuperado
 * depende más del modelo de referencia (menor resolución / profundidad de
 * investigación). Histograma sobre doi_raw por vóxel + percentiles del backend.
 *
 * Scientific QA gating: DOI p50/p85 = 0 or null is FAIL, never displayed
 * as a valid value ("0.000"). A zero DOI is physically impossible in a valid
 * inversion and indicates solver failure or a degenerate grid.
 */
export default function DoiConfidenceWidget({
  report,
  cells,
}: {
  report: Record<string, unknown> | null;
  cells: Record<string, unknown>[];
}) {
  const summary = asRec(report?.doiDiagnostics);

  const doiValues = cells
    .map((c) => Number(c.doi_raw))
    .filter((v) => Number.isFinite(v));

  const p50 = numOf(summary, "p50");
  const p85 = numOf(summary, "p85");
  const p95 = numOf(summary, "p95");
  const maxV = numOf(summary, "max");

  // QA gating: classify each percentile independently
  const p50Qa = classifyDoiPercentile(p50);
  const p85Qa = classifyDoiPercentile(p85);
  const p95Qa = classifyDoiPercentile(p95);
  const maxQa = classifyDoiPercentile(maxV);

  // Display-safe values: null when QA fails → fmtNum renders "—"
  const p50Display = qaGatedValue(p50, p50Qa);
  const p85Display = qaGatedValue(p85, p85Qa);
  const p95Display = qaGatedValue(p95, p95Qa);
  const maxDisplay = qaGatedValue(maxV, maxQa);

  const dataMax = doiValues.length > 0 ? Math.max(...doiValues) : 0;
  const hi = dataMax > 0 ? dataMax : (maxDisplay ?? 1);
  const bins = buildHistogram(doiValues, 22, [0, hi]);

  // Confianza relativa: % de vóxeles por debajo de la mediana DOI = mejor resolución.
  const lowDoiPct =
    doiValues.length > 0 && p50Display !== null
      ? (100 * doiValues.filter((v) => v <= p50Display).length) / doiValues.length
      : null;

  // Determine the worst QA status across all percentiles for the inline notice
  const failReasons = [p50Qa, p85Qa, p95Qa, maxQa]
    .filter((q) => q.status === "FAIL" || q.status === "NOT_AVAILABLE")
    .map((q) => q.reason);
  const uniqueReasons = Array.from(new Set(failReasons));

  const allUnavailable =
    doiValues.length === 0 &&
    p50Qa.status === "NOT_AVAILABLE" &&
    p85Qa.status === "NOT_AVAILABLE";

  if (allUnavailable) {
    return (
      <EmptyState>
        DOI no disponible para esta corrida (requiere doble inversión con modelos de
        referencia).
      </EmptyState>
    );
  }

  return (
    <div className="space-y-2.5">
      {uniqueReasons.length > 0 && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-2.5 py-1.5">
          <p className="text-[8px] font-mono text-red-400 leading-tight">
            ⚠ QA: {uniqueReasons[0]}
          </p>
        </div>
      )}

      <div className="grid grid-cols-4 gap-1.5">
        <StatCard
          label="DOI p50"
          value={fmtNum(p50Display, 3)}
          tone={qaToTone(p50Qa.status)}
          hint={p50Qa.status !== "PASS" ? p50Qa.status : undefined}
        />
        <StatCard
          label="DOI p85"
          value={fmtNum(p85Display, 3)}
          tone={qaToTone(p85Qa.status)}
          hint={p85Qa.status !== "PASS" ? p85Qa.status : undefined}
        />
        <StatCard
          label="DOI p95"
          value={fmtNum(p95Display, 3)}
          tone={qaToTone(p95Qa.status)}
        />
        <StatCard
          label="DOI máx"
          value={fmtNum(maxDisplay, 3)}
          tone={qaToTone(maxQa.status)}
        />
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
              {p50Display !== null && (
                <ReferenceLine x={p50Display} stroke="#22d3ee" strokeDasharray="3 3" />
              )}
              {p85Display !== null && (
                <ReferenceLine x={p85Display} stroke="#eab308" strokeDasharray="3 3" />
              )}
              {p95Display !== null && (
                <ReferenceLine x={p95Display} stroke="#ef4444" strokeDasharray="3 3" />
              )}
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {bins.map((b, i) => (
                  <Cell
                    key={i}
                    fill={
                      p85Display !== null && b.mid > p85Display
                        ? "#ef4444"
                        : p50Display !== null && b.mid > p50Display
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
