import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "../_lib/backend";

const ZARR_TIMEOUT_MS = 60_000;

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("project_id");
  const runId = searchParams.get("run_id");
  const chunkIdx = searchParams.get("chunk_idx");

  if (!projectId || !runId) {
    return NextResponse.json(
      { error: "project_id and run_id are required" },
      { status: 400 }
    );
  }

  const backendPath = `/block-model-zarr/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`;
  const params = new URLSearchParams();
  if (chunkIdx !== null) params.set("chunk_idx", chunkIdx);

  const queryStr = params.toString();
  const backendUrl = buildBackendUrl(queryStr ? `${backendPath}?${queryStr}` : backendPath);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ZARR_TIMEOUT_MS);

  try {
    const res = await fetch(backendUrl, {
      signal: controller.signal,
      headers: {
        "X-TQ-API-Key": process.env.TQ_API_KEY ?? "",
      },
    });

    clearTimeout(timeout);

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json(
        { error: text || `Backend error ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    clearTimeout(timeout);
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: `Zarr fetch failed: ${msg}` }, { status: 502 });
  }
}
