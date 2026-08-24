"use client";

/**
 * FASE 14 — Qué hizo (y qué NO hizo) el prior geológico implícito.
 *
 * SOLO renderiza `report.implicit_geology` tal como lo emite el backend
 * (`services/geophysics_service._build_implicit_geology_reference`). No calcula
 * φ, ni fracciones, ni veredictos.
 *
 * Existe porque la fase midió que este prior puede afirmar geología donde no hay
 * dato, y que puede ser exactamente inerte, y las dos cosas pasaban en silencio:
 *
 *  · `degenerate_planar_field` — con contactos a una sola profundidad el HRBF
 *    degenera a su deriva polinómica: «la superficie» es un plano extrapolado a
 *    toda la malla. Medido: 1 sondaje ⇒ φ ≥ 0 en el 85 % de las celdas.
 *  · `inert_no_contrast` — si el prior clasifica todo como una sola unidad, el
 *    m_ref es constante y el término de suavidad lo anula EXACTO (L·1 = 0): la
 *    inversión sale igual que sin prior aunque el panel diga «activado».
 *  · `target_volume_fraction` / `extrapolation_max_m` — cuánto volumen se está
 *    declarando objetivo y a qué distancia del sondaje más cercano.
 */

import { asRec, numOf, strOf, boolOf, StatCard, EmptyState, type Tone } from "./analyticsShared";

export default function ImplicitGeologyWidget({
  report,
}: {
  report: Record<string, unknown> | null;
}) {
  const g = asRec(report?.implicit_geology);
  if (!g) {
    return (
      <EmptyState>
        Esta corrida no usó prior geológico implícito. Se activa en Preparación →
        Avanzado → «Geología implícita», y necesita sondajes con litología.
      </EmptyState>
    );
  }

  const inerte = boolOf(g, "inert_no_contrast") === true;
  const plano = boolOf(g, "degenerate_planar_field") === true;
  const fraccion = numOf(g, "target_volume_fraction");
  const extrapolacion = numOf(g, "extrapolation_max_m");
  const nPozos = numOf(g, "n_boreholes");
  const nContactos = numOf(g, "n_contact_points");
  const nOrientaciones = numOf(g, "n_orientations");
  const celdasObjetivo = numOf(g, "n_target_cells");
  const celdasTotal = numOf(g, "n_total_cells");
  const termino = strOf(g, "binding_term");
  const peso = numOf(g, "prior_weight");
  const litologias = Array.isArray(g.target_lithologies)
    ? (g.target_lithologies as unknown[]).map((x) => String(x))
    : [];
  const avisos = Array.isArray(g.warnings)
    ? (g.warnings as unknown[]).map((x) => String(x))
    : [];

  // El tono lo decide el dato del backend, no una heurística nueva del frontend.
  const tonoCobertura: Tone =
    fraccion === null ? "neutral" : fraccion >= 0.5 ? "bad" : fraccion >= 0.25 ? "warn" : "good";

  return (
    <div className="space-y-3">
      {inerte && (
        <p className="text-[9px] text-red-300 border border-red-500/40 rounded px-2.5 py-2 leading-relaxed">
          <strong>El prior no actuó.</strong> Clasificó toda la malla como una sola
          unidad, así que el modelo de referencia es constante y el término de
          suavidad lo anula exactamente. Esta inversión es la misma que sin prior.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatCard
          label="Unidad objetivo"
          value={litologias.length ? litologias.join(" + ") : "—"}
          hint={`${nContactos ?? 0} contacto(s) en ${nPozos ?? 0} sondaje(s)`}
        />
        <StatCard
          label="Volumen declarado"
          value={fraccion === null ? "—" : `${(fraccion * 100).toFixed(1)}`}
          unit="%"
          tone={tonoCobertura}
          hint={
            celdasObjetivo !== null && celdasTotal !== null
              ? `${celdasObjetivo} de ${celdasTotal} celdas`
              : undefined
          }
        />
        <StatCard
          label="Extrapolación máx."
          value={extrapolacion === null ? "—" : extrapolacion.toFixed(0)}
          unit="m"
          tone={plano ? "warn" : "neutral"}
          hint="distancia horizontal al sondaje más cercano"
        />
        <StatCard
          label="Campo implícito"
          value={plano ? "PLANO" : "interpolado"}
          tone={plano ? "warn" : "good"}
          hint={
            nOrientaciones
              ? `${nOrientaciones} orientación(es) estructural(es)`
              : "sin medidas estructurales"
          }
        />
      </div>

      {/* En QUÉ término del funcional entró. No es un detalle de implementación:
          está medido que la diferencia entre los dos cambia el resultado. */}
      {termino ? (
        <p className="text-[8px] text-white/40 leading-relaxed">
          Entró por el término{" "}
          <strong>{termino === "smallness" ? "de smallness" : "de suavidad"}</strong>
          {termino === "smallness" && peso !== null ? ` (α = ${peso})` : ""} —{" "}
          {termino === "smallness"
            ? "α‖m − m_ref‖² además de la suavidad, que es donde la medición dice que el contacto ayuda."
            : "sólo ‖L·(m − m_ref)‖², el comportamiento histórico: actúa en la curvatura del contacto y NO en la magnitud."}
        </p>
      ) : null}

      {avisos.map((aviso, i) => (
        <p
          key={i}
          className="text-[9px] text-yellow-300/90 border border-yellow-500/30 rounded px-2.5 py-2 leading-relaxed"
        >
          {aviso}
        </p>
      ))}

      {/* Lo que la fase MIDIÓ, dicho donde el usuario decide, no en un README —
          incluido el límite de esa medición, que es la mitad que importa. */}
      <p className="text-[8px] text-white/35 leading-relaxed">
        El prior entra como <strong>restricción geométrica</strong>: lo que transporta
        información es <em>dónde</em> está el contacto, no cuánto contrasta. Sobre
        verdad conocida (dique inclinado, 25 realizaciones de ruido pareadas) mejoró
        la recuperación en <strong>25 de 25</strong>, y equivocar la densidad al doble
        o a la mitad seguía mejorándola; con una geología <em>falsa</em> el resultado
        empeora en 25 de 25, que es como se comprobó que mide geología y no «tener un
        prior». <strong>Medido en un solo escenario</strong> —un cuerpo tabular
        inclinado, con sondajes que lo cortan—: no está medido en cuerpos compactos,
        con geología a medias equivocada, ni en magnetometría. Trátalo como una
        hipótesis geológica que se contrasta. Ver{" "}
        <code>scripts/validation/f14_implicit_geology_experiment.py</code>.
      </p>
    </div>
  );
}
