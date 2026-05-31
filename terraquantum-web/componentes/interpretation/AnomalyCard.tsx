import { memo } from "react";
import type { GeminiAnomaly, GeminiAnomalyPriority } from "./GeophysicalInterpretationSection";

const PRIORITY_STYLES: Record<
  GeminiAnomalyPriority,
  { bg: string; text: string; border: string }
> = {
  HIGH: {
    bg: "bg-[rgba(30,120,70,0.15)]",
    text: "text-emerald-400",
    border: "border-emerald-800/50",
  },
  MEDIUM: {
    bg: "bg-[rgba(180,130,20,0.15)]",
    text: "text-amber-400",
    border: "border-amber-700/50",
  },
  LOW: {
    bg: "bg-[rgba(60,80,140,0.15)]",
    text: "text-blue-400",
    border: "border-blue-800/50",
  },
};

function formatVolume(m3: number): string {
  if (m3 >= 1e9) return `${(m3 / 1e9).toFixed(2)} km³`;
  if (m3 >= 1e6) return `${(m3 / 1e6).toFixed(2)} Mm³`;
  return `${m3.toLocaleString(undefined, { maximumFractionDigits: 0 })} m³`;
}

type Props = { anomaly: GeminiAnomaly };

const AnomalyCard = memo(function AnomalyCard({ anomaly }: Props) {
  const style = PRIORITY_STYLES[anomaly.priority] ?? PRIORITY_STYLES.LOW;

  return (
    <div className="bg-neutral-950/60 border border-neutral-800 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold font-mono text-white">{anomaly.id}</span>
        <span
          className={`text-[7px] font-bold px-2 py-0.5 rounded uppercase tracking-widest border ${style.bg} ${style.text} ${style.border}`}
        >
          {anomaly.priority}
        </span>
      </div>

      <p className="text-[10px] text-neutral-400 leading-relaxed">
        {anomaly.description}
      </p>

      <div className="grid grid-cols-3 gap-2 border-t border-neutral-800 pt-3">
        <div>
          <p className="text-[7px] uppercase tracking-widest text-neutral-600 mb-0.5">ρ_mean</p>
          <p className="text-[10px] font-mono text-white">{anomaly.density_mean.toFixed(3)}</p>
          <p className="text-[7px] text-neutral-600">g/cm³</p>
        </div>
        <div>
          <p className="text-[7px] uppercase tracking-widest text-neutral-600 mb-0.5">χ_mean</p>
          <p className="text-[10px] font-mono text-white">{anomaly.susceptibility_mean.toFixed(5)}</p>
          <p className="text-[7px] text-neutral-600">SI</p>
        </div>
        <div>
          <p className="text-[7px] uppercase tracking-widest text-neutral-600 mb-0.5">Vol.</p>
          <p className="text-[10px] font-mono text-white">{formatVolume(anomaly.volume_m3)}</p>
        </div>
      </div>
    </div>
  );
});

export default AnomalyCard;
