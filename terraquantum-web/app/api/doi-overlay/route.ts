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
 * Proxy a GET /v2/doi-overlay del backend (Fase F4.5 — incertidumbre visible).
 *
 * El horizonte DOI viene calculado (convención B2) y en coordenadas del visor;
 * aquí solo se reenvía. El frontend NO calcula física.
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
    path: `/v2/doi-overlay?${backendParams.toString()}`,
    method: "GET",
    timeoutMs: 30_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) || "No se pudo cargar el horizonte DOI.",
        backendStatus: result.status,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
