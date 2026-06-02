"use client";

import {
  useMemo,
  useRef,
  useLayoutEffect,
  useEffect,
  useState,
  type RefObject,
} from "react";
import { useThree, useFrame } from "@react-three/fiber";
import {
  OrbitControls,
  ContactShadows,
  Environment,
  Grid,
  Edges,
  Html,
} from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import * as THREE from "three";
import { useAppStore } from "../store/useAppStore";
import type { VisualLayer, SliceAxis, ViewMode } from "../store/useAppStore";
import { buildTerrainTextureProxyUrl } from "../lib/terraquantum/frontendApi";
import { updateInstancedBuffers } from "../lib/terraQuantumGeology";
import PostFX from "./viewport/PostFX";
import { fmtNum, fmtSci } from "./datos/helpers";
import { motion } from "framer-motion";

// Tipos mínimos locales para las celdas del modelo 3D
interface SceneCell {
  x?: number; cx?: number;
  y?: number; cy?: number;
  z?: number; cz?: number;
  density?: number | null; rho?: number | null;
  probability?: number;
  visual_score?: number;
  grade?: number; real_grade?: number;
  is_active?: boolean | number | null;
  normalized_sensitivity?: number | null;
  sensitivity_proxy?: number | null;
  [key: string]: number | boolean | null | undefined;
}

interface ProfessionalScoreStats {
  p2: number;
  p5: number;
  p50: number;
  p85: number;
  p90: number;
  p95: number;
  p98: number;
  threshold: number;
  highThreshold: number;
  extremeThreshold: number;
  isDegenerate: boolean;
  highlightedCount: number;
  highlightedRatio: number;
}

interface ElevationVisualState {
  enabled: boolean;
  refElev: number;
  minVoxelY: number | null;
  maxVoxelY: number | null;
}

interface BackendPercentileStats {
  is_degenerate?: boolean;
  visual_score_p2?: number | null;
  visual_score_p5?: number | null;
  visual_score_p50?: number | null;
  visual_score_p85?: number | null;
  visual_score_p90?: number | null;
  visual_score_p95?: number | null;
  visual_score_p98?: number | null;
  professional_threshold?: number | null;
  professional_high_threshold?: number | null;
  professional_extreme_threshold?: number | null;
}

// Densidad de roca país de referencia (granodiorita). El backend debe proveer el valor específico del sitio.
const DENSITY_COUNTRY_ROCK_FALLBACK_T_M3 = 2.75;
function clamp01(value: number) {
  return Math.max(0, Math.min(1, value));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  return value as Record<string, unknown>;
}

function safeNumber(value: unknown, fallback = 0): number {
  const n = Number(value);

  return Number.isFinite(n) ? n : fallback;
}

function getCellNumber(cell: SceneCell, keys: string[], fallback = 0) {
  for (const key of keys) {
    const value = Number(cell?.[key]);
    if (Number.isFinite(value)) return value;
  }

  return fallback;
}

function getVisualVoxelY(
  cell: SceneCell,
  elevationEnabled: boolean,
  refElev: number,
): number {
  if (elevationEnabled) {
    const elev = Number(cell.voxel_elevation_masl);
    if (Number.isFinite(elev)) {
      return elev - refElev;
    }
  }
  return getCellNumber(cell, ["y", "cy"], 0);
}

function getVoxelAnomalyIntensity(cell: SceneCell) {
  return getCellNumber(cell, ["anomaly_intensity", "grade", "real_grade", "rho"], 0);
}

function getVoxelTargetScore(cell: SceneCell) {
  return getCellNumber(cell, ["target_score", "probability"], 0);
}

function getVoxelModeledDensity(cell: SceneCell) {
  return getCellNumber(cell, ["modeled_density_index", "density", "rho"], 2.6);
}

function getVoxelDensityAnomalyScore(cell: SceneCell) {
  const score = getCellNumber(cell, ["density_anomaly_score"], -999);
  if (score !== -999) return score;
  const dens = getVoxelModeledDensity(cell);
  return Math.max(0, dens - DENSITY_COUNTRY_ROCK_FALLBACK_T_M3) / DENSITY_COUNTRY_ROCK_FALLBACK_T_M3;
}

function getExplorationDensity(cell: SceneCell) {
  return getVoxelModeledDensity(cell);
}

// Estos controles solo alteran la visualización; no modifican el modelo físico calculado por backend.
function getVoxelVisualValue(cell: SceneCell, layer: VisualLayer): number {
  switch (layer) {
    case "anomaly_intensity": return getVoxelAnomalyIntensity(cell);
    case "target_score":      return getVoxelTargetScore(cell);
    case "density_anomaly_score": return getVoxelDensityAnomalyScore(cell);
    case "modeled_density":   return getVoxelModeledDensity(cell);
    default:                  return getVoxelTargetScore(cell);
  }
}

function getCellVisualScore(cell: unknown): number {
  if (!cell || typeof cell !== "object") return 0;
  const sc = cell as SceneCell;
  
  if (sc.visual_score !== undefined && Number.isFinite(sc.visual_score)) return clamp01(sc.visual_score);
  if (sc.relative_target_score !== undefined && Number.isFinite(sc.relative_target_score)) return clamp01(sc.relative_target_score as number);
  const densityAnomaly = getCellNumber(sc, ["density_anomaly_score"], -999);
  if (densityAnomaly !== -999) return clamp01(densityAnomaly);
  if (sc.probability !== undefined && Number.isFinite(sc.probability)) return clamp01(sc.probability);
  
  const density = getVoxelModeledDensity(sc);
  return clamp01(Math.max(0, density - DENSITY_COUNTRY_ROCK_FALLBACK_T_M3) / DENSITY_COUNTRY_ROCK_FALLBACK_T_M3);
}

function readFiniteRecordNumber(
  record: Record<string, unknown> | null | undefined,
  key: string,
  fallback: number
) {
  const value = Number(record?.[key]);

  return Number.isFinite(value) ? value : fallback;
}

function countScoresAtOrAbove(cells: SceneCell[], threshold: number) {
  return cells.reduce(
    (total, cell) => total + (getCellVisualScore(cell) >= threshold ? 1 : 0),
    0
  );
}

function getBackendProfessionalScoreStats(
  modelRecord: Record<string, unknown> | null,
  cells: SceneCell[]
): ProfessionalScoreStats | null {
  const diagnosticStats = asRecord(modelRecord?.diagnosticStats);
  const scoreStatsRecord =
    asRecord(modelRecord?.scoreStats) ??
    asRecord(modelRecord?.visualScoreStats) ??
    asRecord(diagnosticStats?.visual_score);

  if (!scoreStatsRecord) return null;

  const p2 = readFiniteRecordNumber(scoreStatsRecord, "p2", 0);
  const p5 = readFiniteRecordNumber(scoreStatsRecord, "p5", p2);
  const p50 = readFiniteRecordNumber(scoreStatsRecord, "p50", p5);
  const p85 = readFiniteRecordNumber(scoreStatsRecord, "p85", p50);
  const p90 = readFiniteRecordNumber(scoreStatsRecord, "p90", p85);
  const p95 = readFiniteRecordNumber(scoreStatsRecord, "p95", p90);
  const p98 = readFiniteRecordNumber(scoreStatsRecord, "p98", p95);
  const isDegenerate =
    scoreStatsRecord.isDegenerate === true ||
    scoreStatsRecord.is_degenerate === true ||
    modelRecord?.isDegenerate === true ||
    modelRecord?.is_degenerate === true ||
    Math.abs(readFiniteRecordNumber(scoreStatsRecord, "max", p98) - readFiniteRecordNumber(scoreStatsRecord, "min", p2)) <= 0.000001;
  const highlightedCount = isDegenerate ? 0 : countScoresAtOrAbove(cells, p85);

  return {
    p2,
    p5,
    p50,
    p85,
    p90,
    p95,
    p98,
    threshold: p85,
    highThreshold: p95,
    extremeThreshold: p98,
    isDegenerate,
    highlightedCount,
    highlightedRatio: cells.length > 0 ? highlightedCount / cells.length : 0,
  };
}

