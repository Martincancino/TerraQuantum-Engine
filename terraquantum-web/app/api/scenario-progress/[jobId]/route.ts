import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  const record = data as Record<string, unknown>;

  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;

  return null;
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await context.params;

    const result = await fetchBackendJson({
      path: `/scenario-progress/${encodeURIComponent(jobId)}`,
      method: "GET",
      timeoutMs: 30_000,
    });

    if (!result.ok) {
      return NextResponse.json(
        {
          detail: readBackendMessage(result.data) || "Failed to fetch scenario progress",
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
        : "Internal Server Error in scenario-progress API Route";

    console.error("Route error (/scenario-progress/[jobId]):", error);

    return NextResponse.json(
      { detail: message },
      { status: 500 }
    );
  }
}
