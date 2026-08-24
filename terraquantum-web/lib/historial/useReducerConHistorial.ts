"use client";

// ─── FASE 13 (auditoría 06 §10) — Historial sobre los reducers de la Fase 10 ──
//
// El criterio de aceptación pide Ctrl+Z «en las acciones de preparación y
// visualización». Las de visualización viven en Zustand y las cubre
// `store/historialVisor.ts`. Las de preparación NO: viven en cuatro máquinas de
// `useReducer` que construyó la Fase 10 (`componentes/prep/prepPanelState.ts`).
//
// **Este hook no toca esas máquinas.** Y no es una elección estética: los cuatro
// reducers cierran con `const _exhaustivo: never = accion`, así que añadir
// UNDO/REDO a su unión de acciones rompería la compilación de las seis máquinas
// a la vez. Envolviendo por fuera, `prepPanelState.ts` queda con 0 líneas
// modificadas.
//
// Tres decisiones que conviene no re-litigar:
//
// 1. **El registro va en un efecto, no dentro del reducer.** Un reducer tiene
//    que ser puro; React lo invoca dos veces en modo estricto y grabar ahí
//    duplicaría cada comando. El efecto compara el estado anterior con el nuevo,
//    que además es exactamente la forma de sacar un delta.
// 2. **El historial no vive dentro del `useReducer`.** MEDIDO: `PreparacionView`
//    sólo se monta cuando la vista activa es «preparación», así que cambiar de
//    pestaña DESMONTA el árbol y resetea las cuatro máquinas a su estado
//    inicial. Un historial guardado ahí moriría con ellas — y peor, un deshacer
//    posterior aplicaría un delta contra un estado que ya no es el que lo
//    produjo. Por eso las pilas viven en `comandos.ts` y **se limpian al
//    desmontar**, que es coherente con lo que el panel ya hacía con su estado.
// 3. **Hay dos grupos, no una transacción.** La única acción que cruza las dos
//    máquinas es el cambio de archivos, y ésa no entra en el historial: es una
//    BARRERA que lo borra (ver `limpiarHistorialPreparacion`).

import { useEffect, useMemo, useReducer, useRef, type Dispatch } from "react";
import {
  calcularDelta,
  limpiar,
  registrar,
  sacarParaDeshacer,
  sacarParaRehacer,
  type Ambito,
  type Delta,
} from "./comandos";

const MARCA_RESTAURAR = "__HISTORIAL_RESTAURAR__";

interface AccionRestaurar {
  type: typeof MARCA_RESTAURAR;
  parche: Record<string, unknown>;
}

function esRestaurar(a: unknown): a is AccionRestaurar {
  return (
    typeof a === "object" &&
    a !== null &&
    (a as { type?: unknown }).type === MARCA_RESTAURAR
  );
}

// ── Registro de aplicadores ──────────────────────────────────────────────────
//
// Un delta lleva su `grupo`; deshacer necesita saber a qué `dispatch` mandarlo.
// El registro es module-level porque los atajos de teclado se disparan desde
// fuera del árbol de React que posee el estado.

type Aplicador = (parche: Record<string, unknown>) => void;
const aplicadores = new Map<string, Aplicador>();

const clave = (ambito: Ambito, grupo: string) => `${ambito}::${grupo}`;

function aplicar(d: Delta, cual: "antes" | "despues"): boolean {
  const f = aplicadores.get(clave(d.ambito, d.grupo));
  if (!f) return false;
  f(cual === "antes" ? d.antes : d.despues);
  return true;
}

export interface OpcionesReducerConHistorial<E> {
  ambito: Ambito;
  /** Identifica la máquina dentro del ámbito: «contexto», «parametros»… */
  grupo: string;
  /** Las claves que SÍ se deshacen. Lo que no esté aquí es invisible al
   *  historial: no se graba y no se restaura. */
  vigiladas: readonly (keyof E & string)[];
  etiquetar: (claves: readonly string[]) => { etiqueta: string; fusionable: boolean };
}

