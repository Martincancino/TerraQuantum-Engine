"use client";

/**
 * Reporte honesto (trilogía backend B1+B3+B2) — SOLO renderiza campos del report_payload.
 * NO calcula física ni veredictos: consume report.overall_verdict, report.best_target y
 * report.depthResolution tal cual los emite el backend (geophysics_service).
 *
 *  • OverallVerdictWidget  — el veredicto ÚNICO reconciliado (B3): corona los badges que
 *    antes se contradecían (GOOD/HIGH junto a UNCLASSIFIED/REMEDIATION).
 *  • BestTargetWidget      — el blanco RESOLUBLE (B1) + el artefacto de piso descartado
 *    (floor_saturated_demoted), con la confianza ya capada por B3.
 *  • DepthResolutionWidget — historia POR-EJE (B2): footprint horizontal DETERMINADO vs
 *    profundidad = cola null-space (deep_mass_fraction). Mata el "±2 km" engañoso.
 */
import { asRec, numOf, strOf, boolOf, fmtNum, StatCard, EmptyState, type Tone } from "./analyticsShared";

// ── Mapas de etiqueta/tono (display) ──────────────────────────────────────────
function levelTone(level: string | null): Tone {
  const v = String(level || "").toUpperCase();
  if (v === "HIGH") return "good";
  if (v === "MEDIUM") return "warn";
  if (v === "LOW") return "bad";
  return "neutral";
}

function levelLabel(level: string | null): string {
  const v = String(level || "").toUpperCase();
  if (v === "HIGH") return "ALTA";
  if (v === "MEDIUM") return "MEDIA";
  if (v === "LOW") return "BAJA";
  return "—";
}

const LIMITING_LABELS: Record<string, string> = {
  survey_confidence: "Confianza del survey",
  model_reliability: "Confiabilidad del modelo",
  priority_class: "Prioridad de targeting",
  r06_padding_physical: "Padding/regional (físico)",
  best_target_null_space: "Blanco null-space",
};

function limitingLabel(code: string): string {
  return LIMITING_LABELS[code] || code;
}

// ══════════════════════════════════════════════════════════════════════════════
//  B3 — Veredicto único reconciliado
// ══════════════════════════════════════════════════════════════════════════════
export function OverallVerdictWidget({ report }: { report: Record<string, unknown> | null }) {
  const v = asRec(report?.overall_verdict);
  if (!v) {
    return <EmptyState>Veredicto reconciliado no disponible para esta corrida.</EmptyState>;
  }

  const level = strOf(v, "level");
  const headline = strOf(v, "headline");
  const action = strOf(v, "recommended_action");
  const limiting = Array.isArray(v.limiting_factors)
    ? (v.limiting_factors as unknown[]).map((x) => String(x))
    : [];
  const comp = asRec(v.components);

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-1.5">
        <StatCard label="Veredicto único" value={levelLabel(level)} tone={levelTone(level)} />
        <StatCard
          label="Factor limitante"
          value={limiting.length ? limiting.map(limitingLabel).join(" · ") : "—"}
          tone={limiting.length ? levelTone(level) : "neutral"}
        />
      </div>

      {headline && (
        <p className="text-[10px] text-white/80 leading-snug">{headline}</p>
      )}
      {action && (
        <p className="text-[9px] text-white/55 leading-snug">
          <span className="text-white/40 uppercase tracking-[0.15em] text-[7px]">Acción · </span>
          {action}
        </p>
      )}

      {/* Componentes reconciliados (transparencia: el eslabón más débil manda). */}
      {comp && (
        <div className="rounded-md border border-white/10 bg-white/[0.02] px-2.5 py-2 space-y-1">
          <p className="text-[7px] uppercase tracking-[0.18em] text-white/40">
            Señales reconciliadas (eslabón más débil)
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <CompRow label="Confianza survey" value={strOf(comp, "survey_confidence")} />
            <CompRow label="Confiabilidad" value={strOf(comp, "model_reliability")} />
            <CompRow label="Prioridad" value={strOf(comp, "priority_class")} />
            <CompRow label="Gate padding (r06)" value={strOf(comp, "r06_padding_gate")} />
          </div>
          {numOf(comp, "r06_physical_severity") !== null && (
            <p className="text-[7px] text-white/35 leading-tight">
              Severidad física padding: {fmtNum(numOf(comp, "r06_physical_severity"), 3)}{" "}
              {Number(comp.r06_physical_severity) < 0.01
                ? "(gate REMEDIATION físicamente irrelevante → ignorado)"
                : ""}
            </p>
          )}
        </div>
      )}

      <p className="text-[8px] text-white/40 leading-tight">
        Un solo veredicto = el más conservador entre confianza, confiabilidad, prioridad,
        gate físico de padding/regional y validez del blanco. Reemplaza badges que antes
        se contradecían.
      </p>
    </div>
  );
}

