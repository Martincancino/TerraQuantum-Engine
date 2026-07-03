# TerraQuantum — MAPA DEL CÓDIGO (F1)

| Campo | Valor |
|---|---|
| Fecha | 2026-07-02 |
| Método | 9 routers analizados en profundidad por agentes (con búsqueda exhaustiva de usos) + grafo de imports mecánico (script) de TODO el backend + escaneo de endpoints usados por el frontend + verificaciones puntuales. |
| Estado | Backend completo a nivel archivo. **Pendiente 2ª pasada:** caza de símbolos muertos DENTRO de los servicios grandes y áreas frontend (componentes/lib) archivo por archivo. |
| Clases | **DORADO** (camino dorado) · **SECUNDARIO** (usado, fuera del camino) · **SIN_CABLEAR** (construido sin llamadores, previsto por el plan) · **MUERTO** (sin llamadores ni rol) |

---

## 1. El camino dorado (verificado, cadena exacta)

```
CSV usuario → PrepPanel/PreparacionView
  → POST /gravity-import/preview + /v2/analyze-columns   (csv_analysis, column_mapping)
  → POST /v2/enrich-package                              (csv_enrichment → gravity_corrections, igrf, elevation, helmert, opentopo, coordinate_transform)
  → POST /v2/build-package                               (csv_package_service; sondajes vía POST /borehole/parse-csv → boreholes_json)
  → POST /v2/load-package  [SÍNCRONO — dolor conocido]   (gravity_import_service → geophysics_service.run_geophysics_inversion
                                                          → inversion_kernel/solver/postprocess, joint_inversion,
                                                          exploration/gravimetry.py, exploration/magnetometry.py,
                                                          gates: spatial_readiness, regional_scale_preflight)
  → block model persistido (block_model_store, parquet)  + report B1/B2/B3 + favorability.json
  → GET /block-model-arrow (visor 3D, Exploration3DView) | /block-model (JSON fallback, Historial) | /block-model-zarr (>500k vóxeles)
  → GET /export/bundle/{p}/{r} (ZIP: vtr/mod/msh/gslib)  + GET /export-report
```

## 2. Clasificación por archivo — API (17 routers, todos registrados en main.py)

