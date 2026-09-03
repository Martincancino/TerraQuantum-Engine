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
// 2. **El historial no vive dentro del `useReducer`.** Las pilas viven en
//    `comandos.ts`, que es un módulo: sobreviven al desmontaje por
//    construcción. Se limpian **a propósito** al desmontar el panel, y la
//    FASE 24 tuvo que re-justificar ese borrado porque le quitó su premisa.
//
//    La razón original era: «cambiar de pestaña resetea las cuatro máquinas a
//    su estado inicial, así que un delta guardado describiría una transición que
//    ya no existe». Desde la Fase 24 **eso es falso**: el estado vive en el
//    store y sobrevive. La razón que queda —y que basta— es el APLICADOR: el
//    mapa `aplicadores` guarda un `despachar` que cierra sobre el componente, y
//    el cleanup lo borra. Un delta superviviente sin dueño montado entra por
//    `deshacerAmbito`, no encuentra aplicador y **borra la pila entera en el
//    acto**: un botón «deshacer» que no deshace, que es justo el defecto que
//    esta familia de código persigue. Se prefiere el borrado explícito y visible
//    al implícito y sorprendente.
//
//    Queda declarado como LÍMITE de la Fase 24: **el estado sobrevive al cambio
//    de pestaña, el historial no.** Es la misma semántica que la barrera de
//    archivos, que el e2e de la Fase 13 ya fija con letra: *se borra la
//    HISTORIA, no el estado*. Hacer que también sobreviva exige que el aplicador
//    deje de depender del montaje, y eso es un cambio del historial, no del
//    panel.
// 3. **Hay dos grupos, no una transacción.** La única acción que cruza las dos
//    máquinas es el cambio de archivos, y ésa no entra en el historial: es una
//    BARRERA que lo borra (ver `limpiarHistorialPreparacion`).

import { useCallback, useEffect, useMemo, useReducer, useRef, type Dispatch } from "react";
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

/** FASE 24 — de dónde sale y a dónde va el estado, cuando NO es un `useReducer`.
 *
 *  `leer` y `escribir` tienen que ser estables entre renders y seguir siendo
 *  válidas después de desmontar (ver `store/preparacion.ts`). `valor` es lo que
 *  se está renderizando ahora. */
export interface EstadoExterno<E> {
  valor: E;
  leer: () => E;
  escribir: (siguiente: E) => void;
}

function esExterno<E>(fuente: E | EstadoExterno<E>): fuente is EstadoExterno<E> {
  return (
    typeof fuente === "object" &&
    fuente !== null &&
    typeof (fuente as EstadoExterno<E>).leer === "function" &&
    typeof (fuente as EstadoExterno<E>).escribir === "function"
  );
}

/**
 * FASE 24 — el `useReducer` de una máquina cuyo estado vive fuera, SIN historial.
 *
 * Es el hermano pobre de `useReducerConHistorial` y existe porque dos de las
 * cuatro máquinas de la Fase 10 (`avanzado`) y la del flujo principal
 * (`enriquecer`) no llevan historial y no deben llevarlo — el motivo de cada
 * exclusión está escrito en `componentes/prep/deshaciblePrep.ts`. Darles el hook
 * con historial «por uniformidad» metería en Ctrl+Z los modales y el CSV
 * corregido, que es justo lo que aquel fichero descartó midiendo.
 */
export function useReducerExterno<E extends Record<string, unknown>, A>(
  reducer: (estado: E, accion: A) => E,
  externo: EstadoExterno<E>,
): Dispatch<A> {
  const { leer, escribir } = externo;
  return useCallback(
    (accion: A) => {
      escribir(reducer(leer(), accion));
    },
    [reducer, leer, escribir],
  );
}

/**
 * `useReducer` que además graba deltas de las claves vigiladas.
 *
 * Devuelve exactamente lo que devuelve `useReducer`, así que sustituirlo es un
 * cambio de una línea en el llamador y el JSX no se entera.
 *
 * **FASE 24 — el estado puede vivir fuera.** Si el tercer argumento es un
 * `EstadoExterno`, la máquina no guarda nada: lee y escribe donde le digan (hoy,
 * el store), y el hook se queda sólo con lo que es suyo — grabar el delta y
 * saber restaurarlo. Los reducers de `prepPanelState.ts` no se enteran: siguen
 * cerrando con su `const _exhaustivo: never = accion`, intacto.
 */
export function useReducerConHistorial<E extends Record<string, unknown>, A>(
  reducer: (estado: E, accion: A) => E,
  fuente: E | EstadoExterno<E>,
  opciones: OpcionesReducerConHistorial<E>,
): [E, Dispatch<A>] {
  const { ambito, grupo, vigiladas, etiquetar } = opciones;
  const externo = esExterno(fuente) ? fuente : null;
  const inicial = externo ? externo.valor : (fuente as E);

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

  // Con estado externo el `useReducer` local queda inerte: se declara igual
  // porque un hook no se puede llamar condicionalmente, y nadie lo despacha.
  const [estadoLocal, despacharLocal] = useReducer(envuelto, inicial);
  const estado = externo ? externo.valor : estadoLocal;

  // `leer`/`escribir` son constantes de módulo (`store/preparacion.ts`), así que
  // este `despachar` es estable — y por eso el efecto de abajo puede depender de
  // él sin re-registrar el aplicador en cada render.
  //
  // El `leer()` es lo que hace correcto despachar DOS acciones seguidas a la
  // misma máquina (`resetOnFileChange`, el `onChange` de los bounds): con el
  // valor del render, la segunda pisaría a la primera. React encolaba por
  // nosotros; un store hay que leerlo cada vez.
  const leer = externo?.leer;
  const escribir = externo?.escribir;
  const despachar = useCallback(
    (accion: A | AccionRestaurar) => {
      if (leer && escribir) escribir(envuelto(leer(), accion));
      else despacharLocal(accion as A);
    },
    [envuelto, leer, escribir],
  );

  // FASE 24 — la semilla es el estado EFECTIVO, no el de fábrica. Con estado
  // externo, al remontar el panel `estado` vale lo que sobrevivió mientras un
  // `useRef(inicialDeFabrica)` valdría los defaults: el efecto de abajo vería
  // una diferencia que el usuario no hizo y grabaría un delta espurio **cuyo
  // `antes` son los valores de fábrica**. Un solo Ctrl+Z habría borrado todo el
  // trabajo bajo la etiqueta «Preset de densidad (+7)».
  const anterior = useRef<E>(inicial);
  const restaurando = useRef(false);

  // Registro del aplicador y BARRERA de desmontaje.
  useEffect(() => {
    const k = clave(ambito, grupo);
    aplicadores.set(k, (parche) => {
      restaurando.current = true;
      despachar({ type: MARCA_RESTAURAR, parche } as AccionRestaurar);
    });
    return () => {
      aplicadores.delete(k);
      // FASE 24 — el motivo ya no es «el estado vuelve a su inicial» (con estado
      // externo ya no vuelve): es que el APLICADOR se va con el componente, y un
      // delta sin dueño hace que `deshacerAmbito` borre la pila entera al primer
      // clic. Se borra aquí, a la vista, en vez de allí, por sorpresa. El
      // razonamiento largo está en la cabecera de este fichero.
      limpiar(ambito, "se desmontó el panel de preparación");
    };
  }, [ambito, grupo, despachar]);

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
