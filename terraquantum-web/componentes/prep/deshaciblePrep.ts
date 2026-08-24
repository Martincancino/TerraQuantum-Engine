// ─── FASE 13 (auditoría 06 §10) — Qué se deshace en el panel de preparación ───
//
// Mismo criterio que en el visor (`store/deshacible.ts`): sólo entra en el
// historial lo que es INTENCIÓN del usuario y cuyo efecto no ha salido ya del
// navegador. De las cuatro máquinas de la Fase 10, dos quedan enteras fuera y
// las otras dos entran parcialmente:
//
//   · `operacion`  — FUERA. Son banderas de vuelo (cargando, error, mensaje) y
//     resultados de red. MEDIDO: no hay un solo `AbortController` en los tres
//     paneles, así que deshacer un `loading: true → false` dejaría la interfaz
//     diciendo «listo» con una petición todavía abierta que despachará igual al
//     volver. Y sus mensajes de éxito describen cosas que ya ocurrieron FUERA
//     del navegador: el orden real al generar el paquete es `a.click()` —el
//     fichero ya está en el disco del usuario— y sólo después el mensaje.
//     Deshacer ese mensaje sería des-decir un hecho.
//
//   · `avanzado`   — FUERA. Sus booleanos MONTAN Y DESMONTAN componentes:
//     deshacer un cierre del asistente de correcciones lo re-monta y vuelve a
//     disparar su petición de arranque (un undo que toca la red sin que nadie lo
//     pida), y deshacer una apertura lo desmonta y DESTRUYE sus 16 campos de
//     estado — un deshacer que borra trabajo en vez de restaurarlo. Además
//     guarda un `File`, que no es un valor de interfaz sino el producto de una
//     corrida real del backend sobre todas las estaciones.
//
//   · `contexto`   — DENTRO, menos lo que no se puede mover o desincronizaría.
//   · `parametros` — DENTRO, menos los reconocimientos de riesgo.

import type { ContextoState, ParametrosState } from "./prepPanelState";

