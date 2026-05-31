"use client";
import {
  asRecord,
  fmtNum,
  fmtSci,
  levelCls,
  residualLevelCls,
  uncertaintyLevelCls,
  sensorFlagLevelCls,
} from "./helpers";
import type {
  ProjectRunDetail,
  TechnicalSummary,
  UncertaintyDiagnostics,
  SensorQualityFlags,
  FitDiagnostics,
  ObservationQuality,
  ResidualPoint,
} from "./types";

interface RunDiagnosticsPanelProps {
  detail: ProjectRunDetail;
}

export default function RunDiagnosticsPanel({ detail }: RunDiagnosticsPanelProps) {
  const reportRaw = detail.report;
  if (!reportRaw) return null;

  const tsRaw = asRecord(reportRaw["technicalSummary"]);
  const ts: TechnicalSummary | null = tsRaw
    ? {
        overall_level: typeof tsRaw["overall_level"] === "string" ? tsRaw["overall_level"] : undefined,
        survey_level: typeof tsRaw["survey_level"] === "string" ? tsRaw["survey_level"] : undefined,
        fit_level: typeof tsRaw["fit_level"] === "string" ? tsRaw["fit_level"] : undefined,
        residual_level: typeof tsRaw["residual_level"] === "string" ? tsRaw["residual_level"] : undefined,
        summary: typeof tsRaw["summary"] === "string" ? tsRaw["summary"] : undefined,
        key_findings: Array.isArray(tsRaw["key_findings"]) ? (tsRaw["key_findings"] as unknown[]).filter((w): w is string => typeof w === "string") : [],
        warnings: Array.isArray(tsRaw["warnings"]) ? (tsRaw["warnings"] as unknown[]).filter((w): w is string => typeof w === "string") : [],
        recommended_next_steps: Array.isArray(tsRaw["recommended_next_steps"]) ? (tsRaw["recommended_next_steps"] as unknown[]).filter((w): w is string => typeof w === "string") : [],
      }
    : null;

  const udRaw = asRecord(reportRaw["uncertaintyDiagnostics"]);
  const ud: UncertaintyDiagnostics | null = udRaw
    ? {
        uncertainty_level: typeof udRaw["uncertainty_level"] === "string" ? udRaw["uncertainty_level"] : undefined,
        uncertainty_score: typeof udRaw["uncertainty_score"] === "number" ? udRaw["uncertainty_score"] : undefined,
        interpretation: typeof udRaw["interpretation"] === "string" ? udRaw["interpretation"] : undefined,
        recommended_action: typeof udRaw["recommended_action"] === "string" ? udRaw["recommended_action"] : undefined,
        drivers: Array.isArray(udRaw["drivers"]) ? (udRaw["drivers"] as unknown[]).filter((w): w is string => typeof w === "string") : [],
      }
    : null;

  const sqfRaw = asRecord(reportRaw["sensorQualityFlags"]);
  const sqf: SensorQualityFlags | null = sqfRaw
    ? {
        sensor_count: typeof sqfRaw["sensor_count"] === "number" ? sqfRaw["sensor_count"] : undefined,
        flagged_count: typeof sqfRaw["flagged_count"] === "number" ? sqfRaw["flagged_count"] : undefined,
        flagged_ratio: typeof sqfRaw["flagged_ratio"] === "number" ? sqfRaw["flagged_ratio"] : undefined,
        flag_level: typeof sqfRaw["flag_level"] === "string" ? sqfRaw["flag_level"] : undefined,
        summary: typeof sqfRaw["summary"] === "string" ? sqfRaw["summary"] : undefined,
        recommended_action: typeof sqfRaw["recommended_action"] === "string" ? sqfRaw["recommended_action"] : undefined,
        flagged_sensors: Array.isArray(sqfRaw["flagged_sensors"])
          ? (sqfRaw["flagged_sensors"] as Record<string, unknown>[]).map(s => ({
              sensor_index: typeof s["sensor_index"] === "number" ? s["sensor_index"] : undefined,
              x_m: typeof s["x_m"] === "number" ? s["x_m"] : undefined,
              y_m: typeof s["y_m"] === "number" ? s["y_m"] : undefined,
              z_m: typeof s["z_m"] === "number" ? s["z_m"] : undefined,
              residual: typeof s["residual"] === "number" ? s["residual"] : undefined,
              abs_residual: typeof s["abs_residual"] === "number" ? s["abs_residual"] : undefined,
              normalized_residual: typeof s["normalized_residual"] === "number" ? s["normalized_residual"] : undefined,
              residual_level: typeof s["residual_level"] === "string" ? s["residual_level"] : undefined,
              review_priority: typeof s["review_priority"] === "string" ? s["review_priority"] : undefined,
              flags: Array.isArray(s["flags"]) ? (s["flags"] as unknown[]).filter((f): f is string => typeof f === "string") : [],
            }))
          : [],
      }
    : null;

  const qaqcRaw = asRecord(reportRaw["observationQuality"]);
  const oq: ObservationQuality | null = qaqcRaw
    ? {
        quality_level: typeof qaqcRaw["quality_level"] === "string" ? qaqcRaw["quality_level"] : undefined,
        quality_score: typeof qaqcRaw["quality_score"] === "number" ? qaqcRaw["quality_score"] : undefined,
        observation_count: typeof qaqcRaw["observation_count"] === "number" ? qaqcRaw["observation_count"] : undefined,
        coverage_ratio_x: typeof qaqcRaw["coverage_ratio_x"] === "number" ? qaqcRaw["coverage_ratio_x"] : undefined,
        coverage_ratio_z: typeof qaqcRaw["coverage_ratio_z"] === "number" ? qaqcRaw["coverage_ratio_z"] : undefined,
        signal_dynamic_range: typeof qaqcRaw["signal_dynamic_range"] === "number" ? qaqcRaw["signal_dynamic_range"] : undefined,
        g_std: typeof qaqcRaw["g_std"] === "number" ? qaqcRaw["g_std"] : undefined,
        warnings: Array.isArray(qaqcRaw["warnings"]) ? (qaqcRaw["warnings"] as unknown[]).filter((w): w is string => typeof w === "string") : [],
      }
    : null;

  const fdRaw = asRecord(reportRaw["fitDiagnostics"]);
  const fd: FitDiagnostics | null = fdRaw
    ? {
        fit_level: typeof fdRaw["fit_level"] === "string" ? fdRaw["fit_level"] : undefined,
        fit_quality: typeof fdRaw["fit_quality"] === "number" ? fdRaw["fit_quality"] : undefined,
        residual_rmse: typeof fdRaw["residual_rmse"] === "number" ? fdRaw["residual_rmse"] : undefined,
        residual_mae: typeof fdRaw["residual_mae"] === "number" ? fdRaw["residual_mae"] : undefined,
        residual_bias: typeof fdRaw["residual_bias"] === "number" ? fdRaw["residual_bias"] : undefined,
        normalized_rmse: typeof fdRaw["normalized_rmse"] === "number" ? fdRaw["normalized_rmse"] : undefined,
        residual_l2: typeof fdRaw["residual_l2"] === "number" ? fdRaw["residual_l2"] : undefined,
        residualMap: Array.isArray(fdRaw["residualMap"])
          ? (fdRaw["residualMap"] as unknown[]).filter((p): p is ResidualPoint => typeof p === "object" && p !== null)
          : null,
      }
    : null;

  const resMap: ResidualPoint[] = fd?.residualMap ?? [];
  const topResiduals = [...resMap]
    .sort((a, b) => (b.abs_residual ?? 0) - (a.abs_residual ?? 0))
    .slice(0, 8);

  const countByLevel = (level: string) => resMap.filter((p) => p.residual_level === level).length;

  const validMapPoints = resMap.filter(
    (p) => typeof p.x_m === "number" && Number.isFinite(p.x_m) && typeof p.z_m === "number" && Number.isFinite(p.z_m)
  );
  const hasMapPoints = validMapPoints.length > 0;

  let xMin = 0, xMax = 0, zMin = 0, zMax = 0;
  if (hasMapPoints) {
    xMin = Math.min(...validMapPoints.map((p) => p.x_m!));
    xMax = Math.max(...validMapPoints.map((p) => p.x_m!));
    zMin = Math.min(...validMapPoints.map((p) => p.z_m!));
    zMax = Math.max(...validMapPoints.map((p) => p.z_m!));
  }

  const toPercent = (value: number, min: number, max: number) => {
    if (max === min) return 50;
    return ((value - min) / (max - min)) * 100;
  };

  const getResidualDotClass = (level: string | undefined) => {
    if (level === "LOW") return "bg-[#C2D8C4] shadow-[0_0_4px_rgba(194,216,196,0.6)]";
    if (level === "MEDIUM") return "bg-yellow-500 shadow-[0_0_4px_rgba(234,179,8,0.6)]";
    if (level === "HIGH") return "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.8)]";
    return "bg-neutral-500";
  };

  return (
    <div className="border border-neutral-800 bg-black/40 rounded-xl p-4 space-y-4">
      <p className="text-[10px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold border-l-2 border-[#C2D8C4] pl-3">
        Diagnóstico geofísico
      </p>

      {/* ── Technical Summary ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-4">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">Resumen técnico</p>
        {ts ? (
          <div className="space-y-4">
            <div className="flex flex-col gap-2 border-b border-neutral-900 pb-3">
              <div className="flex items-center gap-3">
                <span className={`text-[10px] uppercase tracking-widest px-3 py-1 rounded border font-bold ${levelCls(ts.overall_level)}`}>
                  OVERALL: {ts.overall_level ?? "—"}
                </span>
                <span className="text-[11px] text-white font-light">{ts.summary ?? "—"}</span>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {[
                ["Survey", ts.survey_level],
                ["Fit", ts.fit_level],
                ["Residual Map", ts.residual_level],
              ].map(([label, lvl], i) => (
                <div key={i} className="flex flex-col gap-1">
                  <p className="text-[8px] uppercase tracking-widest text-neutral-600">{label}</p>
                  <span className={`text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border w-max font-bold ${levelCls(lvl)}`}>
                    {lvl ?? "—"}
                  </span>
                </div>
              ))}
            </div>

            {ts.key_findings && ts.key_findings.length > 0 && (
              <div>
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Hallazgos clave</p>
                <ul className="list-disc list-inside text-[9px] text-neutral-300 font-mono space-y-0.5">
                  {ts.key_findings.map((kf, i) => <li key={i}>{kf}</li>)}
                </ul>
              </div>
            )}

            {ts.warnings && ts.warnings.length > 0 && (
              <div>
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Warnings</p>
                <ul className="list-disc list-inside text-[9px] text-yellow-500 font-mono space-y-0.5">
                  {ts.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}

            {ts.recommended_next_steps && ts.recommended_next_steps.length > 0 && (
              <div>
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Próximos pasos recomendados</p>
                <ul className="list-disc list-inside text-[9px] text-[#C2D8C4] font-mono space-y-0.5">
                  {ts.recommended_next_steps.map((step, i) => <li key={i}>{step}</li>)}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500 font-mono">Resumen técnico no disponible para esta corrida.</p>
        )}
      </div>

      {/* ── Uncertainty Diagnostics ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-4">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">Incertidumbre geofísica</p>
        {ud ? (
          <div className="space-y-4">
            <div className="flex flex-col gap-2 border-b border-neutral-900 pb-3">
              <div className="flex items-center gap-3">
                <span className={`text-[10px] uppercase tracking-widest px-3 py-1 rounded border font-bold ${uncertaintyLevelCls(ud.uncertainty_level)}`}>
                  {ud.uncertainty_level ?? "—"}
                </span>
                <span className="text-[9px] text-neutral-400 font-mono">
                  Score: {fmtNum(ud.uncertainty_score, 3)}
                </span>
              </div>
              <p className="text-[11px] text-white font-light mt-1">{ud.interpretation ?? "—"}</p>
            </div>

            {ud.drivers && ud.drivers.length > 0 && (
              <div>
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Drivers de incertidumbre</p>
                <ul className="list-disc list-inside text-[9px] text-neutral-300 font-mono space-y-0.5">
                  {ud.drivers.map((driver, i) => <li key={i}>{driver}</li>)}
                </ul>
              </div>
            )}

            {ud.recommended_action && (
              <div>
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">Acción recomendada</p>
                <p className="text-[9px] text-[#C2D8C4] font-mono">{ud.recommended_action}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500 font-mono">Diagnóstico de incertidumbre no disponible para esta corrida.</p>
        )}
      </div>

      {/* ── Sensor Quality Flags ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-4">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">Sensores a revisar</p>
        {sqf ? (
          <div className="space-y-4">
            <div className="flex flex-col gap-2 border-b border-neutral-900 pb-3">
              <div className="flex items-center gap-3">
                <span className={`text-[10px] uppercase tracking-widest px-3 py-1 rounded border font-bold ${sensorFlagLevelCls(sqf.flag_level)}`}>
                  {sqf.flag_level ?? "—"}
                </span>
                <span className="text-[9px] text-neutral-400 font-mono">
                  Sensores marcados: {sqf.flagged_count ?? 0} / {sqf.sensor_count ?? 0} ({(sqf.flagged_ratio ? sqf.flagged_ratio * 100 : 0).toFixed(1)}%)
                </span>
              </div>
              <p className="text-[11px] text-white font-light mt-1">{sqf.summary ?? "—"}</p>
              {sqf.recommended_action && (
                <p className="text-[9px] text-[#C2D8C4] font-mono mt-1">{sqf.recommended_action}</p>
              )}
            </div>

            <div>
              <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-2">Sensores marcados</p>
              {sqf.flagged_sensors && sqf.flagged_sensors.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-max">
                    <thead>
                      <tr className="border-b border-neutral-800">
                        {["idx", "x_m", "y_m", "z_m", "residual", "norm_res", "res_level", "priority", "flags"].map((h) => (
                          <th key={h} className="pb-2 pr-3 text-[8px] uppercase text-neutral-500 font-normal">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="text-[9px] font-mono text-neutral-300">
                      {sqf.flagged_sensors.slice(0, 10).map((s, i) => (
                        <tr key={i} className="border-b border-neutral-900/50 hover:bg-neutral-900/30">
                          <td className="py-1.5 pr-3 text-neutral-500">{s.sensor_index ?? "—"}</td>
                          <td className="py-1.5 pr-3">{fmtNum(s.x_m, 1)}</td>
                          <td className="py-1.5 pr-3">{fmtNum(s.y_m, 1)}</td>
                          <td className="py-1.5 pr-3">{fmtNum(s.z_m, 1)}</td>
                          <td className="py-1.5 pr-3">{fmtSci(s.residual)}</td>
                          <td className="py-1.5 pr-3">{fmtNum(s.normalized_residual, 3)}</td>
                          <td className="py-1.5 pr-3">
                            <span className={residualLevelCls(s.residual_level)}>
                              {s.residual_level ?? "—"}
                            </span>
                          </td>
                          <td className="py-1.5 pr-3">
                            <span className={`px-1 py-0.5 rounded text-[7px] ${sensorFlagLevelCls(s.review_priority)}`}>
                              {s.review_priority ?? "—"}
                            </span>
                          </td>
                          <td className="py-1.5 pr-3">
                            <div className="flex flex-wrap gap-1">
                              {(s.flags || []).map((f, j) => (
                                <span key={j} className="text-[7px] px-1 bg-neutral-800 text-neutral-400 rounded">
                                  {f}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {sqf.flagged_sensors.length > 10 && (
                    <p className="text-[8px] text-neutral-500 mt-2 italic font-mono">
                      Mostrando 10 de {sqf.flagged_sensors.length} sensores marcados.
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-[9px] text-neutral-500 font-mono">No hay sensores marcados para revisión.</p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500 font-mono">Diagnóstico de sensores no disponible para esta corrida.</p>
        )}
      </div>

      {/* ── QA/QC ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-3">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">QA/QC de observaciones</p>
        {oq ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <span className={`text-[8px] uppercase tracking-widest px-2 py-1 rounded border font-bold ${levelCls(oq.quality_level)}`}>
                {oq.quality_level ?? "—"}
              </span>
              <span className="text-[9px] text-neutral-400 font-mono self-center">
                Score: {fmtNum(oq.quality_score, 2)} &nbsp;|&nbsp; Obs: {oq.observation_count ?? "—"}
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {([
                ["coverage_x", fmtNum(oq.coverage_ratio_x, 3)],
                ["coverage_z", fmtNum(oq.coverage_ratio_z, 3)],
                ["dyn_range", fmtSci(oq.signal_dynamic_range)],
                ["g_std", fmtSci(oq.g_std)],
              ] as [string, string][]).map(([label, val]) => (
                <div key={label}>
                  <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">{label}</p>
                  <p className="text-[10px] text-white font-mono">{val}</p>
                </div>
              ))}
            </div>
            {oq.warnings && oq.warnings.length > 0 ? (
              <div className="space-y-1">
                {oq.warnings.map((w, i) => (
                  <p key={i} className="text-[9px] text-yellow-400 font-mono">⚠ {w}</p>
                ))}
              </div>
            ) : (
              <p className="text-[9px] text-neutral-500 font-mono">Sin advertencias.</p>
            )}
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500">QA/QC no disponible para esta corrida.</p>
        )}
      </div>

      {/* ── Observed vs Modeled ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-3">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">Observed vs Modeled</p>
        {fd ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <span className={`text-[8px] uppercase tracking-widest px-2 py-1 rounded border font-bold ${levelCls(fd.fit_level)}`}>
                {fd.fit_level ?? "—"}
              </span>
              <span className="text-[9px] text-neutral-400 font-mono self-center">
                Quality: {fmtNum(fd.fit_quality, 2)}
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {([
                ["rmse", fmtSci(fd.residual_rmse)],
                ["mae", fmtSci(fd.residual_mae)],
                ["bias", fmtSci(fd.residual_bias)],
                ["nrmse", fmtNum(fd.normalized_rmse, 4)],
                ["l2", fmtSci(fd.residual_l2)],
              ] as [string, string][]).map(([label, val]) => (
                <div key={label}>
                  <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-1">{label}</p>
                  <p className="text-[10px] text-white font-mono">{val}</p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500">Observed vs modeled no disponible para esta corrida.</p>
        )}
      </div>

      {/* ── Residual Map ── */}
      <div className="border border-neutral-900 bg-neutral-950/70 rounded-lg p-3">
        <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">Residuales por sensor</p>
        {resMap.length > 0 ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <span className="text-[9px] text-neutral-400 font-mono">Total: {resMap.length}</span>
              <span className={`text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border ${residualLevelCls("LOW")}`}>LOW: {countByLevel("LOW")}</span>
              <span className={`text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border ${residualLevelCls("MEDIUM")}`}>MED: {countByLevel("MEDIUM")}</span>
              <span className={`text-[8px] uppercase tracking-widest px-2 py-0.5 rounded border ${residualLevelCls("HIGH")}`}>HIGH: {countByLevel("HIGH")}</span>
            </div>

            <div>
              <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-2">Mapa 2D de residuales</p>
              {hasMapPoints ? (
                <div className="space-y-2">
                  <div className="relative w-full h-[220px] bg-black/60 border border-neutral-800 rounded-lg overflow-hidden">
                    {xMin === xMax || zMin === zMax ? (
                      <div className="absolute inset-0 flex items-center justify-center text-[10px] text-neutral-500 font-mono bg-black/80 z-10">
                        Dominio espacial reducido.
                      </div>
                    ) : null}
                    {validMapPoints.map((p, i) => {
                      const left = toPercent(p.x_m!, xMin, xMax);
                      const top = 100 - toPercent(p.z_m!, zMin, zMax);
                      const isHigh = p.residual_level === "HIGH";
                      return (
                        <div
                          key={`pt-${i}`}
                          className={`absolute rounded-full ${getResidualDotClass(p.residual_level)} ${isHigh ? 'w-2 h-2 z-10' : 'w-1.5 h-1.5 opacity-80 z-0'}`}
                          style={{ left: `${left}%`, top: `${top}%`, transform: 'translate(-50%, -50%)' }}
                          title={`Idx: ${p.sensor_index}\nX: ${fmtNum(p.x_m, 1)}\nZ: ${fmtNum(p.z_m, 1)}\nRes: ${fmtSci(p.residual)}\nNivel: ${p.residual_level}`}
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between items-center px-1">
                    <p className="text-[8px] text-neutral-600 italic">Vista planta X/Z basada en sensores del residualMap.</p>
                    <div className="flex gap-2 text-[8px] uppercase tracking-widest text-neutral-500">
                      <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#C2D8C4]" /> LOW</span>
                      <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-yellow-500" /> MED</span>
                      <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-500" /> HIGH</span>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-[10px] text-neutral-500 font-mono">Mapa 2D no disponible para esta corrida.</p>
              )}
            </div>

            {topResiduals.length > 0 ? (
              <div className="overflow-x-auto">
                <p className="text-[8px] uppercase tracking-widest text-neutral-600 mb-2">Sensores con mayor residual</p>
                <table className="w-full text-left text-[9px] font-mono">
                  <thead className="text-neutral-600 uppercase">
                    <tr>
                      {["idx", "x_m", "y_m", "z_m", "observed", "modeled", "residual", "level"].map((h) => (
                        <th key={h} className="pb-2 pr-3 font-normal whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="text-neutral-300">
                    {topResiduals.map((p, i) => (
                      <tr key={i} className="border-t border-neutral-900">
                        <td className="py-1.5 pr-3">{p.sensor_index ?? "—"}</td>
                        <td className="py-1.5 pr-3">{fmtNum(p.x_m, 1)}</td>
                        <td className="py-1.5 pr-3">{fmtNum(p.y_m, 1)}</td>
                        <td className="py-1.5 pr-3">{fmtNum(p.z_m, 1)}</td>
                        <td className="py-1.5 pr-3">{fmtSci(p.observed)}</td>
                        <td className="py-1.5 pr-3">{fmtSci(p.modeled)}</td>
                        <td className="py-1.5 pr-3">{fmtSci(p.residual)}</td>
                        <td className="py-1.5 pr-3">
                          <span className={`px-1.5 py-0.5 rounded text-[8px] uppercase font-bold ${residualLevelCls(p.residual_level)}`}>
                            {p.residual_level ?? "—"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-[10px] text-neutral-500">Mapa de residuales no disponible.</p>
        )}
      </div>
    </div>
  );
}
