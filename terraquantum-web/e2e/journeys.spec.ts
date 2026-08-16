import { test, expect, Page } from "@playwright/test";

/**
 * F8 — Recorridos de usuario (UI E2E). Cubre la NAVEGACIÓN y el render de las
 * vistas principales + el panel del copiloto (F6), con el invariante transversal
 * de la UI: **ningún error de JS sin capturar** al recorrer la app ("nunca
 * crashea", visto desde el navegador). La física NUNCA se calcula en TS, así que
 * estos tests verifican render y flujo, no números.
 *
 * El recorrido pesado invertir→progreso→3D→descargar contra una inversión EN VIVO
 * (minutos, async) se cubre en el harness de backend (test_f8_e2e_matrix); aquí se
 * cubre la parte navegable (figura 3D / Historial renderizan sin crash).
 */

// FASE 9: «Sistema» es la séptima vista — licencia, diagnóstico y conexión, que
// hasta ahora no tenían ninguna interfaz (H-10).
const NAV = ["inicio", "Preparación", "ia geológica", "figura 3D", "Datos", "Historial", "Sistema"];

/** Entra a la plataforma (pasa la WelcomeScreen) y devuelve la lista de errores de página. */
async function enterApp(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  const inicio = page.getByRole("button", { name: /^inicio$/i });
  const enter = page.getByRole("button", { name: /Entrar a la Plataforma/i });
  await enter.waitFor({ state: "visible" });
  // Reintenta el click hasta transicionar: cubre el margen de hidratación (en
  // producción es rápida y fiable, pero el reintento lo hace robusto igual).
  await expect(async () => {
    if (!(await inicio.isVisible())) await enter.click();
    await expect(inicio).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20_000 });
  return errors;
}

async function navTo(page: Page, label: string) {
  await page.getByRole("button", { name: new RegExp(`^${label}$`, "i") }).click();
}

test.describe("F8 · recorridos de UI", () => {
  test("welcome → entrar → NavBar presente", async ({ page }) => {
    const errors = await enterApp(page);
    // Todos los items de navegación existen (7 desde la Fase 9).
    for (const label of NAV) {
      await expect(page.getByRole("button", { name: new RegExp(`^${label}$`, "i") })).toBeVisible();
    }
    expect(errors, `errores de JS: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("navegar por todas las vistas sin crash", async ({ page }) => {
    const errors = await enterApp(page);
    for (const label of NAV) {
      await navTo(page, label);
      // La NavBar sobrevive (la vista no reventó el árbol) = la app sigue viva.
      // (No usamos locator('main'): algunas vistas montan su propio <main>.)
      await expect(page.getByRole("navigation")).toBeVisible();
      await expect(page.getByRole("button", { name: /^Historial$/i })).toBeVisible();
      await page.waitForTimeout(300); // deja asentar el fetch de la vista
    }
    // Errores de red (backend) son tolerados por diseño (nunca-crashea); errores de
    // JS sin capturar NO: la app debe degradar con gracia, no tirar el árbol.
    const fatal = errors.filter((e) => !/fetch|network|Failed to fetch|Load failed/i.test(e));
    expect(fatal, `errores de JS fatales: ${fatal.join(" | ")}`).toHaveLength(0);
  });

  test("copiloto IA (F6): selector de modo + BYO-key + input de chat", async ({ page }) => {
    await enterApp(page);
    await navTo(page, "ia geológica");
    // Campo BYO-key (F6) y su placeholder.
    await expect(page.getByText(/API Key de Gemini/i)).toBeVisible();
    await expect(page.getByPlaceholder(/Pega tu clave/i)).toBeVisible();
    // Input de chat.
    await expect(page.getByPlaceholder(/Hazle una pregunta/i)).toBeVisible();
    // Escribir en el chat no debe romper nada (no enviamos: gastaría tokens/clave).
    await page.getByPlaceholder(/Hazle una pregunta/i).fill("¿qué es el χ²?");
    await expect(page.getByPlaceholder(/Hazle una pregunta/i)).toHaveValue("¿qué es el χ²?");
  });

  test("preparación renderiza el panel de carga", async ({ page }) => {
    await enterApp(page);
    await navTo(page, "Preparación");
    await expect(page.locator("main").first()).not.toBeEmpty();
    // Debe existir alguna vía de carga de datos (input file o control de subida).
    const hasUpload =
      (await page.locator('input[type="file"]').count()) > 0 ||
      (await page.getByText(/cargar|subir|arrastr|CSV/i).count()) > 0;
    expect(hasUpload, "la vista de preparación no muestra ninguna vía de carga").toBeTruthy();
  });

  test("historial renderiza (consume backend, sin crash)", async ({ page }) => {
    const errors = await enterApp(page);
    await navTo(page, "Historial");
    await expect(page.locator("main").first()).not.toBeEmpty();
    const fatal = errors.filter((e) => !/fetch|network|Failed to fetch|Load failed/i.test(e));
    expect(fatal).toHaveLength(0);
  });

  test("regresión visual de vistas clave (baseline)", async ({ page }) => {
    await enterApp(page);
    for (const label of ["inicio", "ia geológica"]) {
      await navTo(page, label);
      await page.waitForTimeout(500);
      // maxDiffPixelRatio tolera antialiasing/fuentes; crea baseline en la 1ª corrida.
      await expect(page).toHaveScreenshot(`view-${label.replace(/\s+/g, "-")}.png`, {
        maxDiffPixelRatio: 0.03,
        animations: "disabled",
      });
    }
  });
});
