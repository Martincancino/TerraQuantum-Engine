# PLAN MAESTRO DE REMEDIACIÓN — TERRAQUANTUM V3
**Generado: 2026-05-31 | Basado en auditoría de código completa | 15 agentes, 236 tool calls | Clasificación: INTERNO**

---

## FASE 0 — ESTADO REAL ACTUAL

TerraQuantum V2 es un prototipo de exploración geofísica técnicamente ambicioso, construido por un solo desarrollador en aproximadamente un mes. La arquitectura central es coherente: FastAPI + Polars en el backend, Next.js + Three.js en el frontend, con módulos de inversión gravimétrica/magnética en Python puro usando LSQR + NumPy. El código tiene claramente buenas intenciones de cumplimiento (JORC/NI-43-101), capas de validación Pydantic, y un sistema de proyectos/runs con trazabilidad básica.

Sin embargo, el estado real revela una brecha profunda entre lo que el código pretende hacer y lo que realmente hace en producción:

**Lo que está genuinamente bien:**
- La matemática de kernels gravitacionales (Nagy 1966, exacta para campo cercano) es correcta.
- El agente Gemini (`gemini_agent.py`) tiene guardrails de compliance robustos: banned words list, validación Pydantic en dos capas, temperatura conservadora.
- La separación regional-residual y el checkerboard test existen como QA básico.
- El esquema de inversión conjunta cross-gradient (Gallardo-Meju) está conceptualmente bien implementado.
- El sistema de block model store con `clean_trace_id` y prevención de path traversal es sólido.
- El módulo de enfoque MS-x (Portniaguine & Zhdanov 1999) es correcto conceptualmente.

**Lo que está roto o es riesgo activo:**
- Inyección de ruido gaussiano en observaciones reales cuando el misfit es "demasiado bajo" — contaminación activa de datos.
- `pandas` usado en servicios de producción sin estar en `requirements.txt` — falla silenciosa en despliegue limpio.
- Modelo Gemini `gemini-1.5-pro` deprecado en dos endpoints.
- Chat API viola compliance JORC en su propio system prompt ("estimación de recursos minerales").
- Transporte Arrow completamente implementado en backend y proxy frontend, pero **ningún componente del frontend lo llama**.
- Susceptibilidad llega al frontend con color NaN silencioso cuando los datos magnéticos están ausentes.
- Topografía hardcodeada a `None` en todos los call sites de producción — todos los vóxeles activos independientemente de la superficie.
- Bounds físicos (densidad, susceptibilidad) aplicados por `np.clip()` post-LSQR, no por optimización con restricciones.
- Schema divergente entre inversión gravity-only, magnética y joint — ningún contrato unificado de Parquet.
- Zero autenticación en ningún endpoint.

---

## EVIDENCIA VERIFICADA — CLAIMS DEL INFORME

Los 15 hallazgos críticos del informe de auditoría fueron verificados contra el código real:

| Claim | Veredicto | Evidencia (archivo:línea) |
|---|---|---|
| pandas no declarado en requirements | **VALIDADO** | `gravity_import_service.py:253`, `export_service.py:681` — lazy imports en producción |
| Inyección de ruido gaussiano | **VALIDADO** | `geophysics_service.py:1988-1994` — np.random.normal en path principal |
| gemini-1.5-pro deprecado | **VALIDADO** | `chat_api.py:72`, `gemini_agent.py:304` |
| Bounds por np.clip post-LSQR | **VALIDADO** | `exploration/gravimetry.py:1386-1401`, sin L-BFGS-B ni TRF en ningún archivo |
| Topografía hardcodeada None | **VALIDADO** | `geophysics_service.py:1978, 2011, 2352, 2391, 2964` — 5 call sites |
| Arrow ruta muerta en frontend | **VALIDADO** | `route.ts` + backend implementados; cero llamadas en `.tsx` |
| susceptibility_si no transmitida | **VALIDADO** | `block_model_service.py:691-727` — campo ausente del cell dict |
| Schema joint divergente | **VALIDADO** | joint: `x_c/y_c/z_c`; standard: `ix/iy/iz` — get_index_columns() falla |
| Chat viola JORC | **VALIDADO** | `chat_api.py:49` — "estimación de recursos minerales" en system prompt |
| Run manifest sin hash CSV/seed | **PARCIALMENTE VALIDADO** | Config hash en export bundle solamente; sin SHA-256 de CSV; sin seed |
| geophysics_service.py monolito | **VALIDADO** | 3,022 líneas, 17+ responsabilidades distintas |
| CSR explícita (no matrix-free) | **VALIDADO** | `gravimetry.py:274`, `magnetometry.py:228` — sp.csr_matrix materializado |
| Límite 200,000 vóxeles | **VALIDADO** | Magic number `200_000` en 3 lugares sin constante `MAX_VOXELS` |
| Cross-gradient alternante (no GN simultáneo) | **VALIDADO** | `joint_inversion.py:2-3` — docstring explícito + loop alternante |
| Zero autenticación | **VALIDADO** | main.py: sin JWT, sin OAuth, sin RBAC — solo rate-limiting por IP |

### Hallazgos Descartados / Ya Resueltos

1. **Bug del hundimiento (depth-over-focusing)** — RESUELTO en commit `ae4ab94`. Fix Li & Oldenburg estricto aplicado.
2. **Schema sondajes density/susceptibility separados** — RESUELTO (documentado en proyecto_fase_9b_calibracion).
3. **Joint inversion no escribe Parquet** — OBSOLETO. `_persist_joint_parquet` en `joint_inversion.py:243-254` SÍ persiste. El gap real es la sobreescritura del legacy path (B-10).
4. **Métrica E_norm global saturada** — RESUELTO en commit `e695990` (fix métrica por celda grid-independiente).

---

## FASE 1 — MAPA DE BRECHAS VERIFICADAS

