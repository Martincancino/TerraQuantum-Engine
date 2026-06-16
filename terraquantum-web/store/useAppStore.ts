import { create } from 'zustand';
import type { TerrainResponse, VoxelMineralModel } from '../lib/terraQuantumGeology';
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
  // Postprocessing cinemático (Fase C): N8AO + Bloom + SMAA + Vignette.
  // Toggle para poder volver al render directo (rendimiento / debug).
  postprocessingEnabled: boolean;
  setPostprocessingEnabled: (val: boolean) => void;
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
  susceptibilityDataAvailable: boolean;
  setSusceptibilityDataAvailable: (val: boolean) => void;
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
}

export const useAppStore = create<AppState>((set) => ({
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
    set((state) => ({
      activeRun: {
        ...state.activeRun,
        ...patch,
      },
    })),
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
  setModel: (m) => {
    set({
      model: m,
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
            hasElevationData: false,
            blockModelDemSource: null,
            blockModelGeorefConfidence: null,
            blockModelElevationRange: null,
            percentileStats: null,
          }
        : {}),
    });
  },

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
  postprocessingEnabled: true,
  setPostprocessingEnabled: (val) => set({ postprocessingEnabled: val }),
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
  susceptibilityDataAvailable: true,
  setSusceptibilityDataAvailable: (val) => set({ susceptibilityDataAvailable: val }),
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
}));
