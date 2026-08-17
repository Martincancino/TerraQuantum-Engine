"use client";
import { useEffect, useState, useCallback, useReducer } from "react";
import { useAppStore } from "../../store/useAppStore";
import {
  compareRuns,
  deleteRun,
  exportBundleUrl,
  fetchProjectFootprint,
  getExplorationBlockModelForRun,
  getProjectRunDetail,
  getProjectRuns,
} from "../../lib/terraquantum/frontendApi";
import type {
  ProjectRunsViewData,
  ProjectRunDetail,
  SelectedRun,
  CompareResult,
} from "../datos/types";
import {
  asRecord,
  fmtNum,
  fmtSci,
  levelCls,
  parseProjectRuns,
  parseProjectRunDetail,
  parseBlockModel,
  parseCompareResult,
  buildRunKey,
  hasRunFiles,
  projectRunFileLabels,
} from "../datos/helpers";
import RunComparePanel from "../datos/RunComparePanel";
import RunDiagnosticsPanel from "../datos/RunDiagnosticsPanel";

// ─── F3: panel de estado de corridas (historial SQLite del backend) ──────────
// Display-only: lista las corridas registradas con su estado REAL persistente
// (queued/running/done/error/cancelled/interrumpida) — sobrevive reinicios del
// backend. Los detalles y la re-apertura de modelos siguen en la lista de
// proyectos de abajo (escaneo de disco); esto agrega el ESTADO que esa lista
// no conoce (p.ej. una corrida interrumpida a mitad de inversión).
const HISTORY_STATUS_META: Record<string, { label: string; cls: string }> = {
  done: { label: "Completada", cls: "text-green-400 border-green-600/40 bg-green-900/20" },
  running: { label: "En curso", cls: "text-sky-400 border-sky-600/40 bg-sky-900/20" },
  queued: { label: "En cola", cls: "text-neutral-300 border-neutral-600/40 bg-neutral-800/40" },
  error: { label: "Error", cls: "text-red-400 border-red-600/40 bg-red-900/20" },
  cancelled: { label: "Cancelada", cls: "text-amber-400 border-amber-600/40 bg-amber-900/20" },
  interrumpida: { label: "Interrumpida", cls: "text-orange-400 border-orange-600/40 bg-orange-900/20" },
};

