import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "../_lib/backend";

/**
 * FASE 12 — Proxy de descarga del Open Mining Format (.omf).
 *
 * Mismo contrato que `export-bundle`: el backend se resuelve en tiempo de
 * EJECUCIÓN (nunca una URL horneada en el bundle de cliente, H-21/H-19) y la
 * respuesta va en streaming, porque un OMF con block model, estaciones,
 * sondajes e isosuperficies pesa más que el ZIP industrial.
 *
 * A diferencia del bundle, aquí el error del backend SÍ se propaga como JSON con
 * su status: el botón que lo llama reporta el mensaje en la UI en vez de abrir
 * una pestaña con un JSON crudo. Importa porque el backend contesta 422 con un
 * motivo accionable cuando la corrida no tiene malla reconstruible.
 */
export async function GET(req: NextRequest) {
  const projectId = req.nextUrl.searchParams.get("project_id");
  const runId = req.nextUrl.searchParams.get("run_id");
  const includeSurfaces = req.nextUrl.searchParams.get("include_surfaces");

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const query =
    includeSurfaces === null
      ? ""
      : `?include_surfaces=${encodeURIComponent(includeSurfaces)}`;
  const backendUrl = buildBackendUrl(
    `/export/omf/${encodeURIComponent(projectId)}/${encodeURIComponent(
      runId
    )}${query}`
  );

  try {
    const apiKey = process.env.TQ_API_KEY ?? "";
    const res = await fetch(backendUrl, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/octet-stream",
        ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
      },
    });

    if (!res.ok || !res.body) {
      let detail = "No se pudo generar el fichero OMF.";
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
      `terraquantum_${projectId}_${runId}.omf`;

    return new NextResponse(res.body, {
      status: 200,
      headers: {
        "Content-Type":
          res.headers.get("content-type") || "application/octet-stream",
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
