import { test, expect, Page } from "@playwright/test";

import {
  huellaDeInvalidacion,
  N_PARAMETROS_INVALIDANTES,
} from "../componentes/prep/invalidaResultado";
import {
  avanzadoInicial,
  contextoInicial,
  parametrosInicial,
} from "../componentes/prep/prepPanelState";
import { enriquecerInicial } from "../componentes/prep/prepEnrichState";

/**
 * FASE 25 (plan 15-26) — Lo que el backend dice y el frontend no escucha.
 * ============================================================================
 *
 * Dos huecos del mismo tipo: el backend publica algo y el frontend no lo consume.
 *
 *   · **NUEVO-7** — la Fase 16 hizo que la ingesta caracterizara los roles por
 *     RANGO físico y PROPUSIERA una columna cuando el nombre no basta. Esa
 *     propuesta viaja en `column_mapping.suggestions` desde entonces y MEDIDO al
 *     abrir esta fase: **0 consumidores en TypeScript**. La parte cara de la
 *     Fase 16 —el criterio que evita que un `X,Y,Z` entre torcido— estaba
 *     construida y muda.
 *   · **H-36** — el aviso «resultado desactualizado» salía de una lista A MANO
 *     de 23 variables, y ya se había quedado atrás.
 *
 * **Por qué este fichero existe y no bastaban los e2e que ya había.** Los dos
 * únicos mocks del repo que construyen un plan de mapeo mandan `suggestions: {}`
 * (`fase10_csv_sucio.spec.ts:88`, `fase24_preparacion_persistente.spec.ts:102`).
 * Con la sugerencia SIEMPRE vacía, un frontend que la pinta y uno que no la pinta
 * dan exactamente el mismo resultado: la suite no podía distinguirlos. Aquí el
 * mock la manda POBLADA, que es la única forma de que la aserción signifique algo.
 *
 * La afirmación más dura del recorrido A no es que el texto aparezca, sino que al
 * ACEPTAR la sugerencia el rol elegido **viaja en `column_map_json`**: se
 * intercepta el `multipart/form-data` de `/api/gravity-import/enrich-package` y
 * se lee el campo. «Se ve en pantalla» y «llega al backend» son cosas distintas,
 * y esta fase entera trata justamente de esa diferencia.
 *
 * El recorrido B ataca la mitad de H-36 que NINGÚN test cubría: `fase1_confianza`
 * ya prueba el aviso moviendo `densityMin` en el flujo CLÁSICO (el colapsado bajo
 * «Avanzado»), pero MEDIDO al abrir esta fase `markResultStale()` tenía UN solo
 * llamador en todo el frontend y el flujo PRINCIPAL —por donde entra el usuario—
 * no era ninguno. Aquí se mueve la zona UTM del flujo principal, que viaja al
 * backend como `config.utm_zone` y decide la proyección de las estaciones.
 *
 * Como en el resto de la suite, el backend se sustituye en la frontera HTTP.
 */

const PROJECT_A = "proj_f25";
const RUN_A = "run_f25";

/** Cabecera del caso REAL de la Fase 16: `X,Y,Z` no dice qué es cada columna, y
 *  el mapeo por nombre no puede resolverlo sin adivinar. El backend lo resuelve
 *  por RANGO (medianas de UTM este/norte) y lo PROPONE. */
const CSV_XYZ = [
  "X,Y,Z,Bouguer_mGal",
  ...Array.from(
    { length: 9 },
    (_, i) => `${363000 + i * 25},${7412000 + i * 25},${3000 + i * 10},${(10.1 + i * 0.37).toFixed(3)}`,
  ),
  "",
].join("\n");

const FILAS_PARSEADAS = Array.from({ length: 9 }, (_, i) => ({
  X: String(363000 + i * 25),
  Y: String(7412000 + i * 25),
  Z: String(3000 + i * 10),
  Bouguer_mGal: (10.1 + i * 0.37).toFixed(3),
}));