| ID | Problema | Severidad | Estado | Archivos Afectados | Riesgo Negocio | Riesgo Científico | Riesgo Compliance |
|---|---|---|---|---|---|---|---|
| B-01 | Inyección de ruido gaussiano en observaciones reales (misfit <= 0.01%) | **CRÍTICA** | VALIDADO | `services/geophysics_service.py:1988-1994` | ALTO: resultados no reproducibles | CRÍTICO: contamina el observable | ALTO: datos del cliente alterados sin consentimiento |
| B-02 | `pandas` en producción sin declarar en `requirements.txt` | **CRÍTICA** | VALIDADO | `services/gravity_import_service.py:253`, `services/export_service.py:681` | CRÍTICO: falla en despliegue limpio | NINGUNO | BAJO |
| B-03 | Chat API viola JORC en system prompt ("estimación de recursos minerales") y sin banned-words filter | **CRÍTICA** | VALIDADO | `api/chat_api.py:49` | ALTO: exposición legal inmediata | BAJO | CRÍTICO: bypassa todos los guardrails |
| B-04 | Modelo Gemini `gemini-1.5-pro` deprecado en dos endpoints | **CRÍTICA** | VALIDADO | `api/chat_api.py:72`, `services/gemini_agent.py:304` | CRÍTICO: falla total de servicio LLM cuando Google retira el modelo | BAJO | MEDIO |
| B-05 | Topografía hardcodeada `None` en todos los call sites de producción | ALTA | VALIDADO | `services/geophysics_service.py:1978, 2011, 2352, 2391, 2964` | MEDIO | ALTO: artefactos sistemáticos en capa superficial | MEDIO |
| B-06 | Bounds físicos por `np.clip()` post-LSQR, no por optimización con restricciones | ALTA | VALIDADO | `exploration/gravimetry.py:1386-1401` | MEDIO | ALTO: la solución clipeada no es el mínimo real del funcional | MEDIO |
| B-07 | Ruta Arrow completamente implementada backend+proxy pero nunca llamada por frontend | ALTA | VALIDADO | `terraquantum-web/app/api/block-model/route.ts`, `api/block_model_api.py` | ALTO: payload JSON 40MB bloquea el browser | BAJO | BAJO |
| B-08 | Susceptibilidad `NaN` silenciosa en visor 3D cuando datos magnéticos ausentes | ALTA | VALIDADO | `terraquantum-web/componentes/Scene3D.tsx`, `lib/terraQuantumGeology.ts` | ALTO: artefactos visuales confundibles con datos | BAJO | MEDIO |
| B-09 | Schema Parquet divergente entre gravity-only, magnetic, y joint inversion | ALTA | VALIDADO | `services/joint_inversion.py:243-254`, `services/geophysics_service.py:818-836`, `services/block_model_service.py:60-69` | ALTO: frontend hace suposiciones rotas | MEDIO | BAJO |
| B-10 | Joint sobreescribe el Parquet legacy de gravity-only en `DEFAULT_BLOCK_MODEL_PATH` | ALTA | VALIDADO | `services/joint_inversion.py` | MEDIO: datos de corrida gravity-only se pierden | ALTO: pérdida de proveniencia | BAJO |
| B-11 | Zero autenticación en todos los endpoints | ALTA | VALIDADO | `terraquantum-backend/main.py`, todos los routers | CRÍTICO para producción: cualquiera puede leer/escribir proyectos | BAJO | ALTO: datos de clientes expuestos |
| B-12 | `enable_focusing` marcado "deprecated since A1.4" pero sigue activo en schema sin advertencia | MEDIA | VALIDADO | `schemas/geophysics_schema.py` | BAJO | MEDIO | BAJO |
| B-13 | `response_model` no cableado en geophysics_api ni system_api | MEDIA | VALIDADO | `api/geophysics_api.py`, `api/system_api.py` | BAJO | BAJO | BAJO |
| B-14 | Rate limiting solo en 3 endpoints de 15+ | MEDIA | VALIDADO | `terraquantum-backend/main.py` | MEDIO | BAJO | BAJO |
| B-15 | Inverse crime en checkerboard: misma malla forward e inversión | MEDIA | VALIDADO (por omisión) | `exploration/checkerboard_test.py` | BAJO | ALTO: test pasa aunque el solver tenga bugs sistemáticos | BAJO |
| B-16 | `geophysics_service.py` tiene 3,022 líneas — God File | MEDIA | VALIDADO | `services/geophysics_service.py` | MEDIO: mantenimiento difícil | BAJO | BAJO |
| B-17 | `APP_VERSION = "0.1.0"` sin schema versioning ni migrations | BAJA | VALIDADO | `core/config.py:7` | BAJO ahora, alto en V3 | BAJO | BAJO |
| B-18 | `FEATURE_FLAGS` sin documentación ni pruebas de activación accidental | BAJA | VALIDADO | `terraquantum-backend/main.py` | MEDIO: activación accidental de pit_design | BAJO | MEDIO |
| B-19 | Sin frontend tests (.test.ts / .spec.ts = 0 archivos) | BAJA | VALIDADO | `terraquantum-web/` | MEDIO | BAJO | BAJO |
| B-20 | CSR explícita no escala a 1M+ vóxeles | BAJA (hoy) | VALIDADO | `exploration/gravimetry.py:274`, `exploration/magnetometry.py:228` | BAJO (límite 200k), alto en V3 | ALTO a escala | BAJO |

---

## FASE 2 — ARQUITECTURA OBJETIVO

### Backend — Hexagonal con Worker Separation

La arquitectura objetivo separa tres capas que hoy están mezcladas en `geophysics_service.py`:

**Capa de Dominio (Pura, sin I/O):**
- `domain/geophysics/`: kernels, solvers, objetivos funcionales — sin FastAPI ni filesystem
- `domain/inversion/`: configuración de parámetros de inversión
- `domain/block_model/`: schema unificado, serialización/deserialización

**Capa de Aplicación:**
- `services/`: orquestación de casos de uso (llamar dominio + persistir resultado)
- `workers/`: workers Celery o RQ para inversiones > 5 segundos
- `api/`: routers FastAPI delgados — solo validación Pydantic + llamada al service

**Capa de Infraestructura:**
- `persistence/`: lectura/escritura Parquet con schema fijo versionado
- `storage/`: abstracción filesystem hoy, S3/GCS mañana

### Geophysics Engine — Matrix-Free + Bound-Constrained

Para el camino a 1M+ vóxeles:
- **Kernel matrix-free**: reemplazar CSR explícita por `scipy.sparse.linalg.LinearOperator` con `matvec = compute_G_times_v(v, geometry)`
- **Solver bound-constrained**: `scipy.optimize.lsq_linear(method='bvls')` o PCGLS proyectado. Garantiza la solución es el mínimo real dentro de los bounds.
- **Topografía activa**: activar el código ya existente en `gravimetry.py` y `magnetometry.py` — simplemente dejar de hardcodear `topography_elevations=None`

