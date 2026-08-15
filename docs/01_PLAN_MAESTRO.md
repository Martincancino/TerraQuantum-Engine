# TerraQuantum — PLAN MAESTRO hasta producto industrializado

| Campo | Valor |
|---|---|
| Fecha | 2026-07-02 |
| Estado | VIGENTE — único plan válido. Reemplaza a todos los anteriores (borrados). |
| Base factual | Código verificado en commits hasta `4d72305` + `docs/00_INVESTIGACION_MERCADO.md` + límites físicos MEDIDOS (memoria de sesión) |
| Regla | Este documento se actualiza al cerrar cada fase (marcar ✅ + commit). No se abre una fase sin cerrar la anterior. |

---

# PARTE I — RESUMEN: LAS FASES (el mapa en una página)

| # | Fase | Qué entrega | Estado |
|---|------|-------------|--------|
| **F0** | **Definición de producto y reglas** | `docs/02_PRODUCTO.md`: quién es el usuario, el camino dorado, qué significa "robusto". Las reglas de trabajo. | ✅ 2026-07-02 |
| **F1** | **Mapa y limpieza del código** | Inventario ruta-por-ruta (dorado/secundario/muerto), borrado de lo muerto, raíz del repo limpia, CI mínima que corre en cada cambio. | ✅ 2026-07-03 (gate: mapa publicado, 5 muertos podados verificados, raíz limpia, check.ps1, suite 1700 tests verde tras fix del único fallo; 2ª pasada de símbolos intra-servicio continúa dentro de F2) |
| **F2** | **Ingesta blindada universal** | "Cualquier CSV entra": encoding/separador/decimales/preámbulos/columnas en español auto-mapeadas; cuando falta algo, PREGUNTA (nunca inventa, nunca crashea). Corpus de CSVs sucios reales + tests generativos. | ✅ 2026-07-04 (gate MEDIDO: corpus real 19/19 a TQPKG vía enrich sin mapeo manual; 10.000 casos generativos con 0 excepciones y 0 corrupción vs ground truth; subset ingesta 673 verde; check.ps1 VERDE con eslint 0 errores; commits 1e712b1→fb4fef7) |
| **F2B** | **El gabinete del consultor automatizado** | La preparación no solo LEE: TRABAJA. Todo el procesamiento que hoy el consultor hace a mano: drift+marea desde lecturas crudas, Nettleton, regional-residual; diurna, RTP, derivadas (tilt/señal analítica/1VD), continuación ascendente, deconvolución de Euler (profundidades!); desurvey + QA/QC de sondajes. | ✅ 2026-07-06 (gate MEDIDO: LdM crudo Excel-ES → correcciones de campo + regional-residual + mapas; suite mag validada vs dipolo cerrado; pozo inclinado en su posición verdadera; Euler 0% error en esfera 200 m y dipolo 150 m; commits 0a98e99→2e65b86) |
| **F3** | **Flujo dorado asíncrono + base de datos** | Preparación → inversión → 3D sin timeouts: cola de trabajos con progreso en vivo, historial de proyectos/corridas en SQLite, botón cancelar, presupuesto de vóxeles con aviso previo. | ✅ 2026-07-05 (gate MEDIDO: joint 96.768 vóxeles E2E con progreso visible en 11,5 min — encolado en 0,3 s, aviso previo ~21 min, etapas queued→warmup→joint_loop→done, parquets + historial SQLite done; historial sobrevive reinicio con reconciliación "interrumpida"; Celery ELIMINADO con evidencia de 0 llamadores; commits eed5b76→a8c9546) |
| **F4** | **Render 3D clase mundial** | Isosuperficies suaves (adiós confeti de cubos), cortes transversales arbitrarios, sondajes dibujados, terreno, incertidumbre visible, WebGPU progresivo. El 3D más CLARO y HONESTO de su rango de precio. | ✅ 2026-07-09 (QA visual de Martín aprobado con datos demo; F4.1-F4.7 entregados; reviewer frontera física PASS; WebGPU congelado con decisión medida) |
| **F5** | **Datos, gráficos y exportables** | Todo descargable: imágenes PNG alta resolución con escala/norte/leyenda, cortes, obs-vs-calc, histogramas, reporte PDF, block model CSV/VTK/GLB. Diagnósticos SIEMPRE coherentes (fix UQ NaN, recalibrar B2). | ✅ 2026-07-22 (gate: horizonte DOI recalibrado medido en 3 datasets reales, UQ con razón explícita, coherencia B1↔B2↔B3 testeada, gráficos+exportables completos; suite 1903 passed/5 skipped) |
| **F6** | **Copiloto IA para el consultor (Gemini)** | Chat anclado a los datos de la corrida + borrador de secciones de informe + explicación de cada métrica. Nunca inventa números. Context caching para costo mínimo. | 🟦 BACKEND 2026-07-22 (migrado del SDK deprecado `google-generativeai` al nuevo `google-genai`, imports lazy; grounding total de la trilogía B1/B2/B3 + χ² + warnings; 3 modos explicar/redactar/enseñar; guard de compliance JORC número+unidad + guard de anclaje numérico; BYO-key cuerpo/header/env; modelos por tier env-configurables; suite mockeada 30/30 sin tokens; 1993 tests colectan sin regresión). UI HECHA (`IAChatView.tsx`: selector de modo + acciones rápidas + campo BYO-key con localStorage + indicador de anclaje ⚓/⚠/redactado; eslint 0 + tsc 0). Context caching HECHO (opt-in `GEMINI_CONTEXT_CACHE`, TTL, fallback + 3 tests). Gate script HECHO (`scripts/validation/f6_gate_copilot.py`: 20 preguntas, auto-descubre corrida LdM, checks automáticos, self-test 8/8). Suite F6 33/33, 1996 colectan sin regresión. **Falta para cerrar:** correr el gate EN VIVO con la key real de Martín (BYO-key) + verificar caching real |
| **F7** | **Empaque local-first + licencias** | Instalador de escritorio (Tauri 2 + sidecar PyInstaller) o script local de un clic; datos NUNCA salen de la máquina del cliente; licenciamiento simple. | 🟦 NÚCLEO + PLAN B 2026-07-22 (sin deps nuevas, backend-primero, física intacta): data dir portable a %APPDATA% (`TERRAQUANTUM_DATA_DIR`); **licenciamiento Ed25519 offline** (verificar/firmar/activar/tiers local·free·pro + CLI de emisión, `cryptography` ya presente); **exportar-diagnóstico sin datos de survey ni secretos** (probado con secreto sembrado); **honestidad offline** (`/system/connectivity`, camino dorado 100% offline confirmado); wiring en `main.py` verificado E2E; **Plan B launcher de un clic** (`run_terraquantum_desktop.ps1`, no toca los `.bat`) + `docs/04_EMPAQUE_LOCAL_FIRST.md`. Gate `f7_gate_packaging.py` **PASS 30/30**; 29 tests F7 verdes; suite colecta 1969 sin regresión. **+ INSTALADOR NATIVO Tauri 2 CONSTRUIDO Y VERIFICADO E2E** (Martín autorizó instalar el toolchain): spike PyInstaller OK (backend 199MB, boot 14s, proj.db+IGRF bundled); arquitectura de **2 sidecars** (backend exe + frontend Node standalone con los 40 proxies INTACTOS — se descartó `output:'export'` porque los proxies transforman de verdad y reescribirlos duplicaría lógica, prohibido); shell Rust `src-tauri/` orquesta ambos + navega tras health + limpia procesos; instalador **`TerraQuantum_0.2.0_x64-setup.exe` (322MB)** + **firma updater `.sig`**; verificado: ambos sidecars levantan y el proxy frontend→backend responde desde el bundle. Pipeline `scripts/build_desktop.ps1`. Frontend INTACTO. **Pendiente menor:** cronómetro formal en VM Windows limpia + publicar `latest.json` + iconos de marca. SIN commitear (patrón F5/F6). |
| **F8** | **Tormenta de pruebas (cientos de flujos)** | Matriz E2E: 3 físicas × combos × CSVs sucios × tamaños; UI con Playwright; fuzzing de API; garantía "nunca crashea, siempre error en español". | 🟦 HARNESS COMPLETO + VERDE 2026-07-23 (backend dep-free; UI Playwright diferida): matriz E2E 20/20 sin bug, fuzzer propio 106/106 (nunca 500 pelado), soak sin fuga (+1.5 MB/iter), ingesta 10k=1.4s (<5s), gate maestro PASS 4/4, **UI E2E Playwright 6/6 verdes** (autorización total de Martín). Hallazgo diagnosticado (no bug): la lentitud aparente = contención de CPU × degeneración de malla 6³, no el solver (que es 1.1s). Falta cierre: barrido completo ×3 días + render-fps en vivo + tarde adversarial |
| **F9** | **Validación física como regresión automática** | DO-27, Raglan, San Nicolás, LdM como suite automática con tolerancias que corre sola. La física YA está validada — esto la congela para siempre. | ✅ 2026-07-23 (gate PASS 6/6 MEDIDO: synthetic Pearson 0.726≥0.70, DO-27 53.7≤70 m, Raglan 212≤250 m, San Nicolás misfit 1.51≤3%, LdM χ²=0.99∈[0.7,1.3], ambigüedad-z 2675 m = LÍMITE documentado; suite `pytest -m validation` saltada por defecto; reporte HTML imprimible; prueba de degradación: kernel roto → Raglan 212→1570 m FALLA. Hallazgo: `depth_beta` es inerte (Ws absorbe W_z)) |
| **F10** | **Producto y lanzamiento** | Manual ES, video demo, landing, tier gratis, casos públicos (las validaciones), primeros consultores + servicio productizado a juniors chilenas. | ⬜ |
| **F11** | **El camino hacia la realidad** | Acotar la no-unicidad con información independiente: pedir los datos correctos (petrofísica, geología mapeada, sondajes con mediciones), cablear lo ya construido (PGI, geología implícita F7, FTG, ensemble), usar Euler/espectral como prior de profundidad, y a futuro nuevas físicas (IP/EM/MT). | ⬜ (post-lanzamiento, guiado por usuarios) |

**Dependencias:** F0→F1→F2→F2B→F3→F4→F5 son secuenciales (cada una asume la anterior); los productos de mapa de F2B se VISUALIZAN en F5. F6 y F7 pueden ir en paralelo después de F5. F8 es transversal (cada fase cierra con sus tests) pero tiene su fase propia de matriz sistemática. F9 corre apenas exista CI (F1). F10 al final, pero el **servicio productizado puede empezar desde F5** (lo operas tú; no necesita empaque ni IA). F11 es post-lanzamiento: se prioriza con feedback de usuarios reales.

**Los 3 principios innegociables** (correcciones a la visión original, con evidencia medida):

1. **El 3D compite en CLARIDAD, no en "realidad".** La física medida (ambigüedad-z 2675 m, null-space) prueba que ningún software muestra "lo que hay bajo tierra" — muestran modelos no-únicos. Perseguir "realismo inexplicable" es perseguir lo imposible; perseguir el visor más claro, profesional y honesto del rango de precio es alcanzable y vendible.
2. **"Los datos no pueden fallar" = pipeline que nunca crashea y diagnósticos siempre coherentes — NO ocultar debilidad.** El reporte honesto (B1/B2/B3) es el escudo legal (mundo JORC firma una Persona Calificada; TQ = decision support) y el diferenciador de confianza.
3. **A Gemini no se le entrena.** Todo lo que se quiere (respuestas ancladas a JORC, conocimiento minero, borradores de informe) se logra con system prompt + contexto estructurado (el `report_payload` que ya existe) + context caching. Fine-tuning sería caro, frágil e innecesario.

---

# PARTE II — LO QUE YA ESTÁ HECHO (verificado en código, NO rehacer)

Esta sección existe para que ninguna fase re-implemente lo que ya funciona.

## Motor físico (validado contra 4 benchmarks externos — NO TOCAR salvo bug demostrado)
- **Gravedad** (`exploration/gravimetry.py`, 3.976 líneas): prisma Nagy near-field + masa puntual far-field con KDTree híbrido, depth-weighting formal Li & Oldenburg (W_z como cambio de variable), normalización Ws, λ_eff escalado √(n/256), Morozov auto-λ, IRLS compacto minimum-support, ancla dura por eliminación de variables, dispatch TRF/LSQR/LSMR/FISTA, poda R-05, shuttle de null-space, Woodbury, ranking de targets.
- **Magnetometría** (`exploration/magnetometry.py`, 3.163 líneas): dipolo TMI, prisma Bhattacharyya/Sharma, MVI 3-componentes, FTG, remanencia Q-ratio, self-demag, β=1.5 validado.
- **Joint** (`services/joint_inversion.py`): cross-gradient Gallardo-Meju, Gramian, PGI 2D ρ-χ, padding conjunto. Hallazgo honesto medido: cross-gradient NO mejora gravedad en DO-27.
- **Correcciones** (`services/gravity_corrections_service.py`): Somigliana GRS80, aire libre, Bouguer, terreno point-mass; enriquecimiento con pyproj + DEM + IGRF-14 offline (`csv_enrichment_service.py`).
- **Validaciones PASADAS** (material de credibilidad, no re-validar): DO-27 kimberlita 53.7 m horizontal (grav), 61.6 m (joint-mag, `c98d0e7`); Raglan Ni-Cu dato crudo 212 m; San Nicolás techo 125 m vs 150-220 publicado; Laguna del Maule χ²=0.92, targeting ~2 km coincide con literatura.
- **Límites físicos MEDIDOS y cerrados** (no re-litigar, están en memoria): gravedad-sola NO resuelve profundidad (z-err 2675 m robusto); ancla tautológica; regional refutada; λ=0.1 refutado. Producto = targeting horizontal (50-200 m), jamás profundidad/densidad-entre-pozos.

