"use client";

// ─── FASE 13 — Rehidratar y guardar las preferencias, sin romper la hidratación ─
//
// La regla de Next con el App Router: `localStorage` NO existe en el render del
// servidor, así que leerlo durante el render daría un HTML de servidor distinto
// del primer render de cliente y React avisaría de un desajuste de hidratación.
// Se lee dentro de un efecto, que corre sólo en el cliente y sólo DESPUÉS del
// primer pintado — el mismo patrón que ya usa `IAChatView` con la clave del
// copiloto, que es el único precedente del repositorio.
//
// La consecuencia visible es que hay un fotograma con los valores por defecto
// antes de aplicar los guardados. Es aceptable para preferencias de
// visualización y es el precio de no mentirle al hidratador.

import { useEffect, useRef } from "react";
import { useAppStore } from "../../store/useAppStore";
import { aplicarSinRegistrar } from "../../store/historialVisor";
import {
  escribirPreferencias,
  huellaDePreferencias,
  leerPreferencias,
  PREFERENCIAS_PERSISTIDAS,
  type ClavePersistida,
} from "./preferenciasVisuales";

const CLAVES = Object.keys(PREFERENCIAS_PERSISTIDAS) as ClavePersistida[];

/** Retardo de escritura. Un arrastre de slider dispara decenas de cambios; sin
 *  esto se escribiría en disco en cada uno. */
const RETARDO_GUARDADO_MS = 400;

/**
 * Monta la persistencia de preferencias. Debe montarse UNA sola vez, en la raíz.
 */
export function usePreferenciasVisuales(): void {
  const rehidratado = useRef(false);

  // 1. Rehidratar, una vez, después del primer pintado.
  useEffect(() => {
    if (rehidratado.current) return;
    rehidratado.current = true;
    const guardadas = leerPreferencias();
    if (Object.keys(guardadas).length === 0) return;
    // `aplicarSinRegistrar`: restaurar la sesión anterior NO es una acción del
    // usuario en ésta. Si entrara al historial, el primer Ctrl+Z de la sesión
    // desharía «lo que había cuando abrí la app», que no significa nada.
    aplicarSinRegistrar(guardadas);
  }, []);

  // 2. Guardar cuando cambien, con retardo.
  useEffect(() => {
    let temporizador: ReturnType<typeof setTimeout> | null = null;
    let ultima = huellaDePreferencias(useAppStore.getState());

    const desuscribir = useAppStore.subscribe((estado) => {
      const huella = huellaDePreferencias(estado);
      if (huella === ultima) return;
      ultima = huella;
      if (temporizador) clearTimeout(temporizador);
      temporizador = setTimeout(() => {
        escribirPreferencias(useAppStore.getState());
      }, RETARDO_GUARDADO_MS);
    });

    return () => {
      if (temporizador) clearTimeout(temporizador);
      desuscribir();
    };
  }, []);
}

/** Las claves vigiladas, expuestas para los tests. */
export const CLAVES_PERSISTIDAS = CLAVES;
