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
 * Proxy a GET /v2/isosurface del backend (Fase F4.1).
 *
 * Las mallas ya vienen en el espacio visual de Three.js (centrado + flip-Y) y con
 * arrays base64; aquí solo se reenvía el JSON. El frontend NO calcula física.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");
  const field = searchParams.get("field") || "density";

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const backendParams = new URLSearchParams({
    project_id: projectId,
    run_id: runId,
    field,
  });
  const levels = searchParams.get("levels");
  if (levels) backendParams.set("levels", levels);
  const taubin = searchParams.get("taubin_iterations");
  if (taubin) backendParams.set("taubin_iterations", taubin);

  const result = await fetchBackendJson({
    path: `/v2/isosurface?${backendParams.toString()}`,
    method: "GET",
    timeoutMs: 90_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) ||
          "No se pudieron construir las isosuperficies.",
        backendStatus: result.status,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
