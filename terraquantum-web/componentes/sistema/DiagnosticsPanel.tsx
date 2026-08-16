"use client";

// ─── FASE 9 (H-10) — Exportar diagnóstico ─────────────────────────────────────
//
// F7 dejó `GET /diagnostics/manifest` y `GET /diagnostics/export` sin consumidor:
// cuando algo falla, el cliente no tenía forma de enviar un diagnóstico salvo
// pidiéndole que abriera una terminal.
//
// El panel muestra PRIMERO qué contiene el paquete y sólo después ofrece la
// descarga. Es deliberado: la promesa de confidencialidad («ningún dato de
// survey sale de tu máquina») sólo vale si se puede comprobar mirando. El
// backend ya recorta secretos y excluye parquets/CSV; aquí se enseña el
// resultado, no se repite la promesa.

import { useEffect, useState } from "react";
import {
  DIAGNOSTICS_EXPORT_URL,
  getDiagnosticManifest,
  type DiagnosticManifest,
} from "../../lib/terraquantum/systemApi";

/** Lo que el backend mete en el ZIP (`services/diagnostics_service.py`). */
const CONTENIDO = [
  ["system.json", "versión de la app, Python, sistema operativo, ruta de datos"],
  ["packages.txt", "versiones de las librerías clave"],
  ["config.json", "configuración saneada — sin claves ni tokens"],
  ["connectivity.json", "qué funciones necesitan internet"],
  ["license.json", "estado del tier, sin material secreto"],
  ["recent_errors.json", "últimos errores a nivel de código"],
] as const;

export default function DiagnosticsPanel() {
  const [manifest, setManifest] = useState<DiagnosticManifest | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const res = await getDiagnosticManifest();
      if (!alive) return;
      if (!res.ok || !res.data) {
        setManifest(null);
        setError(res.error ?? "No se pudo generar el diagnóstico.");
        return;
      }
      setError(null);
      setManifest(res.data);
    })();
    return () => {
      alive = false;
    };
  }, []);

  const system = (manifest?.system ?? {}) as Record<string, unknown>;
  const nErrors = Array.isArray(manifest?.recent_errors) ? manifest.recent_errors.length : 0;

  return (
    <div className="flex flex-col gap-4" data-testid="diagnostics-panel">
      <p className="text-[10px] leading-relaxed text-white/60">
        Genera un archivo con la información técnica necesaria para diagnosticar un
        problema. Lo descargas tú y lo envías tú: nada sale de esta máquina de
        forma automática.
      </p>

      {/* ── Qué va dentro ──────────────────────────────────────────────────── */}
      <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
        <p className="text-[9px] uppercase tracking-[0.16em] text-white/40 mb-2">
          Contenido del paquete
        </p>
        <ul className="flex flex-col gap-1">
          {CONTENIDO.map(([file, desc]) => (
            <li key={file} className="flex items-start gap-2">
              <span className="text-[9px] font-mono text-accent/80 shrink-0 w-[112px]">
                {file}
              </span>
              <span className="text-[9px] text-white/50 leading-relaxed">{desc}</span>
            </li>
          ))}
        </ul>
        <p className="text-[8.5px] text-white/40 mt-2.5 leading-relaxed border-t border-white/[0.06] pt-2">
          <span className="text-white/60">No incluye</span>, a propósito: ningún dato
          de survey (CSV, parquet, coordenadas, valores medidos), ninguna clave ni
          credencial, ningún cuerpo de petición.
        </p>
      </div>

      {/* ── Lo que se está a punto de enviar, medido ───────────────────────── */}
      {error && (
        <p className="text-[10px] text-yellow-400/80 font-mono leading-relaxed">{error}</p>
      )}

      {manifest && (
        <div className="grid grid-cols-2 gap-2" data-testid="diagnostics-summary">
          <Stat label="Versión" value={String(system.app_version ?? "—")} />
          <Stat label="Plataforma" value={String(system.platform ?? "—")} />
          <Stat
            label="Paquetes"
            value={String(Object.keys(manifest.packages ?? {}).length)}
          />
          <Stat
            label="Errores recientes"
            value={String(nErrors)}
            hint={nErrors === 0 ? "nada que reportar" : undefined}
          />
        </div>
      )}

      {/* ── Descarga ───────────────────────────────────────────────────────── */}
      <a
        data-testid="diagnostics-export"
        href={DIAGNOSTICS_EXPORT_URL}
        download
        className="self-start rounded-lg border border-accent/40 bg-accent/10 px-4 py-1.5 text-[9px] uppercase tracking-[0.18em] font-bold text-accent hover:bg-accent/20 transition-colors"
      >
        Exportar diagnóstico (.zip)
      </a>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.02] px-2.5 py-2">
      <p className="text-[7.5px] uppercase tracking-[0.18em] text-white/40 mb-1">{label}</p>
      <p className="text-[11px] font-mono text-white/85 leading-none break-all">{value}</p>
      {hint && <p className="text-[7.5px] text-white/35 mt-1">{hint}</p>}
    </div>
  );
}