function HistoryStatusPanel() {
  const [runs, setRuns] = useState<import("../../lib/terraquantum/frontendApi").HistoryRun[]>([]);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    import("../../lib/terraquantum/frontendApi").then(({ getHistoryRuns }) =>
      getHistoryRuns().then((res) => {
        if (!cancelled && res.ok && res.data) setRuns(res.data.runs);
      })
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (runs.length === 0) return null;
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950/50 px-4 py-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between text-left"
      >
        <span className="text-[9px] uppercase tracking-widest text-neutral-500 font-bold">
          Estado de corridas · {runs.length} registradas
        </span>
        <span className="text-[9px] text-neutral-600">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1">
          {runs.slice(0, 12).map((r) => {
            const meta = HISTORY_STATUS_META[r.status] ?? {
              label: r.status, cls: "text-neutral-400 border-neutral-700 bg-neutral-900",
            };
            return (
              <li
                key={`${r.project_id}/${r.run_id}`}
                className="flex items-center gap-2 text-[9px] font-mono text-neutral-400"
              >
                <span className={`px-1.5 py-0.5 rounded border text-[8px] uppercase tracking-wider ${meta.cls}`}>
                  {meta.label}
                </span>
                <span className="truncate">{r.project_id} / {r.run_id}</span>
                {r.route && <span className="text-neutral-600">{r.route}</span>}
                {r.finished_at && (
                  <span className="ml-auto text-neutral-600 shrink-0">
                    {new Date(r.finished_at).toLocaleString()}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ─── Georef badge helper ────────────────────────────────────────────────────
function georefBadge(confidence?: string | null) {
  const c = (confidence ?? "MISSING").toUpperCase();
  if (c === "HIGH")   return { label: "GEOREF ALTA",  cls: "text-green-400 border-green-600/40 bg-green-900/20" };
  if (c === "MEDIUM") return { label: "GEOREF MEDIA", cls: "text-yellow-400 border-yellow-600/40 bg-yellow-900/20" };
  if (c === "LOW")    return { label: "GEOREF BAJA",  cls: "text-orange-400 border-orange-600/40 bg-orange-900/20" };
  return { label: "SIN GEOREF", cls: "text-red-400 border-red-600/40 bg-red-900/20" };
}

// ─── Stat pill ────────────────────────────────────────────────────────────────
function StatPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[7px] uppercase tracking-widest text-neutral-600">{label}</span>
      <span className="text-[10px] font-mono text-white">{value}</span>
    </div>
  );
}

// ─── Section header ──────────────────────────────────────────────────────────
function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[9px] uppercase tracking-widest text-neutral-500 font-bold mb-2">{children}</p>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// FASE 10 — El estado de la vista, explícito.
// Cinco flujos asíncronos independientes; cada uno con su propio final.
// ─────────────────────────────────────────────────────────────────────────────

type HistorialState = {
  projectRuns: ProjectRunsViewData | null;
  loading: boolean;
  loadError: string | null;
  loadingRunKey: string | null;
  runError: string | null;
  detailKey: string | null;
  detailLoading: string | null;
  runDetails: Record<string, ProjectRunDetail>;
  detailError: string | null;
  baseRun: SelectedRun | null;
  compareRun: SelectedRun | null;
  loadingCompare: boolean;
  compareError: string | null;
  compareResult: CompareResult | null;
  deletingKey: string | null;
  deleteError: string | null;
  confirmDelete: { projectId: string; runId: string } | null;
};

const historialInicial: HistorialState = {
  projectRuns: null, loading: true, loadError: null,
  loadingRunKey: null, runError: null,
  detailKey: null, detailLoading: null, runDetails: {}, detailError: null,
  baseRun: null, compareRun: null, loadingCompare: false,
  compareError: null, compareResult: null,
  deletingKey: null, deleteError: null, confirmDelete: null,
};

type HistorialAction =
  | { type: "CAMPO"; campo: keyof HistorialState; valor: HistorialState[keyof HistorialState] }
  | { type: "CATALOGO_PEDIDO" }
  | { type: "CATALOGO_OK"; datos: ProjectRunsViewData | null }
  | { type: "CATALOGO_FALLO"; mensaje: string }
  | { type: "MODELO_ABRIENDO"; clave: string }
  | { type: "MODELO_FALLO"; mensaje: string }
  | { type: "MODELO_LISTO" }
  | { type: "DETALLE_CERRADO" }
  | { type: "DETALLE_PEDIDO"; clave: string }
  | { type: "DETALLE_OK"; clave: string; detalle: ProjectRunDetail }
  | { type: "DETALLE_FALLO"; mensaje: string }
  | { type: "BASE_ELEGIDA"; seleccion: SelectedRun }
  | { type: "COMPARACION_INICIADA"; seleccion: SelectedRun }
  | { type: "COMPARACION_OK"; resultado: CompareResult | null }
  | { type: "COMPARACION_FALLO"; mensaje: string }
  | { type: "COMPARACION_TERMINADA" }
  | { type: "BORRADO_INICIADO"; clave: string }
  | { type: "BORRADO_FALLO"; mensaje: string }
  | { type: "BORRADO_TERMINADO" };

function historialReducer(estado: HistorialState, accion: HistorialAction): HistorialState {
  switch (accion.type) {
    case "CAMPO":
      return { ...estado, [accion.campo]: accion.valor };
    case "CATALOGO_PEDIDO":
      return { ...estado, loading: true, loadError: null };
    case "CATALOGO_OK":
      // `parseProjectRuns` devuelve `null` si el payload no tiene la forma
      // esperada. Eso NO es una carga con éxito y vacía: es un formato que no se
      // entendió, y decirlo es más útil que pintar una lista vacía.
      return accion.datos
        ? { ...estado, projectRuns: accion.datos, loading: false, loadError: null }
        : { ...estado, projectRuns: null, loading: false,
            loadError: "El historial llegó con un formato que no se pudo leer." };
    case "CATALOGO_FALLO":
      return { ...estado, loading: false, loadError: accion.mensaje };
    case "MODELO_ABRIENDO":
      return { ...estado, loadingRunKey: accion.clave, runError: null };
    case "MODELO_FALLO":
      // El indicador se apaga EN LA MISMA transición que pone el error: eran dos
      // llamadas separadas repetidas en tres sitios.
      return { ...estado, runError: accion.mensaje, loadingRunKey: null };
    case "MODELO_LISTO":
      return { ...estado, loadingRunKey: null };
    case "DETALLE_CERRADO":
      return { ...estado, detailKey: null };
    case "DETALLE_PEDIDO":
      return { ...estado, detailKey: accion.clave, detailLoading: accion.clave, detailError: null };
    case "DETALLE_OK":
      return {
        ...estado,
        runDetails: { ...estado.runDetails, [accion.clave]: accion.detalle },
        detailLoading: null,
      };
    case "DETALLE_FALLO":
      return { ...estado, detailError: accion.mensaje, detailLoading: null };
    case "BASE_ELEGIDA":
      return { ...estado, baseRun: accion.seleccion, compareError: null };
    case "COMPARACION_INICIADA":
      return { ...estado, compareRun: accion.seleccion, loadingCompare: true, compareError: null };
    case "COMPARACION_OK":
      return {
        ...estado,
        compareResult: accion.resultado,
        compareError: accion.resultado ? null : "Resultado de comparación con formato inválido.",
      };
    case "COMPARACION_FALLO":
      return { ...estado, compareResult: null, compareError: accion.mensaje };
    case "COMPARACION_TERMINADA":
      return { ...estado, loadingCompare: false };
    case "BORRADO_INICIADO":
      // Confirmar y empezar a borrar es UN movimiento: el diálogo no puede
      // quedarse abierto sobre una corrida que ya se está borrando.
      return { ...estado, deletingKey: accion.clave, deleteError: null, confirmDelete: null };
    case "BORRADO_FALLO":
      return { ...estado, deleteError: accion.mensaje };
    case "BORRADO_TERMINADO":
      return { ...estado, deletingKey: null };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}

export default function HistorialView() {
  const {
    setModel, setView, setActiveRun, setShow3D,
    activeRun, blockModelDataMode, setIsBlockModelLoading,
    setGeorefState, georefConfidence, crsInfo, hasElevationData,
  } = useAppStore();

  // ── FASE 10 (H-16) — 17 `useState` → una máquina con transiciones con nombre ──
  //
  // Esta vista hace CINCO cosas asíncronas a la vez (listar, abrir un modelo,
  // pedir un detalle, comparar, borrar) y cada una tiene su trío
  // pidiendo/ok/fallo. Con 17 piezas sueltas nada impedía dejar un `loading` en
  // true tras un fallo, o mostrar el error de un borrado junto al resultado de
  // una comparación que sí funcionó. Aquí cada final apaga su propio indicador
  // porque la transición lo hace, no porque alguien se acuerde.
  const [ui, dispatch] = useReducer(historialReducer, historialInicial);
  const {
    projectRuns, loading, loadError, loadingRunKey, runError,
    detailKey, detailLoading, runDetails, detailError,
    baseRun, compareRun, loadingCompare, compareError, compareResult,
    deletingKey, deleteError, confirmDelete,
  } = ui;
  const setCompareError = (mensaje: string | null) =>
    dispatch({ type: "CAMPO", campo: "compareError", valor: mensaje });
  const setConfirmDelete = (valor: { projectId: string; runId: string } | null) =>
    dispatch({ type: "CAMPO", campo: "confirmDelete", valor });

  const loadRuns = useCallback(async () => {
    dispatch({ type: "CATALOGO_PEDIDO" });
    const result = await getProjectRuns();
    if (result.ok && result.data) {
      dispatch({ type: "CATALOGO_OK", datos: parseProjectRuns(result.data) });
    } else {
      dispatch({ type: "CATALOGO_FALLO", mensaje: result.error || "No se pudieron cargar los proyectos." });
    }

  }, []);

  // Carga inicial y cuando cambia la corrida activa
  useEffect(() => {
    void loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRun.runId]);

  const handleLoadModel = async (projectId: string, runId: string) => {
    const key = buildRunKey(projectId, runId);
    dispatch({ type: "MODELO_ABRIENDO", clave: key });
    setIsBlockModelLoading(true);

    const result = await getExplorationBlockModelForRun(
      projectId, runId, blockModelDataMode,
      blockModelDataMode === "exploration" ? 5000 : 250000
    );

    if (!result.ok || !result.data) {
      dispatch({ type: "MODELO_FALLO", mensaje: result.error || "No se pudo cargar el modelo 3D." });
      setIsBlockModelLoading(false);
      return;
    }

    const model = parseBlockModel(result.data);
    if (!model) {
      dispatch({ type: "MODELO_FALLO", mensaje: "La corrida no devolvió celdas válidas." });
      setIsBlockModelLoading(false);
      return;
    }

    // FASE 1 (H-28): la identidad de la corrida se fija ANTES de cargar el modelo.
    // El modelo se sella con la corrida vigente en setModel; al revés quedaría
    // sellado con la corrida anterior y el visor se negaría a pintarlo.
    setActiveRun({
      projectId, runId, source: "history", status: "ready",
      error: null, importMetadata: null, observationsSummary: null,
      reportSummary: null, focusing: null,
    });
    setModel(model);
    setShow3D(true);
    setView("figura 3d");
    dispatch({ type: "MODELO_LISTO" });
    setIsBlockModelLoading(false);

    fetchProjectFootprint(projectId).then((fp) => {
      if (fp.ok && fp.data) {
        const footprint = fp.data.footprint;
        setGeorefState({
          footprint: footprint ?? null,
          confidence: fp.data.georef_confidence ?? null,
          warnings: fp.data.warnings ?? [],
          crsInfo: footprint ? {
            epsg_code: footprint.epsg_code ?? null,
            crs_source: footprint.crs_source ?? null,
            crs_confidence: footprint.crs_confidence ?? null,
            utm_zone: footprint.utm_zone ?? null,
            utm_hemisphere: footprint.utm_hemisphere ?? null,
          } : null,
        });
      }
    }).catch(() => null);
  };

  const handleLoadDetail = async (projectId: string, runId: string) => {
    const key = buildRunKey(projectId, runId);
    if (detailKey === key) {
      dispatch({ type: "DETALLE_CERRADO" });
      return;
    }
    dispatch({ type: "DETALLE_PEDIDO", clave: key });

    const result = await getProjectRunDetail(projectId, runId);
    if (!result.ok || !result.data) {
      dispatch({ type: "DETALLE_FALLO", mensaje: result.error || "No se pudo cargar el detalle." });
      return;
    }
    const detail = parseProjectRunDetail(result.data);
    if (!detail) {
      dispatch({ type: "DETALLE_FALLO", mensaje: "Detalle con formato inválido." });
      return;
    }
    dispatch({ type: "DETALLE_OK", clave: key, detalle: detail });
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    const { projectId, runId } = confirmDelete;
    const key = buildRunKey(projectId, runId);
    dispatch({ type: "BORRADO_INICIADO", clave: key });

    const result = await deleteRun(projectId, runId);
    if (!result.ok) {
      dispatch({ type: "BORRADO_FALLO", mensaje: result.error || "No se pudo eliminar la corrida." });
    } else {
      // Si la corrida eliminada es la activa, limpiarla
      if (activeRun.projectId === projectId && activeRun.runId === runId) {
        setActiveRun({ projectId: null, runId: null, source: null, status: "idle", error: null, importMetadata: null, observationsSummary: null, reportSummary: null, focusing: null });
        setModel(null);
        setShow3D(false);
      }
      await loadRuns();
    }
    dispatch({ type: "BORRADO_TERMINADO" });
  };

  const handleCompare = async (projectId: string, runId: string) => {
    if (!baseRun) {
      setCompareError("Selecciona una corrida base primero.");
      return;
    }
    dispatch({ type: "COMPARACION_INICIADA", seleccion: { projectId, runId } });

    const result = await compareRuns({
      baseProjectId: baseRun.projectId, baseRunId: baseRun.runId,
      compareProjectId: projectId, compareRunId: runId,
    });

    if (!result.ok || !result.data) {
      dispatch({ type: "COMPARACION_FALLO", mensaje: result.error || "No se pudieron comparar las corridas." });
    } else {
      const parsed = parseCompareResult(result.data);
      dispatch({ type: "COMPARACION_OK", resultado: parsed });
    }
    dispatch({ type: "COMPARACION_TERMINADA" });
  };

  const isActiveRun = (projectId: string, runId: string) =>
    activeRun.projectId === projectId && activeRun.runId === runId;

  // ─── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="h-full overflow-y-auto custom-scrollbar pb-12 pr-1 flex flex-col gap-6">

      {/* ── Header ── */}
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-[13px] uppercase tracking-[0.22em] text-white font-bold">
            Historial de Inversiones
          </h1>
          <p className="text-[9px] text-neutral-500 font-mono mt-0.5">
            {loading
              ? "Cargando corridas..."
              : `${projectRuns?.totalProjects ?? 0} proyectos · ${projectRuns?.totalRuns ?? 0} corridas`}
          </p>
        </div>
        <button
          onClick={loadRuns}
          disabled={loading}
          className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded border border-neutral-700 text-neutral-400 hover:text-white hover:border-neutral-500 transition-colors disabled:opacity-40"
        >
          {loading ? "Actualizando…" : "↺ Actualizar"}
        </button>
      </div>

      {/* ── F3: estado real de corridas (SQLite, sobrevive reinicios) ── */}
      <HistoryStatusPanel />

      {/* ── Errores globales ── */}
      {loadError && (
        <div className="rounded-xl border border-red-900/50 bg-red-950/20 px-4 py-3 text-[10px] text-red-400 font-mono">
          {loadError}
        </div>
      )}
      {runError && (
        <div className="rounded-xl border border-red-900/50 bg-red-950/20 px-4 py-3 text-[10px] text-red-400 font-mono">
          {runError}
        </div>
      )}
      {detailError && (
        <div className="rounded-xl border border-yellow-900/50 bg-yellow-950/20 px-4 py-3 text-[10px] text-yellow-400 font-mono">
          {detailError}
        </div>
      )}
      {compareError && (
        <div className="rounded-xl border border-orange-900/50 bg-orange-950/20 px-4 py-3 text-[10px] text-orange-400 font-mono">
          {compareError}
        </div>
      )}
      {deleteError && (
        <div className="rounded-xl border border-red-900/60 bg-red-950/20 px-4 py-3 text-[10px] text-red-400 font-mono">
          Error al eliminar: {deleteError}
        </div>
      )}

      {/* ── Modal de confirmación de borrado ── */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-neutral-950 border border-neutral-700 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <p className="text-[11px] uppercase tracking-widest text-white font-bold mb-2">
              Eliminar corrida
            </p>
            <p className="text-[10px] text-neutral-400 font-mono mb-1">
              Proyecto: <span className="text-white">{confirmDelete.projectId}</span>
            </p>
            <p className="text-[10px] text-neutral-400 font-mono mb-4">
              Run: <span className="text-red-400">{confirmDelete.runId}</span>
            </p>
            <p className="text-[9px] text-neutral-500 mb-5 leading-relaxed">
              Esta acción eliminará el modelo y todos los archivos asociados del servidor.
              No se puede deshacer.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmDelete(null)}
                className="flex-1 py-2 rounded-lg border border-neutral-700 text-neutral-300 text-[9px] uppercase tracking-widest hover:border-neutral-500 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleDelete}
                className="flex-1 py-2 rounded-lg border border-red-700/60 bg-red-900/20 text-red-400 text-[9px] uppercase tracking-widest hover:bg-red-900/40 transition-colors"
              >
                Eliminar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Panel de comparación ── */}
      {(baseRun || compareRun || compareResult || loadingCompare) && (
        <RunComparePanel
          baseRun={baseRun}
          compareRun={compareRun}
          compareResult={compareResult}
          loadingCompare={loadingCompare}
        />
      )}

      {/* ── Estado vacío ── */}
      {!loading && !loadError && (!projectRuns || projectRuns.totalRuns === 0) && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-neutral-600">
          <span className="text-3xl">⊘</span>
          <p className="text-[10px] uppercase tracking-widest">No hay corridas guardadas</p>
          <p className="text-[9px] text-neutral-700 font-mono">
            Genera un modelo desde Figura 3D para que aparezca aquí.
          </p>
        </div>
      )}

      {/* ── Lista de proyectos y corridas ── */}
      {!loading && !loadError && projectRuns && projectRuns.totalRuns > 0 && (
        <div className="flex flex-col gap-5">
          {projectRuns.projects.map((project) => (
            <div key={project.projectId} className="border border-neutral-800 bg-neutral-950/50 rounded-2xl overflow-hidden">
              {/* Proyecto header */}
              <div className="flex items-center justify-between px-5 py-3 bg-neutral-900/60 border-b border-neutral-800/60">
                <div className="flex items-center gap-3">
                  <span className="h-1.5 w-1.5 rounded-full bg-accent shrink-0" />
                  <span className="text-[10px] text-white font-mono">{project.projectId}</span>
                </div>
                <span className="text-[8px] text-neutral-500 uppercase tracking-widest">
                  {project.runs.length} {project.runs.length === 1 ? "corrida" : "corridas"}
                </span>
              </div>

              {/* Corridas */}
              <div className="divide-y divide-neutral-900/60">
                {project.runs.map((run) => {
                  const key = buildRunKey(project.projectId, run.runId);
                  const isActive = isActiveRun(project.projectId, run.runId);
                  const isLoadingThis = loadingRunKey === key;
                  const isDeletingThis = deletingKey === key;
                  const isDetailOpen = detailKey === key;
                  const isDetailLoading = detailLoading === key;
                  const detail = runDetails[key];
                  const gb = isActive ? georefBadge(georefConfidence) : null;

                  return (
                    <div key={run.runId} className={`px-5 py-4 transition-colors ${isActive ? "bg-accent/5" : "hover:bg-neutral-900/30"}`}>
                      {/* Fila principal */}
                      <div className="flex items-start gap-4">
                        {/* Indicador activo */}
                        <div className="shrink-0 mt-1">
                          {isActive
                            ? <span className="inline-block h-2 w-2 rounded-full bg-accent shadow-[0_0_6px_rgba(52,216,240,0.6)]" />
                            : <span className="inline-block h-2 w-2 rounded-full bg-neutral-700" />
                          }
                        </div>

                        {/* Info del run */}
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2 mb-2">
                            <span className={`text-[10px] font-mono font-bold ${isActive ? "text-accent" : "text-white"}`}>
                              {run.runId}
                            </span>
                            {isActive && (
                              <span className="text-[7px] px-1.5 py-0.5 rounded bg-accent/20 text-accent border border-accent/30 uppercase tracking-widest font-bold">
                                Activa
                              </span>
                            )}
                            {isActive && gb && (
                              <span className={`text-[7px] px-1.5 py-0.5 border rounded uppercase tracking-widest font-bold ${gb.cls}`}>
                                {gb.label}
                              </span>
                            )}
                            {isActive && crsInfo?.epsg_code && (
                              <span className="text-[7px] px-1.5 py-0.5 border border-blue-600/40 bg-blue-900/20 text-blue-400 rounded font-mono">
                                EPSG:{crsInfo.epsg_code}
                              </span>
                            )}
                            {isActive && hasElevationData && (
                              <span className="text-[7px] px-1.5 py-0.5 border border-cyan-600/40 bg-cyan-900/20 text-cyan-400 rounded uppercase tracking-widest font-bold">
                                DEM
                              </span>
                            )}
                            <span className={`text-[7px] uppercase tracking-widest ${run.exists ? "text-green-400" : "text-red-500"}`}>
                              {run.exists ? "● OK" : "● Faltante"}
                            </span>
                          </div>

                          {/* Files chips */}
                          <div className="flex flex-wrap gap-1.5 mb-3">
                            {projectRunFileLabels.map((file) => (
                              <span
                                key={file.key}
                                className={`text-[7px] uppercase px-1.5 py-0.5 rounded border font-mono ${
                                  run.files[file.key]
                                    ? "border-accent/30 bg-accent/10 text-accent/80"
                                    : "border-neutral-800 text-neutral-700"
                                }`}
                              >
                                {file.label}
                              </span>
                            ))}
                          </div>
                        </div>

                        {/* Acciones */}
                        <div className="flex flex-wrap items-center gap-2 shrink-0">
                          {/* Cargar modelo */}
                          {run.files.block_model && (
                            <button
                              type="button"
                              onClick={() => handleLoadModel(project.projectId, run.runId)}
                              disabled={!!loadingRunKey}
                              className={`text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                                isActive
                                  ? "border-accent/40 bg-accent/10 text-accent hover:bg-accent hover:text-black"
                                  : "border-neutral-600 bg-neutral-900 text-neutral-300 hover:border-accent/40 hover:text-accent"
                              }`}
                            >
                              {isLoadingThis ? "Cargando…" : isActive ? "↺ Recargar" : "▶ Cargar"}
                            </button>
                          )}

                          {/* Ver detalle */}
                          <button
                            type="button"
                            onClick={() => handleLoadDetail(project.projectId, run.runId)}
                            disabled={!!detailLoading}
                            className={`text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                              isDetailOpen
                                ? "border-neutral-500 bg-neutral-800 text-white"
                                : "border-neutral-700 bg-neutral-950 text-neutral-400 hover:border-neutral-500 hover:text-white"
                            }`}
                          >
                            {isDetailLoading ? "Cargando…" : isDetailOpen ? "▲ Cerrar" : "▼ Detalle"}
                          </button>

                          {/* Usar como base para comparación */}
                          <button
                            type="button"
                            onClick={() => dispatch({ type: "BASE_ELEGIDA", seleccion: { projectId: project.projectId, runId: run.runId } })}
                            className={`text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border transition-colors ${
                              baseRun?.runId === run.runId && baseRun?.projectId === project.projectId
                                ? "border-blue-500/50 bg-blue-900/20 text-blue-400"
                                : "border-neutral-700 bg-neutral-950 text-neutral-400 hover:border-blue-500/40 hover:text-blue-400"
                            }`}
                          >
                            ◈ Base
                          </button>

                          {/* Comparar */}
                          <button
                            type="button"
                            onClick={() => handleCompare(project.projectId, run.runId)}
                            disabled={loadingCompare || !baseRun}
                            className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border border-neutral-700 bg-neutral-950 text-neutral-400 hover:border-neutral-500 hover:text-white transition-colors disabled:opacity-40"
                          >
                            {loadingCompare && compareRun?.runId === run.runId ? "…" : "⇄ Comparar"}
                          </button>

                          {/* Descargar ZIP */}
                          {hasRunFiles(run.files) && (
                            <a
                              href={exportBundleUrl(project.projectId, run.runId)}
                              download
                              className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border border-neutral-700 bg-neutral-950 text-neutral-400 hover:border-accent/40 hover:text-accent transition-colors"
                            >
                              ↓ ZIP
                            </a>
                          )}

                          {/* Eliminar */}
                          <button
                            type="button"
                            onClick={() => setConfirmDelete({ projectId: project.projectId, runId: run.runId })}
                            disabled={isDeletingThis}
                            className="text-[8px] uppercase tracking-widest px-3 py-1.5 rounded-lg border border-neutral-800 bg-neutral-950 text-neutral-600 hover:border-red-700/50 hover:text-red-400 transition-colors disabled:opacity-40"
                          >
                            {isDeletingThis ? "…" : "✕"}
                          </button>
                        </div>
                      </div>

                      {/* Detalle expandible */}
                      {isDetailOpen && (
                        <div className="mt-4 border-t border-neutral-800/60 pt-4">
                          {isDetailLoading ? (
                            <p className="text-[9px] text-neutral-500 font-mono">Cargando detalle…</p>
                          ) : detail ? (
                            <RunDetailPanel detail={detail} fmtNum={fmtNum} fmtSci={fmtSci} levelCls={levelCls} />
                          ) : (
                            <p className="text-[9px] text-neutral-600 font-mono italic">Sin detalle disponible.</p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Sub-componente de detalle de corrida ─────────────────────────────────────
function RunDetailPanel({
  detail,
  fmtNum: fmt,
  fmtSci: fSci,
  levelCls: lvlCls,
}: {
  detail: ProjectRunDetail;
  fmtNum: typeof fmtNum;
  fmtSci: typeof fmtSci;
  levelCls: typeof levelCls;
}) {
  const inputs = asRecord(detail.inputs);
  const report = asRecord(detail.report);

  return (
    <div className="space-y-4">
      {/* IDs */}
      <div className="grid grid-cols-2 gap-3">
        <StatPill label="Project ID" value={detail.projectId} />
        <StatPill label="Run ID" value={detail.runId} />
      </div>

      {/* Inputs */}
      {inputs && (
        <div className="bg-neutral-900/40 rounded-xl p-3">
          <SectionHeader>Parámetros de entrada</SectionHeader>
          <div className="grid grid-cols-3 md:grid-cols-4 gap-3">
            {["depth", "nir", "fe", "region", "lat", "lon", "nx", "ny", "nz", "block_size"].map((field) => (
              inputs[field] !== undefined && (
                <StatPill key={field} label={field} value={String(inputs[field])} />
              )
            ))}
          </div>
        </div>
      )}

      {/* Métricas del reporte */}
      {report && (
        <div className="bg-neutral-900/40 rounded-xl p-3">
          <SectionHeader>Métricas del solver</SectionHeader>
          <div className="grid grid-cols-3 md:grid-cols-4 gap-3">
            {["fit_quality", "residual_rmse", "residual_mae", "normalized_rmse", "max_density", "avg_density"].map((field) => {
              const val = report[field];
              if (val === undefined || val === null) return null;
              return (
                <StatPill
                  key={field}
                  label={field.replace(/_/g, " ")}
                  value={typeof val === "number" ? fmt(val, 4) : String(val)}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Files */}
      <div className="bg-neutral-900/40 rounded-xl p-3">
        <SectionHeader>Archivos en disco</SectionHeader>
        <div className="flex flex-wrap gap-1.5">
          {projectRunFileLabels.map((file) => (
            <span
              key={file.key}
              className={`text-[7px] uppercase px-2 py-1 rounded border ${
                detail.files[file.key]
                  ? "border-accent/30 bg-accent/10 text-accent/80"
                  : "border-neutral-800 text-neutral-700"
              }`}
            >
              {file.label}
            </span>
          ))}
        </div>
      </div>

      {/* Diagnóstico técnico */}
      <RunDiagnosticsPanel detail={detail} />

      {/* Silenciar warnings de parámetros no usados */}
      <span style={{ display: "none" }}>{fSci(0)}{lvlCls("")}</span>
    </div>
  );
}