| Router | Clase | Evidencia clave |
|---|---|---|
| gravity_import_api.py | **DORADO** (mixto) | 5 endpoints = corazón del flujo. Muertos parciales: wrapper FE `invertGravityCsv`+proxy sin llamador UI (endpoint v1 vive en tests de contrato); `/v2/invert-with-corrections` solo tests/docs (flujo de campo F25) |
| block_model_api.py | **DORADO** (mixto) | arrow/json/zarr vivos E2E. `/v2/block-model-profile` (secciones A-A') 0 llamadores → **es la semilla de los cortes de F4/F5** |
| borehole_api.py | **DORADO** (mixto) | parse-csv cableado E2E. `/lithology-properties` 0 llamadores → F4 (colorear sondajes) |
| geophysics_api.py | **DORADO** (mixto) | ⭐ **HALLAZGO F3**: `/geophysics-invert` (BackgroundTasks, :232) + `/geophysics-status` + `/v2/…/stream` (SSE) + `/geophysics-misfit` — ruta asíncrona SIN Celery que el flujo DIRECTO ya usa (Exploration3DView importa runGeophysicsInvert+getGeophysicsStatus); el flujo de PAQUETE nunca la adoptó → F3 = replicar ese patrón en load-package. Muertos: `/geophysics-live-update` (Woodbury, 0 usos → F11), ~~`/export/vtr`~~ (podado), `/v2/geophysics-invert` (solo tests) |
| async_api.py | **SIN_CABLEAR** | Celery/Redis punta a punta (worker, proxies, helpers TS con poll/cancel) y CERO llamadores UI. Bug: proxy DELETE llama con GET (route.ts:35). F3 decide: esta vía (requiere Redis) vs geophysics_api nativa (cero infra) |
| gravity_corrections_api.py | **SECUNDARIO** (mixto) | `/apply` vivo (wizard opt-in en Preparación). ⭐ `/nettleton` EXISTE (servicio testeado) sin UI → F2B lo cablea (corrige al plan que lo daba por inexistente). `/terrain-dem` 0 usos → MUERTO (cubierto por /apply) |
| export_api.py | **DORADO** (mixto) | `/export/bundle` = paso exports del camino. `/qa-diagnostics` 0 usos (datos llegan vía report) → **MUERTO confirmado** (arrastra export_service.get_run_qa_diagnostics:975) |
| chat_api.py | **SECUNDARIO** | IAChatView E2E vivo. Base de F6. Duplica _BANNED_WORDS con gemini_agent (F6 unifica). 0 tests |
| favorability_api.py | **SECUNDARIO** | Panel en DatosView vivo E2E (corrige la sospecha de sin-cablear) |
| system_api.py | **SECUNDARIO** | health/system-status/project-runs/compare/export-run — todos con FE (Historial, system-check) |
| project_api.py, terrain_api.py, spectral_api.py | **SECUNDARIO** | terreno + índices satelitales GEE, vivos vía app/api/terrain |
| multimodal_api.py | **SECUNDARIO** | `/plan` vivo (MultimodalComboPanel) |
| metrics_api.py | **SECUNDARIO** | `/metrics` ← AnalyticsPanel |
| report_api.py | **DORADO** | `/export-report` vivo (frontendApi + proxy) |
| keys_api.py | **SECUNDARIO** (latente) | Auth por API-key montada pero TQ_AUTH_ENABLED=false. ⚠️ F7: activarla HOY rompería la UI (el frontend nunca envía X-TQ-API-Key) |

## 3. Clasificación — servicios (grafo de imports de producción)

- **DORADO (cadena de ingesta):** csv_analysis, column_mapping, csv_enrichment, csv_package, elevation_enrichment, helmert_transform, igrf, opentopo, coordinate_transform_real/service, grid_calculator, gravity_preprocessing, gravity_corrections, gravity_import_service, borehole_service.
- **DORADO (cadena de inversión/entrega):** geophysics_service (orquestador, 45 usos en tests/scripts), inversion_kernel/solver/postprocess, joint_inversion, block_model_service, export_service (menos el símbolo muerto), spatial_readiness, regional_scale_preflight, octree_mesh_builder (importado por geophysics_service y grid_calculator — SÍ está en producción).
- **SECUNDARIO:** favorability_service, satellite_service, spectral_service (GEE), multimodal_fusion_service, gemini_agent (usado por joint_inversion para el reporte de interpretación; base F6), metrics.
- **SIN_CABLEAR:** svdag_service (solo lo importa volumetric_service), volumetric_service (importado por geophysics_service — ejecución condicional a verificar en F4). Motor: shuttle F8.1, level-set F7, Woodbury live-update (endpoints/uso en F11).
- **CASO ÚNICO — prod=0:** field_validation_service (solo tests/scripts, 5) → herramienta de la suite de validación → se queda como soporte de **F9**, no se borra.

## 4. PODA — muertos confirmados ✅ EJECUTADA 2026-07-02

| # | Qué | Evidencia | Estado |
|---|---|---|---|
| 1 | `get_qa_diagnostics` + `export_service.get_run_qa_diagnostics` (además FABRICABA L-curve ilustrativa y checkerboard estimado) | Grep repo completo: solo la definición; el panel consume los mismos datos vía report | ✅ commit `096c2e4` |
| 2 | `compute_terrain_correction_dem` (POST /terrain-dem) + modelos `TerrainCorrection*` | 0 llamadores; cubierto por /apply; helper `_compute_tc_opentopo` conservado (compartido) | ✅ `096c2e4` |
| 3 | `GET /export/vtr/{p}/{r}` | 0 usos; el bundle ZIP ya entrega model.vtr | ✅ `096c2e4` |
| 4 | `findDemoHighlightVoxel` (función + import) | Import sin uso; 0 usos repo-wide; física en TS marcada DEMO | ✅ `9c53d70` |
| 5 | Wrapper FE `invertGravityCsv` + proxy `app/api/gravity-import/invert/route.ts` | Ningún componente los llama; tipos `GravityCsvInvert*` conservados (store/PrepPanel); endpoint backend v1 conservado (tests de contrato) | ✅ `9c53d70` |

Verificación post-poda: compileall OK, 41 tests export+corrections PASS, `tsc --noEmit` limpio, eslint 0 errores en archivos tocados.

## 5. SIN_CABLEAR — decisiones por pieza ✅ DESTINOS APROBADOS por Martín (2026-07-02)

| Pieza | Propuesta | Fase |
|---|---|---|
| async_api (Celery/Redis) | Preferir la vía nativa de geophysics_api (cero infra, coherente local-first); Celery se borra o congela al cerrar F3 | F3 |
| `/v2/block-model-profile` (secciones A-A') | Cablear como base de los cortes | F4/F5 |
| `/borehole/lithology-properties` | Cablear al colorear sondajes en el visor | F4 |
| `/gravity-corrections/nettleton` | Cablear UI (¡ya existe el cálculo!) | F2B |
| `/v2/invert-with-corrections` | Fusionar con enrich-package o retirar tras F2B | F2B/F3 |
| `/geophysics-live-update` (Woodbury) | Semilla del bucle perforar→re-invertir | F11 |
| svdag/volumetric | Medir si la ruta se ejecuta; decidir en render | F4 |
| `/v2/geophysics-invert` (solo tests) | Revisar al unificar rutas de inversión | F3 |

## 6. Bugs y riesgos encontrados de pasada (no bloqueantes, anotados)

1. Proxy `app/api/async/tasks/[task_id]/route.ts:35`: el handler DELETE llama al backend con `method: "GET"` — nunca cancelaría. Corregir si F3 adopta esa vía.
2. `/block-model-zarr` serializa vóxel por vóxel a JSON (block_model_api.py:151-161) — funciona pero contradice el camino binario; revisar en F4 si los grids grandes se vuelven norma.
3. `TQ_AUTH_ENABLED=true` rompería la web UI actual (frontend no envía el header) — resolver en F7 (licencias/seguridad).
4. `_BANNED_WORDS` duplicada (chat_api vs gemini_agent) — unificar en F6.
5. Cobertura de tests HTTP inexistente en: borehole_api, chat_api, export_api, keys_api, favorability (endpoint) — F8 (schemathesis) lo cubrirá de golpe.
6. eslint baseline (2026-07-02): **7 errores preexistentes** react-hooks — `GravityCorrectionWizard.tsx` (setState síncrono en effect :218 + 5× componentes creados durante render :386-390) y `ObsVsCalcPanel.tsx` (:266 setState en effect). Arreglar cuando F2B rehaga el wizard (es el mismo componente); mientras, la CI usa umbral de warnings, no de errores nuevos.

## 7. Raíz del repo — orden ✅ EJECUTADO 2026-07-02

- `diag_*.py` (7) + `generar_*.py` (4) → `terraquantum-backend/scripts/diagnostics/` (sys.path corregidos).
- CSVs de prueba (`LdM_*`, `multi_*`, `prueba_*`, `do27_*`, `laguna_*`) + `.tqpkg` (18 archivos) → `terraquantum-backend/tests/fixtures/csv_reales/` = **corpus de F2**. Referencias en scripts de validación actualizadas.
- **2ª tanda ✅ EJECUTADA con aprobación de Martín (2026-07-02):** borrados `simpeg_env/` (venv recreable), `simpeg_github/` (clon), `simpeg_data_gravity3d/` y `simpeg_data_potential/` (vacíos), `TERRAQUANTUM_API_ROUTES.json` (dump generado sin referencias, obsoleto tras la poda). Movidos a `data/external/`: simpeg_data_joint_inversion, simpeg_data_mag, PNGs/PDF de visualización. Movidos a `scripts/diagnostics/`: convertir_a_csv, descargar_*, inspeccionar_*, visualizar_datasets (cwd-relativos: correr desde la raíz del repo). **SE QUEDAN en la raíz** (trackeados y referenciados por tests/validación — fixtures de F9): `DO-27_Kimberlite/` (113 MB), `Raglan_Magnetic/`, `benchmarks/`.

## 8. Línea base de CI (medida hoy)

- `python -m compileall api services exploration core` → **OK**
- `pytest --co` → **1.700 tests colectados** en 188 archivos (~20 s colección)
- Pendiente F1: script `check.ps1` + suite rápida marcada + eslint/tsc, corriendo en cada commit.
