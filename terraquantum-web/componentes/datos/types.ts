import type { VoxelMineralModel } from "../../lib/terraQuantumGeology";
import type { JsonValue } from "../../lib/terraquantum/frontendApi";
import type { BlockModelResponse } from "../../types/backend-contracts.generated";

export type { JsonValue };

export type RunFiles = {
  block_model: boolean;
  inputs: boolean;
  observations: boolean;
  report: boolean;
  metrics: boolean;
  schedule: boolean;
};

export type StoredRun = {
  runId: string;
  exists: boolean;
  files: RunFiles;
};

export type StoredProject = {
  projectId: string;
  runs: StoredRun[];
};

export type ProjectRunsViewData = {
  totalProjects: number;
  totalRuns: number;
  projects: StoredProject[];
};

/** El modelo 3D tal como lo deja el backend, listo para el visor.
 *
 *  FASE 10 — este tipo estaba declarado **cuatro veces** (aquí, en `PrepPanel`,
 *  en `Exploration3DView` y en `packageInversion`) y las cuatro no coincidían:
 *  tres decían `VoxelMineralModel & { visualMode? }` y la cuarta añadía
 *  `densityMin`, `densityMax` y `mode`. Cuatro nombres iguales, cuatro formas
 *  distintas, y el compilador tan contento: el caso exacto de H-16.
 *
 *  Ahora vive una sola vez y los campos que vienen del backend se toman del
 *  contrato generado, así que no pueden derivar de lo que emite `/block-model`.
 *  `VoxelMineralModel` sigue siendo del frontend: es lo que el visor necesita
 *  para pintar, no lo que el motor calcula. */
export type BackendVoxelModel = VoxelMineralModel &
  Partial<Pick<BlockModelResponse, "visualMode" | "densityMin" | "densityMax" | "mode">>;

export type JsonObject = { [key: string]: JsonValue };

// ─── Tipos Fase 4.5 ───────────────────────────────────────────────────────────
export type ResidualPoint = {
  sensor_index?: number;
  x_m?: number;
  y_m?: number;
  z_m?: number;
  observed?: number;
  modeled?: number;
  residual?: number;
  abs_residual?: number;
  normalized_residual?: number;
  residual_level?: string;
};

export type TechnicalSummary = {
  overall_level?: string;
  survey_level?: string;
  fit_level?: string;
  residual_level?: string;
  summary?: string;
  key_findings?: string[];
  warnings?: string[];
  recommended_next_steps?: string[];
};

export type UncertaintyDiagnostics = {
  uncertainty_level?: string;
  uncertainty_score?: number;
  drivers?: string[];
  interpretation?: string;
  recommended_action?: string;
};

export type SensorFlaggedPoint = {
  sensor_index?: number;
  x_m?: number;
  y_m?: number;
  z_m?: number;
  residual?: number;
  abs_residual?: number;
  normalized_residual?: number;
  residual_level?: string;
  flags?: string[];
  review_priority?: string;
};

export type SensorQualityFlags = {
  sensor_count?: number;
  flagged_count?: number;
  flagged_ratio?: number;
  flag_level?: string;
  flagged_sensors?: SensorFlaggedPoint[];
  summary?: string;
  recommended_action?: string;
};

export type FitDiagnostics = {
  fit_level?: string;
  fit_quality?: number;
  residual_rmse?: number;
  residual_mae?: number;
  residual_bias?: number;
  normalized_rmse?: number;
  residual_l2?: number;
  residualMap?: ResidualPoint[] | null;
};

export type ObservationQuality = {
  quality_level?: string;
  quality_score?: number;
  observation_count?: number;
  coverage_ratio_x?: number;
  coverage_ratio_z?: number;
  signal_dynamic_range?: number;
  g_std?: number;
  warnings?: string[];
};

export type ProjectRunDetail = {
  projectId: string;
  runId: string;
  files: Partial<RunFiles>;
  inputs: JsonObject | null;
  report: JsonObject | null;
  metrics: JsonObject | null;
  schedule: JsonObject[];
  observations?: JsonObject[];
};

export type SelectedRun = {
  projectId: string;
  runId: string;
};

export type CompareResult = {
  baseProjectId: string;
  baseRunId: string;
  compareProjectId: string;
  compareRunId: string;
  deltas: Record<string, JsonValue | undefined>;
};
