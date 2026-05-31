import { NextResponse } from "next/server";
import { fetchBackendJson, type JsonValue } from "../_lib/backend";

function getBackendDetail(data: JsonValue) {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const detail = data.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }

  return "No se pudo listar proyectos y corridas.";
}

export async function GET() {
  try {
    const result = await fetchBackendJson({
      path: "/project-runs",
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
        : "Error desconocido listando proyectos y corridas.";

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
