# TerraQuantum — Roadmap a Software Industrial

> Auditoría multi-agente de solo lectura, 2026-06-03. 20 subsistemas, ~67.000 líneas leídas, **255 hallazgos (18 P0, 76 P1, 97 P2, 64 P3)**.
> Detalle completo con `file:línea`, evidencia y fix en:
> - `01_hallazgos_backend_lote1.md` (11 subsistemas: física, servicios, API, seguridad, tests, render)
> - `02_hallazgos_frontend_lote2.md` (9 subsistemas: cliente API, BFF, UI, store, contratos, traza física)

---

## 1. Diagnóstico en una frase

El backend **sí hace geofísica real** (recupera el cuerpo de Bushveld). Lo que impide que esto sea "industrial" no son 255 bugs sueltos: son **~10 decisiones de diseño** que se repiten en cada capa. La más grave: **el sistema está construido para devolver siempre algo plausible en vez de fallar honestamente.** Por eso "se ve bien por fuera y no funciona", y por eso toda IA decía "excelente": evaluaban código plausible, no comportamiento real, y los propios tests están amañados para pasar.

Arreglar esto es cambiar esas ~10 causas, no parchear 255 síntomas.

---

## 2. Las 10 causas raíz (ordenadas por impacto)

### A. 🔴 Fallbacks silenciosos que fingen resultados — *EL pecado capital*
Un dato ausente se reemplaza por un número plausible en vez de fallar. Genera **~40 de los 255 hallazgos**.
- `density = 2.6` cuando falta densidad — en **6+ lugares** (backend `block_model_service.py:79`, `geophysics_service.py:956`; frontend `terraQuantumGeology.ts:221`, `geophysicsModel.ts:5`).
- `probability = 1.0` cuando falta (FE `geophysicsModel.ts:98`) → todo vóxel denso se marca 100% probable.
- `misfit = 0%` / `score = 1.0` sobre datos vacíos (`gravimetry.py:1480`) → "ajuste perfecto" falso.
- `getF32()` devuelve **array de ceros** si falta la columna (`frontendApi.ts:1156`) → modelo entero en density=0, `ok:true`.
- DEM mock = 0 m s.n.m. presentado como elevación real (`geo_utils.py:271`).
- `ExecutiveGeoReport` y `DatosView` pintan un run **totalmente fallido** (misfit 100%, modelo nulo) como análisis normal (`DatosView.tsx:334`, P0 DV-02).
- **Fix arquitectónico:** política de proyecto → todo campo físico ausente = `null`/`NaN` + flag `degraded` explícito; la UI muestra `—`/banner de fallo, **nunca** un número inventado. Prohibir `valor || 0` y `valor || 1` sobre campos físicos.

### B. 🔴 Gates de mentira (validación no-op)
Funciones documentadas como "hard gate industrial" que **no bloquean nada**.
- `_enforce_spatial_readiness_gate` es un no-op (`gravity_import_api.py:480`, P0): un CSV sin datos espaciales corre igual la inversión 3D y se presenta como georreferenciado.
- Gate QA de `viewMode` decorativo: deja entrar a modo susceptibilidad sin datos (`MultiPhysicsControls.tsx:87`).
- Filtro compliance JORC/NI-43-101 del chat: lista en **inglés** sobre un asistente que responde en **español** → no bloquea nada y da falsos positivos (`chat_api.py:12`).
- **Fix:** que cada gate realmente corte (HTTP 422 + acknowledge) o renombrarlo honestamente. Un gate que no bloquea es peor que no tenerlo.

