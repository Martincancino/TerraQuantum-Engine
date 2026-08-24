import { create } from 'zustand';
// FASE 13: el historial de comandos se engancha aquí y en ningún otro sitio.
// `conHistorial` envuelve el `set` que reciben las 93 acciones y también el
// `setState` de la api, calcula el delta sobre las claves declaradas en
// `deshacible.ts` y lo registra. Ninguna acción de este fichero sabe que existe.
import { conHistorial } from './historialVisor';
import type { TerrainResponse, VoxelMineralModel } from '../lib/terraQuantumGeology';
import type { IsosurfaceData } from '../lib/render/IsosurfaceMeshLayer';
import type { BoreholeViewData } from '../lib/render/BoreholeLayer';
import type { SectionData } from '../lib/render/SectionPaintLayer';
import type { DoiOverlayData } from '../lib/render/DoiOverlayLayer';
import type { FavorabilityResult } from '../componentes/datos/favorability_types';
import type { GeorefConfidence, ProjectFootprint, CrsInfo, ElevationRange, PercentileStats, GravityImportPreviewResponse, GravityCsvInvertResponse } from '../lib/terraquantum/frontendApi';

// Tipos mínimos para campos que antes eran any[]
export interface HeatmapPoint {
  x: number;
  y: number;
  value: number;
  density?: number;
  probability?: number;
}

export interface TargetInfo {
  x_m?: number;
  y_m?: number;
  z_m?: number;
  density?: number;
  density_proxy_index?: number;
  probability?: number;
  [key: string]: number | string | undefined;
}

export interface VoxelInfo {
  cx?: number; x?: number;
  cy?: number; y?: number;
  cz?: number; z?: number;
  density?: number;
  rho?: number;
  probability?: number;
  [key: string]: number | undefined;
}

/** Vóxel seleccionado por picking (raycast sobre el instancedMesh). */
export interface SelectedVoxel {
  index: number;
  cell: Record<string, number | string | boolean | null | undefined>;
  position: [number, number, number];
}

export interface GeoRankingTarget {
  id: string;
  probabilidad: number;
  profundidad: number;
  coordenadas: string;
  estado: string;
}

export interface GeoReportInfo {
  status?: string;
  recommendation?: string;
  risk_level?: string;
  profundidad?: number;
  masaKg?: number;
  anomaliaPico?: number;
  clasificacionEstructural?: string;
  contrasteDensidad?: string;
  leyPromedio?: string;
  indiceAnomalia?: string | number;
  zonaGeografica?: string;
  firmaSuperficial?: string;
  justificacion?: string;
  score?: number;
  uncertainty?: number;
  estimatedAnomalyTonnage?: number;
  rankingTargets?: GeoRankingTarget[];
  recomendacionPerforacion?: boolean;
  // DV-02: run degenerado (misfit indefinido + sin best_target). Declarado
  // explícito: si cae al index signature unknown, el guard JSX
  // `{report?.isDegraded && ...}` tipa unknown y rompe el build.
  isDegraded?: boolean;
  [key: string]: unknown;
}

export type ActiveRunSource =
  | "csv"
  | "synthetic"
  | "history"
  | "legacy"
  | null;

export type ActiveRunStatus =
  | "idle"
  | "loading"
  | "ready"
  | "error";

export interface ActiveRunState {
  projectId: string | null;
  runId: string | null;
  source: ActiveRunSource;
  status: ActiveRunStatus;
  error: string | null;
  importMetadata: Record<string, unknown> | null;
  observationsSummary: Record<string, unknown> | null;
  reportSummary: Record<string, unknown> | null;
  focusing: Record<string, unknown> | null;
}

export type VisualLayer =
  | "modeled_density"
  | "anomaly_intensity"
  | "target_score"
  | "density_anomaly_score"
  | "uncertainty";

export type SliceAxis = "x" | "y" | "z" | "none";

// ── Fase 6: Render volumétrico (raymarch opt-in) ─────────────────────────────
/** "off" = renderer instanciado clásico; "fog"/"isosurface" = raymarch WebGL2. */
export type VolumeRenderMode = "off" | "fog" | "isosurface";

// ── Fase 12: Render Multi-Física ─────────────────────────────────────────────
/** Modo de visualización de la capa física activa en el InstancedMesh. */
export type ViewMode = 'density' | 'susceptibility' | 'joint';

export type BlockModelDataMode = "exploration" | "full" | "anomaly";

/** Schema v3.0 — contrato unificado de vóxel de bloque para gravity / magnetic / joint.
 *  Espejo TypeScript de GeophysicsVoxel (schemas/geophysics_schema.py).
 */
