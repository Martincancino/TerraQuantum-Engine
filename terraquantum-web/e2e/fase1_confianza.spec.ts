import { test, expect, Page } from "@playwright/test";

/**
 * FASE 1 (auditoría 06 §10) — Los bugs de confianza del camino dorado.
 * =====================================================================
 *
 * Los tres recorridos de aceptación que la fase exige, uno por bug:
 *
 *  (a) H-28 — CSV A → invertir → volver a Preparación → CSV B → vista 3D:
 *      NO debe haber modelo. Antes se seguía pintando el modelo de A sin
 *      ninguna señal de que no correspondía a B.
 *  (b) H-29 — reconocer el riesgo espacial con el archivo A → cambiar el
 *      magnético → la casilla se desmarca y el botón queda deshabilitado.
 *  (c) H-27 — corrida con topografía degradada a plana → el aviso APARECE
 *      en pantalla (vista 3D y reporte), no sólo en el log del backend.
 *
 * El backend se sustituye en la frontera HTTP (`page.route`): estos recorridos
 * verifican INVARIANTES DE LA INTERFAZ, y una inversión real tarda minutos y no
 * los haría más ciertos. Las mitades de backend (rechazo de modos fantasma,
 * emisión del aviso de topografía) están cubiertas por pytest:
 * `tests/test_fase1_confianza_camino_dorado.py`.
 */

const PROJECT_A = "pytest_fase1_A";
const RUN_A = "run_fase1_A";

const TOPO_WARNING =
  "Topografía degradada a PLANA: la interpolación de la superficie desde las " +
  "elevaciones de los sensores falló y la inversión se resolvió asumiendo terreno " +
  "horizontal.";

/** CSV mínimo que supera el validador local de PrepPanel (≥5 estaciones, columna
 *  de dato reconocida, posiciones distintas y rango no nulo). */
function csvFixture(column: "gravity_mgal" | "magnetic_nt", offset: number): string {
  const rows = Array.from({ length: 8 }, (_, i) =>
    `${i * 25},0,${i * 15},${(offset + i * 0.37).toFixed(3)}`,
  );
  return `x_m,y_m,z_m,${column}\n${rows.join("\n")}\n`;
}

const CSV_A = csvFixture("gravity_mgal", 0.1);
const CSV_B = csvFixture("gravity_mgal", 5.4);
const CSV_MAG = csvFixture("magnetic_nt", 120);

