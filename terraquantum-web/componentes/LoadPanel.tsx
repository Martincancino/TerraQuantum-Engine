"use client";

// ─── Fase R4 (frontend) — LoadPanel (vista 3D) ───────────────────────────────
//
// Sube el "paquete CSV" auto-contenido generado en «Preparación» y carga el
// modelo 3D. El backend (load-package) parsea el paquete, corre la inversión
// ruteada (grav/mag/joint/+sondajes) y persiste el block model; aquí solo se
// sube el archivo y se carga el modelo resultante en el visor. No calcula física
// ni arma payloads (eso vive en el backend).

import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../store/useAppStore";
import {
  loadModelFromPackage,
  type PackageProgress,
} from "../lib/terraquantum/packageInversion";
import { errorViewFromString, type TQErrorView } from "../lib/terraquantum/errorContract";
import ErrorModal from "./ErrorModal";

// F3 — etiquetas ES para las etapas reales que reporta el backend.
const STAGE_LABEL: Record<string, string> = {
  queued: "En cola",
  loading_data: "Validando datos",
  building_mesh: "Construyendo malla",
  kernel: "Armando kernel",
  solving_lsqr: "Resolviendo (LSQR)",
  solving: "Resolviendo",
  postprocess: "Postproceso",
  "post-processing": "Postproceso",
  done: "Completado",
};

export default function LoadPanel() {
  const displayResolutionFactor = useAppStore((s) => s.displayResolutionFactor);

  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  // F3 — progreso en vivo (etapas reales del solver vía polling) + cancelar.
  const [progress, setProgress] = useState<PackageProgress | null>(null);
  const cancelRequested = useRef(false);
  // Al desmontar el panel se ABANDONA el polling (la corrida sigue en el
  // backend y aparece en Historial) — no se cancela ni se toca más el store.
  const abandoned = useRef(false);
  useEffect(() => {
    abandoned.current = false;
    return () => {
      abandoned.current = true;
    };
  }, []);
  // FASE 23 — error accionable del backend (load-package): se normaliza al contrato
  // TQErrorView y se muestra en ErrorModal (RESUMEN/DETALLES/ACCIÓN), no inline plano.
  const [errorView, setErrorView] = useState<TQErrorView | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const reportError = (msg: string) => {
    setErrorView(errorViewFromString(msg, "Error al cargar el modelo 3D desde el paquete."));
    setModalOpen(true);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    setErrorView(null);
    setModalOpen(false);
    const f = e.target.files?.[0] ?? null;
    setFile(f);
  };

  const handleLoadModel = async () => {
    if (!file) return;
    setLoading(true);
    setErrorView(null);
    setModalOpen(false);
    setProgress(null);
    cancelRequested.current = false;
    try {
      const res = await loadModelFromPackage(file, displayResolutionFactor, {
        onProgress: (p) => {
          if (!abandoned.current) setProgress(p);
        },
        shouldCancel: () => cancelRequested.current,
        shouldAbandon: () => abandoned.current,
      });
      if (!res.ok && !res.cancelled && !abandoned.current) reportError(res.error);
    } catch (err) {
      reportError(
        err instanceof Error ? err.message : "Error inesperado al cargar el modelo 3D.",
      );
    } finally {
      setLoading(false);
      setProgress(null);
    }
  };

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden flex flex-col gap-3">
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Sube el paquete CSV generado en «Preparación» y carga el modelo 3D. La
        inversión corre en el backend al cargar.
      </p>

      {/* Subir paquete */}
      <label className="block">
        <span className="text-[9px] uppercase tracking-widest text-white/50 font-bold">
          Subir paquete
        </span>
        <input
          type="file"
          accept=".csv,.tqpkg,.tqpkg.csv,text/csv"
          onChange={handleFile}
          disabled={loading}
          className="mt-1 block w-full text-[9px] text-white/70 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-[9px] file:bg-white/10 file:text-white/80 hover:file:bg-white/20 file:cursor-pointer disabled:opacity-50"
        />
      </label>

      {file && (
        <div className="rounded border border-white/10 bg-white/[0.03] p-2 text-[9px] font-mono text-white/60">
          <div className="flex justify-between gap-2">
            <span>Paquete:</span>
            <span className="text-white/80 truncate max-w-[160px]" title={file.name}>
              {file.name}
            </span>
          </div>
        </div>
      )}

      {/* Cargar modelo 3D */}
      <button
        onClick={handleLoadModel}
        disabled={!file || loading}
        className="h-9 w-full justify-center px-4 bg-[#C2D8C4] text-black text-[10px] uppercase font-bold tracking-widest rounded hover:bg-white disabled:opacity-50 transition-colors flex items-center"
      >
        {loading ? "Cargando modelo 3D..." : "Cargar modelo 3D"}
      </button>

      {loading && (
        <div className="flex flex-col gap-2">
          {/* F3 — progreso REAL por etapas del solver (polling 1.5 s) */}
          {progress ? (
            <div className="rounded border border-white/10 bg-white/[0.03] p-2 flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2 text-[9px] font-mono text-white/70">
                <span>
                  {STAGE_LABEL[progress.stage ?? ""] ?? progress.stage ?? "Procesando"}
                </span>
                {typeof progress.progress === "number" && (
                  <span className="text-white/50">
                    {Math.round(progress.progress * 100)}%
                  </span>
                )}
              </div>
              <div className="h-1.5 w-full rounded bg-white/10 overflow-hidden">
                <div
                  className="h-full bg-[#C2D8C4] transition-all duration-500"
                  style={{
                    width: `${Math.max(3, Math.round((progress.progress ?? 0) * 100))}%`,
                  }}
                />
              </div>
              {progress.message && (
                <p className="text-[8px] font-mono text-white/45 leading-relaxed">
                  {progress.message}
                </p>
              )}
              {progress.budget?.warning && (
                <p className="text-[8px] font-mono text-amber-400/90 leading-relaxed">
                  {progress.budget.warning}
                </p>
              )}
              <button
                type="button"
                onClick={() => { cancelRequested.current = true; }}
                className="self-start mt-1 px-2 py-1 rounded border border-red-700/50 text-[9px] uppercase tracking-widest text-red-400 hover:bg-red-950/40"
              >
                Cancelar corrida
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-[9px] font-mono text-white/55">
              <span className="h-3 w-3 rounded-full border-2 border-white/20 border-t-[#C2D8C4] animate-spin" />
              Enviando el paquete al backend…
            </div>
          )}
        </div>
      )}

      {errorView && (
        <div className="rounded border border-red-900/50 bg-red-950/20 p-2 text-[10px] font-mono text-red-400">
          <p className="mb-1 break-words">{errorView.userMessage}</p>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="underline underline-offset-2 hover:text-red-300"
          >
            Ver detalle y acción sugerida
          </button>
        </div>
      )}

      {errorView && modalOpen && (
        <ErrorModal
          error={errorView}
          onClose={() => setModalOpen(false)}
          onRetry={() => { setModalOpen(false); void handleLoadModel(); }}
        />
      )}
    </div>
  );
}
