import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL } from "../../_lib/backend";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const backendUrl = `${BACKEND_URL}/v2/geophysics-status/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}/stream`;

  try {
    const apiKey = process.env.TQ_API_KEY ?? "";
    const upstream = await fetch(backendUrl, {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
        ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
      },
      cache: "no-store",
    });

    if (!upstream.ok) {
      return NextResponse.json(
        { detail: `Backend SSE error (HTTP ${upstream.status})` },
        { status: upstream.status }
      );
    }

    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[geophysics-status/stream] proxy error:", message);
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
