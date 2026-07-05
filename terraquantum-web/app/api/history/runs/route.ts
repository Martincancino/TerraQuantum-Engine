import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

// F3 — Historial SQLite de corridas (estado real que sobrevive reinicios:
// done / error / cancelled / interrumpida). Proxy fino, sin lógica.
export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const projectId = searchParams.get("project_id");
    const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";

    const result = await fetchBackendJson({
      path: `/v2/history/runs${qs}`,
      method: "GET",
      timeoutMs: 15_000,
    });

    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const detail =
      error instanceof Error ? error.message : "Error leyendo el historial.";
    return NextResponse.json({ detail }, { status: 500 });
  }
}