### C. 🔴 Contrato roto "no llega JSON válido" — *el bug que te bloquea hoy*
Cadena de 3 fallos:
1. `/preview` no sanitiza NaN → FastAPI emite el token literal `NaN`, que **no es JSON** (`gravity_import_api.py:597`, P0 csv-json-01 / CONTRACT-003).
2. El proxy `preview/route.ts:34` hace `await res.json()` incondicional → cualquier error no-JSON se aplasta a "Error interno del proxy" (CONTRACT-002). La ruta `invert` **sí** lo hace bien — divergen.
3. Errores estructurados (gate, 422) se aplastan a `"Error 422"` perdiendo el mensaje (`frontendApi.ts:1012`, F4).
- Relacionados: `/geophysics-status` tampoco sanitiza NaN; `excepts` globales que tragan el traceback (`gravity_import_service.py:678`).
- **Fix:** sanitizar NaN→null en TODA salida del backend (encoder global), y en TODOS los proxies leer `text()` + `JSON.parse` en try/catch propagando el status real. Helper compartido único.

### D. 🟠 Física duplicada en TypeScript que diverge del backend
Viola tu propia Regla de Oro ("el FE no calcula física").
- Constantes de densidad 2.6/4.2 en el bundle cliente (`geophysicsModel.ts:5`).
- EPSG derivado en TS (`GravityCsvPreviewPanel.tsx:40`) — duplica Python.
- `cellSize` re-inferido en TS con default mágico 10 m (`frontendApi.ts:1125`) — ignora el block_size real (1552 m).
- `domainL/H/W` recalculados desde el subconjunto devuelto, ignorando los headers `X-TQ-Bounds` autoritativos (`frontendApi.ts:1196`).
- **Lógica de color clonada** worker vs hilo principal → divergen (causa E del joint cian).
- **Fix:** el backend es la única fuente de verdad física; el FE solo consume (headers/payload). Extraer la lógica de color a un módulo compartido importado por worker y main.

### E. 🔴 Ejes Norte/Este inconsistentes
La física usa `x=Norte, z=Este`; la georef/DEM y el frontend asumen `x=Este, z=Norte`.
- `elevation_enrichment_service.py:258` (P0) → lat/lon y elevación **transpuestas**; es consistente con tu "no toma en cuenta el mapa".
- Visualizador muestra el cuerpo rotado 90° (`terraQuantumGeology.ts:304`, TRACE-01).
- **Fix:** UNA convención canónica documentada en el contrato + test de esquina conocida (vóxel NE → lat/lon esperado por pyproj).

### F. 🔴 Economía calculada sobre datos inexistentes
- El parquet de inversión **no tiene** grade/tonnage/domain → NPV/pit se calculan sobre ceros y se devuelve `done` (P0 econ-grade-tonnage-zero-01).
- El "grade" es un **proxy de densidad**, no ensayo químico; aun así se emite NPV en USD como defendible (P0 econ-grade-proxy-02).
- `cutoff_grade` sin el factor /100 → off-by-100x (`pit_design_service.py:545`).
- `domain=0` default → todo estéril; tonelaje "normalizado a 25 m" mezcla escalas en el NPV (`scheduler.py:156`).
- **Fix:** exigir columnas de ensayo reales o etiquetar TODO como "proxy no validado" en la **respuesta de la API** (no solo el PDF). No emitir NPV en USD sin ley real.

### G. 🟠 Escala y profundidad física
Tus síntomas "157 km se ve como 2 km" y "cuerpo plano cortado por láser".
- `buildGridConfig` fija nx=nz=8, blockSize=10 m → dominio fijo de 80 m sin importar la escala (`geophysicsModel.ts:122`).
- La grilla colapsa el dominio físico; la cámara hereda el colapso (TRACE-06).
- Cuerpo aplanado: pocas capas verticales (ny bajo) + depth-weighting β=2 (TRACE-05).
- **Fix:** derivar la grilla del bounding box real de los sensores; validar `nx·block_size ≥ extensión del survey`; subir resolución vertical; mostrar escala métrica real.

### H. 🔴 Seguridad (descalifica "industrial" por sí sola)
- **Clave privada RSA real de GCP** sin cifrar en disco dentro de OneDrive sincronizado (`credenciales_gee.json`, P0).
- **API key en el bundle del navegador** vía `NEXT_PUBLIC_TQ_API_KEY` (`frontendApi.ts:703`, P0) → auth inútil, permite DELETE de runs.
- Auth fail-**open** por defecto; Docker corre como root sin definir auth; CORS sin guardia contra `*`; path traversal en `export_vtr`; comparación de master key vulnerable a timing; deps sin pin.
- **Fix inmediato (hoy, fuera de código):** rotar/revocar la service account de GCP y la API key `tq_8YBe...`. Luego: keys solo server-side, auth fail-closed, usuario no-root, `.dockerignore`, lockfile.

