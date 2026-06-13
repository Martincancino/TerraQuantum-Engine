/// <reference lib="webworker" />
// HITO 6 — WebWorker: construcción off-thread de buffers InstancedMesh.
// Sin imports de Three.js: pura aritmética. Recibe params serializables,
// devuelve Float32Array transferibles (sin copia) para instanceMatrix e instanceColor.

// ── Tipos mínimos (espejo de terraQuantumGeology.ts) ─────────────────────────
type ColorStop = [number, [number, number, number]];
type SliceAxis = "none" | "x" | "y" | "z";

interface ExplorationDensityStats {
  densities: number[];
  supportScores: number[];
  visualValues: number[];
  visualMin: number;
  visualMax: number;
  densityMin: number;
  densityMax: number;
  visibleDensityFloor: number;
}

interface ProfessionalScoreStats {
  p2: number; p5: number; p50: number;
  p85: number; p90: number; p95: number; p98: number;
  threshold: number;
  highThreshold: number;
  extremeThreshold: number;
  isDegenerate: boolean;
  highlightedCount: number;
  highlightedRatio: number;
}

interface WorkerInput {
  reqId: number;
  cells: Record<string, unknown>[];
  cellSize: number;
  cellSizeX?: number;
  cellSizeY?: number;
  cellSizeZ?: number;
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
  sliceAxis: SliceAxis;
  slicePosition: number;
  sliceThickness: number;
  showOnlySlice: boolean;
  elevationEnabled: boolean;
  refElev: number;
  densityStats: ExplorationDensityStats;
  professionalScoreStats: ProfessionalScoreStats;
  sigma95?: number;
  visualLayer?: string;
  viewMode?: 'density' | 'susceptibility' | 'joint';
  jointThreshold?: number;
}

interface WorkerOutput {
  reqId: number;
  matricesF32: Float32Array;
  colorsF32: Float32Array;
  visibleCount: number;
  highlightedCount: number;
  susceptibilityAvailable: boolean;
}

// ── Colormaps (copiados de terraQuantumGeology.ts — sin dependencias) ─────────
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

// RdBu divergente (azul→blanco→rojo) — densidad por CONTRASTE respecto al fondo.
// Centrado en 0 = fondo neutro (blanco); déficit = azul, exceso = rojo. Evita que
// la geología se aplaste en una banda media del colormap secuencial (causa del
// "todo blanco/uniforme"). Estándar SimPEG/Leapfrog. Debe coincidir con
// terraQuantumGeology.ts::DENSITY_DIVERGING_STOPS.
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
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const t0 = stops[i - 1][0], t1 = stops[i][0];
      const local = (t - t0) / (t1 - t0 > 1e-9 ? t1 - t0 : 1e-9);
      const a = stops[i - 1][1], b = stops[i][1];
      return [a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local, a[2] + (b[2] - a[2]) * local];
    }
  }
  return stops[stops.length - 1][1];
}

function clamp01(v: number): number { return v < 0 ? 0 : v > 1 ? 1 : v; }

// ── Helpers de celda (espejo exacto de terraQuantumGeology.ts) ────────────────
const DENSITY_FALLBACK = 2.75;
const NEUTRAL_GRAY: [number, number, number] = [0.5, 0.5, 0.5];

function getCellNum(cell: Record<string, unknown>, keys: string[], fb = 0): number {
  for (const k of keys) {
    const v = Number(cell[k]);
    if (Number.isFinite(v)) return v;
  }
  return fb;
}

function getTargetScore(cell: Record<string, unknown>): number {
  return getCellNum(cell, ["target_score", "probability"], 0);
}

function getAnomalyIntensity(cell: Record<string, unknown>): number {
  return getCellNum(cell, ["anomaly_intensity", "grade", "real_grade", "rho"], 0);
}

function getModeledDensity(cell: Record<string, unknown>): number {
  return getCellNum(cell, ["modeled_density_index", "density", "rho"], 2.6);
}

function getDensityAnomalyScore(cell: Record<string, unknown>): number {
  const score = getCellNum(cell, ["density_anomaly_score"], -999);
  if (score !== -999) return score;
  const dens = getModeledDensity(cell);
  return Math.max(0, dens - DENSITY_FALLBACK) / DENSITY_FALLBACK;
}