/** El plan tal como lo emite el backend para ese CSV. Los dos roles requeridos
 *  `x` e `y` están en `missing_required` —así que sus desplegables salen en
 *  «— sin asignar —»— y `suggestions` trae exactamente lo que los llenaría.
 *
 *  Que `suggestions` sólo se pueble para roles de `missing_required` no es una
 *  suposición del test: el servicio sólo llama al sugeridor dentro de
 *  `if missing:` (`column_mapping_service.py:680-681`), y por eso `needs_mapping`
 *  es SIEMPRE true cuando hay sugerencias — el paso de mapeo está en pantalla. */
function planConSugerencias() {
  return {
    data_kind: "gravity",
    raw_columns: ["X", "Y", "Z", "Bouguer_mGal"],
    auto_detected: {},
    roles: { z: "Z", gravity_value: "Bouguer_mGal" },
    overridden: {},
    invalid_overrides: {},
    required_roles: ["x", "y", "gravity_value"],
    optional_roles: ["z"],
    missing_required: ["x", "y"],
    needs_mapping: true,
    confidence: "low",
    role_labels: { x: "Este / X", y: "Norte / Y", z: "Cota / Z", gravity_value: "Gravedad" },
    literals: {},
    range_checks: {},
    suspicions: [],
    role_confidence: { x: "low", y: "low" },
    // ── Lo que esta fase viene a hacer visible ────────────────────────────────
    suggestions: {
      x: {
        column: "X",
        confidence: "medium",
        reason:
          "Rango de 'X' (mediana ~363,000) calza con UTM este; forma par único con el norte sugerido. Confírmelo antes de continuar.",
      },
      y: {
        column: "Y",
        confidence: "medium",
        reason:
          "Rango de 'Y' (mediana ~7,412,000) calza con UTM norte; forma par único con el este sugerido. Confírmelo antes de continuar.",
      },
    },
    needs_confirmation: false,
    questions: [],
    inferred_literals: {},
  };
}

function sniffJson() {
  return {
    version: "csv_sniff_v1",
    filename: "xyz.csv",
    encoding: { value: "utf-8", confidence: "high", evidence: "Decodifica sin errores.", discarded: [] },
    separator: { value: ",", confidence: "high", evidence: "',' aparece 3 veces por línea.", discarded: [] },
    decimal: { value: ".", confidence: "high", evidence: "El separador es ',': el decimal es '.'.", discarded: [] },
    preamble_count: 0,
    preamble_lines: [],
    header_line_number: 1,
    header_columns: ["X", "Y", "Z", "Bouguer_mGal"],
    broken_rows: [],
    broken_row_count: 0,
    n_lines_sampled: 10,
    sample_truncated: false,
    warnings: [],
  };
}

function blockModelJson() {
  const cells = [
    { x: 10, y: 10, z: 10, density: 2.9, anomaly: 0.3 },
    { x: 20, y: 20, z: 20, density: 3.1, anomaly: 0.5 },
    { x: 30, y: 30, z: 30, density: 2.7, anomaly: 0.1 },
  ];
  return {
    cells,
    domainL: 100, domainH: 60, domainW: 100, cellSize: 10,
    densityMin: 2.6, densityMax: 3.0,
    mode: "exploration",
    returned_voxels: cells.length,
    total_voxels: cells.length,
    warnings: [],
  };
}

function runDetailJson() {
  return {
    project_id: PROJECT_A,
    run_id: RUN_A,
    inputs: { depth: 300, region: "norte_chile" },
    report: {
      status: "done",
      warnings: [],
      topography_used: "from_sensor_elevations_masl[linear]",
      topography_degraded: false,
      technicalSummary: { overall_level: "MEDIUM", summary: "Corrida de prueba.", warnings: [] },
      misfit_error_percent: 3.2,
      best_target: { x_m: 40, y_m: 30, z_m: 20, probability: 0.6 },
      observationQuality: { observation_count: 3 },
    },
  };
}

// ─── Sustitución del backend en la frontera HTTP ─────────────────────────────

/** Guarda el `column_map_json` del último `enrich-package` para poder afirmar
 *  sobre lo que SALIÓ del navegador, no sobre lo que se ve. */
