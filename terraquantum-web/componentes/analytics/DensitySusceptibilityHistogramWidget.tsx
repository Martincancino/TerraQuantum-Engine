"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { EmptyState, buildHistogram, axisProps, tooltipStyle } from "./analyticsShared";

/**
 * F5 — Histograma de densidad (y susceptibilidad, si el run es joint/mag) sobre
 * las celdas activas YA cargadas por el visor. No calcula física: solo cuenta
 * valores que el backend ya entregó por vóxel (density / susceptibility_si).
 */
export default function DensitySusceptibilityHistogramWidget({
  cells,
}: {
  cells: Record<string, unknown>[];
}) {
  const active = cells.filter((c) => c.is_active !== false && c.is_active !== 0);

  const density = active
    .map((c) => Number(c.density ?? c.modeled_density_index ?? c.rho))
    .filter((v) => Number.isFinite(v));

  const susceptibility = active
    .map((c) => Number(c.susceptibility_si))
    .filter((v) => Number.isFinite(v));

  if (density.length === 0 && susceptibility.length === 0) {
    return <EmptyState>Sin datos de densidad/susceptibilidad para esta corrida.</EmptyState>;
  }

  const densityBins = buildHistogram(density, 24);
  const chiBins = susceptibility.length > 0 ? buildHistogram(susceptibility, 24) : [];

  return (
    <div className="space-y-3">
      {density.length > 0 && (
        <div>
          <p className="text-[7px] uppercase tracking-[0.18em] text-white/40 mb-1">
            Densidad (t/m³) — {density.length.toLocaleString()} vóxeles activos
          </p>
          <div className="h-[130px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={densityBins} margin={{ top: 4, right: 8, bottom: 2, left: -18 }}>
                <XAxis
                  dataKey="mid"
                  type="number"
                  {...axisProps}
                  tickFormatter={(v: number) => v.toFixed(2)}
                />
                <YAxis {...axisProps} allowDecimals={false} width={30} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  formatter={(value) => [String(value), "vóxeles"]}
                  labelFormatter={(label) => `ρ ≈ ${Number(label).toFixed(3)} t/m³`}
                />
                <Bar dataKey="count" fill="#22d3ee" fillOpacity={0.75} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {chiBins.length > 0 && (
        <div>
          <p className="text-[7px] uppercase tracking-[0.18em] text-white/40 mb-1">
            Susceptibilidad (SI) — {susceptibility.length.toLocaleString()} vóxeles activos
          </p>
          <div className="h-[130px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chiBins} margin={{ top: 4, right: 8, bottom: 2, left: -18 }}>
                <XAxis
                  dataKey="mid"
                  type="number"
                  {...axisProps}
                  tickFormatter={(v: number) => v.toExponential(1)}
                />
                <YAxis {...axisProps} allowDecimals={false} width={30} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  formatter={(value) => [String(value), "vóxeles"]}
                  labelFormatter={(label) => `χ ≈ ${Number(label).toExponential(2)} SI`}
                />
                <Bar dataKey="count" fill="#eab308" fillOpacity={0.75} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
