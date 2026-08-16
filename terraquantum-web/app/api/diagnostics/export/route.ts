import { NextResponse } from "next/server";
import { buildBackendUrl } from "../../_lib/backend";

/**
 * FASE 9 (H-10) — descarga del ZIP de diagnóstico.
 *
 * No usa `fetchBackendJson` porque la respuesta es BINARIA: se hace streaming del
 * cuerpo, igual que `app/api/export-bundle`. Y va por el proxy —no directo al
 * :8010 desde el navegador— por las dos razones que la Fase 2 midió en H-21: el
 * navegador no lleva la `X-TQ-API-Key`, y el backend puede estar en un puerto
 * alternativo que una URL horneada en el bundle no seguiría.
 *
 * Local-first: el ZIP se genera y se descarga; nada se envía a ningún sitio. El
 * usuario decide a quién se lo manda.
 */
export async function GET() {
  const backendUrl = buildBackendUrl("/diagnostics/export");

  try {
    const apiKey = process.env.TQ_API_KEY ?? "";
    const res = await fetch(backendUrl, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/zip",
        ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
      },
    });

    if (!res.ok || !res.body) {
      let detail = "No se pudo generar el paquete de diagnóstico.";
      try {
        const data = (await res.json()) as { detail?: unknown };
        if (typeof data?.detail === "string") detail = data.detail;
      } catch {
        // El backend no devolvió JSON: se conserva el mensaje genérico.
      }
      return NextResponse.json(
        { detail, backendStatus: res.status, backendUrl },
        { status: res.status || 502 }
      );
    }

    const filename =
      res.headers.get("content-disposition")?.match(/filename="?([^"]+)"?/)?.[1] ||
      "terraquantum_diagnostico.zip";

    return new NextResponse(res.body, {
      status: 200,
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/zip",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "error desconocido";
    return NextResponse.json(
      {
        detail: `No se pudo conectar con el backend Python: ${message}`,
        backendStatus: 500,
        backendUrl,
      },
      { status: 500 }
    );
  }
}
