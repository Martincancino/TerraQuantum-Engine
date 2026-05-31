import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  const record = data as Record<string, unknown>;

  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;

  return null;
}

export async function GET(req: NextRequest) {
  const projectId = req.nextUrl.searchParams.get("project_id");

  if (!projectId) {
    return NextResponse.json({ detail: "project_id requerido" }, { status: 400 });
  }

  const result = await fetchBackendJson({
    path: `/projects/${encodeURIComponent(projectId)}/terrain`,
    method: "GET",
    timeoutMs: 30_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: readBackendMessage(result.data) || "No se pudo leer el terreno.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
