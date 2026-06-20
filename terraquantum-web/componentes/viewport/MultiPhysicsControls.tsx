"use client";

import { useMemo, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import type { ViewMode } from "../../store/useAppStore";
import { motion, AnimatePresence } from "framer-motion";
import { classifyViewModeAvailability } from "../../lib/terraquantum/qaStatus";

// ── Descriptores de cada modo de visualización ───────────────────────────────
const VIEW_MODES: {
  id: ViewMode;
  label: string;
  shortLabel: string;
  description: string;
  icon: string;
  accentColor: string;
  dotColor: string;
}[] = [
  {
    id: "density",
    label: "Densidad",
    shortLabel: "ρ",
    description: "Viridis · density_t_m3 normalizada",
    icon: "⬡",
    accentColor: "#22d3ee",
    dotColor: "#22d3ee",
  },
  {
    id: "susceptibility",
    label: "Susceptibilidad",
    shortLabel: "χ",
    description: "Turbo · log₁₀(χ + ε)",
    icon: "⇡",
    accentColor: "#f59e0b",
    dotColor: "#f59e0b",
  },
  {
    id: "joint",
    label: "Conjunto",
    shortLabel: "J",
    description: "Filtro · joint_structural_score ≥ θ",
    icon: "◈",
    accentColor: "#0bd3ee",
    dotColor: "#0bd3ee",
  },
];

// ── Gradiente de referencia para el slider de umbral ─────────────────────────
const JOINT_GRADIENT =
  "linear-gradient(to right, #1e3a4c 0%, #0bd3ee 100%)";

export default function MultiPhysicsControls() {
  const viewMode      = useAppStore((s) => s.viewMode);
  const setViewMode   = useAppStore((s) => s.setViewMode);
  const threshold     = useAppStore((s) => s.jointThreshold);
  const setThreshold  = useAppStore((s) => s.setJointThreshold);
  const model         = useAppStore((s) => s.model);
  const showMviVectors    = useAppStore((s) => s.showMviVectors);
  const setShowMviVectors = useAppStore((s) => s.setShowMviVectors);

  const [collapsed, setCollapsed] = useState(false);

  // Compute data availability per mode from model cells.
  // Uses .some() → exits on first match, O(n) worst case but fast in practice.
  // Memoized on model so it doesn't recompute on every render.
  const cells = useMemo(
    () => (model?.cells ?? []) as Array<Record<string, unknown>>,
    [model]
  );
  const susceptibilityQa = useMemo(
    () => classifyViewModeAvailability("susceptibility", cells),
    [cells]
  );
  const jointQa = useMemo(
    () => classifyViewModeAvailability("joint", cells),
    [cells]
  );
  // FASE 20C iter 2: ¿hay dirección de magnetización (MVI) en el modelo?
  // .some() corta en el primer match → barato en práctica.
  const mviAvailable = useMemo(
    () => cells.some((c) => Number.isFinite(Number(c["magnetization_inc_deg"]))),
    [cells]
  );

  if (!model) return null;

  const active = VIEW_MODES.find((m) => m.id === viewMode) ?? VIEW_MODES[0];

  function modeQa(id: ViewMode) {
    if (id === "susceptibility") return susceptibilityQa;
    if (id === "joint") return jointQa;
    return null;
  }

  function handleSetViewMode(id: ViewMode) {
    const qa = modeQa(id);
    if (qa && qa.status === "FAIL") {
      // Gate: no hay datos para este modo — no cambiar viewMode.
      return;
    }
    setViewMode(id);
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="absolute top-4 right-4 z-20 select-none"
      style={{ pointerEvents: "auto" }}
    >
      {/* ── Panel principal ─────────────────────────────────────────────── */}
      <div
        className="rounded-xl border border-white/10 shadow-2xl"
        style={{
          background: "rgba(5, 8, 14, 0.88)",
          backdropFilter: "blur(18px)",
          minWidth: 220,
        }}
      >
        {/* Cabecera */}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="w-full flex items-center justify-between px-3.5 py-2.5 gap-2 rounded-t-xl hover:bg-white/[0.04] transition-colors"
        >
          <div className="flex items-center gap-2">
            {/* indicador de modo activo */}
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: active.dotColor, boxShadow: `0 0 6px ${active.dotColor}` }}
            />
            <span className="text-[9px] uppercase tracking-[0.18em] font-mono text-white/70">
              Multi-Física
            </span>
          </div>
          <span className="text-white/30 text-[10px] font-mono leading-none">
            {collapsed ? "▾" : "▸"}
          </span>
        </button>

        <AnimatePresence initial={false}>
          {!collapsed && (
            <motion.div
              key="body"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: "easeInOut" }}
              style={{ overflow: "hidden" }}
            >
              <div className="px-3.5 pb-3.5 pt-1 flex flex-col gap-3">
                {/* ── Selector de viewMode ──────────────────────────── */}
                <div className="flex flex-col gap-1.5">
                  <p className="text-[7.5px] font-mono text-white/35 uppercase tracking-[0.14em]">
                    Capa física activa
                  </p>
                  <div className="grid grid-cols-3 gap-1">
                    {VIEW_MODES.map((m) => {
                      const isActive = viewMode === m.id;
                      const qa = modeQa(m.id);
                      const isUnavailable = qa !== null && qa.status === "FAIL";

                      return (
                        <div key={m.id} className="flex flex-col items-center gap-0.5">
                          <button
                            id={`multiphysics-btn-${m.id}`}
                            type="button"
                            onClick={() => handleSetViewMode(m.id)}
                            title={isUnavailable ? qa.reason : m.description}
                            className="relative w-full flex flex-col items-center justify-center gap-0.5 py-2 rounded-lg border transition-all duration-150"
                            style={{
                              borderColor: isUnavailable
                                ? "rgba(239,68,68,0.35)"
                                : isActive
                                ? m.accentColor + "70"
                                : "rgba(255,255,255,0.08)",
                              background: isUnavailable
                                ? "rgba(239,68,68,0.06)"
                                : isActive
                                ? `${m.accentColor}18`
                                : "rgba(255,255,255,0.02)",
                              color: isUnavailable
                                ? "rgba(239,68,68,0.55)"
                                : isActive
                                ? m.accentColor
                                : "rgba(255,255,255,0.4)",
                              boxShadow: isActive && !isUnavailable
                                ? `0 0 12px ${m.accentColor}28`
                                : "none",
                            }}
                          >
                            <span className="text-[12px] leading-none">{m.icon}</span>
                            <span className="text-[7.5px] font-mono tracking-wider leading-none">
                              {m.shortLabel}
                            </span>
                          </button>
                          {/* QA unavailability indicator below button */}
                          {isUnavailable && (
                            <span
                              className="text-[6px] font-mono text-red-400/70 leading-none tracking-wider"
                              title={qa.reason}
                            >
                              sin datos
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Descripción del modo activo */}
                  <p
                    className="text-[7px] font-mono leading-relaxed"
                    style={{ color: active.accentColor + "99" }}
                  >
                    {active.description}
                  </p>

                  {/* QA notice when active mode has no data */}
                  {(() => {
                    const activeQa = modeQa(viewMode);
                    if (!activeQa || activeQa.status !== "FAIL") return null;
                    return (
                      <div className="rounded border border-red-500/25 bg-red-500/5 px-2 py-1">
                        <p className="text-[7px] font-mono text-red-400/80 leading-tight">
                          ⚠ {activeQa.reason}
                        </p>
                      </div>
                    );
                  })()}
                </div>

                {/* ── Slider de umbral conjunto ─────────────────────── */}
                <AnimatePresence>
                  {viewMode === "joint" && (
                    <motion.div
                      key="joint-slider"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.18 }}
                      style={{ overflow: "hidden" }}
                    >
                      <div className="flex flex-col gap-1.5 pt-1 border-t border-white/[0.06]">
                        <div className="flex items-center justify-between">
                          <span className="text-[7.5px] font-mono text-white/40 uppercase tracking-[0.14em]">
                            Umbral conjunto θ
                          </span>
                          <span
                            className="text-[9px] font-mono tabular-nums"
                            style={{ color: "#0bd3ee" }}
                          >
                            {threshold.toFixed(2)}
                          </span>
                        </div>
                        <input
                          id="joint-threshold-slider"
                          type="range"
                          min={0}
                          max={1}
                          step={0.01}
                          value={threshold}
                          onChange={(e) => setThreshold(Number(e.target.value))}
                          className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                          style={{
                            background: JOINT_GRADIENT,
                            accentColor: "#0bd3ee",
                          }}
                        />
                        <div className="flex justify-between text-[7px] font-mono text-white/25">
                          <span>0.00</span>
                          <span>0.50</span>
                          <span>1.00</span>
                        </div>
                        <p className="text-[7px] font-mono text-white/30 leading-relaxed">
                          Vóxeles con joint_structural_score &lt; θ se ocultarán.
                        </p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* ── Leyenda colormap ─────────────────────────────── */}
                <div className="flex flex-col gap-1">
                  <p className="text-[7px] font-mono text-white/25 uppercase tracking-[0.12em]">
                    Colormap
                  </p>
                  <ColormapStrip mode={viewMode} />
                </div>

                {/* ── Overlay de flechas MVI (sólo si hay dirección invertida) ── */}
                {mviAvailable && (
                  <div className="flex flex-col gap-1 pt-2 border-t border-white/6">
                    <button
                      id="mvi-vectors-toggle"
                      type="button"
                      onClick={() => setShowMviVectors(!showMviVectors)}
                      className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg border transition-all duration-150"
                      style={{
                        borderColor: showMviVectors ? "rgba(232,121,249,0.5)" : "rgba(255,255,255,0.08)",
                        background: showMviVectors ? "rgba(232,121,249,0.12)" : "rgba(255,255,255,0.02)",
                        color: showMviVectors ? "#e879f9" : "rgba(255,255,255,0.5)",
                        boxShadow: showMviVectors ? "0 0 12px rgba(232,121,249,0.22)" : "none",
                      }}
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="text-[12px] leading-none">↗</span>
                        <span className="text-[8px] font-mono uppercase tracking-[0.12em]">Vectores MVI</span>
                      </span>
                      <span className="text-[7px] font-mono tracking-wider">
                        {showMviVectors ? "ON" : "OFF"}
                      </span>
                    </button>
                    <p className="text-[7px] font-mono text-white/30 leading-relaxed">
                      Dirección de magnetización recuperada (largo ∝ |M|). Glifos de mayor amplitud.
                    </p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ── Tira de colormap compacta ─────────────────────────────────────────────────
function ColormapStrip({ mode }: { mode: ViewMode }) {
  const gradients: Record<ViewMode, string> = {
    density:
      "linear-gradient(to right, #440154, #31688e, #35b779, #fde725)",
    susceptibility:
      "linear-gradient(to right, #301551, #2766e7, #16c3d0, #30ee5a, #aef920, #ffc614, #f45c01, #7a0500)",
    joint:
      "linear-gradient(to right, rgba(11,211,238,0.15) 0%, #0bd3ee 100%)",
  };

  const labels: Record<ViewMode, [string, string]> = {
    density:    ["Baja ρ", "Alta ρ"],
    susceptibility: ["χ bajo", "χ alto"],
    joint:      [`θ = umbral`, "score = 1"],
  };

  const [lo, hi] = labels[mode];

  return (
    <div className="flex flex-col gap-0.5">
      <div
        className="w-full h-2.5 rounded"
        style={{ background: gradients[mode] }}
      />
      <div className="flex justify-between text-[6.5px] font-mono text-white/30">
        <span>{lo}</span>
        <span>{hi}</span>
      </div>
    </div>
  );
}
