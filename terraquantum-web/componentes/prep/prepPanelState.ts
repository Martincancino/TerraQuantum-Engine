// ─── FASE 10 (H-16) — El estado de `PrepPanel`, explícito y con transiciones ───
//
// **El número que originó esto:** 41 `useState` en un solo componente — el 24 %
// de todo el estado local del frontend en un archivo. Con 41 piezas
// independientes el número de combinaciones alcanzables no se puede razonar ni
// testear, y los bugs de este tipo de componente son siempre «en cierta
// secuencia de clics queda inconsistente».
//
// **Y no es hipotético en este archivo concreto.** H-29 fue exactamente eso: al
// cambiar el CSV de magnetometría, el manejador NO reseteaba los reconocimientos
// de riesgo, así que una casilla marcada entendiendo el riesgo del archivo A
// viajaba al backend como si el usuario hubiera aceptado el de la configuración
// nueva. La Fase 1 lo arregló extrayendo `resetOnFileChange()` — la solución
// correcta con las herramientas de entonces, pero sostenida por la disciplina de
// acordarse de llamarla.
//
// Aquí ese reset es UNA transición con nombre: `ARCHIVOS_CAMBIARON`. Ya no
// depende de que nadie lo olvide, porque no hay otra forma de mover ese estado.
//
// Los cuatro grupos NO son una partición estética: son cuatro cosas que cambian
// por motivos distintos.
//   · `operacion`  — lo que está pasando ahora (cargas, errores, mensajes).
//   · `contexto`   — lo que el usuario DECLARA sobre el survey.
//   · `parametros` — las perillas de la inversión, incluidos los reconocimientos.
//   · `avanzado`   — modales y lo que traen de vuelta.
//
// Regla de Oro: aquí no se calcula física. Son transiciones de interfaz.

import type { TQErrorView } from "../../lib/terraquantum/errorContract";
import type { GravityCorrectionReport } from "../../lib/terraquantum/frontendApi";
import type { MagneticRemanenceParamsUI } from "../MagneticRemanenceForm";
import type { PgiParamsUI } from "../PgiParamsForm";

export type CsvIssue = { type: "error" | "warning"; message: string };

export interface CsvValidationResult {
  status: "ok" | "warning" | "invalid";
  issues: CsvIssue[];
  n_sensors: number;
  can_invert: boolean;
}

export type DataType = "gravity" | "magnetic";
export type DensityPreset = "granite" | "magnetite" | "copper" | "custom";
export type LambdaMode = "auto" | "custom";

// ═══════════════════════════════════════════════════════════════════════════
// 1. OPERACIÓN — qué está pasando ahora mismo
// ═══════════════════════════════════════════════════════════════════════════

export type OperacionState = {
  loading: boolean;
  errorMsg: string | null;
  cleanCsvLoading: boolean;
  cleanCsvError: string | null;
  packageMessage: string | null;
  packageErrorView: TQErrorView | null;
  packageModalOpen: boolean;
  geoError: string | null;
  csvValidation: CsvValidationResult | null;
};

export const operacionInicial: OperacionState = {
  loading: false,
  errorMsg: null,
  cleanCsvLoading: false,
  cleanCsvError: null,
  packageMessage: null,
  packageErrorView: null,
  packageModalOpen: false,
  geoError: null,
  csvValidation: null,
};

export type OperacionAction =
  /** El usuario cambió un archivo: caduca TODO lo que describía al anterior. */
  | { type: "ARCHIVOS_CAMBIARON" }
  | { type: "VALIDACION_INICIADA" }
  | { type: "VALIDACION_FALLO"; mensaje: string }
  | { type: "VALIDACION_TERMINADA" }
  | { type: "ERROR_DESCARTADO" }
  | { type: "CSV_LIMPIO_INICIADO" }
  | { type: "CSV_LIMPIO_FALLO"; mensaje: string }
  | { type: "CSV_LIMPIO_TERMINADO" }
  | { type: "PAQUETE_INICIADO" }
  | { type: "PAQUETE_PROGRESO"; mensaje: string }
  | { type: "PAQUETE_TERMINADO"; mensaje: string }
  /** Error accionable del backend: abre el modal RESUMEN/DETALLES/ACCIÓN. */
  | { type: "PAQUETE_FALLO"; error: TQErrorView }
  | { type: "PAQUETE_ERROR_REABIERTO" }
  | { type: "PAQUETE_ERROR_CERRADO" }
  | { type: "COORDENADAS_INVALIDAS"; mensaje: string }
  | { type: "COORDENADAS_OK" }
  | { type: "CSV_VALIDADO_LOCALMENTE"; resultado: CsvValidationResult | null };

