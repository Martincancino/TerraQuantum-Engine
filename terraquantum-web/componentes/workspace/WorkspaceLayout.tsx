"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 36 };

function CollapseTab({
  open,
  onClick,
  side,
}: {
  open: boolean;
  onClick: () => void;
  side: "left" | "right";
}) {
  // ‹ colapsa hacia el borde, › expande
  const pointLeft = side === "left" ? open : !open;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={open ? "Colapsar panel" : "Expandir panel"}
      className="self-center shrink-0 h-16 w-3.5 rounded-full bg-white/[0.04] border border-white/10 text-white/40 hover:text-accent hover:border-accent/40 transition-colors text-[11px] leading-none flex items-center justify-center"
    >
      {pointLeft ? "‹" : "›"}
    </button>
  );
}

/**
 * WorkspaceLayout — orquestador de las 4 zonas del workspace científico:
 *  · CommandBar (top)  · Scientific Sidebar (left, colapsable)
 *  · Viewport (center, ~70%)  · Analytics Panel (right, colapsable)
 *
 * Layout puro y modular: recibe las zonas como slots, lo que prepara el terreno
 * para workflows multi-panel / comparación de runs side-by-side (2ª interfaz futura).
 */
export default function WorkspaceLayout({
  commandBar,
  sidebar,
  viewport,
  analytics,
  sidebarWidth = 380,
  analyticsWidth = 380,
}: {
  commandBar: React.ReactNode;
  sidebar: React.ReactNode;
  viewport: React.ReactNode;
  analytics: React.ReactNode;
  sidebarWidth?: number;
  analyticsWidth?: number;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [analyticsOpen, setAnalyticsOpen] = useState(true);

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col gap-3 animate-fadeIn">
      {commandBar}

      <div className="flex-grow min-h-0 min-w-0 flex gap-1.5">
        {/* LEFT — Scientific Sidebar */}
        <motion.aside
          animate={{ width: sidebarOpen ? sidebarWidth : 0, opacity: sidebarOpen ? 1 : 0 }}
          transition={SPRING}
          className="h-full min-h-0 shrink-0 overflow-hidden"
        >
          <div
            style={{ width: sidebarWidth }}
            className="tq-panel rounded-2xl h-full overflow-y-auto overflow-x-hidden custom-scrollbar"
          >
            {sidebar}
          </div>
        </motion.aside>
        <CollapseTab side="left" open={sidebarOpen} onClick={() => setSidebarOpen((v) => !v)} />

        {/* CENTER — Viewport (~70%) */}
        <main className="flex-grow min-w-0 min-h-0 relative">{viewport}</main>

        {/* RIGHT — Analytics Panel */}
        <CollapseTab side="right" open={analyticsOpen} onClick={() => setAnalyticsOpen((v) => !v)} />
        <motion.aside
          animate={{ width: analyticsOpen ? analyticsWidth : 0, opacity: analyticsOpen ? 1 : 0 }}
          transition={SPRING}
          className="h-full min-h-0 shrink-0 overflow-hidden"
        >
          <div
            style={{ width: analyticsWidth }}
            className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar flex flex-col gap-3 pr-0.5"
          >
            {analytics}
          </div>
        </motion.aside>
      </div>
    </div>
  );
}
