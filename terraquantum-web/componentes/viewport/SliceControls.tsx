"use client";

import { useEffect, useMemo } from "react";
import { useAppStore } from "../../store/useAppStore";
import type { SliceAxis } from "../../store/useAppStore";
import type { SectionData } from "../../lib/render/SectionPaintLayer";

/**
 * Controles del plano de corte (Fase C — slice planes tipo Leapfrog).
 *
 * El corte es un filtro puramente visual: oculta el half-space más allá del plano
 * y dibuja la superficie de sección. No modifica el block model ni la inversión.
 *
 * F4.3: con el corte activo se pide al backend la CARA PINTADA (/api/section,
 * raster de contraste en el plano snapeado) con debounce — arrastrar el slider
 * no dispara una ráfaga de fetches. El frontend solo pinta el raster recibido.
 */
const AXES: { id: SliceAxis; label: string }[] = [
  { id: "none", label: "Off" },
  { id: "x", label: "X" },
  { id: "y", label: "Y" },
  { id: "z", label: "Z" },
];

type AxisKey = "x" | "y" | "z";

export default function SliceControls() {
  const model = useAppStore((s) => s.model);
  const sliceAxis = useAppStore((s) => s.sliceAxis);
  const setSliceAxis = useAppStore((s) => s.setSliceAxis);
  const slicePosition = useAppStore((s) => s.slicePosition);
  const setSlicePosition = useAppStore((s) => s.setSlicePosition);
  const showOnlySlice = useAppStore((s) => s.showOnlySlice);
  const setShowOnlySlice = useAppStore((s) => s.setShowOnlySlice);
  const showSectionPaint = useAppStore((s) => s.showSectionPaint);
  const setShowSectionPaint = useAppStore((s) => s.setShowSectionPaint);
  const setSectionData = useAppStore((s) => s.setSectionData);
  const projectId = useAppStore((s) => s.activeRun.projectId);
  const runId = useAppStore((s) => s.activeRun.runId);
  const viewMode = useAppStore((s) => s.viewMode);

  // F4.3: fetch de la cara pintada, debounced 250 ms (arrastre del slider).
  useEffect(() => {
    if (sliceAxis === "none" || !showSectionPaint || !projectId || !runId) {
      setSectionData(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const field = viewMode === "susceptibility" ? "susceptibility" : "density";
      try {
        const res = await fetch(
          `/api/section?project_id=${encodeURIComponent(projectId)}` +
            `&run_id=${encodeURIComponent(runId)}&axis=${sliceAxis}` +
            `&position=${encodeURIComponent(String(slicePosition))}&field=${field}`,
          { cache: "no-store" }
        );
        if (cancelled) return;
        if (!res.ok) {
          setSectionData(null);
          return;
        }
        const data = (await res.json()) as SectionData;
        if (!cancelled) setSectionData(data);
      } catch {
        if (!cancelled) setSectionData(null);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sliceAxis, slicePosition, showSectionPaint, projectId, runId, viewMode, setSectionData]);

  // Rango real por eje, derivado de las coords de celda (una pasada, memoizada).
  const ranges = useMemo<Record<AxisKey, [number, number]>>(() => {
    const fallback: Record<AxisKey, [number, number]> = {
      x: [-100, 100],
      y: [-100, 100],
      z: [-100, 100],
    };
    const cells = model?.cells;
    if (!cells || cells.length === 0) return fallback;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;

    for (const raw of cells as Record<string, unknown>[]) {
      const x = Number(raw.x ?? raw.cx ?? 0);
      const y = Number(raw.y ?? raw.cy ?? 0);
      const z = Number(raw.z ?? raw.cz ?? 0);
      if (Number.isFinite(x)) { if (x < minX) minX = x; if (x > maxX) maxX = x; }
      if (Number.isFinite(y)) { if (y < minY) minY = y; if (y > maxY) maxY = y; }
      if (Number.isFinite(z)) { if (z < minZ) minZ = z; if (z > maxZ) maxZ = z; }
    }

    return {
      x: [Number.isFinite(minX) ? minX : -100, Number.isFinite(maxX) ? maxX : 100],
      y: [Number.isFinite(minY) ? minY : -100, Number.isFinite(maxY) ? maxY : 100],
      z: [Number.isFinite(minZ) ? minZ : -100, Number.isFinite(maxZ) ? maxZ : 100],
    };
  }, [model]);

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para activar los cortes geológicos.
      </p>
    );
  }

  const activeRange = sliceAxis === "none" ? null : ranges[sliceAxis];
  const step =
    activeRange && activeRange[1] > activeRange[0]
      ? Math.max((activeRange[1] - activeRange[0]) / 200, 0.1)
      : 1;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Filtro visual de sección. No altera el modelo ni la inversión.
      </p>

      {/* Selector de eje */}
      <div className="grid grid-cols-4 gap-1.5">
        {AXES.map((axis) => {
          const active = sliceAxis === axis.id;
          return (
            <button
              key={axis.id}
              type="button"
              onClick={() => setSliceAxis(axis.id)}
              className={`py-1.5 rounded-md text-[9px] font-mono uppercase tracking-wider border transition-colors ${
                active
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-white/10 bg-white/[0.02] text-white/45 hover:text-white/70 hover:border-white/20"
              }`}
            >
              {axis.label}
            </button>
          );
        })}
      </div>

      {/* Slider de posición */}
      {activeRange && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-[8px] font-mono text-white/45">
            <span>Posición eje {sliceAxis.toUpperCase()}</span>
            <span className="text-accent">{slicePosition.toFixed(1)} m</span>
          </div>
          <input
            type="range"
            min={activeRange[0]}
            max={activeRange[1]}
            step={step}
            value={Math.max(activeRange[0], Math.min(activeRange[1], slicePosition))}
            onChange={(e) => setSlicePosition(Number(e.target.value))}
            className="w-full accent-[#22d3ee]"
          />
          <div className="flex items-center justify-between text-[7px] font-mono text-white/30">
            <span>{activeRange[0].toFixed(0)}</span>
            <span>{activeRange[1].toFixed(0)}</span>
          </div>

          <label className="flex items-center gap-2 mt-1 text-[8px] font-mono text-white/50 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showOnlySlice}
              onChange={(e) => setShowOnlySlice(e.target.checked)}
              className="accent-[#22d3ee]"
            />
            Mostrar solo el lado seccionado
          </label>

          <label className="flex items-center gap-2 text-[8px] font-mono text-white/50 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showSectionPaint}
              onChange={(e) => setShowSectionPaint(e.target.checked)}
              className="accent-[#22d3ee]"
            />
            Cara del corte pintada (densidad)
          </label>
        </div>
      )}
    </div>
  );
}
