"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceDot,
  ResponsiveContainer,
} from "recharts";
import { getGeophysicsConvergence } from "../../lib/terraquantum/frontendApi";
import type { ConvergenceResponse } from "../../lib/terraquantum/frontendApi";
import { EmptyState, axisProps, tooltipStyle } from "./analyticsShared";

/**
 * F5 — Curva de "convergencia" YA calculada por el solver: el barrido de λ
 * (Morozov chi² discrepancy) usado para seleccionar la regularización
 * automática. NO es chi² por iteración de un solve único (esa serie no se
 * persiste hoy) — el backend lo aclara en `note` y este widget lo muestra tal
 * cual, sin inventar una curva de iteraciones que no existe.
 */
export default function ConvergenceCurveWidget({
  projectId,
  runId,
}: {
  projectId: string | null;
  runId: string | null;
}) {
  if (!projectId || !runId) return null;
  return (
    <ConvergenceCurveWidgetInner
      key={`${projectId}/${runId}`}
      projectId={projectId}
      runId={runId}
    />
  );
}

type FetchState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "done"; data: ConvergenceResponse };

function ConvergenceCurveWidgetInner({
  projectId,
  runId,
}: {
  projectId: string;
  runId: string;
}) {
  const [state, setState] = useState<FetchState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    getGeophysicsConvergence(projectId, runId).then((result) => {
      if (cancelled) return;
      if (!result.ok || !result.data) {
        setState({ status: "error", error: result.error ?? "Error leyendo convergencia." });
        return;
      }
      setState({ status: "done", data: result.data });
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, runId]);

  if (state.status === "loading") {
    return (
      <div className="flex items-center gap-2 py-2">
        <div className="w-3 h-3 rounded-full border-2 border-white/20 border-t-white/60 animate-spin" />
        <span className="text-[9px] text-white/40">Cargando barrido λ…</span>
      </div>
    );
  }

  if (state.status === "error") {
    return <EmptyState>Convergencia no disponible: {state.error}</EmptyState>;
  }

  const { data } = state;
  if (!data.available || data.trials.length === 0) {
    return <EmptyState>{data.note}</EmptyState>;
  }

  const points = data.trials
    .filter(
      (t): t is { lambda_value: number; chi2_reduced: number } =>
        t.lambda_value !== null && t.chi2_reduced !== null
    )
    .map((t) => ({ lambda: t.lambda_value, chi2: t.chi2_reduced }))
    .sort((a, b) => a.lambda - b.lambda);

  const selected = points.find(
    (p) => data.lambda_selected !== null && Math.abs(p.lambda - data.lambda_selected) < 1e-12
  );

  return (
    <div className="space-y-2">
      <div className="h-[150px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 6, right: 12, bottom: 2, left: -12 }}>
            <XAxis
              dataKey="lambda"
              type="number"
              scale="log"
              domain={["auto", "auto"]}
              {...axisProps}
              tickFormatter={(v: number) => v.toExponential(0)}
            />
            <YAxis {...axisProps} width={34} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value) => [Number(value).toFixed(4), "χ² reducido"]}
              labelFormatter={(label) => `λ = ${Number(label).toExponential(3)}`}
            />
            <Line type="monotone" dataKey="chi2" stroke="#22d3ee" strokeWidth={1.5} dot={{ r: 2 }} />
            {selected && (
              <ReferenceDot x={selected.lambda} y={selected.chi2} r={5} fill="#eab308" stroke="none" />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {data.selection_method === "morozov_chi2_discrepancy" && (
        <p className="text-[8px] text-white/45 leading-tight">
          Morozov: λ seleccionado ≈ {data.lambda_selected?.toExponential(3)} (χ² ={" "}
          {data.chi2_achieved?.toFixed(3)}, {data.n_solves} solves). Punto ámbar = seleccionado.
        </p>
      )}
      <p className="text-[7px] text-white/30 leading-tight italic">{data.note}</p>
    </div>
  );
}