function getProfessionalScoreStats(
  cells: SceneCell[],
  modelRecord?: Record<string, unknown> | null,
  storePercentileStats?: BackendPercentileStats | null
): ProfessionalScoreStats {
  // Priority 1: store percentile stats computed on full df by backend
  if (
    storePercentileStats &&
    !storePercentileStats.is_degenerate &&
    storePercentileStats.professional_threshold != null
  ) {
    const p2 = storePercentileStats.visual_score_p2 ?? 0;
    const p5 = storePercentileStats.visual_score_p5 ?? p2;
    const p50 = storePercentileStats.visual_score_p50 ?? p5;
    const p85 = storePercentileStats.visual_score_p85 ?? p50;
    const p90 = storePercentileStats.visual_score_p90 ?? p85;
    const p95 = storePercentileStats.visual_score_p95 ?? p90;
    const p98 = storePercentileStats.visual_score_p98 ?? p95;
    const threshold = storePercentileStats.professional_threshold;
    const highThreshold = storePercentileStats.professional_high_threshold ?? p95;
    const extremeThreshold = storePercentileStats.professional_extreme_threshold ?? p98;
    const highlightedCount = countScoresAtOrAbove(cells, threshold);
    return {
      p2, p5, p50, p85, p90, p95, p98,
      threshold,
      highThreshold,
      extremeThreshold,
      isDegenerate: false,
      highlightedCount,
      highlightedRatio: cells.length > 0 ? highlightedCount / cells.length : 0,
    };
  }

  if (storePercentileStats?.is_degenerate === true) {
    return {
      p2: 0, p5: 0, p50: 0, p85: 0, p90: 0, p95: 0, p98: 0,
      threshold: 0, highThreshold: 0, extremeThreshold: 0,
      isDegenerate: true,
      highlightedCount: 0,
      highlightedRatio: 0,
    };
  }

  // Priority 2: backend model record stats
  const backendStats = getBackendProfessionalScoreStats(modelRecord ?? null, cells);
  if (backendStats) return backendStats;

  const scores = cells
    .map((cell) => getCellVisualScore(cell))
    .filter((score) => Number.isFinite(score));

  if (scores.length === 0) {
    return {
      p2: 0,
      p5: 0,
      p50: 0,
      p85: 0,
      p90: 0,
      p95: 0,
      p98: 0,
      threshold: 0,
      highThreshold: 0,
      extremeThreshold: 0,
      isDegenerate: true,
      highlightedCount: 0,
      highlightedRatio: 0,
    };
  }

  const sortedScores = [...scores].sort((a, b) => a - b);
  const p2 = getQuantileFromSorted(sortedScores, 0.02);
  const p5 = getQuantileFromSorted(sortedScores, 0.05);
  const p50 = getQuantileFromSorted(sortedScores, 0.5);
  const p85 = getQuantileFromSorted(sortedScores, 0.85);
  const p90 = getQuantileFromSorted(sortedScores, 0.9);
  const p95 = getQuantileFromSorted(sortedScores, 0.95);
  const p98 = getQuantileFromSorted(sortedScores, 0.98);
  let minScore = Infinity;
  let maxScore = -Infinity;
  for (const score of scores) {
    if (score < minScore) minScore = score;
    if (score > maxScore) maxScore = score;
  }
  const isDegenerate = Math.abs(maxScore - minScore) <= 0.000001;
  const highlightedCount = isDegenerate ? 0 : scores.reduce(
    (total, score) => total + (score >= p85 ? 1 : 0),
    0
  );

  return {
    p2,
    p5,
    p50,
    p85,
    p90,
    p95,
    p98,
    threshold: p85,
    highThreshold: p95,
    extremeThreshold: p98,
    isDegenerate,
    highlightedCount,
    highlightedRatio: highlightedCount / scores.length,
  };
}

interface ModelBounds {
  minX: number; maxX: number;
  minY: number; maxY: number;
  minZ: number; maxZ: number;
}

// slicePosition is in absolute model coords. Genera un único plano half-space:
// oculta todo lo que está BEYOND el plano (axisPos > slicePosition).
// THREE.Plane(n, d) clips where n·p + d < 0.
// Para "ocultar donde x > center": n = (−1,0,0), d = center → −x + center < 0 ↔ x > center ✓
function computeClippingPlanes(
  sliceAxis: SliceAxis,
  slicePosition: number,
  modelBounds: ModelBounds | null
): THREE.Plane[] {
  if (sliceAxis === "none" || !modelBounds) return [];

  const axisNormals: Record<"x" | "y" | "z", THREE.Vector3> = {
    x: new THREE.Vector3(1, 0, 0),
    y: new THREE.Vector3(0, 1, 0),
    z: new THREE.Vector3(0, 0, 1),
  };
  const axisBounds: Record<"x" | "y" | "z", [number, number]> = {
    x: [modelBounds.minX, modelBounds.maxX],
    y: [modelBounds.minY, modelBounds.maxY],
    z: [modelBounds.minZ, modelBounds.maxZ],
  };

  const normal = axisNormals[sliceAxis];
  const [min, max] = axisBounds[sliceAxis];
  const range = max - min;

  if (range < 1e-9) return [];

  const relPos = Math.max(0, Math.min(1, (slicePosition - min) / range));
  const center = min + relPos * range;

  // Un solo plano half-space: oculta axisPos > center.
  // normal.negate() → (−1,0,0) para X; constante = center.
  return [
    new THREE.Plane(normal.clone().negate(), center),
  ];
}

function getQuantile(values: number[], q: number) {
  if (values.length === 0) return 0;

  const sorted = [...values].sort((a, b) => a - b);
  return getQuantileFromSorted(sorted, q);
}

function getQuantileFromSorted(sorted: number[], q: number) {
  if (sorted.length === 0) return 0;

  const index = Math.floor(clamp01(q) * (sorted.length - 1));

  return sorted[index] ?? 0;
}

function getExplorationSupportScore(cell: SceneCell, densityRatio: number) {
  const probability = clamp01(getVoxelTargetScore(cell));
  const visualScore = clamp01(getCellNumber(cell, ["visual_score"], densityRatio));
  const densityAnomalyScore = clamp01(getVoxelDensityAnomalyScore(cell));

  return Math.max(probability * 0.45, visualScore * 0.45, densityAnomalyScore * 0.10);
}

