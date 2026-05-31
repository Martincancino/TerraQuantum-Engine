"use client";

import {
  asRec,
  numOf,
  strOf,
  fmtNum,
  fmtSci,
  StatCard,
  EmptyState,
  type Tone,
} from "./analyticsShared";

function chiTone(chi: number | null): { tone: Tone; hint: string } {
  if (chi === null) return { tone: "neutral", hint: "" };
  if (chi >= 0.5 && chi <= 2) return { tone: "good", hint: "Ajuste consistente con el ruido (ideal ≈ 1)." };
  if (chi < 0.5) return { tone: "warn", hint: "χ² bajo: posible sobreajuste al ruido." };
  if (chi <= 5) return { tone: "warn", hint: "χ² alto: subajuste / sobre-regularización." };
  return { tone: "bad", hint: "χ² muy alto: el modelo no reproduce los datos." };
}

export default function SolverDiagnosticsWidget({
  report,
  inputs,
  metrics,
}: {
  report: Record<string, unknown> | null;
  inputs: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
}) {
  const fd = asRec(report?.fitDiagnostics);
  const chi = numOf(fd, "chi_squared");
  const residualL2 = numOf(fd, "residual_l2");
  const nrmse = numOf(fd, "normalized_rmse");
  const fitQuality = numOf(fd, "fit_quality");
  const fitLevel = strOf(fd, "fit_level");
  const misfit = numOf(report, "misfit_error_percent");
  const lambda = numOf(inputs, "lambda_mag") ?? numOf(report, "lambda_mag");
  const alpha = numOf(inputs, "alpha_spatial") ?? numOf(report, "alpha_spatial");
  const iterations =
    numOf(metrics, "iterations", "lsqr_iterations", "n_iter", "itn") ??
    numOf(report, "iterations", "lsqr_iterations", "n_iter", "itn");

  const hasAny =
    chi !== null || residualL2 !== null || nrmse !== null || misfit !== null;

  if (!hasAny) {
    return <EmptyState>Diagnóstico del solver no disponible para esta corrida.</EmptyState>;
  }

  const { tone, hint } = chiTone(chi);
  const fitTone: Tone =
    fitLevel === "GOOD" ? "good" : fitLevel === "MEDIUM" ? "warn" : fitLevel ? "bad" : "neutral";

  return (
    <div className="space-y-2.5">
      {/* χ² destacado */}
      <div
        className={`rounded-lg border px-3 py-2.5 flex items-center justify-between ${
          tone === "good"
            ? "border-[#C2D8C4]/30 bg-[#C2D8C4]/[0.06]"
            : tone === "warn"
            ? "border-yellow-500/30 bg-yellow-500/[0.06]"
            : tone === "bad"
            ? "border-red-500/30 bg-red-500/[0.06]"
            : "border-white/10 bg-white/[0.02]"
        }`}
      >
        <div>
          <p className="text-[7px] uppercase tracking-[0.2em] text-white/45">χ² reducido</p>
          <p className="text-[22px] font-mono leading-none mt-1">{fmtNum(chi, 3)}</p>
        </div>
        <p className="text-[8px] text-white/55 max-w-[55%] leading-tight text-right">
          {hint || "Objetivo ≈ 1.0 (< 2 aceptable)."}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        <StatCard label="Residual L2" value={fmtSci(residualL2)} />
        <StatCard label="NRMSE" value={fmtNum(nrmse, 4)} />
        <StatCard label="Misfit" value={fmtNum(misfit, 2)} unit="%" />
        <StatCard label="λ (mag)" value={fmtSci(lambda)} />
        <StatCard label="α espacial" value={fmtNum(alpha, 3)} />
        <StatCard
          label="Iteraciones"
          value={iterations !== null ? fmtNum(iterations, 0) : "≤150"}
          hint={iterations === null ? "LSQR (máx)" : undefined}
        />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[7px] uppercase tracking-[0.2em] text-white/40">Fit</span>
        <span
          className={`text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border font-bold ${
            fitTone === "good"
              ? "text-[#C2D8C4] border-[#C2D8C4]/40 bg-[#C2D8C4]/10"
              : fitTone === "warn"
              ? "text-yellow-400 border-yellow-500/40 bg-yellow-500/10"
              : fitTone === "bad"
              ? "text-red-400 border-red-500/40 bg-red-500/10"
              : "text-white/60 border-white/15"
          }`}
        >
          {fitLevel ?? "—"}
        </span>
        {fitQuality !== null && (
          <span className="text-[8px] font-mono text-white/45">quality {fmtNum(fitQuality, 2)}</span>
        )}
      </div>
    </div>
  );
}
