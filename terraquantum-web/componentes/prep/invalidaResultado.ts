// ─── FASE 25 (H-36) — Qué invalida un resultado, declarado por TIPOS ──────────
//
// El aviso «Resultado desactualizado: cambiaste parámetros tras esta inversión»
// (`Exploration3DView.tsx`, badge `stale-result-badge`) se disparaba desde una
// LISTA A MANO: un `JSON.stringify([...])` de 23 variables sueltas dentro de
// `PrepPanel.tsx`. Una lista a mano sólo es correcta el día que se escribe.
//
// **Y ya había dejado de serlo.** MEDIDO al abrir esta fase, comparando la lista
// contra lo que `handleGeneratePackage` mete de verdad en el `config_json` que
// viaja al backend, cuatro entradas que SÍ cambian el paquete no estaban en ella:
//
//   · `implicitGeologyParams`   → `config.implicit_geology` (FASE 14). El prior
//     geológico implícito: cambia el `m_ref` del smallness y con él la solución.
//   · `acknowledgeSpatialRisk`  → `config.acknowledge_spatial_risk`.
//   · `acknowledgeRegionalScale`→ `config.acknowledge_regional_scale`.
//   · `correctedFile`           → es el fichero PRIMARIO del paquete y además
//     fuerza `allow_g_raw`. Aplicar el asistente de correcciones después de
//     invertir cambiaba el dato de entrada entero, en silencio.
//
// La de la Fase 14 es la que el plan nombra, y las otras tres salieron de medir.
// El caso de `correctedFile` es el más caro de los cuatro: cambiar de ARCHIVO sí
// avisa —`resetOnFileChange()` llama a `clearActiveRun()` y el modelo se va—,
// pero `CORRECCIONES_APLICADAS` no pasa por ahí, así que sustituía el CSV bajo un
// modelo que seguía en pantalla sin una sola marca.
//
// **Por qué un tipo y no una lista más larga.** La Fase 13 ya demostró en este
// repositorio que el complemento exacto funciona (`store/deshacible.ts`,
// `NO_DESHACIBLE`): un campo sin clasificar **no compila**. Aquí se repite el
// patrón sobre las tres máquinas de la Fase 10 que la Fase 24 subió al store, que
// es donde viven hoy los parámetros de inversión. Añadir una perilla nueva y no
// decir si invalida el resultado deja de ser un olvido posible.
//
// Y la huella se CONSTRUYE desde esta declaración (`huellaDeInvalidacion`), no se
// escribe aparte: declarar y comparar son el mismo sitio, así que no pueden
// divergir — que es exactamente cómo se abrió H-36.
//
// El criterio, uno solo y comprobable contra `handleGeneratePackage`:
//   **invalida el resultado lo que cambia el paquete que se le manda al backend.**
// No «lo que parece importante». Cada motivo de abajo nombra el campo del payload.
//
// Regla de Oro: aquí no se calcula física. Es una declaración de interfaz.

import type { AppState } from "../../store/useAppStore";
import type { AvanzadoState, ContextoState, ParametrosState } from "./prepPanelState";
import type { EnriquecerState } from "./prepEnrichState";

/** Lo que hay que decir de un parámetro que SÍ invalida el resultado. */
export interface DescriptorInvalidacion<V, S> {
  /** Qué campo del paquete cambia. Se contrasta contra `handleGeneratePackage`. */
  motivo: string;
  /** Valor comparable. Se declara por dos motivos distintos:
   *
   *  1. El valor crudo no sobrevive a `JSON.stringify` — un `File` se serializa
   *     como `{}`, así que dos CSV distintos darían la MISMA huella y el cambio
   *     pasaría inadvertido: el mismo silencio que esta fase viene a cerrar.
   *  2. El parámetro sólo viaja BAJO CONDICIÓN. Por eso recibe también el estado
   *     de su máquina: `remanenceParams` sólo entra en el paquete si está
   *     `enabled`, y sin esto mover el Q con la remanencia apagada acusaría al
   *     usuario de haber cambiado algo que no salió del navegador. Un aviso que
   *     salta cuando no pasa nada se aprende a ignorar, y entonces deja de
   *     avisar cuando sí pasa. */
  huella?: (valor: V, estado: S) => unknown;
}

/** Declaración parcial sobre una máquina: sólo las claves que invalidan. */
type Declaracion<S> = { [K in keyof S]?: DescriptorInvalidacion<S[K], S> };

/** Identidad estable de un `File`: dos ficheros distintos no colisionan, y el
 *  mismo fichero re-seleccionado tampoco cuenta como cambio. */