### Joint Inversion — Mantener Alternante, Mejorar Criterio de Parada

El esquema alternante (Gallardo-Meju) es correcto para el estado actual. El gap crítico no es el esquema sino:
- Agregar `cross_gradient_residual_norm` como criterio de parada conjunto
- Loguear la evolución de acoplamiento por iteración
- Métrica de similaridad estructural (SSIM) en el report

### Persistence — Schema Parquet Unificado

```
Columnas obligatorias (todos los runs):
  x_m, y_m, z_m          — centroide métrico
  run_type                — "gravity" | "magnetic" | "joint"
  schema_version          — "v3.0"

Columnas de gravimetría (run_type = "gravity" o "joint"):
  density_t_m3            — densidad absoluta
  density_contrast_t_m3   — contraste respecto a background
  density_anomaly_score   — métrica normalizada

Columnas de magnetometría (run_type = "magnetic" o "joint"):
  susceptibility_si       — susceptibilidad magnética SI
  susceptibility_score    — métrica normalizada

Columnas de joint (run_type = "joint" únicamente):
  joint_structural_score  — similaridad estructural cross-gradient

Columnas de incertidumbre (opcionales):
  posterior_std           — std de la diagonal del posterior
  doi_raw                 — depth of investigation

Columnas de demo/exploración (solo si expose_demo_grade=True):
  visual_score, probability_score, grade_proxy
```

Cada corrida escribe además un `run_manifest.json`:
- `sha256_parquet`: hash SHA-256 del Parquet escrito
- `sha256_csv`: hash SHA-256 del CSV de input
- `inversion_params`: todos los parámetros del solver (lambda, alpha, nx/ny/nz, block_size, etc.)
- `solver_stats`: iteraciones, misfit final, chi2, condición de número, warnings
- `schema_version`: versión del schema Parquet
- `code_version`: git hash del commit
- `rng_seed`: semilla si se usó randomness (no debe usarse en producción)
- `timestamp_utc`: timestamp de inicio y fin de inversión

### Frontend — Arrow Streaming + WebWorkers + LOD

**Inmediato (Hito 3):** Activar la ruta Arrow en `Exploration3DView.tsx`. El proxy Next.js está implementado, el backend está implementado — falta el llamador.

**Medio plazo (Hito 6):**
- Deserialización Arrow en WebWorker
- LOD: para > 50k vóxeles, agrupar por octantes a distancias lejanas
- Tiling: chunks Arrow de ~10k vóxeles, carga por demanda

**Para susceptibilidad NaN:** Guardia explícita en `terraQuantumGeology.ts` antes de `sampleColormap`. Badge "Sin datos magnéticos" cuando la guardia activa.

### Gemini / LLM — Compliance Compiler Pattern

Un único módulo `core/compliance.py` que:
1. Recibe output crudo del LLM
2. Aplica banned-words filter (centralizado, no duplicado)
3. Valida contra schema Pydantic del endpoint
4. Agrega disclaimers JORC obligatorios
5. Versiona el output con model name y timestamp

`GEMINI_MODEL_NAME` como constante única en `core/config.py`, leída por ambos endpoints.

### CI/CD — Benchmarks como Tests

Agregar a `.github/workflows/ci.yml`:
- `pytest tests/ -m "unit"` — rápido, sin I/O externo
- `pytest tests/ -m "integration"` — con filesystem temporal
- `pytest tests/ -m "benchmark"` — corrida analítica con ground truth
- Regla anti-inverse-crime: el CI debe verificar que `forward_mesh_params != inversion_mesh_params` en tests de recovery

---

## FASE 3 — ROADMAP DE REMEDIACIÓN (8 Hitos)

### HITO 0 — Congelamiento Semántico y Compliance (QUICK WIN, ~1-2 semanas)

**Objetivo:** Eliminar todos los riesgos de compliance activos sin tocar ningún motor de física.

**Justificación:** B-03 y B-04 son riesgos legales y de servicio activos. B-02 es una falla de despliegue que rompe la importación de gravedad en cualquier entorno limpio. Estos tres pueden resolverse en días.

**Dependencias:** Ninguna.

**Archivos afectados:**
- `api/chat_api.py` — corregir system prompt, importar y aplicar banned-words filter
- `services/gemini_agent.py` — cambiar model string a constante
- `core/config.py` — agregar `GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")`
- `requirements.txt` — agregar `pandas>=2.0.0` (o migrar a Polars nativo)
- `services/geophysics_service.py:1988-1994` — **eliminar inyección de ruido gaussiano**

**Riesgos:** Bajo. El único riesgo es comportamiento diferente de `gemini-2.0-flash` — se mitiga con guardrails idénticos.

**Criterios de éxito:**
- `grep -r "gemini-1.5-pro"` devuelve cero resultados
- `grep -i "estimación de recursos minerales" api/chat_api.py` devuelve cero resultados
- Chat API aplica el mismo banned-words filter que `gemini_agent.py`
- `pip install -r requirements.txt && python -c "import services.gravity_import_service"` no falla en virtualenv limpio
- `grep "np.random.normal" services/geophysics_service.py` devuelve cero resultados en el path de producción

**Criterio de rollback:** Si `gemini-2.0-flash` produce outputs con calidad inferior, revertir a constante configurable vía env var.

---

### HITO 1 — Contrato Unificado de Block Model (~2-3 semanas)

**Objetivo:** Definir y enforcar un schema Parquet único versionado para todos los tipos de corrida. Eliminar la sobreescritura del legacy path.

**Justificación:** B-09, B-10. El frontend hace suposiciones rotas dependiendo del path que tomó la corrida. Un schema explícito con `run_type` y `schema_version` elimina esta complejidad.

**Dependencias:** Hito 0 completado.

**Archivos afectados:**
- `services/joint_inversion.py` — eliminar escritura a `DEFAULT_BLOCK_MODEL_PATH`
- `services/geophysics_service.py` — agregar columnas `run_type` y `schema_version` a todos los Parquet escritos
- `core/block_model_store.py` — agregar `validate_parquet_schema(path, expected_run_type)`
- `schemas/geophysics_schema.py` — agregar `GeophysicsVoxel` unificado con campos opcionales explícitos
- `terraquantum-web/store/useAppStore.ts` — actualizar type para reflejar schema unificado

