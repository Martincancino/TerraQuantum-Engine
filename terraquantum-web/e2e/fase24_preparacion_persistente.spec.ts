import { test, expect, Page } from "@playwright/test";

/**
 * FASE 24 (plan 15-26) — La preparación deja de evaporarse.
 * ============================================================================
 *
 * Los dos defectos que esta fase cierra, y por qué hacen falta un navegador y
 * no un test de unidad:
 *
 *   · **NUEVO-2** — `app/page.tsx:55` monta las vistas por igualdad de string,
 *     así que cambiar de pestaña DESMONTA `PreparacionView` y con ella todo su
 *     estado local: el archivo del flujo principal, el mapeo de columnas, los
 *     puntos Helmert, los sondajes y los 25 campos de `PrepPanel`
 *     (10 de contexto + 15 de inversión).
 *   · **NUEVO-3** — el CSV corregido por el asistente de gravimetría vive en la
 *     misma máquina de estado, así que se evapora con ella, y
 *     `handleGeneratePackage` hace `correctedFile ?? file`: el paquete se rearma
 *     sobre el CSV CRUDO. **Y no sólo el fichero**: `allow_g_raw` se enciende
 *     con `correctedFile !== null`, de modo que el backend recibe además una
 *     CONFIGURACIÓN distinta.
 *
 * Ninguna de las dos cosas se ve leyendo un componente: se ven ejerciendo la
 * secuencia montar → trabajar → desmontar → volver, que es lo que hace un
 * usuario cuando corrige un CSV y se va a mirar el 3D.
 *
 * La afirmación más dura de este archivo es la del recorrido C: **se intercepta
 * el `multipart/form-data` de `/api/gravity-import/build-package` y se lee el
 * contenido del fichero adjunto**. Comprobar que el botón sigue habilitado o que
 * la insignia sigue en pantalla no distingue «el corregido viaja» de «el
 * corregido se ve y viaja el crudo», que es exactamente el defecto.
 *
 * La otra pestaña es `inicio` a propósito: MEDIDO, `HomeView` no tiene ni un
 * `fetch` ni un `useEffect`, así que el desmontaje es lo único que se está
 * probando. `figura 3D` habría metido peticiones de red en medio.
 *
 * Como en el resto de la suite, el backend se sustituye en la frontera HTTP.
 */

// ─── Datos ───────────────────────────────────────────────────────────────────

/** Cabeceras legibles por las DOS piezas: los alias del asistente de
 *  correcciones (`GravityCorrectionWizard.tsx:17-33`) y el validador local de
 *  `PrepPanel` (`parseCsvForValidation`, `:189-205`). */
const CSV_CRUDO = [
  "station_id,lat,lon,elevation_m,gravity_mgal",
  ...Array.from(
    { length: 9 },
    (_, i) =>
      `ST_${i},${(-23.5 - i * 0.01).toFixed(2)},${(-68.2 - i * 0.01).toFixed(2)},${3000 + i * 10},${(10.1 + i * 0.37).toFixed(3)}`,
  ),
  "",
].join("\n");

/** La cabecera que el asistente escribe (`buildCorrectedCsv`, `:103`) y la
 *  columna de salida (`outputGravityColName`, `:88`). Son la huella del CSV
 *  CORREGIDO. */
const MARCA_CORREGIDO = "# Corrected gravity CSV";
const COLUMNA_CORREGIDA = "complete_bouguer_anomaly";
/** Y la del CRUDO: una columna que el corregido no tiene. */
const COLUMNA_CRUDA = "gravity_mgal";

const FILAS_PARSEADAS = Array.from({ length: 9 }, (_, i) => ({
  station_id: `ST_${i}`,
  lat: (-23.5 - i * 0.01).toFixed(2),
  lon: (-68.2 - i * 0.01).toFixed(2),
  elevation_m: String(3000 + i * 10),
  gravity_mgal: (10.1 + i * 0.37).toFixed(3),
}));

