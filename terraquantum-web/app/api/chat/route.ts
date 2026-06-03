import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../_lib/backend";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const result = await fetchBackendJson({
      path: "/api/chat",
      method: "POST",
      body,
      timeoutMs: 30_000,
    });

    if (!result.ok) {
      return NextResponse.json(result.data, { status: result.status });
    }

    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
