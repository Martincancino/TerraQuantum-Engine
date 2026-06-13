import * as THREE from "three";

// ── Singletons de módulo ─────────────────────────────────────────────────────
// Se reutilizan en cada llamada a updateInstancedBuffers para evitar
// que el GC acumule decenas de miles de Color/Object3D por actualización.
// NUNCA retener referencias externas a estos objetos entre llamadas.
const _dummy    = new THREE.Object3D();
const _tmpColor = new THREE.Color();
// ────────────────────────────────────────────────────────────────────────────

// Exported so engine-physics.ts (demo procedural model) can type its voxel array.
export interface VoxelData {
  x?: number;
  y?: number;
  z?: number;
  grade?: number;
  alteration?: number;
  [key: string]: number | undefined;
}

export interface VoxelMineralModel {
  domainL: number;
  domainH: number;
  domainW: number;
  cellSize: number;
  cells: VoxelData[];
  volumeM3: number;
  scoreStats?: Record<string, unknown>;
  visualScoreStats?: Record<string, unknown>;
  densityStats?: Record<string, unknown>;
  rhoStats?: Record<string, unknown>;
  probabilityStats?: Record<string, unknown>;
  returnedScoreStats?: Record<string, unknown>;
  diagnosticStats?: Record<string, unknown>;
  returnedDiagnosticStats?: Record<string, unknown>;
  warnings?: string[];
  isDegenerate?: boolean;
  is_degenerate?: boolean;
}

export interface TerrainResponse {
  dem_matrix: number[][];
  texture_url?: string;
  metadata: {
    dem_rows: number;
    dem_cols: number;
    extent_x_m: number;
    extent_z_m: number;
    [key: string]: unknown;
  };
}

// Internal cell shape — mirrors SceneCell in Scene3D to avoid circular imports.
interface SceneCell {
  x?: number; cx?: number;
  y?: number; cy?: number;
  z?: number; cz?: number;
  density?: number | null; rho?: number | null;
  probability?: number;
  visual_score?: number;
  relative_target_score?: number;
  grade?: number; real_grade?: number;
  voxel_elevation_masl?: number;
  anomaly_intensity?: number;
  modeled_density_index?: number;
  density_anomaly_score?: number;
  target_score?: number;
  is_active?: boolean | number | null;
  normalized_sensitivity?: number | null;
  sensitivity_proxy?: number | null;
  [key: string]: number | boolean | null | undefined;
}

export interface ExplorationDensityStats {
  densities: number[];
  supportScores: number[];
  visualValues: number[];
  visualMin: number;
  visualMax: number;
  densityMin: number;
  densityMax: number;
  visibleDensityFloor: number;
}

export interface ProfessionalScoreStats {
  p2: number; p5: number; p50: number;
  p85: number; p90: number; p95: number; p98: number;
  threshold: number;
  highThreshold: number;
  extremeThreshold: number;
  isDegenerate: boolean;
  highlightedCount: number;
  highlightedRatio: number;
}

export type SliceAxis = "none" | "x" | "y" | "z";

export interface UpdateInstancedBuffersParams {
  mesh: THREE.InstancedMesh;
  cells: unknown[];
  cellSize: number;
  isExplorationMode: boolean;
  isFullDataMode: boolean;
  isAnomalyDataMode: boolean;
  effectiveProfessionalMode: boolean;
  minTargetScore: number;
  minAnomalyIntensity: number;
  minDensityAnomalyScore: number;
  minDensityRaw: number | null;
  maxDensityRaw: number | null;
  voxelScale: number;
  /** Tamaño real de la celda en cada eje (derivado del espaciado de la grilla).
   *  Si se omite, se usa `cellSize` para los tres ejes como fallback. */
  cellSizeX?: number;
  cellSizeY?: number;
  cellSizeZ?: number;
  sliceAxis: SliceAxis;
  slicePosition: number;
  sliceThickness: number;
  showOnlySlice: boolean;
  elevationEnabled: boolean;
  refElev: number;
  densityStats: ExplorationDensityStats;
  professionalScoreStats: ProfessionalScoreStats;
  /** Percentil 95 del σ posterior (t/m³) para normalizar la capa de incertidumbre.
   *  Proviene de uncertaintyPosterior.p95 en el reporte del backend. */
  sigma95?: number;
  /** Capa visual activa. "uncertainty" activa el colormap Inferno sobre σ. */
  visualLayer?: string;
  // ── Fase 12: Multi-Física ─────────────────────────────────────────
  /** Modo de render multi-física. Default: 'density'. */
  viewMode?: 'density' | 'susceptibility' | 'joint';
  /** Umbral conjunto (0–1): voxels con joint_structural_score < umbral se ocultan. */
  jointThreshold?: number;
}

