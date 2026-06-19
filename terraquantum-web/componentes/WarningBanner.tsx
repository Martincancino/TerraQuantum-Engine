"use client";

// FASE 23 — Sistema de avisos inline (warnings / info no bloqueantes).
//
// A diferencia de ErrorModal (interrumpe el flujo ante un fallo), WarningBanner
// se renderiza embebido en una vista para señalar condiciones de severidad
// "warning" o "info" que NO detienen el proceso pero el usuario debe conocer:
//   ⚠️ "Calidad de datos baja (45%). Modelo menos confiable."
//   ⚠️ "Los sondajes sugieren densidad más baja. Revisa densidades."
//   ℹ️ "Convergencia lenta: 400/500 iteraciones."
//
// Solo visualiza el contrato `TQErrorView` que entrega el backend (Regla de Oro).

import {
  SEVERITY_META,
  type TQErrorView,
} from "../lib/terraquantum/errorContract";

type Props = {
  /** Lista de avisos (severity "warning" o "info"). Los "error" se ignoran:
   *  un error bloqueante debe ir por ErrorModal, no por un banner inline. */
  warnings: TQErrorView[];
  /** Si se entrega, cada aviso muestra una "x" para descartarlo. */
  onDismiss?: (code: string) => void;
  /** Muestra la acción sugerida bajo el mensaje (default: true). */
  showAction?: boolean;
};

export default function WarningBanner({
  warnings,
  onDismiss,
  showAction = true,
}: Props) {
  const visible = warnings.filter((w) => w.severity !== "error");
  if (visible.length === 0) return null;

  return (
    <div className="space-y-2">
      {visible.map((w) => {
        const meta = SEVERITY_META[w.severity];
        return (
          <div
            key={w.code}
            className={`flex items-start gap-2 rounded border ${meta.border} ${meta.bg} px-3 py-2`}
            role="status"
          >
            <span className={`mt-0.5 text-sm ${meta.text}`} aria-hidden>
              {meta.icon}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-relaxed text-white/85">{w.userMessage}</p>
              {showAction && w.suggestedAction && (
                <p className="mt-1 text-[11px] leading-relaxed text-white/55">
                  {w.suggestedAction}
                </p>
              )}
            </div>
            {onDismiss && (
              <button
                type="button"
                onClick={() => onDismiss(w.code)}
                className="shrink-0 rounded px-1 text-white/40 hover:bg-white/10 hover:text-white"
                aria-label="Descartar aviso"
              >
                ✕
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
