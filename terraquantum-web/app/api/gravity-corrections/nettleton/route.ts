import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

// F2B — Barrido de Nettleton (densidad de reducción óptima). Proxy fino:
// el barrido y la correlación viven en el backend; aquí solo se reenvía.
export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Body JSON inválido." }, { status: 400 });
  }
  const qs = req.nextUrl.searchParams.toString();
  const result = await fetchBackendJson({
    path: `/gravity-corrections/nettleton${qs ? `?${qs}` : ""}`,
    method: "POST",
    body,
    timeoutMs: 60_000,
  });
  return NextResponse.json(result.data, { status: result.status });
}
