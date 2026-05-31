import { NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  const record = data as Record<string, unknown>;

  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;

  return null;
}

export async function GET() {
  const result = await fetchBackendJson({
    path: "/health",
    method: "GET",
    timeoutMs: 5_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        online: false,
        detail:
          readBackendMessage(result.data) ||
          "No se pudo conectar con backend Python.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: 200 }
    );
  }

  return NextResponse.json(
    {
      online: true,
      backendStatus: result.status,
      backendUrl: result.backendUrl,
      data: result.data,
    },
    { status: 200 }
  );
}