**Riesgos:** El frontend puede romperse si tenía dependencias implícitas de la sobreescritura legacy. Requiere testing manual de todos los viewModes.

**Criterios de éxito:**
- `block_model_joint.parquet` NUNCA sobreescribe `block_model.parquet`
- Todo Parquet leído por el block_model_store pasa la validación de schema
- Frontend muestra datos correctos para gravity-only, magnetic, y joint en corridas separadas del mismo proyecto

**Criterio de rollback:** Feature flag `LEGACY_BLOCK_MODEL_COMPAT=true` durante 2 semanas post-deploy.

---

### HITO 2 — Provenance Industrial y Run Manifest (~2-3 semanas)

**Objetivo:** Cada corrida tiene un `run_manifest.json` inmutable con hash SHA-256 del Parquet, hash SHA-256 del CSV, parámetros exactos, git hash del código, y versión de schema.

**Justificación:** B-01 ya está parcialmente resuelto en Hito 0 (eliminación del ruido). Este hito cierra la trazabilidad: un auditor externo debe poder verificar que los resultados provienen del CSV original sin modificación.

**Dependencias:** Hito 1 completado (schema unificado necesario para hashear Parquet consistente).

**Archivos afectados:**
- `core/block_model_store.py` — agregar `write_run_manifest(run_dir, manifest_dict)`
- `services/geophysics_service.py` — llamar a `write_run_manifest` al final de cada inversión exitosa
- `services/joint_inversion.py` — ídem
- `services/export_service.py` — actualizar `_build_bundle_manifest` para incluir hash CSV

**Riesgos:** Los tests que usan datos sintéticos perfectos (misfit=0%) ahora loguean un warning en el manifest. Este es el comportamiento correcto.

**Criterios de éxito:**
- Cada run_dir contiene `run_manifest.json` con todos los campos requeridos
- El hash SHA-256 del Parquet en el manifest coincide con el Parquet en disco
- El hash SHA-256 del CSV en el manifest coincide con el CSV guardado
- El run manifest se escribe ATÓMICAMENTE al completarse la inversión (no solo en export)

**Criterio de rollback:** El manifest es una adición — no puede causar regresiones. Si write_manifest falla, loguear error sin bloquear el resultado de la inversión.

---

### HITO 3 — Transporte de Datos Multi-Física al Frontend (~2-3 semanas)

**Objetivo:** Activar Arrow para transporte, corregir NaN silencioso de susceptibilidad, exponer datos magnéticos y joint correctamente en los viewModes.

**Justificación:** B-07, B-08. La infraestructura Arrow ya existe — falta conectar el llamador. El NaN silencioso es un riesgo visual activo para clientes.

**Dependencias:** Hito 1 completado (schema unificado necesario para columnas consistentes en Arrow).

**Archivos afectados:**
- `terraquantum-web/componentes/Exploration3DView.tsx` — reemplazar llamada JSON por llamada Arrow cuando `cells.length > 5000`
- `terraquantum-web/lib/terraQuantumGeology.ts` — agregar guardia antes del colormap de susceptibilidad
- `terraquantum-web/componentes/Scene3D.tsx` — badge "Sin datos magnéticos" cuando susceptibilidad no disponible

**Riesgos:** La deserialización Arrow en el hilo principal puede bloquear la UI brevemente durante el parse. WebWorker (Hito 6) es la solución completa.

**Criterios de éxito:**
- Network tab muestra `application/vnd.apache.arrow.stream` para corridas > 5k vóxeles
- Cambiar viewMode a "susceptibility" sin datos magnéticos muestra gris neutro con badge "Sin datos magnéticos"
- Sin regresión en viewMode density

**Criterio de rollback:** Feature flag `USE_ARROW_TRANSPORT=false` en `.env.local` que fuerza el path JSON.

---

### HITO 4 — Suite de Validación Científica (~3-4 semanas)

**Objetivo:** Agregar benchmarks analíticos que CI ejecuta automáticamente y detectan regresiones en la física. Implementar protocolo anti-inverse-crime.

**Justificación:** B-15. Los tests actuales usan la misma malla para forward e inversión — inverse crime. Un test analítico contra solución cerrada (esfera, prisma de Plouff) no puede pasar por inverse crime porque la solución exacta es independiente del código.

**Dependencias:** Hito 2 completado (proveniencia trazable para que los tests sean auditables).

**Archivos afectados:**
- `tests/test_analytic_sphere_validation.py` — agregar versión con malla de inversión diferente a la malla forward
- `tests/` — agregar `test_prism_recovery_benchmark.py`, `test_doi_calibration.py`, `test_joint_structural_similarity.py`, `test_no_noise_injection.py`
- `.github/workflows/ci.yml` — agregar step de benchmark con threshold de regresión

**Riesgos:** Los nuevos tests pueden fallar si revelan bugs en el solver. Este es el resultado CORRECTO.

**Criterios de éxito:**
- CI tiene step `pytest tests/ -m "benchmark"` que falla si la recuperación esférica tiene error > 10%
- Ningún test usa la misma malla para forward e inversión
- `test_no_noise_injection.py` verifica que `g_observed` es bit-identical al inicio y al final de la inversión

---

### HITO 5 — Hardening del Solver (~4-6 semanas)

**Objetivo:** Reemplazar LSQR + `np.clip` por solver bound-constrained real. Activar topografía en el path de producción.

**Justificación:** B-05, B-06. El solver puede producir densidades negativas durante la solución que luego son clippeadas. Para terrenos rugosos, ignorar la topografía introduce artefactos sistemáticos en los vóxeles superficiales.

**Dependencias:** Hito 4 completado. Los tests científicos DEBEN estar activos antes de cambiar el solver.

**Archivos afectados:**
- `exploration/gravimetry.py` — reemplazar LSQR + `np.clip` por `scipy.optimize.lsq_linear(bounds=(...))`
- `exploration/magnetometry.py` — ídem para susceptibilidad
- `services/geophysics_service.py` — activar `topography_elevations` leyendo elevación del sensor desde el servicio de terreno

