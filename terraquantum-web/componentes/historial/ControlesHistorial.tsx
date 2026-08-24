"use client";

import { useResumenHistorial } from "../../lib/historial/useHistorial";
import type { Ambito } from "../../lib/historial/comandos";
import { nombreDeAtajo } from "../../lib/atajos/teclas";

// Iconos en línea, como el resto del frontend (`MapRoomPanel`, `MviDirectionPanel`,
// `GravityCorrectionWizard`…). MEDIDO al escribir esto: `lucide-react` está
// declarada en `package.json` y **no la importa ni un fichero** del árbol — no
// se estrena aquí una dependencia que nadie usa sólo por dos flechas.
function FlechaDeshacer() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h11a5 5 0 0 1 0 10h-1" />
    </svg>
  );
}

function FlechaRehacer() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m15 14 5-5-5-5" />
      <path d="M20 9H9a5 5 0 0 0 0 10h1" />
    </svg>
  );
}

/**
 * FASE 13 — Los dos botones de deshacer/rehacer, y el motivo cuando no se puede.
 *
 * La plantilla de gate del proyecto (desde la Fase 9) exige que cada fase
 * entregue algo que **un usuario pueda ver y hacer desde la interfaz**, y la
 * auditoría dedica su hallazgo estructural (§1.2) a que la pieza exista no es lo
 * mismo que el camino esté conectado. Un historial sin botones sería un atajo de
 * teclado que sólo conoce quien leyó el código: por eso los comandos también se
 * ven, se etiquetan con el nombre del último cambio y **dicen por qué están
 * apagados** en vez de limitarse a estarlo.
 *
 * No calcula nada: lee el resumen del historial y despacha. Toda la decisión
 * (qué es deshacible, si hay una corrida en curso) vive en `store/deshacible.ts`
 * y `store/historialVisor.ts`.
 */
export interface PropsControlesHistorial {
  ambito: Ambito;
  deshacer: () => boolean;
  rehacer: () => boolean;
  /** Motivo por el que el historial está bloqueado ahora mismo, o null. Se
   *  muestra al usuario: «no se puede» sin explicación es el defecto que esta
   *  fase persigue, no una variante aceptable. */
  bloqueadoPorque?: string | null;
  compacto?: boolean;
}

export default function ControlesHistorial({
  ambito,
  deshacer,
  rehacer,
  bloqueadoPorque = null,
  compacto = false,
}: PropsControlesHistorial) {
  const { puedeDeshacer, puedeRehacer, etiquetaDeshacer, etiquetaRehacer, tamano } =
    useResumenHistorial(ambito);

  const bloqueado = Boolean(bloqueadoPorque);
  const deshacerActivo = puedeDeshacer && !bloqueado;
  const rehacerActivo = puedeRehacer && !bloqueado;

  const clase = (activo: boolean) =>
    `flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-[9px] font-mono uppercase tracking-wider border transition-colors ${
      activo
        ? "border-white/15 bg-white/[0.04] text-white/70 hover:text-accent hover:border-accent/50 cursor-pointer"
        : "border-white/5 bg-white/[0.01] text-white/25 cursor-not-allowed"
    }`;

  return (
    <div
      className="flex flex-col gap-1.5"
      data-testid={`historial-${ambito}`}
      data-tamano={tamano}
      data-puede-deshacer={puedeDeshacer ? "si" : "no"}
      data-puede-rehacer={puedeRehacer ? "si" : "no"}
      data-bloqueado={bloqueado ? "si" : "no"}
    >
      <div className="grid grid-cols-2 gap-1.5">
        <button
          type="button"
          data-testid={`deshacer-${ambito}`}
          disabled={!deshacerActivo}
          onClick={() => deshacer()}
          title={
            bloqueadoPorque ??
            (etiquetaDeshacer
              ? `Deshacer: ${etiquetaDeshacer} (${nombreDeAtajo("deshacer")})`
              : `Nada que deshacer (${nombreDeAtajo("deshacer")})`)
          }
          className={clase(deshacerActivo)}
        >
          <FlechaDeshacer />
          Deshacer
        </button>
        <button
          type="button"
          data-testid={`rehacer-${ambito}`}
          disabled={!rehacerActivo}
          onClick={() => rehacer()}
          title={
            bloqueadoPorque ??
            (etiquetaRehacer
              ? `Rehacer: ${etiquetaRehacer} (${nombreDeAtajo("rehacer")})`
              : `Nada que rehacer (${nombreDeAtajo("rehacer")})`)
          }
          className={clase(rehacerActivo)}
        >
          <FlechaRehacer />
          Rehacer
        </button>
      </div>

      {!compacto && (
        <p
          className="text-[8px] font-mono leading-relaxed text-white/40"
          data-testid={`historial-detalle-${ambito}`}
        >
          {bloqueadoPorque ? (
            <span className="text-amber-400/80">{bloqueadoPorque}</span>
          ) : etiquetaDeshacer ? (
            <>
              Último cambio: <span className="text-white/65">{etiquetaDeshacer}</span>
              {" · "}
              {tamano} en el historial
            </>
          ) : (
            <>Sin cambios que deshacer en esta corrida.</>
          )}
        </p>
      )}
    </div>
  );
}
