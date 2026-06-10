# MCVoxel — Plan de Desarrollo Industrial Tier 1

---

## Metadatos del Documento

| Campo | Valor |
|---|---|
| Versión | 2.1.0 |
| Fecha | 2026-06-07 |
| Autor | Chief Architect / Lead Geophysicist — MCVoxel |
| Estado | ACTUALIZADO — 13 Fases + 5 brechas adicionales identificadas |
| Basado en | Auditoría multi-agente completa + auditoría Tier-1 gaps 2026-06-07: Math Engine, Import Pipeline, Support Services, Schemas/Tests, Frontend, 3D Visualization, Data Layer, Mathematical Audit, Industry Standards, Corrections Standards, Software Comparison, Octree Mesh, PGI, Remanencia, Validación Externa. Revisión v2.1: verificación de código fuente (auth.py, gravimetry.py, treemesh.py, gravity_import_api.py, async_api.py); 5 brechas no cubiertas por el plan original identificadas: auth multi-tenant, async queue wiring, drift/tidal/formatos de campo, sigma adaptivo, despliegue/operación |
| Revisión científica | Comparado contra UBC-GIF GRAV3D, Oasis Montaj VOXI, SimPEG 0.21, Li & Oldenburg (1998), Astic & Oldenburg (2019), Portniaguine & Zhdanov (1999), Farquharson & Oldenburg (2003) |

---

## 1. Resumen Ejecutivo

### Visión

MCVoxel es un sistema de inversión gravimétrica y magnética 3D para exploración minera. Su visión es convertirse en el primer motor de inversión geofísica de nivel industrial accesible desde el navegador, equivalente a UBC-GIF GRAV3D en rigor matemático, con un UX moderno que elimina la curva de aprendizaje de 2-3 semanas que tienen los paquetes de escritorio tradicionales.

### Estado Actual — Diagnóstico Honesto

El sistema tiene una arquitectura end-to-end funcional: CSV → inversion LSQR → parquet → visualización 3D instanciada en WebGL. Los fundamentos estructurales son correctos. Sin embargo, el motor matemático contiene errores que producen modelos geológicamente incorrectos en producción:

1. **Error crítico de correcciones**: No se aplica ninguna corrección geofísica (Free-Air, Bouguer, Terreno, Latitud) antes de la inversión. Para levantamientos de campo en los Andes a 3000-4000 m de elevación, el efecto no corregido es de 600-1540 mGal, entre 100 y 10,000 veces la amplitud de las anomalías de interés. Todos los modelos producidos de datos de campo sin corregir son geológicamente sin sentido.

2. **Error de depth weighting**: El exponente beta se aplica como `1/(z+z0)^2` cuando Li & Oldenburg (1998) prescriben `1/(z+z0)^(beta/2) = 1/(z+z0)^1` para gravedad. El resultado es que todas las fuentes se colocan 2× más superficiales que la profundidad real.

3. **Lambda no calibrado a escala**: lambda=3.0 fue calibrado con n_obs=49, n_active=256. En producción con n_active=14,000 la suavidad efectiva es 2,800× menor que la de calibración. Los modelos de producción están severamente sub-suavizados.

4. **Densidad máxima incorrecta para objetivos de exploración**: `density_max = 4.2 t/m³` bloquea magnetita (5.0-5.2), pirita masiva (4.5-5.0) y cromita (4.5-4.8) — los tipos de yacimientos más importantes en Chile.

### Qué Logra Este Plan

Trece fases de desarrollo que llevan el sistema de "prototipo funcional" a **Tier 1 real** — equivalente en rigor matemático a UBC-GIF GRAV3D y en capacidades a SimPEG, con las siguientes dimensiones:

**Fases 1-8 — Fundamentos industriales (plan original)**
- Pipeline completo de correcciones geofísicas (GRS80, FAC, Bouguer, Terreno vía OpenTopography)
- Reparación de todos los errores matemáticos identificados (depth weighting, lambda, bounds)
- Interfaz de validación Observed vs. Calculated (obligatoria para credibilidad científica)
- Exportación en formatos industriales (ASEG-GDF2, UBC-GIF, VTK)
- Suite de pruebas analíticas verificables contra soluciones exactas

**Fases 9-13 — Capacidades que definen Tier 1 real**
- **Fase 9**: Malla Octree/TreeMesh con resolución de celda core 15×15×20 m (vs. 100m actual) — prerequisito para resolver depósitos reales de escala mineral
- **Fase 10**: Solver escalable con compresión wavelet del Jacobiano e ILU(k) precondicionado — habilita surveys de >100K celdas sin colapso de tiempo de cómputo
- **Fase 11**: Inversión Guiada Petrológica (PGI, Astic & Oldenburg 2019) — ancla el modelo a clases de roca con distribuciones petrográficas, elimina la no-unicidad geológica
- **Fase 12**: Remanencia Magnética — motor magnético con magnetización total J = J_ind + J_rem (ratio Q, dirección Inc/Dec); esencial para Fe-skarn, VMS y magnetita chilena
- **Fase 13**: Validación Externa Publicable — benchmark documentado contra SimPEG/UBC-GIF en el mismo dataset, verificación formal del kernel Nagy, informe de validación reproducible

> **Al completar las 13 fases**: el software es Tier 1 para exploración de escala local a intermedia (surveys hasta 30km × 30km, 500 sensores, 200K celdas activas). Para escala regional (>100K sensores, >1M celdas) se requerirán arquitecturas adicionales (GPU solver, clusters) no incluidas en este plan.

---

## 2. Mapa Completo del Sistema Actual

### 2.1 Arquitectura General

#### Backend (Python/FastAPI) — `terraquantum-backend/`

| Archivo | Propósito | Estado |
|---|---|---|
| `exploration/gravimetry.py` | Motor forward+inversión LSQR, depth weighting, kernel Nagy, UQ Hutchinson | Funciona / errores matemáticos (beta, lambda) |
| `exploration/magnetometry.py` | Motor magnético TMI, cambio de variable Li&Oldenburg | Funciona / sin corrección near-field |
| `exploration/geophysics_math.py` | Operadores gradiente finito (Dx, Dy, Dz) para cross-gradient | Funciona |
| `exploration/focusing.py` | MS-x IRLS (Portniaguine & Zhdanov 1999) post-procesado | Funciona / inconsistencia beta=1.0 vs 2.0 |
| `exploration/checkerboard_test.py` | QA checkerboard automático | Funciona / QA usa sistema distinto que producción |
| `services/geophysics_service.py` | Orquestación: validación, mesh, solver, exportación | Funciona / bug unidades (kg vs tonnes) |
| `api/geophysics_api.py` | Router FastAPI: invert, status, sweep, VTR | Funciona / sin auth, sweep síncrono |
| `api/gravity_import_api.py` | Router: preview CSV, invert CSV | ROTO: `_extract_detected_utm_zone` no definida, `math` no importado |
| `services/gravity_import_service.py` | Parser CSV, detect cols, convert units | Funciona / sin correcciones físicas |
| `services/coordinate_transform_service.py` | Proyección latlon→UTM, SW-origin shift | Parcial: UTM no reprojecta geodésicamente |
| `services/csv_analysis_service.py` | QA estadístico de observaciones | Funciona / area_km2 en degrees² si latlon |
| `services/gravity_preprocessing_service.py` | Remoción regional (polinomio 2D) | Huérfano: nunca llamado en path de producción |
| `services/grid_calculator_service.py` | Auto-grid (R-10, depth=L/3) | Funciona / heurísticas sin justificación publicada |
| `services/spatial_readiness_service.py` | Clasificación de georef por nivel | Funciona |
| `services/regional_scale_preflight_service.py` | Preflight escala regional | Funciona / inconsistencia max_nx=80 vs R10=200K |
| `services/block_model_store.py` | Persistencia filesystem (parquet, JSON, ZIP) | Funciona / DEM compartido entre runs |
| `services/elevation_enrichment_service.py` | Enriquecimiento R3: elevación MASL por voxel | Funciona / loop Python no vectorizado |
| `services/satellite_service.py` | GEE: GLO-30 DEM + Sentinel-2 | Bug: shadowing `clean_project_id`; DEM siempre re-fetch |
| `core/geo_utils.py` | BBox, footprint, DEM bilinear sampling, UTM extract | Funciona / sea-level false mock |
| `core/config.py` | Constantes globales, dirs, feature flags | Bug: GEMINI_MODEL_NAME="gemini-3.1-pro" no existe |
| `core/auth.py` | API keys SQLite (SHA-256 sin salt) | Funciona / sin pooling, sin expiración |
| `core/block_model_store.py` | Store layers de acceso a disco | Funciona / gravity usa x/y/z, magnetic usa x_m/y_m/z_m |
| `schemas/geophysics_schema.py` | Pydantic models inversión | Faltan cross-validaciones (density_min<max, len checks) |
| `schemas/gravity_import_schema.py` | Schemas import CSV | level como free str (no Literal) |
| `schemas/pit_design_schema.py` | PitRequest, SweepRequest | Sin validadores en berm_width, ramp_gradient, discount_rate |
| `scripts/` (benchmark, audit) | Tests standalone (no pytest) | No corren en CI automáticamente |

#### Frontend (Next.js/TypeScript) — `terraquantum-web/`

| Archivo / Componente | Propósito | Estado |
|---|---|---|
| `app/page.tsx` | Router de vistas | Funciona / "diseño mina" y "flota fms" dead buttons |
| `components/GravityCsvPreviewPanel.tsx` | Form upload CSV + preview + invert | Funciona / params legacy hardcodeados |
| `components/Exploration3DView.tsx` | Workspace 3D: sidebar + canvas + analytics | Funciona |
| `components/Scene3D.tsx` | Three.js InstancedMesh + terrain + clipping | Funciona / inconsistencia worker vs main thread en joint mode |
| `components/PostFX.tsx` | N8AO + Bloom + SMAA + Vignette | Funciona |
| `lib/terraQuantumGeology.ts` | Buffer builder CPU (colormaps, TRS) | Funciona / `[R08]` console.log en hot path |
| `workers/voxelBufferBuilder.worker.ts` | WebWorker buffer builder >50k voxels | Bug: joint mode falta data → voxels cyan erróneo |
| `components/DatosView.tsx` | Dashboard análisis post-inversión | Funciona / masaKg label incorrecto |
| `components/HistorialView.tsx` | Browser de runs | Funciona / sin virtualización |
| `components/IAChatView.tsx` | Chat Antigravity IA | Funciona / sin streaming, demo_project silencioso |
| `components/AnalyticsPanel.tsx` | Sidebar diagnósticos (chi², DOI, L-curve) | Funciona |
| `components/SliceControls.tsx` | Half-space slice X/Y/Z | Funciona |
| `components/BoxClipControls.tsx` | 6-plane AABB clip | Funciona |
| `components/MultiPhysicsControls.tsx` | Toggle density/susceptibility/joint | Funciona / colormap label incorrecto ("Viridis" dice, usa YlOrRd) |
| `lib/frontendApi.ts` | Todas las llamadas HTTP | 20+ endpoints / magnetometría CSV no conectada |
| `store/useAppStore.ts` | Zustand global state (~60 campos) | Funciona / `UnifiedVoxelCell` declarado pero no usado |

### 2.2 Flujo End-to-End Actual

```
[1] USUARIO selecciona archivo CSV
    → GravityCsvPreviewPanel.handleFileGravimetryChange()
    → Limpia state: gravityPreviewResult, activeRun, utmZone

[2] USUARIO hace click "Validar CSV"
    → previewGravityCsv(file, {strict, allowGRaw, previewLimit})
    → POST /api/gravity-import/preview (Next.js BFF)
    → POST /gravity-import/preview (FastAPI, 45s timeout)
    → gravity_import_api.preview_gravity_csv()
       → import_gravity_csv_v1(tmp_path)
          → pandas.read_csv(sep='[,;]')
          → _resolve_coordinate_columns() → coord_type
          → per-row: parse_float(x,z,g) + convert_to_ms2()
          → GravityObservation(x_m=raw, z_m=raw)
          → csv_analysis_service.analyze_csv_observations()
             → _infer_coordinate_system() [en raw values]
             → _build_spatial_extent() [en raw values — BUG: degrees si latlon]
             → _build_gravity_stats()
             → _detect_near_duplicates()
             → _build_outlier_info() [z-score 3σ, no elimina]
          → coordinate_transform_service.transform_coordinates()
             → latlon → pyproj UTM → SW shift
             → utm → SW shift solamente (NO geodetic reproject)
          → grid_calculator_service.compute_auto_grid()
             → block_size = mean_spacing/2
             → depth = L_max/3
             → _apply_r10() hasta voxels ≤ 200K
       → _classify_georef_full()
       → spatial_readiness_service.classify_from_csv_analysis()
       → regional_scale_preflight_service.classify_regional_scale_preflight()
       → Retorna GravityImportPreviewResponse
    ← Frontend renderiza: STATUS, metadata, warnings, georef badge,
       UTM input (si detectado), SpatialReadiness panel, RegionalPreflight panel

[3] USUARIO llena bbox opcional, UTM zone, checks de riesgo

[4] USUARIO hace click "Invertir y cargar modelo 3D"
    → handleInvert()
    → buildCsvProjectId() → "proj_TIMESTAMP_UUID"
    → setActiveRun({status:"loading"})
    → invertGravityCsv(file, {project_id, run_id, depth, nx, ny, nz, block_size,
                              cutoff_radius, lambda_mag=3.0, alpha_spatial=1.0,
                              nir=83, fe=79, region="norte_chile"})
    → POST /api/gravity-import/invert (BFF, 20 min timeout — Node http)
    → POST /gravity-import/invert (FastAPI)
    → gravity_import_api.invert_gravity_csv()
       → import_gravity_csv_v1() [repite el parse]
       → spatial readiness gate
       → regional scale gate
       → GeophysicsInvertInput Pydantic validation
       → run_geophysics_inversion(params)
          → validate_geophysics_input()
          → build_sensor_arrays() → g_observed [NO correcciones aplicadas]
          → build_tensor_mesh_with_padding(n_pad=5, pad_factor=1.3)
          → GravimetryForward._build_sparse_kernel() → G_active CSR
             → KDTree + ThreadPool
             → near-field: _nagy_prism_safe() → gz por corners
             → far-field: G*V*rho*dyv/r³
          → solve_inversion_lsqr()
             → Wd = diag(1/sigma_i), sigma = adaptive
             → column scaling Ws = diag(1/||col||)
             → depth weights: w_reg = 1/(z+z0)^2 [BUG: debería ser ^1]
             → Laplacian L_active (no-uniforme)
             → G_aug = vstack([G_scaled, λ_s*L_scaled, diag(w_small)*Ws])
             → lsqr(G_aug, d_aug, iter_lim=500)
             → m_tilde → density_contrast [clip si n>8000]
             → estimate_posterior_std() [Hutchinson 32 probes]
          → build_block_model_dataframe()
          → TargetingEngine.extract_and_export() → parquet
          → build_geophysics_report()
       → compute georef footprint (pyproj o equirectangular)
       → persist: source_gravity.csv + gravity_import_metadata.json + project_meta.json
       → _run_r3_post_inversion_enrichment() → DEM sampling por voxel
       → strip voxels del response (ya en parquet)
       → retorna GravityCsvInvertResponse

[5] FRONTEND: auto-load modelo 3D
    → getExplorationBlockModelForRun(projectId, runId)
    → GET /api/block-model?project_id=...&run_id=...&mode=exploration&limit=5000
    → GET /block-model (FastAPI)
    → build_block_model_response()
       → lee parquet → filtra → serializa → retorna JSON

[6] FRONTEND: renderizar
    → buildVoxelModelFromBackend(cells)
    → setModel(), setShow3D(true), setView("figura 3d")
    → Exploration3DView → Canvas → Scene3D
    → useLayoutEffect → updateInstancedBuffers() [<50k voxels]
    → InstancedMesh: scale, color per voxel → GPU render
    → Terrain: getTerrainData() → GEE DEM 32×32 → PlaneGeometry
```

### 2.3 API Endpoints Actuales

| Método | Ruta | Router | Función | Timeout | Auth |
|---|---|---|---|---|---|
| POST | /gravity-import/preview | gravity_import_api | preview_gravity_csv | 45s (BFF) | No |
| POST | /gravity-import/invert | gravity_import_api | invert_gravity_csv | 20 min | 10/min IP |
| POST | /geophysics-invert | geophysics_api | invert_geophysics | 120s | No |
| GET | /geophysics-status/{pid}/{rid} | geophysics_api | get_geophysics_status | 15s | No |
| POST | /geophysics-sensitivity-sweep | geophysics_api | sensitivity_sweep_geophysics | 90s (bloqueante) | No |
| GET | /export/vtr/{pid}/{rid} | geophysics_api | export_vtr | — | No |
| GET | /block-model | block_model_api | get_block_model | 120s | No |
| GET | /block-model-arrow | block_model_api | get_block_model_arrow | 120s | No |
| GET | /projects/{pid}/terrain | terrain_api | get_terrain | — | No |
| GET | /projects/{pid}/footprint | project_api | get_footprint | — | No |
| DELETE | /projects/{pid}/runs/{rid} | project_api | delete_run | — | No |
| GET | /project-runs | project_api | list_runs | 30s | No |
| GET | /project-run-detail | project_api | get_run_detail | 30s | No |
| GET | /compare-runs | project_api | compare_runs | 30s | No |
| POST | /projects | project_api | create_project | — | No |
| GET | /favorability/{pid}/{rid} | favorability_api | get_favorability | 15s | No |
| POST | /api/chat | chat_api | chat_geologist | — | No |
| POST | /async/invert | async_api | async_invert | — | No (sin frontend) |
| GET | /metrics | metrics_api | prometheus | — | No |

### 2.4 Flujo del Usuario Actual (UX)

1. Abre navegador → WelcomeScreen (animación 4s) → click "Entrar"
2. NavBar muestra 5 vistas; ve HomeView
3. Hace click en "Iniciar exploración" → navega a "figura 3d" (pero sin modelo)
4. Ve GravityCsvPreviewPanel en sidebar izquierdo
5. Selecciona archivo CSV con observaciones de gravedad
6. Configura opciones (strict, allow_g_raw) y click "Validar CSV"
7. Ve resultado de validación, badge de georef, SpatialReadiness, RegionalPreflight
8. Si UTM detectado: ingresa zona UTM
9. Ingresa bbox opcional (lat N/S, lon E/W)
10. Si se requiere: activa checkbox de riesgo espacial o regional
11. Click "Invertir y cargar modelo 3D" — espera ~30-120s (sin feedback de progreso)
12. Si todo ok: modelo 3D aparece automáticamente en el canvas
13. Puede orbitar, hacer click en voxels para ver tooltip con densidad/sigma/DOI
14. Puede ir a "Datos" para ver métricas de calidad (chi², RMSE, favorabilidad)
15. Puede ir a "IA Geológica" para chat con el modelo de contexto

---

## 3. Auditoría del Motor Matemático — Análisis Forense

### 3.1 Problema Forward: Kernel de Gravedad Gz

**Implementación actual** (`gravimetry.py`, función `_nagy_prism_safe`):

```python
# Código actual (simplificado):
def F(x, y, z, r):
    return x*np.log(z+r) + z*np.log(x+r) - y*np.arctan2(x*z, y*r)

# El kernel suma sobre los 8 corners con signos (-1)^(i+j+k):
total_g += sign * F(dx_vec[i], dy_vec[j], dz_vec[k], r)
```

**Formula estándar Li & Oldenburg / Nagy et al. 2000** para la componente vertical (gz):

```
gz = G * rho * SUM_{i,j,k in {0,1}} mu_ijk * [
    x*ln(y+r) + y*ln(x+r) - z*arctan(x*y / (z*r))
]
```

donde r = sqrt(x²+y²+z²+eps), mu_ijk = (-1)^(i+j+k).

La implementación usa una permutación cíclica de los argumentos: la fórmula estándar tiene `x*ln(y+r) + y*ln(x+r) - z*arctan(xy/zr)`, mientras que el código tiene `x*ln(z+r) + z*ln(x+r) - y*arctan(xz/yr)`. Esta permutación es internamente consistente con la convención de ejes usada (y=profundidad, z=Norte), pero NO ha sido verificada contra una solución analítica de prisma único.

El término de campo lejano (point mass) sí es correcto:
```
g_far = G * V * rho_kg_m3 * dyv / r³
```
donde dyv = y_celda - y_sensor (positivo hacia abajo), G = 6.67430e-11, V = dx*dy*dz [m³], rho_kg_m3 = rho_t_m3 * 1000.

**Veredicto**: PENDIENTE DE VERIFICACIÓN. Se requiere el test analítico de la Sección 5.4 para confirmar que el kernel produce el resultado correcto bajo la convención de ejes implementada.

### 3.2 Correcciones de Gravedad

Para cada corrección, la fórmula exacta y si está implementada:

