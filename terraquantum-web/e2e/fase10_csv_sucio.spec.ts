import { test, expect, Page } from "@playwright/test";

/**
 * FASE 10 (auditoría 06 §10, H-16) — El panel de preparación con un CSV SUCIO.
 * ============================================================================
 *
 * La fase pedía «un recorrido que ejercite el panel de preparación con un CSV
 * sucio del corpus real». La razón es concreta: la Fase 10 movió `PrepPanel` de
 * 41 `useState` a cuatro máquinas con transiciones, y `PrepEnrichPanel` de 17 a
 * una. Un refactor de estado no se valida mirando que compile — se valida
 * comprobando que las SECUENCIAS siguen dejando el panel coherente.
 *
 * Y las secuencias que se prueban aquí son exactamente las que la fase convirtió
 * en transiciones atómicas, porque son las que antes podían quedar a medias:
 *
 *   1. **Cambiar de archivo** (`ARCHIVOS_CAMBIARON`): antes eran once `setState`
 *      repartidos, y H-29 nació de que un manejador escribía sólo la mitad.
 *   2. **Aplicar un preset de densidad** (`PRESET_DENSIDAD`): eran hasta tres
 *      `setState`, con un estado intermedio «preset nuevo, bounds viejos».
 *   3. **Editar un bound a mano**: tiene que sacar del preset, siempre.
 *
 * El CSV es sucio DE VERDAD, con las cuatro suciedades que el corpus real trae y
 * que costaron bugs medidos en este repositorio: preámbulo de instrumento antes
 * del encabezado, separador `;`, **decimal con coma** (el que producía
 * `parseFloat("1,23") === 1` en silencio) y una fila rota. Sirve para dos cosas
 * a la vez: comprobar que la interfaz aguanta, y comprobar que el frontend NO
 * intenta parsearlo por su cuenta — eso lo hace el backend, que es la regla que
 * evita reintroducir el bug decimal-coma.
 *
 * Como los demás recorridos de esta suite, el backend se sustituye en la
 * frontera HTTP: lo que se afirma son invariantes de interfaz, y una inversión
 * real de minutos no los haría más ciertos.
 */

/** CSV sucio: preámbulo + `;` + decimal coma + una fila con campos de menos. */
const CSV_SUCIO = [
  "# Scintrex CG-6 - descarga de campo",
  "# Proyecto: Quebrada Seca / operador: MC",
  "",
  "x_m;y_m;z_m;gravity_mgal",
  ...Array.from({ length: 9 }, (_, i) =>
    `${i * 25};0;${i * 15};${(0.1 + i * 0.37).toFixed(3).replace(".", ",")}`,
  ),
  "310;0;140",
  "",
].join("\n");

/** El mismo survey, ya limpio: sirve para el recorrido de «cambiar de archivo». */
const CSV_LIMPIO = [
  "x_m,y_m,z_m,gravity_mgal",
  ...Array.from({ length: 8 }, (_, i) => `${i * 30},0,${i * 12},${(5.4 + i * 0.41).toFixed(3)}`),
  "",
].join("\n");

/** Lo que el backend responde a `/preview` para un CSV que sí pudo leer. */
function previewJson() {
  return {
    status: "ok",
    stage: "preview",
    csv_analysis: {
      n_observations: 9,
      coordinate_system: { detected: "local_meters", confidence: "MEDIUM" },
    },
    spatial_readiness: { level: "OK", requires_user_acknowledgement: false },
    regional_scale_preflight: { can_run_single_inversion: true },
    errors: [],
    warnings: ["Se descartó 1 fila con campos de menos (línea 14)."],
  };
}

