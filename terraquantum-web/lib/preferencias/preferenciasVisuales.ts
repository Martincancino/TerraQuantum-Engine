// ─── FASE 13 (auditoría 06 §10) — Persistencia de las preferencias del visor ──
//
// La auditoría lo puso en §9H.2 como uno de los tres huecos que más cuestan en
// una demo: «la app fuerza una pantalla de bienvenida en cada recarga y no
// recuerda el estado. Para un experto que la abre a diario, es fricción diaria».
// Medido al abrir la fase, es cierto y no había NADA que respetar: el store se
// crea sin middleware de persistencia y el único uso de `localStorage` en todo
// el frontend es la clave BYO del copiloto.
//
// ── Qué se guarda, y por qué justo eso ──────────────────────────────────────
//
// Sólo PREFERENCIAS: cómo quiere ver el usuario, nunca qué está viendo. La
// diferencia no es de tamaño, es de verdad. Un `model`, un `report` o una malla
// de isosuperficies pertenecen a UNA corrida —la Fase 1 los selló con
// `modelRunKey` justamente para que no sobrevivan a ella—, y restaurarlos al
// abrir la app pintaría el resultado de ayer sobre el encabezado de hoy.
//
// Tampoco se guardan las posiciones de corte (`slicePosition`, `clipBox`): van
// en coordenadas del modelo, y heredarlas sobre otra malla no es una preferencia
// sino un número sin significado.
//
// ── El aviso que hay que dar, porque es real ────────────────────────────────
//
// MEDIDO en el empaquetado: el orquestador de Tauri sirve la interfaz en el
// PRIMER puerto libre del tramo 3000..3011 y navega la ventana a
// `http://localhost:<puerto>`. `localStorage` está particionado por origen, y
// 3000 y 3001 son orígenes distintos: si algo ocupa el 3000 (otra instancia, un
// `npm run dev`, un contenedor), las preferencias guardadas dejan de verse.
//
// No se disimula: la degradación es benigna (se vuelve a los valores por
// defecto, nunca a datos de otro), la ausencia de almacén es el caso NORMAL y
// no un error, y queda escrito en `docs/06` como deuda con dueño. La alternativa
// —guardarlas en el backend, que sí tiene ruta estable— exige un endpoint nuevo
// y es una iteración de backend, no de esta fase.
//
// La API de Tauri tampoco es una salida: `src-tauri/capabilities/default.json`
// no declara `remote`, así que la aplicación servida por HTTP no recibe ningún
// permiso aunque `withGlobalTauri` exponga el objeto.

import type { AppState } from "../../store/useAppStore";

export const CLAVE_ALMACEN = "tq.preferencias.visor.v1";

/** Un validador por clave. No se restaura nada que no pase por aquí: el
 *  contenido de `localStorage` es una entrada NO CONFIABLE —lo edita cualquiera
 *  desde la consola y sobrevive a los cambios de versión de la app—, y meter un
 *  enum inventado en el store rompería el visor en el arranque. */
type Validador<T> = (v: unknown) => v is T;

const esBooleano = (v: unknown): v is boolean => typeof v === "boolean";

const esUnoDe =
  <T extends string>(...valores: readonly T[]) =>
  (v: unknown): v is T =>
    typeof v === "string" && (valores as readonly string[]).includes(v);

const esNumeroEntre =
  (min: number, max: number) =>
  (v: unknown): v is number =>
    typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;

const esUnoDeNumeros =
  (...valores: readonly number[]) =>
  (v: unknown): v is number =>
    typeof v === "number" && valores.includes(v);

/** Las claves persistidas. Es un SUBCONJUNTO de las deshacibles, y lo es por
 *  construcción: si el usuario no puede cambiar algo, guardarlo no significa
 *  nada. Cada entrada trae su validador. */
