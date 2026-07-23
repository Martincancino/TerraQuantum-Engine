import { defineConfig, devices } from "@playwright/test";

/**
 * F8 — UI E2E con Playwright (iteración frontend de la tormenta de pruebas).
 *
 * Levanta el backend Python (:8010) y el frontend Next.js (:3000) como webServers
 * (reuseExistingServer: si ya los tienes corriendo, los reutiliza). Los recorridos
 * de usuario viven en `e2e/`. Headless, un solo navegador (chromium) — el objetivo
 * es cubrir la NAVEGACIÓN y el render de las vistas principales sin física en TS.
 *
 * Correr:  npx playwright test           (desde terraquantum-web)
 *          npx playwright test --ui       (modo interactivo)
 * NO está en check.ps1: E2E es pesado y bajo demanda (como el gate del backend).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "python -m uvicorn main:app --host 127.0.0.1 --port 8010",
      cwd: "../terraquantum-backend",
      url: "http://127.0.0.1:8010/health",
      reuseExistingServer: true,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 180_000,
    },
    {
      // Producción, NO `next dev`: en dev el HMR WebSocket falla y el cliente no
      // hidrata (Next 16 + turbopack), dejando un shell SSR estático. `next start`
      // sirve el build hidratado — además es lo correcto para E2E (probar el bundle
      // que se envía). Requiere `npm run build` previo (lo hace scripts/e2e.ps1 / el CI).
      command: "npm run start",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: true,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 180_000,
    },
  ],
});
