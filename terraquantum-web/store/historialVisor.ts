// ─── FASE 13 (auditoría 06 §10) — El historial del visor, cableado al store ───
//
// Middleware de Zustand que observa cada escritura, calcula el DELTA sobre las
// 16 claves deshacibles y lo registra. Todo lo demás pasa sin dejar rastro: la
// ráfaga de cinco escrituras con la que termina una inversión, los payloads del
// backend y la telemetría del render no entran en el historial porque sus
// claves no están vigiladas — no porque alguien se acuerde de filtrarlas.
//
// Este módulo NO importa `useAppStore`: se quedaría un ciclo, porque el store lo
// importa a él. Guarda la `api` que el propio middleware recibe y opera contra
// ella. Es también la razón de que `deshacible.ts` importe `AppState` sólo como
// tipo (se borra al compilar).

import type { StateCreator, StoreApi } from "zustand";
import type { AppState } from "./useAppStore";
import { CLAVES_DESHACIBLES, ORDEN_VIGILADO, etiquetarCambio } from "./deshacible";
import {
  calcularDelta,
  limpiar,
  registrar,
  sacarParaDeshacer,
  sacarParaRehacer,
} from "../lib/historial/comandos";

type Establecer = StoreApi<AppState>["setState"];

/** El visor tiene un solo dueño de estado (el store), a diferencia del panel de
 *  preparación, que tiene dos máquinas. */
const GRUPO_VISOR = "store";

let api: StoreApi<AppState> | null = null;

/** Mientras está en alto, las escrituras NO se registran. Lo levantan sólo dos
 *  caminos: aplicar un deshacer/rehacer (que no debe grabar su propio eco) y
 *  rehidratar las preferencias guardadas al arrancar (que no es una acción del
 *  usuario en esta sesión). */
let silencio = false;

/** Aplica un parche sin que el historial lo grabe. Único punto por el que se
 *  escribe el store "desde fuera" en esta fase. */
export function aplicarSinRegistrar(parche: Partial<AppState>): void {
  if (!api) return;
  silencio = true;
  try {
    api.setState(parche);
  } finally {
    silencio = false;
  }
}

export const conHistorial =
  (crear: StateCreator<AppState>): StateCreator<AppState> =>
  (set, get, store) => {
    api = store;

    const establecer = ((parcial: unknown, reemplazar?: boolean) => {
      const antes = get();
      (set as unknown as (p: unknown, r?: boolean) => void)(parcial, reemplazar);
      const despues = get();

      // BARRERA. Al cambiar la identidad de la corrida, el store ya invalida
      // doce campos derivados; el historial tiene que caer con ellos. Un
      // Ctrl+Z que cruzara ese límite restauraría un corte o una capa que
      // pertenecían a OTRA corrida, y la Fase 1 (H-28) existe justo para que
      // nada de una corrida sobreviva a la siguiente.
      if (
        antes.activeRun.projectId !== despues.activeRun.projectId ||
        antes.activeRun.runId !== despues.activeRun.runId
      ) {
        limpiar("visor", "cambió la identidad de la corrida activa");
        return;
      }

      if (silencio) return;

      const delta = calcularDelta(
        "visor",
        GRUPO_VISOR,
        antes as unknown as Record<string, unknown>,
        despues as unknown as Record<string, unknown>,
        ORDEN_VIGILADO,
        etiquetarCambio,
        Date.now(),
      );
      if (delta) registrar(delta);
    }) as Establecer;

    // Se reemplaza también en la `api`, no sólo en el `set` que reciben las
    // acciones: así una escritura directa `useAppStore.setState(...)` tampoco
    // puede saltarse el historial. (Medido al abrir la fase: hoy no hay ninguna
    // en todo el árbol; esto impide que aparezca la primera sin enterarse.)
    store.setState = establecer;

    return crear(establecer, get, store);
  };

// ── Puerta de las corridas en curso ──────────────────────────────────────────

/** El criterio de aceptación dice «no interfiere con corridas en curso», y esta
 *  fase lo cumple en DOS capas independientes:
 *
 *  1. **Por construcción.** Ni `activeRun`, ni `model`, ni `view`, ni `show3D`,
 *     ni ningún payload del backend son deshacibles. Aunque esta puerta fallara,
 *     un deshacer no puede tocar una corrida: no tiene por dónde.
 *  2. **Esta puerta**, que además evita el desperdicio: deshacer una perilla
 *     visual relanza el worker de geometría (su efecto tiene entre sus
 *     dependencias el corte, los umbrales y la capa física), y hacerlo encima de
 *     una carga en marcha sería trabajo tirado.
 *
 *  HUECO MEDIDO Y DECLARADO: entre el clic de «Cargar modelo 3D» y la primera
 *  escritura de identidad, el paquete se está SUBIENDO y el store no declara
 *  nada — `LoadPanel` lleva su propio `loading` en estado local. En esa ventana
 *  esta puerta deja pasar el deshacer. Es benigno: todavía no hay modelo, así
 *  que no hay worker que relanzar, y la capa 1 sigue impidiendo tocar la corrida.
 *  Cerrarlo del todo exigiría que `LoadPanel` publicara su estado al store, que
 *  es una mutación del camino dorado y no el alcance de esta fase. */
export function sePuedeOperarElHistorial(): boolean {
  if (!api) return false;
  const s = api.getState();
  return !(
    s.activeRun.status === "loading" ||
    s.isBlockModelLoading ||
    s.isWorkerProcessing
  );
}

// ── Deshacer / rehacer ───────────────────────────────────────────────────────

export function deshacerVisor(): boolean {
  if (!sePuedeOperarElHistorial()) return false;
  const d = sacarParaDeshacer("visor");
  if (!d) return false;
  aplicarSinRegistrar(d.antes as Partial<AppState>);
  return true;
}

export function rehacerVisor(): boolean {
  if (!sePuedeOperarElHistorial()) return false;
  const d = sacarParaRehacer("visor");
  if (!d) return false;
  aplicarSinRegistrar(d.despues as Partial<AppState>);
  return true;
}

/** Las claves que el historial vigila, para los tests y para la UI. */
export const CLAVES_VIGILADAS = Object.keys(CLAVES_DESHACIBLES);
