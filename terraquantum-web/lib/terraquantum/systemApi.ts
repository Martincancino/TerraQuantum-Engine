// ─── FASE 9 (H-10) — cliente de la superficie F7: licencia, diagnóstico, conexión ───
//
// H-10 midió que la fase F7 entera (licenciamiento local-first, exportación de
// diagnóstico y honestidad offline) no tenía **ninguna** interfaz: 5 endpoints
// sin un solo consumidor. Su gate se declaró en verde midiendo el backend, no al
// usuario. Este módulo es el cable que faltaba.
//
// Los tipos describen lo que el backend devuelve HOY (medido leyendo
// `core/license_service.py`, `services/diagnostics_service.py` y
// `services/connectivity_service.py`). No se normaliza ni se completa nada: si un
// campo no viene, viene `undefined` y la UI lo dice. Regla de Oro — aquí no se
// calcula nada, sólo se transporta.

import type { FrontendApiResult } from "./frontendApi";

// ─── Contratos ────────────────────────────────────────────────────────────────

/** `GET /license/status` y `POST /license/activate` (mismo cuerpo + `activated`).
 *
 *  `tier` es una cadena LIBRE dentro del token firmado: el backend no la valida
 *  contra un enumerado (`license_service.py`, `tier = str(payload.get("tier") …)`)
 *  y los límites sólo están tabulados para `local`/`pro`/`free`. Por eso aquí es
 *  `string` y no una unión: cerrarla en el frontend sería inventar un contrato. */
export type LicenseStatus = {
  valid: boolean;
  tier: string;
  /** Motivo en español, escrito por el backend. Es la única explicación del estado. */
  reason: string;
  licensee: string | null;
  product: string | null;
  issued_at: string | null;
  /** ISO-8601, o `null` = licencia perpetua. */
  expires_at: string | null;
  expired: boolean;
  /** De dónde salió el token vigente. `env` gana sobre `file` — ver aviso en el panel. */
  source: "env" | "file" | "none" | string;
  effective_tier: string;
  limits: { max_voxels: number | null; watermark: boolean } | null;
  mode: "licensed" | "local_free" | string;
  /** Sólo en la respuesta de activación. Un token inválido devuelve HTTP 200
   *  con `activated:false`: mirar el código de estado no basta. */
  activated?: boolean;
};

/** Una función que puede necesitar internet, tal como la declara el backend. */
export type ConnectivityFeature = {
  name: string;
  key: string;
  requires_internet: boolean;
  required_for_golden_path: boolean;
  configured: boolean;
  local_fallback: boolean;
  message: string;
  /** Fase 9: la clave la pone el usuario en la interfaz (BYO-key). Sin este
   *  campo, `configured:false` se lee como «no disponible», que es falso. */
  user_supplied_key?: boolean;
};

/** `GET /system/connectivity`. */
export type ConnectivitySummary = {
  golden_path_offline: boolean;
  golden_path_note: string;
  /** Siempre `false`: este resumen NUNCA sale a la red. */
  probed: boolean;
  probe_requested?: boolean;
  probe_note?: string;
  online_features: ConnectivityFeature[];
};

/** `GET /diagnostics/manifest` — lo que va dentro del ZIP, para poder mirarlo
 *  ANTES de descargarlo. Es lo que hace comprobable la promesa de que no sale
 *  ningún dato de survey. */
export type DiagnosticManifest = {
  system: Record<string, unknown>;
  packages: Record<string, string>;
  config_sanitized: Record<string, unknown>;
  connectivity: ConnectivitySummary;
  license: Record<string, unknown>;
  recent_errors: unknown[];
};

/** `GET /api/backend-health` — el proxy ya existía y no lo llamaba nadie. */
export type BackendHealth = {
  online: boolean;
  detail?: string;
  backendStatus?: number;
  backendUrl?: string;
  data?: Record<string, unknown>;
};

// ─── Transporte ───────────────────────────────────────────────────────────────

async function getJson<T>(
  path: string,
  timeoutMs = 10_000,
): Promise<FrontendApiResult<T>> {
  return requestJson<T>(path, { method: "GET" }, timeoutMs);
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<FrontendApiResult<T>> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      ...init,
      cache: "no-store",
      headers: { accept: "application/json", ...(init.headers ?? {}) },
      signal: controller.signal,
    });
    const raw = await res.text();
    let data: unknown = {};
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      return { ok: false, status: res.status || 500, data: null,
               error: `La ruta ${path} no devolvió JSON válido.` };
    }
    if (!res.ok) {
      const rec = data && typeof data === "object" ? (data as Record<string, unknown>) : null;
      return {
        ok: false,
        status: res.status,
        data: data as T,
        error:
          (typeof rec?.detail === "string" ? rec.detail : null) ??
          `La ruta ${path} falló con status ${res.status}.`,
      };
    }
    return { ok: true, status: res.status, data: data as T, error: null };
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" || error.message.toLowerCase().includes("aborted"));
    return {
      ok: false,
      status: isTimeout ? 504 : 500,
      data: null,
      error: isTimeout
        ? `Timeout: ${path} tardó más de ${timeoutMs / 1000}s.`
        : `No se pudo contactar con ${path}.`,
    };
  } finally {
    window.clearTimeout(timer);
  }
}

// ─── Llamadas ─────────────────────────────────────────────────────────────────

export async function getLicenseStatus() {
  return getJson<LicenseStatus>("/api/license/status");
}

/** Activa por pegado de clave. OJO: un token inválido responde 200 con
 *  `activated:false` — la condición de éxito es `activated === true`, no `ok`. */
export async function activateLicense(token: string) {
  return requestJson<LicenseStatus>(
    "/api/license/activate",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    },
    10_000,
  );
}

export async function getConnectivity() {
  return getJson<ConnectivitySummary>("/api/system/connectivity");
}

export async function getDiagnosticManifest() {
  return getJson<DiagnosticManifest>("/api/diagnostics/manifest", 20_000);
}

export async function getBackendHealth() {
  return getJson<BackendHealth>("/api/backend-health", 6_000);
}

/** URL de descarga del ZIP. Se navega, no se hace fetch: así el navegador
 *  gestiona la descarga y el usuario elige dónde guardarla. */
export const DIAGNOSTICS_EXPORT_URL = "/api/diagnostics/export";
