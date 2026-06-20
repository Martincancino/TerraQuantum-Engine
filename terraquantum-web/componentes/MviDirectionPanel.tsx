"use client";

import { useMemo } from "react";
import Panel from "./workspace/Panel";
import type { VoxelMineralModel } from "../lib/terraQuantumGeology";
import type { GeoReportInfo } from "../store/useAppStore";

/**
 * MviDirectionPanel — FASE 20C (frontend, iteración 1).
 *
 * Visualiza la DIRECCIÓN de magnetización RECUPERADA por la inversión vectorial (MVI).
 * El frontend NO calcula física: sólo lee inc/dec por celda que el backend ya invirtió
 * (columnas magnetization_inc_deg/dec_deg del block model) y los valores del campo
 * geomagnético B0 del report. El "cuerpo principal" es la celda de mayor amplitud
 * (susceptibility_si = |M|); seleccionarla es presentación, no física.
 *
 * Sólo se renderiza cuando el modelo es MVI. En caso contrario devuelve null.
 */

type Props = {
  model: VoxelMineralModel | null;
  report: GeoReportInfo | null;
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}
function readNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function readString(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

/** f̂ = (cosI·cosD, sinI, cosI·sinD) — convención de ejes del backend (x=N, y=prof, z=E). */
function unitVector(incDeg: number, decDeg: number): [number, number, number] {
  const I = (incDeg * Math.PI) / 180;
  const D = (decDeg * Math.PI) / 180;
  return [Math.cos(I) * Math.cos(D), Math.sin(I), Math.cos(I) * Math.sin(D)];
}

/** Ángulo (°) entre dos direcciones (inc/dec). Pura geometría para comparación visual. */
function angleBetween(
  incA: number, decA: number, incB: number, decB: number,
): number {
  const a = unitVector(incA, decA);
  const b = unitVector(incB, decB);
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return (Math.acos(Math.max(-1, Math.min(1, dot))) * 180) / Math.PI;
}

export default function MviDirectionPanel({ model, report }: Props) {
  // ── Dirección del cuerpo principal: celda de máxima |M| con dirección definida ──
  const dominant = useMemo(() => {
    const cells = model?.cells;
    if (!cells || cells.length === 0) return null;
    let best: { susc: number; inc: number; dec: number } | null = null;
    for (const c of cells) {
      const inc = readNumber(c["magnetization_inc_deg"]);
      const dec = readNumber(c["magnetization_dec_deg"]);
      if (inc === null || dec === null) continue;
      const susc = readNumber(c["susceptibility_si"]) ?? 0;
      if (best === null || susc > best.susc) best = { susc, inc, dec };
    }
    return best;
  }, [model]);

  // ── El report puede llegar plano (path magnético) o anidado bajo backendReport
  // (buildReportForFrontend curado). Buscamos en ambos sin asumir la forma. ──
  const rawReport: Record<string, unknown> | null = isRecord(report?.["backendReport"])
    ? (report!["backendReport"] as Record<string, unknown>)
    : (isRecord(report) ? (report as Record<string, unknown>) : null);

  // ── ¿Es un modelo MVI? Señal autoritativa = magnetization_model del report. ──
  const reportSaysVector =
    readString(report?.["magnetization_model"]) === "vector" ||
    readString(rawReport?.["magnetization_model"]) === "vector";
  const isMvi = reportSaysVector || dominant !== null;
  if (!isMvi || !dominant) return null;

  // ── Campo geomagnético B0 (inducido) desde el report, para comparación. ──
  const field = isRecord(rawReport?.["field"]) ? (rawReport!["field"] as Record<string, unknown>) : null;
  const b0Inc = readNumber(field?.["inclination_deg"]);
  const b0Dec = readNumber(field?.["declination_deg"]);
  const hasB0 = b0Inc !== null && b0Dec !== null;

  const obliquity = hasB0 ? angleBetween(dominant.inc, dominant.dec, b0Inc!, b0Dec!) : null;
  // Umbral de evidencia de remanencia: dirección recuperada lejos de la inducida.
  const remanenceLikely = obliquity !== null && obliquity >= 20;

  // ── Compás (declinación, vista en planta): N arriba, E a la derecha, D horario. ──
  const compass = (decDeg: number, color: string) => {
    const r = 22;
    const cx = 28;
    const cy = 28;
    const D = (decDeg * Math.PI) / 180;
    const tx = cx + r * Math.sin(D);
    const ty = cy - r * Math.cos(D);
    return (
      <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="1" />
        <text x={cx} y="9" textAnchor="middle" fontSize="6" fill="rgba(255,255,255,0.4)">N</text>
        <text x="51" y={cy + 2} textAnchor="middle" fontSize="6" fill="rgba(255,255,255,0.3)">E</text>
        <line x1={cx} y1={cy} x2={tx} y2={ty} stroke={color} strokeWidth="2" />
        <circle cx={tx} cy={ty} r="2.2" fill={color} />
        <circle cx={cx} cy={cy} r="1.6" fill="rgba(255,255,255,0.5)" />
      </svg>
    );
  };

  // ── Indicador de buzamiento (inclinación, vista de perfil): + hacia abajo. ──
  const dip = (incDeg: number, color: string) => {
    const cx = 6;
    const cy = 28;
    const L = 44;
    const I = (incDeg * Math.PI) / 180;
    const tx = cx + L * Math.cos(I);
    const ty = cy + L * Math.sin(I);
    return (
      <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden>
        <line x1={cx} y1={cy} x2={cx + L} y2={cy} stroke="rgba(255,255,255,0.15)" strokeWidth="1" strokeDasharray="2 2" />
        <line x1={cx} y1={cy} x2={tx} y2={ty} stroke={color} strokeWidth="2" />
        <circle cx={tx} cy={ty} r="2.2" fill={color} />
        <circle cx={cx} cy={cy} r="1.6" fill="rgba(255,255,255,0.5)" />
      </svg>
    );
  };

  const fmt = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(0)}°`;

  return (
    <Panel
      title="Magnetización (MVI)"
      subtitle="Dirección recuperada del cuerpo principal"
      right={
        <span className="text-[7px] font-mono uppercase tracking-[0.18em] px-1.5 py-0.5 rounded bg-fuchsia-500/15 text-fuchsia-300 border border-fuchsia-400/30">
          Vector
        </span>
      }
    >
      <p className="text-[8px] text-white/50 mb-3 leading-relaxed">
        La inversión vectorial recupera la dirección de magnetización <span className="text-white/70">desde los datos</span>,
        sin asumirla. Útil para detectar <span className="text-white/70">remanencia</span> (magnetita reorientada).
      </p>

      <div className="grid grid-cols-2 gap-3">
        {/* Recuperada */}
        <div className="flex flex-col items-center gap-1 rounded-lg bg-white/3 border border-fuchsia-400/20 p-2">
          <span className="text-[7px] uppercase tracking-wider text-fuchsia-300/80">Recuperada</span>
          <div className="flex items-center gap-1">
            {compass(dominant.dec, "#e879f9")}
            {dip(dominant.inc, "#e879f9")}
          </div>
          <span className="text-[8px] font-mono text-white/75 tabular-nums">
            Inc {fmt(dominant.inc)} · Dec {fmt(dominant.dec)}
          </span>
        </div>

        {/* Campo B0 (inducido) */}
        <div className="flex flex-col items-center gap-1 rounded-lg bg-white/3 border border-white/10 p-2">
          <span className="text-[7px] uppercase tracking-wider text-white/40">Campo B0 (inducido)</span>
          {hasB0 ? (
            <>
              <div className="flex items-center gap-1">
                {compass(b0Dec!, "#7dd3fc")}
                {dip(b0Inc!, "#7dd3fc")}
              </div>
              <span className="text-[8px] font-mono text-white/55 tabular-nums">
                Inc {fmt(b0Inc!)} · Dec {fmt(b0Dec!)}
              </span>
            </>
          ) : (
            <span className="text-[8px] font-mono text-white/30 py-4">No disponible</span>
          )}
        </div>
      </div>

      {obliquity !== null && (
        <div className="mt-3 pt-3 border-t border-white/10 flex items-center justify-between">
          <span className="text-[8px] font-mono text-white/45">Desvío vs B0</span>
          <span
            className={`text-[9px] font-mono font-bold tabular-nums ${
              remanenceLikely ? "text-fuchsia-300" : "text-white/70"
            }`}
          >
            {obliquity.toFixed(0)}°
          </span>
        </div>
      )}

      {remanenceLikely && (
        <p className="mt-2 text-[8px] leading-tight text-fuchsia-300/90">
          La dirección recuperada difiere del campo inducido → evidencia de <span className="font-semibold">remanencia</span>.
          El motor escalar (que asume inducción) ubicaría mal este cuerpo.
        </p>
      )}

      <p className="mt-3 text-[7px] text-white/30 leading-tight">
        Cuerpo principal = celda de mayor amplitud |M|. Visualización de valores invertidos
        por el backend; no constituye confirmación geológica.
      </p>
    </Panel>
  );
}
