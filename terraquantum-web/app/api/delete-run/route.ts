import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

/**
 * Fase 2 (H-21) — borrado de una corrida, ahora por proxy en vez de directo
 * desde el navegador.
 *
 * NOTA HONESTA (hallazgo de esta fase, no introducido por ella): el backend
 * **no expone hoy** `DELETE /projects/{id}/runs/{run_id}` — no existe ninguna
 * ruta de borrado en `api/`. La llamada devolvía 404 antes de este cambio y
 * sigue devolviendo 404 después; lo único que cambia es que ya no sale del
 * navegador. El proxy propaga el estado tal cual para que la interfaz muestre
 * el fallo en vez de fingir que borró algo. Queda anotado en la auditoría.
 */
export async function DELETE(req: NextRequest) {
  const projectId = req.nextUrl.searchParams.get("project_id");
  const runId = req.nextUrl.searchParams.get("run_id");

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const result = await fetchBackendJson({
    path: `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`,
    method: "DELETE",
    timeoutMs: 20_000,
  });

  return NextResponse.json(result.data, { status: result.status || 502 });
}