### I. 🟠 Tests teatro (por esto "todo funciona")
- `scripts/validation/` **nunca** corre en pytest (`pytest.ini:2`).
- Benchmarks sin funciones `test_` → 0 asserts colectados; `--ci` siempre `exit(0)` sin umbral.
- Asserts dentro de `if status==422` (pasan si el gate nunca dispara); `ok=True` hardcodeado; comparación de un run **contra sí mismo**.
- **Fix:** asserts duros contra ground-truth sintético (pearson_r, profundidad, posición), en CI, con umbrales reales. Esto es lo que convierte "verde" en "verdad".

### J. 🟡 Calibración de la inversión (requiere criterio geofísico)
- `density_min = base_density = 2.6` → no puede recuperar contrastes negativos (`gravimetry.py:925`).
- Depth-weighting solo en la suavidad (Laplaciano), no en la smallness → masa somera no corregida.
- L-curve mide una roughness distinta a la penalizada → λ "óptimo" inconsistente.
- Cross-gradient joint con escalado asimétrico entre física grav/mag.
- **Fix:** revisar con tu agente `geophysics-benchmark-reviewer` contra ground-truth, una hipótesis a la vez.

---

## 3. Plan secuencial (principio a fin)

> Regla: **una causa por iteración**, nunca backend+frontend en el mismo cambio (tu Regla de Oro). Cada fase tiene un criterio de "hecho" verificable.

### FASE 0 — Seguridad (HOY, no es código) 🔴
Rotar la key de GCP y la API key expuesta. **Hazlo tú** (son credenciales).
✔ Hecho: keys viejas revocadas en GCP IAM y backend; nuevas fuera de OneDrive.

### FASE 1 — Desbloqueo: que el flujo básico funcione (causa C + bugs de contrato) ✔ COMPLETADA
Para poder *probar* cualquier otra cosa necesitas importar CSV.
- Sanitizar NaN en `/preview` y `/geophysics-status`.
- Proteger TODOS los proxies (`text()`+`JSON.parse` en try/catch).
- Arreglar `exportRunUrl` (`runId`→`run_id`) y el puerto del chat (`IAChatView` 8000→8010).
✔ Hecho (2026-06-03): subes un CSV real (con huecos/NaN) y ves preview o un error claro, nunca "no es JSON".

### FASE 2 — Honestidad: matar los fallbacks y activar los gates (causas A + B) — *la palanca #1* ✔ COMPLETADA
El cambio arquitectónico que más acerca a "industrial". Va a *romper* cosas en pantalla — bien: eso es la verdad saliendo a la luz.
- Política null/degraded en backend y frontend; prohibir `||0`/`||1` en campos físicos.
- Banner de "modelo no recuperado" en DatosView/ExecutiveReport cuando el run es degenerado.
- Gates que realmente bloqueen (o renombrar).
✔ Hecho (2026-06-03): un run fallido se ve como fallido; un modelo sin densidad NO se pinta; gates 422 reales.

### FASE 3 — Verdad física en pantalla (causas D + E + G) ✔ COMPLETADA
- Backend única fuente de verdad: emitir cell_size, bounds, EPSG, density_min/max; FE solo consume.
- Una convención de ejes + test de esquina. (E: pospuesto a iteración posterior)
- Grilla derivada del survey real; escala métrica correcta.
- Módulo de color compartido worker/main.
✔ Hecho (2026-06-03): 157 km se ve como 157 km; headers X-TQ-* como verdad única; no hay re-cálculo mágico en TS; densityMin/Max autoritativos.

### FASE 4 — Física de la inversión (causa J, con `geophysics-benchmark-reviewer`)
Depth-weighting, λ/L-curve, contrastes negativos, joint. Una hipótesis a la vez, validada contra ground-truth.
✔ Hecho: el self-test sintético recupera profundidad/posición conocidas con pearson_r ≥ umbral.

