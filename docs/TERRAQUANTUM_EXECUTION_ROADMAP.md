# TerraQuantum Execution Roadmap V2.0

**Versión:** 2.0
**Fecha:** 2026-05-16
**Estado del proyecto:** TRANSICIÓN V1→V2
**Documento maestro:** `docs/TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md`
**Estrategia geoespacial:** `docs/TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md`

---

> **Cambio de dirección estratégica V1→V2:**
> V1 tenía como núcleo el flujo CSV → esferas 3D → diseño de mina.
> V2 cambia el núcleo: el **modelo 3D geoespacial volumétrico** respaldado por terreno real,
> satélite e inversión gravimétrica es ahora el producto principal.
> El diseño de mina se reposiciona como fase posterior (Bloque 6).
> MapeoIA se elimina y se reemplaza por datos satelitales reales (Bloque 3).

---

## Historial V1 — Fases completadas

Estas fases son trazabilidad histórica del proyecto. No se eliminan.

| Código | Nombre | Descripción breve | Estado |
|--------|--------|-------------------|--------|
| CORE-DOC-0 | Organización base | Auditoría completa del código. Creación de docs maestros (MASTER_VISION + EXECUTION_ROADMAP v1). Identificación de bugs R1 y R2. | ✅ COMPLETA |
| CORE-0 | Estabilización funcional | Inversión LSQR + Tikhonov 3D operativa. Flujo CSV → inversión → 3D funcional. | ✅ COMPLETA |
| CORE-1 | Persistencia trazable | Sistema project/run con Parquets + JSONs en `data/projects/{pid}/runs/{rid}/`. | ✅ COMPLETA |
| CORE-2 | Importador CSV v1 | Formato CSV v1 documentado. Validación de headers, unidades, detección de duplicados. | ✅ COMPLETA |
| CORE-3 | Madurez semántica | Glosario técnico. Disclaimers textuales. Niveles de certeza (SINTÉTICO/EXPERIMENTAL/CONCEPTUAL/DEMO/REAL). | ✅ COMPLETA |
| CORE-EXP-1 | MS-x focusing validado | Algoritmo Portniaguine & Zhdanov (1999) implementado en `exploration/focusing.py`. Validado en 5 casos sintéticos. Config fija aprobada. | ✅ COMPLETA |
| CORE-DOCKER | Containerización | `docker compose up` levanta sistema completo. Dockerfiles backend + frontend funcionales. | ✅ COMPLETA |

---

## Estado actual del sistema

### Lo que funciona hoy

**Backend:**
- Inversión LSQR + Tikhonov 3D (`exploration/gravimetry.py`) — scipy sparse, orden Fortran. NIVEL 1 REAL.
- Focusing MS-x IRLS (`exploration/focusing.py`) — experimental aprobado, config fija validada. NIVEL 1 EXPERIMENTAL.
- Importador CSV v1 (`services/gravity_import_service.py`) — formato documentado y validado. NIVEL 1 REAL.
- Persistencia project/run (`core/block_model_store.py`) — trazable con Parquets + JSONs. NIVEL 1 REAL.
- Pit design Lerchs-Grossmann (`engine.py` + `pit_design_service.py`) — algoritmo REAL / parámetros CONCEPTUALES.
- Scheduler LOM (`scheduler.py`) — física de transporte real, inputs son proxies heurísticos. CONCEPTUAL.
- Docker Compose funcional.

**Frontend:**
- `Exploration3DView.tsx` — funcional, orquesta CSV → inversión → 3D correctamente.
- `MineDesignView.tsx` — funcional (requiere `activeRun.status === "ready"`).
- `Scene3D.tsx` — funcional, InstancedMesh, filtros, slicing visual.
- `FmsDashboard.tsx` — DEMO (temperatura por fórmula, no sensor).

### Deuda técnica conocida

- **BUG R1 (CRÍTICO):** `DatosView.handleLoadRunModel` no llama `setActiveRun`. MineDesignView queda 100% bloqueado para corridas del historial.
- **BUG R2 (CRÍTICO):** `pit_design_schema.py` tiene fallback silencioso a `block_model_001.parquet`. Puede generar pit sobre modelo equivocado sin aviso.
- Sin tests automatizados (pytest). 15 scripts de validación manuales.
- Sin CI/CD. Sin GitHub Actions.
- Logging por `print()`. Sin structlog.
- `Scene3D.tsx` lee `store.model` directamente (posible desfase respecto a `activeRun`).
- MS-x no expuesto en UI del flujo principal.
- `DatosView.tsx` monolítica (~80KB). Sin separación de responsabilidades.