function sniffJson() {
  return {
    version: "csv_sniff_v1",
    filename: "crudo.csv",
    encoding: { value: "utf-8", confidence: "high", evidence: "Decodifica sin errores.", discarded: [] },
    separator: { value: ",", confidence: "high", evidence: "',' aparece 4 veces por línea.", discarded: [] },
    decimal: { value: ".", confidence: "high", evidence: "El separador es ',': el decimal es '.'.", discarded: [] },
    preamble_count: 0,
    preamble_lines: [],
    header_line_number: 1,
    header_columns: ["station_id", "lat", "lon", "elevation_m", "gravity_mgal"],
    broken_rows: [],
    broken_row_count: 0,
    n_lines_sampled: 10,
    sample_truncated: false,
    warnings: [],
  };
}

/** Plan de mapeo con los roles SIN resolver: el usuario los asigna a mano, y eso
 *  es justo lo que tiene que sobrevivir al cambio de pestaña. */
function mappingPlanJson() {
  return {
    data_kind: "gravity",
    raw_columns: ["station_id", "lat", "lon", "elevation_m", "gravity_mgal"],
    auto_detected: {}, roles: {}, overridden: {}, invalid_overrides: {},
    required_roles: ["x", "y", "gravity_value"],
    optional_roles: ["z"],
    missing_required: ["x", "y", "gravity_value"],
    needs_mapping: true, confidence: "low",
    role_labels: { x: "Este / X", y: "Norte / Y", z: "Cota / Z", gravity_value: "Gravedad" },
    literals: {}, range_checks: {}, suspicions: [], role_confidence: {},
    suggestions: {}, needs_confirmation: false, questions: [], inferred_literals: {},
  };
}

function previewJson() {
  return {
    status: "ok",
    stage: "preview",
    csv_analysis: {
      n_observations: 9,
      coordinate_system: { detected: "geographic", confidence: "HIGH" },
    },
    spatial_readiness: { level: "OK", requires_user_acknowledgement: false },
    regional_scale_preflight: { can_run_single_inversion: true, requires_user_acknowledgement: false },
    errors: [],
    warnings: [],
  };
}

/** Respuesta de `/api/gravity-corrections/apply`. El asistente la pide dos veces
 *  (5 estaciones para la vista previa, todas al aplicar), así que se responde
 *  con tantas como llegaron para que los contadores de la UI cuadren. */
function correccionesJson(n: number) {
  return {
    output_gravity_type: "complete_bouguer_anomaly",
    corrected: Array.from({ length: n }, (_, i) => ({
      station_id: `ST_${i}`,
      lat_deg: -23.5 - i * 0.01,
      lon_deg: -68.2 - i * 0.01,
      elev_m: 3000 + i * 10,
      g_obs_mgal: 978120.1 + i * 0.5,
      gamma_mgal: 978100.0,
      fac_mgal: 925.5 + i * 3.1,
      bc_mgal: 335.7 + i * 1.1,
      tc_mgal: 1.2 + i * 0.01,
      g_bouguer_mgal: 12.345 + i * 0.5,
      uncertainty_mgal: 0.02,
      gravity_type: "complete_bouguer_anomaly",
    })),
    report: {
      n_stations: n,
      corrections_applied: ["latitude", "free_air", "bouguer", "terrain"],
      reduction_density_gcc: 2.67,
      dem_source: "COP30",
      terrain_radius_m: 22000,
      fac_min_mgal: 925.5, fac_max_mgal: 950.3,
      bc_min_mgal: 335.7, bc_max_mgal: 344.5,
      tc_min_mgal: 1.2, tc_max_mgal: 1.28,
      g_bouguer_min_mgal: 12.345, g_bouguer_max_mgal: 16.345,
      warnings: [],
    },
  };
}

// ─── Sustitución del backend en la frontera HTTP ─────────────────────────────