const huellaDeArchivo = (f: File | null) =>
  f ? `${f.name}:${f.size}:${f.lastModified}` : null;

// ═══════════════════════════════════════════════════════════════════════════
// 1. CONTEXTO — lo que el usuario declara sobre el survey
// ═══════════════════════════════════════════════════════════════════════════

export const CONTEXTO_INVALIDA = {
  gravimeterType: { motivo: "→ `config.gravimeter_type`: fija el σ del instrumento, y con él el peso de los datos." },
  utmZone: { motivo: "→ `config.utm_zone`: decide la proyección con la que se georreferencian las estaciones." },
  inclinationDeg: { motivo: "→ `config.inclination_deg`: es el campo inductor del kernel magnético." },
  declinationDeg: { motivo: "→ `config.declination_deg`: ídem. La Fase 18 midió que una D mal puesta descorrelaciona la anomalía." },
  fieldIntensityNt: { motivo: "→ `config.field_intensity_nt`: escala la magnetización inducida." },
  suscMin: { motivo: "→ `config.susc_min`: bound inferior de susceptibilidad; la Fase 20 midió que un bound clava celdas." },
  suscMax: { motivo: "→ `config.susc_max`: bound superior de susceptibilidad." },
} satisfies Declaracion<ContextoState>;

export const CONTEXTO_NO_INVALIDA: Record<
  Exclude<keyof ContextoState, keyof typeof CONTEXTO_INVALIDA>,
  string
> = {
  expectedRock:
    "No viaja en el paquete. Es contexto para INTERPRETAR (y para el ruteo del combo multimodal), " +
    "no una entrada del solver: cambiarlo no cambia una sola celda del modelo ya calculado.",
  expectedDepth: "Ídem `expectedRock`: guía la lectura del resultado, no lo produce.",
  dataType:
    "Espejo de qué archivo se cargó (`ARCHIVO_GRAVIMETRIA_CARGADO` lo fija). No lo elige el usuario y " +
    "no viaja: el tipo del paquete lo decide `handleGeneratePackage` mirando qué ficheros hay. Además " +
    "todo cambio de archivo pasa por `resetOnFileChange()`, que BORRA la corrida — no hay resultado que marcar.",
};

// ═══════════════════════════════════════════════════════════════════════════
// 2. PARÁMETROS — las perillas de la inversión
// ═══════════════════════════════════════════════════════════════════════════

export const PARAMETROS_INVALIDA = {
  densityMin: { motivo: "→ `config.density_min`. La Fase 20 midió que 2 de 3 presets clavan el 76,20 % de las celdas contra este bound." },
  densityMax: { motivo: "→ `config.density_max`." },
  lambdaMode: { motivo: "→ `config.lambda_mag`: en `auto` va 0 y el backend elige (Morozov u operating-point); en `custom` manda el número." },
  lambdaCustom: { motivo: "→ `config.lambda_mag` cuando el modo es `custom`. Es la palanca de profundidad medida en el punto 4." },
  paddingKappaLog: { motivo: "→ `config.padding_kappa` (10^valor): peso del anillo de padding." },
  anchorKappaLog: { motivo: "→ `config.anchor_kappa` (10^valor): peso del anclaje por sondajes." },
  autoKappa: { motivo: "→ `config.auto_kappa`: deja que el backend elija las kappas e ignora las dos de arriba." },
  enableDepthPrior: { motivo: "→ `config.enable_depth_prior`: prohíbe contraste somero. Default OFF; encenderlo cambia el resultado." },
  strict: { motivo: "→ query `strict` de /build-package: decide si un CSV con avisos entra o se rechaza." },
  allowGRaw: { motivo: "→ query `allow_g_raw`: admite gravedad cruda sin reducir. Cambia qué dato entra al motor." },
  acknowledgeSpatialRisk: {
    motivo:
      "→ `config.acknowledge_spatial_risk`. AUSENTE de la lista vieja. Es un gate del backend: " +
      "sin él, una geometría de riesgo se rechaza; con él, entra. Dos paquetes que sólo difieren " +
      "en esta casilla no son el mismo paquete.",
  },
  acknowledgeRegionalScale: {
    motivo: "→ `config.acknowledge_regional_scale`. AUSENTE de la lista vieja; mismo caso que el anterior.",
  },
} satisfies Declaracion<ParametrosState>;

export const PARAMETROS_NO_INVALIDA: Record<
  Exclude<keyof ParametrosState, keyof typeof PARAMETROS_INVALIDA>,
  string
