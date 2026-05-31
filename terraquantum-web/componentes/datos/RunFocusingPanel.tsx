"use client";
import { asRecord, fmtNum, fmtSci } from "./helpers";

interface RunFocusingPanelProps {
  focusingData: Record<string, unknown> | undefined | null;
}

export default function RunFocusingPanel({ focusingData }: RunFocusingPanelProps) {
  if (!focusingData) return null;

  const focusing = focusingData;
  const enabled = focusing.enabled === true;
  const scaleStatus = String(focusing.scale_status ?? "");
  const useMode = String(focusing.use_mode ?? "");
  const safetyLabels = Array.isArray(focusing.safety_labels)
    ? (focusing.safety_labels as unknown[]).map(String)
    : [];
  const meta = asRecord(focusing.focusing_metadata);

  const scaleStatusInfo = (() => {
    if (scaleStatus === "OK") return { label: "Escala convergente", cls: "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10" };
    if (scaleStatus === "SUPRIMIDA") return { label: "Escala suprimida — señal atenuada", cls: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10" };
    if (scaleStatus === "INESTABLE") return { label: "Escala inestable — resultado no confiable", cls: "text-red-400 border-red-500/40 bg-red-500/10" };
    return { label: scaleStatus || "—", cls: "text-neutral-400 border-neutral-800 bg-neutral-950" };
  })();

  const useModeLabel = (() => {
    if (useMode === "physical_mask_candidate") return "Candidato a máscara de contraste (no densidad física)";
    if (useMode === "relative_targeting_score") return "Score relativo de targeting (no recurso)";
    return useMode || "—";
  })();

  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-[10px] uppercase text-yellow-400/80 tracking-widest hover:text-yellow-400 outline-none">
        Focusing MS-x — Resultado experimental
      </summary>
      <div className="mt-3 border border-yellow-600/20 bg-yellow-600/5 rounded-lg p-4">
        <div className="mb-3 p-2 border border-yellow-600/30 bg-yellow-600/10 text-yellow-500 text-[9px] font-mono rounded">
          msx_density_candidate NO es densidad física. No representa un recurso mineral ni estimación formal. El modelo LSQR base no fue modificado.
        </div>

        {!enabled && (
          <p className="text-[10px] text-neutral-500 font-mono">
            Focusing no disponible.{focusing.error ? ` Error: ${String(focusing.error)}` : ""}
          </p>
        )}

        {enabled && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <span className={`text-[9px] uppercase tracking-widest px-2 py-1 rounded border font-mono ${scaleStatusInfo.cls}`}>
                {scaleStatusInfo.label}
              </span>
              <span className="text-[9px] text-neutral-400 font-mono px-2 py-1 border border-neutral-800 rounded bg-neutral-950">
                {useModeLabel}
              </span>
            </div>

            {safetyLabels.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {safetyLabels.map((label) => (
                  <span key={label} className="text-[8px] uppercase tracking-widest px-2 py-1 rounded border border-neutral-800 bg-neutral-950 text-neutral-500 font-mono">
                    {label}
                  </span>
                ))}
              </div>
            )}

            {meta && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  ["best_iter", String(meta.best_iter ?? "—")],
                  ["total_iters", String(meta.total_iters ?? "—")],
                  ["converged", String(meta.converged ?? "—")],
                  ["elapsed_s", fmtNum(meta.elapsed_seconds, 2)],
                  ["rms_base", fmtSci(meta.rms_base)],
                  ["rms_best", fmtSci(meta.rms_best)],
                  ["maxd_base", fmtNum(meta.max_density_base, 4)],
                  ["maxd_msx", fmtNum(meta.max_density_msx, 4)],
                ].map(([label, val]) => (
                  <div key={label}>
                    <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">{label}</p>
                    <p className="text-[10px] text-white font-mono">{val}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
