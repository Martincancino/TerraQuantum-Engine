"use client";
import { useMemo } from "react";
import ExecutiveSummaryPanel from "./ExecutiveSummaryPanel";
import AnomaliesGrid from "./AnomaliesGrid";
import OverallAssessmentPanel from "./OverallAssessmentPanel";
import ComplianceLimitationsPanel from "./ComplianceLimitationsPanel";

// ─── Types ────────────────────────────────────────────────────────────────────

export type GeminiAnomalyPriority = "HIGH" | "MEDIUM" | "LOW";

export type GeminiAnomaly = {
  id: string;
  description: string;
  density_mean: number;
  susceptibility_mean: number;
  volume_m3: number;
  priority: GeminiAnomalyPriority;
};

export type GeminiInterpretation = {
  executive_summary: string;
  anomalies: GeminiAnomaly[];
  overall_assessment: string;
  limitations: string;
};

// ─── Component ────────────────────────────────────────────────────────────────

type Props = {
  interpretation: GeminiInterpretation;
};

export default function GeophysicalInterpretationSection({ interpretation }: Props) {
  const anomalies = useMemo(
    () => interpretation.anomalies ?? [],
    [interpretation.anomalies]
  );

  return (
    <div className="space-y-3">
      <p className="text-[9px] uppercase tracking-[0.22em] text-neutral-500 font-bold border-l-2 border-neutral-700 pl-3">
        Interpretación Geofísica — IA
      </p>
      <div className="flex flex-col gap-4">
        <ExecutiveSummaryPanel summary={interpretation.executive_summary} />
        {anomalies.length > 0 && <AnomaliesGrid anomalies={anomalies} />}
        <OverallAssessmentPanel assessment={interpretation.overall_assessment} />
        <ComplianceLimitationsPanel limitations={interpretation.limitations} />
      </div>
    </div>
  );
}
