import { NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

/**
 * FASE 9 (H-10) — el primer consumidor que ha tenido `GET /license/status`.
 *
 * F7 dejó el licenciamiento completo en el backend y su gate lo declaró en verde
 * midiendo el endpoint, no al usuario: no había una sola línea de frontend que lo
 * llamara. Sin esto, un cliente no puede activar su licencia sin `curl`.
 *
 * El backend NUNCA falla aquí (`license_service.get_license_status` degrada a modo
 * local libre ante cualquier error), así que un no-ok de este proxy significa
 * "backend caído/inalcanzable", no "licencia inválida".
 */
export async function GET() {
  const result = await fetchBackendJson({
    path: "/license/status",
    method: "GET",
    timeoutMs: 10_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: "No se pudo leer el estado de la licencia.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