#### Gravedad Normal (Corrección de Latitud)

**Fórmula GRS80 exacta** (Moritz, 1980 — IUGG):

```
gamma(phi) = 9.7803267715 * (1 + 0.001931851353 * sin²(phi)) / sqrt(1 - 0.0066943800229 * sin²(phi))   [m/s²]
```

Serie expandida suficiente para la mayoría de levantamientos:
```
gamma(phi) = 9.780327 * (1 + 5.3024e-3 * sin²(phi) - 5.8e-6 * sin²(2*phi))   [m/s²]
```

**Implementado**: NO. El servicio `gravity_import_service.py` acepta y almacena el campo `gravity_type` (bouguer_anomaly, free_air_anomaly, g_raw) pero nunca aplica correcciones.

**Impacto**: Variación de ~5 Gal de ecuador a polo. Para levantamientos N-S de 100 km en Chile, el efecto de latitud no corregido es ~50 mGal. Las anomalías de interés son 0.1-10 mGal.

#### Corrección Free-Air (FAC)

**Fórmula exacta dependiente de latitud** (Heiskanen & Moritz):

```
FAC = (0.3087691 - 0.0004398 * sin²(phi)) * h - 7.2125e-8 * h²   [mGal]
```

**Versión simplificada** (válida para h < 2000 m, error < 0.01 mGal):
```
FAC = 0.3086 * h   [mGal]
```

El coeficiente 0.3086 mGal/m proviene de 2g/R = 2*9.81/6371000 = 3.08e-6 m/s² por metro, convertido a mGal.

**Implementado**: NO.

**Impacto crítico**: En los Andes a h=3000 m: FAC = 926 mGal. La anomalía de Bouguer típica en exploración es 0.1-10 mGal. El dato sin FAC es 92-9260 veces la señal.

#### Corrección Bouguer

**Fórmula exacta** (Hinze et al., 2005 — NAGD):

```
BC = 2 * pi * G * rho_s * h = 0.04193 * rho_s * h   [mGal]
```

donde G = 6.6743e-11 m³/(kg·s²) (CODATA), rho_s = densidad de reducción [g/cm³], h = elevación [m].

**Densidad estándar**: 2.67 g/cm³ (corteza continental superior media). Para Chile andino puede justificarse 2.7-2.8 para rocas volcánicas.

**Coeficiente actualizado**: 0.04193 (no el antiguo 0.04190, que usaba G=6.670e-11 pre-CODATA 1986).

Para rho_s = 2.67: BC = 0.04193 * 2.67 * h = 0.1119 mGal/m.

**Implementado**: NO.

#### Corrección de Terreno (TC)

**Método de prismas** (estándar moderno):

```
TC_compartimento = G * rho_s * n_sectores * [r2 - r1 + sqrt(z² + r1²) - sqrt(z² + r2²)]
```

donde r1, r2 = radios interior/exterior del anillo, z = diferencia de altura estación vs elevación media del compartimento.

**Implementado**: NO. El sistema usa GEE para obtener DEM para visualización, pero este DEM no se usa para corrección de terreno pre-inversión.

**Impacto**: En el altiplano chileno, la TC puede ser 5-20 mGal cerca de volcanes y escarpes. Ignorarla introduce artefactos equivalentes a cuerpos densos inexistentes.

### 3.3 Depth Weighting — Diagnóstico Corregido (2026-06-07)

> **CORRECCIÓN POST-TEST SINTÉTICO**: El análisis pre-test predijo skin effect (fuentes demasiado superficiales). La prueba empírica demostró lo contrario: **sinking effect grave**. El mecanismo real es más complejo que un simple error de exponente.

#### Evidencia empírica (audit_synthetic_test.py — 2026-06-07)

Esfera 3.0 t/m³ a 400 m de profundidad real:

| Métrica | Valor | Criterio | Estado |
|---|---|---|---|
| Profundidad pico recuperado | 775 m | ≤ 500 m | **FAIL — sinking 375 m** |
| Chi² reducido | 0.000 | ≈ 1.0 | **FAIL — sobreajuste** |
| Masa en zona correcta (±150 m) | 24% | ≥ 50% | WARN |
| Misfit | 0.01% | ≤ 15% | PASS |

El dato se ajusta casi perfectamente (misfit=0.01%) pero el modelo geológico coloca la masa 7.5 celdas más profunda que la realidad.

#### Mecanismo real del bug — Doble Compensación de Profundidad

`gravimetry.py` líneas ~1380-1421 aplica **dos** compensaciones de profundidad en la misma dirección:

**Compensación 1 — Column scaling implícito** (Ws):
```python
col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
Ws = sp.diags(1.0 / col_norms)   # amplifica columnas con norma pequeña
G_scaled = G_w @ Ws
```
Las columnas de celdas profundas tienen norma pequeña (sensibilidad decae con la distancia). Ws las amplifica, actuando como compensación de profundidad implícita en el término de datos.

**Compensación 2 — Depth weighting explícito** (w_reg) aplicado sobre la regularización:
```python
w_depth = (true_depth + z0) ** depth_beta   # = (z+z0)^2
w_reg = 1.0 / w_depth                       # ≈ 0 para celdas profundas
_w_small = float(lambda_mag) * w_reg        # penalización smallness ≈ 0 en profundidad
```

**Efecto combinado**: Para z_deep=500m, z_shallow=25m:
- `_w_small(superficial)` ≈ 1/25² = 1.6 × 10⁻³
- `_w_small(profundo)` ≈ 1/500² = 4 × 10⁻⁶
- Asimetría real: **~400×** (no el valor nominal 20× de beta/2 correcto)

El solver ve celdas profundas con coste de regularización casi nulo → concentra toda la masa en el fondo. Chi²≈0 porque la estimación de ruido (`sigma_adaptive`) sobreestima σ en ~55×, lo que además disconnecta el lambda del Discrepancy Principle.

**Li & Oldenburg (1998), Eq. 7** — implementación correcta:

```
w(z_j) = 1 / (z_j + z_0)^(beta/2)   con beta = 2 → exponente = 1

Cambio de variable formal: m = W_z^{-1} m̃
W_z^{-1} = diag( (z_j + z_0)^(beta/2) )

Se multiplica simétricamente en TODOS los bloques:
  G_scaled = G_w  @ W_z^{-1}    ← datos
  L_scaled = L    @ W_z^{-1}    ← suavidad
  I_scaled = I    @ W_z^{-1}    ← smallness
```

Con este cambio de variable, la asimetría de regularización desaparece porque el término de datos y el de regularización ven la misma transformación. No hay doble compensación.

**z0**: correctamente implementado como `z0 = self.dy / 2.0` (semiancho de celda).

**Fix correcto** — idéntico al motor magnético post-commit ae4ab94 (`magnetometry.py`):

```python
# REEMPLAZAR en solve_inversion_lsqr() (~líneas 1380-1421):
# QUITAR: col_norms + Ws + w_reg separado
# AGREGAR:

wz_inv_diag = (true_depth + z0) ** (0.5 * float(depth_beta))
wz_inv_diag = wz_inv_diag / np.mean(wz_inv_diag)   # normalizar para evitar escalar λ
Wz_inv = sp.diags(wz_inv_diag)

G_scaled = G_w @ Wz_inv                             # amplifica datos Y regularización igual
L_scaled = L_active @ Wz_inv                        # sin w_reg separado
_small_block = float(lambda_mag) * sp.eye(n_active) # uniform en espacio m̃

# Back-transform al final:
# density_contrast = Wz_inv @ m_tilde
```

**Por qué el fix anterior (solo cambiar beta a beta/2) era insuficiente**: Cambiarlo a `(depth_beta / 2.0)` reduce la asimetría de 400× a 20×, pero deja el column scaling implícito actuando sobre el término de datos. La doble compensación persiste, solo más débil. La solución correcta elimina el column scaling y usa el cambio de variable formal.

### 3.4 Función Objetivo y Regularización

**Objetivo estándar Li & Oldenburg** (4-componente completo):

```
Phi(m) = alpha_s * ||W_s * W_z * (m - m_ref)||²
        + alpha_x * ||W_x * dm/dx||²
        + alpha_y * ||W_y * dm/dy||²
        + alpha_z * ||W_z_deriv * dm/dz||²
```

**Implementación actual** (Laplaciano gráfico, todas las direcciones iguales):

```
Phi_m = lambda_spatial * ||diag(w_reg) * L_active * Ws * m_tilde||²
       + lambda_mag     * ||diag(w_reg) * Ws * m_tilde||²
```

Esta es una forma especial (isótropa, sin pesos direccionales distintos) que es válida pero no permite regularización anisótropa. El sistema aumentado es:

```
[Wd*G*Ws           ] [m_tilde]   [Wd*d_obs]
[lambda_s*Wm*L*Ws  ] *         = [  0     ]
[lambda_mag*diag(w) ]             [  0     ]
```

**El problema del lambda=3.0**:

En el sistema aumentado, lambda_spatial entra CUADRADO en la función objetivo porque LSQR minimiza la suma de cuadrados de los residuos del sistema aumentado. La suavidad efectiva es proporcional a `lambda_spatial²`.

Ratio n_obs/n_active en calibración (benchmark sintético): 49/256 = 0.191

Ratio n_obs/n_active en producción típica: 50/14,000 = 0.0036

El factor `alpha_spatial = n_obs/n_active` cambia 53 veces entre calibración y producción. La suavidad efectiva en producción es `(0.0036)²/(0.191)² ≈ 1/2800` de la calibración. Con lambda=3.0 fijo, el modelo de producción está severamente sub-suavizado.

**lambda correcto para producción** debe recalibrarse con un benchmark sintético a escala real (nx=32, ny=20, nz=32, block=1552m).

### 3.5 Solver LSQR

**Sistema aumentado** (correcto):
```
G_aug = vstack([
    Wd @ G_active @ Ws,                          # (n_obs × n_active)
    lambda_s * diag(w_reg) @ L_active @ Ws,      # (n_active × n_active)
    lambda_mag * diag(w_reg) @ Ws                # (n_active × n_active)
])
```
damp=0.0 es correcto cuando la regularización está explícita en G_aug.

**Problema TRF vs LSQR+clip**:
- Para n_active ≤ 8,000: `lsq_linear` TRF con bounds correctos → mínimo del objetivo sobre la caja feasible.
- Para n_active > 8,000: `lsqr` sin bounds → clip post-hoc. El resultado NO minimiza el objetivo sobre la caja. Si la fracción de celdas clippeadas supera el 10%, el modelo tiene violaciones de bounds no resueltas.

**Stopping criteria**: iter_lim=500, atol=btol=1e-8. Para sistemas con cond(A)~10^6, LSQR puede requerir O(sqrt(cond))~1000 iteraciones para converger. Con 500 iteraciones el solver puede parar antes de la convergencia óptima.

### 3.6 Tabla Resumen — Veredicto del Motor

| Componente | Fórmula en Código | Implementado | Correcto | Prioridad |
|---|---|---|---|---|
| Corrección de Latitud (GRS80) | Ninguna | NO | N/A | CRÍTICA |
| Corrección Free-Air | Ninguna | NO | N/A | CRÍTICA |
| Corrección Bouguer | Ninguna | NO | N/A | CRÍTICA |
| Corrección de Terreno | Ninguna | NO | N/A | CRÍTICA |
| Kernel Gz Nagy (far field) | G*V*rho*dyv/r³ | SÍ | SÍ | OK |
| Kernel Gz Nagy (near field) | Permutación cíclica | SÍ | PENDIENTE | Alta |
| Depth weighting exponent | 1/(z+z0)^2 | SÍ | NO (debe ser ^1) | Alta |
| z0 half-cell stabilizer | dy/2 | SÍ | SÍ | OK |
| Función objetivo estructura | Laplaciano gráfico | SÍ | Parcial (sin anisotropía) | Media |
| Lambda calibración | 3.0 (n=49, n_a=256) | SÍ | NO para producción | Alta |
| LSQR damp=0.0 | Correcto | SÍ | SÍ | OK |
| TRF bounds (n_active≤8K) | lb/ub correctos | SÍ | SÍ | OK |
| LSQR+clip (n_active>8K) | Clip post-hoc | SÍ | NO (no es TRF) | Media |
| density_max=4.2 t/m³ | Hardcoded | SÍ | NO para Fe-ore | Alta |
| density_min=base=2.6 | Sin contrastes negativos | SÍ | NO para exploración | Alta |
| modeled_rock_mass_kg units | density*volume = tonnes | SÍ | NO (son toneladas, no kg) | Media |
| Hutchinson UQ 32 probes | Estimador diagonal | SÍ | Adecuado | OK |

### 3.7 Orden de Reparación Matemática (Prioridad)

1. **[CRÍTICO] Implementar correcciones de gravedad** (FAC, Bouguer, Terreno, Latitud) como nuevo servicio de preprocessing. Bloquear inversión si `gravity_type == "g_raw"` sin correcciones aplicadas.
2. **[P0-A CRÍTICO] Reemplazar column scaling + depth weighting por W_z formal** en `gravimetry.py` función `solve_inversion_lsqr()` (~líneas 1380-1421): eliminar `Ws = diag(1/col_norms)` y `w_reg = 1/(z+z0)^beta` separados; reemplazar por `Wz_inv = diag((z+z0)^(beta/2))` multiplicando simétricamente datos y regularización (idéntico al motor magnético post-commit ae4ab94). Corregir también `focusing.py:36` donde `_DEPTH_BETA=1.0` está hardcodeado en vez de usar el parámetro del solver. Recalibrar lambda después con benchmark sintético a escala de producción. **Referencia**: test sintético 2026-06-07 confirmó sinking effect de 375 m (pico a 775 m vs 400 m real), chi²=0.000.
3. **[ALTA] Recalibrar lambda a escala de producción**: run del benchmark sintético con nx=32, ny=20, nz=32, block=1552m, variar lambda en [0.01, 0.1, 1.0, 10.0], medir Pearson r. Encontrar punto de operación.
4. **[ALTA] Exponer density_max como parámetro requerido** con lookup table por mineralogía objetivo (ver Sección 5.2 de correcciones).
5. **[ALTA] Agregar negative density contrast capability**: `density_min` debe poder ser menor que `base_density` para detectar cuerpos menos densos.
6. **[ALTA] Verificar kernel Nagy** contra solución analítica de esfera/prisma (ver test en Sección 5.4).
7. **[MEDIA] Reemplazar LSQR+clip** con LSMR bounded para todos los tamaños de grilla.
8. **[MEDIA] Fix `modeled_rock_mass_kg`**: renombrar columna a `modeled_rock_mass_tonnes` en `geophysics_service.py` y `TargetingEngine`.
9. **[MEDIA] Conectar `gravity_preprocessing_service.py`** al path de producción. Agregar llamada a `maybe_separate_regional_residual` en `build_sensor_arrays()`.
10. **[BAJA] Fix nombre GEMINI_MODEL_NAME** en `core/config.py`: cambiar "gemini-3.1-pro" al model ID correcto actual.

---

## 4. Análisis de Brechas Industriales

### 4.1 Comparación con Software Tier 1

| Característica | Oasis Montaj | Leapfrog Geo | UBC-GIF GRAV3D | MCVoxel | Brecha |
|---|---|---|---|---|---|
| Corrección Latitud GRS80 | SÍ | SÍ | SÍ | NO | CRÍTICA |
| Corrección Free-Air | SÍ | SÍ | SÍ | NO | CRÍTICA |
| Corrección Bouguer | SÍ, 3 fórmulas | SÍ | SÍ | NO | CRÍTICA |
| Corrección Terreno (DEM) | SÍ, prisms+Hammer | SÍ | SÍ | NO | CRÍTICA |
| Análisis Nettleton | SÍ (automático) | No | No | NO | Alta |
| Inversión 3D densidad | SÍ (VOXI cloud) | SÍ (ext.) | SÍ | SÍ | OK (parcial) |
| Depth weighting correcto | SÍ (beta=2, exp=1) | SÍ | SÍ | NO (exp=2) | Alta |
| Selección lambda L-curve | SÍ | SÍ | SÍ | SÍ (presente) | OK |
| Selección lambda chi² | SÍ | SÍ | SÍ | SÍ (presente) | OK |
| Chi-squared misfit target | SÍ (chifact=1) | SÍ | SÍ | SÍ (presente) | OK |
| Observed vs Calculated | SÍ (3 mapas) | SÍ | SÍ | NO | Alta |
| DOI visualization | SÍ | SÍ | SÍ | Parcial (analytics) | Alta |
| Bounds per lithology | SÍ | SÍ | SÍ | Parcial | Media |
| Borehole constraints | SÍ | SÍ | SÍ | SÍ | OK |
| Isosurface rendering | SÍ | SÍ | Paraview | NO (esfera proxy) | Alta |
| VTK export | SÍ | SÍ | SÍ | Parcial (.vtr) | Media |
| ASEG-GDF2 export | SÍ | No nativo | No | NO | Media |
| UBC-GIF format | Importa | Importa | Nativo | NO | Media |
| Wavelet compression | SÍ | No | SÍ | NO → **Fase 10** | Alta (escala) |
| Terrain correction API | DEM integrado | GIS integrado | Manual | OpenTopography → **Fase 1** | Plan OK |
| Negative density contrast | SÍ | SÍ | SÍ | NO → **Fase 2** | Alta |
| Full UQ ensemble | No (solo SD) | No | No | No (solo Hutchinson) | Media |
| **Malla Octree/adaptativa** | SÍ (VOXI) | SÍ | SÍ (TreeMesh) | NO (TensorMesh 100m) → **Fase 9** | CRÍTICA (resolución) |
| **Resolución celda core** | 5-20 m | 2-10 m | 10-50 m | **100 m actual → 15 m Fase 9** | CRÍTICA |
| **PGI petrológico** | SÍ (GeoKrige) | SÍ (Lithologies) | SÍ (SimPEG PGI) | NO → **Fase 11** | Alta (no-unicidad) |
| **Remanencia magnética** | SÍ (Q ratio, Inc/Dec) | SÍ | SÍ (AMP inversion) | NO (solo inducida) → **Fase 12** | Alta (Fe-ore Chile) |
| **Benchmark validado** | Publicado (Geosoft) | Publicado (Seequent) | SimPEG paper | NO → **Fase 13** | Alta (credibilidad) |
| **Kernel Nagy verificado** | SÍ | SÍ | SÍ | PENDIENTE → **Fase 13** | CRÍTICA |

### 4.2 Gaps Críticos por Categoría

**Categoría 1 — Correcciones Físicas (bloquea uso con datos de campo)**
- Ninguna corrección de gravedad implementada
- `gravity_type` aceptado pero ignorado
- Sin pipeline de reducción de Bouguer
- Sin integración DEM para corrección de terreno pre-inversión

**Categoría 2 — Motor Matemático (produce modelos incorrectos)**
- Exponente depth weighting 2× demasiado agresivo
- Lambda sin calibrar a escala de producción
- LSQR+clip no es un solucionador de caja restringida

**Categoría 3 — Validación Científica (credibilidad en producción)**
- Sin gráfico Observed vs. Calculated (obligatorio en cualquier informe minero)
- Sin mapa de residuos normalizado
- DOI solo en barra lateral, no visualizado en el modelo 3D

**Categoría 4 — Escalabilidad (arquitectura a mediano plazo)**
- Sin compresión wavelet del kernel de sensibilidad
- DEM re-fetch en cada llamada (sin caché)
- Loop Python sin vectorizar en enriquecimiento por elevación (~200K llamadas Python)

**Categoría 5 — Resolución y Malla (bloquea surveys reales a escala mineral)**
- TensorMesh con celda uniforme de 100m: incapaz de resolver cuerpos minerales de escala típica (skarn 50-500m, veta 10-100m) que requieren celdas de 15m en zona core
- Sin soporte para Octree/TreeMesh: no es posible tener resolución fina en zona de interés y gruesa en padding simultáneamente
- Implicación: con malla TensorMesh 100m, un cuerpo a 400m de profundidad está descrito por 4×4×4=64 celdas máximo — insuficiente para forma geológica real

**Categoría 6 — Geología guiada (no-unicidad no resuelta)**
- Sin PGI: dos modelos completamente distintos pueden ajustar los datos igualmente bien
- Sin ancla petrológica desde sondajes: el modelo es geométricamente posible pero geológicamente no informado
- Sin remanencia magnética: todos los depósitos con Q > 1 (magnetita, pirrotita, ilmenita) producen modelos de susceptibilidad incorrectos

**Categoría 7 — Validación externa (credibilidad científica no demostrada)**
- Kernel Nagy no verificado contra solución analítica — si hay error, todos los modelos históricos son incorrectos
- Sin benchmark publicable contra UBC-GIF GRAV3D o SimPEG
- Sin test de joint inversion sintético (las dos anomalías deben recuperarse co-localizadas)

