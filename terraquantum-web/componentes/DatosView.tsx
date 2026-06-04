// components/DatosView.tsx
"use client";
import { useEffect, useMemo, useState } from "react";
import { useAppStore, type GeoReportInfo, type ActiveRunState } from "../store/useAppStore";
import type { JsonValue } from "./datos/types";
import {
  safeNumber,
  safeString,
  safeArray,
  asRecord,
  readString,
  readNumber,
  readArrayLength,
} from "./datos/helpers";
import RunFocusingPanel from "./datos/RunFocusingPanel";
import RunFavorabilityPanel from "./datos/RunFavorabilityPanel";
import {
  downloadTechnicalReport,
  exportBundleUrl,
  getFavorability,
  getProjectRunDetail,
} from "../lib/terraquantum/frontendApi";
import type { FavorabilityResult } from "./datos/favorability_types";
import GeophysicalInterpretationSection, {
  type GeminiInterpretation,
} from "@/componentes/interpretation/GeophysicalInterpretationSection";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mapPriorityClassLabel(value: string | null | undefined): string {
  const v = String(value || "").toUpperCase().trim();
  if (v === "HIGH_RELATIVE_PRIORITY" || v === "DRILL")   return "Prioridad relativa alta";
  if (v === "MEDIUM_RELATIVE_PRIORITY" || v === "OBSERVE" || v === "WAIT") return "Prioridad relativa media";
  if (v === "LOW_RELATIVE_PRIORITY") return "Prioridad relativa baja";
  if (v === "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE" || v === "UNCLASSIFIED") return "Sin clasificar";
  return v || "N/A";
}

function readOptionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readOptionalText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

function probabilityPercent(value: unknown): number {
  const p = readOptionalNumber(value) ?? 0;
  return p <= 1 ? Math.round(p * 100) : Math.round(p);
}

function buildDatosReportFromRunDetail(
  detail: Record<string, unknown> | null,
  persistedReport: Record<string, unknown>
): GeoReportInfo {
  const inputs                = asRecord(detail?.inputs);
  const fitDiagnostics        = asRecord(persistedReport.fitDiagnostics);
  const observationQuality    = asRecord(persistedReport.observationQuality);
  const technicalSummary      = asRecord(persistedReport.technicalSummary);
  const uncertaintyDiagnostics = asRecord(persistedReport.uncertaintyDiagnostics);
  const bestTarget            = asRecord(persistedReport.best_target);

  const bestTargetProbability = probabilityPercent(bestTarget?.probability);
  const bestTargetDepth       = readOptionalNumber(bestTarget?.z_m) ?? 0;
  const estimatedTonnage      =
    readOptionalNumber(persistedReport.estimated_anomaly_tonnage) ??
    readOptionalNumber(persistedReport.estimated_total_tonnage) ?? 0;

  // DV-02: detectar run degenerado (misfit NaN + sin best_target = la inversión no recuperó nada)
  const rawMisfit = persistedReport.misfit_error_percent;
  const misfitIsDegenerate =
    rawMisfit === null ||
    rawMisfit === undefined ||
    (typeof rawMisfit === "number" && !Number.isFinite(rawMisfit));
  const isDegraded = bestTarget === null && misfitIsDegenerate;

  return {
    ...persistedReport,
    isDegraded,
    profundidad:
      readOptionalNumber(inputs?.depth) ??
      readOptionalNumber(bestTarget?.z_m) ??
      readOptionalNumber(persistedReport.profundidad),
    masaKg: estimatedTonnage,
    anomaliaPico:
      readOptionalNumber(persistedReport.max_density) ??
      readOptionalNumber(persistedReport.avg_density),
    clasificacionEstructural:
      readOptionalText(persistedReport.recommendation) ??
      readOptionalText(persistedReport.drill_recommendation) ?? "No disponible",
    contrasteDensidad:
      readOptionalNumber(persistedReport.avg_density) !== undefined ||
      readOptionalNumber(persistedReport.max_density) !== undefined
        ? `${(readOptionalNumber(persistedReport.avg_density) ?? 0).toFixed(3)} g/cm³`
        : readOptionalText(persistedReport.density_contrast) ?? "No disponible",
    leyPromedio:
      readOptionalText(persistedReport.density_proxy_index) ??
      readOptionalText(persistedReport.ley_promedio) ?? "No disponible",
    firmaSuperficial:
      readOptionalText(persistedReport.surface_signature) ??
      readOptionalText(persistedReport.firma_superficial) ?? "Baja",
    indiceAnomalia:
      readOptionalNumber(persistedReport.anomaly_score) ??
      readOptionalNumber(persistedReport.indice_anomalia) ?? 0,
    zonaGeografica:
      readOptionalText(persistedReport.region) ??
      readOptionalText(inputs?.region) ?? "Desconocida",
    justificacion:
      readOptionalText(persistedReport.interpretation) ??
      readOptionalText(persistedReport.justificacion) ??
      readOptionalText(technicalSummary?.summary) ?? "Sin justificación disponible.",
    score:
      readOptionalNumber(fitDiagnostics?.fit_quality) ??
      readOptionalNumber(observationQuality?.quality_score) ?? 0,
    uncertainty: readOptionalNumber(uncertaintyDiagnostics?.uncertainty_score) ?? 0,
    rankingTargets: bestTarget
      ? [{
          id: "BT-01",
          coordenadas: `X ${safeNumber(bestTarget.x_m).toFixed(1)}, Y ${safeNumber(bestTarget.y_m).toFixed(1)}, Z ${safeNumber(bestTarget.z_m).toFixed(1)}`,
          profundidad: bestTargetDepth,
          probabilidad: bestTargetProbability,
          estado:
            readOptionalText(persistedReport.recommendation) ??
            readOptionalText(persistedReport.drill_recommendation) ?? "OBSERVACION",
        }]
      : [],
  };
}

