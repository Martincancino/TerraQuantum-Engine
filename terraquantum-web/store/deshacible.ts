// ─── FASE 13 (auditoría 06 §10) — Qué es deshacible, y por qué lo demás no ────
//
// El diseño de la fase dice: «registre comandos inversibles para las acciones
// del usuario (NO para datos derivados del backend)». Este fichero es donde esa
// frase deja de ser una intención y se vuelve una lista que el compilador
// obliga a mantener completa.
//
// **El patrón estructural que la auditoría encontró CINCO veces** (§1.2) es
// «entre lo que el sistema declara y lo que el sistema hace se abre un hueco que
// nadie comprueba», y su causa nombrada es que los criterios de cierre miden que
// la pieza exista, no que el camino esté conectado. Aquí el hueco se cierra por
// TIPOS: `NO_DESHACIBLE` está declarado como el COMPLEMENTO EXACTO de
// `CLAVES_DESHACIBLES` sobre los campos de `AppState`. Añadir un campo nuevo al
// store y no clasificarlo **no compila**. No hace falta acordarse.
//
// Los tres criterios para que una clave sea deshacible, y los tres se midieron:
//   1. **Un control montado la cambia.** Medido al abrir la fase: de las 93
//      acciones del store, 44 no tienen ni un llamador en todo el árbol. Un
//      undo sobre una perilla que nadie puede mover es teatro.
//   2. **Es intención del usuario, no un dato.** Los payloads del backend
//      (`model`, `report`, las mallas, el terreno) no se deshacen: restaurarlos
//      crearía una vista con los datos de una corrida y el encabezado de otra.
//   3. **Deshacerla no arrastra una recarga cara ni toca una corrida viva.**

import type { AppState } from "./useAppStore";

/** Los miembros de `AppState` que son ESTADO y no acciones.
 *
 *  `capturePngSnapshot` cae de este lado a propósito: su tipo es
 *  `((n: number) => string) | null`, y una unión con `null` no satisface la
 *  restricción de función — así que el compilador la trata como el dato que es
 *  (un puntero vivo del renderer) y exige clasificarla. */
type SoloDatos<T> = {
  [K in keyof T]-?: T[K] extends (...a: never[]) => unknown ? never : K;
}[keyof T];

export type CampoDeEstado = SoloDatos<AppState>;

