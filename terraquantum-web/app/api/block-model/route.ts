import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson, buildBackendUrl } from "../_lib/backend";

function readBackendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  const record = data as Record<string, unknown>;

  if (typeof record.detail === "string") return record.detail;
  if (typeof record.error === "string") return record.error;

  return null;
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);

  const format = searchParams.get("format");
  const mode = searchParams.get("mode") || "exploration";
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");

  // ── Arrow binary path — proxy puro sin JSON.parse ──────────────────────────
  if (format === "arrow") {
    const backendParams = new URLSearchParams({ mode });
    if (projectId && runId) {
      backendParams.set("project_id", projectId);
      backendParams.set("run_id", runId);
    }
    const displayFactor = searchParams.get("display_factor");
    if (displayFactor) backendParams.set("display_factor", displayFactor);

    const backendUrl = buildBackendUrl(`/block-model-arrow?${backendParams.toString()}`);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90_000);

    try {
      const apiKey = process.env.TQ_API_KEY ?? "";
      const res = await fetch(backendUrl, {
        method: "GET",
        cache: "no-store",
        headers: {
          accept: "application/vnd.apache.arrow.stream",
          ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
        },
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        return NextResponse.json(
          { detail: text || "Error al cargar Arrow desde backend.", backendStatus: res.status },
          { status: res.status }
        );
      }

      const buffer = await res.arrayBuffer();

      const responseHeaders = new Headers({
        "Content-Type": "application/vnd.apache.arrow.stream",
        "Cache-Control": "no-store",
      });

      // Propagar headers X-TQ-* del backend
      for (const [key, val] of res.headers.entries()) {
        if (key.toLowerCase().startsWith("x-tq-")) {
          responseHeaders.set(key, val);
        }
      }

      return new NextResponse(buffer, { status: 200, headers: responseHeaders });
    } catch (error: unknown) {
      const isTimeout =
        error instanceof Error &&
        (error.name === "AbortError" || error.message.toLowerCase().includes("aborted"));
      return NextResponse.json(
        { detail: isTimeout ? "Timeout Arrow block model." : "Error al conectar con backend Arrow." },
        { status: isTimeout ? 504 : 500 }
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  // ── JSON path (existente — sin cambios) ────────────────────────────────────
  const limit = searchParams.get("limit") || "5000";

  const backendParams = new URLSearchParams({
    mode,
    limit,
  });

  if (projectId && runId) {
    backendParams.set("project_id", projectId);
    backendParams.set("run_id", runId);
  }

  const result = await fetchBackendJson({
    path: `/block-model?${backendParams.toString()}`,
    method: "GET",
    timeoutMs: 45_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      {
        detail: readBackendMessage(result.data) || "No se pudo leer el block model.",
        backendStatus: result.status,
        backendUrl: result.backendUrl,
        backendDetails: result.data,
      },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data, {
    status: result.status,
  });
}
