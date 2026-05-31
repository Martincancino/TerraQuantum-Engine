"use client";

import React from "react";
import { useAppStore } from "../../store/useAppStore";

function formatInteger(value: unknown) {
  const n = Number(value || 0);
  return n.toLocaleString("en-US", {
    maximumFractionDigits: 0,
  });
}

function formatDecimal(value: unknown, decimals = 2) {
  const n = Number(value || 0);
  return n.toFixed(decimals);
}

function mapPriorityClassLabel(value: string) {
  const v = String(value || "").toUpperCase().trim();
  if (v === "HIGH_RELATIVE_PRIORITY" || v === "DRILL") return "Prioridad relativa alta";
  if (v === "MEDIUM_RELATIVE_PRIORITY" || v === "OBSERVE" || v === "WAIT") return "Prioridad relativa media";
  if (v === "LOW_RELATIVE_PRIORITY") return "Prioridad relativa baja";
  if (v === "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE" || v === "UNCLASSIFIED") return "Sin clasificar";
  return v || "N/A";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  return value as Record<string, unknown>;
}

function readObjectField(value: unknown, key: string): Record<string, unknown> {
  const record = asRecord(value);
  const field = record?.[key];

  return asRecord(field) ?? {};
}

function readNumberField(value: unknown, key: string, fallback = 0): number {
  const record = asRecord(value);
  const n = Number(record?.[key]);

  return Number.isFinite(n) ? n : fallback;
}

function readStringField(value: unknown, key: string, fallback = ""): string {
  const record = asRecord(value);
  const field = record?.[key];

  return typeof field === "string" && field.trim().length > 0 ? field : fallback;
}


function readFirstNumber(fallback: number, ...fields: Array<[unknown, string]>): number {
  for (const [value, key] of fields) {
    const n = readNumberField(value, key, Number.NaN);

    if (Number.isFinite(n)) return n;
  }

  return fallback;
}

function reliabilityStyles(level: string) {
  const v = String(level || "").toUpperCase();

  if (v === "HIGH") {
    return {
      label: "CONFIABILIDAD ALTA",
      badge: "text-[#C2D8C4] border-[#C2D8C4]/30 bg-[#C2D8C4]/10",
      dot: "bg-[#C2D8C4]",
    };
  }

  if (v === "MEDIUM") {
    return {
      label: "CONFIABILIDAD MEDIA",
      badge: "text-yellow-200 border-yellow-500/30 bg-yellow-500/10",
      dot: "bg-yellow-300",
    };
  }

  return {
    label: "CONFIABILIDAD BAJA",
    badge: "text-red-200 border-red-500/30 bg-red-500/10",
    dot: "bg-red-400",
  };
}

