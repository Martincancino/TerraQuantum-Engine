import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL ||
  process.env.TERRAQUANTUM_BACKEND_URL ||
  "http://127.0.0.1:8010";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    
    const file = formData.get("file");
    const strict = formData.get("strict");
    const allow_g_raw = formData.get("allow_g_raw");
    const preview_limit = formData.get("preview_limit");
    
    const url = new URL(`${BACKEND_URL}/gravity-import/preview`);
    if (strict !== null) url.searchParams.append("strict", strict as string);
    if (allow_g_raw !== null) url.searchParams.append("allow_g_raw", allow_g_raw as string);
    if (preview_limit !== null) url.searchParams.append("preview_limit", preview_limit as string);

    const backendFormData = new FormData();
    if (file) {
      backendFormData.append("file", file);
    }

    const backendResponse = await fetch(url.toString(), {
      method: "POST",
      body: backendFormData,
    });

    const data = await backendResponse.json();

    if (!backendResponse.ok) {
      return NextResponse.json(
        { detail: data?.detail || "Error del backend importador", backendStatus: backendResponse.status },
        { status: backendResponse.status }
      );
    }

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    return NextResponse.json(
      { detail: "Error interno del proxy", error: message },
      { status: 500 }
    );
  }
}
