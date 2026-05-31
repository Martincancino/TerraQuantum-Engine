"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { useAppStore } from "../../store/useAppStore";
import { VoxelMineralModel } from "../../lib/terraQuantumGeology";

import Scene3D from "../Scene3D";
import TelemetryConsole from "../huds/TelemetryConsole";
import BackendStatusBadge from "../huds/BackendStatusBadge";
import GravityCsvPreviewPanel from "../GravityCsvPreviewPanel";
import InversionQualityBadge from "../InversionQualityBadge";
import WorkspaceLayout from "../workspace/WorkspaceLayout";
import CommandBar from "../workspace/CommandBar";
import SidebarSection from "../workspace/SidebarSection";
import Panel from "../workspace/Panel";
import SliceControls from "../viewport/SliceControls";
import AnalyticsPanel from "../analytics/AnalyticsPanel";

import { GravityObservation } from "../../lib/terraquantum/geophysicsSurvey";
import {
  buildGeophysicsPayload,
  buildGridConfig,
  buildHeatmapFromBlockModel,
  buildReportForFrontend,
  findDemoHighlightVoxel,
} from "../../lib/terraquantum/geophysicsModel";
import {
  getExplorationBlockModelForRun,
  getTerrainData,
  runGeophysicsInvert,
  getGeophysicsStatus,
  getProjectRunDetail,
  exportRunUrl,
} from "../../lib/terraquantum/frontendApi";
import { AppState, VoxelInfo } from "../../store/useAppStore";
import type { BlockModelDataMode } from "../../store/useAppStore";
import type { VoxelData } from "../../lib/terraQuantumGeology";

/** Extiende VoxelMineralModel con campos opcionales que devuelve el backend. */
type BackendVoxelModel = VoxelMineralModel & {
  visualMode?: string;
  densityMin?: number;
  densityMax?: number;
  mode?: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  return value as Record<string, unknown>;
}

function readArrayField(value: unknown, key: string): unknown[] {
  const record = asRecord(value);
  const field = record?.[key];

  return Array.isArray(field) ? field : [];
}

function readNumberField(value: unknown, key: string, fallback = 0): number {
  const record = asRecord(value);
  const field = record?.[key];

  if (field === null || field === undefined || field === "") return fallback;

  const n = Number(field);
  return Number.isFinite(n) ? n : fallback;
}

function readStringField(value: unknown, key: string, fallback = ""): string {
  const record = asRecord(value);
  const field = record?.[key];

  return typeof field === "string" && field.trim().length > 0 ? field : fallback;
}

function readObjectField(value: unknown, key: string): Record<string, unknown> | undefined {
  const record = asRecord(value);
  const field = record?.[key];

  return asRecord(field) ?? undefined;
}

function readStringArrayField(value: unknown, key: string): string[] {
  return readArrayField(value, key).filter(
    (item): item is string => typeof item === "string"
  );
}

function readOptionalNumber(record: Record<string, unknown> | null, key: string): number | null {
  const n = Number(record?.[key]);

  return Number.isFinite(n) ? n : null;
}

function isVoxelData(value: unknown): value is VoxelData {
  return Boolean(asRecord(value));
}

function toVoxelInfo(voxel: VoxelData | null): VoxelInfo | null {
  if (!voxel) return null;

  return { ...voxel };
}