// ─── KPI Card ────────────────────────────────────────────────────────────────
function KpiCard({ label, value, unit, highlight = false }: {
  label: string; value: string | number; unit: string; highlight?: boolean;
}) {
  return (
    <div className="bg-neutral-950/60 border border-neutral-800 rounded-2xl p-5 flex flex-col gap-1">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500">{label}</p>
      <p className={`text-2xl font-mono font-light ${highlight ? "text-accent" : "text-white"}`}>
        {value} <span className="text-xs text-neutral-600">{unit}</span>
      </p>
    </div>
  );
}

// ─── Section header ───────────────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <p className="text-[9px] uppercase tracking-[0.22em] text-neutral-500 font-bold border-l-2 border-neutral-700 pl-3">
        {title}
      </p>
      {children}
    </div>
  );
}

// ─── Download button ──────────────────────────────────────────────────────────
function DlButton({ onClick, disabled, loading, label, icon, variant = "default" }: {
  onClick?: () => void; disabled?: boolean; loading?: boolean;
  label: string; icon: string;
  variant?: "default" | "primary" | "danger";
}) {
  const cls = {
    default: "border-neutral-700 text-neutral-300 hover:border-neutral-500 hover:text-white bg-neutral-950",
    primary: "border-accent/40 text-accent hover:bg-accent hover:text-black bg-accent/10",
    danger:  "border-red-800/50 text-red-400 hover:bg-red-900/20 bg-neutral-950",
  }[variant];

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border text-[9px] uppercase tracking-widest font-bold transition-all disabled:opacity-40 ${cls}`}
    >
      <span>{icon}</span>
      <span>{loading ? "Generando…" : label}</span>
    </button>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function DatosView() {
  const {
    activeRun, report, setReport,
    favorabilityResult, setFavorabilityResult, setFavorabilityGate,
  } = useAppStore();

  const [isDownloadingHTML, setIsDownloadingHTML] = useState(false);
  const [isExportingPDF,    setIsExportingPDF]    = useState(false);
  const [isAutoLoading,     setIsAutoLoading]      = useState(false);
  const [autoError,         setAutoError]          = useState<string | null>(null);
  const [isFavLoading,      setIsFavLoading]       = useState(false);
  const [favError,          setFavError]           = useState<string | null>(null);

  // Auto-load report when active run changes
  useEffect(() => {
    if (!activeRun.projectId || !activeRun.runId || activeRun.status !== "ready") return;
    if (report) return;

    let isMounted = true;

    const loadReport = async () => {
      setIsAutoLoading(true);
      setAutoError(null);

      const result = await getProjectRunDetail(activeRun.projectId!, activeRun.runId!);
      if (!isMounted) return;
      if (!result.ok || !result.data) {
        setAutoError(result.error || "No se pudo cargar el reporte de la corrida activa.");
        setIsAutoLoading(false);
        return;
      }
      const detail = asRecord(result.data);
      const persistedReport = asRecord(detail?.report);
      if (!persistedReport) {
        setAutoError("La corrida activa no tiene report.json disponible.");
        setIsAutoLoading(false);
        return;
      }
      setReport(buildDatosReportFromRunDetail(detail, persistedReport));
      setIsAutoLoading(false);
    };

    loadReport();

    return () => { isMounted = false; };
  }, [activeRun.projectId, activeRun.runId, activeRun.status, report, setReport]);

  // Load favorability
  useEffect(() => {
    if (!activeRun.projectId || !activeRun.runId || activeRun.status !== "ready") {
      setFavorabilityResult(null);
      setFavorabilityGate(null, null);
      return;
    }
    let isMounted = true;

    const loadFavorability = async () => {
      setFavorabilityResult(null);
      setFavorabilityGate(null, null);
      setFavError(null);
      setIsFavLoading(true);

      const result = await getFavorability(activeRun.projectId!, activeRun.runId!);
      if (!isMounted) return;
      if (result.ok && result.data) {
        const fav = result.data as FavorabilityResult;
        setFavorabilityResult(fav);
        setFavorabilityGate(fav.score ?? null, fav.level ?? null);
      } else {
        setFavorabilityGate(null, null);
        setFavError(result.status === 404
          ? "Favorabilidad no disponible para esta corrida."
          : result.error ?? "Error cargando favorabilidad.");
      }
      setIsFavLoading(false);
    };

    loadFavorability();

    return () => { isMounted = false; };
  }, [activeRun.projectId, activeRun.runId, activeRun.status, setFavorabilityGate, setFavorabilityResult]);

  const handleDownloadHTML = async () => {
    if (!activeRun.projectId || !activeRun.runId) return;
    setIsDownloadingHTML(true);
    try {
      await downloadTechnicalReport(activeRun.projectId, activeRun.runId);
    } catch { /* handled */ }
    setIsDownloadingHTML(false);
  };

  const handleExportPDF = () => {
    window.print();
  };

  const geminiInterpretation = useMemo<GeminiInterpretation | null>(() => {
    const gi = asRecord(report?.gemini_interpretation);
    if (!gi || typeof gi.error === "string") return null;
    return gi as unknown as GeminiInterpretation;
  }, [report?.gemini_interpretation]);

  // ── Estado: sin corrida activa ────────────────────────────────────────────
  const hasActiveRun = activeRun.status === "ready" && activeRun.projectId && activeRun.runId;

  if (!hasActiveRun) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4 text-neutral-600">
        <span className="text-4xl">◎</span>
        <p className="text-[10px] uppercase tracking-widest">Sin corrida activa</p>
        <p className="text-[9px] text-neutral-700 font-mono max-w-xs text-center leading-relaxed">
          Carga un modelo desde Figura 3D o selecciona una corrida en Historial para ver los datos analíticos.
        </p>
      </div>
    );
  }

  // ── Estado: cargando ─────────────────────────────────────────────────────
  if (isAutoLoading) {
    return (
      <div className="h-full flex items-center justify-center text-neutral-500 text-[10px] font-mono uppercase tracking-widest">
        Cargando análisis de corrida…
      </div>
    );
  }

  // ── Estado: error en carga ────────────────────────────────────────────────
  if (autoError && !report) {
    return (
      <div className="h-full flex flex-col gap-4 overflow-y-auto custom-scrollbar pb-12 pr-1">
        <RunHeader activeRun={activeRun} />
        <div className="border border-yellow-800/40 bg-yellow-900/10 text-yellow-400 text-[10px] font-mono rounded-xl px-4 py-3">
          {autoError}
        </div>
        <div className="flex-1 flex items-center justify-center border border-dashed border-neutral-800 rounded-2xl text-neutral-700 text-[9px] uppercase tracking-widest">
          No hay datos de análisis disponibles para esta corrida.
        </div>
      </div>
    );
  }

  // ── Vista completa ────────────────────────────────────────────────────────
  return (
    <div className="h-full overflow-y-auto custom-scrollbar pb-12 pr-1 print:overflow-visible print:bg-white print:text-black">
      <div className="flex flex-col gap-7">

        {/* ── Cabecera de corrida + Exportaciones ── */}
        <div className="flex items-start justify-between gap-4 shrink-0">
          <RunHeader activeRun={activeRun} />
          <ExportBar
            hasRun={!!hasActiveRun}
            projectId={activeRun.projectId!}
            runId={activeRun.runId!}
            onDownloadHTML={handleDownloadHTML}
            onExportPDF={handleExportPDF}
            isDownloadingHTML={isDownloadingHTML}
            isExportingPDF={isExportingPDF}
          />
        </div>

        {/* ── Banner: modelo degenerado (DV-02) ── */}
        {report?.isDegraded && (
          <div className="border border-red-700/50 bg-red-900/10 rounded-xl px-4 py-3 flex items-start gap-3">
            <span className="text-red-500 text-base leading-none mt-0.5">⚠</span>
            <div>
              <p className="text-red-400 text-[10px] font-mono font-bold uppercase tracking-widest mb-0.5">
                Modelo no recuperado
              </p>
              <p className="text-red-400/70 text-[9px] font-mono leading-relaxed">
                La inversión no recuperó ningún cuerpo anómalo (misfit indefinido, sin target).
                Los indicadores a continuación no tienen validez física.
              </p>
            </div>
          </div>
        )}

        {/* ── KPIs principales ── */}
        {report && (
          <Section title="Indicadores principales">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard
                label="Densidad máx. anómalo"
                value={report.anomaliaPico !== undefined ? `${safeNumber(report.anomaliaPico).toFixed(3)}` : "—"}
                unit="t/m³"
              />
              <KpiCard label="Cota de techo (Z)"  value={String(report.profundidad ?? "—")}  unit="m" />
              <KpiCard label="Volumen anómalo"    value={(safeNumber(report.masaKg) / 1000).toFixed(1)} unit="Ton" />
              <KpiCard label="Score relativo"
                value={String(report.indiceAnomalia ?? "—")} unit="/ 100"
                highlight={safeNumber(report.indiceAnomalia) > 85}
              />
            </div>
          </Section>
        )}

        {/* ── Favorabilidad ── */}
        <Section title="Score de favorabilidad exploratoria">
          <RunFavorabilityPanel
            data={favorabilityResult}
            isLoading={isFavLoading}
            error={favError}
          />
        </Section>

        {/* ── Targets geofísicos ── */}
        {report && safeArray(report.rankingTargets).length > 0 && (
          <Section title="Ranking de targets geofísicos">
            <div className="flex flex-col gap-3">
              {safeArray(report.rankingTargets).map((target, idx) => {
                const t = asRecord(target);
                const estado      = safeString(t?.estado);
                const id          = safeString(t?.id);
                const coordenadas = safeString(t?.coordenadas);
                const profundidad = safeNumber(t?.profundidad);
                const probabilidad = safeNumber(t?.probabilidad);

                return (
                  <div
                    key={idx}
                    className={`p-5 rounded-xl border flex items-center justify-between gap-4 ${
                      idx === 0 && estado === "HIGH_RELATIVE_PRIORITY"
                        ? "bg-accent/5 border-accent/30"
                        : estado === "DESCARTADO"
                        ? "bg-red-900/10 border-red-900/40"
                        : "bg-neutral-950 border-neutral-800"
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-3 mb-1.5">
                        <span className={`text-sm font-bold ${idx === 0 && estado === "HIGH_RELATIVE_PRIORITY" ? "text-accent" : "text-white"}`}>
                          {id}
                        </span>
                        <span className={`text-[8px] font-bold px-2.5 py-0.5 rounded uppercase tracking-widest ${
                          estado === "HIGH_RELATIVE_PRIORITY"
                            ? "bg-accent text-black"
                            : estado === "LOW_RELATIVE_PRIORITY"
                            ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/40"
                            : "bg-red-900/30 text-red-400 border border-red-900/50"
                        }`}>
                          {mapPriorityClassLabel(estado)}
                        </span>
                      </div>
                      <p className="text-[9px] text-neutral-400 font-mono">
                        {coordenadas} · Z-{profundidad}m
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[8px] text-neutral-500 uppercase tracking-widest mb-1">Score</p>
                      <p className={`text-3xl font-bold font-mono ${probabilidad >= 80 ? "text-accent" : "text-white"}`}>
                        {probabilidad}%
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* ── Dictamen algorítmico ── */}
        {report && (
          <Section title="Interpretación">
            <div className="grid md:grid-cols-3 gap-4">
              {/* Panel de clasificación */}
              <div className="bg-neutral-950/60 border border-neutral-800 rounded-2xl p-5 flex flex-col gap-3">
                <p className="text-[8px] uppercase tracking-widest text-neutral-500">Clasificación estructural</p>
                <p className={`text-xl font-bold leading-tight ${
                  safeString(report.clasificacionEstructural).includes("Descartado") ||
                  safeString(report.clasificacionEstructural).includes("Sin Target")
                    ? "text-red-400" : "text-accent"
                }`}>
                  {report.clasificacionEstructural}
                </p>
                <div className="border-t border-neutral-800 pt-3 space-y-2 text-[9px]">
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Densidad</span>
                    <span className="text-white font-mono">{report.contrasteDensidad}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Índice interés</span>
                    <span className="text-white font-mono">{report.leyPromedio}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Alteración SWIR</span>
                    <span className="text-white font-mono">{report.firmaSuperficial}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Confianza</span>
                    <span className="text-white font-mono">{(safeNumber(report.score) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>

              {/* Dictamen */}
              <div className="md:col-span-2 bg-neutral-950/30 border border-neutral-800 rounded-2xl p-5 relative">
                <div className="absolute top-0 left-0 w-1 h-full bg-accent/40 rounded-l-2xl" />
                <p className="text-[8px] uppercase tracking-widest text-accent mb-3 ml-2">Dictamen algorítmico integral</p>
                <p className="text-[11px] text-neutral-300 leading-loose font-light whitespace-pre-wrap ml-2">
                  {report.justificacion}
                </p>
              </div>
            </div>
          </Section>
        )}

        {/* ── Interpretación Gemini ── */}
        {geminiInterpretation && (
          <GeophysicalInterpretationSection interpretation={geminiInterpretation} />
        )}

        {/* ── Datos de la corrida activa ── */}
        {hasActiveRun && (
          <Section title="Metadatos de la corrida">
            <ActiveRunMeta activeRun={activeRun} report={report} />
          </Section>
        )}

        {/* ── Focusing ── */}
        {activeRun.focusing && (
          <Section title="Focusing">
            <RunFocusingPanel focusingData={activeRun.focusing} />
          </Section>
        )}

      </div>
    </div>
  );
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function RunHeader({ activeRun }: { activeRun: ActiveRunState }) {
  return (
    <div>
      <h1 className="text-[13px] uppercase tracking-[0.22em] text-white font-bold">
        Análisis de Inversión
      </h1>
      <p className="text-[9px] text-neutral-500 font-mono mt-0.5">
        {activeRun.runId
          ? <>Run: <span className="text-accent">{activeRun.runId}</span></>
          : "Sin corrida activa"}
      </p>
    </div>
  );
}

function ExportBar({
  hasRun, projectId, runId, onDownloadHTML, onExportPDF, isDownloadingHTML, isExportingPDF,
}: {
  hasRun: boolean; projectId: string; runId: string;
  onDownloadHTML: () => void; onExportPDF: () => void;
  isDownloadingHTML: boolean; isExportingPDF: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2 shrink-0 print:hidden">
      {hasRun && (
        <>
          {/* CSV / ZIP bundle */}
          <a
            href={exportBundleUrl(projectId, runId)}
            download
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-neutral-700 bg-neutral-950 text-neutral-300 text-[9px] uppercase tracking-widest font-bold hover:border-neutral-500 hover:text-white transition-all"
          >
            <span>↓</span><span>CSV / ZIP</span>
          </a>

          {/* HTML report */}
          <DlButton
            icon="↓" label="Reporte HTML"
            onClick={onDownloadHTML}
            loading={isDownloadingHTML}
          />

          {/* PDF */}
          <DlButton
            icon="↓" label="Imprimir"
            onClick={onExportPDF}
            variant="primary"
          />
        </>
      )}
    </div>
  );
}

function ActiveRunMeta({
  activeRun,
  report,
}: {
  activeRun: ActiveRunState;
  report: GeoReportInfo | null;
}) {
  const { importMetadata, observationsSummary, reportSummary } = activeRun;

  return (
    <div className="bg-neutral-950/50 border border-neutral-800 rounded-2xl p-5 relative overflow-hidden">
      <div className="absolute top-0 left-0 w-0.5 h-full bg-accent/30" />
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-x-6 gap-y-4 pl-3">
        <MetaItem label="Project ID" value={activeRun.projectId} />
        <MetaItem label="Run ID"     value={activeRun.runId} />
        <MetaItem label="Source"     value={activeRun.source?.toUpperCase()} />
        <MetaItem label="Status"     value={activeRun.status?.toUpperCase()} highlight />
        {activeRun.error && (
          <div className="col-span-2 md:col-span-4 border border-red-900/50 bg-red-950/20 p-2 rounded text-[9px] text-red-400 font-mono">
            {activeRun.error}
          </div>
        )}
        {importMetadata && (
          <>
            {readString(importMetadata.source_file)  && <MetaItem label="Archivo fuente"  value={readString(importMetadata.source_file)} />}
            {readString(importMetadata.unit_original) && <MetaItem label="Unidad original" value={readString(importMetadata.unit_original)} />}
            {readString(importMetadata.gravity_type)  && <MetaItem label="Gravity type"    value={readString(importMetadata.gravity_type)} />}
          </>
        )}
        {observationsSummary && (
          <>
            {readNumber(observationsSummary.totalObservations as JsonValue, -1) !== -1 && (
              <MetaItem label="Observaciones"  value={String(readNumber(observationsSummary.totalObservations as JsonValue, 0))} />
            )}
            {readArrayLength(observationsSummary.warnings) !== null && (
              <MetaItem label="Warnings" value={String(readArrayLength(observationsSummary.warnings) ?? 0)} />
            )}
          </>
        )}
        {reportSummary && (
          <>
            {readString(reportSummary.fit_level)          && <MetaItem label="Fit level"        value={readString(reportSummary.fit_level)} />}
            {readString(reportSummary.confidence_level)   && <MetaItem label="Confidence"       value={readString(reportSummary.confidence_level)} />}
          </>
        )}
        {report && (
          <MetaItem label="Región" value={safeString(report.zonaGeografica).toUpperCase()} />
        )}
      </div>
    </div>
  );
}

function MetaItem({ label, value, highlight = false }: { label: string; value?: string | number | null; highlight?: boolean }) {
  return (
    <div>
      <p className="text-[7px] uppercase tracking-widest text-neutral-600 mb-0.5">{label}</p>
      <p className={`text-[10px] font-mono ${highlight ? "text-accent" : "text-white"}`}>
        {value ?? "—"}
      </p>
    </div>
  );
}