// Densidad de roca país fallback. El backend provee el valor específico del sitio.
const DENSITY_COUNTRY_ROCK_FALLBACK_T_M3 = 2.75;

// Umbral de contraste (|ρ − fondo| / escala robusta) por encima del cual una celda
// se considera cuerpo anómalo y se muestra. ~0.18 deja emerger déficit y exceso de
// masa y oculta el fondo neutro, revelando forma orgánica en vez de una caja llena.
const ANOMALY_CONTRAST_VISIBLE = 0.18;

// Color neutro gris para vóxeles sin datos (e.g. susceptibilidad ausente en corrida gravity-only)
const NEUTRAL_GRAY: [number, number, number] = [0.5, 0.5, 0.5];

// ── Colormaps científicos (sin d3) ────────────────────────────────────────────
// Implementación directa de Viridis e Inferno (matplotlib/colorcet).
// Cada stop es [t, [r, g, b]] con valores normalizados [0,1].

type ColorStop = [number, [number, number, number]];

const INFERNO_STOPS: ColorStop[] = [
  [0.000, [0.000, 0.000, 0.016]],
  [0.143, [0.122, 0.047, 0.165]],
  [0.286, [0.369, 0.082, 0.325]],
  [0.429, [0.580, 0.071, 0.298]],
  [0.571, [0.780, 0.239, 0.224]],
  [0.714, [0.937, 0.494, 0.122]],
  [0.857, [0.988, 0.749, 0.353]],
  [1.000, [0.988, 1.000, 0.643]],
];

// Turbo (Google) — para susceptibilidad magnética
const TURBO_STOPS: ColorStop[] = [
  [0.000, [0.188, 0.071, 0.231]],
  [0.143, [0.153, 0.392, 0.945]],
  [0.286, [0.090, 0.745, 0.812]],
  [0.429, [0.188, 0.933, 0.353]],
  [0.571, [0.686, 0.980, 0.082]],
  [0.714, [0.996, 0.776, 0.082]],
  [0.857, [0.957, 0.365, 0.004]],
  [1.000, [0.478, 0.027, 0.000]],
];

// RdBu divergente (ColorBrewer, invertido azul→blanco→rojo) — densidad por
// CONTRASTE respecto al fondo. Gravimetría NUNCA se muestra en densidad absoluta:
// el fondo (~2.6 t/m³) vive en el centro y aplasta toda la geología en una banda
// estrecha del colormap secuencial. Centrado en 0 = fondo neutro (blanco), déficit
// de masa = azul, exceso de masa = rojo. Así los cuerpos resaltan (estándar
// SimPEG/Leapfrog/Oasis montaj).
const DENSITY_DIVERGING_STOPS: ColorStop[] = [
  [0.0, [0.020, 0.188, 0.380]],
  [0.1, [0.129, 0.400, 0.675]],
  [0.2, [0.263, 0.576, 0.765]],
  [0.3, [0.573, 0.773, 0.871]],
  [0.4, [0.820, 0.898, 0.941]],
  [0.5, [0.969, 0.969, 0.969]],
  [0.6, [0.992, 0.859, 0.780]],
  [0.7, [0.957, 0.647, 0.510]],
  [0.8, [0.839, 0.376, 0.302]],
  [0.9, [0.698, 0.094, 0.169]],
  [1.0, [0.404, 0.000, 0.121]],
];

