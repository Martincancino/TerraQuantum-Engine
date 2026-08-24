import { test, expect, Page } from "@playwright/test";

/**
 * FASE 13 (auditoría 06 §10) — Undo/redo, atajos y persistencia.
 * ============================================================================
 *
 * Los criterios de aceptación de la fase son tres, y aquí hay un recorrido por
 * cada uno más los que salieron al medir:
 *
 *   1. **Ctrl+Z / Ctrl+Y en las acciones de preparación y visualización.**
 *   2. **El historial no crece sin límite.**
 *   3. **No interfiere con corridas en curso.**
 *
 * Y tres invariantes que el diseño exige y que sólo se ven ejerciendo la
 * secuencia, no leyendo el código:
 *
 *   · **La barrera de archivos.** Cambiar de CSV BORRA el historial. No es una
 *     comodidad: H-29 fue un reconocimiento de riesgo marcado sobre el archivo A
 *     que viajaba al backend describiendo el archivo B, y un Ctrl+Z que cruzara
 *     ese límite lo resucitaría.
 *   · **El aislamiento de foco.** Dentro de un campo de texto manda el deshacer
 *     nativo del navegador; el historial de la aplicación no se lo roba.
 *   · **Deshacer no toca lo que vino del backend.** El modelo sigue en pantalla.
 *
 * Como en el resto de la suite, el backend se sustituye en la frontera HTTP: lo
 * que se afirma son invariantes de interfaz, y una inversión real de minutos no
 * los haría más ciertos.
 */

const PROJECT_A = "proyecto_fase13";
const RUN_A = "run_fase13";

const CSV_A = [
  "x_m,y_m,z_m,gravity_mgal",
  ...Array.from({ length: 8 }, (_, i) => `${i * 25},0,${i * 15},${(0.1 + i * 0.37).toFixed(3)}`),
  "",
].join("\n");

const CSV_B = [
  "x_m,y_m,z_m,gravity_mgal",
  ...Array.from({ length: 8 }, (_, i) => `${i * 30},0,${i * 12},${(5.4 + i * 0.41).toFixed(3)}`),
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

function previewJson() {
  return {
    status: "ok", stage: "preview",
    csv_analysis: { n_observations: 8, coordinate_system: { detected: "local_meters", confidence: "HIGH" } },
    spatial_readiness: { level: "OK", requires_user_acknowledgement: false },
    regional_scale_preflight: { can_run_single_inversion: true },
    errors: [], warnings: [],
  };
}

async function mockBackend(page: Page) {
  await page.route("**/api/backend-health**", (route) => route.fulfill({ json: { online: true } }));
  await page.route("**/api/project-runs**", (route) => route.fulfill({ json: { projects: [] } }));
  await page.route("**/api/gravity-import/preview**", (route) => route.fulfill({ json: previewJson() }));
  await page.route("**/api/gravity-import/load-package", (route) =>
    route.fulfill({
      json: { status: "done", project_id: PROJECT_A, run_id: RUN_A, route: "gravity_only", errors: [] },
    }),
  );
  await page.route("**/api/block-model?**", (route) => route.fulfill({ json: blockModelJson() }));
  await page.route("**/api/block-model-zarr**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/geophysics-status**", (route) =>
    route.fulfill({ json: { status: "done", stage: "done", progress: 1 } }),
  );
  await page.route("**/api/project-run-detail**", (route) =>
    route.fulfill({ json: { project_id: PROJECT_A, run_id: RUN_A, inputs: {}, report: { status: "done" } } }),
  );
  await page.route("**/api/section**", (route) =>
    route.fulfill({ json: { axis: "x", position: 0, width: 2, height: 2, values: [0, 1, 1, 0], vmin: 0, vmax: 1 } }),
  );
  await page.route("**/api/isosurface**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/boreholes**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/doi-overlay**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/terrain**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/favorability**", (route) => route.fulfill({ status: 404, json: {} }));
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

async function openAdvancedPanel(page: Page) {
  await page.getByText(/Avanzado · parámetros de inversión/i).click();
  await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible({ timeout: 10_000 });
}

async function loadModelInViewer(page: Page) {
  await navTo(page, "figura 3D");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "paquete.tqpkg.csv", mimeType: "text/csv", buffer: Buffer.from("#CONFIG\n" + CSV_A),
  });
  await page.getByRole("button", { name: /Cargar modelo 3D/i }).click();
  await expect(page.getByText(/Modelo cargado/i)).toBeVisible({ timeout: 30_000 });
}

