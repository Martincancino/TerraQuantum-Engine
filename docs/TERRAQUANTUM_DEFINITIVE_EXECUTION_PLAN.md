# TerraQuantum — Plan Definitivo de Ejecución

**Versión:** 1.0
**Fecha:** 2026-05-17
**Estado:** PLAN ACTIVO
**Reemplaza el orden de:** TERRAQUANTUM_EXECUTION_ROADMAP.md (V2)
**Fuentes:** TERRAQUANTUM_EXECUTION_ROADMAP.md (V2.0) · TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md · TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md (V1.1)

---

> **Propósito de este documento:**
> El EXECUTION_ROADMAP.md V2 define la arquitectura y los bloques de trabajo.
> Este documento define el ORDEN en que se ejecutan y los criterios exactos de cierre
> de cada etapa, en lenguaje sin ambigüedad operacional.
> No contradice el roadmap V2. Lo ordena.

---

## Filosofía guía

**Principio 1 — Física solo en el backend.**
El backend es la única fuente de cálculo físico, matemático y económico.
El frontend visualiza y consume APIs.
Ninguna línea de TypeScript implementa física, geofísica, ni fórmula económica productiva.
Esta regla es inviolable (R-02, R-07, R-V2-03).

**Principio 2 — Todo resultado lleva su nivel de certeza.**
Ningún resultado de TerraQuantum se presenta sin el nivel de certeza correspondiente
(SINTÉTICO / EXPERIMENTAL / CONCEPTUAL / DEMO / REAL).
Sin nivel de certeza declarado, el resultado no es válido y no se muestra.
Esta regla es inviolable (R-V2-01, R-V2-04, R-V2-05).

**Principio 3 — Validación externa antes de comercializar.**
TerraQuantum no se presenta a un cliente pagador, minera, consultora ni inversionista
hasta haber completado la Etapa D:
mínimo dos revisores externos independientes (un geofísico + un ingeniero de minas)
con documento de validación firmado.
Sin esto, el sistema es un prototipo técnico con nivel de madurez PROTOTIPO (ver Sección 8 del MASTER_VISION).

---

## ETAPA A — CERRAR EL FLUJO

**Objetivo de la etapa:**
Que el flujo completo CSV → inversión → modelo 3D → reporte funcione para cualquier dataset gravimétrico razonable,
sin que el usuario configure parámetros de grilla y sin deuda técnica bloqueante activa.

**Criterio de cierre de Etapa A:**
Todos los criterios de A1 y A2 marcados como completados.
El CORE-REAL-9 (HVC, 251 pts, 50×50 km, blockSize=1552 m) invierte correctamente
sin intervención manual de parámetros.

**Advertencia:** Esta etapa puede salir mal.
El backend auto-adaptativo (A1) es trabajo nuevo, no un bugfix.
Si la detección automática de sistema de coordenadas falla en casos edge,
la etapa puede tardar más de lo estimado.
No avanzar a Etapa B hasta que A1 y A2 estén cerrados.

---

### A1 — Bloque 2: Backend Auto-Adaptativo

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 2
**Prioridad:** ALTA
**Depende de:** Bloque 1 (Modelo 3D Profesional, subfases 1B-1 a 1B-6)
**Nivel de riesgo:** MEDIO — backend nuevo, múltiples rutas de entrada

**Objetivo:**
Que cualquier CSV gravimétrico razonable sea analizado y procesado automáticamente.
El usuario no configura nx, ny, nz, blockSize, ni lambda directamente.
El backend detecta, analiza, convierte y propone todos los parámetros de grilla.
Esta regla es inviolable en V2 (R-V2-03).

#### A1.1 — Análisis automático del CSV de entrada

Al recibir un CSV, el backend calcula y reporta automáticamente:

- Número de observaciones (n)
- Rango espacial (x_min, x_max, z_min, z_max) en unidades originales
- Área cubierta en km²
- Separación promedio entre puntos
- Densidad de muestreo (puntos / km²)
- Detección de duplicados (coordenadas exactas o dentro de tolerancia)
- Detección de outliers (gravedad > 3σ del rango del dataset)
- Inferencia de unidades (mGal, µGal, m/s²)
- Rango de gravedad (min, max, std, p5, p95)
- Inferencia del sistema de coordenadas (lat/lon, UTM, local en metros)

**Criterio de cierre A1.1:**
- [ ] Un CSV con 10 observaciones produce todos los campos del análisis sin error
- [ ] Un CSV con 10,000 observaciones produce todos los campos sin error
- [ ] Un CSV con duplicados genera warning explícito (no error silencioso)
- [ ] Un CSV con outliers genera warning con identificación de los puntos afectados
- [ ] Los 3 sistemas de coordenadas son inferidos correctamente en al menos 5 casos de prueba

#### A1.2 — Conversión automática al sistema de coordenadas canónico

El backend convierte automáticamente desde cualquier sistema de entrada
al sistema canónico local en metros definido en TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md:

- `x_m`: eje Este (metros desde origen del survey)
- `y_m`: eje profundidad (metros desde superficie, positivo hacia abajo)
- `z_m`: eje Norte (metros desde origen del survey)
- Origen: esquina SW del bounding box del survey

**Rutas de conversión requeridas:**
- CSV lat/lon → conversión a metros (proyección local centrada en el centroide del survey)
- CSV UTM → conversión al sistema canónico local
- CSV coordenadas locales en metros → uso directo sin conversión

**Criterio de cierre A1.2:**
- [ ] CSV con lat/lon se convierte a metros correctamente (error < 1% sobre la extensión total)
- [ ] CSV con UTM se convierte a metros correctamente
- [ ] CSV con coordenadas locales en metros pasa sin conversión
- [ ] El origen siempre es la esquina SW del bounding box, no el centroide ni otro punto

#### A1.3 — Cálculo automático de parámetros de grilla

El backend calcula y propone:

- Block size recomendado (función del rango espacial y número de observaciones)
- Grilla recomendada (nx, ny, nz) que no exceda el límite de 200,000 voxeles (R-10)
- Profundidad sugerida de inversión (función del espaciado y número de puntos)
- Resolución espacial estimada
- Calidad del dataset (ALTA / MEDIA / BAJA / INSUFICIENTE)

**Regla de límite (R-10 inviolable):** `nx × ny × nz ≤ 200,000 voxeles`
Si el auto-cálculo supera este límite, el bloque size se ajusta automáticamente hacia arriba
hasta que se respete el límite, con warning explícito al usuario.