type Espia = { columnMapJson: string | null; llamadas: number };

async function mockBackend(page: Page, espia: Espia) {
  await page.route("**/api/gravity-import/enrich-package**", async (route) => {
    espia.llamadas += 1;
    espia.columnMapJson = leerCampoMultipart(route.request().postData(), "column_map_json");
    await route.fulfill({
      json: {
        needs_mapping: true,
        needs_confirmation: false,
        column_mapping: planConSugerencias(),
        sniff_report: sniffJson(),
        sample_rows: FILAS_PARSEADAS.slice(0, 3),
        message:
          "No se reconocieron automáticamente todas las columnas requeridas. Asigne manualmente los roles e intente de nuevo.",
      },
    });
  });
  await page.route("**/api/gravity-import/preview**", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        previewCount: 3,
        totalObservations: 3,
        observationsPreview: [],
        importMetadata: { gravity_type: "complete_bouguer_anomaly" },
        warnings: [],
        errors: [],
        spatial_readiness: { level: "OK", requires_user_acknowledgement: false },
        regional_scale_preflight: { can_run_single_inversion: true, requires_user_acknowledgement: false },
      },
    }),
  );
  await page.route("**/api/gravity-import/load-package**", (route) =>
    route.fulfill({
      json: { status: "done", project_id: PROJECT_A, run_id: RUN_A, route: "gravity_only", errors: [] },
    }),
  );
  await page.route("**/api/block-model?**", (route) => route.fulfill({ json: blockModelJson() }));
  await page.route("**/api/block-model-zarr**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/project-run-detail**", (route) => route.fulfill({ json: runDetailJson() }));
  await page.route("**/api/geophysics-status**", (route) =>
    route.fulfill({ json: { status: "done", stage: "done", progress: 1 } }),
  );
  // Ruido de las vistas que no afecta a lo que se afirma aquí.
  await page.route("**/api/backend-health**", (route) => route.fulfill({ json: { online: true } }));
  await page.route("**/api/project-runs**", (route) => route.fulfill({ json: { projects: [] } }));
  await page.route("**/api/multimodal/plan**", (route) =>
    route.fulfill({ json: { plan: null, insufficient_reason: "Sin datos suficientes." } }),
  );
  await page.route("**/api/terrain**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/favorability**", (route) => route.fulfill({ status: 404, json: {} }));
}

/** Lee un campo de texto de un `multipart/form-data` serializado. Basta con un
 *  corte por el nombre del campo: los valores de este test son JSON de una línea. */
function leerCampoMultipart(cuerpo: string | null, campo: string): string | null {
  if (!cuerpo) return null;
  const marca = `name="${campo}"`;
  const i = cuerpo.indexOf(marca);
  if (i < 0) return null;
  const resto = cuerpo.slice(i + marca.length);
  const inicio = resto.indexOf("\r\n\r\n");
  if (inicio < 0) return null;
  const fin = resto.indexOf("\r\n", inicio + 4);
  return resto.slice(inicio + 4, fin < 0 ? undefined : fin);
}

// ─── Navegación ──────────────────────────────────────────────────────────────

async function enterApp(page: Page) {
  await page.goto("/");
  const inicio = page.getByRole("button", { name: /^inicio$/i });
  const enter = page.getByRole("button", { name: /Entrar a la Plataforma/i });
  await enter.waitFor({ state: "visible" });
  await expect(async () => {
    if (!(await inicio.isVisible())) await enter.click();
    await expect(inicio).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20_000 });
}

async function navTo(page: Page, label: string) {
  await page.getByRole("button", { name: new RegExp(`^${label}$`, "i") }).click();
}

/** Zona de carga de gravimetría del flujo PRINCIPAL (`PrepEnrichPanel`). */
const enrichGravityInput = (page: Page) => page.locator('input[type="file"][accept=".csv"]').nth(0);

/** Sube el CSV `X,Y,Z` y pide generar: el backend responde `needs_mapping` y el
 *  paso de mapeo aparece con las sugerencias. */
