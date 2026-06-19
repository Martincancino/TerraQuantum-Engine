import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

// FASE 21 — BFF: proxya el cálculo del plan de fusión multimodal al backend.
// El backend decide la ruta (combo), la confianza y el error de profundidad a
// partir de los CONTEOS de datos disponibles; el frontend no calcula física ni
// confianza (Regla de Oro: la decisión vive en Python).

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
    path: "/multimodal/plan",
    method: "POST",
    body,
    timeoutMs: 30_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) ||
          "Error al calcular el plan de fusión multimodal.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
