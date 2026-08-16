import { test, expect, Page } from "@playwright/test";

/**
 * FASE 9 (auditoría 06 §10) — Interfaz para F7 y superficies nunca montadas.
 * =========================================================================
 *
 * La fase cierra H-10: la fase F7 completa (licenciamiento local-first,
 * exportación de diagnóstico, honestidad offline) existía en el backend y **no
 * tenía ninguna interfaz** — 5 endpoints sin un solo consumidor, con un gate
 * declarado en verde porque midió el endpoint y no al usuario. Más las tres
 * superficies de UI que el cierre de la Fase 6 encontró escritas y sin montar.
 *
 * Los criterios de aceptación de la fase, uno por recorrido:
 *
 *  (a) Un tester que no conozca el código **activa una licencia** sin tocar la
 *      API a mano — incluyendo el caso que más engaña: un token inválido
 *      responde HTTP 200, así que "activada" no puede deducirse del status.
 *  (b) **Exporta un diagnóstico**, desde la vista de Sistema y desde el modal
 *      de error.
 *  (c) **Ve su estado de conexión**, y es un estado COMPROBADO: si el motor de
 *      cálculo no responde, lo dice.
 *  (d) **Enciende el plano de corte** (SliceControls, montado por fin).
 *  (e) **Cambia de capa física a mano** (MultiPhysicsControls, ídem).
 *  (f) Un resultado que **no convergió** lo dice donde se mira el modelo.
 *
 * Como en `fase1_confianza.spec.ts`, el backend se sustituye en la frontera HTTP:
 * lo que se afirma aquí son invariantes de INTERFAZ. Las mitades de backend
 * (honestidad de `/system/connectivity`, licencias, ZIP sin datos de survey)
 * están cubiertas por pytest: `tests/test_f7_*.py`.
 */

const PROJECT_A = "pytest_fase9_A";
const RUN_A = "run_fase9_A";

const TOKEN_VALIDO = "tqlic1.eyJwcm9kdWN0IjoidGVycmFxdWFudHVtIn0.firma";
const TOKEN_INVALIDO = "tqlic1.roto.roto";

function csvFixture(): string {
  const rows = Array.from({ length: 8 }, (_, i) =>
    `${i * 25},0,${i * 15},${(0.1 + i * 0.37).toFixed(3)}`,
  );
  return `x_m,y_m,z_m,gravity_mgal\n${rows.join("\n")}\n`;
}

/** Block model mínimo. `susceptibility_si` presente → la capa χ está disponible
 *  y el selector multi-física puede ejercerse de verdad. */
