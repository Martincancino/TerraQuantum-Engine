// ─── FASE 13 (auditoría 06 §10) — Aislamiento de foco para atajos globales ────
//
// La auditoría lo anotó en §9H.2 como «listener de teclado global sin
// aislamiento de foco: choca con los sliders del visor 3D». Al medirlo para
// esta fase salió que el diagnóstico se quedaba corto y el número estaba mal:
//
//   · Son **8 sliders**, no ~10 controles sueltos, y están acotados: las vistas
//     son mutuamente excluyentes, así que los 21 inputs de `PrepPanel` y los del
//     resto de paneles NUNCA coexisten con el listener de `Scene3D`. En el
//     subárbol del visor hay 8 `input[type=range]` (6 del corte caja, 1 del
//     corte de sección, 1 del umbral conjunto), 3 casillas y 1 selector de
//     fichero. Cero `<textarea>`, cero `<select>`, cero `contentEditable`.
//   · Y no es «doble efecto» sino **secuestro**: el manejador de `Scene3D`
//     llama a `preventDefault()` de forma INCONDICIONAL y está enganchado en
//     `window` en fase de burbuja. El paso por flechas de un `input[type=range]`
//     es la acción por defecto CANCELABLE del `keydown`, y el evento burbujea
//     hasta `window` antes de ejecutarla. Con un slider enfocado, las flechas
//     mueven la cámara y **el slider no se mueve**.
//
// [DEDUCIDO del código y de la especificación HTML, no verificado en navegador]
// La parte MEDIDA e indiscutible es que no había ningún filtro de foco y que el
// `preventDefault` era incondicional. La reparación es la misma en los dos casos.
//
// Se separan DOS preguntas porque el navegador se comporta distinto en cada una,
// y confundirlas es lo que produce atajos que pisan al usuario:

const ETIQUETAS_DE_FORMULARIO = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** Tipos de `<input>` que llevan un buffer de texto y por tanto tienen el
 *  deshacer NATIVO del navegador dentro del campo. `range`, `checkbox`, `radio`,
 *  `color`, `file` y `button` NO están: ahí no hay nada que deshacer. */
const TIPOS_CON_TEXTO = new Set([
  "text",
  "search",
  "url",
  "tel",
  "email",
  "password",
  "number",
  "date",
  "datetime-local",
  "month",
  "time",
  "week",
]);

function elemento(evento: KeyboardEvent): Element | null {
  const objetivo = evento.target;
  if (objetivo instanceof Element) return objetivo;
  // Si el evento no trae objetivo utilizable (p. ej. lo emitió el documento),
  // se cae al elemento con foco real.
  return typeof document === "undefined" ? null : document.activeElement;
}

function esEditable(el: Element | null): boolean {
  if (!el) return false;
  return el instanceof HTMLElement && el.isContentEditable;
}

/**
 * ¿El foco está en un sitio donde el navegador YA hace deshacer?
 *
 * Se usa para **Ctrl+Z / Ctrl+Y**: dentro de un campo de texto, el deshacer
 * nativo es el que el usuario espera (deshace su tecleo, carácter a carácter) y
 * robárselo sería peor que no tener atajo. Fuera de un campo de texto, ese
 * atajo no hace nada en el navegador y es nuestro.
 */
export function elFocoTieneDeshacerPropio(evento: KeyboardEvent): boolean {
  const el = elemento(evento);
  if (esEditable(el)) return true;
  if (!el || el.tagName !== "INPUT") return false;
  const tipo = (el as HTMLInputElement).type?.toLowerCase() || "text";
  return TIPOS_CON_TEXTO.has(tipo);
}

/**
 * ¿El foco está en un control de formulario que el teclado ya maneja?
 *
 * Se usa para las **flechas**: un `input[type=range]`, un `input[type=number]`
 * y un `<select>` cambian de valor con las flechas por comportamiento nativo.
 * Un atajo global que las capture (y peor, que llame a `preventDefault`) deja
 * esos controles inoperables por teclado — que es exactamente el defecto que
 * esta fase repara en `Scene3D`.
 */
export function elFocoEstaEnUnControl(evento: KeyboardEvent): boolean {
  const el = elemento(evento);
  if (esEditable(el)) return true;
  if (!el) return false;
  if (ETIQUETAS_DE_FORMULARIO.has(el.tagName)) return true;
  // Controles compuestos accesibles (todavía no hay ninguno en el visor, pero
  // el día que lo haya no debe romperse en silencio).
  const rol = el.getAttribute("role");
  return rol === "textbox" || rol === "slider" || rol === "spinbutton";
}