export interface UnifiedVoxelCell {
  run_type?: 'gravity' | 'magnetic' | 'joint';
  schema_version?: string;
  // Coordenadas (aliases según el run path)
  x_m?: number; x?: number;
  y_m?: number; y?: number;
  z_m?: number; z?: number;
  // Gravity
  density?: number;
  density_t_m3?: number;
  density_contrast_t_m3?: number;
  density_anomaly_score?: number;
  // Magnetic / joint
  susceptibility_si?: number;
  susceptibility_score?: number;
  joint_structural_score?: number;
  // Uncertainty / DOI
  posterior_std?: number;
  doi_raw?: number;
  [key: string]: number | string | boolean | null | undefined;
}

export type VoxelTracePatch = {
  totalVoxels?: number | null;
  storedVoxels?: number | null;
  anomalyVoxels?: number | null;
  returnedVoxels?: number | null;
  blockModelMode?: string | null;
};

export interface AppState {
  // 1. CORE & VISTAS
  activeRun: ActiveRunState;
  setActiveRun: (patch: Partial<ActiveRunState>) => void;
  clearActiveRun: () => void;

  view: string;
  setView: (v: string) => void;
  model: VoxelMineralModel | null;
  setModel: (m: VoxelMineralModel | null) => void;

  // ── FASE 1 (H-28/H-36): el modelo 3D es un DATO EVALUADO ───────────────────
  // Identidad de la corrida que produjo el `model` actual, sellada en setModel.
  // El modelo no es un objeto libre que vive por su cuenta: PERTENECE a una
  // evaluación. Si la corrida activa cambia de identidad (otro CSV, otro run) el
  // modelo deja de ser válido por construcción y la vista 3D se niega a pintarlo,
  // en vez de depender de que alguien se acuerde de llamar a una limpieza.
  modelRunKey: string | null;
  /** true = hay modelo cargado y corresponde a la corrida activa. */
  isModelForActiveRun: () => boolean;

  // ── FASE 1 (§9H.2): invalidación "stale" ───────────────────────────────────
  // El usuario cambió parámetros de preparación DESPUÉS de esta inversión: el
  // resultado en pantalla sigue siendo real, pero ya no corresponde a lo que la
  // interfaz muestra como configuración. Se marca; no se borra.
  resultIsStale: boolean;
  markResultStale: () => void;

  // ── Fase F4.2: Isosuperficies del backend (mallas suaves) ──────────────────
  /** Mallas de /v2/isosurface (ya en espacio visual). null = no cargadas. */
  isosurfaceData: IsosurfaceData | null;
  setIsosurfaceData: (d: IsosurfaceData | null) => void;
  /** Mostrar isosuperficies (default off hasta el QA visual). */
  showIsosurfaces: boolean;
  setShowIsosurfaces: (v: boolean) => void;

  // ── Fase F4.4: Sondajes en el visor 3D ─────────────────────────────────────
  boreholeData: BoreholeViewData | null;
  setBoreholeData: (d: BoreholeViewData | null) => void;
  showBoreholes: boolean;
  setShowBoreholes: (v: boolean) => void;

  // ── Fase F4.3: Cara del corte pintada ──────────────────────────────────────
  sectionData: SectionData | null;
  setSectionData: (d: SectionData | null) => void;
  /** Pintar la cara del corte cuando hay slice activo (default ON). */
  showSectionPaint: boolean;
  setShowSectionPaint: (v: boolean) => void;

  // ── Fase F4.5: Horizonte DOI (incertidumbre visible) ───────────────────────
  doiOverlayData: DoiOverlayData | null;
  setDoiOverlayData: (d: DoiOverlayData | null) => void;
  showDoiOverlay: boolean;
  setShowDoiOverlay: (v: boolean) => void;

  // 2. FAVORABILITY GATE
  favorabilityScore: number | null;
  favorabilityLevel: string | null;
  setFavorabilityGate: (score: number | null, level: string | null) => void;

  // 3. UI 3D (TOGGLES Y SLIDERS)
  showVoxels: boolean;
  setShowVoxels: (show: boolean) => void;
  sliceX: number;
  setSliceX: (val: number) => void;
  show3D: boolean;
  setShow3D: (show: boolean) => void;
  // Reset de cámara por nonce: incrementar dispara una animación suave en Scene3D
  // (CameraRig) en lugar de remontar el <Canvas> y perder el contexto WebGL.
  cameraResetNonce: number;
  requestCameraReset: () => void;
  // Fase 6 (cierre): aquí vivían `postprocessingEnabled` y `setPostprocessingEnabled`,
  // borrados con `viewport/PostFX.tsx`, su ÚNICO lector. La perilla venía en `true` por
  // defecto y no despachaba a ninguna parte: el mismo pecado que USE_SPARSE_DIRECT en el
  // backend, pero en el store. El postprocesado que SÍ se entrega es `subsurfaceAoEnabled`
  // (abajo), que Scene3D monta y `VolumeRenderControls` conmuta de verdad.
  // Picking de vóxel (Fase E): vóxel seleccionado por raycast para el tooltip científico.
  selectedVoxel: SelectedVoxel | null;
  setSelectedVoxel: (v: SelectedVoxel | null) => void;
  showFloor: boolean;
  setShowFloor: (show: boolean) => void;
  showTerrain: boolean;
  setShowTerrain: (val: boolean) => void;
  terrainOpacity: number;
  setTerrainOpacity: (val: number) => void;
  terrainVerticalExaggeration: number;
  setTerrainVerticalExaggeration: (val: number) => void;
  terrainData: TerrainResponse | null;
  setTerrainData: (data: TerrainResponse | null) => void;
  showBoundingBox: boolean;
  setShowBoundingBox: (val: boolean) => void;
  gestureMode: boolean;
  setGestureMode: (show: boolean) => void;

