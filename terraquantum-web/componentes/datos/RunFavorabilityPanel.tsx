"use client";

import type { FavorabilityFactor, FavorabilityResult } from "./favorability_types";

interface Props {
  data: FavorabilityResult | null;
  isLoading: boolean;
  error: string | null;
}

type LevelBadge = {
  label: string;
  cls: string;
};

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

function formatMultiplier(value: number) {
  return `x${value.toFixed(2)}`;
}

function getFactorValue(factor: FavorabilityFactor) {
  return typeof factor.value === "number" && Number.isFinite(factor.value)
    ? factor.value
    : null;
}

function getLevelBadge(level: string): LevelBadge {
  const clean = level.trim().toUpperCase();

  if (clean === "MUY ALTO" || clean === "VERY_HIGH") {
    return { label: "MUY ALTO", cls: "text-emerald-400 bg-emerald-900/20 border-emerald-500/30" };
  }
  if (clean === "ALTO" || clean === "HIGH") {
    return { label: "ALTO", cls: "text-[#C2D8C4] bg-[#C2D8C4]/10 border-[#C2D8C4]/30" };
  }
  if (clean === "MODERADO" || clean === "MEDIO" || clean === "MEDIUM") {
    return { label: "MEDIO", cls: "text-yellow-400 bg-yellow-900/20 border-yellow-500/30" };
  }
  if (clean === "BAJO" || clean === "LOW") {
    return { label: "BAJO", cls: "text-orange-400 bg-orange-900/20 border-orange-500/30" };
  }

  return { label: "CRÍTICO", cls: "text-red-400 bg-red-900/20 border-red-500/30" };
}

function getStatusClass(status: string) {
  const clean = status.toLowerCase();
  if (clean === "evaluated") {
    return "text-[#C2D8C4] border-[#C2D8C4]/30 bg-[#C2D8C4]/10";
  }
  if (clean === "not_evaluated") {
    return "text-neutral-500 border-neutral-800 bg-neutral-950";
  }
  return "text-yellow-400 border-yellow-500/30 bg-yellow-900/20";
}

