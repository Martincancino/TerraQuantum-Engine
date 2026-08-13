# TerraQuantum — Empaque local-first + licencias (F7)

| Campo | Valor |
|---|---|
| Fase | F7 — Empaque local-first + licencias |
| Estado | **Instalador nativo Tauri 2 CONSTRUIDO y verificado E2E** (backend PyInstaller + frontend Node como sidecars); núcleo agnóstico al empaque + Plan B también hechos. Updater firmado configurado. |
| Principio | Los datos del cliente **NUNCA** salen de su máquina. La barrera de confidencialidad convertida en ventaja de venta. |

---

## 1. La decisión de empaque (spike medido) — y su resolución

El spike midió el mayor riesgo del plan: que **PyInstaller** empaquetara el backend científico (FastAPI + scipy/pyproj/scikit-image + IGRF). **Resultado: FUNCIONA** — ejecutable onefile de ~199 MB que arranca en ~14 s, sirve los endpoints y trae `proj.db` (pyproj) + IGRF bundleados. Con eso despejado, y con Martín autorizando instalar el toolchain, se construyó el **instalador nativo Tauri 2 completo**.

### Arquitectura final: Tauri 2 con DOS sidecars

En vez del `output:'export'` que sugería el plan, la app usa **dos sidecars** empaquetados. La razón es medida y dura: los **40 proxies** `app/api/*/route.ts` NO son pass-throughs triviales — hacen transformación real (query→segmentos de path en `geophysics-status`, reformateo de parámetros + manejo de Arrow binario en `block-model`, prefijos `/v2/`, renombres). Reescribirlos a "directo-a-backend" para un export estático obligaría a **duplicar esa lógica en TypeScript**, lo que `.claude/CLAUDE.md` prohíbe explícitamente ("NO duplicar lógica en TS"). Por eso:

- **Sidecar 1 — Backend Python** (`terraquantum-backend.exe`, PyInstaller): FastAPI/uvicorn en `127.0.0.1:8010`, datos en `%APPDATA%\TerraQuantum\data`.
- **Sidecar 2 — Frontend Next.js** (Node standalone): servidor en `127.0.0.1:3000` con **los 40 proxies intactos** — cero cambios de código de app, cero duplicación.
- **Shell Tauri** (`terraquantum-web/src-tauri/`, Rust): al arrancar lanza ambos sidecars ocultos (`CREATE_NO_WINDOW`, stdio a `%APPDATA%\TerraQuantum\logs`), muestra un splash, espera a que `:3000` responda y **navega la ventana** al server local; al cerrar **mata ambos árboles de proceso**.

El frontend **no se tocó** (respeta "iteraciones separadas"): el `next.config.ts` ya era `output:'standalone'`, perfecto para el sidecar Node.

**Verificado E2E** desde el `app.exe` construido: backend `:8010/health` OK, frontend `:3000` sirve `<title>TerraQuantum</title>`, y el proxy `/api/backend-health` del frontend llega correctamente al backend Python. Instalador NSIS producido: `TerraQuantum_0.2.0_x64-setup.exe` — **321,5 MB medidos** (este documento decía 253 MB; era una cifra estimada que envejeció, corregida en la Fase 2 tras medir el artefacto real).

**GOTCHA medido (no re-aprender):** al lanzar el sidecar de Node desde Rust, pasar la ruta ABSOLUTA de `server.js` fallaba con `EISDIR: lstat 'C:'` — el resolvedor de recursos devuelve rutas verbatim (`\\?\C:\...`) y la resolución de módulos de Node las mutila. Fix: pasar `server.js` **relativo** (con `current_dir` al dir del frontend) y limpiar el prefijo verbatim de todos los recursos.

### Plan B — launcher de un clic (alternativa para máquinas con Python+Node)
`run_terraquantum_desktop.ps1` (raíz del repo, no toca los `.bat` existentes): fija `TERRAQUANTUM_DATA_DIR`, bind del backend a loopback, levanta backend+`next start`, abre el navegador. Sigue disponible para desarrollo o máquinas que ya tienen los runtimes; el instalador Tauri es la distribución para el usuario final (no exige Python ni Node).

### Pipeline de build repetible
`scripts/build_desktop.ps1`: (1) PyInstaller del backend → exe; (2) `next build` standalone; (3) staging de `backend.exe` + `node.exe` + frontend a `src-tauri/resources/`; (4) `tauri build` → instalador NSIS firmado.

