"use client";

import { useRunDiagnostics } from "./useRunDiagnostics";
import { asRec, numOf, strOf, fmtNum, fmtSci } from "./analyticsShared";
import type { SelectedRun } from "../datos/types";

type Kind = "num" | "sci" | "text";
type Row = {
  label: string;
  kind: Kind;
  decimals?: number;
  get: (r: Record<string, unknown> | null) => number | string | null;
};

const ROWS: Row[] = [
  { label: "χ² reducido", kind: "num", decimals: 3, get: (r) => numOf(asRec(r?.fitDiagnostics), "chi_squared") },
  { label: "Residual L2", kind: "sci", get: (r) => numOf(asRec(r?.fitDiagnostics), "residual_l2") },
  { label: "NRMSE", kind: "num", decimals: 4, get: (r) => numOf(asRec(r?.fitDiagnostics), "normalized_rmse") },
  { label: "Misfit %", kind: "num", decimals: 2, get: (r) => numOf(r, "misfit_error_percent") },
  { label: "Fit", kind: "text", get: (r) => strOf(asRec(r?.fitDiagnostics), "fit_level") },
  { label: "DOI p50", kind: "num", decimals: 3, get: (r) => numOf(asRec(r?.doiDiagnostics), "p50") },
  { label: "DOI p95", kind: "num", decimals: 3, get: (r) => numOf(asRec(r?.doiDiagnostics), "p95") },
  { label: "σ p50", kind: "num", decimals: 4, get: (r) => numOf(asRec(r?.uncertaintyPosterior), "p50") },
  { label: "σ p95", kind: "num", decimals: 4, get: (r) => numOf(asRec(r?.uncertaintyPosterior), "p95") },
  { label: "Cobertura X", kind: "num", decimals: 3, get: (r) => numOf(asRec(r?.observationQuality), "coverage_ratio_x") },
  { label: "Cobertura Z", kind: "num", decimals: 3, get: (r) => numOf(asRec(r?.observationQuality), "coverage_ratio_z") },
  { label: "Observaciones", kind: "num", decimals: 0, get: (r) => numOf(asRec(r?.observationQuality), "observation_count") },
  { label: "Incertidumbre", kind: "text", get: (r) => strOf(asRec(r?.uncertaintyDiagnostics), "uncertainty_level") },
];

function fmtVal(v: number | string | null, kind: Kind, decimals?: number): string {
  if (v === null) return "—";
  if (typeof v === "string") return v;
  if (kind === "sci") return fmtSci(v);
  return fmtNum(v, decimals ?? 2);
}

/**
 * Comparación científica side-by-side de dos corridas (Fase E).
 * Lee el detalle de cada run (report del backend) y enfrenta las métricas clave
 * del solver/DOI/incertidumbre/cobertura, con delta para las numéricas.
 */
export default function RunCompareSideBySide({
  baseRun,
  compareRun,
}: {
  baseRun: SelectedRun | null;
  compareRun: SelectedRun | null;
}) {
  const base = useRunDiagnostics(
    baseRun?.projectId ?? null,
    baseRun?.runId ?? null,
    baseRun ? "ready" : "idle"
  );
  const cmp = useRunDiagnostics(
    compareRun?.projectId ?? null,
    compareRun?.runId ?? null,
    compareRun ? "ready" : "idle"
  );

  if (!baseRun || !compareRun) return null;

  const rb = base.data?.report ?? null;
  const rc = cmp.data?.report ?? null;
  const loading = base.loading || cmp.loading;

  return (
    <div className="mb-4">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-2">
        Comparación científica side-by-side
      </p>
      {loading && !rb && !rc ? (
        <p className="text-[10px] text-neutral-500 font-mono">Cargando diagnósticos de ambas corridas…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[9px] font-mono">
            <thead className="text-neutral-600 uppercase">
              <tr>
                <th className="pb-2 pr-3 font-normal">métrica</th>
                <th className="pb-2 pr-3 font-normal text-[#C2D8C4]">base</th>
                <th className="pb-2 pr-3 font-normal text-white">compare</th>
                <th className="pb-2 pr-3 font-normal text-neutral-500">Δ</th>
              </tr>
            </thead>
            <tbody className="text-neutral-300">
              {ROWS.map((row) => {
                const bv = row.get(rb);
                const cv = row.get(rc);
                const isNum = typeof bv === "number" && typeof cv === "number";
                const delta = isNum ? (cv as number) - (bv as number) : null;
                return (
                  <tr key={row.label} className="border-t border-neutral-900">
                    <td className="py-1.5 pr-3 text-neutral-500">{row.label}</td>
                    <td className="py-1.5 pr-3 text-[#C2D8C4]">{fmtVal(bv, row.kind, row.decimals)}</td>
                    <td className="py-1.5 pr-3 text-white">{fmtVal(cv, row.kind, row.decimals)}</td>
                    <td className="py-1.5 pr-3 text-[#22d3ee]">
                      {delta === null
                        ? "—"
                        : `${delta >= 0 ? "+" : ""}${fmtVal(delta, row.kind === "sci" ? "sci" : "num", row.decimals)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!rb && !rc && !loading && (
            <p className="text-[9px] text-neutral-600 mt-2 italic">
              Sin diagnósticos disponibles para estas corridas.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
