"use client";

// ─── FASE 9 (H-10) — Panel de licencia ────────────────────────────────────────
//
// F7 construyó el licenciamiento local-first entero (Ed25519, verificación
// offline, tiers) y NADIE podía usarlo: `GET /license/status` y
// `POST /license/activate` no tenían un solo consumidor en el frontend. Este
// panel es el camino de usuario que faltaba: ver el estado y activar pegando la
// clave, sin tocar la API a mano.
//
// Sólo visualiza lo que el backend declara. En particular, `reason` viene ya
// escrito en español desde `core/license_service.py`: no se reinterpreta aquí.

import { useEffect, useState } from "react";
import {
  activateLicense,
  getLicenseStatus,
  type LicenseStatus,
} from "../../lib/terraquantum/systemApi";

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-white/5 py-1.5 last:border-b-0">
      <span className="text-[9px] uppercase tracking-[0.16em] text-white/40 shrink-0">
        {label}
      </span>
      <div className="min-w-0 text-right">
        <span className="text-[10px] font-mono text-white/85 break-all">{value}</span>
        {hint && <p className="text-[8px] text-white/35 mt-0.5 leading-tight">{hint}</p>}
      </div>
    </div>
  );
}

export default function LicensePanel() {
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  /** Resultado del ÚLTIMO intento de activación. `null` = aún no se intentó. */
  const [attempt, setAttempt] = useState<{ ok: boolean; message: string } | null>(null);

  /** Nº de recargas pedidas. Es el disparador del efecto: tras activar hay que
   *  volver a preguntar, y hacerlo por estado (y no llamando a una función desde
   *  el manejador) mantiene la carga dentro del efecto, que es donde la regla
   *  `set-state-in-effect` del React Compiler la quiere. */
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let alive = true;
    void (async () => {
      // Frontera de microtask: evita el setState síncrono dentro del efecto
      // (mismo patrón que `analytics/useRunDiagnostics.ts`).
      await Promise.resolve();
      if (!alive) return;
      const res = await getLicenseStatus();
      if (!alive) return;
      if (!res.ok || !res.data) {
        setStatus(null);
        setLoadError(res.error ?? "No se pudo leer el estado de la licencia.");
        return;
      }
      setLoadError(null);
      setStatus(res.data);
    })();
    return () => {
      alive = false;
    };
  }, [reloads]);

  async function handleActivate() {
    if (!token.trim() || busy) return;
    setBusy(true);
    setAttempt(null);
    const res = await activateLicense(token.trim());
    setBusy(false);

    if (!res.ok || !res.data) {
      // Aquí sí es un fallo de transporte: el backend de licencias nunca lanza.
      setAttempt({ ok: false, message: res.error ?? "No se pudo contactar con el backend." });
      return;
    }
    // La condición de éxito es `activated`, NO el código HTTP: un token inválido
    // responde 200. Y hay un caso real de `valid:true` con `activated:false`
    // (licencia correcta que no se pudo escribir en disco), donde el backend
    // sobreescribe `reason` con el motivo.
    const data = res.data;
    setAttempt({
      ok: data.activated === true,
      message: data.reason || (data.activated ? "Licencia activada." : "Licencia rechazada."),
    });
    if (data.activated) setToken("");
    // Vuelve a leer el estado: activar escribe en disco, y el `source` puede
    // seguir siendo `env` (que manda sobre el archivo). Lo que se muestre tiene
    // que ser lo que el backend diga AHORA, no lo que devolvió la activación.
    setReloads((n) => n + 1);
  }

  const licensed = status?.mode === "licensed";

  return (
    <div className="flex flex-col gap-4" data-testid="license-panel">
      {/* ── Estado ─────────────────────────────────────────────────────────── */}
      {loadError && (
        <p className="text-[10px] text-yellow-400/80 font-mono leading-relaxed">
          {loadError}
        </p>
      )}

      {status && (
        <>
          <div className="flex items-center gap-2">
            <span
              data-testid="license-mode"
              className={`text-[9px] uppercase tracking-[0.18em] font-bold px-2.5 py-1 rounded border ${
                licensed
                  ? "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10"
                  : "text-white/70 border-white/15 bg-white/[0.03]"
              }`}
            >
              {licensed ? "Licencia activa" : "Modo local libre"}
            </span>
            <span
              data-testid="license-tier"
              className="text-[9px] uppercase tracking-[0.18em] text-white/50 font-mono"
            >
              tier · {status.effective_tier}
            </span>
          </div>

          <p className="text-[10px] leading-relaxed text-white/60">{status.reason}</p>

          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
            <Row label="Modo" value={status.mode} />
            <Row label="Tier efectivo" value={status.effective_tier} />
            <Row label="Licenciatario" value={status.licensee ?? "—"} />
            <Row label="Producto" value={status.product ?? "—"} />
            <Row
              label="Vence"
              value={status.expires_at ?? (status.valid ? "perpetua" : "—")}
              hint={status.expired ? "Vencida: el tier volvió a local." : undefined}
            />
            <Row
              label="Origen"
              value={status.source}
              hint={
                status.source === "env"
                  ? "La variable de entorno TQ_LICENSE tiene PRIORIDAD sobre el archivo: activar aquí no la reemplazará."
                  : undefined
              }
            />
            {status.limits && status.limits.max_voxels !== null && (
              <Row
                label="Límite declarado"
                value={`${status.limits.max_voxels.toLocaleString()} vóxeles`}
                // Medido en la Fase 9: `check_voxel_budget` no tiene ningún
                // llamador de producción. Prometer que el límite se aplica sería
                // exactamente el tipo de afirmación sin respaldo que esta
                // auditoría persigue.
                hint="Lo declara el token. Hoy ninguna inversión lo comprueba."
              />
            )}
          </div>

          {status.source === "env" && (
            <p
              data-testid="license-env-warning"
              className="text-[9px] leading-relaxed text-yellow-400/75 rounded border border-yellow-500/25 bg-yellow-500/[0.06] px-3 py-2"
            >
              La licencia vigente viene de la variable de entorno{" "}
              <span className="font-mono">TQ_LICENSE</span>, que manda sobre el
              archivo. Si activas una clave nueva aquí se guardará, pero seguirá
              mostrándose la del entorno hasta que lo quites.
            </p>
          )}
        </>
      )}

      {/* ── Activación por pegado ──────────────────────────────────────────── */}
      <div className="flex flex-col gap-2 pt-1 border-t border-white/[0.06]">
        <label
          htmlFor="license-token"
          className="text-[9px] uppercase tracking-[0.16em] text-white/45"
        >
          Activar licencia — pega tu clave
        </label>
        <textarea
          id="license-token"
          data-testid="license-token-input"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          rows={3}
          spellCheck={false}
          placeholder="tqlic1.…"
          className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-[10px] font-mono text-white/85 placeholder:text-white/25 focus:border-accent/50 focus:outline-none resize-y"
        />
        <button
          type="button"
          data-testid="license-activate"
          onClick={() => void handleActivate()}
          disabled={busy || token.trim().length === 0}
          className="self-start rounded-lg border border-accent/40 bg-accent/10 px-4 py-1.5 text-[9px] uppercase tracking-[0.18em] font-bold text-accent hover:bg-accent/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? "Verificando…" : "Activar"}
        </button>

        {attempt && (
          <p
            data-testid="license-activate-result"
            className={`text-[10px] leading-relaxed rounded border px-3 py-2 ${
              attempt.ok
                ? "text-[#C2D8C4] border-[#C2D8C4]/30 bg-[#C2D8C4]/[0.06]"
                : "text-red-400/90 border-red-500/30 bg-red-500/[0.06]"
            }`}
          >
            {attempt.message}
          </p>
        )}

        <p className="text-[8px] text-white/30 leading-relaxed">
          La verificación es local (firma Ed25519): no se envía nada a ningún
          servidor y funciona sin internet. Sin licencia, TerraQuantum corre en
          modo local libre y sin límites.
        </p>
      </div>
    </div>
  );
}