**Reproducibilidad (Fase 2, H-23).** El determinismo numérico ya estaba cubierto —`numpy`, `scipy`, `pyproj` y `polars` con pin exacto— pero la cadena de build no. Ahora:
- `terraquantum-backend/requirements-build.txt` fija **`pyinstaller==6.21.0`**, la herramienta que produce el ejecutable que se firma y distribuye. Va en un archivo aparte a propósito: PyInstaller no debe viajar dentro del contenedor Docker ni del entorno del usuario.
- `terraquantum-backend/.python-version` declara el intérprete verificado (3.14.4).
- Las 6 dependencias que usaban `>=` sin techo (`pyarrow`, `zarr`, `dask`, `PyWavelets`, `scikit-learn`, `scikit-image`) llevan **techo de major**, con la versión medida anotada al lado.
- `tests/test_fase2_arranque.py::test_no_requirement_is_unbounded` convierte eso en invariante: una dependencia nueva sin techo rompe la suite.

---

## 2. Ubicación de datos (portabilidad)

`core/config.py::_resolve_data_dir()`:
- **Dev (sin env var):** `<repo>/terraquantum-backend/data` (comportamiento histórico intacto).
- **Escritorio (`TERRAQUANTUM_DATA_DIR` seteada por el launcher):** carpeta del usuario, p.ej. `%APPDATA%\TerraQuantum\data` (Windows), `~/Library/Application Support/TerraQuantum/data` (macOS), `~/.local/share/TerraQuantum/data` (Linux).

Se mueven en bloque **solo los datos de usuario**: proyectos, corridas (parquet/JSON), historial SQLite (`terraquantum.db`), API keys (`api_keys.db`) y la **licencia** (`license.key`). Los **assets de instalación** (`public/models`, `tmp` de scratch) siguen junto al código.

**Respaldo = copiar la carpeta de datos.** "Abrir carpeta de proyectos" en la UI = abrir `TERRAQUANTUM_DATA_DIR`.

---

## 3. Licenciamiento (offline, sin servidor)

Ed25519 con `cryptography` (ya en requirements — sin dependencia nueva). Ver `core/license_service.py`.

- **Token** (una línea, apto para pegar): `tqlic1.<b64url(payload)>.<b64url(firma)>`. Payload: `product, licensee, tier, issued_at, expires_at`.
- **Clave privada** (firma): solo en la máquina del emisor, JAMÁS en el repo. **Clave pública** (verifica): se distribuye vía `TQ_LICENSE_PUBLIC_KEY_HEX`.
- **Emitir** (offline): `python scripts/mint_license.py genkey` (una vez) y `... sign --licensee "X" --tier pro --days 365`.
- **Activar** (cliente): pega el token → `POST /license/activate` lo verifica y guarda en `license.key`. Estado: `GET /license/status`.

**Regla dura (local-first):** sin emisor configurado o sin licencia → modo **local libre** (`tier="local"`, sin límites). La instalación propia jamás se castiga. Los tiers con límites solo aplican cuando una licencia los declara:

| Tier | max_voxels | watermark | Uso |
|---|---|---|---|
| `local` (default) | ∞ | no | Self-hosted / dev |
| `pro` | ∞ | no | Cliente pagado |
| `free` | 40.000 (`TQ_FREE_MAX_VOXELS`) | sí | Canal freemium de distribución |

El tope de vóxeles se consulta con `license_service.check_voxel_budget(n)`; la marca de agua en exports se activa con `limits.watermark` del tier efectivo.

---

## 4. Canal de diagnóstico (confidencialidad primero)

`GET /diagnostics/export` → ZIP con **solo metadatos**: `system.json`, `packages.txt`, `config.json` (saneada, sin secretos), `connectivity.json`, `license.json` (sin material privado), `recent_errors.json` (últimos errores a nivel de código: path + tipo + traceback, **sin body de request**).

**Nunca** incluye datos de survey (CSV/parquet/coordenadas/valores) ni secretos. El test `test_f7_diagnostics.py` siembra secretos y verifica que no aparecen, y que el bundle contiene exactamente los archivos de metadatos. El usuario descarga el ZIP y lo envía **manualmente** — ningún byte sale solo.

Crash reporting automático (sentry-tauri) queda como **opt-in apagado por defecto**, a decidir con los primeros clientes.

---

## 5. Modo sin internet (honesto)