export default function ExecutiveGeoReport() {
  const { report } = useAppStore();

  if (!report) return null;

  const reportRecord = asRecord(report);
  const backendReport = readObjectField(reportRecord, "backendReport");
  const bestTarget = asRecord(reportRecord?.rawBestTarget);

  const recommendation = mapPriorityClassLabel(
    readStringField(backendReport, "priority_class") ||
      readStringField(backendReport, "drill_recommendation") ||
      readStringField(backendReport, "recommendation") ||
      "OBSERVE"
  );

  const probability = Math.round(
    readFirstNumber(
      0,
      [backendReport, "max_probability"],
      [backendReport, "target_score"],
      [reportRecord, "score"],
      [reportRecord, "indiceAnomalia"]
    ) * 100
  );

  const maxDensity = readFirstNumber(
    0,
    [backendReport, "max_density"],
    [reportRecord, "anomaliaPico"]
  );

  const avgDensity = readNumberField(backendReport, "avg_density");

  // Prioridad: avg_grade calculada por el backend. Fallback: leyEstimada es supuesto del usuario.
  const avgGrade = readFirstNumber(
    0,
    [backendReport, "avg_anomaly_intensity"],
    [backendReport, "avg_grade"],
    [reportRecord, "leyEstimada"] // supuesto del usuario — no dato medido del yacimiento
  );

  const totalTonnage = readNumberField(
    backendReport,
    "estimated_total_tonnage",
    readNumberField(reportRecord, "masaKg") / 1000
  );

  const anomalyTonnage = readFirstNumber(
    0,
    [backendReport, "estimated_anomaly_tonnage"],
    [reportRecord, "estimatedAnomalyTonnage"]
  );

  const anomalyScore = readFirstNumber(
    0,
    [backendReport, "anomaly_score"],
    [reportRecord, "score"]
  );

  const cutoffDensity = readNumberField(backendReport, "cutoff_density");

  const risk = reliabilityStyles(
    readStringField(backendReport, "model_reliability_level") ||
      readStringField(backendReport, "risk_level", "LOW")
  );

  return (
    <div className="w-full rounded-[28px] border border-white/10 bg-[#070908]/90 backdrop-blur-xl shadow-[0_0_45px_rgba(0,0,0,0.35)] overflow-hidden">
      <div className="px-6 py-5 border-b border-white/10">
        <div className="flex items-start justify-between gap-5">
          <div className="min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <span className={`h-2 w-2 rounded-full ${risk.dot}`} />
              <span className="text-[9px] uppercase tracking-[0.32em] text-neutral-500 font-black">
                Reporte ejecutivo
              </span>
            </div>

            <h2 className="text-white text-[22px] md:text-[26px] font-black leading-tight">
              Target Geofísico
            </h2>

            <p className="mt-2 text-[12px] text-neutral-400 leading-relaxed max-w-2xl">
              Lectura resumida del modelo gravimétrico, densidad, intensidad de anomalía
              y target de prioridad relativa. Score relativo del modelo; no es probabilidad real de mineralización.
            </p>
          </div>

          <span
            className={`shrink-0 rounded-full border px-4 py-2 text-[9px] uppercase tracking-[0.24em] font-black ${risk.badge}`}
          >
            {risk.label}
          </span>
        </div>
      </div>

      <div className="p-6 space-y-6">
        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <MetricCard label="Clase de prioridad relativa" value={recommendation} accent />
          <MetricCard label="Target Score" value={`${probability}%`} />
          <MetricCard
            label="Densidad máx."
            value={formatDecimal(maxDensity, 3)}
            suffix="t/m3"
          />
          <MetricCard
            label="Density Proxy Index"
            value={formatDecimal(avgGrade, 3)}
            suffix="(Índice de Interés)"
          />
        </div>

        <div className="grid xl:grid-cols-2 gap-5">
          <SectionCard eyebrow="Tonelaje estimado" badge="Block Model">
            <div className="grid sm:grid-cols-2 gap-4">
              <SmallCard label="Total" value={`${formatInteger(totalTonnage)} t`} />
              <SmallCard
                label="Anomalía"
                value={`${formatInteger(anomalyTonnage)} t`}
              />
            </div>
          </SectionCard>

          <SectionCard eyebrow="Coordenada objetivo" badge="Primary Lock">
            {bestTarget ? (
              <div className="grid grid-cols-3 gap-4">
                <SmallCard label="X" value={formatDecimal(readNumberField(bestTarget, "x_m"), 1)} />
                <SmallCard label="Y" value={formatDecimal(readNumberField(bestTarget, "y_m"), 1)} />
                <SmallCard label="Z" value={formatDecimal(readNumberField(bestTarget, "z_m"), 1)} />
              </div>
            ) : (
              <div className="rounded-2xl border border-white/10 bg-black/30 px-4 py-4 text-[12px] text-neutral-400">
                Sin coordenada objetivo disponible.
              </div>
            )}
          </SectionCard>
        </div>

        <div className="grid sm:grid-cols-3 gap-4">
          <SmallCard
            label="Densidad promedio"
            value={`${formatDecimal(avgDensity, 3)} t/m3`}
          />
          <SmallCard label="Anomaly score" value={formatDecimal(anomalyScore, 3)} />
          <SmallCard
            label="Cutoff densidad"
            value={`${formatDecimal(cutoffDensity, 3)} t/m3`}
          />
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  eyebrow,
  badge,
  children,
}: {
  eyebrow: string;
  badge: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/2.5 p-5">
      <div className="flex items-center justify-between gap-4 mb-5">
        <p className="text-[9px] uppercase tracking-[0.26em] text-neutral-500 font-black">
          {eyebrow}
        </p>

        <p className="text-[9px] uppercase tracking-[0.26em] text-cyan-300 font-black">
          {badge}
        </p>
      </div>

      {children}
    </div>
  );
}

function MetricCard({
  label,
  value,
  suffix,
  accent = false,
}: {
  label: string;
  value: string;
  suffix?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-[22px] border px-5 py-5 min-h-35 flex flex-col justify-between ${
        accent
          ? "border-[#C2D8C4]/25 bg-[#C2D8C4]/10"
          : "border-white/10 bg-black/30"
      }`}
    >
      <p className="text-[9px] uppercase tracking-[0.24em] text-neutral-500 font-black leading-relaxed">
        {label}
      </p>

      <div className="flex items-end gap-2 flex-wrap">
        <span className="text-[28px] md:text-[34px] font-black text-white leading-none wrap-break-word">
          {value}
        </span>

        {suffix && (
          <span className="text-[12px] text-neutral-500 font-bold leading-none mb-1">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

function SmallCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-white/10 bg-black/30 px-4 py-4 min-h-26 flex flex-col justify-between">
      <p className="text-[9px] uppercase tracking-[0.22em] text-neutral-500 font-black leading-relaxed">
        {label}
      </p>

      <p className="text-[20px] md:text-[24px] font-black text-white leading-tight wrap-break-word">
        {value}
      </p>
    </div>
  );
}