function sampleColormap(stops: ColorStop[], t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const t0 = stops[i - 1][0], t1 = stops[i][0];
      const local = (t - t0) / Math.max(t1 - t0, 1e-9);
      const a = stops[i - 1][1], b = stops[i][1];
      return [a[0] + (b[0] - a[0]) * local,
              a[1] + (b[1] - a[1]) * local,
              a[2] + (b[2] - a[2]) * local];
    }
  }
  return stops[stops.length - 1][1];
}
// ─────────────────────────────────────────────────────────────────────────────

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function getCellNumber(cell: SceneCell, keys: string[], fallback = 0): number {
  for (const key of keys) {
    const raw = cell?.[key];
    // CRÍTICO: Number(null) === 0 (no NaN). Si la 1ª clave llega como null
    // (el response_model estricto emite campos opcionales como null), la versión
    // antigua devolvía 0 y NUNCA caía a la clave de respaldo -> target_score=null
    // se leía como 0 (ocultando todo) y modeled_density_index=null hacía
    // densidad=0 en TODA la malla. Solo aceptamos números finitos reales; null /
    // undefined / no-número se saltan para usar la siguiente clave.
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  }
  return fallback;
}

function getVoxelTargetScore(cell: SceneCell): number {
  return getCellNumber(cell, ["target_score", "probability"], 0);
}

function getVoxelAnomalyIntensity(cell: SceneCell): number {
  return getCellNumber(cell, ["anomaly_intensity", "grade", "real_grade", "rho"], 0);
}

function getVoxelModeledDensity(cell: SceneCell): number {
  return getCellNumber(cell, ["modeled_density_index", "density", "rho"], 2.6);
}

function getVoxelDensityAnomalyScore(cell: SceneCell): number {
  const score = getCellNumber(cell, ["density_anomaly_score"], -999);
  if (score !== -999) return score;
  const dens = getVoxelModeledDensity(cell);
  return Math.max(0, dens - DENSITY_COUNTRY_ROCK_FALLBACK_T_M3) / DENSITY_COUNTRY_ROCK_FALLBACK_T_M3;
}

function getCellVisualScore(cell: SceneCell): number {
  if (cell.visual_score !== undefined && Number.isFinite(cell.visual_score))
    return clamp01(cell.visual_score);
  if (cell.relative_target_score !== undefined && Number.isFinite(cell.relative_target_score))
    return clamp01(cell.relative_target_score);
  const das = getCellNumber(cell, ["density_anomaly_score"], -999);
  if (das !== -999) return clamp01(das);
  if (cell.probability !== undefined && Number.isFinite(cell.probability))
    return clamp01(cell.probability);
  const density = getVoxelModeledDensity(cell);
  return clamp01(Math.max(0, density - DENSITY_COUNTRY_ROCK_FALLBACK_T_M3) / DENSITY_COUNTRY_ROCK_FALLBACK_T_M3);
}

function normalizeDensity(density: number, stats: ExplorationDensityStats): number {
  const range = stats.densityMax - stats.densityMin;
  if (range <= 0.000001) return 0.5;
  return clamp01((density - stats.densityMin) / range);
}

function getExplorationSupportScore(cell: SceneCell, densityRatio: number): number {
  const probability = clamp01(getVoxelTargetScore(cell));
  const visualScore = clamp01(getCellNumber(cell, ["visual_score"], densityRatio));
  const densityAnomalyScore = clamp01(getVoxelDensityAnomalyScore(cell));
  return Math.max(probability * 0.45, visualScore * 0.45, densityAnomalyScore * 0.10);
}

function isExplorationCellVisible(
  density: number,
  supportScore: number,
  stats: ExplorationDensityStats,
  isDegenerate = false,
): boolean {
  const densityRange = stats.densityMax - stats.densityMin;
  if (densityRange <= 0.000001) return Number.isFinite(density);
  // When all scores are zero (degenerate model), fall back to density-only visibility
  // so the physical block model is still visible even without anomaly scores.
  if (isDegenerate) return density >= stats.visibleDensityFloor;
  return density >= stats.visibleDensityFloor && supportScore >= 0.25;
}

