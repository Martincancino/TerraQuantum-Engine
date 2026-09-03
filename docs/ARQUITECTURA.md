# ARQUITECTURA TÉCNICA — TerraQuantum Engine

**Versión:** post-Fase-19 · **Fecha:** 2026-08-27  
**Estado del sistema:** 74% de madurez técnica estimada  
**Convención de ejes canónica (Fase 19):** `x_m=Este · y_m=Profundidad↓ · z_m=Norte`

> Este documento es la fuente de verdad de la arquitectura del sistema. Se actualiza al cerrar cada fase. Leerlo antes de editar cualquier módulo de física, pipeline de datos, orquestador o frontend.

---

## Índice

1. [Visión General](#1-visión-general)
2. [Convención de Ejes y Unidades](#2-convención-de-ejes-y-unidades)
3. [Motor Físico](#3-motor-físico)
4. [Pipeline de Ingesta](#4-pipeline-de-ingesta)
5. [Orquestador y API](#5-orquestador-y-api)
6. [Frontend y Render 3D](#6-frontend-y-render-3d)
7. [SDK Python](#7-sdk-python)
8. [Sistema de Veredictos (B1, B2, B3)](#8-sistema-de-veredictos-b1-b2-b3)
9. [Persistencia y Formatos de Exportación](#9-persistencia-y-formatos-de-exportación)
10. [Bugs Abiertos por Dominio](#10-bugs-abiertos-por-dominio)
11. [Constantes Críticas](#11-constantes-críticas)

---

## 1. Visión General

TerraQuantum es una plataforma de inversión geofísica exploratoria 3D para datos de **gravimetría** y **magnetometría**. Es local-first (desktop), sin servidor en la nube, con stack:

| Capa | Tecnología | Entrada/Salida |
|------|-----------|----------------|
| **Motor físico** | Python puro · NumPy · SciPy | Observaciones → modelo 3D de densidad/susceptibilidad |
| **Backend** | FastAPI · Uvicorn | REST API · paquetes TQPKG · Parquet |
| **Frontend** | Next.js 16 · React 19 · TypeScript · React-Three-Fiber | UI desktop + visor 3D |
| **SDK scripting** | Python (`terraquantum` package) | Scripting sin red (in-process) |
| **Desktop wrapper** | Tauri (Rust) | Instalador nativo Windows |

### Flujo General

```
CSV crudo
   ↓
[analyze-columns] → plan de mapeo + sugerencias (NUEVO-7: sugerencias no se muestran en UI)
   ↓
[parse-rows] → filas parseadas (Python, no JS)
   ↓
[enrich-package] → TQPKG con correcciones gravimétricas aplicadas
   ↓
[load-package] → inversión → block_model.parquet
   ↓
[Frontend] → visor 3D · isosuperficies · cortes · DOI overlay · exportación OMF
```

---

## 2. Convención de Ejes y Unidades

### Convención Canónica (definida en `docs/11_CONVENCION_DE_EJES.md`)

| Slot interno | Significado | Signo | Formato UBC-GIF |
|-------------|-------------|-------|-----------------|
| `x_m` · Eje 0 · `nx` | **Este** (Easting) | + al Este | `n_east` |
| `y_m` · Eje 1 · `ny` | **Profundidad** | **+ hacia abajo** | `n_z` (UBC mide Z↑, TQ mide Y↓) |
| `z_m` · Eje 2 · `nz` | **Norte** (Northing) | + al Norte | `n_north` |

**Orden Fortran en memoria:** `ix + nx·iy + nx·ny·iz`  
**Permutación UBC-GIF:** `(n_east=nx, n_north=nz, n_z=ny)` — ver `export_service.py:684`  
**Permutación OMF:** `(u=Este, v=Norte, w=Arriba)` — TQ exporta transponiendo y negando `y`

### Unidades

| Magnitud | Unidad interna | Conversión en kernel |
|----------|---------------|---------------------|
| Densidad | t/m³ | × 1000 → kg/m³ antes de G·V |
| Gravedad | m/s² → mGal | × 1e5 en frontend |
| Susceptibilidad | SI (adimensional) | — |
| Anomalía magnética | nT | — |
| Coordenadas | metros (m) | — |

### ACAD-1 — Bug de Ejes Magnéticos (Cerrado Fase 19)

El vector de campo geomagnético **antes de la corrección** usaba `(cos I·cos D, sin I, cos I·sin D)` asumiendo `x=Norte`. La convención correcta con `x=Este` es:

```
f̂ = (cos I · sin D,   sin I,   cos I · cos D)
```

**Impacto medido en Chile (I=-30°, D=2°):**  
`error_rms_sobre_señal = 1.45` · Pearson `r = -0.05` · misfit 1% → 51.6% · error horizontal 30m → 150m

---

## 3. Motor Físico

### Jerarquía de Módulos

```
exploration/
├── protocols.py          (115L) — ForwardOperator, Solver como typing.Protocol
├── potential_field_core.py  (884L) — núcleo compartido, sigma, weights
├── gravimetry.py          (~4000L) — GravimetryForward, GravimetryInversion
├── magnetometry.py        (~3200L) — MagnetometryForward, MagnetometryInversion
├── implicit_modeling.py   — HRBF, prior litológico
└── checkerboard_test.py   — QA de resolución espacial
```

### `protocols.py`

**`ForwardOperator` (typing.Protocol):**
- `_build_sparse_kernel(x_c, y_c, z_c, sensor_coords) → scipy.sparse.csr_matrix`
- `supports_nonuniform_mesh: bool`

**`Solver` (typing.Protocol):**
- `solve(...) → dict` con campos: `density_full`, `relative_score_full`, `misfit_percent`, `normalized_sensitivity`

### `potential_field_core.py` — Núcleo Compartido

**Estimador Hutchinson (`hutchinson_diag_inv`):**  
Calcula `diag(A⁻¹)` estocásticamente con sondas Rademacher (+1/-1). Usa LSMR + Woodbury.

**Sigma Adaptativo (`_sigma_adaptive`):**  
Cuando `noise_floor=0.02` y `noise_pct=0.02` (valores sentinel), estima ruido con diferencias finitas 2D en malla Delaunay. Piso: `1e-4`. Outliers: `|d - median| > 3 MAD`.

**Pesos de Profundidad (Li & Oldenburg 1996):**  
`W_z = diag((depth + z0)^(-beta/2))`  
- Gravedad: `beta=0.5`, `z0 = 0.5·dy`  
- Magnetometría: `beta=1.5`, `z0 = 0.5·dy`

### `gravimetry.py` — `GravimetryForward`

**Partición campo cercano / lejano:**
- Umbral: `r = min(4.0 · a_eq, cutoff_radius)` donde `a_eq = sqrt(dx² + dy² + dz²)`
- **Cercano:** Prisma exacto Nagy (1966), función `_nagy_prism_safe`
- **Lejano:** Masa puntual: `G · V · 1000 · dy / r³`

**Implementación:** Caché de geometría (size=1 · `np.array_equal`) · `ThreadPoolExecutor` · aborta si pares > 0.6×RAM

**ACAD-0 (Cerrado Fase 17):** La corrección de terreno calculaba el módulo de la atracción en vez de la componente vertical. Error de 200× a 1 km. Ahora usa: `Δh² / (r·s·(r+s))` (columna en forma analítica cerrada).

**NUEVO-1 (Cerrado Fase 23):** La inversión **conjunta** pasaba `topography_elevations=None` fijo a los dos motores: la cota del CSV no tocaba la física (mismo modelo bit a bit con y sin ella) y el **15,93 %** del contraste recuperado caía en celdas de aire. Ahora la superficie llega a las dos físicas —los bloques de acoplamiento se recortan al espacio del solver, como ya se hacía con la poda observable— y el reporte publica `topography_used`, `topography_degraded` y `warnings[]`, igual que las otras dos rutas. La preparación de la superficie vive ahora en `services/geo_utils.py::prepare_topography_from_elevations`, una sola vez para las tres.

### `gravimetry.py` — `GravimetryInversion`

**Laplaciano 3D:**
- Uniforme: diferencias finitas estándar
- No-uniforme (TreeMesh): `w_ij = 2 / (h_i + h_j)`

**Selección de λ:**  
L-Curve de Morozov, barrido logarítmico buscando χ²_reducido ≈ 1

**IRLS ("compact"):**  
Foco `f_i = 1/sqrt(c_i² + eps²)` — itera hasta convergencia

**Distribución bimodal (medida — 24 semillas):**  
33% de corridas en régimen baseline producen ~170m de error. El sistema reporta `('MEDIUM', 'LOW', False)` en ambos casos. `Spearman(χ², PR-AUC) = 0.073`.

### `magnetometry.py` — `MagnetometryForward`

**Dipolo (Bhattacharyya 1964, Sharma 1966):**  
`near_field_mode="dipole"` en producción. H-39 (abierto): `near_field_mode="prism"` ignorado.

**MVI:** `build_mvi_kernels` calcula `gx`, `gy`, `gz`. Declinación efectiva: medias circulares + `atan2(Mx, Mz)`.

### `magnetometry.py` — `MagnetometryInversion`

**Cambio de variable:** `m_tilde = W_z · m`  
**Padding:** `padding_kappa = 1e5` — evita aglomeración de susceptibilidad en bordes  
**Solvers:** n_active < 2500 → LSMR+TRF (bounds duros) · n_active ≥ 2500 → LSQR+clip+FISTA

### `implicit_modeling.py` — HRBF

**Sistema HRBF:** `[K P; P^T 0] [alpha; a] = [phi; n]` · kernel cúbico `r³`  
**Invariante:** Si φ es constante → `L·m_ref = 0` → inversión idéntica a sin prior  
**Integración (Fase 14):** `λ_spatial · (L · m_ref)` en el funcional del solver

---

## 4. Pipeline de Ingesta

### Flujo Completo (CSV → TQPKG)

```
1. analyze-columns   → SniffReport + ColumnMappingPlan + suggestions
2. parse-rows        → filas parseadas (Python, no JS — bug coma decimal)
3. enrich-package    → correcciones gravimétricas + DEM + IGRF → TQPKG
4. load-package      → inversión
```

### Correcciones Gravimétricas (en orden)

| N° | Corrección | Referencia | Estado |
|----|-----------|-----------|--------|
| 1 | Pre-reducciones: marea (Longman 1959) + deriva | Estampas `time_utc` + estación base | Opcional |
| 2 | Latitud (GRS80) | Moritz 1980 — IUGG | Siempre |
| 3 | Free-Air | Heiskanen & Moritz 1967, fórmula 3-57 | Siempre |
| 4 | Bouguer Simple (ρ=2.67 g/cm³) | Hinze et al. 2005 | Siempre |
| 5 | Terreno (Fase 17) | `Δh²/(r·s·(r+s))` | Opcional (apply_terrain=True default) |

### Detección de Roles de Columna

**Fuzzy matching:** `Anomalía Bouguer (mGal)` → `anomaliabouguermgal`  
**Heurística de rango:** Si el slot `y_m` tiene valores ~1e6 → sospecha de Northing UTM  
**H-F11-1 (Cerrado Fase 16):** Con cabecera `X,Y,Z` = easting, northing, cota → el northing pasaba como profundidad

### Viabilidad Espacial (`SpatialReadiness`)

| Nivel | Desbloquea |
|-------|-----------|
| `NO_SPATIAL_DATA` | Solo exploración conceptual |
| `LOCAL_UNANCHORED` | Inversión con ACKNOWLEDGE |
| `UTM_WITH_ZONE` / `GEOGRAPHIC_COORDS` | DEM, exportación con coordenadas |
| `PROFESSIONAL_SURVEY` | Todos los features |

### Schemas Clave (`geophysics_schema.py`)

| Campo | Default | Rango | Nota |
|-------|---------|-------|------|
| `density_min` | `0.0` | — | Variable de régimen, no default roto. Contraste efectivo = `density_min - base_density`. No visible en UI (Fase 20 lo expone). |
| `density_max` | `5.5` | — | Cubre magnetita, cromita |
| `base_density` | `2.6` | `1.0`–`6.0` | No viaja desde la UI (medido Fase 20); sí por la API directa. Desde la **Fase 22** la exportación resta ESTE valor, no un literal, y viaja en `inputs.json` y en el manifiesto del ZIP |
| `inclination_deg` | `-30.0` | — | Default Chile |
| `declination_deg` | `2.0` | — | Default Chile |
| `regularization_norm` | `"L2"` | `"L2"/"compact"` | L2=smoothness, compact=cuerpos nítidos |
| `magnetization_model` | `"scalar"` | `"scalar"/"vector"` | vector=MVI para remanencia |

---

## 5. Orquestador y API

### Endpoints Principales

| Endpoint | Método | Descripción |
|---------|--------|-------------|
| `/v2/gravity-import/analyze-columns` | POST | Sniff + plan de mapeo |
| `/v2/gravity-import/parse-rows` | POST | Parsing canónico |
| `/v2/gravity-import/enrich-package` | POST | TQPKG con correcciones |
| `/v2/gravity-import/load-package` | POST | Inversión (sync o async) |
| `/v2/geophysics-invert` | POST | Inversión directa |
| `/v2/depth-estimate` | POST | Euler + espectro radial |
| `/export/*` | GET | Bundles ZIP, OMF, reportes |

**Rate limits (Slowapi):** 10/min inversiones · 30/min parseo  
**Problema:** No emite `Retry-After` en 429. SDK mitiga con backoff ciego.

### Flujo `run_geophysics_inversion`

```
1. Validación (gates: espacial R06, regional, cobertura)
2. Forward operators (GravimetryForward / MagnetometryForward)
3. Restricciones de sondajes
4. Prior geológico implícito (si implicit_geology en allowlist)
5. Solver (_lsqr_resolver_irls)
6. Diagnósticos (χ², misfit_percent, residuales)
7. Veredictos B1, B2, B3
8. Persistencia (Parquet + inputs.json)
```

---

## 6. Frontend y Render 3D

### Vistas

`home` · `preparacion` · `ia-chat` · `exploration3d` · `historial` · `sistema`

### Estado Global (Zustand — `useAppStore.ts`)

**Deshacible:** `sliceX/Y/Z`, `sliceAxis`, `showIsosurfaces`, `viewMode`, `visualLayer`, `clipBox`, `showMviVectors`, `jointThreshold`, `doiThreshold` + 7 más.  
**No deshacible:** `model`, `activeRun`, `modelRunKey`, datos de backend.

**Mecanismo:** Middleware de deltas (no snapshots) · Límite de historial · Barrera al cambiar archivo.

### Capas de Render

| Layer | Estado | Descripción |
|-------|--------|-------------|
| `IsosurfaceMeshLayer` | ✅ Activo | Marching Cubes del backend |
| `BoreholeLayer` | ✅ Activo | Sondajes como cilindros |
| `DoiOverlayLayer` | ✅ Activo | Velo DOI bajo horizonte de confianza |
| `VolumeRaymarchLayer` | ⚠️ **No montado** | WebGL2 ray-marching — implementado completo, visible=false |
| `SectionPaintLayer` | Condicional | Secciones transversales |

---

## 7. SDK Python

Paquete `terraquantum/` — funciona en modo in-process (sin red) usando `fastapi.testclient.TestClient`.

```python
import terraquantum as tq

paquete = tq.enrich(gravity="survey.csv", config={"utm_zone": "19S"})
corrida = tq.run_inversion(paquete, project_id="cerro_x")
corrida.save_bundle("entrega/")

# Batch
corridas = tq.batch(
    [{"name": f"s{i}", "gravity": f"surveys/s{i}.csv"} for i in range(1, 13)],
    config={"utm_zone": "19S"},
)
```

**26 símbolos exportados.** `API_VERSION = "0"` (explícitamente inestable).  
**H-F11-3 (Abierto):** `wait=True` no inscribe el run en historial SQLite (Parquet se guarda).

---

## 8. Sistema de Veredictos (B1, B2, B3)

### B3 — Veredicto Reconciliado (worst-of)

```python
# geophysics_service.py:877-881
if cb_status == "FAIL":
    levels.append(("MEDIUM", "checkerboard_resolution"))
```

El checkerboard alterna celda a celda (longitud de onda 250m, por debajo del límite físico de resolución). Retorna `pearson_r ≈ 0.116` constante en todo survey realista. **HIGH es inalcanzable por construcción** hasta ejecutar Fase 26.

**ACAD-11 (Abierto):** `NOT_RUN` no topa igual que `FAIL` (Fase 21 lo corrige).

### B2 — Profundidad (`depth_confidence`)

Índice DOI de doble inversión. `_DOI_NULLSPACE_CUTOFF = 1.0`. Medido: `LOW` en 75/75 corridas.

### B1 — Null-Space (`null_space_artifact`)

Condición: saturación total en el piso. Demasiado estrecha. Medido: `False` en 75/75, incluyendo 15 casos con PR-AUC ≤ 0.01 donde el modelo SÍ es smear del null-space.

### Secuencia Correcta para Desbloquear HIGH

**Fase 26 primero:** Checkerboard con bloques del tamaño del objetivo · gate: Spearman ≥ umbral sobre ≥75 corridas / ≥5 regímenes.  
**Fase 30 después:** Desbloquear HIGH — **solo si la Fase 26 cerró con discriminación real**.  
Subir el techo sin señal discriminante = sobreconfianza (el único cuadrante inaceptable).

---

## 9. Persistencia y Formatos de Exportación

### Parquet (Fuente de Verdad)

`PROJECTS_DIR / project_id / runs / run_id / block_model.parquet`  
Columnas: `x_m`, `y_m`, `z_m`, `density_t_m3`, `relative_score`, `is_active`, `is_null_space`, ...

`inputs.json` — configuración completa de la corrida  
`boreholes.json` — sondajes con ida y vuelta garantizada

### OMF (`omf_export_service.py`)

- `VolumeElement` — block model con atributos curados
- `PointSetElement` — estaciones (observado/calculado/residual)
- `LineSetElement` — trazas de sondaje
- `SurfaceElement` — isosuperficies

**Permutación:** `(nx_tq, ny_tq, nz_tq)` → `(nE, nN, nZ_up)` = `(nx, nz, ny)` con `origin_z = -ny*bs`

### Bundle ZIP (Entrega Cliente)

`.vtr` (VTK) · `.msh` + `.den` (UBC-GIF) · `.gslib` (SGeMS) · `report.html` · `summary.csv`

**ACAD-1c (Cerrado Fase 19):** El ZIP antes escribía cabeceras UBC-GIF incorrectas para mallas no cúbicas. Ahora permuta correctamente.

---

## 10. Bugs Abiertos por Dominio

### Motor Físico

| ID | Descripción |
|----|-------------|
| H-39 | MVI y tensor ignoran `near_field_mode="prism"`, usan dipolo siempre |
| Bimodal 33% | Sistema no puede distinguir resultado bueno de malo en régimen baseline |

### Pipeline de Datos

| ID | Descripción |
|----|-------------|
| NUEVO-7 | `suggestions` del mapeo de columnas: 0 consumidores en TypeScript |
| NUEVO-9 | El `config_hash` del manifiesto del ZIP (`_AUDIT_KEYS`) ignora `base_density`, `density_min` y `density_max`: dos corridas con roca caja distinta salen con el MISMO hash de auditoría (abierto por la Fase 22) |

### Orquestador / API

| ID | Descripción |
|----|-------------|
| ACAD-11 | `NOT_RUN` no topa igual que `FAIL` en B3 (Fase 21) |
| H-F11-3 | `run_inversion(wait=True)` no inscribe en historial SQLite |
| H-20 | Updater apunta a repositorio inexistente; fallo presentado como falta de internet |
| NUEVO-4 | `.spec` traga la excepción de OMF — instalador puede salir sin OMF sin avisar |
| NUEVO-6 | Tauri sirve en primer puerto libre 3000..3011 — localStorage se pierde si cambia el puerto |

### Frontend

| ID | Descripción |
|----|-------------|
| ~~NUEVO-2~~ | ✅ Fase 24 (09-02): el estado de preparación vive en el store (`prepContexto`/`prepParametros`/`prepAvanzado`/`prepEnriquecer`/`prepSondajes`) y sobrevive al cambio de pestaña |
| ~~NUEVO-3~~ | ✅ Fase 24 (09-02): el CSV corregido sobrevive **y** el validador local reconoce las columnas que el asistente escribe — sin lo segundo el botón del paquete quedaba apagado y el corregido no llegaba nunca |
| H-34 | Turbo en leyenda de `MultiPhysicsControls` describe colores que ya no se pintan |
| H-36 | `resultIsStale` no incluye parámetros de Fase 14 |
| VolumeRaymarch | Implementado completo pero no montado en vista clásica |

---

## 11. Constantes Críticas

| Constante | Valor | Módulo | Descripción |
|-----------|-------|--------|-------------|
| `PRECONDITIONED_OPERATING_LAMBDA` | `0.1` | `geophysics_service.py:59` | Calibrado en n_active=256, benchmark 8×4×8. **No verificado a escala regional.** |
| `_DOI_NULLSPACE_CUTOFF` | `1.0` | `geophysics_service.py` | Límite DOI para B2 |
| `padding_kappa` | `1e5` | `magnetometry.py` | Regularización de padding magnético |
| `_CHECKERBOARD_PASS_THRESHOLD` | `0.60` | `checkerboard_test.py` | Umbral inalcanzable por cualquier survey realista (Fase 26 lo recalibra) |
| `MAX_LOC` | `300` | `scripts/ci/ast_budgets.py` | Máximo LOC por función |
| `MAX_CC` | `40` | `scripts/ci/ast_budgets.py` | Complejidad ciclomática máxima |
| `MAX_ARGS` | `12` | `scripts/ci/ast_budgets.py` | Máximo argumentos por función |
| `API_VERSION` | `"0"` | `terraquantum/__init__.py` | Explícitamente inestable |

---

## Documentos de Detalle

- [`arquitectura_motor_fisico.md`](./arquitectura_motor_fisico.md) — Motor completo con fórmulas y código
- [`arquitectura_pipeline_datos.md`](./arquitectura_pipeline_datos.md) — Pipeline ingesta completo
- [`arquitectura_orquestador_api.md`](./arquitectura_orquestador_api.md) — API, veredictos, SDK, OMF
- [`arquitectura_frontend.md`](./arquitectura_frontend.md) — UI, estado, render 3D, contratos

---
*Generado 2026-08-27 | Integra lectura exhaustiva de 463 archivos Python + ~75 archivos TypeScript*