// Envolvente visual aproximada del cuerpo anómalo. No modifica el modelo físico ni confirma mineral.
function AnomalyEnvelope({
  elevationVisualState,
  clippingPlanes,
}: {
  elevationVisualState: ElevationVisualState;
  clippingPlanes?: THREE.Plane[];
}) {
  const {
    model,
    visualLayer,
    minTargetScore,
    minAnomalyIntensity,
    minDensityAnomalyScore,
    showAnomalyEnvelope,
    anomalyEnvelopePercent,
  } = useAppStore();

  const { enabled: elevationEnabled, refElev } = elevationVisualState;

  const envelope = useMemo(() => {
    if (!model || !model.cells || model.cells.length === 0) return null;

    const cells = model.cells as SceneCell[];

    // Score each cell by the current visual layer
    const scored = cells
      .map((cell, idx) => ({ cell, idx, score: getVoxelVisualValue(cell, visualLayer) }))
      .filter(({ cell }) => {
        // Honour the same user filters as the voxel renderer
        return (
          getVoxelTargetScore(cell) >= minTargetScore &&
          getVoxelAnomalyIntensity(cell) >= minAnomalyIntensity &&
          getVoxelDensityAnomalyScore(cell) >= minDensityAnomalyScore
        );
      });

    if (scored.length === 0) return null;

    // Keep only the top anomalyEnvelopePercent of cells
    scored.sort((a, b) => b.score - a.score);
    const topCount = Math.max(1, Math.round(scored.length * anomalyEnvelopePercent));
    const topCells = scored.slice(0, topCount).map((s) => s.cell);

    if (topCells.length < 2) return null;

    // Compute bounding box of top cells
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;

    for (const cell of topCells) {
      const x = getCellNumber(cell, ["x", "cx"], 0);
      const y = getVisualVoxelY(cell, elevationEnabled, refElev);
      const z = getCellNumber(cell, ["z", "cz"], 0);
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (z < minZ) minZ = z;
      if (z > maxZ) maxZ = z;
    }

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const centerZ = (minZ + maxZ) / 2;

    // Add a small padding (half a cell) so the envelope hugs the body properly
    const pad = (model.cellSize || 10) * 0.6;
    const sizeX = Math.max((maxX - minX) / 2 + pad, pad);
    const sizeY = Math.max((maxY - minY) / 2 + pad, pad);
    const sizeZ = Math.max((maxZ - minZ) / 2 + pad, pad);

    return { centerX, centerY, centerZ, sizeX, sizeY, sizeZ };
  }, [model, visualLayer, minTargetScore, minAnomalyIntensity, minDensityAnomalyScore, anomalyEnvelopePercent, elevationEnabled, refElev]);

  if (!showAnomalyEnvelope || !envelope) return null;

  const { centerX, centerY, centerZ, sizeX, sizeY, sizeZ } = envelope;

  return (
    <group position={[centerX, centerY, centerZ]} scale={[sizeX, sizeY, sizeZ]}>
      {/* Solid translucent shell */}
      <mesh>
        <sphereGeometry args={[1, 32, 24]} />
        <meshStandardMaterial
          color="#8ecfaf"
          transparent
          opacity={0.13}
          depthWrite={false}
          roughness={0.4}
          metalness={0.1}
          side={2}
          clippingPlanes={clippingPlanes}
        />
      </mesh>
      {/* Wireframe overlay */}
      <mesh>
        <sphereGeometry args={[1.004, 18, 14]} />
        <meshBasicMaterial
          color="#c2d8c4"
          transparent
          opacity={0.22}
          wireframe
          depthWrite={false}
          clippingPlanes={clippingPlanes}
        />
      </mesh>
    </group>
  );
}

// Volumen host interpretativo — solo para contexto espacial.
function HostVolume({
  modelCenter,
}: {
  modelCenter: [number, number, number];
}) {
  const { model, showHostVolume } = useAppStore();
  if (!model || !showHostVolume) return null;

  const domL = model.domainL || 200;
  const domH = model.domainH || 200;
  const domW = model.domainW || 200;

  return (
    <mesh
      position={[modelCenter[0], modelCenter[1], modelCenter[2]]}
      renderOrder={-1}
    >
      <boxGeometry args={[domL * 1.5, domH, domW * 1.5]} />
      <meshStandardMaterial
        color="#909090"
        wireframe
        depthWrite={false}
        clippingPlanes={[]}
      />
    </mesh>
  );
}

// HITO 6: por encima de este umbral se usa el WebWorker para no bloquear el hilo principal.
const LOD_WORKER_THRESHOLD = 50_000;