function getCellVisualScore(cell: Record<string, unknown>): number {
  const vs = Number(cell.visual_score);
  if (Number.isFinite(vs)) return clamp01(vs);
  const rt = Number(cell.relative_target_score);
  if (Number.isFinite(rt)) return clamp01(rt);
  const das = getCellNum(cell, ["density_anomaly_score"], -999);
  if (das !== -999) return clamp01(das);
  const prob = Number(cell.probability);
  if (Number.isFinite(prob)) return clamp01(prob);
  return clamp01(Math.max(0, getModeledDensity(cell) - DENSITY_FALLBACK) / DENSITY_FALLBACK);
}

function getCellAxisPos(cell: Record<string, unknown>, axis: SliceAxis): number {
  if (axis === "none") return 0;
  if (axis === "y") return getCellNum(cell, ["y", "cy"], 0);
  if (axis === "z") return getCellNum(cell, ["z", "cz"], 0);
  return getCellNum(cell, ["x", "cx"], 0);
}

// ── Escritura de matriz TRS (posición + escala, sin rotación) ─────────────────
// Three.js Matrix4 columna-mayor: [sx,0,0,0, 0,sy,0,0, 0,0,sz,0, px,py,pz,1]
// Índices:                         [0 1 2 3  4  5 6 7  8  9 10 11 12 13 14 15]
function writeMatrix(arr: Float32Array, base: number,
  sx: number, sy: number, sz: number,
  px: number, py: number, pz: number): void {
  arr[base + 0]  = sx;  arr[base + 1]  = 0;  arr[base + 2]  = 0;  arr[base + 3]  = 0;
  arr[base + 4]  = 0;   arr[base + 5]  = sy; arr[base + 6]  = 0;  arr[base + 7]  = 0;
  arr[base + 8]  = 0;   arr[base + 9]  = 0;  arr[base + 10] = sz; arr[base + 11] = 0;
  arr[base + 12] = px;  arr[base + 13] = py; arr[base + 14] = pz; arr[base + 15] = 1;
}

