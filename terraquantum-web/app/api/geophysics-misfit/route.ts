import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const projectId = searchParams.get("project_id");
    const runId = searchParams.get("run_id");

    if (!projectId || !runId) {
      return NextResponse.json(
        { detail: "project_id y run_id son requeridos." },
        { status: 400 }
      );
    }

    const result = await fetchBackendJson({
      path: `/geophysics-misfit/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`,
      method: "GET",
      timeoutMs: 30_000,
    });

    if (!result.ok) {
      return NextResponse.json(
        {
          detail: "Error al leer datos obs vs calc.",
          backendStatus: result.status,
          backendDetails: result.data,
        },
        { status: result.status }
      );
    }

    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const detail =
      error instanceof Error ? error.message : "Error desconocido.";
    return NextResponse.json({ detail }, { status: 500 });
  }
}
