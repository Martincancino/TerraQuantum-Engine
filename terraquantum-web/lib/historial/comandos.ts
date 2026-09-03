// ─── FASE 13 (auditoría 06 §10) — Historial de comandos por DELTAS ────────────
//
// El informe 04 (§9F.2, punto 3) es explícito y la auditoría lo repite en
// `docs/06_AUDITORIA_TECNICA_INTEGRAL.md:1112` y `:1120`: undo/redo se guarda
// como **incrementos**, nunca clonando el documento entero. No es una
// preferencia estética. Medido en este repositorio:
//
//   · `GravityCorrectionWizard` guarda el CSV parseado ENTERO en su estado
//     (`csvRows`), y `PrepEnrichPanel` guarda el CSV enriquecido completo como
//     string (`result.packageText`).
//   · El `model` del visor llega a ~1,7 M vóxeles (`useAppStore.ts`, factor de
//     resolución de display 6).
//
// Un historial por instantáneas multiplicaría esos bloques por cada entrada.
// Uno por deltas los toca una sola vez y por REFERENCIA.
//
// Este módulo no sabe nada de Zustand, de React ni del dominio: recibe deltas
// ya calculados y los ordena. Los dos ámbitos que hoy lo alimentan son el visor
// 3D (store de Zustand) y el panel de preparación (reducers de la Fase 10).

/** Los dos orígenes de comandos. Cada uno tiene su pila: deshacer en el visor
 *  no puede sacar una acción del panel de preparación, porque el usuario no las
 *  percibe como una sola secuencia — viven en pestañas distintas y sus controles
 *  nunca están en pantalla a la vez.
 *
 *  (Aquí decía además «y el estado de preparación ni siquiera sobrevive al
 *  cambio de pestaña». **La FASE 24 lo dejó falso**: ese estado vive ahora en el
 *  store y sobrevive; lo que no sobrevive es su HISTORIAL, y el porqué está en
 *  `useReducerConHistorial.ts`. La separación de pilas no dependía de eso.) */
export type Ambito = "visor" | "preparacion";

export const AMBITOS: readonly Ambito[] = ["visor", "preparacion"] as const;

/** Un comando inversible. `antes`/`despues` contienen SÓLO las claves que
 *  cambiaron — es la definición operativa de "delta, no instantánea". */
export interface Delta {
  ambito: Ambito;
  /** Dueño del estado dentro del ámbito. El visor tiene uno solo (el store); el
   *  panel de preparación tiene DOS máquinas independientes (`contexto` y
   *  `parametros`), y el delta tiene que saber a cuál devolverse. */
  grupo: string;
  claves: readonly string[];
  antes: Readonly<Record<string, unknown>>;
  despues: Readonly<Record<string, unknown>>;
  /** Texto que ve el usuario: «Deshacer: Opacidad de vóxeles». */
  etiqueta: string;
  /** true en los controles continuos (sliders): un arrastre es UN comando, no
   *  doscientos. Ver `VENTANA_FUSION_MS`. */
  fusionable: boolean;
  t: number;
}

/** Criterio de aceptación de la fase: «el historial no crece sin límite».
 *
 *  50 no es un número redondo elegido al azar. El coste de una entrada es el de
 *  las claves que cambiaron (un booleano, un número, o los 6 números de la caja
 *  de corte), no el del estado: 50 entradas son unos pocos kilobytes. Y por
 *  arriba, 50 deshaceres consecutivos es más de lo que un usuario reconstruye
 *  mentalmente — pasado ese punto el historial deja de ser una ayuda y se
 *  vuelve una máquina del tiempo que nadie sabe leer. */
export const TECHO_HISTORIAL = 50;

/** Ventana de fusión de comandos continuos. Un arrastre de slider emite un
 *  evento cada pocos milisegundos; sin esto, un solo gesto llenaría el techo
 *  entero y borraría todo lo anterior.
 *
 *  Contrapartida declarada: si el usuario arrastra despacio y se detiene más de
 *  medio segundo, el arrastre se parte en dos comandos. Es el precio de no
 *  tener una señal de «soltó el ratón» a nivel de estado; se prefiere partir de
 *  más a fusionar dos gestos deliberados en uno. */
