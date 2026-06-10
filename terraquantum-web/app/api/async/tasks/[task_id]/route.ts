import { NextRequest, NextResponse } from "next/server";
import { fetchBackendJson } from "../../../_lib/backend";

export async function GET(
  _req: NextRequest,
  { params }: { params: { task_id: string } }
) {
  try {
    const taskId = params.task_id;
    if (!taskId) {
      return NextResponse.json({ detail: "task_id es requerido." }, { status: 400 });
    }
    const result = await fetchBackendJson({
      path: `/api/async/tasks/${encodeURIComponent(taskId)}`,
      method: "GET",
      timeoutMs: 10_000,
    });
    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[async/tasks/{task_id}] proxy error:", message);
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { task_id: string } }
) {
  try {
    const taskId = params.task_id;
    const result = await fetchBackendJson({
      path: `/api/async/tasks/${encodeURIComponent(taskId)}`,
      method: "GET",
      timeoutMs: 5_000,
    });
    return NextResponse.json(result.data, { status: result.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
