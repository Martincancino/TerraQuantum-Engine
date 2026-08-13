import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "../_lib/backend";

/**
 * Fase 2 (H-21) — el bundle de exportación se pedía DIRECTO desde el navegador
 * a `http://127.0.0.1:8010`, una URL horneada en el bundle de cliente en tiempo
 * de build. Dos consecuencias medidas:
 *
 *  1. Seguridad: rompía la premisa "todo pasa por los proxies", que es lo que
 *     permitiría activar autenticación algún día (el navegador no lleva la
 *     `X-TQ-API-Key`, el proxy sí).
 *  2. Corrección: desde la Fase 2 el orquestador puede levantar el backend en
 *     un puerto alternativo si el 8010 está ocupado. Una URL horneada apuntaría
 *     entonces a **otro proceso** — exactamente el fallo de identidad de H-19,
 *     pero servido al usuario como una descarga.
 *
 * El proxy resuelve el backend en tiempo de EJECUCIÓN, así que sigue al puerto
 * que sea. Se hace streaming: el bundle puede pesar decenas de MB.
 */
export async function GET(req: NextRequest) {
  const projectId = req.nextUrl.searchParams.get("project_id");
  const runId = req.nextUrl.searchParams.get("run_id");

  if (!projectId || !runId) {
    return NextResponse.json(
      { detail: "project_id y run_id son requeridos." },
      { status: 400 }
    );
  }

  const backendUrl = buildBackendUrl(
    `/export/bundle/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`
  );

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
      let detail = "No se pudo generar el bundle de exportación.";
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
      `terraquantum_${projectId}_${runId}.zip`;

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
