"use client";
import { useAppStore } from "../store/useAppStore";

export default function InversionQualityBadge() {
  const report = useAppStore((s) => s.report);
  const show3D = useAppStore((s) => s.show3D);
  const model = useAppStore((s) => s.model);

  if (!show3D || !model || !report) return null;

  const backendReport = (report as Record<string, unknown>)?.backendReport as Record<string, unknown> | null;
  const techSummary = backendReport?.technicalSummary as Record<string, unknown> | null;
  const overallLevel = techSummary?.overall_level as string | undefined;

  let label: string;
  let cls: string;

  if (overallLevel === "GOOD") {
    label = "Inversión: BUENA";
    cls = "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  } else if (overallLevel === "MEDIUM") {
    label = "Inversión: ACEPTABLE";
    cls = "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  } else {
    label = "Inversión: REVISAR";
    cls = "text-red-400 border-red-500/40 bg-red-500/10";
  }

  return (
    <p
      className={`text-[8px] uppercase tracking-[0.2em] font-bold px-2 py-1 rounded border w-max mt-1 ${cls}`}
    >
      {label}
    </p>
  );
}