/**
 * `useReducer` que además graba deltas de las claves vigiladas.
 *
 * Devuelve exactamente lo que devuelve `useReducer`, así que sustituirlo es un
 * cambio de una línea en el llamador y el JSX no se entera.
 */
export function useReducerConHistorial<E extends Record<string, unknown>, A>(
  reducer: (estado: E, accion: A) => E,
  inicial: E,
  opciones: OpcionesReducerConHistorial<E>,
): [E, Dispatch<A>] {
  const { ambito, grupo, vigiladas, etiquetar } = opciones;

  const envuelto = useMemo(
    () =>
      (estado: E, accion: A | AccionRestaurar): E => {
        // La acción de restaurar NUNCA llega al reducer original: por eso su
        // comprobación de exhaustividad (`never`) sigue intacta.
        if (esRestaurar(accion)) return { ...estado, ...(accion.parche as Partial<E>) };
        return reducer(estado, accion);
      },
    [reducer],
  );

  const [estado, despachar] = useReducer(envuelto, inicial);

  const anterior = useRef<E>(inicial);
  const restaurando = useRef(false);

  // Registro del aplicador y BARRERA de desmontaje.
  useEffect(() => {
    const k = clave(ambito, grupo);
    aplicadores.set(k, (parche) => {
      restaurando.current = true;
      despachar({ type: MARCA_RESTAURAR, parche } as AccionRestaurar as A);
    });
    return () => {
      aplicadores.delete(k);
      // Al desmontar, el estado de esta máquina vuelve a su inicial: un delta
      // guardado describiría una transición que ya no existe.
      limpiar(ambito, "se desmontó el panel de preparación");
    };
  }, [ambito, grupo]);

  // Grabación. Comparar contra la referencia anterior es puro y sobrevive al
  // doble render del modo estricto (la segunda pasada ve `antes === estado`).
  useEffect(() => {
    const antes = anterior.current;
    if (antes === estado) return;
    anterior.current = estado;

    if (restaurando.current) {
      restaurando.current = false;
      return;
    }

    const d = calcularDelta(ambito, grupo, antes, estado, vigiladas, etiquetar, Date.now());
    if (d) registrar(d);
  }, [estado, ambito, grupo, vigiladas, etiquetar]);

  return [estado, despachar as Dispatch<A>];
}

// ── Deshacer / rehacer de un ámbito basado en reducers ───────────────────────

export function deshacerAmbito(ambito: Ambito): boolean {
  const d = sacarParaDeshacer(ambito);
  if (!d) return false;
  if (!aplicar(d, "antes")) {
    // El dueño de ese grupo ya no está montado. Se descarta el historial entero
    // en vez de dejar entradas que no se pueden aplicar: un botón que dice
    // «deshacer» y no deshace es justo el defecto que esta fase persigue.
    limpiar(ambito, "el dueño del comando ya no está montado");
    return false;
  }
  return true;
}

export function rehacerAmbito(ambito: Ambito): boolean {
  const d = sacarParaRehacer(ambito);
  if (!d) return false;
  if (!aplicar(d, "despues")) {
    limpiar(ambito, "el dueño del comando ya no está montado");
    return false;
  }
  return true;
}

/** BARRERA del panel de preparación.
 *
 *  Se llama cuando el usuario cambia de archivo. **No es una comodidad: es una
 *  regla de seguridad de datos.** H-29 fue exactamente que un reconocimiento de
 *  riesgo marcado entendiendo el archivo A viajaba al backend como si el usuario
 *  hubiera aceptado el riesgo del archivo B. La Fase 10 lo convirtió en la
 *  transición `ARCHIVOS_CAMBIARON`, que caduca esos reconocimientos.
 *
 *  Un Ctrl+Z que cruzara ese límite los resucitaría. Así que el historial no
 *  cruza: se borra. */
export function limpiarHistorialPreparacion(motivo: string): void {
  limpiar("preparacion", motivo);
}
