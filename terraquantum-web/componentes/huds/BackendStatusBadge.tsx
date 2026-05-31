"use client";

import React, { useEffect, useState } from "react";

type SystemCheck = {
  online: boolean;
  backendUrl: string;
  health?: {
    ok: boolean;
    status: number;
    data?: {
      status?: string;
      service?: string;
    };
  };
  routes?: {
    health: boolean;
    geophysicsInvert: boolean;
    blockModel: boolean;
    generate: boolean;
  };
  routesReady?: boolean;
  blockModel?: {
    ok: boolean;
    status: number;
    ready: boolean;
    cells: number;
    visualMode: string | null;
    domainL: number;
    domainH: number;
    domainW: number;
    error: string | null;
  };
  summary?: {
    status: string;
    message: string;
  };
};

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <div
      className={`w-1.5 h-1.5 rounded-full ${
        ok ? "bg-[#C2D8C4]" : "bg-red-500"
      }`}
    />
  );
}

export default function BackendStatusBadge() {
  const [check, setCheck] = useState<SystemCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const runCheck = async () => {
    try {
      const res = await fetch("/api/system-check", {
        method: "GET",
        cache: "no-store",
      });

      const data = (await res.json()) as SystemCheck;
      setCheck(data);
    } catch (error: unknown) {
      setCheck({
        online: false,
        backendUrl: "unknown",
        summary: {
          status: "ERROR",
          message:
            error instanceof Error
              ? error.message
              : "No se pudo consultar system-check.",
        },
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runCheck();

    const interval = window.setInterval(() => {
      runCheck();
    }, 8000);

    return () => window.clearInterval(interval);
  }, []);

  const online = Boolean(check?.online);
  const routesReady = Boolean(check?.routesReady);
  const blockReady = Boolean(check?.blockModel?.ready);

  const label = loading
    ? "Backend: checking"
    : online
    ? "System Ready"
    : "Backend Offline";

  return (
    <div className="absolute top-6 left-6 z-20 pointer-events-auto">
      <button
        onClick={() => setExpanded((prev) => !prev)}
        title={check?.backendUrl || "Backend status"}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border backdrop-blur-md transition-all ${
          online
            ? "bg-black/50 border-neutral-800 hover:border-[#C2D8C4]/50"
            : "bg-red-950/60 border-red-500/40 hover:border-red-400"
        }`}
      >
        <div
          className={`w-1.5 h-1.5 rounded-full ${
            loading
              ? "bg-yellow-400 animate-pulse"
              : online
              ? "bg-[#C2D8C4] animate-pulse"
              : "bg-red-500 animate-pulse"
          }`}
        />

        <span
          className={`text-[8px] uppercase tracking-widest font-bold ${
            online ? "text-[#C2D8C4]" : "text-red-300"
          }`}
        >
          {label}
        </span>
      </button>

      {expanded && (
        <div className="mt-3 w-[290px] bg-black/90 border border-neutral-800 rounded-2xl p-4 shadow-2xl backdrop-blur-xl">
          <div className="flex justify-between items-start border-b border-neutral-800 pb-3 mb-3">
            <div>
              <p className="text-[9px] uppercase tracking-widest text-white font-bold">
                System Diagnostics
              </p>
              <p className="text-[8px] text-neutral-500 font-mono mt-1 break-all">
                {check?.backendUrl || "Backend URL no disponible"}
              </p>
            </div>

            <span
              className={`text-[8px] px-2 py-1 rounded font-bold uppercase ${
                online
                  ? "bg-[#C2D8C4]/10 text-[#C2D8C4]"
                  : "bg-red-500/10 text-red-300"
              }`}
            >
              {check?.summary?.status || "UNKNOWN"}
            </span>
          </div>

          <div className="space-y-2 text-[9px] font-mono">
            <div className="flex items-center justify-between">
              <span className="text-neutral-400">Backend /health</span>
              <div className="flex items-center gap-2">
                <StatusDot ok={Boolean(check?.health?.ok)} />
                <span
                  className={
                    check?.health?.ok ? "text-[#C2D8C4]" : "text-red-300"
                  }
                >
                  {check?.health?.ok ? "OK" : "FAIL"}
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-neutral-400">Rutas críticas</span>
              <div className="flex items-center gap-2">
                <StatusDot ok={routesReady} />
                <span className={routesReady ? "text-[#C2D8C4]" : "text-red-300"}>
                  {routesReady ? "OK" : "FAIL"}
                </span>
              </div>
            </div>

            <div className="pl-3 space-y-1 border-l border-neutral-800">
              <div className="flex items-center justify-between">
                <span className="text-neutral-500">/geophysics-invert</span>
                <StatusDot ok={Boolean(check?.routes?.geophysicsInvert)} />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-neutral-500">/block-model</span>
                <StatusDot ok={Boolean(check?.routes?.blockModel)} />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-neutral-500">/generate</span>
                <StatusDot ok={Boolean(check?.routes?.generate)} />
              </div>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-neutral-800">
              <span className="text-neutral-400">Block Model</span>
              <div className="flex items-center gap-2">
                <StatusDot ok={blockReady} />
                <span className={blockReady ? "text-[#C2D8C4]" : "text-yellow-300"}>
                  {blockReady ? "READY" : "EMPTY"}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-2">
              <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-2">
                <p className="text-neutral-500 uppercase text-[7px]">Cells</p>
                <p className="text-white text-[10px]">
                  {check?.blockModel?.cells ?? 0}
                </p>
              </div>

              <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-2">
                <p className="text-neutral-500 uppercase text-[7px]">Mode</p>
                <p className="text-white text-[10px] truncate">
                  {check?.blockModel?.visualMode || "N/A"}
                </p>
              </div>
            </div>

            {check?.summary?.message && (
              <p className="pt-3 text-[8px] text-neutral-500 leading-relaxed border-t border-neutral-800">
                {check.summary.message}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}