**Riesgos:**
- El solver bound-constrained es más lento (2x-5x). Requiere benchmarking de performance.
- El cambio de solver cambia los resultados de corridas históricas. Documentar con `schema_version`.

**Criterios de éxito:**
- `clip_fraction` reportado en el run report es 0.0% para cualquier corrida bien condicionada
- Tests de `test_analytic_sphere_validation.py` pasan con mallas separadas (anti-inverse-crime)
- Benchmark de performance: solver bound-constrained < 60 segundos para nx=32, ny=20, nz=32

**Criterio de rollback:** Flag `USE_BOUNDED_SOLVER=false` que mantiene LSQR + clip. Disponible 4 semanas post-deploy.

---

### HITO 6 — Escalabilidad y Frontend Industrial (~6-8 semanas)

**Objetivo:** WebWorkers para deserialización Arrow, LOD para rendering, soporte a 500k vóxeles sin bloquear UI.

**Justificación:** Con > 100k vóxeles el tab del browser se congela. Three.js InstancedMesh puede manejar 500k instancias si el buffer de colores se calcula off-thread.

**Dependencias:** Hito 3 completado (Arrow activado).

**Archivos afectados:**
- Nuevo `terraquantum-web/workers/arrowDeserializer.worker.ts`
- `terraquantum-web/componentes/Scene3D.tsx` — recibir Float32Array pre-calculados
- `terraquantum-web/lib/terraQuantumGeology.ts` — mover `updateInstancedBuffers` para callable desde worker

**Criterios de éxito:**
- 200k vóxeles carga y renderiza sin bloquear hilo principal > 16ms
- Frame rate mantiene > 30 FPS con 500k vóxeles en hardware de gama media

---

### HITO 7 — Infraestructura Enterprise (~8-12 semanas)

**Objetivo:** Autenticación, RBAC, workers asíncronos, observabilidad, path a cloud storage.

**Justificación:** B-11. Zero auth es aceptable solo durante desarrollo. Cualquier demo con datos reales de un cliente es una exposición.

**Dependencias:** Hitos 0-5 completados.

**Componentes:**
- Auth middleware con API keys: header `X-TQ-API-Key` validado contra tabla en SQLite/Postgres
- Workers asíncronos: Celery + Redis o ARQ. Endpoint `POST /invert` retorna `{run_id, status_url}`
- Observabilidad: OpenTelemetry traces, Prometheus metrics
- Cloud storage: abstracción `StorageBackend` con implementación local y S3/GCS via `STORAGE_BACKEND` env var

**Criterios de éxito:**
- Ningún endpoint retorna datos sin API key válido
- Una inversión de 200k vóxeles puede ser encolada y el frontend ve el estado via polling
- El sistema maneja 10 inversiones concurrentes sin degradación

---

## FASE 4 — PLAN DETALLADO POR PROBLEMA CRÍTICO

### PROBLEMA B-01 — Inyección de Ruido Gaussiano

**Por qué existe:**
El desarrollador encontró que misfit=0.00% hace que el L-curve no tenga curvatura (la curva es trivial cuando el ajuste es perfecto), lo cual impide la selección automática de lambda. La solución adoptada fue "forzar" el misfit inyectando ruido. Esta solución de conveniencia en un contexto de demo se filtró al path de producción.

**El riesgo real:**
Si un cliente importa datos de gravedad reales y el misfit inicial es < 0.01% (posible con datos de alta precisión o con lambda muy pequeña), sus observaciones son contaminadas con ruido gaussiano del 5% sin ningún aviso. El run report muestra resultados basados en datos alterados. Esto invalida científicamente cualquier interpretación basada en esa corrida. La contaminación es silenciosa.

**La solución industrial:**
Eliminar las líneas 1988–1994 de `geophysics_service.py`. Reemplazar con:
- Si `misfit_percent <= 0.01`: loguear `WARNING: misfit perfecto detectado, posible datos sintéticos o lambda sub-óptima.`
- Agregar campo `misfit_warning: Optional[str]` al report payload
- Para el caso legítimo de selección de lambda con datos sintéticos: la grilla de lambda debe ser fija, no depender del misfit para inyectar ruido

**Cómo validar:**
Test `test_no_noise_injection.py`:
1. Construir observations sintéticas perfectas (misfit exacto = 0%)
2. Correr la inversión completa
3. Verificar que `g_observed` al final es bit-identical a `g_observed` al inicio
4. Verificar que el run report contiene `misfit_warning` con el texto correcto

---

### PROBLEMA B-02 — Pandas no Declarado

**Por qué existe:**
La stack migró de pandas a polars en algún punto del desarrollo, pero dos funciones no fueron migradas. Al estar en lazy imports dentro de funciones, Python no falla al importar el módulo — solo falla cuando se llama la función específica.

**El riesgo real:**
En cualquier entorno de despliegue que no tenga pandas instalado (contenedor Docker limpio, CI, ambiente de un cliente), la importación de gravedad y la exportación fallan con `ModuleNotFoundError` en runtime, no en startup.

**La solución industrial:**
Opción A (preferida): Reescribir las dos funciones usando Polars/PyArrow. Ambas leen CSVs o escriben outputs tabulares — Polars puede hacer ambos.
Opción B (fallback rápido): Agregar `pandas>=2.0.0` a `requirements.txt`. Menos elegante pero resuelve la falla de despliegue en 30 minutos.

**Tests a agregar:**
- `test_imports_clean.py` — importa todos los módulos de servicios; falla si alguno requiere un paquete no declarado

---

### PROBLEMA B-03 — Chat API Viola JORC

**Por qué existe:**
El system prompt del chat fue escrito sin tener en cuenta los guardrails del `gemini_agent.py`. Los dos archivos fueron desarrollados por separado y nunca se auditaron cruzadamente.

**El riesgo real:**
Un geólogo usando el chat puede preguntar "¿qué recursos tiene este depósito?" y el modelo, habiendo sido instruido que es un "especialista en estimación de recursos minerales", puede responder con estimaciones específicas. Si esa respuesta se cita en un informe técnico, es una violación directa de JORC/NI-43-101.

**La solución industrial:**
1. Reescribir system prompt del chat: "asistente de interpretación geofísica y análisis de datos de exploración"
2. Centralizar guardrails en `core/compliance.py` — ambos endpoints importan la misma clase
3. Agregar `response_mime_type = "text/plain"` al chat (no necesita JSON estructurado)