### Lo que se elimina en V2

- **MapeoIA** → eliminada. Reemplazada por Satélite y Territorio real (Bloque 3).
- **Diseño Mina como módulo central** → reposicionado al Bloque 6. Solo se activa cuando el modelo 3D geoespacial está bien construido.
- **Perfil de inversión manual** (nx, ny, nz, blockSize hardcodeados) → reemplazado por backend auto-adaptativo (Bloque 2). El usuario no configura parámetros de grilla.
- **Nube de esferas como visualización principal** → reemplazada por modelo volumétrico profesional (Bloque 1).

---

## BLOQUE 0 — Documentación y reorientación

**Estado:** ✅ COMPLETADO (2026-05-16)
**Depende de:** —

### Entregables
- [x] `docs/TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md` creado
- [x] `docs/TERRAQUANTUM_EXECUTION_ROADMAP.md` actualizado a V2.0

---

## BLOQUE 1 — Modelo 3D Profesional

**Estado:** 🔴 PENDIENTE
**Prioridad:** MÁXIMA — primer entregable visible de V2
**Depende de:** Bloque 0

### Objetivo
Reemplazar la nube de esferas por un modelo 3D volumétrico profesional
comparable con software geológico industrial. El terreno real es visible.
El cuerpo modelado está correctamente ubicado bajo el terreno.
El usuario puede interactuar con cortes, opacidades, y controles de vista.

### Criterios de cierre (todos obligatorios)
- [ ] Terreno real visible (DEM con textura satelital básica)
- [ ] Cuerpo 3D volumétrico con gradiente azul→rojo por densidad
- [ ] Terreno semitransparente sobre cuerpo
- [ ] Cortes interactivos X, Y, Z
- [ ] Zoom con flechas del teclado + mouse
- [ ] Rotación con mouse
- [ ] Control de opacidad del terreno
- [ ] Control de opacidad del cuerpo
- [ ] Leyenda de densidad visible
- [ ] Norte, escala, profundidad en pantalla
- [ ] Coordenadas del cursor visible
- [ ] Modo "solo cuerpo" / "terreno + cuerpo" / "solo terreno"
- [ ] MS-x siempre activo (no opción, sino default)
- [ ] Naming de corridas (el usuario nombra el CSV antes de invertir)
- [ ] Eliminación de corridas desde pantalla de Datos
- [ ] Módulos irrelevantes ocultos o eliminados (FMS demo, MapeoIA)

### Subfases
- **1B-1:** Diagnóstico y limpieza del frontend actual. Qué eliminar, qué esconder, qué reorganizar antes de construir el nuevo modelo 3D.
- **1B-2:** Implementar terreno real (DEM desde coordenadas lat/lon).
- **1B-3:** Modelo volumétrico (reemplazar esferas por mesh/voxel render).
- **1B-4:** Controles profesionales (zoom, rotación, opacidad, cortes).
- **1B-5:** Naming y gestión de corridas (nombre antes de invertir, eliminar desde Datos).
- **1B-6:** MS-x como default en inversión (no toggle opcional).

### Deuda técnica que esta fase cierra
- BUG R1: `DatosView` sin `setActiveRun` (se resuelve en 1B-1)
- BUG R2: `pit_design_schema` fallback silencioso (se resuelve en 1B-1)
- Figura 3D vacía con datos reales (fill rate bajo)
- Perfil de inversión hardcodeado a 25m
- Sin naming de corridas
- Sin eliminar corridas

### Restricciones
- No instalar dependencias sin aprobación explícita.
- Frontend y backend en iteraciones separadas (salvo quirúrgico aprobado).
- No tocar `credenciales_gee.json`, `.env.local`, `data/`, `public/models/`.

---

## BLOQUE 2 — Backend Auto-Adaptativo

**Estado:** 🔴 PENDIENTE
**Prioridad:** ALTA
**Depende de:** Bloque 1

### Objetivo
Que cualquier CSV gravimétrico razonable sea analizado automáticamente
sin que el usuario configure parámetros de grilla.

### Al recibir un CSV, el backend calcula automáticamente:
- Número de observaciones
- Rango espacial (x_min, x_max, z_min, z_max)
- Área cubierta en km²
- Separación promedio entre puntos
- Densidad de muestreo
- Detección de duplicados
- Detección de outliers
- Unidades (mGal, μGal, m/s²)
- Rango de gravedad (min, max, std)
- Sistema de coordenadas inferido (lat/lon, UTM, local)
- Profundidad sugerida de inversión
- Block size recomendado
- Grilla recomendada (nx, ny, nz)
- Resolución espacial estimada
- Calidad del dataset

