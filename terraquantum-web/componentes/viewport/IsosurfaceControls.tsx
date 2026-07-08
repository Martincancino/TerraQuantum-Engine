"use client";

import { useAppStore } from "../../store/useAppStore";

/**
 * Control de las isosuperficies suaves del backend (Fase F4.2).
 *
 * Toggle prominente en la barra izquierda: activa/desactiva las mallas de
 * marching cubes (/v2/isosurface) sobre los vóxeles. Muestra el estado de la
 * corrida (niveles / anomalía débil / error). Es puramente visual.
 */
export default function IsosurfaceControls() {
  const model = useAppStore((s) => s.model);
  const showIsosurfaces = useAppStore((s) => s.showIsosurfaces);
  const setShowIsosurfaces = useAppStore((s) => s.setShowIsosurfaces);
  const isosurfaceData = useAppStore((s) => s.isosurfaceData);

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para activar las isosuperficies.
      </p>
    );
  }

  const hasError = !!isosurfaceData?.error;
  const ready = !!isosurfaceData && !hasError && (isosurfaceData.n_levels ?? 0) > 0;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setShowIsosurfaces(!showIsosurfaces)}
        className={`w-full py-2 rounded-md text-[10px] font-mono uppercase tracking-wider border transition-colors ${
          showIsosurfaces
            ? "border-accent/60 bg-accent/15 text-accent"
            : "border-white/15 bg-white/[0.02] text-white/60 hover:text-white/85 hover:border-white/30"
        }`}
      >
        {showIsosurfaces ? "Isosuperficies: ON" : "Isosuperficies: OFF"}
      </button>

      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Mallas suaves (marching cubes del backend) en vez de cubos. Se superponen a
        los vóxeles; se ocultan en modo elevación.
      </p>

      {isosurfaceData && (
        <p
          className={`text-[8px] font-mono leading-relaxed ${
            hasError ? "text-amber-400/80" : "text-white/45"
          }`}
        >
          {hasError
            ? `Sin superficie: ${isosurfaceData.error}`
            : ready
              ? `${isosurfaceData.n_levels} nivel(es)` +
                (isosurfaceData.weak_anomaly ? " · anomalía débil" : "")
              : "Calculando…"}
        </p>
      )}
    </div>
  );
}
