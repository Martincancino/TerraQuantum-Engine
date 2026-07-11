"use client";

import { useCallback, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import type { DoiOverlayData } from "../../lib/render/DoiOverlayLayer";

/**
 * Control del horizonte DOI en el visor 3D (Fase F4.5 — incertidumbre visible).
 *
 * Toggle autónomo (fetch + recarga + estado explícito). Bajo el horizonte el
 * dato deja de restringir el modelo: el visor lo atenúa con un velo. El valor
 * viene 100% del backend (convención B2); esto es solo visualización.
 */
type FetchState = "idle" | "loading" | "ok" | "error";

export default function DoiOverlayControls() {
  const model = useAppStore((s) => s.model);
  const projectId = useAppStore((s) => s.activeRun.projectId);
  const runId = useAppStore((s) => s.activeRun.runId);
  const showDoiOverlay = useAppStore((s) => s.showDoiOverlay);
  const setShowDoiOverlay = useAppStore((s) => s.setShowDoiOverlay);
  const doiOverlayData = useAppStore((s) => s.doiOverlayData);
  const setDoiOverlayData = useAppStore((s) => s.setDoiOverlayData);

  const [state, setState] = useState<FetchState>("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId || !runId) {
      setState("error");
      setMsg("No hay corrida activa (carga el modelo 3D primero).");
      return;
    }
    setState("loading");
    setMsg(null);
    try {
      const res = await fetch(
        `/api/doi-overlay?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
        { cache: "no-store" }
      );
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setDoiOverlayData(null);
        setState("error");
        setMsg(body?.detail || `El backend respondió ${res.status}.`);
        return;
      }
      const data = (await res.json()) as DoiOverlayData;
      setDoiOverlayData(data);
      setState("ok");
      setMsg(null);
    } catch {
      setDoiOverlayData(null);
      setState("error");
      setMsg("No se pudo conectar al backend.");
    }
  }, [projectId, runId, setDoiOverlayData]);

  const handleToggle = () => {
    const next = !showDoiOverlay;
    setShowDoiOverlay(next);
    if (next) load();
  };

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para ver el horizonte DOI.
      </p>
    );
  }

  let status: { text: string; tone: "muted" | "warn" | "ok" } | null = null;
  if (state === "loading") {
    status = { text: "Calculando horizonte…", tone: "muted" };
  } else if (state === "error") {
    status = { text: msg ?? "Error al pedir el horizonte DOI.", tone: "warn" };
  } else if (state === "ok" && doiOverlayData) {
    if (doiOverlayData.error) {
      status = { text: doiOverlayData.error, tone: "warn" };
    } else {
      status = {
        text: `Horizonte a ${doiOverlayData.depth_m?.toFixed(0)} m de profundidad — bajo eso el dato no restringe el modelo.`,
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
          showDoiOverlay
            ? "border-accent/60 bg-accent/15 text-accent"
            : "border-white/15 bg-white/[0.02] text-white/60 hover:text-white/85 hover:border-white/30"
        }`}
      >
        {showDoiOverlay ? "Horizonte DOI: ON" : "Horizonte DOI: OFF"}
      </button>

      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Vela la zona donde la gravedad ya no &quot;ve&quot; (profundidad de
        investigación). Es el límite honesto del dato, no del software.
      </p>

      {status && <p className={`text-[8px] font-mono leading-relaxed ${toneClass}`}>{status.text}</p>}
    </div>
  );
}
