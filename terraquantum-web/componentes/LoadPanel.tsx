"use client";

// ─── Fase R3 — LoadPanel (vista 3D) ──────────────────────────────────────────
//
// Sube un "paquete CSV" generado en la vista «Preparación», corre la inversión
// (reusando el endpoint existente vía invertFromPackage) y carga el modelo 3D en
// el visor. No prepara datos ni calcula física: solo dispara la inversión del
// paquete ya preparado y rutea la respuesta al store.

import { useState } from "react";
import { useAppStore } from "../store/useAppStore";
import {
  parseCsvPackage,
  type CsvPackage,
} from "../lib/terraquantum/csvPackage";
import { invertFromPackage } from "../lib/terraquantum/packageInversion";

const STAGE_LABELS: Record<string, string> = {
  queued: "En cola...",
  building_kernel: "Construyendo kernel de sensibilidad...",
  running_lsqr: "Ejecutando inversor LSQR...",
  computing_uq: "Calculando incertidumbre...",
  exporting_model: "Exportando modelo 3D...",
  running: "Ejecutando inversión...",
  done: "Inversión completa",
  completed: "Inversión completa",
  error: "Error en inversión",
};

export default function LoadPanel() {
  const displayResolutionFactor = useAppStore((s) => s.displayResolutionFactor);

  const [pkg, setPkg] = useState<CsvPackage | null>(null);
  const [pkgFilename, setPkgFilename] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handlePackageFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setParseError(null);
    setErrorMsg(null);
    setPkg(null);
    setPkgFilename(null);

    const f = e.target.files?.[0];
    if (!f) return;

    let text: string;
    try {
      text = await f.text();
    } catch {
      setParseError("No se pudo leer el archivo del paquete.");
      return;
    }

    const result = parseCsvPackage(text);
    if (!result.ok) {
      setParseError(result.error);
      return;
    }

    setPkg(result.package);
    setPkgFilename(f.name);
  };

  const handleLoadModel = async () => {
    if (!pkg) return;
    setLoading(true);
    setErrorMsg(null);
    setStage("queued");
    setProgress(0);

    try {
      const res = await invertFromPackage(
        pkg,
        {
          onStage: (s) => setStage(s),
          onProgress: (p) => setProgress(p),
        },
        displayResolutionFactor,
      );
      if (!res.ok) {
        setErrorMsg(res.error);
      }
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Error inesperado al cargar el modelo 3D.",
      );
    } finally {
      setLoading(false);
      setStage(null);
      setProgress(0);
    }
  };

  const nBoreholes = pkg?.boreholes?.length ?? 0;

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden flex flex-col gap-3">
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Sube el paquete CSV generado en «Preparación» y carga el modelo 3D. La
        inversión corre al cargar.
      </p>

      {/* Subir paquete */}
      <label className="block">
        <span className="text-[9px] uppercase tracking-widest text-white/50 font-bold">
          Subir paquete
        </span>
        <input
          type="file"
          accept=".json,.tqpkg.json,application/json"
          onChange={handlePackageFile}
          disabled={loading}
          className="mt-1 block w-full text-[9px] text-white/70 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-[9px] file:bg-white/10 file:text-white/80 hover:file:bg-white/20 file:cursor-pointer disabled:opacity-50"
        />
      </label>

      {parseError && (
        <p className="text-[10px] text-red-400 font-mono">{parseError}</p>
      )}

      {/* Resumen del paquete */}
      {pkg && (
        <div className="rounded border border-white/10 bg-white/[0.03] p-2 text-[9px] font-mono text-white/60 leading-relaxed">
          <div className="flex justify-between gap-2">
            <span>Archivo:</span>
            <span className="text-white/80 truncate max-w-[150px]" title={pkgFilename ?? undefined}>
              {pkgFilename}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span>Tipo:</span>
            <span className="text-white/80">
              {pkg.dataType === "magnetic" ? "Magnetometría" : "Gravimetría"}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span>CSV:</span>
            <span className="text-white/80 truncate max-w-[150px]" title={pkg.csv.filename}>
              {pkg.csv.filename}
              {pkg.csv.corrected ? " (corregido)" : ""}
            </span>
          </div>
          {nBoreholes > 0 && (
            <div className="flex justify-between gap-2">
              <span>Sondajes:</span>
              <span className="text-white/80">{nBoreholes}</span>
            </div>
          )}
        </div>
      )}

      {/* Cargar modelo 3D */}
      <button
        onClick={handleLoadModel}
        disabled={!pkg || loading}
        className="h-9 w-full justify-center px-4 bg-[#C2D8C4] text-black text-[10px] uppercase font-bold tracking-widest rounded hover:bg-white disabled:opacity-50 transition-colors flex items-center"
      >
        {loading ? "Cargando modelo 3D..." : "Cargar modelo 3D"}
      </button>

      {loading && (
        <div>
          <div className="flex justify-between items-center mb-1">
            <span className="text-[9px] font-mono text-neutral-400 uppercase tracking-widest">
              {stage
                ? STAGE_LABELS[stage] ?? stage.replace(/_/g, " ")
                : "Preparando inversión..."}
            </span>
            <span className="text-[9px] font-mono text-neutral-500">
              {progress > 0 ? `${Math.round(progress * 100)}%` : ""}
            </span>
          </div>
          <div className="w-full h-1 bg-neutral-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#C2D8C4] transition-all"
              style={{ width: `${Math.max(progress * 100, 4)}%` }}
            />
          </div>
        </div>
      )}

      {errorMsg && (
        <p className="text-[10px] text-red-400 font-mono">{errorMsg}</p>
      )}
    </div>
  );
}
