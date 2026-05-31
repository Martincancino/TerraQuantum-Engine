import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  const record = data as Record<string, unknown>;

  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;

  return null;
}

export async function POST(req: NextRequest) {
  const body = await req.json();

  const result = await fetchBackendJson({
    path: "/geophysics-invert",
    method: "POST",
    body,
    timeoutMs: 90_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) ||
          "El backend Python rechazó la inversión geofísica.",
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
}
