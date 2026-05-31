import { NextResponse } from "next/server";
import { BACKEND_URL, fetchBackendJson } from "../_lib/backend";

function asRecord(data: unknown): Record<string, unknown> | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  return data as Record<string, unknown>;
}

function readObjectField(data: unknown, field: string): Record<string, unknown> {
  const record = asRecord(data);
  if (!record) return {};

  const value = record[field];
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};

  return value as Record<string, unknown>;
}

function readArrayField(data: unknown, field: string): unknown[] {
  const record = asRecord(data);
  if (!record) return [];

  const value = record[field];
  return Array.isArray(value) ? value : [];
}

function readStringField(data: unknown, field: string): string | null {
  const record = asRecord(data);
  if (!record) return null;

  const value = record[field];
  return typeof value === "string" ? value : null;
}

function readNumberField(data: unknown, field: string): number | null {
  const record = asRecord(data);
  if (!record) return null;

  const value = record[field];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export async function GET() {
  const [healthResult, openapiResult, blockModelResult, systemStatusResult] =
    await Promise.all([
      fetchBackendJson({
        path: "/health",
        method: "GET",
        timeoutMs: 5_000,
      }),
      fetchBackendJson({
        path: "/openapi.json",
        method: "GET",
        timeoutMs: 5_000,
      }),
      fetchBackendJson({
        path: "/block-model?mode=exploration&limit=1000",
        method: "GET",
        timeoutMs: 10_000,
      }),
      fetchBackendJson({
        path: "/system-status",
        method: "GET",
        timeoutMs: 5_000,
      }),
    ]);

  const paths = readObjectField(openapiResult.data, "paths");

  const routes = {
    health: Boolean(healthResult.ok),
    systemStatus: Boolean(paths["/system-status"]),
    geophysicsInvert: Boolean(paths["/geophysics-invert"]),
    blockModel: Boolean(paths["/block-model"]),
    generate: Boolean(paths["/generate"]),
    scenarioSweep: Boolean(paths["/scenario-sweep"]),
  };

  const blockModelJson = asRecord(blockModelResult.data) || {};

  const cells = readArrayField(blockModelJson, "cells").length;

  const blockModelReady = Boolean(blockModelResult.ok && cells > 0);

  const routesReady =
    routes.health &&
    routes.systemStatus &&
    routes.geophysicsInvert &&
    routes.blockModel &&
    routes.generate;

  const online = Boolean(
    healthResult.ok &&
      openapiResult.ok &&
      systemStatusResult.ok &&
      routesReady
  );

  return NextResponse.json(
    {
      online,
      backendUrl: BACKEND_URL,

      health: {
        ok: healthResult.ok,
        status: healthResult.status,
        data: healthResult.data,
      },

      systemStatus: {
        ok: systemStatusResult.ok,
        status: systemStatusResult.status,
        data: systemStatusResult.data,
      },

      routes,
      routesReady,

      blockModel: {
        ok: blockModelResult.ok,
        status: blockModelResult.status,
        ready: blockModelReady,
        cells,
        visualMode: readStringField(blockModelJson, "visualMode") || null,
        domainL: readNumberField(blockModelJson, "domainL") ?? 0,
        domainH: readNumberField(blockModelJson, "domainH") ?? 0,
        domainW: readNumberField(blockModelJson, "domainW") ?? 0,
        totalRows: readNumberField(blockModelJson, "totalRows") ?? 0,
        returnedCells: readNumberField(blockModelJson, "returnedCells") ?? 0,
        error: readStringField(blockModelJson, "error") || null,
      },

      summary: {
        status: online ? "READY" : "OFFLINE_OR_INCOMPLETE",
        message: online
          ? "Backend conectado y rutas críticas disponibles."
          : "Backend desconectado o rutas críticas faltantes.",
      },
    },
    { status: 200 }
  );
}
