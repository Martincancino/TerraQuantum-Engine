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
  try {
    const body = await req.json();

    const result = await fetchBackendJson({
      path: "/scenario-sweep",
      method: "POST",
      body,
      timeoutMs: 180_000,
    });

    if (!result.ok) {
      return NextResponse.json(
        {
          detail:
            readBackendMessage(result.data) ||
            "Failed to start scenario sweep",
          backendStatus: result.status,
          backendUrl: result.backendUrl,
          backendDetails: result.data,
        },
        { status: result.status || 500 }
      );
    }

    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const message =
      error instanceof Error
        ? error.message
        : "Internal Server Error in scenario-sweep API Route";

    console.error("Route error (/scenario-sweep):", error);

    return NextResponse.json(
      { detail: message },
      { status: 500 }
    );
  }
}
