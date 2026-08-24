"use client";

import { useCallback, useEffect, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import type { BoreholeViewData } from "../../lib/render/BoreholeLayer";

/**
 * Control de los sondajes en el visor 3D (Fase F4.4).
 *
 * Toggle en la barra izquierda; el control hace el fetch a /api/boreholes
 * (autónomo, con recarga y estado explícito). Los cilindros se dibujan como
 * contexto geológico junto a los vóxeles/isosuperficies. Puramente visual.
 */
type FetchState = "idle" | "loading" | "ok" | "error";

export default function BoreholeControls() {
  const model = useAppStore((s) => s.model);
  const projectId = useAppStore((s) => s.activeRun.projectId);
  const runId = useAppStore((s) => s.activeRun.runId);
  const showBoreholes = useAppStore((s) => s.showBoreholes);
  const setShowBoreholes = useAppStore((s) => s.setShowBoreholes);
  const boreholeData = useAppStore((s) => s.boreholeData);
  const setBoreholeData = useAppStore((s) => s.setBoreholeData);

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
        `/api/boreholes?project_id=${encodeURIComponent(projectId)}&run_id=${encodeURIComponent(runId)}`,
        { cache: "no-store" }
      );
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setBoreholeData(null);
        setState("error");
        setMsg(body?.detail || `El backend respondió ${res.status}.`);
        return;
      }
      const data = (await res.json()) as BoreholeViewData;
      setBoreholeData(data);
      setState("ok");
      setMsg(null);
    } catch {
      setBoreholeData(null);
      setState("error");
      setMsg("No se pudo conectar al backend.");
    }
  }, [projectId, runId, setBoreholeData]);

  const handleToggle = () => {
    setShowBoreholes(!showBoreholes);
  };

  // FASE 13 — asimetría medida y reparada. Antes, la carga vivía DENTRO del
  // manejador del clic: la capa sólo tenía datos si el usuario había pulsado
  // este botón concreto. Cualquier otro camino que encendiera `showBoreholes`
  // —y el deshacer/rehacer es exactamente eso— dejaba el toggle en «ON» con
  // `boreholeData` en null: la capa encendida y vacía, sin error visible.
  //
  // Ahora los datos siguen al estado, venga de donde venga. Es la misma forma
  // que ya usaba `IsosurfaceControls`, con su mismo diferido por `setTimeout`
  // para no hacer setState síncrono dentro del efecto — pero SIN duplicar la
  // llamada en el manejador, que es lo que allí produce dos peticiones por clic.
  useEffect(() => {
    if (!(showBoreholes && model && projectId && runId)) return;
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [showBoreholes, model, projectId, runId, load]);

  if (!model) {
    return (
      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Carga un modelo 3D para ver los sondajes.
      </p>
    );
  }

  let status: { text: string; tone: "muted" | "warn" | "ok" } | null = null;
  if (state === "loading") {
    status = { text: "Cargando sondajes…", tone: "muted" };
  } else if (state === "error") {
    status = { text: msg ?? "Error al pedir sondajes.", tone: "warn" };
  } else if (state === "ok" && boreholeData) {
    if (boreholeData.error) {
      status = { text: boreholeData.error, tone: "warn" };
    } else {
      status = {
        text: `${boreholeData.n_holes} pozo(s) · ${boreholeData.n_intervals} intervalo(s)`,
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
          showBoreholes
            ? "border-accent/60 bg-accent/15 text-accent"
            : "border-white/15 bg-white/[0.02] text-white/60 hover:text-white/85 hover:border-white/30"
        }`}
      >
        {showBoreholes ? "Sondajes: ON" : "Sondajes: OFF"}
      </button>

      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        Cilindros por litología (o densidad). Se dibujan donde el pozo cruza el
        cuerpo. Requiere haber cargado el paquete con sondajes.
      </p>

      {status && <p className={`text-[8px] font-mono leading-relaxed ${toneClass}`}>{status.text}</p>}

      {showBoreholes && (
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