function MineralComplex({
  elevationVisualState,
  clippingPlanes,
}: {
  elevationVisualState: ElevationVisualState;
  clippingPlanes?: THREE.Plane[];
}) {
  const {
    model, showVoxels,
    visualLayer, minTargetScore, minAnomalyIntensity, minDensityAnomalyScore,
    minDensityRaw, maxDensityRaw,
    voxelOpacity, voxelScale,
    sliceAxis, slicePosition, sliceThickness, showOnlySlice, setVisibleCellCount,
    setHighlightedCellCount, setSelectedVoxel,
    blockModelDataMode, visualProfessionalMode,
    setSusceptibilityDataAvailable,
  } = useAppStore();
  const percentileStats = useAppStore((s) => s.percentileStats);
  // ── Fase 12: selectores granulares para evitar cascading renders ───────────────
  const viewMode = useAppStore((s) => s.viewMode);
  const jointThreshold = useAppStore((s) => s.jointThreshold);

  const meshRef = useRef<THREE.InstancedMesh>(null);
  const lastVisibleCellCount = useRef(-1);
  const lastHighlightedCellCount = useRef(-1);
  // Captura el mesh actual antes de que cambie el count (nuevo modelo).
  // Se usa para liberar los buffers GPU de la malla anterior.
  const meshToDisposeRef = useRef<THREE.InstancedMesh | null>(null);
  // ── HITO 6: WebWorker para modelos grandes ────────────────────────────────
  const workerRef = useRef<Worker | null>(null);
  const pendingReqRef = useRef(0);

  const count = model && model.cells ? model.cells.length : 0;

  // ── Dispose de recursos GPU al cambiar de modelo ──────────────────────────
  // Capturamos el mesh ANTES de que count cambie. Cuando el efecto se limpia
  // (nuevo count → R3F reconstruye el instancedMesh), liberamos la malla vieja.
  useEffect(() => {
    meshToDisposeRef.current = meshRef.current;
    return () => {
      const prev = meshToDisposeRef.current;
      if (!prev) return;
      try {
        prev.geometry.dispose();
        const mat = prev.material;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else if (mat && typeof mat.dispose === "function") mat.dispose();
        // No se tocan instanceMatrix.array ni instanceColor.array:
        // Three.js no soporta redimensionar buffers ya cargados en GPU —
        // hacerlo mientras ContactShadows aún renderiza la malla vieja
        // lanza "Resizing buffer attributes is not supported".
        // R3F elimina la malla del scene graph y el GC libera la memoria.
      } catch {
        // Silenciar errores de dispose: el contexto WebGL puede ya estar perdido.
      }
      meshToDisposeRef.current = null;
    };
  }, [count]); // re-corre cuando count cambia (nuevo modelo) o al desmontar
  // ────────────────────────────────────────────────────────────────────────────

  // ── HITO 6: ciclo de vida del WebWorker ─────────────────────────────────────
  useEffect(() => {
    const w = new Worker(
      new URL('../workers/voxelBufferBuilder.worker.ts', import.meta.url)
    );
    workerRef.current = w;
    return () => {
      w.terminate();
      workerRef.current = null;
    };
  }, []); // montar/desmontar una sola vez
  // ────────────────────────────────────────────────────────────────────────────

  const modelRecord = asRecord(model);

  const visualMode = String(
    modelRecord?.visualMode ?? "density_probability"
  ).toLowerCase();

  const isExplorationMode =
    visualMode.includes("density") ||
    visualMode.includes("probability") ||
    visualMode.includes("exploration");

  const isFullDataMode = blockModelDataMode === "full";
  const isAnomalyDataMode = blockModelDataMode === "anomaly";

  const professionalScoreStats = useMemo(() => {
    const cells = model?.cells ? (model.cells as SceneCell[]) : [];
    return getProfessionalScoreStats(cells, modelRecord, percentileStats);
  }, [model, modelRecord, percentileStats]);
  const effectiveProfessionalMode =
    visualProfessionalMode && !professionalScoreStats.isDegenerate;

  // ── Tamaño real de la celda por eje ────────────────────────────────────────
  // Derivado del mínimo espaciado entre posiciones únicas en cada eje.
  // Garantiza que BoxGeometry(1,1,1) × scale = celda exacta → sin huecos.
  const voxelCellSizes = useMemo(() => {
    const fb = model?.cellSize || 10;
    if (!model?.cells?.length) return { dx: fb, dy: fb, dz: fb };

    const cells = model.cells as SceneCell[];
    const xVals = new Set<number>();
    const yVals = new Set<number>();
    const zVals = new Set<number>();

    for (const cell of cells) {
      xVals.add(getCellNumber(cell, ["x", "cx"], 0));
      yVals.add(getCellNumber(cell, ["y", "cy"], 0));
      zVals.add(getCellNumber(cell, ["z", "cz"], 0));
    }

    const minGap = (vals: Set<number>, fallback: number): number => {
      const sorted = Array.from(vals).sort((a, b) => a - b);
      if (sorted.length < 2) return fallback;
      let m = Infinity;
      for (let i = 1; i < sorted.length; i++) {
        const d = sorted[i] - sorted[i - 1];
        if (d > 1e-6 && d < m) m = d;
      }
      return m < Infinity ? m : fallback;
    };

    return {
      dx: minGap(xVals, fb),
      dy: minGap(yVals, fb),
      dz: minGap(zVals, fb),
    };
  }, [model]);
  // ────────────────────────────────────────────────────────────────────────────

  const densityStats = useMemo(() => {
    if (!model || !model.cells || model.cells.length === 0) {
      return {
        densities: [] as number[],
        supportScores: [] as number[],
        visualValues: [] as number[],
        visualMin: 0,
        visualMax: 1,
        densityMin: 0,
        densityMax: 0,
        visibleDensityFloor: 0,
      };
    }

    const modelStats = asRecord(model) ?? {};
    const cells = model.cells as SceneCell[];
    const densities = cells.map((cell) => getExplorationDensity(cell));
    let cellDensityMin = Infinity;
    let cellDensityMax = -Infinity;
    for (const density of densities) {
      if (density < cellDensityMin) cellDensityMin = density;
      if (density > cellDensityMax) cellDensityMax = density;
    }
    const backendDensityMin = Number(modelStats.densityMin);
    const backendDensityMax = Number(modelStats.densityMax);
    const hasBackendDensityRange =
      Number.isFinite(backendDensityMin) &&
      Number.isFinite(backendDensityMax) &&
      backendDensityMax > backendDensityMin;

    const densityMin = hasBackendDensityRange ? backendDensityMin : cellDensityMin;
    const densityMax = hasBackendDensityRange ? backendDensityMax : cellDensityMax;
    const densityRange = densityMax - densityMin;
    const supportScores = cells.map((cell, index) => {
      const densityRatio =
        densityRange > 0.000001
          ? clamp01((densities[index] - densityMin) / densityRange)
          : 0.5;

      return getExplorationSupportScore(cell, densityRatio);
    });

    // Compute per-layer visual values for color mapping
    const visualValues = cells.map((cell) => getVoxelVisualValue(cell, visualLayer));
    let visualMin = Infinity;
    let visualMax = -Infinity;
    for (const value of visualValues) {
      if (value < visualMin) visualMin = value;
      if (value > visualMax) visualMax = value;
    }

    /*
      En modo exploración NO queremos mostrar el cubo completo.
      Mostramos el cuerpo anómalo: el grupo superior por densidad/probabilidad.
      Esto es solo un filtro visual; el backend sigue calculando el modelo completo.
    */
    const backendDensityStats = asRecord(modelStats.densityStats);
    let densityFloorByQuantile = readFiniteRecordNumber(
      backendDensityStats,
      "p5",
      Number.NaN
    );
    if (!Number.isFinite(densityFloorByQuantile)) {
      densityFloorByQuantile = getQuantile(densities, 0.08);
    }
    const densityFloorByRange =
      densityRange > 0.000001 ? densityMin + densityRange * 0.015 : densityMin;
    const visibleDensityFloor = Math.max(
      densityFloorByQuantile,
      densityFloorByRange
    );

    return {
      densities,
      supportScores,
      visualValues,
      visualMin,
      visualMax,
      densityMin,
      densityMax,
      visibleDensityFloor,
    };
  }, [model, visualLayer]);

  // Percentil 95 de posterior_std — normaliza la capa Inferno en updateInstancedBuffers.
  // Se recalcula solo cuando cambia el modelo (no en cada cambio de visualLayer).
  const sigma95 = useMemo((): number => {
    if (!model?.cells?.length) return 1;
    const stds: number[] = [];
    for (const c of model.cells as Array<Record<string, unknown>>) {
      const v = Number(c.posterior_std);
      if (Number.isFinite(v) && v > 0) stds.push(v);
    }
    if (stds.length === 0) return 1;
    stds.sort((a, b) => a - b);
    const idx = Math.min(Math.floor(0.95 * stds.length), stds.length - 1);
    return stds[idx] ?? 1;
  }, [model]);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || !model || count === 0) return;

    // ── HITO 6: modelos grandes → ocultar todo mientras el worker calcula ─────
    if (count > LOD_WORKER_THRESHOLD) {
      // Zero-out rápido (memset): oculta todas las instancias sin bloquear el hilo.
      (mesh.instanceMatrix.array as Float32Array).fill(0);
      mesh.instanceMatrix.needsUpdate = true;
      return;
    }
    // ─────────────────────────────────────────────────────────────────────────

    const { visibleCount, highlightedCount, susceptibilityAvailable } = updateInstancedBuffers({
      mesh,
      cells: model.cells,
      cellSize: model.cellSize || 10,
      // Tamaño real por eje (espaciado derivado de posiciones únicas de la grilla)
      cellSizeX: voxelCellSizes.dx,
      cellSizeY: voxelCellSizes.dy,
      cellSizeZ: voxelCellSizes.dz,
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
      sliceAxis,
      slicePosition,
      sliceThickness,
      showOnlySlice,
      elevationEnabled: elevationVisualState.enabled,
      refElev: elevationVisualState.refElev,
      densityStats,
      professionalScoreStats,
      visualLayer,
      sigma95,
      // ── Fase 12 ──
      viewMode,
      jointThreshold,
    });

    // ── Frustum Culling: bounding sphere explícita ────────────────────────
    // BoxGeometry(1,1,1) tiene radio ~0.87, insuficiente para un modelo de
    // cientos de metros. Calculamos el radio real para que Three.js no elimine
    // incorrectamente la malla cuando el centro sale del frustum.
    // El grupo padre ya centra el modelo en el origen del mundo,
    // así que el centro de la esfera es (0,0,0) en espacio local.
    {
      const r = Math.sqrt(
        Math.pow((model.domainL || 200) / 2, 2) +
        Math.pow((model.domainH || 200) / 2, 2) +
        Math.pow((model.domainW || 200) / 2, 2)
      ) * 1.05; // 5 % de margen para celdas en los bordes
      if (!mesh.geometry.boundingSphere) {
        mesh.geometry.boundingSphere = new THREE.Sphere();
      }
      mesh.geometry.boundingSphere.center.set(0, 0, 0);
      mesh.geometry.boundingSphere.radius = r;
    }
    // ────────────────────────────────────────────────────────────────────────

    if (visibleCount !== lastVisibleCellCount.current) {
      lastVisibleCellCount.current = visibleCount;
      setVisibleCellCount(visibleCount);
    }
    if (highlightedCount !== lastHighlightedCellCount.current) {
      lastHighlightedCellCount.current = highlightedCount;
      setHighlightedCellCount(highlightedCount);
    }
    if (viewMode === 'susceptibility') {
      setSusceptibilityDataAvailable(susceptibilityAvailable);
    }
  }, [
    model,
    count,
    isExplorationMode,
    isFullDataMode,
    isAnomalyDataMode,
    densityStats,
    voxelCellSizes,
    minTargetScore,
    minAnomalyIntensity,
    minDensityAnomalyScore,
    minDensityRaw,
    maxDensityRaw,
    voxelScale,
    sliceAxis,
    slicePosition,
    sliceThickness,
    showOnlySlice,
    effectiveProfessionalMode,
    professionalScoreStats,
    elevationVisualState,
    setVisibleCellCount,
    setHighlightedCellCount,
    setSusceptibilityDataAvailable,
    visualLayer,
    sigma95,
    // ── Fase 12 ──
    viewMode,
    jointThreshold,
  ]);

  // ── HITO 6: path asíncrono para modelos grandes (worker) ─────────────────────
  // Se dispara con los mismos deps que useLayoutEffect. Para count <= umbral
  // el retorno temprano garantiza que no hace nada (lo maneja el path síncrono).
  useEffect(() => {
    if (count <= LOD_WORKER_THRESHOLD) return;
    const worker = workerRef.current;
    const mesh = meshRef.current;
    if (!worker || !mesh || !model || count === 0) return;

    const reqId = ++pendingReqRef.current;
    worker.postMessage({
      reqId,
      cells: model.cells,
      cellSize: model.cellSize || 10,
      cellSizeX: voxelCellSizes.dx,
      cellSizeY: voxelCellSizes.dy,
      cellSizeZ: voxelCellSizes.dz,
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
      sliceAxis,
      slicePosition,
      sliceThickness,
      showOnlySlice,
      elevationEnabled: elevationVisualState.enabled,
      refElev: elevationVisualState.refElev,
      densityStats,
      professionalScoreStats,
      visualLayer,
      sigma95,
      viewMode,
      jointThreshold,
    });

    const handleMsg = (e: MessageEvent<{
      reqId: number;
      matricesF32: Float32Array;
      colorsF32: Float32Array;
      visibleCount: number;
      highlightedCount: number;
      susceptibilityAvailable: boolean;
    }>) => {
      if (!e.data || e.data.reqId !== reqId) return;
      worker.removeEventListener('message', handleMsg);

      const m = meshRef.current;
      if (!m) return;

      const { matricesF32, colorsF32, visibleCount: vc, highlightedCount: hc, susceptibilityAvailable: sa } = e.data;

      (m.instanceMatrix.array as Float32Array).set(matricesF32);
      m.instanceMatrix.needsUpdate = true;

      if (!m.instanceColor) {
        m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(colorsF32), 3);
      } else {
        (m.instanceColor.array as Float32Array).set(colorsF32);
      }
      m.instanceColor.needsUpdate = true;

      // Bounding sphere explícita para frustum culling correcto
      if (!m.geometry.boundingSphere) m.geometry.boundingSphere = new THREE.Sphere();
      m.geometry.boundingSphere.center.set(0, 0, 0);
      m.geometry.boundingSphere.radius = Math.sqrt(
        Math.pow((model?.domainL || 200) / 2, 2) +
        Math.pow((model?.domainH || 200) / 2, 2) +
        Math.pow((model?.domainW || 200) / 2, 2)
      ) * 1.05;

      if (vc !== lastVisibleCellCount.current) {
        lastVisibleCellCount.current = vc;
        setVisibleCellCount(vc);
      }
      if (hc !== lastHighlightedCellCount.current) {
        lastHighlightedCellCount.current = hc;
        setHighlightedCellCount(hc);
      }
      if (viewMode === 'susceptibility') {
        setSusceptibilityDataAvailable(sa);
      }
    };

    worker.addEventListener('message', handleMsg);
    return () => worker.removeEventListener('message', handleMsg);
  }, [
    model, count, isExplorationMode, isFullDataMode, isAnomalyDataMode,
    densityStats, voxelCellSizes, minTargetScore, minAnomalyIntensity,
    minDensityAnomalyScore, minDensityRaw, maxDensityRaw, voxelScale,
    sliceAxis, slicePosition, sliceThickness, showOnlySlice,
    effectiveProfessionalMode, professionalScoreStats, elevationVisualState,
    setVisibleCellCount, setHighlightedCellCount, setSusceptibilityDataAvailable,
    visualLayer, sigma95, viewMode, jointThreshold,
  ]);
  // ────────────────────────────────────────────────────────────────────────────

  if (!model || count === 0) return null;

  // Transparencia física (transmission) solo cuando la malla es ligera y translúcida:
  // refractar/transmitir cuesta un render-target extra, inviable en modelos densos
  // (modo full/anomaly hasta 250k). En modo exploración (≤5k) y vista debug translúcida
  // sí podemos permitirla para un look "mineral" premium.
  const useTransmission =
    isExplorationMode && !effectiveProfessionalMode && count > 0 && count <= 20000;
  const cellRef = model.cellSize || 10;

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, count] as unknown as [THREE.BufferGeometry, THREE.Material, number]}
      castShadow
      receiveShadow
      visible={showVoxels}
      // frustumCulled=false: la visibilidad por instancia ya se gestiona con
      // scale=0 en updateInstancedBuffers. La BoxGeometry(1,1,1) tiene un
      // bounding sphere de radio ~0.87, insuficiente para modelos de cientos
      // de metros, lo que causaría culling incorrecto de toda la malla.
      frustumCulled={false}
      onClick={(e) => {
        // Picking de vóxel (Fase E): raycast → instanceId → celda del modelo.
        const id = e.instanceId;
        if (id === undefined || !model || !model.cells) return;
        const cell = model.cells[id] as SceneCell | undefined;
        if (!cell) return;
        e.stopPropagation();
        const x = getCellNumber(cell, ["x", "cx"], 0);
        const y = getVisualVoxelY(
          cell,
          elevationVisualState.enabled,
          elevationVisualState.refElev
        );
        const z = getCellNumber(cell, ["z", "cz"], 0);
        setSelectedVoxel({
          index: id,
          cell: cell as Record<string, number | string | boolean | null | undefined>,
          position: [x, y, z],
        });
      }}
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshPhysicalMaterial
        roughness={effectiveProfessionalMode ? 0.48 : 0.4}
        metalness={0.12}
        clearcoat={0.35}
        clearcoatRoughness={0.4}
        ior={1.45}
        specularIntensity={0.6}
        envMapIntensity={0.9}
        transparent={!effectiveProfessionalMode && isExplorationMode}
        opacity={!effectiveProfessionalMode && isExplorationMode ? voxelOpacity : 1}
        transmission={useTransmission ? 0.32 : 0}
        thickness={useTransmission ? cellRef : 0}
        attenuationDistance={useTransmission ? cellRef * 10 : Infinity}
        attenuationColor="#dfe7ee"
        clippingPlanes={clippingPlanes}
      />
    </instancedMesh>
  );
}