export const PREFERENCIAS_PERSISTIDAS = {
  showIsosurfaces: esBooleano,
  showSectionPaint: esBooleano,
  showOnlySlice: esBooleano,
  showMviVectors: esBooleano,
  subsurfaceAoEnabled: esBooleano,
  visualProfessionalMode: esBooleano,
  clipBoxEnabled: esBooleano,
  sliceAxis: esUnoDe("x", "y", "z", "none"),
  viewMode: esUnoDe("density", "susceptibility", "joint"),
  volumeRenderMode: esUnoDe("off", "fog", "isosurface"),
  jointThreshold: esNumeroEntre(0, 1),
  displayResolutionFactor: esUnoDeNumeros(1, 4, 6),
} as const satisfies Partial<{ [K in keyof AppState]: Validador<AppState[K]> }>;

export type ClavePersistida = keyof typeof PREFERENCIAS_PERSISTIDAS;

/** Las deshacibles que NO se guardan, con motivo. La lista es portante: hay un
 *  test que comprueba que sigue describiendo la realidad. */
export const NO_PERSISTIDA: Record<string, string> = {
  slicePosition:
    "Va en metros del modelo. Heredar la posición de corte de otra malla no es una preferencia: " +
    "es un número sin significado sobre el dato nuevo. `setSliceAxis` ya la deja en 0 al activar " +
    "un eje, que es el aterrizaje correcto.",
  clipBox:
    "Ídem: seis coordenadas del modelo. Se guarda el interruptor (`clipBoxEnabled`), no los límites.",
  showBoreholes:
    "Enciende una capa cuyos datos pertenecen a una corrida concreta. Restaurarla al arrancar, sin " +
    "corrida activa, dejaría el toggle en ON sobre nada.",
  showDoiOverlay:
    "Ídem sondajes, y peor: el horizonte DOI es el juicio de incertidumbre de UNA inversión.",
};

// ── Lectura ──────────────────────────────────────────────────────────────────

/**
 * Lee las preferencias guardadas, descartando en silencio lo que no valide.
 *
 * Devuelve `{}` en todos los casos degradados —sin `window`, sin almacén, JSON
 * corrupto, versión distinta—, porque **no haber guardado nada es el caso
 * normal**, no un fallo del que informar.
 */
export function leerPreferencias(): Partial<Pick<AppState, ClavePersistida>> {
  if (typeof window === "undefined") return {};
  let bruto: string | null = null;
  try {
    bruto = window.localStorage.getItem(CLAVE_ALMACEN);
  } catch {
    // Almacenamiento deshabilitado (modo privado, política de empresa).
    return {};
  }
  if (!bruto) return {};

  let datos: unknown;
  try {
    datos = JSON.parse(bruto);
  } catch {
    return {};
  }
  if (typeof datos !== "object" || datos === null) return {};

  const fuente = datos as Record<string, unknown>;
  const salida: Record<string, unknown> = {};
  for (const [clave, valida] of Object.entries(PREFERENCIAS_PERSISTIDAS)) {
    if (!(clave in fuente)) continue;
    const v = fuente[clave];
    if ((valida as (x: unknown) => boolean)(v)) salida[clave] = v;
  }
  return salida as Partial<Pick<AppState, ClavePersistida>>;
}

// ── Escritura ────────────────────────────────────────────────────────────────

export function escribirPreferencias(estado: Pick<AppState, ClavePersistida>): void {
  if (typeof window === "undefined") return;
  const salida: Record<string, unknown> = {};
  for (const clave of Object.keys(PREFERENCIAS_PERSISTIDAS) as ClavePersistida[]) {
    salida[clave] = estado[clave];
  }
  try {
    window.localStorage.setItem(CLAVE_ALMACEN, JSON.stringify(salida));
  } catch {
    // Cuota llena o almacenamiento deshabilitado. Perder una preferencia no
    // justifica romper la sesión del usuario: se sigue sin guardar.
  }
}

/** Extrae del estado completo sólo lo persistible. Se usa para comparar antes
 *  de escribir y no tocar el disco en cada movimiento de un slider. */
export function huellaDePreferencias(estado: Pick<AppState, ClavePersistida>): string {
  const salida: Record<string, unknown> = {};
  for (const clave of Object.keys(PREFERENCIAS_PERSISTIDAS) as ClavePersistida[]) {
    salida[clave] = estado[clave];
  }
  return JSON.stringify(salida);
}
