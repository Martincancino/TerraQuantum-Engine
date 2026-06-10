"use client";
import { readText, compareDeltaFields } from "./helpers";
import type { SelectedRun, CompareResult } from "./types";

interface RunComparePanelProps {
  baseRun: SelectedRun | null;
  compareRun: SelectedRun | null;
  compareResult: CompareResult | null;
  loadingCompare: boolean;
}

export default function RunComparePanel({
  baseRun,
  compareRun,
  compareResult,
  loadingCompare,
}: RunComparePanelProps) {
  return (
    <div className="border border-neutral-800 bg-black/40 rounded-xl p-4 mb-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
        <div>
          <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Base</p>
          <p className="text-[10px] text-[#C2D8C4] font-mono">
            {baseRun ? `${baseRun.projectId} / ${baseRun.runId}` : "No disponible"}
          </p>
        </div>
        <div>
          <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Comparar</p>
          <p className="text-[10px] text-white font-mono">
            {compareRun ? `${compareRun.projectId} / ${compareRun.runId}` : "No disponible"}
          </p>
        </div>
      </div>


      {loadingCompare ? (
        <p className="text-[10px] text-neutral-500">Comparando corridas...</p>
      ) : null}

      {compareResult && !loadingCompare ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[10px] font-mono">
            <thead className="text-neutral-600 uppercase">
              <tr>
                <th className="pb-2 pr-4 font-normal">delta</th>
                <th className="pb-2 pr-4 font-normal">valor</th>
              </tr>
            </thead>
            <tbody className="text-neutral-300">
              {compareDeltaFields.map((field) => (
                <tr key={field} className="border-t border-neutral-900">
                  <td className="py-2 pr-4">{field}</td>
                  <td className="py-2 pr-4">{readText(compareResult.deltas[field])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
