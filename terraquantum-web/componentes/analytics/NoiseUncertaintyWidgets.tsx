"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import {
  asRec,
  numOf,
  strOf,
  boolOf,
  fmtNum,
  fmtSci,
  StatCard,
  EmptyState,
  buildHistogram,
  axisProps,
  tooltipStyle,
  type Tone,
} from "./analyticsShared";
import { classifyUncertaintyValues } from "../../lib/terraquantum/qaStatus";

// ─── Ruido / SNR ──────────────────────────────────────────────────────────────
export function NoiseSnrWidget({
  report,
}: {
  report: Record<string, unknown> | null;
}) {
  const oq = asRec(report?.observationQuality);
  const fd = asRec(report?.fitDiagnostics);

  const dynRange = numOf(oq, "signal_dynamic_range");
  const gStd = numOf(oq, "g_std");
  const obsCount = numOf(oq, "observation_count");
  const qualityLevel = strOf(oq, "quality_level");
  const residualRmse = numOf(fd, "residual_rmse");
  const residualStd = numOf(fd, "residual_std", "residual_rmse");

  // Indicador de visualización (no es una métrica física del backend):
  // razón entre el rango dinámico de la señal observada y el residual RMSE.
  const snr =
    dynRange !== null && residualRmse !== null && residualRmse > 0
      ? dynRange / residualRmse
      : null;

  const hasAny = dynRange !== null || gStd !== null || residualRmse !== null;
  if (!hasAny) {
    return <EmptyState>Métricas de ruido/SNR no disponibles para esta corrida.</EmptyState>;
  }

  const qTone: Tone =
    qualityLevel === "GOOD" ? "good" : qualityLevel === "MEDIUM" ? "warn" : qualityLevel ? "bad" : "neutral";
  const snrTone: Tone =
    snr === null ? "neutral" : snr >= 10 ? "good" : snr >= 4 ? "warn" : "bad";

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-1.5">
        <StatCard label="Rango dinámico" value={fmtSci(dynRange)} />
        <StatCard label="g_std" value={fmtSci(gStd)} />
        <StatCard label="Residual RMSE" value={fmtSci(residualRmse)} />
        <StatCard
          label="SNR ≈"
          value={snr !== null ? fmtNum(snr, 1) : "—"}
          tone={snrTone}
          hint="rango/residual"
        />
        <StatCard label="Residual σ" value={fmtSci(residualStd)} />
        <StatCard
          label="Obs / calidad"
          value={obsCount !== null ? fmtNum(obsCount, 0) : "—"}
          tone={qTone}
          hint={qualityLevel ?? undefined}
        />
      </div>
      <p className="text-[8px] text-white/40 leading-tight">
        SNR ≈ es un indicador de visualización (rango dinámico ÷ residual RMSE), no una
        métrica física del backend.
      </p>
    </div>
  );
}

// ─── Incertidumbre posterior (Hutchinson) ──────────────────────────────────────
export function UncertaintyPosteriorWidget({
  report,
  cells,
}: {
  report: Record<string, unknown> | null;
  cells: Record<string, unknown>[];
}) {
  const summary = asRec(report?.uncertaintyPosterior);
  const computed = boolOf(summary, "computed");
  const unit = strOf(summary, "unit") ?? "t/m³";
  const p50 = numOf(summary, "p50");
  const p95 = numOf(summary, "p95");
  const maxV = numOf(summary, "max");

  const sigmaValues = cells
    .map((c) => Number(c.posterior_std))
    .filter((v) => Number.isFinite(v));

  // QA gating: block display when no valid uncertainty data exists.
  // All-zero sigma is scientifically indistinguishable from "not computed"
  // — showing a uniform dark histogram would imply precise zero uncertainty,
  // which is only possible for an exact forward problem (not a real inversion).
  const sigmaQa = classifyUncertaintyValues(sigmaValues);

  const backendSaysNotComputed = !computed && p50 === null && sigmaValues.length === 0;

  if (backendSaysNotComputed || sigmaQa.status === "NOT_AVAILABLE") {
    const reason = backendSaysNotComputed
      ? "σ posterior no calculada en esta corrida (compute_uncertainty desactivado)."
      : sigmaQa.reason;
    return (
      <div className="space-y-1.5">
        <EmptyState>{reason}</EmptyState>
        <p className="text-[8px] font-mono text-white/30 leading-tight">
          Estado: No disponible para esta corrida
        </p>
      </div>
    );
  }

  const dataMax = sigmaValues.length > 0 ? Math.max(...sigmaValues) : 0;
  const hi = dataMax > 0 ? dataMax : (maxV ?? 1);
  const bins = buildHistogram(sigmaValues, 22, [0, hi]);

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-1.5">
        <StatCard label={`σ p50`} value={fmtNum(p50, 4)} unit={unit} />
        <StatCard label={`σ p95`} value={fmtNum(p95, 4)} unit={unit} />
        <StatCard label={`σ máx`} value={fmtNum(maxV, 4)} unit={unit} />
      </div>

      {bins.length > 0 && (
        <div className="h-[150px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins} margin={{ top: 6, right: 8, bottom: 2, left: -18 }}>
              <XAxis
                dataKey="mid"
                type="number"
                domain={[0, hi]}
                {...axisProps}
                tickFormatter={(v: number) => v.toFixed(3)}
              />
              <YAxis {...axisProps} allowDecimals={false} width={34} />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                formatter={(value) => [String(value), "vóxeles"]}
                labelFormatter={(label) => `σ ≈ ${Number(label).toFixed(4)} ${unit}`}
              />
              {p50 !== null && (
                <ReferenceLine x={p50} stroke="#22d3ee" strokeDasharray="3 3" />
              )}
              {p95 !== null && (
                <ReferenceLine x={p95} stroke="#ef4444" strokeDasharray="3 3" />
              )}
              <Bar dataKey="count" fill="#818cf8" fillOpacity={0.8} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className="text-[8px] text-white/40 leading-tight">
        σ posterior lineal (1σ) por vóxel vía estimador de Hutchinson. Incertidumbre
        estadística, no captura no-unicidad no-lineal.
      </p>
    </div>
  );
}
