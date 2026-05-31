import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "../_lib/backend";

function getFilename(projectId: string, runId: string) {
  return `project_${projectId}__run_${runId}.zip`;
}

async function readBackendError(res: Response) {
  try {
    const data = (await res.json()) as unknown;
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
    }
  } catch {
    // Fall back below when backend error is not JSON.
  }

  return "No se pudo exportar la corrida.";
}

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const projectId = searchParams.get("project_id");
    const runId = searchParams.get("run_id");

    if (!projectId || !runId) {
      return NextResponse.json(
        { detail: "project_id y run_id son requeridos." },
        { status: 400 }
      );
    }

    const backendParams = new URLSearchParams({
      project_id: projectId,
      run_id: runId,
    });

    const backendUrl = buildBackendUrl(`/export-run?${backendParams.toString()}`);
    const res = await fetch(backendUrl, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/zip",
      },
    });

    if (!res.ok) {
      return NextResponse.json(
        {
          detail: await readBackendError(res),
          backendStatus: res.status,
          backendUrl,
        },
        { status: res.status }
      );
    }

    const data = await res.arrayBuffer();
    const filename =
      res.headers
        .get("content-disposition")
        ?.match(/filename="?([^"]+)"?/)?.[1] || getFilename(projectId, runId);

    return new NextResponse(data, {
      status: res.status,
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (error: unknown) {
    const detail =
      error instanceof Error
        ? error.message
        : "Error desconocido exportando corrida.";

    return NextResponse.json(
      {
        detail,
        backendStatus: 500,
        backendUrl: null,
      },
      { status: 500 }
    );
  }
}