async function mockBackend(page: Page) {
  await page.route("**/api/backend-health**", (r) => r.fulfill({ json: { online: true } }));
  await page.route("**/api/project-runs**", (r) => r.fulfill({ json: { projects: [] } }));
  await page.route("**/api/multimodal/plan**", (r) =>
    r.fulfill({ json: { plan: null, insufficient_reason: "Sin datos suficientes." } }),
  );
  await page.route("**/api/gravity-import/preview**", (r) => r.fulfill({ json: previewJson() }));
  await page.route("**/api/gravity-import/analyze-columns**", (r) =>
    r.fulfill({
      json: {
        column_mapping: mappingPlanJson(),
        sniff_report: sniffJson(),
        sample_rows: FILAS_PARSEADAS.slice(0, 3),
      },
    }),
  );
  await page.route("**/api/gravity-import/parse-rows**", (r) =>
    r.fulfill({
      json: {
        headers: ["station_id", "lat", "lon", "elevation_m", "gravity_mgal"],
        rows: FILAS_PARSEADAS,
        n_rows: FILAS_PARSEADAS.length,
        truncated: false,
        sniff_report: sniffJson(),
      },
    }),
  );
  await page.route("**/api/borehole/parse-file**", (r) =>
    r.fulfill({
      json: {
        survey: {
          holes: [
            {
              hole_id: "BH01", x_m: 50, z_m: 50,
              depth_from_m: 0, depth_to_m: 30, sample_type: "core",
              density_t_m3: 3.2, density_uncertainty: 0.15,
              lithology: "magnetite", susceptibility_si: null, comment: "",
            },
          ],
          crs: "local",
          datum_elevation_m: 0,
        },
        n_holes: 1, n_samples: 1, n_with_density: 1,
        n_with_susceptibility: 0, n_with_lithology: 1,
        lithologies_detected: ["magnetite"], unrecognized_lithologies: [],
      },
    }),
  );
  await page.route("**/api/gravity-corrections/apply**", async (r) => {
    let n = FILAS_PARSEADAS.length;
    try {
      const body = JSON.parse(r.request().postData() ?? "{}");
      if (Array.isArray(body.stations)) n = body.stations.length;
    } catch {
      /* el cuerpo siempre es JSON aquí; si no lo fuera, el total es inocuo */
    }
    await r.fulfill({ json: correccionesJson(n) });
  });
}

// ─── Navegación y aperturas ──────────────────────────────────────────────────

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

/** Salir de «Preparación» y volver. Es LA operación que esta fase defiende. */
async function darLaVuelta(page: Page) {
  await navTo(page, "inicio");
  await expect(page.getByText(/Avanzado · parámetros de inversión/i)).toHaveCount(0);
  await navTo(page, "Preparación");
}

/** `PrepPanel` vive dentro de un `<details>` colapsado. Al volver de otra
 *  pestaña el `<details>` es un elemento NUEVO y vuelve cerrado: eso es estado
 *  del DOM, no del usuario, y NO es lo que esta fase persigue. Hay que reabrirlo
 *  o las aserciones fallarían por invisibilidad y no por pérdida de estado. */
async function abrirAvanzado(page: Page) {
  await page.getByText(/Avanzado · parámetros de inversión/i).click();
  await expect(page.getByText(/^CSV Gravimetría$/i)).toBeVisible({ timeout: 20_000 });
}

/** Orden real en el DOM: 0 y 1 son las zonas de carga del flujo principal
 *  (`PrepEnrichPanel`); 2 y 3, las del `PrepPanel` clásico. El de sondajes queda
 *  fuera del filtro porque su `accept` incluye `.omf`. */
const enrichGravityInput = (page: Page) => page.locator('input[type="file"][accept=".csv"]').nth(0);
const prepGravityInput = (page: Page) => page.locator('input[type="file"][accept=".csv"]').nth(2);
const prepMagneticInput = (page: Page) => page.locator('input[type="file"][accept=".csv"]').nth(3);

