"use client";

// ─── FASE 9 (H-10) — La vista que le faltaba a F7 ─────────────────────────────
//
// La auditoría midió que la fase F7 completa —licenciamiento local-first,
// exportación de diagnóstico y honestidad offline— no tenía **ninguna** interfaz:
// 5 endpoints sin un solo consumidor, y un gate declarado en verde porque midió
// el backend en vez del camino del usuario. Esta vista es ese camino.
//
// Es también donde vive la respuesta a «¿esto funciona sin internet?», que para
// un producto local-first vendido a consultores no es una curiosidad técnica sino
// el argumento de compra.

import React from "react";
import Panel from "../workspace/Panel";
import LicensePanel from "../sistema/LicensePanel";
import DiagnosticsPanel from "../sistema/DiagnosticsPanel";
import ConnectivityPanel from "../sistema/ConnectivityPanel";

export default function SistemaView() {
  return (
    <div className="h-full w-full overflow-y-auto custom-scrollbar animate-fadeIn">
      <div className="min-h-full flex flex-col gap-6 px-2 pb-8 pt-4" data-testid="sistema-view">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[#C2D8C4] shadow-[0_0_20px_rgba(194,216,196,0.8)]" />
          <h1 className="text-base font-black tracking-tight text-white">Sistema</h1>
          <span className="text-[11px] font-mono text-neutral-500">
            Licencia, diagnóstico y conexión — todo local, nada se envía solo.
          </span>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <Panel title="Licencia" subtitle="Verificación local (Ed25519), sin servidor">
            <LicensePanel />
          </Panel>

          <Panel title="Conexión" subtitle="Qué necesita internet y qué no">
            <ConnectivityPanel />
          </Panel>

          <Panel
            title="Diagnóstico"
            subtitle="Paquete de soporte sin datos de survey"
            className="xl:col-span-2"
          >
            <DiagnosticsPanel />
          </Panel>
        </div>
      </div>
    </div>
  );
}