function passesDensityFilter(
  density: number,
  minRaw: number | null,
  maxRaw: number | null,
): boolean {
  if (minRaw !== null && density < minRaw) return false;
  if (maxRaw !== null && density > maxRaw) return false;
  return true;
}

// Retorna solo la visibilidad (scale=0 → oculto, scale=1 → visible).
// El color se determina exclusivamente por el colormap físico Viridis/Inferno.
interface VoxelVisualConfig { scale: number; }

function getGeologicalVoxelConfig(
  score: number,
  stats: ProfessionalScoreStats,
): VoxelVisualConfig {
  if (score < stats.threshold) return { scale: 0 };
  return { scale: 1.0 };
}

function getCellAxisPosition(cell: SceneCell, axis: SliceAxis): number {
  if (axis === "none") return 0;
  if (axis === "y")    return getCellNumber(cell, ["y", "cy"], 0);
  if (axis === "z")    return getCellNumber(cell, ["z", "cz"], 0);
  return                      getCellNumber(cell, ["x", "cx"], 0);
}

/**
 * Fills the InstancedMesh matrices and colors for every voxel cell.
 *
 * Coordinate convention (Dato → WebGL):
 *   x_visual = voxel.x   (raw Easting)
 *   y_visual = voxel.y   (raw Y — same space as modelCenter in Scene3D so the
 *                          group offset [-mc[0], -mc[1], -mc[2]] centers correctly)
 *   z_visual = voxel.z   (raw Northing)
 *
 * Exception: when elevationEnabled, voxel_elevation_masl − refElev is used for Y.
 */
