import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

/**
 * Fase 2 (H-21) — el footprint del proyecto se pedía DIRECTO desde el navegador
 * con la URL del backend horneada en el bundle de cliente. Ahora pasa por el
 * proxy, que resuelve el backend en tiempo de ejecución (y por tanto sigue al
 * puerto alternativo cuando el 8010 está ocupado).
 */
export async function GET(req: NextRequest) {
  const projectId = req.nextUrl.searchParams.get("project_id");

  if (!projectId) {
    return NextResponse.json(
      { detail: "project_id es requerido." },
      { status: 400 }
    );
  }

  const result = await fetchBackendJson({
    path: `/projects/${encodeURIComponent(projectId)}/footprint`,
    method: "GET",
    timeoutMs: 15_000,
  });

  return NextResponse.json(result.data, { status: result.status || 502 });
}
