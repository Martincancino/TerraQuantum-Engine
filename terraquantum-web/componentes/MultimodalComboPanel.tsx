"use client";

// FASE 21 — Selector visual de combo multimodal + visualización de error.
// El usuario indica qué datos tiene cargados (sensores gravimétricos/magnéticos,
// sondajes con densidad, calidad, cobertura) y el panel consulta al backend
// (/api/multimodal/plan) qué combinación se usaría, con qué confianza y qué error
// de profundidad esperado. NO calcula física ni confianza en el cliente: sólo
// muestra la decisión que toma el backend (Regla de Oro).

import { useEffect, useState } from "react";
import {
  getMultimodalPlan,
  MULTIMODAL_ROUTE_LABELS,
  type MultimodalPlan,
} from "../lib/terraquantum/frontendApi";

type Props = {
  /** Conteos iniciales (p. ej. derivados del survey y los sondajes cargados). */
  nGravitySensors?: number;
  nMagneticSensors?: number;
  nBoreholesWithDensity?: number;
  dataQuality?: number | null;
  coveragePct?: number;
  /** Se invoca cuando hay un plan válido (combo confirmado). */
  onSelectCombo?: (plan: MultimodalPlan) => void;
};

// Escala de referencia para la barra de error (mag-only ≈ 40–55 m es el peor caso).
const ERROR_SCALE_MAX_M = 55;

function confidenceColor(pct: number): string {
  if (pct >= 80) return "#22c55e"; // verde
  if (pct >= 65) return "#eab308"; // ámbar
  return "#ef4444"; // rojo
}

export default function MultimodalComboPanel({
  nGravitySensors = 0,
  nMagneticSensors = 0,
  nBoreholesWithDensity = 0,
  dataQuality = null,
  coveragePct = 1.0,
  onSelectCombo,
}: Props) {
  // Estado interno inicializado desde props (panel autónomo: si el contenedor
  // necesita empujar conteos nuevos, puede remontar con `key`).
  const [nGrav, setNGrav] = useState(nGravitySensors);
  const [nMag, setNMag] = useState(nMagneticSensors);
  const [nBh, setNBh] = useState(nBoreholesWithDensity);
  const [dq, setDq] = useState<number | null>(dataQuality);
  const [cov, setCov] = useState(coveragePct);

  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<MultimodalPlan | null>(null);
  const [insufficient, setInsufficient] = useState<string | null>(null);

  // Recalcular el plan cuando cambian los datos disponibles. El cuerpo del efecto
  // no llama setState de forma síncrona (todo ocurre tras el await), evitando
  // renders en cascada; la petición obsoleta se descarta con `cancelled`.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const res = await getMultimodalPlan({
        n_gravity_sensors: nGrav,
        n_magnetic_sensors: nMag,
        n_boreholes_with_density: nBh,
        data_quality: dq,
        coverage_pct: cov,
      });
      if (cancelled) return;
      if (!res.ok || !res.data) {
        setError(res.error ?? "No se pudo calcular el combo recomendado.");
        setPlan(null);
        setInsufficient(null);
        return;
      }
      setError(null);
      setPlan(res.data.plan);
      setInsufficient(res.data.insufficient_reason);
    })();
    return () => {
      cancelled = true;
    };
  }, [nGrav, nMag, nBh, dq, cov]);

  const errorPct = plan
    ? Math.min(100, (plan.error_depth_m / ERROR_SCALE_MAX_M) * 100)
    : 0;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-700 bg-slate-900/60 p-4 text-slate-200">
      <div>
        <h3 className="text-base font-semibold text-slate-100">
          Fusión multimodal (Fase 21)
        </h3>
        <p className="text-xs text-slate-400">
          Indica qué datos tienes y el backend recomienda el combo, su confianza y
          el error de profundidad esperado.
        </p>
      </div>

      {/* Checklist editable de datos disponibles */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <CountField label="Sensores gravimetría" value={nGrav} onChange={setNGrav} />
        <CountField label="Sensores magnetometría" value={nMag} onChange={setNMag} />
        <CountField label="Sondajes con densidad" value={nBh} onChange={setNBh} />
        <label className="flex flex-col text-xs text-slate-400">
          Calidad de datos (0–100, opcional)
          <input
            type="number"
            min={0}
            max={100}
            value={dq ?? ""}
            placeholder="—"
            onChange={(e) =>
              setDq(e.target.value === "" ? null : Number(e.target.value))
            }
            className="mt-1 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100"
          />
        </label>
        <label className="flex flex-col text-xs text-slate-400 sm:col-span-2">
          Cobertura espacial: {(cov * 100).toFixed(0)}%
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={cov}
            onChange={(e) => setCov(Number(e.target.value))}
            className="mt-1 accent-indigo-500"
          />
        </label>
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      {insufficient && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          {insufficient}
        </div>
      )}

      {plan && (
        <div className="flex flex-col gap-3">
          {/* Combo recomendado */}
          <div className="rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">
              Combo recomendado
            </div>
            <div className="text-sm font-semibold text-slate-100">
              {MULTIMODAL_ROUTE_LABELS[plan.route] ?? plan.route}
            </div>
          </div>

          {/* Confianza */}
          <div>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Confianza</span>
              <span className="font-semibold text-slate-100">
                {plan.confidence_pct.toFixed(0)}%
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-700">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${plan.confidence_pct}%`,
                  backgroundColor: confidenceColor(plan.confidence_pct),
                }}
              />
            </div>
          </div>

          {/* Error de profundidad — visualización de banda de incertidumbre */}
          <div>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Error de profundidad esperado</span>
              <span className="font-semibold text-slate-100">
                ±{plan.error_depth_m.toFixed(0)} m
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              {/* Marcador del objetivo + banda ± a cada lado */}
              <div className="relative h-6 flex-1 rounded bg-slate-800">
                <div
                  className="absolute inset-y-0 left-1/2 -translate-x-1/2 rounded bg-indigo-500/30"
                  style={{ width: `${errorPct}%` }}
                  title={`Banda de incertidumbre ±${plan.error_depth_m.toFixed(0)} m`}
                />
                <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-indigo-300" />
              </div>
            </div>
            <p className="mt-1 text-[10px] text-slate-500">
              Banda ± alrededor de la profundidad estimada del cuerpo. Más angosta =
              localización más precisa.
            </p>
          </div>

          {/* Avisos */}
          {plan.warnings.length > 0 && (
            <div className="flex flex-col gap-1">
              {plan.warnings.map((w, i) => (
                <div
                  key={i}
                  className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-300"
                >
                  ⚠ {w}
                </div>
              ))}
            </div>
          )}

          {/* Prioridad de resolución de conflictos */}
          <div className="text-[10px] text-slate-500">
            Prioridad ante conflicto: {plan.resolution_priority.join(" › ")}
          </div>

          {onSelectCombo && (
            <button
              onClick={() => onSelectCombo(plan)}
              className="self-start rounded bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500"
            >
              ✓ Continuar con este combo
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function CountField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <label className="flex flex-col text-xs text-slate-400">
      {label}
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
        className="mt-1 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100"
      />
    </label>
  );
}
