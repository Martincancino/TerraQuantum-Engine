# TERRAQUANTUM — VISIÓN INDUSTRIAL, ARQUITECTURA REAL Y ROADMAP MAESTRO

**Versión:** 1.1
**Fecha:** 2026-05-14 (v1.0) / actualizado 2026-05-14 (v1.1 — revisión externa)
**Estado del repo al momento de esta auditoría:** Post-Fase 6 / Pre-CORE-4
**Autor original (v1.0):** Claude Sonnet 4.6 (auditoría completa del código fuente — lectura de todos los archivos productivos de backend y frontend)
**Actualización v1.1:** Clasificación paralela de madurez infraestructural (PROTOTIPO → DESARROLLO → PRE-PRODUCCIÓN → PRODUCCIÓN) en Sección 8. Reglas inviolables 13-15 (versionado, tests antes de merge, logging estructurado en cambios nuevos) en Sección 14. Riesgos R11-R13 (tests automatizados, containerización, validación humana externa) en Sección 20.

---

> **Nota de uso:** Este documento es la fuente de verdad estratégica de TerraQuantum. Debe actualizarse cada vez que se complete una fase de desarrollo mayor. Toda IA o colaborador que trabaje en el repo debe leer este documento antes de proponer cambios de arquitectura.

---

## Índice

