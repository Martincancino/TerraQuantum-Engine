// ─── FASE 1 (H-27) — Avisos de la corrida hacia la vista de resultados ───────
//
// El backend degrada en voz alta: cuando la interpolación de topografía falla y la
// inversión sigue con terreno plano, lo declara en `report.warnings[]` y en
// `report.technicalSummary.warnings[]`. Hasta ahora ese canal moría en el log
// estructurado y en el detalle de Historial: la vista donde se decide dónde
// perforar no mostraba nada.
//
// Este módulo NO calcula física ni interpreta: sólo extrae los textos que el
// backend ya emitió y los normaliza al contrato `TQErrorView` que consume
// WarningBanner. Si el backend no emite nada, aquí no se inventa nada.

import { getProjectRunDetail } from "./frontendApi";
import type { TQErrorView } from "./errorContract";

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  );
}

/** Textos de aviso de una corrida, sin duplicados y en orden estable.
 *  Acepta el `report` persistido (report.json) tal cual lo entrega el backend. */
export function extractRunWarnings(report: unknown): string[] {
  const rec = asRecord(report);
  if (!rec) return [];
  const technical = asRecord(rec.technicalSummary);
  const all = [...stringArray(rec.warnings), ...stringArray(technical?.warnings)];
  return Array.from(new Set(all.map((w) => w.trim())));
}

/** Adapta textos de aviso al contrato que renderiza WarningBanner. */
export function warningViewsFromTexts(texts: string[], limit = 8): TQErrorView[] {
  return texts.slice(0, limit).map((msg, i) => ({
    code: `RUN_WARNING_${i}`,
    severity: "warning" as const,
    userMessage: msg,
    suggestedAction: "",
    technicalDetails: {},
  }));
}

/** Igual, partiendo del `report` persistido de la corrida. */
export function runWarningViews(report: unknown, limit = 8): TQErrorView[] {
  return warningViewsFromTexts(extractRunWarnings(report), limit);
}

/** El `report` persistido de una corrida, o `null` si no se pudo leer.
 *  FASE 9: la vista 3D necesita del mismo documento DOS señales (los avisos y si
 *  el solver convergió). Se expone la lectura para no pedir el detalle dos veces
 *  ni duplicar el manejo de errores. */
export async function fetchRunReport(
  projectId: string,
  runId: string,
): Promise<Record<string, unknown> | null> {
  const res = await getProjectRunDetail(projectId, runId);
  if (!res.ok || !res.data) return null;
  return asRecord(asRecord(res.data)?.report);
}

/** Carga el reporte persistido de una corrida y devuelve sus avisos.
 *  Devuelve [] ante cualquier fallo: un aviso que no llega nunca debe romper
 *  la vista, pero tampoco se sustituye por un texto inventado. */
export async function fetchRunWarnings(
  projectId: string,
  runId: string,
): Promise<string[]> {
  return extractRunWarnings(await fetchRunReport(projectId, runId));
}
