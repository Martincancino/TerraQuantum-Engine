// ─── Fase R3 — Paquete CSV ───────────────────────────────────────────────────
//
// Formato de "paquete CSV" que desacopla la PREPARACIÓN de la INVERSIÓN.
//
// PrepPanel (vista «Preparación») recolecta el CSV limpio/corregido + todos los
// parámetros de inversión y los serializa en un paquete descargable. LoadPanel
// (vista 3D) sube ese paquete, reconstruye el File + los parámetros y dispara la
// inversión contra el endpoint existente (invertGravityCsv). El paquete es 100%
// del lado del cliente: no hay formato ni endpoint nuevo en el backend.

import type { GravityCsvInvertPayload } from "./frontendApi";
import type { PgiParamsUI } from "../../componentes/PgiParamsForm";
import type { MagneticRemanenceParamsUI } from "../../componentes/MagneticRemanenceForm";

/** Versión del formato. Subir si cambia la forma de CsvPackage de modo incompatible. */
export const CSV_PACKAGE_VERSION = 1 as const;

export type CsvPackageDataType = "gravity" | "magnetic";

/** Coordenadas del bounding box (grados decimales, como strings de formulario). */
export type CsvPackageCoords = {
  latNorth: string;
  latSouth: string;
  lonEast: string;
  lonWest: string;
};

/** Parámetros físicos/de inversión que viajan en el paquete. */
export type CsvPackageParams = {
  strict: boolean;
  allowGRaw: boolean;
  densityMin: string;
  densityMax: string;
  densityPreset: "granite" | "magnetite" | "copper" | "custom";
  gravimeterType: string;
  lambdaMode: "auto" | "custom";
  lambdaCustom: string;
  paddingKappaLog: number;
  anchorKappaLog: number;
  autoKappa: boolean;
  utmZone: string;
  acknowledgeSpatialRisk: boolean;
  acknowledgeRegionalScale: boolean;
  // Contexto del survey (interpretación / ruteo multimodal).
  expectedRock: string;
  expectedDepth: string;
  // Parámetros del campo geomagnético (solo relevantes en modo magnetic).
  inclinationDeg: number;
  declinationDeg: number;
  fieldIntensityNt: number;
  suscMin: string;
  suscMax: string;
};

/** Paquete CSV completo: dato + parámetros, todo lo que la inversión consume. */
export type CsvPackage = {
  formatVersion: typeof CSV_PACKAGE_VERSION;
  /** Etiqueta del producto que lo generó (trazabilidad). */
  generator: "terraquantum-prep";
  dataType: CsvPackageDataType;
  csv: {
    filename: string;
    /** Texto del CSV ya limpio/corregido. */
    text: string;
    /** true si el texto es el CSV corregido por el wizard (afecta allowGRaw). */
    corrected: boolean;
  };
  params: CsvPackageParams;
  pgiParams: PgiParamsUI | null;
  remanenceParams: MagneticRemanenceParamsUI | null;
  boreholes: NonNullable<GravityCsvInvertPayload["boreholes"]> | null;
};

/** Entrada para construir el paquete (acepta el texto del CSV ya leído). */
export type BuildCsvPackageInput = {
  dataType: CsvPackageDataType;
  csvFilename: string;
  csvText: string;
  corrected: boolean;
  params: CsvPackageParams;
  pgiParams?: PgiParamsUI | null;
  remanenceParams?: MagneticRemanenceParamsUI | null;
  boreholes?: GravityCsvInvertPayload["boreholes"] | null;
};

/** Construye un CsvPackage normalizado a partir del estado del PrepPanel. */
export function buildCsvPackage(input: BuildCsvPackageInput): CsvPackage {
  return {
    formatVersion: CSV_PACKAGE_VERSION,
    generator: "terraquantum-prep",
    dataType: input.dataType,
    csv: {
      filename: input.csvFilename,
      text: input.csvText,
      corrected: input.corrected,
    },
    params: input.params,
    pgiParams: input.pgiParams ?? null,
    remanenceParams: input.remanenceParams ?? null,
    boreholes:
      input.boreholes && input.boreholes.length > 0 ? input.boreholes : null,
  };
}

/** Serializa el paquete a JSON (texto del archivo descargable). */
export function serializeCsvPackage(pkg: CsvPackage): string {
  return JSON.stringify(pkg, null, 2);
}

/** Nombre de archivo sugerido para el paquete (a partir del CSV de origen). */
export function csvPackageFilename(pkg: CsvPackage): string {
  const base = (pkg.csv.filename || "survey")
    .replace(/\.[^./\\]+$/, "")
    .replace(/[^A-Za-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `paquete_${base || "survey"}.tqpkg.json`;
}

export type ParseCsvPackageResult =
  | { ok: true; package: CsvPackage }
  | { ok: false; error: string };

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Parsea y valida (de forma) el texto de un paquete subido. */
export function parseCsvPackage(text: string): ParseCsvPackageResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: "El paquete no es un JSON válido." };
  }

  if (!isObject(raw)) {
    return { ok: false, error: "El paquete no tiene el formato esperado." };
  }

  if (raw.generator !== "terraquantum-prep") {
    return {
      ok: false,
      error: "El archivo no es un paquete CSV de TerraQuantum.",
    };
  }

  if (raw.formatVersion !== CSV_PACKAGE_VERSION) {
    return {
      ok: false,
      error: `Versión de paquete no soportada (esperada ${CSV_PACKAGE_VERSION}).`,
    };
  }

  const csv = raw.csv;
  if (!isObject(csv) || typeof csv.text !== "string" || csv.text.length === 0) {
    return { ok: false, error: "El paquete no contiene datos CSV." };
  }

  if (!isObject(raw.params)) {
    return { ok: false, error: "El paquete no contiene parámetros de inversión." };
  }

  if (raw.dataType !== "gravity" && raw.dataType !== "magnetic") {
    return { ok: false, error: "Tipo de dato del paquete inválido." };
  }

  return { ok: true, package: raw as unknown as CsvPackage };
}

/** Reconstruye un File a partir del CSV del paquete (para invertGravityCsv). */
export function csvPackageToFile(pkg: CsvPackage): File {
  return new File([pkg.csv.text], pkg.csv.filename || "survey.csv", {
    type: "text/csv",
  });
}

/** Dispara la descarga del paquete en el navegador. */
export function downloadCsvPackage(pkg: CsvPackage): void {
  const blob = new Blob([serializeCsvPackage(pkg)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = csvPackageFilename(pkg);
  a.click();
  URL.revokeObjectURL(url);
}