**Tests a agregar:**
- `test_chat_compliance.py` — mockear respuesta de Gemini con cada palabra de `_BANNED_WORDS`, verificar que el endpoint retorna respuesta redactada
- `test_banned_words_coverage.py` — verifica que `_BANNED_WORDS` es la misma lista en ambos endpoints

---

### PROBLEMA B-04 — Gemini 1.5 Pro Deprecated

**Por qué existe:**
El modelo fue hardcodeado en dos archivos independientes. No existe una constante centralizada de configuración para el modelo LLM.

**El riesgo real:**
Cuando Google retira `gemini-1.5-pro`, ambos endpoints retornan 404 o 503 simultáneamente. Sin fallback. Sin preaviso en el código.

**La solución industrial:**
1. `core/config.py`: `GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")`
2. Ambos archivos leen de `config.GEMINI_MODEL_NAME`
3. `.env.example`: `# GEMINI_MODEL_NAME=gemini-2.5-pro`
4. Health check incluye `gemini_model_status: "ok" | "error"`

---

### PROBLEMA B-05 — Topografía Hardcodeada None

**Por qué existe:**
El código de celdas activas por topografía existe en `gravimetry.py` y `magnetometry.py`, pero `geophysics_service.py` nunca lo activa porque la UI no tiene (aún) un mecanismo de entrada de elevaciones de terreno por sensor. En lugar de dejar el parámetro sin conectar, fue hardcodeado a None con un comentario explicativo.

**El riesgo real:**
En cualquier levantamiento sobre terreno con relieve > 50m (prácticamente toda minería de superficie), los vóxeles sobre la superficie real son tratados como roca. Introduce densidades anómalas sistemáticas en los primeros 1-3 capas de vóxeles que el intérprete puede confundir con anomalías reales.

**La solución industrial:**
1. Agregar campo opcional `sensor_elevations_masl: Optional[List[float]]` al request
2. Si se provee y tiene la misma longitud que `observations`, pasarlo al motor de inversión
3. El informe técnico indica si la inversión usó topografía real o plana
4. La UI puede obtener la elevación de cada sensor desde `terrain_api.py` (ya existe)

**Tests a agregar:**
- `test_topography_masking.py` — correr con y sin topografía, verificar que con topografía hay menos celdas activas y diferente distribución superficial

---

### PROBLEMA B-06 — Bounds por Clip Post-Hoc

**Por qué existe:**
LSQR es el solver estándar de mínimos cuadrados escasos pero no soporta bounds. La opción rápida fue aplicar `np.clip` después de la solución. El código tiene un diagnóstico de `clip_fraction` que revela que el equipo sabía que el solver excede los bounds.

**El riesgo real:**
La solución clipeada no es el mínimo del funcional objetivo dentro del espacio factible. En la práctica, `clip_fraction > 10%` significa que el solver está encontrando un mínimo fuera de la física permitida.

**La solución industrial:**
- Corto plazo: `scipy.optimize.lsq_linear(A, b, bounds=(lb, ub), method='bvls')`
- Largo plazo con kernels grandes: Projected Conjugate Gradient o Active Set
- `clip_fraction` mantenerlo como diagnóstico; valor esperado = 0.0% con el nuevo solver

---

### PROBLEMA B-07 — Arrow Ruta Muerta

**Por qué existe:**
La ruta Arrow fue implementada completamente en el backend y el proxy Next.js como preparación para escalabilidad, pero el componente frontend que debería llamarla (`Exploration3DView.tsx`) nunca fue actualizado.

**El riesgo real:**
Con 200k vóxeles, el response JSON es ~40MB. El browser descarga 40MB de JSON, lo parsea en el hilo principal (bloqueando la UI durante ~2-5 segundos), y React re-renderiza el componente completo.

**La solución industrial:**
En `Exploration3DView.tsx`, la función `fetchBlockModel` debe intentar primero `GET /api/block-model?format=arrow&...`. Si la respuesta es `application/vnd.apache.arrow.stream`, deserializar con `apache-arrow`. Si falla, fallback al JSON endpoint.

---

### PROBLEMA B-08 — NaN Silencioso en Susceptibilidad

**Por qué existe:**
El modo "susceptibility" en el visor 3D fue diseñado asumiendo que los datos de susceptibilidad siempre están presentes. No hay un guard para el caso en que la corrida es gravity-only y `susceptibility_si` no existe en el Parquet.

**El riesgo real:**
El visor muestra colores garbage (valores NaN propagados a RGB) que visualmente pueden parecer datos reales. Un cliente no-técnico puede interpretar los colores arbitrarios como información geológica.

**La solución industrial:**
En `terraQuantumGeology.ts`, antes de calcular el colormap para susceptibilidad: si `dynChiRange === 0` o el valor es `NaN`, asignar `NEUTRAL_GRAY` y marcar `susceptibility_available = false`. En la UI, mostrar badge "Datos magnéticos no disponibles para esta corrida".

---

## FASE 5 — PLAN DE VALIDACIÓN CIENTÍFICA

### Gravimetría

**Test 1 — Esfera Analítica (Anti-Inverse-Crime)**
- Forward: fórmula analítica exacta de una esfera de radio R, densidad ρ, profundidad d
- Inversión: malla de inversión DIFERENTE a la malla forward (diferente nx, ny, nz, block_size)
- Criterio: celda de máxima densidad recuperada dentro de 1.5 bloques del centroide analítico
- Criterio: masa total recuperada dentro del 15% de la masa analítica

**Test 2 — Prisma de Plouff (Consistencia de Kernel)**
- Forward: fórmula de Plouff (1976) — misma base que `_nagy_prism_safe`
- Criterio: error relativo < 0.1% para todos los sensores

**Test 3 — Checkerboard Anti-Inverse-Crime**
- Forward: malla de resolución 2x la malla de inversión
- Patrón: tablero 2x2x2 bloques, contraste = 0.3 t/m³, ruido 2% RMS
- Criterio: correlación espacial > 0.7 con patrón original

**Test 4 — Li & Oldenburg Benchmark**
- Comparar contra los valores publicados en Li & Oldenburg (1998) Tabla 1
- Criterio: resultados dentro del 5% de los valores publicados