export function operacionReducer(
  estado: OperacionState,
  accion: OperacionAction,
): OperacionState {
  switch (accion.type) {
    case "ARCHIVOS_CAMBIARON":
      // H-29 vivía aquí. Un solo sitio, y no hay forma de olvidarse de la mitad.
      return {
        ...estado,
        errorMsg: null,
        packageMessage: null,
        packageErrorView: null,
        packageModalOpen: false,
        geoError: null,
      };
    case "VALIDACION_INICIADA":
      return {
        ...estado,
        loading: true,
        errorMsg: null,
        packageMessage: null,
        packageErrorView: null,
        packageModalOpen: false,
      };
    case "VALIDACION_FALLO":
      return { ...estado, loading: false, errorMsg: accion.mensaje };
    case "VALIDACION_TERMINADA":
      return { ...estado, loading: false };
    case "ERROR_DESCARTADO":
      return { ...estado, errorMsg: null };
    case "CSV_LIMPIO_INICIADO":
      return { ...estado, cleanCsvLoading: true, cleanCsvError: null };
    case "CSV_LIMPIO_FALLO":
      return { ...estado, cleanCsvLoading: false, cleanCsvError: accion.mensaje };
    case "CSV_LIMPIO_TERMINADO":
      return { ...estado, cleanCsvLoading: false };
    case "PAQUETE_INICIADO":
      return { ...estado, packageMessage: null, packageErrorView: null, packageModalOpen: false };
    case "PAQUETE_PROGRESO":
    case "PAQUETE_TERMINADO":
      return { ...estado, packageMessage: accion.mensaje };
    case "PAQUETE_FALLO":
      // El mensaje de progreso se borra: dejarlo junto al error contaría dos
      // historias distintas del mismo intento.
      return {
        ...estado,
        packageMessage: null,
        packageErrorView: accion.error,
        packageModalOpen: true,
      };
    case "PAQUETE_ERROR_REABIERTO":
      return { ...estado, packageModalOpen: true };
    case "PAQUETE_ERROR_CERRADO":
      return { ...estado, packageModalOpen: false };
    case "COORDENADAS_INVALIDAS":
      return { ...estado, geoError: accion.mensaje };
    case "COORDENADAS_OK":
      return { ...estado, geoError: null };
    case "CSV_VALIDADO_LOCALMENTE":
      return { ...estado, csvValidation: accion.resultado };
    default: {
      // Exhaustividad: si alguien añade una acción y olvida tratarla, esto no
      // compila. Es la mitad del valor de tener transiciones con nombre.
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. CONTEXTO — lo que el usuario declara sobre el survey
// ═══════════════════════════════════════════════════════════════════════════

export type ContextoState = {
  expectedRock: string;
  expectedDepth: string;
  dataType: DataType;
  /** Campo geomagnético inducido. Defaults del norte de Chile; el backend los
   *  valida. El frontend no calcula nada con ellos: los transporta. */
  inclinationDeg: number;
  declinationDeg: number;
  fieldIntensityNt: number;
  suscMin: string;
  suscMax: string;
  utmZone: string;
  gravimeterType: string;
};

export const contextoInicial: ContextoState = {
  expectedRock: "",
  expectedDepth: "",
  dataType: "gravity",
  inclinationDeg: -30,
  declinationDeg: 2,
  fieldIntensityNt: 23500,
  suscMin: "0.0",
  suscMax: "1.0",
  utmZone: "",
  gravimeterType: "unknown",
};

export type ContextoAction =
  | { type: "CAMPO"; campo: keyof ContextoState; valor: ContextoState[keyof ContextoState] }
  /** Subir un CSV de gravimetría fija el tipo Y limpia la zona UTM declarada:
   *  una zona es una afirmación sobre un archivo concreto. */
  | { type: "ARCHIVO_GRAVIMETRIA_CARGADO" }
  | { type: "ARCHIVO_MAGNETOMETRIA_CARGADO" };

export function contextoReducer(estado: ContextoState, accion: ContextoAction): ContextoState {
  switch (accion.type) {
    case "CAMPO":
      return { ...estado, [accion.campo]: accion.valor };
    case "ARCHIVO_GRAVIMETRIA_CARGADO":
      return { ...estado, dataType: "gravity", utmZone: "" };
    case "ARCHIVO_MAGNETOMETRIA_CARGADO":
      return { ...estado, dataType: "magnetic" };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. PARÁMETROS — las perillas de la inversión
// ═══════════════════════════════════════════════════════════════════════════

export type ParametrosState = {
  strict: boolean;
  allowGRaw: boolean;
  previewLimit: number;
  densityMin: string;
  densityMax: string;
  densityPreset: DensityPreset;
  lambdaMode: LambdaMode;
  lambdaCustom: string;
  showAdvancedKappas: boolean;
  /** Escala log10. `5` = 1e5. */
  paddingKappaLog: number;
  anchorKappaLog: number;
  autoKappa: boolean;
  enableDepthPrior: boolean;
  /** Reconocimientos de riesgo. SIEMPRE se refieren a un conjunto de archivos
   *  concreto: si el conjunto cambia, caducan (H-29). */
  acknowledgeSpatialRisk: boolean;
  acknowledgeRegionalScale: boolean;
};

export const parametrosInicial: ParametrosState = {
  strict: true,
  allowGRaw: false,
  previewLimit: 20,
  densityMin: "0.0",
  densityMax: "5.5",
  densityPreset: "custom",
  lambdaMode: "auto",
  lambdaCustom: "0.1",
  showAdvancedKappas: false,
  paddingKappaLog: 5,
  anchorKappaLog: 4,
  autoKappa: true,
  enableDepthPrior: false,
  acknowledgeSpatialRisk: false,
  acknowledgeRegionalScale: false,
};

/** Bounds por litología. Los números son del backend (`docs/05`), no del visor;
 *  aquí sólo se eligen. `custom` no toca los bounds: es «los pongo yo». */
const BOUNDS_POR_PRESET: Record<Exclude<DensityPreset, "custom">, [string, string]> = {
  granite: ["2.6", "3.0"],
  magnetite: ["4.5", "5.5"],
  copper: ["4.3", "4.8"],
};

export type ParametrosAction =
  | { type: "CAMPO"; campo: keyof ParametrosState; valor: ParametrosState[keyof ParametrosState] }
  /** Un preset mueve TRES piezas a la vez. Con `useState` eran tres llamadas que
   *  podían quedar a medias; aquí es atómico por construcción. */
  | { type: "PRESET_DENSIDAD"; preset: DensityPreset }
  | { type: "ARCHIVOS_CAMBIARON" };

export function parametrosReducer(
  estado: ParametrosState,
  accion: ParametrosAction,
): ParametrosState {
  switch (accion.type) {
    case "CAMPO":
      return { ...estado, [accion.campo]: accion.valor };
    case "PRESET_DENSIDAD": {
      if (accion.preset === "custom") return { ...estado, densityPreset: "custom" };
      const [min, max] = BOUNDS_POR_PRESET[accion.preset];
      return { ...estado, densityPreset: accion.preset, densityMin: min, densityMax: max };
    }
    case "ARCHIVOS_CAMBIARON":
      return { ...estado, acknowledgeSpatialRisk: false, acknowledgeRegionalScale: false };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. AVANZADO — modales y lo que traen de vuelta
// ═══════════════════════════════════════════════════════════════════════════

export type AvanzadoState = {
  showCorrectionWizard: boolean;
  /** El CSV que devuelve el asistente de correcciones, si se usó. Sustituye al
   *  original para la inversión, y por eso caduca con los archivos. */
  correctedFile: File | null;
  correctionReport: GravityCorrectionReport | null;
  showPgiModal: boolean;
  pgiParams: PgiParamsUI | null;
  showRemanenceModal: boolean;
  remanenceParams: MagneticRemanenceParamsUI | null;
};

export const avanzadoInicial: AvanzadoState = {
  showCorrectionWizard: false,
  correctedFile: null,
  correctionReport: null,
  showPgiModal: false,
  pgiParams: null,
  showRemanenceModal: false,
  remanenceParams: null,
};

export type AvanzadoAction =
  | { type: "ASISTENTE_CORRECCIONES_ABIERTO" }
  | { type: "ASISTENTE_CORRECCIONES_CERRADO" }
  /** El asistente terminó: entra el CSV corregido con su reporte, y se cierra. */
  | { type: "CORRECCIONES_APLICADAS"; archivo: File; reporte: GravityCorrectionReport | null }
  | { type: "MODAL_PGI"; abierto: boolean }
  | { type: "PGI_GUARDADO"; params: PgiParamsUI | null }
  | { type: "MODAL_REMANENCIA"; abierto: boolean }
  | { type: "REMANENCIA_GUARDADA"; params: MagneticRemanenceParamsUI | null }
  | { type: "ARCHIVOS_CAMBIARON" };

export function avanzadoReducer(estado: AvanzadoState, accion: AvanzadoAction): AvanzadoState {
  switch (accion.type) {
    case "ASISTENTE_CORRECCIONES_ABIERTO":
      return { ...estado, showCorrectionWizard: true };
    case "ASISTENTE_CORRECCIONES_CERRADO":
      return { ...estado, showCorrectionWizard: false };
    case "CORRECCIONES_APLICADAS":
      return {
        ...estado,
        correctedFile: accion.archivo,
        correctionReport: accion.reporte,
        showCorrectionWizard: false,
      };
    case "MODAL_PGI":
      return { ...estado, showPgiModal: accion.abierto };
    case "PGI_GUARDADO":
      return { ...estado, pgiParams: accion.params, showPgiModal: false };
    case "MODAL_REMANENCIA":
      return { ...estado, showRemanenceModal: accion.abierto };
    case "REMANENCIA_GUARDADA":
      return { ...estado, remanenceParams: accion.params, showRemanenceModal: false };
    case "ARCHIVOS_CAMBIARON":
      // El CSV corregido describe al archivo anterior: no puede sobrevivirlo.
      return {
        ...estado,
        correctedFile: null,
        correctionReport: null,
        showCorrectionWizard: false,
      };
    default: {
      const _exhaustivo: never = accion;
      return _exhaustivo;
    }
  }
}