`GET /system/connectivity` reporta qué feature necesita red y confirma `golden_path_offline: true`. El camino dorado (ingesta → correcciones/preparación → inversión → 3D → export/reporte) **no toca la red**.

| Feature | Internet | ¿Requerida por el camino dorado? | Fallback local |
|---|---|---|---|
| IGRF-14 (geomagnetismo) | No | Sí | Embebido offline |
| DEM OpenTopography (corrección de terreno) | Sí | No | Subir DEM local |
| Índices satelitales (GEE) | Sí | No | — (capa exploratoria) |
| Copiloto IA (Gemini, BYO-key) | Sí | No | — (ayuda de redacción) |

Ninguna llamada de red está en la ruta crítica de inversión.

---

## 6. Actualizaciones firmadas y release

- **Updater Tauri 2 configurado y firmado:** `tauri-plugin-updater` registrado; `bundle.createUpdaterArtifacts: true`; clave pública minisign en `plugins.updater.pubkey`; la **clave privada vive fuera del repo** (`~/.tauri/terraquantum_updater.key`) y firma los artefactos en el build (`TAURI_SIGNING_PRIVATE_KEY`). El manifiesto `latest.json` se publica en GitHub Releases = cero servidores que operar.
- **Camino de consumo, cableado en la Fase 2 (H-20).** Hasta entonces el plugin estaba registrado pero **nadie llamaba a `check()`**: la firma funcionaba y el usuario no veía jamás un aviso. Ahora el menú **Ayuda → «Buscar actualizaciones…»** lo invoca desde Rust y muestra el resultado en una ventana de estado. Es **manual a propósito**: un producto cuya promesa es que los datos no salen de la máquina no debe hacer llamadas de red silenciosas al arrancar; la ventana lo dice explícitamente ("es la única función que usa internet").
  - **Lo que está verificado:** que la comprobación se ejecuta y que un endpoint inalcanzable produce un mensaje honesto en español ("si no tienes internet es lo esperable"), no un silencio.
  - **Lo que NO está verificado (y por qué):** la instalación de una actualización real, porque **todavía no existe ningún release publicado** en el endpoint. El botón de descarga no se cableó: prometer un camino que no se puede probar sería repetir el patrón que H-20 denunció. Queda como trabajo del primer release público.
- **Para publicar una versión:** subir la versión en `tauri.conf.json` + `Cargo.toml`, correr `scripts/build_desktop.ps1` con la clave privada en el entorno, y publicar el instalador + su `.sig` + `latest.json` en el endpoint. Reemplazar el placeholder `endpoints` (`github.com/TerraQuantum/terraquantum/...`) por el repo real.
- **Datos preservados:** actualizar reemplaza la instalación; los datos viven en `%APPDATA%\TerraQuantum` y sobreviven intactos (portabilidad testeada).
- **Versionado:** SemVer. Checklist de release: suites F8 + F9 verdes → firmar → publicar manifiesto.

---

## 7. Estado de cierre F7

**Núcleo agnóstico al empaque (backend, sin deps nuevas, física intacta):** data dir portable; licenciamiento Ed25519 (verificar/firmar/activar/tiers) + CLI de emisión; exportar-diagnóstico sin datos; honestidad offline; wiring en `main.py`; 29 tests F7 verdes; gate `scripts/validation/f7_gate_packaging.py` PASS 30/30.

**Instalador nativo Tauri 2 (CONSTRUIDO y verificado E2E):** `terraquantum-web/src-tauri/` con shell Rust que orquesta 2 sidecars (backend PyInstaller + frontend Node standalone), splash + navegación tras health, cleanup de procesos al salir, logging de sidecars. Instalador `TerraQuantum_0.2.0_x64-setup.exe` (**321,5 MB medidos**) producido por `tauri build` + `scripts/build_desktop.ps1`. Updater firmado configurado. Frontend intacto (cero duplicación de proxies).

**Plan B:** launcher `run_terraquantum_desktop.ps1` (para máquinas con Python+Node ya instalados).

> **Corrección de la Fase 2:** este documento decía ~253 MB en dos sitios; el artefacto real mide **321,5 MB**. Corregido tras medirlo. La lección vale más que el número: la documentación envejece más rápido que el artefacto, y una cifra sin fecha de medición es una promesa sin respaldo.