export const VENTANA_FUSION_MS = 500;

interface Pila {
  deshacer: Delta[];
  rehacer: Delta[];
}

const pilas: Record<Ambito, Pila> = {
  visor: { deshacer: [], rehacer: [] },
  preparacion: { deshacer: [], rehacer: [] },
};

// ── Suscripción (para que la UI se entere sin sondear) ───────────────────────

type Oyente = () => void;
const oyentes = new Set<Oyente>();

function avisar(): void {
  instantaneas = { visor: null, preparacion: null };
  for (const o of oyentes) o();
}

export function suscribir(o: Oyente): () => void {
  oyentes.add(o);
  return () => {
    oyentes.delete(o);
  };
}

/** Lo que la UI necesita saber, y nada más. */
export interface ResumenHistorial {
  puedeDeshacer: boolean;
  puedeRehacer: boolean;
  /** Etiqueta del comando que se desharía, para el tooltip. null si no hay. */
  etiquetaDeshacer: string | null;
  etiquetaRehacer: string | null;
  tamano: number;
}

const RESUMEN_VACIO: ResumenHistorial = {
  puedeDeshacer: false,
  puedeRehacer: false,
  etiquetaDeshacer: null,
  etiquetaRehacer: null,
  tamano: 0,
};

// `useSyncExternalStore` exige que la instantánea sea ESTABLE por referencia
// mientras nada cambie: devolver un objeto nuevo en cada lectura provoca un
// bucle de renders. Se cachea y se invalida en `avisar()`.
let instantaneas: Record<Ambito, ResumenHistorial | null> = {
  visor: null,
  preparacion: null,
};

export function resumen(ambito: Ambito): ResumenHistorial {
  const cacheada = instantaneas[ambito];
  if (cacheada) return cacheada;
  const p = pilas[ambito];
  const arriba = p.deshacer[p.deshacer.length - 1];
  const rearriba = p.rehacer[p.rehacer.length - 1];
  const nueva: ResumenHistorial = {
    puedeDeshacer: p.deshacer.length > 0,
    puedeRehacer: p.rehacer.length > 0,
    etiquetaDeshacer: arriba ? arriba.etiqueta : null,
    etiquetaRehacer: rearriba ? rearriba.etiqueta : null,
    tamano: p.deshacer.length,
  };
  instantaneas[ambito] = nueva;
  return nueva;
}

/** Instantánea para el render del servidor: en SSR no hay historial todavía.
 *  Debe ser la MISMA referencia siempre o React avisa de bucle. */
export function resumenServidor(): ResumenHistorial {
  return RESUMEN_VACIO;
}

// ── Escritura ────────────────────────────────────────────────────────────────

/** Registra un comando. Devuelve `true` si entró como entrada nueva y `false`
 *  si se fusionó con la anterior (útil para los tests). */
export function registrar(delta: Delta): boolean {
  if (delta.claves.length === 0) return false;
  const p = pilas[delta.ambito];

  // Cualquier acción nueva invalida el futuro: es la regla del Command Pattern.
  // Sin esto, rehacer aplicaría un comando calculado sobre un estado que ya no
  // existe — el bug clásico de los undo caseros.
  p.rehacer.length = 0;

  const arriba = p.deshacer[p.deshacer.length - 1];
  if (
    arriba &&
    arriba.fusionable &&
    delta.fusionable &&
    arriba.grupo === delta.grupo &&
    delta.t - arriba.t < VENTANA_FUSION_MS &&
    mismasClaves(arriba.claves, delta.claves)
  ) {
    // Fusión: se conserva el `antes` MÁS ANTIGUO (deshacer devuelve al punto en
    // el que empezó el gesto) y se toma el `despues` más reciente.
    p.deshacer[p.deshacer.length - 1] = {
      ...arriba,
      despues: delta.despues,
      t: delta.t,
    };
    avisar();
    return false;
  }

  p.deshacer.push(delta);
  if (p.deshacer.length > TECHO_HISTORIAL) {
    // Anillo: se cae la MÁS ANTIGUA. El estado no se pierde (sigue aplicado);
    // lo que se pierde es la capacidad de volver más atrás que N pasos.
    p.deshacer.splice(0, p.deshacer.length - TECHO_HISTORIAL);
  }
  avisar();
  return true;
}

