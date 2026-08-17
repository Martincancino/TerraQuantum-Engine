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
  getGeophysicsStatus,
  cancelGeophysicsRun,
  type InversionBudget,
} from "./frontendApi";
import { isJsonObject, readStringField, readNumberField } from "../../componentes/datos/helpers";
import type { VoxelData } from "../terraQuantumGeology";
import { useAppStore } from "../../store/useAppStore";

type JsonObject = Record<string, unknown>;
// FASE 10: `BackendVoxelModel` estaba declarado 4 veces con 3 formas distintas.
// Vive una sola vez, en `componentes/datos/types.ts`, derivado del contrato.
import type { BackendVoxelModel } from "../../componentes/datos/types";

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
  | { ok: false; error: string; cancelled?: boolean };

// F3 — progreso reportado a la UI durante el polling (datos del backend tal cual).
export type PackageProgress = {
  status: string;
  stage: string | null;
  progress: number | null;   // 0..1 del backend
  message: string | null;
  budget: InversionBudget | null;
  projectId: string;
  runId: string;
};

export type LoadModelHooks = {
  onProgress?: (p: PackageProgress) => void;
  /** La UI lo pone en true para cancelar; aquí se llama al endpoint de cancel. */
  shouldCancel?: () => boolean;
  /** Panel desmontado: detener el POLLING sin cancelar la corrida del backend
   * (sigue en segundo plano y aparece en Historial) y sin tocar más el store. */
  shouldAbandon?: () => boolean;
};

const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["done", "error", "cancelled", "interrumpida"]);

function _sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

/**
 * Sube el paquete al backend y carga el block model resultante en el visor.
 *
 * F3: load-package ENCOLA (worker de proceso) y devuelve {status:"queued"} de
 * inmediato; aquí se POLLEA GET /geophysics-status (1.5 s) mostrando etapas
 * reales del solver hasta done/error/cancelled — nunca más un proxy colgado
 * 20 minutos. `hooks.onProgress` alimenta la barra de la UI; si
 * `hooks.shouldCancel()` devuelve true se llama al endpoint de cancelación.
 * Maneja directamente el store (activeRun, model, viewMode, show3D, view).
 */
export async function loadModelFromPackage(
  file: File,
  displayResolutionFactor = 1,
  hooks: LoadModelHooks = {},
): Promise<LoadModelFromPackageResult> {
  const store = useAppStore.getState();

  const res = await loadPackage(file);
  if (!res.ok || !res.data) {
    store.setActiveRun({ source: "csv", status: "error", error: res.error ?? "Error al cargar el paquete." });
    return { ok: false, error: res.error ?? "Error al cargar el paquete." };
  }

  const { project_id: projectId, run_id: runId, route } = res.data;
  if (!projectId || !runId) {
    const msg = (res.data.errors && res.data.errors[0]) || "El backend no devolvió project_id/run_id.";
    store.setActiveRun({ source: "csv", status: "error", error: msg });
    return { ok: false, error: msg };
  }

  const budget = res.data.budget ?? null;

  // ── F3: corrida ENCOLADA → poll de estado con progreso real ────────────────
  if (res.data.status === "queued") {
    store.setActiveRun({ projectId, runId, source: "csv", status: "loading", error: null });
    hooks.onProgress?.({
      status: "queued", stage: "queued", progress: 0,
      message: "Inversión en cola de procesamiento.", budget, projectId, runId,
    });

    let finalStatus = "";
    // Tope de fallos CONSECUTIVOS del endpoint de status (~90 s sin señal):
    // sin esto el loop reintentaría eternamente ante un backend caído.
    let consecutiveFailures = 0;
    const MAX_CONSECUTIVE_FAILURES = 60;
    for (;;) {
      if (hooks.shouldAbandon?.()) {
        // La corrida SIGUE en el backend; su estado queda en el Historial.
        return {
          ok: false,
          error: "Panel cerrado: la corrida continúa en segundo plano (ver Historial).",
          cancelled: false,
        };
      }
      if (hooks.shouldCancel?.()) {
        await cancelGeophysicsRun(projectId, runId);
        store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: "Corrida cancelada por el usuario." });
        return { ok: false, error: "Corrida cancelada por el usuario.", cancelled: true };
      }
      const st = await getGeophysicsStatus(projectId, runId);
      if (!st.ok || !st.data) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
          const msg =
            "Sin respuesta del estado de la corrida (~90 s). La inversión puede " +
            "seguir en el backend: revisa el Historial cuando vuelva la conexión.";
          store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: msg });
          return { ok: false, error: msg };
        }
      } else {
        consecutiveFailures = 0;
      }
      if (st.ok && st.data) {
        const s = st.data;
        hooks.onProgress?.({
          status: s.status,
          stage: s.stage ?? null,
          progress: typeof s.progress === "number" ? s.progress : null,
          message: s.message ?? null,
          budget, projectId, runId,
        });
        if (TERMINAL_STATUSES.has(s.status)) {
          finalStatus = s.status;
          if (s.status !== "done") {
            const msg = s.error || s.message ||
              (s.status === "cancelled" ? "Corrida cancelada." : "La inversión del paquete no finalizó.");
            store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: msg });
            return { ok: false, error: msg, cancelled: s.status === "cancelled" };
          }
          break;
        }
      }
      // Errores transitorios de red/poll: se reintenta en el siguiente tick.
      await _sleep(POLL_INTERVAL_MS);
    }
    if (finalStatus !== "done") {
      const msg = "La inversión del paquete no finalizó.";
      store.setActiveRun({ projectId, runId, source: "csv", status: "error", error: msg });
      return { ok: false, error: msg };
    }
  } else if (res.data.status !== "done") {
    // Modo síncrono histórico con fallo inline.
    const msg = (res.data.errors && res.data.errors[0]) || "La inversión del paquete no finalizó.";
    store.setActiveRun({ source: "csv", status: "error", error: msg });
    return { ok: false, error: msg };
  }

  // Panel cerrado mientras terminaba: no secuestrar el visor con setModel/
  // setView — el modelo queda persistido y se re-abre desde Historial.
  if (hooks.shouldAbandon?.()) {
    return {
      ok: false,
      error: "Panel cerrado: el modelo quedó persistido (ver Historial).",
      cancelled: false,
    };
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
