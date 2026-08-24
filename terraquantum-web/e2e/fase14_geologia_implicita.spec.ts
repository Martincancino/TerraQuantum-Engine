import { test, expect, Page } from "@playwright/test";

/**
 * FASE 14 (auditoría 06 §10) — El modelamiento implícito llega al usuario.
 * ============================================================================
 *
 * El criterio de aceptación de la fase tiene dos mitades y sólo una se mide con
 * un navegador:
 *
 *   · «un contacto geológico mapeado por el usuario acota la inversión» → esto.
 *   · «y se MIDE la mejora contra verdad conocida» → eso no se comprueba con
 *     Playwright sino con `scripts/validation/f14_implicit_geology_experiment.py`,
 *     y su respuesta está escrita en docs/06 §FASE 14: por el término de SUAVIDAD
 *     (cableado histórico) el prior empeora la recuperación; por el de SMALLNESS
 *     —el default desde esta fase— la mejora en 25 de 25 semillas.
 *
 * Lo que sí exige un navegador es lo segundo, que es donde esta fase se juega la
 * honestidad: **que lo que el prior hizo y lo que NO hizo se vea**. El motor ya
 * publicaba `report.implicit_geology`; hasta ahora no había pantalla, así que un
 * prior que declaraba el 85 % de la malla como unidad objetivo, o uno que era
 * exactamente inerte, se veían igual que uno bueno: no se veían.
 *
 * Como en el resto de la suite, el backend se sustituye en la frontera HTTP.
 */

const PROJECT = "proyecto_fase14";
const RUN = "run_fase14";

const CSV = [
  "x_m,y_m,z_m,gravity_mgal",
  ...Array.from({ length: 8 }, (_, i) => `${i * 25},0,${i * 15},${(0.1 + i * 0.37).toFixed(3)}`),
  "",
].join("\n");

function blockModelJson() {
  const cells = Array.from({ length: 8 }, (_, i) => ({
    x: i * 10, y: 10 + i * 5, z: 20,
    density: 2.6 + i * 0.05,
    density_t_m3: 2.6 + i * 0.05,
    susceptibility_si: 0.001 + i * 0.0002,
    probability: 0.5, visual_score: 0.4, sensitivity_proxy: 0.8,
  }));
  return {
    cells, domainL: 100, domainH: 60, domainW: 100, cellSize: 10,
    densityMin: 2.6, densityMax: 3.0, mode: "exploration",
    returned_voxels: cells.length, total_voxels: cells.length, warnings: [],
  };
}

/** El reporte tal como lo emite `_build_implicit_geology_reference` cuando el
 *  campo implícito DEGENERA: es el caso medido con un solo sondaje. */
const IMPLICIT_GEOLOGY_DEGENERADO = {
  enabled: true,
  binding: "m_ref (Li & Oldenburg reference model)",
  target_lithologies: ["kimberlite"],
  n_value_points: 3,
  n_contact_points: 1,
  n_orientations: 0,
  n_target_cells: 6800,
  n_total_cells: 8000,
  n_boreholes: 1,
  target_volume_fraction: 0.85,
  extrapolation_max_m: 403.1,
  degenerate_planar_field: true,
  inert_no_contrast: false,
  declared_std_is_inert: true,
  target_density_t_m3: 3.6,
  host_density_t_m3: 2.6,
  softness: 0,
  warnings: [
    "El campo implícito degeneró a un PLANO (los pesos RBF son ~0): los contactos disponibles no fijan curvatura.",
    "El prior declara unidad objetivo en el 85% de la malla, hasta 403 m del sondaje más cercano.",
  ],
};

function reportDetail(implicitGeology: unknown) {
  return {
    project_id: PROJECT,
    run_id: RUN,
    inputs: {},
    report: { status: "done", implicit_geology: implicitGeology },
  };
}

async function mockBackend(page: Page, implicitGeology: unknown) {
  await page.route("**/api/backend-health**", (r) => r.fulfill({ json: { online: true } }));
  await page.route("**/api/project-runs**", (r) => r.fulfill({ json: { projects: [] } }));
  await page.route("**/api/gravity-import/preview**", (r) =>
    r.fulfill({
      json: {
        status: "ok",
        stage: "preview",
        csv_analysis: {
          n_observations: 8,
          coordinate_system: { detected: "local_meters", confidence: "HIGH" },
        },
        spatial_readiness: { level: "OK", requires_user_acknowledgement: false },
        regional_scale_preflight: { can_run_single_inversion: true },
        errors: [],
        warnings: [],
      },
    }),
  );
  await page.route("**/api/gravity-import/load-package", (r) =>
    r.fulfill({ json: { status: "done", project_id: PROJECT, run_id: RUN, route: "gravity_only", errors: [] } }),
  );
  await page.route("**/api/block-model?**", (r) => r.fulfill({ json: blockModelJson() }));
  await page.route("**/api/block-model-zarr**", (r) => r.fulfill({ status: 404, json: {} }));
  await page.route("**/api/geophysics-status**", (r) =>
    r.fulfill({ json: { status: "done", stage: "done", progress: 1 } }),
  );
  await page.route("**/api/project-run-detail**", (r) => r.fulfill({ json: reportDetail(implicitGeology) }));
  for (const ruta of ["section", "isosurface", "boreholes", "doi-overlay", "terrain", "favorability"]) {
    await page.route(`**/api/${ruta}**`, (r) => r.fulfill({ status: 404, json: {} }));
  }
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

async function loadModelInViewer(page: Page) {
  await navTo(page, "figura 3D");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "paquete.tqpkg.csv", mimeType: "text/csv", buffer: Buffer.from("#CONFIG\n" + CSV),
  });
  await page.getByRole("button", { name: /Cargar modelo 3D/i }).click();
  await expect(page.getByText(/Modelo cargado/i)).toBeVisible({ timeout: 30_000 });
}