const densityMinInput = (page: Page) => page.locator('input[title^="Bound inferior absoluto"]');
const densityMaxInput = (page: Page) => page.locator('input[title^="Bound superior absoluto"]');
const presetSelect = (page: Page) => page.locator('select[title^="Selecciona un preset"]');
const previewLimitInput = (page: Page) =>
  page.locator('input[type="number"][min="1"][max="100"]');
/** Los dos `<select>` de gravímetro se distinguen por el texto de sus opciones:
 *  el del panel clásico declara el piso de ruido en mGal. */
const gravimetroPrep = (page: Page) =>
  page.locator("select").filter({ hasText: "0.020 mGal" });
const rocaEsperada = (page: Page) =>
  page.locator("select").filter({ hasText: "Cobre / pórfido" });

function csvAdjunto(nombre: string, contenido: string) {
  return { name: nombre, mimeType: "text/csv", buffer: Buffer.from(contenido, "utf-8") };
}

// ─── Pasos compuestos ────────────────────────────────────────────────────────

/** Deja el panel clásico con un CSV cargado y validado (la SECCIÓN DE INVERSIÓN
 *  sólo existe tras validar) y las perillas en valores que NO son los de
 *  fábrica. Toca las dos máquinas con historial: `parametros` y `contexto`. */
async function prepararPanelClasico(page: Page) {
  await abrirAvanzado(page);
  await prepGravityInput(page).setInputFiles(csvAdjunto("crudo.csv", CSV_CRUDO));
  await expect(densityMinInput(page)).toBeVisible({ timeout: 20_000 });

  // `parametros`: un preset (que mueve TRES claves de golpe) y un número.
  await presetSelect(page).selectOption("magnetite");
  await expect(densityMinInput(page)).toHaveValue("4.5");
  await previewLimitInput(page).fill("33");

  // `contexto`: el gravímetro es una declaración del usuario sobre su survey.
  await gravimetroPrep(page).selectOption("scintrex_cg6");

  await page.getByRole("button", { name: /^Validar CSV$/i }).click();
  await expect(page.getByText(/Inversión 3D/i)).toBeVisible({ timeout: 20_000 });

  // `contexto`: la roca esperada vive dentro de la SECCIÓN DE INVERSIÓN.
  await rocaEsperada(page).selectOption("granito");
}

/** Recorre los cuatro pasos del asistente y deja el CSV corregido en el panel.
 *  La insignia «Correcciones aplicadas» es la señal de que `correctedFile` vive. */
async function aplicarCorrecciones(page: Page) {
  await page.getByRole("button", { name: /Aplicar correcciones geofísicas/i }).click();
  await expect(page.getByText(/Paso 1\/4/i)).toBeVisible({ timeout: 20_000 });
  // El mapeo del asistente se auto-detecta de las cabeceras, así que «Siguiente»
  // ya está activo sin tocar nada.
  await page.getByRole("button", { name: /Siguiente →/ }).click();
  await expect(page.getByText(/Paso 2\/4/i)).toBeVisible();
  await page.getByRole("button", { name: /Siguiente →/ }).click();
  await expect(page.getByText(/Paso 3\/4/i)).toBeVisible();
  await page.getByRole("button", { name: /Ver vista previa →/ }).click();
  await expect(page.getByText(/Paso 4\/4/i)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: /Aplicar a \d+ estaciones/ }).click();
  await expect(page.getByText(/Correcciones aplicadas/i)).toBeVisible({ timeout: 20_000 });
}

/** Lo que de verdad viajó: el adjunto llamado `file` del multipart, su nombre y
 *  el query string. Se trocea en `latin1` (byte a byte) y sólo el contenido se
 *  re-decodifica a utf-8, para no romper el em-dash de la cabecera. */
type PaqueteCapturado = { filename: string | null; contenido: string; qs: URLSearchParams };

