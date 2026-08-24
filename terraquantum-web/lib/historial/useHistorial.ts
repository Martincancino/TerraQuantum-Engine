"use client";

// ─── FASE 13 (auditoría 06 §10) — Los hooks que usan las vistas ───────────────
//
// Dos piezas y nada más: leer el resumen del historial de forma reactiva, y
// enganchar los atajos de teclado de un ámbito mientras la vista esté montada.

import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  resumen,
  resumenServidor,
  suscribir,
  type Ambito,
  type ResumenHistorial,
} from "./comandos";
import { elFocoTieneDeshacerPropio } from "../atajos/foco";
import { esDeshacer, esRehacer } from "../atajos/teclas";

/** Lee el estado del historial. Se re-renderiza sólo cuando cambia de verdad:
 *  `resumen()` cachea la instantánea y la invalida en cada mutación, que es lo
 *  que `useSyncExternalStore` exige para no entrar en bucle. */
export function useResumenHistorial(ambito: Ambito): ResumenHistorial {
  const leer = useCallback(() => resumen(ambito), [ambito]);
  return useSyncExternalStore(suscribir, leer, resumenServidor);
}

export interface OpcionesAtajos {
  deshacer: () => boolean;
  rehacer: () => boolean;
  /** Si es false, el listener no se registra. Lo usan las vistas para no dejar
   *  atajos vivos cuando su panel no está en pantalla. */
  activo?: boolean;
}

/**
 * Registra Ctrl+Z / Ctrl+Y mientras el componente esté montado.
 *
 * **El aislamiento de foco es la parte que importa.** Dentro de un campo de
 * texto no se hace nada: ahí manda el deshacer nativo del navegador, y ese es el
 * que el usuario espera cuando acaba de teclear. Fuera de un campo de texto ese
 * atajo no tiene comportamiento nativo, así que es nuestro y se consume con
 * `preventDefault` — pero sólo cuando de verdad se ha atendido.
 */
export function useAtajosDeHistorial({ deshacer, rehacer, activo = true }: OpcionesAtajos): void {
  useEffect(() => {
    if (!activo) return;
    const alPulsar = (e: KeyboardEvent) => {
      if (!esDeshacer(e) && !esRehacer(e)) return;
      // El deshacer del navegador dentro de un campo de texto gana siempre.
      if (elFocoTieneDeshacerPropio(e)) return;
      const atendido = esDeshacer(e) ? deshacer() : rehacer();
      // `preventDefault` SÓLO si se hizo algo. Si el historial estaba vacío o
      // bloqueado por una corrida en curso, el evento sigue su camino en vez de
      // desaparecer en silencio — que es el defecto que esta fase repara en el
      // manejador de flechas de `Scene3D`.
      if (atendido) e.preventDefault();
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [deshacer, rehacer, activo]);
}