async function abrirPasoDeMapeo(page: Page) {
  await navTo(page, "Preparación");
  await enrichGravityInput(page).setInputFiles({
    name: "xyz.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_XYZ),
  });
  await page.getByRole("button", { name: /Generar CSV completo/i }).click();
  await expect(page.getByText(/Mapeo manual de columnas/i)).toBeVisible({ timeout: 30_000 });
}

/** Carga un modelo en el visor por la vía real (LoadPanel → paquete → block model). */
async function cargarModeloEnElVisor(page: Page) {
  await navTo(page, "figura 3D");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "paquete.tqpkg.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("#CONFIG\n" + CSV_XYZ),
  });
  await page.getByRole("button", { name: /Cargar modelo 3D/i }).click();
  await expect(page.getByText(/Modelo cargado/i)).toBeVisible({ timeout: 30_000 });
}

// ─── Recorrido A — NUEVO-7 ───────────────────────────────────────────────────

test.describe("Fase 25 · A — la sugerencia de mapeo llega al usuario", () => {
  test("la sugerencia se PINTA en el rol al que pertenece, con su motivo y su confianza", async ({ page }) => {
    const espia: Espia = { columnMapJson: null, llamadas: 0 };
    await mockBackend(page, espia);
    await enterApp(page);
    await abrirPasoDeMapeo(page);

    // Una sugerencia por cada rol requerido sin resolver, y NINGUNA para los
    // roles que el backend sí resolvió por nombre (`z`, `gravity_value`): pintar
    // una propuesta sobre un rol ya decidido sería pedir que se confirme algo
    // que nadie puso en duda.
    await expect(page.getByTestId("role-suggestion-x")).toBeVisible();
    await expect(page.getByTestId("role-suggestion-y")).toBeVisible();
    await expect(page.getByTestId("role-suggestion-z")).toHaveCount(0);
    await expect(page.getByTestId("role-suggestion-gravity_value")).toHaveCount(0);

    // La columna propuesta y el MOTIVO medido por el backend (el rango), que es
    // lo que permite al usuario juzgar la propuesta en vez de obedecerla.
    await expect(page.getByTestId("role-suggestion-x")).toHaveAttribute("data-suggested-column", "X");
    await expect(page.getByTestId("role-suggestion-x")).toContainText(/mediana ~363,000/);
    await expect(page.getByTestId("role-suggestion-y")).toContainText(/UTM norte/);

    // Y su CONFIANZA, dicha en castellano. El backend la fija en `medium` en los
    // tres sitios que construyen una sugerencia y tiene un test que impide que
    // sea `high`: «se propone, se confirma, no se aplica sola».
    await expect(page.getByTestId("role-suggestion-x")).toContainText(/confianza media/i);
  });

  test("NO se aplica sola: el desplegable sigue vacío hasta que el usuario acepta", async ({ page }) => {
    const espia: Espia = { columnMapJson: null, llamadas: 0 };
    await mockBackend(page, espia);
    await enterApp(page);
    await abrirPasoDeMapeo(page);

    // Ésta es la aserción que impide «arreglar» NUEVO-7 auto-rellenando el mapa:
    // eso reabriría el defecto que la Fase 16 cerró (adivinar el rol de una
    // columna) y además dejaría el botón «Aplicar mapeo» habilitado sin que
    // nadie haya leído nada.
    await expect(page.locator('select[data-role="x"]')).toHaveValue("");
    await expect(page.locator('select[data-role="y"]')).toHaveValue("");

    // Aceptar es un acto explícito.
    await page.getByTestId("role-suggestion-accept-x").click();
    await expect(page.locator('select[data-role="x"]')).toHaveValue("X");

    // Y una vez aceptada, la propuesta se retira: repetirla sería pedir que se
    // confirme algo ya confirmado.
    await expect(page.getByTestId("role-suggestion-x")).toHaveCount(0);
    await expect(page.getByTestId("role-suggestion-y")).toBeVisible();
  });

  test("lo aceptado VIAJA: el rol sugerido sale en `column_map_json`", async ({ page }) => {
    const espia: Espia = { columnMapJson: null, llamadas: 0 };
    await mockBackend(page, espia);
    await enterApp(page);
    await abrirPasoDeMapeo(page);

    expect(espia.llamadas).toBe(1);
    // La primera llamada no llevaba mapa: por eso el backend pidió mapeo.
    expect(espia.columnMapJson).toBeNull();

    await page.getByTestId("role-suggestion-accept-x").click();
    await page.getByTestId("role-suggestion-accept-y").click();
    await page.getByRole("button", { name: /Aplicar mapeo y generar/i }).click();

    // «Se ve en pantalla» y «llega al backend» son cosas distintas, y esta fase
    // trata de esa diferencia: se lee el multipart que salió del navegador.
    await expect(async () => {
      expect(espia.llamadas).toBeGreaterThan(1);
      expect(espia.columnMapJson).not.toBeNull();
    }).toPass({ timeout: 20_000 });

    const mapa = JSON.parse(espia.columnMapJson as string);
    expect(mapa.x).toBe("X");
    expect(mapa.y).toBe("Y");
  });
});