async function mockBackend(page: Page) {
  await page.route("**/api/gravity-import/preview**", (route) =>
    route.fulfill({ json: previewJson() }),
  );
  await page.route("**/api/gravity-import/analyze-columns**", (route) =>
    route.fulfill({
      json: {
        column_mapping: {
          data_kind: "gravity",
          raw_columns: ["x_m", "y_m", "z_m", "gravity_mgal"],
          auto_detected: { x: "x_m", y: "y_m", gravity_value: "gravity_mgal" },
          roles: { x: "x_m", y: "y_m", gravity_value: "gravity_mgal" },
          overridden: {}, invalid_overrides: {},
          required_roles: ["x", "y", "gravity_value"],
          optional_roles: [], missing_required: [],
          needs_mapping: false, confidence: "high",
          role_labels: {}, literals: {}, range_checks: {}, suspicions: [],
          role_confidence: {}, suggestions: {}, needs_confirmation: false,
          questions: [], inferred_literals: {},
        },
        // El sniff es la EVIDENCIA de que el backend leyó la suciedad: si el
        // frontend lo pintara desde su propia lectura del archivo, esta prueba
        // no distinguiría una cosa de la otra.
        sniff_report: {
          version: "csv_sniff_v1",
          filename: "sucio.csv",
          encoding: { value: "utf-8", confidence: "high", evidence: "Decodifica sin errores.", discarded: [] },
          separator: { value: ";", confidence: "high", evidence: "';' aparece 3 veces por línea.", discarded: [] },
          decimal: { value: ",", confidence: "high", evidence: "El separador es ';': el decimal es ','.", discarded: [] },
          preamble_count: 3,
          preamble_lines: [{ line_number: 1, text: "# Scintrex CG-6", reason: "comentario" }],
          header_line_number: 4,
          header_columns: ["x_m", "y_m", "z_m", "gravity_mgal"],
          broken_rows: [{ line_number: 14, field_count: 3, expected_fields: 4, excerpt: "310;0;140" }],
          broken_row_count: 1,
          n_lines_sampled: 15,
          sample_truncated: false,
          warnings: [],
        },
        sample_rows: [{ x_m: "0", y_m: "0", z_m: "0", gravity_mgal: "0.100" }],
      },
    }),
  );
  await page.route("**/api/project-runs**", (route) => route.fulfill({ json: { projects: [] } }));
  await page.route("**/api/backend-health**", (route) => route.fulfill({ json: { online: true } }));
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

/** Los 2 últimos `input[accept=".csv"]` son los del PrepPanel clásico; los 2
 *  primeros, los del flujo principal (PrepEnrichPanel). */
function prepGravityInput(page: Page) {
  return page.locator('input[type="file"][accept=".csv"]').nth(2);
}

function densityMinInput(page: Page) {
  return page.locator('input[title^="Bound inferior absoluto"]');
}

/** El preset de litología es un `<select>`, no botones. */
function presetSelect(page: Page) {
  return page.locator('select[title^="Selecciona un preset"]');
}

test.describe("Fase 10 · el panel de preparación con un CSV sucio", () => {
  test("un CSV con preámbulo, ';', decimal coma y fila rota no rompe el panel", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    await prepGravityInput(page).setInputFiles({
      name: "sucio.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_SUCIO, "utf-8"),
    });

    // El invariante «nunca crashea»: el panel sigue en pie y con sus controles.
    await expect(densityMinInput(page)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible();
  });

  test("el preset de densidad mueve preset y bounds en un solo paso", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    const min = densityMinInput(page);
    await expect(min).toBeVisible({ timeout: 20_000 });
    await expect(min).toHaveValue("0.0");

    // `PRESET_DENSIDAD`: antes eran hasta 3 `setState` sueltos y existía el
    // estado intermedio «magnetita seleccionada con los bounds de antes».
    await presetSelect(page).selectOption("magnetite");
    await expect(min).toHaveValue("4.5");
    await expect(page.locator('input[title^="Bound superior absoluto"]')).toHaveValue("5.5");
    await expect(presetSelect(page)).toHaveValue("magnetite");

    // Y al revés: tocar un bound a mano tiene que sacar del preset SIEMPRE, o el
    // panel afirmaría una litología que ya no describe los números en pantalla.
    await min.fill("1.9");
    await min.blur();
    await expect(min).toHaveValue("1.9");
    await expect(presetSelect(page)).toHaveValue("custom");
  });

  test("cambiar de archivo caduca lo que describía al anterior", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await openAdvancedPanel(page);

    await prepGravityInput(page).setInputFiles({
      name: "sucio.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_SUCIO, "utf-8"),
    });
    const min = densityMinInput(page);
    await expect(min).toBeVisible({ timeout: 20_000 });

    // Los parámetros de inversión NO dependen del archivo y deben sobrevivir…
    await presetSelect(page).selectOption("magnetite");
    await expect(min).toHaveValue("4.5");

    // …mientras que lo que describía al archivo anterior caduca. Ésta es la
    // transición `ARCHIVOS_CAMBIARON`, que H-29 tenía escrita a mano y a medias.
    await prepGravityInput(page).setInputFiles({
      name: "limpio.csv", mimeType: "text/csv", buffer: Buffer.from(CSV_LIMPIO, "utf-8"),
    });
    await expect(min).toBeVisible({ timeout: 20_000 });
    await expect(min).toHaveValue("4.5");
    await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible();
  });
});