> = {
  previewLimit:
    "Cuántas filas se pintan en la tabla de vista previa. No sale del navegador: no aparece en " +
    "`BuildPackageConfig` ni en la query de /build-package.",
  showAdvancedKappas:
    "Abrir y cerrar una sección de la interfaz. Si esto marcara el resultado como desactualizado, " +
    "desplegar un panel para MIRAR las kappas sin tocarlas acusaría al usuario de haberlas cambiado.",
  densityPreset:
    "No viaja: `PRESET_DENSIDAD` mueve `densityMin`/`densityMax`, y son ESAS dos las que van al " +
    "paquete y las que están declaradas arriba. Declararlo además contaría dos veces el mismo " +
    "cambio, y encima marcaría el caso `custom`, que no toca los bounds.",
};

// ═══════════════════════════════════════════════════════════════════════════
// 3. AVANZADO — modales y lo que traen de vuelta
// ═══════════════════════════════════════════════════════════════════════════

export const AVANZADO_INVALIDA = {
  pgiParams: {
    motivo:
      "→ `config.pgi_params`: el prior petrofísico gaussiano entra en el funcional. Sólo viaja " +
      "si `enabled`, y la huella lo respeta: tocar `alpha_pgi` con el PGI apagado no sale del navegador.",
    huella: (p: AvanzadoState["pgiParams"]) => (p?.enabled ? p : null),
  },
  remanenceParams: {
    motivo:
      "→ `config.remanence`: cambia el modelo directo magnético (Q, inc/dec remanente, modo). " +
      "Sólo viaja si `enabled`; la huella lo respeta. Queda un residuo MEDIDO y no cerrado: el " +
      "paquete además exige `pkgDataType === 'magnetic'`, que depende de qué ficheros hay y no de " +
      "esta máquina, así que con gravimetría sola un cambio de remanencia sigue marcando de más. " +
      "Marcar de más avisa sin motivo; marcar de menos calla con motivo. Se deja del lado seguro.",
    huella: (r: AvanzadoState["remanenceParams"]) => (r?.enabled ? r : null),
  },
  implicitGeologyParams: {
    motivo:
      "→ `config.implicit_geology` (FASE 14). **El que el plan nombra.** El prior geológico implícito " +
      "mueve el `m_ref` del smallness: la Fase 14 midió que ahí gana 25/25 y que una geología FALSA " +
      "pasa a ser el peor brazo. Cambiarlo tras invertir cambia la solución y no marcaba nada.",
  },
  correctedFile: {
    motivo:
      "Es el fichero PRIMARIO del paquete (`correctedFile ?? file`) y además fuerza `allow_g_raw`. " +
      "AUSENTE de la lista vieja, y es el hueco más caro: cambiar de archivo sí avisa " +
      "(`resetOnFileChange()` → `clearActiveRun()`), pero `CORRECCIONES_APLICADAS` no pasa por ahí.",
    huella: huellaDeArchivo,
  },
} satisfies Declaracion<AvanzadoState>;

export const AVANZADO_NO_INVALIDA: Record<
  Exclude<keyof AvanzadoState, keyof typeof AVANZADO_INVALIDA>,
  string
> = {
  showCorrectionWizard:
    "Booleano de ventana. Y no es sólo que no viaje: `despertarPreparacion()` lo apaga al volver a " +
    "la pestaña, así que si contara, VISITAR la pestaña marcaría el resultado como desactualizado.",
  showPgiModal: "Ídem: booleano de ventana, y `despertarPreparacion()` lo apaga al volver.",
  showRemanenceModal: "Ídem.",
  showImplicitGeologyModal: "Ídem.",
  correctionReport:
    "Reporte que DESCRIBE lo que el backend hizo sobre `correctedFile`; no viaja en el paquete. " +
    "Quien cambia el dato es el fichero, y ése sí está declarado arriba.",
};

// ═══════════════════════════════════════════════════════════════════════════
// 4. ENRIQUECER — el flujo PRINCIPAL, que no tenía huella NINGUNA
// ═══════════════════════════════════════════════════════════════════════════
//
// MEDIDO al abrir esta fase, y no estaba en la ficha: `markResultStale()` tenía
// UN solo llamador en todo el frontend (`PrepPanel.tsx`) y `PrepEnrichPanel` no
// era ninguno. Es decir, el aviso de «resultado desactualizado» cubría el flujo
// CLÁSICO —el que vive colapsado bajo «Avanzado»— y no cubría el flujo por el que
// entra el usuario. Seis de sus campos viajan al backend en cada generación.
//
// Cerrar H-36 sólo en `PrepPanel` habría dejado el tipo exhaustivo sobre la mitad
// que casi nadie toca. Va aquí porque es el mismo defecto y la misma máquina de
// declararlo, no porque sea un extra.