// ─── Recorrido B — H-36 ──────────────────────────────────────────────────────

test.describe("Fase 25 · B — el aviso de «desactualizado» cubre el flujo principal", () => {
  // Los dos recorridos cargan un modelo por la vía REAL (LoadPanel → paquete →
  // block model), y eso solo ya gasta ~50 s de los 60 del timeout por defecto.
  // MEDIDO: en aislamiento pasaban, y encadenados el primero moría por
  // TIMEOUT y no por aserción — un rojo que no dice nada del código. Se
  // declara la lentitud en vez de recortar el recorrido: cargar el modelo de
  // verdad es lo que hace que el aviso signifique algo.
  test.slow();
  test("mover la zona UTM del flujo PRINCIPAL tras invertir marca el resultado", async ({ page }) => {
    const espia: Espia = { columnMapJson: null, llamadas: 0 };
    await mockBackend(page, espia);
    await enterApp(page);
    await cargarModeloEnElVisor(page);
    await expect(page.getByTestId("stale-result-badge")).toHaveCount(0);

    // La zona UTM del flujo PRINCIPAL viaja como `config.utm_zone` y decide la
    // proyección con la que se georreferencian las estaciones. Antes de esta
    // fase no la miraba nadie: `markResultStale()` sólo se llamaba desde el
    // flujo clásico, así que este cambio no dejaba una sola marca en pantalla.
    await navTo(page, "Preparación");
    const utm = page.getByPlaceholder("ej. 19S");
    await expect(utm).toBeVisible({ timeout: 20_000 });
    await utm.fill("19S");
    await utm.blur();

    await navTo(page, "figura 3D");
    await expect(page.getByTestId("stale-result-badge")).toBeVisible({ timeout: 20_000 });
  });

  test("volver a la pestaña sin tocar nada NO marca el resultado", async ({ page }) => {
    const espia: Espia = { columnMapJson: null, llamadas: 0 };
    await mockBackend(page, espia);
    await enterApp(page);
    await cargarModeloEnElVisor(page);

    // El control del recorrido anterior. `despertarPreparacion()` ESCRIBE en el
    // store al volver a la pestaña (apaga cargas, errores y modales), así que un
    // aviso mal declarado saltaría por el simple hecho de visitar «Preparación».
    // Que esos campos estén en `*_NO_INVALIDA` es lo que se comprueba aquí: un
    // aviso que salta cuando no pasa nada se aprende a ignorar.
    await navTo(page, "Preparación");
    await expect(page.getByPlaceholder("ej. 19S")).toBeVisible({ timeout: 20_000 });
    await navTo(page, "figura 3D");
    await expect(page.getByTestId("stale-result-badge")).toHaveCount(0);
  });
});

