import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

// F3 — Cancela una corrida del flujo de paquete (worker de proceso en el
// backend: bandera cooperativa + terminate). Proxy fino, sin lógica.
export async function POST(req: NextRequest) {
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
      path: `/geophysics-cancel/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`,
      method: "POST",
      timeoutMs: 20_000,
    });

    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const detail =
      error instanceof Error ? error.message : "Error desconocido al cancelar.";
    return NextResponse.json({ detail }, { status: 500 });
  }
}