### Magnetometría

**Test 1 — Dipolo Magnético Analítico**
- Esfera de susceptibilidad χ en campo externo (I, D, F configurables)
- Criterio: error relativo < 5% en todos los sensores a distancia > 2R

**Test 2 — Warning de Remanencia**
- Crear escenario con TMI que solo puede explicarse con remanencia
- Criterio: el run report contiene `remanence_warning` con el texto correcto

### Inversión Conjunta

**Test 1 — Verificación de Acoplamiento Cross-Gradient**
- Forward: dos cuerpos co-ubicados, uno denso (gravedad) y uno susceptible (magnético)
- Criterio: SSIM entre rho y chi recuperados > 0.6 para inversión conjunta vs. < 0.3 para inversiones independientes

**Test 2 — Convergencia del Acoplamiento**
- Criterio: `joint_structural_score` aumenta monótonamente con las iteraciones

### DOI

**Test 1 — DOI Correcto vs Sintético**
- Correr dos inversiones con el mismo modelo pero lambdas diferentes (lambda1 = 10*lambda2)
- DOI = profundidad donde las dos soluciones divergen en más del 10%
- Criterio: DOI calculado por el código coincide con el DOI calculado manualmente dentro del 15%

### Incertidumbre

**Test 1 — Hutchinson Calibrado** (expande `test_uncertainty_hutchinson.py`)
- Criterio: estimador converge al estimador exacto dentro del 15% con N=100 vectores
- Criterio: la incertidumbre AUMENTA con la profundidad (propiedad física fundamental)

### Protocolo Anti-Inverse-Crime

**Regla 1 (Obligatoria, CI enforcement):** Ningún test puede usar la misma malla para forward e inversión.

**Regla 2 (Obligatoria):** El ruido en tests sintéticos se agrega ANTES de pasar observaciones al solver. Nivel de ruido >= 2% del RMS de la señal.

**Regla 3 (Recomendada):** Al menos un test usa un dataset público y publicado (por ejemplo, UBC-GIF datasets disponibles públicamente).

---

## FASE 6 — ANÁLISIS DE ESCALABILIDAD

### 200k Vóxeles — Estado Actual

**Bottlenecks actuales:**
- Kernel CSR: `(n_obs=500) × (n_active=200000)` en float64 = ~800MB en RAM
- JSON transport: 200k vóxeles × 8 campos × ~20 bytes/campo = ~32MB, 2-5 segundos de parse en browser
- Three.js InstancedMesh: 200k instancias manejables si buffers en GPU; bottleneck es la construcción en hilo principal

**Factibilidad:** Posible con el código actual pero degradado. Arrow (Hito 3) reduce transport a ~6MB.

### 500k Vóxeles — Qué se rompe

- CSR de `(500 × 500000)` = 2GB — borderline en servidor 16GB RAM
- `lsq_linear` con BVLS: inviable en O(n²) para 500k. Requiere TRF (Trust Region Reflective) que es O(n log n)
- Frontend: construcción del buffer en JS tarda > 1 segundo → WebWorker obligatorio

**Fix requerido:** WebWorker (Hito 6). Kernel matrix-free o compresión del kernel.

### 1M Vóxeles — Requisitos de Arquitectura

- **Kernel matrix-free obligatorio:** CSR para `(1000 × 1000000)` = 8GB. Inmanejable.
- **Workers asíncronos obligatorios:** Inversión > 5 minutos. Endpoint HTTP no puede estar bloqueado.
- **Frontend con tiling obligatorio:** No se pueden cargar 1M vóxeles en memoria del browser.

### 5M Vóxeles — Transformación Completa

- **OcTree mesh:** Malla regular no es eficiente. OcTree con refinamiento reduce celdas activas por factor 10x-100x.
- **GPU compute:** Kernel matrix-free como shader de cómputo. 100x más rápido que CPU para este tamaño.
- **Almacenamiento distribuido:** Parquets de ~400MB, S3/GCS con particionamiento.
- **Costo de infraestructura:** > 64GB RAM, > 4 horas de compute. Territorio de HPC o GPU cloud (A100, H100).

---

## FASE 7 — RIESGOS DE COMPLIANCE

### JORC 2012

**Qué viola actualmente el código:**
- `chat_api.py:49` — "estimación de recursos minerales" en system prompt
- Si `ENABLE_ECONOMIC_FEATURES=true` se activa accidentalmente, `pit_design_api` y `scenario_sweep_api` están disponibles con estimaciones de NPV sin disclaimer de Competent Person
- `estimate_grade_from_geophysics()` produce "estimación de grado" que, si se cita, puede parecer una estimación JORC

### NI 43-101 (Canadá)

**Aplicable a exploración en o para compañías listadas en TSX/TSX-V.**

**Fix requerido:** Todo reporte exportado debe tener disclaimer obligatoria de portada:
> "Este informe es una interpretación geofísica preliminar y no constituye una estimación de recursos minerales bajo NI 43-101 o JORC 2012. No ha sido revisado por un Qualified Person ni Competent Person."

### Chat Bypass

**Riesgo específico:** El chat endpoint es el bypass más peligroso porque:
1. Es conversacional — el usuario puede construir el contexto que lleva al LLM a dar estimaciones específicas
2. No tiene output validation
3. El system prompt declara el sistema como experto en lo que precisamente no puede reportar

**Estado actual:** Completamente sin guardrails (B-03 validado). Requiere fix inmediato (Hito 0).

### Economic Gated Modules

**Riesgo si se activan accidentalmente (`ENABLE_ECONOMIC_FEATURES=true`):**
- `pit_design_api.py`, `scenario_sweep_api.py`, `mine_method_api.py` con estimaciones NPV sin disclaimer

**Fix:** Agregar logging de auditoría obligatorio cuando se activa: `AUDIT: ENABLE_ECONOMIC_FEATURES=true activated at {timestamp}`.

### LLM Deprecation

**Riesgo:** Google retire `gemini-1.5-pro` sin preaviso suficiente. Falla total y simultánea de ambas funcionalidades LLM.

**Upgrade path:** `gemini-1.5-pro → gemini-2.0-flash → gemini-2.5-pro`

### Export Formats