**Categoría 8 — Autenticación multi-tenant robusta (BLOQUEANTE para SaaS/producción)**
- Todos los endpoints tienen `Auth: No` en la tabla de la Sección 2.3
- `core/auth.py`: SHA-256 sin salt (vulnerable a rainbow tables), sin pooling SQLite, sin campo de expiración
- Sin aislamiento de datos por tenant: `project_id` es un string arbitrario accesible por cualquier usuario
- Sin OAuth2/JWT, sin refresh tokens, sin RBAC (roles de usuario vs. admin)
- **Impacto**: ninguna minera aceptará un sistema donde sus datos de exploración son accesibles sin autenticación real. Bloquea cualquier comercialización como SaaS.

**Categoría 9 — Inversión asíncrona real con cola de trabajos (BLOQUEANTE para escala multi-usuario)**
- `async_api.py` + `workers/tasks.py` + `workers/celery_app.py` existen con Celery + Redis, pero el frontend los ignora completamente
- El endpoint de producción (`/gravity-import/invert`) es síncrono con timeout de 20 minutos: si el servidor cae, el trabajo se pierde sin notificación
- No hay límite de jobs concurrentes por usuario, no hay retry automático, no hay prioridad de trabajos
- El sensitivity sweep en `geophysics_api.py` es explícitamente síncrono y bloqueante
- **Impacto**: el sistema no puede servir múltiples usuarios simultáneos con inversiones largas (30-300s)

**Categoría 10 — Datos de campo reales: drift, mareas y formatos propietarios (BLOQUEANTE para uso profesional)**
- Fase 1 cubre FAC/Bouguer/TC, pero asume que el CSV ya contiene `g_raw` limpio. En campo esto NO es cierto.
- **Corrección de deriva del gravímetro (drift)**: los gravímetros Scintrex CG-6 y LaCoste & Romberg derivan ~0.05-0.5 mGal/hora. Sin corrección, las lecturas del día son incomparables. Requiere ocupar una estación de referencia al inicio y fin de cada perfil.
- **Corrección de marea terrestre (tidal)**: efecto periódico de ±0.3 mGal con período ~12 horas. En levantamientos de campo de >4 horas es comparable a la anomalía de interés. Requiere modelo de marea (Longman 1959 o librerías modernas como `tides`).
- **Formatos propietarios**: los datos de Scintrex CG-6 se exportan en `.txt` con columnas fijas; LaCoste & Romberg produce `.obs`. Ningún formato es CSV estándar.
- **Lecturas repetidas por estación**: en campo profesional se ocupan 2-3 lecturas por estación para estimar RMSE instrumental; el sistema no tiene módulo para promediar ni rechazar lecturas discordantes.
- **Impacto**: el pipeline actual solo sirve para datos ya preprocesados por otro software (Scintrex Reader, Oasis Montaj). No es un sistema de ingesta desde campo.

**Categoría 11 — Despliegue y operación (BLOQUEANTE para comercialización)**
- No hay documentación de usuario (no técnica): un geofísico de campo no puede usar el software sin leer el código
- No hay estrategia de backup de datos de usuario (proyectos/runs en filesystem local, sin replicación)
- La infraestructura cloud no está definida (¿AWS? ¿GCP? ¿Azure? ¿Docker?): el `docker-compose.yml` es un entorno de desarrollo, no producción
- No hay definición de SLA: si la inversión falla a mitad, ¿qué garantía tiene el usuario?
- No hay modelo de pricing ni de acceso (¿por inversión? ¿por proyecto? ¿suscripción mensual?)
- **Nota**: estas brechas son de producto, no de ingeniería. El plan resuelve el motor; el producto que lo rodea requiere trabajo adicional no incluido en las 13 fases.

**⚠️ Categoría 12 — Sigma adaptivo incorrecto para datos de campo reales (MUY ALTA)**
- El código actual: `sigma = np.maximum(0.02 * |g_observed|, 0.01 * data_range)` (gravimetry.py línea ~29)
- Para anomalía de Bouguer real de amplitud ~10 mGal: sigma = max(0.02×10, 0.01×range) ≈ 0.1-0.2 mGal
- Scintrex CG-6 precisión real: 0.001-0.005 mGal → sigma sobreestima el ruido **20-200×**
- Efecto: el Discrepancy Principle (lambda tal que chi²=1) no converge al valor correcto porque sigma ficticio desconecta el chi² de la calidad real del ajuste
- Chi² reportado = ficticio, no relacionado con la calidad del ajuste real
- **Fix correcto**: exponer `noise_floor` y `noise_pct` como parámetros del endpoint v2, con defaults derivados del gravímetro declarado por el usuario (ver tabla en Fase 2, sección 2.2)

---

## 5. Las 13 Fases del Plan de Desarrollo

---

### FASE 1: Preprocessing Interface — CSV Sucio → CSV Limpio

#### 1.1 Objetivo y Alcance

Implementar un pipeline completo de correcciones de gravedad que transforme datos crudos de campo (g_raw u otras variantes) en anomalías correctamente reducidas, listas para inversión. Este es el requisito más urgente: sin esta fase, toda inversión de datos de campo produce modelos geológicamente sin sentido.

Alcance: backend `gravity_corrections_service.py` nuevo + API endpoint nuevo `/gravity-corrections/apply` + componente frontend `GravityCorrectionWizard.tsx`.

#### 1.2 Corrección Gravedad Normal (GRS80) — fórmula exacta

```python
# gravity_corrections_service.py

import numpy as np

def compute_normal_gravity_grs80(latitudes_deg: np.ndarray) -> np.ndarray:
    """
    Gravedad teórica según GRS80 (Moritz, 1980 — IUGG).
    
    Returns: gamma en m/s²
    """
    phi = np.radians(latitudes_deg)
    sin2 = np.sin(phi)**2
    
    # Fórmula exacta Somigliana / GRS80
    gamma_e = 9.7803267715  # m/s² en ecuador
    k = 0.001931851353      # constante GRS80
    e2 = 0.0066943800229    # primera excentricidad al cuadrado
    
    gamma = gamma_e * (1 + k * sin2) / np.sqrt(1 - e2 * sin2)
    return gamma  # m/s²


def compute_normal_gravity_simplified(latitudes_deg: np.ndarray) -> np.ndarray:
    """
    Serie expandida: error < 0.0001 mGal (suficiente para exploración).
    """
    phi = np.radians(latitudes_deg)
    sin2 = np.sin(phi)**2
    sin4 = np.sin(2*phi)**2
    
    # Forma clásica (Moritz 1980)
    gamma = 9.780327 * (1 + 5.3024e-3 * sin2 - 5.8e-6 * sin4)  # m/s²
    return gamma
```

#### 1.3 Corrección Free-Air — fórmula exacta, coeficiente justificado

```python
def compute_free_air_correction(
    elevations_m: np.ndarray,
    latitudes_deg: np.ndarray
) -> np.ndarray:
    """
    Corrección Free-Air dependiente de latitud.
    
    Returns: FAC en mGal (siempre positivo para elevaciones > 0)
    
    Referencia: Heiskanen & Moritz (1967), fórmula 3-57.
    Justificación coeficiente: deriva de dgamma/dh = -2*gamma/R para WGS84.
    """
    phi = np.radians(latitudes_deg)
    h = elevations_m
    
    # Fórmula dependiente de latitud (Moritz 1980)
    # Variación de 0.3083 mGal/m (ecuador) a 0.3088 mGal/m (polos)
    fac_coef = 0.3087691 - 0.0004398 * np.sin(phi)**2  # mGal/m
    
    # Término de segundo orden: significativo solo para h > 2000 m
    h2_term = 7.2125e-8 * h**2  # mGal
    
    fac = fac_coef * h - h2_term  # mGal, positivo hacia arriba
    return fac


def simple_free_air_correction(elevations_m: np.ndarray) -> np.ndarray:
    """Simplificado: 0.3086 mGal/m. Error < 0.01 mGal para levantamientos
    sin grandes variaciones de latitud (< 2 grados N-S)."""
    return 0.3086 * elevations_m  # mGal
```

#### 1.4 Corrección Bouguer Simple — fórmula exacta

```python
def compute_bouguer_correction(
    elevations_m: np.ndarray,
    reduction_density_gcc: float = 2.67
) -> np.ndarray:
    """
    Corrección Bouguer de placa infinita.
    
    Coeficiente 0.04193: usa G = 6.6743e-11 m³/(kg·s²) (CODATA 2018).
    El coeficiente antiguo 0.04190 usaba G = 6.670e-11 (pre-CODATA 1986).
    Referencia: Hinze et al. (2005), Geophysics — NAGD standardization.
    
    Args:
        elevations_m: elevación por estación [m]
        reduction_density_gcc: densidad de reducción [g/cm³]
            Estándar: 2.67 (corteza continental)
            Chile andino volcánico: 2.7-2.8
    
    Returns: BC en mGal (positivo — se resta del FAA para obtener BA)
    """
    # 2 * pi * G * rho convertido a mGal/(m * g/cm³)
    # = 2 * 3.14159265 * 6.6743e-11 * 1e3 * 1e5 = 0.04193
    BOUGUER_COEF = 0.04193  # mGal / (m * g/cm³) — estándar moderno
    
    bc = BOUGUER_COEF * reduction_density_gcc * elevations_m  # mGal
    return bc
```

#### 1.5 Corrección de Terreno (Prism Method) — fórmula, radio, DEM

```python
def compute_terrain_correction_prism(
    station_x_m: np.ndarray,   # coordenadas locales
    station_z_m: np.ndarray,
    station_elev_m: np.ndarray,
    dem_x_grid: np.ndarray,    # grilla DEM (2D)
    dem_z_grid: np.ndarray,
    dem_elev_grid: np.ndarray,
    dem_cell_size_m: float,
    reduction_density_gcc: float = 2.67,
    max_radius_m: float = 22000.0  # Hammer zone M outer limit
) -> np.ndarray:
    """
    Corrección de terreno por método de prismas rectangulares.
    
    Fórmula de compartimento cilíndrico (Hammer 1939, forma exacta):
        TC_compartimento = G * rho * n_sectores * [r2 - r1 + sqrt(h² + r1²) - sqrt(h² + r2²)]
    donde h = |elevacion_estacion - elevacion_media_compartimento|
    
    Para DEM de alta resolución, se usa la fórmula de prisma rectangular:
        TC_prism = G * rho * integral sobre el prisma de la componente vertical
    
    Nota: TC es siempre positiva (terreno por encima del plano de reducción
    reduce la gravedad medida por atracción hacia arriba; terreno por debajo
    aumenta por el "vacío" relativo a la placa de Bouguer).
    
    Args:
        max_radius_m: radio máximo de integración. Recomendación:
            - Exploracion local: 22,000 m (Hammer zones A-M)
            - Regional: 167,000 m (Bullard B limit)
    """
    G = 6.6743e-11  # m³/(kg·s²)
    rho_kg_m3 = reduction_density_gcc * 1000.0  # g/cm³ → kg/m³
    
    tc = np.zeros(len(station_x_m))
    
    # [Implementar integración por celdas DEM dentro del radio max_radius_m]
    # Para cada estación y cada celda DEM dentro del radio:
    #   dh = elev_celda - elev_estacion
    #   r = distancia horizontal
    #   Si r > 0: tc_contrib = G * rho * area_celda * dh / r³  (aprox lejano)
    #   Para r < 4*cell_size: usar fórmula exacta de prisma
    
    return tc  # mGal
```

#### 1.6 Integración OpenTopography — API endpoint, params, auth, fallback

```python
# services/opentopo_service.py

import httpx
import os

OPENTOPO_API_KEY = os.getenv("OPENTOPO_API_KEY", "")
OPENTOPO_BASE_URL = "https://portal.opentopography.org/API"
DEM_TYPES = {
    "SRTM30": "SRTMGL1",      # 30m, global, standard
    "SRTM90": "SRTMGL3",      # 90m, global, más rápido
    "COP30": "COP30",          # Copernicus GLO-30, calidad máxima
    "ALOS": "AW3D30",          # 30m, mejor en zonas forestadas
    "NASADEM": "NASADEM",      # 30m, SRTM reprocesado mejorado
}

async def fetch_dem_for_survey(
    south: float,
    north: float,
    west: float,
    east: float,
    dem_type: str = "COP30",
    output_format: str = "GTiff"
) -> bytes:
    """
    Descarga DEM de OpenTopography para el bbox de la encuesta.
    
    Límites de API: 200 calls/día (académico), 50/día (no académico).
    
    Args:
        dem_type: "COP30" recomendado. Fallback automático: SRTM30 → SRTM90.
    
    Fallback: si OpenTopography no disponible, usa el DEM 32×32 de GEE
              (resolución degradada, pero sin latencia adicional).
    """
    params = {
        "demtype": DEM_TYPES.get(dem_type, "SRTMGL1"),
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": output_format,
        "API_Key": OPENTOPO_API_KEY,
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(f"{OPENTOPO_BASE_URL}/globaldem", params=params)
            response.raise_for_status()
            return response.content  # bytes del GeoTIFF
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            # Fallback: usa DEM de GEE ya disponible en el sistema
            raise TerrainFetchError(f"OpenTopography no disponible: {e}. Usar DEM de GEE como fallback.")
```

Nuevo endpoint en `terrain_api.py`:
```
POST /terrain/corrections-dem
Params: {project_id, south, north, west, east, dem_type="COP30", radius_m=22000}
Returns: {dem_path: str, resolution_m: float, coverage_pct: float, source: str}
```

#### 1.7 QC y Limpieza de Datos — reglas de rechazo con umbrales

Cada regla implementada en `gravity_corrections_service.py`:

| Regla | Umbral | Acción | Código |
|---|---|---|---|
| Latitud fuera de rango | \|lat\| > 90° | Error hard | ValueError |
| Longitud fuera de rango | \|lon\| > 180° | Error hard | ValueError |
| Duplicado exacto (x,y,z) | Mismo punto | Eliminar, log | seen_coords set |
| Duplicado cercano | dist < 1.0 m | Warning, mantener primero | cKDTree |
| g_raw outlier sigma | \|z-score\| > 3.0 | Warning, no eliminar | z-score en mGal |
| g_raw outlier range | \|g\| > 1000 mGal | Error hard (post-corrección FA = 0.3086*h) | ValueError |
| Corrección negativa TC | TC < 0 (imposible) | Error en cómputo | assert TC >= 0 |
| Elevación ausente | elev_m is None | Error si gravity_type = "g_raw" | Check pre-corrección |
| Delta entre repeticiones | RMSE > 0.02 mGal | Warning por estación | agrupación station_id |
| Trend Nettleton | r(BA, elev) > 0.5 | Warning, sugerir otra densidad | corrcoef |

#### 1.8 Column Mapping UI

El componente `GravityCorrectionWizard.tsx` mostrará:

1. **Step 1 — Detección automática de columnas**: muestra tabla con headers del CSV, con chips de tipo detectado (Latitud/Longitud/Elevación/Gravedad/Incertidumbre). El usuario puede drag-and-drop para reasignar.

2. **Step 2 — Selector de tipo de dato**: radio buttons `g_raw (sin correcciones)` | `free_air_anomaly (FAC aplicado)` | `bouguer_anomaly (FAC+Bouguer)` | `complete_bouguer_anomaly (FAC+Bouguer+Terreno)`.

3. **Step 3 — Parámetros de reducción**: si g_raw: mostrar campo `Densidad Bouguer [g/cm³]` (default 2.67), selector `Tipo DEM` (COP30/SRTM30/SRTM90), campo `Radio terreno [m]` (default 22000).

4. **Step 4 — Preview correcciones**: tabla con las primeras 5 estaciones mostrando g_raw → FAC → BC → TC → g_bouguer.

#### 1.9 CSV Output Format — especificación exacta de columnas

El nuevo CSV limpio de salida (`clean_gravity_v1.0`):

```
# Clean Gravity CSV v1.0 — MCVoxel
# created_by: gravity_corrections_service.py
# schema_version: 1.0
# corrections_applied: latitude_grs80, free_air, bouguer, terrain
# reduction_density_gcc: 2.67
# dem_source: OpenTopography/COP30
# terrain_radius_m: 22000

station_id,   lat_deg,  lon_deg,  elev_m,  g_obs_mgal, gamma_mgal, fac_mgal, bc_mgal, tc_mgal, g_bouguer_mgal, uncertainty_mgal, gravity_type
ST_000001,  -22.2800, -68.8900,  3200.0,  978001.234, 978450.123,  987.296,  357.897,   4.231,    180.411,            0.020,  complete_bouguer_anomaly
```

Campos requeridos: `lat_deg`, `lon_deg`, `elev_m`, `g_bouguer_mgal`, `uncertainty_mgal`.
Campos opcionales: todos los intermedios (FAC, BC, TC individuales).

#### 1.10 Backend Nuevos Servicios

| Servicio | Funciones Principales | Inputs | Outputs |
|---|---|---|---|
| `gravity_corrections_service.py` | `compute_all_corrections(obs, params)`, `apply_nettleton_test(densities, obs)`, `validate_corrected_data(corrected_obs)` | `List[GravityObservation]`, `CorrectionParams` | `CorrectedGravityResult` |
| `opentopo_service.py` | `fetch_dem_for_survey(bbox, dem_type)`, `compute_terrain_correction_from_dem(obs, dem)` | bbox, DEM type | GeoTIFF bytes, TC array |
| `correction_report_service.py` | `build_correction_report(obs_raw, corrected, params)` | raw + corrected obs | `CorrectionReport` dict |

Nuevo schema en `schemas/gravity_corrections_schema.py`:
```python
class CorrectionParams(BaseModel):
    reduction_density_gcc: float = Field(default=2.67, ge=1.5, le=4.0)
    dem_type: Literal["COP30", "SRTM30", "SRTM90", "ALOS", "NASADEM"] = "COP30"
    terrain_radius_m: float = Field(default=22000.0, ge=1000.0, le=200000.0)
    apply_lat_correction: bool = True
    apply_fac: bool = True
    apply_bouguer: bool = True
    apply_terrain: bool = True
    polynomial_regional_order: Optional[int] = Field(default=None, ge=1, le=4)
```

#### 1.11 Frontend Nuevos Componentes

| Componente | Props | Interacciones |
|---|---|---|
| `GravityCorrectionWizard.tsx` | `file: File, onComplete: (result) => void` | Stepper 4 pasos, drag-drop col mapping |
| `CorrectionPreviewTable.tsx` | `stations: CorrectedStation[], columns: string[]` | Tabla con valores intermedios y finales |
| `NettletonAnalysisChart.tsx` | `correlations: {density: float, r: float}[]` | Scatter plot densidad vs r, estrella en mínimo |
| `TerrainCorrectionMap.tsx` | `stations: Station[], tc_values: float[]` | Mapa 2D coloreado por TC magnitude |

#### 1.12 Tests Requeridos

- `test_corrections_grs80.py`: comparar gamma(0°) = 9.7803267715, gamma(90°) = 9.8321863685 vs valores tabulados GRS80.
- `test_corrections_fac.py`: para h=1000 m, lat=-22°: FAC debe ser ≈ 308.7 mGal.
- `test_corrections_bouguer.py`: para h=1000 m, rho=2.67: BC debe ser ≈ 111.9 mGal.
- `test_corrections_chain.py`: para datos sintéticos conocidos (esfera a 500 m de prof.), verificar que BA = g_obs - gamma - FAC + BC - TC reproduce la anomalía esperada.
- `test_nettleton.py`: para datos donde densidad correcta = 2.67, verificar que el coeficiente de correlación es mínimo en esa densidad.

#### 1.13 Criterios de Aceptación

1. Para g_raw sin elevaciones: el endpoint `/gravity-corrections/apply` retorna HTTP 422 con mensaje claro.
2. Para datos sintéticos con elevación conocida: FAC calculado coincide con fórmula en < 0.005 mGal.
3. Bouguer coefficient = 0.04193 ± 0.0001.
4. Corrección de terreno es ≥ 0 en todas las estaciones (propiedad matemática obligatoria).
5. Análisis Nettleton identifica la densidad correcta ± 0.05 g/cm³ en datos sintéticos.
6. El CSV de salida contiene todas las columnas del formato v1.0.
7. El wizard de UI completa el flujo de 4 pasos sin errores en Chrome/Firefox.

#### 1.14 Preproceso de Datos de Instrumentos Reales (Drift, Mareas, Formatos)

> **GAP NO CUBIERTO POR LAS CORRECCIONES ESTÁNDAR**: Fase 1 asume que el CSV contiene `g_raw` limpio (lecturas únicas por estación, sin deriva instrumental, sin corrección de marea pendiente). Esta sección cubre el pipeline real desde datos de gravímetro de campo.

**1.14.1 Corrección de Deriva del Gravímetro (Instrument Drift)**

Los gravímetros de relativo (Scintrex CG-6, Burris, ZLS Ultra) derivan con el tiempo. La deriva típica es 0.05-0.5 mGal/hora. Corrección estándar:

