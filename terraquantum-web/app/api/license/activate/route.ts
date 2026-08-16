import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

/**
 * FASE 9 (H-10) — activación de licencia por pegado de clave.
 *
 * Contrato del backend (`api/license_api.py`): body `{ "token": "tqlic1.…" }`.
 *
 * Detalle que la UI tiene que respetar y que es fácil equivocar: un token
 * INVÁLIDO no es un error HTTP. El backend responde **200** con
 * `{ activated: false, valid: false, reason: "<motivo en español>" }`. Quien
 * mire sólo el código de estado dirá "activada" sobre una licencia rechazada.
 * Por eso este proxy pasa el cuerpo tal cual y no traduce nada.
 */
export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Body JSON inválido." }, { status: 400 });
  }

  const token =
    body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>).token
      : undefined;

  if (typeof token !== "string" || token.trim().length === 0) {
    // El backend respondería 422 (campo requerido); se responde antes con un
    // mensaje en español, porque este caso es "el usuario no pegó nada".
    return NextResponse.json(
      { detail: "Pega el token de licencia antes de activar." },
      { status: 400 }
    );
  }

  const result = await fetchBackendJson({
    path: "/license/activate",
    method: "POST",
    body: { token: token.trim() },
    timeoutMs: 10_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: "No se pudo contactar con el servicio de licencias.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
