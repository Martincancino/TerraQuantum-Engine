# TERRAQUANTUM — BIBLIA TÉCNICA DE REALIDAD INDUSTRIAL

**Versión:** 1.1  
**Fecha:** 2026-05-19  
**Autor:** Claude Code — Auditoría completa de arquitectura, código fuente y documentación existente  
**Estado:** DOCUMENTO MAESTRO ACTIVO — ACTUALIZADO POST-C1/C5  
**Documentos fuente consultados:** TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md (v1.1), TERRAQUANTUM_DEFINITIVE_EXECUTION_PLAN.md, TERRAQUANTUM_EXECUTION_ROADMAP.md (V2), TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md, TERRAQUANTUM_HVC_VALIDATION_V1.md, TERRAQUANTUM_SECURITY_BASELINE.md, TERRAQUANTUM_MSX_FOCUSING_VALIDATION.md, código fuente completo de backend y frontend  
**Actualización v1.1 basada en:** Auditoría de código fuente post-C1/C2/C3/C4/C5 — 2026-05-19 — verificación directa de `report_generator.py`, `block_model_service.py`, `Scene3D.tsx`, `BottomControls.tsx`, `GeoDashboard.tsx`, `ProjectRunList.tsx`, `useAppStore.ts`, `pitDesignModel.ts`, `system_api.py`, `docker-compose.yml`

---

> **Propósito de este documento:**  
> Esta biblia define con exactitud brutal qué es TerraQuantum, qué no es, qué existe en el código, qué falta, qué está mal, qué es peligroso y qué camino seguir para convertirlo en un prototipo técnico serio y honesto. No es un documento motivacional. Es una guía de realidad.

---

# 0. Estado Real Actualizado Post-C1/C5

Esta sección reemplaza el estado de apertura de la versión 1.0 y registra con precisión qué cambió y qué no cambió desde la primera auditoría. Todo lo aquí afirmado fue verificado directamente en el código fuente el 2026-05-19.

---

## 0.1 Cerrado / avanzado

| Fase | Estado | Qué resolvió | Qué no resuelve |
|------|--------|--------------|-----------------|
| **C1-BE** — Saneamiento semántico backend | COMPLETADO — verificado en `geophysics_service.py`, `report.json` de corridas reales | Agregó `priority_class`, `relative_target_score`, `model_reliability_level`. Lógica que impide que HVC con favorability=12.2/BAJA produzca DRILL semánticamente. | Los aliases legacy (`recommendation`, `probability`, `risk_level`) siguen presentes en el JSON persistido para compatibilidad. Requieren auditoría de consumo en futuros flujos. |
| **C1-REP** — Saneamiento semántico del reporte HTML | COMPLETADO — verificado en `report_generator.py` | El HTML ya no muestra "Recomendación: DRILL", "Riesgo: LOW" ni "Probabilidad" como probabilidad real. Muestra "Clase de Prioridad Relativa", "Score Relativo del Target" con nota explícita de que no es probabilidad de mineralización. | Los aliases internos en JSON persistido no se eliminaron; solo se ocultaron en la presentación. Si un consumidor futuro lee los JSON directamente, puede encontrar campos legacy. |
| **C2-FE** — Saneamiento semántico frontend | COMPLETADO — verificado en `componentes/`: ningún archivo devuelve "Probabilidad IA", "PERFORAR AQUÍ", "Recomendación exploratoria", "Risk Level", "HIGH/MEDIUM/LOW RISK", "Probabilidad de Éxito" en búsqueda directa | UI usa "Score relativo", "Clase de prioridad relativa", "Confiabilidad técnica", "Prioridad relativa". | Algunos tipos TypeScript internos como `GeoReportInfo` en `useAppStore.ts` aún definen campos `recommendation`, `risk_level` como propiedades del objeto (compatibilidad con JSON legacy). No son visibles en UI pero existen en tipos. |
| **C3-REP** — Gate económico/minero en reporte HTML | COMPLETADO — verificado en `report_generator.py:_check_economic_gate` y `_mining_section_html` | Cuando favorability < 25 o overall_level=LOW o quality_label=BAJA, el HTML muestra "Evaluación Económica/Minera No Habilitada" con motivos. No muestra NPV/tonelajes/LOM/strip ratio como métricas principales cuando el gate falla. | El gate se basa en thresholds fijos (score < 25). No existe revisión profesional de si esos thresholds son los correctos. |
| **C3-FE** — Gate económico/minero frontend | COMPLETADO — verificado en `useAppStore.ts` (`favorabilityScore`, `favorabilityLevel`, `setFavorabilityGate`), `pitDesignModel.ts` (`evaluateEconomicGate`) | Store tiene estado de gate. `pitDesignModel.ts` implementa la lógica de bloqueo. DatosView, MineDesignView, PitMetricsPanel y MineExecutiveSummary deberían bloquear o degradar cuando el gate falla. | No se auditó si todos los componentes que consumen métricas económicas realmente leen el gate state en todos los flujos posibles. Requiere QA completo de flujo HVC. |
| **C4** — Infraestructura y documentación | COMPLETADO con riesgo menor — verificado en `docker-compose.yml`, `system_api.py` | `.gitignore` raíz creado; `/health` existe y responde; `docker-compose.yml` tiene `TERRAQUANTUM_HOST`/`TERRAQUANTUM_PORT` explícitos, CORS, healthcheck de backend, frontend depende de backend healthy; READMEs backend/frontend/raíz/Docker/local actualizados. | Docker runtime no fue validado en ejecución real porque Docker Desktop no estaba corriendo en el momento del QA. El C4-QA fue PASS con riesgo menor por esa razón. |
| **C5.1** — Voxel trace | COMPLETADO — verificado en `block_model_service.py:build_voxel_trace_metadata`, `GeoDashboard.tsx` | `/block-model` expone `total_voxels`, `stored_voxels`, `anomaly_voxels`, `returned_voxels`, `mode`. GeoDashboard muestra "Modelo completo de inversión", "Modelo almacenado", "Anomalías detectadas", "Cargados en UI", "Modo de datos". `ProjectRunList.tsx` llama `setShow3D(true)` y `setActiveRun` al cargar desde historial — bug de carga histórica corregido. | El voxel trace es conteo de filas, no trazabilidad de coordenadas geográficas. La transparencia es numérica, no espacial. |
| **C5.2** — Selector de modo de datos 3D | COMPLETADO — verificado en `block_model_service.py` (modes: `exploration`, `full`, `anomaly`, `economic`) | UI tiene selector de modo. QA confirmó: exploration=5000 voxels, full=20480, anomaly=1813 en corrida HVC real. | El modo `economic` existe en backend pero usa `grade > 0.3` como cutoff fijo heurístico; no está conectado al gate de favorabilidad. |
| **C5.3 + C5.4** — Host volume conceptual + controles estáticos | COMPLETADO — verificado en `Scene3D.tsx:HostVolume`, `useAppStore.ts` (`showHostVolume`, `hostVolumeOpacity`), `BottomControls.tsx`, `GeoDashboard.tsx` | Store tiene toggle y opacidad. Scene3D tiene HostVolume conceptual con `BoxGeometry`. BottomControls tiene toggle "Vol. Subsuelo" y slider de opacidad. GeoDashboard muestra nota "volumen conceptual del subsuelo — no representa litología medida". Grupo geológico es estático (sin `<Float>` de @react-three/drei). | El HostVolume es una `BoxGeometry` plana, no un volumen que siga la topografía DEM. Esto es correcto para esta fase conceptual, pero debe clarificarse visualmente ante cualquier audiencia técnica. |

---

## 0.2 Sigue abierto

Las correcciones anteriores son reales y significativas. **No convierten el sistema en industrial.** Los siguientes problemas siguen sin resolver:

| Problema | Severidad | Por qué importa | Fase recomendada |
|----------|-----------|-----------------|------------------|
| Verdad espacial real — footprint completo | **CRÍTICA** | Sin footprint real, el modelo no tiene ubicación geográfica defensable. Ningún geofísico puede validar la posición de la anomalía. | R1 |
| Bbox/polígono/4 esquinas del survey | **CRÍTICA** | Un lat/lon central no define el área del survey. Los voxels no tienen coordenadas absolutas asignadas. | R1 |
| CRS completo — UTM zone obligatorio | **CRÍTICA** | UTM sin zona es ambiguo. El sistema no puede hacer transformación correcta sin zona. | R1 |
| Relación matemática CSV → footprint → DEM → voxels | **CRÍTICA** | La cadena completa de georreferenciación no existe. Los voxels no tienen lat/lon absoluta calculada. | R1 |
| DEM co-registrado con footprint real | **ALTA** | El terreno DEM se carga sobre punto central, no sobre el footprint real del survey. Posición visual incorrecta. | R3 |
| `voxel_absolute_elevation = surface_elevation_at_xy - depth_below_surface` | **ALTA** | La profundidad de voxels no está referenciada al DEM local real. No hay elevaciones absolutas en el parquet. | R3 |
| Host volume siguiendo topografía DEM | **ALTA** | El HostVolume es un BoxGeometry plano. Un volumen real debería recortarse por la topografía. | R3/R4 |
| Terreno extendido real por footprint/margen desde GEE | **ALTA** | El terreno GEE se carga sobre punto central, no sobre el bounding box real del survey más margen. | R3 |
| Slices profesionales como visualización default | **ALTA** | Los cubos individuales no son visualización profesional. Un geofísico evalúa secciones, no cubos de color. | R4 |
| Colorbar técnica con valores de densidad | **ALTA** | Sin leyenda cuantitativa, el modelo no es interpretable técnicamente. | R4 |
| Coordenadas del cursor y profundidad real | **ALTA** | Al pasar el cursor sobre un voxel, no se muestran coordenadas ni profundidad en sistema de referencia real. | R4 |
| Validación sintética con ground truth (PR-AUC, Top-K, IoU, F1) | **ALTA** | El solver nunca se validó cuantitativamente contra una solución conocida. No se puede afirmar precisión. | R7 |
| Validación profesional externa | **CRÍTICA** | Sin un geofísico o ingeniero de minas que valide el enfoque, el sistema no tiene credibilidad externa. | R8/R11 |
| Multi-dato mínimo (magnetometría, geología superficial, densidades medidas) | **MEDIA** | Con solo gravimetría, la ambigüedad equivalente es inherente. | R6 |
| Frontend final limpio (sin controles experimentales visibles) | **MEDIA** | El frontend actual mezcla módulos reales con demos sin aviso prominente suficiente. | R9 |
| Ocultar o rediseñar FMS, pit design, mine design, economía, MapeoIA | **ALTA** | Estos módulos son conceptuales o vacíos. Si están visibles en demo externa sin aviso, dañan la credibilidad. | R9 |
| Aliases legacy (`recommendation`, `probability`, `risk_level`) en JSON persistido | **MEDIA** | Siguen presentes en JSONs guardados para compatibilidad. Si se exponen a consumidores externos, son semánticamente peligrosos. | R0 pendiente |

---

## 0.3 Próxima fase real

La próxima fase no es más UI cosmética ni más módulos mineros.

**La próxima fase es R1 — Contrato espacial real.**

> Objetivo: que cada proyecto TerraQuantum tenga un objeto `project_footprint` explícito con tipo, CRS, esquinas y nivel de confianza declarado. Que el sistema deje de fingir georreferenciación cuando solo tiene un lat/lon central.

Tareas concretas de R1:
- Crear schema `ProjectFootprint` en backend
- Modificar `coordinate_transform_service.py` para emitir footprint con tipo y confianza
- Crear endpoint `GET /project-footprint`
- Agregar campo `georef_confidence` a `report.json`
- Requerir zona UTM cuando el CSV tiene coordenadas UTM
- Mostrar `footprint_type` y `georef_confidence` en frontend con badge de color (NONE=rojo, LOW=naranja, MEDIUM=amarillo, HIGH=verde)

**Hasta que R1 no esté completo, el sistema no puede afirmar que la anomalía está en ningún lugar geográfico específico.**

---

## Índice