```python
def correct_instrument_drift(
    readings: pd.DataFrame,          # columnas: station_id, time_utc, g_raw_mgal
    base_station_id: str,            # estación de referencia (ocupada al inicio y fin del perfil)
    base_g_known_mgal: float,        # valor absoluto de la estación base
) -> pd.DataFrame:
    """
    Corrección de deriva lineal por perfil.
    
    Método: ajuste lineal de la deriva entre dos ocupaciones de la estación base.
    Fórmula: g_corrected_i = g_raw_i - drift_rate * (t_i - t_0)
    
    donde drift_rate = (g_base_final - g_base_inicial) / (t_final - t_inicial)
    
    La estación base debe ocuparse mínimo al inicio y al final de cada perfil.
    Para perfiles > 4 horas, se recomienda una ocupación de referencia intermedia.
    """
    base_readings = readings[readings['station_id'] == base_station_id].sort_values('time_utc')
    if len(base_readings) < 2:
        raise ValueError("Se requieren mínimo 2 ocupaciones de la estación base para calcular deriva.")
    
    t0 = base_readings['time_utc'].iloc[0]
    t1 = base_readings['time_utc'].iloc[-1]
    drift_rate_mgal_per_sec = (base_readings['g_raw_mgal'].iloc[-1] - base_readings['g_raw_mgal'].iloc[0]) / (t1 - t0).total_seconds()
    
    readings = readings.copy()
    readings['g_drift_corrected'] = readings['g_raw_mgal'] - drift_rate_mgal_per_sec * (readings['time_utc'] - t0).dt.total_seconds()
    readings['drift_correction_mgal'] = drift_rate_mgal_per_sec * (readings['time_utc'] - t0).dt.total_seconds()
    return readings
```

**1.14.2 Corrección de Marea Terrestre (Earth Tide)**

El efecto de marea terrestre es ±0.3 mGal con período ~12 horas (componentes M2, S2, O1). En levantamientos de campo de >4 horas es comparable o mayor que la anomalía de interés.

```python
def correct_earth_tides(
    station_lat_deg: float,
    station_lon_deg: float,
    station_elev_m: float,
    times_utc: pd.DatetimeIndex,
) -> np.ndarray:
    """
    Calcula corrección de marea terrestre usando Longman (1959).
    
    Para implementación moderna: usar la librería `tides` (Python) o el modelo
    ETERNA 3.40 (Wenzel 1996) — más preciso pero requiere parámetros de amor.
    
    Returns: array de correcciones en mGal (restar del valor observado)
    
    Alternativa práctica si no hay tiempo_utc disponible:
        Usar gravímetro con corrección de marea integrada (CG-6 tiene módulo de marea automático).
        En ese caso, verificar que el CG-6 tenga configurado el datum de marea correcto.
    """
    # [Implementar con librería tides o modelo Longman]
    # Referencia: Longman (1959) JGR, "Formulas for computing the tidal accelerations due to the moon and sun"
```

**1.14.3 Import de Formatos Propietarios**

| Gravímetro | Formato nativo | Extensión | Columnas clave |
|---|---|---|---|
| Scintrex CG-6 | ASCII fixed-width | `.txt` | `Line`, `Sta`, `Time`, `CorrGrav`, `StdDev` |
| ZLS Burris | CSV extendido | `.csv` | `STA_NAME`, `STD_DEV`, `GRAV`, `TIDE`, `DRIFT` |
| LaCoste & Romberg G | ASCII | `.obs` | `STN`, `DIAL`, `BEAM`, `GRAV` |
| Micro-g LaCoste FG5 | ASCII | `.project` | Solo gravedad absoluta, sin deriva |

```python
# services/gravimeter_import_service.py

def import_scintrex_cg6(file_path: str) -> pd.DataFrame:
    """
    Import de archivo de texto del Scintrex CG-6.
    El CG-6 puede exportar corrección de marea integrada (TideCorr) y deriva (DriftCorr).
    Verificar encabezado para saber qué correcciones ya aplicó el instrumento.
    """
    # ... parser de columnas fijas

def import_zls_burris(file_path: str) -> pd.DataFrame:
    """Import de CSV del ZLS Burris. Columna GRAV ya incluye corrección de marea si está activa."""
    # ... 

def import_lacoste_g(file_path: str) -> pd.DataFrame:
    """Import de LaCoste & Romberg G. Requiere escala del dial (g_dial_constant × DIAL)."""
    # ...
```

**1.14.4 Lecturas Repetidas por Estación**

En campo profesional se realizan 2-3 lecturas por estación para estimar la repetibilidad instrumental:

```python
def aggregate_station_readings(
    readings: pd.DataFrame,          # múltiples filas por station_id
    method: str = "mean",            # "mean" | "median" | "best_n"
    max_std_mgal: float = 0.05,      # sigma máximo aceptable por estación
) -> pd.DataFrame:
    """
    Agrupa lecturas repetidas por estación.
    Estaciones con std > max_std_mgal se marcan como WARN para revisión.
    """
```

**Criterios adicionales de Aceptación para 1.14:**

1. `correct_instrument_drift()` con dos ocupaciones de base de la misma estación produce corrección nula (autoconsistencia).
2. Corrección de marea para lat=-22°, lon=-68°, h=3000 m en un período de 24 horas produce variación máxima de ±0.30 mGal ± 10% (verificable con tablas de Longman 1959).
3. `import_scintrex_cg6()` parsea correctamente un archivo de ejemplo sin pérdida de lecturas.
4. Estaciones con std > 0.05 mGal se marcan como WARN, no eliminadas silenciosamente.

---

### FASE 2: Inversion Pipeline — CSV Limpio → Modelo 3D

#### 2.1 Refactorización del Monolito

`geophysics_service.py` tiene 3301 líneas. Refactorizar en módulos aislados:
- `services/inversion_kernel_service.py`: build_kernel, build_sensor_arrays
- `services/inversion_solver_service.py`: solve_inversion_lsqr, estimate_posterior_std
- `services/inversion_postprocess_service.py`: build_block_model_dataframe, build_anomaly_dataframe
- Mantener `geophysics_service.py` como orquestador que llama a estos módulos

#### 2.2 Nuevo Endpoint v2

```python
# POST /v2/geophysics-invert

class GeophysicsInvertInputV2(BaseModel):
    # Grilla
    nx: int = Field(ge=4, le=200)
    ny: int = Field(ge=4, le=200)
    nz: int = Field(ge=4, le=200)
    block_size: float = Field(gt=0.0, le=50000.0)  # float, no int
    
    # Física
    density_min: float = Field(ge=-5.0, le=5.0, description="Contraste mínimo t/m³")
    density_max: float = Field(gt=0.0, le=8.0)
    base_density: float = Field(default=2.6, ge=1.5, le=4.0)
    
    # Regularización
    lambda_strategy: Literal["fixed", "lcurve", "chi2"] = "chi2"
    lambda_fixed: Optional[float] = None
    
    # Correcciones (confirmación obligatoria)
    corrections_applied: List[Literal["latitude", "free_air", "bouguer", "terrain"]]
    gravity_type: Literal["complete_bouguer_anomaly", "free_air_anomaly"]  # g_raw rechazado
    
    @model_validator(mode="after")
    def check_density_range(self):
        if self.density_min >= self.density_max:
            raise ValueError("density_min must be < density_max")
        return self
    
    @model_validator(mode="after")
    def check_list_lengths(self):
        if self.magnetic_nt is not None and len(self.magnetic_nt) != len(self.observations):
            raise ValueError("magnetic_nt length must equal observations length")
        return self
```

#### 2.3 Grid Auto-Calculation Review

Cambios en `grid_calculator_service.py`:
- `MAX_BLOCK_SIZE = 10_000.0 m` es correcto pero debe documentarse.
- `MIN_BLOCK_SIZE` ajustar a `max(station_spacing / 4, 10.0)` en lugar de hardcoded 25m.
- El factor de profundidad L/3: documentar que viene de Li & Oldenburg (1998) tabla 1 — "the model should extend to approximately 1/3 to 1/2 of the maximum survey dimension".

#### 2.4 Sigma Adaptivo — Fix para Datos de Campo Reales

> **GAP CRÍTICO**: la fórmula actual `sigma = max(0.02*|g|, 0.01*range)` sobreestima el ruido **20-200×** para datos de Bouguer reales (amplitud ~10 mGal, precisión del CG-6 = 0.001-0.005 mGal). El chi² resultante es ficticio y desconecta el Discrepancy Principle.

**Fix — exponer noise_floor y noise_pct como parámetros del endpoint v2:**

```python
class GeophysicsInvertInputV2(BaseModel):
    # ... campos existentes ...
    
    # Parámetros de ruido — con defaults por gravímetro
    noise_floor_mgal: float = Field(
        default=0.02,
        ge=0.0001, le=1.0,
        description="Ruido de piso del gravímetro [mGal]. "
                    "Scintrex CG-6: 0.005 mGal. ZLS Burris: 0.002 mGal. "
                    "LaCoste & Romberg G: 0.010 mGal. "
                    "Default 0.02 mGal es conservador para datos de campo sin especificar gravímetro."
    )
    noise_pct: float = Field(
        default=0.01,
        ge=0.0, le=0.10,
        description="Ruido relativo como fracción de la amplitud. "
                    "Para anomalías corregidas de Bouguer: 0.005-0.02 típico."
    )
```

**Tabla de referencia noise_floor por gravímetro (mostrar en UI):**

| Gravímetro | noise_floor (mGal) | noise_pct | Notas |
|---|---|---|---|
| Scintrex CG-6 | 0.005 | 0.005 | Estándar moderno Chile |
| ZLS Burris | 0.002 | 0.005 | Alta precisión |
| LaCoste & Romberg G | 0.010 | 0.010 | Modelo clásico |
| Micro-g FG5 (absoluto) | 0.001 | 0.002 | Solo para estaciones base |
| Desconocido (default) | 0.020 | 0.010 | Conservador — no penaliza |

**Test de validación:**

Para datos sintéticos con ruido de 0.005 mGal (precisión CG-6):
- Con `noise_floor=0.005`: chi²_red debe estar en [0.5, 2.0] ✓
- Con `noise_floor=0.020` (default actual): chi²_red ≈ 0.001 (sobreajuste ficticio) ✗

#### 2.5 Activar Celery/Async — Wiring al Frontend

> **INFRAESTRUCTURA EXISTENTE**: `async_api.py`, `workers/tasks.py` y `workers/celery_app.py` ya están implementados con Celery + Redis. El frontend NO los usa. Esta sección documenta el wiring necesario.

**Estado actual:**
- `POST /async/invert` → encola tarea Celery → retorna `{task_id, status_url}` inmediatamente ✓
- `GET /async/status/{task_id}` → polling del estado de la tarea ✓
- Frontend usa: `POST /gravity-import/invert` (síncrono, 20 min timeout) ✗

**Cambios necesarios en el frontend:**

```typescript
// lib/frontendApi.ts — nueva función
export async function invertGravityCsvAsync(
  file: File,
  params: InvertParams
): Promise<{task_id: string; status_url: string}> {
  // 1. Subir CSV y parámetros
  // 2. Llamar POST /api/async/invert (BFF)
  // 3. Retornar task_id para polling
}

// Polling con SSE o interval:
export async function pollInversionStatus(
  task_id: string,
  onProgress: (stage: string, pct: number) => void,
  onComplete: (result: InversionResult) => void
): Promise<void> {
  // GET /async/status/{task_id} cada 3s hasta done o failed
}
```

**Prerequisitos de infraestructura:**
```bash
# Requiere Redis corriendo:
docker run -d -p 6379:6379 redis:7-alpine

# Y al menos un worker Celery:
celery -A workers.celery_app worker --loglevel=info --concurrency=4

# Variables de entorno:
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**Criterios de aceptación:**
1. `POST /async/invert` retorna `task_id` en < 1 segundo (sin esperar la inversión).
2. `GET /async/status/{task_id}` retorna `{status: "PENDING"}` durante la inversión y `{status: "SUCCESS", result: {...}}` al terminar.
3. Si el servidor muere durante la inversión, el resultado persiste en Redis y se recupera al reiniciar.
4. El frontend muestra barra de progreso durante la inversión (no loading indefinido).

#### 2.6 Status Polling SSE (Streaming)

Añadir endpoint de streaming de progreso:
```
GET /v2/geophysics-status/{project_id}/{run_id}/stream
Retorna: Server-Sent Events con {stage, progress, message, elapsed_s}
```

Stages: `building_kernel | running_lsqr | computing_uq | exporting_model | done`

#### 2.7 Tests Requeridos

- `test_v2_density_validation.py`: density_min >= density_max → 422.
- `test_v2_corrections_required.py`: gravity_type="g_raw" → 422 con mensaje.
- `test_v2_lambda_lcurve.py`: lambda seleccionado por L-curve en modelo sintético, verificar que Pearson r mejora vs lambda fijo incorrecto.
- `test_v2_sigma_adaptive.py`: con `noise_floor=0.005` (CG-6) y datos sintéticos con ruido 0.005 mGal, chi²_red debe estar en [0.5, 2.0].
- `test_v2_async_enqueue.py`: `POST /async/invert` retorna task_id en < 1s.

#### 2.8 Criterios de Aceptación

1. `gravity_type="g_raw"` rechazado con HTTP 422 y mensaje explicativo.
2. `density_min >= density_max` rechazado con HTTP 422.
3. `len(magnetic_nt) != len(observations)` rechazado con HTTP 422.
4. Chi² reducido en rango [0.5, 2.0] para datos sintéticos con ruido al 5% y `noise_floor` correcto para el gravímetro declarado.
5. Status SSE stream emite eventos cada 5 segundos durante inversión.
6. Con `noise_floor=0.005 mGal` (Scintrex CG-6) y datos sintéticos: chi²_red ≠ 0.000 (sin sobreajuste ficticio).

---

### FASE 3: 3D Model Engine

#### 3.1 Parquet Schema Actual vs Requerido

**Schema actual (v3.0)**:
- Gravedad: columnas x, y, z, density (inconsistencia: no usa _m suffix)
- Magnético: x_m, y_m, z_m, susceptibility_si

**Schema requerido (v4.0)**:
```
run_type: str
schema_version: "v4.0"
ix, iy, iz: int
x_m, y_m, z_m: float  # coordenadas locales [m] — unificado
density_t_m3: float
density_contrast_t_m3: float
density_anomaly_score: float
susceptibility_si: Optional[float]
posterior_std: Optional[float]
doi_index: Optional[float]  # Oldenburg & Li 1999 DOI index (0-1)
voxel_lat: Optional[float]  # WGS84
voxel_lon: Optional[float]  # WGS84
voxel_elevation_masl: Optional[float]
```

Renombrar columnas con migración limpia. Actualizar `_REQUIRED_COLUMNS_BY_RUN_TYPE` en `block_model_store.py`.

#### 3.2 Filtering Modes — criterios exactos

| Mode | Criterio de filtro | Límite |
|---|---|---|
| exploration | density_anomaly_score >= P85 OR density_t_m3 >= base + 0.2 | 5,000 voxels |
| anomaly | density_t_m3 >= density_cutoff (param del informe) | 50,000 voxels |
| full | sin filtro (todos los activos) | 250,000 voxels |
| doi_reliable | doi_index < 0.2 (solo celdas bien constrainadas) | Sin límite |
| profile | intersección con plano A-A' definido por usuario | Sin límite |

#### 3.3 Arrow IPC Optimization

El endpoint `/block-model-arrow` retorna todo el parquet como Arrow IPC. Para modelos grandes (>100K voxels), añadir compresión LZ4:
```python
buf = pa.ipc.serialize_pandas(df, use_threads=True)
compressed = lz4.compress(buf)
return Response(content=compressed, media_type="application/x-arrow-lz4")
```
Frontend detecta header `Content-Encoding: lz4` y descomprime antes de parsear.

#### 3.4 Profile Endpoint (nuevo — necesario para Fase 8)

```
GET /v2/block-model-profile
Params: project_id, run_id, 
        x0_m, z0_m, x1_m, z1_m,  # línea A-A'
        halfwidth_m=50.0,           # ancho de la sección
        include_observations=true   # incluir observaciones de gravedad para Observed vs Calc
