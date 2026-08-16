import { NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

/**
 * FASE 9 (H-10) — el contenido del paquete de diagnóstico, como JSON.
 *
 * Sirve para que la UI pueda MOSTRAR qué se va a enviar antes de que el usuario
 * descargue el ZIP. Es la mitad que hace creíble la promesa de confidencialidad:
 * "nada de tus datos sale de aquí" se puede comprobar mirando, no confiando.
 *
 * El backend ya recorta secretos (`_SECRET_MARKERS` en `diagnostics_service`) y
 * no incluye ningún dato de survey.
 */
export async function GET() {
  const result = await fetchBackendJson({
    path: "/diagnostics/manifest",
    method: "GET",
    timeoutMs: 15_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: "No se pudo generar el diagnóstico.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
