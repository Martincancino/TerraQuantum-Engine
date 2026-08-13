export const BACKEND_URL =
  process.env.TERRAQUANTUM_BACKEND_URL || "http://127.0.0.1:8010";

export const DEFAULT_BACKEND_TIMEOUT_MS = 45_000;

// Tipo seguro para valores JSON arbitrarios
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface BackendJsonResult {
  ok: boolean;
  status: number;
  backendUrl: string;
  data: JsonValue;
}

export function buildBackendUrl(path: string) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${BACKEND_URL}${cleanPath}`;
}

export async function fetchBackendJson(options: {
  // DELETE se añadió en la Fase 2 (H-21) para poder enrutar por proxy la única
  // llamada de borrado, que hasta entonces salía DIRECTA desde el navegador.
  path: string;
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
}): Promise<BackendJsonResult> {
  const {
    path,
    method = "GET",
    body,
    timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
  } = options;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  const backendUrl = buildBackendUrl(path);

  try {
    const apiKey = process.env.TQ_API_KEY ?? "";
    const res = await fetch(backendUrl, {
      method,
      cache: "no-store",
      headers: {
        accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const rawText = await res.text();

    let data: JsonValue;

    try {
      data = rawText ? (JSON.parse(rawText) as JsonValue) : {};
    } catch {
      return {
        ok: false,
        status: res.status || 500,
        backendUrl,
        data: {
          detail: "El backend Python no devolvió JSON válido.",
          backendStatus: res.status,
          backendRawResponse: rawText,
          backendUrl,
        },
      };
    }

    return {
      ok: res.ok,
      status: res.status,
      backendUrl,
      data,
    };
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" ||
        error.message.toLowerCase().includes("aborted"));

    const message =
      error instanceof Error ? error.message : "unknown error";

    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      backendUrl,
      data: {
        detail: isTimeout
          ? `Timeout: el backend Python tardó más de ${timeoutMs / 1000}s en responder.`
          : `Error conectando con backend Python: ${message}`,
        backendUrl,
        hint: `Verifica que FastAPI esté corriendo en ${BACKEND_URL}`,
      },
    };
  } finally {
    clearTimeout(timeout);
  }
}