export const ENRIQUECER_INVALIDA = {
  utmZone: { motivo: "→ `config.utm_zone` de /enrich-package: la proyección con la que se georreferencian las estaciones." },
  gravimeterType: { motivo: "→ `config.gravimeter_type`: fija el σ del instrumento." },
  surveyDate: {
    motivo:
      "→ `config.survey_date`: el backend deriva de ella el IGRF-14 offline. Es el ÚNICO sitio del " +
      "frontend que la envía, y cambiar el año cambia el campo inductor con el que se invierte.",
  },
  useHelmert: { motivo: "Decide si los puntos de control se serializan: apagarlo retira la transformada Helmert del paquete." },
  ctrlPoints: {
    motivo:
      "→ `helmert_control_points_json`: fija la georreferenciación de coordenadas locales, o sea " +
      "DÓNDE queda el cuerpo. Sólo viaja con `useHelmert`, y la huella lo respeta.",
    huella: (p: EnriquecerState["ctrlPoints"], e: EnriquecerState) => (e.useHelmert ? p : null),
  },
  columnMap: {
    motivo:
      "→ `column_map_json`: decide QUÉ COLUMNA cumple cada rol físico. Es lo que la Fase 16 cerró " +
      "(un `X,Y,Z` mandaba el northing a profundidad): re-mapear un rol tras invertir cambia el " +
      "significado de cada fila del CSV, que es el cambio más grande que se puede hacer sin tocar el fichero.",
  },
} satisfies Declaracion<EnriquecerState>;

export const ENRIQUECER_NO_INVALIDA: Record<
  Exclude<keyof EnriquecerState, keyof typeof ENRIQUECER_INVALIDA>,
  string
> = {
  gravFile:
    "Cambiar de archivo no deja un resultado viejo: lo BORRA. `onSourceFileChange` llama a " +
    "`clearActiveRun()` (FASE 24) además de caducar el plan de mapeo. Mismo caso que `fileGravimetry`.",
  magFile: "Ídem `gravFile`: mismo `onSourceFileChange`, mismo `clearActiveRun()`.",
  loading: "Bandera de vuelo. Y `despertarPreparacion()` la apaga al volver a la pestaña: si contara, visitar la pestaña marcaría el resultado.",
  error: "Mensaje de un intento abandonado. Mismo caso: `despertarPreparacion()` lo borra al volver.",
  mapRoomLoading: "Bandera de vuelo de la sala de mapas.",
  mapRoomError: "Error de la sala de mapas; `despertarPreparacion()` lo borra al volver.",
  mappingPlan:
    "RESPUESTA del backend describiendo el CSV, no una decisión del usuario. Lo que el usuario " +
    "decide sobre él es `columnMap`, y ése sí está declarado arriba.",
  sniffReport: "Respuesta del backend (encoding/separador/decimal detectados). Es evidencia que se muestra, no una entrada.",
  sampleRows: "Filas de muestra ya parseadas, para el preview. No salen del navegador.",
  mapRoomStations: "Estaciones cargadas bajo demanda para la vista regional-residual. Derivadas del mismo CSV; no viajan en el paquete.",
  result:
    "El paquete YA generado. Es la SALIDA de esta máquina, no una entrada: marcar el resultado como " +
    "desactualizado porque se produjo un paquete nuevo confundiría las dos direcciones del flujo.",
};

// ═══════════════════════════════════════════════════════════════════════════
// 5. LO QUE PREPPANEL LEE DEL STORE Y NO ES NINGUNA DE LAS CUATRO MÁQUINAS
// ═══════════════════════════════════════════════════════════════════════════
//
// El límite está declarado a propósito y no es «todo `AppState`»: el complemento
// exacto sobre el store entero ya existe y es `NO_DESHACIBLE` (Fase 13), que
// clasifica sus ~120 campos y cuyas secciones (e)/(f)/(g) muestran que el resto
// son perillas del VISOR — pintan un modelo ya calculado y no pueden cambiar el
// paquete con el que se calculó. Aquí se cubre exactamente la rodaja que
// `PrepPanel` lee para armar el paquete, y se cubre ENTERA.
//
// `Pick` sobre `AppState` y no una interfaz a mano: si el store renombra uno de
// estos campos, esto deja de compilar en vez de quedarse mirando a un nombre muerto.

export type EntradasDeStore = Pick<
  AppState,
  "latNorth" | "latSouth" | "lonEast" | "lonWest" | "fileGravimetry" | "fileMagnetometry" | "prepSondajes"
>;

