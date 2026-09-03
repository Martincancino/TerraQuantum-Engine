// ─── FASE 24 — El estado del flujo PRINCIPAL de preparación, fuera del componente ──
//
// Este fichero no inventa nada: es el `EnriquecerState` que la **Fase 10** creó
// dentro de `PrepEnrichPanel.tsx` (17 `useState` → una máquina con transiciones
// con nombre), movido aquí **sin cambiarle una línea de lógica**. Se mueve por
// una razón concreta y no estética: la Fase 24 lo sube al store, y el store lo
// importa el árbol entero. Si el valor inicial y el reducer siguieran viviendo
// en un `.tsx` de cliente, `store/useAppStore.ts` tendría que importar un
// componente — la clase de dependencia que convierte un store en el centro del
// grafo de módulos. `prepPanelState.ts` (Fase 10) ya vive aquí por el mismo
// motivo; esto sólo le pone al lado a su hermano.
//
// Lo ÚNICO nuevo es `ARCHIVOS_CAMBIARON`, y su motivo está abajo, en el reducer.
//
// Regla de Oro: aquí no se calcula física. Son transiciones de interfaz.

import type {
  ColumnMappingPlan,
  EnrichmentSummary,
  SniffReport,
} from "../../lib/terraquantum/frontendApi";

/** FASE 19 (Caso B) — fila editable de punto de control (todo string en la UI). */
export type ControlPointRow = {
  localX: string;
  localY: string;
  realE: string;
  realN: string;
};

export type PaqueteEnriquecido = {
  filename: string;
  packageText: string;
  summary: EnrichmentSummary;
  warnings: string[];
  nStations: number;
};

export type EnriquecerState = {
  gravFile: File | null;
  magFile: File | null;
  utmZone: string;
  gravimeterType: string;
  surveyDate: string;
  useHelmert: boolean;
  ctrlPoints: ControlPointRow[];
  loading: boolean;
  error: string | null;
  mappingPlan: ColumnMappingPlan | null;
  columnMap: Record<string, string>;
  sniffReport: SniffReport | null;
  sampleRows: Record<string, string>[];
  mapRoomStations: Record<string, number | string>[] | null;
  mapRoomLoading: boolean;
  mapRoomError: string | null;
  result: PaqueteEnriquecido | null;
};

export const enriquecerInicial: EnriquecerState = {
  gravFile: null, magFile: null,
  utmZone: "", gravimeterType: "unknown", surveyDate: "",
  useHelmert: false,
  ctrlPoints: [
    { localX: "", localY: "", realE: "", realN: "" },
    { localX: "", localY: "", realE: "", realN: "" },
  ],
  loading: false, error: null,
  mappingPlan: null, columnMap: {}, sniffReport: null, sampleRows: [],
  mapRoomStations: null, mapRoomLoading: false, mapRoomError: null,
  result: null,
};

export type EnriquecerAction =
  | { type: "CAMPO"; campo: keyof EnriquecerState; valor: EnriquecerState[keyof EnriquecerState] }
  | { type: "GENERACION_PEDIDA" }
  | { type: "GENERACION_TERMINADA" }
  | { type: "GENERACION_FALLO"; mensaje: string }
  /** El backend no pudo con las columnas: hay que mapear antes de enriquecer. */
  | { type: "HACE_FALTA_MAPEO"; plan: ColumnMappingPlan; sniff: SniffReport | null;
      filas: Record<string, string>[]; mapaPrevio: Record<string, string>; mensaje: string | null }
  | { type: "PAQUETE_LISTO"; paquete: PaqueteEnriquecido; sniff: SniffReport | null }
  | { type: "MAPA_ACTUALIZADO"; mapa: Record<string, string> }
  | { type: "SALA_DE_MAPAS_PEDIDA" }
  | { type: "SALA_DE_MAPAS_OK"; estaciones: Record<string, number | string>[] }
  | { type: "SALA_DE_MAPAS_FALLO"; mensaje: string }
  /** FASE 24 — el usuario cambió un archivo de ORIGEN: caduca todo lo que
   *  describía al anterior. Ver el caso del reducer. */
  | { type: "ARCHIVOS_CAMBIARON" };

export function enriquecerReducer(estado: EnriquecerState, accion: EnriquecerAction): EnriquecerState {
  switch (accion.type) {
    case "CAMPO":
      return { ...estado, [accion.campo]: accion.valor };
    case "GENERACION_PEDIDA":
      // Empezar de nuevo borra el resultado anterior: dejarlo en pantalla
      // mientras se recalcula es la forma más barata de mentir.
      return { ...estado, loading: true, error: null, result: null };
    case "GENERACION_TERMINADA":
      return { ...estado, loading: false };
    case "GENERACION_FALLO":
      return { ...estado, loading: false, error: accion.mensaje };
    case "HACE_FALTA_MAPEO":
      return {
        ...estado,
        mappingPlan: accion.plan,
        sniffReport: accion.sniff,
        sampleRows: accion.filas,
        columnMap: accion.mapaPrevio,
        error: accion.mensaje,
        result: null,
      };
    case "PAQUETE_LISTO":
      // Y al revés: si salió el paquete, el paso de mapeo se cierra.
      return { ...estado, mappingPlan: null, sniffReport: accion.sniff,
               result: accion.paquete, error: null };
    case "MAPA_ACTUALIZADO":
      return { ...estado, columnMap: accion.mapa };
    case "SALA_DE_MAPAS_PEDIDA":
      return { ...estado, mapRoomLoading: true, mapRoomError: null };
    case "SALA_DE_MAPAS_OK":
      return { ...estado, mapRoomLoading: false, mapRoomStations: accion.estaciones };
    case "SALA_DE_MAPAS_FALLO":
      return { ...estado, mapRoomLoading: false, mapRoomError: accion.mensaje };
    case "ARCHIVOS_CAMBIARON":
      // ─── FASE 24 — la caducidad que a este panel le FALTABA ────────────────
      //
      // MEDIDO al abrir la fase: el flujo clásico tenía `ARCHIVOS_CAMBIARON` en
      // tres de sus cuatro máquinas desde la Fase 10 (H-29), y el flujo
      // PRINCIPAL —por donde entra el usuario— no tenía ninguna. Cambiar el CSV
      // de gravimetría dejaba en pantalla la `ResultCard` del archivo anterior,
      // con su `packageText` completo detrás del botón «Descargar», y reenviaba
      // el `columnMap` del anterior en la siguiente generación.
      //
      // Hoy ese agujero dura una visita a la pestaña, porque el desmontaje lo
      // tapa por accidente. **Esta fase quita ese accidente**: al hacer que el
      // estado sobreviva, el agujero pasaría a durar la sesión entera. Hacer
      // sobrevivir el estado OBLIGA a declarar su caducidad — no es un extra.
      //
      // Lo que caduca es lo que DESCRIBE al archivo. Lo que el usuario declara
      // sobre el SURVEY (zona UTM, gravímetro, fecha, puntos Helmert) no: son
      // afirmaciones sobre el terreno, no sobre el fichero.
      return {
        ...estado,
        mappingPlan: null,
        columnMap: {},
        sniffReport: null,
        sampleRows: [],
        result: null,
        mapRoomStations: null,
        error: null,
        mapRoomError: null,
      };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}