### FASE 5 — Economía honesta (causa F)
Exigir ensayo real o etiquetar proxy en la API; corregir unidades (cutoff /100, tonelaje); no emitir USD sin ley real.
✔ Hecho: no hay NPV en USD sobre datos inventados; el proxy está rotulado como tal en la respuesta.

### FASE 6 — Tests reales + CI (causa I)
Asserts contra ground-truth, en CI, con umbrales. Sin esto, todo lo anterior se degrada en silencio otra vez.
✔ Hecho: romper a propósito la inversión hace fallar el CI.

### FASE 7 — Hardening de producción (resto de H + perf + limpieza)
Auth fail-closed, Docker no-root, `.dockerignore`, lockfile de deps, CORS, path traversal, timing; borrar `*_tmp.py`, `.bat` con rutas absolutas, controles fantasma (sliceThickness, input de magnetometría, "Exportar PDF"), `console.log` en hot paths, polling muerto del store.
✔ Hecho: deploy reproducible y cerrado por defecto; sin controles que mientan.

---

## 4. Los 18 P0 (showstoppers) — referencia rápida

| # | ID | Qué | Archivo | Causa |
|---|----|----|---------|-------|
| 1 | csv-json-01 / CONTRACT-003 | `/preview` no sanitiza NaN → CSV "no es JSON" | gravity_import_api.py:597 | C |
| 2 | csv-mag-01 | Magnetometría imposible de importar (exige gravedad) | gravity_import_service.py:30 | — |
| 3 | georef-axis-conflict | Ejes N/E transpuestos en georef/DEM | elevation_enrichment_service.py:258 | E |
| 4 | econ-grade-tonnage-zero | Economía sobre ceros, devuelve `done` | block_model_service.py:100 | A/F |
| 5 | econ-grade-proxy | NPV en USD sobre "grade" proxy de densidad | pit_design_service.py:377 | F |
| 6 | grav-gate-01 | "Hard gate" espacial es no-op | gravity_import_api.py:480 | B |
| 7 | sec-secret-01 | Clave RSA de GCP real en OneDrive | credenciales_gee.json | H |
| 8 | sec-secret-02 / TQ-VIEWS-003 | API key expuesta al navegador (NEXT_PUBLIC) | frontendApi.ts:703 | H |
| 9 | joint-divergence / TRACE-02 | Worker pinta gravity-only como joint cian (>50k vox) | voxelBufferBuilder.worker.ts:376 | A/D |
| 10 | F1 | `getF32` devuelve ceros si falta columna | frontendApi.ts:1156 | A |
| 11 | CSV-P0-01 | Coords de Chile hardcodeadas si faltan anchors | GravityCsvPreviewPanel.tsx:584 | A |
| 12 | DV-01 | KPI muestra densidad etiquetada como mGal | DatosView.tsx:77 | A |
| 13 | DV-02 | Run totalmente fallido se ve como análisis normal | DatosView.tsx:334 | A |
| 14 | DV-03 | "probability" (ranking) mostrado como Score 100% | DatosView.tsx:47 | A |
| 15 | TQ-VIEWS-001 | IAChat apunta a puerto equivocado (8000) | IAChatView.tsx:36 | — |
| 16 | TQ-VIEWS-002 | IAChat no envía API key → 401 en prod | IAChatView.tsx:36 | C/H |

> (Algunos P0 son el mismo defecto visto desde dos subsistemas: #1≈CONTRACT-003, #8≈TQ-VIEWS-003, #9≈TRACE-02. Defectos P0 únicos ≈ 15.)

---

## 5. Cómo seguir
Trabaja por fases, de arriba hacia abajo. Para cada cambio: scope chico, un lado (backend **o** frontend), y validar con el criterio "✔ Hecho". Para las fases físicas (4) y de seguridad (0/7), apóyate en los agentes auditores del proyecto con un invariante numérico concreto, no con "revisa esto".