// ── Builder principal ─────────────────────────────────────────────────────────
function buildBuffers(p: WorkerInput): WorkerOutput {
  const n = p.cells.length;
  const matricesF32 = new Float32Array(n * 16);
  const colorsF32   = new Float32Array(n * 3);

  const rdx = (p.cellSizeX ?? p.cellSize) * p.voxelScale;
  const rdy = (p.cellSizeY ?? p.cellSize) * p.voxelScale;
  const rdz = (p.cellSizeZ ?? p.cellSize) * p.voxelScale;

  const effectiveSigma95 = (p.sigma95 !== undefined && p.sigma95 > 0) ? p.sigma95 : 1;
  const viewMode = p.viewMode ?? 'density';
  const jointThreshold = p.jointThreshold ?? 0.6;

  // ── Rango dinámico para normalización (susceptibility / density) ─────────
  let dynChiMin = Infinity, dynChiMax = -Infinity;
  let dynDensMin = Infinity, dynDensMax = -Infinity;
  // Muestras de densidad para normalización robusta por percentiles (P2–P98).
  const densitySamples: number[] = [];

  if (viewMode === 'susceptibility' || viewMode === 'density') {
    for (let i = 0; i < n; i++) {
      const cell = p.cells[i];
      if (cell.is_active === false || cell.is_active === 0 || cell.density === null || cell.rho === null) continue;
      if (viewMode === 'susceptibility') {
        const chiRaw = Number(cell.susceptibility_si);
        if (Number.isFinite(chiRaw)) {
          const chiLog = Math.log10(Math.max(chiRaw, 0) + 1e-9);
          if (chiLog < dynChiMin) dynChiMin = chiLog;
          if (chiLog > dynChiMax) dynChiMax = chiLog;
        }
      } else {
        const dens = getModeledDensity(cell);
        if (dens < dynDensMin) dynDensMin = dens;
        if (dens > dynDensMax) dynDensMax = dens;
        densitySamples.push(dens);
      }
    }
  }
  if (dynChiMax <= dynChiMin) { dynChiMin = -9; dynChiMax = 0; }
  if (dynDensMax <= dynDensMin) { dynDensMin = p.densityStats.densityMin; dynDensMax = p.densityStats.densityMax; }
  const _dynChiRange = dynChiMax - dynChiMin;

  // Piso robusto P2 (recorta un outlier bajo); techo = máximo real. El cuerpo
  // mineralizado es <2% del volumen y vive entero por encima de P98: recortar a
  // P98 satura toda la anomalía a un rojo plano. Con el máximo se ve su gradiente.
  // Densidad por contraste: fondo = mediana (ancla el blanco), escala simétrica
  // robusta (mayor desviación P5/P95). Debe coincidir con terraQuantumGeology.ts.
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

  let visibleCount = 0, highlightedCount = 0, susceptibilityFoundCount = 0;
  const DOI_THRESHOLD = 0.05;

  for (let i = 0; i < n; i++) {
    const cell = p.cells[i];
    const mb = i * 16;
    const cb = i * 3;

    // ── Posición visual ──────────────────────────────────────────────────────
    const rawY = getCellNum(cell, ["y", "cy"], 0);
    let ry_visual: number;
    if (p.elevationEnabled) {
      const elev = Number(cell.voxel_elevation_masl);
      ry_visual = Number.isFinite(elev) ? elev - p.refElev : rawY;
    } else {
      ry_visual = rawY;
    }
    const rx_visual = getCellNum(cell, ["x", "cx"], 0);
    const rz_visual = getCellNum(cell, ["z", "cz"], 0);

    // ── Filtro is_active / null ───────────────────────────────────────────────
    if (cell.is_active === false || cell.is_active === 0 || cell.density === null || cell.rho === null) {
      writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
      colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
      continue;
    }

    // ── DOI / sensitivity proxy ───────────────────────────────────────────────
    const _rawSens = cell.sensitivity_proxy !== undefined ? cell.sensitivity_proxy : cell.normalized_sensitivity;
    const sensitivityProxy = (() => {
      // null/undefined = sin dato de DOI -> visible (1.0), no "sensibilidad 0".
      // Tratar null como 0.0 ocultaba el modelo entero (ver terraQuantumGeology).
      if (_rawSens === undefined || _rawSens === null) return 1.0;
      const n2 = Number(_rawSens);
      return Number.isFinite(n2) ? n2 : 1.0;
    })();
    if (sensitivityProxy < DOI_THRESHOLD) {
      writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
      colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
      continue;
    }

    // ── Slice filter ─────────────────────────────────────────────────────────
    if (p.showOnlySlice && p.sliceAxis !== "none") {
      const axisPos = getCellAxisPos(cell, p.sliceAxis);
      if (axisPos > p.slicePosition) {
        writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
        colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
        continue;
      }
    }

    const density = getModeledDensity(cell);
    const targetScore = getTargetScore(cell);
    const anomalyIntensity = getAnomalyIntensity(cell);
    const densityAnomalyScore = getDensityAnomalyScore(cell);
    const visualScore = getCellVisualScore(cell);

    // Contraste simétrico vs. fondo: déficit y exceso de masa son ambos cuerpos
    // reales. Debe coincidir con terraQuantumGeology.ts::ANOMALY_CONTRAST_VISIBLE.
    const _contrastMag = densScale > 1e-9 ? Math.abs(density - densBackground) / densScale : 0;
    const ANOMALY_CONTRAST_VISIBLE = 0.18;

    // ── Score/density filters ─────────────────────────────────────────────────
    if (!p.isFullDataMode && !p.professionalScoreStats.isDegenerate && _contrastMag < ANOMALY_CONTRAST_VISIBLE) {
      if (targetScore < p.minTargetScore || anomalyIntensity < p.minAnomalyIntensity || densityAnomalyScore < p.minDensityAnomalyScore) {
        writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
        colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
        continue;
      }
    }
    if (p.minDensityRaw !== null && density < p.minDensityRaw) {
      writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
      colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
      continue;
    }
    if (p.maxDensityRaw !== null && density > p.maxDensityRaw) {
      writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
      colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
      continue;
    }

    // ── Visibilidad ───────────────────────────────────────────────────────────
    let visible = false;
    if (p.effectiveProfessionalMode) {
      if (visualScore < p.professionalScoreStats.threshold) {
        writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
        colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
        continue;
      }
      visible = true;
      if (visualScore >= p.professionalScoreStats.threshold) highlightedCount++;
    } else if (p.isExplorationMode) {
      const densRange = p.densityStats.densityMax - p.densityStats.densityMin;
      if (densRange <= 1e-6) {
        visible = Number.isFinite(density);
      } else if (p.professionalScoreStats.isDegenerate) {
        visible = density >= p.densityStats.visibleDensityFloor;
      } else {
        // Visibilidad por contraste simétrico: emergen los cuerpos anómalos
        // (déficit O exceso); el fondo neutro se oculta -> sin caja blanca.
        visible = _contrastMag >= ANOMALY_CONTRAST_VISIBLE;
      }
    } else if (p.isAnomalyDataMode) {
      visible = anomalyIntensity > 0;
    } else if (p.isFullDataMode) {
      visible = true;
    } else {
      visible = visualScore > 0.01;
    }

    if (!visible) {
      writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
      colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
      continue;
    }
    visibleCount++;

    // ── Color físico multi-física ─────────────────────────────────────────────
    let _r: number, _g: number, _b: number;

    if (viewMode === 'susceptibility') {
      const chiRaw = Number(cell.susceptibility_si);
      if (!Number.isFinite(chiRaw)) {
        [_r, _g, _b] = NEUTRAL_GRAY;
      } else {
        susceptibilityFoundCount++;
        const chiLog = Math.log10(Math.max(chiRaw, 0) + 1e-9);
        const chiNorm = clamp01((chiLog - dynChiMin) / _dynChiRange);
        [_r, _g, _b] = sampleColormap(TURBO_STOPS, chiNorm);
      }
    } else if (viewMode === 'joint') {
      const jointRaw = cell.joint_structural_score;
      const jointScore = (jointRaw !== undefined && jointRaw !== null) ? Number(jointRaw) : 1.0;
      if (!Number.isFinite(jointScore) || jointScore < jointThreshold) {
        writeMatrix(matricesF32, mb, 0, 0, 0, rx_visual, ry_visual, rz_visual);
        colorsF32[cb] = 0; colorsF32[cb + 1] = 0; colorsF32[cb + 2] = 0;
        continue;
      }
      _r = 0.047; _g = 0.827; _b = 0.933;
    } else {
      const _sigmaRaw = Number(cell.posterior_std);
      const _sigmaRatio = (Number.isFinite(_sigmaRaw) && effectiveSigma95 > 0)
        ? Math.min(_sigmaRaw / effectiveSigma95, 1) : 0;

      if (p.visualLayer === "uncertainty") {
        [_r, _g, _b] = sampleColormap(INFERNO_STOPS, _sigmaRatio);
      } else {
        // Densidad por CONTRASTE respecto al fondo (mediana). t=0.5=fondo (blanco),
        // t<0.5=déficit (azul), t>0.5=exceso (rojo). Escala simétrica robusta.
        const _contrast = density - densBackground;
        const _u = clamp01(0.5 + 0.5 * (_contrast / densScale));
        [_r, _g, _b] = sampleColormap(DENSITY_DIVERGING_STOPS, _u);
        const _alpha = 1 - 0.7 * _sigmaRatio;
        _r *= _alpha; _g *= _alpha; _b *= _alpha;
      }
    }

    const brightness = 0.55 + Math.min(1.0, (sensitivityProxy - DOI_THRESHOLD) / (0.3 - DOI_THRESHOLD)) * 0.45;
    writeMatrix(matricesF32, mb, rdx, rdy, rdz, rx_visual, ry_visual, rz_visual);
    colorsF32[cb]     = _r * brightness;
    colorsF32[cb + 1] = _g * brightness;
    colorsF32[cb + 2] = _b * brightness;
  }

  return {
    reqId: p.reqId,
    matricesF32,
    colorsF32,
    visibleCount,
    highlightedCount,
    susceptibilityAvailable: susceptibilityFoundCount > 0,
  };
}

// ── Entry point ───────────────────────────────────────────────────────────────
self.onmessage = (e: MessageEvent<WorkerInput>) => {
  const result = buildBuffers(e.data);
  // Transferir buffers (zero-copy): el worker cede ownership al hilo principal.
  (self as DedicatedWorkerGlobalScope).postMessage(result, [result.matricesF32.buffer, result.colorsF32.buffer]);
};