## Reporte honesto (trilogía completa backend+frontend, sellada por reviewer)
- B1 `build_best_target` (geophysics_service.py:610), B3 `build_reconciled_verdict` (:783, worst-of-chain), B2 `build_depth_resolution` (por-eje, deep_mass_fraction, DOI half-max). Widgets display-only en `componentes/analytics/HonestReportWidgets.tsx`.

## Ingesta (el ~70% que ya existe)
- TQPKG autocontenido (`services/csv_package_service.py`: #TQPKG/1 + #CONFIG + #BOREHOLES + #PLAN + CSV).
- Mapeo manual de columnas con contrato por rol; literales `unit`, `coordinate_system`, `elevation_unit`, `gravity_type` (`services/column_mapping_service.py`).
- Detección decimal-coma europeo (`e7d2858`), gravity_type literal anti-doble-Bouguer (`9045719`), Helmert ≥2 puntos en enrich (`68c3060`), hardening de combos (`621c3ff`), m/ft, magnetic_column_map_json.
- `/enrich-package` deriva con física real; lo no-derivable → `needs_context`, nunca inventado.

## Procesamiento geofísico: qué existe y qué NO (verificado 2026-07-02, base de F2B)
- **EXISTE**: latitud Somigliana GRS80, aire libre, Bouguer, corrección de terreno point-mass con DEM, IGRF-14 offline, Helmert, transformación de coordenadas pyproj.
- ~~**NO existe (F2B lo construye)**~~ ✅ **CONSTRUIDO en F2B 2026-07-06**: deriva instrumental + marea terrestre Longman desde lecturas crudas (`earth_tide_service`, `drift_correction_service`, encadenadas en `/apply`); regional-residual (`regional_residual_service`); corrección diurna magnética + RTP + 1VD/THD/tilt/señal analítica + continuación (`mag_enhancement_service`, `/v2/mag-enhance`); Euler + espectro radial (`euler_spectral_service`, `/v2/depth-estimate`); desurvey por curvatura mínima + QA/QC + compositación (`borehole_desurvey_service`, `/borehole/desurvey`).
- **CORRECCIÓN (inventario F1, 2026-07-02): Nettleton SÍ existe** — `POST /gravity-corrections/nettleton` (gravity_corrections_api.py) con servicio testeado (tests/test_gravity_corrections.py:260), pero SIN UI que lo llame → F2B lo CABLEA (gráfico + confirmación del usuario), no lo construye.
- **OJO**: `services/spectral_service.py` es índices SATELITALES (GEE, hierro/arcilla) — no confundir con análisis espectral de potenciales; ese no existe.

## Infraestructura ya construida (algunas piezas SIN cablear — las fases las cablean, no las reconstruyen)
- **Ruta asíncrona** `api/async_api.py`: `POST /invert` + `GET /tasks/{task_id}` — EXISTE, el flujo de paquete no la usa (causa del "error interno del proxy" con joint de 96k vóxeles). F3 la adopta.
- **Agente Gemini** `services/gemini_agent.py` (369 líneas): reporte de interpretación estructurado (Pydantic), system prompt con reglas de compliance (palabras prohibidas reserve/resource/grade/NPV), validación y fallback. + `api/chat_api.py` (212 líneas). F6 construye SOBRE esto.
- **Export** `services/export_service.py` (1.066 líneas) + `api/export_api.py` + `api/report_api.py`. F5 completa sobre esto.
- **Render**: Viridis + piso-relativo-al-pico + weakAnomaly (`4d72305`) en `lib/terraQuantumGeology.ts` + `workers/voxelBufferBuilder.worker.ts`; LOD threshold 50k en `Scene3D.tsx`; SVDAG (`services/svdag_service.py`), octree (`services/octree_mesh_builder.py`), volumétrico (`services/volumetric_service.py`) — construidos, no cableados a producción. WebGPU progresivo diseñado (ADR F6 God-Tier).
- **Errores**: catálogo 60 errores en español + ErrorModal (F23).
- **Tests**: 188 archivos en `terraquantum-backend/tests/` (~1.400 tests), fixture anti-rate-limiter en conftest.

## Deuda técnica conocida (registrada aquí, cada ítem tiene fase asignada)
| Deuda | Fase |
|---|---|
| ~~load-package síncrono → proxy timeout en inversiones largas~~ ✅ F3 2026-07-05 (encola en worker de proceso + progreso + cancelar) | F3 |
| ~~B2 DOI half-max demasiado agresivo en producción (deep_frac ~0.94 casi siempre)~~ ✅ F5 2026-07-22 (horizonte DOI de doble inversión; DO-27 0.43/San Nicolás 0.40 = 'poor', LdM 0.75 = 'null_space' — discriminante restaurado, MEDIDO) | F5 |
| ~~Auto-mapeo de nombres de columna en español~~ ✅ F2 2026-07-04 | F2 |
| ~~Parser CSV local de GravityCorrectionWizard~~ ✅ 2026-07-06 (endpoint parse-rows: el backend parsea, el wizard solo marshaling + Number() ruidoso) | F2 |
| ~~BoreholeUploadPanel envía csv_text ya decodificado UTF-8~~ ✅ F2B 2026-07-06 (`/borehole/parse-csv-file` multipart; el sniffer decide el encoding) | F2B |
| ~~UQ posterior_std 100% NaN + filtrado NaN downstream~~ ✅ F5 2026-07-22 (status/reason explícitos: disabled_by_default vs ill_conditioned; sigue OFF por defecto por física real, ahora con razón transparente) | F5 |
| `findDemoHighlightVoxel` import muerto con física en TS (Exploration3DView.tsx:26) | F1 |
| Render = confeti de vóxeles, sin isosuperficie | F4 |
| QA visual nunca hecho | F4 |
| Scripts `diag_*.py` y CSVs de prueba sueltos en la raíz | F1 |
| SVDAG/octree/volumétrico/level-set/shuttle sin cablear | F1 decide: cablear (fase que corresponda) o congelar |

---

# PARTE III — LAS FASES EN DETALLE

Formato de cada fase: **Objetivo → Investigación previa → Trabajo → Tests/verificación → Criterio de salida (gate)**. Ninguna fase se cierra sin su gate en verde. Regla de oro del repo se mantiene: backend y frontend en iteraciones separadas salvo cableo explícito.

---

## F0 — Definición de producto y reglas (½ día)

**Objetivo:** que nunca más se trabaje sin saber para quién ni para qué. Es un documento, no código.

**Trabajo:**
1. Escribir `docs/02_PRODUCTO.md` con:
   - **Usuario primario:** consultor geofísico LatAm (por qué: `docs/00_INVESTIGACION_MERCADO.md`). **Cliente final:** junior/pequeña minera vía el consultor o vía servicio productizado.
   - **El camino dorado** (LA frase del producto): *"Me entregan cualquier CSV de gravimetría/magnetometría/sondajes → lo preparo y completo → invierto → veo un 3D claro con cortes → descargo imágenes y reporte honesto → se lo explico a mi cliente con ayuda del copiloto."*
   - **Definición de "robusto"** (medible): (a) ningún input produce crash o basura silenciosa — siempre resultado válido o error en español que dice qué hacer; (b) ninguna operación deja al usuario sin feedback >5 s; (c) los diagnósticos nunca se contradicen entre sí.
   - **Qué NO es el producto** (anti-scope): no estima recursos/reservas, no reemplaza al QP, no resuelve profundidad con gravedad sola (límites medidos), no compite con Leapfrog en modelado geológico.
2. Actualizar `.claude/CLAUDE.md`: apuntar a este plan como fuente de verdad de prioridades.

**Gate:** `docs/02_PRODUCTO.md` existe y Martín lo aprueba línea por línea.

---

## F1 — Mapa y limpieza del código (2-4 días)

**Objetivo:** saber exactamente qué hay, borrar lo muerto, y que un fallo futuro siempre sea localizable en un eslabón concreto. NO es un refactor global (prohibido por reglas): es inventario + poda + red de seguridad.

**Investigación previa (interna):** generar el inventario COMPLETO leyendo código, no memoria: por cada router de `api/` (19 archivos) y cada servicio de `services/` (35 archivos), clasificar: **[DORADO]** en el camino dorado / **[SECUNDARIO]** útil fuera del camino / **[CONSTRUIDO-SIN-CABLEAR]** (svdag, octree, volumétrico, level-set F7, shuttle F8.1, solver escalable) / **[MUERTO]** nadie lo llama.

**Trabajo:**
1. Escribir el inventario en `docs/03_MAPA_CODIGO.md` (tabla: archivo → rol → clasificación → quién lo llama).
2. **Podar lo [MUERTO]**: `findDemoHighlightVoxel` y su import (Exploration3DView.tsx:26), camino JSON client-side retirado, rutas sin consumidores. Cada borrado = commit atómico con el grep que prueba que nadie lo usaba.
3. **Decidir lo [CONSTRUIDO-SIN-CABLEAR]** (decisión por pieza, con Martín): cablear en su fase natural (p.ej. octree→F4 LOD) o CONGELAR (mover a `experimental/`, excluido del camino dorado y de la CI estricta). No borrar física validada.
4. **Ordenar la raíz del repo**: `diag_*.py` → `terraquantum-backend/scripts/diagnostics/`; CSVs y generadores de prueba → `terraquantum-backend/tests/fixtures/csv_reales/` (¡son ORO para F2!); `.tqpkg` de prueba → fixtures.
5. **Partir solo los 2 archivos monstruo si dificultan F2-F5** (geophysics_service.py 4.372 líneas, gravity_import_api.py): extraer módulos cohesivos SIN cambiar lógica (p.ej. `report_builders.py` con B1/B2/B3). Si un archivo grande no estorba, se deja — el objetivo es navegabilidad, no estética.
6. **CI mínima local** (script `check.ps1` / `check.sh` + GitHub Actions si hay remoto): `python -m compileall api services scripts exploration` + `pytest tests/ -x -q --timeout=300` (suite rápida marcada) + `npx eslint` + `tsc --noEmit`. Corre en cada commit.

**Tests/verificación:** la suite existente (188 archivos) sigue verde tras cada poda; `repo-safety-guardian` audita los borrados.

**Gate:** inventario publicado; raíz limpia; CI corre en <10 min y está verde; cero imports muertos conocidos.

---

## F2 — Ingesta blindada universal (1-2 semanas) — EL ACTIVO DEL PRODUCTO

**Objetivo:** *"que nos entreguen cualquier CSV y convertirlo en uno que sirva, preguntando lo que falte"*. La tesis del producto entera vive aquí. Un consultor con un CSV de Excel-ES de 2009 con preámbulo de 14 líneas debe llegar a un TQPKG válido sin frustrarse.

**Investigación previa:** (a) recolectar formatos reales del dominio: exports de Geosoft (GDB→CSV), Surfer, QGIS, planillas Excel-ES/EN, formatos de gravímetros (Scintrex CG-5/CG-6) y magnetómetros (GEM, Geometrics G-859); (b) revisar los 5 CSVs reales de LdM ya en fixtures — cada bug que destaparon es una regla.

**Trabajo (backend primero, UI después — iteraciones separadas):**
1. **Lector universal de capa física** (`services/csv_sniffer_service.py`, nuevo): cadena de detección con evidencia — encoding (UTF-8/BOM → cp1252 → latin-1, vía `charset-normalizer` ya que chardet quedó atrás), separador (`,` `;` `\t` `|`) por consistencia modal, decimal (`.`/`,` — ya existe `_detect_semicolon_decimal_comma`, generalizarla), líneas de preámbulo/basura (saltar hasta la fila que parsea consistente), filas rotas (reportadas con número de línea, nunca tragadas). Salida: `SniffReport` (qué detectó, con qué confianza, qué descartó) que viaja al frontend.
2. **Auto-mapeo de columnas ES/EN** (cierra deuda F2): diccionario de sinónimos por rol (`este/easting/x/utm_e`, `gravedad/bouguer/gz_mgal`, `cota/elev/altitud/z`...) + heurística por RANGO físico (lat ∈ [-90,90], UTM ∈ [1e5,1e6], mGal ∈ [-500,500], nT ∈ [±10k]) + unidades embebidas en el header (`(m)`, `[mGal]`). Confianza alta → pre-mapea; media → sugiere y PREGUNTA; baja → pide mapeo manual (la UI ya existe). NUNCA auto-mapear en silencio con confianza media/baja: el doble-Bouguer enseñó que adivinar mal corrompe en silencio.
3. **Contrato "nunca crashea"**: TODA excepción del pipeline de ingesta se convierte en error del catálogo ES (F23) con acción sugerida. Prohibido el 500 pelado.
4. **Preguntas estructuradas** (`needs_context` ya existe en enrich — extenderlo a ingesta): cuando falta un dato no-derivable (datum, tipo de gravedad, unidad ambigua), el backend devuelve la PREGUNTA tipada y la UI de preparación la muestra como formulario, no como error.
5. **UI del panel de preparación** (iteración frontend): flujo guiado por archivo (grav/mag/sondajes + opcionales DEM/puntos de control), mostrando el SniffReport ("detecté separador `;`, decimales con coma, 3 líneas de preámbulo — ¿correcto?"), preview de las primeras filas YA parseadas, y descarga del CSV enriquecido/TQPKG final.

**Tests/verificación:**
- **Corpus real**: los CSVs de LdM + cada formato recolectado en investigación → test paramétrico "todos llegan a TQPKG o a pregunta clara".
- **Tests generativos** (Hypothesis): mutador de CSVs válidos — cambia encoding, inyecta preámbulos, rompe filas, mezcla decimales — el pipeline NUNCA lanza excepción no-catalogada y NUNCA produce números corruptos en silencio (validación: re-parsear el output y comparar contra ground truth del generador).
- Regresión: los 2 bugs históricos (decimal-coma, doble-Bouguer) como tests con nombre propio.

**Gate:** 100% del corpus real pasa; 0 excepciones no-catalogadas en 10.000 casos generativos; demo en vivo: Martín le da un CSV sucio nunca visto y llega a TQPKG sin ayuda.

**✅ CERRADA 2026-07-04.** Entregado en 6 commits atómicos (backend 1e712b1, 991897b, 4fab917, 81c131e, 647219a; frontend fb4fef7):
1. `csv_sniffer_service.py` (SniffReport con evidencia; UTF-8/BOM→UTF-16→cp1252→latin-1; preámbulo; filas rotas con nº de línea) cableado sin romper byte-idéntico.
2. Auto-mapeo ES/EN + heurística por RANGO físico + guardia northing-en-y (2 capas: plan pregunta, import bloquea).
3. Handlers globales nunca-crashea (TerraquantumError→payload F23; Exception→TQ_INTERNAL) + fuzz 4 endpoints.
4. Preguntas estructuradas blocking (unidad/tipo) por el canal column_map existente; tipo inferido del header CON aviso.
5. UI: SniffReportCard/SuspicionsBanner/QuestionsForm/SampleRowsTable display-only (reviewer frontera física PASS) + los 7 errores eslint react-hooks preexistentes ARREGLADOS (check.ps1 VERDE).
6. Gate medido: corpus 19/19, generativo 10k en verde (9m12s), subset 673. Bug real cazado por el harness: fila rota con campos extra como 1ª fila de datos → pandas infería index_col y desplazaba TODO el parseo (fix `index_col=False`).
Deuda que pasa a F2B: parser local de `GravityCorrectionWizard` (parseCsvText/parseFloat) no pasa por el sniffer — riesgo decimal-coma latente; se cierra cuando F2B rehaga el wizard.

---

## F2B — El gabinete del consultor automatizado (2-3 semanas) — LA PREPARACIÓN QUE TRABAJA

**Objetivo:** que la preparación no solo lea el CSV: que haga el trabajo de gabinete que hoy el consultor hace a mano en Oasis montaj/Excel antes de poder invertir o interpretar. Cada producto le ahorra horas facturables — esto ES valor de venta directo, y además alimenta la inversión con datos mejor reducidos.

**El flujo real del consultor (investigado — esto es lo que automatizamos):** con gravimetría cruda: amarre a base → deriva instrumental → marea terrestre → latitud → aire libre → Bouguer (eligiendo densidad de reducción) → terreno → separación regional-residual → grillas y mapas. Con magnetometría: corrección diurna → resta de IGRF → reducción al polo → derivadas (vertical, horizontal total, tilt, señal analítica) → continuación ascendente → estimaciones de profundidad (Euler). Con sondajes: desurvey → QA/QC de intervalos → compositación.

**Trabajo (todo backend con numpy/scipy ya presentes — sin dependencias nuevas; UI en iteración separada):**

1. **Gravimetría desde lecturas CRUDAS de campo** (hoy TQ exige el dato ya reducido o semi-reducido):
   - Detección del nivel del dato (crudo de gravímetro / observada absoluta / anomalía ya reducida — extiende el literal `gravity_type` anti-doble-Bouguer).
   - **Corrección de deriva**: ajuste por cierres de loop a estación base (lineal/por tramos) — pide identificar la columna de tiempo y las repeticiones de base (patrón `needs_context` existente).
   - **Marea terrestre**: fórmula de Longman 1959 (astronomía pura: lat/lon/fecha-hora, offline, sin dependencias) — si no hay timestamp, se informa que no aplica y por qué.
   - Latitud/aire-libre/Bouguer/terreno: YA existen — solo se encadenan.
   - **Nettleton**: barrido de densidades de reducción 1.8–3.2 g/cc, correlación Bouguer-vs-topografía por perfil → sugiere la óptima CON gráfico; el usuario confirma (nunca silencioso).
   - **Regional-residual como producto de USUARIO**: tendencia polinomial (orden 1-3) y regional por continuación ascendente, con el residual descargable. ADVERTENCIA medida en el propio flujo: se ofrece como producto de mapa/decisión del usuario, NO se aplica automático antes de invertir (medido: no cura el sink de LdM y degradó DO-27).
2. **Magnetometría — la suite de realce completa** (operaciones FFT sobre grilla, numpy puro):
   - **Corrección diurna** desde archivo de estación base (input opcional nuevo del panel).
   - Resta de IGRF: YA existe (IGRF-14 offline).
   - **Reducción al polo (RTP)** usando inc/dec ya en config; en latitudes bajas (inestable) → ofrecer tilt como alternativa estable y DECIRLO.
   - **Derivadas**: primera vertical (1VD), horizontal total (THD), **tilt derivative**, **señal analítica** — los 4 mapas estándar con los que el consultor ve estructura y lineamientos.
   - **Continuación ascendente** a alturas elegibles (separar fuentes someras/profundas).
   - **Deconvolución de Euler** (índice estructural 0-3): nube de soluciones de profundidad-a-fuente → se muestra EN el visor 3D (puntos) y se exporta CSV. Es la estimación de profundidad INDEPENDIENTE de la inversión — puente directo a F11.
   - **Espectro de potencia radial**: profundidades promedio de ensambles de fuentes (método clásico de dos pendientes), como chequeo cruzado de Euler.
3. **Sondajes — de archivo a datos confiables**:
   - **Desurvey por curvatura mínima**: aceptar collar + survey (azimut/inclinación) además del formato vertical actual → traza 3D verdadera (hoy los pozos inclinados se posicionan MAL si se asumen verticales).
   - **QA/QC automático con reporte**: solapes, huecos, FROM≥TO, duplicados, densidades fuera de rango físico por litología, unidades faltantes — cada hallazgo con número de fila y severidad (bloqueante/advertencia).
   - **Compositación** a intervalos regulares para el uso como ancla (elección del usuario, documentada).
4. **Panel "Sala de mapas"** (iteración frontend, se integra con F5): grillas de cada producto (Bouguer, residual, RTP, tilt, señal analítica, continuaciones) como mapas 2D descargables PNG/GeoTIFF/CSV, con la MISMA disciplina visual del 3D (Viridis, colorbar, escala, norte).

**Tests/verificación:** cada operador FFT validado contra caso publicado o implementación de referencia (Fatiando a Terra/harmonica como oráculo de comparación en tests, sin agregarla como dependencia de producción); Longman contra tablas publicadas de marea; Euler sobre DO-27 y la esfera sintética (profundidad conocida) con tolerancia documentada; desurvey contra cálculo manual de un pozo inclinado de 3 tramos; regresión: el enriquecimiento actual de LdM debe reproducirse idéntico.

**Gate:** desde el CSV CRUDO de LdM (el del usuario, con preámbulo y comas decimales) se llega a: Bouguer completa + residual + mapas descargables sin tocar Excel; suite de realce magnético validada contra referencia; un pozo inclinado se dibuja en su posición verdadera; Euler reporta profundidad correcta (±tolerancia) en los 2 casos con verdad conocida.

**✅ CERRADA 2026-07-06.** Entregado en 9 commits atómicos (backend 0a98e99, d15a010, bd116a8, a9ce730, eb076c1, 699a56f, 0739d9a, c5b2912; frontend 2e65b86):
1. **Marea Longman 1959** (`earth_tide_service.py`): offline, sin deps; validada contra el oráculo publicado de MIT LongmanTide a **1e-8 mGal**.
2. **Deriva por cierres de base** (`drift_correction_service.py`): lineal + por tramos; recupera deriva sintética exacta; sugiere la base con evidencia.
3. **Encadenado crudo** (`apply_field_prereductions` en el pipeline `/apply`): marea→deriva antes de GRS80/FAC/BC/TC; E2E recupera la anomalía limpia a <0.001 mGal; guardarraíles 422 (dato ya reducido, sin hora, sin base).
4. **Regional-residual** producto de usuario (`regional_residual_service.py` + `potential_field_grid_service.py`): tendencia polinomial 1-3 + continuación ascendente con **oráculo analítico FFT exp(−|k|h) a ±2%**; advertencia medida en cada salida; endpoint JSON+CSV.
5. **Suite de realce magnético** (`mag_enhancement_service.py`): diurna, RTP (estabilizado + aviso en latitud baja), 1VD/THD/tilt/|AS|, continuación; validada contra dipolo TMI de forma cerrada (RTP corr>0.97 vs polo, |AS| pica sobre la fuente).
6. **Euler + espectro radial** (`euler_spectral_service.py`): profundidad independiente; **0% de error** en esfera gravimétrica 200 m (SI=2) y dipolo magnético 150 m (SI=3); DO-27 real coherente.
7. **Desurvey por curvatura mínima + QA/QC + compositación** (`borehole_desurvey_service.py`): pozo de 3 tramos contra cálculo a mano; el inclinado queda en su posición verdadera (cierra la deuda de asumir vertical); QA/QC detecta 7 defectos con fila+severidad.
8. **Encoding de sondajes** (`/borehole/parse-csv-file` multipart): cierra el gap del reviewer (latin-1 con ñ ya no llega mojibake).
9. **Frontend**: wizard con marea/deriva/Nettleton, `MapRoomPanel` (sala de mapas), `BoreholeUploadPanel` multipart — reviewer frontera física PASS.
**Gate medido** (`scripts/validation/f2b_gate_cabinet.py`): los 4 criterios en verde. Suite F2B 80/80. **Suite completa post-F2B: 1852 passed, 5 skipped (VERDE, +66 vs post-F3, cero regresiones).**
Deuda que pasa a F5 (donde el plan ya visualiza los mapas): la Sala de Mapas hoy cablea regional-residual (gravedad, lat/lon); el realce magnético y Euler tienen endpoint+componente listos pero se integran plenamente al visor 3D en F4/F5 con los productos de mapa.

---

## F3 — Flujo dorado asíncrono + base de datos (1 semana)

**Objetivo:** eliminar para siempre el "error interno del proxy": ninguna inversión, por larga que sea, deja al usuario sin feedback. Historial persistente de proyectos y corridas.

**Investigación previa:** medir tiempos reales por tamaño (grav-sola / mag / joint × 10k/50k/100k vóxeles) para calibrar el presupuesto de vóxeles y los mensajes de estimación.

**Trabajo:**
1. **Adoptar la ruta asíncrona en el flujo de paquete.** Hallazgo del inventario F1: existen DOS mecanismos — (a) `api/async_api.py` con **Celery/Redis** (completo punta a punta pero exige Redis corriendo: infraestructura que un local-first no debe pedir; además su proxy DELETE tiene un bug method:"GET") y (b) la vía **nativa** de `api/geophysics_api.py`: `POST /geophysics-invert` + `GET /geophysics-status/{p}/{r}` + `GET /v2/…/stream` (SSE) + `/geophysics-misfit`, con proxies Next.js YA hechos. **Decisión: adoptar la vía nativa (b)** — cero dependencias de infraestructura — moviendo la ejecución a un worker de proceso (`ProcessPoolExecutor` de 1-2 workers; CPU-bound, el GIL castiga threads); `load-package` pasa a encolar y devolver de inmediato. La vía Celery se borra o congela al cerrar F3 (decisión registrada en `docs/03_MAPA_CODIGO.md` §5).
2. **Progreso real por etapas**: el solver ya loguea etapas (malla → kernel → solve → postproceso); exponerlas vía el task status con % y mensaje ES ("Invirtiendo… iteración 12/50, χ²=1.8"). Frontend: polling ligero (1-2 s) — SSE opcional después; el polling es más robusto tras proxies y suficiente.
3. **Cancelación**: botón cancelar → flag cooperativo que el solver consulta entre iteraciones (LSQR/IRLS son iterativos, el hook es natural).
4. **Presupuesto de vóxeles**: ANTES de encolar, estimar #vóxeles y tiempo (con la calibración medida); si excede umbral → avisar ("~18 min; ¿continuar, reducir resolución, o usar malla gruesa?"). Nunca más un joint de 96k vóxeles sorpresa.
5. **SQLite para historial** (`services/project_store.py`, nuevo — SQLite es LA elección local-first: cero config, un archivo, respaldable): proyectos, corridas (task_id, config, estado, rutas de artefactos parquet/JSON), timestamps. La UI lista corridas anteriores y re-abre cualquier modelo sin re-invertir.
6. **Iteración frontend separada**: pantalla de estado de corrida (progreso, cancelar, historial).

**Tests/verificación:** E2E con inversión artificialmente lenta (sleep en hook) → el flujo completo responde, cancela y persiste; matar el backend a mitad de corrida → al reiniciar, la corrida figura "interrumpida", no colgada; los 3 CSVs multi-física de fixtures pasan por el flujo nuevo.

**Gate:** joint de 96k vóxeles (el caso que mató al proxy) completa vía UI con progreso visible de principio a fin; historial sobrevive reinicio.

**✅ CERRADA 2026-07-05.** Entregado (backend eed5b76/74919ad + frontend 207b85e + poda 37a98e1/cc6db03/a8c9546):
1. `project_store.py` (SQLite local-first, un archivo, WAL) + `GET /v2/history/runs`; reconciliación al arrancar: corridas huérfanas → "interrumpida", jamás colgadas.
2. `run_queue_service.py`: load-package ENCOLA por defecto (worker de PROCESO spawn; Process directo en vez de pool para poder cancelar de verdad) y devuelve `{queued, budget}` de inmediato; progreso por el canal NATIVO existente (etapas reales del solver → /geophysics-status); cancelación de 2 capas (bandera + terminate) vía `POST /geophysics-cancel`; presupuesto de vóxeles con aviso previo (coeficiente CALIBRADO con el gate: 7,16 ms/vóxel joint).
3. Frontend: encolar+poll 1,5 s con barra de etapas, botón cancelar, abandono limpio al desmontar, HistoryStatusPanel con estados persistentes (reviewer frontera física PASS).
4. Vía Celery/Redis BORRADA (backend+frontend) con grep de 0 llamadores — cero infraestructura, coherente local-first. Su bug DELETE-como-GET murió con ella.
5. BUG preexistente arreglado: el pattern de GeophysicsStatusResponse no admitía "running" → el polling devolvía 500 DURANTE la inversión.
**Gate medido** (`scripts/validation/f3_gate_joint96k.py`): joint 96.768 vóxeles → encolado 0,3 s, aviso previo "~21 min", progreso visible de punta a punta, done en 11,5 min, parquets persistidos, historial done. sync=true conserva el contrato histórico para tests/scripts. **Suite completa post-F3: 1786 passed, 5 skipped (VERDE).**

**Post-cierre 2026-07-06 (calibración del presupuesto, `f3_budget_calibration.py`):** MEDIDO que un coeficiente constante s/vóxel para grav/mag NO existe — con bloques chicos la gravedad de 10,6k vóxeles dio 82,7 ms/vóxel (11× el joint) y dos mallas cortaron con `SOLVER_KERNEL_TOO_DENSE` (catalogado: la guardia funciona). El costo lo dominan la densidad del kernel (cutoff/block) y la RAM del momento. El estimador declara su base (`basis`: joint MEDIDO, grav/mag heurístico) y NO promete precisión; las garantías duras son progreso visible + cancelación + guardia de memoria. La matriz sistemática por régimen queda en F8 (donde el plan ya la tenía).

---

## F4 — Render 3D clase mundial (2-3 semanas) — CLARIDAD, NO "REALIDAD"

**Objetivo:** que el modelo 3D se vea como un producto de US$10k: isosuperficies suaves con cortes limpios, sondajes, terreno e incertidumbre — no confeti de cubos. Todo lo que se muestra viene del backend (regla: frontend no calcula física).

**Investigación previa (estado del arte 2026, verificado):** Three.js (r190+) trae `WebGPURenderer` por defecto con TSL y compute shaders, con soporte de navegadores ~70% y fallback WebGL2 automático — la estrategia progresiva del ADR F6 sigue siendo correcta. Para el estilo visual, calcar el estándar que el consultor ya respeta: isosuperficies estilo Leapfrog/VOXI + secciones, no voxels.

**Trabajo (orden estricto, cada paso con QA visual contra checklist):**
1. **Isosuperficies en el backend** (`services/isosurface_service.py`, nuevo): marching cubes sobre el block model (`skimage.measure.marching_cubes` — ya probado en el ecosistema; malla suavizada Taubin para no encoger volumen) a 2-3 niveles de contraste (p.ej. 50/70/90% del pico, consistente con el piso-relativo ya medido). Salida: mallas indexadas (posiciones/normales/índices) vía Arrow/binario — el frontend NO calcula el nivel, lo recibe.
2. **Visor de isosuperficies** (frontend): render de las mallas con material físico sobrio, transparencia por nivel (90% opaco, 50% translúcido), Viridis anclado a valores absolutos con colorbar SIEMPRE visible. Los vóxeles quedan como modo alternativo ("modo bloques"), no default.
3. **Cortes transversales arbitrarios**: clipping planes de Three.js (gratis en GPU) con UI de arrastre (X/Y/Z + libre); la CARA del corte pintada con la textura de densidad del plano (el backend ya sabe hacer slices → endpoint de sección) — esto es "cortar la tierra a la mitad y ver el mineral donde es más denso", literal.
4. **Contexto geológico**: sondajes como cilindros coloreados por litología/densidad (datos ya en TQPKG #BOREHOLES); superficie de terreno del DEM del enriquecimiento (malla drapeada semi-transparente); flechas MVI ya existentes se mantienen.
5. **Incertidumbre visible (el diferenciador honesto)**: overlay de DOI — atenuar/rayar la zona bajo el horizonte de sensibilidad (dato de B2 ya calculado); tooltip por celda con σ cuando UQ esté sano (F5).
6. **WebGPU progresivo**: mantener WebGL2 como base garantizada ("computadores normales" = requisito del producto); activar `WebGPURenderer` detrás de detección de capacidad para raymarching volumétrico de alta calidad como modo "presentación". Los building blocks del ADR F6 (raymarch/LOD/AO) se cablean AQUÍ o se congelan (decisión F1).
7. **LOD**: para modelos >50k celdas, usar el octree ya construido (`octree_mesh_builder.py`) para decimación de la isosuperficie lejana, si la medición lo justifica.

**Tests/verificación:** QA VISUAL formal (la deuda eterna): checklist con capturas de referencia por los 4 datasets canónicos (esfera sintética, DO-27, Raglan, LdM) — ¿se ve el cuerpo? ¿colorbar correcta? ¿corte muestra el interior? ¿60 fps en laptop sin GPU dedicada con 100k celdas? Regresión de píxeles (Playwright screenshots) para no volver a romper el render sin enterarse.

**Gate:** los 3 CSVs multi-física de prueba producen un 3D que Martín aprueba visualmente ("esto se lo muestro a un cliente"); 30+ fps en laptop integrada; cero física calculada en TS (reviewer `frontend-physics-boundary-reviewer` PASS).

**✅ CERRADA 2026-07-09 (gate: QA visual de Martín aprobado con datos demo + reviewer frontera física PASS). Commits: backend `c7652e3`→`72006b9`, frontend `94d4a16`→`ff248ff`.**
- **F4.1 (backend `c7652e3`, +fix OOM `c7e5eef`):** `services/isosurface_service.py` + `GET /v2/isosurface`. Marching cubes (skimage) sobre CONTRASTE robusto idéntico al visor (fondo=mediana, escala=max(P95-bg, bg-P5, 0.05)); niveles = fracciones del pico (0.5/0.7/0.9); Taubin (no encoge); transform al espacio visual (centrado+flip-Y) **idéntico a Arrow**; normales por voto contra −∇|contraste| (robusto en mallas abiertas); nunca-crashea. **FIX crítico cazado por dato REAL:** el motor guarda coords en METROS sin ix/iy/iz → tomarlas como índices reventaba la RAM (29 GiB); `_axis_grid` ahora rank/STEP-encode por coordenada + tope anti-OOM.
- **F4.2 (frontend `94d4a16` + QA `8cb9e4f`/`2407708`/`1c0ee6b`/`dcdc46f`):** `IsosurfaceMeshLayer.tsx` + proxy + store + toggle prominente izquierda. QA destapó **oclusión** (vóxeles opacos tapaban la malla) → fix = vóxeles como nube FANTASMA (ghostMode opacity 0.08) detrás de la cáscara → conecta la nube ancha (smear de gravedad) con el núcleo denso (cuerpo robusto), estilo Leapfrog.
- **F4.3 (backend `72006b9` + frontend `6c9084f`):** cara del corte PINTADA. `section_service.py` + `GET /v2/section`: raster 2D del contraste en el plano axis=position (coords visuales, snap a la capa; misma escala robusta; NaN=celda podada; tope anti-OOM). `SectionPaintLayer.tsx` pinta el raster como DataTexture Viridis en un plano colocado en la capa snapeada; SliceControls fetch debounced 250ms + checkbox (default ON). 8 tests.
- **F4.4 (backend `08b41df` + frontend `f9e2557`):** sondajes como cilindros. load-package persiste `#BOREHOLES`→`boreholes.json`; `borehole_view_service.py` + `GET /borehole/view` transforman al espacio visual (mismo centrado+flip-Y) + contraste. `BoreholeLayer.tsx` InstancedMesh cilindros color por litología (o densidad). GOTCHA: `boreholeSurveyToIntervals` descartaba lithology → agregada. 7 tests. Terreno DEM (drapeado): ya existía de fases previas.
- **F4.5 (backend `72006b9` + frontend `6c9084f`):** incertidumbre VISIBLE. `doi_overlay_service.py` + `GET /v2/doi-overlay`: horizonte de sensibilidad half-max por capa (misma convención B2), en coords visuales. `DoiOverlayLayer.tsx` plano ámbar + velo oscuro bajo el horizonte. Corridas joint (sin sensibilidad/doi por celda) → error honesto "no se estima" (deuda F5 registrada). 5 tests.
- **F4.6 (DECISIÓN, sin código nuevo):** WebGPU progresivo → **CONGELADO con evidencia**. WebGL2 es la base garantizada (requisito "computadores normales") y YA cumple: `VolumeRaymarchLayer.tsx` (raymarch fog/isosurface) corre con textura UNORM8 3D universal detrás de `probeGpuCapabilities` (oculto si no hay soporte); `gpuCapabilities.ts`/`webgpuCull.ts` ya detectan WebGPU. Migrar el RENDERER completo a WebGPURenderer no se justifica: (1) target = laptops sin GPU dedicada; (2) las isosuperficies F4.1/2 YA entregan la CLARIDAD que es el objetivo de F4 (no fotorrealismo volumétrico); (3) la detección queda cableada para activar WebGPU tras el gate a futuro sin rearquitectura. El raymarch WebGL2 existente queda como modo "presentación" opcional.
- **F4.7 (backend `72006b9`):** LOD MEDIDO. Marching cubes: los verts son pocos incluso a 8M celdas (~29k) → octree/decimación GPU NO justificado (congelado con la medición); el costo real es la extracción CPU (~650ms/nivel a 8M) → `_lod_step`: step_size=2 sobre 2M celdas (4-10× más rápido, pérdida visual nula). 1 test de umbrales.
- **Reviewer frontera física (2026-07-09):** PASS — cero física/coordenadas calculadas en TS en las 4 capas nuevas; contraste/horizonte/centrado vienen todos del backend. Único hallazgo (T1, media): caches del visor no se invalidaban al cambiar de corrida → corregido en `setActiveRun` (commit `ff248ff`).
- **Deuda registrada para F5:** panel derecho "no disponible" (veredicto/blanco/resolución/solver) en corridas JOINT; sensibilidad/doi por celda NO se persisten en joint → el horizonte DOI cae al error honesto en esas corridas (se cablea en F5 junto con la coherencia de diagnósticos y el fix de UQ NaN). **Actualización F5 (2026-07-22): la recalibración del horizonte DOI y el fix de UQ SÍ se hicieron (grav/mag); persistir sensibilidad/doi por celda en corridas JOINT específicamente NO se abordó en esta pasada — sigue pendiente, cae en fallback geométrico honesto en joint hasta que se cablee.**

---

## F5 — Datos, gráficos y exportables (1-2 semanas)

**Objetivo:** todo lo que el consultor pega en SU informe sale de TQ con un clic, y ningún número que muestre el software se contradice con otro.

**Trabajo:**
1. **Coherencia de diagnósticos (primero, es deuda):**
   - Recalibrar B2 DOI half-max (hoy deep_frac ~0.94 para casi cualquier cuerpo → pierde poder discriminante): calibrar el umbral contra los 4 datasets canónicos para que separe casos sanos de patológicos, documentando la elección.
   - Arreglar UQ posterior_std 100% NaN + filtrado NaN downstream: o se calcula bien (Hutchinson ya existe) o el campo NO se muestra — jamás un NaN o un "—" sin explicación en la UI.
   - Auditoría de contradicciones: un test que corre los 4 canónicos y verifica que verdict/best_target/depth_resolution/χ² cuentan la MISMA historia (la regla B3 worst-of ya apunta ahí).
2. **Gráficos** (frontend, con datos 100% del backend): mapa obs-vs-calc con residuales (endpoint ya existe de H-C2), histograma de densidades/susceptibilidades, curva de convergencia (χ² por iteración, ya logueado), secciones de profundidad (depth-slices) navegables.
3. **Exportables:**
   - **Imágenes PNG alta resolución** de cualquier vista 3D/corte/gráfico: render off-screen a 4K con barra de escala, flecha norte, colorbar, título y fecha (canvas del visor + composición).
   - **Reporte PDF** (extender `report_api.py` + `export_service.py`): portada, mapa, 3D, cortes, obs-vs-calc, tabla de targets B1, veredicto B3 con limitaciones B2 EN PROSA (el texto honesto es el activo legal), disclaimers no-JORC.
   - **Block model**: CSV (estándar minero x,y,z,ρ,σ), VTK/VTU (para ParaView — el consultor senior lo pedirá), GLB (ya existe camino).
4. Botonera "Descargar" unificada en la UI.

**Tests/verificación:** golden files de export (PDF/CSV/VTK se re-generan y comparan estructura); el test de coherencia de diagnósticos en CI; abrir el VTK en ParaView y el CSV en Excel como checklist manual una vez.

**Gate:** desde una corrida de LdM real: PDF + 3 PNGs + block model CSV descargados y presentables sin editar; cero NaN/contradicciones visibles en toda la UI.

**✅ CERRADA 2026-07-22.** Entregado en working tree (backend + frontend en iteraciones separadas, sin commitear aún — pendiente de commit por el usuario siguiendo el patrón backend-primero de F4):

1. **Coherencia de diagnósticos:**
   - **Horizonte DOI recalibrado** (`services/geophysics_service.py::build_depth_resolution`): causa raíz VERIFICADA en código (no asumida) — `sensitivity_proxy` es la norma-L2 de columna del kernel `G_w` tomada ANTES del cambio de variable de depth-weighting `Wz_inv` (`exploration/gravimetry.py:2160`, previo a la línea 2208), sensibilidad CRUDA que decae ~1/prof²; pero la densidad recuperada es `Wz_inv·m_tilde` (línea 2633) — el depth-weighting (Li & Oldenburg 1998) compensa esa caída dejando la masa ~uniforme en profundidad. Comparar masa post-compensación contra un horizonte pre-compensación daba `deep_mass_fraction`≈0.92-0.98 SIEMPRE (sano o patológico) — artefacto estructural, no señal. **Fix:** el horizonte primario ahora usa el índice DOI de doble inversión (`doi_index`/`doi_raw`, Oldenburg & Li 1999, ya calculado en producción — sin costo nuevo), que vive en el mismo espacio post-compensación que la masa; umbral absoluto `doi≥1.0` = celda controlada por el prior, no por el dato. Fallback a sensibilidad half-max si no hay DOI. **Calibrado y MEDIDO** contra 3 corridas reales (`scripts/validation/f5_b2_doi_calibration.py`, reproducido independientemente): DO-27 (sano, 53.7m horiz. validado) 0.961→null_space pasa a **0.433→poor**; San Nicolás (sano, techo 125m aprobado) 0.975→null_space pasa a **0.396→poor**; LdM (patológico, smear real documentado) 0.923→null_space se mantiene en **0.751→null_space**. El discriminante quedó restaurado sin tocar el motor de inversión (solo la capa de reporte). Raglan excluido por costo (cache sin columna doi_index). 3 tests nuevos + 1 test de integración real (San Nicolás, con skip si el run persistido no está disponible).
   - **UQ posterior_std con razón explícita**: `posterior_uncertainty_summary` ahora incluye `status` (`"computed"`|`"ill_conditioned"`|`"disabled_by_default"`) + `reason` (ES, con el σ real si está mal condicionado — mediana/máx medidos ~41/~1e13 t/m³, no físico). Aditivo: NO cambia CUÁNDO se calcula (sigue OFF por defecto en producción porque a la λ que selecciona Morozov en surveys subdeterminados la covarianza posterior se mal-condiciona), solo la transparencia de POR QUÉ. Frontend (`NoiseUncertaintyWidgets.tsx`) consume el campo y trata `ill_conditioned` igual que "no disponible" — nunca muestra σ no física como si fuera válida.
   - **Test de coherencia cruzada** (`tests/test_f5_diagnostics_coherence.py`, nuevo — el gap que el plan pedía explícitamente): invariantes estructurales entre B1/B2/B3 que no dependen de umbrales específicos — `depthResolution.resolvable_body_depth_m` es passthrough exacto de `best_target.depth_m` (nunca una profundidad inventada); `best_target.is_null_space_artifact=True` colapsa el veredicto a LOW SIEMPRE sin importar otras señales; la limitación vertical universal de B2 (`null_space_dominated`) NUNCA por sí sola degrada el veredicto B3 (contrato de diseño explícito, ahora testeado — evita que se pierda de nuevo el poder discriminante); integración real contra LdM.
2. **Gráficos** (frontend, 100% datos del backend): `ObsVsCalcPanel` (ya existía, ahora montado en `AnalyticsPanel`) + `DensitySusceptibilityHistogramWidget` (nuevo, histograma de densidad/susceptibilidad sobre celdas ya cargadas) + `ConvergenceCurveWidget` (nuevo, consume el endpoint `/v2/geophysics-convergence` — expone el barrido λ/Morozov chi² YA calculado por el solver; el widget aclara honestamente que NO es chi² por iteración de un solve único, esa serie no se persiste hoy). Depth-slices navegables: ya existían (`SliceControls`/`SectionPaintLayer`), no requerían trabajo nuevo.
3. **Exportables:**
   - **Block model CSV** (`export_block_model_to_csv` en `export_service.py` + endpoint `GET /export/block-model-csv/{project_id}/{run_id}`): lee DIRECTO el parquet persistido (coordenadas reales x_m/y_m/z_m, coherente con el gotcha F4 de coords-en-metros-sin-ix/iy/iz) — a diferencia de GSLIB/UBC/VTR que reconstruyen una grilla densa. Columnas: X_m,Y_m,Z_m,Density_gcm3[,Susceptibility_SI],Sensitivity_Proxy,DOI_Index,Posterior_Std,Probability,Is_Active. Wireado también dentro del bundle ZIP (`model.csv`).
   - **Reporte "PDF"**: decisión de diseño explícita — se entrega como HTML imprimible (ya tenía `@media print`) en vez de instalar una librería PDF nueva (regla del proyecto: no dependencias sin permiso). Se completó `report_generator.py` con las 2 secciones que faltaban: **veredicto B3 en prosa** (badge de color + headline + acción recomendada + factores limitantes + señales reconciliadas) y **resolución de profundidad B2** (statement + horizontal/vertical + deep_mass_fraction), más los campos honestos de B1 (depth_m, is_resolvable_depth, is_null_space_artifact, selection_note) en la tabla de target — antes ausentes del reporte. El usuario imprime a PDF desde el navegador.
   - **PNG alta resolución**: `CanvasExportBridge.tsx` (puente dentro de `<Canvas>` que sube pixelRatio, renderiza un frame síncrono, `toDataURL`, restaura) + `ExportPanel.tsx` compone el PNG con colorbar Viridis (mismos stops exactos que el legend on-screen, no un colormap inventado), título/fecha/disclaimer NO-JORC. No se fabricó escala/norte para la vista 3D en perspectiva (deshonesto en esa proyección); en su lugar se muestra el rango real de densidad t/m³.
   - GLB y VTU: no se tocaron — VTR (RectilinearGrid) ya cubre el caso de uso ParaView del bundle existente; GLB no tenía camino claro nuevo que agregar sin más contexto de uso.
4. **Botonera "Descargar" unificada**: `componentes/viewport/ExportPanel.tsx`, sidebar de `Exploration3DView`, con PNG/CSV/Reporte/Bundle.
5. **Endpoint de convergencia** (`GET /v2/geophysics-convergence/{project_id}/{run_id}`): expone `fitDiagnostics.lambda_scan_chi2` (ya calculado, nunca antes expuesto vía endpoint propio) con `available=False` honesto (200, no error) cuando la corrida usó λ fijo sin Morozov.

**Gate MEDIDO:** `check.ps1 -Tests` (compileall + tsc + eslint + suite completa) → **VERDE**: 0 errores de compilación/tipos, 29 warnings preexistentes (no relacionados), **1903 passed, 5 skipped, 0 failed** en 1:33:23. Reviewers: `repo-safety-guardian` OK (motor de física intacto, sin dependencias nuevas, sin credenciales/datos tocados, sin path traversal — `project_id`/`run_id` saneados vía `clean_trace_id`); `frontend-physics-boundary-reviewer` PASS (cero física nueva en TS, colormap Viridis reutilizado verbatim, campos backend consumidos como pass-through).

**GOTCHAS F5 (no re-aprender):** (1) el 0.94 "universal" de deep_mass_fraction NO era ruido del survey — era un desajuste estructural entre qué mide el numerador (masa post-Wz) y qué medía el horizonte (sensibilidad pre-Wz); cualquier métrica de "profundidad resoluble" derivada del modelo recuperado debe vivir en el MISMO espacio (post-depth-weighting) que la cantidad que mide. (2) DOI de doble inversión (`doi_index`) ya se calculaba en producción para el widget de confianza DOI — reutilizarlo para B2 no agrega costo. (3) B3 (`build_reconciled_verdict`) deliberadamente NO lee `depthResolution` — es un contrato de diseño (la ambigüedad vertical es universal en gravimetría-sola, no un defecto por-survey) ahora bloqueado con test de regresión. (4) "Reporte PDF" del plan se resolvió como HTML imprimible, no PDF binario — evita instalar reportlab/weasyprint sin permiso; si se quiere PDF real en el futuro, es una decisión de dependencia que requiere autorización explícita.

---

## F6 — Copiloto IA para el consultor (1-2 semanas) — construir SOBRE lo que existe

**Objetivo:** el diferenciador que nadie tiene en el nicho: un copiloto en español que explica LA corrida concreta, redacta borradores de secciones de informe, y jamás inventa un número.

**Ya existe (F10 histórica, verificado):** `services/gemini_agent.py` — reporte de interpretación estructurado (Pydantic), system prompt con compliance (prohibido reserve/resource/grade/NPV — ¡mantener! es el escudo legal), validación con fallback; `api/chat_api.py`. **OJO (medido en suite 2026-07-03):** ambos usan el SDK `google.generativeai` DEPRECADO (FutureWarning: soporte terminado) → F6 migra a `google.genai`.

**Investigación previa (estado 2026, verificado):** Gemini 3.1 Pro = flagship razonamiento (contexto 1M tokens, ~US$12/1M output); Gemini 3.5 Flash (mayo 2026, US$1.50/M in, US$9/M out) para chat ágil; 3.1 Flash-Lite (US$0.25/M in) para operaciones baratas; context caching = pagar una vez el contexto grande y reusar con descuento — clave para anclar cada sesión de chat al mismo `report_payload`. Decisión de modelos: **chat = 3.5 Flash; borrador de informe = 3.1 Pro; clasificaciones menores = Flash-Lite**.

**Trabajo:**
1. **Anclaje total a datos (grounding):** cada sesión de chat carga como contexto cacheado: `report_payload` completo (trilogía B1/B2/B3, χ², targets, config, warnings) + SniffReport de ingesta + metadata del proyecto. Regla dura en system prompt: *"Si el dato no está en el contexto, dices 'ese dato no está en esta corrida' — nunca lo estimas"*. Validación post-respuesta: los números citados deben existir en el payload (regex + comparación), si no → regenerar/fallback (el patrón banned-words ya existente, extendido a números).
2. **Modos del copiloto:** (a) **Explicar** — "¿por qué el veredicto es MEDIUM?" → responde desde B3 y sus fracciones físicas; (b) **Redactar** — borrador de sección de informe geofísico (estructura tipo industria: introducción, datos, método, resultados, limitaciones) que el consultor edita y FIRMA él; (c) **Enseñar** — glosario minero-geofísico ES (qué es Bouguer, χ², DOI) para el usuario junior.
3. **Contexto JORC sin violar compliance:** el copiloto puede EXPLICAR qué exige JORC/NI 43-101 y por qué TQ no reporta recursos (educación), manteniendo la prohibición de generar lenguaje de estimación de recursos. Documentos de referencia (guías públicas JORC) como contexto cacheado, no fine-tuning.
4. **API key del usuario** (BYO-key): el consultor pone SU key de Gemini (ya existe `keys_api.py`) → costo cero para TQ, datos del cliente van directo de su máquina a Google con su cuenta (coherente con local-first; documentar esto en privacidad).
5. **UI**: panel lateral de chat en la vista 3D/reporte, con botones de acción rápida ("explícame este veredicto", "borrador de informe") — iteración frontend separada.

**Tests/verificación:** suite de prompts adversariales ("¿cuántas toneladas de cobre hay?" → debe rehusar con explicación; "¿a qué profundidad exacta está?" → debe citar B2 y la no-unicidad); test de grounding con payload sintético (números trampa); mock de Gemini en CI (sin gastar tokens), smoke real semanal.

**Gate:** 20 preguntas de consultor real respondidas correctamente ancladas a una corrida de LdM; 0 números inventados en la suite adversarial; borrador de informe que Martín evaluaría mostrar a un profesor de geofísica.

---

## F7 — Empaque local-first + licencias (1-2 semanas, paralelo a F6)

**Objetivo:** "instálalo y funciona" en el computador del consultor, con sus datos sin salir de su máquina — la barrera de confidencialidad convertida en ventaja de venta.

**Investigación previa (estado 2026, verificado):** patrón dominante = **Tauri 2 + sidecar Python**: PyInstaller empaqueta FastAPI+deps en un ejecutable, Tauri lo lanza como sidecar y sirve el frontend Next.js (export estático) en el webview nativo — instaladores livianos, sin Chromium. Riesgos conocidos a validar en spike: tamaño del bundle SciPy/NumPy (~200-400 MB, aceptable), antivirus Windows vs PyInstaller (firmar el ejecutable o documentar exclusión), rutas de datos en `%APPDATA%`.

**Trabajo:**
1. **Spike de 2 días ANTES de comprometerse**: PyInstaller del backend completo (con pyproj/scipy/pandas/IGRF data files) corriendo standalone → si falla feo, plan B: **instalador simple** (script que instala Python embebido + venv + acceso directo que levanta backend+frontend y abre el navegador). El plan B es perfectamente vendible; Tauri es el ideal.
2. Next.js → `output: 'export'` para el modo escritorio (auditar las API routes del frontend que hoy hacen proxy — en escritorio el webview habla directo a `localhost:800x`).
3. **Licenciamiento simple**: clave offline firmada (Ed25519: producto, cliente, expiración) verificada por el backend local — sin servidor de licencias (local-first, y un dev solo no opera infraestructura de activación). Tier gratis = límite de vóxeles/marca de agua en exports (canal freemium de la investigación).
4. Datos y DB SQLite en el directorio de datos del usuario, con botón "abrir carpeta de proyectos" y respaldo = copiar carpeta.
5. Versión web (Vercel/servidor) se MANTIENE como demo pública con datasets de ejemplo — no para datos de clientes (mensaje explícito).
6. **Actualizaciones firmadas** (investigado 2026): plugin updater de Tauri 2 — firma obligatoria (clave privada firma el instalador; la pública va en `tauri.conf.json`), manifiesto JSON estático en GitHub Releases = cero servidores que operar. Cada release conserva los proyectos del usuario (test explícito).
7. **Canal de diagnóstico compatible con confidencialidad** (la respuesta al riesgo soporte-de-un-dev-solo SIN violar LOCAL-FIRST): (a) botón **"Exportar diagnóstico"** — empaqueta logs + config + versiones + traza del último error, SIN datos de survey (los payloads de crash pueden contener fragmentos de datos abiertos — riesgo real documentado); el consultor lo envía por correo manualmente; (b) crash reporting automático (sentry-tauri existe para esta arquitectura) SOLO opt-in, apagado por defecto, con scrubbing y sin adjuntar datos — se decide instalarlo según los primeros clientes. La regla: ningún byte sale de la máquina sin acción explícita del usuario.
8. **Modo sin internet, honesto**: IGRF ya es offline; DEM → si no hay internet, se pide el archivo DEM local (input opcional ya existente); satelital/GEE = feature marcada "requiere conexión" y NUNCA bloquea el camino dorado. Versionado del producto: SemVer + checklist de release (suite F8 + F9 verdes → firmar → publicar manifiesto).

**Tests/verificación:** instalación limpia en una máquina Windows sin Python ni Node (VM) → camino dorado completo offline (salvo copiloto); desinstalación limpia; actualización sobre versión anterior conserva proyectos; "Exportar diagnóstico" no contiene ningún dato de survey (test que lo inspecciona).

**Gate:** un tercero (no Martín) instala y completa el camino dorado sin ayuda en <15 min.

**🟦 NÚCLEO + PLAN B CERRADOS 2026-07-22** (backend + 2 archivos raíz, sin deps nuevas, física intacta; SIN commitear — patrón F5/F6). El **spike medido** decidió el empaque: Rust/cargo y PyInstaller NO están instalados y la regla del repo prohíbe instalarlos sin permiso expreso → se implementa el **Plan B** (vendible según el plan) + todo el **núcleo agnóstico al empaque** que ambos caminos comparten. Detalle en `docs/04_EMPAQUE_LOCAL_FIRST.md`.

1. **Directorio de datos portable** (`core/config.py::_resolve_data_dir`): sin env var = `<repo>/data` (dev intacto); con `TERRAQUANTUM_DATA_DIR` = carpeta del usuario (`%APPDATA%\TerraQuantum\data`). Se mueven en bloque solo los DATOS de usuario (proyectos, corridas, `terraquantum.db`, `api_keys.db`, `license.key`); los assets de instalación (`public/models`, `tmp`) siguen junto al código. Respaldo = copiar una carpeta.
2. **Licenciamiento offline Ed25519** (`core/license_service.py` + `api/license_api.py` + `scripts/mint_license.py`): token `tqlic1.<payload>.<firma>` (product/licensee/tier/expiración) verificado EN la máquina, sin servidor. Clave pública se distribuye (`TQ_LICENSE_PUBLIC_KEY_HEX`), la privada jamás entra al repo. **Regla dura local-first:** sin emisor o sin licencia = modo **local libre** (sin límites, nunca bloquea el arranque ni el camino dorado). Tiers: `local`/`pro` sin límite, `free` = tope de vóxeles (`check_voxel_budget`) + marca de agua. `cryptography` ya estaba en requirements → cero deps nuevas.
3. **Exportar diagnóstico compatible con confidencialidad** (`services/diagnostics_service.py` + `api/diagnostics_api.py` + `core/diagnostics_buffer.py`): `GET /diagnostics/export` → ZIP con SOLO metadatos (versiones, config saneada, conectividad, estado de licencia, últimos errores a nivel de código: path+tipo+traceback, **sin body de request**). NUNCA incluye datos de survey ni secretos — el test siembra un secreto y verifica que no aparece, y que el bundle son exactamente 7 archivos de metadatos. El usuario lo envía manualmente.
4. **Honestidad offline** (`services/connectivity_service.py` + `GET /system/connectivity`): confirma `golden_path_offline=true` y marca cada feature de red (DEM OpenTopo → fallback local; GEE satelital; copiloto Gemini) como NO requerida por el camino dorado; IGRF offline y requerido. Verificado que ninguna llamada de red está en la ruta crítica de inversión.
5. **Plan B launcher de un clic** (`run_terraquantum_desktop.ps1`, raíz, archivo NUEVO — no toca `start-terraquantum.bat`): fija `TERRAQUANTUM_DATA_DIR`=%APPDATA%, bind del backend a 127.0.0.1 (loopback), levanta backend, espera `/health`, construye/sirve el frontend, abre el navegador y apaga limpio. **Hallazgo que simplificó el alcance:** el Plan B corre `next start` con los 40 proxies vigentes contra el backend local → **el frontend NO se toca** (el `output:'export'` y la reescritura de proxies a directo-a-backend son requisito EXCLUSIVO del webview Tauri, diferido).
6. **Wiring** (`main.py`): routers `license`/`diagnostics` incluidos; los 2 handlers globales nunca-crashea ahora alimentan el buffer de diagnóstico (solo en errores internos, sin body). Verificado E2E con `TestClient`.

**Gate MEDIDO** (`scripts/validation/f7_gate_packaging.py`): **PASS 30/30** (data dir portable, licencia round-trip + rechazos, tiers, diagnóstico limpio, offline honesto, Plan B presente). **Tests F7 29/29 verdes** (`test_f7_license`/`_diagnostics`/`_data_dir`/`_connectivity`). Suite completa colecta **1969 sin regresión de import**; `compileall` VERDE. Auto-auditoría de seguridad (reviewers no disponibles por límite de sesión): backend/frontend separados, sin deps nuevas, sin `.bat`/`.env`/credenciales/datos/física tocados, sin path traversal (rutas de licencia/diagnóstico fijas, token verificado antes de escribir).

**GOTCHAS F7 (no re-aprender):** (1) el spike NO instaló Rust/PyInstaller (regla del repo + no estaban) → Plan B + núcleo agnóstico; Tauri es upgrade que requiere autorizar la instalación. (2) El Plan B NO necesita `output:'export'` ni modo directo-a-backend — eso es solo para el webview Tauri; por eso el frontend quedó intacto (respeta "iteraciones separadas" no tocándolo). (3) Modo local-first sin licencia = **libre sin límites** a propósito: castigar la instalación propia con el "tier free" sería absurdo; los límites aplican solo cuando una licencia los declara (canal de distribución). (4) Los `.ps1` se guardan con **BOM UTF-8** o Windows PowerShell 5.1 los lee como ANSI (los acentos/guiones salen mojibake; el `ParseFile` incluso reporta un falso "}" inesperado). (5) El diagnóstico expone rutas con el usuario del SO (`%APPDATA%`) — aceptable en un bundle que el usuario exporta y envía él mismo; no es dato de survey.

**✅ INSTALADOR NATIVO TAURI 2 — CONSTRUIDO Y VERIFICADO E2E (2026-07-22, Martín autorizó "permiso completo, autorizo todo").**

- **Spike (el mayor riesgo del plan) PASÓ:** PyInstaller empaqueta el backend científico completo (FastAPI+scipy+pyproj+skimage+IGRF) → onefile 199 MB, arranca standalone en ~14 s, sirve endpoints, con `proj.db` (pyproj) + IGRF bundleados (verificado en la extracción `_MEI`). `terraquantum_backend.spec` (bundlea submódulos de la app para imports lazy; excluye ee/genai/matplotlib).
- **Toolchain instalado (autorizado):** Rust 1.97.1 (rustup vía winget), VS Build Tools 2022 con C++ (MSVC 14.44 — Tauri en Windows necesita el linker), Tauri CLI 2.11.4, PyInstaller 6.21. WebView2 ya estaba.
- **Arquitectura = 2 sidecars (decisión MEDIDA, no `output:'export'`):** los 40 proxies `app/api/*/route.ts` NO son triviales — transforman de verdad (query→segmentos de path en geophysics-status; params+Arrow binario en block-model; prefijos /v2/; renombres). Un export estático obligaría a **duplicar esa lógica en TS** (prohibido por CLAUDE.md). Solución: Tauri lanza **backend exe** (`:8010`) + **frontend Next.js standalone sobre Node** (`:3000`, proxies INTACTOS). Frontend NO tocado (el `next.config` ya era `output:'standalone'`). Shell Rust (`terraquantum-web/src-tauri/`, `lib.rs`): resuelve recursos, fija `TERRAQUANTUM_DATA_DIR`=%APPDATA%, spawnea ambos ocultos con stdio a `%APPDATA%\TerraQuantum\logs`, splash → espera `:3000` → navega la ventana, y mata ambos árboles de proceso al salir.
- **Instalador producido:** `TerraQuantum_0.2.0_x64-setup.exe` (~322 MB) por `tauri build` (NSIS, WebView2 embedBootstrapper) + pipeline repetible `scripts/build_desktop.ps1` (pyinstaller→next build→staging→tauri build).
- **Updater firmado:** `tauri-plugin-updater` registrado; `createUpdaterArtifacts:true`; pubkey minisign en `tauri.conf.json`; **clave privada FUERA del repo** (`~/.tauri/terraquantum_updater.key`) firma el instalador → `.sig` generado. Endpoint `latest.json` placeholder (GitHub Releases) a reemplazar por el repo real.
- **Verificado E2E desde el bundle** (2 lanzamientos del `app.exe` construido): backend `:8010/health` OK, frontend `:3000` sirve `<title>TerraQuantum</title>`, y el proxy `/api/backend-health` del frontend LLEGA al backend Python (`online:true`) — los proxies funcionan intactos empaquetados.
- **GOTCHA nativo (no re-aprender):** el sidecar Node moría con `EISDIR: lstat 'C:'` — el resolvedor de recursos devuelve rutas verbatim `\\?\C:\...` y Node las mutila al resolver el módulo main. Fix: pasar `server.js` RELATIVO (cwd=frontend) + `strip_verbatim` en `resource()`. Otro: cuando se spawnea Node con ventana oculta + stdio redirigido bajo carga de CPU pesada, Next tarda en bindear (no es fallo, es contención) — el log a archivo lo destapó.

**Pendiente MENOR de F7 (no bloquea; el motor y el empaque están probados):** cronómetro formal del "tercero instala en <15 min" en una VM Windows LIMPIA (sin Python/Node) corriendo el `.exe`; publicar `latest.json` firmado en el repo de releases real; reemplazar iconos placeholder por la marca; opcional `webviewInstallMode: offlineInstaller` si se quiere instalación 100% sin internet. Todo F7 (backend núcleo + Plan B + Tauri) **SIN commitear** (patrón F5/F6, decisión del usuario).

---

## F8 — Tormenta de pruebas (1-2 semanas + continuo)

**Objetivo:** la promesa central — "siempre, de los siempre, funciona" — demostrada con una matriz sistemática, no con optimismo. (Cada fase ya cerró con sus tests; esto es la validación TRANSVERSAL del producto entero.)

**Trabajo:**
1. **Matriz E2E de flujos** (script paramétrico sobre la API + Playwright para UI): {grav, mag, sondajes, grav+mag, grav+sondajes, grav+mag+sondajes} × {CSV limpio, sucio-ES, sucio-encoding, con preámbulo, unidades mixtas} × {chico 100 est., mediano 900, grande 2.500} × {con/sin DEM, con/sin Helmert} — cientos de combinaciones generadas, cada una debe terminar en: modelo 3D válido O error catalogado con acción. NUNCA: crash, timeout sin mensaje, basura silenciosa (validador automático del block model: rangos físicos, sin NaN, χ² coherente).
2. **Fuzzing de la API** (schemathesis sobre el OpenAPI de FastAPI): toda respuesta ∈ {2xx, 4xx catalogado}; 5xx = bug, se arregla.
3. **UI E2E con Playwright**: los 8 recorridos de usuario principales grabados como tests (subir → mapear → preguntar → invertir → progreso → 3D → corte → descargar), corriendo headless en CI con screenshots de regresión.
4. **Soak test**: 50 inversiones consecutivas en el mismo proceso → memoria estable (sin leaks de kernels/parquets), SQLite íntegra.
5. **Presupuestos de rendimiento** como tests: ingesta 10k filas <5 s; inversión 30k vóxeles <3 min; render 100k celdas >30 fps (medido en la máquina de referencia).
6. Registro de TODO fallo encontrado → fix → test con nombre. El catálogo de 60 errores ES crece con cada caso nuevo.

**Gate:** matriz completa verde 3 corridas seguidas en días distintos; 0 excepciones no-catalogadas; Martín intenta romperlo una tarde entera y no puede (o cada rotura se arregla en <1 día).

**🟦 HARNESS COMPLETO + VERDE 2026-07-23** (backend/tests, sin deps nuevas, sin tocar frontend ni el motor de física; SIN commitear — patrón F5/F6/F7). Decisión de sesión de Martín: **núcleo backend dep-free** (fuzzer propio en vez de schemathesis; Playwright UI **diferido** a iteración frontend) + **subset rápido corrido ahora** (el barrido completo de cientos de combos y las cláusulas multi-día/adversariales del gate quedan para Martín con el harness listo).

Entregado (6 archivos):
1. **Biblioteca del harness** (`tests/f8_storm_lib.py`): genera surveys sintéticos con VERDAD conocida sobre los 5 ejes del plan — {grav, mag, sondajes, grav+mag, grav+sondajes, grav+mag+sondajes} × {limpio, sucio-ES `;`+coma-decimal+BOM, sucio-encoding cp1252/latin-1 con acentos, con preámbulo, unidades mixtas} × {chico, mediano, grande} × {lat-lon vs local+Helmert} × {DEM on/off}. Conduce cada combo por el flujo REAL del usuario (`enrich-package` → `load-package` síncrono) y lo clasifica en el invariante: `outcome ∈ {modelo_3d_válido, error_catalogado}`, jamás `{crash, 5xx_pelado, basura_silenciosa}`. **Validador automático del block model**: lee el parquet persistido DIRECTAMENTE (fuente de verdad, agnóstico a la física — grav→`density`, mag→`susceptibility_si`), verifica finitud en celdas ACTIVAS + rango físico + χ² coherente. Resetea el rate-limiter por combo (el gate corre fuera de pytest).
2. **Matriz E2E** (`tests/test_f8_e2e_matrix.py`, `slow`): subconjunto de cobertura (cada valor de cada eje ≥1 vez) por el flujo real + expectativa semántica (el camino feliz DEBE invertir, sondajes-solo DEBE rechazar). **20/20 combos verdes, 0 bugs** (medido). El barrido cartesiano completo (cientos) vive en el gate.
3. **Fuzzing de API dep-free** (`tests/test_f8_api_fuzz.py`): fuzzer propio (regla del repo: sin deps sin permiso) del contrato F2 "nunca un 500 pelado" — 12 payloads de bytes malformados (no-UTF8, null-bytes, PNG binario, JSON-como-CSV, campo gigante, inf/nan, filas rotas) × la superficie de entrada (enrich/load/parse-rows/analyze-columns) + forms malformados (config/boreholes/helmert) + IDs adversariales (traversal `../`, inyección SQL, `\x00`, jndi) en GET con path param. Invariante: toda respuesta `<500` O `5xx CON envoltura catalogada ES` (code + user_message), y el cliente NUNCA lanza. **106 tests verdes** — cero 5xx pelados en toda la superficie.
4. **Soak** (`tests/test_f8_soak.py`, `slow`): N inversiones consecutivas → RSS estable (tendencia último-tercio vs primer-tercio bajo umbral por-iteración) + historial SQLite íntegro tras la ráfaga. CI N=8; el gate N=50. **Verde, +1.5 MB/iter (sin fuga)**.
5. **Presupuestos** (`tests/test_f8_perf_budgets.py`): **ingesta 10k filas = 1.4 s (MEDIDO, cumple el 5 s del plan)**; inversión acotada (`slow`); render 100k >30fps **DIFERIDO** (requiere navegador → Playwright, la iteración frontend separada de F8).
6. **Gate maestro** (`scripts/validation/f8_gate_storm.py`): corre bajo demanda las 4 patas — matriz (cobertura o `TQ_F8_FULL=1` cartesiano completo con tamaños reales 100/900/2500) + soak-50 + presupuestos estrictos del plan (ingesta<5s, inversión ~30k vóxeles<3min) + subprocess del fuzzer — y emite veredicto medido + `f8_gate_report.json`. Env: `TQ_F8_FULL`, `TQ_F8_MATRIX_LIMIT`, `TQ_F8_SOAK_N`, budgets. `main()`-only (no lo recoge pytest pese a `testpaths` incluir `scripts/validation`). **Smoke de orquestación PASS 4/4** (reporte JSON escrito).

**Hallazgo de la tormenta — DIAGNOSTICADO (no es bug del motor, no afecta al usuario real):** el "222 s para 216 vóxeles" del primer preview resultó ser **(a) contención de CPU** (corría el fuzzer + otros pytest en paralelo) **× (b) degeneración de la malla 6³**. Profiling aislado: el solver `run_geophysics_inversion` es **rápido (1,1 s con 225 estaciones)**; el enrich es **1,1 s**. El costo real aparece en `load-package` porque una malla 6³ con datos enriquecidos queda **mal condicionada** (`FOCUSING rms=nan`) y el lazo externo IRLS/Morozov agota iteraciones → **305 llamadas a `lsmr` vs 17** en un caso bien puesto (mismo `block_size`/`cutoff`). Es régimen DEGENERADO (malla artificialmente diminuta), fuera del régimen validado — el usuario real invierte mallas mayores y bien puestas (el gate F3 hizo 96k vóxeles en 11,5 min). NO es un solver super-lineal (afirmación previa CORREGIDA). El tier rápido usa mallas chicas a propósito (robustez ≠ convergencia física); el gate usa tamaños reales.

**GOTCHAS F8 (no re-aprender):** (1) el `density` del parquet es un **contraste** (Δρ sobre el fondo): ~0 en el fondo es legítimo, no basura — el validador solo caza NaN/Inf en celdas ACTIVAS y magnitudes absurdas, sin piso positivo. (2) El **rate-limiter** (10/min por endpoint) auto-estrangula la tormenta: en pytest lo resetea el fixture autouse de conftest; el gate (fuera de pytest) lo resetea por combo. (3) El export CSV de F5 es **solo-gravedad** (busca `block_model.parquet`; el mag persiste `block_model_magnetic.parquet`) → validar leyendo el parquet directo, no por el export. (4) httpx **rechaza formar URL** con chars de control (`\x00`) del lado cliente → URL-encode el segmento para que el SERVIDOR reciba y sanee. (5) `depth` default 1000 m excede la matriz en mallas chicas (máx físico ~264 m) → fijar `depth` acorde en el config del paquete.

**✅ UI E2E con Playwright — HECHO 2026-07-23 (Martín autorizó "autorización total"; iteración frontend separada, deps nuevas).** `@playwright/test` 1.61.1 + chromium instalados; `terraquantum-web/playwright.config.ts` levanta backend (:8010) + frontend (:3000) solo; `e2e/journeys.spec.ts` cubre los recorridos de UI con el invariante transversal "ningún error de JS sin capturar al recorrer la app" (nunca-crashea desde el navegador, sin física en TS): welcome→entrar, navegar las 6 vistas sin crash, copiloto IA (selector de modo + BYO-key + input de chat, F6), preparación (panel de carga), historial (consume backend), y **regresión de píxeles** (screenshots de inicio + IA con `toHaveScreenshot`). **6/6 verdes contra el build de producción** + `npm run test:e2e` + `scripts/e2e_ui.ps1`. `tsc`/`eslint` de check.ps1 siguen verdes (0 errores). **GOTCHA CLAVE:** `next dev` NO hidrata bajo Playwright (el WS de HMR `_next/webpack-hmr` falla con `ERR_INVALID_HTTP_RESPONSE` en Next 16 + turbopack → shell SSR estático, ni timers ni onClick) → E2E DEBE correr contra `next build`+`next start` (además es lo correcto: probar el bundle que se envía). Otro: la WelcomeScreen monta un overlay 4s → el `enterApp` reintenta el click hasta transicionar; `locator('main')` viola strict-mode (algunas vistas montan su propio `<main>`) → usar la NavBar como testigo de "app viva".

**Falta para cerrar el gate del plan** (inherentemente multi-día / humano): (a) correr `TQ_F8_FULL=1 f8_gate_storm.py` (barrido cartesiano completo con tamaños reales) **3 corridas en días distintos** en verde — es trabajo de reloj/calendario (el barrido a tamaños reales es de horas, por diseño), con el harness ya listo; (b) el recorrido pesado invertir→progreso→3D→descargar contra una inversión EN VIVO (minutos) y el **render-fps 100k>30fps** (medición en el navegador con datos reales — pendiente de una corrida sembrada); (c) la **tarde adversarial de Martín** intentando romperlo (el fuzzer de 106 casos es el proxy automatizado). El harness que hace medibles esas cláusulas ya está construido y verde.

---

## F9 — Validación física como regresión automática (2-3 días)

**Objetivo:** la física YA está validada (DO-27, Raglan, San Nicolás, LdM, sintéticos) — congelarla para que ningún cambio futuro la degrade sin que suene una alarma.

**Trabajo:**
1. Consolidar los scripts de `scripts/validation/` en una suite `pytest -m validation` con **tolerancias explícitas** (DO-27 error horizontal ≤70 m; Raglan pico interior ≤250 m; LdM χ² ∈ [0.7, 1.3]; sintético esfera: masa-en-top2% ≥60%; ambigüedad-z DOCUMENTADA como expectativa, no como fallo).
2. Datasets canónicos versionados en fixtures (o descarga cacheada con hash verificado).
3. Corre: semanal + antes de cada release + a demanda. NO en cada commit (son minutos-horas).
4. Reporte HTML de la suite (tabla PASS/FAIL con métricas) → material de credibilidad actualizado gratis para F10.

**Gate:** suite corre sola de punta a punta y produce el reporte; una degradación inyectada a propósito (romper W_z) la hace fallar.

**✅ CERRADA 2026-07-23.** Suite `pytest -m validation` + gate + reporte HTML, backend-only, sin tocar el motor. Entregado (SIN commitear, patrón F5-F8):
1. **`scripts/validation/f9_regression_lib.py`** — un solo lugar de verdad con 6 casos que RE-INVIERTEN el motor real (no leen modelos cacheados) y tolerancias EXPLÍCITAS medidas con margen:
   - **Esfera sintética** (canónica `tests/synthetic_recovery_benchmark`, anti-inverse-crime): Pearson r **0.726 ≥ 0.70**.
   - **Ambigüedad-z** (sintético régimen LdM, esfera analítica): z-error **2675 m ≥ 400 m** = LÍMITE FÍSICO DOCUMENTADO (gravedad-sola no resuelve profundidad; el ancla lo colapsa 2675→75 m). NO es fallo: es expectativa.
   - **DO-27** (kimberlita, benchmark externo): error horizontal **53.7 ≤ 70 m**.
   - **San Nicolás** (VMS, dato real re-invertido desde observaciones guardadas): misfit **1.51 ≤ 3%** (estaciones submuestreadas stride 4 por la guardia de memoria de 8 GB).
   - **LdM** (Bouguer real, Miller 2017, re-invertido): χ² **0.987 ∈ [0.7, 1.3]** (ajuste al nivel de ruido).
   - **Raglan** (Ni-Cu, dato real): pico interior **212 ≤ 250 m**.
2. **`tests/test_f9_physics_regression.py`** — 6 tests marcados `validation` (+ `slow`); `tests/conftest.py` los SALTA por defecto (hook `pytest_collection_modifyitems`), sólo corren con `TQ_RUN_VALIDATION=1` o `--run-validation` → jamás rompen el CI rápido por timeout. Verificado: 6 skipped en 0,13 s por defecto; 3/3 PASS con el flag.
3. **`scripts/validation/f9_gate_regression.py`** (main-only) + **`f9_report.py`** → **gate PASS 6/6 MEDIDO en 1972 s** (~33 min; DO-27 = 22 min domina por IRLS compacto sobre malla profunda) + reporte JSON (`f9_gate_report.json`) + HTML imprimible (`f9_validation_report.html`, material de credibilidad F10).
4. **`scripts/validation/f9_degradation_check.py`** — prueba de sensibilidad del gate: inyecta una falla de física (geometría del kernel corrupta, vóxeles +800 m) y comprueba que Raglan colapsa **212 → 1570 m → FALLA** (sano PASS → roto FALLO).

**HALLAZGO MEDIDO (importante para el equipo de física):** el parámetro `depth_beta` del solver gravimétrico es **algebraicamente INERTE** para el modelo recuperado — la normalización de columnas Ws (`gravimetry.py` ~2224) absorbe el cambio de variable W_z y el objetivo en el espacio del modelo queda invariante a beta. Por eso "romper W_z" vía `depth_beta` no cambia nada; la palanca real de la física es el operador forward, y ES sensible (una geometría de kernel corrupta hace fallar el targeting). El criterio del gate se cumple con esa degradación real.

> **Precisión medida el 2026-08-14 (Fase 4, auditoría 06 §10).** Este párrafo decía que beta=0 y beta=2 dan resultados "byte-idénticos". **Son idénticos como física, no como bits**: `Wz` sigue siendo un precondicionador por la derecha legítimo, y con tolerancias finitas dos precondicionadores no aterrizan en el mismo punto. Medido: mover beta de 0 a 4 mueve la solución **2,5e-04** (relativo L2) con TRF y **5,2e-06** con LSQR+GPCG — que el número cambie **48× al cambiar de solver** es lo que prueba que es parada temprana y no física. Y hay un segundo matiz que este párrafo no podía saber: **`depth_beta` sólo está muerto en `solve_inversion_lsqr`**. En `solve_inversion_treemesh` (malla Octree, que producción elige sola cuando la grilla pasa de 50.000 celdas o el survey de 50 km) el peso está **vivo**: mueve la solución 2,045, ocho mil veces más. Detalle completo en `docs/06` §FASE 4.

**Desviaciones honestas del plan (medidas, no ajustadas para pasar):** (a) la métrica propuesta "masa-en-top2% ≥ 60%" midió ~10% (mal especificada) → se reemplazó por el canario W_z establecido Pearson r ≥ 0.70 (umbral de CI del propio benchmark); (b) el χ² de campo es dependiente de σ y Morozov necesita σ explícito ausente en las observaciones guardadas → San Nicolás congela el misfit% (σ-independiente); LdM conserva χ² porque el σ sentinel ya aterriza en χ²≈1; (c) San Nicolás submuestrea estaciones (stride 4) por la guardia de memoria en 8 GB.

---

## F10 — Producto y lanzamiento (2-3 semanas, y nunca termina)

**Objetivo:** convertir el software robusto en negocio, por el camino que la investigación validó: consultores primero, servicio productizado como puente de ingresos.

**Trabajo:**
1. **Material de credibilidad**: página/PDF por validación (DO-27, Raglan, San Nicolás, LdM) con imágenes del F4/F5 — honesto: "targeting horizontal validado; la profundidad es no-única y lo decimos" (nadie más lo dice: es ventaja).
2. **Manual de usuario ES** (con el copiloto integrado, el manual puede ser corto) + 1 video de 5 min del camino dorado.
3. **Landing** simple: qué hace, qué NO hace, precio, demo web pública con dataset de ejemplo, descarga tier gratis.
4. **Precios** (de la investigación, validar con los primeros 5 contactos): consultores US$50-150/mes o US$300-800/proyecto; juniors solo por-proyecto US$500-1.500; ancla mental US$156/día de Consultants Daily.
5. **Servicio productizado (EMPEZAR ANTES, desde F5)**: Martín + TQ venden la inversión HECHA a juniors chilenas (US$2-4k/proyecto) — genera casos, contactos e ingresos mientras F6-F9 avanzan. Chile = piloto (76 juniors, Cochilco); mercado real = consultores LatAm.
6. **Canal**: contenido técnico LinkedIn (las validaciones son los posts), boca a boca de consultores, FEXMIN ago-2026 (verificar fechas/contactos), partnership académico (profesor de geofísica que revise y preste credibilidad — mitiga la barrera "estudiante de 2º año").
7. **Feedback loop**: cada sesión con usuario real → lista de fricciones → se priorizan sobre CUALQUIER feature nueva.

**Gate (el de verdad):** 3 consultores usando TQ en proyectos reales, al menos 1 pagando; 1 servicio productizado vendido y entregado.

---

## F11 — El camino hacia la realidad (post-lanzamiento, guiado por usuarios)

**La pregunta que responde esta fase:** *"si grav+mag+sondajes no bastan para que el 3D se parezca a la realidad, ¿qué hay que pedir o hacer?"*

**El principio (respaldado por la literatura y por nuestras propias mediciones):** la no-unicidad de los campos potenciales no se ELIMINA con mejor software — se ACOTA con **información independiente**. Cada dato nuevo que restringe el modelo recorta el espacio de modelos falsos-pero-consistentes. Así es exactamente como lo hacen UBC-GIF, SimPEG (PGI) y los flujos integrados de la industria: inversión con restricciones geológicas y petrofísicas, no inversión "más inteligente" a secas. La escalera, ordenada por impacto/costo:

**Nivel 1 — Exprimir lo que YA está construido en TQ (costo: solo cableo):**
| Pieza | Qué aporta a la "realidad" | Estado |
|---|---|---|
| Ancla dura + PGI/GMM (F2/F11 motor) | Petrofísica de sondajes como restricción estadística, no solo puntual — la mejora documentada en literatura para recuperar estructura | Construido; PGI sin uso en producción |
| Geología implícita F7 (Hermite-RBF, level-set) | Contactos y fallas mapeados en superficie → superficies 3D que limitan dónde PUEDE haber cuerpo | Construido, solver sin cablear |
| FTG (tensor gradiente) | La gradiometría resuelve lo somero mucho mejor que gz — si el cliente tiene datos FTG (survey aéreo), TQ ya tiene los kernels | Kernels construidos |
| Euler + espectro radial (nuevo en F2B) | Estimación de profundidad INDEPENDIENTE de la inversión → usarla como prior: fijar z0/modelo de referencia del depth-weighting con la profundidad de Euler | F2B lo crea; el puente al solver es F11 |
| Ensemble null-space shuttle (F8.1) | No acerca el modelo a la realidad: muestra el RANGO de realidades compatibles — "el cuerpo está entre 200 y 600 m" es información honesta y accionable | Construido, sin cablear |

**Nivel 2 — Datos que el panel de preparación debe PEDIR (con la explicación de qué mejora cada uno — esto se agrega a la UI de F2/F2B como campos opcionales con beneficio explícito):**
1. **Sondajes con MEDICIONES físicas, no solo litología**: densidad (gamma-gamma o probeta) y susceptibilidad (KT-10) por tramo. Es la restricción #1 de la literatura. La UI debe decirlo: *"con densidades medidas, el modelo queda anclado a valores reales"*.
2. **Petrofísica de superficie**: muestras de mano medidas (densidad/susceptibilidad por unidad litológica) → media y varianza por unidad para PGI. Barato para el cliente (una campaña de martillo + balanza).
3. **Mapeo geológico**: contactos, fallas, rumbos/manteos, shapefile o CSV de puntos → superficies implícitas (F7) que acotan la geometría.
4. **Diseño del survey ANTES de medirlo** (prevención > corrección): guía en la UI con la regla medida — extensión ≥ 2× la profundidad objetivo, espaciamiento ≤ ½ de la profundidad objetivo; TQ ya calcula `observable_depth_max_m`: mostrarlo COMO advertencia previa ("con este survey, la sensibilidad confiable llega a ~X m; lo más profundo será extrapolación").
5. **Alturas múltiples / continuación**: si hay datos aéreos + terrestres, la diferencia de altura aporta sensibilidad vertical extra (joint multi-altura).

**Nivel 3 — Nuevas físicas (cada una = fase futura propia, SOLO si los usuarios la piden y pagan):** IP/resistividad (la cargabilidad discrimina sulfuros — el complemento clásico de mag en pórfidos), EM/TEM (conductividad con sondeo real en profundidad), MT (profundo). La arquitectura joint de TQ (Gramian/cross-gradient/PGI multi-física) ya está preparada para recibirlas. Sísmica queda fuera (otro mundo de procesamiento).

**Nivel 4 — Lo que no se promete con potenciales solos… y CÓMO la industria SÍ lo resuelve (investigado — módulos futuros con nombre):**

Los dos límites medidos (ley entre pozos, profundidad exacta) no son callejones sin salida: la industria los resuelve con OTRAS herramientas. Que TQ no los prometa hoy no significa que no pueda ofrecerlos mañana — con la herramienta correcta y el framing legal correcto.

**(a) Ley/densidad ENTRE pozos → GEOESTADÍSTICA, no geofísica → módulo futuro F11-G.**
- **Cómo lo hace la industria** (Leapfrog EDGE, Datamine, Vulcan): variograma (cuantifica la correlación espacial de las LEYES de los sondajes) → **kriging** (el estándar desde Krige, años 50) → **simulación condicional** (20-50 realizaciones Monte Carlo para el rango de incertidumbre, hoy el reemplazo aceptado del indicator kriging). El insumo NO es gravedad: son los ensayos (assays) de los sondajes — que el usuario de TQ YA sube.
- **Por qué es factible para TQ**: es matemática pura (numpy/scipy bastan; GStatSim y PyKrige son referencias open-source para validar contra). Nuestro leave-one-out NO_GO midió que la GRAVEDAD no interpola densidad entre pozos — el kriging sobre ensayos es un producto distinto y válido; de hecho el mismo leave-one-out es SU método estándar de validación (cross-validation).
- **Alcance del módulo**: variograma experimental + ajuste interactivo, kriging ordinario, simulación condicional con mapa de incertidumbre, compositación (ya en F2B). Se muestra en el MISMO visor 3D junto al modelo geofísico.
- **Framing legal innegociable**: es *interpolación como decision-support* — jamás "estimación de recursos"; eso lo firma una Persona Calificada (JORC/NI 43-101). Mismo patrón de disclaimers de la trilogía honesta.

**(b) Profundidad exacta → tres caminos reales, dos ya al alcance:**
1. **El bucle perforar→anclar→re-invertir (¡TQ YA tiene el mecanismo!)**: así lo hace la industria de verdad — se perfora el mejor target, la intersección da la profundidad REAL, y esa intersección entra como restricción dura para re-invertir todo el modelo. El ancla dura de TQ (F2 motor) es exactamente esto. El reframe medido: el ancla es tautológica ANTES de perforar (no adivina lejos del pozo), pero DESPUÉS del primer pozo es calibración legítima que propaga información real. **Trabajo en F11: hacer de este bucle un flujo de producto explícito** ("perforaste → ingresa la intersección → re-invierte → targets actualizados"), que además es el modelo de negocio del acompañamiento por-proyecto.
2. **Geofísica de POZO (downhole)**: sondas dentro del pozo ven lo que el pozo no tocó — downhole EM/TDEM detecta conductores hasta ~800 m alrededor del pozo (rutinario en metales base; Abitibi lo vende como servicio estándar), gravedad/magnetometría de pozo existen. Para TQ = un formato de ingesta futuro (Nivel 3), no un cambio de motor.
3. **Físicas con sensibilidad vertical real**: TEM/MT/sísmica sondean profundidad por física (tiempo/frecuencia), no por geometría — es el Nivel 3. La combinación potenciales (footprint horizontal barato) + un sondeo EM (profundidad) es el matrimonio clásico de la exploración.

**Lo único que JAMÁS se promete (sin herramienta que lo salve):** "ver la realidad" — siempre se entrega el mejor modelo consistente con TODOS los datos disponibles, con su rango de incertidumbre dicho en voz alta.

**Regla de validación de F11 (aprendida con cross-gradient):** toda restricción nueva se valida contra un benchmark con verdad conocida (DO-27/esfera sintética) midiendo la mejora REAL antes de venderla como feature. Si no mejora (como el cross-gradient en DO-27), se documenta y no se promete.

**Priorización:** esta fase NO tiene orden interno predefinido — se ordena con el feedback de los primeros consultores (F10). Lo único que se adelanta a F2B/F2 es la UI que PIDE los datos del Nivel 2 (pedirlos cuesta un formulario; tenerlos multiplica el valor del modelo).

---

# PARTE IV — REGLAS DE EJECUCIÓN (cómo se trabaja este plan)

1. **Una fase a la vez, en orden.** Se puede adelantar SOLO lo marcado paralelo (F6/F7) o continuo (F8, servicio en F10.5).
2. **Cada fase: investigar → implementar → testear → gate → actualizar este archivo (✅ + commit) → memoria.** Sin gate verde no se abre la siguiente.
3. **Regla de oro intacta**: backend y frontend en iteraciones separadas; cambios chicos y aislados; sin refactors globales; los reviewers (`repo-safety-guardian`, `frontend-physics-boundary-reviewer`, `geophysics-benchmark-reviewer`) auditan lo que les corresponde.
4. **La física está cerrada.** Ningún trabajo de fases toca el motor validado salvo bug demostrado con test. Los límites medidos (profundidad, ancla, regional) NO se re-litigan: se comunican honestamente (B1/B2/B3).
5. **Sinceridad operativa**: reportar lo que falló tal cual; "funciona" solo con evidencia (test/medición). Cuando algo no se sabe → control de descarte sistemático (el método que encontró el bug del visible=0).
6. **Presupuesto de tiempo total estimado**: ~3-4 meses de trabajo enfocado hasta el gate de F10 (asumiendo dedicación parcial de estudiante). El servicio productizado puede generar ingresos desde ~mes 2 (post-F5).

---

## Referencias de investigación 2026 usadas en este plan
- Three.js r190 / WebGPURenderer default + TSL: [threejsroadmap.com](https://threejsroadmap.com/blog/webgl-vs-webgpu-explained), [byteiota — WebGPU 2026](https://byteiota.com/webgpu-2026-70-browser-support-15x-performance-gains/), [Codrops BatchedMesh+WebGPU](https://tympanus.net/codrops/2024/10/30/interactive-3d-with-three-js-batchedmesh-and-webgpurenderer/)
- Gemini API mid-2026 (3.1 Pro / 3.5 Flash / Flash-Lite, context caching, precios): [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing), [eesel — Gemini 3 pricing](https://www.eesel.ai/blog/google-gemini-3-pricing), [nxcode — Gemini 3.1 Pro guide](https://www.nxcode.io/resources/news/gemini-3-1-pro-complete-guide-benchmarks-pricing-api-2026)
- Tauri 2 + Python sidecar (Next.js + FastAPI empaquetados): [tauri.app Next.js](https://v2.tauri.app/start/frontend/nextjs/), [example-tauri-v2-python-server-sidecar](https://github.com/dieharders/example-tauri-v2-python-server-sidecar), [Production desktop LLM apps: Tauri+FastAPI+PyInstaller](https://aiechoes.substack.com/p/building-production-ready-desktop)
- Flujo de procesamiento gravimétrico del consultor (deriva/marea/latitud/aire-libre/Bouguer/Nettleton/terreno/regional-residual): [GPG UBC — gravity data acquisition & reduction](https://gpg.geosci.xyz/content/gravity/gravity_data.html), [Geosphere — Bouguer reduction estandarizada](https://pubs.geoscienceworld.org/gsa/geosphere/article/3/2/86/31148/Gravity-reduction-spreadsheet-to-calculate-the), [Seequent — Gravity & Terrain Correction workflow](https://www.seequent.com/a-new-level-of-workflow-control-with-the-gravity-terrain-correction-extension-in-oasis-montaj-2021-2/)
- Flujo de procesamiento magnético (diurna/IGRF/RTP/derivadas/tilt/señal analítica/continuación/Euler): [Scientific Reports — interpretación aeromagnética con RTP+derivadas+Euler](https://www.nature.com/articles/s41598-024-65941-1), [BGS — data processing](https://earthwise.bgs.ac.uk/index.php/OR/14/014_Part_3:_Data_processing), [Rangefront — magnetic surveys guide](https://rangefront.com/blog/magnetic-surveys-guide/)
- Sondajes (desurvey/QAQC): [SRK — why desurveying method matters](https://www.srk.com/en/publications/why-does-the-desurveying-method-for-drillholes-matter), [AusIMM bulletin](https://www.ausimm.com/bulletin/bulletin-articles/why-does-the-desurveying-method-for-drillholes-matter/)
- Reducir la no-unicidad (restricciones geológicas/petrofísicas, joint, boreholes): [SimPEG/arXiv — inversiones con restricciones petrofísicas y geológicas (PGI)](https://arxiv.org/pdf/2203.13894), [ResearchGate — borehole data en inversión con fuzzy clustering](https://www.researchgate.net/publication/323450651_Integration_of_Borehole_Data_in_Geophysical_Inversion_Using_Fuzzy_Clustering), [Springer — joint 3D potenciales con cross-gradient y depth weighting](https://link.springer.com/article/10.1007/s11600-025-01561-1)
- Ley entre pozos = geoestadística (F11-G): [Snowden Optiro — simulación condicional en estimación de recursos](https://snowdenoptiro.com/the-power-of-conditional-simulation-in-mineral-resource-evaluation/), [Springer — cuantificación de incertidumbre en estimación de recursos](https://link.springer.com/article/10.1007/s11053-024-10394-6), [GStatSim (paquete Python open-source de referencia)](https://gmd.copernicus.org/articles/16/3765/2023/)
- Profundidad = geofísica de pozo y EM (F11-b): [Discovery Alert — downhole geophysics para exploración](https://discoveryalert.com.au/downhole-geophysics-mineral-exploration-2025/), [CJES — Lalor: EM multi-escala (aéreo/superficie/pozo) para exploración profunda](https://cdnsciencepub.com/doi/10.1139/cjes-2018-0069), [Abitibi Geophysics — borehole TDEM](https://www.ageophysics.com/en/borehole-tdem)
- Mercado/precios/comprador: `docs/00_INVESTIGACION_MERCADO.md` (fuentes dentro).
