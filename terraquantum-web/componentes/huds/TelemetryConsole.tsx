"use client";

import React, { useState } from "react";
import { useAppStore, HeatmapPoint } from "../../store/useAppStore";
import {
  DEFAULT_OBSERVATIONS,
  // DEMO_STRONG_OBSERVATIONS, // DEAD CODE (Fase B II): demo section removed
  GravityObservation,
  countObservations,
  parseObservations,
} from "../../lib/terraquantum/geophysicsSurvey";

interface TelemetryProps {
  onExecute: (observations: GravityObservation[]) => void | Promise<void>;
  syncState: "idle" | "syncing" | "complete";
  syncProgress: number;
  syncLog: string;
}

export default function TelemetryConsole({
  onExecute,
  syncState,
  syncProgress,
  syncLog,
}: TelemetryProps) {
  const {
    heatmapData,
    bestTarget,
    setView,
  } = useAppStore();

  const [observationsText, setObservationsText] = useState(DEFAULT_OBSERVATIONS);
  const [observationError, setObservationError] = useState<string | null>(null);
  const [inputMode, setInputMode] = useState<"real" | "demo_low" | "demo_strong">(
    "demo_low"
  );
  const [dirtyAfterReady, setDirtyAfterReady] = useState(false);

  const modelReady = syncState === "complete" && !dirtyAfterReady;

  const markDirty = () => {
    if (syncState === "complete") {
      setDirtyAfterReady(true);
    }
  };

  /* ─── DEAD CODE (Fase B II): Demo functions removed from UI ──────
  // Preserved for reference / future use, but no longer called from any button
  const scanSatelliteData = async () => { ... }
  const loadWeakDemo = () => { ... }
  const loadStrongDemo = () => { ... }
  ─────────────────────────────────────────────────────────────────── */

  const handleMainAction = async () => {
    if (syncState === "syncing") return;

    if (modelReady) {
      setView("datos");
      return;
    }

    try {
      setObservationError(null);
      const observations = parseObservations(observationsText);
      await onExecute(observations);
      setDirtyAfterReady(false);
    } catch (error: unknown) {
      setObservationError(
        error instanceof Error ? error.message : "Survey gravimétrico inválido."
      );
    }
  };

  const modeLabel =
    inputMode === "real"
      ? "PARÁMETROS MANUALES"
      : inputMode === "demo_strong"
      ? "MODO DEMO FUERTE"
      : "MODO DEMO BAJO";

  const mainButtonText =
    syncState === "syncing"
      ? "Procesando inversión..."
      : modelReady
      ? "Ver Diagnósticos →"
      : dirtyAfterReady
      ? "Recalcular Modelo"
      : "Generar Modelo 3D";

  return (
    <div className="w-full max-w-full min-w-0 flex flex-col gap-4 overflow-y-auto overflow-x-hidden custom-scrollbar pb-4 pr-1">
      <div className="bg-neutral-900/30 border border-neutral-800 rounded-2xl p-4 shrink-0 min-w-0 overflow-hidden">
        <div className="flex items-start justify-between gap-3 mb-4 min-w-0">
          <h3 className="min-w-0 text-[10px] uppercase tracking-[0.16em] text-[#C2D8C4] font-bold break-words">
            Consola Centro de Mando
          </h3>

          <span
            className={`shrink-0 text-[7px] px-2 py-1 rounded-full border font-bold tracking-widest whitespace-nowrap ${
              inputMode === "real"
                ? "text-blue-300 border-blue-500/40 bg-blue-500/10"
                : inputMode === "demo_strong"
                ? "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10"
                : "text-yellow-300 border-yellow-500/40 bg-yellow-500/10"
            }`}
          >
            {modeLabel}
          </span>
        </div>

        <div className="bg-black rounded-lg p-3 border border-neutral-800 flex flex-col gap-3 min-w-0 overflow-hidden">
          <p
            className={`text-[9px] font-mono break-words ${
              syncState === "complete" ? "text-[#C2D8C4]" : "text-neutral-500"
            }`}
          >
            &gt; {syncLog}
          </p>

          {syncState === "syncing" && (
            <div className="w-full h-0.5 bg-neutral-900 overflow-hidden">
              <div
                className="h-full bg-[#C2D8C4] transition-all"
                style={{ width: `${syncProgress}%` }}
              />
            </div>
          )}
        </div>
      </div>

      {heatmapData && heatmapData.length > 0 && (
        <div className="bg-neutral-900/30 border border-neutral-800 rounded-2xl p-4 shrink-0 min-w-0 overflow-hidden">
          <p className="text-neutral-400 text-[9px] uppercase tracking-widest font-bold mb-3 border-b border-neutral-800/50 pb-2">
            Heatmap IoT Frontal
          </p>

          <div className="grid grid-cols-5 gap-1.5">
            {heatmapData.map((p: HeatmapPoint, i: number) => (
              <div
                key={i}
                className="w-full h-8 rounded"
                style={{
                  background: `rgba(255, 0, 68, ${Math.max(
                    0.08,
                    Math.min(1, Number(p.value || 0))
                  )})`,
                }}
                title={`Densidad: ${p.density?.toFixed?.(3) ?? "N/A"}`}
              />
            ))}
          </div>

          {bestTarget && (
            <p className="text-[9px] text-[#ff0044] mt-3 text-center font-mono font-bold tracking-widest bg-[#ff0044]/10 py-1.5 px-2 rounded break-words">
              LAT: {Number(bestTarget.x).toFixed(4)} | LON:{" "}
              {Number(bestTarget.y).toFixed(4)}
            </p>
          )}
        </div>
      )}

      {syncState === "complete" && (
        <div className="bg-[#C2D8C4]/10 border border-[#C2D8C4]/30 rounded-2xl p-4 min-w-0 overflow-hidden">
          <p className="text-[#C2D8C4] text-[10px] uppercase tracking-widest font-black mb-2">
            Modelo geofísico listo
          </p>
          <p className="text-neutral-400 text-[9px] leading-relaxed font-mono">
            Puedes revisar el modelo 3D. Si modificas parámetros, el botón
            principal volverá a recalcular el mineral.
          </p>
        </div>
      )}

      {/* ─── INLINE SURVEY TEXTAREA (replaces "Modo demo" section) ─────── */}
      <div className="bg-neutral-900/30 border border-neutral-800 rounded-2xl p-4 shrink-0 min-w-0 overflow-hidden">
        <div className="flex justify-between gap-3 text-[9px] text-neutral-400 mb-2 min-w-0">
          <span>Survey Gravimétrico (CSV)</span>
          <span>{countObservations(observationsText)}</span>
        </div>

        <textarea
          value={observationsText}
          onChange={(e) => {
            setInputMode("real");
            setObservationsText(e.target.value);
            markDirty();
          }}
          spellCheck={false}
          placeholder="Pegue datos de survey (lat,lon,gravity,error) o deje en blanco para usar demo..."
          className="w-full min-w-0 h-32 bg-black border border-neutral-800 text-[#C2D8C4] text-[9px] p-3 rounded-xl outline-none font-mono resize-none focus:border-[#C2D8C4]"
        />

        {observationError && (
          <p className="text-[9px] text-red-400 mt-2 font-mono">
            {observationError}
          </p>
        )}
      </div>

      {/* ─── MAIN ACTION BUTTON ──────────────────────────────────────────── */}
      <button
        onClick={handleMainAction}
        disabled={syncState === "syncing"}
        className={`w-full py-4 px-3 text-[10px] font-black uppercase tracking-[0.16em] rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed break-words ${
          modelReady
            ? "bg-[#C2D8C4] text-black hover:bg-white"
            : "bg-white text-black hover:bg-[#C2D8C4]"
        }`}
      >
        {mainButtonText}
      </button>
    </div>
  );
}