function TerrainTexturedMaterial({
  textureUrl,
  opacity,
}: {
  textureUrl: string;
  opacity: number;
}) {
  const [terrainTexture, setTerrainTexture] = useState<THREE.Texture | null>(null);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    let isActive = true;
    let loadedTexture: THREE.Texture | null = null;

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");

    try {
      loader.load(
        textureUrl,
        (texture) => {
          if (!isActive) {
            texture.dispose();
            return;
          }

          texture.colorSpace = THREE.SRGBColorSpace;
          texture.wrapS = THREE.ClampToEdgeWrapping;
          texture.wrapT = THREE.ClampToEdgeWrapping;
          texture.needsUpdate = true;
          loadedTexture = texture;
          setTerrainTexture(texture);
        },
        undefined,
        (error) => {
          if (!isActive) return;

          console.warn("Terrain texture failed, using fallback material.", error);
          setHasError(true);
        }
      );
    } catch (error) {
      console.warn("Terrain texture failed, using fallback material.", error);
      queueMicrotask(() => {
        if (isActive) setHasError(true);
      });
    }

    return () => {
      isActive = false;
      loadedTexture?.dispose();
    };
  }, [textureUrl]);

  if (hasError || !terrainTexture) {
    return <FallbackTerrainMaterial opacity={opacity} />;
  }

  return (
    <meshStandardMaterial
      map={terrainTexture}
      color="#ffffff"
      roughness={0.85}
      transparent
      opacity={opacity}
      side={THREE.DoubleSide}
      polygonOffset
      polygonOffsetFactor={-1}
      polygonOffsetUnits={-1}
      clippingPlanes={[]}
    />
  );
}