Returns: {
    profile_voxels: [...],           # voxels dentro del ancho
    profile_observations: [...],     # g_obs + g_pred + residual por estación en perfil
    profile_distance_m: [...],       # distancia a lo largo de A-A'
}
```

#### 3.5 Criterios de Aceptación

1. Schema v4.0 con columnas x_m/y_m/z_m unificadas, sin inconsistencia gravity vs magnetic.
2. `doi_index` presente en parquet para runs con `compute_uncertainty=True`.
3. Modo `doi_reliable` filtra correctamente por doi_index < 0.2.
4. Endpoint `/v2/block-model-profile` retorna voxels intersectando el plano con ±halfwidth_m.

---

### FASE 4: 3D Visualization

#### 4.1 Performance Analysis y LOD Strategy

Estado actual: sin LOD. InstancedMesh con escala=0 para voxels ocultos — correcto pero sin optimización geométrica.

LOD Strategy propuesta:
- **< 5,000 voxels**: render completo, BoxGeometry, meshPhysicalMaterial (clearcoat+transmission actual)
- **5,000 - 50,000 voxels**: InstancedMesh, BoxGeometry, meshStandardMaterial (sin clearcoat)
- **> 50,000 voxels**: WebWorker buffer builder (implementado), sin transmission, sin N8AO

Terreno LOD:
- **< 5 km survey**: PlaneGeometry 64×64 (actual: 32×32)
- **5-50 km**: PlaneGeometry 32×32 (actual)
- **> 50 km**: PlaneGeometry 16×16 (degradado)

#### 4.2 Terrain Mesh con DEM Real

Problema actual: DEM 32×32 para cualquier escala. Para survey de 300 km → cells de ~9 km.

Solución: Para Fase 1, el DEM de corrección de terreno (alta resolución, OpenTopography) se persiste. Usar este mismo DEM para la visualización 3D en lugar del GEE 32×32:
```
terrain_api.py: nuevo parámetro ?source=correction_dem|gee (default gee)
```

#### 4.3 Voxel Picking

El click-to-pick ya funciona. Añadir:
- Tooltip muestra `doi_index` con color (verde < 0.1, amarillo 0.1-0.2, rojo > 0.2)
- Tooltip muestra `voxel_elevation_masl` si disponible
- Click muestra perfil vertical de densidad en ese (ix, iz) — tiny sparkline chart

#### 4.4 Cross-Section View

Implementar en Scene3D:
- Cuando sliceAxis ≠ "none": renderizar una "cara" plana en la posición del slice con los valores de densidad proyectados — equivalente a un mapa de calor 2D.
- Usa un PlaneGeometry con ShaderMaterial que mapea colores desde una Texture (densidades en la sección).
- Esto reemplaza el semi-transparente half-space actual por una vista de sección estilo GMSYS.

#### 4.5 Criterios de Aceptación

1. Render a 30 FPS constante para modelos de hasta 50,000 voxels en hardware mid-range (NVIDIA GTX 1650).
2. Tooltip muestra doi_index con color codificado.
3. Slice plane muestra mapa de calor 2D de densidad en la sección.
4. Terreno visible y correctamente alineado con voxels para surveys en range [1km, 100km].

---

### FASE 5: Data Flow and Formulas Audit

#### 5.1 Tabla Maestra de Fórmulas

| Fórmula | Expresión | Archivo | Línea | Correcto? |
|---|---|---|---|---|
| Gravedad normal GRS80 | gamma = gamma_e*(1+k*sin²phi)/sqrt(1-e²*sin²phi) | gravity_corrections_service.py (NUEVO) | — | SÍ (planificado) |
| FAC | 0.3086 * h [mGal] | gravity_corrections_service.py (NUEVO) | — | SÍ (planificado) |
| Bouguer | 0.04193 * rho * h [mGal] | gravity_corrections_service.py (NUEVO) | — | SÍ (planificado) |
| Kernel Nagy near-field | x*ln(z+r) + z*ln(x+r) - y*arctan(xz/yr) | gravimetry.py | ~155 | PENDIENTE TEST |
| Kernel point mass | G*V*rho*dyv/r³ | gravimetry.py | ~251 | SÍ |
| Sigma adaptivo | max(0.02*\|d_i\|, 0.01*range, 1e-30) | gravimetry.py | ~89 | SÍ |
| Depth weight | W_z formal: Wz_inv = diag((z+z0)^(beta/2)), multiplicando G y L simétricamente | gravimetry.py | 1380-1421 | NO — bug real: column scaling Ws + w_reg = doble compensación → sinking 375 m (test 2026-06-07). Fix: reemplazar ambos por Wz_inv (ver §3.3) |
| Column scaling | Ws = diag(1/\|\|col_j(G)\|\|) | gravimetry.py | ~1450 | SÍ |
| Tikhonov augmented | G_aug = vstack([Wd*G*Ws, λs*Wm*L*Ws, λm*diag(w)*Ws]) | gravimetry.py | ~1480 | SÍ (estructura) |
| Hutchinson | diag(A^-1) ≈ (1/N)*Σ z_k ⊙ (A^-1 z_k) | gravimetry.py | ~1950 | SÍ |
| Chi² reducido | χ² = (1/n)*Σ((d_i - Gm_i)/sigma_i)² | geophysics_service.py | ~680 | SÍ |
| TMI dipole | G_ij = C*(3(f̂·r)² - r²)/r⁵ | magnetometry.py | ~180 | SÍ (débil anomalía ok) |
| Profundidad normal | gamma(phi) | (faltante) | — | FALTA |
| FAC | (faltante) | — | — | FALTA |
| Bouguer plate | (faltante) | — | — | FALTA |
| Terrain correction | (faltante) | — | — | FALTA |

#### 5.2 Tabla de Constantes

| Constante | Valor en Código | Valor Correcto | Fuente | Fix necesario |
|---|---|---|---|---|
| G (Newton) | 6.67430e-11 | 6.67430e-11 | NIST CODATA 2014 | No |
| gamma_e (GRS80) | No implementado | 9.7803267715 m/s² | GRS80 | Agregar |
| FAC coef | No implementado | 0.3086 mGal/m (simple) / 0.3087691 (exacto) | Heiskanen & Moritz | Agregar |
| Bouguer coef | No implementado | 0.04193 mGal/(m·g/cm³) | Hinze et al. 2005 | Agregar |
| base_density | 2.6 t/m³ | 2.6 t/m³ (aceptable) | Estándar | No (pero exponer como param) |
| density_max | 4.2 t/m³ | Depende de target: Fe-ore: 5.2, Cu-porphyry: 4.2-4.5 | Petrografía | Exponer como param requerido |
| density_min | 2.6 t/m³ (= base) | 0.0+ o negativo para algunos targets | Geológico | Fix: permitir contraste negativo |
| depth_beta gravity | 2.0 — pero el bug real es column scaling Ws + w_reg = doble compensación (sinking 375 m confirmado en test 2026-06-07) | W_z formal: Wz_inv = diag((z+z0)^(beta/2)) multiplicando datos Y regularización simétricamente (como motor magnético ae4ab94) | Li & Oldenburg 1998 | **P0-A**: Reemplazar Ws + w_reg por Wz_inv en solve_inversion_lsqr(); fix en focusing.py _DEPTH_BETA=1.0→usar param |
| depth_beta magnetic | 1.5 (como exponente completo) | 1.5 (kernel 1/r³, weight usa beta/2=0.75) | Li & Oldenburg 1996 | Verificar |
| LAMBDA operating point | 3.0 | Recalibrar a escala de producción | Benchmark | Recalibrar |
| Hutchinson n_probes | 32 | 32 (bias O(1/√32)≈18%) | Bekas et al. 2007 | Aceptable |
| TRF threshold | 8000 voxels | Eliminar cliff — usar LSMR para todo | Numérico | Fix |
| cutoff_radius | 800 m default | 4× a_eq o mayor si voxels grandes | Geometric | Verificar |
| GEMINI_MODEL_NAME | "gemini-3.1-pro" | "gemini-1.5-pro" o "gemini-2.0-flash" | Google AI | Fix |

#### 5.3 Unit Consistency Audit

| Variable | Unidad Correcta | Unidad en Código | Bug? |
|---|---|---|---|
| g_observed | m/s² | m/s² (convertido en import) | No |
| g_kernel output | m/s² | m/s² | No |
| density_contrast | t/m³ | t/m³ | No |
| density×volume | tonnes | columna llamada `_kg` | SÍ — renombrar |
| sigma_adaptive input | m/s² | m/s² | No |
| FAC (si existiera) | mGal | — | — |
| Bouguer (si existiera) | mGal | — | — |
| depth_weight w_reg | adimensional | adimensional | No |
| posterior_std | t/m³ | t/m³ | No |

#### 5.4 Tests Analíticos

**Test 1 — Esfera sólida** (verifica kernel Gz):

Para una esfera de radio R centrada a profundidad D, la gravedad vertical en la superficie directamente sobre el centro es exactamente:
```
gz_exact = G * (4/3 * pi * R³) * rho_contrast * D / (D² + eps)^(3/2)
```

Para R=100m, D=500m, rho_contrast=0.5 t/m³ = 500 kg/m³:
```python
def test_sphere_forward():
    R = 100.0; D = 500.0; rho = 500.0  # kg/m³
    V_sphere = (4/3) * np.pi * R**3
    gz_exact = 6.67430e-11 * V_sphere * rho * D / (D**2 + D**2)**1.5  # m/s²
    
    # Construir grilla de voxels cúbicos aproximando la esfera
    # Correr _build_sparse_kernel
    # Comparar gz_modeled vs gz_exact
    assert abs(gz_modeled - gz_exact) / gz_exact < 0.05  # < 5% error
```

**Test 2 — Placa de Bouguer infinita** (verifica corrección Bouguer):

Para una placa horizontal de espesor h, densidad rho, el efecto gravitacional exacto es:
```
gz_slab = 2 * pi * G * rho * h   [m/s²]
         = 0.04193 * (rho en g/cm³) * h   [mGal]
```

**Test 3 — FAC** (verifica corrección Free-Air):

Para un sensor elevado h metros sobre la superficie, sin masa entre el sensor y la superficie:
```
dg_freeair = -2*g/R * h ≈ -0.3086 * h [mGal]   (disminuye con altura)
```

El test verifica que `compute_free_air_correction(h=1000, lat=-22)` ≈ 308.7 mGal ± 0.5 mGal.

#### 5.5 Criterios de Aceptación

1. Test de esfera pasa con error < 5% en norma L2.
2. Test de placa Bouguer: resultado ± 0.01 mGal del valor analítico.
3. FAC: error < 0.01 mGal vs fórmula analítica.
4. `modeled_rock_mass_tonnes` (renombrado) tiene valor en toneladas consistente con density_t_m3 * volume_m3.
5. depth_beta corregido: nueva calibración lambda produce Pearson r >= 0.80 en benchmark sintético con ruido 5%.

---

### FASE 6: Reports

#### 6.1 Reporte de Preprocessing — template completo

El reporte de correcciones (PDF + JSON) debe contener:

**Sección 1 — Survey Metadata**
- N estaciones, rango coordenadas (lat, lon, elevación), fuente datum
- Gravímetro declarado (del CSV si está presente)
- Fecha/hora de la corrección

**Sección 2 — Correcciones Aplicadas**
- Latitud: fórmula usada (GRS80 simplificada o exacta), rango gamma_min/max [mGal]
- FAC: coeficiente usado, elevación media, FAC media/std [mGal]
- Bouguer: densidad usada, BC media/std [mGal]
- Terreno: fuente DEM (OpenTopography/COP30/SRTM30), radio [m], TC media/std [mGal]

**Sección 3 — Análisis Nettleton**
- Tabla: densidad probada | r(BA, elev) | marcado si es mínimo
- Gráfico: r vs densidad (sparkline)
- Densidad recomendada y nivel de confianza

**Sección 4 — Estadísticas Post-Corrección**
- Histograma de la anomalía de Bouguer completa
- Outliers detectados (si los hay): station_id, valor, z-score
- Anomalía mínima/máxima/media/std [mGal]
- Calidad: ALTA / MEDIA / BAJA / INSUFICIENTE

#### 6.2 Reporte de Inversión — template completo

**Sección 1 — Setup de Inversión**
- Grilla: nx, ny, nz, block_size, n_active, n_padding
- Regularización: lambda usado (y método de selección), alpha_spatial
- Bounds: density_min, density_max, base_density
- Solver: LSQR o TRF, iter_lim, stopping criteria usados

**Sección 2 — Convergencia**
- Tabla de iteraciones: iter | phi_d | phi_m | chi²_red
- Gráfico L-curve (si se calculó): log(phi_m) vs log(phi_d) con punto seleccionado marcado
- Chi² reducido final vs target (1.0)

**Sección 3 — Ajuste de Datos (Observed vs Calculated)** ← CLAVE PARA FASE 8
- RMSE [m/s²] y NRMSE [%]
- Gráfico scatter: g_obs vs g_pred (puntos en línea ideal = buen ajuste)
- Mapa 2D de residuos: coloreado por |residual|/sigma (debe ser aleatorio)
- Histograma de residuos normalizados (debe ser Gaussiano centrado en 0)

**Sección 4 — Modelo Recuperado**
- Densidad mínima/máxima/media en celdas activas
- % celdas en bounds superior/inferior (indicador de saturación)
- DOI: % celdas con DOI < 0.2 (confiables)
- Top 10 anomalías: coordenadas, densidad media, volumen estimado

**Sección 5 — Disclaimer JORC/NI43-101**
- "Este modelo es una representación posible de la distribución de densidades subsuperficiales y no constituye recurso mineral según JORC/NI43-101."
- "El modelo no está validado por sondajes."

#### 6.3 Formatos de Exportación

| Formato | Propósito | Librería | Estado |
|---|---|---|---|
| CSV (Clean Gravity v1.0) | Intercambio datos de campo corregidos | pandas | Planificado Fase 1 |
| Parquet v4.0 | Almacenamiento modelo 3D | polars | Migración Fase 3 |
| Arrow IPC (LZ4) | Streaming al frontend | pyarrow + lz4 | Fase 3 |
| VTK (.vtu) | ParaView, análisis externo | pyvista | Implementar |
| UBC-GIF (.msh + .den) | GRAV3D, SimPEG | Custom writer | Implementar |
| ASEG-GDF2 (.dat + .dfn) | Entrega regulatoria (Australia, NZ) | Custom writer | Implementar |
| ZIP (bundle) | Entrega completa al cliente | zipfile | Existe |
| HTML Report | Informe técnico cliente | Jinja2 | Existe, mejorar |

#### 6.4 Criterios de Aceptación

1. Reporte de preprocessing incluye gráfico Nettleton con densidad óptima marcada.
2. Reporte de inversión incluye sección "Observed vs Calculated" con RMSE y mapa de residuos.
3. Export UBC-GIF: archivo `.den` leíble por SimPEG (`discretize` + `simpeg` sin modificaciones).
4. Export ASEG-GDF2: `.dfn` contiene campo `DATUM = GDA94` y `PROJECTION = UTM` con zona correcta.
5. Todos los reportes incluyen disclaimer explícito sobre no-unicidad de la solución.

---

### FASE 7: AI Integration

#### 7.1 Contexto del Modelo en el Chat

El chat actual envía `{project_id, run_id, messages}` al backend, que llama a Gemini (o Claude). El contexto geológico es mínimo.

Nuevo contexto estructurado:
```python
def build_geological_context(project_id: str, run_id: str) -> str:
    detail = get_project_run_detail(project_id, run_id)
    report = detail.get("report", {})
    
    context = f"""
CONTEXTO DEL LEVANTAMIENTO:
- Región: {report.get('region', 'desconocida')}
- N° observaciones: {report.get('n_observations', '?')}
- Extensión: {report.get('extent_x_km', '?')} km × {report.get('extent_z_km', '?')} km
- Profundidad modelo: {report.get('depth_m', '?')} m

PARÁMETROS DE INVERSIÓN:
- Chi² reducido final: {report.get('chi_squared_reduced', '?')}
- RMSE: {report.get('rmse_ms2', '?')} m/s²
- Lambda usado: {report.get('lambda_used', '?')}
- Correcciones: {report.get('corrections_applied', 'no especificado')}

ANOMALÍAS DETECTADAS:
- N° cuerpos densos (contrast > 0.3 t/m³): {report.get('n_anomalies', '?')}
- Densidad máxima recuperada: {report.get('max_density', '?')} t/m³
- Coordenada principal anomalía: x={report.get('best_x_m', '?')} m, z={report.get('best_z_m', '?')} m, profundidad={report.get('best_depth_m', '?')} m

CALIDAD DEL MODELO:
- DOI confiable hasta: {report.get('doi_reliable_depth_m', '?')} m
- Chi² target (1.0) alcanzado: {report.get('chi2_target_reached', '?')}
"""
    return context
```

#### 7.2 Geological Interpretation Prompts

System prompt para el chat geológico:
```
Eres un geofísico experto en exploración minera, especializado en inversión gravimétrica 3D.
Responde en español. Sé específico con números cuando los datos estén disponibles.
No inventes datos que no estén en el contexto proporcionado.
Cuando el chi² sea > 2, advierta que el ajuste de datos no es satisfactorio.
Cuando no haya correcciones aplicadas, advierta que el modelo puede ser artefactual.
```

#### 7.3 Criterios de Aceptación

1. El chat incluye en cada mensaje el contexto estructurado del run activo.
2. Cuando `chi_squared_reduced > 2.0`, el bot advierte automáticamente sobre la calidad del ajuste.
3. Cuando `corrections_applied` es vacío y `gravity_type != "complete_bouguer_anomaly"`, el bot advierte sobre la necesidad de correcciones.

---

### FASE 8: Validation Interface — Observed vs Calculated

#### 8.1 Por Qué Es Obligatorio

En cualquier informe geofísico para minería (NI 43-101, JORC, SEC Modernization), la comparación Observed vs. Calculated es requisito implícito de credibilidad. Oasis Montaj, UBC-GIF GRAV3D, y SimPEG la incluyen automáticamente. Sin ella, el modelo no puede ser independientemente verificado.

La métrica central es el chi² reducido:
```
chi²_red = (1/N) * Σ_i [ (g_obs_i - g_pred_i)² / sigma_i² ]
```

Target: chi²_red ≈ 1.0. Si chi²_red >> 1: modelo insuficiente. Si chi²_red << 1: sobreajuste (modelo fitting ruido).

#### 8.2 Los Datos Ya Existen

Los datos de g_obs (observado) y g_pred (predicho) se calculan en `build_fit_diagnostics()` dentro de `geophysics_service.py` y se incluyen en el JSON del reporte (campo `residual_map`). El parquet v4.0 debe incluir una tabla de observaciones con:
```
obs_id, x_m, z_m, g_obs_ms2, g_pred_ms2, residual_ms2, normalized_residual, sigma_ms2
```

Esta tabla ya se construye en el backend en `build_fit_diagnostics` para hasta 500 puntos. Solo falta exponerla al frontend correctamente y visualizarla.

#### 8.3 Diseño del Gráfico

**Vista 1 — Scatter Observed vs. Calculated**:
- X axis: g_obs [m/s²] o [mGal] (con 3 decimales)
- Y axis: g_pred [m/s²] o [mGal]
- Línea ideal: y = x en gris punteado
- Puntos: colorados por |residual|/sigma (verde < 1, amarillo 1-2, rojo > 2)
- Título: "Observed vs. Calculated (chi²_red = X.XX)"

**Vista 2 — Mapa 2D de Residuos**:
- X axis: coordenada local Este [m]
- Y axis: coordenada local Norte [m]
- Puntos en la posición de cada estación, colorados por residual normalizado
- Colormap divergente: azul (-3σ) → blanco (0) → rojo (+3σ)
- Los residuos deben parecer espacialmente aleatorios. Si hay estructura → modelo incompleto.

**Vista 3 — Histograma de Residuos Normalizados**:
- X: residual_i / sigma_i
- Y: frecuencia
- Curva gaussiana teórica N(0,1) superpuesta en línea roja
- Si la distribución se desvía significativamente de N(0,1) → problema en sigma_i o en el modelo

#### 8.4 Estadísticas de Misfit — fórmulas

```
RMSE [m/s²]     = sqrt( mean( (g_obs - g_pred)² ) )
NRMSE [%]       = RMSE / (max(g_obs) - min(g_obs)) * 100
chi²_red        = mean( (g_obs - g_pred)² / sigma² )
L2_norm [m/s²]  = sqrt( sum( (g_obs - g_pred)² ) )
bias [m/s²]     = mean(g_obs - g_pred)
MAE [m/s²]      = mean(|g_obs - g_pred|)
```

Criterios de calidad:
- BUENO: chi²_red ∈ [0.5, 2.0]
- ACEPTABLE: chi²_red ∈ [2.0, 5.0]
- REVISAR: chi²_red > 5.0 o < 0.5

#### 8.5 Profile Selector Design

Interface de selector de perfil A-A':
1. Mapa 2D de estaciones (scatter plot pequeño con posiciones de sensores)
2. Usuario hace click en dos puntos para definir la línea A-A'
3. Slider "halfwidth" para ajustar el ancho de la sección (10-500 m)
4. Lista de perfiles guardados (A-A', B-B', C-C') con botones de eliminación
5. Al seleccionar un perfil: cargar datos via `/v2/block-model-profile` y renderizar gráfico de perfil

Componente `ProfileSelector.tsx`:
```typescript
interface ProfileSelectorProps {
  stations: {x_m: number; z_m: number; g_obs: number; g_pred: number}[]
  onProfileDefined: (x0: number, z0: number, x1: number, z1: number, hw: number) => void
}
```

#### 8.6 Stack Técnico

Recharts vs Visx vs D3:

- **Recharts**: más fácil de integrar con React, componentes listos para scatter y bar. Limitación: menos control sobre las animaciones de carga y personalización de ejes. Recomendado para RMSE KPIs y histogramas.
- **Visx (Airbnb)**: mayor control, built on D3, mejor para mapas 2D de residuos con tooltips personalizados. Más código boilerplate.
- **D3 puro**: máximo control, pero requiere reconciliar el DOM de D3 con React (useRef + useEffect). No recomendado para este proyecto.

**Decisión**: Recharts para scatter Observed vs. Calculated y histograma. Visx para mapa 2D de residuos.

```typescript
// components/ObservedVsCalculatedChart.tsx
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts'

interface OvCChartProps {
  observations: {g_obs: number; g_pred: number; normalized_residual: number}[]
  chiSquaredReduced: number
}
```

#### 8.7 Criterios de Aceptación

1. La pestaña "Validación" en DatosView muestra scatter Observed vs. Calculated con línea ideal y chi² en título.
2. El mapa 2D de residuos tiene colormap divergente centrado en cero.
3. Estadísticas visibles: RMSE, NRMSE, chi²_red, bias, MAE.
4. Para datos sintéticos conocidos (benchmark): el scatter muestra puntos cercanos a la diagonal y chi²_red ≈ 1.0.
5. Para un modelo claramente malo (lambda incorrecto): el scatter muestra dispersión obvia y chi²_red >> 2.

---

### FASE 9: Malla Octree/TreeMesh — Resolución 15×15×20 m

#### 9.0 Estado Actual — treemesh.py Ya Implementado (Sprint 3A)

> **IMPORTANTE**: El plan original describía esta fase como construir el Octree desde cero. Sin embargo, **`exploration/treemesh.py` ya existe** y contiene una implementación completa (Sprint 3A — Foundation):
> - `TreeMesh` class con estructura de datos Octree completa (bounds, centros, volúmenes, profundidades)
> - Refinamiento Octree dirigido por sensores: `_refine_near_sensors()`
> - Laplaciano Octree con adyacencia por caras: `build_laplacian_octree()` (Sprint 3B)
> - Kernel de celdas variables: `_build_sparse_kernel_variable()` en `GravimetryForward`
>
> **Por tanto, Fase 9 es INTEGRACIÓN, no construcción desde cero.** El trabajo restante es:
> 1. Conectar `treemesh.py` al pipeline de producción (`geophysics_service.py` y `gravity_import_service.py`)
> 2. Adaptar el auto-grid para generar parámetros Octree en lugar de TensorMesh
> 3. Verificar el kernel en el TreeMesh contra la solución analítica de esfera (test_sphere_forward.py)
> 4. Integrar el Laplaciano Octree ya implementado en el solver LSQR/LSMR

#### 9.1 Objetivo y Motivación

**El problema con la malla TensorMesh actual**: El sistema usa TensorMesh con celda uniforme de ~100m en todo el volumen. Para una zona de interés de 3km × 3km × 1.5km esto da 30×30×15 = 13,500 celdas en la zona core — resolución insuficiente para describir la morfología real de un cuerpo mineralizado.

**Por qué 15m y no 100m**: Un skarn de hierro típico en Chile tiene dimensiones de 200×200×300m. Con celdas de 100m, queda descrito por ~2×2×3=12 celdas. Con celdas de 15m, por ~13×13×20=3,380 celdas. Solo con ~15m se obtiene la fidelidad geométrica necesaria para estimar recursos y planificar sondajes.

**El problema de escalar a 15m con TensorMesh**: Para una zona de survey de 3km × 3km × 1.5km + padding de 5km en cada dirección (total ~13km × 13km × 6km), con celdas de 15m:
```
n_cells = (13000/15) × (13000/15) × (6000/15) ≈ 867 × 867 × 400 ≈ 300M celdas
```
Imposible. Requiere Octree.

**La solución TreeMesh (Octree)**: Celda mínima de 15m en la zona core (dentro de la huella del survey), creciendo por factor 2 en cada nivel Octree hacia el borde de la malla:
```
Nivel 0 (core):     15 m — celdas en zona mineralizable central
Nivel 1:            30 m
Nivel 2:            60 m
Nivel 3:           120 m
Nivel 4:           240 m — padding exterior
Nivel 5:           480 m — padding lejano
```
Total n_active típico para survey de 2km × 2km: 50K-200K celdas — manejable.

#### 9.2 Criterio de Refinamiento Octree

El criterio de refinamiento debe garantizar que la resolución sea suficiente para el kernell de sensibilidad, no solo para la geometría. Regla general (Oldenburg et al.):

```
Criterio: h_cell ≤ depth_to_target / 10