### Sistema de coordenadas canónico
Ver `docs/TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md`.
El backend detecta y convierte automáticamente desde cualquier
sistema al sistema canónico local en metros (x_m, y_m, z_m).

### Criterios de cierre
- [ ] CSV de 10 observaciones funciona sin ajuste manual
- [ ] CSV de 10,000 observaciones funciona sin ajuste manual
- [ ] CSV con lat/lon se convierte a metros correctamente
- [ ] CSV con UTM se convierte a metros correctamente
- [ ] CSV con coordenadas locales en metros funciona directo
- [ ] Block size se auto-calcula según extensión del survey
- [ ] MS-x siempre activo (no toggle, integrado al solver)
- [ ] Reporte explica qué parámetros se calcularon y por qué
- [ ] Ningún parámetro de grilla es hardcodeado en el frontend

---

## BLOQUE 3 — Satélite y Territorio Real

**Estado:** 🔴 PENDIENTE
**Prioridad:** ALTA
**Depende de:** Bloque 2
**Reemplaza:** MapeoIA (eliminada)

### Objetivo
Agregar evidencia superficial real al modelo 3D.
El usuario entrega lat/lon del proyecto.
TerraQuantum descarga y muestra datos reales del área.

### Fuentes primarias (gratuitas, públicas)
- **Sentinel-2** (ESA Copernicus) — imagen RGB + bandas espectrales
- **SRTM / Copernicus DEM** — terreno/topografía
- **Landsat 8/9** — backup y series temporales

### Fuentes futuras (investigar acceso)
- ASTER — alteración hidrotermal
- EMIT (NASA) — mineralogía superficial
- EnMAP — hiperspectral
- PRISMA (ASI) — hiperspectral
- LiDAR público donde exista

### Índices a calcular
- NDVI (vegetación)
- Índice de arcillas (band ratio SWIR)
- Índice de óxidos de hierro (band ratio)
- Índice de alteración hidrotermal
- Lineamientos estructurales

### Integración con modelo 3D
- Textura satelital sobre terreno DEM
- Capas activables/desactivables
- Superposición con cuerpo modelado
- Corte vertical que muestre superficie + subsuelo

### Regla de honestidad (inviolable)
> "El satélite aporta evidencia superficial.
> La gravimetría aporta evidencia del subsuelo.
> TerraQuantum cruza ambas para priorizar objetivos.
> No se afirma qué mineral hay."

### Criterios de cierre
- [ ] DEM real visible sobre el modelo 3D
- [ ] Imagen Sentinel-2 RGB proyectada sobre terreno
- [ ] Al menos 2 índices espectrales calculados y visibles
- [ ] Capas activables/desactivables independientemente
- [ ] Cuerpo modelado correctamente ubicado bajo el terreno real
- [ ] No se afirma mineral confirmado en ninguna pantalla

---

## BLOQUE 4 — Motor de Favorabilidad Exploratoria

**Estado:** 🔴 PENDIENTE
**Prioridad:** MEDIA-ALTA
**Depende de:** Bloques 2 y 3

### Objetivo
Crear un score que combine evidencia geofísica y superficial
para priorizar objetivos exploratorios.

### Nombre correcto del output
- NO usar: "probabilidad de mineral"
- SÍ usar: "score de favorabilidad exploratoria", "ranking de objetivo", "nivel de evidencia convergente"

### Evidencias a cruzar (fase inicial)
- Anomalía gravimétrica (magnitud, gradiente)
- MS-x score (focalización del cuerpo)
- Densidad modelada (contraste con background)
- Profundidad del centro de masa
- Volumen del cuerpo anómalo
- Geometría (esférica, elongada, tabular)
- Continuidad del cuerpo
- Calidad de la inversión (fit, RMSE)
- Índice de alteración superficial (Sentinel-2)
- Lineamientos estructurales
- Incertidumbre total

### Output esperado
Score entre 0 y 100 con:
- Desglose por factor
- Explicación en lenguaje simple
- Incertidumbre visible
- Recomendación de próximo paso

### Criterios de cierre
- [ ] Score calculado para cualquier corrida
- [ ] Factores mostrados con su peso individual
- [ ] Incertidumbre explicada
- [ ] No dice "mineral confirmado" en ningún lugar
- [ ] Reporte incluye score y desglose

---

## BLOQUE 5 — Multi-Física Futura

**Estado:** 🔵 PLANIFICADO (sin fecha)
**Depende de:** Bloques 1-4 completos y validados

### 5.1 Magnetometría
Primera fuente adicional después de gravedad.
Objetivo: inversión conjunta densidad + susceptibilidad magnética.
Técnica futura: cross-gradient joint inversion.