  // 3b. UI 3D VISOR AVANZADO (Fase 7.1)
  visualLayer: VisualLayer;
  setVisualLayer: (layer: VisualLayer) => void;
  // Fase 6 — render volumétrico raymarch (opt-in, default "off")
  volumeRenderMode: VolumeRenderMode;
  setVolumeRenderMode: (mode: VolumeRenderMode) => void;
  // Fase 6 slice 5 — oclusión ambiental screen-space (stand-in de RTAO, opt-in)
  subsurfaceAoEnabled: boolean;
  setSubsurfaceAoEnabled: (val: boolean) => void;
  minTargetScore: number;
  setMinTargetScore: (val: number) => void;
  minAnomalyIntensity: number;
  setMinAnomalyIntensity: (val: number) => void;
  minDensityAnomalyScore: number;
  setMinDensityAnomalyScore: (val: number) => void;
  voxelOpacity: number;
  setVoxelOpacity: (val: number) => void;
  voxelScale: number;
  setVoxelScale: (val: number) => void;
  showLegend: boolean;
  setShowLegend: (val: boolean) => void;
  visualProfessionalMode: boolean;
  displayResolutionFactor: number;
  setDisplayResolutionFactor: (val: number) => void;
  setVisualProfessionalMode: (val: boolean) => void;

  // 3c. CORTES X/Y/Z (Fase 7.2)
  sliceAxis: SliceAxis;
  setSliceAxis: (axis: SliceAxis) => void;
  slicePosition: number;
  setSlicePosition: (val: number) => void;
  sliceThickness: number;
  setSliceThickness: (val: number) => void;
  showOnlySlice: boolean;
  setShowOnlySlice: (val: boolean) => void;
  visibleCellCount: number;
  setVisibleCellCount: (n: number) => void;
  highlightedCellCount: number;
  setHighlightedCellCount: (n: number) => void;
  // Anomalía DÉBIL: el pico de contraste del modelo no supera el umbral robusto.
  // El visor muestra igual el núcleo (top de celdas) pero la UI avisa para que el
  // usuario no confunda "corrió y es débil" con "no corrió".
  anomalyWeak: boolean;
  setAnomalyWeak: (val: boolean) => void;
  susceptibilityDataAvailable: boolean;
  setSusceptibilityDataAvailable: (val: boolean) => void;
  // FASE 20C iter 2: overlay de flechas de magnetización (MVI). Independiente del
  // viewMode: se superpone a cualquier capa. Default off.
  showMviVectors: boolean;
  setShowMviVectors: (val: boolean) => void;
  totalVoxels: number | null;
  storedVoxels: number | null;
  anomalyVoxels: number | null;
  returnedVoxels: number | null;
  blockModelMode: string | null;
  blockModelDataMode: BlockModelDataMode;
  setBlockModelDataMode: (mode: BlockModelDataMode) => void;
  lodLevel: 'far' | 'medium' | 'full';
  setLodLevel: (level: 'far' | 'medium' | 'full') => void;
  isBlockModelLoading: boolean;
  setIsBlockModelLoading: (loading: boolean) => void;
  // HITO 6: true mientras el WebWorker construye los buffers de geometría masiva.
  // Distinto de isBlockModelLoading (carga de API): este cubre el procesamiento
  // off-thread de InstancedMesh para modelos > LOD_WORKER_THRESHOLD.
  isWorkerProcessing: boolean;
  setIsWorkerProcessing: (processing: boolean) => void;
  setVoxelTrace: (trace: VoxelTracePatch) => void;

  // 3d. ENVOLVENTE VISUAL (Fase 7.3)
  showAnomalyEnvelope: boolean;
  setShowAnomalyEnvelope: (val: boolean) => void;
  anomalyEnvelopePercent: number;
  setAnomalyEnvelopePercent: (val: number) => void;

  // 3f. VOLUMEN CONCEPTUAL DEL SUBSUELO (C5.3)
  showHostVolume: boolean;
  setShowHostVolume: (val: boolean) => void;
  hostVolumeOpacity: number;
  setHostVolumeOpacity: (val: number) => void;