1. [Visión Industrial de TerraQuantum](#1-visión-industrial-de-terraquantum)
2. [Principio de Honestidad Técnica](#2-principio-de-honestidad-técnica)
3. [Producto Núcleo v1 — Flujo Central](#3-producto-núcleo-v1--flujo-central)
4. [Niveles de Realidad y Validación](#4-niveles-de-realidad-y-validación)
5. [Arquitectura Ideal (Meta)](#5-arquitectura-ideal-meta)
6. [Backend Actual — Estado Real del Repo](#6-backend-actual--estado-real-del-repo)
7. [Frontend Actual — Estado Real del Repo](#7-frontend-actual--estado-real-del-repo)
8. [Clasificación de Módulos](#8-clasificación-de-módulos)
9. [Estado de MS-x (Focusing Experimental)](#9-estado-de-ms-x-focusing-experimental)
10. [Estado de FMS](#10-estado-de-fms)
11. [Estado de MapeoIA / Satélite](#11-estado-de-mapeoía--satélite)
12. [Estado de Diseño Mina](#12-estado-de-diseño-mina)
13. [Estado de IA Local Futura](#13-estado-de-ia-local-futura)
14. [Reglas Técnicas Inviolables](#14-reglas-técnicas-inviolables)
15. [Reglas de Autonomía y Seguridad para IAs](#15-reglas-de-autonomía-y-seguridad-para-ias)
16. [Roadmap por Fases](#16-roadmap-por-fases)
17. [Próxima Prioridad Inmediata](#17-próxima-prioridad-inmediata)
18. [Preguntas Abiertas para el Dueño del Proyecto](#18-preguntas-abiertas-para-el-dueño-del-proyecto)
19. [Recomendaciones de Claude — Hallazgos de la Auditoría](#19-recomendaciones-de-claude--hallazgos-de-la-auditoría)
20. [Riesgos Críticos](#20-riesgos-críticos)

---

## 1. Visión Industrial de TerraQuantum

### Qué es TerraQuantum

TerraQuantum es un prototipo de plataforma industrial minera que conecta datos geofísicos crudos (gravimetría) con decisiones conceptuales de exploración y diseño de mina. Su ambición es integrar el flujo completo que hoy está fragmentado entre distintas herramientas comerciales costosas y poco transparentes:

```
Dato físico (CSV gravimétrico)
  → Validación y QA/QC
  → Inversión 3D (LSQR + Tikhonov)
  → Block model preliminar
  → Target de perforación
  → Decisión rajo vs. subterránea
  → Pit design conceptual (Lerchs-Grossmann)
  → Life of Mine + economía exploratoria
  → Reporte técnico trazable
```

Este flujo hoy existe parcialmente en el sistema. La visión completa incluye capas futuras de FMS real, datos satelitales, IA minera local y multiusuario.

### Qué NO es TerraQuantum hoy

TerraQuantum **no es** ni debe pretender ser:

- Software certificado para declaración de reservas bajo JORC, NI 43-101, SAMREC o equivalente
- Sistema de telemetría real con sensores conectados (FMS, MWD, GPS de flota)
- Reemplazo de perforación, geoquímica, geotecnia o metalurgia
- Plataforma de producción con uptime industrial y SLA
- Herramienta de valuación bancable (el NPV es conceptual sobre supuestos editables)

### Qué distingue a TerraQuantum de un demo genérico

TerraQuantum tiene varios elementos que lo separan de una demo de visualización:

- **Inversión geofísica real:** scipy sparse LSQR con regularización Tikhonov 3D (`exploration/gravimetry.py`), no heurísticas ni datos hardcodeados
- **Motor de pit design real:** Lerchs-Grossmann con PyMaxflow (`engine.py`), el estándar de la industria
- **Persistencia trazable:** cada corrida queda guardada por `project_id/run_id` con todos sus artefactos en Parquets y JSONs (`core/block_model_store.py`)
- **Suite de validación:** 15 scripts de validación y 17 scripts de demo, todos ejecutables desde `scripts/`
- **Focusing MS-x validado:** implementación de Portniaguine & Zhdanov (1999) con validación experimental contra ground truth sintético (`exploration/focusing.py` + `docs/TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md`)
- **Física de transporte real:** `Camiones/fms.py` implementa `TruckPhysics` (CAT 797F) y `DispatchEngineV2` con simulación de eventos discretos

### Visión final

TerraQuantum aspira a ser una plataforma industrial de minería que conecte:

1. Datos reales de exploración (gravimetría, magnetometría, geoquímica)
2. Validación de datos y QA/QC automático
3. Inversión geofísica 3D (LSQR + MS-x + métodos futuros)
4. Block model 3D trazable
5. Targeting y priorización de blancos de perforación
6. Decisión conceptual entre rajo abierto y subterránea
7. Diseño minero conceptual (Lerchs-Grossmann para rajo; método futuro para subterránea)
8. Economía exploratoria (LOM, NPV, escenarios de precio)
9. Reportes técnicos exportables con disclaimers y trazabilidad
10. FMS conectado a sensores reales (futuro)
11. Datos satelitales (GEE, Sentinel, Landsat — futuro)
12. IA minera local con agentes especializados (futuro)
13. Trazabilidad completa por `project_id/run_id` en todo el sistema

---

## 2. Principio de Honestidad Técnica

### Regla fundamental

Todo resultado de TerraQuantum debe presentarse con su nivel de certeza real. Si algo es sintético, debe decir sintético. Si algo es experimental, debe decir experimental. Si algo es conceptual, debe decir conceptual.

### Qué son realmente los campos del sistema

| Campo del sistema | Qué es realmente | Qué NO es |
|---|---|---|
| `density` | Contraste de densidad modelado por inversión LSQR (t/m³) | Densidad medida por sondaje DDH |
| `grade` | Proxy heurístico: `(density - 2.8) * 2.5 + 0.4` (% Cu aproximado) | Ley medida por análisis geoquímico |
| `probability` | Métrica de ajuste residual normalizada (fit quality) | Probabilidad estadística geológica |
| `targeting_score` | `density × probability`, ranking relativo de anomalías | Indicador validado de mineralización |
| `visual_score` | Score visual para coloreado del bloque (proporcional a anomalía) | Índice geológico certificado |
| `NPV` del LOM | NPV calculado sobre supuestos editables de precio/costo | Evaluación económica bancable |
| `tonnage` del bloque | `block_volume × density` (tonelaje calculado) | Tonelaje muestreado o estimado por kriging |
| FMS temperatures | Fórmula determinista sobre `avgCap` del plan LOM | Temperatura real de motor desde sensor |
| FMS truck status | Estado derivado del plan LOM (`"OPERATIVO_PLAN"`) | Telemetría GPS/CAN de camión real |
| MS-x `m_best` | Contraste de densidad en espacio de focusing (t/m³) | Densidad física absoluta |
| AnomalyEnvelope | Bounding box visual del percentil superior de anomalía | Isosuperficie calculada físicamente |
| Drill densidades (MwdLiveLink) | `predictedDensity + Math.sin(depth * 0.37) * 0.04` | Telemetría de sensor MWD |

### Glosario prohibido (sin validación de campo)

Las siguientes expresiones **no pueden usarse** en la UI, reportes ni documentación sin haber pasado por validación profesional externa:

- "mineral confirmado"
- "ley real"
- "reserva probada" / "reserva probable"
- "recurso medido" / "recurso indicado" / "recurso inferido"
- "NPV bancable"
- "plan minero operativo"
- "rentabilidad garantizada"
- "rajo final"
- "mineral económico" (sin sustento de ley medida)

### Clasificación oficial de niveles de certeza

El sistema usa los siguientes niveles en disclaimers, reportes y UI:

- **SINTÉTICO:** Datos generados algorítmicamente. No provienen de mediciones de campo.
- **EXPERIMENTAL:** Implementación validada en condiciones sintéticas con ground truth. No validado en datos reales.
- **CONCEPTUAL:** Algoritmo correcto, pero parametrización basada en supuestos exploratorios, no en muestreo.
- **DEMO:** Código con propósito de visualización o demostración. No debe usarse para decisiones técnicas.
- **PLACEHOLDER:** UI presente pero funcionalidad no implementada.
- **REAL (código validado):** Algoritmo validado contra múltiples casos de prueba. Listo para datos reales.
- **INDUSTRIAL:** Validado con datos reales de campo + auditoría externa. TerraQuantum aún no tiene ningún módulo en este nivel.

---

## 3. Producto Núcleo v1 — Flujo Central

### Descripción del flujo

El flujo central de TerraQuantum v1 existe completo en el código hoy. Cada paso tiene archivos responsables claramente identificados.

```
[1] CSV gravimétrico
     ↓ GravityCsvPreviewPanel.tsx
     ↓ /api/gravity-import/preview  →  preview + validación
     ↓ /api/gravity-import/invert   →  inversión completa
     ↓ gravity_import_service.py    →  parseo + formato v1
     ↓ geophysics_service.py        →  orquestación + QA/QC
     ↓ gravimetry.py                →  kernel CSR + LSQR + Tikhonov
     ↓ block_model.parquet          →  persistido en projects/{pid}/runs/{rid}/

[2] Block Model 3D
     ↓ /api/block-model?mode=exploration&limit=5000
     ↓ block_model_service.py       →  muestreo inteligente (45% anomalía, 30% densidad...)
     ↓ Scene3D.tsx                  →  InstancedMesh con filtros visuales

[3] Pit Design
     ↓ MineDesignView.tsx           →  requiere activeRun.status === "ready"
     ↓ /api/generate-pit
     ↓ pit_design_service.py        →  orquestación
     ↓ engine.py                    →  LerchsGrossmannEngine + PyMaxflow
     ↓ pit_mesh.py                  →  malla 3D con benches + export GLB
     ↓ scheduler.py                 →  ProductionScheduler (LOM + NPV)

[4] FMS conceptual
     ↓ FmsDashboard.tsx             →  flota derivada del lomMetrics store
     ↓ Camiones/fms.py              →  TruckPhysics + DispatchEngineV2 (en scheduler)
```

### Punto de entrada recomendado para demos

Dataset sintético validado: `scripts/demo/` con datos generados por `generate_tq_synthetic_copper_demo_v1.py`.

Perfil recomendado para demo industrial: `industrial_demo_v1` (32×20×32 voxeles, blockSize=25m, depth=250m, ~500 sensores sintéticos).

### Prerrequisito crítico para MineDesignView

`MineDesignView.tsx` tiene una guardia explícita:

```typescript
if (!activeRun.projectId || !activeRun.runId || activeRun.status !== "ready") {
  // muestra error: "Debes generar o cargar una corrida activa desde Figura 3D"
}
```

Esto significa que el usuario debe completar el flujo Paso 1+2 antes de poder usar el diseño de mina. **BUG ACTIVO:** `DatosView.tsx` no actualiza `activeRun` cuando carga una corrida histórica, bloqueando este flujo. Ver [Sección 17](#17-próxima-prioridad-inmediata).

---

## 4. Niveles de Realidad y Validación

### Escala de madurez del sistema

| Nivel | Definición | Criterio de ascenso |
|---|---|---|
| **NIVEL 0 — PLACEHOLDER** | UI presente, funcionalidad no implementada | — |
| **NIVEL 1 — SINTÉTICO** | Algoritmo implementado, validado contra datos generados con ground truth conocido | Tests passing, métricas de recovery medibles (PR-AUC, Top-K, IoU) |
| **NIVEL 2 — DATASET PÚBLICO** | Validado con datos públicos o académicos (Geoscience Australia, USGS, etc.) | Resultados reproducibles, comparables con literatura |
| **NIVEL 3 — DATOS REALES** | Validado con datos de campaña de campo real, aunque sea pequeña | QA/QC externo, comparación con resultado de perforación |
| **NIVEL 4 — VALIDACIÓN PROFESIONAL** | Revisado y aprobado por geofísico o geólogo senior externo | Reporte firmado por profesional competente |
| **NIVEL 5 — INDUSTRIAL** | Integrado en flujo operativo de una minera o consultora | Uptime, soporte, auditoría periódica |

### Clasificación actual de cada módulo

| Módulo | Nivel actual | Justificación |
|---|---|---|
| Inversión LSQR + Tikhonov 3D | NIVEL 1 | scipy sparse, validado contra casos sintéticos con ground truth conocido, 15+ tests |
| Importador CSV v1 | NIVEL 1 | Formato documentado, 15 tests de validación, flujo completo confirmado |
| Persistencia project/run | NIVEL 1 | Parquets + JSONs, exportación ZIP, trazabilidad completa |
| Pit Design LG + PyMaxflow | NIVEL 1 (algoritmo) / CONCEPTUAL (parámetros) | LG es correcto; grade/tonnage son proxies, no datos reales |
| Focusing MS-x IRLS | NIVEL 1 EXPERIMENTAL | Validado en 5 escenarios sintéticos, config fija, documentado en `TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md` |
| Scheduler LOM | CONCEPTUAL | DispatchEngineV2 usa física real; inputs (grade, tonnage) son proxies |
| FMS física (Camiones/) | CONCEPTUAL | Física CAT 797F real; sin telemetría GPS/MQTT |
| FmsDashboard | DEMO | Temperatura y status calculados, no desde sensor |
| AnomalyEnvelope | VISUAL DEMO | Bounding box percentil, no isosuperficie |
| MWD Live Link | DEMO | `Math.sin()` explícito |
| MapeoIA / NLP | NIVEL 0 PLACEHOLDER | Textarea + store, motor NLP no implementado |
| GEE / Satélite | NIVEL 0 PLACEHOLDER | Credenciales existen, cero código activo |

---

## 5. Arquitectura Ideal (Meta)

### Backend ideal

```
terraquantum-backend/
├── api/               # Routers FastAPI (thin layer, sin lógica)
├── core/              # config, tracing, block_model_store
├── exploration/       # Motores geofísicos (LSQR, MS-x, métodos futuros)
├── mining/            # LG engine, scheduler, FMS physics
├── data_ingestion/    # Importadores: CSV v1, Leapfrog, GOCAD, GSF, Excel
├── reporting/         # Generadores HTML/PDF con disclaimers
├── validation/        # QAQC, uncertainty quantification, benchmark
└── tests/             # pytest structurado, no scripts sueltos
```

### Frontend ideal

```
terraquantum-web/
├── store/             # Zustand: un solo activeRun como fuente de verdad
├── views/             # Vistas de alto nivel (Exploration3DView, MineDesignView, etc.)
├── panels/            # Paneles atómicos reutilizables
├── charts/            # Visualizaciones aisladas (sensitivity, LOM, etc.)
├── 3d/                # Scene3D y helpers Three.js
└── api/               # Proxies Next.js tipados hacia backend
```

### Estado global ideal

El estado global debe tener un único nodo central: `activeRun`. Todos los demás estados derivados (model, lomMetrics, fmsTrucks, pitModelUrl) deben derivarse o limpiarse cuando `activeRun` cambia.

```typescript
// Invariante ideal:
// store.model SIEMPRE proviene de store.activeRun.projectId + store.activeRun.runId
// store.lomMetrics SIEMPRE proviene de store.activeRun (corrida activa)
// store.fmsTrucks SIEMPRE se genera desde store.lomMetrics de la corrida activa

activeRun: {
  projectId: string,
  runId: string,
  source: "csv" | "history" | "synthetic" | "legacy",
  status: "idle" | "loading" | "ready" | "error",
  error: string | null,
  // Metadata completa de la corrida
  importMetadata, observationsSummary, reportSummary, focusing
}
```

**Estado actual:** `GravityCsvPreviewPanel.tsx` lo implementa correctamente. `DatosView.tsx` no — ver bug en [Sección 20, R1](#20-riesgos-críticos).

### Persistencia ideal futura

| Hoy | Ideal futuro (producción) |
|---|---|
| JSONs sueltos por carpeta | SQLite local con schema de proyectos |
| Parquets en filesystem local | S3 / MinIO para almacenamiento distribuido |
| Sin auth | Auth con JWT, roles (geólogo, analista, admin) |
| Sin versionado de modelos | Versionado de block models por run_id (ya existe) |

---

## 6. Backend Actual — Estado Real del Repo

### Stack tecnológico

- **Python:** 3.10+ con type hints en toda la codebase
- **FastAPI + Pydantic v2:** routers delgados, validación estricta de schemas
- **SciPy sparse + LSQR:** solver de inversión principal (scipy.sparse.linalg.lsqr)
- **NumPy:** álgebra lineal, grilla en `order='F'` (convenio Fortran, inviolable)
- **Polars:** lectura/escritura de Parquets (más rápido que Pandas para columnas)
- **PyMaxflow:** algoritmo Max-Flow/Min-Cut para Lerchs-Grossmann
- **Trimesh + Shapely:** construcción de malla 3D de pit con benches y rampas
- **Python-multipart:** upload de archivos CSV desde frontend

### Endpoints registrados (main.py)

| Endpoint | Router | Función |
|---|---|---|
| `GET /health` | system_api | Health check + versión |
| `GET /system-status` | system_api | Paths, config, existencia de archivos |
| `GET /project-runs` | system_api | Lista todos proyectos y corridas guardadas |
| `GET /project-run-detail` | system_api | Detalle completo de un run (metadata + status de archivos) |
| `GET /compare-runs` | system_api | Deltas entre dos corridas |
| `GET /export-run` | system_api | Descarga ZIP con todos los artefactos de un run |
| `POST /geophysics-invert` | geophysics_api | Inversión LSQR directa (legacy, sin CSV import) |
| `POST /geophysics-sensitivity-sweep` | geophysics_api | Barrido de lambda/alpha en paralelo |
| `GET /block-model` | block_model_api | Voxeles con muestreo inteligente |
| `POST /gravity-import/preview` | gravity_import_api | Parseo y validación CSV (sin inversión) |
| `POST /gravity-import/invert` | gravity_import_api | Import CSV + inversión en un paso (flujo principal) |
| `POST /generate` | pit_design_api | Lerchs-Grossmann + mesh + scheduling |
| `POST /scenario-sweep` | scenario_sweep_api | Variación de precio commodity para NPV curve |
| `GET /scenario-progress/{jobId}` | scenario_sweep_api | Status de sweep en paralelo |
| `GET /models/*` | static files | GLBs del pit design (servidos como archivos estáticos) |

### Estructura de persistencia

```
terraquantum-backend/data/projects/{project_id}/runs/{run_id}/
├── block_model.parquet               # Block model completo con densidad final
├── block_model_anomaly.parquet       # Contraste de densidad (anomalía)
├── block_model_focusing.parquet      # Solo si enable_focusing=True (MS-x)
├── inputs.json                       # Parámetros exactos de la inversión
├── observations.json                 # Observaciones gravimétricas de entrada
├── report.json                       # QA/QC, fit diagnostics, best_target
├── metrics.json                      # LOM metrics anuales (si pit design se ejecutó)
├── schedule.json                     # Schedule por año (si pit design se ejecutó)
├── source_gravity.csv                # CSV original importado (trazabilidad)
└── gravity_import_metadata.json      # Metadata del import (unidades, columnas, warnings)
```

### Servicios principales

- **`geophysics_service.py`** (~46 KB): orquestación completa de inversión (validación → grilla → QA/QC → LSQR → MS-x opcional → persistencia)
- **`gravity_import_service.py`** (~10 KB): parseo CSV v1 con validación estricta, soporte para mGal/µGal/m·s⁻²
- **`block_model_service.py`** (~10 KB): muestreo inteligente para respuestas de visualización (45% anomalía, 30% densidad alta, 15% probability, 10% distribución)
- **`pit_design_service.py`** (~18 KB): orquestación LG + mesh Trimesh + GLB export
- **`scenario_sweep_service.py`** (~6 KB): parallelización con `ProcessPoolExecutor` para barrido de precios

### Scripts de validación (15 archivos en `scripts/validation/`)

Cubren: QA/QC de observaciones, fit diagnostics, input validation, anomaly mask semantics, residual mapping, uncertainty diagnostics, sensitivity API, gravity CSV v1, import API, persistence, trace export, focusing module, geophysics focusing integration, project run flow, casos sintéticos.

### Scripts de demo (17 archivos en `scripts/demo/`)

Cubren: generación del dataset sintético copper demo v1, smoke test, hyperparameter sweep, adaptive threshold, cutoff sweep, depth ensemble, minimum support benchmark, nonnegativity benchmark, topological targeting, weighting experiments, adaptive threshold by architecture, MS-x space experiment, weighted candidate robustness suite.

### Problema documentado: fallback silencioso en pit_design_schema.py

```python
# terraquantum-backend/schemas/pit_design_schema.py
class PitRequest(BaseModel):
    file: str = "block_model_001.parquet"  # FALLBACK SILENCIOSO — RIESGO
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    ...
```

Si `project_id`/`run_id` no se resuelven a un archivo válido, el sistema silenciosamente usa el Parquet legacy. Esto puede producir un pit design sobre el modelo equivocado sin que el usuario lo sepa. Ver [Riesgo R2](#20-riesgos-críticos).

---

## 7. Frontend Actual — Estado Real del Repo

### Stack tecnológico

- **Next.js 15 (App Router):** routing basado en `app/`, server components donde aplica
- **React 19:** hooks, Suspense, concurrent features
- **TypeScript:** tipado estricto en toda la codebase
- **Three.js / @react-three/fiber:** visualización 3D con InstancedMesh para voxeles
- **Zustand:** estado global centralizado (~444 líneas en `useAppStore.ts`)
- **Tailwind CSS:** estilos utilitarios
- **Recharts:** gráficos de LOM, sensibilidad, NPV curve
- **@mediapipe/hands:** detección de gestos (experimental, no en flujo principal)
- **simplex-noise:** generación procedural para efectos visuales

### Vistas principales

| Vista | Componente | Estado real |
|---|---|---|
| Inicio | `HomeView.tsx` | Funcional — pipeline visual, CTAs |
| Figura 3D (exploración) | `Exploration3DView.tsx` | Funcional — orquesta CSV→inversión→3D, llama `setActiveRun` correctamente |
| Diseño Mina | `MineDesignView.tsx` | Funcional — requiere `activeRun.status === "ready"` como guardia |
| Datos (historial) | `DatosView.tsx` | Funcional pero monolítica (80+ KB). **BUG:** no llama `setActiveRun` |
| FMS | `FmsDashboard.tsx` | DEMO — derivado del plan LOM, sin telemetría real |
| Mapeo IA | `MapeoIAView.tsx` | PLACEHOLDER VACÍO — textarea + tags, sin backend NLP |

### Componentes críticos

**`Scene3D.tsx`** — Motor de visualización 3D
- InstancedMesh para miles de voxeles sin pérdida de performance
- Capas de color seleccionables: `modeled_density`, `anomaly_intensity`, `target_score`, `density_anomaly_score`
- Slicing visual en X/Y/Z (solo filtra la renderización, no modifica el modelo en el backend)
- AnomalyEnvelope: esfera wireframe alrededor del percentil superior (visual, no isosuperficie física)
- Lee `store.model` directamente — NO lee `store.activeRun` (desfase potencial entre modelo visible y corrida activa)

**`GravityCsvPreviewPanel.tsx`** — Importador CSV + inversión
- Flujo correcto: preview → selección de perfil → invert → `setActiveRun({projectId, runId, source:"csv", status:"ready"})` → `setModel()`
- Llama `setActiveRun` correctamente con todos los campos

**`DatosView.tsx`** — Historial de corridas (80+ KB, monolítico)
- `handleLoadRunModel`: llama `setModel(backendModel)` + `setView("figura 3d")` pero **OMITE** `setActiveRun`
- Consecuencia: MineDesignView queda bloqueado para corridas cargadas desde el historial

**`MwdLiveLink.tsx`** — Simulación de perforación
- Línea crítica: `liveDensitySynth = predictedDensity + Math.sin(currentDepthMeters * 0.37) * 0.04`
- Esta es la simulación de "dato en tiempo real" — es `Math.sin()`, no sensor

### Store Zustand (useAppStore.ts, ~444 líneas)

El store se divide en 8 grupos de estado:

1. **Core y vistas:** `activeRun`, `view`, `model` (voxeles 3D)
2. **Economía y LOM:** `lomMetrics`, `npvTotal`, `precioCu`, `costoTon`, `leyEstimada`
3. **UI 3D — toggles:** `showVoxels`, `show3D`, `showFloor`, `showMineDesign`, `gestureMode`
4. **UI 3D — capas y filtros:** `visualLayer`, `minTargetScore`, `minAnomalyIntensity`, `voxelOpacity`, `voxelScale`
5. **Cortes 3D:** `sliceX`, `sliceAxis`, `slicePosition`, `sliceThickness`, `showOnlySlice`
6. **Diseño Mina:** `mineDesignType`, `pitAngle`, `benchHeight`, `bermWidth`, `isDesignGenerated`, `pitModelUrl`
7. **FMS:** `fleet_size`, `isExtracting`, `selectedTruck`, `fmsTrucks[]`
8. **Geofísica y perforación:** `geoLat`, `geoLon`, `inputNIR`, `inputFe`, `inputDepth`, `heatmapData`, `bestTarget`, `bestVoxel`, `report`, `mwdStatus`, `liveDrillDepth`, `drillProfile`

### API routes (proxies Next.js hacia backend)

Todas las rutas en `app/api/` son proxies delgados hacia FastAPI. El cliente tipado está en `app/api/_lib/backend.ts`. No hay lógica de negocio en las rutas de Next.js.

### Responsabilidades mixtas en lib/terraquantum/geophysicsModel.ts

| Función | Tipo | Estado |
|---|---|---|
| `buildGeophysicsPayload()` | Construcción de payload para backend | ACEPTABLE — solo estructura datos |
| `buildGridConfig()` | Calcula nx×ny×nz según depth | ACEPTABLE — solo lógica de configuración |
| `buildHeatmapFromBlockModel()` | Extrae heatmap 2D | ACEPTABLE — transformación visual |
| `buildReportForFrontend()` | Mapea report del backend al formato frontend | ACEPTABLE |
| `findDemoHighlightVoxel()` | Scoring de voxeles en TypeScript | PROBLEMA — scoring en frontend, debe estar en backend |
| `generateDemoDrillProfile()` | Perfil densidad vs. profundidad con ruido senoidal | PROBLEMA — física simulada en TypeScript |

Ambas funciones problemáticas están marcadas `// DEMO ONLY` en el código y la fuente primaria del backend (`report.best_target`) tiene precedencia. Son tolerables mientras estén claramente etiquetadas.

---

## 8. Clasificación de Módulos

### Tabla consolidada de todos los módulos del sistema

| Módulo | Archivos clave | Clasificación | Justificación |
|---|---|---|---|
| **Inversión LSQR + Tikhonov 3D** | `exploration/gravimetry.py` | REAL (código validado) | scipy sparse, Tikhonov 3D, 15+ tests de validación, validado contra casos sintéticos con ground truth |
| **Importador CSV v1** | `services/gravity_import_service.py` | REAL | Formato documentado en `docs/TERRAQUANTUM_GRAVITY_CSV_V1.md`, 6 scripts de validación |
| **QA/QC de observaciones** | `services/geophysics_service.py` | REAL | Validación exhaustiva: NaN, duplicados, cobertura espacial, dynamic range |
| **Persistencia project/run** | `core/block_model_store.py`, `core/config.py` | REAL | Parquets + JSONs, trazabilidad completa, exportación ZIP |
| **Pit Design Lerchs-Grossmann** | `engine.py`, `services/pit_design_service.py` | REAL (algoritmo) / CONCEPTUAL (parámetros) | Algoritmo LG correcto con PyMaxflow; grade y tonnage son proxies heurísticos, no mediciones |
| **Malla 3D de pit (benches)** | `pit_mesh.py` | REAL (código) / CONCEPTUAL (geometría) | Trimesh + Shapely correcto; geometría sobre datos conceptuales |
| **Focusing MS-x IRLS** | `exploration/focusing.py` | EXPERIMENTAL APROBADO | Portniaguine & Zhdanov (1999), config fija validada, 5 escenarios sintéticos, documentado en `TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md` |
| **Scheduler LOM** | `scheduler.py` | CONCEPTUAL | `DispatchEngineV2` usa física real; inputs (grade, tonnage) son proxies heurísticos |
| **FMS física** | `Camiones/fms.py` | CONCEPTUAL | `TruckPhysics` (CAT 797F real), `DispatchEngineV2` (simulador eventos discretos real); sin telemetría GPS/MQTT |
| **FmsDashboard** | `componentes/FmsDashboard.tsx` | DEMO | Temperatura y status calculados desde LOM, no desde sensor real |
| **Visor 3D de voxeles** | `componentes/Scene3D.tsx` | REAL (visualización) | InstancedMesh correcto, slicing visual, filtros por layer |
| **AnomalyEnvelope** | `componentes/Scene3D.tsx` (sección envelope) | VISUAL DEMO | Bounding box del percentil superior de anomalía, no isosuperficie física |
| **MWD Live Link** | `componentes/huds/MwdLiveLink.tsx` | DEMO | `Math.sin()` explícito para "densidad en tiempo real", documentado como simulación |
| **MapeoIA / NLP** | `componentes/views/MapeoIAView.tsx` | PLACEHOLDER VACÍO | Textarea + store.extractedTags, motor NLP no implementado |
| **GEE / Satélite** | — (credenciales en `credenciales_gee.json`) | PLACEHOLDER (infraestructura) | Credenciales existen, cero código activo que las use |
| **Scenario Sweep** | `services/scenario_sweep_service.py` | REAL | Parallelización con ProcessPoolExecutor, NPV curve funcional |
| **Sensitivity Sweep** | `api/geophysics_api.py` | REAL | Barrido de lambda/alpha en paralelo, funcional |
| **Exportación de corridas** | `core/block_model_store.py:export_project_run_zip` | REAL | ZIP con todos los artefactos, funcional |
| **Compare Runs** | `core/block_model_store.py:compare_project_runs` | REAL | Deltas entre dos corridas, funcional |

### Clasificación paralela: madurez infraestructural

Adicional a la clasificación por nivel de certeza de datos (SINTÉTICO, EXPERIMENTAL, CONCEPTUAL, REAL, INDUSTRIAL), el proyecto introduce una clasificación paralela de **madurez infraestructural**, que mide la calidad del entorno de desarrollo, despliegue y operación independientemente de la calidad del cálculo físico:

- **PROTOTIPO:** Funciona en máquina del desarrollador. Sin tests automatizados. Sin CI/CD. Sin containerización. Logging por `print()`. Cualquier cambio puede romper algo sin que se detecte hasta uso manual.
- **DESARROLLO:** Tests automatizados pasando en CI/CD básico. Sistema containerizado y levantable con un comando. Logging estructurado en servicios críticos. Errores explícitos en endpoints públicos.
- **PRE-PRODUCCIÓN:** Lo anterior + seguridad mínima profesional (CORS explícito, rate limiting, `.env.example` documentado) + documentación completa (README ejecutivo, demo grabada) + validación externa firmada por mínimo 2 revisores independientes.
- **PRODUCCIÓN:** Lo anterior + monitoreo activo (métricas, dashboards) + alertas operativas + plan de respaldo y recuperación + SLA documentado + auditoría periódica.

**Estado actual de TerraQuantum:** nivel **PROTOTIPO**. Las fases CORE-QA-0.5, CORE-DOCKER, CORE-SEC y CORE-VALID-EXT (documentadas en `TERRAQUANTUM_EXECUTION_ROADMAP.md`) tienen como objetivo elevar el sistema a **PRE-PRODUCCIÓN**. Llegar a **PRODUCCIÓN** requiere además infraestructura de monitoreo y un cliente activo con SLA — eso es CORE-PROD-15.

Esta clasificación es ortogonal a la de certeza de datos: un módulo puede ser REAL en certeza y PROTOTIPO en madurez infraestructural simultáneamente. La inversión LSQR de TerraQuantum es ese caso hoy.

---

## 9. Estado de MS-x (Focusing Experimental)

### Status: EXPERIMENTAL APROBADO — no predeterminado en producción

La implementación de MS-x (Minimum Support IRLS) es el trabajo técnico más sofisticado del proyecto. Está completamente implementada en el backend, validada contra ground truth sintético, y lista para activarse con `enable_focusing=True`.

### Implementación

**Archivo:** `terraquantum-backend/exploration/focusing.py:run_focusing()`

**Algoritmo:** Minimum Support IRLS en espacio x, formulación Portniaguine & Zhdanov (1999).

**Configuración fija validada (NO modificar sin nueva fase experimental):**
```python
_BETA_MS = 0.01      # Factor de scaling de soporte mínimo
_EPS_0 = 0.80        # Epsilon inicial (cooldown exponencial)
_EPS_MIN = 0.12      # Epsilon mínimo
_MAX_IRLS = 10       # Máximo de iteraciones IRLS
_COOLING = 0.90      # Factor de cooling por iteración
_M_MAX = 1.60        # Densidad relativa máxima permitida
```

### Salida del algoritmo

`MSXResult` con:
- `m_best`: contraste de densidad en t/m³ (NO densidad absoluta, NO combinar con base sin documentarlo)
- `scale_status`: `"OK"` | `"SUPRIMIDA"` | `"INESTABLE"`
- `use_mode`: `"physical_mask_candidate"` | `"relative_targeting_score"`
- `safety_labels`: lista de etiquetas de seguridad

### Diagrama de decisión de scale_status

```
scale_status == "OK"
  → use_mode = "physical_mask_candidate"
  → Se puede usar como máscara física candidata

scale_status == "SUPRIMIDA"
  → use_mode = "relative_targeting_score"
  → El prior de soporte mínimo suprimió la escala
  → Usar solo como ranking relativo, no como densidad física

scale_status == "INESTABLE"
  → Spike de densidad > 1.5× valor base
  → NO usar para ningún propósito físico
  → Registrar en report y descartar esta iteración
```

### Por qué MS-x y no MS-m

MS-m (penalización directa de la norma de `m`) falló porque introduce un gradiente mayor en profundidad que se opone al depth weighting. MS-x opera en el espacio transformado `x = m / W_d^(1/2)`, donde `W_d` es la matriz de depth weighting. Esto garantiza presión uniforme en todos los voxeles independientemente de la profundidad.

**Esta distinción es fundamental y no debe modificarse sin una nueva fase experimental documentada.**

### lambda_mag en MS-x

`lambda_mag` se recibe como parámetro por consistencia de API pero su valor efectivo dentro de la iteración IRLS es 0. El prior de soporte mínimo (`focus_diag`) reemplaza al damping escalar del LSQR base. Esto está documentado en `config_summary["lambda_mag_used_in_msx"] = 0` del report.

### Activación desde la UI

Actualmente solo activable via payload directo en `/gravity-import/invert` con `enable_focusing=True`. No está expuesto como toggle visible en `GravityCsvPreviewPanel.tsx` para `industrial_demo_v1`. Ver [Recomendación 5](#19-recomendaciones-de-claude--hallazgos-de-la-auditoría) y [CORE-6](#roadmap-pendiente).

### Documentación de referencia

Ver `docs/TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md` para resultados completos de la fase experimental 1.7C.3L.

### Próxima fase

Validación con datos reales de campo (no sintéticos) — Fase propuesta: 1.7C.3M. Requiere planning separado.

---

## 10. Estado de FMS

### Status: CONCEPTUAL — física de transporte real, telemetría inexistente

El Fleet Management System de TerraQuantum tiene una arquitectura bicapa:

**Capa 1 — Física real (backend):**
- `Camiones/fms.py:TruckPhysics` — física mecánica del CAT 797F (payload 360t, potencia 2983kW, resistencia rodadura 2%, eficiencia mecánica 85%)
- `Camiones/fms.py:DispatchEngineV2` — simulador de eventos discretos con heapq, cola de prioridad por pala, fallo estocástico de pala (30% probabilidad, reparación 60-180 min)
- `_assign_best_shovel()` — dispatch económico: minimiza `fuel_cost + maintenance_cost + travel_time + queue_estimate`
- Este componente es llamado por `scheduler.py:ProductionScheduler._simulate_annual_capacity()` en cada año de LOM

**Capa 2 — Dashboard demo (frontend):**
- `FmsDashboard.tsx` genera flota basada en `store.lomMetrics` (plan LOM)
- Temperatura de motor: `tempBase = 85 + Math.min((avgCap / count) * 0.015, 20)` — calculada, no sensor
- Status: `"OPERATIVO_PLAN"` si hay LOM, `"ESPERANDO_LOM"` si no
- Sin GPS, sin MQTT, sin API de telemetría, sin sensor real

### Dependencia FMS → LOM

El dashboard FMS solo se "activa" cuando `store.lomMetrics.length > 0`. Si el usuario no ha ejecutado `MineDesignView`, el FMS muestra flota en standby. Esto es arquitectónicamente correcto (FMS depende del plan), pero la UI no lo explica bien al usuario.

### Camino a FMS real

Para que FMS pase de DEMO a REAL requiere:

1. MQTT broker o API de dispatch del sistema real de la mina
2. WebSocket en FastAPI que reciba eventos en tiempo real
3. Modelo de datos de `TruckEvent` con GPS, payload, ciclo, tiempo de espera, disponibilidad
4. Actualización de Zustand desde WebSocket
5. Rediseño de `FmsDashboard.tsx` para consumir datos reales vs. datos LOM

**Estimación de trabajo:** 3-6 meses. No iniciar sin acceso a datos reales de ciclo.

---

## 11. Estado de MapeoIA / Satélite

### Status: PLACEHOLDER VACÍO

`MapeoIAView.tsx` existe como vista del sistema pero no tiene funcionalidad implementada.

### Lo que existe hoy

- `MapeoIAView.tsx`: textarea para "Diario de Terreno" + panel "Vectores NLP Extraídos" (sin datos)
- `store.geologistNote: string` — nota del geólogo guardada en estado
- `store.extractedTags: string[]` — array vacío en el store, nunca se puebla automáticamente
- `store.geoLat`, `store.geoLon` — coordenadas geográficas, usadas en `buildGeophysicsPayload()` para el payload de inversión
- `app/api/_lib/backend.ts` tiene constantes de lat/lon de demo para Chile

### Lo que NO existe

- Ningún llamado a API de NLP o LLM desde `MapeoIAView.tsx`
- No hay integración activa con Google Earth Engine (las credenciales en `credenciales_gee.json` existen pero ningún código las usa en el flujo activo)
- No hay capas de satélite (NDVI, NDWI, bandas multiespectrales, mosaicos)
- No hay parser de texto geológico (minerales, alteraciones, estructuras)
- El único uso real de `geologistNote` es pasarlo como contexto textual en `buildReportForFrontend()` al campo `notasTerreno`, donde va al reporte sin procesarse

### Visión futura

La visión es transformar este módulo en un sistema de satélite/territorio que:
- Consulte datos satelitales públicos (Sentinel-2, Landsat-8) o privados usando lat/lon
- Genere capas: NDVI, NDWI, relaciones de bandas para detección de alteración hidrotermal
- Produzca heatmaps de probabilidad geológica superficial
- Use GEE como backend de procesamiento satelital

El NLP geológico podría ser:
- **Corto plazo:** API Claude/GPT con prompt de vocabulario geológico
- **Largo plazo:** modelo NLP local (spaCy + vocabulario geológico español/técnico) sin dependencia de API externa

### Recomendación

Ver [Recomendación 6 implícita en Sección 19](#19-recomendaciones-de-claude--hallazgos-de-la-auditoría) sobre si renombrar, ocultar o eliminar esta vista antes de una demo a terceros.

---

## 12. Estado de Diseño Mina

### Status: REAL (algoritmo) / CONCEPTUAL (parametrización)

### Lo que es real

- `engine.py:LerchsGrossmannEngine.build_sparse_graph()` — grafo de precedencia correcto con ángulos geotécnicos por dominio (no escalar)
- `optimize_with_maxflow()` — PyMaxflow estándar, Max-Flow/Min-Cut, extrae envolvente óptima de pit
- `pit_mesh.py:build_benched_mesh()` — malla 3D con benches y rampas, exportación GLB con Trimesh
- `scheduler.py:ProductionScheduler` — LOM real con física de transporte por año, NPV con discount_rate
- Guardia en `MineDesignView.tsx` — requiere `activeRun.status === "ready"`, bloqueante

### Lo que es conceptual

- `grade` del block model: `(density - 2.8) * 2.5 + 0.4` — proxy heurístico, no ley medida
- `tonnage = block_volume × density` — tonelaje calculado, no muestreado ni estimado por kriging
- LOM asume 100% de recuperación metalúrgica, sin dilución, sin cut-off variable
- Parámetros económicos por defecto (precio Cu, costo minado, costo proceso) son supuestos editables por el usuario
- Strip ratio no está explícitamente calculado ni presentado como métrica

### Advertencias en la UI

`MineDesignView.tsx` tiene el disclaimer:
> "Escenario preliminar basado en modelo de densidad/anomalía. No representa diseño final de mina."

Este disclaimer existe como texto plano. No es un modal bloqueante que el usuario deba aceptar.

### Problema crítico: fallback silencioso

Ver [Sección 6](#6-backend-actual--estado-real-del-repo) y [Riesgo R2](#20-riesgos-críticos). Si `project_id`/`run_id` no resuelven a un Parquet válido, el pit design silenciosamente usa `data/block_model_001.parquet`. El usuario puede ver un pit design correcto en la UI pero calculado sobre el modelo equivocado.

### Rajo vs. subterránea

Actualmente el sistema solo genera rajo abierto. La decisión conceptual entre rajo y subterránea no está implementada. Variables relevantes para implementarla en el futuro:

- Profundidad del cuerpo (disponible desde block model)
- Tonelaje estimado (disponible, proxy)
- Geometría e inclinación (disponible desde block model)
- Strip ratio implícito (derivable del LG)
- Ángulo de pit y profundidad máxima económica (disponible desde LOM)
- Incertidumbre del modelo (disponible desde report)
- Ley estimada (disponible, proxy)

---

## 13. Estado de IA Local Futura

Esta sección documenta la visión de largo plazo para componentes de IA que no existen hoy en el sistema. Ninguno de estos componentes está implementado. Se documentan como referencia para planificación futura.

### Componente 1 — Copiloto Geológico (NLP de campo)

**Función:** Extraer entidades geológicas estructuradas de texto libre del geólogo de campo.

- **Entrada:** Nota de terreno en español técnico geológico (texto libre)
- **Procesamiento:** LLM API (Claude/GPT) con prompt de vocabulario geológico + extracción de entidades
- **Salida:** `extractedTags[]` estructurados: minerales (calcopirita, bornita), alteraciones (propilítica, potásica, fílica), estructuras (falla NE, contacto intrusivo), indicadores de tipología (pórfido Cu-Mo, IOCG)
- **Pre-requisito técnico:** Dataset de ejemplos de notas geológicas para few-shot prompting

### Componente 2 — Interpretación asistida del modelo gravimétrico

**Función:** Sugerir tipología de yacimiento a partir del modelo 3D + contexto geológico.

- **Entrada:** Resultado de inversión LSQR (densidades, forma, profundidad) + tags geológicos de campo
- **Salida:** Hipótesis de tipología (IOCG, pórfido Cu-Mo, VMS, skarn) con probabilidades relativas y justificación
- **Pre-requisito técnico:** Dataset de pares (modelo gravimétrico, tipología geológica confirmada)
- **Nivel de certeza:** EXPERIMENTAL hasta tener al menos 50 casos validados

### Componente 3 — Análisis de imágenes satelitales (GEE)

**Función:** Generar capas de alteración superficial y anomalías litológicas desde satélite.

- **Entrada:** Coordenadas lat/lon del área de interés
- **Procesamiento:** Google Earth Engine API (credenciales ya existen en `credenciales_gee.json`)
- **Capas propuestas:** NDVI, NDWI, Ratio de bandas Sentinel-2 para hidrotermal (B11/B8A, B12/B11), Landsat-8 PC1
- **Salida:** Heatmaps GeoJSON/PNG superpuestos sobre la vista principal

### Componente 4 — Optimización automática de parámetros de inversión

**Función:** Seleccionar `lambda_mag`, `alpha_spatial`, `nx`, `ny`, `nz`, `depth` óptimos para un dataset CSV dado.

- **Algoritmo candidato:** Bayesian Optimization (Optuna, BoTorch) sobre el espacio de hiperparámetros
- **Función objetivo:** PR-AUC contra ground truth (si disponible) o resolución de inversión como proxy
- **Pre-requisito técnico:** Ground truth sintético o perforaciones de validación

### Arquitectura conceptual de IA integrada

```
Backend (física y datos)
  ↓ calcula inversión, pit design, LOM
  ↓ guarda en projects/{pid}/runs/{rid}/

Base de datos de corridas (hoy: archivos; futuro: SQLite/PostgreSQL)
  ↓ accesible por ID, proyecto, fecha, parámetros

Agentes de IA (futuro)
  ├── Agente Geólogo: lee corridas + notas de campo → hipótesis geológicas
  ├── Agente Economista: lee LOM → análisis de sensibilidad automático
  ├── Agente QA/QC: lee report.json → detecta inconsistencias, sugiere acciones
  └── Agente Reportero: genera HTML/PDF técnico con disclaimers automáticos

Frontend (visualización)
  ↓ consume resultados de backend y agentes
  ↓ muestra con disclaimers apropiados por nivel de certeza
```

**Principio:** Los agentes razonan sobre datos reales del sistema. No reemplazan la física del backend. No inventan datos.

---

## 14. Reglas Técnicas Inviolables

Estas reglas están basadas en lecciones aprendidas del código, bugs resueltos, y decisiones de arquitectura documentadas. Violarlas puede producir resultados incorrectos silenciosos.

**Regla 1 — Orden de memoria Fortran es inviolable**
Toda la grilla 3D usa `order='F'` (Fortran, column-major). Esto aplica a `exploration/gravimetry.py`, `engine.py`, y cualquier reshape de arrays 3D. Nunca mezclar con `order='C'`. El bug histórico de `axis 0 index X exceeds matrix dimension Y` se solucionó al respetar esta convención consistentemente.

**Regla 2 — Frontend no calcula física productiva**
`lib/terraquantum/geophysicsModel.ts` puede estructurar payloads para el backend. No puede implementar nuevas fórmulas físicas o geológicas. Los únicos helpers de TypeScript tolerados son construcciones de payload y transformaciones visuales. `findDemoHighlightVoxel` y `generateDemoDrillProfile` están en zona gris — tolerables solo si:
- Están marcados `// DEMO ONLY` explícitamente en el código
- El backend (`report.best_target`) provee la fuente primaria y tiene precedencia

**Regla 3 — MS-x no se modifica sin nueva fase experimental**
Los hiperparámetros `_BETA_MS`, `_EPS_0`, `_EPS_MIN`, `_COOLING`, `_M_MAX` en `exploration/focusing.py` fueron fijados en la fase experimental 1.7C.3L.8. No modificar sin: (a) nueva hipótesis documentada, (b) validación contra los mismos 5 casos sintéticos, (c) comparación de métricas contra la configuración base.

**Regla 4 — activeRun es la fuente de verdad de la corrida activa**
Cualquier módulo del frontend que cargue un modelo en el store DEBE llamar `setActiveRun({ projectId, runId, source, status: "ready" })`. Sin esto, `MineDesignView` queda bloqueado y el sistema pierde trazabilidad de qué corrida se está visualizando.

**Regla 5 — El fallback legacy debe ser explícito, no silencioso**
Si `project_id`/`run_id` no resuelven a un archivo válido en `pit_design_service.py`, el sistema debe retornar HTTP 400 con mensaje explicativo. No debe silenciosamente usar `block_model_001.parquet`. Un pit design sobre el modelo equivocado es más peligroso que un error visible.

**Regla 6 — Disclaimers en módulos económicos son obligatorios**
Todo módulo que presente NPV, grade, LOM, reservas estimadas o métricas económicas DEBE tener disclaimer visible. En el próximo ciclo, estos disclaimers deben convertirse en modales bloqueantes que el usuario acepte al primer uso. Son parte del criterio de aceptación de cada feature económica.

**Regla 7 — No duplicar lógica Python en TypeScript**
Si se necesita un cálculo que requiere datos del block model o datos geológicos, crear un endpoint en el backend. No reimplementar en TypeScript. La única excepción son transformaciones puramente visuales (colores, posiciones de cámara, rangos de sliders).

**Regla 8 — Los tests corren antes de cualquier commit a código de inversión o pit**
Antes de tocar `exploration/`, `services/`, `engine.py`, `scheduler.py`:
```bash
python -m compileall api services scripts exploration
python scripts/validation/test_project_run_flow.py
npm run lint  # en terraquantum-web
```

**Regla 9 — No tocar credenciales_gee.json ni .env.local**
Estos archivos están excluidos del repo por `.gitignore`. Si se necesita agregar una nueva variable de entorno, documentar en `.env.example` y agregar la instrucción en `README_TERRAQUANTUM_LOCAL.md`.

**Regla 10 — Grilla máxima: nx × ny × nz ≤ 200,000 voxeles**
Arriba de este límite el endpoint retorna `422 Unprocessable Entity`. No subir el límite sin análisis de memoria (la matriz kernel CSR es `n_sensors × n_voxels`, con 500 sensores y 200K voxeles = 100M elementos × float64 = ~800 MB si densa; la versión sparse es manejable).

**Regla 11 — Inversión requiere mínimo 10 observaciones**
Validado en `geophysics_service.py:validate_geophysics_input()`. Con menos de 10 observaciones el sistema está subdeterminado en la mayoría de las configuraciones de grilla. Este mínimo es inviolable.

**Regla 12 — Todo código nuevo usa modo project_run, no legacy**
El Parquet legacy `data/block_model_001.parquet` existe por compatibilidad histórica. Cualquier nuevo endpoint, servicio o flujo debe usar `core/block_model_store.py:get_run_block_model_reference(project_id, run_id)`.

**Regla 13 — Versionado obligatorio**
Cada cierre de fase mayor (CORE-FLOW-1, CORE-DATA-2, CORE-ECON-8, etc.) genera una nueva versión semántica (v0.X.Y), una entrada en `CHANGELOG.md`, y un tag de Git. Sin esto, no se considera que la fase está cerrada. La razón es trazabilidad: con versiones es posible afirmar "esta versión funcionaba, esta no" y revertir si una regresión llega a producción. Sin versiones, cada cierre de fase se diluye en el flujo continuo de commits.

**Regla 14 — Tests antes de merge**
Cualquier cambio en código de `exploration/`, `services/` o `engine.py` requiere tests automatizados (pytest) que cubran al menos el camino exitoso del cambio. Sin tests, el cambio no se mergea. Esta regla solo aplica a partir del cierre de CORE-QA-0.5 (cuando exista la infraestructura pytest). Antes de eso, los scripts de validación manuales en `scripts/validation/` cumplen el rol equivalente pero con menor garantía.

**Regla 15 — Logging estructurado en cambios nuevos**
Cualquier código nuevo en el backend usa `structlog`, no `print()`. Esta regla aplica desde el cierre de CORE-QA-0.5. Código legacy con `print()` se migra cuando se toca para otra razón (corrección de bug, refactor planificado), no como tarea separada — esto evita refactors masivos y mantiene los cambios pequeños y aislados.

---

## 15. Reglas de Autonomía y Seguridad para IAs

Estas reglas aplican a Claude Code, Gemini, ChatGPT o cualquier IA que trabaje en el repositorio.

**Regla 1 — Nunca backend y frontend en la misma iteración**
A menos que el prompt lo exija explícitamente y esté justificado. El riesgo de introducir inconsistencias entre API y cliente aumenta cuando se tocan ambos lados sin revisión intermediaria.

**Regla 2 — El nivel de riesgo define el modelo IA a usar**
- Bajo riesgo (UI, textos, disclaimers, documentación): Claude Sonnet / Gemini Pro Low
- Riesgo medio (APIs, refactors locales, nuevas rutas): Claude Sonnet / GPT-4o
- Alto riesgo (física, inversión, activeRun, store global, schemas, economía): Claude Opus / Gemini Pro High

**Regla 3 — Confirmar antes de tocar archivos > 300 líneas**
Archivos como `DatosView.tsx` (~2000 líneas), `geophysics_service.py` (~1500 líneas), `useAppStore.ts` (~444 líneas) requieren confirmación explícita del dueño antes de modificar.

**Regla 4 — No instalar dependencias sin permiso expreso**
Ni en `package.json`, ni en `requirements.txt`. Proponer la dependencia y esperar confirmación.

**Regla 5 — No hacer refactors globales**
Los cambios deben ser pequeños, aislados y por fases. Un refactor de toda la lógica de persistencia o del store de Zustand es un cambio de alto riesgo que requiere planning previo.

**Regla 6 — No inventar física en TypeScript**
Si una IA propone implementar un cálculo geofísico, geotécnico o económico en el frontend, la respuesta correcta es proponer un endpoint backend. La IA debe detectar esto proactivamente y no esperar que el dueño lo corrija.

**Regla 7 — No modificar data/, tmp/, public/models/ sin permiso**
Estos directorios contienen datos de corridas, archivos temporales y modelos GLB. Su modificación puede invalidar resultados guardados.

**Regla 8 — No modificar scripts .bat sin permiso**
Los scripts de inicio y smoke test son parte del flujo operacional. Cambiarlos sin permiso puede romper el entorno de desarrollo.

**Regla 9 — Formato obligatorio de respuesta al terminar una tarea**
1. Archivos modificados (con ruta)
2. Resumen de los cambios
3. Qué NO se tocó (límites respetados)
4. Comandos ejecutados o sugeridos de validación
5. Riesgos pendientes

**Regla 10 — En duda, preguntar antes de ejecutar**
El costo de parar y preguntar es bajo. El costo de un cambio incorrecto en la física o en el store global puede ser muy alto (resultados incorrectos silenciosos, deuda técnica difícil de rastrear).

---

## 16. Roadmap por Fases

### Fases completadas (mapeadas a nomenclatura CORE)

| Fase interna | Nombre CORE | Descripción | Estado |
|---|---|---|---|
| Fase 1 | CORE-0 | Estabilización funcional: FastAPI + Next.js operativos, inversión básica, scripts de inicio | ✅ COMPLETA |
| Fase 3 | CORE-1 | Persistencia trazable: system project_id/run_id con Parquets + JSONs | ✅ COMPLETA |
| Fase 5 | CORE-2 | Importador CSV v1: formato documentado, preview + inversión, trazabilidad de source_gravity.csv | ✅ COMPLETA |
| Fase 6 | CORE-3 | Madurez semántica: disclaimers, separación física/heurística, glosario prohibido, limpieza de lenguaje demo/conceptual | ✅ COMPLETA |
| Fase 1.7C.3L | CORE-EXP-1 | MS-x focusing validado experimentalmente: config fija, 5 casos sintéticos, safety labels | ✅ COMPLETA |

### Fases pendientes (en orden de prioridad calculada por esta auditoría)

**CORE-4 — Corrección de trazabilidad (CRÍTICO, BUG)**

Prioridad máxima. Dos cambios pequeños que desbloquean el flujo DatosView → MineDesignView.

- **CORE-4A:** `terraquantum-web/componentes/DatosView.tsx` — `handleLoadRunModel` debe llamar `setActiveRun({ projectId, runId, source: "history", status: "ready", ... })` después de `setModel()`. (~30 líneas de cambio)
- **CORE-4B:** `terraquantum-backend/schemas/pit_design_schema.py` — Eliminar el fallback silencioso a `block_model_001.parquet`. Si no hay `project_id`/`run_id` válidos, retornar HTTP 400 explícito. (1-5 líneas)

Riesgo: BAJO | Impacto: ALTO

---

**CORE-5 — Disclaimers bloqueantes (IMPORTANTE)**

Protección comercial y honestidad técnica reforzada.

- Modal en primer acceso a `MineDesignView.tsx` con lista de supuestos (grade es proxy, NPV es conceptual, LOM asume 100% recovery)
- Banner persistente en `FmsDashboard.tsx` que no se puede cerrar ("SIMULACIÓN — NO ES TELEMETRÍA REAL")
- Posiblemente: `localStorage` flag para no mostrar el modal después de la primera aceptación

Riesgo: BAJO | Impacto: MEDIO

---

**CORE-6 — MS-x expuesto en UI como opción (GEOFÍSICA)**

El activo técnico más valioso del proyecto está oculto detrás de un parámetro de API.

- Toggle visible de `enable_focusing` en `GravityCsvPreviewPanel.tsx` para el perfil `industrial_demo_v1`
- Exposición de `scale_status`, `use_mode`, `safety_labels` en `DatosView.tsx` (el panel ya existe, solo falta conectar los datos)
- Disclaimer asociado: "MS-x EXPERIMENTAL — resultado no es densidad física, es score de targeting relativo"

Riesgo: BAJO | Impacto: ALTO (diferenciador técnico visible)

---

**CORE-7 — Refactor DatosView (DEUDA TÉCNICA)**

`DatosView.tsx` tiene ~2000 líneas y mezcla lista de corridas, diagnósticos geofísicos, panel económico, sensitivity sweep, compare runs y focusing panel.

- Dividir en componentes atómicos:
  - `<ProjectRunList />` — lista y selección de corridas
  - `<RunDiagnosticsPanel />` — QA/QC, fit, uncertainty
  - `<RunEconomicPanel />` — NPV, LOM, métricas económicas
  - `<RunFocusingPanel />` — MS-x scale_status, safety_labels
  - `<RunComparePanel />` — deltas entre dos corridas
- El refactor no debe cambiar funcionalidad, solo organización

Riesgo: MEDIO (componente central del sistema) | Impacto: ALTO (mantenibilidad)

---

**CORE-8 — Reportes técnicos exportables (VALOR DEMO)**

Generar HTML/PDF técnico al final de una corrida, con disclaimers automáticos y trazabilidad.

- **Backend:** `terraquantum-backend/reporting/` (nuevo módulo)
  - `report_geophysics.py` — reporte HTML de inversión + QA/QC + fit diagnostics
  - `report_economic.py` — reporte HTML de LOM + NPV + supuestos explícitos
  - Jinja2 para templates + WeasyPrint o pdfkit para PDF
- **Endpoint:** `GET /export-report?project_id=X&run_id=Y&format=html|pdf`
- **Frontend:** botón "Descargar Reporte Técnico" en `DatosView.tsx` y `MineDesignView.tsx`

Riesgo: BAJO | Impacto: ALTO (valor para demos y validación externa)

---

**CORE-9 — Clasificación conceptual rajo vs. subterránea (GEOTECNIA)**

Primera versión conceptual de la decisión metodológica central de diseño minero.

- **Backend:** lógica de scoring multi-criterio en `services/mine_method_service.py` (nuevo):
  - Variables de entrada: profundidad del cuerpo, tonelaje estimado, geometría (thickness/plunge), strip ratio implícito del LG, ángulo de pit, incertidumbre del modelo
  - Output: `{ recommendation: "open_pit" | "underground" | "needs_more_data", confidence: float, rationale: { ... } }`
- **Frontend:** nueva sección en `MineDesignView.tsx` con visualización de criterios + disclaimer de certeza

Riesgo: MEDIO | Impacto: ALTO (decisión de negocio clave del flujo minero)

---

**CORE-10 — Datos reales o dataset público/académico (VALIDACIÓN)**

Primer paso hacia el NIVEL 2 de la escala de madurez.

- Identificar un dataset público de gravimetría con resultados de perforación conocidos (Geoscience Australia, USGS, academia)
- Ejecutar el flujo CSV → inversión → block model → comparación con perforaciones reales
- Documentar métricas de recuperación en condiciones reales
- Si hay acceso a datos privados de campaña: firmar NDA, validar en NIVEL 3

Riesgo: ALTO (impacto directo en confiabilidad del motor) | Impacto: MUY ALTO (credibilidad industrial)

---

**CORE-11 — Satélite/Territorio (reemplaza MapeoIA)**

Transformar el placeholder vacío de MapeoIA en un módulo real de análisis territorial.

- Activar integración con Google Earth Engine (`credenciales_gee.json` ya existe)
- Capas: NDVI, NDWI, Ratio B12/B11 Sentinel-2 para detección de alteración
- Requiere refactorizar `MapeoIAView.tsx` completamente o crear una nueva vista `TerritorioView.tsx`

Riesgo: MEDIO | Impacto: ALTO (diferenciador visual en demos)

---

**CORE-12 — FMS real con sensores**

Solo cuando exista:
- Acceso a datos de ciclo reales (GPS, payload, tiempos, disponibilidad de flota)
- API de dispatch (MQTT/Modbus) o exportación desde sistema existente (Jigsaw, Modular Mining, etc.)

No iniciar sin datos reales. El código de física (`Camiones/fms.py`) ya está preparado para recibir parámetros reales.

---

**CORE-13 — IA local minera y agentes**

Ver [Sección 13](#13-estado-de-ia-local-futura). Requiere CORE-8 (reportes) y CORE-10 (datos reales) como prerequisitos.

---

**CORE-14 — Escalabilidad, multiusuario, deployment**

- SQLite local → PostgreSQL con schema de proyectos y usuarios
- Auth con JWT + roles (geólogo, analista, admin, read-only)
- Docker Compose para deployment reproducible
- CI/CD básico (GitHub Actions)

---

## 17. Próxima Prioridad Inmediata

### CORE-4: Corrección de trazabilidad — dos cambios aislados, bajo riesgo, alto impacto

#### CORE-4A: Fix DatosView.tsx

**Archivo:** `terraquantum-web/componentes/DatosView.tsx`

**Función a modificar:** `handleLoadRunModel` (aproximadamente línea 489)

**Cambio requerido:** Agregar llamada a `setActiveRun` después de `setModel()`:

```typescript
// AGREGAR después de setModel(backendModel) y setView("figura 3d"):
setActiveRun({
  projectId,
  runId,
  source: "history",
  status: "ready",
  error: null,
  importMetadata: null,
  observationsSummary: null,
  reportSummary: null,
  focusing: null,
});
```

**Por qué esto desbloquea el flujo:** `MineDesignView.tsx` valida `activeRun.status === "ready"` antes de habilitar el botón "Generar escenario conceptual". Sin este fix, el 100% de las corridas cargadas desde el historial quedan bloqueadas en MineDesignView.

**Precaución:** Verificar que `ActiveRunState` en `useAppStore.ts` acepta `source: "history"`. Si el tipo solo tiene `"csv" | "synthetic" | "legacy"`, agregar `"history"` al union type.

#### CORE-4B: Fix pit_design_schema.py

**Archivo:** `terraquantum-backend/schemas/pit_design_schema.py`

**Cambio requerido:** Eliminar el default del campo `file` o hacer que `pit_design_service.py` retorne error explícito si `project_id`/`run_id` no resuelven:

```python
# Antes (fallback silencioso):
file: str = "block_model_001.parquet"

# Después (explícito — opción A: sin default):
file: Optional[str] = None

# Y en pit_design_service.py validar:
if not request.project_id and not request.run_id and not request.file:
    raise HTTPException(status_code=400, detail="Debe proveer project_id/run_id o file explícito")
```

#### Secuencia de validación post-fix

```bash
# Backend
python -m compileall api services schemas
python scripts/validation/test_project_run_flow.py

# Frontend
npm run lint  # en terraquantum-web/

# Test manual
# 1. Ejecutar una inversión desde GravityCsvPreviewPanel → guardar corrida
# 2. Ir a DatosView → cargar la corrida guardada
# 3. Ir a MineDesignView → verificar que el botón "Generar escenario" está habilitado
# 4. Generar pit → verificar que usa el modelo correcto (no block_model_001.parquet)
```

---

## 18. Preguntas Abiertas para el Dueño del Proyecto

Estas preguntas deben responderse antes de implementar las fases CORE-5 en adelante, ya que afectan decisiones de diseño.

**P1 — MapeoIA:** ¿Planeas implementar NLP geológico real en los próximos 3 meses? Si la respuesta es no, debería ocultarse la vista en la navegación o reemplazarse por un placeholder más honesto ("Módulo en desarrollo — disponible en una versión futura").

**P2 — Datos reales:** ¿Tienes acceso a datos reales de gravimetría (aunque sean de una campaña pequeña o dataset académico público)? Incluso 50-100 puntos de datos reales elevarían la credibilidad del sistema de NIVEL 1 a NIVEL 2.

**P3 — Disclaimers bloqueantes:** ¿Estás de acuerdo en que los disclaimers económicos (NPV, grade, LOM) deben ser modales que el usuario deba aceptar en el primer uso? Esto es especialmente importante si hay demos a terceros (geólogos, ingenieros, inversionistas).

**P4 — Deploy:** ¿La plataforma permanece local (Windows, localhost) o hay planes de staging en cloud (Vercel, Railway, AWS) en los próximos 6 meses? La respuesta afecta decisiones de SQLite vs. PostgreSQL, paths locales vs. S3, y cómo manejar las credenciales GEE.

**P5 — MS-x en UI:** ¿Quieres activar MS-x como toggle visible en `GravityCsvPreviewPanel.tsx` para el perfil `industrial_demo_v1`? Requiere exponer `scale_status` y `safety_labels` en la UI de resultados.

**P6 — DatosView refactor:** ¿Tienes tiempo para el refactor de DatosView (CORE-7) en el próximo ciclo, o prefieres hacer solo el fix de `setActiveRun` (CORE-4A) y posponer el refactor?

**P7 — Credenciales GEE:** ¿Las credenciales en `credenciales_gee.json` son válidas y activas? Si no, ¿hay plan de renovarlas para la fase CORE-11 de satélite/territorio?

**P8 — MWD Live Link:** ¿El simulador de perforación MWD debe mantenerse como demo permanente (y ser más honesto en su etiquetado) o hay intención de conectarlo a telemetría real en algún momento? Esto define si se mantiene el código actual o se rediseña completamente.

---

## 19. Recomendaciones de Claude — Hallazgos de la Auditoría

Estos hallazgos surgieron de la lectura completa del código fuente. Se presentan como recomendaciones concretas, no como críticas.

### Hallazgo 1 — El bug de DatosView tiene consecuencias en cascada

El problema no es solo que MineDesignView queda bloqueado. Hay un segundo efecto: si el usuario carga un modelo desde DatosView y luego hace clic en "Figura 3D", `Exploration3DView` puede ejecutar su `resetExplorationState()` al inicializar, que incluye `setModel(null)`. El usuario pierde el modelo que cargó desde DatosView. La corrección de CORE-4A resuelve ambos efectos porque una vez que `activeRun` está correctamente seteado, los componentes pueden verificar el estado antes de limpiar.

**Recomendación:** CORE-4A debe ser la primera tarea implementada. No agregar nuevas features hasta que este bug esté corregido.

### Hallazgo 2 — geophysicsModel.ts tiene responsabilidades mixtas que son distinguibles

No todo `geophysicsModel.ts` viola la regla "frontend no calcula física". Las funciones de construcción de payload (`buildGeophysicsPayload`, `buildGridConfig`, `buildHeatmapFromBlockModel`) son helpers de transformación de datos, aceptables en el frontend. Las funciones problemáticas son `findDemoHighlightVoxel` y `generateDemoDrillProfile`, que implementan scoring y física simplificada en TypeScript.

**Recomendación:** No refactorizar todo el archivo — solo mover `findDemoHighlightVoxel` y `generateDemoDrillProfile` a un archivo explícitamente llamado `demoPreviews.ts` y marcarlos `// DEMO ONLY — no usar en flujo productivo`. Esto hace la separación visible sin romper nada.

### Hallazgo 3 — La arquitectura de activeRun está bien diseñada

El tipo `ActiveRunState` en `useAppStore.ts` es correcto. `GravityCsvPreviewPanel.tsx` lo usa bien. Solo `DatosView.tsx` falla en usarlo. Esto no requiere rediseño arquitectónico — solo aplicar consistentemente el patrón existente en el único componente que lo viola.

**Recomendación:** No proponer un "rediseño del store" para resolver este problema. La solución es quirúrgica (CORE-4A) y el diseño existente es el correcto.

### Hallazgo 4 — Los disclaimers textuales no son suficientes para demos a terceros

Los disclaimers existen en el código. Los encontré en al menos 7 componentes distintos. El problema es que son texto plano o badges pequeños que un usuario no técnico puede ignorar o no leer. En una demo ante ingenieros senior, geólogos consultores o potenciales inversionistas, un usuario que saca conclusiones sobre reservas o NPV bancable desde la pantalla sin haber leído el disclaimer es un riesgo real.

**Recomendación:** CORE-5 (modal bloqueante en primer acceso a MineDesignView) debe implementarse antes de cualquier demo externa. El modal puede usar `localStorage` para no repetirse, pero debe ser explícito la primera vez.

### Hallazgo 5 — MS-x es el activo técnico más valioso y está subutilizado en la UI

La fase experimental 1.7C.3L.8 fue el trabajo más riguroso del proyecto (validación contra ground truth sintético, config fija, safety labels robustos). Sin embargo, un usuario que usa la UI estándar nunca ve MS-x porque:
1. El toggle `enable_focusing` no está expuesto en `GravityCsvPreviewPanel.tsx`
2. Los resultados de focusing (`scale_status`, `use_mode`, `safety_labels`) existen en el store pero no se muestran visualmente

**Recomendación:** CORE-6 tiene un impacto de credibilidad técnica desproporcionado a su esfuerzo de implementación. Es un toggle + 3 campos de texto adicionales en componentes que ya existen.

### Hallazgo 6 — El stack Python del backend es sólido

El uso de Polars (no Pandas) para Parquets es una buena decisión de performance. SciPy sparse + LSQR es la elección correcta para inversión 3D a escala de prototipo. PyMaxflow para LG es la implementación de referencia del algoritmo. No hay deuda técnica mayor en el backend matemático. El único riesgo concreto es el fallback silencioso de `pit_design_schema.py` (CORE-4B).

**Recomendación:** No proponer reescrituras del backend matemático. Está bien. El foco debe estar en:
1. Corregir el fallback silencioso (CORE-4B)
2. Agregar el módulo de reportes (CORE-8)
3. Cuando haya datos reales, validar que el motor LSQR se comporta como se espera

---

## 20. Riesgos Críticos

| # | Riesgo | Severidad | Probabilidad de ocurrencia | Archivos involucrados |
|---|---|---|---|---|
| **R1** | `DatosView.tsx:handleLoadRunModel` no llama `setActiveRun` → MineDesignView bloqueado para el 100% de las corridas cargadas desde el historial | ALTA | **CONFIRMADA** (bug en código) | `componentes/DatosView.tsx:~489`, `store/useAppStore.ts:setActiveRun` |
| **R2** | `pit_design_schema.py` tiene fallback silencioso a `block_model_001.parquet` → pit design puede calcularse sobre el modelo equivocado sin que el usuario lo sepa | ALTA | LATENTE (se activa cuando project_id/run_id no resuelven) | `schemas/pit_design_schema.py`, `services/pit_design_service.py` |
| **R3** | NPV, grade y LOM presentados sin modal bloqueante → sobrepromesa a terceros en demos o evaluaciones externas | MEDIA-ALTA | POSIBLE en demos | `views/MineDesignView.tsx`, `FmsDashboard.tsx`, `DatosView.tsx` |
| **R4** | `findDemoHighlightVoxel` y `generateDemoDrillProfile` en TypeScript → viola la regla "frontend no calcula física productiva" | MEDIA | BAJA (marcados `// DEMO ONLY`, backend tiene precedencia) | `lib/terraquantum/geophysicsModel.ts` |
| **R5** | `Scene3D.tsx` lee `store.model` directamente (no `store.activeRun`) → desfase visual entre modelo visible y corrida activa cuando el usuario navega fuera del flujo CSV | MEDIA | POSIBLE (navegación no lineal) | `componentes/Scene3D.tsx`, `store/useAppStore.ts` |
| **R6** | `AnomalyEnvelope` es un bounding box del percentil superior, no una isosuperficie calculada físicamente → un geólogo puede malinterpretar la forma del cuerpo anómalo | MEDIA | POSIBLE en demos técnicas | `componentes/Scene3D.tsx` (sección AnomalyEnvelope) |
| **R7** | `MapeoIAView.tsx` es placeholder vacío con UI funcional y sin aviso claro de que no está implementado → usuario puede esperar funcionalidad de NLP inexistente | BAJA-MEDIA | PROBABLE en demos a terceros | `componentes/views/MapeoIAView.tsx` |
| **R8** | `MwdLiveLink.tsx` usa `Math.sin()` para "densidad en tiempo real" → dato de sensor 100% sintético. Los disclaimers existen pero no son prominentes | BAJA | BAJA (disclaimers existen) | `componentes/huds/MwdLiveLink.tsx`, `componentes/Scene3D.tsx` |
| **R9** | MS-x IRLS no ha sido validado con datos reales de campo → su comportamiento fuera de las condiciones sintéticas es desconocido | MEDIA | DESCONOCIDA (no hay datos reales aún) | `exploration/focusing.py` |
| **R10** | Perfil `quick_check` produce grilla 4×4×4 = 64 voxeles → modelo sin resolución espacial útil, pero apariencia de resultado real si el usuario no entiende los parámetros | BAJA | BAJA (documentado en `GravityCsvPreviewPanel.tsx:INVERSION_PROFILES.quick_check`) | `componentes/GravityCsvPreviewPanel.tsx` |
| **R11** | Sin tests automatizados, cualquier cambio puede romper funcionalidad existente sin que se detecte hasta uso manual | ALTA | LATENTE (alta probabilidad de manifestarse al refactorizar DatosView en FASE 2) | Todo el backend y frontend |
| **R12** | Sin containerización, no se puede demostrar el sistema a profesores universitarios o en faena minera sin instalación manual de Python + Node + dependencias (Polars, PyMaxflow) | MEDIA-ALTA | CONFIRMADA (impacta plan de validación externa CORE-VALID-EXT) | Repositorio completo |
| **R13** | Sin validación humana externa por geofísico/ingeniero de minas, el sistema no tiene credibilidad técnica frente a clientes potenciales o decisores en mineras | MUY ALTA | CONFIRMADA (es prerequisito de ventas y de pilotos profesionales) | Sistema completo |

---

## Documentos de Referencia

Los siguientes documentos en `docs/` proveen detalle técnico sobre aspectos específicos del sistema:

| Documento | Contenido | Estado |
|---|---|---|
| `TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md` | Validación completa de MS-x: casos sintéticos, métricas, config fija, safety labels | Aprobado (2026-05-12) |
| `TERRAQUANTUM_FULL_SYSTEM_AUDIT.md` | Auditoría de arquitectura completa: deuda técnica, trazabilidad, mezcla demo/real | Referencia (2026-05-09) |
| `TERRAQUANTUM_CODE_AUDIT.md` | Auditoría profunda del código fuente | Referencia (2026-05-08) |
| `TERRAQUANTUM_SYNTHETIC_COPPER_DEMO_V1.md` | Especificación del dataset sintético de demostración (1089 estaciones, 20.480 vóxeles) | Activo |
| `TERRAQUANTUM_PHASE_6_SEMANTIC_MATURITY_CLOSURE.md` | Cierre de madurez semántica: disclaimers, separación física/heurística | Completado |
| `TERRAQUANTUM_PHASE_6_MODEL_SEPARATION_AUDIT.md` | Auditoría de separación backend/frontend | Completado |
| `TERRAQUANTUM_PHASE_6_5_MINING_ECONOMIC_SEMANTIC_AUDIT.md` | Auditoría de semántica económica minera | Completado |
| `TERRAQUANTUM_PHASE_5_GRAVITY_IMPORT_FLOW.md` | Flujo de importación CSV v1 | Completado |
| `TERRAQUANTUM_GRAVITY_CSV_V1.md` | Especificación del formato CSV v1 para datos gravimétricos | Activo — usar como referencia para importación |
| `GRAVITY_DATA_FORMATS_RESEARCH.md` | Investigación sobre formatos de datos gravimétricos en la industria | Referencia |

---

*Fin del documento. Próxima actualización recomendada al completar CORE-4.*

---

## Historial de versiones

- **v1.0 (2026-05-14):** Versión inicial. Visión industrial, principio de honestidad técnica, arquitectura real, clasificación de módulos por nivel de certeza, 12 reglas inviolables, 10 riesgos críticos, roadmap CORE-0 a CORE-14.
- **v1.1 (2026-05-14):** Revisión externa por consultor. Sección 8: clasificación paralela de madurez infraestructural (PROTOTIPO/DESARROLLO/PRE-PRODUCCIÓN/PRODUCCIÓN), ortogonal a la clasificación por certeza de datos. Sección 14: tres reglas inviolables nuevas (Regla 13 — versionado obligatorio, Regla 14 — tests antes de merge, Regla 15 — logging estructurado en cambios nuevos). Sección 20: tres riesgos críticos nuevos (R11 — sin tests automatizados, R12 — sin containerización, R13 — sin validación humana externa).