export interface DescriptorPrep {
  etiqueta: string;
  fusionable: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONTEXTO — lo que el usuario declara sobre el survey
// ═══════════════════════════════════════════════════════════════════════════

export const CONTEXTO_DESHACIBLE = {
  expectedRock: { etiqueta: "Roca esperada", fusionable: false },
  expectedDepth: { etiqueta: "Profundidad esperada", fusionable: false },
  utmZone: { etiqueta: "Zona UTM", fusionable: false },
  gravimeterType: { etiqueta: "Tipo de gravímetro", fusionable: false },
} as const satisfies Partial<Record<keyof ContextoState, DescriptorPrep>>;

export const CONTEXTO_NO_DESHACIBLE: Record<
  Exclude<keyof ContextoState, keyof typeof CONTEXTO_DESHACIBLE>,
  string
> = {
  dataType:
    "No lo elige el usuario: lo fija subir un archivo (ARCHIVO_GRAVIMETRIA_CARGADO / " +
    "ARCHIVO_MAGNETOMETRIA_CARGADO). Deshacerlo dejaría el tipo de dato diciendo una cosa y el " +
    "archivo cargado siendo otra — el estado a medias que la Fase 10 vino a matar.",
  inclinationDeg:
    "Constante disfrazada de estado: la Fase 10 midió que no tiene setter ni input en todo el " +
    "panel. No hay nada que deshacer porque no hay forma de cambiarlo.",
  declinationDeg: "Ídem `inclinationDeg`: sin setter ni input (medido por la Fase 10).",
  fieldIntensityNt: "Ídem `inclinationDeg`: sin setter ni input (medido por la Fase 10).",
  suscMin: "Ídem `inclinationDeg`: sin setter ni input (medido por la Fase 10).",
  suscMax: "Ídem `inclinationDeg`: sin setter ni input (medido por la Fase 10).",
};

// ═══════════════════════════════════════════════════════════════════════════
// PARÁMETROS — las perillas de la inversión
// ═══════════════════════════════════════════════════════════════════════════
//
// Éste es el historial que más vale del producto: son las perillas que un
// consultor mueve una y otra vez comparando corridas.

export const PARAMETROS_DESHACIBLE = {
  strict: { etiqueta: "Modo estricto", fusionable: false },
  allowGRaw: { etiqueta: "Permitir g cruda", fusionable: false },
  previewLimit: { etiqueta: "Filas de vista previa", fusionable: false },
  densityPreset: { etiqueta: "Preset de densidad", fusionable: false },
  densityMin: { etiqueta: "Densidad mínima", fusionable: false },
  densityMax: { etiqueta: "Densidad máxima", fusionable: false },
  lambdaMode: { etiqueta: "Modo de lambda", fusionable: false },
  lambdaCustom: { etiqueta: "Lambda manual", fusionable: false },
  paddingKappaLog: { etiqueta: "Kappa de padding", fusionable: true },
  anchorKappaLog: { etiqueta: "Kappa de anclaje", fusionable: true },
  autoKappa: { etiqueta: "Kappa automático", fusionable: false },
  enableDepthPrior: { etiqueta: "Prior de profundidad", fusionable: false },
} as const satisfies Partial<Record<keyof ParametrosState, DescriptorPrep>>;

export const PARAMETROS_NO_DESHACIBLE: Record<
  Exclude<keyof ParametrosState, keyof typeof PARAMETROS_DESHACIBLE>,
  string
> = {
  acknowledgeSpatialRisk:
    "RECONOCIMIENTO DE RIESGO. Viaja al backend dentro del paquete y siempre se refiere a un " +
    "conjunto de archivos concreto (H-29). Un atajo de teclado no es una lectura del riesgo: " +
    "rehacer una casilla marcada re-afirmaría un consentimiento que el usuario no volvió a leer.",
  acknowledgeRegionalScale:
    "Ídem `acknowledgeSpatialRisk`. El cambio de archivos ya los caduca; el historial no puede " +
    "ser la puerta de atrás por la que vuelvan.",
  showAdvancedKappas:
    "Es abrir y cerrar una sección de la interfaz, no un parámetro. Meter los despliegues en el " +
    "historial hace que Ctrl+Z gaste pasos plegando paneles en vez de deshacer decisiones.",
};

// ═══════════════════════════════════════════════════════════════════════════

export const CLAVES_CONTEXTO = [
  "expectedRock",
  "expectedDepth",
  "utmZone",
  "gravimeterType",
] as const satisfies readonly (keyof typeof CONTEXTO_DESHACIBLE)[];

export const CLAVES_PARAMETROS = [
  "strict",
  "allowGRaw",
  "previewLimit",
  "densityPreset",
  "densityMin",
  "densityMax",
  "lambdaMode",
  "lambdaCustom",
  "paddingKappaLog",
  "anchorKappaLog",
  "autoKappa",
  "enableDepthPrior",
] as const satisfies readonly (keyof typeof PARAMETROS_DESHACIBLE)[];

// El compilador exige que las listas de barrido cubran las dos declaraciones.
type ContextoSinOrden = Exclude<
  keyof typeof CONTEXTO_DESHACIBLE,
  (typeof CLAVES_CONTEXTO)[number]
>;
type ParametrosSinOrden = Exclude<
  keyof typeof PARAMETROS_DESHACIBLE,
  (typeof CLAVES_PARAMETROS)[number]
>;
const _contextoCompleto: ContextoSinOrden extends never ? true : never = true;
const _parametrosCompleto: ParametrosSinOrden extends never ? true : never = true;
void _contextoCompleto;
void _parametrosCompleto;

function etiquetarCon(
  mapa: Record<string, DescriptorPrep>,
  claves: readonly string[],
): { etiqueta: string; fusionable: boolean } {
  const desc = claves[0] ? mapa[claves[0]] : undefined;
  if (!desc) return { etiqueta: "Cambio de preparación", fusionable: false };
  const fusionable = desc.fusionable && claves.length === 1;
  return {
    etiqueta: claves.length > 1 ? `${desc.etiqueta} (+${claves.length - 1})` : desc.etiqueta,
    fusionable,
  };
}

export function etiquetarContexto(claves: readonly string[]) {
  return etiquetarCon(CONTEXTO_DESHACIBLE, claves);
}

export function etiquetarParametros(claves: readonly string[]) {
  // El preset de densidad mueve TRES claves a la vez (`PRESET_DENSIDAD`), y el
  // usuario lo percibe como una sola decisión: la etiqueta lo dice así porque
  // `densityPreset` va primero en `CLAVES_PARAMETROS`.
  return etiquetarCon(PARAMETROS_DESHACIBLE, claves);
}