  // 3e. FILTRO DENSIDAD ABSOLUTA (Subfase 1B-4)
  minDensityRaw: number | null;
  setMinDensityRaw: (val: number | null) => void;
  maxDensityRaw: number | null;
  setMaxDensityRaw: (val: number | null) => void;

  // 4. MAPEO IA (NLP Y TERRENO)
  geologistNote: string;
  setGeologistNote: (note: string) => void;
  extractedTags: string[];
  setExtractedTags: (tags: string[]) => void;
  geoRegionName: string;
  setGeoRegionName: (name: string) => void;

  // 5. TELEMETRÍA Y GEOFÍSICA
  geoLat: string;
  setGeoLat: (lat: string) => void;
  geoLon: string;
  setGeoLon: (lon: string) => void;
  inputNIR: number;
  setInputNIR: (val: number) => void;
  inputFe: number;
  setInputFe: (val: number) => void;
  inputDepth: number;
  setInputDepth: (val: number) => void;
  inputGrav: number;
  setInputGrav: (val: number) => void;
  region: string;
  setRegion: (reg: string) => void;
  heatmapData: HeatmapPoint[];
  setHeatmapData: (data: HeatmapPoint[]) => void;
  bestTarget: TargetInfo | null;
  setBestTarget: (target: TargetInfo | null) => void;
  bestVoxel: VoxelInfo | null;
  setBestVoxel: (voxel: VoxelInfo | null) => void;
  report: GeoReportInfo | null;
  setReport: (rep: GeoReportInfo | null) => void;
  favorabilityResult: FavorabilityResult | null;
  setFavorabilityResult: (result: FavorabilityResult | null) => void;

  // 5.5 DATASET & INVERSIÓN (PERSISTENCIA CSV Y BBOX)
  fileGravimetry: File | null;
  setFileGravimetry: (file: File | null) => void;
  fileMagnetometry: File | null;
  setFileMagnetometry: (file: File | null) => void;
  latNorth: string;
  setLatNorth: (val: string) => void;
  latSouth: string;
  setLatSouth: (val: string) => void;
  lonEast: string;
  setLonEast: (val: string) => void;
  lonWest: string;
  setLonWest: (val: string) => void;
  gravityPreviewResult: GravityImportPreviewResponse | null;
  setGravityPreviewResult: (res: GravityImportPreviewResponse | null) => void;
  gravityInvertResult: GravityCsvInvertResponse | null;
  setGravityInvertResult: (res: GravityCsvInvertResponse | null) => void;

  // 9. GEOREF (R1-FE-2) + CRS (R2-FE)
  projectFootprint: ProjectFootprint | null;
  georefConfidence: GeorefConfidence | string | null;
  georefWarnings: string[];
  crsInfo: CrsInfo | null;
  setProjectFootprint: (footprint: ProjectFootprint | null) => void;
  setGeorefConfidence: (confidence: GeorefConfidence | string | null) => void;
  setGeorefWarnings: (warnings: string[]) => void;
  setCrsInfo: (info: CrsInfo | null) => void;
  setGeorefState: (payload: {
    footprint?: ProjectFootprint | null;
    confidence?: GeorefConfidence | string | null;
    warnings?: string[];
    crsInfo?: CrsInfo | null;
  }) => void;

  // 10. R3 ELEVATION METADATA
  hasElevationData: boolean;
  blockModelDemSource: string | null;
  blockModelGeorefConfidence: string | null;
  blockModelElevationRange: ElevationRange | null;
  setBlockModelElevationMeta: (meta: {
    hasElevationData?: boolean;
    demSource?: string | null;
    georefConfidence?: string | null;
    elevationRange?: ElevationRange | null;
  }) => void;

  // 11. PERCENTILE STATS (modelo completo, calculado por backend antes del sampling)
  percentileStats: PercentileStats | null;
  setPercentileStats: (stats: PercentileStats | null) => void;

  // 12. RENDER SETTINGS — Fase 12 Multi-Física
  // Aislado del blockModel y la cámara para evitar cascading renders.
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  jointThreshold: number;
  setJointThreshold: (val: number) => void;

  // 13. CORTE CAJA (Sprint 4A) — 6 planes AABB para secciones A-A'/B-B'
  // Independiente del sliceAxis: puede usarse junto al corte half-space.
  clipBoxEnabled: boolean;
  setClipBoxEnabled: (val: boolean) => void;
  clipBox: { xMin: number; xMax: number; yMin: number; yMax: number; zMin: number; zMax: number };
  setClipBox: (patch: Partial<{ xMin: number; xMax: number; yMin: number; yMax: number; zMin: number; zMax: number }>) => void;

  // 14. DOI THRESHOLD (Fase 7B-1) — slider interactivo 0.0–1.0
  doiThreshold: number;
  setDoiThreshold: (val: number) => void;