**Caso crítico documentado — CORE-REAL-9 (HVC):**
Dataset QUEST-South Highland Valley Copper: 251 pts, survey 50×50 km.
- blockSize correcto: 1,552 m (NO 25 m — con 25 m el modelo cubre solo 800 m de los 50 km reales)
- Grilla: nx=32, ny=20, nz=32 → 20,480 voxeles
- Ratio obs/voxel = 0.012 (bajo, esperado para levantamiento aerogravimétrico regional)
- La inversión LSQR con regularización Tikhonov tolera este ratio

**Criterio de cierre A1.3:**
- [ ] CSV de 10 observaciones genera grilla auto-calculada sin ajuste manual
- [ ] CSV de 10,000 observaciones genera grilla auto-calculada sin ajuste manual
- [ ] El CORE-REAL-9 (HVC, 251 pts, 50×50 km) genera blockSize ≈ 1,552 m automáticamente
- [ ] Ningún parámetro de grilla es hardcodeado en el frontend
- [ ] Si nx × ny × nz > 200,000, el sistema ajusta automáticamente y reporta el ajuste

#### A1.4 — MS-x siempre activo como default

En V2, MS-x (Minimum Support IRLS, Portniaguine & Zhdanov 1999) no es un toggle opcional.
Es el default integrado al solver de inversión (R-V2-02).

La configuración fija validada en CORE-EXP-1 (fase 1.7C.3L.8) se mantiene sin modificación:
```
_BETA_MS = 0.01
_EPS_0   = 0.80
_EPS_MIN = 0.12
_MAX_IRLS = 10
_COOLING  = 0.90
_M_MAX    = 1.60
```

Esta configuración es inviolable (R-03) hasta que haya una nueva fase experimental documentada.

El frontend no expone toggle de MS-x. El backend siempre invierte con `enable_focusing=True`.
El reporte siempre muestra `scale_status`, `use_mode`, y `safety_labels`.

**Criterio de cierre A1.4:**
- [ ] `enable_focusing=True` es el default del endpoint `/gravity-import/invert`
- [ ] No existe toggle de MS-x en el frontend
- [ ] El reporte de toda inversión incluye `scale_status`, `use_mode`, `safety_labels`
- [ ] Si `scale_status == "INESTABLE"`, el sistema lo reporta explícitamente y lo documenta
- [ ] La configuración fija `_BETA_MS`, `_EPS_0`, etc. no fue modificada

#### A1.5 — Reporte de parámetros auto-calculados

Cada inversión genera un campo en `report.json` que explica explícitamente:

- Qué parámetros fueron auto-calculados y cómo
- El sistema de coordenadas detectado y la conversión aplicada
- El blockSize calculado y la lógica de cálculo
- La grilla resultante (nx, ny, nz) y el número de voxeles
- La profundidad máxima de inversión estimada
- La calidad del dataset
- Los warnings generados (duplicados, outliers, ajuste de grilla)

Este campo es parte de `gravity_import_metadata.json` y de la respuesta del endpoint.

**Criterio de cierre A1.5:**
- [ ] `report.json` incluye sección `auto_params` con todos los campos listados arriba
- [ ] Los warnings de duplicados y outliers aparecen en el reporte, no solo en logs
- [ ] El usuario puede ver en la UI qué parámetros se calcularon y por qué (sin configurarlos)

---

### A2 — Cerrar deuda técnica bloqueante

**Referencia:** TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md — Sección 17, 20; TERRAQUANTUM_EXECUTION_ROADMAP.md — Deuda técnica conocida
**Prioridad:** MÁXIMA — esta deuda bloquea el flujo o introduce resultados incorrectos silenciosos
**Nivel de riesgo:** BAJO-MEDIO por tarea individual

**Advertencia:** Las tareas A2.1 y A2.2 son los dos bugs más peligrosos del sistema actual.
A2.1 bloquea el 100% de las corridas cargadas desde el historial.
A2.2 puede generar un pit design sobre el modelo equivocado sin que el usuario lo sepa.
Deben resolverse antes de cualquier demo externa.

#### A2.1 — BUG R1: DatosView no llama setActiveRun (CRÍTICO)

**Archivo:** `terraquantum-web/componentes/DatosView.tsx` (~línea 489)
**Función:** `handleLoadRunModel`
**Bug confirmado:** `handleLoadRunModel` llama `setModel(backendModel)` y `setView("figura 3d")`
pero OMITE `setActiveRun`. Consecuencia: `MineDesignView.tsx` queda bloqueado
para el 100% de las corridas cargadas desde el historial.

**Efecto en cascada documentado:** Si el usuario carga un modelo desde DatosView
y luego navega a "Figura 3D", `Exploration3DView` puede ejecutar `resetExplorationState()`
al inicializar, que incluye `setModel(null)`. El usuario pierde el modelo cargado.

**Fix requerido:**
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

Verificar que `ActiveRunState` en `useAppStore.ts` acepta `source: "history"`.
Si el tipo solo tiene `"csv" | "synthetic" | "legacy"`, agregar `"history"` al union type.

**Criterio de cierre A2.1:**
- [ ] `handleLoadRunModel` llama `setActiveRun` con todos los campos requeridos
- [ ] `source: "history"` está en el union type de `ActiveRunState`
- [ ] Test manual: cargar corrida desde DatosView → ir a MineDesignView → botón habilitado
- [ ] Test manual: cargar corrida → ir a Figura 3D → modelo no se pierde

#### A2.2 — BUG R2: pit_design_schema fallback silencioso (CRÍTICO)

**Archivo:** `terraquantum-backend/schemas/pit_design_schema.py`
**Bug latente:**
```python
# Fallback silencioso — RIESGO CONFIRMADO:
file: str = "block_model_001.parquet"
```
Si `project_id`/`run_id` no resuelven a un Parquet válido,
el pit design silenciosamente usa el Parquet legacy.
Un pit design sobre el modelo equivocado es más peligroso que un error visible.

**Fix requerido:**
```python
# Opción A — sin default:
file: Optional[str] = None

# Y en pit_design_service.py:
if not request.project_id and not request.run_id and not request.file:
    raise HTTPException(
        status_code=400,
        detail="Debe proveer project_id/run_id o file explícito. "
               "No existe fallback silencioso a modelo legacy."
    )
```

**Criterio de cierre A2.2:**
- [ ] El campo `file` en `PitRequest` no tiene default a `block_model_001.parquet`
- [ ] Si no hay `project_id`/`run_id` válidos, el endpoint retorna HTTP 400 con mensaje explícito
- [ ] El fallback legacy puede usarse solo si se pasa `file` explícitamente por el usuario
- [ ] Test: llamar al endpoint sin project_id/run_id → debe retornar 400, no pit design

