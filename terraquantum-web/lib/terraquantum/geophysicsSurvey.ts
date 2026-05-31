export type GravityObservation = {
  x_m: number;
  y_m: number;
  z_m: number;
  g: number;
};

// DEMO — observaciones sintéticas, no provenientes de campaña gravimétrica real.
export const DEFAULT_OBSERVATIONS = `[
  { "x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000008 },
  { "x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000009 },
  { "x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000011 },
  { "x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000013 },
  { "x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000012 },
  { "x_m": 55, "y_m": 0, "z_m": 5, "g": 0.00000010 },
  { "x_m": 65, "y_m": 0, "z_m": 5, "g": 0.00000009 },
  { "x_m": 75, "y_m": 0, "z_m": 5, "g": 0.00000008 },
  { "x_m": 35, "y_m": 0, "z_m": 35, "g": 0.00000014 },
  { "x_m": 45, "y_m": 0, "z_m": 35, "g": 0.00000015 }
]`;

// DEMO — grilla sintética de alta anomalía para validación visual.
export const DEMO_STRONG_OBSERVATIONS = `[
  { "x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000080 },
  { "x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000090 },
  { "x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000110 },
  { "x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000150 },
  { "x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000145 },
  { "x_m": 55, "y_m": 0, "z_m": 5, "g": 0.00000110 },
  { "x_m": 65, "y_m": 0, "z_m": 5, "g": 0.00000090 },
  { "x_m": 75, "y_m": 0, "z_m": 5, "g": 0.00000080 },

  { "x_m": 5, "y_m": 0, "z_m": 35, "g": 0.00000085 },
  { "x_m": 15, "y_m": 0, "z_m": 35, "g": 0.00000100 },
  { "x_m": 25, "y_m": 0, "z_m": 35, "g": 0.00000135 },
  { "x_m": 35, "y_m": 0, "z_m": 35, "g": 0.00000220 },
  { "x_m": 45, "y_m": 0, "z_m": 35, "g": 0.00000230 },
  { "x_m": 55, "y_m": 0, "z_m": 35, "g": 0.00000135 },
  { "x_m": 65, "y_m": 0, "z_m": 35, "g": 0.00000100 },
  { "x_m": 75, "y_m": 0, "z_m": 35, "g": 0.00000085 },

  { "x_m": 5, "y_m": 0, "z_m": 65, "g": 0.00000075 },
  { "x_m": 15, "y_m": 0, "z_m": 65, "g": 0.00000090 },
  { "x_m": 25, "y_m": 0, "z_m": 65, "g": 0.00000110 },
  { "x_m": 35, "y_m": 0, "z_m": 65, "g": 0.00000145 },
  { "x_m": 45, "y_m": 0, "z_m": 65, "g": 0.00000140 },
  { "x_m": 55, "y_m": 0, "z_m": 65, "g": 0.00000110 },
  { "x_m": 65, "y_m": 0, "z_m": 65, "g": 0.00000090 },
  { "x_m": 75, "y_m": 0, "z_m": 65, "g": 0.00000075 }
]`;

export function parseObservations(raw: string): GravityObservation[] {
  const parsed = JSON.parse(raw);

  if (!Array.isArray(parsed)) {
    throw new Error("El survey debe ser un arreglo JSON.");
  }

  if (parsed.length < 10) {
    throw new Error("Debes ingresar al menos 10 observaciones gravimétricas.");
  }

  return parsed.map((obs, index) => {
    const x_m = Number(obs.x_m);
    const y_m = Number(obs.y_m);
    const z_m = Number(obs.z_m);
    const g = Number(obs.g);

    if (
      !Number.isFinite(x_m) ||
      !Number.isFinite(y_m) ||
      !Number.isFinite(z_m) ||
      !Number.isFinite(g)
    ) {
      throw new Error(`Observación ${index + 1} contiene valores inválidos.`);
    }

    return {
      x_m,
      y_m,
      z_m,
      g,
    };
  });
}

export function countObservations(raw: string) {
  try {
    return `${parseObservations(raw).length} obs`;
  } catch {
    return "inválido";
  }
}