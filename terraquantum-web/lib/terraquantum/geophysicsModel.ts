import { VoxelMineralModel } from "../terraQuantumGeology";
import { GravityObservation } from "./geophysicsSurvey";

// DEMO ONLY — densidades de referencia para pórfidos cupríferos (norte de Chile).
// El backend debe proveer estos valores si el contexto litológico cambia.
const DENSITY_HOST_ROCK_T_M3 = 2.6;  // roca encajante típica (granodiorita/diorita)
const DENSITY_ORE_BODY_T_M3 = 4.2;   // límite superior esperado para Cu de alta ley

// Tipo para un voxel geofísico proveniente del backend
export interface GeoVoxel {
  cx?: number; x?: number;
  cy?: number; y?: number;
  cz?: number; z?: number;
  density?: number;
  rho?: number;
  probability?: number;
  visual_score?: number;
  sensitivity_proxy?: number;
  density_proxy_index?: number;
  modeled_rock_mass_tonnes?: number;
  density_zone_flag?: number;
  is_demo_grade?: boolean;
  provenance?: { grade_source: string; assay_supported: boolean; economically_validated: boolean };
  [key: string]: number | boolean | { grade_source: string; assay_supported: boolean; economically_validated: boolean } | undefined;
}

// Tipo para un punto del perfil de perforación
export interface DrillProfileEntry {
  depth: number;
  density: number;
}

export type BackendInvertResponse = {
  voxels: GeoVoxel[];
  best_target: {
    x_m: number;
    y_m: number;
    z_m: number;
    density: number;
    density_proxy_index: number;
    is_demo_grade: boolean;
    provenance: { grade_source: string; assay_supported: boolean; economically_validated: boolean };
    probability: number;
    // B1 (null-space honesto): blanco resoluble + transparencia del artefacto de piso.
    depth_m?: number;
    is_resolvable_depth?: boolean | null;
    confidence_level?: string;          // capado por el veredicto reconciliado (B3)
    is_null_space_artifact?: boolean;
    n_floor_saturated_cells?: number;
    anomaly_magnitude?: number;
    floor_saturated_demoted?: {
      x_m: number; y_m: number; z_m: number; density: number; depth_m: number; reason: string;
    } | null;
    selection_note?: string;
  } | null;
  report: {
    status: string;
    priority_class?: string;
    // B3 — veredicto único reconciliado (eslabón más débil).
    overall_verdict?: {
      level: string;
      limiting_factors?: string[];
      components?: Record<string, unknown>;
      headline?: string;
      recommended_action?: string;
    };
    // B2 — resolución de profundidad por-eje (cola null-space; sin posterior σ).
    depthResolution?: {
      computed: boolean;
      resolvable_depth_max_m?: number;
      resolvable_depth_horizon_method?: string;
      geometric_observable_depth_max_m?: number;
      resolvable_body_depth_m?: number | null;
      deep_mass_fraction?: number;
      horizontal_extent_m?: number | null;
      per_axis?: {
        horizontal?: { determined: boolean; compactness: string; extent_m: number | null };
        vertical?: { quality: string; deep_mass_fraction: number };
      };
      statement?: string;
    };
    preliminary_signal?: string;
    risk_level: string;
    min_density?: number;
    avg_density?: number;
    max_density?: number;
    estimated_total_tonnage?: number;
    estimated_anomaly_tonnage?: number;
    avg_grade?: number;
    avg_density_proxy_index?: number;
    is_demo_grade?: boolean;
    provenance?: { grade_source: string; assay_supported: boolean; economically_validated: boolean };
    anomaly_score?: number;
    max_probability?: number;
    cutoff_density?: number;
    total_voxels?: number;
    returned_voxels?: number;
    parquet_path?: string;
  };
};

// Helper para leer un número de una celda con clave dinámica
function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  return value as Record<string, unknown>;
}