test.describe("Fase 14 — geología implícita", () => {
  test("el usuario ve QUÉ contacto acotó la inversión y hasta dónde se extrapoló", async ({ page }) => {
    await mockBackend(page, IMPLICIT_GEOLOGY_DEGENERADO);
    await enterApp(page);
    await loadModelInViewer(page);

    const panel = page.getByText("Geología implícita", { exact: true }).first();
    await expect(panel).toBeVisible({ timeout: 30_000 });

    // La unidad objetivo, el volumen que el prior declara y la extrapolación: los
    // tres números que deciden si uno se cree el resultado.
    await expect(page.getByText("kimberlite").first()).toBeVisible();
    await expect(page.getByText("85.0").first()).toBeVisible();
    await expect(page.getByText("403").first()).toBeVisible();

    // Y el aviso de que «la superficie» es un plano: es el hallazgo de la fase, y
    // vive donde el usuario decide, no en un README.
    await expect(page.getByText(/degeneró a un PLANO/i)).toBeVisible();
    await expect(page.getByText(/85% de la malla/i)).toBeVisible();
  });

  test("un prior inerte se declara inerte en vez de decir «activado»", async ({ page }) => {
    // MEDIDO: si φ clasifica toda la malla como una sola unidad, el m_ref es
    // constante y el término de suavidad lo anula EXACTO (L·1 = 0). El panel no
    // puede dar a entender que la geología hizo algo.
    await mockBackend(page, {
      ...IMPLICIT_GEOLOGY_DEGENERADO,
      n_target_cells: 0,
      target_volume_fraction: 0,
      extrapolation_max_m: 0,
      degenerate_planar_field: false,
      inert_no_contrast: true,
      warnings: ["El prior clasifica el 0% de la malla como una sola unidad: la inversión sale igual que sin prior."],
    });
    await enterApp(page);
    await loadModelInViewer(page);

    await expect(page.getByText(/El prior no actuó/i)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/misma que sin prior/i)).toBeVisible();
  });

  test("sin prior, el panel dice dónde se activa en vez de quedarse en blanco", async ({ page }) => {
    await mockBackend(page, null);
    await enterApp(page);
    await loadModelInViewer(page);

    await expect(page.getByText(/no usó prior geológico implícito/i)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/sondajes con litología/i)).toBeVisible();
  });

  test("sin sondajes con litología el botón está apagado y dice por qué", async ({ page }) => {
    await mockBackend(page, null);
    await enterApp(page);
    await navTo(page, "Preparación");
    // `PrepPanel` vive dentro de un <details> colapsado: hay que abrir «Avanzado»
    // antes de que sus controles existan en el DOM (gotcha de la Fase 1).
    await page.getByText(/Avanzado · parámetros de inversión/i).click();
    await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible({ timeout: 20_000 });

    // La «SECCIÓN DE INVERSIÓN» —donde viven los botones de parámetros avanzados—
    // sólo existe DESPUÉS de validar el CSV: sin dato no hay inversión que
    // configurar. Los inputs de fichero del panel son los índices 2 y 3 (0 y 1
    // son los de `PrepEnrichPanel`), otro gotcha heredado de la Fase 1.
    await page.locator('input[type="file"][accept=".csv"]').nth(2).setInputFiles({
      name: "gravimetria.csv", mimeType: "text/csv", buffer: Buffer.from(CSV, "utf-8"),
    });
    await page.getByRole("button", { name: /^Validar CSV$/i }).click();
    await expect(page.getByText(/Inversión 3D/i)).toBeVisible({ timeout: 20_000 });

    const boton = page.getByRole("button", { name: /Geología implícita/i });
    await expect(boton).toBeVisible({ timeout: 20_000 });
    await expect(boton).toBeDisabled();
    // El motivo no se esconde en un tooltip vacío: es la regla de la fase —sin
    // contactos no se infiere geología— y está escrita.
    await expect(boton).toHaveAttribute("title", /sin contactos no se infiere geología/i);
  });
});
