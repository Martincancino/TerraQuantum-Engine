"use client";

// ─── Fase R4 (frontend) — LoadPanel (vista 3D) ───────────────────────────────
//
// Sube el "paquete CSV" auto-contenido generado en «Preparación» y carga el
// modelo 3D. El backend (load-package) parsea el paquete, corre la inversión
// ruteada (grav/mag/joint/+sondajes) y persiste el block model; aquí solo se
// sube el archivo y se carga el modelo resultante en el visor. No calcula física
// ni arma payloads (eso vive en el backend).

import { useState } from "react";
import { useAppStore } from "../store/useAppStore";
import { loadModelFromPackage } from "../lib/terraquantum/packageInversion";
import { errorViewFromString, type TQErrorView } from "../lib/terraquantum/errorContract";
import ErrorModal from "./ErrorModal";

export default function LoadPanel() {
  const displayResolutionFactor = useAppStore((s) => s.displayResolutionFactor);

  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
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
    try {
      const res = await loadModelFromPackage(file, displayResolutionFactor);
      if (!res.ok) reportError(res.error);
    } catch (err) {
      reportError(
        err instanceof Error ? err.message : "Error inesperado al cargar el modelo 3D.",
      );
    } finally {
      setLoading(false);
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
        <div className="flex items-center gap-2 text-[9px] font-mono text-white/55">
          <span className="h-3 w-3 rounded-full border-2 border-white/20 border-t-[#C2D8C4] animate-spin" />
          Invirtiendo en el backend (puede tardar)...
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
