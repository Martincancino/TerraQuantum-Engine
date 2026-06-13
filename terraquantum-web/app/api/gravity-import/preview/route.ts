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
    const data_type = formData.get("data_type");

    const url = new URL(`${BACKEND_URL}/gravity-import/preview`);
    if (strict !== null) url.searchParams.append("strict", strict as string);
    if (allow_g_raw !== null) url.searchParams.append("allow_g_raw", allow_g_raw as string);
    if (preview_limit !== null) url.searchParams.append("preview_limit", preview_limit as string);
    if (data_type !== null) url.searchParams.append("data_type", data_type as string);

    const backendFormData = new FormData();
    if (file) {
      backendFormData.append("file", file);
    }

    const apiKey = process.env.TQ_API_KEY ?? "";
    const backendResponse = await fetch(url.toString(), {
      method: "POST",
      body: backendFormData,
      headers: apiKey ? { "X-TQ-API-Key": apiKey } : undefined,
    });

    const rawText = await backendResponse.text();
    let data: unknown;
    try {
      data = JSON.parse(rawText);
    } catch {
      return NextResponse.json(
        { detail: "El backend no devolvió JSON válido.", raw: rawText.slice(0, 300) },
        { status: 502 }
      );
    }

    if (!backendResponse.ok) {
      const detail = (data as Record<string, unknown>)?.detail;
      const detailMsg = typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null
          ? (detail as Record<string, unknown>).message ?? JSON.stringify(detail)
          : "Error del backend importador";
      return NextResponse.json(
        { detail: detailMsg, backendStatus: backendResponse.status },
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