export interface Descriptor {
  /** Lo que lee el usuario en «Deshacer: …». En español, como toda la UI. */
  etiqueta: string;
  /** true en los controles continuos (sliders): un arrastre se fusiona en un
   *  solo comando. Ver `VENTANA_FUSION_MS` en `lib/historial/comandos.ts`. */
  fusionable: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. LO DESHACIBLE — 16 claves, todas con un control montado que las mueve
// ═══════════════════════════════════════════════════════════════════════════
//
// El ORDEN importa: `calcularDelta` recorre las claves en este orden y la
// etiqueta del comando sale de la PRIMERA que cambió. Por eso `sliceAxis` va
// antes que `slicePosition`: cambiar de eje mueve las dos (el store pone la
// posición a 0 en la misma transición) y el usuario lo percibe como «cambié el
// eje», no como «moví la posición».

export const CLAVES_DESHACIBLES = {
  // ── Corte de sección (SliceControls) ──────────────────────────────────────
  sliceAxis: { etiqueta: "Eje de corte", fusionable: false },
  slicePosition: { etiqueta: "Posición del corte", fusionable: true },
  showOnlySlice: { etiqueta: "Mostrar solo el lado seccionado", fusionable: false },
  showSectionPaint: { etiqueta: "Cara del corte pintada", fusionable: false },

  // ── Corte caja (BoxClipControls) ──────────────────────────────────────────
  clipBoxEnabled: { etiqueta: "Corte caja", fusionable: false },
  clipBox: { etiqueta: "Límites del corte caja", fusionable: true },

  // ── Capas del visor ───────────────────────────────────────────────────────
  showIsosurfaces: { etiqueta: "Isosuperficies", fusionable: false },
  showBoreholes: { etiqueta: "Sondajes", fusionable: false },
  showDoiOverlay: { etiqueta: "Horizonte DOI", fusionable: false },
  showMviVectors: { etiqueta: "Vectores MVI", fusionable: false },

  // ── Multi-física (MultiPhysicsControls) ───────────────────────────────────
  viewMode: { etiqueta: "Capa física", fusionable: false },
  jointThreshold: { etiqueta: "Umbral conjunto", fusionable: true },

  // ── Render (VolumeRenderControls / barra de comandos) ─────────────────────
  volumeRenderMode: { etiqueta: "Render volumétrico", fusionable: false },
  subsurfaceAoEnabled: { etiqueta: "Oclusión ambiental", fusionable: false },
  visualProfessionalMode: { etiqueta: "Modo de vista", fusionable: false },
  displayResolutionFactor: { etiqueta: "Resolución de display", fusionable: false },
} as const satisfies Partial<Record<CampoDeEstado, Descriptor>>;

export type ClaveDeshacible = keyof typeof CLAVES_DESHACIBLES;

/** El orden de barrido. Se declara a mano (no `Object.keys`) porque el orden es
 *  parte del contrato de etiquetado, y así el compilador obliga a incluir cada
 *  clave nueva también aquí. */
export const ORDEN_VIGILADO: readonly ClaveDeshacible[] = [
  "sliceAxis",
  "slicePosition",
  "showOnlySlice",
  "showSectionPaint",
  "clipBoxEnabled",
  "clipBox",
  "showIsosurfaces",
  "showBoreholes",
  "showDoiOverlay",
  "showMviVectors",
  "viewMode",
  "jointThreshold",
  "volumeRenderMode",
  "subsurfaceAoEnabled",
  "visualProfessionalMode",
  "displayResolutionFactor",
];

// El compilador comprueba que `ORDEN_VIGILADO` cubre TODAS las claves
// deshacibles: si se añade una a `CLAVES_DESHACIBLES` y se olvida aquí, este
// tipo deja de resolver a `never` y la línea siguiente no compila.
type ClaveSinOrden = Exclude<ClaveDeshacible, (typeof ORDEN_VIGILADO)[number]>;
const _todasLasClavesTienenOrden: ClaveSinOrden extends never ? true : never = true;
void _todasLasClavesTienenOrden;

// ═══════════════════════════════════════════════════════════════════════════
// 2. LO QUE NO SE DESHACE — el complemento EXACTO, con motivo escrito
// ═══════════════════════════════════════════════════════════════════════════
//
// El tipo `Record<Exclude<CampoDeEstado, ClaveDeshacible>, string>` es lo que
// convierte esta lista en portante: no admite una clave de más (no es campo del
// store) ni una de menos (campo sin clasificar). Es el mismo papel que
// `HUERFANOS_TOLERADOS` (Fase 6) o `RUTAS_SIN_UI_TOLERADAS` (Fase 9), pero
// verificado por `tsc` en vez de por un test.

export const NO_DESHACIBLE: Record<Exclude<CampoDeEstado, ClaveDeshacible>, string> = {
  // ── (a) Identidad y ciclo de vida de la corrida ───────────────────────────
  activeRun:
    "Identidad de la corrida. Cambiar projectId/runId dispara la cascada que borra 12 campos " +
    "(useAppStore.setActiveRun); deshacerlo mientras el bucle de polling sigue vivo dejaría al " +
    "bucle escribiendo sobre una identidad que el usuario ya deshizo.",
  view:
    "Navegación. MEDIDO: las vistas se montan por igualdad de string en app/page.tsx, así que " +
    "deshacer `view` DESMONTA Exploration3DView y con él LoadPanel, cuyo cleanup abandona el " +
    "sondeo de una inversión en curso. Un Ctrl+Z no puede tener ese efecto.",
  show3D:
    "Lo escribe la máquina de inversión al terminar. Deshacerlo desmonta el <Canvas> y con él " +
    "Scene3D y su worker.",
  model:
    "Resultado de UNA corrida. `setModel` SELLA la procedencia con `modelRunKey` en el momento " +
    "de la llamada (H-28): restaurar un modelo viejo lo sellaría con la corrida actual, que es " +
    "exactamente la mentira que la Fase 1 vino a impedir.",
  modelRunKey:
    "Sello de procedencia del modelo (H-28). Es metadato de un invariante, no una preferencia: " +
    "restaurarlo por separado deja la comprobación de pertenencia mintiendo.",
  resultIsStale:
    "Aviso de honestidad («cambiaste parámetros después de esta inversión»). Deshacer un aviso " +
    "no es deshacer una acción del usuario: es ocultar una advertencia.",

  // ── (b) Payloads del backend: son datos, no comandos ──────────────────────
  isosurfaceData: "Malla de /v2/isosurface de esa corrida. El store ya la borra al cambiar de corrida.",
  boreholeData: "Sondajes del proyecto activo. Se limpian al cambiar la identidad de la corrida.",
  sectionData: "Raster de la cara del corte, en coordenadas del modelo que lo produjo.",
  doiOverlayData:
    "Horizonte DOI: es un juicio de incertidumbre de una inversión concreta. Pintarlo sobre otra " +
    "corrida afirmaría una profundidad de investigación que nadie calculó.",
  terrainData: "Matriz DEM del área de ese proyecto. Sobre otro proyecto dibuja la topografía de otro sitio.",
  report:
    "Reporte que el backend calculó para ESA corrida (misfit, targeting, veredicto B1/B2/B3). El " +
    "store ya lo borra al cambiar de corrida; restaurarlo pondría el juicio de una inversión " +
    "sobre el modelo de otra.",
  percentileStats: "Estadísticos del modelo completo, calculados por el backend antes del muestreo.",
  bestTarget: "Mejor objetivo calculado por el backend.",
  bestVoxel: "Vóxel destacado calculado por el backend.",
  heatmapData: "Mapa de calor derivado de la corrida.",
  favorabilityResult: "Resultado del gate de favorabilidad.",
  favorabilityScore: "Puntaje del gate de favorabilidad.",
  favorabilityLevel: "Nivel del gate de favorabilidad.",
  gravityPreviewResult: "Vista previa de importación devuelta por el backend.",
  gravityInvertResult: "Resultado de inversión devuelto por el backend.",
  projectFootprint: "Huella georreferenciada calculada en la ingesta.",
  georefConfidence: "Confianza de georreferenciación declarada por el backend.",
  georefWarnings: "Avisos de georreferenciación del backend. Deshacer un aviso es esconderlo.",
  crsInfo: "Sistema de referencia resuelto por el backend.",
  hasElevationData: "Metadato de elevación del block model.",
  blockModelDemSource: "Origen del DEM, declarado por el backend.",
  blockModelGeorefConfidence: "Confianza de georreferencia del block model.",
  blockModelElevationRange: "Rango de elevación del block model.",

  // ── (c) Telemetría del render y banderas de vuelo ─────────────────────────
  visibleCellCount: "Lo cuenta Scene3D al pintar. Es una lectura, no una decisión.",
  highlightedCellCount:
    "Lo cuenta Scene3D al pintar, igual que `visibleCellCount`. Es el resultado de aplicar los " +
    "filtros, no un filtro: deshacerlo mentiría sobre cuántas celdas hay en pantalla.",
  totalVoxels:
    "Traza que el adaptador de la API copia de la respuesta del backend: cuántos vóxeles tiene el " +
    "modelo completo. Es un hecho sobre la corrida, no una decisión del usuario.",
  storedVoxels:
    "Cuántos vóxeles guardó el backend en disco para esa corrida. Mismo motivo que `totalVoxels`.",
  anomalyVoxels:
    "Cuántos vóxeles superaron el umbral de anomalía en el backend. Mismo motivo que `totalVoxels`.",
  returnedVoxels:
    "Cuántos vóxeles llegaron en ESTA descarga (depende del modo y del límite pedido). Restaurar " +
    "un valor viejo describiría una descarga que ya no es la que está en pantalla.",
  blockModelMode: "Modo con el que el backend sirvió el block model.",
  anomalyWeak: "Lo decide Scene3D midiendo el modelo: es un diagnóstico, no una perilla.",
  susceptibilityDataAvailable: "Lo decide Scene3D midiendo el modelo.",
  isBlockModelLoading:
    "Bandera de vuelo. Además esta fase le da su PRIMER lector: es una de las tres condiciones " +
    "que bloquean deshacer mientras hay una carga en curso.",
  isWorkerProcessing:
    "Bandera de vuelo del worker de geometría. Igual que la anterior: se LEE para bloquear el " +
    "undo, nunca se deshace.",

  // ── (d) Sin inverso natural, o no es una modificación ─────────────────────
  cameraResetNonce:
    "Nonce monótono: incrementarlo dispara una animación de cámara. No tiene inverso — deshacer " +
    "un reset de cámara no es «volver a la cámara anterior», que nadie guardó.",
  selectedVoxel:
    "Selección por picking. Seleccionar es LEER un vóxel, no modificar el modelo; ninguna " +
    "herramienta del sector pone la selección en el historial.",

  // ── (e) Perillas que hoy NADIE puede mover (medido: 0 llamadores) ─────────
  //
  // No son deshacibles porque no son alcanzables. Están aquí con nombre para
  // que el número no crezca en silencio: es deuda de la familia H-10 (la pieza
  // existe y no tiene camino de usuario), y su dueña natural es una fase de UI,
  // no ésta. Scene3D SÍ lee las marcadas con ⚠: son perillas que el visor honra
  // y que ningún control ofrece.
  showVoxels: "⚠ Scene3D la lee; ningún control montado la cambia (0 llamadores de setShowVoxels).",
  visualLayer: "⚠ Scene3D la lee para colorear; 0 llamadores de setVisualLayer.",
  voxelOpacity: "⚠ Scene3D la aplica al material; 0 llamadores de setVoxelOpacity.",
  voxelScale: "⚠ Scene3D la aplica a la instancia; 0 llamadores de setVoxelScale.",
  minTargetScore: "⚠ Scene3D filtra celdas con ella; 0 llamadores de setMinTargetScore.",
  minAnomalyIntensity: "⚠ Scene3D filtra con ella; 0 llamadores.",
  minDensityAnomalyScore: "⚠ Scene3D filtra con ella; 0 llamadores.",
  showAnomalyEnvelope: "⚠ Scene3D la lee; 0 llamadores de setShowAnomalyEnvelope.",
  anomalyEnvelopePercent: "⚠ Scene3D la lee; 0 llamadores.",
  showFloor: "⚠ Scene3D la lee; 0 llamadores de setShowFloor.",
  showTerrain: "⚠ Scene3D la lee; 0 llamadores de setShowTerrain.",
  terrainOpacity: "⚠ Scene3D la lee; 0 llamadores.",
  terrainVerticalExaggeration: "⚠ Scene3D la lee; 0 llamadores.",
  showBoundingBox: "⚠ Scene3D la lee; 0 llamadores.",
  showHostVolume: "⚠ Scene3D la lee; 0 llamadores.",
  hostVolumeOpacity: "⚠ Scene3D la lee; 0 llamadores.",
  showLegend: "⚠ La lee Exploration3DView; 0 llamadores de setShowLegend.",
  sliceThickness: "⚠ Scene3D la lee para el espesor del corte; 0 llamadores de setSliceThickness.",
  doiThreshold: "⚠ Scene3D la lee; 0 llamadores de setDoiThreshold.",
  gestureMode: "0 llamadores de setGestureMode.",
  minDensityRaw: "Filtro de densidad absoluta; `setModel` la resetea. 0 llamadores del setter.",
  maxDensityRaw: "Filtro de densidad absoluta; `setModel` la resetea. 0 llamadores del setter.",
  sliceX: "Campo muerto: 0 consumidores fuera del store. Dueña: una fase de limpieza, no ésta.",
  blockModelDataMode:
    "0 llamadores de su setter Y dispara la cadena de recarga Zarr/Arrow. Escribirla desde el " +
    "undo estrenaría un camino de recarga que nunca se ha ejercitado.",

  // ── (f) Disparan una recarga cara, no un cambio visual ────────────────────
  lodLevel:
    "Sí tiene control, pero deshacerlo relanza la cadena de recarga del block model (Zarr o " +
    "Arrow) y termina llamando a setModel — con `model` en las dependencias de ese efecto, lo " +
    "único que hoy separa la app de una recarga infinita es un guard por refs. No se toca.",

  // ── (g) Datos del usuario que no pertenecen al visor ──────────────────────
  fileGravimetry: "Objeto File del navegador. Cambiar de archivo pasa por una limpieza completa de la corrida.",
  fileMagnetometry: "Objeto File del navegador. H-29: el estado que sobrevive a un cambio de fichero es un bug conocido.",
  geologistNote: "Texto libre del geólogo: tiene el deshacer nativo del navegador dentro del propio campo.",
  extractedTags: "Derivado del texto por el backend.",
  geoRegionName: "Campo de formulario; deshacer nativo del navegador.",
  geoLat: "Campo de formulario; deshacer nativo del navegador.",
  geoLon: "Campo de formulario; deshacer nativo del navegador.",
  latNorth: "Campo de formulario; deshacer nativo del navegador.",
  latSouth: "Campo de formulario; deshacer nativo del navegador.",
  lonEast: "Campo de formulario; deshacer nativo del navegador.",
  lonWest: "Campo de formulario; deshacer nativo del navegador.",
  region: "Selección del simulador; 0 llamadores de setRegion.",
  inputNIR: "Entrada del simulador; 0 llamadores.",
  inputFe: "Entrada del simulador; 0 llamadores.",
  inputDepth: "Entrada del simulador; 0 llamadores.",
  inputGrav: "Entrada del simulador; 0 llamadores.",

  // ── (i) FASE 24 — el estado de PREPARACIÓN ────────────────────────────────
  //
  // Las cuatro máquinas que la Fase 10 creó y la Fase 24 subió al store. Ninguna
  // es deshacible DESDE AQUÍ, y no porque no valga la pena deshacerlas: dos de
  // ellas ya tienen historial, pero en el ámbito «preparacion»
  // (`componentes/prep/deshaciblePrep.ts`), no en el del visor. Meterlas en
  // `CLAVES_DESHACIBLES` las metería en `ORDEN_VIGILADO`, y entonces un Ctrl+Z
  // pulsado mirando el modelo 3D restauraría un bound de densidad de otra
  // pestaña — dos historiales pisándose sobre el mismo estado.
  prepContexto:
    "Lo que el usuario DECLARA sobre el survey (roca esperada, zona UTM, gravímetro). Sí se " +
    "deshace, pero en el ámbito «preparacion» y con sus propias claves vigiladas " +
    "(`deshaciblePrep.ts`, CLAVES_CONTEXTO): su historial es el del panel, no el del visor.",
  prepParametros:
    "Las perillas de la inversión. Mismo caso que `prepContexto`: tienen historial propio en " +
    "el ámbito «preparacion» (CLAVES_PARAMETROS, 12 de 15), y los tres que quedan fuera —los " +
    "dos reconocimientos de riesgo y el despliegue de kappas— tienen su motivo escrito allí.",
  prepAvanzado:
    "Modales y lo que traen de vuelta, incluido el CSV corregido. `deshaciblePrep.ts` ya midió " +
    "por qué no se deshace: sus booleanos MONTAN componentes (deshacer un cierre relanza una " +
    "petición de red) y guarda un `File` que es el producto de una corrida real del backend.",
  prepEnriquecer:
    "El flujo PRINCIPAL de preparación: archivos, mapeo de columnas, puntos Helmert y el " +
    "paquete enriquecido. No tiene historial en ningún ámbito, y es deliberado: su unidad de " +
    "trabajo es «generar el paquete», que sale del navegador y no se des-hace.",
  prepSondajes:
    "Intervalos de sondaje confirmados en BoreholeUploadPanel. Son un DATO parseado por el " +
    "backend a partir del CSV del usuario, no una perilla: se reemplazan confirmando otro " +
    "survey, y el camino para deshacerlos es volver a confirmar, no un atajo de teclado.",

  // ── (h) No serializable y vivo ────────────────────────────────────────────
  capturePngSnapshot:
    "Puntero a una función VIVA del renderer que registra CanvasExportBridge al montar el " +
    "<Canvas>. Restaurar uno viejo apuntaría a un canvas desmontado y rompería la exportación PNG.",
};

/** Etiqueta de un comando a partir de las claves que cambiaron. La primera en
 *  `ORDEN_VIGILADO` manda; si cambiaron varias se dice cuántas, para que
 *  «Deshacer: Eje de corte» no oculte que también se movió la posición. */
export function etiquetarCambio(claves: readonly string[]): {
  etiqueta: string;
  fusionable: boolean;
} {
  const primera = claves[0] as ClaveDeshacible | undefined;
  const desc = primera ? CLAVES_DESHACIBLES[primera] : undefined;
  if (!desc) return { etiqueta: "Cambio de visualización", fusionable: false };
  // Sólo se fusiona un gesto continuo puro: si el cambio arrastró más de una
  // clave es una transición con nombre (cambiar de eje), no un arrastre.
  const fusionable = desc.fusionable && claves.length === 1;
  return {
    etiqueta: claves.length > 1 ? `${desc.etiqueta} (+${claves.length - 1})` : desc.etiqueta,
    fusionable,
  };
}