async function interceptarPaquete(page: Page, destino: { valor: PaqueteCapturado | null }) {
  await page.route("**/api/gravity-import/build-package**", async (route) => {
    const req = route.request();
    const buf = req.postDataBuffer();
    const ct = req.headers()["content-type"] ?? "";
    const boundary = /boundary=(.+)$/.exec(ct)?.[1];
    let filename: string | null = null;
    let contenido = "";
    if (buf && boundary) {
      const crudo = buf.toString("latin1");
      for (const parte of crudo.split("--" + boundary)) {
        const m = /Content-Disposition: form-data; name="file"(?:; filename="([^"]*)")?/i.exec(parte);
        if (!m) continue; // ignora config_json / boreholes_json / magnetic_file
        filename = m[1] ?? null;
        const i = parte.indexOf("\r\n\r\n");
        contenido = Buffer.from(parte.slice(i + 4).replace(/\r\n$/, ""), "latin1").toString("utf8");
      }
    }
    destino.valor = { filename, contenido, qs: new URL(req.url()).searchParams };
    await route.fulfill({
      status: 200,
      contentType: "text/csv; charset=utf-8",
      headers: {
        "content-disposition": 'attachment; filename="paquete.tqpkg.csv"',
        "x-tq-package-route": "gravity_only",
      },
      body: "#TQPKG\nx_m,y_m,z_m,gravity_mgal\n0,0,0,1.0\n",
    });
  });
}

// ─── Recorridos ──────────────────────────────────────────────────────────────

