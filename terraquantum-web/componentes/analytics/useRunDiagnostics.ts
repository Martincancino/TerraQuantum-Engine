"use client";

import { useEffect, useState } from "react";
import { getProjectRunDetail } from "../../lib/terraquantum/frontendApi";

export type RunDetailData = {
  report: Record<string, unknown> | null;
  inputs: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  observations: Record<string, unknown>[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/**
 * Carga (una sola vez por run) el detalle persistido de una corrida:
 * report + inputs + metrics + observations. Es la fuente para los widgets
 * científicos del viewport 3D. Solo lee datos del backend — no calcula física.
 */
export function useRunDiagnostics(
  projectId: string | null,
  runId: string | null,
  status: string
) {
  const [data, setData] = useState<RunDetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    (async () => {
      // Frontera de microtask: evita setState síncrono dentro del effect
      // (regla set-state-in-effect del React Compiler).
      await Promise.resolve();
      if (!active) return;

      if (!projectId || !runId || status !== "ready") {
        setData(null);
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const res = await getProjectRunDetail(projectId, runId);
        if (!active) return;
        if (!res.ok || !res.data) {
          setError(res.error || "No se pudo leer el detalle de la corrida.");
          setData(null);
          return;
        }
        const root = asRecord(res.data);
        const obsRaw = root?.observations;
        setData({
          report: asRecord(root?.report),
          inputs: asRecord(root?.inputs),
          metrics: asRecord(root?.metrics),
          observations: Array.isArray(obsRaw)
            ? obsRaw
                .map(asRecord)
                .filter((o): o is Record<string, unknown> => o !== null)
            : [],
        });
      } catch (e: unknown) {
        if (!active) return;
        setError(e instanceof Error ? e.message : "Error de red");
        setData(null);
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [projectId, runId, status]);

  return { data, loading, error };
}
