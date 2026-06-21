// FASE 23 — Contrato de errores accionables (frontend).
//
// Espeja el contrato del backend (core/errors.py · TerraquantumError):
//   • to_dict()          → { code, severity, user_message, technical_details, suggested_action }
//   • to_error_details() → { code, message, source, stage, details:{ ...technical_details,
//                                                                     severity, suggested_action } }
//
// Este módulo NO inventa mensajes ni física: sólo NORMALIZA lo que el backend
// envía a una forma única (`TQErrorView`) que consume el modal (Regla de Oro —
// el frontend visualiza, no calcula). Si la respuesta no trae el contrato rico,
// degradamos con elegancia a un error genérico mínimamente accionable.

export type TQErrorSeverity = "error" | "warning" | "info";

/** Forma normalizada que consumen ErrorModal / WarningBanner. */
export interface TQErrorView {
  code: string;
  severity: TQErrorSeverity;
  userMessage: string;
  suggestedAction: string;
  /** Diagnósticos técnicos (cond(A), SNR, iteraciones, conteos…). */
  technicalDetails: Record<string, unknown>;
  source?: string | null;
  stage?: string | null;
}

const VALID_SEVERITIES: ReadonlySet<string> = new Set(["error", "warning", "info"]);

const FALLBACK_MESSAGE =
  "Ocurrió un error inesperado al procesar tu solicitud. Tus datos no se perdieron; " +
  "el detalle técnico quedó registrado para diagnóstico.";

const FALLBACK_ACTION =
  "Reintenta la operación. Si el problema persiste, descarga el registro de error y " +
  "compártelo con soporte para una revisión detallada.";

function coerceSeverity(value: unknown): TQErrorSeverity {
  return typeof value === "string" && VALID_SEVERITIES.has(value)
    ? (value as TQErrorSeverity)
    : "error";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function firstString(...candidates: unknown[]): string | null {
  for (const c of candidates) {
    if (typeof c === "string" && c.trim().length > 0) return c;
  }
  return null;
}

/**
 * Normaliza cualquier payload de error del backend a `TQErrorView`.
 *
 * Acepta, en orden de preferencia:
 *   1. El dict de `to_dict()`            (user_message / suggested_action / technical_details)
 *   2. El `error_details` de `to_error_details()` (message + details anidados)
 *   3. Un string suelto o `{ detail }` / `{ error }` legacy → error genérico accionable.
 */
export function parseBackendError(
  raw: unknown,
  fallbackMessage?: string,
): TQErrorView {
  // Caso 3a: string suelto.
  if (typeof raw === "string") {
    return {
      code: "TQ_INTERNAL",
      severity: "error",
      userMessage: raw.trim() || fallbackMessage || FALLBACK_MESSAGE,
      suggestedAction: FALLBACK_ACTION,
      technicalDetails: {},
    };
  }

  const obj = asRecord(raw);

  // Algunas respuestas anidan el contrato bajo error_details / errorDetails.
  const nested = asRecord(obj.error_details ?? obj.errorDetails);
  const root = Object.keys(nested).length > 0 ? nested : obj;

  // `details` existe en el shape error_details; technical_details en to_dict().
  const details = asRecord(root.details ?? root.technical_details);

  const userMessage =
    firstString(
      root.user_message,
      root.message,
      obj.detail,
      obj.error,
      fallbackMessage,
    ) ?? FALLBACK_MESSAGE;

  const suggestedAction =
    firstString(root.suggested_action, details.suggested_action) ?? FALLBACK_ACTION;

  const severity = coerceSeverity(root.severity ?? details.severity);

  const code = firstString(root.code) ?? "TQ_INTERNAL";

  // technical_details sin las claves de control que el backend mete en `details`.
  const technicalDetails: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(details)) {
    if (k === "severity" || k === "suggested_action") continue;
    technicalDetails[k] = v;
  }

  return {
    code,
    severity,
    userMessage,
    suggestedAction,
    technicalDetails,
    source: firstString(root.source) ?? null,
    stage: firstString(root.stage) ?? null,
  };
}

/**
 * Conveniencia para los paneles cuyo cliente API devuelve `error` como STRING
 * (buildPackage / loadPackage). El backend puede mandar el detail como contrato
 * JSON serializado; intentamos parsearlo para recuperar los campos ricos (code,
 * suggested_action, technical_details). Si es un string plano, degrada al error
 * genérico accionable de `parseBackendError`. No inventa nada: solo normaliza.
 */
export function errorViewFromString(
  message: string | null | undefined,
  fallbackMessage?: string,
): TQErrorView {
  const raw = (message ?? "").trim();
  if (raw.startsWith("{") || raw.startsWith("[")) {
    try {
      return parseBackendError(JSON.parse(raw), fallbackMessage ?? raw);
    } catch {
      /* no era JSON: cae al string plano */
    }
  }
  return parseBackendError(raw, fallbackMessage);
}

/** Etiqueta y paleta por severidad (consumidas por el modal y el banner). */
export const SEVERITY_META: Record<
  TQErrorSeverity,
  { label: string; icon: string; accent: string; border: string; bg: string; text: string }
> = {
  error: {
    label: "Error",
    icon: "✕",
    accent: "#ef4444",
    border: "border-red-900/50",
    bg: "bg-red-950/20",
    text: "text-red-400",
  },
  warning: {
    label: "Advertencia",
    icon: "⚠",
    accent: "#eab308",
    border: "border-yellow-700/50",
    bg: "bg-yellow-950/20",
    text: "text-yellow-400",
  },
  info: {
    label: "Información",
    icon: "ℹ",
    accent: "#38bdf8",
    border: "border-sky-800/50",
    bg: "bg-sky-950/20",
    text: "text-sky-400",
  },
};
