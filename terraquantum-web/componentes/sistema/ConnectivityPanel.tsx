"use client";

// ─── FASE 9 (H-10) — Indicador de conectividad HONESTO ────────────────────────
//
// «Honesto» es la palabra que hace el trabajo. Dos cosas se dicen aquí y ninguna
// se adorna:
//
//  1. **El backend**: se comprueba de verdad con `/api/backend-health`, que
//     pregunta al proceso Python. No se deduce de `navigator.onLine` (que sólo
//     sabe si hay tarjeta de red) ni se asume.
//  2. **Las funciones que necesitan internet**: se listan tal como el backend
//     las declara, con el detalle de que este resumen **no sale a la red** —
//     describe configuración, no alcance real. La respuesta trae `probe_note`
//     explicándolo y se muestra en vez de inventar una explicación propia.
//
// El copiloto IA se declara aparte porque su clave la pone el usuario en la
// interfaz (BYO-key): «no configurado en el servidor» NO significa «no se puede
// usar», y sin esa distinción el panel mentiría por omisión.

import { useEffect, useState } from "react";
import {
  getBackendHealth,
  getConnectivity,
  type BackendHealth,
  type ConnectivitySummary,
} from "../../lib/terraquantum/systemApi";

export default function ConnectivityPanel() {
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ConnectivitySummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const [h, c] = await Promise.all([getBackendHealth(), getConnectivity()]);
      if (!alive) return;
      if (h.ok && h.data) {
        setHealth(h.data);
        setHealthError(null);
      } else {
        setHealth(null);
        setHealthError(h.error ?? "No se pudo comprobar el backend.");
      }
      if (c.ok && c.data) {
        setSummary(c.data);
        setSummaryError(null);
      } else {
        setSummary(null);
        setSummaryError(c.error ?? "No se pudo leer el estado de conectividad.");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const backendOnline = health?.online === true;

  return (
    <div className="flex flex-col gap-4" data-testid="connectivity-panel">
      {/* ── Motor de cálculo ───────────────────────────────────────────────── */}
      <div className="flex items-start gap-2.5">
        <span
          className={`mt-1 h-2 w-2 rounded-full shrink-0 ${
            backendOnline ? "bg-[#C2D8C4] shadow-[0_0_8px_rgba(194,216,196,0.8)]" : "bg-red-500"
          }`}
        />
        <div className="min-w-0">
          <p
            data-testid="connectivity-backend-state"
            className="text-[10px] uppercase tracking-[0.18em] font-bold text-white/85"
          >
            {backendOnline ? "Motor de cálculo conectado" : "Motor de cálculo no responde"}
          </p>
          <p className="text-[9px] font-mono text-white/40 mt-1 leading-relaxed break-all">
            {backendOnline
              ? `${health?.backendUrl ?? "backend"} · versión ${
                  (health?.data?.version as string | undefined) ?? "—"
                }`
              : healthError ?? health?.detail ?? "Sin detalle del backend."}
          </p>
        </div>
      </div>

      {/* ── Camino dorado ──────────────────────────────────────────────────── */}
      {summary && (
        <div className="rounded-lg border border-[#C2D8C4]/25 bg-[#C2D8C4]/[0.05] px-3 py-2">
          <p className="text-[9px] uppercase tracking-[0.16em] text-[#C2D8C4] font-bold">
            {summary.golden_path_offline
              ? "El flujo principal funciona sin internet"
              : "El flujo principal requiere internet"}
          </p>
          <p className="text-[9px] text-white/55 mt-1 leading-relaxed">
            {summary.golden_path_note}
          </p>
        </div>
      )}

      {summaryError && (
        <p className="text-[10px] text-yellow-400/80 font-mono leading-relaxed">
          {summaryError}
        </p>
      )}

      {/* ── Funciones que salen a la red ───────────────────────────────────── */}
      {summary && (
        <div className="flex flex-col gap-2">
          <p className="text-[9px] uppercase tracking-[0.16em] text-white/40">
            Funciones que usan internet
          </p>
          {summary.online_features.map((f) => {
            // Tres estados distintos, y confundirlos es la mentira que este panel
            // existe para evitar:
            //   · no necesita internet          → verde, nada que hacer
            //   · BYO-key sin clave en servidor → neutro: se usa desde la interfaz
            //   · necesita internet y no está   → ámbar: opcional, con fallback
            const offline = !f.requires_internet;
            const byoKey = f.user_supplied_key === true && !f.configured;
            const tone = offline
              ? "border-[#C2D8C4]/30 text-[#C2D8C4]"
              : f.configured
              ? "border-[#C2D8C4]/25 text-[#C2D8C4]/85"
              : byoKey
              ? "border-white/15 text-white/60"
              : "border-yellow-500/30 text-yellow-400/85";
            const label = offline
              ? "offline"
              : f.configured
              ? "configurada"
              : byoKey
              ? "clave desde la interfaz"
              : "sin configurar";

            return (
              <div
                key={f.key}
                data-testid={`connectivity-feature-${f.key}`}
                className={`rounded-lg border bg-white/[0.02] px-3 py-2 ${tone}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[10px] text-white/85 leading-tight min-w-0">{f.name}</p>
                  <span className="text-[8px] uppercase tracking-widest font-bold shrink-0">
                    {label}
                  </span>
                </div>
                <p className="text-[8.5px] text-white/45 mt-1.5 leading-relaxed">{f.message}</p>
                {f.requires_internet && !f.required_for_golden_path && (
                  <p className="text-[8px] text-white/30 mt-1">
                    No es requisito del flujo principal
                    {f.local_fallback ? " · tiene alternativa local." : "."}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── La letra pequeña que hace honesto al panel ─────────────────────── */}
      {summary?.probe_note && (
        <p
          data-testid="connectivity-probe-note"
          className="text-[8px] text-white/35 leading-relaxed border-t border-white/[0.06] pt-2"
        >
          {summary.probe_note}
        </p>
      )}
    </div>
  );
}
