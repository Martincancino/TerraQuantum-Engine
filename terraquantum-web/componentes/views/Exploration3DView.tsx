"use client";

import React, { Suspense, useEffect, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { useAppStore } from "../../store/useAppStore";

import Scene3D from "../Scene3D";
import LoadPanel from "../LoadPanel";
import MviDirectionPanel from "../MviDirectionPanel";
import InversionQualityBadge from "../InversionQualityBadge";
import WorkspaceLayout from "../workspace/WorkspaceLayout";
import CommandBar from "../workspace/CommandBar";
import SidebarSection from "../workspace/SidebarSection";
import Panel from "../workspace/Panel";
import BoxClipControls from "../viewport/BoxClipControls";
import AnalyticsPanel from "../analytics/AnalyticsPanel";
import VolumeRenderControls from "../viewport/VolumeRenderControls";
import IsosurfaceControls from "../viewport/IsosurfaceControls";
import BoreholeControls from "../viewport/BoreholeControls";
import DoiOverlayControls from "../viewport/DoiOverlayControls";
import ExportPanel from "../viewport/ExportPanel";
import HistorialVisorControls from "../viewport/HistorialVisorControls";
// FASE 9 — dos superficies terminadas que NUNCA se montaron (cierre de la Fase 6).
// `SliceControls` es el único escritor del estado del corte, y `SectionPaintLayer`
// ya estaba montada en Scene3D con `/api/section` respondiendo: el plano de corte
// estaba construido de punta a punta y no había nada que lo encendiera.
// `MultiPhysicsControls` es el único control HUMANO de `setViewMode` — hasta ahora
// la capa física la fijaba `packageInversion.ts` de forma automática y el usuario
// no podía cambiarla.
import SliceControls from "../viewport/SliceControls";
import MultiPhysicsControls from "../viewport/MultiPhysicsControls";
import CanvasExportBridge from "../../lib/render/CanvasExportBridge";
import WarningBanner from "../WarningBanner";
import {
  extractRunWarnings,
  fetchRunReport,
  warningViewsFromTexts,
} from "../../lib/terraquantum/runWarnings";
import { solverConverged } from "../analytics/RegularizationFunctionalWidget";

import {
  getExplorationBlockModelForRunWithArrow,
  getTerrainData,
  runGeophysicsInvert,
  getGeophysicsStatus,
  getProjectRunDetail,
  exportRunUrl,
} from "../../lib/terraquantum/frontendApi";
import { AppState, VoxelInfo, runKeyOf } from "../../store/useAppStore";
import type { BlockModelDataMode } from "../../store/useAppStore";
import type { VoxelData } from "../../lib/terraQuantumGeology";
// FASE 10: una sola declaración de `BackendVoxelModel` (antes eran 4, y la de
// este archivo era la única que incluía densityMin/densityMax/mode).
import type { BackendVoxelModel } from "../datos/types";



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
    displayResolutionFactor,
    setDisplayResolutionFactor,
    setSelectedVoxel,
    showLegend,
    visibleCellCount,
    highlightedCellCount,
    returnedVoxels,
    visualLayer,
    lodLevel,
    setLodLevel,
  } = useAppStore() as AppState;

  const hasElevation =
    hasElevationData || hasValidElevationRange(blockModelElevationRange);

  // ── FASE 1 (H-28/H-36): el visor sólo pinta datos DE LA CORRIDA ACTIVA ──────
  // El modelo lleva sellada la identidad de la evaluación que lo produjo. Si no
  // coincide con la corrida activa, no se dibuja: mostrar el modelo del survey
  // equivocado sin avisar es el peor error posible en una herramienta cuyo único
  // propósito es decidir dónde perforar. La invalidación central del store hace
  // que esto casi nunca ocurra; esta comprobación es la que lo vuelve imposible.
  const modelRunKey = useAppStore((s) => s.modelRunKey);
  const resultIsStale = useAppStore((s) => s.resultIsStale);
  const modelBelongsToActiveRun = modelRunKey === runKeyOf(activeRun);
  const showModel = show3D && !!model && modelBelongsToActiveRun;
  const modelIsForeign = !!model && !modelBelongsToActiveRun;

  const blockModelReloadRequestRef = React.useRef(0);
  const previousBlockModelDataModeRef =
    React.useRef<BlockModelDataMode>(blockModelDataMode);
  const previousLodLevelRef = React.useRef<'far' | 'medium' | 'full'>(lodLevel);

  // Fase 10 v0.4.0 — Zarr progressive loader state
  const [zarrLoadProgress, setZarrLoadProgress] = React.useState(0);
  const [isZarrLoading, setIsZarrLoading] = React.useState(false);

  // Estados de la interfaz fake eliminados

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
  const viewMode = useAppStore((s) => s.viewMode);
  const isWorkerProcessing = useAppStore((s) => s.isWorkerProcessing);
  const susceptibilityDataAvailable = useAppStore((s) => s.susceptibilityDataAvailable);
  const report = useAppStore((s) => s.report);

  // Etiqueta legible del objeto físico en cálculo (HITO 6 overlay).
  const viewModeLabel =
    viewMode === "susceptibility"
      ? "Susceptibilidad"
      : viewMode === "joint"
      ? "Conjunto (Joint)"
      : "Densidad";
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

  // ── FASE 1 (H-34): la leyenda usa la MISMA escala que el visor ──────────────
  // Los stops replican los colormaps de terraQuantumGeology.ts: Viridis para
  // densidad/contraste, Plasma para susceptibilidad, Inferno para incertidumbre.
  // Si divergen, la leyenda estaría describiendo colores que nadie pintó.
  const isSusceptibilityLayer = viewMode === "susceptibility";
  const LEGEND_GRADIENTS = {
    density:
      "linear-gradient(to right, rgb(68,1,84) 0%, rgb(72,36,117) 12.5%, rgb(65,68,135) 25%, rgb(53,95,141) 37.5%, rgb(42,120,142) 50%, rgb(33,145,140) 62.5%, rgb(34,168,132) 75%, rgb(122,209,81) 87.5%, rgb(253,231,37) 100%)",
    susceptibility:
      "linear-gradient(to right, rgb(13,8,135) 0%, rgb(75,3,161) 12.5%, rgb(120,0,168) 25%, rgb(160,33,150) 37.5%, rgb(193,70,124) 50%, rgb(221,106,98) 62.5%, rgb(241,146,71) 75%, rgb(252,193,40) 87.5%, rgb(240,249,33) 100%)",
    uncertainty:
      "linear-gradient(to right, rgb(0,0,4) 0%, rgb(31,12,42) 14.3%, rgb(94,21,83) 28.6%, rgb(148,18,76) 42.9%, rgb(199,61,57) 57.1%, rgb(239,126,31) 71.4%, rgb(252,191,90) 85.7%, rgb(252,255,164) 100%)",
  } as const;
  const activeLegendGradient = isSusceptibilityLayer
    ? LEGEND_GRADIENTS.susceptibility
    : visualLayer === "uncertainty"
    ? LEGEND_GRADIENTS.uncertainty
    : LEGEND_GRADIENTS.density;

  // FASE 1 (H-28): `resetExplorationState` vivía aquí y NUNCA se llamaba desde
  // ningún sitio — era la limpieza correcta esperando a que alguien se acordara.
  // Su trabajo (modelo, show3D, reporte, heatmap, target/vóxel, terreno) lo hace
  // ahora el store al cambiar o limpiar la identidad de la corrida, que es el
  // punto por el que pasan TODOS los caminos. Convertido en invariante, borrado
  // como función muerta.

  // Fase 10 v0.4.0 — Zarr progressive chunk loader.
  // Returns assembled BackendVoxelModel when Zarr store exists, null otherwise.
  const loadBlockModelZarr = React.useCallback(
    async (projectId: string, runId: string) => {
      // 1. Fetch metadata (returns 404 when grid < 500k voxels → use normal path)
      const metaRes = await fetch(
        `/api/block-model-zarr?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`
      );
      if (!metaRes.ok) return null; // 404 = no Zarr store, fall through to Arrow

      const meta = await metaRes.json() as {
        total_voxels: number; chunk_count: number; chunk_size_voxels: number;
        bounds: { x_min: number; x_max: number; y_min: number; y_max: number; z_min: number; z_max: number };
      };

      setIsZarrLoading(true);
      setZarrLoadProgress(0);

      const allVoxels: unknown[] = [];
      const { chunk_count, bounds } = meta;

      try {
        for (let i = 0; i < chunk_count; i++) {
          const chunkRes = await fetch(
            `/api/block-model-zarr?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}&chunk_idx=${i}`
          );
          if (!chunkRes.ok) break;
          const chunkData = await chunkRes.json() as { voxels: unknown[] };
          allVoxels.push(...(chunkData.voxels ?? []));
          setZarrLoadProgress(Math.round(((i + 1) / chunk_count) * 100));
        }
      } finally {
        setIsZarrLoading(false);
        setZarrLoadProgress(0);
      }

      if (allVoxels.length === 0) return null;

      // Compute domain from bounds (Three.js centers voxels at origin)
      const domainL = Math.max(bounds.x_max - bounds.x_min, 1);
      const domainH = Math.max(bounds.y_max - bounds.y_min, 1);
      const domainW = Math.max(bounds.z_max - bounds.z_min, 1);

      return {
        cells: allVoxels,
        domainL,
        domainH,
        domainW,
        cellSize: 10,
        volumeM3: domainL * domainH * domainW,
        mode: "zarr",
        visualMode: "density_probability",
        warnings: [],
      } as BackendVoxelModel;
    },
    [setIsZarrLoading, setZarrLoadProgress]
  );

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

  // ── FASE 1 (H-27): avisos de la corrida en la vista donde se decide ─────────
  // El backend ya declara sus degradaciones (topografía plana, ajuste débil…) en
  // `warnings[]`. Antes sólo se veían en el detalle de Historial; aquí llegan a la
  // pantalla donde el usuario mira el modelo y elige dónde perforar.
  const [runWarnings, setRunWarnings] = React.useState<string[]>([]);
  // FASE 9: `true` sólo si el backend declaró explícitamente que NO convergió.
  // `null` (no aplica: la ruta acotada no usa LSQR) NO es un fallo y no avisa.
  const [solverDidNotConverge, setSolverDidNotConverge] = React.useState(false);
  useEffect(() => {
    let isMounted = true;
    // FASE 9: antes exigía `status === "ready"`, así que una corrida en ERROR
    // —la que más motivos tiene para traer avisos— no pedía ninguno. `ready` y
    // `error` son los dos estados terminales: en ambos hay reporte que leer.
    // `fetchRunReport` ya devuelve null si aún no hay nada persistido.
    const terminal = activeRun.status === "ready" || activeRun.status === "error";
    if (!activeRun.projectId || !activeRun.runId || !terminal) {
      setRunWarnings([]);
      setSolverDidNotConverge(false);
      return () => {
        isMounted = false;
      };
    }
    // Una sola lectura del detalle para las DOS señales que la vista necesita.
    fetchRunReport(activeRun.projectId, activeRun.runId)
      .then((rep) => {
        if (!isMounted) return;
        setRunWarnings(extractRunWarnings(rep));
        setSolverDidNotConverge(solverConverged(rep) === false);
      })
      .catch(() => {
        if (!isMounted) return;
        setRunWarnings([]);
        setSolverDidNotConverge(false);
      });
    return () => {
      isMounted = false;
    };
  }, [activeRun.projectId, activeRun.runId, activeRun.status]);

  useEffect(() => {
    const previousMode = previousBlockModelDataModeRef.current;
    const previousLod = previousLodLevelRef.current;
    previousBlockModelDataModeRef.current = blockModelDataMode;
    previousLodLevelRef.current = lodLevel;

    if (previousMode === blockModelDataMode && previousLod === lodLevel) return;
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
        // Fase 10 v0.4.0: Zarr-first path for grids >500k voxels.
        // Falls back to Arrow when no Zarr store exists (small grids).
        const zarrModel = await loadBlockModelZarr(
          activeRun.projectId as string,
          activeRun.runId as string,
        );
        if (zarrModel) {
          if (blockModelReloadRequestRef.current !== requestId) return;
          if (preservedElevationMeta) setBlockModelElevationMeta(preservedElevationMeta);
          setModel(zarrModel);
          setShow3D(true);
          setSliceX(zarrModel.domainL / 2);
          return;
        }

        const blockResult = await getExplorationBlockModelForRunWithArrow(
          activeRun.projectId as string,
          activeRun.runId as string,
          blockModelDataMode,
          limitForBlockModelMode(blockModelDataMode),
          1,
          lodLevel
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
    loadBlockModelZarr,
    lodLevel,
    model,
    setBlockModelElevationMeta,
    setIsBlockModelLoading,
    setModel,
    setShow3D,
    setSliceX,
    show3D,
    view,
  ]);

  // handleSyncMachine eliminado

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
                      showModel ? "bg-accent" : "bg-white/25"
                    }`}
                  />
                  {showModel ? "Modelo cargado" : "Sin modelo"}
                </span>
                {activeRun.runId && (
                  <span className="truncate max-w-[180px]">Run: {activeRun.runId}</span>
                )}
                {showModel && <span>{loadedVoxelCount.toLocaleString()} vóxeles</span>}
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
                id: "resolution",
                label: `Resolución · ${
                  displayResolutionFactor >= 6 ? "Máxima ~1.7M"
                    : displayResolutionFactor >= 4 ? "Alta ~500k"
                    : "Nativa"
                }`,
                active: displayResolutionFactor > 1,
                disabled: !showModel,
                // Cicla Nativa(1) → Alta(4, ~500k) → Máxima(6, ~1.7M). Es solo
                // densificado de display (interpolación trilineal); la inversión
                // no cambia. Al cambiar, el panel recarga el modelo al factor nuevo.
                onClick: () => setDisplayResolutionFactor(
                  displayResolutionFactor >= 6 ? 1 : displayResolutionFactor >= 4 ? 6 : 4
                ),
              },
              {
                id: "reset",
                label: "Reset Cámara",
                disabled: !showModel,
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
            <SidebarSection title="Modelo 3D">
              <LoadPanel />
            </SidebarSection>
            {/* FASE 13: arriba del todo y SIEMPRE montado (no sólo con modelo),
                porque también registra los atajos Ctrl+Z/Ctrl+Y de esta vista y
                porque tiene que poder decir «hay una inversión en curso»
                justamente cuando todavía no hay modelo que enseñar. */}
            <SidebarSection title="Historial de cambios">
              <HistorialVisorControls />
            </SidebarSection>
            {showModel && (
              <SidebarSection title="Isosuperficies">
                <IsosurfaceControls />
              </SidebarSection>
            )}
            {showModel && (
              <SidebarSection title="Sondajes">
                <BoreholeControls />
              </SidebarSection>
            )}
            {showModel && (
              <SidebarSection title="Horizonte DOI">
                <DoiOverlayControls />
              </SidebarSection>
            )}
            {showModel && (
              <SidebarSection title="Corte caja A-A' / B-B'">
                <BoxClipControls />
              </SidebarSection>
            )}
            {showModel && (
              <SidebarSection title="Plano de corte">
                <SliceControls />
              </SidebarSection>
            )}
            {activeRun.projectId && activeRun.runId && (
              <SidebarSection title="Descargar">
                <ExportPanel projectId={activeRun.projectId} runId={activeRun.runId} />
              </SidebarSection>
            )}
          </div>
        }
        viewport={
          <div className="h-full min-h-0 border border-white/10 rounded-3xl overflow-hidden bg-[#050505] relative shadow-[0_0_50px_rgba(0,0,0,0.5)] flex flex-col tq-grid-bg">
            <div className="flex-grow relative min-w-0 min-h-0 overflow-hidden">
              {!showModel ? (
                <div
                  data-testid="viewport-empty-state"
                  className="absolute inset-0 flex flex-col items-center justify-center px-6 text-neutral-600 text-[10px] tracking-[0.28em] uppercase text-center"
                >
                  {modelIsForeign ? (
                    // FASE 1 (H-28): hay un modelo en memoria pero pertenece a OTRA
                    // corrida. No se pinta y se dice por qué: el silencio es lo que
                    // hacía que el usuario creyera estar viendo sus datos nuevos.
                    <>
                      <span className="break-words text-amber-400/80">
                        Modelo no válido para los datos actuales
                      </span>
                      <span className="mt-3 max-w-[340px] text-[9px] tracking-[0.12em] text-neutral-500 normal-case">
                        El modelo cargado corresponde a otra corrida. Genera el paquete
                        con los datos actuales y vuelve a cargar el modelo 3D.
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="break-words">Esperando inversión gravimétrica</span>
                      <span className="mt-3 max-w-[320px] text-[9px] tracking-[0.12em] text-neutral-700 normal-case">
                        Sube un CSV, valida datos y carga el modelo 3D generado.
                      </span>
                    </>
                  )}
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
                  <CanvasExportBridge />
                </Canvas>
              )}
              {/* ── HITO 6: overlay no-bloqueante mientras el WebWorker construye ──
                   la geometría masiva (150k–500k vóxeles). pointer-events-none:
                   la cámara/OrbitControls siguen interactivos por debajo. */}
              {showModel && isWorkerProcessing && (
                <div className="absolute inset-0 z-40 flex items-center justify-center pointer-events-none">
                  <div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" />
                  <div className="relative flex flex-col items-center gap-4 px-8 py-6 rounded-2xl border border-cyan-400/25 bg-[#05070a]/85 shadow-[0_8px_40px_rgba(0,0,0,0.6)]">
                    <span className="h-10 w-10 rounded-full border-2 border-cyan-400/25 border-t-[#22d3ee] animate-spin" />
                    <div className="flex flex-col items-center gap-1">
                      <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-[#22d3ee]">
                        Procesando geometría masiva en GPU
                      </span>
                      <span className="text-[9px] font-mono tracking-[0.14em] text-white/55">
                        Objeto: {viewModeLabel}
                      </span>
                    </div>
                  </div>
                </div>
              )}
              {/* ── Fase 10: Zarr progressive loader overlay ─────────────────────── */}
              {isZarrLoading && (
                <div className="absolute inset-0 z-50 flex items-end justify-start p-4 pointer-events-none">
                  <div className="flex flex-col gap-2 px-4 py-3 rounded-xl border border-emerald-400/25 bg-[#05070a]/90 shadow-[0_8px_40px_rgba(0,0,0,0.6)] min-w-[240px]">
                    <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-emerald-400">
                      Cargando modelo Zarr...
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-emerald-400 rounded-full transition-all duration-300"
                          style={{ width: `${zarrLoadProgress}%` }}
                        />
                      </div>
                      <span className="text-[9px] font-mono text-white/55 tabular-nums w-8 text-right">
                        {zarrLoadProgress}%
                      </span>
                    </div>
                  </div>
                </div>
              )}
              {/* ── Fase 12: Panel Multi-Física (overlay sobre el Canvas) ────────── */}
              {/* FASE 9: montado por fin. El panel existía completo desde la Fase 12
                  y su único llamador vivo era el automático de `packageInversion`,
                  así que el badge de más abajo avisaba de un modo que el usuario no
                  podía elegir. Va fuera del <Canvas> (es DOM, no R3F) y fuera de la
                  columna de avisos, que es `pointer-events-none`: dentro de ella
                  quedaría montado pero muerto al clic — otra vez UI inalcanzable. */}
              {showModel && <MultiPhysicsControls />}

              {/* ── Avisos flotantes sobre el modelo ─────────────────────────────
                  FASE 9: los dos badges que había ocupaban EXACTAMENTE la misma
                  posición (`top-2 left-1/2`) y sólo no chocaban porque uno se
                  excluía con `!resultIsStale`. Al añadir un tercero —la
                  no-convergencia, que es independiente de los otros dos— eso deja
                  de sostenerse. Se apilan en una columna. */}
              <div className="absolute top-2 left-1/2 -translate-x-1/2 z-30 flex flex-col items-center gap-1.5 pointer-events-none">
                {/* ── FASE 1 (§9H.2): resultado DESACTUALIZADO ────────────────── */}
                {/* El modelo sigue siendo real, pero los parámetros de preparación
                    cambiaron después de esta inversión: lo que se ve ya no es lo que
                    la interfaz declara. Se marca en pantalla en vez de borrarlo. */}
                {showModel && resultIsStale && (
                  <div
                    data-testid="stale-result-badge"
                    className="flex items-center gap-1.5 bg-black/80 border border-amber-500/70 text-amber-300 text-[10px] font-mono px-3 py-1 rounded-full"
                  >
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
                    Resultado desactualizado: cambiaste parámetros tras esta inversión
                  </div>
                )}

                {/* ── FASE 9: el solver no convergió ───────────────────────────
                    La Fase 7 midió que el LSQR magnético termina por límite de
                    iteraciones (istop=7, 500/500) y que ahí un parámetro inerte
                    sobre el papel mueve el resultado hasta un 86 %. El dato ya
                    viajaba en el reporte; lo que faltaba era decirlo donde se
                    mira el modelo. El detalle está en «Funcional y convergencia». */}
                {showModel && solverDidNotConverge && (
                  <div
                    data-testid="solver-not-converged-badge"
                    className="flex items-center gap-1.5 bg-black/80 border border-yellow-500/70 text-yellow-300 text-[10px] font-mono px-3 py-1 rounded-full"
                  >
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-yellow-400" />
                    El solver no convergió: es donde se detuvo, no la solución
                  </div>
                )}

                {/* Badge: datos magnéticos no disponibles para la corrida actual */}
                {showModel && !resultIsStale && viewMode === 'susceptibility' && !susceptibilityDataAvailable && (
                  <div className="flex items-center gap-1.5 bg-black/75 border border-yellow-500/60 text-yellow-400 text-[10px] font-mono px-3 py-1 rounded-full">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-yellow-400" />
                    Datos magnéticos no disponibles para este modelo
                  </div>
                )}
              </div>
            </div>

            {showModel && (
              <div className="h-auto shrink-0 bg-black/70 border-t border-white/10 px-3 py-2 flex items-center justify-center overflow-hidden">
                {/* BottomControls eliminado: ahora moved to Sidebar (Fase C) */}
              </div>
            )}
          </div>
        }
        analytics={
          <>
            {/* FASE 1 (H-27) + FASE 9: lo que el backend degradó, dicho aquí.
                La Fase 1 lo montó DENTRO de la rama `showModel`, de modo que los
                avisos desaparecían justo cuando el modelo no se podía pintar —
                que es cuando más falta hacen (solver que no converge, corrida en
                error). Ahora vive fuera del ternario y se ve haya modelo o no. */}
            {runWarnings.length > 0 && (
              <div data-testid="run-warnings" className="mb-3">
                <WarningBanner
                  warnings={warningViewsFromTexts(runWarnings)}
                  showAction={false}
                />
              </div>
            )}
            {showModel ? (
            <>
              {resultIsStale && (
                <div className="mb-3 rounded border border-amber-500/50 bg-amber-950/20 px-3 py-2">
                  <p className="text-[10px] leading-relaxed text-amber-300">
                    Cambiaste parámetros de preparación después de esta inversión. El
                    modelo mostrado sigue siendo el de la corrida anterior: vuelve a
                    generar el paquete y a invertir para ver el resultado de los
                    parámetros actuales.
                  </p>
                </div>
              )}
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
                  <span className="col-span-2 mt-2 mb-1 text-[7px] uppercase tracking-wider text-white/30">
                    Detalle renderizado (LOD)
                  </span>
                  <span className="col-span-2">
                    <div className="flex gap-1">
                      {(["far", "medium", "full"] as const).map((lvl) => (
                        <button
                          key={lvl}
                          onClick={() => setLodLevel(lvl)}
                          className={`flex-1 rounded px-1 py-1 text-[7px] font-mono transition-colors ${
                            lodLevel === lvl
                              ? "bg-accent text-black font-bold"
                              : "bg-white/10 text-white/55 hover:bg-white/20"
                          }`}
                        >
                          {lvl === "far" ? "Far 1%" : lvl === "medium" ? "Med 10%" : "Full"}
                        </button>
                      ))}
                    </div>
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
                    {/* FASE 1 (H-34): la barra de la leyenda refleja la escala QUE
                        SE ESTÁ PINTANDO. Antes era Viridis fija incluso en la capa
                        de susceptibilidad — la leyenda mentía sobre el color. */}
                    <div
                      className="h-2 w-full rounded-sm"
                      style={{ background: activeLegendGradient }}
                    />
                    <div className="mt-1 flex justify-between text-[7px] font-mono text-white/45">
                      {isSusceptibilityLayer ? (
                        <>
                          <span>Menos susceptible</span>
                          <span>Más susceptible</span>
                        </>
                      ) : (
                        <>
                          <span>Menos denso</span>
                          <span>Roca fondo</span>
                          <span>Más denso</span>
                        </>
                      )}
                    </div>
                    {!isSusceptibilityLayer && (() => {
                      const dMin = (model as { densityMin?: number })?.densityMin;
                      const dMax = (model as { densityMax?: number })?.densityMax;
                      return Number.isFinite(dMin) && Number.isFinite(dMax) ? (
                        <div className="mt-0.5 flex justify-between text-[7px] font-mono text-white/55">
                          <span>{(dMin as number).toFixed(2)}</span>
                          <span>t/m³</span>
                          <span>{(dMax as number).toFixed(2)}</span>
                        </div>
                      ) : null;
                    })()}
                    {!isSusceptibilityLayer && (
                      <p className="text-[7px] font-mono text-white/30 mt-1 leading-tight">
                        Contraste vs. fondo {formatLegendPercentile(layerPercentiles.p95)} t/m³ (P95)
                      </p>
                    )}
                    {isSusceptibilityLayer && (
                      <p className="text-[7px] font-mono text-white/30 mt-1 leading-tight">
                        Susceptibilidad magnética (SI), escala logarítmica
                      </p>
                    )}
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

              <MviDirectionPanel model={model} report={report} />

              <Panel title="Calidad de Inversión">
                <InversionQualityBadge />
              </Panel>

              <Panel title="Render Volumétrico" subtitle="Fase 6 — raymarch (visual)">
                <VolumeRenderControls />
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
            )}
          </>
        }
      />
    </div>
  );
}
