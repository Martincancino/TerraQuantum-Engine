"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { useAppStore } from "../../store/useAppStore";
import Panel from "../workspace/Panel";
import { asRec } from "./analyticsShared";
import { useRunDiagnostics } from "./useRunDiagnostics";
import SolverDiagnosticsWidget from "./SolverDiagnosticsWidget";
import DoiConfidenceWidget from "./DoiConfidenceWidget";
import { NoiseSnrWidget, UncertaintyPosteriorWidget } from "./NoiseUncertaintyWidgets";
import LCurveWidget from "./LCurveWidget";
import { SensorCoverageWidget, RecoveryWidget } from "./RecoveryCoverageWidgets";

/** Entrada escalonada (Fase E — microinteracciones) preservando el gap del slot. */
function FadePanel({ index, children }: { index: number; children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut", delay: Math.min(index, 8) * 0.04 }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Panel de analytics científico del viewport 3D (Fase D).
 * Consume únicamente datos del backend (report/inputs/metrics/observations del run
 * + posterior_std/doi_raw por vóxel). No calcula física.
 */
export default function AnalyticsPanel() {
  const activeRun = useAppStore((s) => s.activeRun);
  const model = useAppStore((s) => s.model);
  const storeReport = useAppStore((s) => s.report);

  const { data, loading, error } = useRunDiagnostics(
    activeRun.projectId,
    activeRun.runId,
    activeRun.status
  );

  // Fuente de report: detalle del run (autoritativo) con fallback al backendReport
  // ya presente en el store (corridas recién ejecutadas).
  const backendReport = asRec(
    (storeReport as Record<string, unknown> | null)?.backendReport
  );
  const report = data?.report ?? backendReport;
  const inputs = data?.inputs ?? null;
  const metrics = data?.metrics ?? null;
  const observations = data?.observations ?? [];
  const cells = (model?.cells ?? []) as Record<string, unknown>[];

  if (!model) return null;

  return (
    <>
      <FadePanel index={0}>
        <Panel title="Solver" subtitle="Convergencia y ajuste de la inversión">
          <SolverDiagnosticsWidget report={report} inputs={inputs} metrics={metrics} />
        </Panel>
      </FadePanel>

      <FadePanel index={1}>
        <Panel title="DOI Confidence" subtitle="Profundidad de investigación (Li & Oldenburg)">
          <DoiConfidenceWidget report={report} cells={cells} />
        </Panel>
      </FadePanel>

      <FadePanel index={2}>
        <Panel title="Ruido / SNR" subtitle="Calidad de señal observada">
          <NoiseSnrWidget report={report} />
        </Panel>
      </FadePanel>

      <FadePanel index={3}>
        <Panel title="Incertidumbre posterior" subtitle="σ por vóxel (Hutchinson)">
          <UncertaintyPosteriorWidget report={report} cells={cells} />
        </Panel>
      </FadePanel>

      <FadePanel index={4}>
        <Panel title="L-Curve" subtitle="Sensibilidad a la regularización λ">
          <LCurveWidget inputs={inputs} observations={observations} />
        </Panel>
      </FadePanel>

      <FadePanel index={5}>
        <Panel title="Cobertura de sensores" subtitle="Planta X/Z del survey">
          <SensorCoverageWidget report={report} observations={observations} />
        </Panel>
      </FadePanel>

      <FadePanel index={6}>
        <Panel title="Recuperación sintética" subtitle="Benchmark de resolución">
          <RecoveryWidget report={report} metrics={metrics} />
        </Panel>
      </FadePanel>

      {loading && !report && (
        <p className="text-[8px] text-white/35 font-mono px-1">Cargando diagnósticos…</p>
      )}
      {error && !report && (
        <p className="text-[8px] text-yellow-400/70 font-mono px-1 leading-tight">
          Diagnósticos del run no disponibles: {error}
        </p>
      )}
    </>
  );
}
