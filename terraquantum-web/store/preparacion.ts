// ─── FASE 24 — El acceso al estado de preparación, estable y sin hooks ────────
//
// Los reducers de la Fase 10 no cambian de dueño de golpe: `PrepPanel` y
// `PrepEnrichPanel` siguen despachando acciones con nombre, pero el estado que
// esas acciones transforman vive ahora en el store. El puente entre las dos
// cosas es este fichero, y su única exigencia es que sea **estable**:
//
//   · `leer()` lee el valor FRESCO en el momento del despacho, no el del
//     render. Es obligatorio, no una precaución: `resetOnFileChange` y el
//     `onChange` de los bounds de densidad despachan DOS acciones seguidas a la
//     MISMA máquina, y con el valor capturado en el render la segunda pisaría a
//     la primera. Un `useReducer` no tenía este problema porque React encola;
//     un store hay que leerlo cada vez.
//   · `escribir()` es una función de módulo, no un `useCallback`. Así sigue
//     siendo válida DESPUÉS de desmontar el panel — que es lo que hace que el
//     `finally { GENERACION_TERMINADA }` de una petición en vuelo aterrice
//     aunque el usuario ya se haya ido a otra pestaña.
//
// `escribir` pasa por `useAppStore.setState`, que el middleware `conHistorial`
// sustituye (`historialVisor.ts`): ninguna escritura se salta el historial del
// visor. Como las claves de preparación NO están en `ORDEN_VIGILADO`, el delta
// del visor sale vacío y no se registra nada — su historial es el de
// `preparacion`, no el del visor.

import { useAppStore } from "./useAppStore";
import type { AppState } from "./useAppStore";

/** Lectura fresca + escritura, ambas estables entre renders y tras desmontar. */
export interface AccesoExterno<E> {
  leer: () => E;
  escribir: (siguiente: E) => void;
}

function acceso<K extends keyof AppState>(
  clave: K,
): AccesoExterno<AppState[K]> {
  return {
    leer: () => useAppStore.getState()[clave],
    escribir: (siguiente) =>
      useAppStore.setState({ [clave]: siguiente } as unknown as Partial<AppState>),
  };
}

export const ACCESO_CONTEXTO = acceso("prepContexto");
export const ACCESO_PARAMETROS = acceso("prepParametros");
export const ACCESO_AVANZADO = acceso("prepAvanzado");
export const ACCESO_ENRIQUECER = acceso("prepEnriquecer");
