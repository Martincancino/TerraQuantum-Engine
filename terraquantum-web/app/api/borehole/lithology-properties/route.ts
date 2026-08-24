import { NextResponse } from "next/server";
import { fetchBackendJson } from "../../_lib/backend";

// FASE 14 — BFF: proxya la tabla petrofísica por litología.
//
// Hasta ahora esta ruta del backend no tenía consumidor y vivía en la lista
// RUTAS_SIN_UI_TOLERADAS del guard de la Fase 9 ("no hay pantalla que lo liste").
// Con el prior geológico implícito sí lo tiene: cuando el usuario elige qué
// litología de sus sondajes es la unidad objetivo, el formulario necesita saber
// qué densidad tiene esa unidad para proponerla — y ese número vive en el
// backend (exploration/pgi_engine LITHOLOGY_PROPERTIES), no en el frontend.
// Regla de Oro: la tabla petrofísica NO se duplica en TypeScript.

export async function GET() {
  const result = await fetchBackendJson({
    path: "/borehole/lithology-properties",
    method: "GET",
    timeoutMs: 15_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: "No se pudo leer la tabla petrofísica por litología.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, { status: result.status });
}