1. [Resumen Ejecutivo Brutal](#1-resumen-ejecutivo-brutal)
2. [Nueva Identidad Técnica de TerraQuantum](#2-nueva-identidad-técnica-de-terraquantum)
3. [Estado Actual Real del Sistema](#3-estado-actual-real-del-sistema)
4. [Problema Central: Verdad Espacial](#4-problema-central-verdad-espacial)
5. [Contrato Industrial de Datos de Entrada](#5-contrato-industrial-de-datos-de-entrada)
6. [Qué Puede y Qué No Puede Hacer la Gravimetría](#6-qué-puede-y-qué-no-puede-hacer-la-gravimetría)
7. [Requisitos del Modelo 3D Industrial](#7-requisitos-del-modelo-3d-industrial)
8. [Arquitectura Geoespacial Objetivo](#8-arquitectura-geoespacial-objetivo)
9. [Arquitectura Visual Objetivo](#9-arquitectura-visual-objetivo)
10. [Arquitectura Geofísica Objetivo](#10-arquitectura-geofísica-objetivo)
11. [Arquitectura Multi-Dato](#11-arquitectura-multi-dato)
12. [Reportabilidad y Honestidad Técnica](#12-reportabilidad-y-honestidad-técnica)
13. [Frontend Final Requerido](#13-frontend-final-requerido)
14. [Backend Final Requerido](#14-backend-final-requerido)
15. [Roadmap Realista por Fases](#15-roadmap-realista-por-fases)
16. [Criterios de Aceptación Industrial](#16-criterios-de-aceptación-industrial)
17. [Preguntas para el Profesor](#17-preguntas-para-el-profesor)
18. [Qué Mostrar y Qué No Mostrar al Profesor](#18-qué-mostrar-y-qué-no-mostrar-al-profesor)
19. [Backlog de Eliminación y Ocultamiento](#19-backlog-de-eliminación-y-ocultamiento)
20. [Backlog Técnico Completo](#20-backlog-técnico-completo)
21. [Riesgos Existenciales](#21-riesgos-existenciales)
22. [Decisión Final de Enfoque](#22-decisión-final-de-enfoque)

---

# 1. Resumen Ejecutivo Brutal

## Dónde está TerraQuantum hoy

TerraQuantum es un prototipo funcional de software de procesamiento geofísico construido por un estudiante de segundo año de ingeniería civil en minas en aproximadamente un mes. Eso, por sí solo, es un logro técnico significativo. El sistema procesa datos gravimétricos reales, ejecuta inversión LSQR con regularización Tikhonov 3D, aplica focusing Minimum Support (MS-x), calcula scores de favorabilidad exploratoria y genera reportes estructurados. Tiene Docker, persistencia trazable, validación de esquemas, tests parciales y documentación técnica.

Desde la versión 1.0 de esta biblia se completaron las fases C1 a C5, que limpiaron la semántica peligrosa del lenguaje visible, agregaron un gate económico real, mejoraron la infraestructura Docker y documentación, introdujeron voxel trace completo, modos de datos 3D (exploration/full/anomaly) y host volume conceptual.

**Estas correcciones son reales. No convierten el sistema en industrial.**

## Qué sirve hoy

- El motor de inversión LSQR con regularización Tikhonov 3D funciona matemáticamente.
- El importador CSV v1 detecta unidades, duplicados, outliers y calidad del dataset.
- El sistema de coordenadas detecta lat/lon, UTM y metros locales, y convierte al sistema canónico.
- El auto-grid calcula block_size, nx, ny, nz automáticamente sin intervención del usuario.
- MS-x (Minimum Support IRLS) está implementado y validado en condiciones sintéticas.
- La persistencia por project_id/run_id es trazable y exportable.
- El score de favorabilidad combina múltiples factores geofísicos con penalizaciones por calidad.
- El reporte HTML tiene gate económico real: no muestra NPV/tonelajes cuando la evidencia es insuficiente.
- El reporte HTML muestra "Clase de Prioridad Relativa" y "Score Relativo del Target" con disclaimers anti-probabilidad.
- Docker Compose levanta el sistema completo con healthcheck y CORS explícito.
- La visualización 3D con InstancedMesh funciona para miles de voxels.
- El voxel trace expone total_voxels, stored_voxels, anomaly_voxels, returned_voxels y modo.
- Los modos exploration/full/anomaly están implementados y validados en QA.
- La UI ya no muestra "Probabilidad IA", "PERFORAR AQUÍ", "Risk Level HIGH/LOW", ni "Probabilidad de Éxito".
- La carga desde historial llama correctamente `setActiveRun` y `setShow3D(true)`.

## Qué no sirve hoy o está incompleto

- El modelo 3D no tiene verdad espacial completa. Un punto lat/lon central no define un footprint real.
- El terreno satelital puede verse real, pero no está matemáticamente co-registrado con el CSV.
- Los voxels se visualizan como cubos (modo debug), no como modelo profesional con slices.
- La profundidad de voxels no está referenciada al DEM local real.
- El host volume es una caja conceptual (BoxGeometry), no un volumen que siga la topografía.
- MS-x no convergió en la validación HVC real (best_iter=0, converged=false).
- El dataset HVC real produjo fit_level=LOW y favorabilidad=12.2/100 (MUY BAJO).
- Los aliases legacy (`recommendation="DRILL"`, `risk_level="LOW"`, `probability`) siguen en los JSON persistidos para compatibilidad interna; requieren auditoría de consumo.
- No hay autenticación de usuarios.
- No hay tests pytest automatizados (solo scripts manuales).
- No hay CI/CD.
- El módulo FMS es completamente demo (temperatura calculada con fórmula, no sensor real).
- El módulo MapeoIA es placeholder vacío sin funcionalidad.
- El módulo de diseño de mina tiene parámetros conceptuales y requiere datos reales con footprint.

## Por qué no está listo para vender

1. No tiene validación por profesional externo.
2. No tiene verdad espacial defensable (sigue sin footprint real).
3. Los campos legacy en JSON persistido siguen siendo semánticamente peligrosos si se exponen.
4. El único dataset real probado produjo fit LOW y favorabilidad MUY BAJA.
5. MS-x no convergió en condiciones reales.
6. El FMS y el diseño de mina son conceptuales, no industriales.
7. No hay autenticación ni política de datos de clientes.
8. El frontend no tiene slices profesionales como visualización default.

## Por qué sí puede convertirse en un prototipo serio

- La inversión LSQR + Tikhonov es el algoritmo correcto, implementado con scipy sparse en Python, no con heurísticas.
- MS-x es una implementación real de Portniaguine & Zhdanov (1999), validada sintéticamente.
- El gate económico real en reporte y frontend es arquitectónicamente correcto.
- La semántica de UI ya no engaña al usuario con lenguaje de probabilidad o recomendación de perforación.
- El voxel trace permite auditar exactamente cuántos voxels pasaron por cada etapa.
- El sistema auto-grid funcionó correctamente en HVC (blockSize≈1552-1557m, n=32×20×32).
- Docker, persistencia y estructura de servicios son suficientemente sólidos para expandir.

## Cuál es la nueva dirección

TerraQuantum debe consolidarse como plataforma de integración, inversión y visualización de evidencia geofísica para priorización exploratoria conceptual. La siguiente tarea concreta es resolver la verdad espacial (R1: footprint real, CRS completo, georef_confidence). Sin eso, ninguna otra mejora tiene validez técnica defensable.

---

# 2. Nueva Identidad Técnica de TerraQuantum

## Definición oficial

**TerraQuantum es una plataforma experimental de integración, inversión y visualización de evidencia geofísica para priorización exploratoria conceptual. Procesa datos gravimétricos georreferenciados, genera modelos de contraste de densidad del subsuelo mediante inversión LSQR con focusing Minimum Support, y permite visualizar anomalías en contexto topográfico con trazabilidad, incertidumbre y advertencias técnicas. Sus resultados son evidencia exploratoria conceptual que requiere validación profesional mediante geología de campo, geofísica complementaria y perforación antes de cualquier decisión técnica o económica.**

## Qué es TerraQuantum

- Plataforma de procesamiento de datos gravimétricos CSV
- Motor de inversión geofísica 3D (LSQR + MS-x focusing)
- Sistema de análisis automático de calidad de datos
- Visualizador 3D de modelos de contraste de densidad
- Calculador de score de favorabilidad exploratoria
- Generador de reportes técnicos con disclaimers, gate económico y trazabilidad
- Prototipo técnico en nivel de madurez PROTOTIPO → objetivo PRE-PRODUCCIÓN

## Qué NO es TerraQuantum

- Software que encuentra mineral
- Software que confirma mineralización
- Software que estima leyes minerales
- Software que estima recursos o reservas bajo ningún código (JORC, NI 43-101, SAMREC)
- Software que calcula NPV bancable
- Software de diseño de mina operativo
- Reemplazo de perforación
- Reemplazo de geólogo o geofísico profesional
- Software de telemetría de flota real
- Plataforma con uptime industrial ni SLA
- Herramienta para decisiones de inversión

## Usuario objetivo

- Equipo de exploración minera en etapa de priorización conceptual
- Académicos y estudiantes de geofísica o ingeniería en minas
- Consultoras de exploración que necesitan visualización rápida de datos gravimétricos
- Equipos de investigación que trabajan con inversión geofísica 3D

El sistema NO está diseñado para uso por personas sin formación técnica en geofísica.

## Etapa actual

**PROTOTIPO** — funciona en la máquina del desarrollador. Sin tests automatizados. Sin CI/CD. Sin autenticación. Logging por print() en servicios críticos. Validación externa pendiente.

## Etapa futura objetivo

**PRE-PRODUCCIÓN** — sistema containerizado, tests automatizados, CORS explícito, logging estructurado, validación externa firmada por geofísico e ingeniero de minas.

## Lenguaje permitido

- Anomalía de densidad
- Contraste de densidad
- Evidencia geofísica exploratoria
- Candidato exploratorio
- Prioridad relativa de objetivo
- Score de favorabilidad exploratoria
- Score relativo del target
- Clase de prioridad relativa
- Confiabilidad técnica del modelo
- Conceptual
- No validado
- Requiere validación profesional
- Datos de calidad ALTA/MEDIA/BAJA/INSUFICIENTE
- Incertidumbre ALTA/MEDIA/BAJA

## Lenguaje prohibido (sin validación de campo)

- Mineral confirmado
- Probabilidad de mineral
- Reserva (probada, probable, posible)
- Recurso (medido, indicado, inferido)
- NPV real o bancable
- Drill (como recomendación sin reservas)
- Riesgo bajo (sin sustento geológico)
- Ley estimada (sin muestreo)
- Rentable
- Plan minero operativo
- Gravimetría cuántica (término sin respaldo científico)
- Industrial (hasta tener validación externa)
- Preciso (sin validación contra datos reales)

---

# 3. Estado Actual Real del Sistema

## Tabla de módulos — Backend

| Módulo | Archivos principales | Qué hace hoy | Estado | Riesgo | Decisión |
|--------|----------------------|--------------|--------|--------|----------|
| **CSV import** | `gravity_import_service.py`, `gravity_import_api.py` | Parsea CSV, valida headers/unidades, detecta duplicados/outliers, convierte unidades (mGal→m/s²) | CORE_VALIDO | Bajo | Mantener |
| **CSV analysis** | `csv_analysis_service.py` | Analiza calidad del dataset: densidad, spatial extent, quality_label | CORE_VALIDO | Bajo | Mantener |
| **Coordinate transform** | `coordinate_transform_service.py` | Detecta lat/lon, UTM, local_meters; convierte al sistema canónico x_m/z_m | CORE_INCOMPLETO | Medio | Completar con footprint y UTM zone (R1) |
| **Auto-grid** | `grid_calculator_service.py` | Calcula block_size, nx, ny, nz, depth automáticamente | CORE_VALIDO | Bajo | Mantener |
| **LSQR inversion** | `exploration/gravimetry.py` | Inversión sparse LSQR + Tikhonov 3D, kernel CSR, order='F' | CORE_VALIDO | Bajo | Mantener |
| **MS-x focusing** | `exploration/focusing.py` | IRLS Minimum Support, config fija validada sintéticamente, always-on | CORE_INCOMPLETO | Medio | No modificar hiperparámetros; documentar no-convergencia en HVC real |
| **Block model** | `core/block_model_store.py`, `services/block_model_service.py` | Persiste y muestrea Parquets por project_id/run_id; modes exploration/full/anomaly/economic; voxel trace completo | CORE_VALIDO | Bajo | Mantener. Agregar columnas de georef en R3. |
| **Favorability** | `services/favorability_service.py`, `api/favorability_api.py` | Score 0-100 con gates de calidad e incertidumbre; priority_class, relative_target_score, model_reliability_level | CORE_INCOMPLETO | Medio | Aliases legacy en JSON persistido requieren auditoría de consumo |
| **Semántica backend** | `geophysics_service.py` | priority_class, relative_target_score, model_reliability_level implementados. Gate lógico funciona. | COMPLETADO C1-BE | Bajo | Mantener. Auditar aliases en flujos secundarios. |
| **Reporte HTML** | `reporting/report_generator.py` | Gate económico real (_check_economic_gate). No muestra DRILL, no muestra risk_level LOW, no muestra probability como probabilidad. Muestra Clase de Prioridad Relativa, Score Relativo del Target, disclaimers. | COMPLETADO C1-REP/C3-REP | Bajo | Mantener. Completar secciones de georef en R1. |
| **GEE terrain** | `core/gee_client.py`, `services/satellite_service.py` | Credenciales existen; integración activa parcial | CORE_INCOMPLETO | Medio | Completar con footprint real en R3 |
| **Terrain API** | `api/terrain_api.py`, `schemas/terrain_schema.py` | Endpoint de terreno existente; carga sobre lat/lon central | CORE_INCOMPLETO | Medio | Completar con footprint bbox en R3 |
| **Health endpoint** | `api/system_api.py` | `/health` existe y responde status ok | CORE_VALIDO | Bajo | Mantener |
| **Spectral** | `services/spectral_service.py`, `api/spectral_api.py` | Índices espectrales satelitales | CORE_INCOMPLETO | Medio | Futuro (Bloque 3) |
| **Mine design** | `engine.py`, `services/pit_design_service.py`, `pit_mesh.py` | LG + PyMaxflow + malla GLB; fallback silencioso en schema; parámetros son proxies | DANGEROUS_SEMANTICS | Alto | Ocultar hasta datos reales con footprint. Corregir fallback pit_design_schema. |
| **Economy/LOM** | `scheduler.py` | DispatchEngineV2, física CAT 797F; inputs son proxies | CONCEPTUAL_ONLY | Alto | Ocultar antes de demos externas. Gate C3 bloquea reporte cuando evidencia insuficiente. |
| **FMS** | `Camiones/fms.py` | Física de transporte real (CAT 797F); sin telemetría real | CONCEPTUAL_ONLY | Alto | Ocultar |
| **Scenario sweep** | `services/scenario_sweep_service.py` | Barrido de precio con ProcessPoolExecutor | FUTURE_MODULE | Bajo | Dejar para después |
| **Mine method** | `services/mine_method_service.py`, `schemas/mine_method_schema.py` | Clasificación rajo/subterránea | FUTURE_MODULE | Bajo | Dejar para después |
| **Docker** | `Dockerfile`, `docker-compose.yml` | Containerización con healthcheck, CORS, TERRAQUANTUM_HOST/PORT explícitos. Frontend depende de backend healthy. | CORE_VALIDO C4 | Bajo | Mantener |
| **Tests pytest** | `tests/` | 4 tests pytest básicos; sin CI/CD | CORE_INCOMPLETO | Alto | Completar urgente |

## Tabla de módulos — Frontend

| Módulo | Archivos principales | Qué hace hoy | Estado | Riesgo | Decisión |
|--------|----------------------|--------------|--------|--------|----------|
| **GravityCsvPreviewPanel** | `GravityCsvPreviewPanel.tsx` | Importación CSV + inversión, llama setActiveRun correctamente | CORE_VALIDO | Bajo | Mantener |
| **Scene3D** | `componentes/Scene3D.tsx` | InstancedMesh, slicing, filtros; HostVolume conceptual; grupo geológico estático (sin Float); cubos como visualización principal | CORE_INCOMPLETO | Medio | Reescribir modo profesional (R4) |
| **Exploration3DView** | `componentes/views/Exploration3DView.tsx` | Orquesta flujo CSV→inversión→3D | CORE_VALIDO | Bajo | Mantener |
| **DatosView / ProjectRunList** | `componentes/DatosView.tsx`, `componentes/datos/ProjectRunList.tsx` | Historial de corridas; bug de carga histórica CORREGIDO: llama setActiveRun y setShow3D(true) | CORE_VALIDO C5.1 | Bajo | Mantener. Refactorizar en componentes atómicos en R9. |
| **MineDesignView** | `componentes/views/MineDesignView.tsx` | Diseño de mina; gate C3-FE activo; parámetros son proxies | CONCEPTUAL_ONLY | Alto | Ocultar hasta datos reales con footprint |
| **FmsDashboard** | `componentes/FmsDashboard.tsx` | Flota derivada de LOM; temperatura por fórmula | UI_DEBUG_ONLY | Alto | Ocultar con banner de simulación permanente |
| **MapeoIAView** | `componentes/views/MapeoIAView.tsx` | Textarea + tags; NLP no implementado | REMOVE_OR_HIDE | Alto | Ocultar de navegación |
| **PitMetricsPanel** | Dentro de MineDesignView | NPV, tonelaje, LOM sobre proxies; gate C3-FE activo | DANGEROUS_SEMANTICS | Alto | Ocultar hasta datos reales |
| **GeoDashboard** | `componentes/huds/GeoDashboard.tsx` | Dashboard geofísico con voxel trace completo; nota conceptual de host volume | CORE_VALIDO C5.1 | Bajo | Mantener. Limpiar en R9. |
| **BottomControls** | `componentes/huds/BottomControls.tsx` | Toggle Vol. Subsuelo, slider opacidad, label "conceptual / no litología medida" | CORE_VALIDO C5.4 | Bajo | Mantener. Simplificar en R9. |
| **MwdLiveLink** | `componentes/huds/MwdLiveLink.tsx` | Simulación con Math.sin(); no es sensor real | UI_DEBUG_ONLY | Medio | Ocultar o marcar prominentemente |
| **useAppStore** | `store/useAppStore.ts` | Zustand store; favorabilityScore, favorabilityLevel, setFavorabilityGate, showHostVolume, hostVolumeOpacity implementados | CORE_VALIDO C3-FE/C5.3 | Bajo | Mantener |
| **frontendApi** | `lib/terraquantum/frontendApi.ts` | Proxies tipados hacia FastAPI | CORE_VALIDO | Bajo | Mantener |
| **pitDesignModel** | `lib/terraquantum/pitDesignModel.ts` | evaluateEconomicGate implementado; helpers de payload; findDemoHighlightVoxel y generateDemoDrillProfile son física en TypeScript | CORE_INCOMPLETO | Medio | Mover funciones demo a demoPreviews.ts |

## Clasificación de madurez infraestructural actual

| Aspecto | Estado actual | Objetivo |
|---------|---------------|----------|
| Tests automatizados | Sin pytest. 15+ scripts manuales | 4+ tests pytest en A2.5 |
| CI/CD | Sin GitHub Actions | PRE-PRODUCCIÓN |
| Logging | print() en servicios críticos | structlog |
| CORS | Explícito en docker-compose, solo localhost | Mantener en PRE-PRODUCCIÓN |
| Rate limiting | Activo (10/min inversión, 5/min pit) | Mantener |
| Autenticación | Sin auth | PRE-PRODUCCIÓN (JWT) |
| Docker | Funcional con healthcheck y CORS C4 | Verificar runtime en próxima iteración |
| README ejecutivo | Actualizado en C4 — backend, frontend, raíz, Docker, local | Actualizar cuando cambie arquitectura |
| Versionado | Sin CHANGELOG ni tags Git | Obligatorio por fase |

**Nivel de madurez global: PROTOTIPO.**

---

# 4. Problema Central: Verdad Espacial

Este es el problema más importante del sistema y el que más limita su credibilidad técnica. **Nada de lo hecho en C1-C5 lo resuelve.**

## Por qué un punto lat/lon central no basta

El sistema actual permite al usuario ingresar una coordenada lat/lon central que se usa para cargar el terreno satelital en la UI 3D. Esto crea la ilusión de georreferenciación, pero no es georreferenciación real.

**Lo que hace el sistema hoy:**
- El usuario ingresa lat=-22.28, lon=-68.89 (por ejemplo)
- El backend usa esas coordenadas para pedir el DEM/tile satelital
- El frontend muestra ese terreno sobre el modelo 3D
- Los voxels se posicionan "debajo" del terreno visualmente

**Lo que el sistema NO hace:**
- No verifica que el CSV de entrada corresponda a esa lat/lon
- No define cuáles son las esquinas reales del survey en coordenadas absolutas
- No asigna a cada voxel una coordenada geográfica absoluta (lat/lon o UTM)
- No verifica que la elevación del terreno corresponda a las profundidades del modelo

En la validación HVC, el CSV venía de British Columbia (Canadá) pero la lat/lon fue configurada para Atacama (Chile). La inversión funcionó matemáticamente, pero el terreno visible era de Chile, no de Canadá. Nadie que use ese modelo puede afirmar que la anomalía está en ningún lugar geográfico específico.

## Por qué se necesita un footprint real

Un footprint real es el polígono o bounding box que define exactamente qué área geográfica cubre el survey gravimétrico. Sin footprint real:

- Un voxel en posición ix=5, iz=10 no tiene coordenada geográfica definida
- El modelo no se puede superponer con mapas geológicos
- No se puede comparar con otras campañas geofísicas del mismo área
- No se puede definir dónde se haría una perforación

## Por qué se necesitan 4 esquinas/polígono/bbox

El footprint mínimo defensable es un bounding box con 4 esquinas en coordenadas absolutas (lat/lon o UTM con zona). Esto permite:
- Definir la escala del modelo (metros por voxel en coordenadas reales)
- Ubicar el terreno DEM exactamente sobre el modelo
- Afirmar que la anomalía está en tal cuadrante, no en otro

## Por qué se necesita CRS/datum/orientación

El sistema de coordenadas (CRS) define el datum (WGS84, SIRGAS2000, etc.), la proyección (UTM zona X, geográficas) y la orientación (Norte magnético vs. Norte verdadero). Sin CRS:

- UTM zona 17 S y UTM zona 18 S tienen coordenadas con formato similar pero posiciones muy diferentes
- Lat/lon sin datum puede diferir decenas de metros entre WGS84 y SAD69
- El backend no puede hacer la transformación correcta de CSV → coordenadas reales

## Por qué coordenadas locales sin anclaje son solo conceptuales

El HVC CSV tiene coordenadas en metros locales (x_m, z_m) con origen en (0,0). Eso es suficiente para la inversión matemática. Pero sin un punto de anclaje en coordenadas absolutas, no se puede decir en qué parte del mundo está ese (0,0).

**Consecuencia:** el modelo es correcto matemáticamente, pero no tiene ubicación geográfica absoluta. Para el propósito de exploración minera, eso lo hace conceptual, no georreferenciado.

## Cómo debe relacionarse CSV → voxels → DEM

La cadena correcta es:

```
CSV con coordenadas reales (lat/lon o UTM con zona)
  → Backend detecta CRS
  → Convierte a sistema canónico local (x_m, z_m)
  → Define footprint = bbox del survey en coordenadas absolutas
  → Calcula grilla (nx, ny, nz, blockSize)
  → Para cada voxel (ix, iy, iz):
      lat_voxel, lon_voxel = canónico_a_geográfico(ix * blockSize, iz * blockSize)
      surface_elevation = DEM.sample(lat_voxel, lon_voxel)
      depth_below_surface = iy * blockSize
      voxel_absolute_elevation = surface_elevation - depth_below_surface
  → Terreno DEM se carga exactamente sobre el footprint
```

Hoy, el paso "lat_voxel, lon_voxel = canónico_a_geográfico()" no existe. Los voxels no tienen coordenadas absolutas. El DEM se carga sobre un punto central, no sobre el footprint real del survey.

## Qué pasa con UTM sin zona

UTM sin zona definida es ambiguo. X=400000, Y=5000000 puede ser cualquiera de 60 zonas. El sistema debe requerir la zona UTM como campo obligatorio cuando el CSV tiene coordenadas UTM.

## Contrato espacial mínimo propuesto

Todo proyecto TerraQuantum debe tener un objeto `project_footprint` con:

```json
{
  "project_footprint": {
    "type": "bbox | polygon | local_reference | missing",
    "crs": "EPSG:4326 | EPSG:32718 | local_meters",
    "corners": {
      "sw": {"lat": ..., "lon": ...},
      "ne": {"lat": ..., "lon": ...}
    },
    "utm_zone": "18S | null",
    "source": "csv_columns | user_input | inferred | missing",
    "confidence": "HIGH | MEDIUM | LOW | NONE",
    "warnings": ["lat/lon central no es footprint real", ...]
  }
}
```

**Qué partes existen hoy:**
- CRS detection: EXISTS (`coordinate_transform_service.py` detecta lat/lon, UTM, local_meters)
- Bbox de extensión del survey: EXISTS (`SpatialExtent` en `csv_analysis_service.py`)
- Conversión canónica: EXISTS parcialmente
- Objeto project_footprint: NO EXISTE
- Asignación de coordenadas absolutas a voxels: NO EXISTE
- Verificación de footprint vs DEM: NO EXISTE

---

# 5. Contrato Industrial de Datos de Entrada

## 5.1 CSV apto para modelo georreferenciado

Un CSV es apto para modelo georreferenciado si cumple:

| Requisito | Descripción | Obligatorio |
|-----------|-------------|-------------|
| Coordenadas absolutas | lat/lon con datum, o UTM con zona | Sí |
| CRS explícito | EPSG o nombre del sistema | Sí |
| Unidades declaradas | mGal, µGal o m/s² | Sí |
| Elevación | Elevación de estación o referencia vertical | Recomendado |
| Gravedad/anomalía | Columna con anomalía de Bouguer o free-air | Sí |
| station_id | Identificador único por estación | Recomendado |
| Espaciado razonable | Consistente, sin saltos de >10x el espaciado medio | Sí |
| timestamp | Fecha/hora de medición | Recomendado |
| instrument_id | Identificador del gravímetro | Recomendado |
| QA/QC | Sin > 10% de outliers (>3σ) | Sí |
| Cobertura | Area cubierta suficiente para el target | Sí |
| Mínimo observaciones | ≥ 10 (R-11 inviolable) | Sí |

**Acción:** ACEPTAR con nivel de confianza ALTO. Footprint real calculable.

## 5.2 CSV apto solo para modelo conceptual

Un CSV produce solo modelo conceptual cuando:

- Tiene coordenadas locales en metros sin punto de anclaje geográfico
- No tiene CRS explícito
- No tiene elevación de estación
- No tiene instrumento ni timestamp
- Tiene densidad de muestreo baja (< 1 punto/km²)
- Tiene cobertura insuficiente para el target de interés

**Acción:** ACEPTAR con advertencias prominentes. Footprint = local_reference. El modelo no tiene ubicación geográfica absoluta. Todo resultado se clasifica automáticamente como CONCEPTUAL.

## 5.3 CSV no apto

Un CSV no es apto cuando:

- No tiene columnas de coordenadas identificables
- Unidades son imposibles o inconsistentes
- Tiene > 30% de outliers
- Menos de 10 observaciones válidas
- Cobertura de un único punto o línea sin extensión espacial
- Columnas ambiguas no resolubles por el sistema

**Acción:** BLOQUEAR. Retornar HTTP 422 con diagnóstico detallado de por qué se bloquea.

## Tabla de decisión

| Condición del CSV | Acción | Tipo de modelo resultante |
|-------------------|--------|---------------------------|
| Coordenadas absolutas + CRS + unidades | ACEPTAR | Georreferenciado |
| Local metros sin anclaje + unidades | ACEPTAR CON WARNINGS | Conceptual |
| Local metros sin anclaje + sin unidades claras | DEGRADAR a conceptual | Solo conceptual (advertencia prominente) |
| < 10 observaciones | BLOQUEAR | No aplica |
| > 30% outliers | BLOQUEAR | No aplica |
| Sin coordenadas | BLOQUEAR | No aplica |

---

# 6. Qué Puede y Qué No Puede Hacer la Gravimetría

## Lo que la gravimetría puede hacer en TerraQuantum

| Capacidad real | Descripción |
|----------------|-------------|
| Detectar contrastes de densidad | Un cuerpo con densidad diferente al background produce una anomalía |
| Sugerir geometría aproximada del cuerpo | Profundidad estimada del centro de masa, extensión lateral |
| Apoyar priorización exploratoria relativa | Zona A tiene mayor anomalía que zona B → candidato preferencial |
| Generar hipótesis exploratorias | "Esta zona tiene contraste de densidad positivo, coherente con intrusivo" |
| Complementar otras fuentes de datos | Cruzado con magnetometría o geoquímica, aumenta confiabilidad |
| Mapear grandes estructuras regionales | Cuencas, intrusivos regionales, corteza, discontinuidades |

## Lo que la gravimetría NO puede hacer (en ningún software)

| Limitación fundamental | Explicación |
|------------------------|-------------|
| Identificar mineral específico | Muchos minerales distintos tienen densidades similares |
| Confirmar presencia de cobre, oro, etc. | La densidad no es química |
| Estimar ley mineral | La ley requiere muestreo geoquímico, no inversión geofísica |
| Estimar recursos ni reservas | Requiere sondajes, kriging y código de reporte profesional |
| Calcular NPV real | Requiere ley medida, tonelaje verificado, costos reales, metalurgia |
| Recomendar perforación por sí sola | La gravimetría es evidencia de primer orden, no suficiente |
| Reemplazar sondajes DDH | Un sondaje da información directa que ningún método geofísico reemplaza |
| Resolver la ambigüedad equivalente | Infinitas distribuciones de densidad producen la misma señal superficial |
| Distinguir dirección de magnetización | Eso es magnetometría, no gravimetría |
| Medir profundidad exacta | La profundidad estimada tiene incertidumbre creciente con la profundidad |

## Tabla: output actual vs. interpretación correcta

| Campo del sistema | Interpretación correcta | Interpretación incorrecta (prohibida) |
|-------------------|------------------------|---------------------------------------|
| `density` (t/m³) | Contraste de densidad relativa modelado por LSQR | Densidad absoluta medida por sondaje |
| `anomaly_intensity` | Intensidad relativa del contraste respecto al background | Concentración mineral |
| `target_score` / `relative_target_score` | Score relativo del target en el modelo; no es probabilidad de mineralización | Probabilidad de encontrar mineral |
| `favorability_score` (12.2/100 en HVC) | Nivel de evidencia geofísica para priorización conceptual | Probabilidad de depósito económico |
| `fit_level = LOW` | El modelo no reproduce bien la señal observada | El modelo es incorrecto (es el ajuste el que es bajo) |
| `recommendation = "DRILL"` (campo LEGACY en JSON) | Alias interno legacy; la UI y el reporte ya no lo muestran como recomendación | Recomendación de perforación validada |
| `probability = 0.99` (campo LEGACY en JSON) | Alias interno legacy; la UI y el reporte lo contextualizan como score relativo | Probabilidad geológica de mineralización |
| `priority_class` | Clase de prioridad relativa basada en evidencia geofísica y controles de calidad; no es recomendación de perforación | Recomendación directa de acción exploratoria |
| `scale_status = OK` en MS-x | El focusing IRLS completó sin inestabilidad | El modelo de densidad es físicamente calibrado |

---

# 7. Requisitos del Modelo 3D Industrial

Un modelo 3D defensable ante un geofísico profesional debe tener:

## Requisitos de georreferenciación

1. **Footprint real**: el modelo debe saber en qué parte del mundo está. Requiere coordenadas absolutas del survey.
2. **DEM real**: la topografía debe provenir de un DEM (SRTM, Copernicus) co-registrado con el footprint real.
3. **Modelo georreferenciado**: cada voxel debe tener lat/lon absoluta (o UTM) asignable.
4. **Profundidad respecto al DEM local**: la profundidad de cada voxel debe ser relativa a la elevación real del DEM en esa posición horizontal.
5. **Terreno mayor que el modelo**: el terreno visualizado debe extenderse más allá del footprint del modelo para dar contexto topográfico.

## Requisitos visuales mínimos

6. **Gradiente de color por densidad/anomalía**: azul = baja densidad, rojo = alta densidad. Leyenda con valores.
7. **Cortes X/Y/Z interactivos**: planos de corte que muestren secciones del modelo.
8. **Modo slices como default**: los slices son la visualización profesional, no los cubos individuales.
9. **Escala visible**: escala de distancia en km o m, norte, eje de profundidad.
10. **Coordenadas del cursor**: al pasar el cursor sobre un voxel, mostrar coordenadas y profundidad.
11. **Leyenda técnica completa**: unidades, rango, fecha de corrida, dataset fuente.

## Requisitos de honestidad

12. **Incertidumbre visible**: el nivel de incertidumbre de la corrida debe ser visible en el modelo.
13. **Residual visible**: el fit_level y el RMSE deben ser accesibles desde la vista 3D.
14. **Trazabilidad**: project_id y run_id deben estar visibles.
15. **Disclaimer en pantalla**: advertencia visible de que el modelo es evidencia exploratoria conceptual.

## Requisitos de análisis

16. **Modo debug de voxels**: cubos individuales como modo debug, no como default.
17. **Isosuperficies**: en el futuro, malla suave por umbral de densidad (no bounding box).
18. **Export técnico**: capacidad de exportar secciones como PNG con coordenadas.

## Lo que el modelo 3D actual no tiene y debe tener

- **Los cubos son modo debug, no visualización principal.** El frontend actual muestra voxels como la visualización predeterminada. Un geofísico no evalúa un modelo por cubos individuales.
- **La caja café (host volume) es insuficiente.** El HostVolume actual es un `BoxGeometry` conceptual, no una isosuperficie calculada físicamente. Está correctamente etiquetado como conceptual.
- **El terreno debe ser mayor que el modelo.** El DEM debe extenderse para dar contexto topográfico real.
- **El host volume debe seguir el DEM.** El volumen del modelo debe recortarse en la superficie siguiendo la topografía.
- **No llamar "mineral" a la anomalía.** En la UI, todo debe ser "anomalía de densidad", nunca "mineral" o "recurso".

---

# 8. Arquitectura Geoespacial Objetivo

## Objetos de datos necesarios

### ProjectFootprint (nuevo objeto requerido — R1)

```python
class ProjectFootprint(BaseModel):
    type: Literal["bbox", "polygon", "local_reference", "missing"]
    crs: str  # "EPSG:4326", "EPSG:32718", "local_meters"
    corners: Optional[dict]  # {"sw": {"lat": ..., "lon": ...}, "ne": {...}}
    utm_zone: Optional[str]  # "18S", "19N", etc.
    source: Literal["csv_columns", "user_input", "inferred", "missing"]
    confidence: Literal["HIGH", "MEDIUM", "LOW", "NONE"]
    warnings: List[str]
    area_km2: Optional[float]
    center_lat: Optional[float]
    center_lon: Optional[float]
```

### VoxelGeoreference (nuevo objeto por voxel — R3)

Para cada voxel (ix, iy, iz):

```
lat_voxel, lon_voxel = footprint.canónico_a_geográfico(ix * block_size, iz * block_size)
surface_elevation_at_xy = DEM.sample(lat_voxel, lon_voxel)
depth_below_surface = iy * block_size
voxel_absolute_elevation = surface_elevation_at_xy - depth_below_surface
voxel_bottom_elevation = voxel_absolute_elevation - block_size
```

### GeorefConfidence (campo en report.json — R1)

```json
{
  "georef_confidence": {
    "level": "HIGH | MEDIUM | LOW | NONE",
    "has_absolute_coordinates": true | false,
    "has_dem_coregistration": true | false,
    "footprint_type": "bbox | local_reference | missing",
    "warnings": [...]
  }
}
```

## Qué se implementa en backend vs frontend

### Backend (toda la física y geometría):
- Detección de CRS
- Conversión a sistema canónico
- Cálculo de footprint
- Asignación de coordenadas absolutas a voxels
- Sampling del DEM por posición de voxel
- Cálculo de elevación absoluta de voxels
- Persistencia de georef en project_footprint.json

### Frontend (solo visualización):
- Cargar terreno DEM exactamente sobre el footprint
- Posicionar voxels en elevación absoluta
- Mostrar coordenadas del cursor en sistema de referencia del usuario
- Mostrar georef_confidence con color (NONE=rojo, LOW=naranja, HIGH=verde)

---

# 9. Arquitectura Visual Objetivo

## Modos de visualización

| Modo | Descripción | Estado |
|------|-------------|--------|
| **Slices** (default objetivo) | Planos de corte X/Y/Z con heatmap de densidad | A implementar (R4) |
| **Isosurface** | Malla suave por umbral de densidad | Futuro (R5 GLB) |
| **Block debug** | Cubos individuales con gradiente de color | Existe como visualización actual; mover a modo avanzado en R4 |
| **Anomaly only** | Solo voxels por encima del umbral de anomalía | Existe vía modo anomaly (C5.2) |
| **Full density** | Todos los voxels con escala continua de densidad | Existe vía modo full (C5.2) |
| **Exploration** | Subconjunto representativo de 5000 voxels | Existe vía modo exploration (C5.2) |
| **Terrain only** | Solo el DEM, sin modelo | A implementar |

## Controles que deben estar en el frontend final

- Opacidad del terreno (slider 0-100%)
- Opacidad del modelo (slider 0-100%)
- Corte X (posición del plano de corte este-oeste)
- Corte Y (profundidad)
- Corte Z (posición norte-sur)
- Capa de color (anomalía / densidad / favorabilidad)
- Escala de color (colorbar con mín/máx)
- Modo de visualización (slices / bloque / solo anomalía)
- Norte y escala de distancia
- Coordenadas del cursor
- Selector de modo de datos (exploration / full / anomaly) — ya existe

## Pantallas recomendadas para frontend final

1. **Proyecto / datos**: lista de proyectos, carga CSV, validación
2. **Validación CSV**: resultado del análisis automático, quality_label, warnings
3. **Modelo 3D**: visualización principal con terreno + modelo
4. **Cortes**: secciones X/Y/Z con colorbar y coordenadas
5. **Favorabilidad**: score, factores, incertidumbre
6. **Reporte**: reporte técnico exportable
7. **Configuración avanzada** (separada): parámetros que el usuario experto puede modificar

## Controles actuales a eliminar o mover

| Control | Acción |
|---------|--------|
| Toggle manual de MS-x | Eliminar (MS-x es siempre activo, R-V2-02) |
| Parámetros manuales de grilla (nx, ny, nz) | Mover a configuración avanzada |
| Simulación MWD Live Link | Ocultar (no es sensor real) |
| FMS Dashboard como vista principal | Ocultar |
| MapeoIA en navegación | Ocultar |
| AnomalyEnvelope sin disclaimer | Agregar label: "Envelope visual, no isosuperficie física" |

---

# 10. Arquitectura Geofísica Objetivo

## Estado actual del solver LSQR

| Componente | Estado | Observación |
|------------|--------|-------------|
| Kernel de sensitividad CSR | CORE_VALIDO | Correcto. No modificar. |
| Regularización Tikhonov 3D | CORE_VALIDO | Funciona. |
| Order='F' (Fortran column-major) | CORE_VALIDO | Inviolable (R-01). |
| LSQR sparse | CORE_VALIDO | scipy.sparse.linalg.lsqr correcto. |
| Depth weighting | CORE_VALIDO | Presente. |
| Density bounds (no-negativity) | CORE_INCOMPLETO | Existe pero puede mejorarse. |
| Residual computation | CORE_VALIDO | RMSE, MAE, fit_level correcto. |
| Uncertainty quantification | CORE_INCOMPLETO | uncertainty_score existe; cuantificación formal falta. |
| Resolution matrix | NO EXISTE | Falta para evaluación de resolución por zona. |
| Sensitivity map | NO EXISTE | Falta para informar al usuario de zonas mal resueltas. |
| Topographic correction | NO EXISTE | Corrección topográfica para surveys en terreno accidentado. |
| Bouguer correction | NO EXISTE | El sistema asume que el CSV ya tiene anomalía de Bouguer. |

## Qué falta para ser defendible ante un geofísico

1. **Residual map exportable**: mapa 2D de residuals por estación, exportable como PNG o CSV.
2. **Uncertainty quantification formal**: estimación de incertidumbre por voxel (no solo score global).
3. **Resolution matrix diagonal**: cuáles voxels están bien resueltos, cuáles no.
4. **Sensitivity map**: visualización de qué zonas del subsuelo tienen sensores cercanos.
5. **Documentación del tipo de corrección aplicada**: el sistema debe declarar si el CSV tiene anomalía de Bouguer libre, Bouguer completa, o gravedad sin corregir.
6. **Topographic correction**: para surveys en topografía accidentada, la corrección topográfica es necesaria para resultados correctos.

## MS-x: estado real y limitaciones conocidas

- MS-x está implementado correctamente según Portniaguine & Zhdanov (1999).
- Validado en 5 casos sintéticos con config fija (`_BETA_MS=0.01`, `_EPS_0=0.80`, etc.).
- En la validación HVC (dataset real), MS-x no convergió (best_iter=0, converged=false).
- Esto es consistente: cuando el ajuste base es LOW, MS-x no tiene solución robusta para focalizar.
- MS-x es "always-on" (R-V2-02), pero sus resultados se reportan honestamente incluyendo best_iter y converged.
- No modificar los hiperparámetros de MS-x sin nueva fase experimental documentada (R-03).

---

# 11. Arquitectura Multi-Dato

## Por qué la gravimetría sola es insuficiente

La gravimetría mide contrastes de densidad. Muchos objetos geológicos diferentes tienen densidades similares:

- Un intrusivo granítico (no mineralizado) puede tener la misma firma gravimétrica que una brecha mineralizada.
- Un basamento máfico profundo puede producir una anomalía positiva comparable a un depósito de sulfuros.
- Las anomalías negativas pueden ser cuencas sedimentarias o zonas de alteración.

Sin datos complementarios, la interpretación geológica tiene ambigüedad inherente. Esto es un principio fundamental de la geofísica, no una limitación del software.

## Mínimo defensable: evidencia convergente mínima

Para que una interpretación exploratoria tenga credibilidad básica:

| Nivel | Datos requeridos | Uso posible |
|-------|-----------------|-------------|
| **Mínimo conceptual** | Gravimetría | Solo anomalía de densidad. Sin interpretación geológica. |
| **Mínimo técnico** | Gravimetría + geología superficial | Puede correlacionar anomalía con litología conocida. |
| **Mínimo defensable** | Gravimetría + magnetometría + geología superficial + densidades medidas | Inversión conjunta posible. Interpretación con más fundamento. |
| **Mínimo avanzado** | Lo anterior + IP + sondaje de verificación | Puede identificar zonas de sulfuros. |
| **Industrial completo** | Todo lo anterior + geoquímica + muestreo estadístico | Base para estimación de recursos. |

## Hoja de ruta para multi-dato (fases futuras)

### Fase R6 — Magnetometría (primera prioridad)
- Segunda fuente más común en exploración
- Datos públicos disponibles (Geoscience Australia, USGS, EMAG2)
- Inversión de susceptibilidad magnética 3D
- Primero por separado, luego inversión conjunta con cross-gradient

### Fase F2 — Geología superficial
- Capa de litología del área
- Mapas de alteración existentes
- Integración como restricción blanda al inversor

### Fase F3 — Densidades medidas (crítico)
- Sin densidades medidas por muestreo o sondaje, la calibración del modelo de densidad es imposible
- Las densidades del modelo LSQR son contrastes relativos, no densidades absolutas

### Fase F4 — IP (Inducción Polarizada)
- Detecta sulfuros
- Muy relevante para pórfidos Cu-Mo y depósitos IOCG
- Algoritmo diferente al LSQR; requiere planning separado

### Fase F5 — Geoquímica
- Requiere muestras de campo reales
- No implementable sin datos físicos
- Integración como score de favorabilidad geoquímica

---

# 12. Reportabilidad y Honestidad Técnica

## Qué debe incluir un reporte técnico de TerraQuantum

| Sección | Contenido obligatorio |
|---------|----------------------|
| Identificación | project_id, run_id, fecha, versión del software |
| Dataset | Fuente, nombre, número de observaciones, calidad (quality_label) |
| Georreferenciación | footprint_type, CRS, georef_confidence, warnings |
| Análisis CSV | Duplicados, outliers, unidades, sistema de coordenadas detectado |
| Auto-grid | block_size, nx, ny, nz, voxels totales, lógica de cálculo |
| Inversión | lambda_mag, alpha_spatial, RMSE, MAE, fit_level, normalized_RMSE |
| MS-x | scale_status, use_mode, best_iter, converged, safety_labels |
| Favorabilidad | score, nivel, factores, quality_gate, uncertainty_gate |
| Clase de prioridad | priority_class con nota de que no es recomendación de perforación |
| Score relativo | relative_target_score con nota de que no es probabilidad |
| Incertidumbre | uncertainty_score, uncertainty_level, drivers |
| Gate económico | estado del gate (GATE_PASS / GATE_FAIL / NOT_EVALUATED) con motivos |
| Limitaciones | Lista explícita de qué no se puede concluir |
| Disclaimers | Texto legal y técnico obligatorio |

**Estado actual del reporte HTML:** Implementado en C1-REP y C3-REP. Contiene gate económico, clase de prioridad, score relativo y disclaimers. Falta: sección de georreferenciación real (requiere R1), residual map exportable (requiere R4), formato PDF.

## Términos prohibidos en reportes (sin validación de campo)

No deben aparecer en ningún reporte generado por TerraQuantum:

- "mineral confirmado" o cualquier variante
- "probabilidad de mineral" o "probabilidad de X%"
- "drill" o "perforar" como recomendación sin caveats
- "riesgo bajo" sin sustento geológico
- "NPV real" o "valor presente neto bancable"
- "recurso" (medido, indicado, inferido)
- "reserva" (probada, probable)
- "factibilidad"
- "ley estimada" (sin muestreo geoquímico)
- "rentable"
- "depósito económico"

## Términos permitidos en reportes

- "anomalía de densidad"
- "contraste de densidad"
- "evidencia geofísica exploratoria"
- "candidato exploratorio"
- "clase de prioridad relativa"
- "score relativo del target"
- "score de favorabilidad exploratoria: X/100"
- "conceptual"
- "no validado"
- "requiere validación profesional"
- "fit_level LOW/MEDIUM/HIGH"
- "incertidumbre MEDIA/ALTA"

## Disclaimer mínimo obligatorio en todos los reportes

> Este documento describe resultados de un modelo geofísico computacional de carácter exploratorio y conceptual. Los resultados NO confirman presencia de mineral económico de ningún tipo, NO representan estimación de ley, tonelaje, recurso ni reserva bajo ningún código técnico (JORC, NI 43-101, SAMREC). El uso de estos resultados en decisiones de inversión, perforación o declaración de activos sin validación profesional externa es inapropiado. TerraQuantum requiere revisión por geofísico y/o ingeniero de minas habilitado antes de cualquier aplicación en decisión técnica real.

---

# 13. Frontend Final Requerido

## Estado actual del frontend

El frontend actual es un prototipo de transición. Tiene funcionalidad correcta en el flujo principal (CSV → inversión → 3D), semántica limpiada en C2-FE, gate económico en C3-FE, voxel trace en C5.1, selector de modo en C5.2, y host volume conceptual en C5.3/C5.4. El bug crítico de carga histórica fue corregido (ProjectRunList llama setActiveRun y setShow3D).

## Qué componentes se mantienen

| Componente | Decisión | Razón |
|------------|----------|-------|
| `GravityCsvPreviewPanel.tsx` | Mantener | Flujo correcto, setActiveRun correcto |
| `Exploration3DView.tsx` | Mantener + refactorizar | Orquestación correcta |
| `Scene3D.tsx` | Reescribir modo profesional en R4 | Cubos deben ser modo debug |
| `useAppStore.ts` | Mantener + limpiar aliases legacy de tipos | Gate económico y voxel trace implementados |
| `frontendApi.ts` | Mantener | Proxies correctos |
| `pitDesignModel.ts` | Limpiar | evaluateEconomicGate implementado; mover funciones demo a demoPreviews.ts |
| `ProjectRunList.tsx` | Mantener | Bug de historial corregido en C5.1 |
| `GeoDashboard.tsx` | Mantener + limpiar en R9 | Voxel trace completo |
| `BottomControls.tsx` | Mantener + simplificar en R9 | Toggle host volume con label conceptual |

## Qué componentes se reescriben

| Componente | Razón |
|------------|-------|
| `Scene3D.tsx` (modo visual) | Agregar slices profesionales como modo default (R4) |
| `HomeView.tsx` | Nuevo onboarding con definición honesta del sistema |
| Navegación principal | Reorganizar para flujo guiado |

## Qué componentes se ocultan o eliminan

| Componente | Acción | Razón |
|------------|--------|-------|
| `MapeoIAView.tsx` | OCULTAR de navegación | Placeholder vacío, engañoso |
| `FmsDashboard.tsx` | OCULTAR o agregar banner de simulación permanente | No es telemetría real |
| `MineDesignView.tsx` | OCULTAR hasta datos reales con footprint | Parámetros son proxies conceptuales |
| `MwdLiveLink.tsx` | OCULTAR o label prominente | Math.sin() no es sensor |
| AnomalyEnvelope en `Scene3D.tsx` | Agregar label | No es isosuperficie física |
| Controles manuales de grilla | Mover a modo avanzado | R-V2-03: backend auto-propone |

## Interfaz final recomendada

```
Pantalla 1 — Inicio
  ├── Descripción honesta del sistema
  ├── Lista de proyectos existentes
  └── Botón "Nuevo proyecto"

Pantalla 2 — Importar CSV
  ├── Drag & drop CSV
  ├── Análisis automático de calidad
  ├── quality_label + warnings
  ├── footprint_type + georef_confidence (badge color)
  └── Botón "Ejecutar inversión"

Pantalla 3 — Modelo 3D [Vista principal]
  ├── Terreno DEM semitransparente
  ├── Modelo volumétrico con slices (default en R4)
  ├── Leyenda de densidad con colorbar
  ├── Coordenadas del cursor
  ├── fit_level + uncertainty_level visibles
  ├── Voxel trace (ya implementado en GeoDashboard)
  └── Disclaimer en pantalla

Pantalla 4 — Cortes
  ├── Secciones X, Y, Z del modelo
  ├── Colorbar con valores
  └── Coordenadas + profundidad

Pantalla 5 — Favorabilidad
  ├── Score (X/100) con nivel
  ├── Factores con pesos
  ├── Gates de penalización
  ├── Clase de prioridad relativa
  └── Disclaimer

Pantalla 6 — Reporte
  └── HTML exportable con todos los campos

Pantalla 7 — Configuración avanzada (separada)
  ├── Parámetros de inversión (lambda, alpha)
  └── Solo para usuarios expertos
```

---

# 14. Backend Final Requerido

## Servicios que se mantienen

| Servicio | Estado | Acción |
|----------|--------|--------|
| `gravity_import_service.py` | CORE_VALIDO | Mantener + agregar footprint output en R1 |
| `csv_analysis_service.py` | CORE_VALIDO | Mantener |
| `coordinate_transform_service.py` | CORE_INCOMPLETO | Completar con UTM zone y footprint en R1 |
| `grid_calculator_service.py` | CORE_VALIDO | Mantener |
| `exploration/gravimetry.py` | CORE_VALIDO | No modificar (R-01, R-03) |
| `exploration/focusing.py` | CORE_VALIDO | No modificar hiperparámetros |
| `core/block_model_store.py` | CORE_VALIDO | Mantener + agregar georef fields en R3 |
| `services/block_model_service.py` | CORE_VALIDO C5.1/C5.2 | Mantener; modes exploration/full/anomaly/economic |
| `services/favorability_service.py` | CORE_INCOMPLETO | Aliases legacy en JSON persistido requieren auditoría |
| `reporting/report_generator.py` | COMPLETADO C1-REP/C3-REP | Mantener; agregar sección de georef en R1 |
| `api/system_api.py` | CORE_VALIDO C4 | /health endpoint activo |

## Servicios que se refactorizan

| Servicio | Problema | Acción |
|----------|---------|--------|
| `services/geophysics_service.py` | print() en paths críticos | Migrar a structlog |
| `services/gravity_import_service.py` | print() en paths críticos | Migrar a structlog |
| `schemas/pit_design_schema.py` | Fallback silencioso a legacy | Eliminar fallback |

## Servicios que quedan como legacy hasta validación

| Servicio | Razón |
|----------|-------|
| `engine.py` (Lerchs-Grossmann) | Algoritmo correcto, parámetros conceptuales |
| `scheduler.py` | Inputs son proxies, no datos reales |
| `Camiones/fms.py` | Sin telemetría real |
| `services/pit_design_service.py` | Depende de datos reales para ser útil |

## Schemas definitivos pendientes

| Schema | Estado | Acción |
|--------|--------|--------|
| `ProjectFootprint` | NO EXISTE | Crear en R1 |
| `GeorefConfidence` | NO EXISTE | Crear en R1 |
| `AutoParamsReport` | Parcial en report.json | Formalizar |
| `FavorabilityReport` | EXISTE con priority_class, relative_target_score | Auditar aliases legacy en JSON persistido |
| `pit_design_schema.py:PitRequest` | Tiene fallback peligroso | Corregir |

## Endpoints pendientes de crear

| Endpoint | Propósito | Prioridad |
|----------|-----------|-----------|
| `GET /project-footprint?project_id=X&run_id=Y` | Retornar footprint del survey | P0 — R1 |
| `DELETE /project-run?project_id=X&run_id=Y` | Eliminar corrida | P1 |
| `PATCH /project-run/name` | Renombrar corrida | P1 |

## Estructura de storage ideal

```
terraquantum-backend/data/projects/{project_id}/runs/{run_id}/
├── block_model.parquet                # Block model completo
├── block_model_anomaly.parquet        # Voxels de anomalía
├── block_model_focusing.parquet       # MS-x resultado
├── inputs.json                        # Parámetros de la inversión
├── observations.json                  # Observaciones de entrada
├── report.json                        # QA/QC, fit, best_target, priority_class
├── favorability.json                  # Score, factores, gates
├── gravity_import_metadata.json       # Metadata del CSV
├── project_footprint.json             # [R1 — PENDIENTE]
├── source_gravity.csv                 # CSV original (trazabilidad)
└── report.html                        # Reporte HTML con gate económico
```

---

# 15. Roadmap Realista por Fases

## Fase R0 — Congelar lenguaje y alcance

**Estado post-C1/C2/C3:** PARCIALMENTE COMPLETADA

**Qué se completó:**
- UI ya no muestra "Probabilidad IA", "PERFORAR AQUÍ", "Risk Level HIGH/LOW", "Probabilidad de Éxito" (C2-FE verificado)
- Reporte HTML no muestra "Recomendación: DRILL" como output principal (C1-REP verificado)
- Reporte HTML no muestra "Riesgo: LOW" como output principal (C1-REP verificado)
- Gate económico real bloquea NPV/tonelajes cuando evidencia es insuficiente (C3-REP/C3-FE verificado)
- `priority_class`, `relative_target_score`, `model_reliability_level` implementados en backend (C1-BE verificado)

**Qué sigue pendiente de R0:**
- Los aliases legacy (`recommendation="DRILL"`, `risk_level="LOW"`, `probability`) siguen en los JSON persistidos. No se muestran en UI ni reporte, pero existen internamente. Requieren auditoría de todos los flujos que los consumen y eventual renombre o deprecación formal.
- MapeoIA: requiere verificar que esté efectivamente oculto de la navegación en el build actual.
- FmsDashboard: requiere banner de simulación no removible si está visible.
- Disclaimer UI principal: verificar que esté prominente en pantalla en todos los flujos.

**Criterios de aceptación originales:**
- [x] El campo `recommendation = "DRILL"` no aparece en la UI de favorabilidad ni en el reporte HTML
- [x] El campo `max_probability = 1.0` no aparece sin contexto de "score de ranking"
- [ ] MapeoIA no aparece en la barra de navegación — verificar en QA
- [ ] FmsDashboard tiene banner no removible — verificar en QA

---

## Fase R1 — Contrato espacial real

**Estado: SIGUIENTE FASE ACTIVA**

**Objetivo:** Que el sistema produzca un footprint explícito para cada proyecto, con nivel de confianza declarado.

**Tareas:**
- Crear schema `ProjectFootprint`
- Modificar `coordinate_transform_service.py` para emitir footprint
- Crear endpoint `GET /project-footprint`
- Agregar campo `georef_confidence` a `report.json`
- Requerir UTM zone cuando el CSV tiene coordenadas UTM
- Modificar frontend para mostrar footprint_type y georef_confidence con color

**Criterios de aceptación:**
- Toda corrida tiene `project_footprint.json` con `type`, `confidence` y `warnings`
- Un CSV con lat/lon reales produce `type=bbox` y `confidence=HIGH`
- Un CSV con coordenadas locales sin anclaje produce `type=local_reference` y `confidence=NONE`
- La UI muestra georef_confidence como badge (NONE=rojo, LOW=naranja, MEDIUM=amarillo, HIGH=verde)

**Qué NO resuelve:** DEM co-registrado con footprint real, elevaciones absolutas de voxels

---

## Fase R2 — CSV industrial validator

**Estado: PENDIENTE**

**Objetivo:** Que el sistema acepte, degrade o bloquee datasets según criterios industriales explícitos.

**Tareas:**
- Implementar clasificación formal: APTO_GEORREF / APTO_CONCEPTUAL / NO_APTO
- Agregar validación de UTM zone
- Agregar validación de CRS explícito
- Agregar acción DEGRADAR_A_CONCEPTUAL con warnings
- Agregar acción BLOQUEAR con diagnóstico detallado

**Criterios de aceptación:**
- CSV sin coordenadas retorna HTTP 422 con diagnóstico, no intenta invertir
- CSV con coordenadas locales produce advertencia prominente "MODELO CONCEPTUAL — sin georreferenciación absoluta"
- El tipo de modelo resultante (GEORREF / CONCEPTUAL) es visible en toda la UI

---

## Fase R3 — DEM y profundidad real

**Estado: PENDIENTE**

**Objetivo:** Que cada voxel tenga elevación absoluta calculada desde el DEM local.

**Tareas:**
- Implementar `surface_elevation_at_xy(lat, lon)` usando SRTM/Copernicus DEM
- Calcular `voxel_absolute_elevation = surface_elevation - iy * block_size`
- Persistir elevaciones en `block_model.parquet` como columnas adicionales
- Verificar que el terreno DEM se carga exactamente sobre el footprint del survey (no sobre un punto central arbitrario)
- Modificar frontend para posicionar el terreno sobre el footprint real
- Host volume siguiendo topografía DEM (no BoxGeometry plana)

**Criterios de aceptación:**
- `block_model.parquet` contiene columnas `surface_elevation_m` y `voxel_elevation_m`
- El terreno 3D coincide geográficamente con el footprint del CSV
- La profundidad de un voxel es medible en metros desde la superficie real

---

## Fase R4 — Modelo 3D profesional

**Estado: PENDIENTE**

**Objetivo:** Reemplazar los cubos como visualización principal por slices profesionales con coordenadas.

**Tareas:**
- Implementar modo slices como default en `Scene3D.tsx`
- Agregar colorbar con valores de densidad
- Agregar norte y escala de distancia
- Agregar coordenadas del cursor
- Agregar fit_level y uncertainty_level visibles en el modelo
- Mover modo de cubos a "configuración avanzada"

**Criterios de aceptación:**
- Un geofísico puede leer el modelo 3D sin instrucciones
- El modelo muestra: escala, norte, profundidad, coordenadas del cursor, leyenda de densidad
- Los cubos individuales no son la visualización default

---

## Fase R5 — Isosuperficies y GLB

**Estado: PENDIENTE**

**Objetivo:** Generar mallas suaves (isosuperficies) por umbral de densidad.

**Tareas:**
- Implementar generación de isosuperficie en backend (marching cubes o similar)
- Exportar como GLB
- Mostrar isosuperficie en Scene3D como alternativa a slices
- Etiquetar como "isosuperficie de contraste de densidad ≥ X t/m³"

**Criterios de aceptación:**
- Un umbral de densidad genera una malla suave coherente
- La malla está co-registrada con el footprint real
- No se llama "superficie de mineral" en ningún lugar

---

## Fase R6 — Multi-dato mínimo (magnetometría)

**Estado: PENDIENTE**

**Objetivo:** Agregar magnetometría como segunda fuente geofísica independiente.

**Tareas:**
- Importador CSV magnético
- Inversión de susceptibilidad magnética 3D (LSQR separado)
- Visualización de susceptibilidad en modelo 3D
- Cruce de evidencia gravimétrica + magnética en favorabilidad

**Criterios de aceptación:**
- El sistema puede procesar un CSV magnético
- El modelo de susceptibilidad es visualizable junto al modelo gravimétrico
- La favorabilidad puede usar ambas fuentes

---

## Fase R7 — Validación sintética rigurosa

**Estado: PENDIENTE**

**Objetivo:** Benchmarkear el solver contra casos sintéticos con ground truth conocido.

**Tareas:**
- Crear suite de 10+ casos sintéticos con geometría y densidad conocida
- Medir PR-AUC, Top-K Recall, IoU, F1 para cada caso
- Documentar en qué condiciones el solver falla
- Corregir problemas identificados

**Criterios de aceptación:**
- PR-AUC ≥ 0.7 en casos sintéticos de geometría simple
- Top-K recall ≥ 70% para K = 5% del total de voxels
- Documentación de casos donde el solver es ineficaz

---

## Fase R8 — Validación real con profesional

**Estado: PENDIENTE**

**Objetivo:** Ejecutar el flujo completo con un dataset real bien georreferenciado, revisado por un geofísico externo.

**Tareas:**
- Obtener dataset real con coordenadas absolutas correctas (no el HVC con lat/lon de Atacama para datos de BC)
- Corregir georreferenciación del HVC (lat/lon de British Columbia, no Atacama)
- Ejecutar inversión completa con el nuevo backend
- Documentar resultados en reporte de validación formal
- Revisión por geofísico externo con documento firmado

**Criterios de aceptación:**
- Dataset real con fit_level ≥ MEDIUM (normalizado_RMSE < 0.20)
- Geofísico externo firma documento de validación
- El documento no usa lenguaje del glosario prohibido

---

## Fase R9 — Frontend limpio

**Estado: PENDIENTE**

**Objetivo:** Interfaz final técnica, limpia, sin controles experimentales visibles.

**Tareas:**
- Implementar flujo guiado de 7 pantallas (Sección 9)
- Eliminar ruido visual de controles experimentales
- Agregar disclaimers en pantalla en puntos clave
- Agregar modo avanzado separado para usuarios expertos
- Ocultar o eliminar FMS, MapeoIA, MineDesign, MwdLiveLink

**Criterios de aceptación:**
- Un geofísico puede navegar el sistema sin instrucciones verbales
- Ningún módulo DEMO o PLACEHOLDER aparece sin aviso claro
- Los disclaimers son visibles y no ocultables

---

## Fase R10 — Reporte técnico defendible

**Estado: PARCIALMENTE COMPLETADO (C1-REP/C3-REP)**

**Qué existe:** Gate económico, Clase de Prioridad Relativa, Score Relativo del Target, disclaimers, favorabilidad con desglose de factores.

**Qué falta:** Sección de georreferenciación real (depende de R1), residual map exportable, formato PDF, capturas del modelo 3D con coordenadas.

---

## Fase R11 — Revisión externa

**Estado: PENDIENTE**

**Objetivo:** Validación por profesor, geofísico o ingeniero de minas.

**Tareas:**
- Identificar revisor(es) con perfil técnico apropiado
- Preparar material de presentación
- Sesión de revisión documentada
- Incorporar observaciones del revisor

**Criterios de aceptación:**
- Mínimo 2 revisores externos (geofísico + ingeniero minas)
- Documentos de revisión archivados en docs/
- Observaciones críticas documentadas y planificadas para resolución

---

## Fase R12 — Producto piloto

**Estado: PENDIENTE — NO INICIAR HASTA COMPLETAR R8/R11**

**Condiciones de entrada:**
- Validación externa completada
- Dataset real con fit_level ≥ MEDIUM
- Frontend limpio y profesional
- Reportes técnicos con disclaimers correctos

**Sin estas condiciones, R12 no comienza.**

---

# 16. Criterios de Aceptación Industrial

## Apto para demo técnica interna

Condiciones mínimas para mostrar a compañeros técnicos o al equipo de desarrollo:

- [x] Carga CSV correctamente
- [x] Reporta quality_label y georef_confidence (parcial — badge de confianza pendiente R1)
- [x] Ejecuta inversión sin error
- [x] Muestra modelo 3D con gradiente de densidad
- [x] Reporta fit_level y uncertainty_level
- [x] No tiene campos `recommendation="DRILL"` visibles en UI ni reporte
- [x] Gate económico bloquea NPV/tonelajes cuando evidencia es insuficiente
- [x] Voxel trace visible (total, almacenados, anomalías, cargados)
- [ ] MapeoIA oculta o con aviso de "en desarrollo" — verificar en QA
- [ ] FmsDashboard tiene banner de simulación — verificar en QA

## Apto para demo técnica ante profesor

Condiciones para mostrar a un profesor universitario de ingeniería o geofísica:

- [x] Todo lo anterior
- [ ] georef_confidence badge visible en UI — pendiente R1
- [x] Disclaimers en reporte HTML
- [x] Reporte HTML exportable con gate económico, prioridad relativa, score relativo
- [x] El sistema no afirma "encontrar mineral" en ningún lado
- [ ] El modelo 3D tiene slices, no solo cubos — pendiente R4
- [ ] FmsDashboard oculto o solo con banner — verificar

**Mostrar como:** "Prototipo geofísico conceptual con roadmap claro para verdad espacial."  
**No mostrar como:** "modelo industrial correcto."  
**No presentar geoespacialmente correcto** si la corrida no tiene footprint real.

## Apto para revisión profesional externa

Condiciones para revisión por geofísico o ingeniero de minas:

- [ ] Todo lo anterior
- [ ] Footprint real o declaración explícita de footprint local — requiere R1
- [ ] DEM co-registrado con footprint — requiere R3
- [ ] Elevaciones absolutas de voxels — requiere R3
- [ ] Residual map exportable — requiere R4
- [ ] Reporte HTML completo con todas las secciones de la Sección 12 — requiere R1/R4
- [ ] Dataset real con fit_level ≥ MEDIUM — requiere R8
- [x] MS-x con scale_status y best_iter visibles en reporte
- [x] Favorabilidad con desglose de factores visible

## Apto para piloto controlado

Condiciones para uso con un cliente piloto real (bajo NDA):

- [ ] Todo lo anterior
- [ ] Validación externa firmada por geofísico
- [ ] Docker funcional en máquina externa
- [ ] Auth mínima (al menos contraseña básica)
- [ ] Política de datos del cliente documentada
- [ ] Licencia del proyecto definida
- [ ] Datos del cliente aislados por cliente

## NO apto para uso comercial (condiciones actuales)

- Sin validación de campo real
- Sin validación profesional externa
- Sin autenticación de usuarios
- Sin verdad espacial completa (footprint real)
- Aliases legacy en JSON persistido (`recommendation`, `risk_level`, `probability`) no formalmente deprecados
- Sin tests automatizados
- Sin CI/CD
- MS-x sin convergencia verificada en datos reales

---

# 17. Preguntas para el Profesor

Al presentar el proyecto a un profesor universitario, se recomienda preguntar proactivamente:

## Sobre datos mínimos requeridos

1. ¿Qué densidad mínima de puntos considera razonable para una inversión gravimétrica 3D de utilidad práctica?
2. ¿Hay datasets gravimétricos públicos de calidad conocida que pueda recomendar para validación académica?
3. ¿El dataset HVC (251 puntos, 50×50 km, aerogravimétrico regional) es representativo para demostrar el sistema?

## Sobre georreferenciación

4. ¿Es aceptable que un modelo gravimétrico opere en coordenadas locales sin anclaje geográfico?
5. ¿Qué nivel de exactitud en el footprint del survey considera mínimo para una interpretación geológica básica?
6. ¿La proyección equirectangular local que usa el sistema es suficiente o se requiere pyproj para extensiones > 50 km?

## Sobre visualización

7. ¿Cómo evaluaría la calidad de la visualización 3D para una presentación académica?
8. ¿Los slices de sección X/Y/Z son suficientes para evaluar la geometría de un cuerpo anómalo?
9. ¿Qué información adicional esperaría ver en un modelo de inversión gravimétrica antes de opinar sobre él?

## Sobre geofísica

10. ¿Qué piensa del enfoque LSQR + Tikhonov 3D para inversión gravimétrica a escala de prototipo?
11. ¿El focusing Minimum Support (MS-x) le parece apropiado para este contexto?
12. ¿Qué tipo de corrección topográfica esperaría ver en un sistema que procesa surveys en terreno accidentado?
13. ¿Cuáles son los errores más comunes que ve en inversiones gravimétricas mal aplicadas?

## Sobre minería

14. ¿Hasta qué punto podría ser útil un score de favorabilidad exploratoria computado solo desde gravimetría?
15. ¿Qué información adicional sería necesaria para que una herramienta como esta sea útil en exploración minera real?

## Sobre lenguaje peligroso

16. ¿Hay expresiones o conceptos en la demostración que le parezcan potencialmente engañosos?
17. ¿Los disclaimers actuales son suficientemente claros para el nivel de audiencia al que apunta el sistema?

## Sobre qué validar primero

18. ¿Qué le parece lo más importante a mejorar para que el sistema sea técnicamente defendible?
19. ¿Estaría disponible para una segunda revisión cuando se hayan corregido los problemas identificados?

---

# 18. Qué Mostrar y Qué No Mostrar al Profesor

## MOSTRAR sin reservas (actualizado post-C1/C5)

- **Flujo CSV → análisis → inversión → modelo 3D**: mostrar la cadena completa con el dataset sintético o HVC.
- **Auto-grid**: mostrar que el sistema calcula automáticamente block_size, nx, ny, nz.
- **Análisis de calidad**: mostrar quality_label, duplicados, outliers, unidades.
- **Voxel trace**: mostrar total_voxels, stored_voxels, anomaly_voxels, returned_voxels — muestra transparencia del proceso.
- **Modos full/anomaly/exploration**: mostrar selector de modo de datos 3D y resultados cualitativamente diferentes.
- **Guardrails de lenguaje**: mostrar que la UI ya no usa "Probabilidad de mineralización", "PERFORAR AQUÍ" ni "Risk Level LOW".
- **Clase de prioridad relativa**: mostrar que el sistema usa lenguaje técnico correcto.
- **Economía bloqueada**: mostrar que cuando favorabilidad=12.2/100, el reporte HTML no muestra NPV ni tonelajes — el gate funciona.
- **Fit_level y RMSE**: mostrar que el sistema sabe cuándo un resultado es de baja confiabilidad.
- **Score de favorabilidad con penalizaciones**: mostrar que el score baja cuando la calidad es mala.
- **Safety labels de MS-x**: mostrar que el sistema declara las limitaciones del focusing.
- **Trazabilidad**: mostrar que cada corrida tiene project_id/run_id y que los artefactos son recuperables.
- **Disclaimer en pantalla y reporte**: mostrar que el sistema se presenta honestamente.
- **Infraestructura y documentación**: mostrar Docker con healthcheck, /health endpoint, READMEs.
- **Roadmap**: mostrar que hay un plan técnico claro para las fases siguientes, especialmente R1.
- **El Documento HVC**: mostrar que el sistema fue validado operativamente y que el resultado fue honestamente LOW.

## NO MOSTRAR como autoridad técnica

- **FMS/flota de camiones**: es una simulación. No mostrar como telemetría real.
- **NPV y LOM**: son sobre proxies heurísticos, no datos reales. No mostrar sin disclaimers prominentes; el gate debería bloquearlos en corridas HVC.
- **Diseño de mina**: los parámetros son conceptuales. No mostrar como diseño real.
- **Gravimetría cuántica**: este término no debe aparecer en ninguna presentación.
- **"Mineral confirmado"**: nunca mostrar esto.
- **MapeoIA**: es un placeholder vacío. No mostrar.
- **AnomalyEnvelope como isosuperficie física**: es un bounding box visual, no una isosuperficie calculada.
- **Cubos como modelo final**: son la visualización actual (modo debug), no la visualización profesional objetivo.
- **El resultado HVC como validación geológica**: es solo validación operativa del pipeline.
- **El modelo 3D como georreferenciado**: mientras no exista footprint real, el modelo no tiene posición geográfica absoluta defensable.

## Cómo presentar ante el profesor

**Presentar como:** "Prototipo geofísico conceptual con roadmap claro para verdad espacial. Muestra el flujo completo con transparencia técnica. La semántica está limpiada. La economía está bloqueada cuando la evidencia es insuficiente. Lo que sigue es R1 — footprint real."

**No presentar como:** "modelo industrial correcto", "solución geoespacial completa", "herramienta lista para exploración real".

---

# 19. Backlog de Eliminación y Ocultamiento

Los siguientes elementos deben ocultarse o eliminarse de la UI antes de cualquier demo externa:

## Ocultar de la navegación principal

| Elemento | Acción | Razón | Estado |
|----------|--------|-------|--------|
| MapeoIA/NLP | Ocultar de nav | Placeholder vacío; NLP no implementado | PENDIENTE — verificar en QA |
| FmsDashboard | Ocultar o banner permanente | No es telemetría real | PENDIENTE — verificar en QA |
| MineDesignView | Ocultar hasta datos reales | Parámetros son proxies | PENDIENTE |
| MwdLiveLink | Ocultar o label prominente | Math.sin() no es sensor | PENDIENTE |

## Eliminar o contextualizar en la UI

| Elemento | Acción | Estado |
|----------|--------|--------|
| Campo `recommendation = "DRILL"` visible en UI | COMPLETADO en C1-REP/C2-FE — ya no visible | CERRADO |
| Campo `probability` visible como probabilidad real en UI | COMPLETADO en C1-REP/C2-FE — contextualizado como score relativo | CERRADO |
| Campo `risk_level = "LOW"` visible en UI | COMPLETADO en C1-REP/C2-FE — ya no visible como riesgo | CERRADO |
| NPV/tonelajes sin gate económico | COMPLETADO en C3-REP/C3-FE — gate bloquea cuando evidencia insuficiente | CERRADO |
| Aliases legacy en JSON persistido | Siguen presentes internamente; no visibles en UI/reporte | PENDIENTE — auditoría y deprecación formal |
| AnomalyEnvelope sin disclaimer | Agregar tooltip "Envelope visual, no isosuperficie física" | PENDIENTE |
| Toggle manual de MS-x | Eliminar (MS-x siempre activo) | PENDIENTE |
| Parámetros manuales de grilla en UI | Mover a modo avanzado | PENDIENTE |

## Textos legacy a corregir

- Cualquier referencia a "gravimetría cuántica"
- Cualquier referencia a "probabilidad de X%" en UI visible
- Cualquier "Drill" sin caveats en UI visible
- Cualquier "industrial" sin validación
- Cualquier "preciso" sin validación

---

# 20. Backlog Técnico Completo

## COMPLETADO / PARCIAL — post-C1/C5

| Tarea | Fase | Estado |
|-------|------|--------|
| Saneamiento semántico backend (priority_class, relative_target_score, model_reliability_level) | C1-BE | COMPLETADO |
| Saneamiento semántico reporte HTML | C1-REP | COMPLETADO |
| Saneamiento semántico frontend (eliminar labels peligrosos visibles) | C2-FE | COMPLETADO |
| Gate económico/minero reporte HTML (_check_economic_gate) | C3-REP | COMPLETADO |
| Gate económico/minero frontend (store + evaluateEconomicGate) | C3-FE | COMPLETADO |
| .gitignore raíz | C4 | COMPLETADO |
| /health endpoint | C4 | COMPLETADO |
| docker-compose.yml con healthcheck, CORS, env explícitas | C4 | COMPLETADO |
| READMEs (backend, frontend, raíz, Docker, local) | C4 | COMPLETADO |
| Voxel trace en /block-model (total/stored/anomaly/returned/mode) | C5.1 | COMPLETADO |
| Voxel trace en GeoDashboard | C5.1 | COMPLETADO |
| Fix carga histórica (setShow3D + setActiveRun en ProjectRunList) | C5.1 | COMPLETADO |
| Selector de modo datos 3D (exploration/full/anomaly) | C5.2 | COMPLETADO |
| Host volume conceptual (HostVolume en Scene3D, store, BottomControls) | C5.3/C5.4 | COMPLETADO |
| Grupo geológico estático (sin Float de drei) | C5.4 | COMPLETADO |

## P0 — Bloqueante (hacer antes de cualquier demo externa)

| Tarea | Archivos | Descripción |
|-------|----------|-------------|
| Verificar ocultamiento MapeoIA | `app/layout.tsx` o nav | Confirmar que no aparece en navegación |
| Banner FmsDashboard | `FmsDashboard.tsx` | Confirmar banner no removible de simulación |
| Auditar aliases legacy en JSON persistido | `services/`, `schemas/` | `probability`, `recommendation`, `risk_level` en JSONs persistidos |
| BUG: pit_design_schema fallback | `schemas/pit_design_schema.py` | Fallback silencioso a `block_model_001.parquet` — eliminar |

## P1 — R1: Contrato espacial real

| Tarea | Archivos | Descripción |
|-------|----------|-------------|
| Schema ProjectFootprint | Nueva schema backend | Objeto footprint para todo proyecto |
| Modificar coordinate_transform_service | `coordinate_transform_service.py` | Emitir footprint con tipo y confianza |
| Endpoint /project-footprint | Nueva API | Retornar footprint con confidence |
| georef_confidence en report.json | `report.json` output | Campo de confianza de georreferenciación |
| UTM zone validation | `csv_analysis_service.py` | Requerir zona UTM si CSV es UTM |
| Badge georef_confidence en frontend | Frontend | Color por nivel NONE/LOW/MEDIUM/HIGH |

## P2 — Mejoras técnicas core

| Tarea | Archivos | Descripción |
|-------|----------|-------------|
| 4 tests pytest mínimos | `tests/` | LSQR, MS-x, LG, block_model_store |
| structlog en servicios críticos | `geophysics_service.py`, otros | Migrar print() a logging estructurado |
| Slices en Scene3D | `Scene3D.tsx` | Modo slices como default (R4) |
| Colorbar y leyenda | `Scene3D.tsx` | Leyenda de densidad con valores (R4) |
| DEM co-registro con footprint | `terrain_api.py` | Cargar DEM exactamente sobre footprint (R3) |
| Elevación absoluta de voxels | `block_model_store.py` | Columnas `surface_elevation_m`, `voxel_elevation_m` (R3) |
| Residual map exportable | `report_api.py` | Mapa 2D de residuals como PNG |

## P3 — Futuro

| Tarea | Descripción |
|-------|-------------|
| Magnetometría | Segunda fuente geofísica (R6) |
| Geología superficial | Capa de litología como restricción |
| Densidades medidas | Calibración del modelo |
| IP 3D | Detección de sulfuros |
| Inversión conjunta | Cross-gradient gravimetría + magnetometría |
| IA interpretativa | Agentes que razonan sobre resultados |
| Auth JWT | Autenticación de usuarios |
| Multi-usuario | PostgreSQL + roles |
| CI/CD | GitHub Actions |
| Isosuperficies | Marching cubes + GLB (R5) |
| Diseño de mina v2 | Desde modelo con footprint real |

---

# 21. Riesgos Existenciales

Los siguientes factores pueden impedir que TerraQuantum se convierta en un prototipo técnico serio:

## RE-1 — No conseguir validación profesional externa (MÁXIMO)

Sin un geofísico o ingeniero de minas externo que valide el enfoque técnico, el sistema no tiene credibilidad ante ningún actor relevante (universidad, minera, consultora). La validación puede ser informal (revisión de un académico), pero debe existir y estar documentada.

**Mitigación:** Identificar revisores antes de construir más funcionalidades. Preparar demo post-R1.

## RE-2 — No tener datos reales bien georreferenciados (ALTO)

El único dataset real probado (HVC) fue configurado con coordenadas de Atacama en lugar de British Columbia. El resultado fue fit_level=LOW y MS-x no convergió. Sin un dataset real con georreferenciación correcta, no se puede afirmar que el sistema funciona en condiciones reales.

**Mitigación:** Corregir la georreferenciación del HVC. Buscar datasets públicos de calidad (Geoscience Australia, USGS, Geoscience BC).

## RE-3 — Prometer más de lo que se puede demostrar (ALTO)

Si alguien presenta TerraQuantum como "software que encuentra mineral" o "gravimetría cuántica con 90% de precisión", la credibilidad del proyecto colapsa en la primera revisión técnica seria. Esto puede ocurrir en una presentación a inversores o en una entrevista universitaria.

**Mitigación:** Usar la definición oficial de la Sección 2 en todas las presentaciones.

## RE-4 — Mala georreferenciación destruye la visualización (ALTO)

Si el modelo 3D muestra voxels en una posición geográfica incorrecta (el caso HVC con Atacama en lugar de BC), cualquier análisis visual es inválido. Un geofísico notará esto inmediatamente.

**Mitigación:** Implementar Fase R1 (contrato espacial real) antes de cualquier demo a profesionales.

## RE-5 — Usar solo gravimetría como base de negocio (MEDIO-ALTO)

La gravimetría sola tiene ambigüedad equivalente inherente. Un competidor que ofrezca gravimetría + magnetometría + geoquímica tendrá siempre más credibilidad.

**Mitigación:** Implementar Fase R6 (magnetometría) y posicionar el sistema como plataforma de integración multi-dato.

## RE-6 — Visualización poco técnica (MEDIO)

Un modelo 3D con cubos de colores sin escala, sin coordenadas y sin leyenda no es creíble ante un geofísico. La presentación visual es tan importante como la calidad del cálculo.

**Mitigación:** Implementar Fase R4 (modelo 3D profesional) con slices, colorbar, escala y coordenadas.

## RE-7 — Aliases legacy no deprecados producen confusión futura (MEDIO)

Los campos `recommendation="DRILL"`, `risk_level="LOW"`, `probability` siguen en los JSON persistidos. Si un consumidor futuro los lee directamente (script, API externa, análisis posterior), puede interpretar incorrectamente los resultados.

**Mitigación:** Auditar consumo de aliases. Deprecar formalmente en la siguiente fase y documentar en CHANGELOG.

## RE-8 — Construir demasiados módulos antes de validar el núcleo (BAJO-MEDIO)

FMS, diseño de mina, economía, IA: ninguno de estos módulos tiene valor si el núcleo geofísico no es defensable.

**Mitigación:** Seguir el roadmap R0-R8 en orden. No iniciar R6+ hasta completar R1-R5.

---

# 22. Decisión Final de Enfoque

## TerraQuantum debe enfocarse primero en

### 1. Verdad espacial (R1) — PRÓXIMA FASE ACTIVA
Sin footprint real y sin voxels con coordenadas absolutas, el modelo no es georreferenciado. Esta es la limitación técnica más importante y la que más limita la credibilidad ante cualquier revisión profesional.

### 2. Validación de datos (R2)
El sistema debe clasificar explícitamente cada CSV como APTO_GEORREF, APTO_CONCEPTUAL, o NO_APTO. El usuario debe saber desde el principio qué tipo de modelo va a obtener.

### 3. Inversión gravimétrica honesta (R7-R8)
El solver LSQR funciona. Hay que demostrar con datos reales bien configurados que produce resultados con fit_level ≥ MEDIUM. El caso HVC con Atacama no cuenta.

### 4. Visualización profesional (R4)
Slices con colorbar, escala, norte, coordenadas. Un geofísico debe poder leer el modelo sin instrucciones.

### 5. Reporte conservador (R10)
El reporte debe decir exactamente qué se hizo, con qué calidad, qué no se puede concluir, y qué sigue. El reporte HTML post-C3 es una base sólida; requiere la sección de georef (R1) para ser completo.

### 6. Revisión profesional (R11)
Sin revisión externa, todo lo anterior no tiene credibilidad. Es el prerrequisito de cualquier uso real.

## TerraQuantum debe dejar para después

- **Diseño de mina real**: requiere datos reales, footprint real, ley medida. No antes de R8.
- **Economía (NPV, LOM)**: requiere diseño de mina sobre datos reales. No antes de R12.
- **FMS real**: requiere telemetría de campo. No en los próximos 12 meses sin socio minero.
- **IA local**: requiere que el núcleo geofísico sea sólido y que haya reportes que los agentes puedan leer.
- **Unreal Engine**: valor visual sin sustancia técnica. No es prioridad.
- **Automatización avanzada**: requiere multi-usuario y auth. No antes de PRE-PRODUCCIÓN.
- **Producto comercial**: requiere validación externa, datos reales, auth y política de datos.

## Resumen de la decisión

```
HACER AHORA:
  R0 → Completar auditoría de aliases legacy y ocultamiento de módulos demo (pendiente)
  R1 → Footprint y georef_confidence (PRÓXIMA FASE ACTIVA)
  R2 → Validador industrial de CSV

HACER PRONTO:
  R3 → DEM y elevaciones reales de voxels
  R4 → Modelo 3D profesional con slices
  R7 → Benchmark sintético riguroso
  R8 → Validación real con dataset bien configurado

HACER CUANDO EL NÚCLEO ESTÉ VALIDADO:
  R5 → Isosuperficies
  R6 → Magnetometría
  R9 → Frontend limpio final
  R10 → Reporte técnico completo
  R11 → Revisión externa

HACER SOLO DESPUÉS DE R11:
  Diseño de mina real
  Economía
  FMS real
  Multi-dato completo
  Producto comercial (R12)
```

---

## Declaración final

TerraQuantum no es un software industrial. Es un prototipo técnico ambicioso construido por un estudiante de segundo año. Eso es exactamente lo que debe ser, y es un logro genuino.

Las fases C1-C5 completadas son correcciones reales: el lenguaje peligroso visible fue eliminado, el gate económico funciona, el voxel trace es transparente, la infraestructura es sólida. Pero estas correcciones no resuelven el problema central: el modelo no sabe en qué parte del mundo está.

Para convertirse en algo más, necesita:
1. Decir la verdad sobre lo que puede hacer.
2. Demostrar que el núcleo matemático funciona con datos reales bien configurados.
3. Tener a un profesional externo que lo valide.
4. Mostrar la anomalía en el lugar correcto del mundo.

Eso, y no los módulos de FMS o economía, es lo que separa un prototipo técnico serio de un demo visual.

---

*Documento actualizado por: Claude Code — Auditoría completa de arquitectura post-C1/C5*  
*Fecha actualización: 2026-05-19*  
*Versión: 1.1*  
*Próxima actualización recomendada: Al completar la Fase R1 o antes de cualquier demo externa profesional.*