Para target a 200m: h_cell ≤ 20m  → nivel 0 (15m) ✓
Para target a 500m: h_cell ≤ 50m  → nivel 2 (60m) ✓ en zona exterior
```

**Número de niveles de refinamiento**: `n_levels = ceil(log2(L_total / h_min))` donde L_total es la dimensión de la malla y h_min el tamaño de celda mínimo.

**Refinamiento forzado cerca de sensores**: Para capturar correctamente el kernel near-field, cada celda adyacente a un sensor debe estar en el nivel más fino (h = 15m). Implementar con `refine_at_sensor_locations()`.

#### 9.3 Implementación — Integrar treemesh.py al Pipeline de Producción

`exploration/treemesh.py` ya implementa la estructura Octree. El trabajo de Fase 9 es **wiring**:

```python
# En geophysics_service.py — reemplazar build_tensor_mesh_with_padding() por:
# exploration/octree_mesh_builder.py (wrapper de integración)

import numpy as np
from exploration.treemesh import TreeMesh  # YA EXISTE

def build_octree_mesh(
    sensor_xyz: np.ndarray,       # (n_sensors, 3) — posiciones x,z,y
    dx: float = 15.0,             # celda mínima X [m]
    dy: float = 20.0,             # celda mínima Y (profundidad) [m]  ← 15×15×20
    dz: float = 15.0,             # celda mínima Z [m]
    n_levels: int = 5,            # niveles de refinamiento
    n_pad: int = 5,               # celdas de padding por lado
    depth_max: float = 2000.0,    # profundidad máxima [m]
) -> TreeMesh:
    """
    Construye TreeMesh con refinamiento forzado en zona de sensores.
    Celda core: 15×15×20 m (horizontal × vertical).
    """
    # Dimensiones de la malla base
    x_min, x_max = sensor_xyz[:,0].min(), sensor_xyz[:,0].max()
    z_min, z_max = sensor_xyz[:,2].min(), sensor_xyz[:,2].max()
    
    h_core = [dx, dy, dz]
    
    # Padding: n_pad celdas creciendo por factor 1.5 fuera del survey
    h_pad = [[h_core[i] * 1.5**j for j in range(n_pad)] for i in range(3)]
    
    mesh = TreeMesh(
        [h_core[0], h_core[1], h_core[2]],
        n_cells_per_level=[2**n_levels, 2**n_levels, 2**n_levels],
        origin="C00",               # origen en centroide X, superficie Y=0
    )
    
    # Refinar en zona de survey
    mesh.refine_box(
        [x_min - dx, 0, z_min - dz],
        [x_max + dx, depth_max, z_max + dz],
        level=n_levels,
    )
    
    # Refinamiento extra cerca de sensores (near-field)
    mesh.refine_points(sensor_xyz, level=n_levels, finalize=False)
    mesh.finalize()
    
    return mesh


def get_active_cells(mesh: TreeMesh, depth_max: float) -> np.ndarray:
    """
    Retorna máscara booleana de celdas activas (por encima de depth_max).
    """
    cell_centers = mesh.cell_centers
    return cell_centers[:, 1] <= depth_max   # y = profundidad
```

#### 9.4 Compatibilidad con el Kernel de Gravedad

El kernel Nagy actual asume celdas del mismo tamaño (dx, dy, dz). Para TreeMesh, cada celda tiene dimensiones variables. El builder del kernel debe recibir las dimensiones individuales de cada celda:

```python
# En GravimetryForward._build_sparse_kernel():

# Actual (TensorMesh — celdas uniformes):
cell_sizes = np.ones(n_active) * (dx, dy, dz)

# Nuevo (TreeMesh — celdas variables):
cell_sizes = mesh.cell_sizes[active_cells]   # (n_active, 3) — dx_i, dy_i, dz_i por celda

# El kernel Nagy recibe (dx_i, dy_i, dz_i) por celda en vez de escalares
gz_ij = _nagy_prism_safe(
    sensor_pos, cell_center_j,
    dx=cell_sizes[j, 0],
    dy=cell_sizes[j, 1],
    dz=cell_sizes[j, 2],
)
```

#### 9.5 Actualización del Auto-Grid

`grid_calculator_service.py` actualmente calcula TensorMesh. Con Octree, el output cambia:

```python
# Nuevo campo en GravityImportPreviewResponse:
"octree_params": {
    "dx_min_m": 15,
    "dy_min_m": 20,
    "dz_min_m": 15,
    "n_levels": 5,
    "n_active_estimated": 87420,
    "depth_max_m": 1800,
    "note": "Malla TreeMesh Octree — celda core 15×15×20 m"
}
```

#### 9.6 Criterios de Aceptación

1. `build_octree_mesh()` para survey sintético 2km × 2km produce n_active < 200K con dx_min=15m.
2. El kernel de gravedad aplicado sobre TreeMesh produce gz_theoretical para esfera analítica con error < 5%.
3. Tiempo de build del kernel (500 sensores × 100K celdas) < 60 segundos en hardware dev.
4. El modelo recuperado por inversión sobre TreeMesh pasa el test de profundidad (esfera a 400m: error < 15%).

---

### FASE 10: Solver Escalable — Compresión Wavelet + ILU(k) Precondicionado

#### 10.1 El Problema de Escala

Con Octree y celdas de 15m, n_active puede alcanzar 200K. El kernel G tiene dimensiones:
```
G: (n_sensors × n_active) = (500 × 200,000) = 100,000,000 elementos
En float64: 100M × 8 bytes = 800 MB — todavía manejable
En float32: 400 MB — mejor
```

Pero el sistema normal para LSQR tiene condición `kappa(G_aug^T G_aug) ~ 10^6-10^8`. LSQR requiere O(sqrt(kappa)) ~ 10,000 iteraciones para converger — inaceptable. LSMR con precondicionador ILU(k) reduce esto a O(100-300) iteraciones.

Para surveys más grandes (1,000 sensores × 500K celdas), G sería 4 GB — no entra en RAM. Requiere compresión wavelet.

#### 10.2 Compresión Wavelet del Jacobiano

**Método**: Farquharson & Oldenburg (2003), "A comparison of automatic techniques for estimating the regularization parameter in non-linear inverse problems."

La idea: la fila i-ésima de G (sensibilidad del sensor i a todas las celdas) es una función suave en el espacio — tiene estructura de baja frecuencia que se comprime bien con wavelets.

```python
# exploration/jacobian_wavelet.py

import pywt
import numpy as np
import scipy.sparse as sp