### 5.2 IP 3D
Cargabilidad para detección de sulfuros.
Muy relevante para cobre y oro asociados a sulfuros.

### 5.3 Geoquímica + ML
Para cuando existan muestras reales de campo.
El ML genera favorabilidad basada en patrones, no leyes profundas.

### 5.4 MT/EM/AEM
Conductividad y resistividad.
Útil para estructuras, fluidos, sulfuros conductivos.

### Nota sobre ANT (Ambient Noise Tomography)
Requiere red de sismómetros físicos en campo.
No es implementable sin hardware real.
Queda como investigación futura sin fecha.

---

## BLOQUE 6 — Diseño Mina (vuelve desde modelo sólido)

**Estado:** 🔵 PLANIFICADO (sin fecha)
**Depende de:** Bloques 1-4 completos

### Condición de entrada
El diseño de mina solo se activa cuando:
- Terreno real está integrado en el modelo 3D
- Cuerpo bien ubicado geoespacialmente
- Volumen y geometría estimados
- Score de favorabilidad calculado
- Incertidumbre documentada

### Lo que vuelve
- Decisión conceptual rajo vs subterránea
- Parámetros básicos del escenario
- Reporte de decisión con justificación
- Métricas con disclaimers claros

### Lo que NO vuelve
- NPV de billones de dólares sin sentido
- Tonelajes sin normalización de escala
- Diseño sobre modelo de baja resolución

---

## BLOQUE 7 — Reportes Industriales

**Estado:** 🔵 PLANIFICADO
**Depende de:** Bloques 1-4

### Tipos de reporte
- Reporte geofísico (inversión, calidad, fit)
- Reporte satelital (índices, alteración, lineamientos)
- Reporte de favorabilidad (score, factores, incertidumbre)
- Reporte de modelo 3D (capturas, secciones X/Y/Z)
- Reporte de decisión mina (cuando Bloque 6 esté activo)

### Requisitos de todos los reportes
- project_id, run_id, fecha
- Origen y calidad del dataset
- Parámetros usados y por qué
- Limitaciones explícitas
- Incertidumbre cuantificada
- Disclaimers técnicos y legales
- Capturas del modelo 3D
- Secciones verticales y horizontales

---

## BLOQUE 8 — IA Minera Local y Agentes

**Estado:** 🔵 PLANIFICADO (fase final)
**Depende de:** Bloques 1-7

### Regla fundamental
La IA no calcula la física.
El backend calcula. La IA interpreta y razona sobre resultados.

### Agentes futuros
- Agente geofísico (interpreta corridas)
- Agente satelital (interpreta índices)
- Agente de favorabilidad (cruza evidencia)
- Agente de reportes (genera narrativa técnica)
- Agente QA/QC (detecta inconsistencias)
- Agente económico (estimaciones conceptuales)

### Requisito arquitectónico
Implementar interfaz `LLMProvider` abstracta antes de la primera línea de código de IA.
Debe soportar: Claude API (Anthropic), OpenAI, modelos locales (Ollama).

---

## Reglas del proyecto (inviolables)

### Reglas V1 vigentes (de TERRAQUANTUM_MASTER_VISION_AND_ROADMAP.md)

R-01: `order='F'` (Fortran column-major) inviolable en todas las grillas 3D. Cualquier
      operación que cambie el orden de los ejes destruye la geometría del modelo.

R-02: El frontend no calcula física productiva. No hay física, matemáticas de inversión,
      ni cálculos de NPV/LOM/strip-ratio en TypeScript. Solo visualización y consumo de APIs.

R-03: MS-x no se modifica sin nueva fase experimental documentada.
      La config fija validada no se toca.

R-04: `activeRun` es la única fuente de verdad de qué modelo está activo.
      Todo módulo que cargue o use un modelo DEBE llamar `setActiveRun`.

R-05: Ningún fallback a modelo legacy puede ser silencioso.
      Si se usa un fallback, el usuario debe saberlo con mensaje explícito.

R-06: Módulos con cálculos económicos (NPV, strip ratio, LOM) requieren disclaimer
      visible en pantalla y en reporte. No opcional, no omisible.

R-07: No duplicar lógica Python en TypeScript. Si TypeScript necesita un cálculo,
      llama al backend.

R-08: Tests corren antes de commit en código de inversión/pit design (pytest).

R-09: No tocar `credenciales_gee.json` ni `.env.local`.

R-10: Grilla máxima: nx × ny × nz ≤ 200,000 voxeles. Sobre ese límite la inversión
      consume RAM inmanejable en hardware estándar.

