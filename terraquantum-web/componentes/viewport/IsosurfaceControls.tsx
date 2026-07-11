"use client";

import { useCallback, useEffect, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import type { IsosurfaceData } from "../../lib/render/IsosurfaceMeshLayer";

/**
 * Control de las isosuperficies suaves del backend (Fase F4.2).
 *
 * Toggle prominente en la barra izquierda. El propio control hace el fetch a
 * /api/isosurface (autónomo, con botón de recarga y estado explícito) para no
 * depender del timing de otros effects y dar feedback claro: Calculando / N
 * niveles / error del backend. Es puramente visual.
 *
 * Gate F4 (QA visual aprobado): default ON — al cargar un modelo, las mallas se
 * piden solas (auto-fetch) y la vista producto es la cáscara suave.
 */
type FetchState = "idle" | "loading" | "ok" | "error";

export default function IsosurfaceControls() {
  const model = useAppStore((s) => s.model);
  const projectId = useAppStore((s) => s.activeRun.projectId);
  const runId = useAppStore((s) => s.activeRun.runId);
  const viewMode = useAppStore((s) => s.viewMode);
  const showIsosurfaces = useAppStore((s) => s.showIsosurfaces);
  const setShowIsosurfaces = useAppStore((s) => s.setShowIsosurfaces);
  const isosurfaceData = useAppStore((s) => s.isosurfaceData);
  const setIsosurfaceData = useAppStore((s) => s.setIsosurfaceData);

  const [state, setState] = useState<FetchState>("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId || !runId) {
      setState("error");
      setMsg("No hay corrida activa (carga el modelo 3D primero).");
      return;
    }
    const field = viewMode === "susceptibility" ? "susceptibility" : "density";
    setState("loading");
    setMsg(null);
    try {
      const res = await fetch(
        `/api/isosurface?project_id=${encodeURIComponent(projectId)}` +
          `&run_id=${encodeURIComponent(runId)}&field=${field}`,
        { cache: "no-store" }
      );
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setIsosurfaceData(null);
        setState("error");
        setMsg(
          body?.detail ||
            `El backend respondió ${res.status}. ¿Está reiniciado con el fix?`
        );
        return;
      }
      const data = (await res.json()) as IsosurfaceData;
      setIsosurfaceData(data);
      setState("ok");
      setMsg(null);
    } catch {
      setIsosurfaceData(null);
      setState("error");
      setMsg("No se pudo conectar al backend (¿está corriendo?).");
    }
  }, [projectId, runId, viewMode, setIsosurfaceData]);

  const handleToggle = () => {
    const next = !showIsosurfaces;
    setShowIsosurfaces(next);
    if (next) load(); // al encender, (re)pide las mallas — recoge un backend recién reiniciado
  };

  // Auto-fetch (gate F4, default ON): al quedar lista una corrida con el toggle
  // encendido, pide las mallas sin exigir un click. `load` cambia con
  // projectId/runId/viewMode → re-fetch automático al cambiar de corrida o campo.
  // Diferido con timeout: sin setState síncrono dentro del effect.
  useEffect(() => {
    if (!(showIsosurfaces && model && projectId && runId)) return;
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [showIsosurfaces, model, projectId, runId, load]);

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para activar las isosuperficies.
      </p>
    );
  }

  // Línea de estado.
  let status: { text: string; tone: "muted" | "warn" | "ok" } | null = null;
  if (state === "loading") {
    status = { text: "Calculando isosuperficies…", tone: "muted" };
  } else if (state === "error") {
    status = { text: msg ?? "Error al pedir isosuperficies.", tone: "warn" };
  } else if (state === "ok" && isosurfaceData) {
    if (isosurfaceData.error) {
      status = { text: `Sin superficie: ${isosurfaceData.error}`, tone: "warn" };
    } else {
      status = {
        text:
          `${isosurfaceData.n_levels} nivel(es)` +
          (isosurfaceData.weak_anomaly ? " · anomalía débil" : ""),
        tone: "ok",
      };
    }
  }

  const toneClass =
    status?.tone === "warn"
      ? "text-amber-400/80"
      : status?.tone === "ok"
        ? "text-accent/70"
        : "text-white/45";

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={handleToggle}
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

      {status && <p className={`text-[8px] font-mono leading-relaxed ${toneClass}`}>{status.text}</p>}

      {showIsosurfaces && (
        <button
          type="button"
          onClick={load}
          disabled={state === "loading"}
          className="self-start text-[8px] font-mono uppercase tracking-wider text-white/50 hover:text-white/80 underline underline-offset-2 disabled:opacity-40"
        >
          Recargar
        </button>
      )}
    </div>
  );
}