#### A2.3 — Scene3D: desacoplamiento de store.model vs activeRun

**Archivo:** `terraquantum-web/componentes/Scene3D.tsx`
**Deuda:** `Scene3D.tsx` lee `store.model` directamente, no `store.activeRun`.
Esto genera desfase potencial entre el modelo visible y la corrida activa
cuando el usuario navega de forma no lineal.

**Alcance del fix:**
- Verificar que `Scene3D.tsx` no lee `store.model` de forma independiente de `store.activeRun`
- Si el desfase es real y reproducible, sincronizar el modelo visual con `activeRun.runId`
- Si el desfase solo ocurre en flujos anómalos post-bug A2.1, verificar si A2.1 lo resuelve implícitamente

**Nota:** Este ítem puede marcarse cerrado si el fix de A2.1 elimina el desfase en todos los flujos de uso normales. Documentar la decisión.

**Criterio de cierre A2.3:**
- [ ] Verificado que `Scene3D.tsx` no muestra modelo de corrida diferente a `activeRun`
- [ ] O documentado explícitamente que el desfase residual es solo en flujos legacy no soportados

#### A2.4 — Logging: pasar de print() a structlog en servicios críticos

**Referencia:** R-15 (inviolable para código nuevo desde cierre de CORE-QA-0.5)
**Archivos afectados:**
- `terraquantum-backend/services/geophysics_service.py`
- `terraquantum-backend/services/pit_design_service.py`
- `terraquantum-backend/services/gravity_import_service.py`

El código legacy con `print()` se migra solo al tocarlo por otra razón
(no como tarea separada de refactor global — RA-05).
Esta tarea se ejecuta en coordinación con los fixes de A2.1 y A2.2
cuando se modifiquen los servicios afectados.

**Criterio de cierre A2.4:**
- [ ] `geophysics_service.py`: logging estructurado con structlog en rutas críticas (inversión, QA/QC, MS-x)
- [ ] `pit_design_service.py`: logging estructurado en rutas críticas (validación de request, LG, mesh)
- [ ] `gravity_import_service.py`: logging estructurado en rutas de parseo y validación
- [ ] No se usa `print()` en ningún path de inversión exitoso ni en errores

#### A2.5 — Tests pytest mínimos (infraestructura de validación automatizada)

**Referencia:** R-08, R-14 — tests corren antes de commit en código crítico
**Estado actual:** 15 scripts de validación manuales en `scripts/validation/`. Sin pytest.
**Riesgo:** Sin tests automatizados, cualquier cambio puede romper funcionalidad
sin detección hasta uso manual (Riesgo R11, severidad ALTA).

**Tests mínimos requeridos (4 tests core):**
1. `test_lsqr_inversion.py` — inversión LSQR: dataset sintético conocido → verificar RMSE < umbral
2. `test_msx_focusing.py` — MS-x IRLS: los 5 casos sintéticos validados en CORE-EXP-1 pasan
3. `test_lerchs_grossmann.py` — LG engine: dataset sintético → pit válido generado
4. `test_block_model_store.py` — persistencia: guardar/cargar corrida → datos intactos

**Criterio de cierre A2.5:**
- [ ] `pytest tests/` ejecuta sin errores en los 4 tests
- [ ] Los 4 tests cubren camino exitoso de inversión, focusing, LG y persistencia
- [ ] Los tests son ejecutables con `python -m pytest tests/` desde `terraquantum-backend/`
- [ ] Los tests no modifican `data/projects/` (usan fixtures temporales o `tmp_path`)

---

## ETAPA B — VALIDACIÓN END-TO-END

**Objetivo de la etapa:**
Verificar que el sistema completo funciona de punta a punta con un dataset real
(no sintético), documentando el resultado en un reporte de validación formal.

**Criterio de cierre de Etapa B:**
El CORE-REAL-9 (Highland Valley Copper) invierte correctamente con el backend V2.
El documento de validación HVC está redactado y archivado en `docs/`.

**Depende de:** Etapa A completada (todos los criterios de A1 y A2)

---

### B1 — Re-correr CORE-REAL-9 con el nuevo backend

**Dataset:** QUEST-South Highland Valley Copper (HVC)
- 251 puntos de observación
- Survey 50×50 km (levantamiento aerogravimétrico regional)
- Sistema de coordenadas: a verificar en CSV original
- Parámetros correctos validados: blockSize=1,552 m, nx=32, ny=20, nz=32

**Secuencia de ejecución:**

1. Cargar el CSV HVC en TerraQuantum V2 (con backend auto-adaptativo activo)
2. Verificar que el backend detecta automáticamente el sistema de coordenadas
3. Verificar que el backend propone blockSize ≈ 1,552 m (no 25 m)
4. Verificar que propone nx=32, ny=20, nz=32 (o equivalente dentro del límite de 200K voxeles)
5. Ejecutar inversión con MS-x activo (default V2)
6. Exportar `report.json`, `block_model.parquet`, `block_model_focusing.parquet`
7. Verificar `scale_status` de MS-x — registrar si es "OK", "SUPRIMIDA" o "INESTABLE"
8. Repetir con MS-x OFF (modificación temporal para comparación) — registrar diferencias
9. Generar visualización 3D en la nueva interfaz V2 (Bloque 1 completado)

**Advertencia:** El ratio obs/voxel del HVC es 0.012 (bajo para levantamiento regional).
Esto es esperado y no bloquea la inversión LSQR con regularización Tikhonov.
Sin embargo, la resolución del modelo será regional — no apta para interpretación de
cuerpos menores de ~1,500 m. Documentar esto explícitamente en el reporte.

**Criterio de cierre B1:**
- [ ] CSV HVC invierte con el backend V2 sin intervención manual de parámetros
- [ ] blockSize auto-calculado es ≥ 1,000 m (no 25 m)
- [ ] MS-x activo: inversión completa sin error, `scale_status` registrado
- [ ] MS-x OFF: inversión completa sin error (para comparación)
- [ ] Modelo 3D visible en la interfaz V2 con gradiente correcto azul→rojo
- [ ] Archivos `report.json` y `block_model.parquet` exportados y archivados con `run_id` trazable

---

### B2 — Documento de validación HVC

**Propósito:**
Documento interno que certifica que TerraQuantum V2 procesa correctamente
un dataset real de levantamiento aerogravimétrico regional.
Este documento es el antecedente técnico que se entrega a revisores externos en Etapa D.

**Contenido obligatorio del documento:**

