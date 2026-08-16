"use client";

// ─── FASE 9 — El funcional declarado, y la convergencia, en pantalla ──────────
//
// La Fase 7 hizo que cada corrida publique QUÉ funcional de regularización usó
// (`regularization_functional`), con `depth_weighting_active`, `effect_mechanism`,
// `solver_converged` y el motivo escrito en español. Hasta ahora eso llegaba sólo
// al JSON. Dos cosas que sin esto el usuario no puede saber:
//
//  · **Comparar dos corridas.** La misma configuración nominal aplica un depth
//    weighting o ninguno según haya padding: H-33. Ahora la corrida lo dice.
//  · **Si el resultado convergió.** La Fase 7 midió que el LSQR magnético termina
//    por límite de iteraciones (`istop=7`, 500/500) y que eso hace que un
//    parámetro inerte sobre el papel mueva el resultado hasta un 86 %. Un
//    resultado que no convergió y no lo dice es el mismo patrón que H-27.
//
// Regla de Oro: aquí no se calcula ni se interpreta nada. `explanation_es` la
// escribe el backend (`exploration/potential_field_core.py::declare_functional`)
// y se muestra literal. Si el campo no viene, se dice que no viene.

import { asRec, boolOf, fmtNum, numOf, strOf, EmptyState, StatCard } from "./analyticsShared";

/** Dónde vive la declaración según el motor:
 *  · gravimetría → `report.regularization_functional` (raíz)
 *  · magnetometría → `report.solver.regularization_functional`
 *  No se normaliza en el backend, así que se buscan las dos. */
export function readRegularizationFunctional(
  report: Record<string, unknown> | null,
): Record<string, unknown> | null {
  return (
    asRec(report?.regularization_functional) ??
    asRec(asRec(report?.solver)?.regularization_functional)
  );
}

/** `true` = convergió · `false` = NO convergió · `null` = no aplica/no medido.
 *  Los tres estados son distintos y colapsarlos sería la mentira: una corrida por
 *  la ruta acotada (TRF) no usa LSQR y publica `null`, que no es un fallo. */
export function solverConverged(
  report: Record<string, unknown> | null,
): boolean | null {
  const decl = readRegularizationFunctional(report);
  const v = decl?.solver_converged;
  return typeof v === "boolean" ? v : null;
}

const MECANISMO_ES: Record<string, string> = {
  functional: "el peso entra en el funcional",
  early_stopping: "sólo por parada temprana del solver",
  none: "no actúa",
};

/** Qué solver corrió de verdad y con qué λ.
 *
 *  FASE 9, auditoría retroactiva del gate de la **Fase 5**: aquella fase midió
 *  que `bounded_solver_active` publicaba lo que se HABÍA PEDIDO y que con más de
 *  8.000 celdas —el régimen normal— el solver usaba LSQR igualmente (H-37 otra
 *  vez). Lo arregló en el backend… y los 6 campos resultantes (`solver_path`,
 *  `bounded_solver_requested`, `bounded_solver_active`, `projected_solver_used`,
 *  `lambda_used`, `lambda_effective`) aparecían en **cero** archivos del
 *  frontend. Es el mismo H-10: capacidad honesta en el backend, camino del
 *  usuario detenido ahí. Se cierra aquí, que es donde se compara una corrida
 *  con otra. */
function SolverRealmenteUsado({ report }: { report: Record<string, unknown> | null }) {
  const solverPath = strOf(report, "solver_path");
  const pedido = report?.bounded_solver_requested;
  const activo = report?.bounded_solver_active;
  const proyectado = report?.projected_solver_used;
  const lam = numOf(report, "lambda_used");
  const lamEff = numOf(report, "lambda_effective");

  if (solverPath === null && lam === null) return null;

  // Que se pida un solver acotado no significa que se use: decirlo es el punto.
  const divergencia = pedido === true && activo === false;

  return (
    <div className="space-y-1.5 border-t border-white/[0.06] pt-2">
      <p className="text-[7px] uppercase tracking-[0.18em] text-white/35">
        Solver realmente usado
      </p>
      <div className="grid grid-cols-2 gap-1.5">
        <StatCard label="Ruta" value={solverPath ?? "—"} />
        <StatCard
          label="Acotado"
          value={activo === true ? "sí" : activo === false ? "no" : "—"}
          tone={divergencia ? "warn" : "neutral"}
          hint={divergencia ? "se pidió, pero no se usó" : undefined}
        />
        <StatCard label="λ usada" value={lam !== null ? fmtNum(lam, 5) : "—"} />
        <StatCard
          label="λ efectiva"
          value={lamEff !== null ? fmtNum(lamEff, 5) : "—"}
          hint={
            lam !== null && lamEff !== null && Math.abs(lamEff - lam) > 1e-12
              ? "reescalada por el solver"
              : undefined
          }
        />
      </div>
      {proyectado === true && (
        <p className="text-[7.5px] text-white/40">Con solver proyectado (bounds KKT).</p>
      )}
    </div>
  );
}