export const STORE_INVALIDA = {
  latNorth: { motivo: "→ `config.lat`. Viaja tal cual." },
  lonWest: { motivo: "→ `config.lon`. Viaja tal cual." },
  latSouth: {
    motivo:
      "No viaja suelto, pero es la otra mitad de UNA declaración: `validateCoords()` exige las " +
      "cuatro esquinas o ninguna, y la caja que el usuario declaró es lo que decide si el paquete " +
      "se genera. Se declara para que la caja sea atómica — media caja cambiada es una caja distinta.",
  },
  lonEast: { motivo: "Ídem `latSouth`: la otra mitad de la misma caja." },
  prepSondajes: {
    motivo:
      "→ `boreholes_json` (`buildPackage` lo anexa si hay intervalos). AUSENTE de la lista vieja. " +
      "Son el ANCLAJE de la inversión y además la fuente de las litologías del prior implícito: " +
      "confirmar otro survey de sondajes cambia el paquete entero. Va SIN `huella` a propósito: " +
      "contar intervalos sería más barato y estaría mal, porque el caso interesante es justo " +
      "re-subir el mismo sondaje con densidades o litologías corregidas — mismo número de filas, " +
      "otro anclaje y otro prior. Son objetos planos, así que se comparan enteros.",
  },
} satisfies Declaracion<EntradasDeStore>;

export const STORE_NO_INVALIDA: Record<
  Exclude<keyof EntradasDeStore, keyof typeof STORE_INVALIDA>,
  string
> = {
  fileGravimetry:
    "Cambiar de archivo NO deja un resultado desactualizado: lo BORRA. `handleFileGravimetryChange` " +
    "llama a `resetOnFileChange()`, que llama a `clearActiveRun()` (H-28) y se lleva modelo y corrida. " +
    "Marcarlo aquí sería avisar de que está viejo algo que ya no está en pantalla.",
  fileMagnetometry: "Ídem `fileGravimetry`: mismo camino, mismo `resetOnFileChange()`.",
};

// ═══════════════════════════════════════════════════════════════════════════
// 6. LA HUELLA — construida DESDE la declaración, nunca escrita aparte
// ═══════════════════════════════════════════════════════════════════════════

/** Vista sin genéricos de una declaración, para recorrerla en tiempo de ejecución.
 *  `never` en el parámetro es lo que la hace aceptar cualquier `huella` concreta
 *  con `strictFunctionTypes` (contravarianza). */
type DeclaracionOpaca = Record<
  string,
  { motivo: string; huella?: (valor: never, estado: never) => unknown }
>;

function paresDe(
  prefijo: string,
  declaracion: DeclaracionOpaca,
  estado: object,
): [string, unknown][] {
  // Claves ORDENADAS: la huella no puede depender del orden en que se escribió
  // la declaración, o reordenar comentarios marcaría resultados como viejos.
  return Object.keys(declaracion)
    .sort()
    .map((clave) => {
      const descriptor = declaracion[clave];
      const valor = (estado as Record<string, unknown>)[clave];
      const huella = descriptor.huella as
        | ((v: unknown, e: unknown) => unknown)
        | undefined;
      return [`${prefijo}.${clave}`, huella ? huella(valor, estado) : valor];
    });
}

/** Cadena estable que cambia si —y sólo si— cambió algo declarado como
 *  invalidante. `PrepPanel` la compara contra la anterior y, si difiere, llama a
 *  `markResultStale()`. */
export function huellaDeInvalidacion(entradas: {
  contexto: ContextoState;
  parametros: ParametrosState;
  avanzado: AvanzadoState;
  enriquecer: EnriquecerState;
  store: EntradasDeStore;
}): string {
  return JSON.stringify([
    ...paresDe("contexto", CONTEXTO_INVALIDA, entradas.contexto),
    ...paresDe("parametros", PARAMETROS_INVALIDA, entradas.parametros),
    ...paresDe("avanzado", AVANZADO_INVALIDA, entradas.avanzado),
    ...paresDe("enriquecer", ENRIQUECER_INVALIDA, entradas.enriquecer),
    ...paresDe("store", STORE_INVALIDA, entradas.store),
  ]);
}

/** Cuántos parámetros invalidan el resultado. Lo lee el test de la fase: un
 *  número que baja sin que nadie lo note es cómo se abrió H-36. */
export const N_PARAMETROS_INVALIDANTES =
  Object.keys(CONTEXTO_INVALIDA).length +
  Object.keys(PARAMETROS_INVALIDA).length +
  Object.keys(AVANZADO_INVALIDA).length +
  Object.keys(ENRIQUECER_INVALIDA).length +
  Object.keys(STORE_INVALIDA).length;
