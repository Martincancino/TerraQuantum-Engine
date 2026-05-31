import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson, type JsonValue } from "../_lib/backend";

function getBackendDetail(data: JsonValue) {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const detail = data.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }

  return "No se pudo leer el score de favorabilidad.";
}

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const projectId = searchParams.get("project_id");
    const runId = searchParams.get("run_id");

    if (!projectId || !runId) {
      return NextResponse.json(
        {
          detail: "project_id y run_id son requeridos.",
          backendStatus: 400,
          backendUrl: null,
          backendDetails: null,
        },
        { status: 400 }
      );
    }

    const result = await fetchBackendJson({
      path: `/favorability/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`,
      method: "GET",
      timeoutMs: 30_000,
    });

    if (!result.ok) {
      return NextResponse.json(
        {
          detail: getBackendDetail(result.data),
          backendStatus: result.status,
          backendUrl: result.backendUrl,
          backendDetails: result.data,
        },
        { status: result.status }
      );
    }

    return NextResponse.json(result.data, {
      status: result.status,
    });
  } catch (error: unknown) {
    const detail =
      error instanceof Error
        ? error.message
        : "Error desconocido leyendo favorabilidad.";

    return NextResponse.json(
      {
        detail,
        backendStatus: 500,
        backendUrl: null,
        backendDetails: null,
      },
      { status: 500 }
    );
  }
}