// ─── Recorrido C — H-36, el contrato de la declaración ───────────────────────
//
// Sin navegador: se importa la declaración y se compara la huella. Existe porque
// el recorrido B sólo puede ejercitar los parámetros que TIENEN un control fácil
// de conducir, y los cuatro que faltaban en la lista vieja no lo tienen — el
// prior geológico implícito de la Fase 14 exige sondajes con litología y un
// modal, y el CSV corregido exige el asistente entero. Sin esto, la parte de
// H-36 que el plan nombra por su nombre quedaría sin guardia.
//
// Y hay un límite que conviene decir: el tipo exhaustivo obliga a CLASIFICAR
// cada parámetro, no acierta por ti la clasificación. Mover una clave de
// `*_INVALIDA` a `*_NO_INVALIDA` compila igual de bien. Lo que lo impide es esta
// tabla, y por eso es una lista explícita y no un recorrido de las declaraciones:
// derivarla de lo declarado la haría pasar siempre.

const ESTADO_BASE = {
  contexto: contextoInicial,
  parametros: parametrosInicial,
  avanzado: avanzadoInicial,
  enriquecer: enriquecerInicial,
  store: {
    latNorth: "", latSouth: "", lonEast: "", lonWest: "",
    fileGravimetry: null, fileMagnetometry: null, prepSondajes: [],
  },
};

const conCambio = (parche: Record<string, unknown>) =>
  huellaDeInvalidacion({ ...ESTADO_BASE, ...parche } as never);

const HUELLA_BASE = huellaDeInvalidacion(ESTADO_BASE as never);

/** Los que cambian el paquete que se manda al backend. Los cinco marcados
 *  AUSENTE no estaban en la lista a mano que esta fase retiró. */
const INVALIDAN: [string, Record<string, unknown>][] = [
  ["densityMin → config.density_min", { parametros: { ...parametrosInicial, densityMin: "1.0" } }],
  ["lambdaCustom → config.lambda_mag", { parametros: { ...parametrosInicial, lambdaCustom: "0.5" } }],
  ["enableDepthPrior → config.enable_depth_prior", { parametros: { ...parametrosInicial, enableDepthPrior: true } }],
  ["strict → query strict", { parametros: { ...parametrosInicial, strict: false } }],
  ["utmZone → config.utm_zone", { contexto: { ...contextoInicial, utmZone: "19S" } }],
  ["suscMax → config.susc_max", { contexto: { ...contextoInicial, suscMax: "2.0" } }],
  ["latNorth → config.lat", { store: { ...ESTADO_BASE.store, latNorth: "-23.4" } }],
  // ── AUSENTES de la lista vieja ────────────────────────────────────────────
  ["AUSENTE implicitGeologyParams → config.implicit_geology (FASE 14)", {
    avanzado: { ...avanzadoInicial, implicitGeologyParams: { enabled: true, target_lithologies: ["magnetita"] } },
  }],
  ["AUSENTE acknowledgeSpatialRisk → config.acknowledge_spatial_risk", {
    parametros: { ...parametrosInicial, acknowledgeSpatialRisk: true },
  }],
  ["AUSENTE acknowledgeRegionalScale → config.acknowledge_regional_scale", {
    parametros: { ...parametrosInicial, acknowledgeRegionalScale: true },
  }],
  ["AUSENTE correctedFile → es el fichero PRIMARIO del paquete", {
    avanzado: { ...avanzadoInicial, correctedFile: { name: "c.csv", size: 42, lastModified: 7 } },
  }],
  ["AUSENTE prepSondajes → boreholes_json", {
    store: { ...ESTADO_BASE.store, prepSondajes: [{ hole_id: "BH01", density_t_m3: 3.2 }] },
  }],
  // ── El flujo PRINCIPAL, que no tenía huella ninguna ───────────────────────
  ["enriquecer.utmZone → config.utm_zone", { enriquecer: { ...enriquecerInicial, utmZone: "19S" } }],
  ["enriquecer.surveyDate → config.survey_date (IGRF-14)", { enriquecer: { ...enriquecerInicial, surveyDate: "2016" } }],
  ["enriquecer.columnMap → column_map_json (el rol de cada columna)", {
    enriquecer: { ...enriquecerInicial, columnMap: { x: "X" } },
  }],
  ["enriquecer.useHelmert → decide si viajan los puntos de control", {
    enriquecer: { ...enriquecerInicial, useHelmert: true },
  }],
];