**Pendiente (no bloquea el gate):** correr el instalador en una VM Windows LIMPIA (sin Python/Node) para el cronómetro formal del "tercero instala en <15 min" — la app ya se verificó levantando ambos sidecars y sirviendo el camino dorado desde el bundle en esta máquina; instalador firmado real requiere publicar el `latest.json` en el repo de releases. Iconos: placeholders del scaffold (reemplazar por la marca antes del lanzamiento público).

---

## 8. Arranque que falla en voz alta (Fase 2)

El principio de producto —*"ningún input produce crash ni basura silenciosa; siempre un error en español que dice qué hacer"* (`02_PRODUCTO.md` §4.1)— se aplicaba con rigor al pipeline de datos y **no llegaba al arranque**, que es justo donde no hay un desarrollador presente. La Fase 2 lo extiende al proceso de arranque. Cinco mecanismos, todos en `terraquantum-web/src-tauri/src/lib.rs`:

| Mecanismo | Qué cambia | Hallazgo |
|---|---|---|
| **Splash con estados** | El splash era una barra que giraba **para siempre**. Ahora recibe eventos (`tq://boot`) y, si algo falla, muestra causa en español + **[Reintentar]** + **[Ver registros]** + [Cerrar]. La barra **se detiene** al fallar: seguir animando era la mentira. | H-17 |
| **Job Object de Windows** | `CreateJobObject` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (FFI directa a kernel32, **sin dependencias nuevas**). Si matan la app desde el Administrador de Tareas, el SO mata a los sidecars. `taskkill` en `RunEvent::Exit` sólo cubría el cierre ordenado. | H-18 |
| **Chequeo de IDENTIDAD** | Ya no basta con que alguien responda en el puerto: el backend recibe un **token de instancia** por entorno y lo publica en `/health`; el shell compara. El frontend se valida por `/api/backend-health`, que además demuestra que el sidecar Node está emparejado con **nuestro** backend. | H-19 |
| **Puertos elegidos antes de spawnear** | Si 8010/3000 están ocupados se usa el siguiente libre del tramo (12 puertos) y **se dice por qué** ("lo ocupa otra instancia de TerraQuantum" / "otra aplicación"). El puerto elegido viaja al sidecar Node por entorno. | H-21 |
| **Registros visibles** | Botón en el splash y menú **Ayuda → Ver registros de arranque / Abrir carpeta de datos**. | H-17 |

**El diario de arranque.** Todo lo que se muestra en el splash se escribe además a `%APPDATA%\TerraQuantum\logs\boot.jsonl` (una línea JSON por estado; el arranque anterior se conserva en `boot.prev.jsonl`). Sirve para dos cosas: soporte —el usuario manda un archivo en vez de describir una animación— y **auditoría automática**: es lo que lee el gate. Splash y diario salen de la **misma** función (`publish`), así que no pueden divergir.

**El gate: matriz de arranque adverso.** `scripts/f2_gate_boot_matrix.ps1` **decide** (exit 0/1) sobre los 6 casos del criterio de aceptación: (a) puerto 8010 ocupado, (b) puerto 3000 ocupado, (c) backend en cuarentena, (d) cierre violento a mitad del arranque, (e) cierre violento con la app en uso, (f) segundo arranque tras cada caso. En cada uno comprueba también **cero procesos huérfanos** comparando el censo de `terraquantum-backend.exe`/`node.exe` antes y después. Requiere la app compilada (`cd terraquantum-web/src-tauri ; cargo build --release`).

> **Honestidad sobre el caso (e).** El criterio original decía "matar durante una inversión". El gate mata con **tráfico real en vuelo por ambos sidecars**, no durante una inversión completa (que exigiría un paquete de datos y minutos de cómputo). Es una aproximación deliberada y está anotada en el propio script: lo que se prueba es el ciclo de vida de los procesos, que no depende de qué esté calculando el backend.

**Seguridad del arranque.** El default de `TERRAQUANTUM_HOST` pasó de `0.0.0.0` a `127.0.0.1` (H-15): la API corre sin autenticación por defecto, así que el binding a loopback es la única barrera real, y ahora lo es **por construcción** y no porque tres lanzadores se acuerden de fijarlo. Docker sigue pidiendo `0.0.0.0` explícito, que es lo correcto dentro de un contenedor. Y el navegador **dejó de conocer la URL del backend** (H-21): las tres llamadas directas que quedaban se enrutaron por proxies nuevos (`/api/export-bundle`, `/api/delete-run`, `/api/project-footprint`), con un gate estático —`terraquantum-web/scripts/check_client_backend_calls.mjs`— que falla si alguna vuelve.
