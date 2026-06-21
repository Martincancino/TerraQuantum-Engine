// ─── Fase R4 (frontend) — Cargar modelo 3D desde el paquete (backend-driven) ──
//
// El paquete CSV auto-contenido lo ENSAMBLA y LEE el backend (formato canónico).
// Aquí solo: (1) subimos el archivo del paquete a /load-package (el backend rutea
// al solver correcto grav/mag/joint/+sondajes y persiste el block model), y
// (2) cargamos ese block model en el visor (store global). No hay física ni
// construcción de payload en el cliente: eso vivía en el camino antiguo (JSON
// del lado del cliente) y se retiró al converger en el formato del backend.

import {
  loadPackage,
  getExplorationBlockModelForRunWithArrow,
} from "./frontendApi";
import { isJsonObject, readStringField, readNumberField } from "../../componentes/datos/helpers";
import type { VoxelMineralModel, VoxelData } from "../terraQuantumGeology";
import { useAppStore } from "../../store/useAppStore";

type JsonObject = Record<string, unknown>;
type BackendVoxelModel = VoxelMineralModel & { visualMode?: string };

// ─── Parsing del block model del backend (shape, no física) ──────────────────

function readArrayProperty(value: unknown, key: string): unknown[] {
  const obj = isJsonObject(value) ? value : null;
  const field = obj?.[key];
  return Array.isArray(field) ? field : [];
}

function readNumberProperty(value: unknown, key: string, fallback = 0): number {
  const obj = isJsonObject(value) ? value : null;
  const n = readNumberField(obj?.[key]);
  return n ?? fallback;
}

function readStringProperty(value: unknown, key: string): string | undefined {
  const obj = isJsonObject(value) ? value : null;
  return readStringField(obj?.[key]) ?? undefined;
}

function readObjectProperty(value: unknown, key: string): JsonObject | undefined {
  const obj = isJsonObject(value) ? value : null;
  const field = obj?.[key];
  return isJsonObject(field) ? field : undefined;
}

function readStringArrayProperty(value: unknown, key: string): string[] {
  return readArrayProperty(value, key).filter(
    (item): item is string => typeof item === "string"
  );
}

function readBlockModelVisualMeta(value: unknown): Partial<BackendVoxelModel> {
  const obj = isJsonObject(value) ? value : null;
  if (!obj) return {};

  const densityMin = readNumberProperty(obj, "densityMin", Number.NaN);
  const densityMax = readNumberProperty(obj, "densityMax", Number.NaN);
  const scoreStats = readObjectProperty(obj, "scoreStats") as BackendVoxelModel["scoreStats"];
  const visualScoreStats = readObjectProperty(obj, "visualScoreStats") as BackendVoxelModel["visualScoreStats"];
  const densityStats = readObjectProperty(obj, "densityStats") as BackendVoxelModel["densityStats"];
  const rhoStats = readObjectProperty(obj, "rhoStats") as BackendVoxelModel["rhoStats"];
  const probabilityStats = readObjectProperty(obj, "probabilityStats") as BackendVoxelModel["probabilityStats"];
  const returnedScoreStats = readObjectProperty(obj, "returnedScoreStats") as BackendVoxelModel["returnedScoreStats"];
  const diagnosticStats = readObjectProperty(obj, "diagnosticStats") as BackendVoxelModel["diagnosticStats"];
  const returnedDiagnosticStats = readObjectProperty(obj, "returnedDiagnosticStats") as BackendVoxelModel["returnedDiagnosticStats"];
  const warnings = readStringArrayProperty(obj, "warnings");
  const isDegenerate = obj.isDegenerate === true || obj.is_degenerate === true;

  return {
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

function isVoxelData(value: unknown): value is VoxelData {
  return isJsonObject(value);
}

function buildVoxelModelFromBackend(data: unknown): BackendVoxelModel | null {
  const obj = isJsonObject(data) ? data : null;
  if (!obj) return null;

  const parsedCells = readArrayProperty(obj, "cells").filter(isVoxelData);
  if (parsedCells.length === 0) return null;

  const domainL = readNumberProperty(obj, "domainL");
  const domainH = readNumberProperty(obj, "domainH");
  const domainW = readNumberProperty(obj, "domainW");
  const cellSize = readNumberProperty(obj, "cellSize", 10);
  const visualMode = readStringProperty(obj, "visualMode");

  return {
    domainL,
    domainH,
    domainW,
    cellSize,
    cells: parsedCells,
    volumeM3: domainL * domainH * domainW,
    ...(visualMode ? { visualMode } : {}),
    ...readBlockModelVisualMeta(obj),
  };
}

export type LoadModelFromPackageResult =
  | { ok: true; route: string | null }
  | { ok: false; error: string };

/**
 * Sube el paquete al backend (que invierte y persiste) y carga el block model
 * resultante en el visor. Maneja directamente el store (activeRun, model,
 * viewMode, show3D, view). Devuelve el resultado para que la UI muestre errores.
 */
export async function loadModelFromPackage(
  file: File,
  displayResolutionFactor = 1,
): Promise<LoadModelFromPackageResult> {
  const store = useAppStore.getState();

  const res = await loadPackage(file);
  if (!res.ok || !res.data) {
    store.setActiveRun({ source: "csv", status: "error", error: res.error ?? "Error al cargar el paquete." });
    return { ok: false, error: res.error ?? "Error al cargar el paquete." };
  }

  const { project_id: projectId, run_id: runId, route } = res.data;
  if (res.data.status !== "done" || !projectId || !runId) {
    const msg = (res.data.errors && res.data.errors[0]) || "La inversión del paquete no finalizó.";
    store.setActiveRun({ source: "csv", status: "error", error: msg });
    return { ok: false, error: msg };
  }

  const isMagnetic = (route ?? "").includes("magnetic_only");

  store.setActiveRun({
    projectId, runId, source: "csv", status: "loading", error: null,
  });

  const blockRes = await getExplorationBlockModelForRunWithArrow(
    projectId, runId, "exploration", 5000, displayResolutionFactor,
  );
  if (!blockRes.ok || !blockRes.data) {
    const msg = "No se pudo cargar el modelo 3D del paquete invertido.";
    store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: msg });
    return { ok: false, error: msg };
  }

  const backendModel = buildVoxelModelFromBackend(blockRes.data);
  if (!backendModel) {
    const msg = "El modelo devuelto no tiene celdas válidas.";
    store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: msg });
    return { ok: false, error: msg };
  }

  store.setModel(backendModel);
  store.setViewMode(isMagnetic ? "susceptibility" : "density");
  store.setShow3D(true);
  store.setView("figura 3d");
  store.setActiveRun({ projectId, runId, source: "csv", status: "ready", error: null });

  return { ok: true, route: route ?? null };
}