const prepGravityInput = (page: Page) => page.locator('input[type="file"][accept=".csv"]').nth(2);
const densityMinInput = (page: Page) => page.locator('input[title^="Bound inferior absoluto"]');
const presetSelect = (page: Page) => page.locator('select[title^="Selecciona un preset"]');
const historialPrep = (page: Page) => page.getByTestId("historial-preparacion");
const historialVisor = (page: Page) => page.getByTestId("historial-visor");

/** El selector de eje del corte no tiene `data-testid`: se localiza por su
 *  etiqueta exacta dentro del panel, y el estado activo se lee por la clase de
 *  acento que usa todo el visor. Es el patrón de la casa cuando no hay testid. */
const ejeZ = (page: Page) => page.getByRole("button", { name: /^Z$/ }).first();

async function abrirPlanoDeCorte(page: Page) {
  // NO se pulsa la cabecera de la sección: `SidebarSection` viene con
  // `defaultOpen = true`, así que pulsarla la CIERRA y la animación de salida
  // de framer-motion desmonta los botones a media prueba. Basta con esperar a
  // que el contenido termine de entrar (la transición dura 0,25 s).
  await ejeZ(page).waitFor({ state: "visible", timeout: 20_000 });
  await expect(ejeZ(page)).toBeEnabled();
}

/** El teclado se manda al `body`: si se mandara al control que acaba de cambiar,
 *  el aislamiento de foco lo ignoraría — que es precisamente lo correcto y lo
 *  que comprueba el recorrido dedicado. */
async function pulsar(page: Page, combo: string) {
  await page.locator("body").click({ position: { x: 2, y: 2 } });
  await page.keyboard.press(combo);
}

