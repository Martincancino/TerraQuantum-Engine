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
 * Proxy a GET /borehole/view del backend (Fase F4.4).
 *
 * Los sondajes ya vienen en coordenadas del visor 3D (centrado + flip-Y); aquí
 * solo se reenvía el JSON. El frontend NO calcula coordenadas ni física.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const backendParams = new URLSearchParams({
    project_id: projectId,
    run_id: runId,
  });

  const result = await fetchBackendJson({
    path: `/borehole/view?${backendParams.toString()}`,
    method: "GET",
    timeoutMs: 30_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) || "No se pudieron cargar los sondajes.",
        backendStatus: result.status,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
