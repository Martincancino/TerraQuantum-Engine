"use client";

// FASE 23 — Modal de error accionable (3 pestañas: RESUMEN / DETALLES / ACCIÓN).
//
// Consume el contrato `TQErrorView` (lib/terraquantum/errorContract) que el
// backend produce con TerraquantumError.to_dict(). El modal SOLO visualiza: no
// calcula física ni inventa diagnósticos (Regla de Oro). Todo el texto (mensaje
// en español, detalles técnicos, acción sugerida) viene del backend.
//
// Uso típico (en cualquier vista cliente):
//   const [err, setErr] = useState<TQErrorView | null>(null);
//   ...catch → setErr(parseBackendError(res.error_details ?? res.error));
//   {err && <ErrorModal error={err} onClose={() => setErr(null)} />}

import { useState } from "react";
import {
  SEVERITY_META,
  type TQErrorView,
} from "../lib/terraquantum/errorContract";
import { DIAGNOSTICS_EXPORT_URL } from "../lib/terraquantum/systemApi";

type Tab = "resumen" | "detalles" | "accion";

type Props = {
  error: TQErrorView;
  onClose: () => void;
  /** Texto opcional para el botón primario (p. ej. "Reintentar"). */
  onRetry?: () => void;
  /** Si se entrega, se muestra botón "Descargar registro" con este JSON. */
  errorLogFilename?: string;
};

function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    // Notación científica para magnitudes extremas (cond(A), etc.).
    if (Number.isFinite(value) && (Math.abs(value) >= 1e5 || (value !== 0 && Math.abs(value) < 1e-3))) {
      return value.toExponential(2);
    }
    return String(value);
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export default function ErrorModal({
  error,
  onClose,
  onRetry,
  errorLogFilename,
}: Props) {
  const [tab, setTab] = useState<Tab>("resumen");
  const meta = SEVERITY_META[error.severity];
  const detailEntries = Object.entries(error.technicalDetails ?? {});

  function downloadLog() {
    const payload = {
      code: error.code,
      severity: error.severity,
      user_message: error.userMessage,
      suggested_action: error.suggestedAction,
      technical_details: error.technicalDetails,
      source: error.source ?? null,
      stage: error.stage ?? null,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = errorLogFilename || `tq_error_${error.code.toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "resumen", label: "RESUMEN" },
    { id: "detalles", label: "DETALLES" },
    { id: "accion", label: "ACCIÓN" },
  ];

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`${meta.label}: ${error.code}`}
      onClick={onClose}
    >
      <div
        className={`w-full max-w-lg rounded-lg border ${meta.border} bg-[#0b0f0d] shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cabecera */}
        <div className={`flex items-center justify-between gap-3 border-b ${meta.border} px-5 py-3`}>
          <div className="flex items-center gap-2 min-w-0">
            <span className={`text-lg ${meta.text}`} aria-hidden>
              {meta.icon}
            </span>
            <div className="min-w-0">
              <p className={`text-sm font-bold uppercase tracking-wide ${meta.text} truncate`}>
                {meta.label}
              </p>
              <p className="text-[9px] font-mono uppercase tracking-[0.2em] text-white/40">
                {error.code}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded px-2 py-1 text-white/50 hover:bg-white/10 hover:text-white"
            aria-label="Cerrar"
          >
            ✕
          </button>
        </div>

        {/* Pestañas */}
        <div className="flex border-b border-white/10">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-widest transition-colors ${
                tab === t.id
                  ? `${meta.text} border-b-2`
                  : "text-white/40 hover:text-white/70"
              }`}
              style={tab === t.id ? { borderColor: meta.accent } : undefined}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Contenido */}
        <div className="max-h-[50vh] overflow-y-auto px-5 py-4">
          {tab === "resumen" && (
            <p className="text-sm leading-relaxed text-white/85">{error.userMessage}</p>
          )}

          {tab === "detalles" && (
            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-white/40">
                Diagnósticos técnicos
              </p>
              {detailEntries.length === 0 ? (
                <p className="text-xs text-white/50">
                  No hay diagnósticos técnicos adicionales para este caso.
                </p>
              ) : (
                <dl className="space-y-1 font-mono text-xs">
                  {detailEntries.map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4 border-b border-white/5 py-1">
                      <dt className="text-white/50">{k}</dt>
                      <dd className="text-right text-white/85 break-all">
                        {formatDetailValue(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {(error.source || error.stage) && (
                <p className="mt-3 text-[10px] font-mono text-white/30">
                  {error.source ? `origen: ${error.source}` : ""}
                  {error.source && error.stage ? " · " : ""}
                  {error.stage ? `etapa: ${error.stage}` : ""}
                </p>
              )}
            </div>
          )}

          {tab === "accion" && (
            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-white/40">
                Próximos pasos
              </p>
              <p className="text-sm leading-relaxed text-white/85">{error.suggestedAction}</p>
            </div>
          )}
        </div>

        {/* Pie */}
        <div className={`flex flex-wrap items-center justify-end gap-2 border-t ${meta.border} px-5 py-3`}>
          {/* FASE 9 (H-10): «Descargar registro» sólo guarda ESTE error. Cuando
              el consultor tiene que pedir soporte hace falta el contexto —
              versiones, config saneada, conectividad, tier, cola de errores— y
              ese paquete existía en el backend desde F7 sin ninguna forma de
              pedirlo. Es una descarga local: no se envía nada a ningún sitio. */}
          <a
            data-testid="error-modal-export-diagnostics"
            href={DIAGNOSTICS_EXPORT_URL}
            download
            title="Descarga un ZIP con versiones, configuración saneada y últimos errores. Sin datos de survey ni claves."
            className="rounded border border-white/15 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-white/60 hover:bg-white/5 hover:text-white"
          >
            Exportar diagnóstico
          </a>
          <button
            type="button"
            onClick={downloadLog}
            className="rounded border border-white/15 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-white/60 hover:bg-white/5 hover:text-white"
          >
            Descargar registro
          </button>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-black"
              style={{ backgroundColor: meta.accent }}
            >
              Reintentar
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-white/15 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-white/80 hover:bg-white/5"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
