import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

// FASE 20 — BFF: proxya el parseo de CSV de sondajes al backend.
// El parseo/validación (unidades pies→m, auto-detección de columnas, tabla
// petrofísica) vive en el backend; aquí solo se reenvía (Regla de Oro: el
// frontend no reimplementa la lógica de Python).

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;
  return null;
}

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Body JSON inválido." }, { status: 400 });
  }

  const result = await fetchBackendJson({
    path: "/borehole/parse-csv",
    method: "POST",
    body,
    timeoutMs: 60_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) ||
          "Error al parsear el CSV de sondajes.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
