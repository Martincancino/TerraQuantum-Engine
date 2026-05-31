import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson, type JsonValue } from "../_lib/backend";

function getBackendDetail(data: JsonValue) {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const detail = data.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }

  return "No se pudieron comparar las corridas.";
}

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const baseProjectId = searchParams.get("base_project_id");
    const baseRunId = searchParams.get("base_run_id");
    const compareProjectId = searchParams.get("compare_project_id");
    const compareRunId = searchParams.get("compare_run_id");

    if (!baseProjectId || !baseRunId || !compareProjectId || !compareRunId) {
      return NextResponse.json(
        {
          detail:
            "base_project_id, base_run_id, compare_project_id y compare_run_id son requeridos.",
          backendStatus: 400,
          backendUrl: null,
          backendDetails: null,
        },
        { status: 400 }
      );
    }

    const backendParams = new URLSearchParams({
      base_project_id: baseProjectId,
      base_run_id: baseRunId,
      compare_project_id: compareProjectId,
      compare_run_id: compareRunId,
    });

    const result = await fetchBackendJson({
      path: `/compare-runs?${backendParams.toString()}`,
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
        : "Error desconocido comparando corridas.";

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