R-11: Inversión requiere mínimo 10 observaciones.

R-12: Todo código nuevo usa modo `project_run`. El modo legacy no se extiende.

R-13: Versionado semántico obligatorio. Cada fase nueva = versión semántica nueva
      + entrada en CHANGELOG + tag Git.

R-14: Tests antes de merge en código crítico (pytest). No hay excepciones para inversión,
      pit design, ni block model.

R-15: Logging estructurado (structlog) en código nuevo de servicios críticos.
      No `print()` en servicios de geofísica, pit design, ni importación.

### Reglas V2 nuevas

R-V2-01: El modelo 3D no muestra mineral confirmado.
          Solo muestra anomalía geofísica y score de favorabilidad exploratoria.

R-V2-02: MS-x es siempre activo. No es una opción experimental ni un toggle.
          Es el default integrado al solver de inversión.

R-V2-03: El backend auto-propone todos los parámetros de grilla.
          El usuario no configura nx, ny, nz, blockSize, ni lambda directamente.

R-V2-04: Toda afirmación sobre el subsuelo incluye incertidumbre explícita.
          No se presentan resultados sin su rango de incertidumbre.

R-V2-05: El satélite aporta evidencia superficial.
          La gravimetría aporta evidencia del subsuelo.
          TerraQuantum cruza ambas. No afirma mineral.
          Esta regla debe ser visible en la UI y en todos los reportes.

R-V2-06: Ningún reporte muestra NPV ni tonelaje absoluto
          hasta que el Bloque 6 esté validado con escala real y normalización correcta.

### Reglas de autonomía para IAs

RA-01: Nunca tocar backend y frontend en la misma iteración salvo quirúrgico aprobado.
RA-02: Nivel de riesgo define modelo IA: bajo→Sonnet, medio→Sonnet/GPT-4o, alto→Opus.
RA-03: Confirmar antes de tocar archivos >300 líneas.
RA-04: No instalar dependencias sin permiso.
RA-05: No hacer refactors globales. Cambios pequeños, aislados, por fases.
RA-06: No inventar física en TypeScript.
RA-07: No modificar `data/`, `tmp/`, `public/models/` sin permiso.
RA-08: No modificar scripts `.bat` sin permiso.
RA-09: Formato obligatorio de respuesta al terminar tarea: (1) archivos modificados,
        (2) resumen de cambios, (3) qué NO se tocó, (4) comandos de validación, (5) riesgos.
RA-10: En duda, preguntar antes de ejecutar.

---

## Decisiones pendientes

D-V2-01: Licencia del proyecto (propietaria / MIT / Apache / híbrida).
D-V2-02: Constitución legal (SpA / EIRL).
D-V2-03: Política de datos de clientes.
D-V2-04: Términos de acceso a imágenes satelitales privadas (ASTER, PRISMA, EnMAP).
D-V2-05: Primer cliente piloto (consultora / junior minera / universidad).

---

## Infraestructura pendiente (deuda transversal)

Estas tareas no pertenecen a un bloque específico pero deben resolverse
en paralelo con Bloques 1 y 2:

- **Tests automatizados:** pytest con 4+ tests cubriendo LSQR, MS-x, LG, block_model_store.
- **CI/CD:** GitHub Actions ejecuta compileall + pytest + npm lint + npm build en cada push.
- **Logging:** structlog en `geophysics_service.py`, `pit_design_service.py`, `gravity_import_service.py`.
- **Seguridad mínima:** CORS explícito (no wildcard), rate limiting (10/min en inversión, 5/min en pit design), `.env.example` documentado.
- **Validación externa:** Mínimo 2 revisores independientes (geofísico + ingeniero de minas) post-Bloque 4.

---

## Próximo paso inmediato

**BLOQUE 1, Subfase 1B-1:**

Diagnóstico y limpieza del frontend actual.
Claude Code lee el estado actual del frontend y propone:
- Qué eliminar (MapeoIA, elementos FMS demo)
- Qué esconder (módulos no relevantes para V2)
- Qué reorganizar (navegación, layout, prioridades visuales)

Antes de construir el nuevo modelo 3D, el frontend debe estar limpio.
Esta subfase NO toca lógica de inversión ni backend.
Solo UI: visibilidad, navegación, eliminación de ruido visual.

**Archivos en scope para 1B-1:**
- `terraquantum-web/app/` — layout y navegación
- `terraquantum-web/components/` — componentes de UI
- `terraquantum-web/views/` — vistas principales
- DatosView.tsx — corrección BUG R1 (setActiveRun)
- NO tocar: Scene3D, inversión, backend, dependencias