function CompRow({ label, value }: { label: string; value: string | null }) {
  return (
    <p className="text-[8px] font-mono text-white/60 leading-tight">
      <span className="text-white/35">{label}: </span>
      {value || "—"}
    </p>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  B1 — Blanco resoluble + artefacto de piso descartado
// ══════════════════════════════════════════════════════════════════════════════
export function BestTargetWidget({ report }: { report: Record<string, unknown> | null }) {
  const bt = asRec(report?.best_target);
  if (!bt) {
    return <EmptyState>Sin blanco recuperado para esta corrida.</EmptyState>;
  }

  const isArtifact = boolOf(bt, "is_null_space_artifact");
  const resolvable = bt.is_resolvable_depth === true;
  const conf = strOf(bt, "confidence_level");
  const depth = numOf(bt, "depth_m", "y_m");
  const demoted = asRec(bt.floor_saturated_demoted);
  const nFloor = numOf(bt, "n_floor_saturated_cells");
  const note = strOf(bt, "selection_note");

  return (
    <div className="space-y-2.5">
      {isArtifact && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-2.5 py-1.5">
          <p className="text-[8px] font-mono text-red-400 leading-tight">
            ⚠ El blanco mostrado satura el piso de malla (null-space) — NO fiable.
          </p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-1.5">
        <StatCard
          label="Profundidad blanco"
          value={fmtNum(depth, 0)}
          unit="m"
          tone={resolvable ? "good" : "warn"}
          hint={resolvable ? "profundidad resoluble" : "bajo el horizonte resoluble"}
        />
        <StatCard label="Densidad" value={fmtNum(numOf(bt, "density"), 2)} unit="t/m³" />
        <StatCard
          label="Confianza"
          value={String(conf || "—").toUpperCase()}
          tone={levelTone(conf)}
          hint="capada por el veredicto único"
        />
      </div>

      <p className="text-[8px] font-mono text-white/55 leading-tight">
        X {fmtNum(numOf(bt, "x_m"), 1)} · Y {fmtNum(numOf(bt, "y_m"), 1)} · Z{" "}
        {fmtNum(numOf(bt, "z_m"), 1)} m
        {numOf(bt, "anomaly_magnitude") !== null && (
          <> · |anomalía| {fmtNum(numOf(bt, "anomaly_magnitude"), 2)}</>
        )}
      </p>

      {/* Transparencia B1: el artefacto bound-saturado del piso, descartado a propósito. */}
      {demoted && (
        <div className="rounded-md border border-white/10 bg-white/[0.02] px-2.5 py-2 space-y-1">
          <p className="text-[7px] uppercase tracking-[0.18em] text-white/40">
            Artefacto descartado (transparencia)
            {nFloor !== null ? ` · ${fmtNum(nFloor, 0)} celdas de piso` : ""}
          </p>
          <p className="text-[8px] font-mono text-white/55 leading-tight">
            ρ {fmtNum(numOf(demoted, "density"), 2)} t/m³ a {fmtNum(numOf(demoted, "depth_m", "y_m"), 0)} m
            (piso de malla) — masa null-space, no es blanco de perforación.
          </p>
        </div>
      )}

      {note && <p className="text-[8px] text-white/40 leading-tight">{note}</p>}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  B2 — Resolución por-eje (footprint horizontal vs cola null-space en profundidad)
// ══════════════════════════════════════════════════════════════════════════════
function verticalTone(quality: string | null): Tone {
  const v = String(quality || "").toLowerCase();
  if (v === "resolved") return "good";
  if (v === "poor") return "warn";
  if (v === "null_space_dominated") return "bad";
  return "neutral";
}

function verticalLabel(quality: string | null): string {
  const v = String(quality || "").toLowerCase();
  if (v === "resolved") return "Resuelta";
  if (v === "poor") return "Parcial";
  if (v === "null_space_dominated") return "No resuelta (null-space)";
  return "—";
}

const COMPACTNESS_LABELS: Record<string, string> = {
  compact: "Compacto",
  broad: "Ancho",
  diffuse: "Difuso",
  unknown: "—",
};

export function DepthResolutionWidget({ report }: { report: Record<string, unknown> | null }) {
  const dr = asRec(report?.depthResolution);
  if (!dr || dr.computed !== true) {
    return (
      <EmptyState>
        Resolución por-eje no disponible (campo recuperado vacío o sin sensibilidad).
      </EmptyState>
    );
  }

  const per = asRec(dr.per_axis);
  const horiz = asRec(per?.horizontal);
  const vert = asRec(per?.vertical);

  const compactness = strOf(horiz, "compactness") || "unknown";
  const determined = horiz?.determined === true;
  const extent = numOf(horiz, "extent_m");
  const vQuality = strOf(vert, "quality");
  const deepFrac = numOf(vert, "deep_mass_fraction") ?? numOf(dr, "deep_mass_fraction");
  const statement = strOf(dr, "statement");
  const horizonMethod = strOf(dr, "resolvable_depth_horizon_method");

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-1.5">
        {/* Horizontal = FORTALEZA (lo que gravedad SÍ resuelve). compactness ≠ calidad. */}
        <StatCard
          label="Footprint horizontal"
          value={determined ? "Determinado" : "—"}
          tone={determined ? "good" : "neutral"}
          hint={
            extent !== null
              ? `${COMPACTNESS_LABELS[compactness] || compactness} · ~${fmtNum(extent, 0)} m`
              : COMPACTNESS_LABELS[compactness] || compactness
          }
        />
        {/* Vertical = el límite honesto (cola null-space). */}
        <StatCard
          label="Profundidad"
          value={verticalLabel(vQuality)}
          tone={verticalTone(vQuality)}
          hint={deepFrac !== null ? `${(deepFrac * 100).toFixed(0)}% masa en cola null-space` : undefined}
        />
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <StatCard
          label="Horizonte resoluble"
          value={fmtNum(numOf(dr, "resolvable_depth_max_m"), 0)}
          unit="m"
          hint={horizonMethod === "sensitivity_doi_half_max_layer" ? "DOI sensibilidad" : "cutoff geom."}
        />
        <StatCard
          label="Cuerpo resoluble"
          value={fmtNum(numOf(dr, "resolvable_body_depth_m"), 0)}
          unit="m"
          tone={numOf(dr, "resolvable_body_depth_m") !== null ? "good" : "neutral"}
        />
      </div>

      {statement && (
        <p className="text-[9px] text-white/70 leading-snug">{statement}</p>
      )}

      <p className="text-[8px] text-white/40 leading-tight">
        La gravimetría resuelve DÓNDE en planta (footprint), no a qué profundidad. El ancho
        del cuerpo es geología, no una falla de resolución.
      </p>
    </div>
  );
}
