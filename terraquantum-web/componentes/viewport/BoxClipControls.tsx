"use client";

import { useMemo } from "react";
import { useAppStore } from "../../store/useAppStore";

type AxisKey = "x" | "y" | "z";

interface AxisRange { min: number; max: number; step: number }

/**
 * Corte caja (Sprint 4A) — 6 planos AABB para secciones A-A' / B-B'.
 * Aísla el sub-volumen definido por [xMin,xMax]×[yMin,yMax]×[zMin,zMax].
 * Filtro puramente visual: no toca el block model ni la inversión.
 */
export default function BoxClipControls() {
  const model          = useAppStore((s) => s.model);
  const clipBoxEnabled = useAppStore((s) => s.clipBoxEnabled);
  const setClipBoxEnabled = useAppStore((s) => s.setClipBoxEnabled);
  const clipBox        = useAppStore((s) => s.clipBox);
  const setClipBox     = useAppStore((s) => s.setClipBox);

  // Rango real por eje derivado de las coordenadas de celda.
  const ranges = useMemo<Record<AxisKey, AxisRange>>(() => {
    const fallback: Record<AxisKey, AxisRange> = {
      x: { min: -100, max: 100, step: 1 },
      y: { min: -100, max: 100, step: 1 },
      z: { min: -100, max: 100, step: 1 },
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

    const toRange = (lo: number, hi: number): AxisRange => ({
      min: Number.isFinite(lo) ? lo : -100,
      max: Number.isFinite(hi) ? hi : 100,
      step: Number.isFinite(lo) && Number.isFinite(hi) ? Math.max((hi - lo) / 200, 0.1) : 1,
    });

    return {
      x: toRange(minX, maxX),
      y: toRange(minY, maxY),
      z: toRange(minZ, maxZ),
    };
  }, [model]);

  // Inicializar clipBox al rango completo cuando el usuario activa el toggle.
  function handleToggle() {
    if (!clipBoxEnabled) {
      setClipBox({
        xMin: ranges.x.min, xMax: ranges.x.max,
        yMin: ranges.y.min, yMax: ranges.y.max,
        zMin: ranges.z.min, zMax: ranges.z.max,
      });
    }
    setClipBoxEnabled(!clipBoxEnabled);
  }

  function handleReset() {
    setClipBox({
      xMin: ranges.x.min, xMax: ranges.x.max,
      yMin: ranges.y.min, yMax: ranges.y.max,
      zMin: ranges.z.min, zMax: ranges.z.max,
    });
  }

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para activar el corte caja.
      </p>
    );
  }

  const AXES: { key: AxisKey; label: string; minKey: keyof typeof clipBox; maxKey: keyof typeof clipBox }[] = [
    { key: "x", label: "X (Este)", minKey: "xMin", maxKey: "xMax" },
    { key: "y", label: "Y (Profundidad)", minKey: "yMin", maxKey: "yMax" },
    { key: "z", label: "Z (Norte)", minKey: "zMin", maxKey: "zMax" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Sección caja A-A&#x27; / B-B&#x27;. No altera el modelo ni la inversión.
      </p>

      {/* Toggle enable */}
      <label className="flex items-center justify-between cursor-pointer select-none">
        <span className="text-[9px] font-mono text-white/60">Activar corte caja</span>
        <div
          onClick={handleToggle}
          className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${
            clipBoxEnabled ? "bg-accent/70" : "bg-white/10"
          }`}
        >
          <div
            className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
              clipBoxEnabled ? "translate-x-4" : "translate-x-0.5"
            }`}
          />
        </div>
      </label>

      {clipBoxEnabled && (
        <>
          {AXES.map(({ key, label, minKey, maxKey }) => {
            const r = ranges[key];
            const lo = Math.max(r.min, Math.min(r.max, clipBox[minKey]));
            const hi = Math.max(r.min, Math.min(r.max, clipBox[maxKey]));
            return (
              <div key={key} className="flex flex-col gap-1">
                <span className="text-[8px] font-mono text-white/50">{label}</span>

                {/* Min slider */}
                <div className="flex items-center justify-between text-[7px] font-mono text-white/40">
                  <span>Min</span>
                  <span className="text-accent">{lo.toFixed(0)} m</span>
                </div>
                <input
                  type="range"
                  min={r.min}
                  max={r.max}
                  step={r.step}
                  value={lo}
                  onChange={(e) => {
                    const v = Math.min(Number(e.target.value), hi);
                    setClipBox({ [minKey]: v });
                  }}
                  className="w-full accent-[#22d3ee]"
                />

                {/* Max slider */}
                <div className="flex items-center justify-between text-[7px] font-mono text-white/40">
                  <span>Max</span>
                  <span className="text-accent">{hi.toFixed(0)} m</span>
                </div>
                <input
                  type="range"
                  min={r.min}
                  max={r.max}
                  step={r.step}
                  value={hi}
                  onChange={(e) => {
                    const v = Math.max(Number(e.target.value), lo);
                    setClipBox({ [maxKey]: v });
                  }}
                  className="w-full accent-[#22d3ee]"
                />

                <div className="flex justify-between text-[7px] font-mono text-white/25">
                  <span>{r.min.toFixed(0)}</span>
                  <span>{r.max.toFixed(0)}</span>
                </div>
              </div>
            );
          })}

          <button
            type="button"
            onClick={handleReset}
            className="mt-1 py-1 text-[8px] font-mono text-white/40 border border-white/10 rounded-md hover:text-white/70 hover:border-white/25 transition-colors"
          >
            Restablecer rango completo
          </button>
        </>
      )}
    </div>
  );
}
