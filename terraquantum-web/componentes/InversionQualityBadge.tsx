"use client";
import { useAppStore } from "../store/useAppStore";

export default function InversionQualityBadge() {
  const report = useAppStore((s) => s.report);
  const show3D = useAppStore((s) => s.show3D);
  const model = useAppStore((s) => s.model);

  if (!show3D || !model || !report) return null;

  const backendReport = (report as Record<string, unknown>)?.backendReport as Record<string, unknown> | null;

  // B3: el badge usa el VEREDICTO ÚNICO reconciliado (eslabón más débil), no la calidad
  // cruda del survey — así deja de decir "BUENA" cuando el veredicto real es BAJO
  // (p.ej. LdM: survey GOOD pero blanco null-space / sin clasificar). Fallback al
  // overall_level histórico si la corrida no trae overall_verdict.
  const verdict = backendReport?.overall_verdict as Record<string, unknown> | null;
  const verdictLevel = String((verdict?.level as string) || "").toUpperCase();
  const techSummary = backendReport?.technicalSummary as Record<string, unknown> | null;
  const overallLevel = techSummary?.overall_level as string | undefined;

  let label: string;
  let cls: string;

  const goodCls = "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10";
  const warnCls = "text-yellow-400 border-yellow-500/40 bg-yellow-500/10";
  const badCls = "text-red-400 border-red-500/40 bg-red-500/10";

  if (verdictLevel === "HIGH") {
    label = "Veredicto: CONFIABLE";
    cls = goodCls;
  } else if (verdictLevel === "MEDIUM") {
    label = "Veredicto: CON CAUTELA";
    cls = warnCls;
  } else if (verdictLevel === "LOW") {
    label = "Veredicto: INDICIO — REVISAR";
    cls = badCls;
  } else if (overallLevel === "GOOD") {
    label = "Inversión: BUENA";
    cls = goodCls;
  } else if (overallLevel === "MEDIUM") {
    label = "Inversión: ACEPTABLE";
    cls = warnCls;
  } else {
    label = "Inversión: REVISAR";
    cls = badCls;
  }

  return (
    <p
      className={`text-[8px] uppercase tracking-[0.2em] font-bold px-2 py-1 rounded border w-max mt-1 ${cls}`}
    >
      {label}
    </p>
  );
}