export default function RegularizationFunctionalWidget({
  report,
}: {
  report: Record<string, unknown> | null;
}) {
  const decl = readRegularizationFunctional(report);

  if (!decl) {
    return (
      <div className="space-y-2.5" data-testid="regularization-functional">
        <EmptyState>
          Esta corrida no declara su funcional de regularización. Lo publican las
          corridas hechas a partir de la Fase 7; las anteriores no lo guardaron.
        </EmptyState>
        <SolverRealmenteUsado report={report} />
      </div>
    );
  }

  const convergio = typeof decl.solver_converged === "boolean" ? decl.solver_converged : null;
  const istop = numOf(decl, "lsqr_istop");
  const iters = numOf(decl, "lsqr_iters");
  const kind = strOf(decl, "model_weight_kind");
  const mecanismo = strOf(decl, "effect_mechanism");
  const beta = numOf(decl, "depth_beta_declared");
  const betaEq = numOf(decl, "effective_beta_equivalente");
  const desv = numOf(decl, "effective_desviacion_max_pct");
  const explicacion = strOf(decl, "explanation_es");
  const depthActivo = boolOf(decl, "depth_weighting_active");
  const betaTieneEfecto = boolOf(decl, "depth_beta_has_effect");

  return (
    <div className="space-y-2.5" data-testid="regularization-functional">
      {/* ── Convergencia: lo primero, porque condiciona todo lo demás ──────── */}
      {convergio === false && (
        <div
          data-testid="solver-not-converged"
          className="rounded-lg border border-yellow-500/40 bg-yellow-500/[0.07] px-3 py-2.5"
        >
          <p className="text-[9px] uppercase tracking-[0.18em] text-yellow-400 font-bold">
            El solver no convergió
          </p>
          <p className="text-[9px] text-white/65 mt-1.5 leading-relaxed">
            Terminó por criterio de parada{" "}
            <span className="font-mono text-white/85">istop={istop ?? "—"}</span>
            {iters !== null && (
              <>
                {" "}tras <span className="font-mono text-white/85">{fmtNum(iters, 0)}</span>{" "}
                iteraciones
              </>
            )}
            {istop === 7 && " (se agotó el límite de iteraciones)"}
            {istop === 3 && " (número de condición demasiado alto)"}. El modelo que
            ves es donde el solver se detuvo, no la solución del problema
            planteado.
          </p>
        </div>
      )}

      {convergio === true && (
        <div className="rounded-lg border border-[#C2D8C4]/25 bg-[#C2D8C4]/[0.05] px-3 py-2">
          <p className="text-[9px] uppercase tracking-[0.18em] text-[#C2D8C4] font-bold">
            Solver convergido
          </p>
          <p className="text-[8.5px] text-white/50 mt-1 font-mono">
            istop={istop ?? "—"}
            {iters !== null ? ` · ${fmtNum(iters, 0)} iteraciones` : ""}
          </p>
        </div>
      )}

      {convergio === null && (
        <p className="text-[9px] text-white/40 leading-relaxed italic">
          Convergencia no aplicable a esta corrida: no pasó por LSQR (la ruta
          acotada no publica <span className="font-mono">istop</span>).
        </p>
      )}

      {/* ── Qué funcional usó ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-1.5">
        <StatCard
          label="Peso de modelo"
          value={kind === "depth" ? "Profundidad" : kind === "sensitivity" ? "Sensibilidad" : "—"}
        />
        <StatCard
          label="Depth weighting"
          value={depthActivo ? "activo" : "inerte"}
          tone={depthActivo ? "good" : "neutral"}
        />
        <StatCard
          label="β declarado"
          value={beta !== null ? fmtNum(beta, 2) : "—"}
          hint={
            beta !== null && !betaTieneEfecto ? "no cambia este resultado" : undefined
          }
        />
        <StatCard
          label="Mecanismo"
          value={mecanismo ? (MECANISMO_ES[mecanismo] ?? mecanismo) : "—"}
          tone={mecanismo === "early_stopping" ? "warn" : "neutral"}
        />
      </div>

      {betaEq !== null && (
        <div className="grid grid-cols-2 gap-1.5">
          <StatCard label="β equivalente" value={fmtNum(betaEq, 2)} hint="Li & Oldenburg de ESTA malla" />
          <StatCard
            label="Desviación del ajuste"
            value={fmtNum(desv, 1)}
            unit="%"
            // Es el número que dice si el β equivalente significa algo: con una
            // desviación enorme, la ley de potencia no describe el peso real.
            tone={desv !== null && desv > 100 ? "warn" : "neutral"}
            hint={desv !== null && desv > 100 ? "la ley de potencia ajusta mal" : undefined}
          />
        </div>
      )}

      {/* ── Qué solver corrió (auditoría retroactiva del gate de la Fase 5) ── */}
      <SolverRealmenteUsado report={report} />

      {/* ── El motivo, escrito por el backend ──────────────────────────────── */}
      {explicacion && (
        <p className="text-[8.5px] text-white/50 leading-relaxed border-t border-white/[0.06] pt-2">
          {explicacion}
        </p>
      )}
    </div>
  );
}
