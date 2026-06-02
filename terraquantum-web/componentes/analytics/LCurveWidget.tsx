"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceDot,
  ResponsiveContainer,
} from "recharts";
import { runGeophysicsSensitivitySweep } from "../../lib/terraquantum/frontendApi";
import type { SensitivitySweepCase } from "../../lib/terraquantum/frontendApi";
import { numOf, fmtSci, fmtNum, EmptyState, axisProps, tooltipStyle } from "./analyticsShared";
import { classifyLCurvePoints } from "../../lib/terraquantum/qaStatus";

type SweepState = "idle" | "loading" | "done" | "error";

function logSpaceAround(base: number): number[] {
  const b = Number.isFinite(base) && base > 0 ? base : 1e-4;
  return [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30].map((m) => b * m);
}

export default function LCurveWidget({
  inputs,
  observations,
}: {
  inputs: Record<string, unknown> | null;
  observations: Record<string, unknown>[];
}) {
  const [state, setState] = useState<SweepState>("idle");
  const [cases, setCases] = useState<SensitivitySweepCase[]>([]);
  const [best, setBest] = useState<SensitivitySweepCase | null>(null);
  const [recommendation, setRecommendation] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const canRun = Boolean(inputs) && observations.length >= 10;

  const points = cases
    .map((c) => ({
      lambda_mag: Number(c.lambda_mag),
      y: Number(c.normalized_rmse ?? c.residual_rmse),
      residual_rmse: Number(c.residual_rmse),
      fit_level: c.fit_level ?? "—",
    }))
    .filter(
      (p) =>
        Number.isFinite(p.lambda_mag) &&
        p.lambda_mag > 0 &&
        Number.isFinite(p.y) &&
        p.y > 0
    )
    .sort((a, b) => a.lambda_mag - b.lambda_mag);

  const xs = points.map((p) => p.lambda_mag);
  const ys = points.map((p) => p.y);
  const domains =
    points.length === 0
      ? null
      : {
          x: [Math.min(...xs) * 0.6, Math.max(...xs) * 1.6] as [number, number],
          y: [Math.min(...ys) * 0.7, Math.max(...ys) * 1.4] as [number, number],
        };

  const bestY = best ? Number(best.normalized_rmse ?? best.residual_rmse) : null;
  const bestX = best ? Number(best.lambda_mag) : null;

  // QA: detect flat L-curve after sweep completes
  const lcurveQa = state === "done" ? classifyLCurvePoints(points) : null;

  async function runSweep() {
    if (!canRun || !inputs) return;
    setState("loading");
    setErrorMsg(null);

    const lambdaBase = numOf(inputs, "lambda_mag") ?? 1e-4;
    const alpha = numOf(inputs, "alpha_spatial") ?? 1.0;

    const payload = {
      ...inputs,
      observations,
      lambda_values: logSpaceAround(lambdaBase),
      alpha_values: [alpha],
      max_cases: 12,
    };

    try {
      const res = await runGeophysicsSensitivitySweep(payload);
      if (!res.ok || !res.data) {
        setErrorMsg(res.error || "El sweep de sensibilidad falló en el backend.");
        setState("error");
        return;
      }
      setCases(Array.isArray(res.data.cases) ? res.data.cases : []);
      setBest(res.data.best_case ?? null);
      setRecommendation(res.data.recommendation ?? "");
      setState("done");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Error de red");
      setState("error");
    }
  }

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[8px] text-white/45 leading-tight max-w-[60%]">
          Barrido de λ: misfit (NRMSE) vs regularización. Marca la λ recomendada.
        </p>
        <button
          type="button"
          onClick={runSweep}
          disabled={!canRun || state === "loading"}
          className={`text-[9px] font-mono uppercase tracking-wider px-3 py-1.5 rounded-md border transition-colors ${
            !canRun || state === "loading"
              ? "border-white/10 text-white/30 cursor-not-allowed"
              : "border-accent/50 text-accent hover:bg-accent/10"
          }`}
        >
          {state === "loading" ? "Calculando…" : state === "done" ? "Recalcular" : "Calcular sweep λ"}
        </button>
      </div>

      {!canRun && (
        <EmptyState>
          Se requieren los inputs del run y ≥10 observaciones para el barrido.
        </EmptyState>
      )}

      {state === "error" && (
        <p className="text-[9px] text-red-400 font-mono leading-tight">⚠ {errorMsg}</p>
      )}

      {/* QA: flat-curve warning shown below the button row, before the chart */}
      {lcurveQa && lcurveQa.status === "WARN" && (
        <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 px-2.5 py-1.5">
          <p className="text-[8px] font-mono text-yellow-400 leading-tight">
            ⚠ λ heurístico — {lcurveQa.reason}
          </p>
        </div>
      )}

      {state === "done" && points.length > 0 && domains && (
        <>
          <div className="h-[170px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 10, bottom: 4, left: -16 }}>
                <XAxis
                  dataKey="lambda_mag"
                  type="number"
                  scale="log"
                  domain={domains.x}
                  {...axisProps}
                  tickFormatter={(v: number) => v.toExponential(0)}
                />
                <YAxis
                  type="number"
                  scale="log"
                  domain={domains.y}
                  {...axisProps}
                  width={38}
                  tickFormatter={(v: number) => v.toPrecision(2)}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(label) => `λ = ${Number(label).toExponential(2)}`}
                  formatter={(value, name) => [
                    typeof value === "number" ? value.toPrecision(4) : String(value),
                    name === "y" ? "NRMSE" : name,
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="y"
                  stroke="#22d3ee"
                  strokeWidth={2}
                  dot={{ r: 2.5, fill: "#22d3ee" }}
                  isAnimationActive={false}
                />
                {bestX !== null && bestY !== null && Number.isFinite(bestX) && Number.isFinite(bestY) && (
                  <ReferenceDot
                    x={bestX}
                    y={bestY}
                    r={5}
                    fill="#4ade80"
                    stroke="#0a0a0a"
                    strokeWidth={1}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {best && (
            <div className="text-[8px] font-mono text-white/55 leading-tight">
              <span className="text-[#4ade80]">● λ óptima</span> ={" "}
              {fmtSci(Number(best.lambda_mag))} · NRMSE{" "}
              {fmtNum(Number(best.normalized_rmse ?? best.residual_rmse), 4)} · {best.fit_level ?? "—"}
              {lcurveQa && lcurveQa.status === "WARN" && (
                <span className="text-yellow-400 ml-1">(heurístico)</span>
              )}
            </div>
          )}
          {recommendation && (
            <p className="text-[8px] text-white/45 leading-tight">{recommendation}</p>
          )}
        </>
      )}
    </div>
  );
}