/** Block model mínimo pero válido (el visor exige celdas para pintar). */
function blockModelJson() {
  const cells = [];
  for (let i = 0; i < 8; i++) {
    cells.push({
      x: i * 10, y: 10 + i * 5, z: 20,
      density: 2.6 + i * 0.05,
      density_t_m3: 2.6 + i * 0.05,
      probability: 0.5,
      visual_score: 0.4,
      sensitivity_proxy: 0.8,
    });
  }
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

/** Reporte persistido de la corrida; `warnings` es el canal de H-27. */
function runDetailJson(warnings: string[]) {
  return {
    project_id: PROJECT_A,
    run_id: RUN_A,
    inputs: { depth: 300, region: "norte_chile" },
    report: {
      status: "done",
      warnings,
      topography_used: warnings.length > 0 ? "flat_fallback" : "from_sensor_elevations_masl[linear]",
      topography_degraded: warnings.length > 0,
      technicalSummary: { overall_level: "MEDIUM", summary: "Corrida de prueba.", warnings },
      misfit_error_percent: 3.2,
      best_target: { x_m: 40, y_m: 30, z_m: 20, probability: 0.6 },
      observationQuality: { observation_count: 3 },
    },
  };
}

/** Preview de validación; `ack` fuerza el gate de reconocimiento espacial. */
function previewJson(ack: boolean) {
  return {
    status: "ok",
    previewCount: 3,
    totalObservations: 3,
    observationsPreview: [],
    importMetadata: { gravity_type: "complete_bouguer_anomaly" },
    warnings: [],
    errors: [],
    spatial_readiness: ack
      ? {
          level: "DEGRADED_LOCAL",
          requires_user_acknowledgement: true,
          reason: "Coordenadas locales sin georreferencia absoluta.",
        }
      : { level: "OK", requires_user_acknowledgement: false },
  };
}

/** Sustituye el backend en la frontera HTTP. */
async function mockBackend(page: Page, opts: { warnings?: string[]; ack?: boolean } = {}) {
  const warnings = opts.warnings ?? [];
  const ack = opts.ack ?? false;

  await page.route("**/api/gravity-import/preview", (route) =>
    route.fulfill({ json: previewJson(ack) }),
  );
  await page.route("**/api/gravity-import/load-package", (route) =>
    route.fulfill({
      json: { status: "done", project_id: PROJECT_A, run_id: RUN_A, route: "gravity_only", errors: [] },
    }),
  );
  await page.route("**/api/block-model?**", (route) => route.fulfill({ json: blockModelJson() }));
  await page.route("**/api/block-model-zarr**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/project-run-detail**", (route) =>
    route.fulfill({ json: runDetailJson(warnings) }),
  );
  await page.route("**/api/geophysics-status**", (route) =>
    route.fulfill({ json: { status: "done", stage: "done", progress: 1 } }),
  );
  // Ruido de la vista que no afecta a lo que se afirma aquí.
  await page.route("**/api/terrain**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/favorability**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/project-runs**", (route) => route.fulfill({ json: { projects: [] } }));
}

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

/** Zonas de carga del flujo PRINCIPAL (PrepEnrichPanel), siempre visibles. */
function enrichFileInput(page: Page, kind: "gravity" | "magnetic") {
  return page.locator('input[type="file"][accept=".csv"]').nth(kind === "gravity" ? 0 : 1);
}

/** El flujo clásico (PrepPanel) vive bajo el desplegable «Avanzado». */
async function openAdvancedPanel(page: Page) {
  const summary = page.getByText(/Avanzado · parámetros de inversión/i);
  await summary.click();
  await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible({ timeout: 10_000 });
}

/** Inputs de archivo del PrepPanel clásico (los 2 últimos con accept=".csv"). */
function prepFileInput(page: Page, kind: "gravity" | "magnetic") {
  const all = page.locator('input[type="file"][accept=".csv"]');
  return kind === "gravity" ? all.nth(2) : all.nth(3);
}

/** Carga un modelo en el visor por la vía real (LoadPanel → paquete → block model). */
async function loadModelInViewer(page: Page) {
  await navTo(page, "figura 3D");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "paquete.tqpkg.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("#CONFIG\n" + CSV_A),
  });
  await page.getByRole("button", { name: /Cargar modelo 3D/i }).click();
  await expect(page.getByText(/Modelo cargado/i)).toBeVisible({ timeout: 30_000 });
}