1. **Descripción del dataset**
   - Fuente: QUEST-South British Columbia (Geoscience BC)
   - Área: Highland Valley Copper, BC, Canada
   - Número de puntos, extensión, sistema de coordenadas original
   - Método de adquisición: aerogravimétrico regional

2. **Parámetros auto-calculados por el backend V2**
   - Sistema de coordenadas detectado
   - blockSize propuesto y lógica de cálculo
   - Grilla propuesta (nx, ny, nz)
   - Calidad del dataset reportada

3. **Resultados de inversión**
   - RMSE del ajuste
   - `scale_status` de MS-x
   - Rango de densidades modeladas (min, max, p5, p95)
   - Profundidad del centro de masa de la anomalía principal

4. **Comparación MS-x ON vs MS-x OFF**
   - Diferencia en distribución espacial de la anomalía
   - Diferencia en `targeting_score` del mejor voxel
   - Evaluación cualitativa de la focalización

5. **Limitaciones explícitas**
   - Resolución del modelo limitada por el blockSize regional
   - El modelo no reemplaza estudios de factibilidad ni estimación de recursos
   - No se afirma qué mineral hay (R-V2-01)
   - Toda afirmación incluye incertidumbre explícita (R-V2-04)

6. **Nivel de certeza del módulo post-validación**
   - Declarar si la inversión escala de NIVEL 1 (SINTÉTICO) a NIVEL 2 (DATASET PÚBLICO)
   - Justificación del ascenso de nivel o documentación de por qué no aplica

**Criterio de cierre B2:**
- [ ] Documento archivado en `docs/TERRAQUANTUM_HVC_VALIDATION_V1.md`
- [ ] Todas las secciones listadas arriba están presentes y sin campos vacíos
- [ ] El documento no usa ninguna expresión del glosario prohibido
  ("mineral confirmado", "reserva", "recurso medido", "NPV bancable", etc.)
- [ ] El documento incluye el nivel de certeza declarado de la inversión post-validación

---

## ETAPA C — PREPARAR PARA MOSTRAR

**Objetivo de la etapa:**
Que el sistema esté en condiciones de ser visto por un revisor técnico externo
sin que el revisor encuentre módulos vacíos, demos sin aviso, bugs visibles,
ni infraestructura que requiera instrucciones verbales para levantar.

**Criterio de cierre de Etapa C:**
El sistema levanta con `docker compose up` en una máquina limpia.
Un revisor externo puede explorar el sistema sin asistencia técnica del dueño.
El módulo de reportes genera un reporte HTML exportable de una corrida real.

**Depende de:** Etapa B completada.

---

### C1 — Bloque 7: Reportes industriales

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 7
**Propósito:** Generar reportes técnicos exportables (HTML/PDF) que un revisor externo pueda leer y evaluar.

**Tipos de reporte a implementar en esta etapa (mínimo viable):**

1. **Reporte geofísico** — Reporte de la inversión gravimétrica:
   - `project_id`, `run_id`, fecha de corrida
   - Origen y calidad del dataset
   - Parámetros auto-calculados y justificación
   - Resultados de inversión (RMSE, fit diagnostics, rango de densidades)
   - Estado de MS-x (scale_status, use_mode, safety_labels)
   - Limitaciones explícitas y disclaimers técnicos
   - Nivel de certeza declarado

2. **Reporte de modelo 3D** — Capturas del modelo:
   - Secciones X, Y, Z del cuerpo modelado
   - Vista isométrica del modelo completo
   - Parámetros de la grilla (nx, ny, nz, blockSize)
   - Escala, norte, profundidad visible

**Requisitos de todos los reportes (inviolables):**
- project_id y run_id en el encabezado (trazabilidad)
- Origen y calidad del dataset
- Parámetros usados y por qué
- Limitaciones explícitas
- Incertidumbre cuantificada
- Disclaimers técnicos y legales
- Ninguna expresión del glosario prohibido

**Arquitectura backend:**
```
terraquantum-backend/reporting/
├── report_geophysics.py    # reporte HTML de inversión + QA/QC + fit diagnostics
└── templates/              # Jinja2 templates
```

**Endpoint:**
```
GET /export-report?project_id=X&run_id=Y&format=html
```

**Frontend:**
- Botón "Descargar Reporte Técnico" en `DatosView.tsx` y en la nueva interfaz de corrida

**Criterio de cierre C1:**
- [ ] Endpoint `/export-report` retorna HTML válido con todas las secciones requeridas
- [ ] El reporte incluye `project_id`, `run_id`, fecha
- [ ] El reporte incluye disclaimers y nivel de certeza declarado
- [ ] El reporte no usa ninguna expresión del glosario prohibido
- [ ] El botón "Descargar Reporte" es visible y funcional en la UI
- [ ] El reporte del CORE-REAL-9 (HVC) se genera correctamente

---

### C2 — Limpieza estética final

**Propósito:**
Que el sistema se vea profesional ante un revisor técnico externo.
No es UX completo — es eliminar lo que distrae o confunde.

**Lista de limpieza (derivada de los módulos en estado DEMO o PLACEHOLDER):**