function numFrom(cell: unknown, ...keys: string[]): number {
  const record = asRecord(cell);
  if (!record) return 0;

  for (const k of keys) {
    const v = record[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return 0;
}

function numFromWithFallback(cell: unknown, fallback: number, ...keys: string[]): number {
  const record = asRecord(cell);
  if (!record) return fallback;

  for (const k of keys) {
    const v = record[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }

  return fallback;
}

function probabilityFrom(cell: unknown): number {
  return numFromWithFallback(cell, 1, "probability");
}

export function mapPriorityClassLabel(value: string | null | undefined): string {
  const v = String(value || "").toUpperCase().trim();
  if (v === "HIGH_RELATIVE_PRIORITY" || v === "DRILL") return "Prioridad relativa alta";
  if (v === "MEDIUM_RELATIVE_PRIORITY" || v === "OBSERVE" || v === "WAIT") return "Prioridad relativa media";
  if (v === "LOW_RELATIVE_PRIORITY") return "Prioridad relativa baja";
  if (v === "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE" || v === "UNCLASSIFIED") return "Sin clasificar — confianza insuficiente";
  return v || "N/A";
}

export function mapReliabilityLabel(value: string): string {
  const v = String(value || "").toUpperCase();
  if (v === "HIGH") return "Confiabilidad técnica alta";
  if (v === "MEDIUM") return "Confiabilidad técnica media";
  return "Confiabilidad técnica baja";
}

export function clamp01(value: number) {
  return Math.max(0, Math.min(1, value));
}

export function buildGridConfig(inputDepth: number) {
  const blockSize = 10;

  const nx = 8;
  const nz = 8;
  const ny = Math.max(4, Math.ceil(Number(inputDepth) / blockSize));

  return {
    nx,
    ny,
    nz,
    block_size: blockSize,
    cutoff_radius: Math.max(120, Number(inputDepth) * 2),
    lambda_mag: 0.00005,
    alpha_spatial: 1.5,
  };
}

export function buildGeophysicsPayload(args: {
  inputDepth: number;
  inputNIR: number;
  inputFe: number;
  region: string;
  geoLat: string;
  geoLon: string;
  observations: GravityObservation[];
}) {
  const gridConfig = buildGridConfig(Number(args.inputDepth));

  return {
    depth: Number(args.inputDepth),
    nir: Number(args.inputNIR),
    fe: Number(args.inputFe),
    region: args.region,
    lat: args.geoLat,
    lon: args.geoLon,
    nx: gridConfig.nx,
    ny: gridConfig.ny,
    nz: gridConfig.nz,
    block_size: gridConfig.block_size,
    cutoff_radius: gridConfig.cutoff_radius,
    lambda_mag: gridConfig.lambda_mag,
    alpha_spatial: gridConfig.alpha_spatial,
    observations: args.observations,
  };
}

export function buildReportForFrontend(
  backend: BackendInvertResponse,
  blockModel: VoxelMineralModel,
  inputDepth: number,
  inputGrav: number,
  inputNIR: number,
  inputFe: number,
  geoRegionName: string,
  geologistNote: string
) {
  const r = backend.report;
  const best = backend.best_target;

  const maxDensity = r.max_density ?? 0;
  const avgDensity = r.avg_density ?? 0;
  const minDensity = r.min_density ?? 0;
  const maxProbability = r.max_probability ?? r.anomaly_score ?? 0;
  const anomalyPct = clamp01(maxProbability) * 100;

  const estimatedTotalTonnage = r.estimated_total_tonnage ?? 0;
  const estimatedAnomalyTonnage = r.estimated_anomaly_tonnage ?? 0;

  const priorityClass =
    r.priority_class || "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE";

  const clasificacion =
    priorityClass === "HIGH_RELATIVE_PRIORITY"
      ? "Anomalía gravimétrica de alta intensidad relativa"
      : "Respuesta geofísica bajo umbral de corte";

  const estado = priorityClass;

  const targetDepth = best ? Math.round(best.y_m) : inputDepth;

  return {
    profundidad: targetDepth,
    masaKg: estimatedTotalTonnage * 1000,
    anomaliaPico: Number(maxDensity.toFixed(3)),
    clasificacionEstructural: clasificacion,
    contrasteDensidad: `Min ${minDensity.toFixed(3)} | Avg ${avgDensity.toFixed(
      3
    )} | Max ${maxDensity.toFixed(3)} t/m3`,
    leyPromedio: `Índice: ${(r.avg_grade ?? 0).toFixed(3)} (Heurística exploración — no ley medida)`,
    indiceAnomalia: anomalyPct.toFixed(1),
    zonaGeografica: geoRegionName || "Norte Chile",
    firmaSuperficial: `NIR ${inputNIR}% | Fe ${inputFe}%`,
    notasTerreno: geologistNote.length > 0 ? "Sí" : "No",
    priorityClass,
    recomendacionPerforacion: false,
    rankingTargets: [
      {
        id: "Target Alpha",
        probabilidad: Number(anomalyPct.toFixed(1)),
        profundidad: targetDepth,
        coordenadas: best
          ? `X ${best.x_m.toFixed(1)} | Y ${best.y_m.toFixed(
              1
            )} | Z ${best.z_m.toFixed(1)}`
          : "Sin target principal",
        estado,
      },
    ],
    justificacion: `Inversión gravimétrica real LSQR + Tikhonov. Total voxels: ${
      r.total_voxels ?? blockModel.cells.length
    }. Voxels sobre cutoff: ${r.returned_voxels ?? 0}.`,
    score: clamp01(maxProbability),
    uncertainty: 1 - clamp01(maxProbability),
    backendReport: r,
    estimatedAnomalyTonnage,
    rawBestTarget: best,
    inputGrav,
  };
}

export function buildHeatmapFromBlockModel(
  model: VoxelMineralModel,
  geoLat: string,
  geoLon: string
) {
  const lat = Number.parseFloat(geoLat);
  const lon = Number.parseFloat(geoLon);

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return [];

  const ranked = [...model.cells]
    .sort((a, b) => {
      const aScore =
        (numFrom(a, "density", "rho") - DENSITY_HOST_ROCK_T_M3) * probabilityFrom(a);
      const bScore =
        (numFrom(b, "density", "rho") - DENSITY_HOST_ROCK_T_M3) * probabilityFrom(b);

      return bScore - aScore;
    })
    .slice(0, 10);

  return ranked.map((cell) => {
    const normalizedX = (cell.cx ?? 0) / Math.max(model.domainL, 1);
    const normalizedZ = (cell.cz ?? 0) / Math.max(model.domainW, 1);

    const density = numFromWithFallback(cell, 2.6, "density", "rho");
    const probability = probabilityFrom(cell);
    const value = clamp01(((density - DENSITY_HOST_ROCK_T_M3) / (DENSITY_ORE_BODY_T_M3 - DENSITY_HOST_ROCK_T_M3)) * probability);

    return {
      x: lat + normalizedX * 0.02,
      y: lon + normalizedZ * 0.02,
      value,
      density,
      probability,
    };
  });
}
