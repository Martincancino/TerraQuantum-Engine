"use client";

import { useAppStore } from "../../store/useAppStore";
import type { VolumeRenderMode } from "../../store/useAppStore";

/**
 * Controles del render volumétrico (Fase 6 — raymarch God-Tier).
 *
 * Conmuta entre el renderer instanciado clásico ("Off") y el ray-march WebGL2
 * del MISMO modelo de vóxeles, en modo niebla (acumulación σ) o isosuperficie.
 * Es puramente visual: no recalcula física ni toca el block model; lee las
 * celdas que ya están en memoria. Si la GPU no soporta texturas 3D, el layer
 * permanece oculto aunque el modo esté activo.
 */
const MODES: { id: VolumeRenderMode; label: string }[] = [
  { id: "off", label: "Off" },
  { id: "fog", label: "Niebla" },
  { id: "isosurface", label: "Iso" },
];

export default function VolumeRenderControls() {
  const model = useAppStore((s) => s.model);
  const volumeRenderMode = useAppStore((s) => s.volumeRenderMode);
  const setVolumeRenderMode = useAppStore((s) => s.setVolumeRenderMode);
  const subsurfaceAoEnabled = useAppStore((s) => s.subsurfaceAoEnabled);
  const setSubsurfaceAoEnabled = useAppStore((s) => s.setSubsurfaceAoEnabled);
  const hasElevationData = useAppStore((s) => s.hasElevationData);

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para activar el render volumétrico.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Ray-march del campo continuo (mismo modelo). Solo visual; requiere GPU con
        texturas 3D (WebGL2).
      </p>
      <div className="grid grid-cols-3 gap-1.5">
        {MODES.map((m) => {
          const active = volumeRenderMode === m.id;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setVolumeRenderMode(m.id)}
              className={`py-1.5 rounded-md text-[9px] font-mono uppercase tracking-wider border transition-colors ${
                active
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-white/10 bg-white/[0.02] text-white/45 hover:text-white/70 hover:border-white/20"
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>

      {volumeRenderMode !== "off" && hasElevationData && (
        <p className="text-[8px] text-amber-400/80 font-mono leading-relaxed">
          El render volumétrico se oculta con el modo elevación activo (el
          retículo regular no alinea con la Y deformada por elevación).
        </p>
      )}

      <label className="flex items-center gap-2 mt-1 text-[8px] font-mono text-white/50 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={subsurfaceAoEnabled}
          onChange={(e) => setSubsurfaceAoEnabled(e.target.checked)}
          className="accent-[#22d3ee]"
        />
        Oclusión ambiental (AO screen-space)
      </label>
    </div>
  );
}