function FallbackTerrainMaterial({ opacity }: { opacity: number }) {
  return (
    <meshStandardMaterial
      color="#9a7a35"
      roughness={0.75}
      transparent
      opacity={opacity}
      side={THREE.DoubleSide}
      polygonOffset
      polygonOffsetFactor={-1}
      polygonOffsetUnits={-1}
      clippingPlanes={[]}
    />
  );
}

// ─── Picking de vóxel (Fase E): tooltip científico + resaltado ───────────────
function TooltipRow({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-white/45">{label}</span>
      <span className={accent ? "text-[#22d3ee]" : "text-white/85"}>{value}</span>
    </div>
  );
}

function VoxelTooltip({
  cell,
}: {
  cell: Record<string, number | string | boolean | null | undefined>;
}) {
  const num = (k: string): number | null => {
    const n = Number(cell[k]);
    return Number.isFinite(n) ? n : null;
  };

  const density = num("density") ?? num("modeled_density_index") ?? num("rho");
  const sigma = num("posterior_std");
  const doi = num("doi_raw");
  const target = num("target_score") ?? num("probability");
  const anomaly = num("density_anomaly_score");
  const x = num("x_m") ?? num("x");
  const y = num("y_m") ?? num("y");
  const z = num("z_m") ?? num("z");
  const depth = num("depth_below_surface_m");
  const elev = num("voxel_elevation_masl");

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.16, ease: "easeOut" }}
      className="w-[180px] rounded-lg border border-cyan-400/30 bg-[#05070a]/95 px-3 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.7)] font-mono text-[8px] leading-relaxed"
    >
      <p className="text-[8px] uppercase tracking-[0.18em] text-[#22d3ee] mb-1.5 border-b border-white/10 pb-1">
        Vóxel inspeccionado
      </p>
      <div className="space-y-0.5">
        {density !== null && <TooltipRow label="Densidad" value={`${fmtNum(density, 3)} t/m³`} accent />}
        {sigma !== null && <TooltipRow label="Posterior σ" value={`${fmtSci(sigma)} t/m³`} />}
        {doi !== null && <TooltipRow label="DOI" value={fmtNum(doi, 3)} />}
        {target !== null && <TooltipRow label="Target score" value={fmtNum(target, 3)} />}
        {anomaly !== null && <TooltipRow label="Anom. densidad" value={fmtNum(anomaly, 3)} />}
        {(x !== null || z !== null) && (
          <TooltipRow label="X / Z" value={`${fmtNum(x, 0)} / ${fmtNum(z, 0)} m`} />
        )}
        {y !== null && <TooltipRow label="Y" value={`${fmtNum(y, 0)} m`} />}
        {depth !== null && <TooltipRow label="Profundidad" value={`${fmtNum(depth, 0)} m`} />}
        {elev !== null && <TooltipRow label="Elevación" value={`${fmtNum(elev, 0)} msnm`} />}
      </div>
    </motion.div>
  );
}

function VoxelInspector() {
  const selectedVoxel = useAppStore((s) => s.selectedVoxel);
  const model = useAppStore((s) => s.model);

  if (!selectedVoxel || !model) return null;

  const size = (model.cellSize || 10) * 1.1;

  return (
    <group position={selectedVoxel.position}>
      <mesh raycast={() => null}>
        <boxGeometry args={[size, size, size]} />
        <meshBasicMaterial
          color="#22d3ee"
          wireframe
          transparent
          opacity={0.95}
          depthTest={false}
        />
      </mesh>
      <group position={[0, size * 1.3, 0]}>
        <Html center occlude={false} zIndexRange={[120, 0]} style={{ pointerEvents: "none" }}>
          <VoxelTooltip cell={selectedVoxel.cell} />
        </Html>
      </group>
    </group>
  );
}

// Plano de corte tipo Leapfrog: superficie de sección semitransparente con marco
// por eje (X rojo · Y verde · Z azul) que sigue slicePosition. Es un indicador
// visual del corte half-space que ya aplica el clipping; no modifica el modelo.
// Vive DENTRO del grupo centrado, en coords de celda, para coincidir con los vóxeles.
const SLICE_AXIS_COLOR: Record<"x" | "y" | "z", string> = {
  x: "#f87171",
  y: "#4ade80",
  z: "#60a5fa",
};

function SlicePlane({
  modelBounds,
  modelCenter,
}: {
  modelBounds: ModelBounds | null;
  modelCenter: [number, number, number];
}) {
  const sliceAxis = useAppStore((s) => s.sliceAxis);
  const slicePosition = useAppStore((s) => s.slicePosition);

  if (sliceAxis === "none" || !modelBounds) return null;

  const pad = 1.06;
  const spanX = (modelBounds.maxX - modelBounds.minX) || 1;
  const spanY = (modelBounds.maxY - modelBounds.minY) || 1;
  const spanZ = (modelBounds.maxZ - modelBounds.minZ) || 1;
  const clampToBounds = (v: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, v));

  let position: [number, number, number];
  let rotation: [number, number, number];
  let size: [number, number];

  if (sliceAxis === "x") {
    const px = clampToBounds(slicePosition, modelBounds.minX, modelBounds.maxX);
    position = [px, modelCenter[1], modelCenter[2]];
    rotation = [0, Math.PI / 2, 0];
    size = [spanZ * pad, spanY * pad];
  } else if (sliceAxis === "y") {
    const py = clampToBounds(slicePosition, modelBounds.minY, modelBounds.maxY);
    position = [modelCenter[0], py, modelCenter[2]];
    rotation = [-Math.PI / 2, 0, 0];
    size = [spanX * pad, spanZ * pad];
  } else {
    const pz = clampToBounds(slicePosition, modelBounds.minZ, modelBounds.maxZ);
    position = [modelCenter[0], modelCenter[1], pz];
    rotation = [0, 0, 0];
    size = [spanX * pad, spanY * pad];
  }

  const color = SLICE_AXIS_COLOR[sliceAxis];

  return (
    <group position={position} rotation={rotation} renderOrder={2}>
      <mesh>
        <planeGeometry args={size} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.08}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
        <Edges color={color} />
      </mesh>
    </group>
  );
}

// Reset de cámara con damping real: anima posición + target hacia la pose "home"
// (derivada del tamaño del modelo actual) en lugar de remontar el <Canvas>.
// Reusa el OrbitControls existente (enableDamping) — no introduce un segundo control.
const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