function parseBackendVoxelModel(data: unknown): BackendVoxelModel | null {
  const blockData = asRecord(data);

  if (!blockData) return null;

  const blockCells = readArrayField(blockData, "cells").filter(isVoxelData);
  const domainL = readNumberField(blockData, "domainL");
  const domainH = readNumberField(blockData, "domainH");
  const domainW = readNumberField(blockData, "domainW");
  const cellSize = readNumberField(blockData, "cellSize", 10);
  const densityMin = readNumberField(blockData, "densityMin", Number.NaN);
  const densityMax = readNumberField(blockData, "densityMax", Number.NaN);
  const visualMode = readStringField(blockData, "visualMode");
  const mode = readStringField(blockData, "mode");
  const scoreStats = readObjectField(blockData, "scoreStats") as BackendVoxelModel["scoreStats"];
  const visualScoreStats = readObjectField(blockData, "visualScoreStats") as BackendVoxelModel["visualScoreStats"];
  const densityStats = readObjectField(blockData, "densityStats") as BackendVoxelModel["densityStats"];
  const rhoStats = readObjectField(blockData, "rhoStats") as BackendVoxelModel["rhoStats"];
  const probabilityStats = readObjectField(blockData, "probabilityStats") as BackendVoxelModel["probabilityStats"];
  const returnedScoreStats = readObjectField(blockData, "returnedScoreStats") as BackendVoxelModel["returnedScoreStats"];
  const diagnosticStats = readObjectField(blockData, "diagnosticStats") as BackendVoxelModel["diagnosticStats"];
  const returnedDiagnosticStats = readObjectField(blockData, "returnedDiagnosticStats") as BackendVoxelModel["returnedDiagnosticStats"];
  const warnings = readStringArrayField(blockData, "warnings");
  const isDegenerate = blockData.isDegenerate === true || blockData.is_degenerate === true;

  return {
    domainL,
    domainH,
    domainW,
    cellSize,
    cells: blockCells,
    volumeM3: domainL * domainH * domainW,
    ...(visualMode ? { visualMode } : {}),
    ...(mode ? { mode } : {}),
    ...(Number.isFinite(densityMin) ? { densityMin } : {}),
    ...(Number.isFinite(densityMax) ? { densityMax } : {}),
    ...(scoreStats ? { scoreStats } : {}),
    ...(visualScoreStats ? { visualScoreStats } : {}),
    ...(densityStats ? { densityStats } : {}),
    ...(rhoStats ? { rhoStats } : {}),
    ...(probabilityStats ? { probabilityStats } : {}),
    ...(returnedScoreStats ? { returnedScoreStats } : {}),
    ...(diagnosticStats ? { diagnosticStats } : {}),
    ...(returnedDiagnosticStats ? { returnedDiagnosticStats } : {}),
    ...(warnings.length > 0 ? { warnings } : {}),
    ...(isDegenerate ? { isDegenerate: true, is_degenerate: true } : {}),
  };
}

function limitForBlockModelMode(mode: BlockModelDataMode) {
  return mode === "exploration" ? 5000 : 250000;
}

function hasValidElevationRange(range: AppState["blockModelElevationRange"]) {
  if (!range) return false;

  const minVoxel = range.min_voxel_elevation_masl;
  const maxVoxel = range.max_voxel_elevation_masl;
  const minSurface = range.min_surface_elevation_masl;
  const maxSurface = range.max_surface_elevation_masl;

  return (
    minVoxel !== null &&
    minVoxel !== undefined &&
    maxVoxel !== null &&
    maxVoxel !== undefined &&
    minSurface !== null &&
    minSurface !== undefined &&
    maxSurface !== null &&
    maxSurface !== undefined &&
    Number.isFinite(minVoxel) &&
    Number.isFinite(maxVoxel) &&
    Number.isFinite(minSurface) &&
    Number.isFinite(maxSurface) &&
    maxVoxel >= minVoxel &&
    maxSurface >= minSurface
  );
}

