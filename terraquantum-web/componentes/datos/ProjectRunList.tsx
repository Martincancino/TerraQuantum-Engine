"use client";
import { useEffect, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import {
  compareRuns,
  exportRunUrl,
  fetchProjectFootprint,
  getExplorationBlockModelForRun,
  getProjectRunDetail,
  getProjectRuns,
  runGeophysicsSensitivitySweep,
  type SensitivitySweepResult,
} from "../../lib/terraquantum/frontendApi";

// Badge georef mínimo para la corrida activa
function miniGeorefBadge(confidence?: string | null): { label: string; cls: string } {
  const c = (confidence ?? "MISSING").toUpperCase();
  if (c === "HIGH") return { label: "GEOREF: ALTA", cls: "text-green-400 border-green-600/40 bg-green-900/20" };
  if (c === "MEDIUM") return { label: "GEOREF: MEDIA", cls: "text-yellow-400 border-yellow-600/40 bg-yellow-900/20" };
  if (c === "LOW") return { label: "GEOREF: BAJA", cls: "text-orange-400 border-orange-600/40 bg-orange-900/20" };
  return { label: "SIN GEOREF", cls: "text-red-400 border-red-600/40 bg-red-900/20" };
}
import type {
  ProjectRunsViewData,
  ProjectRunDetail,
  SelectedRun,
  CompareResult,
  JsonObject,
} from "./types";
import {
  asRecord,
  fmtNum,
  fmtSci,
  levelCls,
  readText,
  parseProjectRuns,
  parseProjectRunDetail,
  parseCompareResult,
  parseBlockModel,
  buildRunKey,
  hasRunFiles,
  projectRunFileLabels,
  inputDetailFields,
  reportDetailFields,
  metricsDetailFields,
  scheduleDetailFields,
} from "./helpers";
import RunFocusingPanel from "./RunFocusingPanel";
import RunComparePanel from "./RunComparePanel";
import RunDiagnosticsPanel from "./RunDiagnosticsPanel";

export default function ProjectRunList() {
  const {
    setModel,
    setView,
    setActiveRun,
    setShow3D,
    activeRun,
    blockModelDataMode,
    setIsBlockModelLoading,
    setGeorefState,
    georefConfidence,
    crsInfo,
    hasElevationData,
  } = useAppStore();

  const [projectRuns, setProjectRuns] = useState<ProjectRunsViewData | null>(null);
  const [projectRunsLoading, setProjectRunsLoading] = useState(true);
  const [projectRunsError, setProjectRunsError] = useState<string | null>(null);
  const [loadingRunKey, setLoadingRunKey] = useState<string | null>(null);
  const [loadRunError, setLoadRunError] = useState<string | null>(null);
  const [detailRunKey, setDetailRunKey] = useState<string | null>(null);
  const [detailLoadingRunKey, setDetailLoadingRunKey] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, ProjectRunDetail>>({});
  const [detailError, setDetailError] = useState<string | null>(null);
  const [sweepLoadingRunKey, setSweepLoadingRunKey] = useState<string | null>(null);
  const [sweepError, setSweepError] = useState<string | null>(null);
  const [sweepResults, setSweepResults] = useState<Record<string, SensitivitySweepResult>>({});
  const [baseRun, setBaseRun] = useState<SelectedRun | null>(null);
  const [compareRun, setCompareRun] = useState<SelectedRun | null>(null);
  const [loadingCompare, setLoadingCompare] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadProjectRuns() {
      setProjectRunsLoading(true);
      setProjectRunsError(null);

      const result = await getProjectRuns();

      if (!isMounted) return;

      if (!result.ok) {
        setProjectRuns(null);
        setProjectRunsError(result.error || "No se pudieron cargar proyectos y corridas.");
        setProjectRunsLoading(false);
        return;
      }

      setProjectRuns(parseProjectRuns(result.data));
      setProjectRunsLoading(false);
    }

    loadProjectRuns();

    return () => {
      isMounted = false;
    };
  }, [activeRun.runId]);

  const handleLoadRunModel = async (projectId: string, runId: string) => {
    const runKey = buildRunKey(projectId, runId);

    setLoadingRunKey(runKey);
    setLoadRunError(null);
    setIsBlockModelLoading(true);

    const result = await getExplorationBlockModelForRun(
      projectId,
      runId,
      blockModelDataMode,
      blockModelDataMode === "exploration" ? 5000 : 250000
    );

    if (!result.ok || !result.data) {
      setLoadRunError(result.error || "No se pudo cargar el modelo 3D de la corrida.");
      setLoadingRunKey(null);
      setIsBlockModelLoading(false);
      return;
    }

    const backendModel = parseBlockModel(result.data);

    if (!backendModel) {
      setLoadRunError("La corrida no devolvió celdas válidas para visualizar.");
      setLoadingRunKey(null);
      setIsBlockModelLoading(false);
      return;
    }

    setModel(backendModel);
    setShow3D(true);
    setActiveRun({
      projectId,
      runId,
      source: "history",
      status: "ready",
      error: null,
      importMetadata: null,
      observationsSummary: null,
      reportSummary: null,
      focusing: null,
    });
    setView("figura 3d");
    setLoadingRunKey(null);
    setIsBlockModelLoading(false);

    // Cargar footprint del proyecto después de activar el modelo (R1-FE-5)
    fetchProjectFootprint(projectId).then((fpResult) => {
      if (fpResult.ok && fpResult.data) {
        const fp = fpResult.data.footprint;
        setGeorefState({
          footprint: fp ?? null,
          confidence: fpResult.data.georef_confidence ?? null,
          warnings: fpResult.data.warnings ?? [],
          crsInfo: fp ? {
            epsg_code: fp.epsg_code ?? null,
            crs_source: fp.crs_source ?? null,
            crs_confidence: fp.crs_confidence ?? null,
            utm_zone: fp.utm_zone ?? null,
            utm_hemisphere: fp.utm_hemisphere ?? null,
          } : null,
        });
      } else {
        console.warn("[ProjectRunList] fetchProjectFootprint failed:", fpResult.error);
      }
    }).catch((e) => {
      console.warn("[ProjectRunList] fetchProjectFootprint exception:", e);
    });
  };

  const handleLoadRunDetail = async (projectId: string, runId: string) => {
    const runKey = buildRunKey(projectId, runId);

    setDetailRunKey(runKey);
    setDetailLoadingRunKey(runKey);
    setDetailError(null);

    const result = await getProjectRunDetail(projectId, runId);

    if (!result.ok || !result.data) {
      setDetailError(result.error || "No se pudo cargar el detalle de la corrida.");
      setDetailLoadingRunKey(null);
      return;
    }

    const detail = parseProjectRunDetail(result.data);

    if (!detail) {
      setDetailError("El detalle de la corrida no tiene formato válido.");
      setDetailLoadingRunKey(null);
      return;
    }

    setRunDetails((current) => ({
      ...current,
      [runKey]: detail,
    }));
    setDetailLoadingRunKey(null);
  };

  const handleRunSensitivitySweep = async (detail: ProjectRunDetail) => {
    const runKey = buildRunKey(detail.projectId, detail.runId);

    if (!detail.inputs || !detail.observations || detail.observations.length === 0) {
      setSweepError("No hay inputs/observations suficientes para ejecutar el sweep.");
      return;
    }

    const inputs = detail.inputs;

    const lambda_mag = typeof inputs.lambda_mag === "number" ? inputs.lambda_mag : null;
    const alpha_spatial = typeof inputs.alpha_spatial === "number" ? inputs.alpha_spatial : null;

    if (lambda_mag === null || alpha_spatial === null) {
      setSweepError("lambda_mag o alpha_spatial no son numéricos en los inputs guardados.");
      return;
    }

    const payload = {
      project_id: detail.projectId,
      run_id: detail.runId,
      depth: inputs.depth,
      nir: inputs.nir,
      fe: inputs.fe,
      region: inputs.region,
      lat: inputs.lat,
      lon: inputs.lon,
      nx: inputs.nx,
      ny: inputs.ny,
      nz: inputs.nz,
      block_size: inputs.block_size,
      cutoff_radius: inputs.cutoff_radius,
      lambda_mag,
      alpha_spatial,
      observations: detail.observations,
      lambda_values: [lambda_mag * 0.5, lambda_mag, lambda_mag * 2],
      alpha_values: [Math.max(alpha_spatial * 0.5, 0), alpha_spatial, alpha_spatial * 2],
      max_cases: 9,
    };

    setSweepLoadingRunKey(runKey);
    setSweepError(null);

    const result = await runGeophysicsSensitivitySweep(payload);

    if (!result.ok || !result.data) {
      setSweepError(result.error || "Falló la ejecución del sweep geofísico.");
      setSweepLoadingRunKey(null);
      return;
    }

    setSweepResults((current) => ({
      ...current,
      [runKey]: result.data as SensitivitySweepResult,
    }));
    setSweepLoadingRunKey(null);
  };

  const handleSetBaseRun = (projectId: string, runId: string) => {
    setBaseRun({ projectId, runId });
    setCompareError(null);
  };

  const handleCompareAgainstBase = async (projectId: string, runId: string) => {
    if (!baseRun) {
      setCompareError("Selecciona una corrida base primero.");
      return;
    }

    setCompareRun({ projectId, runId });
    setLoadingCompare(true);
    setCompareError(null);

    const result = await compareRuns({
      baseProjectId: baseRun.projectId,
      baseRunId: baseRun.runId,
      compareProjectId: projectId,
      compareRunId: runId,
    });

    if (!result.ok || !result.data) {
      setCompareResult(null);
      setCompareError(result.error || "No se pudieron comparar las corridas.");
      setLoadingCompare(false);
      return;
    }

    const parsedResult = parseCompareResult(result.data);

    if (!parsedResult) {
      setCompareResult(null);
      setCompareError("La comparación no tiene formato válido.");
      setLoadingCompare(false);
      return;
    }

    setCompareResult(parsedResult);
    setLoadingCompare(false);
  };

  const renderDetailGrid = (title: string, data: JsonObject | null, fields: string[]) => (
    <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-3">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">{title}</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {fields.map((field) => (
          <div key={field}>
            <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">{field}</p>
            <p className="text-[10px] text-white font-mono">{readText(data?.[field])}</p>
          </div>
        ))}
      </div>
    </div>
  );

  const renderSensitivitySweep = (detail: ProjectRunDetail) => {
    const runKey = buildRunKey(detail.projectId, detail.runId);
    const isLoading = sweepLoadingRunKey === runKey;
    const result = sweepResults[runKey];

    return (
      <div className="border border-neutral-800 bg-black/40 rounded-xl p-4 mt-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
          <div>
            <p className="text-[10px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold">
              Sensitivity Sweep
            </p>
            <p className="text-[9px] text-neutral-500 font-mono mt-1">
              Evaluación manual de lambda_mag y alpha_spatial
            </p>
          </div>
          <button
            onClick={() => handleRunSensitivitySweep(detail)}
            disabled={isLoading}
            className="px-4 py-2 bg-neutral-900 border border-neutral-700 hover:bg-neutral-800 text-[10px] uppercase tracking-widest text-white rounded transition-colors disabled:opacity-50"
          >
            {isLoading ? "Ejecutando sweep..." : "Ejecutar sweep"}
          </button>
        </div>

        {sweepError && (
          <div className="border border-red-900/50 bg-red-950/20 rounded p-3 mb-4 text-[10px] text-red-400 font-mono">
            {sweepError}
          </div>
        )}

        {result && (
          <div className="space-y-4 border-t border-neutral-800 pt-4">
            <div className="flex flex-col gap-2">
              <p className="text-[9px] uppercase tracking-widest text-neutral-500">Mejor Caso</p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">lambda_mag</p>
                  <p className="text-[10px] text-white font-mono">{fmtSci(result.best_case?.lambda_mag)}</p>
                </div>
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">alpha_spatial</p>
                  <p className="text-[10px] text-white font-mono">{fmtSci(result.best_case?.alpha_spatial)}</p>
                </div>
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">fit_level</p>
                  <p className={`text-[10px] font-bold ${levelCls(result.best_case?.fit_level)}`}>
                    {result.best_case?.fit_level ?? "—"}
                  </p>
                </div>
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">normalized_rmse</p>
                  <p className="text-[10px] text-white font-mono">{fmtNum(result.best_case?.normalized_rmse, 4)}</p>
                </div>
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">residual_rmse</p>
                  <p className="text-[10px] text-white font-mono">{fmtSci(result.best_case?.residual_rmse)}</p>
                </div>
                <div className="bg-neutral-900/50 p-2 rounded">
                  <p className="text-[8px] text-neutral-500 uppercase">fit_quality</p>
                  <p className="text-[10px] text-white font-mono">{fmtNum(result.best_case?.fit_quality, 2)}</p>
                </div>
              </div>
            </div>

            <div>
              <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Nota del barrido</p>
              <p className="text-[10px] text-[#C2D8C4] font-mono">{result.recommendation}</p>
            </div>

            {result.warnings && result.warnings.length > 0 && (
              <div>
                <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-1">Warnings</p>
                <ul className="list-disc list-inside text-[10px] text-yellow-500 font-mono">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="overflow-x-auto">
              <p className="text-[9px] uppercase tracking-widest text-neutral-500 mb-2">
                Casos Evaluados ({result.case_count})
              </p>
              <table className="w-full text-left text-[9px] font-mono min-w-max">
                <thead className="text-neutral-600 uppercase border-b border-neutral-800">
                  <tr>
                    <th className="pb-2 pr-3 font-normal">case_id</th>
                    <th className="pb-2 pr-3 font-normal">lambda_mag</th>
                    <th className="pb-2 pr-3 font-normal">alpha_spatial</th>
                    <th className="pb-2 pr-3 font-normal">fit_level</th>
                    <th className="pb-2 pr-3 font-normal">nrmse</th>
                    <th className="pb-2 pr-3 font-normal">rmse</th>
                    <th className="pb-2 pr-3 font-normal">mae</th>
                    <th className="pb-2 pr-3 font-normal">bias</th>
                  </tr>
                </thead>
                <tbody className="text-neutral-300">
                  {result.cases.map((c, i) => (
                    <tr key={i} className="border-b border-neutral-900/50 hover:bg-neutral-900/30">
                      <td className="py-1.5 pr-3 text-neutral-500">{c.case_id}</td>
                      <td className="py-1.5 pr-3">{fmtSci(c.lambda_mag)}</td>
                      <td className="py-1.5 pr-3">{fmtSci(c.alpha_spatial)}</td>
                      <td className="py-1.5 pr-3">
                        <span className={`px-1 py-0.5 rounded text-[8px] uppercase font-bold ${levelCls(c.fit_level)}`}>
                          {c.fit_level}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3">{fmtNum(c.normalized_rmse, 4)}</td>
                      <td className="py-1.5 pr-3">{fmtSci(c.residual_rmse)}</td>
                      <td className="py-1.5 pr-3">{fmtSci(c.residual_mae)}</td>
                      <td className="py-1.5 pr-3">{fmtSci(c.residual_bias)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderRunDetail = (detail: ProjectRunDetail) => (
    <div className="mt-3 border border-neutral-800 bg-black/50 rounded-xl p-4 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">projectId</p>
          <p className="text-[10px] text-white font-mono">{detail.projectId}</p>
        </div>
        <div>
          <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">runId</p>
          <p className="text-[10px] text-white font-mono">{detail.runId}</p>
        </div>
      </div>

      <div>
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-2">storage / files</p>
        <div className="flex flex-wrap gap-2">
          {projectRunFileLabels.map((file) => (
            <span
              key={file.key}
              className={`text-[8px] uppercase tracking-widest px-2 py-1 rounded border ${
                detail.files[file.key]
                  ? "border-[#C2D8C4]/40 bg-[#C2D8C4]/10 text-[#C2D8C4]"
                  : "border-neutral-800 bg-neutral-950 text-neutral-600"
              }`}
            >
              {file.label}
            </span>
          ))}
        </div>
      </div>

      {renderDetailGrid("inputs", detail.inputs, inputDetailFields)}
      {renderDetailGrid("report", detail.report, reportDetailFields)}
      {renderDetailGrid("metrics", detail.metrics, metricsDetailFields)}

      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-3 overflow-x-auto">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">schedule</p>
        {detail.schedule.length > 0 ? (
          <table className="w-full text-left text-[10px] font-mono">
            <thead className="text-neutral-600 uppercase">
              <tr>
                {scheduleDetailFields.map((field) => (
                  <th key={field} className="pb-2 pr-4 font-normal">
                    {field}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-neutral-300">
              {detail.schedule.map((row, idx) => (
                <tr key={`${detail.runId}-schedule-${idx}`} className="border-t border-neutral-900">
                  {scheduleDetailFields.map((field) => (
                    <td key={field} className="py-2 pr-4">
                      {readText(row[field])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-[10px] text-neutral-500">No disponible</p>
        )}
      </div>

      <RunDiagnosticsPanel detail={detail} />
      {renderSensitivitySweep(detail)}
      <RunFocusingPanel focusingData={asRecord(detail.report?.focusing)} />
    </div>
  );

  return (
    <section className="shrink-0 border border-neutral-800 bg-neutral-950/60 rounded-2xl p-6 print:border-neutral-300 print:bg-transparent">
      <div className="flex flex-col gap-1 mb-5">
        <h3 className="text-[12px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold print:text-black">
          Proyectos y corridas
        </h3>
        <p className="text-[10px] text-neutral-500 font-mono">
          {projectRunsLoading
            ? "Cargando corridas guardadas..."
            : `Proyectos: ${projectRuns?.totalProjects ?? 0} | Corridas: ${projectRuns?.totalRuns ?? 0}`}
        </p>
      </div>

      {projectRunsError ? (
        <div className="border border-red-900/50 bg-red-950/20 rounded-xl p-4 text-[11px] text-red-300">
          {projectRunsError}
        </div>
      ) : null}

      {loadRunError ? (
        <div className="border border-red-900/50 bg-red-950/20 rounded-xl p-4 text-[11px] text-red-300 mb-4">
          {loadRunError}
        </div>
      ) : null}

      {detailError ? (
        <div className="border border-red-900/50 bg-red-950/20 rounded-xl p-4 text-[11px] text-red-300 mb-4">
          {detailError}
        </div>
      ) : null}

      {compareError ? (
        <div className="border border-red-900/50 bg-red-950/20 rounded-xl p-4 text-[11px] text-red-300 mb-4">
          {compareError}
        </div>
      ) : null}

      {baseRun || compareRun || compareResult || loadingCompare ? (
        <RunComparePanel
          baseRun={baseRun}
          compareRun={compareRun}
          compareResult={compareResult}
          loadingCompare={loadingCompare}
        />
      ) : null}

      {!projectRunsLoading && !projectRunsError && (!projectRuns || projectRuns.totalRuns === 0) ? (
        <div className="border border-neutral-800 bg-black/40 rounded-xl p-4 text-[11px] text-neutral-500">
          No hay corridas guardadas todavía.
        </div>
      ) : null}

      {!projectRunsLoading && !projectRunsError && projectRuns && projectRuns.totalRuns > 0 ? (
        <div className="space-y-4">
          {projectRuns.projects.map((project) => (
            <div key={project.projectId} className="border border-neutral-800 bg-black/40 rounded-xl p-4">
              <div className="flex items-center justify-between gap-3 mb-3">
                <p className="text-[11px] text-white font-mono">{project.projectId}</p>
                <span className="text-[9px] text-neutral-500 uppercase tracking-widest">
                  {project.runs.length} runs
                </span>
              </div>

              <div className="space-y-3">
                {project.runs.map((run) => (
                  <div key={run.runId} className="border border-neutral-900 rounded-lg p-3">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[10px] text-[#C2D8C4] font-mono">{run.runId}</span>
                        {activeRun.projectId === project.projectId &&
                          activeRun.runId === run.runId &&
                          georefConfidence !== null && (() => {
                            const gb = miniGeorefBadge(georefConfidence);
                            return (
                              <span className={`text-[7px] px-1.5 py-0.5 border rounded uppercase tracking-widest font-bold ${gb.cls}`}>
                                {gb.label}
                              </span>
                            );
                          })()}
                        {activeRun.projectId === project.projectId &&
                          activeRun.runId === run.runId &&
                          crsInfo?.epsg_code && (
                            <span className="text-[7px] px-1.5 py-0.5 border border-blue-600/40 bg-blue-900/20 text-blue-400 rounded font-mono">
                              EPSG:{crsInfo.epsg_code}
                            </span>
                          )}
                        {activeRun.projectId === project.projectId &&
                          activeRun.runId === run.runId &&
                          hasElevationData && (
                            <span className="text-[7px] px-1.5 py-0.5 border border-cyan-600/40 bg-cyan-900/20 text-cyan-400 rounded font-mono uppercase tracking-widest font-bold">
                              Elevación DEM
                            </span>
                          )}
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-3">
                        <button
                          type="button"
                          onClick={() => handleSetBaseRun(project.projectId, run.runId)}
                          className={`text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-full border transition-colors ${
                            baseRun?.projectId === project.projectId && baseRun.runId === run.runId
                              ? "border-[#C2D8C4]/50 bg-[#C2D8C4]/20 text-[#C2D8C4]"
                              : "border-neutral-700 bg-neutral-950 text-neutral-300 hover:border-[#C2D8C4]/40 hover:text-[#C2D8C4]"
                          }`}
                        >
                          Usar como base
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCompareAgainstBase(project.projectId, run.runId)}
                          disabled={loadingCompare}
                          className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-neutral-700 bg-neutral-950 text-neutral-300 hover:border-[#C2D8C4]/40 hover:text-[#C2D8C4] disabled:opacity-50 transition-colors"
                        >
                          {loadingCompare &&
                          compareRun?.projectId === project.projectId &&
                          compareRun.runId === run.runId
                            ? "Comparando..."
                            : "Comparar contra base"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleLoadRunDetail(project.projectId, run.runId)}
                          disabled={detailLoadingRunKey !== null}
                          className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-neutral-700 bg-neutral-950 text-neutral-300 hover:border-[#C2D8C4]/40 hover:text-[#C2D8C4] disabled:opacity-50 transition-colors"
                        >
                          {detailLoadingRunKey === buildRunKey(project.projectId, run.runId)
                            ? "Cargando..."
                            : "Ver detalle"}
                        </button>
                        {hasRunFiles(run.files) ? (
                          <a
                            href={exportRunUrl(project.projectId, run.runId)}
                            download
                            className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-neutral-700 bg-neutral-950 text-neutral-300 hover:border-[#C2D8C4]/40 hover:text-[#C2D8C4] transition-colors"
                          >
                            Descargar ZIP
                          </a>
                        ) : null}
                        {run.files.block_model ? (
                          <button
                            type="button"
                            onClick={() => handleLoadRunModel(project.projectId, run.runId)}
                            disabled={loadingRunKey !== null}
                            className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-[#C2D8C4]/40 bg-[#C2D8C4]/10 text-[#C2D8C4] hover:bg-[#C2D8C4] hover:text-black disabled:opacity-50 disabled:hover:bg-[#C2D8C4]/10 disabled:hover:text-[#C2D8C4] transition-colors"
                          >
                            {loadingRunKey === buildRunKey(project.projectId, run.runId)
                              ? "Cargando..."
                              : "Cargar modelo 3D"}
                          </button>
                        ) : null}
                        <span
                          className={`text-[8px] uppercase tracking-widest ${
                            run.exists ? "text-[#C2D8C4]" : "text-red-400"
                          }`}
                        >
                          {run.exists ? "Existe" : "No existe"}
                        </span>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {projectRunFileLabels.map((file) => (
                        <span
                          key={file.key}
                          className={`text-[8px] uppercase tracking-widest px-2 py-1 rounded border ${
                            run.files[file.key]
                              ? "border-[#C2D8C4]/40 bg-[#C2D8C4]/10 text-[#C2D8C4]"
                              : "border-neutral-800 bg-neutral-950 text-neutral-600"
                          }`}
                        >
                          {file.label}
                        </span>
                      ))}
                    </div>

                    {detailRunKey === buildRunKey(project.projectId, run.runId) &&
                    detailLoadingRunKey === buildRunKey(project.projectId, run.runId) ? (
                      <div className="mt-3 border border-neutral-900 bg-neutral-950/70 rounded-lg p-3 text-[10px] text-neutral-500">
                        Cargando detalle técnico...
                      </div>
                    ) : null}

                    {detailRunKey === buildRunKey(project.projectId, run.runId) &&
                    runDetails[buildRunKey(project.projectId, run.runId)]
                      ? renderRunDetail(runDetails[buildRunKey(project.projectId, run.runId)])
                      : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