test.describe("Fase 13 · deshacer, rehacer y recordar", () => {
  // ── CRITERIO 1: Ctrl+Z / Ctrl+Y en preparación ────────────────────────────

  test("Ctrl+Z deshace un preset de densidad y Ctrl+Y lo rehace", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    const min = densityMinInput(page);
    await expect(min).toBeVisible({ timeout: 20_000 });
    await expect(min).toHaveValue("0.0");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "no");

    // `PRESET_DENSIDAD` mueve TRES claves de golpe. El historial tiene que
    // tratarlas como UN comando: deshacer a medias dejaría «magnetita con los
    // bounds de antes», el estado intermedio que la Fase 10 vino a matar.
    await presetSelect(page).selectOption("magnetite");
    await expect(min).toHaveValue("4.5");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "si");
    await expect(historialPrep(page)).toHaveAttribute("data-tamano", "1");

    await pulsar(page, "Control+z");
    await expect(min).toHaveValue("0.0");
    await expect(page.locator('input[title^="Bound superior absoluto"]')).toHaveValue("5.5");
    await expect(presetSelect(page)).toHaveValue("custom");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "no");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-rehacer", "si");

    await pulsar(page, "Control+y");
    await expect(min).toHaveValue("4.5");
    await expect(presetSelect(page)).toHaveValue("magnetite");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-rehacer", "no");
  });

  test("los botones hacen lo mismo que los atajos y dicen qué desharían", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    await expect(densityMinInput(page)).toBeVisible({ timeout: 20_000 });
    await presetSelect(page).selectOption("copper");
    await expect(densityMinInput(page)).toHaveValue("4.3");

    // El criterio de la plantilla de gate: un usuario puede VERLO, no sólo
    // conocer el atajo por haber leído el código.
    await expect(page.getByTestId("historial-detalle-preparacion")).toContainText(
      /Preset de densidad/i,
    );
    await page.getByTestId("deshacer-preparacion").click();
    await expect(densityMinInput(page)).toHaveValue("0.0");
    await page.getByTestId("rehacer-preparacion").click();
    await expect(densityMinInput(page)).toHaveValue("4.3");
  });

  // ── El aislamiento de foco ────────────────────────────────────────────────

  test("dentro de un campo de texto manda el deshacer del navegador", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    const min = densityMinInput(page);
    await expect(min).toBeVisible({ timeout: 20_000 });
    await presetSelect(page).selectOption("granite");
    await expect(historialPrep(page)).toHaveAttribute("data-tamano", "1");

    // Con el foco DENTRO del campo, Ctrl+Z no puede consumir el historial de la
    // aplicación: ahí el usuario espera deshacer su tecleo.
    await min.click();
    await page.keyboard.press("Control+z");
    await expect(historialPrep(page)).toHaveAttribute("data-tamano", "1");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "si");
  });

  // ── CRITERIO 2: el historial no crece sin límite ──────────────────────────

  test("el historial se detiene en su techo por muchas acciones que haya", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);
    await expect(densityMinInput(page)).toBeVisible({ timeout: 20_000 });

    const presets = ["granite", "magnetite", "copper"];
    for (let i = 0; i < 60; i++) {
      await presetSelect(page).selectOption(presets[i % presets.length]);
    }

    // 60 comandos distintos, y el historial no puede tener 60.
    const tamano = Number(await historialPrep(page).getAttribute("data-tamano"));
    expect(tamano).toBeGreaterThan(0);
    expect(tamano).toBeLessThanOrEqual(50);
    // Control: si el techo no se aplicara, el número sería 60. Se afirma la
    // desigualdad estricta para que la prueba no pase por casualidad.
    expect(tamano).toBeLessThan(60);
  });

  // ── La barrera de archivos (H-29) ─────────────────────────────────────────

  test("cambiar de archivo BORRA el historial: un riesgo aceptado no vuelve", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    await prepGravityInput(page).setInputFiles({
      name: "a.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_A, "utf-8"),
    });
    const min = densityMinInput(page);
    await expect(min).toBeVisible({ timeout: 20_000 });

    await presetSelect(page).selectOption("magnetite");
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "si");

    await prepGravityInput(page).setInputFiles({
      name: "b.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_B, "utf-8"),
    });
    await expect(min).toBeVisible({ timeout: 20_000 });

    // No hay nada que deshacer al otro lado de la barrera, y el valor actual se
    // conserva: la barrera borra la HISTORIA, no el estado.
    await expect(historialPrep(page)).toHaveAttribute("data-puede-deshacer", "no");
    await expect(historialPrep(page)).toHaveAttribute("data-tamano", "0");
    await expect(min).toHaveValue("4.5");
  });

  // ── CRITERIO 1 (visualización) y 3 ────────────────────────────────────────

  test("deshacer en el visor revierte la capa y NO toca lo que vino del backend", async ({ page }) => {
    const errores: string[] = [];
    page.on("pageerror", (e) => errores.push(String(e)));

    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);

    // Al terminar la inversión el historial está vacío: la ráfaga de escrituras
    // con la que cierra la corrida NO es una acción del usuario, y además la
    // barrera de identidad de corrida acaba de dispararse.
    await expect(historialVisor(page)).toHaveAttribute("data-puede-deshacer", "no");

    await abrirPlanoDeCorte(page);
    await expect(ejeZ(page)).not.toHaveClass(/text-accent/);
    await ejeZ(page).click();
    await expect(ejeZ(page)).toHaveClass(/text-accent/);
    await expect(historialVisor(page)).toHaveAttribute("data-puede-deshacer", "si");

    await pulsar(page, "Control+z");
    // Lo que importa NO es que el contador baje, sino que el VALOR vuelva: un
    // deshacer que saca el comando de la pila sin aplicarlo pasaría la primera
    // comprobación y fallaría ésta.
    await expect(ejeZ(page)).not.toHaveClass(/text-accent/);
    await expect(historialVisor(page)).toHaveAttribute("data-puede-deshacer", "no");

    // Y rehacer lo devuelve.
    await pulsar(page, "Control+y");
    await expect(ejeZ(page)).toHaveClass(/text-accent/);

    // El modelo sigue en pantalla: deshacer una perilla visual no puede
    // arrastrar el resultado de la corrida.
    await expect(page.getByText(/Modelo cargado/i)).toBeVisible();

    const fatales = errores.filter((e) => !/fetch|network|Failed to fetch|Load failed|WebGL/i.test(e));
    expect(fatales, `errores de JS fatales: ${fatales.join(" | ")}`).toHaveLength(0);
  });

  // ── Persistencia de preferencias ──────────────────────────────────────────

  test("las preferencias de visualización sobreviven a una recarga", async ({ page }) => {
    test.setTimeout(180_000);
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);

    // El eje de corte es una preferencia pura: dice CÓMO quiere mirar el usuario,
    // no qué está mirando. (La POSICIÓN del corte no se guarda, y a propósito:
    // va en metros del modelo y heredarla sobre otra malla no significa nada.)
    await abrirPlanoDeCorte(page);
    await ejeZ(page).click();
    await expect(ejeZ(page)).toHaveClass(/text-accent/);

    const guardado = await page.evaluate(async () => {
      // El guardado va con retardo para no escribir en cada movimiento de un
      // slider; se espera a que haya pasado.
      await new Promise((r) => setTimeout(r, 900));
      return window.localStorage.getItem("tq.preferencias.visor.v1");
    });
    expect(guardado, "no se escribió la preferencia").toBeTruthy();
    const preferencias = JSON.parse(guardado as string) as Record<string, unknown>;
    expect(preferencias.sliceAxis).toBe("z");

    // Y lo que NO se guarda tampoco se guarda por accidente. Esto es el corazón
    // de la decisión: el resultado de una corrida no puede acabar en el
    // almacenamiento del navegador, ni por tamaño ni —sobre todo— porque
    // pertenece a UNA evaluación (H-28) y no puede sobrevivirla.
    for (const prohibida of ["model", "activeRun", "report", "isosurfaceData", "terrainData", "slicePosition"]) {
      expect(Object.keys(preferencias), `se persistió ${prohibida}`).not.toContain(prohibida);
    }

    // La prueba de verdad no es que el JSON siga en disco: es que al volver a
    // abrir la aplicación el usuario encuentre su ajuste puesto.
    await page.reload();
    await enterApp(page);
    await loadModelInViewer(page);
    await abrirPlanoDeCorte(page);
    await expect(ejeZ(page)).toHaveClass(/text-accent/);
  });

  test("un almacenamiento corrupto no rompe el arranque", async ({ page }) => {
    const errores: string[] = [];
    page.on("pageerror", (e) => errores.push(String(e)));

    await mockBackend(page);
    await page.goto("/");
    await page.evaluate(() => {
      // Entrada NO confiable: cualquiera puede escribir esto desde la consola, y
      // un enum inventado en el store rompería el visor al arrancar.
      window.localStorage.setItem(
        "tq.preferencias.visor.v1",
        JSON.stringify({ viewMode: "plasma", jointThreshold: 99, volumeRenderMode: 7 }),
      );
    });
    await page.reload();
    await enterApp(page);
    await navTo(page, "figura 3D");

    const fatales = errores.filter((e) => !/fetch|network|Failed to fetch|Load failed|WebGL/i.test(e));
    expect(fatales, `errores de JS fatales: ${fatales.join(" | ")}`).toHaveLength(0);
  });
});
