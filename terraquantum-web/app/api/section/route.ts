import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;
  return null;
}

/**
 * Proxy a GET /v2/section del backend (Fase F4.3 — cara del corte pintada).
 *
 * El raster de contraste viene calculado y ya en coordenadas del visor; aquí
 * solo se reenvía. El frontend NO calcula física ni coordenadas.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");
  const axis = searchParams.get("axis");
  const position = searchParams.get("position");
  const field = searchParams.get("field") ?? "density";

  if (!projectId || !runId || !axis || position === null) {
    return NextResponse.json(
      { detail: "project_id, run_id, axis y position son requeridos." },
      { status: 400 }
    );
  }

  const backendParams = new URLSearchParams({
    project_id: projectId,
    run_id: runId,
    axis,
    position,
    field,
  });

  const result = await fetchBackendJson({
    path: `/v2/section?${backendParams.toString()}`,
    method: "GET",
    timeoutMs: 30_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: readBackendMessage(result.data) || "No se pudo cargar la sección.",
        backendStatus: result.status,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