**Gaps de interoperabilidad:**
- Sin exportación en formatos estándar: Geosoft GRD, Surfer GRD, VTK completo para Paraview
- Sin versión de schema en exports — exports anteriores pueden no ser legibles después de un schema change

---

## QUICK WINS (< 1 semana cada uno)

| QW | Tarea | Tiempo estimado | Impacto |
|---|---|---|---|
| QW-1 | Centralizar `GEMINI_MODEL_NAME` en `core/config.py`, default a `gemini-2.0-flash` | 2 horas | Previene falla total de LLM |
| QW-2 | Agregar `pandas>=2.0.0` a `requirements.txt` | 30 minutos | Elimina falla de despliegue |
| QW-3 | Corregir system prompt del chat, importar banned-words filter | 1 hora | Elimina riesgo JORC activo |
| QW-4 | Eliminar inyección de ruido gaussiano (`geophysics_service.py:1988-1994`) | 2 horas | Elimina el riesgo científico más grave |
| QW-5 | Guard NaN en susceptibilidad + badge "Sin datos magnéticos" | 2 horas | Elimina artefactos visuales para clientes |
| QW-6 | Activar Arrow en `Exploration3DView.tsx` (la infraestructura ya existe) | 4 horas | Reduce payload 40MB → 6MB |
| QW-7 | Disclaimer obligatorio JORC/NI-43-101 en todos los reportes exportados | 1 hora | Compliance básico en exports |

---

## RIESGOS CRÍTICOS (si no se resuelven)

**RIESGO 1 — Inyección de ruido contamina datos del cliente (B-01)**
Impacto: cualquier cliente con datos de alta precisión (misfit < 0.01%) recibe resultados basados en datos contaminados. La contaminación es silenciosa. Si lo descubren, es una pérdida de confianza irrecuperable y potencialmente una demanda.

**RIESGO 2 — Chat API viola JORC activamente (B-03)**
Impacto: si un cliente cita en un filing público una estimación producida por el chat, es una violación regulatoria. En jurisdicciones JORC (Australia, Sudáfrica) o NI 43-101 (Canadá), puede resultar en sanciones de mercado.

**RIESGO 3 — Gemini 1.5 Pro deprecation (B-04)**
Impacto: falla total y simultánea de ambas funcionalidades LLM sin preaviso. Mayor probabilidad de ocurrencia en los próximos 90 días.

**RIESGO 4 — Zero autenticación (B-11)**
Impacto: cualquier persona que conozca la URL del backend puede leer todos los proyectos y datos de todos los clientes. En exploración minera, los datos son confidenciales por naturaleza. Una fuga antes de una decisión de inversión puede tener consecuencias bajo leyes de insider trading.

**RIESGO 5 — Pandas no declarado rompe importación de gravedad (B-02)**
Impacto: en cualquier demo en un entorno limpio, la importación de datos de gravedad falla silenciosamente durante la demo, no en startup. El bug puede no reproducirse en el ambiente local del desarrollador.

---

## ESTIMACIÓN REALISTA DE ESFUERZO

| Alcance | Hitos | Semanas (1 desarrollador full-time) |
|---|---|---|
| Minimum Viable — Sin riesgos compliance activos, schema unificado, proveniencia básica, Arrow activado | 0-3 | 6-8 semanas |
| Science-Defensible — Suite de validación científica auditada por geofísico externo | 0-4 | 10-12 semanas |
| Demo-Ready Enterprise — Física correcta (bounds, topografía), presentable a inversores técnicos | 0-5 | 16-20 semanas |
| Full Industrial — Auth, escalabilidad a 500k vóxeles, workers asíncronos, LOD frontend | 0-7 | 32-48 semanas |

**Nota:** Si el desarrollador trabaja medio tiempo (estudios + proyecto), multiplicar los plazos por 1.5-2.0.

---

## ORDEN EXACTO DE EJECUCIÓN

1. **QW-3** — Corregir system prompt chat. Sin dependencias. Riesgo compliance activo. Ejecutar PRIMERO.
2. **QW-4** — Eliminar inyección de ruido. Sin dependencias. El riesgo científico más grave.
3. **QW-1** — Centralizar modelo Gemini. Sin dependencias. Previene falla de servicio total.
4. **QW-2** — Agregar pandas a requirements.txt. Sin dependencias. Elimina falla de despliegue.
5. **QW-5** — Guard NaN susceptibilidad. Sin dependencias frontend. Riesgo visual para clientes.
6. **QW-7** — Disclaimer en reportes exportados. Sin dependencias. Compliance básico.
7. **HITO 0 COMPLETO** — Verificar que QW-1 a QW-4 + QW-7 están en el mismo PR y pasan CI.
8. **HITO 1** — Contrato unificado de block model. Depende de Hito 0.
9. **QW-6** — Activar Arrow en Exploration3DView. Puede ejecutarse en paralelo con Hito 1. Requiere schema unificado para columnas consistentes.
10. **HITO 2** — Provenance y Run Manifest. Depende de Hito 1 (schema unificado para hashear Parquet consistente).
11. **HITO 3** — Transporte Arrow completo. Depende de Hito 1 y QW-6.
12. **HITO 4** — Suite de validación científica. Depende de Hito 2. Puede desarrollarse en paralelo con Hito 3.
13. **HITO 5** — Hardening del solver. **REQUIERE Hito 4 completado.** Los tests científicos DEBEN estar activos antes de cambiar el solver.
14. **HITO 6** — Escalabilidad y frontend industrial. Depende de Hito 3 y Hito 5.
15. **HITO 7** — Infraestructura enterprise. Depende de Hitos 0-5.

### Dependencias Críticas No Negociables

- **Hito 5 NO puede preceder a Hito 4.** Cambiar el solver sin tests científicos activos es ciego.
- **Hito 7 NO puede preceder a Hito 1.** Auth sin schema unificado añade complejidad a un sistema inestable.
- **QW-4 (eliminar ruido) debe ejecutarse antes de Hito 2 (proveniencia).** No tiene sentido hashear Parquets que pueden contener datos contaminados.
- **QW-3 (chat compliance) es independiente de todo lo demás y debe ser el primer commit.**

---

*Este documento fue generado mediante auditoría multi-agente de 15 agentes paralelos sobre el código real del repositorio. Todos los hallazgos están verificados con referencias a archivos y números de línea específicos. Fecha: 2026-05-31.*
