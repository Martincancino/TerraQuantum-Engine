// ─── FASE 9 — Las vistas de la app, declaradas UNA vez ────────────────────────
//
// Antes de esta fase la lista de vistas vivía DUPLICADA en tres sitios:
// `NavBar.menuItems`, la cadena de ternarios de `app/page.tsx` y la lista de
// exclusión del fallback de esa misma página. Añadir una vista exigía tocar los
// tres, y olvidar el tercero no rompía nada visible: la vista nueva caía al
// HomeView **en silencio**.
//
// Es el mismo patrón que esta auditoría persigue en el backend (una capacidad
// declarada en un sitio y no cableada en otro), así que se cierra aquí en vez de
// añadirle una cuarta copia. El identificador es el que el store guarda en
// `view`, y la comparación se hace siempre en minúsculas.

export type ViewId =
  | "inicio"
  | "preparación"
  | "ia geológica"
  | "figura 3d"
  | "datos"
  | "historial"
  | "sistema";

export type ViewDef = {
  /** Clave canónica en minúsculas: lo que se compara contra el store. */
  id: ViewId;
  /** Etiqueta del menú (lo que ve y pulsa el usuario). */
  label: string;
};

export const VIEWS: readonly ViewDef[] = [
  { id: "inicio", label: "inicio" },
  { id: "preparación", label: "Preparación" },
  { id: "ia geológica", label: "ia geológica" },
  { id: "figura 3d", label: "figura 3D" },
  { id: "datos", label: "Datos" },
  { id: "historial", label: "Historial" },
  { id: "sistema", label: "Sistema" },
] as const;

/** Normaliza lo que haya en el store a un id conocido; `inicio` si no lo es. */
export function normalizeView(raw: unknown): ViewId {
  const value = String(raw ?? "").toLowerCase().trim();
  const hit = VIEWS.find((v) => v.id === value);
  return hit ? hit.id : "inicio";
}
