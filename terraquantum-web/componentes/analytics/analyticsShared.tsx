"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { fmtNum, fmtSci } from "../datos/helpers";

export { fmtNum, fmtSci };

/** Convierte un valor desconocido en Record si es un objeto plano. */
export function asRec(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/** Primer número finito encontrado entre las claves dadas (o null). */
export function numOf(
  rec: Record<string, unknown> | null | undefined,
  ...keys: string[]
): number | null {
  if (!rec) return null;
  for (const key of keys) {
    const v = rec[key];
    if (v === null || v === undefined || v === "") continue;
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

export function strOf(
  rec: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  const v = rec?.[key];
  return typeof v === "string" && v.trim().length > 0 ? v : null;
}

export function boolOf(
  rec: Record<string, unknown> | null | undefined,
  key: string
): boolean {
  return rec?.[key] === true;
}

// ─── Tema de gráficos (recharts) ──────────────────────────────────────────────
export const ACCENT = "#22d3ee";
export const axisProps = {
  stroke: "#3f3f46",
  tick: { fontSize: 8, fill: "#a1a1aa" },
} as const;
export const tooltipStyle = {
  backgroundColor: "#050505",
  border: "1px solid #27272a",
  fontSize: "10px",
  borderRadius: "8px",
  color: "#e5e5e5",
  padding: "6px 8px",
} as const;

export type Tone = "good" | "warn" | "bad" | "neutral";

const TONE_CLS: Record<Tone, string> = {
  good: "text-[#C2D8C4] border-[#C2D8C4]/30",
  warn: "text-yellow-400 border-yellow-500/30",
  bad: "text-red-400 border-red-500/30",
  neutral: "text-white/80 border-white/10",
};

/** Tarjeta métrica compacta para los widgets del panel analytics. */
export function StatCard({
  label,
  value,
  unit,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={`rounded-md border bg-white/[0.02] px-2.5 py-2 ${TONE_CLS[tone]}`}
    >
      <p className="text-[7px] uppercase tracking-[0.18em] text-white/40 mb-1">{label}</p>
      <p className="text-[13px] font-mono leading-none">
        {value}
        {unit ? <span className="text-[8px] text-white/40 ml-1">{unit}</span> : null}
      </p>
      {hint ? <p className="text-[7px] text-white/35 mt-1 leading-tight">{hint}</p> : null}
    </motion.div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="text-[9px] text-white/40 font-mono leading-relaxed italic">{children}</p>
  );
}

export type HistogramBin = { x: string; mid: number; count: number };

/** Histograma simple sobre valores finitos. range opcional [min,max]. */
export function buildHistogram(
  values: number[],
  binCount = 24,
  range?: [number, number]
): HistogramBin[] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return [];

  const lo = range ? range[0] : Math.min(...finite);
  let hi = range ? range[1] : Math.max(...finite);
  if (!(hi > lo)) {
    // Todos iguales: un único bin centrado.
    return [{ x: lo.toFixed(2), mid: lo, count: finite.length }];
  }
  // Pequeño margen superior para incluir el máximo en el último bin.
  hi = hi + (hi - lo) * 1e-6;

  const width = (hi - lo) / binCount;
  const bins: HistogramBin[] = Array.from({ length: binCount }, (_, i) => {
    const mid = lo + width * (i + 0.5);
    return { x: mid.toPrecision(2), mid, count: 0 };
  });
  for (const v of finite) {
    let idx = Math.floor((v - lo) / width);
    if (idx < 0) idx = 0;
    if (idx >= binCount) idx = binCount - 1;
    bins[idx].count += 1;
  }
  return bins;
}
