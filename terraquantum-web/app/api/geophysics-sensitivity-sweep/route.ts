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
  let body: unknown;

  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { detail: "Body JSON inválido para sensitivity sweep." },
      { status: 400 }
    );
  }

  const result = await fetchBackendJson({
    path: "/geophysics-sensitivity-sweep",
    method: "POST",
    body,
    // El sweep corre hasta 9 inversiones completas (LSQR+GPCG ~6s c/u) sobre la
    // malla activa; con kernel build + diagnósticos supera los 90s previos y daba
    // timeout. 5 min da margen holgado para un análisis on-demand.
    timeoutMs: 300_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail:
          readBackendMessage(result.data) ||
          "El backend Python rechazó el sensitivity sweep geofísico.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, {
    status: result.status,
  });
}
