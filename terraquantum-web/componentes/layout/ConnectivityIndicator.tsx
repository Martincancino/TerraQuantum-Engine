"use client";

// ─── FASE 9 — El estado de conexión, en la barra, y sin mentir ────────────────
//
// «Honesto» aquí significa tres cosas concretas:
//
//  1. Se COMPRUEBA. Pregunta a `/api/backend-health`, que a su vez habla con el
//     proceso Python. No se deduce de `navigator.onLine` —que sólo sabe si hay
//     tarjeta de red— ni se pinta un "Online" fijo como el que había cableado en
//     la vista del copiloto.
//  2. Distingue COMPROBANDO de CONECTADO. Mientras no hay respuesta el estado es
//     «comprobando», no «conectado»: dar por bueno lo que aún no se sabe es
//     exactamente la clase de optimismo que esta auditoría persigue.
//  3. Lo que informa es el MOTOR DE CÁLCULO, no internet. TerraQuantum es
//     local-first: quedarse sin internet no rompe el flujo principal, y un
//     indicador que dijera «desconectado» por eso asustaría sin motivo.

import { useEffect, useState } from "react";
import { getBackendHealth } from "../../lib/terraquantum/systemApi";
import { useAppStore } from "../../store/useAppStore";

type Estado = "comprobando" | "conectado" | "caido";

/** Cada cuánto se vuelve a preguntar. Barato (un GET a localhost) y suficiente
 *  para notar que el sidecar se cayó sin convertir la barra en un ping-flood. */
const INTERVALO_MS = 20_000;

export default function ConnectivityIndicator() {
  const [estado, setEstado] = useState<Estado>("comprobando");
  const [detalle, setDetalle] = useState<string>("Comprobando el motor de cálculo…");
  const setView = useAppStore((s) => s.setView);

  useEffect(() => {
    let alive = true;

    async function comprobar() {
      const res = await getBackendHealth();
      if (!alive) return;
      if (res.ok && res.data?.online === true) {
        setEstado("conectado");
        setDetalle(
          `Motor de cálculo conectado · ${res.data.backendUrl ?? "backend local"}`,
        );
      } else {
        setEstado("caido");
        setDetalle(
          res.data?.detail ??
            res.error ??
            "El motor de cálculo no responde. La inversión no podrá ejecutarse.",
        );
      }
    }

    void comprobar();
    const timer = window.setInterval(() => void comprobar(), INTERVALO_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const color =
    estado === "conectado"
      ? "bg-[#C2D8C4] shadow-[0_0_8px_rgba(194,216,196,0.7)]"
      : estado === "caido"
      ? "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.7)]"
      : "bg-neutral-500";

  const texto =
    estado === "conectado" ? "motor ok" : estado === "caido" ? "motor caído" : "comprobando";

  return (
    <button
      type="button"
      data-testid="connectivity-indicator"
      data-estado={estado}
      onClick={() => setView("sistema")}
      title={detalle}
      aria-label={detalle}
      className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest transition-colors text-neutral-500 hover:text-white"
    >
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${color}`} />
      <span className="hidden sm:inline">{texto}</span>
    </button>
  );
}
