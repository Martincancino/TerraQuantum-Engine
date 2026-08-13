/**
 * GATE estático de la Fase 2 (H-21): el NAVEGADOR no debe saber dónde escucha
 * el backend.
 *
 * Por qué es una puerta y no un consejo:
 *
 *  - Seguridad. La API corre sin autenticación por defecto. Mientras todo el
 *    tráfico pase por los proxies del servidor Next, esos proxies son el único
 *    lugar donde añadir una cabecera de autenticación el día que se active. Una
 *    sola llamada directa desde el navegador rompe esa propiedad para siempre.
 *  - Corrección. Desde la Fase 2 el orquestador de escritorio puede levantar el
 *    backend en un puerto alternativo si el 8010 está ocupado. Una URL horneada
 *    en el bundle de cliente (`NEXT_PUBLIC_*` se sustituye en tiempo de build)
 *    apuntaría entonces a OTRO proceso.
 *
 * Uso:  node scripts/check_client_backend_calls.mjs      (exit 1 si hay alguna)
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

/** Código que acaba (o puede acabar) ejecutándose en el navegador. */
const CLIENT_DIRS = ["componentes", "lib", "store", "workers", "types", "app"];
/** Los proxies SÍ deben conocer el backend: son el servidor. */
const SERVER_ONLY = join("app", "api");

const FORBIDDEN = [
  {
    pattern: /NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL/,
    why: "expone la URL del backend al navegador (Next la hornea en el bundle de cliente)",
  },
  {
    pattern: /BACKEND_PUBLIC_URL/,
    why: "era la constante que construía llamadas directas navegador→backend",
  },
  {
    pattern: /https?:\/\/(127\.0\.0\.1|localhost):8010/,
    why: "URL del backend escrita a mano en código de cliente",
  },
];

const EXTS = [".ts", ".tsx", ".js", ".mjs"];
const offenders = [];

function scan(dir) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (entry === "node_modules" || entry === ".next") continue;
    if (statSync(full).isDirectory()) {
      scan(full);
      continue;
    }
    if (!EXTS.some((ext) => entry.endsWith(ext))) continue;

    const rel = relative(ROOT, full);
    if (rel.startsWith(SERVER_ONLY + sep)) continue;

    const lines = readFileSync(full, "utf8").split("\n");
    lines.forEach((line, index) => {
      if (line.trimStart().startsWith("//") || line.trimStart().startsWith("*")) return;
      for (const rule of FORBIDDEN) {
        if (rule.pattern.test(line)) {
          offenders.push({ file: rel, line: index + 1, why: rule.why, text: line.trim() });
        }
      }
    });
  }
}

for (const dir of CLIENT_DIRS) scan(join(ROOT, dir));

if (offenders.length > 0) {
  console.error("FALLA — el navegador no debe conocer la URL del backend (H-21):\n");
  for (const o of offenders) {
    console.error(`  ${o.file}:${o.line}`);
    console.error(`     ${o.text}`);
    console.error(`     motivo: ${o.why}\n`);
  }
  console.error(`${offenders.length} ocurrencia(s). Enrútalo por un proxy de app/api/.`);
  process.exit(1);
}

console.log("OK — ninguna llamada directa navegador→backend en el código de cliente.");
process.exit(0);
