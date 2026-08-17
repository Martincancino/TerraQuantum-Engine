// ─── FASE 9 (H-10) — cliente de la superficie F7: licencia, diagnóstico, conexión ───
//
// H-10 midió que la fase F7 entera (licenciamiento local-first, exportación de
// diagnóstico y honestidad offline) no tenía **ninguna** interfaz: 5 endpoints
// sin un solo consumidor. Su gate se declaró en verde midiendo el backend, no al
// usuario. Este módulo es el cable que faltaba.
//
// FASE 10 — los contratos ya NO se escriben aquí a mano.
//
// Hasta la Fase 9 estos tipos se escribían leyendo `core/license_service.py`,
// `services/diagnostics_service.py` y `services/connectivity_service.py`. Estaban
// bien —se midieron— y aun así eran una bomba: el día que el backend añadiera un
// campo, nada fallaba hasta que un consultor viera un dato vacío. Ahora vienen de
// `types/backend-contracts.generated.ts`, que produce el backend desde su propio
// OpenAPI, y un cambio de contrato rompe la COMPILACIÓN.
//
// Lo que sigue siendo local, y por qué: `BackendHealth` no es un contrato del
// backend sino la forma que INVENTA el proxy `/api/backend-health`
// (`online`, `backendStatus`, `backendUrl`). Generarlo sería mentir sobre su
// origen; lo que sí se tipa con el contrato real es su carga útil.

import type { FrontendApiResult } from "./frontendApi";
import type {
  ConnectivityFeature as ConnectivityFeatureContract,
  ConnectivitySummaryResponse,
  DiagnosticManifestResponse,
  HealthResponse,
  LicenseActivationResponse,
  LicenseStatusResponse,
} from "../../types/backend-contracts.generated";

// ─── Contratos (generados desde el OpenAPI del backend) ───────────────────────

/** `GET /license/status`. */
export type LicenseStatus = LicenseStatusResponse;

/** `POST /license/activate`.
 *
 *  **No es el mismo tipo que `LicenseStatus`, y confundirlos era un bug latente:**
 *  medido en la Fase 10, `activate_license()` NUNCA devuelve `mode`. Antes ambas
 *  respuestas compartían un tipo con `mode` obligatorio, así que leer `.mode`
 *  tras activar daba `undefined` sin una sola queja del compilador. Ahora son dos
 *  contratos y `tsc` lo sabe. */
export type LicenseActivation = LicenseActivationResponse;

export type ConnectivityFeature = ConnectivityFeatureContract;

/** `GET /system/connectivity`. */
export type ConnectivitySummary = ConnectivitySummaryResponse;

/** `GET /diagnostics/manifest` — lo que va dentro del ZIP, para poder mirarlo
 *  ANTES de descargarlo. Es lo que hace comprobable la promesa de que no sale
 *  ningún dato de survey. */
export type DiagnosticManifest = DiagnosticManifestResponse;

/** `GET /api/backend-health`. **Esto lo fabrica el proxy de Next, no el backend**:
 *  traduce «respondió / no respondió» a un booleano que la barra de estado puede
 *  pintar. `data` sí es el contrato real de `GET /health`. */
export type BackendHealth = {
  online: boolean;
  detail?: string;
  backendStatus?: number;
  backendUrl?: string;
  data?: HealthResponse;
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
 *  `activated:false` — la condición de éxito es `activated === true`, no `ok`.
 *
 *  Devuelve `LicenseActivation`, que **no trae `mode`**: para saber si la licencia
 *  quedó activa hay que volver a leer `/license/status` (que además es lo correcto,
 *  porque `TQ_LICENSE` del entorno puede anular lo que se acaba de escribir). */
export async function activateLicense(token: string) {
  return requestJson<LicenseActivation>(
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