export default function RunFavorabilityPanel({ data, isLoading, error }: Props) {
  if (!isLoading && !data && !error) return null;

  if (isLoading) {
    return (
      <div className="shrink-0 border border-neutral-800 bg-neutral-950/60 rounded-2xl p-6 mt-2">
        <div className="h-2 w-28 bg-neutral-800 rounded-full mb-4 animate-pulse" />
        <div className="h-10 w-20 bg-neutral-800 rounded-lg mb-3 animate-pulse" />
        <p className="text-[10px] text-neutral-500 font-mono uppercase tracking-widest">
          Calculando score de favorabilidad...
        </p>
      </div>
    );
  }

  if (!data && error) {
    const isUnavailable = error.toLowerCase().includes("no disponible");
    return (
      <div
        className={`shrink-0 rounded-2xl p-5 mt-2 border ${
          isUnavailable
            ? "border-neutral-800 bg-neutral-950/50 text-neutral-500"
            : "border-red-900/50 bg-red-950/20 text-red-400"
        }`}
      >
        <p className="text-[10px] font-mono uppercase tracking-widest">
          {isUnavailable ? "Favorabilidad no disponible para esta corrida." : error}
        </p>
      </div>
    );
  }

  if (!data) return null;

  const badge = getLevelBadge(data.level);

  return (
    <div className="shrink-0 border border-neutral-800 bg-neutral-950/60 rounded-2xl p-6 mt-2 space-y-5 print:border-neutral-300 print:bg-transparent">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold border-l-2 border-[#C2D8C4] pl-3 mb-3 print:text-black">
            Score de Favorabilidad Exploratoria
          </p>
          <div className="flex items-end gap-4">
            <p className="text-6xl leading-none font-mono text-white print:text-black">
              {data.score.toFixed(0)}
            </p>
            <div className="pb-1">
              <span className={`text-[10px] uppercase tracking-widest px-3 py-1 rounded-full border font-bold ${badge.cls}`}>
                {badge.label}
              </span>
              <p className="text-[9px] text-neutral-500 font-mono mt-2">
                v{data.version} | {data.computed_at}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 min-w-[220px]">
          <div className="border border-neutral-800 bg-black/30 rounded-lg px-3 py-2 print:border-neutral-300 print:bg-transparent">
            <p className="text-[8px] uppercase tracking-widest text-neutral-600">WES</p>
            <p className="text-[13px] text-white print:text-black font-mono">
              {data.scoring_detail.weighted_evidence_score.toFixed(3)}
            </p>
          </div>
          <div className="border border-neutral-800 bg-black/30 rounded-lg px-3 py-2 print:border-neutral-300 print:bg-transparent">
            <p className="text-[8px] uppercase tracking-widest text-neutral-600">Peso Evaluado</p>
            <p className="text-[13px] text-white print:text-black font-mono">
              {formatPercent(data.scoring_detail.evaluated_weight_sum)}
            </p>
          </div>
        </div>
      </div>

      <div className="border border-neutral-900 bg-black/25 rounded-xl overflow-x-auto print:border-neutral-300 print:bg-transparent">
        <div className="min-w-[720px]">
          <div className="grid grid-cols-[1.4fr_72px_1fr_72px_92px] gap-3 px-4 py-2 border-b border-neutral-900 text-[8px] uppercase tracking-widest text-neutral-600 print:border-neutral-300">
            <span>Factor</span>
            <span>Peso</span>
            <span>Valor</span>
            <span>Puntos</span>
            <span>Status</span>
          </div>
          <div className="divide-y divide-neutral-900 print:divide-neutral-300">
            {data.factors.map((factor) => {
              const value = getFactorValue(factor);
              const barWidth = value === null ? 0 : Math.max(0, Math.min(100, value * 100));

              return (
                <div key={factor.id} className="px-4 py-3">
                  <div className="grid grid-cols-[1.4fr_72px_1fr_72px_92px] gap-3 items-center">
                    <p className="text-[11px] text-white print:text-black font-medium">
                      {factor.label}
                    </p>
                    <p className="text-[10px] text-neutral-400 font-mono">
                      {formatPercent(factor.weight)}
                    </p>
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 bg-neutral-900 rounded-full overflow-hidden print:border print:border-neutral-300">
                        <div
                          className="h-full bg-[#C2D8C4]"
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                      <span className="text-[9px] text-neutral-500 font-mono w-9 text-right">
                        {value === null ? "N/E" : value.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-[10px] text-white print:text-black font-mono">
                      {factor.points.toFixed(1)}
                    </p>
                    <span className={`text-[8px] uppercase tracking-widest px-2 py-1 rounded border text-center font-mono ${getStatusClass(factor.status)}`}>
                      {factor.status}
                    </span>
                  </div>
                  <p className="text-[9px] text-neutral-500 font-mono mt-2 leading-relaxed">
                    {factor.explanation}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="text-[9px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-neutral-800 bg-black/40 text-neutral-300 font-mono print:border-neutral-300 print:bg-transparent print:text-black">
          Gate Calidad: {formatMultiplier(data.gates.quality_gate.multiplier)}
        </span>
        <span className="text-[9px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-neutral-800 bg-black/40 text-neutral-300 font-mono print:border-neutral-300 print:bg-transparent print:text-black">
          Gate Incertidumbre: {formatMultiplier(data.gates.uncertainty_gate.multiplier)}
        </span>
      </div>

      <div className="border border-yellow-700/40 bg-yellow-950/30 text-yellow-300 text-[9px] rounded-lg px-3 py-2 font-mono leading-relaxed print:border-yellow-700 print:bg-white print:text-yellow-800">
        <p className="font-bold uppercase tracking-widest">
          <span aria-hidden="true">⚠</span> ADVERTENCIA: Este score NO confirma mineralización.
        </p>
        <p>
          Es un indicador de convergencia de evidencia geofísica. No sustituye exploración directa ni perforación confirmatoria.
        </p>
      </div>
    </div>
  );
}