1. **MapeoIA / NLP:** Ocultar la vista de la navegación principal
   (o reemplazar por placeholder honesto: "Módulo Territorio Satelital — en desarrollo.
   Disponible en versión futura.")
   NO eliminar el código — solo ocultarlo de la navegación.

2. **FmsDashboard:** Agregar banner permanente no removible:
   "SIMULACIÓN — Este módulo deriva datos del plan LOM. No es telemetría real de sensores."
   El banner no se puede cerrar. Es obligatorio (R-06 aplicado a FMS).

3. **MineDesignView:** Agregar modal bloqueante en primer acceso con lista de supuestos:
   - "grade es proxy heurístico, no ley medida"
   - "NPV es conceptual sobre supuestos editables, no bancable"
   - "LOM asume 100% de recuperación metalúrgica"
   - "El diseño no reemplaza estudio de factibilidad"
   El modal usa `localStorage` para no repetirse, pero debe mostrarse al menos una vez.

4. **AnomalyEnvelope:** Agregar tooltip o label: "Envelope visual del percentil superior de anomalía.
   No es isosuperficie calculada físicamente."

5. **MwdLiveLink:** Agregar label prominente: "SIMULACIÓN — datos generados algorítmicamente."

**Criterio de cierre C2:**
- [ ] MapeoIA no aparece en la navegación principal (o tiene aviso claro de "en desarrollo")
- [ ] FmsDashboard tiene banner permanente de simulación
- [ ] MineDesignView muestra modal de disclaimers en primer acceso
- [ ] AnomalyEnvelope tiene tooltip/label explicativo
- [ ] MwdLiveLink tiene label de simulación prominente
- [ ] Ningún módulo DEMO o PLACEHOLDER se presenta como funcionalidad real sin aviso

---

### C3 — Infraestructura presentable

**Propósito:**
Que el sistema pueda ser levantado en una máquina diferente a la del desarrollador
sin instrucciones verbales ni dependencias ocultas.

**Requisitos mínimos:**

1. **Docker Compose funcional:**
   `docker compose up` levanta backend + frontend completamente.
   Estado actual: CORE-DOCKER completado. Verificar que sigue funcional post-cambios V2.

2. **`.env.example` documentado:**
   Todas las variables de entorno requeridas están en `.env.example` con descripción.
   No hay variables requeridas que no estén en `.env.example`.

3. **README ejecutivo:**
   Un `README.md` en la raíz del repositorio que explique:
   - Qué es TerraQuantum (en 5 líneas)
   - Cómo levantar el sistema (`docker compose up`)
   - Cómo cargar el dataset demo
   - Qué esperar ver en la UI
   - Qué NO es el sistema (en 3 líneas — honestidad técnica)

4. **Seguridad mínima profesional:**
   - CORS explícito (no wildcard `*`)
   - Rate limiting: 10 req/min en `/gravity-import/invert`, 5 req/min en `/generate`
   - `.env.example` sin credenciales reales

**Criterio de cierre C3:**
- [ ] `docker compose up` levanta el sistema completo en máquina limpia
- [ ] `.env.example` documenta todas las variables requeridas
- [ ] `README.md` existe con las 4 secciones listadas arriba
- [ ] CORS no usa wildcard en producción
- [ ] Rate limiting activo en endpoints de inversión y pit design

---

## ETAPA D — VALIDACIÓN EXTERNA

**Objetivo de la etapa:**
Obtener revisión técnica independiente del sistema por parte de al menos
un geofísico y un ingeniero de minas, con documento de validación firmado.

**Por qué esta etapa es no negociable:**
Sin validación externa, TerraQuantum tiene nivel de madurez PROTOTIPO.
Un sistema con nivel PROTOTIPO no tiene credibilidad técnica frente a clientes,
mineras, consultoras ni inversionistas (Riesgo R13, severidad MUY ALTA).
La validación externa es el prerequisito de la Etapa E (decisión estratégica).

**Depende de:** Etapa C completada (sistema presentable, reporte exportable).

---

### D1 — Selección de revisores

**Perfil de los revisores requeridos:**

**Revisor 1 — Geofísico:**
- Conocimiento en gravimetría de exploración
- Experiencia con inversión 3D (cualquier software: Voxi, GRAV3D, SimPEG, o equivalente)
- Capaz de evaluar si el resultado de inversión es geofísicamente razonable
- No puede ser el dueño del proyecto ni colaborador directo
- Ideal: académico universitario (geofísica aplicada), profesional de consultora, o ex-geofísico de minera

**Revisor 2 — Ingeniero de Minas:**
- Conocimiento en diseño conceptual de minas (rajo / subterránea)
- Capaz de evaluar si los parámetros de diseño son razonables
- Capaz de confirmar si los disclaimers del módulo económico son suficientes
- No puede ser el dueño del proyecto ni colaborador directo
- Ideal: académico universitario (ingeniería en minas), profesional de consultora, o ex-planner de minera

**Fuentes posibles de revisores:**
- Profesores del área de geofísica o minas en universidades chilenas (FCFM, PUC, UNSM, etc.)
- Contactos de ingeniería en minas o consultoras geofísicas
- Red profesional del dueño del proyecto

**Criterio de cierre D1:**
- [ ] Revisor 1 (geofísico) identificado y contactado
- [ ] Revisor 2 (ingeniero minas) identificado y contactado
- [ ] Ambos revisores han confirmado disponibilidad para una sesión de revisión

---

### D2 — Sesiones de revisión

**Formato de la sesión:**
- Duración estimada: 45-90 minutos por revisor
- El dueño presenta el sistema en vivo (o graba un video si la sesión no puede ser presencial)
- El revisor hace preguntas y toma notas
- El dueño responde con honestidad técnica (no vender, no ocultar limitaciones)
- Al final, el revisor recibe el documento de validación HVC para leer por su cuenta

**Qué mostrar en la sesión:**
1. El flujo completo: CSV → inversión → modelo 3D (usando el HVC o el dataset sintético demo v1)
2. Los parámetros auto-calculados y la justificación
3. El resultado de MS-x (scale_status, use_mode)
4. El modelo 3D con gradiente de densidad
5. Los disclaimers en la UI (especialmente en MineDesignView y FmsDashboard)
6. El reporte HTML exportable
7. El documento de validación HVC

**Qué NO ocultar:**
- El nivel de certeza actual de cada módulo
- Que el sistema es un prototipo (nivel PROTOTIPO según clasificación interna)
- Que los parámetros económicos son conceptuales, no bancables
- Que MS-x está validado solo en condiciones sintéticas (NIVEL 1 EXPERIMENTAL)
- Que el sistema no reemplaza perforación, geoquímica ni estudio de factibilidad

**Criterio de cierre D2:**
- [ ] Sesión realizada con Revisor 1 (geofísico) — duración ≥ 45 min
- [ ] Sesión realizada con Revisor 2 (ingeniero minas) — duración ≥ 45 min
- [ ] El dueño tomó notas de todas las observaciones de ambos revisores

---

### D3 — Documento de validación externa firmado

**Propósito:**
Un documento que certifica que el sistema fue revisado por profesionales externos
y que las principales funcionalidades son geofísica y técnicamente razonables.

**Contenido del documento:**

1. Nombre, institución y rol del revisor
2. Fecha de la revisión
3. Versión del sistema revisada (número de versión semántica del software)
4. Dataset usado en la revisión (HVC u otro)
5. Funcionalidades evaluadas
6. Observaciones del revisor (incluyendo limitaciones identificadas)
7. Declaración del revisor: si el enfoque de inversión es geofísicamente razonable
8. Firma o confirmación por email (no requiere firma notarial — solo registro de la revisión)

**Nota honesta:**
No se pide al revisor que "certifique" el software ni que lo "apruebe" para uso industrial.
Se pide que confirme si el enfoque técnico es razonable y documente sus observaciones.
Un documento honesto con observaciones críticas es más valioso que una aprobación sin reservas.

**Criterio de cierre D3:**
- [ ] Documento de validación del Revisor 1 archivado en `docs/`
- [ ] Documento de validación del Revisor 2 archivado en `docs/`
- [ ] Ambos documentos incluyen las 8 secciones listadas arriba
- [ ] Las observaciones de los revisores han sido registradas (aunque no resueltas aún)

---

## ETAPA E — DECISIÓN ESTRATÉGICA

**Objetivo de la etapa:**
Con la validación externa completada, el dueño del proyecto decide la dirección estratégica.

**Esta etapa no tiene código.** Es una decisión humana basada en los resultados de la Etapa D.

**Depende de:** Etapa D completada (documentos de validación firmados).

---

### Opción 1 — Continuar desarrollo antes de comercializar

**Descripción:**
El dueño decide continuar desarrollando el sistema (Etapa F) antes de buscar un cliente,
inversor, o socio comercial.

**Cuándo elegir esta opción:**
- Los revisores de la Etapa D identificaron limitaciones técnicas significativas
  que deben resolverse antes de una demo comercial
- El sistema necesita Bloque 3 (satélite) o Bloque 4 (favorabilidad) para ser suficientemente
  diferenciador frente a alternativas existentes
- El dueño quiere completar la visión técnica completa de V2 antes de exponerla externamente

**Implicancias:**
- Entrar directamente a Etapa F (Expansión)
- No buscar cliente ni inversor hasta que Etapa F tenga al menos F1 y F2 completados
- El sistema queda en nivel de madurez PROTOTIPO → apunta a DESARROLLO durante la Etapa F

**Riesgo de esta opción:**
El desarrollo sin validación de mercado puede producir un sistema técnicamente sólido
que no responde a la necesidad real de clientes potenciales.

---

### Opción 2 — Buscar socio o cliente piloto con lo que hay

**Descripción:**
El dueño decide que el sistema post-Etapa D es suficientemente bueno para buscar
un primer cliente piloto, inversor o socio técnico.

**Cuándo elegir esta opción:**
- Los revisores de la Etapa D validaron positivamente el enfoque técnico
- El sistema con Bloques 1-4 ya ofrece diferenciación clara frente a herramientas existentes
- Hay un cliente concreto (consultora, junior minera, universidad) dispuesto a participar en un piloto

**Forma de un piloto:**
- Dataset real del cliente procesado en TerraQuantum (bajo NDA)
- Reporte técnico entregado al cliente con disclaimers explícitos
- Feedback del cliente documentado
- No implica licenciamiento ni pago — es validación de mercado

**Implicancias:**
- Priorizar Bloque 7 (reportes) y Bloque 6 (diseño mina sobrio) sobre Etapa F expansiva
- El cliente piloto puede ser fuente de requerimientos para Etapa F
- El sistema empieza a subir de nivel de madurez: PROTOTIPO → PRE-PRODUCCIÓN

**Riesgo de esta opción:**
Exponer el sistema prematuramente puede generar expectativas incorrectas
si los disclaimers no son lo suficientemente claros o si el cliente no tiene
el background técnico para interpretar los resultados correctamente.

**Decisión D-V2-05** (del roadmap V2) está vinculada a esta etapa:
"Primer cliente piloto (consultora / junior minera / universidad)."

---

## ETAPA F — EXPANSIÓN

**Objetivo de la etapa:**
Expandir TerraQuantum más allá de la gravimetría hacia un sistema multi-físico
con diseño minero sobrio, IA interpretativa, e infraestructura industrial.

**Esta etapa solo comienza después de la Etapa E.**
El orden interno de F1-F5 es indicativo — puede variar según la decisión estratégica
y los requerimientos del primer cliente piloto (si se eligió Opción 2 en Etapa E).

**Depende de:** Etapa E completada y decisión tomada.

---

### F1 — Magnetometría

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 5.1
**Descripción:**
Primera fuente geofísica adicional después de gravedad.
Objetivo: inversión conjunta densidad + susceptibilidad magnética.

**Por qué magnetometría primero:**
- Es la segunda fuente geofísica más utilizada en exploración minera
- Datos públicos ampliamente disponibles (Geoscience Australia, USGS, EMAG2)
- Algoritmos de inversión magnética están bien documentados en literatura académica
- La inversión conjunta gravimetría + magnetometría aumenta la resolución del modelo
  (evidence cruzada desde dos fuentes independientes — principio fundamental de V2)

**Alcance mínimo viable:**
- Importador CSV para datos magnéticos (formato básico, similar a CSV v1 gravimétrico)
- Motor de inversión magnética 3D (LSQR + regularización)
- Visualización de susceptibilidad magnética en el modelo 3D V2
- Sin inversión conjunta en primera versión — los dos modelos se muestran por separado

**Técnica futura documentada:**
Inversión conjunta con cross-gradient joint inversion.
Requiere planning separado antes de implementar.

**Criterio de cierre F1:**
No definido en este plan — se define cuando comience la Etapa F.

---

### F2 — Diseño mina sobrio

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 6
**Descripción:**
El módulo de diseño de mina vuelve como funcionalidad activa, pero desde un modelo sólido.

**Condición de entrada (inviolable):**
El diseño de mina solo se activa cuando:
- Terreno real está integrado en el modelo 3D (Bloque 1 completado)
- Cuerpo bien ubicado geoespacialmente (sistema de coordenadas canónico activo)
- Volumen y geometría estimados
- Score de favorabilidad calculado (Bloque 4 completado)
- Incertidumbre documentada (R-V2-04 activo)

**Lo que vuelve en F2:**
- Decisión conceptual rajo vs subterránea (scoring multi-criterio en `mine_method_service.py`)
- Variables de decisión: profundidad del cuerpo, tonelaje estimado, geometría, strip ratio implícito del LG,
  ángulo de pit, incertidumbre del modelo
- Output: `{ recommendation, confidence, rationale }`
- Parámetros básicos del escenario minero
- Reporte de decisión con justificación y disclaimers

**Lo que NO vuelve (inviolable hasta Bloque 6 validado — R-V2-06):**
- NPV de billones de dólares sin normalización de escala
- Tonelajes sin normalización y sin cut-off
- Diseño sobre modelo de baja resolución
- Ningún reporte muestra NPV ni tonelaje absoluto hasta que el Bloque 6 esté validado

**Criterio de cierre F2:**
No definido en este plan — se define cuando comience la Etapa F.

---

### F3 — IA interpretativa

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 8
**Descripción:**
Agentes de IA que interpretan y razonan sobre resultados del backend.
No calculan física — el backend calcula. La IA interpreta.

**Requisito arquitectónico inviolable:**
Implementar interfaz `LLMProvider` abstracta antes de la primera línea de código de IA.
Debe soportar: Claude API (Anthropic), OpenAI, modelos locales (Ollama).

**Agentes planificados:**
- Agente geofísico: interpreta corridas de inversión, genera hipótesis de tipología
- Agente satelital: interpreta índices espectrales, identifica alteración superficial
- Agente de favorabilidad: cruza evidencia geofísica + superficial
- Agente de reportes: genera narrativa técnica con disclaimers automáticos
- Agente QA/QC: detecta inconsistencias en los resultados
- Agente económico: estimaciones conceptuales desde LOM

**Prerrequisito técnico:**
CORE-8 (reportes exportables, Etapa C C1) debe estar completado.
Los agentes leen los reportes como input estructurado.

**Criterio de cierre F3:**
No definido en este plan — se define cuando comience la Etapa F.

---

### F4 — IP, EM, Geoquímica

**Referencia:** TERRAQUANTUM_EXECUTION_ROADMAP.md — BLOQUE 5.2, 5.3, 5.4
**Descripción:**
Fuentes geofísicas adicionales después de gravimetría y magnetometría.

**IP 3D (Inducción Polarizada):**
Cargabilidad para detección de sulfuros.
Muy relevante para cobre y oro asociados a sulfuros.
Técnica de inversión diferente (no puramente LSQR) — requiere planning separado.

**Geoquímica + ML:**
Para cuando existan muestras reales de campo.
El ML genera favorabilidad basada en patrones geoquímicos, no en leyes físicas profundas.
Requiere dataset de muestras de campo — no implementable sin datos reales.

**MT/EM/AEM (Electromagnéticos):**
Conductividad y resistividad.
Útil para estructuras, fluidos, sulfuros conductivos.
Implementación más compleja que magnetometría.

**Nota sobre ANT (Ambient Noise Tomography):**
Requiere red de sismómetros físicos en campo.
No implementable sin hardware real.
Queda como investigación futura sin fecha.

**Criterio de cierre F4:**
No definido en este plan — se define cuando comience la Etapa F.
El orden dentro de F4 se decide según requerimientos del cliente piloto.

---

### F5 — Infraestructura industrial

**Referencia:** TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md — Clasificación de madurez infraestructural
**Descripción:**
Elevar el sistema del nivel PROTOTIPO actual al nivel PRE-PRODUCCIÓN o PRODUCCIÓN.

**PRE-PRODUCCIÓN (objetivo mínimo de F5):**
- Tests automatizados pasando en CI/CD (GitHub Actions)
- Seguridad profesional completa (CORS explícito, rate limiting, auth básico con JWT)
- Documentación completa (README ejecutivo, demo grabada, arquitectura documentada)
- Validación externa firmada por 2+ revisores (Etapa D completada)
- Monitoreo básico (logs estructurados accesibles, health check activo)

**PRODUCCIÓN (objetivo futuro, no en este plan):**
Requiere además:
- Monitoreo activo con dashboards y alertas operativas
- Plan de respaldo y recuperación
- SLA documentado
- Auditoría periódica
- Un cliente activo con contrato

**Migración de base de datos (cuando aplique):**
- SQLite local → PostgreSQL con schema de proyectos y usuarios
- Auth con JWT + roles (geólogo, analista, admin, read-only)
- Parquets locales → S3/MinIO para almacenamiento distribuido (cuando haya más de 1 usuario activo)

**Criterio de cierre F5:**
No definido en este plan — se define cuando comience la Etapa F.

---

## INFRAESTRUCTURA TRANSVERSAL

Estas tareas no pertenecen a una etapa específica pero deben avanzar en paralelo.
Su estado actual y la prioridad de resolución están documentadas en el roadmap V2.

| Tarea | Estado actual | Etapa target | Referencia |
|-------|---------------|--------------|------------|
| Tests automatizados (pytest) | ❌ Sin pytest. 15 scripts manuales | A2.5 | R-08, R-14 |
| CI/CD (GitHub Actions) | ❌ Sin CI/CD | Etapa C | R-13 |
| Logging structlog | ❌ Usa print() en servicios críticos | A2.4 | R-15 |
| CORS explícito | ❌ Posible wildcard | C3 | Seguridad |
| Rate limiting | ❌ Sin rate limiting | C3 | Seguridad |
| `.env.example` documentado | ❓ Verificar estado | C3 | R-09 |
| Versionado semántico | ❌ Sin CHANGELOG ni tags Git | Por fase | R-13 |
| Docker Compose funcional | ✅ CORE-DOCKER completo | Verificar en C3 | — |
| README ejecutivo | ❓ Verificar estado | C3 | — |

**Reglas inviolables de infraestructura transversal:**

- **R-13:** Cada cierre de fase genera versión semántica nueva + entrada en `CHANGELOG.md` + tag Git.
- **R-14:** Tests antes de merge en código de `exploration/`, `services/`, `engine.py`.
  Aplica desde cierre de A2.5.
- **R-15:** Logging structlog en código nuevo de servicios críticos.
  Aplica desde cierre de A2.4.
- **R-10:** Grilla máxima nx × ny × nz ≤ 200,000 voxeles. Inviolable.
- **R-11:** Inversión requiere mínimo 10 observaciones. Inviolable.
- **R-12:** Todo código nuevo usa modo `project_run`, no legacy.

---

## DECISIONES NO-TÉCNICAS PENDIENTES

Estas decisiones no requieren código pero bloquean o condicionan decisiones de arquitectura y comerciales.
Tomadas del roadmap V2 (D-V2-01 a D-V2-05).

| Código | Decisión | Impacto | Cuándo decidir |
|--------|----------|---------|----------------|
| D-V2-01 | Licencia del proyecto (propietaria / MIT / Apache / híbrida) | Define si se puede compartir el código con revisores, clientes, o la comunidad | Antes de Etapa D |
| D-V2-02 | Constitución legal (SpA / EIRL / otro) | Necesaria para formalizar un contrato de piloto | Antes de Etapa E Opción 2 |
| D-V2-03 | Política de datos de clientes | Define cómo se guardan y se protegen los CSVs y modelos de clientes | Antes de Etapa D |
| D-V2-04 | Términos de acceso a imágenes satelitales privadas (ASTER, PRISMA, EnMAP) | Afecta el alcance real del Bloque 3 y de la Etapa F | Antes de F4 |
| D-V2-05 | Primer cliente piloto (consultora / junior minera / universidad) | Define el path de Opción 2 en Etapa E | Después de Etapa D |

**Recomendación:**
D-V2-01 y D-V2-03 deben resolverse antes de la Etapa D para poder entregar el documento HVC
y organizar las sesiones de revisión sin ambigüedad sobre quién puede ver qué.

---

## ORDEN CRONOLÓGICO RECOMENDADO

Las fechas son relativas al inicio de la Etapa A (Día 0 = 2026-05-17).
No son compromisos absolutos — son estimaciones de referencia.

| Hito | Fecha relativa | Condición de partida |
|------|----------------|----------------------|
| **Inicio Etapa A** | Día 0 | Decisión de comenzar |
| **A2.1 cerrado** (BUG R1 DatosView) | +2 días desde Día 0 | Ninguna — primera prioridad |
| **A2.2 cerrado** (BUG R2 pit_design_schema) | +2 días desde Día 0 | Ninguna — primera prioridad (paralelo a A2.1) |
| **A2.3 cerrado** (Scene3D desacoplado) | +4 días desde Día 0 | A2.1 cerrado |
| **A2.4 cerrado** (logging structlog) | +6 días desde Día 0 | A2.1 y A2.2 cerrados (se hace al tocar los servicios) |
| **A2.5 cerrado** (4 tests pytest mínimos) | +8 días desde Día 0 | A2.1 y A2.2 cerrados |
| **A1.1 cerrado** (análisis CSV automático) | +5 días desde Día 0 | Paralelo a A2 |
| **A1.2 cerrado** (conversión coordenadas) | +8 días desde Día 0 | A1.1 cerrado |
| **A1.3 cerrado** (cálculo grilla automático) | +10 días desde Día 0 | A1.2 cerrado |
| **A1.4 cerrado** (MS-x como default) | +11 días desde Día 0 | A1.3 cerrado |
| **A1.5 cerrado** (reporte de parámetros) | +12 días desde Día 0 | A1.4 cerrado |
| **Etapa A cerrada** | +12 días desde Día 0 | Todos los criterios A1 y A2 |
| **B1 cerrado** (CORE-REAL-9 re-corrido) | +5 días desde cierre A | Etapa A cerrada |
| **B2 cerrado** (documento validación HVC) | +3 días desde B1 | B1 cerrado |
| **Etapa B cerrada** | +8 días desde cierre A | B1 y B2 cerrados |
| **C1 cerrado** (reportes industriales) | +10 días desde cierre B | Etapa B cerrada |
| **C2 cerrado** (limpieza estética) | +5 días desde cierre B | Etapa B cerrada (paralelo a C1) |
| **C3 cerrado** (infraestructura presentable) | +8 días desde cierre B | Etapa B cerrada (paralelo a C1) |
| **Etapa C cerrada** | +12 días desde cierre B | C1, C2 y C3 cerrados |
| **D1 cerrado** (revisores identificados) | +5 días desde cierre C | Etapa C cerrada + D-V2-01 y D-V2-03 decididas |
| **D2 cerrado** (sesiones realizadas) | +15 días desde D1 | D1 cerrado (depende de agenda de revisores) |
| **D3 cerrado** (documentos firmados) | +5 días desde D2 | D2 cerrado |
| **Etapa D cerrada** | D3 cerrado | — |
| **Etapa E — Decisión estratégica** | Inmediatamente después de Etapa D | Etapa D cerrada |
| **Inicio Etapa F** | Después de Etapa E | Decisión estratégica tomada |

**Total estimado Etapas A a D:** ~55 días desde el Día 0.
**Advertencia:** El tiempo de la Etapa D depende críticamente de la disponibilidad
de los revisores externos (D2). Este es el factor de riesgo más alto del cronograma.

---

## CONFIRMACIÓN ESTRATÉGICA

Este documento es el plan activo de ejecución de TerraQuantum
desde el 2026-05-17 hasta completar la validación externa y tomar la decisión estratégica.

**Lo que este plan hace:**
- Define el orden de ejecución de los bloques del roadmap V2
- Define los criterios exactos de cierre de cada etapa
- Define qué se puede mostrar a externos (solo después de Etapa C)
- Define el prerrequisito para cualquier decisión comercial (Etapa D)

**Lo que este plan NO hace:**
- No contradice ni modifica las reglas inviolables R-01 a R-15 y R-V2-01 a R-V2-06
- No elimina ni modifica las reglas de autonomía RA-01 a RA-10
- No promete fechas absolutas — solo fechas relativas que pueden desplazarse
- No toca código del proyecto

**Reglas inviolables que este plan hereda y no puede modificar:**

```
R-01: order='F' inviolable en grillas 3D
R-02: Frontend no calcula física productiva
R-03: MS-x no se modifica sin nueva fase experimental documentada
R-04: activeRun es la única fuente de verdad de qué corrida está activa
R-05: Ningún fallback a modelo legacy puede ser silencioso
R-06: Disclaimers en módulos económicos son obligatorios
R-07: No duplicar lógica Python en TypeScript
R-08: Tests corren antes de commit en código crítico
R-09: No tocar credenciales_gee.json ni .env.local
R-10: Grilla máxima nx × ny × nz ≤ 200,000 voxeles
R-11: Inversión requiere mínimo 10 observaciones
R-12: Todo código nuevo usa modo project_run
R-13: Versionado semántico obligatorio por fase
R-14: Tests antes de merge en código crítico
R-15: Logging estructurado en código nuevo de servicios críticos

R-V2-01: El modelo 3D no muestra mineral confirmado
R-V2-02: MS-x es siempre activo — no es toggle opcional
R-V2-03: El backend auto-propone todos los parámetros de grilla
R-V2-04: Toda afirmación sobre el subsuelo incluye incertidumbre explícita
R-V2-05: Satélite = evidencia superficial. Gravimetría = evidencia subsuelo.
          TerraQuantum cruza ambas. No afirma mineral.
R-V2-06: Ningún reporte muestra NPV ni tonelaje absoluto
          hasta que Bloque 6 esté validado
```

**Próximo paso inmediato (2026-05-17):**
Iniciar Etapa A, comenzando en paralelo con:
- A2.1: Fix BUG R1 en `DatosView.tsx:handleLoadRunModel`
- A2.2: Fix BUG R2 en `pit_design_schema.py` (eliminar fallback silencioso)

Estos dos bugs son los de mayor riesgo activo en el sistema.
Resolverlos toma 2-4 días de trabajo enfocado y desbloquea el flujo completo.

---

*Fin del documento.*
*Próxima actualización recomendada al completar Etapa A o al cierre de cada etapa.*
*Este documento reemplaza el orden de prioridades del TERRAQUANTUM_EXECUTION_ROADMAP.md V2,
pero NO reemplaza su contenido técnico ni sus reglas.*
