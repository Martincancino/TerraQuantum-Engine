import { NextRequest, NextResponse } from "next/server";

// F2B — Separación regional-residual (producto de usuario). Proxy passthrough
// que respeta el content-type del backend: JSON (grillas para mapas) o
// text/csv (descarga por estación). Cero lógica aquí.

const BACKEND_URL =
  process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL ||
  process.env.TERRAQUANTUM_BACKEND_URL ||
  "http://127.0.0.1:8010";

export async function POST(req: NextRequest) {
  let bodyText: string;
  try {
    bodyText = await req.text();
    JSON.parse(bodyText);
  } catch {
    return NextResponse.json({ detail: "Body JSON inválido." }, { status: 400 });
  }
  try {
    const apiKey = process.env.TQ_API_KEY ?? "";
    const res = await fetch(`${BACKEND_URL}/gravity-corrections/regional-residual`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
      },
      body: bodyText,
      signal: AbortSignal.timeout(120_000),
    });
    const contentType = res.headers.get("content-type") ?? "application/json";
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: {
        "Content-Type": contentType,
        ...(res.headers.get("content-disposition")
          ? { "Content-Disposition": res.headers.get("content-disposition")! }
          : {}),
      },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    return NextResponse.json(
      { detail: "Error del proxy regional-residual", error: message },
      { status: 500 }
    );
  }
}
