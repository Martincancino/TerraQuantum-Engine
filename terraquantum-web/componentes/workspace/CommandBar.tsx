"use client";

import React from "react";

export type CommandAction = {
  id: string;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  primary?: boolean;
  active?: boolean;
};

/**
 * CommandBar — barra superior minimalista estilo workstation científica
 * (Unreal / Blender / mission control). Acciones compactas, sin colores chillones.
 */
export default function CommandBar({
  title,
  status,
  actions = [],
}: {
  title: string;
  status?: React.ReactNode;
  actions?: CommandAction[];
}) {
  return (
    <div className="tq-panel rounded-xl h-12 px-4 flex items-center justify-between gap-4 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex items-center gap-2 shrink-0">
          <span className="h-2 w-2 rounded-[2px] bg-accent rotate-45 tq-glow" />
          <span className="text-[11px] font-semibold tracking-[0.24em] text-white/90 uppercase">
            TerraQuantum
          </span>
        </div>
        <span className="hidden md:block h-4 w-px bg-white/10" />
        <span className="hidden md:block text-[10px] tracking-[0.18em] uppercase text-white/50 truncate">
          {title}
        </span>
      </div>

      {status && <div className="hidden lg:flex items-center min-w-0">{status}</div>}

      <div className="flex items-center gap-1.5 shrink-0">
        {actions.map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={a.onClick}
            disabled={a.disabled}
            className={[
              "px-3 py-1.5 rounded-lg text-[9px] uppercase tracking-[0.16em] font-semibold transition-all border whitespace-nowrap",
              "disabled:opacity-30 disabled:cursor-not-allowed",
              a.primary
                ? "bg-accent text-black border-accent hover:bg-accent-soft tq-glow"
                : a.active
                ? "bg-accent/15 text-accent border-accent/40"
                : "bg-white/[0.03] text-white/65 border-white/10 hover:text-white hover:border-white/25",
            ].join(" ")}
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
