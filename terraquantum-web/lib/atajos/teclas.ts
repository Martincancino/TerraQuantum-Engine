// ─── FASE 13 (auditoría 06 §10) — Las combinaciones, declaradas UNA vez ───────
//
// Antes de esta fase el frontend tenía exactamente dos manejadores de teclado
// (medido: `Scene3D` con las flechas y el `<textarea>` de `IAChatView` con
// Enter) y ningún `ctrlKey`/`metaKey` en todo el árbol. Es decir, no había
// convención que respetar y sí un riesgo claro: que cada componente que quiera
// un atajo se escriba su propia comparación de teclas y acaben divergiendo,
// que es el mismo defecto que la Fase 10 encontró con el estado duplicado.
//
// Por eso las combinaciones viven aquí y en ningún otro sitio, y hay un test que
// lo comprueba.

/** Ctrl+Z (Cmd+Z en macOS). Sin Shift: con Shift es rehacer. */
export function esDeshacer(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
  return e.key.toLowerCase() === "z" && !e.shiftKey;
}

/** Las DOS formas que conviven en el sector: Ctrl+Y (Windows) y Ctrl+Shift+Z
 *  (macOS y la mayoría de las herramientas 3D). Se aceptan ambas porque el
 *  usuario de este producto viene de Leapfrog/Vulcan y no de un único sistema. */
export function esRehacer(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
  const t = e.key.toLowerCase();
  return (t === "z" && e.shiftKey) || (t === "y" && !e.shiftKey);
}

/** Etiqueta legible para el tooltip, dependiente del sistema. Se calcula en el
 *  cliente: en el render del servidor no hay `navigator`. */
export function nombreDeAtajo(accion: "deshacer" | "rehacer"): string {
  const mac =
    typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform || "");
  const mod = mac ? "⌘" : "Ctrl";
  if (accion === "deshacer") return `${mod}+Z`;
  return mac ? `${mod}+Shift+Z` : `${mod}+Y`;
}