test.describe("Fase 24 · la preparación no se evapora al cambiar de pestaña", () => {
  // ── A · NUEVO-2, flujo clásico: los parámetros ────────────────────────────

  test("A · los parámetros de inversión y de contexto siguen ahí al volver", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await prepararPanelClasico(page);

    await darLaVuelta(page);
    await abrirAvanzado(page);

    // `parametros`: los bounds (que llegaron juntos por `PRESET_DENSIDAD`), el
    // preset que los explica y el límite de vista previa. Con el defecto vivo
    // vuelven a 0.0 / 5.5 / custom / 20.
    await expect(densityMinInput(page)).toHaveValue("4.5");
    await expect(densityMaxInput(page)).toHaveValue("5.5");
    await expect(presetSelect(page)).toHaveValue("magnetite");
    await expect(previewLimitInput(page)).toHaveValue("33");

    // `contexto`: el gravímetro, y la roca esperada — que sigue en pantalla sin
    // revalidar porque `gravityPreviewResult` ya vivía en el store.
    await expect(gravimetroPrep(page)).toHaveValue("scintrex_cg6");
    await expect(page.getByText(/Inversión 3D/i)).toBeVisible({ timeout: 20_000 });
    await expect(rocaEsperada(page)).toHaveValue("granito");
  });

  // ── B · NUEVO-2, flujo principal: archivo, mapeo y Helmert ────────────────

  test("B · el archivo, el mapeo de columnas y los puntos Helmert siguen ahí", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");

    await enrichGravityInput(page).setInputFiles(csvAdjunto("crudo.csv", CSV_CRUDO));
    await expect(page.getByText("✓ crudo.csv")).toBeVisible({ timeout: 20_000 });

    // Puntos de control Helmert: dos pares locales ↔ reales.
    await page.getByText(/Georreferenciar coordenadas locales/i).click();
    const localXY = page.locator('input[placeholder="0"]');
    const realE = page.locator('input[placeholder="500000"]');
    const realN = page.locator('input[placeholder="7000000"]');
    await localXY.nth(0).fill("0");
    await localXY.nth(1).fill("0");
    await realE.nth(0).fill("500000");
    await realN.nth(0).fill("7000000");
    await localXY.nth(2).fill("1000");
    await localXY.nth(3).fill("1000");
    await realE.nth(1).fill("501000");
    await realN.nth(1).fill("7001000");
    await expect(page.getByText(/2 puntos válidos/i)).toBeVisible();

    // Mapeo manual: el usuario decide qué columna cumple cada rol.
    await page.getByRole("button", { name: /^Mapear columnas$/i }).click();
    await expect(page.getByRole("heading", { name: "Mapeo manual de columnas" })).toBeVisible({
      timeout: 20_000,
    });
    await page.locator('select[data-role="x"]').selectOption("lon");
    await page.locator('select[data-role="y"]').selectOption("lat");
    await page.locator('select[data-role="gravity_value"]').selectOption("gravity_mgal");

    await darLaVuelta(page);

    // El archivo del FLUJO PRINCIPAL vivía en el reducer del panel, no en el
    // store: hoy se pierde entero, y con él la zona de carga vuelve a vacío.
    await expect(page.getByText("✓ crudo.csv")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/2 puntos válidos/i)).toBeVisible();
    await expect(page.locator('select[data-role="x"]')).toHaveValue("lon");
    await expect(page.locator('select[data-role="y"]')).toHaveValue("lat");
    await expect(page.locator('select[data-role="gravity_value"]')).toHaveValue("gravity_mgal");
  });

  // ── C · NUEVO-3: el gate duro ─────────────────────────────────────────────

  test("C · el paquete se arma con el CSV CORREGIDO, no con el crudo", async ({ page }) => {
    test.setTimeout(180_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await prepararPanelClasico(page);
    await aplicarCorrecciones(page);

    await darLaVuelta(page);
    await abrirAvanzado(page);

    // Primero lo que se VE: la insignia sigue afirmando que hay correcciones.
    await expect(page.getByText(/Correcciones aplicadas/i)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/latitude · free_air · bouguer · terrain/)).toBeVisible();

    // Aplicar correcciones BORRA la vista previa a propósito (`PrepPanel.tsx:1308`):
    // el veredicto describía el CSV crudo y ya no lo describe. Hay que revalidar,
    // y **ese botón es la SEGUNDA CAPA de NUEVO-3**: hasta esta fase el validador
    // local no reconocía ninguna de las cuatro columnas que el asistente escribe
    // (`gCandidates`), así que `can_invert` salía `false` y el botón quedaba
    // APAGADO — el CSV corregido no podía llegar al backend ni sin cambiar de
    // pestaña. Si esta aserción cae, ha vuelto esa ceguera.
    const validar = page.getByRole("button", { name: /^Validar CSV$/i });
    await expect(
      validar,
      "«Validar CSV» está deshabilitado con un CSV corregido: el validador local no reconoce su columna de gravedad",
    ).toBeEnabled();
    await validar.click();
    await expect(page.getByText(/Inversión 3D/i)).toBeVisible({ timeout: 20_000 });

    // Y ahora lo que VIAJA, que es lo único que decide el defecto.
    const paquete: { valor: PaqueteCapturado | null } = { valor: null };
    await interceptarPaquete(page, paquete);

    await page.getByRole("button", { name: /Generar paquete CSV/i }).click();
    await expect(page.getByText(/Paquete CSV generado/i)).toBeVisible({ timeout: 30_000 });

    expect(paquete.valor, "no se interceptó ninguna petición a build-package").not.toBeNull();
    const enviado = paquete.valor!;

    // LA AFIRMACIÓN DE LA FASE, por CONTENIDO y no por nombre: un renombrado
    // pasaría la comprobación del filename, no ésta.
    expect(
      enviado.contenido.includes(MARCA_CORREGIDO),
      "el paquete NO lleva el CSV corregido: viajó otro fichero",
    ).toBe(true);
    expect(
      enviado.contenido.includes(COLUMNA_CORREGIDA),
      "el paquete no lleva la columna que escribe el asistente",
    ).toBe(true);
    expect(
      enviado.contenido.includes(COLUMNA_CRUDA),
      "el paquete lleva la cabecera del CSV crudo: se envió el fichero equivocado",
    ).toBe(false);
    expect(enviado.filename).toBe("corrected_crudo.csv");

    // Y la CONFIGURACIÓN, que es la segunda mitad del defecto: `allow_g_raw` se
    // enciende porque hay CSV corregido (`PrepPanel.tsx:1202`). Comprobarlo
    // separa «se perdió el File» de «se envió el File equivocado».
    expect(enviado.qs.get("allow_g_raw")).toBe("true");
  });

  // ── D · La barrera de H-29 sigue viva: sobrevivir no es ser inmortal ──────

  test("D · cambiar de archivo SÍ caduca el CSV corregido", async ({ page }) => {
    test.setTimeout(180_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await prepararPanelClasico(page);
    await aplicarCorrecciones(page);

    // Un CSV corregido describe al archivo con el que se calculó. Que sobreviva
    // al cambio de PESTAÑA no puede convertirlo en inmortal: al cambiar de
    // ARCHIVO tiene que morir, o esta fase habría resucitado H-29.
    await prepGravityInput(page).setInputFiles(csvAdjunto("otro.csv", CSV_CRUDO));
    await expect(page.getByText(/Correcciones aplicadas/i)).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /Aplicar correcciones geofísicas/i }),
    ).toBeVisible({ timeout: 20_000 });

    // Y el estado NO se borra con la historia: los bounds del preset siguen.
    await expect(densityMinInput(page)).toHaveValue("4.5");

    // ── Y AHORA LO QUE DE VERDAD IMPORTA ─────────────────────────────────────
    //
    // La insignia de arriba la dibuja `correctionReport`, NO `correctedFile`.
    // MEDIDO por mutación al cerrar la fase: dejando vivo `correctedFile` y
    // caducando sólo el reporte, este recorrido **pasaba en verde** mientras el
    // paquete viajaba con el CSV corregido de OTRO archivo. Es exactamente el
    // defecto que la fase persigue —dato que sobrevive y no se ve— con el signo
    // cambiado. Así que aquí se mira el cable, no la pantalla.
    await page.getByRole("button", { name: /^Validar CSV$/i }).click();
    await expect(page.getByText(/Inversión 3D/i)).toBeVisible({ timeout: 20_000 });

    const paquete: { valor: PaqueteCapturado | null } = { valor: null };
    await interceptarPaquete(page, paquete);
    await page.getByRole("button", { name: /Generar paquete CSV/i }).click();
    await expect(page.getByText(/Paquete CSV generado/i)).toBeVisible({ timeout: 30_000 });

    expect(paquete.valor, "no se interceptó ninguna petición a build-package").not.toBeNull();
    const enviado = paquete.valor!;
    expect(
      enviado.contenido.includes(MARCA_CORREGIDO),
      "el paquete lleva el CSV corregido del archivo ANTERIOR: la caducidad de H-29 no se aplicó",
    ).toBe(false);
    expect(enviado.contenido.includes(COLUMNA_CRUDA)).toBe(true);
    expect(enviado.filename).toBe("otro.csv");
    // La bandera se apaga con el fichero: `allowGRaw || correctedFile !== null`.
    expect(enviado.qs.get("allow_g_raw")).toBe("false");
  });

  // ── E · El flujo principal también caduca lo que describe a su archivo ────

  test("E · cambiar el CSV del flujo principal caduca el mapeo de columnas", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");

    await enrichGravityInput(page).setInputFiles(csvAdjunto("a.csv", CSV_CRUDO));
    await page.getByRole("button", { name: /^Mapear columnas$/i }).click();
    await expect(page.getByRole("heading", { name: "Mapeo manual de columnas" })).toBeVisible({
      timeout: 20_000,
    });
    await page.locator('select[data-role="x"]').selectOption("lon");

    // El mapeo describe las columnas de `a.csv`. Con otro archivo cargado, un
    // mapeo superviviente reenviaría al backend los roles del anterior.
    await enrichGravityInput(page).setInputFiles(csvAdjunto("b.csv", CSV_CRUDO));
    await expect(page.getByText("✓ b.csv")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Mapeo manual de columnas" })).toHaveCount(0);
  });

  // ── F · Consecuencia medida al abrir la fase, no declarada en el plan ─────

  test("F · un CSV de magnetometría no se vuelve invisible al volver", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await abrirAvanzado(page);

    // Sólo magnetometría: `fileMagnetometry` vive en el store (sobrevive) pero
    // `dataType` vivía en `contexto` (se evaporaba y volvía a "gravity").
    await prepMagneticInput(page).setInputFiles(csvAdjunto("magnetico.csv", CSV_CRUDO));
    await expect(page.getByText(/Modo magnetometría: magnetico\.csv/i)).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: /Validar CSV magnético/i })).toBeEnabled();

    await darLaVuelta(page);
    await abrirAvanzado(page);

    // Con el defecto vivo el archivo desaparecía de la interfaz —su ÚNICA señal
    // está gateada por `dataType === "magnetic"` (`PrepPanel.tsx:1248`)— mientras
    // SEGUÍA entrando al paquete (`:1111`), y el botón de validar quedaba
    // apagado (`:1557`) sin forma de encenderlo.
    await expect(page.getByText(/Modo magnetometría: magnetico\.csv/i)).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: /Validar CSV magnético/i })).toBeEnabled();
  });

  // ── H · NUEVO-2 nombra «los sondajes», y son lo que VIAJA como anclaje ────

  test("H · los sondajes confirmados siguen anclando la inversión al volver", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");

    // El combo del flujo principal sólo se dibuja si hay al menos un archivo de
    // origen (`comboLabel`), así que la gravimetría entra primero.
    await enrichGravityInput(page).setInputFiles(csvAdjunto("crudo.csv", CSV_CRUDO));
    await page
      .locator('input[type="file"][accept=".csv,text/csv,.omf"]')
      .setInputFiles(csvAdjunto("sondajes.csv", "hole_id,x,z,from,to,density\nBH01,50,50,0,30,3.2\n"));
    await page.getByRole("button", { name: /^Validar sondajes$/i }).click();
    await page.getByRole("button", { name: /Usar sondajes en la inversión/i }).click();

    // Dos indicadores independientes, uno por panel: el combo del flujo
    // principal y el contexto del survey en el clásico. El segundo vive dentro
    // de la SECCIÓN DE INVERSIÓN, que sólo existe tras validar un CSV.
    await expect(page.getByText(/\+ sondajes \(anclaje\)/i)).toBeVisible({ timeout: 20_000 });
    await abrirAvanzado(page);
    await prepGravityInput(page).setInputFiles(csvAdjunto("crudo.csv", CSV_CRUDO));
    await page.getByRole("button", { name: /^Validar CSV$/i }).click();
    await expect(page.getByText(/1 sondaje\(s\) anclado\(s\)/i)).toBeVisible({ timeout: 20_000 });

    await darLaVuelta(page);

    // Éste es el peor de los campos que se evaporaban: los intervalos son lo que
    // se ENVÍA al backend como anclaje. Al perderse, el paquete salía sin
    // anclaje y la interfaz no decía nada.
    await expect(page.getByText(/\+ sondajes \(anclaje\)/i)).toBeVisible({ timeout: 20_000 });
    await abrirAvanzado(page);
    await expect(page.getByText(/1 sondaje\(s\) anclado\(s\)/i)).toBeVisible({ timeout: 20_000 });
  });

  // ── G · Control negativo: el gate no afirma nada sobre el estado inicial ──

  test("G · dar la vuelta sin tocar nada deja los valores de fábrica", async ({ page }) => {
    test.setTimeout(120_000);
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Preparación");
    await abrirAvanzado(page);
    await expect(densityMinInput(page)).toBeVisible({ timeout: 20_000 });

    await darLaVuelta(page);
    await abrirAvanzado(page);

    // Si esto se pusiera rojo, el gate estaría afirmando cosas sobre el arranque
    // en vez de sobre la supervivencia del trabajo del usuario.
    await expect(densityMinInput(page)).toHaveValue("0.0");
    await expect(densityMaxInput(page)).toHaveValue("5.5");
    await expect(presetSelect(page)).toHaveValue("custom");
    await expect(previewLimitInput(page)).toHaveValue("20");
    await expect(page.getByText("✓ crudo.csv")).toHaveCount(0);
  });
});