function CameraRig({
  controlsRef,
  homeTarget,
}: {
  controlsRef: RefObject<OrbitControlsImpl | null>;
  homeTarget: [number, number, number];
}) {
  const camera = useThree((s) => s.camera);
  const model = useAppStore((s) => s.model);
  const hasElevationData = useAppStore((s) => s.hasElevationData);
  const cameraResetNonce = useAppStore((s) => s.cameraResetNonce);

  // Pose "home" derivada del modelo (misma fórmula que el encuadre inicial del Canvas).
  const homePose = useMemo(() => {
    const maxDomain = model
      ? Math.max(
          model.domainL || 0,
          model.domainH || 0,
          model.domainW || 0,
          (model.cellSize || 10) * 4
        )
      : 0;
    const dist = model
      ? Math.max(maxDomain * (hasElevationData ? 2.25 : 1.55), 90)
      : 35;
    const target = new THREE.Vector3(homeTarget[0], homeTarget[1], homeTarget[2]);
    const position = new THREE.Vector3(dist, dist * 0.72, dist).add(target);
    return { position, target };
  }, [model, hasElevationData, homeTarget]);

  const animRef = useRef<{
    t: number;
    fromPos: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toPos: THREE.Vector3;
    toTarget: THREE.Vector3;
  } | null>(null);
  const prevNonce = useRef(cameraResetNonce);

  useEffect(() => {
    if (cameraResetNonce === prevNonce.current) return;
    prevNonce.current = cameraResetNonce;

    const controls = controlsRef.current;
    if (!controls) return;

    animRef.current = {
      t: 0,
      fromPos: camera.position.clone(),
      fromTarget: controls.target.clone(),
      toPos: homePose.position.clone(),
      toTarget: homePose.target.clone(),
    };
  }, [cameraResetNonce, camera, controlsRef, homePose]);

  useFrame((_, delta) => {
    const anim = animRef.current;
    const controls = controlsRef.current;
    if (!anim || !controls) return;

    // ~0.7 s de transición; clamp por si delta es grande tras un stall.
    anim.t = Math.min(1, anim.t + Math.min(delta, 0.05) / 0.7);
    const e = easeInOutCubic(anim.t);
    camera.position.lerpVectors(anim.fromPos, anim.toPos, e);
    controls.target.lerpVectors(anim.fromTarget, anim.toTarget, e);
    controls.update();

    if (anim.t >= 1) animRef.current = null;
  });

  return null;
}