/** Los que NO salen del navegador. Marcar de más no es gratis: un aviso que
 *  salta cuando no pasa nada se aprende a ignorar, y deja de avisar cuando sí. */
const NO_INVALIDAN: [string, Record<string, unknown>][] = [
  ["previewLimit: filas de la tabla de preview", { parametros: { ...parametrosInicial, previewLimit: 999 } }],
  ["showAdvancedKappas: desplegar para MIRAR no es cambiar", { parametros: { ...parametrosInicial, showAdvancedKappas: true } }],
  ["densityPreset sin mover los bounds (caso `custom`)", { parametros: { ...parametrosInicial, densityPreset: "granite" } }],
  ["expectedRock: guía la lectura, no la produce", { contexto: { ...contextoInicial, expectedRock: "granito" } }],
  ["showPgiModal: booleano de ventana", { avanzado: { ...avanzadoInicial, showPgiModal: true } }],
  ["pgiParams APAGADO: alpha movido no viaja", { avanzado: { ...avanzadoInicial, pgiParams: { enabled: false, alpha_pgi: 0.9 } } }],
  ["remanencia APAGADA: q movido no viaja", { avanzado: { ...avanzadoInicial, remanenceParams: { enabled: false, q_ratio: 9 } } }],
  ["ctrlPoints SIN Helmert: no se serializan", {
    enriquecer: { ...enriquecerInicial, ctrlPoints: [{ localX: "1", localY: "2", realE: "3", realN: "4" }] },
  }],
  ["enriquecer.loading/error: lo que `despertarPreparacion()` apaga al volver", {
    enriquecer: { ...enriquecerInicial, loading: true, error: "un intento abandonado" },
  }],
  ["enriquecer.sampleRows: respuesta del backend, no una entrada", {
    enriquecer: { ...enriquecerInicial, sampleRows: [{ a: "1" }] },
  }],
];

test.describe("Fase 25 · C — qué invalida un resultado, sin navegador", () => {
  test("los 16 parámetros que cambian el paquete mueven la huella", () => {
    for (const [nombre, parche] of INVALIDAN) {
      expect(conCambio(parche), `debería invalidar: ${nombre}`).not.toBe(HUELLA_BASE);
    }
  });

  test("los 10 que no salen del navegador NO la mueven", () => {
    for (const [nombre, parche] of NO_INVALIDAN) {
      expect(conCambio(parche), `NO debería invalidar: ${nombre}`).toBe(HUELLA_BASE);
    }
  });

  test("re-declarar el mismo estado da la MISMA huella (es estable, no de orden)", () => {
    expect(huellaDeInvalidacion(ESTADO_BASE as never)).toBe(HUELLA_BASE);
    const survey = [{ hole_id: "BH01", density_t_m3: 3.2, lithology: "magnetite" }];
    const a = conCambio({ store: { ...ESTADO_BASE.store, prepSondajes: survey } });
    const b = conCambio({ store: { ...ESTADO_BASE.store, prepSondajes: [...survey] } });
    expect(a).toBe(b);
    // Y el mismo survey con la densidad corregida NO es el mismo survey: contar
    // intervalos habría sido más barato y habría dejado pasar justo este caso.
    const corregido = [{ hole_id: "BH01", density_t_m3: 2.7, lithology: "granite" }];
    expect(conCambio({ store: { ...ESTADO_BASE.store, prepSondajes: corregido } })).not.toBe(a);
  });

  test("el número de parámetros declarados no baja en silencio", () => {
    // Un contador, no una derivación: si alguien retira una clave de una
    // declaración `*_INVALIDA` y la pasa a `*_NO_INVALIDA`, el typecheck sigue
    // verde y las dos tablas de arriba lo cazan sólo si esa clave está en ellas.
    // Esto caza el resto. Subirlo a mano al añadir un parámetro es el trabajo.
    expect(N_PARAMETROS_INVALIDANTES).toBe(34);
  });
});