test.describe("Fase 1 · bugs de confianza del camino dorado", () => {
  // (a) H-28 ────────────────────────────────────────────────────────────────
  test("H-28: cambiar de CSV invalida el modelo 3D de la corrida anterior", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);

    // El modelo de la corrida A está en pantalla.
    await expect(page.getByText(/Run: /)).toBeVisible();
    await expect(page.getByTestId("viewport-empty-state")).toHaveCount(0);

    // El usuario vuelve a Preparación y elige OTRO CSV (flujo principal).
    await navTo(page, "Preparación");
    await enrichFileInput(page, "gravity").setInputFiles({
      name: "survey_B.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_B),
    });

    // Vuelve a la vista 3D SIN pasar por el panel de carga: no puede haber modelo.
    await navTo(page, "figura 3D");
    await expect(page.getByTestId("viewport-empty-state")).toBeVisible();
    await expect(page.getByText(/Sin modelo/i)).toBeVisible();
    await expect(page.getByText(/Modelo cargado/i)).toHaveCount(0);
  });

  test("H-28: también en el flujo clásico (PrepPanel, «Avanzado»)", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);
    await expect(page.getByTestId("viewport-empty-state")).toHaveCount(0);

    await navTo(page, "Preparación");
    await openAdvancedPanel(page);
    await prepFileInput(page, "gravity").setInputFiles({
      name: "survey_B.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_B),
    });

    await navTo(page, "figura 3D");
    await expect(page.getByTestId("viewport-empty-state")).toBeVisible();
  });

  // (b) H-29 ────────────────────────────────────────────────────────────────
  test("H-29: el reconocimiento de riesgo no sobrevive al cambio del archivo magnético", async ({ page }) => {
    await mockBackend(page, { ack: true });
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    await prepFileInput(page, "gravity").setInputFiles({
      name: "survey_A.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_A),
    });
    await page.getByRole("button", { name: /^Validar CSV$/i }).click();

    const ackBox = page.locator('input[type="checkbox"].accent-yellow-500').first();
    await expect(ackBox).toBeVisible({ timeout: 20_000 });
    await expect(ackBox).not.toBeChecked();

    const generate = page.getByRole("button", { name: /Generar paquete CSV/i });
    await expect(generate).toBeDisabled();
    await ackBox.check();
    await expect(generate).toBeEnabled();

    // El usuario sustituye el archivo MAGNÉTICO: el reconocimiento se refería a
    // otra configuración de entrada, así que tiene que caducar.
    await prepFileInput(page, "magnetic").setInputFiles({
      name: "mag_B.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_MAG),
    });
    await expect(generate).toHaveCount(0); // el panel de resultado se invalida entero

    // Y al re-validar, la casilla vuelve DESMARCADA (no es sólo que se ocultara).
    await page.getByRole("button", { name: /Validar CSV/i }).click();
    const ackBoxAfter = page.locator('input[type="checkbox"].accent-yellow-500').first();
    await expect(ackBoxAfter).toBeVisible({ timeout: 20_000 });
    await expect(ackBoxAfter).not.toBeChecked();
    await expect(page.getByRole("button", { name: /Generar paquete CSV/i })).toBeDisabled();
  });

  // (c) H-27 ────────────────────────────────────────────────────────────────
  test("H-27: la topografía degradada a plana se ve en pantalla", async ({ page }) => {
    await mockBackend(page, { warnings: [TOPO_WARNING] });
    await enterApp(page);
    await loadModelInViewer(page);

    // Vista 3D: el aviso llega a la columna donde se mira el modelo.
    const banner = page.getByTestId("run-warnings");
    await expect(banner).toBeVisible({ timeout: 20_000 });
    await expect(banner).toContainText(/Topograf[ií]a degradada a PLANA/i);

    // Reporte: el mismo aviso, sin dos versiones de la verdad.
    await navTo(page, "Datos");
    const datosBanner = page.getByTestId("datos-run-warnings");
    await expect(datosBanner).toBeVisible({ timeout: 20_000 });
    await expect(datosBanner).toContainText(/Topograf[ií]a degradada a PLANA/i);
  });

  test("H-27: sin degradación no se inventa ningún aviso", async ({ page }) => {
    await mockBackend(page, { warnings: [] });
    await enterApp(page);
    await loadModelInViewer(page);
    await expect(page.getByTestId("run-warnings")).toHaveCount(0);
  });

  // Extra §9H.2 ─────────────────────────────────────────────────────────────
  test("stale: cambiar un parámetro tras invertir marca el resultado como desactualizado", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);
    await expect(page.getByTestId("stale-result-badge")).toHaveCount(0);

    // Mover un parámetro de inversión en Preparación (sin tocar los archivos):
    // el bound inferior de densidad cambia el problema que se resolvió.
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);
    const densityMin = page.locator('input[title^="Bound inferior absoluto"]');
    await expect(densityMin).toBeVisible({ timeout: 20_000 });
    await densityMin.fill("0.4");
    await densityMin.blur();

    await navTo(page, "figura 3D");
    await expect(page.getByTestId("stale-result-badge")).toBeVisible({ timeout: 20_000 });
  });
});
