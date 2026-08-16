import { NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

/**
 * FASE 9 (H-10) — honestidad offline en el camino del usuario.
 *
 * `GET /system/connectivity` declara qué funciones necesitan internet y confirma
 * que el camino dorado (ingesta→inversión→3D→export) NO lo necesita. Nunca sale
 * a la red: describe configuración, no alcance real, y la propia respuesta trae
 * `probed:false` + `probe_note` diciendo por qué (corregido en la iteración de
 * backend de esta misma fase, donde `probed` devolvía `true` sin sondear nada).
 *
 * No se propaga ningún `?probe=`: pedirlo no cambiaría la respuesta y dejaría en
 * la UI la impresión de que existe un sondeo que se puede disparar.
 */
export async function GET() {
  const result = await fetchBackendJson({
    path: "/system/connectivity",
    method: "GET",
    timeoutMs: 10_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: "No se pudo leer el estado de conectividad.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