function mismasClaves(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ── Lectura destructiva ──────────────────────────────────────────────────────

/** Saca el último comando y lo pasa a la pila de rehacer. Devuelve el delta
 *  para que el llamador aplique `antes`; este módulo no toca ningún estado. */
export function sacarParaDeshacer(ambito: Ambito): Delta | null {
  const p = pilas[ambito];
  const d = p.deshacer.pop();
  if (!d) return null;
  p.rehacer.push(d);
  avisar();
  return d;
}

/** Simétrico: devuelve el delta para que el llamador aplique `despues`. */
export function sacarParaRehacer(ambito: Ambito): Delta | null {
  const p = pilas[ambito];
  const d = p.rehacer.pop();
  if (!d) return null;
  p.deshacer.push(d);
  avisar();
  return d;
}

/** Borra la historia de un ámbito. Se llama en las BARRERAS: momentos tras los
 *  cuales volver atrás sería una mentira, no una comodidad.
 *
 *  Hoy hay dos, ambas medidas:
 *   · el usuario cambia de archivo en el panel de preparación (H-29: los
 *     reconocimientos de riesgo CADUCAN con el archivo; un Ctrl+Z que los
 *     resucite re-afirmaría un consentimiento que el proyecto mató a propósito);
 *   · cambia la identidad de la corrida activa en el visor.
 *
 *  El `motivo` no se usa en producción: existe para que quien lea el código vea
 *  por qué se borra, y para poder afirmarlo en un test. */
export function limpiar(ambito: Ambito, motivo: string): void {
  void motivo;
  const p = pilas[ambito];
  if (p.deshacer.length === 0 && p.rehacer.length === 0) return;
  p.deshacer.length = 0;
  p.rehacer.length = 0;
  avisar();
}

/** Sólo para los tests y para el arranque: deja las dos pilas como recién
 *  creadas. No se llama desde ningún camino de usuario. */
export function reiniciarTodo(): void {
  for (const a of AMBITOS) {
    pilas[a].deshacer.length = 0;
    pilas[a].rehacer.length = 0;
  }
  avisar();
}

// ── Cálculo del delta ────────────────────────────────────────────────────────

/** Compara dos estados SÓLO sobre las claves vigiladas y devuelve el delta.
 *
 *  Esto es el corazón de «deltas, no instantáneas»: el objeto que sale contiene
 *  únicamente las claves que cambiaron. Si nada cambió, devuelve `null` y no se
 *  registra nada — que es lo que mantiene fuera del historial las ráfagas de
 *  escritura del backend (escriben claves que no están vigiladas).
 *
 *  La comparación es `Object.is`, es decir POR REFERENCIA para los objetos.
 *  Vale porque las claves vigiladas son primitivas salvo `clipBox`, que el
 *  store reemplaza entero en cada cambio (nunca lo muta in situ). */
export function calcularDelta<E extends Record<string, unknown>>(
  ambito: Ambito,
  grupo: string,
  antes: E,
  despues: E,
  vigiladas: readonly string[],
  etiquetar: (claves: readonly string[]) => { etiqueta: string; fusionable: boolean },
  ahora: number,
): Delta | null {
  const claves: string[] = [];
  for (const k of vigiladas) {
    if (!Object.is(antes[k], despues[k])) claves.push(k);
  }
  if (claves.length === 0) return null;

  const a: Record<string, unknown> = {};
  const d: Record<string, unknown> = {};
  for (const k of claves) {
    a[k] = antes[k];
    d[k] = despues[k];
  }

  const { etiqueta, fusionable } = etiquetar(claves);
  return { ambito, grupo, claves, antes: a, despues: d, etiqueta, fusionable, t: ahora };
}
