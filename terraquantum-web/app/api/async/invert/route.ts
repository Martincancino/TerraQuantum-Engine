import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const result = await fetchBackendJson({
      path: "/api/async/invert",
      method: "POST",
      body,
      timeoutMs: 10_000,
    });
    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[async/invert] proxy error:", message);
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