export default function Exploration3DView() {
  const {
    model,
    setModel,
    show3D,
    setShow3D,
    requestCameraReset,
    setReport,
    setHeatmapData,
    setBestTarget,
    setBestVoxel,
    inputDepth,
    inputGrav,
    inputNIR,
    inputFe,
    geoLat,
    geoLon,
    region,
    geoRegionName,
    geologistNote,
    setSliceX,
    setTerrainData,
    activeRun,
    setActiveRun,
    clearActiveRun,
    showAnomalyEnvelope,
    view,
    blockModelDataMode,
    setIsBlockModelLoading,
    hasElevationData,
    blockModelDemSource,
    blockModelGeorefConfidence,
    blockModelElevationRange,
    setBlockModelElevationMeta,
    visualProfessionalMode,
    setVisualProfessionalMode,
    postprocessingEnabled,
    setPostprocessingEnabled,
    setSelectedVoxel,
    showLegend,
    visibleCellCount,
    highlightedCellCount,
    returnedVoxels,
    setPollingState,
    resetPollingState,
    visualLayer,
  } = useAppStore() as AppState;

  const hasElevation =
    hasElevationData || hasValidElevationRange(blockModelElevationRange);

  const blockModelReloadRequestRef = React.useRef(0);
  const previousBlockModelDataModeRef =
    React.useRef<BlockModelDataMode>(blockModelDataMode);

  const pollingRef = React.useRef<{
    active: boolean;
    timeoutId?: ReturnType<typeof setTimeout>;
  }>({ active: false, timeoutId: undefined });

  useEffect(() => {
    const ref = pollingRef;
    return () => {
      ref.current.active = false;
      if (ref.current.timeoutId !== undefined) {
        clearTimeout(ref.current.timeoutId);
        ref.current.timeoutId = undefined;
      }
    };
  }, []);

  const [syncState, setSyncState] = useState<"idle" | "syncing" | "complete">(
    "idle"
  );
  const [syncProgress, setSyncProgress] = useState(0);
  const [syncLog, setSyncLog] = useState("Esperando telemetría real...");

  const modelMaxDomain = model
    ? Math.max(
        model.domainL || 0,
        model.domainH || 0,
        model.domainW || 0,
        (model.cellSize || 10) * 4
      )
    : 0;
  const cameraDistance = model ? Math.max(modelMaxDomain * (hasElevation ? 2.25 : 1.55), 90) : 35;
  const farPlane = Math.max(200000, cameraDistance * 4);
  const cameraPosition: [number, number, number] = [
    cameraDistance,
    cameraDistance * 0.72,
    cameraDistance,
  ];
  const loadedVoxelCount = returnedVoxels ?? (Array.isArray(model?.cells) ? model.cells.length : 0);
  const percentileStats = useAppStore((s) => s.percentileStats);
  const modelStatsRecord = asRecord(model);
  const scoreStatsRecord =
    asRecord(modelStatsRecord?.scoreStats) ??
    asRecord(modelStatsRecord?.visualScoreStats);
  const scoreIsDegenerate =
    percentileStats?.is_degenerate === true ||
    modelStatsRecord?.isDegenerate === true ||
    modelStatsRecord?.is_degenerate === true ||
    scoreStatsRecord?.isDegenerate === true ||
    scoreStatsRecord?.is_degenerate === true;

  // Percentiles contextuales: selecciona el conjunto correcto según la capa visual activa.
  // Para densidad usa density_p* del backend (más precisos, calculados pre-sampling).
  // Para otras capas usa visual_score_p* o los stats del modelo.
  const layerPercentiles = useMemo(() => {
    if (visualLayer === "modeled_density" && percentileStats) {
      return {
        p85: percentileStats.density_p85 ?? null,
        p90: percentileStats.density_p90 ?? null,
        p95: percentileStats.density_p95 ?? null,
        p98: percentileStats.density_p98 ?? null,
        unit: "t/m³",
        label: "Densidad modelada",
      };
    }
    return {
      p85: percentileStats?.visual_score_p85 ?? readOptionalNumber(scoreStatsRecord, "p85"),
      p90: percentileStats?.visual_score_p90 ?? readOptionalNumber(scoreStatsRecord, "p90"),
      p95: percentileStats?.visual_score_p95 ?? readOptionalNumber(scoreStatsRecord, "p95"),
      p98: percentileStats?.visual_score_p98 ?? readOptionalNumber(scoreStatsRecord, "p98"),
      unit: "",
      label: visualLayer === "density_anomaly_score"
        ? "Contraste de densidad"
        : visualLayer === "anomaly_intensity"
        ? "Intensidad de anomalía"
        : "Target Score",
    };
  }, [visualLayer, percentileStats, scoreStatsRecord]);

  function formatLegendPercentile(value: number | null): string {
    return value === null ? "n/d" : value.toFixed(2);
  }

  const resetExplorationState = () => {
    if (activeRun.source === "history" && activeRun.status === "ready") return;
    setReport(null);
    setModel(null);
    setShow3D(false);
    setHeatmapData([]);
    setBestTarget(null);
    setBestVoxel(null);
    setTerrainData(null);
  };

  useEffect(() => {
    let isMounted = true;

    async function loadTerrainData(projectId: string) {
      const terrainResult = await getTerrainData(projectId);

      if (!isMounted) return;

      setTerrainData(
        terrainResult.ok && terrainResult.data ? terrainResult.data : null
      );
    }

    if (!activeRun.projectId || activeRun.status !== "ready") {
      setTerrainData(null);
      return () => {
        isMounted = false;
      };
    }

    loadTerrainData(activeRun.projectId);

    return () => {
      isMounted = false;
    };
  }, [activeRun.projectId, activeRun.status, setTerrainData]);

  useEffect(() => {
    const previousMode = previousBlockModelDataModeRef.current;
    previousBlockModelDataModeRef.current = blockModelDataMode;

    if (previousMode === blockModelDataMode) return;
    if (view !== "figura 3d") return;
    if (!activeRun.projectId || !activeRun.runId || activeRun.status !== "ready") return;
    if (!show3D && !model) return;

    const requestId = blockModelReloadRequestRef.current + 1;
    blockModelReloadRequestRef.current = requestId;
    const preservedElevationMeta = hasElevation
      ? {
          hasElevationData,
          demSource: blockModelDemSource,
          georefConfidence: blockModelGeorefConfidence,
          elevationRange: blockModelElevationRange,
        }
      : null;

    async function reloadBlockModelForMode() {
      setIsBlockModelLoading(true);

      try {
        const blockResult = await getExplorationBlockModelForRun(
          activeRun.projectId as string,
          activeRun.runId as string,
          blockModelDataMode,
          limitForBlockModelMode(blockModelDataMode)
        );

        if (blockModelReloadRequestRef.current !== requestId) return;

        if (!blockResult.ok || !blockResult.data) {
          throw new Error(
            blockResult.error || "No se pudo recargar el modelo 3D."
          );
        }

        if (blockResult.data.warnings.length > 0) {
          console.warn(
            "[BLOCK-MODEL] warnings:",
            blockResult.data.warnings
          );
        }

        const backendModel = parseBackendVoxelModel(blockResult.data);

        if (!backendModel) {
          throw new Error("La respuesta /block-model no tiene formato válido.");
        }

        if (preservedElevationMeta) {
          setBlockModelElevationMeta(preservedElevationMeta);
        }

        setModel(backendModel);
        setShow3D(true);
        setSliceX(backendModel.domainL / 2);
      } catch (error) {
        console.warn("[BLOCK-MODEL] No se pudo cambiar el modo de datos 3D.", error);
      } finally {
        if (blockModelReloadRequestRef.current === requestId) {
          setIsBlockModelLoading(false);
        }
      }
    }

    reloadBlockModelForMode();
  }, [
    activeRun.projectId,
    activeRun.runId,
    activeRun.status,
    blockModelDemSource,
    blockModelDataMode,
    blockModelElevationRange,
    blockModelGeorefConfidence,
    hasElevation,
    hasElevationData,
    model,
    setBlockModelElevationMeta,
    setIsBlockModelLoading,
    setModel,
    setShow3D,
    setSliceX,
    show3D,
    view,
  ]);

  const handleSyncMachine = async (observations: GravityObservation[]) => {
    if (syncState === "syncing") return;

    // Cancela cualquier polling previo antes de iniciar uno nuevo.
    pollingRef.current.active = false;
    if (pollingRef.current.timeoutId !== undefined) {
      clearTimeout(pollingRef.current.timeoutId);
      pollingRef.current.timeoutId = undefined;
    }

    setSyncState("syncing");
    setSyncProgress(5);
    setSyncLog("Limpiando estado anterior...");

    resetExplorationState();
    clearActiveRun();
    resetPollingState();

    try {
      if (!observations || observations.length < 10) {
        throw new Error(
          "Se requieren al menos 10 observaciones gravimétricas reales."
        );
      }

      const gridConfig = buildGridConfig(Number(inputDepth));

      setSyncProgress(10);
      setSyncLog(
        `Enviando observaciones al backend Python. Grid: ${gridConfig.nx}x${gridConfig.ny}x${gridConfig.nz}`
      );

      const payload = buildGeophysicsPayload({
        inputDepth: Number(inputDepth),
        inputNIR: Number(inputNIR),
        inputFe: Number(inputFe),
        region,
        geoLat,
        geoLon,
        observations,
      });

      const queueResult = await runGeophysicsInvert(payload);

      if (!queueResult.ok || !queueResult.data) {
        throw new Error(
          queueResult.error || "El backend rechazó la inversión geofísica."
        );
      }

      // El backend retorna {status:"queued", run_id, project_id} inmediatamente.
      const queueData = asRecord(queueResult.data);
      const projectId =
        typeof queueData?.project_id === "string" && queueData.project_id
          ? queueData.project_id
          : "default";
      const runId =
        typeof queueData?.run_id === "string" && queueData.run_id
          ? queueData.run_id
          : "";

      if (!runId) {
        throw new Error("El backend no retornó un run_id válido.");
      }

      setActiveRun({
        projectId,
        runId,
        source: "csv",
        status: "loading",
        error: null,
      });

      setSyncProgress(15);
      setSyncLog(`Inversión en cola — run ${runId}. Iniciando monitoreo...`);

      // ── Función interna: carga el block model y el reporte al completar ──
      const loadModelAndReport = async () => {
        setSyncLog("Inversión completada. Cargando block model exploratorio...");
        setIsBlockModelLoading(true);

        try {
          const [blockResult, runDetailResult] = await Promise.all([
            getExplorationBlockModelForRun(
              projectId,
              runId,
              blockModelDataMode,
              limitForBlockModelMode(blockModelDataMode)
            ),
            getProjectRunDetail(projectId, runId),
          ]);

          if (!blockResult.ok || !blockResult.data) {
            throw new Error(
              blockResult.error || "No se pudo leer /block-model desde backend."
            );
          }

          const blockData = asRecord(blockResult.data);
          const blockCells = readArrayField(blockData, "cells").filter(isVoxelData);
          const backendModel = parseBackendVoxelModel(blockResult.data);

          if (!backendModel || blockCells.length === 0) {
            throw new Error(
              "El block model llegó vacío. Revisa el Parquet o el modo exploration."
            );
          }

          const returnedCells = readNumberField(
            blockData,
            "returnedCells",
            blockCells.length
          );

          setSyncProgress(95);
          setSyncLog(
            `Construyendo digital twin 3D. Voxeles recibidos: ${returnedCells}`
          );

          setModel(backendModel);
          setShow3D(true);
          setSliceX(backendModel.domainL / 2);

          setActiveRun({ projectId, runId, source: "csv", status: "ready", error: null });

          // Extrae report y best_target del detalle de corrida persistido en disco.
          const runDetailData = asRecord(runDetailResult.data);
          const reportPayload = asRecord(runDetailData?.report);

          if (reportPayload) {
            // Fuente primaria: best_target calculado por inversión LSQR en backend.
            // Fallback: highlight heurístico del block model en TypeScript.
            const rawBestTarget = asRecord(reportPayload.best_target);
            const bestVx = rawBestTarget
              ? toVoxelInfo({
                  cx: readNumberField(rawBestTarget, "x_m"),
                  cy: readNumberField(rawBestTarget, "y_m"),
                  cz: readNumberField(rawBestTarget, "z_m"),
                  density: readNumberField(rawBestTarget, "density"),
                  density_proxy_index: readNumberField(rawBestTarget, "density_proxy_index"),
                  probability: readNumberField(rawBestTarget, "probability"),
                } as unknown as VoxelData)
              : toVoxelInfo(findDemoHighlightVoxel(backendModel));

            setBestVoxel(bestVx);

            const syntheticBackend = {
              voxels: [],
              best_target: reportPayload.best_target ?? null,
              report: reportPayload,
            } as unknown as Parameters<typeof buildReportForFrontend>[0];

            const mappedReport = buildReportForFrontend(
              syntheticBackend,
              backendModel,
              Number(inputDepth),
              Number(inputGrav),
              Number(inputNIR),
              Number(inputFe),
              geoRegionName,
              geologistNote
            );
            setReport(mappedReport);


            const heatmap = buildHeatmapFromBlockModel(backendModel, geoLat, geoLon);
            setHeatmapData(heatmap);

            if (heatmap.length > 0) {
              const bestHeat = heatmap.reduce((best, current) =>
                current.value > best.value ? current : best
              );
              setBestTarget(bestHeat);
            }

          } else {
            // Fallback sin reporte: usa datos del block model directamente.
            const bestVx = toVoxelInfo(findDemoHighlightVoxel(backendModel));
            setBestVoxel(bestVx);
            const heatmap = buildHeatmapFromBlockModel(backendModel, geoLat, geoLon);
            setHeatmapData(heatmap);
            if (heatmap.length > 0) {
              setBestTarget(
                heatmap.reduce((best, current) =>
                  current.value > best.value ? current : best
                )
              );
            }
          }

          resetPollingState();
          setSyncProgress(100);
          setSyncState("complete");
          setSyncLog(
            `Modelo geofísico generado. Voxeles visualizados: ${returnedCells}.`
          );
        } finally {
          setIsBlockModelLoading(false);
        }
      };

      // ── Polling recursivo seguro (sin setInterval para evitar solapamiento) ──
      let isPolling = true;
      pollingRef.current.active = true;

      const POLL_INTERVAL_MS = 3_000;
      const HEARTBEAT_STALE_MS = 120_000;

      const poll = async () => {
        if (!isPolling || !pollingRef.current.active) return;

        let statusResult;
        try {
          statusResult = await getGeophysicsStatus(projectId, runId);
        } catch {
          // Error de red transitorio: reintenta en el próximo ciclo.
          if (isPolling && pollingRef.current.active) {
            pollingRef.current.timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
          }
          return;
        }

        if (!isPolling || !pollingRef.current.active) return;

        if (!statusResult.ok || !statusResult.data) {
          setSyncLog(
            `Reintentando... (error status ${statusResult.status})`
          );
          if (isPolling && pollingRef.current.active) {
            pollingRef.current.timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
          }
          return;
        }

        const sd = statusResult.data;
        const status = sd.status ?? "unknown";
        const stage = sd.stage ?? null;
        const message = sd.message ?? null;
        const progress =
          typeof sd.progress === "number" && Number.isFinite(sd.progress)
            ? sd.progress
            : 0;
        const heartbeatAt = sd.heartbeat_at ?? null;

        // Detección de Stale Worker: heartbeat > 120s sin actualización.
        if (heartbeatAt && status === "running") {
          const staleness = Date.now() - new Date(heartbeatAt).getTime();
          if (staleness > HEARTBEAT_STALE_MS) {
            isPolling = false;
            pollingRef.current.active = false;
            resetPollingState();
            setSyncState("idle");
            setSyncProgress(0);
            setSyncLog(
              `ERROR: Worker sin respuesta por más de 120s (Stale Worker). ` +
              `La inversión puede haber fallado en el servidor. Run: ${runId}`
            );
            setActiveRun({ status: "error", error: "Stale worker detectado." });
            setIsBlockModelLoading(false);
            return;
          }
        }

        // Actualiza el store con el estado actual del worker.
        setPollingState({
          pollingStatus: status,
          pollingStage: stage,
          pollingMessage: message,
          pollingProgress: Math.round(progress * 100),
          lastHeartbeat: heartbeatAt,
        });

        // Progreso UI: 15%–90% durante inversión activa.
        const displayProgress = 15 + Math.round(progress * 75);
        setSyncProgress(Math.min(displayProgress, 90));
        setSyncLog(`[${stage ?? status}] ${message ?? status}`);

        if (status === "done") {
          isPolling = false;
          pollingRef.current.active = false;
          try {
            await loadModelAndReport();
          } catch (err) {
            const msg = err instanceof Error ? err.message : "Error cargando modelo";
            resetPollingState();
            setSyncState("idle");
            setSyncProgress(0);
            setSyncLog(`ERROR: ${msg}`);
            setIsBlockModelLoading(false);
            setActiveRun({ status: "error", error: msg });
          }
        } else if (status === "error") {
          isPolling = false;
          pollingRef.current.active = false;
          const errMsg = sd.error ?? "La inversión falló en el servidor.";
          resetPollingState();
          setSyncState("idle");
          setSyncProgress(0);
          setSyncLog(`ERROR: ${errMsg}`);
          setActiveRun({ status: "error", error: errMsg });
        } else {
          // status === "running" | "queued" — agenda el próximo poll al terminar este.
          if (isPolling && pollingRef.current.active) {
            pollingRef.current.timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
          }
        }
      };

      // Primer poll tras delay inicial para dar tiempo al worker de arrancar.
      pollingRef.current.timeoutId = setTimeout(poll, 2_000);

    } catch (error: unknown) {
      const message =
        error instanceof Error ? error.message : "fallo desconocido";
      console.error(error);
      pollingRef.current.active = false;
      resetPollingState();
      setSyncState("idle");
      setSyncProgress(0);
      setSyncLog(`ERROR: ${message}`);
    }
  };

  return (
    <div className="h-full min-h-0 min-w-0 relative overflow-hidden">
      {/* GeoDashboard modal removed (Fase B II) */}

      <WorkspaceLayout
        commandBar={
          <CommandBar
            title="Inversión Gravimétrica · Interpretación 3D"
            status={
              <div className="flex items-center gap-4 text-[9px] font-mono text-white/45">
                <span className="flex items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      show3D && model ? "bg-accent" : "bg-white/25"
                    }`}
                  />
                  {show3D && model ? "Modelo cargado" : "Sin modelo"}
                </span>
                {activeRun.runId && (
                  <span className="truncate max-w-[180px]">Run: {activeRun.runId}</span>
                )}
                {model && <span>{loadedVoxelCount.toLocaleString()} vóxeles</span>}
              </div>
            }
            actions={[
              {
                id: "view",
                label: visualProfessionalMode ? "Vista · Profesional" : "Vista · Debug",
                active: visualProfessionalMode,
                onClick: () => setVisualProfessionalMode(!visualProfessionalMode),
              },
              {
                id: "quality",
                label: postprocessingEnabled ? "Calidad · Cinemático" : "Calidad · Rendimiento",
                active: postprocessingEnabled,
                disabled: !model || !show3D,
                onClick: () => setPostprocessingEnabled(!postprocessingEnabled),
              },
              {
                id: "reset",
                label: "Reset Cámara",
                disabled: !model || !show3D,
                onClick: () => requestCameraReset(),
              },
              {
                id: "export",
                label: "Export",
                disabled: !activeRun.runId,
                onClick: () => {
                  if (activeRun.projectId && activeRun.runId) {
                    window.open(
                      exportRunUrl(activeRun.projectId, activeRun.runId),
                      "_blank"
                    );
                  }
                },
              },
              // HUD button removed (Fase B II: GeoDashboard eliminated)
            ]}
          />
        }
        sidebar={
          <div className="flex flex-col">
            <SidebarSection title="Dataset">
              <p className="text-[8px] text-white/40 font-mono mb-3 leading-relaxed">
                Importar y validar survey gravimétrico (CSV) antes de invertir.
              </p>
              <GravityCsvPreviewPanel />
            </SidebarSection>
            <SidebarSection title="Inversión">
              <TelemetryConsole
                onExecute={handleSyncMachine}
                syncState={syncState}
                syncProgress={syncProgress}
                syncLog={syncLog}
              />
            </SidebarSection>
            {show3D && model && (
              <SidebarSection title="Cortes geológicos">
                <SliceControls />
              </SidebarSection>
            )}
          </div>
        }
        viewport={
          <div className="h-full min-h-0 border border-white/10 rounded-3xl overflow-hidden bg-[#050505] relative shadow-[0_0_50px_rgba(0,0,0,0.5)] flex flex-col tq-grid-bg">
            <div className="flex-grow relative min-w-0 min-h-0 overflow-hidden">
              <BackendStatusBadge />

              {!show3D || !model ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center px-6 text-neutral-600 text-[10px] tracking-[0.28em] uppercase text-center">
                  <span className="break-words">Esperando inversión gravimétrica</span>
                  <span className="mt-3 max-w-[320px] text-[9px] tracking-[0.12em] text-neutral-700 normal-case">
                    Sube un CSV, valida datos y carga el modelo 3D generado.
                  </span>
                </div>
              ) : (
                <Canvas
                  shadows
                  camera={{ position: cameraPosition, fov: 35, near: 1, far: farPlane }}
                  onPointerMissed={() => setSelectedVoxel(null)}
                  gl={{
                    logarithmicDepthBuffer: true,
                    antialias: false,
                    stencil: false,
                    powerPreference: "high-performance",
                  }}
                  onCreated={({ gl }) => {
                    gl.localClippingEnabled = true;

                    const canvas = gl.domElement;
                    const onContextLost = (e: Event) => {
                      e.preventDefault();
                      console.warn(
                        "[TerraQuantum] WebGL context perdido. El navegador intentará restaurarlo."
                      );
                    };
                    const onContextRestored = () => {
                      console.info("[TerraQuantum] WebGL context restaurado.");
                    };
                    canvas.addEventListener("webglcontextlost", onContextLost, false);
                    canvas.addEventListener("webglcontextrestored", onContextRestored, false);
                  }}
                >
                  <Suspense fallback={null}>
                    <Scene3D />
                  </Suspense>
                </Canvas>
              )}
            </div>

            {show3D && model && (
              <div className="h-auto shrink-0 bg-black/70 border-t border-white/10 px-3 py-2 flex items-center justify-center overflow-hidden">
                {/* BottomControls eliminado: ahora moved to Sidebar (Fase C) */}
              </div>
            )}
          </div>
        }
        analytics={
          show3D && model ? (
            <>
              <Panel title="Estado del Modelo" subtitle="Modelo geofísico preliminar">
                <p className="text-[8px] text-white/55 mb-3 leading-relaxed">
                  Los colores representan contraste relativo del modelo. No confirman
                  mineralización ni recursos. Requiere validación profesional y QA/QC.
                </p>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 text-[8px] font-mono text-white/50">
                  <span>Elevación:</span>
                  <span className="text-right text-white/75">
                    {hasElevation ? "DEM/MASL" : "Coords locales"}
                  </span>
                  <span>Modo datos:</span>
                  <span className="text-right text-white/75">
                    {blockModelDataMode === "full"
                      ? "Completo"
                      : blockModelDataMode === "exploration"
                      ? "Exploración"
                      : "Anomalía"}
                  </span>
                  <span>Vista:</span>
                  <span className="text-right text-accent">
                    {visualProfessionalMode ? "Profesional" : "Debug vóxeles"}
                  </span>
                  <span>Celdas cargadas:</span>
                  <span className="text-right text-white/75">
                    {loadedVoxelCount.toLocaleString()}
                  </span>
                  <span>Celdas destacadas:</span>
                  <span className="text-right text-accent">
                    {highlightedCellCount.toLocaleString()}
                  </span>
                  {visualProfessionalMode && visibleCellCount !== highlightedCellCount && (
                    <>
                      <span>Renderizadas:</span>
                      <span className="text-right text-white/75">
                        {visibleCellCount.toLocaleString()}
                      </span>
                    </>
                  )}
                </div>

                {showLegend && (
                  <div className="mt-3 pt-3 border-t border-white/10">
                    <p className="text-[7px] font-mono text-white/40 mb-1 uppercase tracking-wider">
                      {layerPercentiles.label}
                      {layerPercentiles.unit ? ` (${layerPercentiles.unit})` : ""}
                    </p>
                    <div
                      className="h-2 w-full rounded-sm"
                      style={{
                        background:
                          "linear-gradient(to right, #1e293b 0%, #1e293b 34%, #22d3ee 52%, #38bdf8 68%, #818cf8 84%, #f8fafc 100%)",
                      }}
                    />
                    <div className="mt-1 grid grid-cols-4 gap-1 text-[7px] font-mono text-white/45">
                      <span>P85 {formatLegendPercentile(layerPercentiles.p85)}</span>
                      <span>P90 {formatLegendPercentile(layerPercentiles.p90)}</span>
                      <span>P95 {formatLegendPercentile(layerPercentiles.p95)}</span>
                      <span>P98 {formatLegendPercentile(layerPercentiles.p98)}</span>
                    </div>
                    {percentileStats && !percentileStats.is_degenerate && (
                      <p className="text-[7px] font-mono text-white/30 mt-1 leading-tight">
                        Percentiles sobre modelo completo
                      </p>
                    )}
                  </div>
                )}

                {scoreIsDegenerate && (
                  <p className="mt-2 text-[8px] leading-tight text-yellow-300">
                    Modelo uniforme: vista profesional usa color debug hasta tener
                    contraste estadístico.
                  </p>
                )}
                {showAnomalyEnvelope && (
                  <p className="text-[8px] text-accent/50 mt-2 leading-tight italic">
                    Envolvente de anomalía (bounding box percentil — no es isosuperficie física)
                  </p>
                )}
              </Panel>

              <Panel title="Calidad de Inversión">
                <InversionQualityBadge />
              </Panel>

              <AnalyticsPanel />

              {/* HUD button removed (Fase B II) */}
            </>
          ) : (
            <Panel title="Analytics">
              <p className="text-[9px] text-white/45 leading-relaxed">
                Los diagnósticos del solver (χ², DOI, L-Curve, recuperación sintética,
                cobertura de sensores) aparecerán aquí tras ejecutar una inversión.
              </p>
            </Panel>
          )
        }
      />
    </div>
  );
}