function blockModelJson() {
  const cells = [];
  for (let i = 0; i < 8; i++) {
    cells.push({
      x: i * 10, y: 10 + i * 5, z: 20,
      density: 2.6 + i * 0.05,
      density_t_m3: 2.6 + i * 0.05,
      susceptibility_si: 0.001 + i * 0.0002,
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

/** Reporte persistido. `regularization_functional` es el canal de la Fase 7:
 *  de ahí salen `solver_converged`, `lsqr_istop` y el motivo en español. */
function runDetailJson(opts: { converged?: boolean | null } = {}) {
  const converged = opts.converged ?? true;
  return {
    project_id: PROJECT_A,
    run_id: RUN_A,
    inputs: { depth: 300 },
    report: {
      status: "done",
      warnings: [],
      technicalSummary: { overall_level: "MEDIUM", summary: "Corrida de prueba.", warnings: [] },
      misfit_error_percent: 3.2,
      fitDiagnostics: { chi_squared: 1.04, fit_level: "GOOD" },
      regularization_functional: {
        model_weight_kind: "depth",
        smallness_block: converged === false ? "scaled_by_W" : "identity_in_tilde",
        model_weight_is_pure_change_of_variable: converged === false,
        model_weight_enters_functional: converged !== false,
        depth_weighting_active: converged !== false,
        depth_beta_declared: 1.5,
        depth_beta_has_effect: true,
        effect_mechanism: converged === false ? "early_stopping" : "functional",
        solver_converged: converged,
        lsqr_istop: converged === false ? 7 : converged === true ? 2 : null,
        lsqr_iters: converged === false ? 500 : converged === true ? 84 : null,
        smoothness_row_weight_applied: false,
        explanation_es:
          converged === false
            ? "Peso de profundidad inerte EN EL FUNCIONAL pero NO en este resultado."
            : "Peso de profundidad Li & Oldenburg ACTIVO (beta=1.5).",
      },
    },
  };
}

const CONNECTIVITY = {
  golden_path_offline: true,
  golden_path_note:
    "Ingesta, correcciones/preparación, inversión, visor 3D y export/reporte funcionan sin internet.",
  probed: false,
  probe_requested: false,
  probe_note: "Este resumen no sale a la red: reporta CONFIGURACIÓN, no alcance real.",
  online_features: [
    {
      name: "Copiloto IA (Gemini)", key: "copilot_gemini",
      requires_internet: true, required_for_golden_path: false,
      configured: false, user_supplied_key: true, local_fallback: false,
      message: "BYO-key: se pega en la interfaz y no se guarda en el servidor.",
    },
    {
      name: "Modelo geomagnético (IGRF-14)", key: "igrf",
      requires_internet: false, required_for_golden_path: true,
      configured: true, local_fallback: true,
      message: "IGRF-14 embebido offline. No requiere internet.",
    },
  ],
};

function licenseJson(over: Record<string, unknown> = {}) {
  return {
    valid: false, tier: "local", reason: "Sin licencia (modo local libre).",
    licensee: null, product: null, issued_at: null, expires_at: null,
    expired: false, source: "none", effective_tier: "local",
    limits: { max_voxels: null, watermark: false }, mode: "local_free",
    ...over,
  };
}

/** Sustituye el backend en la frontera HTTP. */
async function mockBackend(
  page: Page,
  opts: { backendOnline?: boolean; converged?: boolean | null; license?: Record<string, unknown> } = {},
) {
  const online = opts.backendOnline ?? true;

  await page.route("**/api/backend-health", (route) =>
    route.fulfill({
      json: online
        ? { online: true, backendStatus: 200, backendUrl: "http://127.0.0.1:8010",
            data: { status: "ok", version: "0.2.0" } }
        : { online: false, detail: "No se pudo conectar con backend Python.",
            backendStatus: 500, backendUrl: "http://127.0.0.1:8010" },
    }),
  );
  await page.route("**/api/system/connectivity", (route) => route.fulfill({ json: CONNECTIVITY }));
  await page.route("**/api/license/status", (route) =>
    route.fulfill({ json: licenseJson(opts.license ?? {}) }),
  );
  await page.route("**/api/license/activate", async (route) => {
    const body = JSON.parse(route.request().postData() || "{}") as { token?: string };
    const ok = body.token === TOKEN_VALIDO;
    // El punto del recorrido: un token inválido responde **200**.
    route.fulfill({
      json: ok
        ? licenseJson({
            valid: true, activated: true, tier: "pro", effective_tier: "pro",
            mode: "licensed", source: "file", licensee: "Consultora de prueba",
            product: "terraquantum", reason: "Licencia válida.",
          })
        : licenseJson({ activated: false, reason: "Firma de licencia inválida (no emitida por el proveedor)." }),
    });
  });
  await page.route("**/api/diagnostics/manifest", (route) =>
    route.fulfill({
      json: {
        system: { app_version: "0.2.0", platform: "Windows-11", generated_at: "2026-08-16T00:00:00Z" },
        packages: { fastapi: "0.135.0", numpy: "2.1.0" },
        config_sanitized: { APP_NAME: "TerraQuantum" },
        connectivity: CONNECTIVITY,
        license: { valid: false, tier: "local" },
        recent_errors: [],
      },
    }),
  );

  // Camino dorado (para los recorridos que necesitan un modelo en pantalla).
  await page.route("**/api/gravity-import/load-package", (route) =>
    route.fulfill({
      json: { status: "done", project_id: PROJECT_A, run_id: RUN_A, route: "gravity_only", errors: [] },
    }),
  );
  await page.route("**/api/block-model?**", (route) => route.fulfill({ json: blockModelJson() }));
  await page.route("**/api/block-model-zarr**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/project-run-detail**", (route) =>
    route.fulfill({ json: runDetailJson({ converged: opts.converged }) }),
  );
  await page.route("**/api/geophysics-status**", (route) =>
    route.fulfill({ json: { status: "done", stage: "done", progress: 1 } }),
  );
  await page.route("**/api/section**", (route) =>
    route.fulfill({ json: { axis: "x", position: 0, width: 2, height: 2, values: [0, 1, 1, 0], vmin: 0, vmax: 1 } }),
  );
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

async function loadModelInViewer(page: Page) {
  await navTo(page, "figura 3D");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "paquete.tqpkg.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("#CONFIG\n" + csvFixture()),
  });
  await page.getByRole("button", { name: /Cargar modelo 3D/i }).click();
  await expect(page.getByText(/Modelo cargado/i)).toBeVisible({ timeout: 30_000 });
}

test.describe("Fase 9 · interfaz de F7 y superficies montadas", () => {
  // (a) LICENCIA ─────────────────────────────────────────────────────────────
  test("un tester activa una licencia sin tocar la API a mano", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Sistema");

    // Estado inicial: modo local libre, dicho con todas las letras.
    await expect(page.getByTestId("license-mode")).toContainText(/Modo local libre/i);
    await expect(page.getByTestId("license-tier")).toContainText(/local/i);

    // Pega la clave y activa.
    await page.getByTestId("license-token-input").fill(TOKEN_VALIDO);
    await page.getByTestId("license-activate").click();

    await expect(page.getByTestId("license-activate-result")).toContainText(/Licencia válida/i);
  });

  test("un token inválido NO se declara activado (el backend responde 200)", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Sistema");

    await page.getByTestId("license-token-input").fill(TOKEN_INVALIDO);
    await page.getByTestId("license-activate").click();

    const result = page.getByTestId("license-activate-result");
    await expect(result).toBeVisible();
    await expect(result).toContainText(/Firma de licencia inválida/i);
    // Y el estado sigue siendo local: nada se "activó" por haber devuelto 200.
    await expect(page.getByTestId("license-mode")).toContainText(/Modo local libre/i);
  });

  test("si la licencia viene del entorno, el panel avisa de que el archivo no manda", async ({ page }) => {
    await mockBackend(page, {
      license: { valid: true, mode: "licensed", source: "env", tier: "pro",
                 effective_tier: "pro", reason: "Licencia válida." },
    });
    await enterApp(page);
    await navTo(page, "Sistema");
    await expect(page.getByTestId("license-env-warning")).toBeVisible();
  });

  // (b) DIAGNÓSTICO ──────────────────────────────────────────────────────────
  test("un tester exporta un diagnóstico y ve antes qué contiene", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Sistema");

    // Se enseña el contenido ANTES de descargar: la promesa de que no salen
    // datos de survey tiene que poder comprobarse mirando.
    await expect(page.getByTestId("diagnostics-summary")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("diagnostics-panel")).toContainText(/No incluye/i);

    const boton = page.getByTestId("diagnostics-export");
    await expect(boton).toBeVisible();
    await expect(boton).toHaveAttribute("href", "/api/diagnostics/export");
    await expect(boton).toHaveAttribute("download", "");
  });

  // (c) CONEXIÓN ─────────────────────────────────────────────────────────────
  test("el estado de conexión se COMPRUEBA y se ve en la barra", async ({ page }) => {
    await mockBackend(page, { backendOnline: true });
    await enterApp(page);

    const indicador = page.getByTestId("connectivity-indicator");
    await expect(indicador).toBeVisible();
    await expect(indicador).toHaveAttribute("data-estado", "conectado", { timeout: 15_000 });
  });

  test("si el motor de cálculo no responde, el indicador NO dice que está conectado", async ({ page }) => {
    await mockBackend(page, { backendOnline: false });
    await enterApp(page);

    const indicador = page.getByTestId("connectivity-indicator");
    await expect(indicador).toHaveAttribute("data-estado", "caido", { timeout: 15_000 });

    // Y el detalle está a un clic, en la vista de Sistema.
    await indicador.click();
    await expect(page.getByTestId("connectivity-backend-state")).toContainText(/no responde/i);
  });

  test("la conexión distingue BYO-key de «no disponible»", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await navTo(page, "Sistema");

    // El copiloto no tiene clave en el servidor, pero se usa pegando la tuya:
    // decir "sin configurar" a secas sería mentir por omisión.
    await expect(page.getByTestId("connectivity-feature-copilot_gemini")).toContainText(
      /clave desde la interfaz/i,
    );
    // Y el panel declara que este resumen no sale a la red.
    await expect(page.getByTestId("connectivity-probe-note")).toContainText(/no sale a la red/i);
  });

  // (d) PLANO DE CORTE ───────────────────────────────────────────────────────
  test("el usuario puede encender el plano de corte", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);

    // La sección existe en el sidebar (antes no había NADA que encendiera el corte).
    const seccion = page.getByRole("button", { name: /Plano de corte/i });
    await expect(seccion).toBeVisible({ timeout: 20_000 });

    // Elegir eje X hace aparecer el control de posición: el corte está encendido.
    await page.getByRole("button", { name: /^X$/ }).click();
    await expect(page.getByText(/Posición eje X/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Mostrar solo el lado seccionado/i)).toBeVisible();
  });

  // (e) CAPA FÍSICA ──────────────────────────────────────────────────────────
  test("el usuario puede cambiar de capa física a mano", async ({ page }) => {
    await mockBackend(page);
    await enterApp(page);
    await loadModelInViewer(page);

    // El panel multi-física está montado (su único llamador vivo era automático).
    const btnSusceptibilidad = page.locator("#multiphysics-btn-susceptibility");
    await expect(btnSusceptibilidad).toBeVisible({ timeout: 20_000 });

    // El modelo trae susceptibility_si, así que la capa χ es elegible.
    await btnSusceptibilidad.click();
    await expect(page.locator("#multiphysics-btn-density")).toBeVisible();
    // La descripción del modo activo cambia al colormap de susceptibilidad.
    await expect(page.getByText(/log₁₀\(χ \+ ε\)/)).toBeVisible({ timeout: 10_000 });
  });

  // (f) CONVERGENCIA ─────────────────────────────────────────────────────────
  test("un resultado que no convergió lo dice donde se mira el modelo", async ({ page }) => {
    await mockBackend(page, { converged: false });
    await enterApp(page);
    await loadModelInViewer(page);

    await expect(page.getByTestId("solver-not-converged-badge")).toBeVisible({ timeout: 20_000 });
    // Y el detalle (istop, iteraciones, motivo en español) está en analytics.
    const detalle = page.getByTestId("solver-not-converged");
    await expect(detalle).toBeVisible();
    await expect(detalle).toContainText(/istop=7/);
    await expect(detalle).toContainText(/500/);
  });

  test("una corrida que SÍ convergió no muestra el aviso", async ({ page }) => {
    await mockBackend(page, { converged: true });
    await enterApp(page);
    await loadModelInViewer(page);

    await expect(page.getByTestId("regularization-functional")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("solver-not-converged-badge")).toHaveCount(0);
    await expect(page.getByTestId("solver-not-converged")).toHaveCount(0);
  });

  // Combo multimodal ─────────────────────────────────────────────────────────

  /** El contrato REAL de `MultimodalPlan` (lib/terraquantum/frontendApi.ts). */
  const PLAN_COMPLETO = {
    has_gravity: true, has_magnetic: true, has_borehole: false, n_sensors: 256,
    plan: {
      route: "gravity_magnetic",
      has_gravity: true, has_magnetic: true, has_borehole: false,
      n_sensors: 256, base_confidence: 0.7, confidence: 0.72, confidence_pct: 72,
      error_depth_m: 38, coverage_pct: 1, data_quality: null,
      resolution_priority: ["sondajes", "gravimetría", "magnetometría"],
      warnings: [], notes: [],
    },
    insufficient_reason: null,
  };

  test("el combo multimodal (Fase 21) es alcanzable desde Preparación", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/api/multimodal/plan", (route) => route.fulfill({ json: PLAN_COMPLETO }));
    await enterApp(page);
    await navTo(page, "Preparación");

    const summary = page.getByTestId("multimodal-combo-summary");
    await expect(summary).toBeVisible({ timeout: 20_000 });
    await summary.click();

    const panel = page.getByTestId("multimodal-combo-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText(/Fusión multimodal/i);
    await expect(panel).toContainText(/72%/);
    await expect(panel).toContainText(/±38 m/);
  });

  /** Regresión de la Fase 9, encontrada AL MONTARLO.
   *
   *  El panel llevaba escrito desde la Fase 21 sin un solo importador, así que
   *  nunca se había ejecutado contra una respuesta real: leía
   *  `plan.confidence_pct.toFixed()` y `plan.resolution_priority.join()` sin
   *  comprobar nada. Con un plan al que le faltan campos eso es un TypeError en
   *  render — medido: **tira la pestaña entera** ("This page couldn't load").
   *  Montarlo tal cual habría metido en el camino dorado justo lo que el
   *  invariante «nunca crashea» prohíbe. */
  test("un plan incompleto NO tumba la vista de Preparación", async ({ page }) => {
    const errores: string[] = [];
    page.on("pageerror", (e) => errores.push(String(e)));

    await mockBackend(page);
    await page.route("**/api/multimodal/plan", (route) =>
      route.fulfill({ json: { plan: { route: "gravity_only" }, insufficient_reason: null } }),
    );
    await enterApp(page);
    await navTo(page, "Preparación");

    const summary = page.getByTestId("multimodal-combo-summary");
    await expect(summary).toBeVisible({ timeout: 20_000 });
    await summary.click();

    const panel = page.getByTestId("multimodal-combo-panel");
    await expect(panel).toBeVisible();
    // Lo que falta se dice, no se inventa ni se convierte en un cero.
    await expect(panel).toContainText("—");
    expect(errores, `errores de JS: ${errores.join(" | ")}`).toHaveLength(0);
  });
});