def compress_row_wavelet(
    row: np.ndarray,        # (n_active,) — una fila de G
    wavelet: str = "db4",   # Daubechies-4
    level: int = 4,
    threshold_frac: float = 0.01,   # threshold = 1% del máximo absoluto
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Comprime una fila del Jacobiano con umbral wavelet.
    Retorna (coeffs_nonzero, indices_nonzero, compression_ratio).
    """
    coeffs = pywt.wavedec(row, wavelet, level=level)
    coeffs_flat, slices = pywt.coeffs_to_array(coeffs)
    
    threshold = threshold_frac * np.max(np.abs(coeffs_flat))
    coeffs_flat[np.abs(coeffs_flat) < threshold] = 0.0
    
    nonzero_mask = coeffs_flat != 0.0
    return coeffs_flat[nonzero_mask], np.where(nonzero_mask)[0], nonzero_mask.mean()


def build_compressed_kernel(
    G_dense: np.ndarray,    # (n_sensors, n_active)
    wavelet: str = "db4",
    level: int = 4,
    threshold_frac: float = 0.01,
) -> sp.csr_matrix:
    """
    Comprime G fila a fila con umbral wavelet, retorna CSR.
    Ratio de compresión típico: 5-15% de los elementos originales.
    """
    rows, cols, data = [], [], []
    for i, row in enumerate(G_dense):
        vals, idxs, _ = compress_row_wavelet(row, wavelet, level, threshold_frac)
        rows.extend([i] * len(vals))
        cols.extend(idxs)
        data.extend(vals)
    
    return sp.csr_matrix((data, (rows, cols)), shape=G_dense.shape)
```

**Regla de threshold**: `ε = 0.01 × max(|G|)` retiene ~10-15% de entradas con error < 0.1% en el forward problem — suficiente para inversión iterativa.

#### 10.3 Precondicionador ILU(k) para LSMR

El sistema normal equations es `A = G_aug^T G_aug`. ILU(k) construye una aproximación `M ≈ A` con k niveles de fill-in:

```python
# exploration/solver_preconditioned.py

import scipy.sparse as sp
import scipy.sparse.linalg as spla
import numpy as np

def solve_inversion_lsmr_preconditioned(
    G_aug: sp.csr_matrix,    # sistema aumentado
    d_aug: np.ndarray,       # RHS aumentado
    ilu_fill_factor: int = 10,
    max_iter: int = 500,
    tol: float = 1e-6,
) -> np.ndarray:
    """
    LSMR + ILU(k) precondicionado para n_active > 50K.
    Convergencia típica: 100-300 iteraciones vs 500+ de LSQR sin precondicionador.
    """
    # Matriz normal (para precondicionador)
    A = G_aug.T @ G_aug      # (n_active × n_active) — dispersa
    
    # ILU precondicionador
    ilu = spla.spilu(A, fill_factor=ilu_fill_factor)
    M = spla.LinearOperator(A.shape, ilu.solve)
    
    # LSMR usa el precondicionador como transformación del espacio
    # Reformulación: resolver (M^{-1/2} A M^{-1/2}) (M^{1/2} x) = M^{-1/2} b
    # En práctica: LSMR con M como precondicionador de la derecha
    x0 = np.zeros(G_aug.shape[1])
    
    x, flag, itn, normr, *_ = spla.lsmr(
        G_aug, d_aug,
        x0=x0,
        maxiter=max_iter,
        atol=tol,
        btol=tol,
        damp=0.0,
    )
    
    return x


def select_solver(n_active: int) -> str:
    """Selector automático de solver según escala del problema."""
    if n_active <= 8_000:
        return "trf_bounded"          # TRF con bounds correctos
    elif n_active <= 50_000:
        return "lsqr"                 # LSQR sin precondicionador (actual)
    else:
        return "lsmr_preconditioned"  # LSMR + ILU(k) (nuevo)
```

#### 10.4 Out-of-Core para G > 4 GB

Si n_sensors × n_active × 8 bytes > 4 GB (threshold configurable), usar Zarr memory-mapped:

```python
# En GravimetryForward._build_sparse_kernel() con Zarr:
import zarr

if estimated_gb > 4.0:
    store = zarr.open(f"{tmp_dir}/G_{run_id}.zarr", mode="w")
    G_zarr = store.zeros("G", shape=(n_sensors, n_active), dtype="float32", chunks=(100, n_active))
    # ... rellenar G_zarr chunk a chunk, sin cargar todo en RAM
    G_active = G_zarr   # acceso transparente
```

#### 10.5 Benchmarks de Tiempo de Cómputo Objetivo

| Escala | n_sensores | n_active | Solver | Tiempo objetivo | Tiempo actual |
|---|---|---|---|---|---|
| Pequeño | 50 | 10K | LSQR | < 5 s | ~5 s ✓ |
| Mediano | 200 | 50K | LSQR | < 60 s | ~90 s WARN |
| Grande | 500 | 200K | LSMR+ILU | < 300 s | N/A (no escala) |
| Muy grande | 1000 | 500K | LSMR+ILU+wavelet | < 30 min | N/A (no escala) |

#### 10.6 Criterios de Aceptación

1. `build_compressed_kernel(G)` con threshold=1% retiene < 15% de elementos con error forward < 0.5%.
2. `solve_inversion_lsmr_preconditioned()` para n_active=100K converge en < 300 iteraciones.
3. Inversión de survey grande (500 sensores, 200K celdas) completa en < 5 minutos.
4. Resultado numérico de LSMR precondicionado igual a LSQR sin precondicionador para n_active=10K (verificación de correctitud).

---

### FASE 11: PGI — Inversión Guiada Petrológica (Astic & Oldenburg 2019)

#### 11.1 El Problema de la No-Unicidad

La inversión de campos potenciales es inherentemente no-única: existen infinitas distribuciones de densidad que ajustan los datos de gravedad igualmente bien. El depth weighting (Fase P0-A) solo controla la profundidad preferida, pero no discrimina entre cuerpos de geometría diferente con la misma masa total.

**PGI** resuelve esto anclando el modelo a clases petrológicas conocidas, con prior estadístico derivado de muestras de sondaje o bibliografía. El solver busca el modelo que ajusta los datos Y es geológicamente consistente con las rocas mapeadas.

#### 11.2 Formulación Matemática

**Mixtura Gaussiana (GMM)** para las k clases petrológicas:

```
p(m_j) = sum_{k=1}^{K} π_k * N(m_j; μ_k, σ_k²)

donde:
  K = número de litologías (p.ej. 3: roca caja, mineralización media, alta)
  π_k = proporción volumétrica de la litología k
  μ_k = densidad media de la litología k [t/m³]
  σ_k = desviación estándar de la litología k [t/m³]
```

**Función objetivo PGI**:

```
Φ_PGI(m) = Φ_d(m) + λ_m * Φ_m(m) + α_PGI * Φ_geo(m)

Φ_geo(m) = ||W_m * (m - m_PGI(m))||²

donde m_PGI(m) es el modelo de referencia actualizado:
  m_PGI_j = μ_{k*} donde k* = argmax_k [π_k * N(m_j; μ_k, σ_k²)]
```

El término α_PGI * Φ_geo penaliza la distancia de cada celda al centroide de su litología más probable. A medida que la inversión converge, m_PGI se actualiza con las asignaciones de clase del paso anterior.

#### 11.3 Algoritmo Iterativo (Alternate Direction)

```
Entrada: G, d_obs, GMM(K, μ_k, σ_k, π_k), m_ref, α_PGI

Inicializar: m^0 = m_ref, m_PGI^0 = MAP_assignment(m^0, GMM)

Para iter = 1, 2, ..., max_iter:
    1. Actualizar m_PGI^{iter} = MAP_assignment(m^{iter-1}, GMM)
    2. Resolver Φ_PGI con m_PGI fijo (inversión estándar + término PGI):
         m^{iter} = argmin_m [ Φ_d(m) + λ_m*Φ_m(m) + α_PGI*||W_m*(m - m_PGI^{iter})||² ]
    3. Verificar convergencia:
         Si ||m_PGI^{iter} - m_PGI^{iter-1}||_2 / ||m_PGI^{iter-1}||_2 < tol → STOP

Salida: m^{iter}, m_PGI^{iter}, asignación de clase por celda
```

#### 11.4 Fuentes del GMM en TerraQuantum

Tres fuentes posibles para los parámetros del GMM, en orden de confiabilidad:

| Fuente | Confiabilidad | Cómo implementar |
|---|---|---|
| Muestras de sondaje con densidad medida en laboratorio | Alta | Ajuste GMM desde columna density del CSV de sondaje existente |
| Bibliografía por tipo de depósito | Media | Tabla lookup integrada en UI (ver §11.5) |
| Estimación desde el modelo invertido sin PGI | Baja | `fit_gmm_from_model(m_initial, K)` usando sklearn GaussianMixture |

#### 11.5 Tabla de Parámetros GMM por Depósito (Default)

| Litología | Depósito | μ (t/m³) | σ (t/m³) | π |
|---|---|---|---|---|
| Roca caja (andesita) | Todos | 2.65 | 0.08 | 0.85 |
| Mineralización media (calcopirita+cuarzo) | Pórfido Cu | 2.90 | 0.15 | 0.10 |
| Mineralización alta (sulfuros masivos) | VMS | 3.50 | 0.20 | 0.05 |
| Magnetita | Skarn Fe | 5.10 | 0.15 | 0.05 |
| Pirrotita | VMS/IOCG | 4.60 | 0.20 | 0.05 |

#### 11.6 Implementación

```python
# exploration/pgi_engine.py

import numpy as np
from sklearn.mixture import GaussianMixture

class PGIEngine:
    def __init__(self, gmm_params: dict, alpha_pgi: float = 0.1):
        """
        gmm_params: {"means": [2.65, 2.90, 3.50], "stds": [0.08, 0.15, 0.20], "weights": [0.85, 0.10, 0.05]}
        alpha_pgi: peso del término PGI en la función objetivo total
        """
        self.gmm = GaussianMixture(
            n_components=len(gmm_params["means"]),
            covariance_type="diag",
            means_init=np.array(gmm_params["means"]).reshape(-1, 1),
        )
        self.gmm.means_ = np.array(gmm_params["means"]).reshape(-1, 1)
        self.gmm.covariances_ = np.array(gmm_params["stds"]).reshape(-1, 1) ** 2
        self.gmm.weights_ = np.array(gmm_params["weights"])
        self.alpha_pgi = alpha_pgi
    
    def compute_m_pgi(self, m: np.ndarray) -> np.ndarray:
        """Asignación MAP de cada celda a su litología más probable."""
        log_probs = self.gmm.predict_proba(m.reshape(-1, 1))
        class_assignments = np.argmax(log_probs, axis=1)
        return self.gmm.means_[class_assignments].flatten()
    
    def build_pgi_block(
        self, m: np.ndarray, n_active: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Retorna (A_pgi, b_pgi) para agregar al sistema aumentado:
          min ||G_aug @ m̃ - d_aug||² incluye bloque:
          sqrt(alpha_pgi) * W_m * (m - m_pgi) = 0
        """
        m_pgi = self.compute_m_pgi(m)
        A_pgi = np.sqrt(self.alpha_pgi) * np.eye(n_active)
        b_pgi = np.sqrt(self.alpha_pgi) * m_pgi
        return A_pgi, b_pgi
```

#### 11.7 Criterios de Aceptación

1. `PGIEngine.compute_m_pgi()` para m=[2.65, 2.90, 3.50] asigna cada valor al centroide correcto.
2. Inversión PGI en modelo sintético (3 litologías): asignación de clase correcta en > 70% de celdas (benchmark).
3. El histograma de densidad post-inversión con PGI muestra picos en los centroides del GMM (distribución bimodal o trimodal esperada); sin PGI es unimodal difuso.
4. Convergencia en ≤ 10 iteraciones de actualización m_PGI.

---

### FASE 12: Remanencia Magnética — Motor J = J_ind + J_rem

#### 12.1 Por Qué Es Crítico Para Chile

Los tres depósitos más económicos del norte chileno involucran minerales con remanencia significativa:

| Mineral | Depósito típico | Koenigsberger Q | Implicación |
|---|---|---|---|
| Magnetita (Fe₃O₄) | Skarn Fe (Atacama) | Q = 1-10 | J_rem > J_ind en la mayoría de casos |
| Pirrotita (Fe₇S₈) | VMS Cu-Zn | Q = 1-5 | Dirección de J_rem aleatoria (metamorfismo) |
| Ilmenita-magnetita | IOCG (Candelaria, Mantoverde) | Q = 0.5-3 | Remanencia significativa en cuerpos masivos |

Con el motor actual (solo inducida), la inversión de susceptibilidad para un cuerpo con Q=5 subestima χ en un factor ~5 y orienta el campo en dirección incorrecta → modelo de susceptibilidad geológicamente incorrecto.

#### 12.2 Formulación del Campo Total Magnetic Intensity con Remanencia

**Magnetización total**:
```
J_total = J_ind + J_rem
J_ind   = (χ / μ₀) * B₀ * f̂_ind   (dirección del campo ambiental: Inc_amb, Dec_amb)
J_rem   = Q * |J_ind| * f̂_rem      (dirección de remanencia: Inc_rem, Dec_rem)
```

donde `f̂_ind` y `f̂_rem` son vectores unitarios en la dirección de campo inducido y remanente respectivamente.

**TMI kernel con remanencia**:
```
G_ij_total = G_ij_induced(f̂_ind) + Q * G_ij_remanent(f̂_rem)

G_ij_induced = C * [(3(f̂_ind·r̂)² - 1)] / r³      (dipolo alineado con campo ambiental)
G_ij_remanent = C * [(3(f̂_rem·r̂)² - 1)] / r³     (dipolo alineado con remanencia)
```

**Inversión de amplitud** (cuando Inc_rem/Dec_rem son desconocidos):
```
|J_total| = |J_ind + J_rem| (dirección-independiente)
Kernel: G_amp_ij = C * V_j / r_ij³   (amplitud, sin dependencia direccional)
Invertir: |χ_j| = |J_total_j| / (B₀/μ₀)
```

#### 12.3 Parámetros de Usuario

Agregar a `GeophysicsInvertInput`:

```python
class MagneticRemanenceParams(BaseModel):
    enabled: bool = False
    q_ratio: float = Field(default=1.0, ge=0.0, le=100.0,
                           description="Koenigsberger ratio Q = |J_rem| / |J_ind|")
    remanence_inc_deg: float = Field(default=-45.0, ge=-90.0, le=90.0,
                                      description="Inclinación de remanencia [°]")
    remanence_dec_deg: float = Field(default=0.0, ge=-180.0, le=180.0,
                                      description="Declinación de remanencia [°]")
    inversion_mode: Literal["induced_only", "total_field", "amplitude"] = "induced_only"
```

#### 12.4 Implementación en magnetometry.py

```python
# En magnetometry.py — función _build_tmi_kernel():

def _build_tmi_kernel_with_remanence(
    sensor_pos: np.ndarray,
    cell_centers: np.ndarray,
    cell_sizes: np.ndarray,
    B0_nT: float,
    inc_amb_deg: float, dec_amb_deg: float,
    q_ratio: float = 0.0,
    inc_rem_deg: float = -45.0, dec_rem_deg: float = 0.0,
) -> np.ndarray:
    """
    Kernel TMI total = inducido + remanente.
    Para q_ratio=0: idéntico al kernel actual (solo inducida).
    """
    G_ind = _dipole_kernel(sensor_pos, cell_centers, cell_sizes, inc_amb_deg, dec_amb_deg, B0_nT)
    
    if q_ratio == 0.0:
        return G_ind   # sin cambio respecto al motor actual
    
    G_rem = _dipole_kernel(sensor_pos, cell_centers, cell_sizes, inc_rem_deg, dec_rem_deg, B0_nT)
    
    return G_ind + q_ratio * G_rem


def _dipole_kernel(sensor_pos, cell_centers, cell_sizes, inc_deg, dec_deg, B0_nT):
    """Kernel de dipolo magnético con dirección (Inc, Dec) especificada."""
    inc_rad = np.radians(inc_deg)
    dec_rad = np.radians(dec_deg)
    f_hat = np.array([
        np.cos(inc_rad) * np.cos(dec_rad),   # x (Norte)
        np.cos(inc_rad) * np.sin(dec_rad),   # y (Este)
        np.sin(inc_rad),                      # z (abajo)
    ])
    # ... (implementación dipolo existente, parametrizada con f_hat)
```

#### 12.5 Estimación de Q desde Datos (opcional)

Para usuarios sin medición de Q en laboratorio, TerraQuantum puede ofrecer estimación de Q óptimo minimizando el misfit:

```
Q* = argmin_Q ||G_total(Q) m_inv(Q) - d_obs||²

Implementación: barrido de Q ∈ [0, 10] en 20 pasos logarítmicos,
inversión rápida para cada Q, reportar Q* y curva de misfit vs Q.
```

#### 12.6 Criterios de Aceptación

1. Para Q=0: `_build_tmi_kernel_with_remanence()` produce resultado idéntico al kernel actual.
2. Para cuerpo sintético con Q=5 (Inc_rem=-30°, Dec_rem=180°): la inversión con remanencia recupera χ correcto ± 20%; sin remanencia, el error es > 80%.
3. El barrido de Q converge a Q_true ± 50% para datos sintéticos sin ruido.
4. No hay regresión en tests de inversión magnética existentes.

---

### FASE 13: Validación Externa Publicable

#### 13.1 Objetivo

Demostrar de forma reproducible que el motor de TerraQuantum produce resultados comparables a los estándares industriales (UBC-GIF GRAV3D) y académicos (SimPEG). Sin esto, "Tier 1" es una afirmación, no una verificación.

#### 13.2 Suite de Tests Sintéticos — 4 Benchmarks

**Benchmark 1: Esfera** (verificación de exactitud del kernel)
```
Solución analítica: gz(x) = (4/3)π G ρ R³ * d / (x² + d²)^{3/2}

Parámetros: R=100m, ρ=1.0 t/m³, d=400m (profundidad al centro)
Test: gz_numerical vs gz_analytical en 50 puntos de superficie
Criterio: RMSE < 1% del pico
```

**Benchmark 2: Dique inclinado** (verificación de resolución estructural)
```
Dique de 500m × 50m × 2000m, inclinado 60°, top a 100m de profundidad
ρ = 0.5 t/m³ de contraste
Test: el modelo invertido recupera la inclinación 60° ± 10° y la profundidad del top ± 20m
Criterio (Tier 1): inclinación y profundidad dentro de tolerancias
```

**Benchmark 3: Checkerboard** (resolución espacial)
```
Tablero ajedrez de 4×4 celdas de 200×200m, alternando ρ=+0.3 y -0.3 t/m³
Red de 25×25 sensores sobre el tablero
Test: % de celdas con signo correcto
Criterio: > 80% de celdas con signo correcto
```

**Benchmark 4: Dos cuerpos interferentes** (separabilidad)
```
Cuerpo A: ρ=0.5 t/m³, centro (500m, 300m profundidad)
Cuerpo B: ρ=0.3 t/m³, centro (1500m, 500m profundidad)
Test: ¿el modelo invertido muestra dos anomalías separadas?
Criterio: centroide de cada anomalía recuperado a ± 150m
```

#### 13.3 Verificación Formal del Kernel Nagy

```python
# tests/test_sphere_forward.py

import numpy as np
import pytest
from exploration.gravimetry import GravimetryForward

def analytical_sphere_gz(x_m: np.ndarray, depth_m: float, rho_t_m3: float, R_m: float) -> np.ndarray:
    """Solución analítica exacta de gz para esfera homogénea."""
    G_SI = 6.67430e-11
    mass = (4/3) * np.pi * rho_t_m3 * 1000 * R_m**3   # kg
    return G_SI * mass * depth_m / (x_m**2 + depth_m**2)**1.5  # m/s²

def test_nagy_kernel_sphere_profile():
    """Verificación del kernel vs solución analítica de esfera."""
    depth = 400.0        # m
    R = 50.0             # m (radio)
    rho = 1.0            # t/m³

    # Sensores en superficie, perfil E-W
    x_sensors = np.linspace(-1000, 1000, 51)
    sensor_pos = np.column_stack([x_sensors, np.zeros(51), np.zeros(51)])

    gz_analytical = analytical_sphere_gz(x_sensors, depth, rho, R)
    
    # Aproximar esfera con cubo equivalente (volumen = 4/3 π R³)
    # ... (build kernel para una celda cúbica de volumen igual)
    
    rmse_relative = np.sqrt(np.mean((gz_numerical - gz_analytical)**2)) / np.max(np.abs(gz_analytical))
    assert rmse_relative < 0.05, f"RMSE relativo kernel = {rmse_relative:.3%} (límite: 5%)"
```

#### 13.4 Comparación Contra SimPEG

```python
# tests/test_simpeg_comparison.py

def test_gravity_inversion_vs_simpeg():
    """
    Comparación de modelos recuperados entre TerraQuantum y SimPEG.
    Requiere: pip install simpeg (solo para tests)
    """
    # 1. Generar datos sintéticos con el mismo modelo verdadero
    m_true = build_checkerboard_model(...)
    
    # 2. Invertir con TerraQuantum
    m_tq = run_terraquantum_inversion(G, d_obs, params)
    
    # 3. Invertir con SimPEG (mismos parámetros de regularización)
    m_simpeg = run_simpeg_inversion(G, d_obs, params)
    
    # 4. Comparar modelos
    pearson_r = np.corrcoef(m_true, m_tq)[0,1]
    pearson_r_simpeg = np.corrcoef(m_true, m_simpeg)[0,1]
    
    assert pearson_r > 0.70, f"TerraQuantum Pearson r={pearson_r:.2f} < 0.70"
    assert abs(pearson_r - pearson_r_simpeg) < 0.15, \
        f"Gap vs SimPEG: TQ={pearson_r:.2f}, SimPEG={pearson_r_simpeg:.2f} (límite: ±0.15)"
```

#### 13.5 Informe de Validación

Formato `validation_report.json` generado automáticamente al correr `python -m pytest tests/ -k benchmark`:

```json
{
  "terraquantum_version": "2.0.0",
  "validation_date": "2026-XX-XX",
  "benchmarks": {
    "sphere_kernel": {"rmse_relative": 0.021, "status": "PASS"},
    "dipping_dike": {"depth_error_m": 18, "dip_error_deg": 7, "status": "PASS"},
    "checkerboard_4x4": {"correct_sign_pct": 0.84, "status": "PASS"},
    "two_body": {"centroid_error_A_m": 95, "centroid_error_B_m": 142, "status": "PASS"}
  },
  "simpeg_comparison": {
    "pearson_r_terraquantum": 0.76,
    "pearson_r_simpeg": 0.81,
    "gap": 0.05,
    "status": "PASS"
  },
  "overall": "VALIDATED_TIER1_LOCAL_SCALE"
}
```

#### 13.6 Criterios de Aceptación

1. Los 4 benchmarks pasan sus criterios de tolerancia respectivos.
2. Gap de Pearson r entre TerraQuantum y SimPEG < 0.15 en el checkerboard benchmark.
3. `validation_report.json` generado reproduciblemente — mismos resultados en dos corridas independientes.
4. Test de regresión: al modificar cualquier parámetro de la inversión, los benchmarks deben seguir pasando (CI check automático).

---

## 6. Especificaciones Técnicas Completas

### 6.1 Nueva Arquitectura de Archivos

```
terraquantum-backend/
├── api/
│   ├── gravity_corrections_api.py        [NUEVO — Fase 1]
│   ├── gravity_import_api.py             [fix NameError: math, _extract_detected_utm_zone]
│   ├── geophysics_api.py                 [mejorar: auth, async sweep]
│   ├── block_model_api.py                [agregar /v2/block-model-profile]
│   └── terrain_api.py                   [agregar param ?source=correction_dem|gee]
├── exploration/
│   ├── gravimetry.py                     [fix depth_weight, density bounds, units]
│   ├── magnetometry.py                   [agregar remanencia: Fase 12]
│   ├── geophysics_shared.py              [NUEVO — funciones duplicadas gravity+magnetic]
│   ├── geophysics_math.py                [sin cambios]
│   ├── focusing.py                       [fix DEPTH_BETA=1.0→2.0, fix regularizer]
│   ├── octree_mesh_builder.py            [NUEVO — Fase 9: TreeMesh con celda core 15×15×20 m]
│   ├── jacobian_wavelet.py               [NUEVO — Fase 10: compresión wavelet Daubechies-4]
│   ├── solver_preconditioned.py          [NUEVO — Fase 10: LSMR + ILU(k)]
│   └── pgi_engine.py                     [NUEVO — Fase 11: PGI con GMM]
├── services/
│   ├── gravity_corrections_service.py    [NUEVO — Fase 1: FAC, Bouguer, TC, Nettleton]
│   ├── opentopo_service.py               [NUEVO — Fase 1: DEM via OpenTopography]
│   ├── correction_report_service.py      [NUEVO — Fase 6: reporte de correcciones]
│   ├── inversion_kernel_service.py       [NUEVO — extraído de geophysics_service.py]
│   ├── inversion_solver_service.py       [NUEVO — extraído de geophysics_service.py]
│   ├── inversion_postprocess_service.py  [NUEVO — extraído de geophysics_service.py]
│   ├── geophysics_service.py             [refactorizado — orquestador]
│   ├── gravity_import_service.py         [sin cambios estructura, mejorar error handling]
│   ├── gravity_preprocessing_service.py  [conectar al path de producción]
│   └── elevation_enrichment_service.py   [vectorizar DEM sampling]
├── schemas/
│   ├── gravity_corrections_schema.py     [NUEVO — CorrectionParams, CorrectedGravityResult]
│   ├── geophysics_schema.py              [fix cross-validators density_min<max, len checks]
│   └── gravity_import_schema.py          [fix Literal para SpatialReadiness.level]
├── core/
│   ├── config.py                         [fix GEMINI_MODEL_NAME]
│   └── block_model_store.py              [fix gravity column names x→x_m]
└── tests/
    ├── test_corrections_grs80.py          [NUEVO — Fase 1]
    ├── test_corrections_fac.py            [NUEVO — Fase 1]
    ├── test_corrections_bouguer.py        [NUEVO — Fase 1]
    ├── test_sphere_forward.py             [NUEVO — Fase 13: verifica kernel Nagy vs analítico]
    ├── test_depth_weighting.py            [NUEVO — Fase 5: verifica beta/2 corregido]
    ├── test_observed_vs_calculated.py     [NUEVO — Fase 8: verifica residual map]
    ├── test_octree_mesh.py                [NUEVO — Fase 9: celda core 15m, n_active < 200K]
    ├── test_wavelet_compression.py        [NUEVO — Fase 10: ratio < 15%, error forward < 0.5%]
    ├── test_lsmr_preconditioned.py        [NUEVO — Fase 10: convergencia < 300 iter n=100K]
    ├── test_pgi_engine.py                 [NUEVO — Fase 11: asignación GMM correcta]
    ├── test_magnetic_remanence.py         [NUEVO — Fase 12: Q=0 idéntico al motor actual]
    ├── test_benchmark_dipping_dike.py     [NUEVO — Fase 13: dique inclinado]
    ├── test_benchmark_checkerboard.py     [NUEVO — Fase 13: tablero 4×4]
    ├── test_benchmark_two_body.py         [NUEVO — Fase 13: dos cuerpos interferentes]
    └── test_simpeg_comparison.py          [NUEVO — Fase 13: Pearson r gap < 0.15 vs SimPEG]

terraquantum-web/
├── components/
│   ├── GravityCorrectionWizard.tsx        [NUEVO — Fase 1: stepper 4 pasos]
│   ├── CorrectionPreviewTable.tsx         [NUEVO]
│   ├── NettletonAnalysisChart.tsx         [NUEVO]
│   ├── ObservedVsCalculatedChart.tsx      [NUEVO — Fase 8]
│   ├── ResidualMap2D.tsx                  [NUEVO — Fase 8]
│   ├── ResidualHistogram.tsx              [NUEVO — Fase 8]
│   ├── ProfileSelector.tsx                [NUEVO — Fase 8]
│   └── DatosView.tsx                      [actualizar: pestaña Validación]
└── lib/
    └── frontendApi.ts                      [agregar: corrections endpoint, profile endpoint]
```

### 6.2 API Contracts v2

**POST /v2/gravity-corrections/apply**
```json
Request:
{
  "project_id": "string",
  "run_id": "string",
  "correction_params": {
    "reduction_density_gcc": 2.67,
    "dem_type": "COP30",
    "terrain_radius_m": 22000,
    "apply_lat_correction": true,
    "apply_fac": true,
    "apply_bouguer": true,
    "apply_terrain": true
  }
}

Response 200:
{
  "status": "done",
  "corrected_csv_path": "projects/{pid}/runs/{rid}/corrected_gravity.csv",
  "correction_report": {
    "n_stations": 150,
    "fac_mean_mgal": 926.3,
    "bc_mean_mgal": 357.9,
    "tc_mean_mgal": 4.2,
    "ba_mean_mgal": 12.5,
    "ba_std_mgal": 3.4,
    "nettleton_optimal_density": 2.69,
    "outliers": []
  }
}

Response 422 (g_raw sin elevaciones):
{
  "detail": "Se detectó gravity_type='g_raw' pero no se proporcionaron elevaciones de estación. La corrección Free-Air requiere elevación de cada estación. Por favor proporcionar columna 'elev_m' en el CSV."
}
```

**GET /v2/block-model-profile**
```json
Params: project_id, run_id, x0_m, z0_m, x1_m, z1_m, halfwidth_m=50, include_obs=true

Response 200:
{
  "profile_id": "A-A'",
  "length_m": 2450.0,
  "profile_voxels": [
    {"distance_m": 0.0, "depth_m": 25.0, "density_t_m3": 2.74, "doi_index": 0.08}
  ],
  "profile_observations": [
    {"distance_m": 123.0, "g_obs_ms2": 9.7823e-5, "g_pred_ms2": 9.7815e-5, "normalized_residual": 0.34}
  ]
}
```

### 6.3 Formatos de Datos

**Clean Gravity CSV v1.0** (header obligatorio):
```
# MCVoxel Clean Gravity CSV v1.0
# schema: clean_gravity_v1
# corrections: latitude_grs80,free_air,bouguer,terrain
# reduction_density_gcc: 2.67
# dem_source: OpenTopography_COP30
# terrain_radius_m: 22000
station_id,lat_deg,lon_deg,elev_m,g_obs_mgal,gamma_mgal,fac_mgal,bc_mgal,tc_mgal,g_bouguer_mgal,uncertainty_mgal
```

**Parquet v4.0 — columnas requeridas**:
```
run_type, schema_version="v4.0", ix, iy, iz (int32)
x_m, y_m, z_m (float64) — coordenadas locales
density_t_m3, density_contrast_t_m3, density_anomaly_score (float32)
posterior_std (float32, nullable)
doi_index (float32, nullable) — Oldenburg & Li 1999
susceptibility_si (float32, nullable)
voxel_lat, voxel_lon, voxel_elevation_masl (float64, nullable)
modeled_rock_mass_tonnes (float64) — renombrado de _kg
```

**Observaciones para Observed vs Calculated** (tabla separada en parquet):
```
obs_id (int32), station_x_m, station_z_m (float64)
g_obs_ms2, g_pred_ms2, residual_ms2, normalized_residual, sigma_ms2 (float64)
```

### 6.4 Fórmulas de Referencia

```
Gravedad Normal GRS80:
  gamma(phi) = 9.7803267715 * (1 + 0.001931851353*sin²phi) / sqrt(1 - 0.0066943800229*sin²phi)  [m/s²]

Free-Air Correction:
  FAC(phi, h) = (0.3087691 - 0.0004398*sin²phi)*h - 7.2125e-8*h²  [mGal]

Bouguer Slab Correction:
  BC(rho_s, h) = 0.04193 * rho_s * h  [mGal]  (G = 6.6743e-11, CODATA)

Complete Bouguer Anomaly:
  CBA = g_obs - gamma(phi) + FAC - BC + TC  [mGal]

Depth Weight (Li & Oldenburg 1998):
  w(z_j) = 1 / (z_j + z_0)^(beta/2)
  para gravedad: beta=2 → w(z) = 1 / (z + z_0)   [exponent = 1]

Tikhonov Augmented System:
  G_aug = vstack([Wd@G@Ws, lambda_s*(diag(w)*L@Ws), lambda_m*(diag(w)*Ws)])
  Minimizar: ||G_aug @ m_tilde - d_aug||²

Chi-Squared Reducido:
  chi²_red = (1/N) * sum_i[ (g_obs_i - g_pred_i)² / sigma_i² ]
  Target: chi²_red ≈ 1.0

RMSE:
  RMSE = sqrt( mean( (g_obs - g_pred)² ) )  [m/s² o mGal]

DOI Index (Oldenburg & Li 1999):
  DOI(z) = |m1(z) - m2(z)| / |m_ref_1 - m_ref_2|
  Confiable: DOI < 0.2; No confiable: DOI > 0.2

Hutchinson Diagonal Estimator (Bekas 2007):
  diag(A^{-1}) ≈ (1/K) * sum_k[ z_k * (A^{-1} z_k) ]   z_k ~ Rademacher{±1}

TMI Dipole Kernel (induced, sin remanencia):
  G_ij = C * (3*(f_hat @ r_vec)² - r²) / r⁵
  C = B0 * V / (4*pi)  [nT * m³]

TMI Dipole Kernel con Remanencia (Fase 12):
  J_total = J_ind + J_rem
  J_ind = (chi / mu0) * B0 * f_hat_ind
  J_rem = Q * |J_ind| * f_hat_rem
  G_ij_total = G_ij_induced(f_hat_ind) + Q * G_ij_remanent(f_hat_rem)

Mixtura Gaussiana PGI (Fase 11):
  p(m_j) = sum_k pi_k * N(m_j; mu_k, sigma_k^2)
  k*(j) = argmax_k [pi_k * N(m_j; mu_k, sigma_k^2)]   [asignación MAP]
  m_PGI_j = mu_{k*(j)}                                  [modelo de referencia PGI]

Función Objetivo PGI (Fase 11):
  Phi_PGI = Phi_d + lambda_m * Phi_m + alpha_PGI * ||Wm*(m - m_PGI(m))||^2

Resolución Octree por Nivel (Fase 9):
  h_level_k = h_min * 2^k   para k = 0, 1, ..., n_levels
  h_min = 15 m (horizontal), 20 m (vertical)
  Criterio: h_cell(z) <= z_target / 10  [regla de resolución]

Compresión Wavelet Jacobiano (Fase 10):
  G_compressed = Threshold(WT(G), eps)
  eps = 0.01 * max(|G|)
  compression_ratio = nnz(G_compressed) / nnz(G_full) ≈ 0.05-0.15

Criterio Pearson r Validación (Fase 13):
  r_TQ = corr(m_true, m_terraquantum) > 0.70
  |r_TQ - r_SimPEG| < 0.15
```

---

## 7. Métricas de Calidad Industrial

| Métrica | Estado Actual | Target Tier 1 | Cómo Medir |
|---|---|---|---|
| Chi² reducido final | **chi²=0.000 en test sintético 2026-06-07** — sigma_adaptive sobreestima ruido ~55×, desconectando lambda del Discrepancy Principle | 0.5 – 2.0 para el 90% de los runs | `build_fit_diagnostics` → chi_squared_reduced; activar `select_lambda_chi2_target()` automáticamente (P0-B) |
| RMSE (Observed vs Calc) | No expuesto en UI | NRMSE < 10% de la amplitud de anomalía | Nueva tabla observaciones en parquet |
| Correcciones aplicadas | 0% (nunca) | 100% para g_raw, 0% para CBA (ya corregidos) | Nuevo field `corrections_applied` en report |
| Depth weighting error | 2× demasiado agresivo | Error < 15% en profundidad de esfera test | Test analítico esfera |
| Lambda válido en escala | Solo validado n=49 | Calibrado para n_active ∈ [500, 20,000] | Benchmark sintético multi-escala |
| DOI visualizado | Solo en analytics sidebar | DOI marcado en 3D, máscara en reporte | doi_index en parquet + UI de máscara |
| Export UBC-GIF | No implementado | Archivos .msh + .den leídos por SimPEG sin modificaciones | Test de round-trip con SimPEG |
| Observed vs Calculated | No en UI | Scatter + mapa residuos en DatosView | Nueva pestaña Validación |
| Tiempo de cómputo kernel | ~30s para 200 sensores, 10K voxels | < 60s para 500 sensores, 50K voxels | Benchmark hardware dev |
| False-positive rate (QA) | Checkerboard QA usa sistema diferente | QA usa mismo regularizador que producción | Fix checkerboard_test.py |
| density_max para Fe-ore | 4.2 t/m³ (incorrecto) | ≥ 5.2 t/m³ (magnetita) | Schema validation + UI param |
| NameErrors en runtime | 2 confirmados (gravity_import_api) | 0 | Correr test suite + compileall |
| **Resolución celda core** | ~100 m (TensorMesh uniforme) | **15×15×20 m (Octree core, Fase 9)** | test_octree_mesh.py: n_active < 200K con h_min=15m |
| **Descripción de cuerpos minerales** | 4×4×4 celdas (magnetita a 400m con 100m voxel) | ≥ 13×13×20 celdas (con 15m voxel) | Benchmark dique sintético Fase 13 |
| **Escalabilidad del solver** | Colapsa a n_active > 50K (sin precondicionador) | n_active=200K en < 5 min (LSMR+ILU, Fase 10) | test_lsmr_preconditioned.py: < 300 iter n=100K |
| **Compresión Jacobiano** | Sin compresión — G cargado completo en RAM | < 15% nnz con error forward < 0.5% (Fase 10) | test_wavelet_compression.py |
| **PGI — restricción petrológica** | Sin ancla geológica (no-unicidad libre) | Asignación GMM > 70% celdas correctas en benchmark (Fase 11) | test_pgi_engine.py benchmark 3 litologías |
| **Remanencia magnética** | Solo magnetización inducida (Q=0 asumido) | Inversión correcta para Q=5: error χ < 20% (Fase 12) | test_magnetic_remanence.py cuerpo sintético |
| **Validación vs SimPEG** | Sin benchmark externo | Pearson r gap < 0.15 vs SimPEG (Fase 13) | test_simpeg_comparison.py |
| **Kernel Nagy verificado** | PENDIENTE — no verificado vs analítico | RMSE relativo < 1% vs solución esfera (Fase 13) | test_sphere_forward.py |

---

## 8. Timeline de Desarrollo (semana a semana)

| Semana | Fase | Entregables | Criterios de Aceptación Verificables |
|---|---|---|---|
| 1-2 | Bugfixes críticos + Sigma Fix | Fix NameErrors en gravity_import_api.py (definir `_extract_detected_utm_zone`), fix depth_weight exponent, fix column x→x_m en parquet, fix GEMINI_MODEL_NAME; **exponer noise_floor/noise_pct en endpoint v2** (Sección 2.4); activar Celery async (wiring frontend — Sección 2.5); fix expiración en auth.py (campo expires_at) | `python -m compileall api services` sin errores; chi²_red ≠ 0.000 con noise_floor=0.005; `/async/invert` retorna task_id < 1s |
| 3-4 | Fase 1 — Correcciones (backend) | `gravity_corrections_service.py` con FAC, Bouguer, TC; schema `CorrectionParams`; endpoint `/v2/gravity-corrections/apply`; test analíticos pasando | Tests test_corrections_*.py pasan; FAC para h=1000 da 308.7 mGal ± 0.5 |
| 5 | Fase 1 — OpenTopography | `opentopo_service.py`; fallback a GEE; DEM descargado y almacenado en `projects/{id}/terrain_correction_dem.tif` | DEM descargado para bbox de Chile test; TC para esfera sintética ≥ 0 en todas las estaciones |
| 6 | Fase 1 — UI Wizard | `GravityCorrectionWizard.tsx`; 4 pasos funcionales; `CorrectionPreviewTable`; `NettletonAnalysisChart` | Wizard completa flujo sin errores; gráfico Nettleton muestra mínimo en densidad correcta |
| 7-8 | Fase 2 — Inversion Pipeline v2 | Endpoint `/v2/geophysics-invert`; validadores cross-field; recalibración lambda; `gravity_type="g_raw"` → 422 | Recalibración lambda: Pearson r ≥ 0.80 en benchmark n_active=14K; chi²_red ∈ [0.5,2.0] |
| 9 | Fase 5 — Tests Analíticos | `test_sphere_forward.py`; `test_depth_weighting.py` | Esfera: error < 5%; depth weight: fuentes sintéticas recuperadas a profundidad correcta ± 15% |
| 10 | Fase 3 — Parquet v4.0 | Schema v4.0 con doi_index, modeled_rock_mass_tonnes, tabla observaciones; endpoint `/v2/block-model-profile` | validate_parquet_schema pasa para v4.0; profile endpoint retorna voxels correctos |
| 11-12 | Fase 8 — Observed vs Calculated | `ObservedVsCalculatedChart.tsx`; `ResidualMap2D.tsx`; pestaña Validación en DatosView | Scatter visible con chi² en título; mapa de residuos espacialmente aleatorio en datos sintéticos |
| 13-14 | Fase 4 — 3D Visualization | DOI tooltip en voxel picking; cross-section face render; terrain desde DEM de corrección | 30 FPS en modelo 50K voxels; DOI mostrado en tooltip; slice muestra mapa de calor |
| 15-16 | Fase 6 — Reports | Reporte preprocessing con Nettleton; reporte inversión con Obs vs Calc; export UBC-GIF | Export UBC-GIF leído por SimPEG sin error; reporte incluye chi² y mapa residuos |
| 17 | Fase 7 — AI Integration | Contexto estructurado en chat; prompt con warnings automáticos para chi² > 2 | Chat con chi²>2 incluye advertencia automática; contexto incluye n_observaciones y RMSE |
| 18 | Fases 1-8 — Integración Final | Run completo con datos reales de campo o benchmark industrial | Chi² en rango target; export UBC-GIF leído por SimPEG; Observed vs Calculated en UI |
| 18b | **[Extra] Campo Real Completo** | Módulo de drift y tidal correction (`gravity_corrections_service.py`); import Scintrex CG-6 (`.txt`); agregación de lecturas repetidas | Drift autoconsistente en dos ocupaciones de base; corrección de mareas ±0.30 mGal verificada vs tablas Longman; import sin pérdida de lecturas |
| 19-21 | **Fase 9 — Octree Mesh** | `octree_mesh_builder.py`; kernel G adaptado a celdas variables; auto-grid v2 con parámetros Octree | n_active < 200K con h_min=15m; error kernel esfera < 5% sobre TreeMesh; test_octree_mesh pasa |
| 22-23 | **Fase 10 — Solver Escalable** | `jacobian_wavelet.py`; `solver_preconditioned.py`; selector automático LSQR/LSMR | Wavelet: < 15% nnz, error forward < 0.5%; LSMR+ILU: < 300 iter para n=100K; inversión 200K celdas < 5 min |
| 24-25 | **Fase 11 — PGI** | `pgi_engine.py`; integración en geophysics_service.py; UI campos GMM | Benchmark 3 litologías: > 70% asignación correcta; histograma post-inversión bimodal; convergencia ≤ 10 iter |
| 26-27 | **Fase 12 — Remanencia** | `_build_tmi_kernel_with_remanence()` en magnetometry.py; schema `MagneticRemanenceParams`; UI Q/Inc/Dec | Q=0: sin regresión tests magnéticos existentes; Q=5 sintético: error χ < 20%; barrido Q converge a Q_true ± 50% |
| 28-30 | **Fase 13 — Validación Externa** | 4 benchmarks sintéticos; comparación SimPEG; `validation_report.json`; CI check | Los 4 benchmarks pasan; Pearson r gap < 0.15 vs SimPEG; `validation_report.json` reproducible en 2 runs independientes |

---

## 9. Registro de Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| OpenTopography API key agotada (200 calls/día) | Alta | Medio | Caché local de DEM por bbox; fallback a GEE 32×32 |
| Recalibración lambda produce peor recovery | Media | Alto | Mantener lambda=3.0 como fallback; exponer como parámetro UI |
| Fix depth weight cambia todos los modelos históricos | Alta | Medio | Versionar el motor: v1 (beta full) vs v2 (beta/2); campo `engine_version` en parquet |
| GEE credenciales expiran | Media | Alto | Renovar credenciales en `credenciales_gee.json` antes de expiración; alertar en logs |
| Terrain correction lenta para surveys grandes (> 1000 estaciones × 22km radio) | Alta | Medio | Paralelizar por estación con Dask; pre-computar TC grid y luego interpolar |
| Frontend memory overflow para modelos > 200K voxels (Arrow IPC) | Media | Alto | Límite de 250K voxels en modo full; implementar paginación Arrow (batches de 50K) |
| Worker/main-thread inconsistencia en joint mode (bug existente) | Alta | Bajo | Fix inmediato: sincronizar lógica de joint_structural_score en ambas rutas |
| ASEG-GDF2 formato rechazado por reguladores locales | Baja | Alto | Validar contra ejemplos de ASEG Technical Standards 2025; contactar ASEG Chile si aplicable |
| pyproj falla en Windows con ciertas proyecciones | Media | Medio | Mantener fallback equirectangular; testear en Windows 11 (entorno dev actual) |
| Aumento de latencia si se agrega TC pre-inversión (30-120s extra) | Alta | Medio | TC asíncrono: corre en background, inversión puede empezar sin TC y mejorar iterativamente |
| **Octree aumenta complejidad del kernel** (celda variable, no uniforme) | Alta | Alto | Implementar kernel variadic en `_nagy_prism_safe(dx,dy,dz)` desde Fase 9; test unitario por tipo de celda |
| **ILU(k) fill-factor mal elegido** (demasiado grande → OOM; pequeño → sin mejora) | Media | Medio | Auto-tuning: probar fill_factor ∈ {5, 10, 20}, elegir el que minimiza n_iter×memory |
| **PGI parámetros GMM incorrectos** (μ_k erróneos en bibliografía) | Media | Alto | Siempre exponer μ_k, σ_k como parámetros editables en UI; el default de tabla es punto de partida, no verdad absoluta |
| **PGI puede "anclar" el modelo a un GMM incorrecto** y producir modelo con chi²=1 pero geológicamente erróneo | Media | Alto | Siempre reportar chi² y Observed vs Calculated incluso con PGI; el geofísico decide si el modelo es geológicamente razonable |
| **Remanencia: Inc/Dec desconocidos en campo** | Alta | Medio | Ofrecer inversión de amplitud (modo `amplitude`) como fallback cuando Inc_rem/Dec_rem son inciertos; Q=0 como default |
| **SimPEG no disponible en ambiente de producción** (tests de validación) | Media | Bajo | Fase 13 tests marcados `[optional-simpeg]` en pytest; benchmarks sintéticos sin SimPEG también pasan; SimPEG solo para verificación interna |
| **Kernel Nagy con bug no detectado por esfera** (error en permutación de ejes) | Baja | CRÍTICO | El benchmark de esfera es el gate: si RMSE > 5%, detener todas las fases hasta corregir |
| **Auth sin expiración de keys** (current auth.py sin campo expires_at) | Alta | Alto | Agregar columna expires_at a la tabla SQLite; validar en validate_api_key(); documentar rotación de keys |
| **Sigma adaptivo incorrecto** desconecta chi² del Discrepancy Principle | Alta | Alto | Exponer noise_floor/noise_pct como parámetros (Sección 2.4); tabla de defaults por gravímetro en UI |
| **Drift instrumental no corregido** en datos de campo reales de Scintrex CG-6 | Alta | Alto | Implementar `correct_instrument_drift()` y requerir station_id + timestamps en CSV de campo |
| **Celery/Redis no disponibles en producción** — workers sin configurar | Alta | Medio | Documentar prerequisitos en README; agregar healthcheck de Redis al startup de FastAPI; fallback a modo síncrono si Redis no disponible |
| **treemesh.py (Sprint 3A) no integrado a producción** — existe pero no se llama | Alta | Alto | Fase 9 es wiring, no construcción: conectar treemesh.py en geophysics_service.py y validar contra solución analítica |
| **Datos de campo con corrección de marea integrada en gravímetro** (CG-6 aplica marea automáticamente) — riesgo de doble corrección | Media | Alto | El wizard de import debe preguntar explícitamente qué correcciones ya aplicó el instrumento (modo "correction_status" en CG-6) |

---

## 10. Decisiones Técnicas y Justificaciones

**D1 — Bouguer coefficient: 0.04193 (no 0.04190)**
Justificación: CODATA 2018 value G = 6.6743e-11 m³/(kg·s²). La diferencia de 0.01 mGal para h=100m es insignificante pero la consistencia con el estándar NAGD 2005 (Hinze et al.) es obligatoria para cualquier informe regulatorio.

**D2 — DEM source: Copernicus GLO-30 (COP30) como default**
Justificación: COP30 es el DEM de mayor calidad disponible globalmente en OpenTopography (30m nativo, cobertura polar a ±84°). Supera a SRTMGL1 en zonas forestadas y áreas montañosas andinas con fillado de vacíos mejorado.

**D3 — Terrain correction radius: 22,000 m (Hammer zones A-M) como default**
Justificación: El límite externo del sistema de zonas de Hammer (1939) es 21,943.7 m. La corrección de Bullard B (curvatura) a 166,735 m solo es significativa (>0.3 mGal) para surveys con relieve regional de >500m y amplitudes de anomalía <1 mGal. Para exploración minera de escala local, 22 km es suficiente.

**D4 — Stack para Observed vs. Calculated: Recharts + Visx**
Justificación: Recharts para scatter chart (componentes declarativos, zero-config) y Visx para el mapa 2D de residuos (control fino de DOM para tooltips por estación y colormap divergente). Evitar D3 puro para no introducir reconciliación DOM manual.

**D5 — lambda calibración: Requiere benchmark sintético a escala de producción**
Justificación: La dependencia de lambda con n_obs/n_active es matemáticamente demostrable (Sección 3.4). El benchmark debe correr con nx=32, ny=20, nz=32, block=1552m (configuración real), ruido ~5%, y seleccionar lambda via L-curve o chi²=1 target. Este será el nuevo `PRECONDITIONED_OPERATING_LAMBDA` para la escala de producción.

**D6 — Depth weighting: Usar beta/2=1.0 (no beta=2.0)**
Justificación matemática directa de Li & Oldenburg (1998) Equation 7: "We define depth weighting w(z) = (z₀/(z+z₀))^(β/2)". Para gravedad β=2, entonces el exponente del peso es β/2 = 1. Este cambio es una corrección, no una decisión de diseño.

**D7 — Density bounds: Exponer como parámetros requeridos con lookup table**
Justificación: density_max=4.2 t/m³ bloquea los targets más económicos en Chile (magnetita en skarn Fe, pirita masiva en VMS, cromita en ofiolitas). La solución es exponer density_min y density_max como campos requeridos en el endpoint v2, con una tabla de referencia UI:

| Tipo de depósito | density_min (t/m³) | density_max (t/m³) |
|---|---|---|
| Pórfido Cu (default) | 2.6 | 4.5 |
| Skarn Fe (magnetita) | 2.6 | 5.5 |
| VMS (pirita masiva) | 2.6 | 5.2 |
| Cromita | 2.6 | 4.8 |
| Sal / karst (negativo) | 1.8 | 2.6 |
| Cuenca sedimentaria | 1.5 | 2.8 |

**D8 — No usar LLM para inferir correcciones geofísicas**
Justificación: Las correcciones (FAC, Bouguer, TC) son fórmulas físicas deterministas. Usar un LLM para computarlas sería incorrecto, lento y potencialmente inconsistente. El LLM (Gemini/Claude) se usa SOLO para interpretación geológica del modelo ya corregido e invertido, nunca para computación física.

**D9 — Malla Octree como requerimiento no negociable para surveys reales**
Justificación: Con TensorMesh de 100m, un depósito de 200×200×300m a 400m de profundidad está descrito por ~2×2×3=12 celdas — insuficiente para estimar forma, volumen y orientación. Con celdas de 15m, el mismo cuerpo tiene ~13×13×20=3,380 celdas, resolución suficiente para planificación de sondajes. La malla Octree es el único camino para lograr 15m en zona core mientras se mantiene n_active < 200K, dado que TensorMesh uniforme de 15m sobre una zona de survey típica produciría >100M celdas.

**D10 — Dimensiones de celda core: 15m horizontal × 20m vertical (anisótropo)**
Justificación: La resolución vertical de la inversión gravimétrica es inherentemente peor que la horizontal debido a la naturaleza del decaimiento del kernel (1/r²-1/r³). Usar celdas ligeramente más gruesas en vertical (20m vs 15m) es consistente con la resolución real del método, evita sobreinterpretar el modelo en la dirección menos informada, y reduce n_active ~25% frente a celdas cúbicas de 15m. Alternativa: 15×15×15m también aceptable para surveys magnéticos donde la resolución vertical es mejor.

**D11 — PGI solo con prior petrológico documentado**
Justificación: PGI con un GMM incorrecto puede producir modelos con chi²≈1 pero geológicamente absurdos (el solver encuentra la distribución estadística, no la geología). Para evitar esto, el UI de PGI requiere que el usuario cargue o confirme los parámetros del GMM explícitamente; no hay "modo automático sin datos" de PGI. El modo sin PGI (inversión estándar) sigue disponible para todos los casos.

**D12 — Remanencia: Q=0 como default, Inc_rem/Dec_rem siempre explícitos**
Justificación: Una remanencia con dirección incorrecta produce modelos peores que ignorar la remanencia. El default Q=0 (solo inducida) es conservador y reproducible. Cuando el usuario activa remanencia, debe ingresar Inc_rem y Dec_rem explícitamente (o usar inversión de amplitud si son desconocidos). No hay estimación automática de dirección de remanencia desde datos de campo sin AMS medido en laboratorio.

**D13 — Fase 13 es bloqueante antes de cualquier claim público de "Tier 1"**
Justificación: Sin benchmark publicable que demuestre comparabilidad con SimPEG/UBC-GIF, cualquier afirmación de "Tier 1" es marketing. La validación externa no es una feature adicional — es la evidencia que sostiene todas las demás afirmaciones del plan. El `validation_report.json` debe ser reproducible por cualquier tercero con el mismo hardware.

**D14 — La Fase 13 incluye la verificación del kernel Nagy como gate crítico**
Justificación: El kernel Nagy no fue verificado contra solución analítica en ningún punto del desarrollo. Si hay un error en la permutación de ejes (x↔y, y↔z), todos los modelos producidos hasta la corrección son incorrectos. El test `test_sphere_forward.py` con criterio RMSE < 1% es el primer test que debe pasar en la Fase 13. Si falla, todas las fases previas se suspenden hasta que el kernel sea corregido.

---

*Fin del Plan Industrial Tier 1 — MCVoxel / TerraQuantum*
*Versión 2.1.0 — 2026-06-07*
*13 Fases + 5 brechas adicionales documentadas — Target: Tier 1 motor matemático al completar las 13 fases; producto industrial completo requiere además las 5 brechas de Categorías 8-12 (auth, async, campo real, sigma, despliegue).*
*Para preguntas técnicas sobre este documento, revisar las secciones de auditoría fuente o contactar al arquitecto del sistema.*