  // 15. F5 — PUENTE DE CAPTURA PNG (Canvas → botonera de descarga)
  // Función viva del renderer (no serializable) que registra CanvasExportBridge
  // al montar el <Canvas>; ExportPanel la lee para exportar PNG de alta resolución.
  capturePngSnapshot: ((targetWidthPx: number) => string) | null;
  setCapturePngSnapshot: (fn: ((targetWidthPx: number) => string) | null) => void;
}

/** Identidad estable de una corrida — clave de procedencia del modelo 3D (H-28).
 *  Una corrida sin identidad ("∅") nunca coincide con otra: un modelo cargado sin
 *  corrida activa no puede reclamar pertenecer a la siguiente que aparezca. */
export function runKeyOf(run: Pick<ActiveRunState, "projectId" | "runId">): string {
  if (!run.projectId || !run.runId) return "∅";
  return `${run.projectId}::${run.runId}`;
}

export const useAppStore = create<AppState>(conHistorial((set, get) => ({
  // 1. CORE & VISTAS
  activeRun: {
    projectId: null,
    runId: null,
    source: null,
    status: "idle",
    error: null,
    importMetadata: null,
    observationsSummary: null,
    reportSummary: null,
    focusing: null,
  },
  setActiveRun: (patch) =>
    set((state) => {
      // Trazabilidad (reviewer F4, hallazgo T1): al cambiar la IDENTIDAD de la
      // corrida se invalidan los caches del visor derivados de ella — si no,
      // Historial podría dibujar sondajes/velo DOI/sección del run ANTERIOR
      // sobre el modelo nuevo. (isosurface/section re-fetchean solos; borehole
      // y DOI solo cargan al toggle, por eso la limpieza central.)
      const runChanged =
        (patch.projectId !== undefined && patch.projectId !== state.activeRun.projectId) ||
        (patch.runId !== undefined && patch.runId !== state.activeRun.runId);
      return {
        activeRun: {
          ...state.activeRun,
          ...patch,
        },
        ...(runChanged
          ? {
              isosurfaceData: null,
              boreholeData: null,
              sectionData: null,
              doiOverlayData: null,
              // FASE 1 (H-28): el modelo pertenece a la evaluación anterior; con
              // otra identidad de corrida deja de ser un dato válido. Se cae
              // aquí, en el único sitio por el que pasa todo cambio de corrida,
              // y no en cada manejador que recuerde limpiarlo.
              model: null,
              modelRunKey: null,
              show3D: false,
              report: null,
              resultIsStale: false,
              // Derivados de la corrida anterior que también dejarían de
              // corresponder (los limpiaba `resetExplorationState`, que nadie
              // llamaba nunca: ahora la limpieza vive donde sí ocurre siempre).
              heatmapData: [],
              bestTarget: null,
              bestVoxel: null,
            }
          : {}),
      };
    }),
  clearActiveRun: () =>
    set({
      activeRun: {
        projectId: null,
        runId: null,
        source: null,
        status: "idle",
        error: null,
        importMetadata: null,
        observationsSummary: null,
        reportSummary: null,
        focusing: null,
      },
      // FASE 1 (H-28): sin corrida activa no hay modelo que mostrar. Antes el
      // modelo y show3D vivían fuera de esta limpieza, así que el visor 3D seguía
      // pintando el resultado del CSV anterior tras cargar uno nuevo.
      model: null,
      modelRunKey: null,
      show3D: false,
      report: null,
      resultIsStale: false,
      heatmapData: [],
      bestTarget: null,
      bestVoxel: null,
      isosurfaceData: null,
      boreholeData: null,
      sectionData: null,
      doiOverlayData: null,
      terrainData: null,
      favorabilityResult: null,
      favorabilityScore: null,
      favorabilityLevel: null,
      projectFootprint: null,
      georefConfidence: null,
      georefWarnings: [],
      crsInfo: null,
      hasElevationData: false,
      blockModelDemSource: null,
      blockModelGeorefConfidence: null,
      blockModelElevationRange: null,
      percentileStats: null,
    }),

  view: "inicio",
  setView: (v) => set({ view: v }),
  model: null,
  // ── FASE 1 (H-28/H-36) — identidad de la evaluación que produjo el modelo ───
  modelRunKey: null,
  isModelForActiveRun: () => {
    const s = get();
    if (!s.model) return false;
    return s.modelRunKey === runKeyOf(s.activeRun);
  },
  resultIsStale: false,
  markResultStale: () => {
    // Sólo tiene sentido marcar como desactualizado algo que se está mostrando.
    const s = get();
    if (s.model && s.activeRun.runId) set({ resultIsStale: true });
  },
  setModel: (m) => {
    set({
      model: m,
      // Sello de procedencia: el modelo queda atado a la corrida vigente en el
      // momento de cargarlo. Quien llame a setModel debe haber fijado ya la
      // identidad de la corrida (setActiveRun) — el orden importa y está
      // verificado en los recorridos E2E de la Fase 1.
      modelRunKey: m === null ? null : runKeyOf(get().activeRun),
      // Recargar el MISMO run (p.ej. cambio de resolución de display) no vuelve
      // fresco un resultado que ya estaba marcado: sólo lo hace una corrida nueva.
      resultIsStale:
        m !== null && get().modelRunKey === runKeyOf(get().activeRun)
          ? get().resultIsStale
          : false,
      selectedVoxel: null,
      minDensityRaw: null,
      maxDensityRaw: null,
      ...(m === null
        ? {
            totalVoxels: null,
            storedVoxels: null,
            anomalyVoxels: null,
            returnedVoxels: null,
            blockModelMode: null,
            visibleCellCount: 0,
            highlightedCellCount: 0,
            anomalyWeak: false,
            hasElevationData: false,
            blockModelDemSource: null,
            blockModelGeorefConfidence: null,
            blockModelElevationRange: null,
            percentileStats: null,
            isosurfaceData: null,
            boreholeData: null,
            sectionData: null,
            doiOverlayData: null,
          }
        : {}),
    });
  },

  // ── Fase F4.2: Isosuperficies del backend ──────────────────────────────────
  isosurfaceData: null,
  setIsosurfaceData: (d) => set({ isosurfaceData: d }),
  // Default ON: QA visual aprobado 2026-07-09 (gate F4) — la vista producto es
  // la cáscara suave; los vóxeles quedan como nube fantasma de contexto.
  showIsosurfaces: true,
  setShowIsosurfaces: (v) => set({ showIsosurfaces: v }),

  // ── Fase F4.4: Sondajes en el visor 3D ─────────────────────────────────────
  boreholeData: null,
  setBoreholeData: (d) => set({ boreholeData: d }),
  showBoreholes: false,
  setShowBoreholes: (v) => set({ showBoreholes: v }),

  // ── Fase F4.3: Cara del corte pintada ──────────────────────────────────────
  sectionData: null,
  setSectionData: (d) => set({ sectionData: d }),
  showSectionPaint: true,
  setShowSectionPaint: (v) => set({ showSectionPaint: v }),

  // ── Fase F4.5: Horizonte DOI ────────────────────────────────────────────────
  doiOverlayData: null,
  setDoiOverlayData: (d) => set({ doiOverlayData: d }),
  showDoiOverlay: false,
  setShowDoiOverlay: (v) => set({ showDoiOverlay: v }),

  // 2. FAVORABILITY GATE
  favorabilityScore: null,
  favorabilityLevel: null,
  setFavorabilityGate: (score, level) =>
    set({ favorabilityScore: score, favorabilityLevel: level }),

  // 3. UI 3D (TOGGLES Y SLIDERS)
  showVoxels: true,
  setShowVoxels: (show) => set({ showVoxels: show }),
  sliceX: 0,
  setSliceX: (val) => set({ sliceX: val }),
  show3D: false,
  setShow3D: (show) => set({ show3D: show }),
  cameraResetNonce: 0,
  requestCameraReset: () =>
    set((state) => ({ cameraResetNonce: state.cameraResetNonce + 1 })),
  selectedVoxel: null,
  setSelectedVoxel: (v) => set({ selectedVoxel: v }),
  showFloor: true,
  setShowFloor: (show) => set({ showFloor: show }),
  showTerrain: true,
  setShowTerrain: (val) => set({ showTerrain: val }),
  terrainOpacity: 0.8,
  setTerrainOpacity: (val) => set({ terrainOpacity: val }),
  terrainVerticalExaggeration: 1.2,
  setTerrainVerticalExaggeration: (val) => set({ terrainVerticalExaggeration: val }),
  terrainData: null,
  setTerrainData: (data) => set({ terrainData: data }),
  showBoundingBox: true,
  setShowBoundingBox: (val) => set({ showBoundingBox: val }),
  gestureMode: false,
  setGestureMode: (show) => set({ gestureMode: show }),

  // 3b. UI 3D VISOR AVANZADO (Fase 7.1)
  visualLayer: "modeled_density",
  setVisualLayer: (layer) => set({ visualLayer: layer }),
  volumeRenderMode: "off",
  setVolumeRenderMode: (mode) => set({ volumeRenderMode: mode }),
  subsurfaceAoEnabled: false,
  setSubsurfaceAoEnabled: (val) => set({ subsurfaceAoEnabled: val }),
  minTargetScore: 0.15,
  setMinTargetScore: (val) => set({ minTargetScore: val }),
  minAnomalyIntensity: 0,
  setMinAnomalyIntensity: (val) => set({ minAnomalyIntensity: val }),
  minDensityAnomalyScore: 0,
  setMinDensityAnomalyScore: (val) => set({ minDensityAnomalyScore: val }),
  voxelOpacity: 0.72,
  setVoxelOpacity: (val) => set({ voxelOpacity: val }),
  voxelScale: 1.0,
  setVoxelScale: (val) => set({ voxelScale: val }),
  showLegend: true,
  setShowLegend: (val) => set({ showLegend: val }),
  visualProfessionalMode: true,
  setVisualProfessionalMode: (val) => set({ visualProfessionalMode: val }),
  // Factor de sub-muestreo trilineal SOLO de display (separa resolución de
  // inversión de la de visualización). 1=nativo (~8k), 4=~500k, 6=~1.7M vóxeles.
  displayResolutionFactor: 1,
  setDisplayResolutionFactor: (val) => set({ displayResolutionFactor: val }),

  // 3c. CORTES X/Y/Z (Fase 7.2)
  sliceAxis: "none",
  setSliceAxis: (axis) => set((state) => ({
    sliceAxis: axis,
    slicePosition: axis !== "none" ? 0 : state.slicePosition,
  })),
  slicePosition: 0,
  setSlicePosition: (val) => set({ slicePosition: val }),
  sliceThickness: 20,
  setSliceThickness: (val) => set({ sliceThickness: val }),
  showOnlySlice: false,
  setShowOnlySlice: (val) => set({ showOnlySlice: val }),
  visibleCellCount: 0,
  setVisibleCellCount: (n) => set({ visibleCellCount: n }),
  highlightedCellCount: 0,
  setHighlightedCellCount: (n) => set({ highlightedCellCount: n }),
  anomalyWeak: false,
  setAnomalyWeak: (val) => set({ anomalyWeak: val }),
  susceptibilityDataAvailable: true,
  setSusceptibilityDataAvailable: (val) => set({ susceptibilityDataAvailable: val }),
  showMviVectors: false,
  setShowMviVectors: (val) => set({ showMviVectors: val }),
  totalVoxels: null,
  storedVoxels: null,
  anomalyVoxels: null,
  returnedVoxels: null,
  blockModelMode: null,
  blockModelDataMode: "exploration",
  setBlockModelDataMode: (mode) => set({ blockModelDataMode: mode }),
  lodLevel: 'medium',
  setLodLevel: (level) => set({ lodLevel: level }),
  isBlockModelLoading: false,
  setIsBlockModelLoading: (loading) => set({ isBlockModelLoading: loading }),
  isWorkerProcessing: false,
  setIsWorkerProcessing: (processing) => set({ isWorkerProcessing: processing }),
  setVoxelTrace: (trace) =>
    set((state) => ({
      totalVoxels:
        trace.totalVoxels !== undefined ? trace.totalVoxels : state.totalVoxels,
      storedVoxels:
        trace.storedVoxels !== undefined ? trace.storedVoxels : state.storedVoxels,
      anomalyVoxels:
        trace.anomalyVoxels !== undefined
          ? trace.anomalyVoxels
          : state.anomalyVoxels,
      returnedVoxels:
        trace.returnedVoxels !== undefined
          ? trace.returnedVoxels
          : state.returnedVoxels,
      blockModelMode:
        trace.blockModelMode !== undefined
          ? trace.blockModelMode
          : state.blockModelMode,
    })),

  // 3d. ENVOLVENTE VISUAL (Fase 7.3)
  showAnomalyEnvelope: true,
  setShowAnomalyEnvelope: (val) => set({ showAnomalyEnvelope: val }),
  anomalyEnvelopePercent: 0.15,
  setAnomalyEnvelopePercent: (val) => set({ anomalyEnvelopePercent: val }),

  // 3f. VOLUMEN CONCEPTUAL DEL SUBSUELO (C5.3)
  // Por defecto OFF: la caja gris del volumen host se leía como una "jaula"
  // artificial. Con visibilidad por contraste los cuerpos llenan el volumen de
  // forma orgánica; el usuario puede reactivarla como referencia espacial.
  showHostVolume: false,
  setShowHostVolume: (val) => set({ showHostVolume: val }),
  hostVolumeOpacity: 0.10,
  setHostVolumeOpacity: (val) => set({ hostVolumeOpacity: val }),

  // 3e. FILTRO DENSIDAD ABSOLUTA (Subfase 1B-4)
  minDensityRaw: null,
  setMinDensityRaw: (val) => set({ minDensityRaw: val }),
  maxDensityRaw: null,
  setMaxDensityRaw: (val) => set({ maxDensityRaw: val }),

  // 4. MAPEO IA (NLP Y TERRENO)
  geologistNote: "",
  setGeologistNote: (note) => set({ geologistNote: note }),
  extractedTags: [],
  setExtractedTags: (tags) => set({ extractedTags: tags }),
  geoRegionName: "",
  setGeoRegionName: (name) => set({ geoRegionName: name }),

  // 5. TELEMETRÍA Y GEOFÍSICA
  geoLat: "-22.28",
  setGeoLat: (lat) => set({ geoLat: lat }),
  geoLon: "-68.89",
  setGeoLon: (lon) => set({ geoLon: lon }),
  inputNIR: 30,
  setInputNIR: (val) => set({ inputNIR: val }),
  inputFe: 40,
  setInputFe: (val) => set({ inputFe: val }),
  inputDepth: 80,
  setInputDepth: (val) => set({ inputDepth: val }),
  inputGrav: 0.8,
  setInputGrav: (val) => set({ inputGrav: val }),
  region: "norte_chile",
  setRegion: (reg) => set({ region: reg }),
  heatmapData: [],
  setHeatmapData: (data) => set({ heatmapData: data }),
  bestTarget: null,
  setBestTarget: (target) => set({ bestTarget: target }),
  bestVoxel: null,
  setBestVoxel: (voxel) => set({ bestVoxel: voxel }),
  report: null,
  setReport: (rep) => set({ report: rep }),
  favorabilityResult: null,
  setFavorabilityResult: (result) => set({ favorabilityResult: result }),

  // 5.5 DATASET & INVERSIÓN (PERSISTENCIA CSV Y BBOX)
  fileGravimetry: null,
  setFileGravimetry: (file) => set({ fileGravimetry: file }),
  fileMagnetometry: null,
  setFileMagnetometry: (file) => set({ fileMagnetometry: file }),
  latNorth: "",
  setLatNorth: (val) => set({ latNorth: val }),
  latSouth: "",
  setLatSouth: (val) => set({ latSouth: val }),
  lonEast: "",
  setLonEast: (val) => set({ lonEast: val }),
  lonWest: "",
  setLonWest: (val) => set({ lonWest: val }),
  gravityPreviewResult: null,
  setGravityPreviewResult: (res) => set({ gravityPreviewResult: res }),
  gravityInvertResult: null,
  setGravityInvertResult: (res) => set({ gravityInvertResult: res }),

  // 9. GEOREF (R1-FE-2) + CRS (R2-FE)
  projectFootprint: null,
  georefConfidence: null,
  georefWarnings: [],
  crsInfo: null,
  setProjectFootprint: (footprint) => set({ projectFootprint: footprint }),
  setGeorefConfidence: (confidence) => set({ georefConfidence: confidence }),
  setGeorefWarnings: (warnings) => set({ georefWarnings: warnings }),
  setCrsInfo: (info) => set({ crsInfo: info }),
  setGeorefState: (payload) =>
    set((state) => ({
      projectFootprint:
        payload.footprint !== undefined ? payload.footprint : state.projectFootprint,
      georefConfidence:
        payload.confidence !== undefined ? payload.confidence : state.georefConfidence,
      georefWarnings:
        payload.warnings !== undefined ? payload.warnings : state.georefWarnings,
      crsInfo:
        payload.crsInfo !== undefined ? payload.crsInfo : state.crsInfo,
    })),

  // 10. R3 ELEVATION METADATA
  hasElevationData: false,
  blockModelDemSource: null,
  blockModelGeorefConfidence: null,
  blockModelElevationRange: null,
  setBlockModelElevationMeta: (meta) =>
    set((state) => ({
      hasElevationData:
        meta.hasElevationData !== undefined ? meta.hasElevationData : state.hasElevationData,
      blockModelDemSource:
        meta.demSource !== undefined ? meta.demSource : state.blockModelDemSource,
      blockModelGeorefConfidence:
        meta.georefConfidence !== undefined ? meta.georefConfidence : state.blockModelGeorefConfidence,
      blockModelElevationRange:
        meta.elevationRange !== undefined ? meta.elevationRange : state.blockModelElevationRange,
    })),

  // 11. PERCENTILE STATS
  percentileStats: null,
  setPercentileStats: (stats) => set({ percentileStats: stats }),

  // 12. RENDER SETTINGS — Fase 12 Multi-Física
  viewMode: 'density',
  setViewMode: (mode) => set({ viewMode: mode }),
  jointThreshold: 0.6,
  setJointThreshold: (val) => set({ jointThreshold: Math.max(0, Math.min(1, val)) }),

  // 13. CORTE CAJA (Sprint 4A)
  clipBoxEnabled: false,
  setClipBoxEnabled: (val) => set({ clipBoxEnabled: val }),
  clipBox: { xMin: 0, xMax: 0, yMin: 0, yMax: 0, zMin: 0, zMax: 0 },
  setClipBox: (patch) =>
    set((state) => ({ clipBox: { ...state.clipBox, ...patch } })),

  // 14. DOI THRESHOLD (Fase 7B-1)
  doiThreshold: 0.9,
  setDoiThreshold: (val) => set({ doiThreshold: Math.max(0, Math.min(1, val)) }),

  // 15. F5 — Puente de captura PNG
  capturePngSnapshot: null,
  setCapturePngSnapshot: (fn) => set({ capturePngSnapshot: fn }),
})));
