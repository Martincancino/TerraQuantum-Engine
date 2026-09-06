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
[analyze-columns] → plan de mapeo + sugerencias (Fase 25: la sugerencia se PROPONE en el rol, se acepta a mano)
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
└── checkerboard_test.py   — tablero histórico (control; ya NO topea el veredicto)
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

**Qué invalida un resultado (Fase 25, H-36):** declarado por tipos en `componentes/prep/invalidaResultado.ts` con el mismo patrón de complemento exacto que `NO_DESHACIBLE`. El criterio es uno y comprobable: **invalida el resultado lo que cambia el paquete que se manda al backend**. La huella que dispara el aviso «resultado desactualizado» se CONSTRUYE desde esa declaración —no se escribe aparte—, y el efecto vive en `PreparacionView`, padre común de los dos flujos.

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
# geophysics_service.py — desde la Fase 30
res_level, res_meta = _resolution_signal(report_payload)   # LOW si no resuelve NADA
if bt.get("is_floor_smear"):
    levels.append(("LOW", "best_target_floor_smear"))
seal_level, seal_meta = _high_seal(report_payload)         # MEDIUM si NO sella
if seal_level is not None:                                 # None = selló, no topea
    levels.append((seal_level, "high_seal"))
# `priority_class` y `checkerboard_qa` se PUBLICAN en `components` y ya no topean.
```

**Historia del techo, en tres fases.** Hasta la 25 lo ponía el tablero: alterna celda a celda (250 m de longitud de onda en malla de 125 m), devolvía `pearson_r ≈ 0.116` constante y `FAIL` en el 100 % de las corridas ⇒ `HIGH` inalcanzable **por construcción**. La Fase 26 midió que eran **tres** causas, no una (la longitud de onda es la menor: corregirla sola llega a 0.247, con el PASS en 0.60), y lo reemplazó por `services/resolution_qa.py`. El tablero se conserva **publicado como control** (`role: historical_control_since_fase26`) y ya **no topea**.

**ACAD-11 (Cerrado, Fase 21):** `NOT_RUN` topa igual que `FAIL`.
**ACAD-10 (Cerrado, Fase 26):** el diagnóstico de resolución informa. ρ contra PR-AUC = **+0.8081** sobre 75 corridas de confirmación (`chi2_red` da **−0.0675** en el mismo conjunto).

### El sello de `HIGH` (`_high_seal`, Fase 30)

`HIGH` dejó de concederse por AUSENCIA de defectos. Hasta la Fase 29 el worst-of sólo sabía **restar** — con el techo puesto daba igual, porque nadie llegaba arriba. Al retirarlo se midió que soltarlo sin criterio positivo declaraba `HIGH` a **3 corridas de 44** con **978,4 · 636,8 · 542,1 m** de error horizontal. Dos pruebas, las dos obligatorias:

| prueba | criterio | por qué ese número |
|---|---|---|
| resolución | `shallowest_band_resolution_m` **<** `max_block_tested_m` | aprobar sólo el peldaño más grueso de la escalera es aprobar el **suelo del examen**. Condición **estructural**, no un valor: sobrevive a cambios de escalera o de tamaño de celda |
| masa de piso | `floor_mass_excess` **≤ 0.5** | el número que midió la Fase 26. Para **degradar a LOW** dejaba 12 % de margen al peor caso sano (por eso `is_floor_smear` sigue en 1.0); para **negar el nivel superior** no acusa a nadie |

**La ausencia no sella.** Falta cualquiera de los dos datos ⇒ cap a MEDIUM. Es la monotonía de la Fase 21 aplicada al nivel nuevo; sin ella un reporte vacío saldría `HIGH`.

### Perfil de resolución (`services/resolution_qa.py`, Fase 26)

Por banda de profundidad × escalera de bloques laterales: tablero que alterna en (x, z) dentro de la banda, escalado a la **amplitud de señal** (`sqrt(rms_obs² − σ²)`), con el σ **declarado**, puntuado sobre el **mapa en planta**. Salida: **longitud de resolución en metros** por banda + `resolvability_index`. Coste medido: **0.89 s** en una corrida de ~30 s.

### B2 — Profundidad (`depth_confidence`)

Índice DOI de doble inversión. `_DOI_NULLSPACE_CUTOFF = 1.0`. Medido: `LOW` en 75/75 corridas.

### B1 — Null-Space (`null_space_artifact` + `is_floor_smear`)

`is_null_space_artifact` exige saturación **total** en el piso: demasiado estrecha. Medido `False` en 75/75 del barrido y en 75/75 de la confirmación, incluidos los casos con PR-AUC ≤ 0.01 donde el modelo SÍ es smear.

**Fase 26 — `is_floor_smear`:** la versión continua. Anomalía en la banda de piso ÷ la que pondría ahí un modelo uniforme (contada en celdas); dispara con exceso > 1. Es el **único** diagnóstico medido que discrimina DENTRO de un mismo régimen: ρ mediano contra PR-AUC = **+0.71** (`chi2_red` da −0.10). En la confirmación dispara 25/75 con **0 falsos positivos** (PR-AUC máximo 0.204 entre las disparadas).

### Secuencia para Desbloquear HIGH — CERRADA

**Fase 26 — CERRADA (2026-09-03).** Gate pasado: ρ = **+0.8081** sobre 75 corridas / 15 regímenes (listones: 0.073 de `chi2_red`, 0.275 del tablero viejo).

**Fase 30 — CERRADA (2026-09-06).** El techo **no era una entrada, eran tres**, y la única declarada no era la que mandaba:

1. `high_hold_pending_fase30` — la retención honesta. Quitarla **sola no cambiaba ni uno de los 75 veredictos** del barrido de la Fase 26.
2. `priority_class` — capaba a MEDIUM **las 44 de 44** corridas MEDIUM, sin distinguir entre ellas: incluidas las de PR-AUC 1.000 y 11 m de error. Retirado del worst-of por motivo **semántico** (mide atractivo de *targeting*, no confiabilidad, y ya venía multiplicado por la calidad ⇒ la contaba dos veces); se sigue **publicando**.
3. `favorability.score ≥ 65` — el requisito de `priority_class` para llegar a HIGH. En la MEJOR corrida del barrido el score sale **44.9 con los dos multiplicadores de calidad en 1.00**: el techo estaba en la aritmética de los factores. **No se toca en esta fase** (NUEVO-15/16).

Que retirar `priority_class` es seguro está **medido**: las 3 corridas que serían SOBRECONFIADAS si `HIGH` se soltara sin criterio las cazan `survey_confidence` y `model_reliability` por su cuenta. No era quien protegía de la sobreconfianza: era quien impedía medirla.

**Gate PASADO sobre 150 corridas** (semillas frescas, tres criterios declarados antes de correr): `G1` cuadrante SOBRECONFIADO = **0** · `G2` `HIGH` en **36/150 = 24.0%** —sin este criterio el gate se cumple sin que el cambio haga nada— · `G3` nada con `resolves_anywhere=False` ni `is_floor_smear=True` supera LOW. Peor `HIGH`: **164.9 m** (línea 200 m). PR-AUC mediana **1.000** en HIGH contra **0.035** en LOW. **21** corridas habrían salido HIGH sin el sello, **9** de ellas con error > 200 m (hasta 1.337,6 m): sin el sello el gate habría FALLADO. Mutación **12/12**.

Evidencia: `validation/PREREGISTRO_2026-09-06_fase30.md` (escrito antes de medir) y `validation/HALLAZGO_2026-09-06_techo_high.md`. Gate reproducible: `py -3.14 -m validation.exp_high_ceiling`.

⚠ **ERRATA del barrido:** `baseline` y `depth_400m` son el **mismo mundo con distinto id** (misma esfera de 150 m a 400 m, mismo contraste, misma campaña) y dan resultados idénticos bit a bit. Los «15 regímenes» del barrido son **14 casos distintos**; afecta al conteo de la Fase 26, no a su ρ.

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

> **Todo lo de esta sección se re-midió el 2026-09-06 (Fase 29).** La tabla larga, con
> fecha y `ruta:línea` por fila, es §1.3 de `docs/06_AUDITORIA_TECNICA_INTEGRAL.md`.

### Puertas (CI, `check.ps1`, Playwright)

| ID | Descripción |
|----|-------------|
| NUEVO-15 | **152 pruebas escritas como gate que no ejecuta NADIE**: 56 bajo `scripts/validation/` (declaradas en `pytest.ini:2` y fuera de todo paso de CI), 57 recorridos de Playwright (`ci.yml` no menciona playwright en ningún job) y 39 tests `slow` sin paso propio. Se llevan por delante los gates de aceptación de las **Fases 11 y 14 al completo** y la mitad de recorrido de usuario de las Fases 1, 9, 10 y 13. Fase 29 |
| NUEVO-16 | `tests/test_fase3_ci_guards.py:214` existe para cazar justo eso y **sólo mira el marcador `validation` dentro de `tests/`**: no ve `slow`, ni `scripts/validation/`, ni Playwright. Fase 29 |
| NUEVO-17 | `scripts/ci/study_duplication.py:158-175` cuenta **huellas únicas**, así que re-duplicar un bloque ya compartido es invisible (**medido por mutación**: escapó). Y vigila **un** par: los tres peores de hoy son otros (72 / 67 / 64) y la auto-duplicación de `api/gravity_import_api.py` consigo mismo (**102**) no la mira nadie — el baseline la guarda vacía. Fase 29 |
| NUEVO-18 | `scripts/ci/ast_baseline.json` vigila **no-regresión**, no el criterio de la Fase 8: hoy codifica como suelo aceptado CC **181**, 8 funciones > 300 LOC y una firma de **39** argumentos. Un gate que no puede empeorar tampoco obliga a mejorar. Fase 29 |
| NUEVO-19 | `scripts/validation/f14_implicit_geology_experiment.py:333` lanza `KeyError: 'CONTROL_geologia_falsa'` — la clave no existe (los brazos son `CONTROL_falsa_suavidad` / `CONTROL_falsa_smallness`, `:264-265`). **Medido con `--seeds 1`**: hace las nueve inversiones, imprime la tabla y muere antes de escribir su JSON. La medición del criterio de aceptación de la Fase 14 **no se puede reproducir hoy**. Fase 29 |
| NUEVO-20 | **El marcador `slow` dejó de separar lo caro de lo barato.** Corrida completa medida con `py -3.14` (selección del job de PR): **2.796 pasados, 5 saltados, 0 fallos, 8.158 s = 2 h 15 min 58 s**, y **20 tests de 2.796 (0,7 %) consumen el 69 % del tiempo — ninguno marcado `slow`**. Peores: `test_fase3_joint_coupling::test_joint_padding_with_pgi_coupling` **636,9 s**, `test_fase8_3_wiring::test_uses_posterior_std_when_available` **509,9 s**, `test_project_run_flow::test_block_model_response_con_project_run` **473,7 s**. Aparte, `test_doi_calibration.py::test_doi_within_physical_range` (tampoco `slow`) hace **imposible** correr la suite entera: **> 1 h 45 min** dentro de ella y **> 45 min** en solitario sin terminar. `ci.yml` declara que ese paso cuesta «del orden de la hora». Fase 29 |
| NUEVO-21 | `tests/test_fase9_camino_de_usuario.py:36` incluye `"e2e"` en `_WEB_SCAN_DIRS`: una ruta cuyo único consumidor sea un recorrido de Playwright contaría como «tiene camino de usuario», y esos recorridos no los corre nadie. **Agujero latente y hoy vacío**: de 64 rutas, **0** dependen de eso. Arreglo de coste cero. Fase 29 |
| NUEVO-22 | `terraquantum-web/playwright.config.ts:11` dice que el build de E2E «lo hace `scripts/e2e.ps1` / el CI». El script se llama **`e2e_ui.ps1`** y **la CI no corre E2E**. Fase 29 |
| NUEVO-23 | **Los `skip` no son donde está la exclusión.** La corrida informa **5 saltados** (SimPEG ×2, `TQ_RUN_LARGE_FLOW` ×2, navegador Playwright ×1) y la verdad es que hay **56 deseleccionados**. La regresión física F9 **no aparece como skip**: sus 8 tests `validation` llevan también `slow`, así que `-m "not slow"` los deselecciona **antes** de que el `skip` de `tests/conftest.py:11-21` actúe. Un skip se cuenta y se imprime; una deselección no sale en ningún informe. Fase 29 |

### Motor Físico

| ID | Descripción |
|----|-------------|
| H-39 | MVI y tensor ignoran `near_field_mode="prism"`, usan dipolo siempre. **Re-medido por AST el 2026-09-06**: `build_mvi_kernels` (`magnetometry.py:519`) y `build_gradient_tensor_kernels` (`:629`) tienen **cero** referencias a `near_field_mode` y **cero** menciones de `prism` |
| Bimodal 33% | Sistema no puede distinguir resultado bueno de malo en régimen baseline |
| ACAD-3 | **Cerrado midiendo (Fase 29):** el operador de suavidad es de cuarto orden y la cita a Li & Oldenburg 1998 sigue siendo incorrecta, **pero cambiarlo al primer orden no mejora**: ningún criterio lo favorece en los dos mundos y la nitidez del contacto cambia de signo (0/3 sin topografía, 3/3 con ella). Queda **corregir la cita**, no el operador. `scripts/validation/f29_operador_suavidad.py` |
| ACAD-4 | **Cerrado midiendo (Fase 29):** la frontera de Dirichlet implícita **sí** aplana el modelo bajo la topografía —**−2,7 %** de amplitud en la primera banda activa, 3/3 semillas— y **no empeora la recuperación** (PR-AUC indistinguible, `pearson_r` mejor con Dirichlet 3/3). Alcance mayor del descrito: el padding incondicional (H-38) crea aire por sí solo, **2.000 de 7.200 celdas (27,8 %)** en una corrida real, así que la frontera está activa **siempre** |
| H-24 | **Sigue vivo (re-medido 2026-09-06):** `core/diagnostics_buffer.py:31` guarda la cola literal del traceback (2.000 caracteres) y `services/diagnostics_service.py:152` la escribe en el ZIP. Lo que está garantizado es que no viaja el *body*; el **mensaje** de una excepción sí puede llevar valores de celda |
| H-30 | **Sigue vivo (re-medido 2026-09-06):** el frontend deriva el contraste con roca país fija de 2,75 t/m³ en **dos** ficheros — `componentes/Scene3D.tsx:93` y `lib/terraQuantumGeology.ts:143` |

### Pipeline de Datos

| ID | Descripción |
|----|-------------|
| ~~NUEVO-7~~ | ✅ Fase 25 (09-03): la sugerencia se pinta DENTRO del selector de su rol, con el rango que la motiva y su confianza, y se acepta con un botón. Nunca se auto-aplica: el backend la emite siempre como `medium` y auto-rellenarla reabriría el defecto que cerró la Fase 16 |
| NUEVO-9 | El `config_hash` del manifiesto del ZIP (`_AUDIT_KEYS`) ignora `base_density`, `density_min` y `density_max`: dos corridas con roca caja distinta salen con el MISMO hash de auditoría (abierto por la Fase 22) |

### Orquestador / API

| ID | Descripción |
|----|-------------|
| ACAD-11 | `NOT_RUN` no topa igual que `FAIL` en B3 (Fase 21) |
| H-F11-3 | `run_inversion(wait=True)` no inscribe en historial SQLite |
| ~~H-20~~ | ~~Updater apunta a repositorio inexistente; fallo presentado como falta de internet~~ **CERRADO (Fase 28, 09-06)**: apunta al remoto real y el aviso distingue 5 desenlaces. Y no era «inexistente» — `github.com/TerraQuantum` es la cuenta de un **tercero real** (id 90737998) |
| NUEVO-13 | El repositorio es **PRIVADO** (medido: API 404 sin autenticar, `git ls-remote` sí lista ramas). Los assets de release de un repo privado no son descargables sin token ⇒ el updater dará 404 a todos los usuarios **aunque se publique**. Decisión de negocio, no técnica. Fase 28 |
| NUEVO-14 | Deriva de versión: hay tags **locales** `v0.2.0` y `v0.4.0`, `tauri.conf.json` declara `0.2.0`, y `git ls-remote --tags origin` está **vacío** (ningún tag empujado, cero releases). El workflow de release aborta si tag y config no coinciden, pero la deriva existe hoy. Fase 28 |
| ~~NUEVO-4~~ | ~~`.spec` traga la excepción de OMF — instalador puede salir sin OMF sin avisar~~ **CERRADO (Fase 27, 09-03)**: el `.spec` aborta; y no era la excepción — `collect_submodules` devuelve `[]` sin lanzar |
| NUEVO-11 | El lock es reproducible pero **no** es el entorno donde se validó la física: 37 de 105 paquetes difieren (núcleo numérico intacto). Fase 27 |
| NUEVO-12 | `check.ps1` (puerta pre-push) llama a `python` a secas: con el 3.11.9 del PATH, `deps_closure.py` da **falsa alarma**. Mismo H-23 que la Fase 27 cerró en el build. Fase 27 |
| NUEVO-6 | Tauri sirve en primer puerto libre 3000..3011 — localStorage se pierde si cambia el puerto |

### Frontend

| ID | Descripción |
|----|-------------|
| ~~NUEVO-2~~ | ✅ Fase 24 (09-02): el estado de preparación vive en el store (`prepContexto`/`prepParametros`/`prepAvanzado`/`prepEnriquecer`/`prepSondajes`) y sobrevive al cambio de pestaña |
| ~~NUEVO-3~~ | ✅ Fase 24 (09-02): el CSV corregido sobrevive **y** el validador local reconoce las columnas que el asistente escribe — sin lo segundo el botón del paquete quedaba apagado y el corregido no llegaba nunca |
| H-34 | Turbo en leyenda de `MultiPhysicsControls` describe colores que ya no se pintan |
| ~~H-36~~ | ✅ Fase 25 (09-03): la lista a mano (23 entradas) es ahora un tipo exhaustivo (`componentes/prep/invalidaResultado.ts`): **34 parámetros** declarados sobre las 4 máquinas de preparación + la rodaja del store, con el complemento escrito. Faltaban 5 que SÍ viajan al backend (`implicitGeologyParams` de la Fase 14, los dos `acknowledge_*`, `correctedFile` y `prepSondajes`), y el flujo PRINCIPAL no tenía huella ninguna |
| VolumeRaymarch | Implementado completo pero no montado en vista clásica |

---

## 11. Constantes Críticas

| Constante | Valor | Módulo | Descripción |
|-----------|-------|--------|-------------|
| `PRECONDITIONED_OPERATING_LAMBDA` | `0.1` | `geophysics_service.py:59` | Calibrado en n_active=256, benchmark 8×4×8. **No verificado a escala regional.** |
| `_DOI_NULLSPACE_CUTOFF` | `1.0` | `geophysics_service.py` | Límite DOI para B2 |
| `padding_kappa` | `1e5` | `magnetometry.py` | Regularización de padding magnético |
| `_CHECKERBOARD_PASS_THRESHOLD` | `0.60` | `checkerboard_test.py` | Del tablero histórico. Inalcanzable por cualquier survey realista |
| `PASS_PEARSON_R` | `0.60` | `resolution_qa.py` | Mismo valor, examen respondible: un survey sano saca 0.70–0.79 y uno degradado 0.03. La Fase 26 no bajó la vara, hizo el examen contestable |
| `BLOCK_LADDER_CELLS` | `(1,2,3,4,6)` | `resolution_qa.py` | Escalera de tamaños de bloque, en celdas |
| umbral de `is_floor_smear` | `> 1.0` | `geophysics_service.py` | Geométrico: «más masa en el piso de la que le toca por número de celdas». No ajustado |
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