export default function Scene3D() {
  const {
    model,
    showFloor,
    showTerrain,
    terrainOpacity,
    terrainVerticalExaggeration,
    terrainData,
    showBoundingBox,
    visualProfessionalMode,
    sliceAxis,
    slicePosition,
  } = useAppStore();

  const hasElevationData = useAppStore((s) => s.hasElevationData);
  const blockModelElevationRange = useAppStore((s) => s.blockModelElevationRange);

  const elevationVisualState = useMemo((): ElevationVisualState => {
    if (!hasElevationData || !blockModelElevationRange) {
      return { enabled: false, refElev: 0, minVoxelY: null, maxVoxelY: null };
    }

    const minSurf = blockModelElevationRange.min_surface_elevation_masl;
    const maxSurf = blockModelElevationRange.max_surface_elevation_masl;
    const minVox = blockModelElevationRange.min_voxel_elevation_masl;
    const maxVox = blockModelElevationRange.max_voxel_elevation_masl;

    if (
      !Number.isFinite(minSurf) ||
      !Number.isFinite(maxSurf) ||
      !Number.isFinite(minVox) ||
      !Number.isFinite(maxVox)
    ) {
      return { enabled: false, refElev: 0, minVoxelY: null, maxVoxelY: null };
    }

    const refElev = ((minSurf as number) + (maxSurf as number)) / 2;

    return {
      enabled: true,
      refElev,
      minVoxelY: (minVox as number) - refElev,
      maxVoxelY: (maxVox as number) - refElev,
    };
  }, [hasElevationData, blockModelElevationRange]);

  const terrainRef = useRef<THREE.Mesh>(null);
  const orbitControlsRef = useRef<OrbitControlsImpl | null>(null);

  // Single pass over cells: avoids duplicating the O(n) bounds iteration.
  const modelBounds = useMemo((): ModelBounds | null => {
    if (!model?.cells?.length) return null;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;

    for (const c of model.cells as SceneCell[]) {
      const x = getCellNumber(c, ["x", "cx"], 0);
      const y = getVisualVoxelY(c, elevationVisualState.enabled, elevationVisualState.refElev);
      const z = getCellNumber(c, ["z", "cz"], 0);
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
      if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    }

    return { minX, maxX, minY, maxY, minZ, maxZ };
  }, [model, elevationVisualState]);

  const modelCenter = useMemo((): [number, number, number] => {
    if (!modelBounds) return [0, 0, 0];
    return [
      (modelBounds.minX + modelBounds.maxX) / 2,
      (modelBounds.minY + modelBounds.maxY) / 2,
      (modelBounds.minZ + modelBounds.maxZ) / 2,
    ];
  }, [modelBounds]);

  const sliceClippingPlanes = useMemo(
    (): THREE.Plane[] =>
      computeClippingPlanes(
        sliceAxis,
        slicePosition,
        modelBounds
      ),
    [sliceAxis, slicePosition, modelBounds]
  );
  const modelMaxExtent = model
    ? Math.max(
        model.domainL || 0,
        model.domainH || 0,
        model.domainW || 0,
        (model.cellSize || 10) * 10
      )
    : 600;
  const maxCameraDistance = Math.max(modelMaxExtent * 4, 600);
  const terrainRows = Math.max(
    2,
    Math.floor(safeNumber(terrainData?.metadata.dem_rows, 32))
  );
  const terrainCols = Math.max(
    2,
    Math.floor(safeNumber(terrainData?.metadata.dem_cols, 32))
  );
  const fallbackTerrainWidth = (model?.domainL || 200) * 1.3;
  const fallbackTerrainDepth = (model?.domainW || 200) * 1.3;
  const terrainWidth = Math.max(
    safeNumber(terrainData?.metadata.extent_x_m, fallbackTerrainWidth) ||
      fallbackTerrainWidth,
    fallbackTerrainWidth
  );
  const terrainDepth = Math.max(
    safeNumber(terrainData?.metadata.extent_z_m, fallbackTerrainDepth) ||
      fallbackTerrainDepth,
    fallbackTerrainDepth
  );
  const terrainSurfaceClearance = Math.max(
    safeNumber(model?.cellSize, 10) / 2,
    0.5
  );
  const terrainElevationDrop = useMemo(() => {
    const demMatrix = terrainData?.dem_matrix;

    if (!demMatrix || demMatrix.length === 0) return 0;

    let demMin = Infinity;
    let demMax = -Infinity;
    let demSum = 0;
    let demCount = 0;

    for (const row of demMatrix) {
      for (const value of row ?? []) {
        const elevation = safeNumber(value, 0);

        if (elevation < demMin) demMin = elevation;
        if (elevation > demMax) demMax = elevation;
        demSum += elevation;
        demCount++;
      }
    }

    if (demMax <= demMin || demCount === 0) return 0;

    const demMean = demSum / demCount;
    const terrainVerticalScale = (model?.domainH || 200) * terrainVerticalExaggeration;

    return ((demMean - demMin) / (demMax - demMin)) * terrainVerticalScale;
  }, [terrainData, model?.domainH, terrainVerticalExaggeration]);
  const terrainElevationRise = useMemo(() => {
    const demMatrix = terrainData?.dem_matrix;

    if (!demMatrix || demMatrix.length === 0) return 0;

    let demMin = Infinity;
    let demMax = -Infinity;
    let demSum = 0;
    let demCount = 0;

    for (const row of demMatrix) {
      for (const value of row ?? []) {
        const elevation = safeNumber(value, 0);

        if (elevation < demMin) demMin = elevation;
        if (elevation > demMax) demMax = elevation;
        demSum += elevation;
        demCount++;
      }
    }

    if (demMax <= demMin || demCount === 0) return 0;

    const demMean = demSum / demCount;
    const terrainVerticalScale = (model?.domainH || 200) * terrainVerticalExaggeration;

    return ((demMax - demMean) / (demMax - demMin)) * terrainVerticalScale;
  }, [terrainData, model?.domainH, terrainVerticalExaggeration]);
  const terrainTextureUrl = useMemo(() => {
    const rawTextureUrl = terrainData?.texture_url?.trim();

    return rawTextureUrl ? buildTerrainTextureProxyUrl(rawTextureUrl) : "";
  }, [terrainData?.texture_url]);

  useEffect(() => {
    if (!terrainRef.current || !terrainData || terrainData.dem_matrix.length === 0) {
      return;
    }

    const geometry = terrainRef.current.geometry as THREE.BufferGeometry;
    const position = geometry.attributes.position as THREE.BufferAttribute;
    const { dem_matrix: demMatrix, metadata } = terrainData;
    const rows = Math.floor(safeNumber(metadata.dem_rows, 0));
    const cols = Math.floor(safeNumber(metadata.dem_cols, 0));

    if (rows <= 0 || cols <= 0 || position.count < rows * cols) return;

    let demMin = Infinity;
    let demMax = -Infinity;
    let demSum = 0;
    let demCount = 0;

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const elevation = safeNumber(demMatrix[row]?.[col], 0);

        if (elevation < demMin) demMin = elevation;
        if (elevation > demMax) demMax = elevation;
        demSum += elevation;
        demCount++;
      }
    }

    const demRange = demMax > demMin ? demMax - demMin : 1;
    const demMean = demCount > 0 ? demSum / demCount : (demMin + demMax) / 2;
    const domainH = model?.domainH || 200;

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const idx = row * cols + col;
        const elevation = safeNumber(demMatrix[row]?.[col], 0);
        const scaledElevation =
          ((elevation - demMean) / demRange) *
          domainH *
          terrainVerticalExaggeration;

        position.setZ(idx, scaledElevation);
      }
    }

    position.needsUpdate = true;
    geometry.computeVertexNormals();
  }, [terrainData, model?.domainH, terrainRows, terrainCols, terrainVerticalExaggeration]);

  // ─── Keyboard Zoom Control (ArrowUp = zoom in, ArrowDown = zoom out) ────
  useEffect(() => {
    const ZOOM_STEP = 0.9; // factor por tecla; 0.9 = 10% más cerca

    const handleKeyDown = (e: KeyboardEvent) => {
      const ctrl = orbitControlsRef.current;
      if (!ctrl) return;

      if (e.key === 'ArrowUp') {
        ctrl.dollyIn(1 / ZOOM_STEP);   // acercar
        ctrl.update();
        e.preventDefault();
      } else if (e.key === 'ArrowDown') {
        ctrl.dollyOut(1 / ZOOM_STEP);  // alejar
        ctrl.update();
        e.preventDefault();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const terrainLocalY =
    elevationVisualState.enabled && Number.isFinite(elevationVisualState.maxVoxelY)
      ? (elevationVisualState.maxVoxelY as number) + terrainSurfaceClearance + terrainElevationDrop
      : modelCenter[1] + (model?.domainH || 200) / 2 + terrainSurfaceClearance + terrainElevationDrop;
  const elevatedSceneTargetY =
    elevationVisualState.enabled &&
    Number.isFinite(elevationVisualState.minVoxelY)
      ? (
          (elevationVisualState.minVoxelY as number) +
          terrainLocalY +
          terrainElevationRise
        ) / 2 - modelCenter[1]
      : 0;

  const cameraHomeTarget = useMemo<[number, number, number]>(
    () => [0, showTerrain && terrainData ? elevatedSceneTargetY : 0, 0],
    [showTerrain, terrainData, elevatedSceneTargetY]
  );

  return (
    <>
      <ambientLight intensity={0.35} />
      <hemisphereLight args={["#aebfd0", "#0a0d12", 0.4]} />
      <pointLight position={[100, 200, 100]} intensity={1.5} castShadow />
      <directionalLight position={[-50, 100, -50]} intensity={1} castShadow />

      <Environment preset="night" environmentIntensity={0.55} />

      <OrbitControls
        ref={orbitControlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.05}
        target={cameraHomeTarget}
        minDistance={1}
        maxDistance={maxCameraDistance}
      />
      <CameraRig controlsRef={orbitControlsRef} homeTarget={cameraHomeTarget} />

      <group position={[-modelCenter[0], -modelCenter[1], -modelCenter[2]]}>
        <group>
          <group>
            <HostVolume
              modelCenter={modelCenter}
            />
            <MineralComplex
              elevationVisualState={elevationVisualState}
              clippingPlanes={sliceClippingPlanes}
            />
            <AnomalyEnvelope
              elevationVisualState={elevationVisualState}
              clippingPlanes={sliceClippingPlanes}
            />
            <SlicePlane modelBounds={modelBounds} modelCenter={modelCenter} />
            <VoxelInspector />

            {model && (
              <>
                {showBoundingBox && (
                  <mesh position={[modelCenter[0], modelCenter[1], modelCenter[2]]}>
                    <boxGeometry
                      args={[
                        model.domainL || 200,
                        model.domainH || 200,
                        model.domainW || 200,
                      ]}
                    />
                    <meshBasicMaterial
                      color="#4ade80"
                      wireframe
                      transparent
                      opacity={0.35}
                      clippingPlanes={[]}
                    />
                  </mesh>
                )}

                <axesHelper
                  args={[modelMaxExtent * 0.18]}
                  position={[
                    modelCenter[0] - (model.domainL || 200) / 2,
                    modelCenter[1] - (model.domainH || 200) / 2,
                    modelCenter[2] - (model.domainW || 200) / 2,
                  ]}
                />

                <Grid
                  infiniteGrid
                  fadeDistance={Math.max(modelMaxExtent * 2, 300)}
                  sectionSize={Math.max(modelMaxExtent / 10, 50)}
                  cellSize={Math.max(modelMaxExtent / 50, 10)}
                  sectionColor="#1e293b"
                  cellColor="#0f172a"
                  position={[0, (model.domainH || 200) / 2, 0]}
                />

              </>
            )}
          </group>
        </group>

        {showTerrain && terrainData && model && (
          <mesh
            ref={terrainRef}
            rotation={[-Math.PI / 2, 0, 0]}
            position={[
              modelCenter[0],
              terrainLocalY,
              modelCenter[2],
            ]}
            receiveShadow
          >
            <planeGeometry
              key={`terrain-${terrainCols}-${terrainRows}-${terrainWidth}-${terrainDepth}`}
              args={[
                terrainWidth,
                terrainDepth,
                terrainCols - 1,
                terrainRows - 1,
              ]}
            />
            {terrainTextureUrl ? (
              <TerrainTexturedMaterial
                key={terrainTextureUrl}
                textureUrl={terrainTextureUrl}
                opacity={visualProfessionalMode ? Math.max(terrainOpacity, 0.75) : terrainOpacity}
              />
            ) : (
              <FallbackTerrainMaterial opacity={visualProfessionalMode ? Math.max(terrainOpacity, 0.75) : terrainOpacity} />
            )}
          </mesh>
        )}
      </group>

      <mesh position={[0, -100, 0]} receiveShadow visible={showFloor}>
        <boxGeometry args={[1000, 5, 1000]} />
        <meshStandardMaterial color="#0a0a0a" roughness={0.9} clippingPlanes={[]} />
      </mesh>

      <ContactShadows
        position={[0, -97, 0]}
        opacity={0.6}
        scale={500}
        blur={2.5}
        far={10}
      />

      <PostFX />
    </>
  );
}