export function updateInstancedBuffers({
  mesh,
  cells,
  cellSize,
  isExplorationMode,
  isFullDataMode,
  isAnomalyDataMode,
  effectiveProfessionalMode,
  minTargetScore,
  minAnomalyIntensity,
  minDensityAnomalyScore,
  minDensityRaw,
  maxDensityRaw,
  voxelScale,
  cellSizeX,
  cellSizeY,
  cellSizeZ,
  sliceAxis,
  slicePosition,
  showOnlySlice,
  elevationEnabled,
  refElev,
  densityStats,
  professionalScoreStats,
  sigma95,
  visualLayer,
  viewMode = 'density',
  jointThreshold = 0.6,
}: UpdateInstancedBuffersParams): { visibleCount: number; highlightedCount: number; susceptibilityAvailable: boolean } {
  const _r08_t0 = performance.now();
  const dummy = _dummy;
  let visibleCount = 0;
  let highlightedCount = 0;
  let susceptibilityFoundCount = 0;
  const rdx = (cellSizeX !== undefined ? cellSizeX : cellSize) * voxelScale;
  const rdy = (cellSizeY !== undefined ? cellSizeY : cellSize) * voxelScale;
  const rdz = (cellSizeZ !== undefined ? cellSizeZ : cellSize) * voxelScale;

  // σ_95 para normalizar incertidumbre (proviene del reporte o fallback=1).
  const effectiveSigma95: number = (sigma95 !== undefined && sigma95 > 0) ? sigma95 : 1;

  // ── Fase 12: Dynamic min/max para normalización real ──────────────────────
  let dynChiMin = Infinity;
  let dynChiMax = -Infinity;
  let dynDensMin = Infinity;
  let dynDensMax = -Infinity;
  // Muestras de densidad para normalización robusta por percentiles (P2–P98):
  // evita que un único vóxel atípico estire el rango y aplaste todo el gradiente
  // contra el extremo bajo del colormap (causa raíz del "todo morado/plano").
  const densitySamples: number[] = [];

  if (viewMode === 'susceptibility' || viewMode === 'density') {
    for (let i = 0; i < cells.length; i++) {
      const rawCell = cells[i] as Record<string, unknown>;
      if (rawCell.is_active === false || rawCell.is_active === 0 || rawCell.density === null || rawCell.rho === null) continue;

      if (viewMode === 'susceptibility') {
        const chiRaw = Number(rawCell.susceptibility_si);
        if (Number.isFinite(chiRaw)) {
          const chiLog = Math.log10(Math.max(chiRaw, 0) + 1e-9);
          if (chiLog < dynChiMin) dynChiMin = chiLog;
          if (chiLog > dynChiMax) dynChiMax = chiLog;
        }
      } else if (viewMode === 'density') {
        const density = getVoxelModeledDensity(cells[i] as SceneCell);
        if (density < dynDensMin) dynDensMin = density;
        if (density > dynDensMax) dynDensMax = density;
        densitySamples.push(density);
      }
    }
  }

  // Prevenir rangos degenerados
  if (dynChiMax <= dynChiMin) { dynChiMin = -9; dynChiMax = 0; }
  if (dynDensMax <= dynDensMin) { dynDensMin = densityStats.densityMin; dynDensMax = densityStats.densityMax; }
  const _dynChiRange = dynChiMax - dynChiMin;

  // Cotas para el colormap de densidad: piso robusto P2 (recorta un outlier bajo),
  // techo = máximo real. En un campo dominado por roca de fondo, el cuerpo
  // mineralizado es <2% del volumen y vive ENTERO por encima de P98; recortar a
  // P98 satura toda la anomalía a un rojo plano. Con el máximo, el cuerpo muestra
  // su gradiente interno y se distingue del fondo.
  // ── Densidad por contraste: fondo = mediana, escala simétrica robusta ────────
  // El fondo (mediana) ancla el blanco del colormap divergente; la escala es la
  // mayor desviación robusta (P5/P95 respecto a la mediana, ignorando los pocos
  // vóxeles de borde saturados a 0). El contraste se mapea a [-1,+1] -> [azul,rojo].
  let densBackground = 2.6;
  let densScale = 1.0;
  if (densitySamples.length > 1) {
    densitySamples.sort((a, b) => a - b);
    const pick = (q: number) =>
      densitySamples[Math.min(densitySamples.length - 1, Math.max(0, Math.round(q * (densitySamples.length - 1))))];
    densBackground = pick(0.5);
    const spreadHi = pick(0.95) - densBackground;
    const spreadLo = densBackground - pick(0.05);
    densScale = Math.max(spreadHi, spreadLo, 0.05);
  } else if (Number.isFinite(dynDensMin) && Number.isFinite(dynDensMax) && dynDensMax > dynDensMin) {
    densBackground = (dynDensMin + dynDensMax) / 2;
    densScale = Math.max((dynDensMax - dynDensMin) / 2, 0.05);
  }

  for (let i = 0; i < cells.length; i++) {
    const cell = cells[i] as SceneCell;
    const rawY = getCellNumber(cell, ["y", "cy"], 0);
    let ry_visual: number;
    if (elevationEnabled) {
      const elev = Number(cell.voxel_elevation_masl);
      ry_visual = Number.isFinite(elev) ? elev - refElev : rawY;
    } else {
      ry_visual = rawY;
    }
    const rx_visual = getCellNumber(cell, ["x", "cx"], 0);
    const rz_visual = getCellNumber(cell, ["z", "cz"], 0);

    const rawCell = cells[i] as Record<string, unknown>;
    if (rawCell.is_active === false || rawCell.is_active === 0 || rawCell.density === null || rawCell.rho === null) {
      dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue;
    }
    const _rawSens = rawCell.sensitivity_proxy !== undefined ? rawCell.sensitivity_proxy : rawCell.normalized_sensitivity;
    // null/undefined = el backend no proveyó sensibilidad para esta celda ->
    // "sin dato de DOI", NO "sensibilidad cero". Tratarlo como 0.0 ocultaba el
    // modelo entero cuando el campo llegaba null. Sin dato -> visible (1.0); el
    // gate DOI solo debe ocultar celdas con sensibilidad REAL baja (<0.05).
    const sensitivityProxy = (() => { if (_rawSens === undefined || _rawSens === null) return 1.0; const n = Number(_rawSens); return Number.isFinite(n) ? n : 1.0; })();
    const DOI_THRESHOLD = 0.05;
    // El gate DOI NO oculta el vóxel: el modelo de densidad se calcula
    // (regularizado) en TODA la malla; baja sensibilidad = menor confianza, y eso
    // se comunica atenuando el brillo (ver `brightness` más abajo), no borrando.
    // Ocultar aquí eliminaba ~2/3 de un modelo regional válido (causa de "no se
    // ve nada" en surveys dispersos como Laguna del Maule).
    if (showOnlySlice && sliceAxis !== "none") { const axisPos = getCellAxisPosition(cell, sliceAxis); if (axisPos > slicePosition) { dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue; } }
    const density = getVoxelModeledDensity(cell);
    const densityRatio = normalizeDensity(density, densityStats);
    const targetScore = getVoxelTargetScore(cell);
    const anomalyIntensity = getVoxelAnomalyIntensity(cell);
    const densityAnomalyScore = getVoxelDensityAnomalyScore(cell);
    const visualScore = getCellVisualScore(cell);
    // Magnitud de contraste SIMÉTRICA respecto al fondo: |ρ − fondo| / escala.
    // Un déficit de masa (anomalía gravimétrica negativa) es un objetivo tan real
    // como un exceso; los scores positivos (max(0, ρ−fondo)) lo ocultaban -> "no
    // hay azul". Esto hace que los cuerpos anómalos en CUALQUIER signo emerjan y el
    // fondo neutro se oculte (sin "caja blanca", forma orgánica).
    const _contrastMag = densScale > 1e-9 ? Math.abs(density - densBackground) / densScale : 0;
    // El pre-filtro sesgado a positivos NO debe ocultar cuerpos de fuerte contraste
    // (de cualquier signo): solo se aplica a celdas de bajo contraste.
    if (!isFullDataMode && !professionalScoreStats.isDegenerate && _contrastMag < ANOMALY_CONTRAST_VISIBLE) { if (targetScore < minTargetScore || anomalyIntensity < minAnomalyIntensity || densityAnomalyScore < minDensityAnomalyScore) { dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue; } }
    if (!passesDensityFilter(density, minDensityRaw, maxDensityRaw)) { dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue; }
    // ── Visibilidad: lógica de filtrado (sin asignar color) ──────────────────
    let visible = false;
    if (effectiveProfessionalMode) {
      const config = getGeologicalVoxelConfig(visualScore, professionalScoreStats);
      // visualScore es PROSPECTIVIDAD (sesgada a denso = objetivo de mena). Un
      // déficit de masa de fuerte contraste es estructura geológica REAL y debe
      // verse: sin esto, el modo profesional nunca muestra azul (era la causa de
      // "no hay vóxeles azules" — el modo por defecto es profesional).
      const passesContrast = _contrastMag >= ANOMALY_CONTRAST_VISIBLE;
      if (config.scale === 0 && !passesContrast) { dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue; }
      visible = true;
      if (visualScore >= professionalScoreStats.threshold) highlightedCount++;
    } else if (isExplorationMode) {
      if (professionalScoreStats.isDegenerate) {
        // Modelo sin contraste estadístico: visibilidad por piso de densidad.
        const supportScore = densityStats.supportScores[i] ?? getExplorationSupportScore(cell, densityRatio);
        visible = isExplorationCellVisible(density, supportScore, densityStats, true);
      } else {
        // Visibilidad por contraste simétrico: emergen los cuerpos anómalos
        // (déficit O exceso); el fondo neutro se oculta. Resuelve "no hay azul",
        // "todo blanco" y "caja con pocos vóxeles" de una vez.
        visible = _contrastMag >= ANOMALY_CONTRAST_VISIBLE;
      }
    } else if (isAnomalyDataMode) {
      visible = anomalyIntensity > 0;
    } else if (isFullDataMode) {
      visible = true;
    } else {
      visible = visualScore > 0.01;
    }
    if (!visible) { dummy.scale.set(0, 0, 0); dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); continue; }
    visibleCount++;

    // ── Color físico: modo multi-física (Fase 12) ─────────────────────────
    let _r: number, _g: number, _b: number;

    if (viewMode === 'susceptibility') {
      // Campo: susceptibility_si (campo del backend tras Fase 12)
      const chiRaw = Number((rawCell as Record<string, unknown>).susceptibility_si);
      if (!Number.isFinite(chiRaw)) {
        // Corrida gravity-only: susceptibilidad ausente — gris neutro en vez de NaN→garbage color
        [_r, _g, _b] = NEUTRAL_GRAY;
      } else {
        susceptibilityFoundCount++;
        const epsilon = 1e-9;
        const chiLog = Math.log10(Math.max(chiRaw, 0) + epsilon);
        const chiNorm = clamp01((chiLog - dynChiMin) / _dynChiRange);
        [_r, _g, _b] = sampleColormap(TURBO_STOPS, chiNorm);
      }

    } else if (viewMode === 'joint') {
      // Modo conjunto: color corporativo cian TerraQuantum + filtro por umbral.
      // IMPORTANT: if joint_structural_score is absent (gravity-only run), hide the
      // voxel. The previous default of 1.0 caused all voxels to appear with cyan
      // color even when no joint data exists, making a gravity-only inversion look
      // like a joint result. Absence of the field = no joint data = hide.
      const jointRaw = (rawCell as Record<string, unknown>).joint_structural_score;
      if (jointRaw === undefined || jointRaw === null) {
        dummy.scale.set(0, 0, 0);
        dummy.position.set(rx_visual, ry_visual, rz_visual);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        continue;
      }
      const jointScore = Number(jointRaw);
      if (!Number.isFinite(jointScore) || jointScore < jointThreshold) {
        // Ocultar: escalar a cero en lugar de mover (evita artefactos de frustum)
        dummy.scale.set(0, 0, 0);
        dummy.position.set(rx_visual, ry_visual, rz_visual);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        continue;
      }
      // Cian corporativo TerraQuantum
      _r = 0.047; _g = 0.827; _b = 0.933; // #0BD3EE

    } else {
      // viewMode === 'density' (default) — comportamiento original
      const _sigmaRaw = Number(rawCell.posterior_std);
      const _sigmaRatio = (Number.isFinite(_sigmaRaw) && effectiveSigma95 > 0)
        ? Math.min(_sigmaRaw / effectiveSigma95, 1) : 0;

      if (visualLayer === "uncertainty") {
        [_r, _g, _b] = sampleColormap(INFERNO_STOPS, _sigmaRatio);
      } else {
        // Densidad por CONTRASTE respecto al fondo (mediana). t=0.5 = fondo
        // (blanco), t<0.5 = déficit de masa (azul), t>0.5 = exceso (rojo).
        // Escala simétrica robusta -> los cuerpos anómalos resaltan en vez de
        // aplastarse en una banda media casi uniforme (causa del "todo blanco").
        const _contrast = density - densBackground;
        const _u = clamp01(0.5 + 0.5 * (_contrast / densScale));
        [_r, _g, _b] = sampleColormap(DENSITY_DIVERGING_STOPS, _u);
        const _alpha = 1 - 0.7 * _sigmaRatio;
        _r *= _alpha; _g *= _alpha; _b *= _alpha;
      }
    }

    // Brillo DOI (proxy de sensibilidad — invariante de la capa activa)
    const brightness = 0.55 + Math.min(1.0, (sensitivityProxy - DOI_THRESHOLD) / (0.3 - DOI_THRESHOLD)) * 0.45;
    _tmpColor.setRGB(_r * brightness, _g * brightness, _b * brightness);

    dummy.position.set(rx_visual, ry_visual, rz_visual); dummy.scale.set(rdx, rdy, rdz); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); mesh.setColorAt(i, _tmpColor);
  }
  const _r08_loop_end = performance.now();
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  const _r08_gpu_end = performance.now();
  console.log(
    `[R08] updateInstancedBuffers | n=${cells.length} | visible=${visibleCount}` +
    ` | loop=${(_r08_loop_end - _r08_t0).toFixed(1)}ms` +
    ` | gpu_upload=${(_r08_gpu_end - _r08_loop_end).toFixed(1)}ms` +
    ` | total=${(_r08_gpu_end - _r08_t0).toFixed(1)}ms`
  );
  console.log("Vóxeles visibles tras filtro:", visibleCount);
  return { visibleCount, highlightedCount, susceptibilityAvailable: susceptibilityFoundCount > 0 };
}
