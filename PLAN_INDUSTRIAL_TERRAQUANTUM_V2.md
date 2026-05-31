# ☢️ TERRAQUANTUM — INDUSTRIAL READINESS MASTER AUDIT V2 ☢️

**Clasificación:** CONFIDENCIAL / BOARD-LEVEL TECHNICAL DUE DILIGENCE
**Fecha:** 2026-05-30
**Marco mental del auditor:** Recomendar o rechazar una inversión de USD 50M.
**Método:** Toda afirmación está respaldada por archivos concretos y, donde fue posible, por **ejecución en vivo** del código (no por lo que dice el roadmap previo).

> **Diferencia con V1:** El `PLAN_INDUSTRIAL_TERRAQUANTUM.md` (V1) se auto-asignó **68/100** y un commit posterior reclama **80**. Esta auditoría, tras leer y **ejecutar** el motor, lo sitúa en **58/100**. La brecha es el núcleo de este documento: V1 confunde *corrección matemática del código* (que es alta y real) con *industrial readiness del producto* (que es de prototipo). Ambas cosas son ciertas a la vez.

---

## 1. RESUMEN EJECUTIVO

TerraQuantum tiene un **motor matemático genuinamente bueno** envuelto en un **producto de nivel prototipo** con **una bomba de cumplimiento (compliance) sin desactivar**.

Tres verdades simultáneas:

1. **La matemática es real y está validada.** El kernel de Nagy, la regularización Tikhonov compuesta, el depth weighting (Li & Oldenburg β=2), la L-curve por curvatura de Menger y la UQ posterior por Hutchinson están **correctamente implementados, citados y probados**. El test `test_analytic_sphere_validation.py` (validación contra solución analítica de esfera) y los 7 tests de Hutchinson **pasan en vivo** (9 passed, 184s). Esto no es código académico de juguete.

2. **La recuperación geofísica real es mediocre, y el sistema lo admite.** En el benchmark sintético *más favorable posible* (esfera fácil, mismo operador para generar e invertir = "inverse crime", σ de ruido exacto entregado al solver), la recuperación es **Pearson r = 0.6272 → "ACCEPTABLE"**, no "EXCELLENT". Peor: en la ejecución en vivo, **el 49.3% de las celdas activas saturan el bound de densidad [2.6, 4.2]** — la mitad del modelo "recuperado" es un artefacto del recorte, no señal invertida. En el dataset **real** (Andes, `andes97`), el reporte de producción muestra un campo modelado **idénticamente cero** y estadísticos de ajuste mutuamente contradictorios.

3. **El compliance JORC/NI 43-101 era una bomba activa (su pieza más visible ya fue desactivada).** Al momento de la auditoría, el reporte de producción emitía `estimated_total_tonnage: 1448140268380129` (1.4 **cuatrillones** de toneladas — físicamente absurdo), `drill_recommendation` y `max_probability: 1.0` **junto a un disclaimer que decía que esto NO es una estimación de recursos** — peor que cualquiera de las dos cosas por separado. **✅ Corregido (2026-05-30):** estos campos ahora salen en `null` por defecto (`compliance_mode: "exploration_only"`; ver §11). **Residual:** la deuda persiste en las columnas del parquet del block-model y en los routers económicos montados (`pit_design`/`mine_method`/`scenario_sweep`), así que el frente de compliance está *abierto pero ya no sangrando*.

**Veredicto de inversión:** NO invertir USD 50M hoy. SÍ vale una **tesis de inversión por etapas (staged)**: el activo defendible es el motor + la cultura de QA. El producto, la escala, el compliance y el desempeño en dato real son trabajo pendiente de 12–24 meses. Es un **Prototipo Avanzado**, no una plataforma preindustrial.

---

## 2. ESTADO ACTUAL (EVIDENCIA, NO NARRATIVA)

| Subsistema | Evidencia concreta | Estado |
| :--- | :--- | :--- |
| Kernel Nagy + near/far + KDTree + CSR | `exploration/gravimetry.py:98-323` | ✅ Correcto, cacheado por geometría |
| Tikhonov + depth weighting + column scaling + Wd | `gravimetry.py:701-987` | ✅ Correcto |
| L-curve (Menger) | `gravimetry.py:458-699` | ✅ Correcto pero **degenerado** en problemas no-únicos |
| UQ posterior (Hutchinson) | `gravimetry.py:15-67, 989-1110` | ✅ Correcto + 7 tests pasan |
| Validación analítica de esfera | `tests/test_analytic_sphere_validation.py` | ✅ **2 passed en vivo** |
| Recuperación sintética | `tests/synthetic_recovery_results.json` → r=0.6272 | ⚠️ Solo ACCEPTABLE |
| Saturación del bound | Ejecución en vivo: **49.3%** celdas recortadas | ⚠️⚠️ Modelo dominado por el clip |
| Focusing MS-IRLS | Ejecución en vivo: `conv=False`, maxd 0.28→0.19 | ⚠️ Contraproducente; experimental |
| Ajuste en dato real (andes97) | `report.json`: `modeled_*=0.0`, chi²=0.009 vs nrmse=0.636 | ⚠️⚠️ Degenerado / diagnósticos inconsistentes |
| Transporte block-model | `app/api/block-model/route.ts`: JSON, `limit=5000` | ⚠️ JSON crudo, mitigado por truncar |
| Render 3D | `Scene3D.tsx:648` InstancedMesh + dispose; clipping/slices | ✅ Mejor de lo que V1 dice |
| Compliance terminológico | 534 ocurrencias en 56 archivos; backend-pesado | ⚠️⚠️ Migración a medias |
| Tonnage/drill_rec en payload | `geophysics_service.py:1249` (gate `compliance_mode`) | ✅ **Corregido (2026-05-30):** null por defecto, opt-in `conceptual_scenario` (ver §11) |
| Tonnage/probability en parquet block-model | columnas del parquet + `core/block_model_store.py` | ⚠️⚠️ Residual: el gate aún no llega al parquet |
| Routers económicos montados | `main.py:48,51,49` (pit_design, mine_method, scenario_sweep) | ⚠️⚠️ Contradice el pivot a exploración |
| Preflight regional | `services/regional_scale_preflight_service.py` | ✅ Compuerta sensata (gate, no escala) |

**Stack verificado:** Python 3.14.4, numpy 2.4.4, scipy 1.17.1, polars 1.40.0. Backend ≈43k LOC Python; frontend ≈14.7k LOC TS/TSX. Compilación de módulos núcleo: OK.

---

## 3. INDUSTRIAL READINESS SCORE

Puntajes independientes (0–100), recalibrados contra la industria Tier-1 (SimPEG/UBC-GIF/Seequent), no contra "¿el código está bien escrito?".

| Eje | Score | Justificación de una línea |
| :--- | :---: | :--- |
| **Matemática** | **82** | Implementación correcta y validada; penaliza monofísica, UQ solo lineal-gaussiana y clip en vez de constraint de positividad. |
| **Geofísica** | **62** | Forward correcto, pero recuperación ACCEPTABLE, 49% de saturación de bound, fit degenerado en dato real. |
| **HPC** | **45** | CSR explícito + ensamblado Python (setdiff1d por sensor) → techo ~150k vóxeles; sin matrix-free/Cython. |
| **Arquitectura** | **66** | Monorepo limpio, capa de servicios, persistencia por run; pero fronteras de dominio confusas (economía aún acoplada). |
| **Frontend** | **66** | InstancedMesh + dispose + clipping/slices reales; falta colormap geofísico estándar y transporte binario. |
| **UX** | **55** | UI científica funcional con paneles de diagnóstico; sin gestión de proyecto, colaboración ni acabado industrial. |
| **QA / Trazabilidad** | **72** | Cultura de QA real y honesta (benchmark reproducible, tests pasan); penaliza escala de juguete e "inverse crime". |
| **Compliance** | **35** | Tonnage 1.4e15 + drill_recommendation en vivo; estrategia de migración "soft" inadecuada para minería. |
| **Escalabilidad** | **42** | Techo arquitectónico duro; transporte JSON; single-node; sin evidencia de escalado horizontal. |
| **Producto** | **42** | Monofísica (solo gravedad), sin integración de sondajes ni modelado geológico; compite contra players consolidados. |

### INDUSTRIAL READINESS SCORE TOTAL: **58 / 100**

**Clasificación: PROTOTIPO (avanzado)** — banda 50–70. A ~12 puntos de "Preindustrial" (70–85). El cuello de botella para subir no es la matemática (ya es Tier-1); son compliance, escala y desempeño en dato real.

> Ponderación usada: Geofísica 15%, QA 13%, Matemática 12%, Compliance 12%, HPC 10%, Arquitectura 10%, Frontend 8%, Escalabilidad 8%, UX 7%, Producto 5%. (Se pondera alto lo que un comprador minero audita primero: ¿funciona en mi dato? ¿es defendible legalmente? ¿escala?)

---

## 4. VALIDACIÓN DEL ROADMAP V1 (eliminando tareas fantasma)

| Tarea del roadmap V1 | Veredicto | Por qué |
| :--- | :--- | :--- |
| Quick Win: Purga JORC (`grade`→proxy) | **PARCIALMENTE COMPLETADO** | Frontend "Fase A" eliminó identidad minera; `is_demo_grade`/`_demo_grade_value`/disclaimers existen. PERO 534 ocurrencias persisten; `tonnage`/`drill_recommendation` siguen vivos. **No es una tarea nueva: es una estrategia a medio ejecutar.** |
| Quick Win: Transporte binario (Arrow) | **AÚN NECESARIO** | Sigue JSON; "mitigado" truncando a 5000 vóxeles (`block-model/route.ts`). Eso **rompe** la visualización del modelo completo, no la resuelve. |
| Quick Win: Reescritura kernel en Cython/Rust | **PRIORIDAD EQUIVOCADA** | El ensamblado Python existe (`gravimetry.py:198-234`) y es lento, pero no es el primer cuello de botella del *negocio*. Posponer hasta tener matrix-free, o no se gana nada. |
| Quick Win: Focusing usa Tensor Mesh | **OBSOLETO / DESPRIORIZAR** | Focusing es contraproducente en vivo (`conv=False`, reduce contraste). No invertir en consistencia de malla de una feature que aún no recupera mejor. |
| Fase 1: Erradicar terminología JORC | **REDEFINIR** | V1 lo trata como rename. La acción correcta es **arquitectónica**: separar payload "exploración" (limpio) de "escenario conceptual" (opt-in, gated). |
| Fase 2: Kernel magnético + Joint Inversion | **AÚN NECESARIO (el verdadero diferenciador)** | Correcto como prioridad estratégica. Es lo único que rompe la monofísica que hoy limita el producto a 42/100. |
| Fase 2: Geological constraints (pozos) | **AÚN NECESARIO** | Crítico: hoy la no-unicidad se "resuelve" con un clip que satura el 49%. Constraints de pozo atacan la causa raíz. |
| Fase 3: Matrix-free (>2M vóxeles) | **POSPONER (no obsoleto)** | Correcto técnicamente, pero es 2028. Ningún comprador paga por 2M vóxeles si no confía en 10k. |
| Fase 3: FMM campo lejano | **NO CONSTRUIR (todavía)** | Over-engineering. El point-mass actual ya cubre el campo lejano a costo trivial. |
| Fase 4: Plugins Leapfrog/Seequent | **AÚN NECESARIO (adelantar)** | Subestimado en V1. La interoperabilidad (importar/exportar a Leapfrog) es más comercial que la inversión "viva". |
| Fase 4: "Inversión viva" (streaming) | **NO CONSTRUIR** | Solución a un problema que ningún cliente tiene aún. Humo. |
| Innovación: Learned preconditioners (IA) | **CORRECTO: descartar** | V1 acierta. Es humo. |
| Innovación: AMR/Octree | **CORRECTO: posponer** | V1 acierta. El tensor mesh basta. |
| Innovación: MCMC bayesiano completo | **CORRECTO: investigación** | V1 acierta. Intratable para SaaS 3D. |

**Conclusión Fase 2:** El roadmap V1 está **70% bien dirigido** pero infla quick-wins ya hechos a medias y prioriza HPC (Cython) por encima de compliance y joint inversion, que es donde está el valor y el riesgo reales.

---

## 5. AUDITORÍA CIENTÍFICA POR SISTEMA (FASE 3)

| Sistema | Estado | Nivel industrial | Riesgo principal | Qué falta para Tier-1 |
| :--- | :--- | :--- | :--- | :--- |
| Kernel Nagy | Correcto | **Tier-1** | Ninguno material | Tensor field (gxx…gzz) para gradiometría |
| Near/Far + KDTree | Correcto | Tier-2 | Loop Python por sensor | Ensamblado vectorizado/compilado |
| Sparse CSR | Correcto | Tier-2 | Techo de RAM ~150k | Operador matrix-free |
| Tensor mesh + Laplaciano | Correcto | Tier-1 | — | Topografía deformada real |
| Tikhonov compuesto | Correcto | Tier-1 | — | Constraints duros/blandos |
| Depth weighting | Correcto (β=2) | Tier-1 | Sesgo de profundidad inherente | Sensitivity-based weighting opcional |
| L-Curve (Menger) | Correcto | Tier-2 | **Degenerada** cuando el misfit es plano | GCV / discrepancy principle como alternativa |
| Conditioning / column scaling | Correcto | Tier-1 | — | — |
| LSQR | Correcto | Tier-1 | — | CG/IRLS conmutables |
| Bound de densidad | **Riesgoso** | Sub-industrial | **49% saturación → modelo = artefacto del clip** | Reemplazar clip por **projected gradient / NNLS / bound constraints** dentro del solver |
| Focusing MS-IRLS | Experimental | No producción | `conv=False`, empeora recuperación | Aislar; no exponer hasta que mejore r |
| DOI | Correcto (doble inversión L&O 1999) | Tier-2 | — | Calibración de umbrales |
| Synthetic recovery | Correcto y honesto | Tier-2 | Escala juguete + inverse crime | Benchmark a escala real + operador distinto data/inversión |
| Checkerboard | Existe (`exploration/checkerboard_test.py`) | Tier-2 | Sin reporte de resolución publicado | Mapa de resolución espacial |
| Chi² / misfit | **Inconsistente en dato real** | Sub-industrial | chi²=0.009 vs nrmse=0.636 vs misfit=13.8% no concilian | Una sola definición de misfit, validada |
| UQ posterior | Correcto + testeado | Tier-2 | Solo lineal-gaussiana | Propagar a la UI siempre (hoy `computed:false`) |
| Exportaciones | Parquet (block model) + VTK | Tier-2 | Reporte JSON monolítico (3646 líneas con residual map embebido) | Reporte paginado / Arrow |

**El hallazgo científico más importante:** el motor **ajusta el dato casi perfecto (misfit 0.01%) pero recupera el modelo solo a r=0.63**, y compensa la no-unicidad con un **clip que satura la mitad de las celdas**. Esto es física honesta (la gravimetría es intrínsecamente no-única en profundidad), pero significa que el "contraste de densidad recuperado" que se muestra al usuario está **fuertemente moldeado por una restricción dura arbitraria**, no por los datos. Un geofísico Tier-1 lo detectaría en la primera revisión.

---

## 6. COMPARACIÓN CONTRA LA INDUSTRIA (FASE 4)

| Categoría | vs SimPEG/UBC-GIF | vs Leapfrog/Seequent | vs Oasis Montaj | Posición TQ |
| :--- | :--- | :--- | :--- | :--- |
| Física forward | **Equivalente** (Nagy correcto) | Superior (transparente) | Equivalente | 🟢 Fortaleza |
| Inversión | Inferior (SimPEG: multifísica, IRLS maduro, constraints) | Superior a Edge en transparencia | Superior (3D voxel veloz) | 🟡 |
| Multifísica / Joint | **Muy inferior** (TQ solo gravedad) | Inferior | Inferior | 🔴 Brecha crítica |
| QA / reproducibilidad | **Equivalente o superior** (benchmark + seed + disclaimers) | Superior (cajas negras) | Superior | 🟢 Fortaleza diferencial |
| Escalabilidad | Inferior (SimPEG escala a regional) | Inferior | Inferior (grids 2D masivos) | 🔴 |
| UX / Visualización | **Muy superior** (SimPEG no tiene UI) | Inferior (Leapfrog es el estándar) | Superior | 🟡 |
| Cloud / SaaS | Superior (nativo) | Superior (Leapfrog es desktop) | Superior | 🟢 Nicho |
| Exportación / interop | Inferior | **Muy inferior** (sin plugins Leapfrog) | Inferior | 🔴 |
| Automatización | Superior (pipeline auto) | Equivalente | Superior | 🟢 |
| Compliance | Inferior (SimPEG no afirma recursos) | **Muy inferior** (Seequent es JORC-aware) | Inferior | 🔴 Riesgo |

**Nicho defendible real:** *"Motor de inversión geofísica cloud-native, reproducible y auditable, con UI 3D inmediata"* — el cruce entre el rigor abierto de SimPEG y el cero-setup de un SaaS. **Ese nicho es genuino.** Pero solo se sostiene si (a) deja de afirmar recursos/tonelajes, (b) suma al menos magnetometría, y (c) interopera con Leapfrog.

---

## 7. AUDITORÍA HPC (FASE 5)

- **Escalabilidad actual:** buena hasta ~100–150k vóxeles activos; el preflight regional (`regional_scale_preflight_service.py`) **gatea** datasets regionales recomendando subset/tiling en vez de invertir — decisión correcta y honesta.
- **Cuello de botella real (en orden):**
  1. **Transporte JSON** (`block-model/route.ts`, `limit=5000`). Es el primero que el usuario *ve* romperse: o trunca el modelo o colapsa el navegador. **Optimizar primero.**
  2. **Ensamblado del kernel en Python** (`gravimetry.py:198-234`): `setdiff1d` + `concatenate` por sensor bajo ThreadPool. Libera GIL en numpy/scipy pero el overhead Python domina con muchos sensores.
  3. **Matriz CSR explícita en RAM**: techo duro. Para >1M vóxeles, implosiona.
- **Qué romperá primero:** el navegador (transporte), no el solver.
- **Qué optimizar:** transporte binario (semanas) → matrix-free (meses) → ensamblado compilado (solo si matrix-free no basta).
- **Qué NUNCA vale la pena:** GPU sobre CSR explícito (el rango dinámico 1e-10 de la gravedad muere en float32; transferir CSR por PCIe no compensa). FMM hoy. Optimizar el ensamblado Python *antes* que el transporte.

---

## 8. AUDITORÍA FRONTEND (FASE 6)

- **¿Software industrial, académico, SaaS o geocientífico?** Hoy es un **dashboard científico SaaS competente** — más cercano a "herramienta geocientífica seria en construcción" que a "tech-demo" (V1 fue injusto aquí).
- **Lo bueno (verificado):** `THREE.InstancedMesh` con `dispose` seguro (`Scene3D.tsx:648-676`), **clipping/slicing volumétrico real** (`computeClippingPlanes`, `SliceControls.tsx`), paneles de analítica (L-Curve, DOI, incertidumbre, recovery coverage), store Zustand, rutas API como proxies delgados.
- **Lo que falta:**
  1. **Colormap geofísico estándar** (no hay viridis/turbo/cmocean detectado) — los geólogos esperan paletas perceptualmente uniformes.
  2. **Transporte binario** (hoy truncado a 5000 vóxeles).
  3. **Propagación de incertidumbre a la vista** (la UQ existe pero el run la trae `computed:false`).
  4. Gestión de proyectos, comparación de runs robusta, export reproducible one-click.
- **Qué cambiaría primero:** colormaps científicos + leyenda física con unidades + mostrar SIEMPRE el disclaimer y la σ posterior junto al modelo.

---

## 9. AUDITORÍA DE PRODUCTO (FASE 7) — "¿Pagaría como CEO minero?"

**No, todavía no — pero pagaría por un piloto.**

- **Por qué SÍ pagaría un piloto:** cero-setup, inversión 3D reproducible y auditable, QA transparente, resultados en minutos. Para una junior exploradora sin equipo de geofísica interno, esto es atractivo.
- **Por qué NO firmaría enterprise hoy:**
  1. **Solo gravedad.** Mi programa de exploración usa magnetometría, IP, MT, y sondajes. Una plataforma monofísica es un add-on, no un sistema.
  2. **No confío en el dato real.** Si el reporte de mi propio dataset muestra `modeled=0` y estadísticos de ajuste que no concilian, pierdo confianza inmediatamente.
  3. **Me expone legalmente.** Si el JSON dice "tonelaje estimado" y "recomendación de perforación", mi QP (Persona Competente) y mis abogados lo vetan. El disclaimer no me protege; me incrimina.
  4. **No se conecta a Leapfrog**, donde vive mi modelo geológico.
- **Funcionalidad imprescindible para confiar:** (a) eliminación total de afirmaciones de recurso/tonelaje del flujo por defecto; (b) al menos joint grav+mag; (c) constraints de sondaje; (d) export a Leapfrog; (e) un reporte de ajuste **consistente**.

---

## 10. RIESGOS CRÍTICOS

| # | Riesgo | Severidad | Evidencia | Mitigación |
| :-- | :--- | :---: | :--- | :--- |
| R1 | **Responsabilidad JORC/NI 43-101** (RESIDUAL): el reporte por defecto ya NO emite tonelaje/probability/drill_recommendation (✅ gate `compliance_mode`, §11). Persiste en el **parquet del block-model** (columnas `tonnage`/`probability`) y en los **routers económicos montados** | 🟠 ALTO (era 🔴 CRÍTICO) | `geophysics_service.py:1249` (mitigado); `main.py:48,49,51` + parquet (residual) | Extender el gate al parquet; desmontar/gatear `pit_design`/`mine_method`/`scenario_sweep` |
| R2 | **Modelo dominado por el clip** (49% saturación) | 🔴 CRÍTICO | Ejecución en vivo | Constraint de positividad/bound dentro del solver (NNLS/projected gradient) |
| R3 | **Diagnósticos de ajuste inconsistentes en dato real** (modeled=0; chi² vs nrmse vs misfit) | 🔴 CRÍTICO | `report.json:85-104` | Una sola definición de misfit; wirear `modeled` al forward real; test de dato real |
| R4 | **Monofísica** limita el TAM a un nicho | 🟠 ALTO | `main.py` (solo gravedad) | Kernel magnético + joint |
| R5 | **Techo HPC + transporte JSON** | 🟠 ALTO | `block-model/route.ts` | Arrow/binario → matrix-free |
| R6 | **Divergencia backend/frontend**: economía desmontada del UI pero viva en API | 🟠 ALTO | `main.py:48,49,51` | Desmontar o aislar routers económicos tras flag |
| R7 | **Benchmarks optimistas** (inverse crime + escala juguete) | 🟡 MEDIO | `synthetic_recovery_benchmark.py:313-398` | Operador distinto para generar/invertir; escala realista |
| R8 | **L-curve degenerada** en problemas planos | 🟡 MEDIO | Ejecución en vivo | GCV/discrepancy principle de respaldo |

---

## 11. QUICK WINS (≤ 2 semanas c/u, alto ROI)

> **✅ COMPLETADO (2026-05-30) — "Cortar la bomba JORC del payload por defecto".** `build_geophysics_report` ([geophysics_service.py:1249](terraquantum-backend/services/geophysics_service.py)) ahora emite `estimated_total_tonnage`, `estimated_anomaly_tonnage`, `max_probability` y `drill_recommendation` **en `null` por defecto** (`compliance_mode: "exploration_only"`); solo se exponen bajo `expose_economic_estimates=True` (modo `conceptual_scenario`, opt-in). `avg_grade` ya estaba gateado. Las variantes canónicas seguras (`max_ranking_score`, `preliminary_signal`, `max_target_score`, `avg_anomaly_intensity`, `risk_level`) se conservan siempre. **Verificado:** claves presentes (no se rompen consumidores), frontend lee con fallback `??`/`||` (no crashea), `test_grade_integrity` 5/5, módulo compila. **Residual del mismo frente (sigue pendiente, ver R1):** las columnas `tonnage`/`probability` del parquet del block-model y los routers económicos (`pit_design`/`mine_method`/`scenario_sweep`) aún existen.

1. **[2 días] Reparar el reporte de ajuste.** Wirear el campo `modeled` al forward real `G@m`; unificar a una sola métrica de misfit; añadir un test que falle si `modeled` es todo-cero con densidad no-trivial. (Ataca R3, riesgo de credibilidad.)
2. **[1 semana] Reemplazar el clip duro por un bound constraint real** (projected LSQR / NNLS con cota superior) y reportar % de celdas en la cota como métrica de calidad de primer nivel. (Ataca R2.)
3. **[3 días] Colormaps geofísicos** (viridis/turbo/cmocean) + leyenda con unidades + σ posterior visible. (UX inmediata.)
4. **[2 días] Aislar focusing y economía tras feature flags off-by-default.** El payload del reporte ya está gateado (✅ arriba); falta desmontar/gatear los routers `pit_design`/`mine_method`/`scenario_sweep` y el focusing. (Limpia R6 sin borrar código.)
5. **[1 semana] Reporte de checkerboard/resolución publicado** como artefacto QA de cara a cliente.

---

## 12. ROADMAP INDUSTRIAL V2

### Q3 2026 (3 meses) — "Defendible y honesto"
**Objetivo: subir Compliance 35→70 y Geofísica 62→72. No tocar física nueva.**
- Quick wins 1–5 (la purga JORC del payload, antes #1, **ya ejecutada** — ver §11).
- Separación arquitectónica: payload `exploration` (limpio) vs `conceptual_scenario` (opt-in, gated, con disclaimer obligatorio en cada campo). **Semilla ya plantada:** `build_geophysics_report` ya distingue ambos modos vía `expose_economic_estimates`/`compliance_mode`; falta extenderlo al parquet del block-model y exponer el flag en el schema/endpoint. Migrar `favorability_service` a la ruta canónica de scoring.
- Transporte binario (Apache Arrow / Float32Array) en `/block-model`, eliminando el cap de 5000.
- Benchmark sintético honesto: operador distinto para generar vs invertir; añadir caso a escala realista (≥100k vóxeles).
- CI que ejecute el recovery benchmark y los tests científicos en cada push (hoy pasan localmente en 184s).

**Dependencias:** ninguna externa. Bloqueante de todo lo demás (no se vende lo que no es defendible).

### Q4 2026 – Q1 2027 (6 meses) — "Resolver la no-unicidad"
**Objetivo: Geofísica 72→80.**
- **Geological constraints**: fijar densidad en celdas con sondaje conocido (hard) y modelos lito-estructurales (soft) vía `m_ref` y `W_m` (la infraestructura ya existe en `solve_inversion_lsqr`).
- Discrepancy principle / GCV como respaldo de la L-curve.
- Propagación de incertidumbre a la UI por defecto (mapas de confianza).
- Reporte de resolución (checkerboard + DOI calibrado) como entregable de cliente.

**Dependencias:** requiere Q3 (payload limpio) hecho.

### 2027 (12 meses) — "El salto multiparamétrico"
**Objetivo: Producto 42→65, romper la monofísica.**
- **Kernel magnético (vectorial).**
- **Joint inversion grav+mag con cross-gradient.** *Este es el killer feature.*
- **Interop Leapfrog/Seequent** (import/export de mallas y superficies). Comercialmente más valioso que cualquier optimización HPC.

**Dependencias:** joint requiere el solver abstraído (interfaz MatVec/RMatVec) — diseñarla en Q4 2026.

### 2028 (24 meses) — "Escala regional"
**Objetivo: HPC 45→70, Escalabilidad 42→70.**
- **Operador matrix-free** (única vía sobre el millón de vóxeles).
- Ensamblado compilado (Numba/Rust) **solo si** matrix-free no basta.
- Topografía deformada real en mallas irregulares.

**Dependencias:** matrix-free requiere la abstracción del solver (2027).

---

## 13. QUÉ NO CONSTRUIR / QUÉ POSPONER / QUÉ YA

| Categoría | Items |
| :--- | :--- |
| **NO construir** | Learned preconditioners (IA), MCMC bayesiano completo, "inversión viva" streaming, FMM campo lejano, GPU sobre CSR explícito, AMR/Octree. |
| **POSPONER (2028+)** | Matrix-free (necesario, no urgente), ensamblado Cython/Rust, topografía deformada. |
| **CONSTRUIR YA (Q3 2026)** | ~~Cortar bomba JORC del payload~~ (✅ hecho), reparar reporte de ajuste, bound constraint real, transporte binario, colormaps, CI de benchmarks. |

---

## 14. ORDEN EXACTO DE EJECUCIÓN (con dependencias)

```
1. [✅ HECHO 2026-05-30] Cortar tonnage/drill_rec/probability del payload por defecto (gate compliance_mode) ← habilitaba (7) y (11); residual: parquet + routers
2. [Q3] Reparar campo `modeled` + unificar misfit + test anti-regresión ← sin dependencias, credibilidad
3. [Q3] Bound constraint real (NNLS/projected) reemplaza el clip         ← sin dependencias, ataca artefacto 49%
4. [Q3] Transporte binario Arrow (quita cap 5000)                        ← sin dependencias
5. [Q3] Colormaps + σ en UI + flags off para focusing/economía          ← depende de (2) para σ
6. [Q3] CI: recovery benchmark + tests científicos por push             ← depende de (2)
7. [Q4] Separación payload exploration vs conceptual_scenario           ← depende de (1)
8. [Q4] Geological constraints (hard/soft vía m_ref/W_m)                ← depende de (3)
9. [Q4] Abstracción del solver (MatVec/RMatVec)                          ← habilita (10) y (12)
10.[2027] Kernel magnético → Joint grav+mag (cross-gradient)            ← depende de (9)
11.[2027] Interop Leapfrog                                               ← depende de (7)
12.[2028] Operador matrix-free                                           ← depende de (9)
13.[2028] Ensamblado compilado (solo si 12 no basta)                     ← depende de (12)
```

**Regla de oro de ejecución:** nada de física nueva (paso 8+) hasta cerrar compliance y credibilidad (pasos 2–3; el paso 1 ya está hecho). El reporte por defecto ya no emite el tonelaje fantasma de 1.4e15 — pero la deuda persiste en el parquet del block-model y en los routers económicos montados, así que el frente de compliance NO está cerrado, solo desactivada su pieza más visible.

---

## 15. EVALUACIÓN DE OPORTUNIDADES DISRUPTIVAS (FASE 9)

| Iniciativa | Valor real | Complejidad | Riesgo | ROI técnico | ROI comercial | Veredicto |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| Joint inversion (grav+mag) cross-gradient | Alto | Alta | Medio | Alto | **Muy alto** | ✅ HACER (2027) |
| Geological constraints (sondajes) | Alto | Media | Bajo | **Muy alto** | Alto | ✅ HACER YA (Q4) |
| Bound/positividad real en el solver | Alto | Baja | Bajo | **Muy alto** | Alto | ✅ HACER YA (Q3) |
| Matrix-free | Medio | Alta | Medio | Alto | Medio | 🟡 POSPONER (2028) |
| Interop Leapfrog | Medio | Media | Bajo | Medio | **Muy alto** | ✅ HACER (2027) |
| Resolution matrix / posterior covariance | Medio | Media | Bajo | Alto | Medio | 🟡 La UQ ya da una vía; ampliar en Q4 |
| Tensor gravity gradiometry (gxx…gzz) | Medio | Media | Bajo | Alto | Medio | 🟡 Considerar tras joint |
| GPU solvers | Bajo | Alta | Alto | Bajo | Bajo | ⛔ NO (rango dinámico + PCIe) |
| Wavelet compression / H-matrices | Bajo | Alta | Medio | Medio | Bajo | ⛔ NO (matrix-free primero) |
| Physics-informed / learned priors | Bajo | Alta | **Muy alto** | Bajo | Bajo | ⛔ NO (no generaliza, humo) |
| Full Bayesian MCMC | Bajo | **Muy alta** | Alto | Bajo | Bajo | ⛔ NO (intratable SaaS 3D) |
| AMR / Octree | Bajo | Alta | Medio | Bajo | Bajo | ⛔ NO (tensor mesh basta) |

---

## 16. CONCLUSIÓN FINAL DEL AUDITOR

TerraQuantum es la cosa más rara en software geofísico: **un motor matemáticamente honesto**. El benchmark reporta "ACCEPTABLE" cuando podría haber mentido "EXCELLENT"; el código documenta sus propias limitaciones (la nota de alcance de Hutchinson es ejemplar); los tests contra solución analítica pasan. Esa honestidad es el activo más difícil de comprar y el que sostiene la tesis de inversión.

Pero **la honestidad del código no ha llegado al producto**. El producto aún emite tonelajes de 1.4 cuatrillones de toneladas con una recomendación de perforación, recupera el dato real con un campo modelado en cero, y disfraza la no-unicidad con un clip que pinta la mitad del modelo. Un motor honesto envuelto en un producto que sobrepromete es la peor combinación posible para una auditoría JORC.

**Recomendación:** financiar por etapas, condicionado a cerrar los pasos 1–3 del orden de ejecución en 90 días. Si el equipo ejecuta la limpieza de compliance y credibilidad con la misma seriedad con que escribió el kernel de Nagy, esto sube de 58 a ~72 (Preindustrial) en un trimestre, y se vuelve invertible en serio. Si no lo hace, el motor brillante seguirá siendo un pasivo legal con buena visualización.

*— Fin de la auditoría V2. Toda afirmación es trazable a archivo:línea o a ejecución en vivo registrada en esta sesión.*


🗺️ El Nuevo Plan Maestro (Cómo encaja todo)
Ya casi terminamos el motor matemático. Una vez que salgamos de la Fase 10 (VTK para Leapfrog y Magnetometría), tu rol cambiará de "Científico Jefe" a "CTO de Plataforma".

El roadmap de cierre será así:

Fase 11: Migración a S3 y Postgres: Reescribir block_model_store.py para que en vez de guardar en tu disco duro, guarde en buckets en la nube.

Fase 12: Workers Asíncronos (Celery): Separar FastAPI de la matemática pesada para que la app nunca se congele.

Fase 13: Ciberseguridad (Aislamiento y Autenticación): Poner Auth0 o Cognito para el login. Asegurar que las rutas de la API exijan tokens JWT validos y que cada minera viva en su propio silo de datos.

Fase 14: Integración Gemini: Construir el módulo de autogeneración de reportes leyendo los resultados desde la base de datos.

Fase 15: Polish de UI y Despliegue a Producción: Dejar el InstancedMesh perfecto, subir a Vercel/AWS y dejar el dominio terraquantum.io corriendo en vivo.


1. Gemini como "Agente Geofísico" (RAG + Tool Calling)Si le preguntas a Gemini directo en la web "calcula la gravedad de este prisma", se va a equivocar, porque los LLMs son motores de lenguaje, no calculadoras. Para que Gemini funcione con nuestra matemática y nuestra base de datos, usamos una arquitectura que es el estándar de oro actual: Tool Calling (Llamada a Herramientas) y RAG (Retrieval-Augmented Generation).¿Cómo funciona en la práctica?El Cerebro (Gemini): Usamos la API de Gemini, pero le inyectamos un System Prompt brutal: "Eres el Geofísico Principal de TerraQuantum. Tu trabajo es interpretar resultados. NUNCA calcules matemáticas por tu cuenta, usa siempre las herramientas que te proveo".Las Manos (Tools): A la API de Gemini le pasamos "herramientas" (funciones de Python que tú y yo escribimos). Por ejemplo: obtener_metricas_inversion(run_id), consultar_sondajes_db(project_id), leer_documentacion_JORC().El Flujo:El usuario de GEODATO escribe en el chat: "Gemini, resúmeme por qué este modelo es confiable".Gemini "piensa" y dice: "Para responder esto, necesito ejecutar obtener_metricas_inversion".Tu backend de FastAPI ejecuta la función, lee el report.json (con el Pearson r, el $\chi^2$, etc.) y se lo devuelve a Gemini.Gemini lee tus datos duros, razona sobre ellos basándose en la física real, y le responde al usuario con un texto perfecto y 100% fundamentado en tu matemática. Cero alucinaciones.Y sobre Google Cloud Platform (GCP) y el XPRIZE: Tienes toda la razón. Si queremos ir al XPRIZE y demostrar que tenemos "lo mejor de lo mejor", la jugada maestra es usar Vertex AI (la plataforma empresarial de Google Cloud). Ahí es donde vive la API de Gemini Pro, conectada directamente por redes internas ultra-rápidas a tu base de datos en Cloud SQL (Postgres). Es la arquitectura más robusta y premiada del mercado para IA aplicada a ciencias.2. El mito del "Programa instalado" y la Magia del SaaSAquí hay un cambio de chip importante: En el modelo SaaS (Software as a Service), las empresas no se descargan ni instalan tu programa. GEODATO no va a tener un .exe en sus computadores. Ellos van a entrar a app.terraquantum.io desde Google Chrome. Todo el código, la base de datos y la matemática viven en tus servidores en la nube.Esto es una ventaja brutal, porque significa que si tú haces una actualización, todos tus clientes reciben la versión nueva al instante la próxima vez que recarguen la página. No tienes que rogarles que instalen parches.Pero claro, ¿cómo actualizas el código sin que se caiga el sistema mientras hay geólogos trabajando? Así lo hacemos los profesionales:A. Los Tres Entornos (Dev, Staging, Prod)Nunca escribes código directo en el servidor de los clientes. Tienes tres mundos separados:Development (Tu PC): Donde programas, rompes cosas y pruebas.Staging (El clon en la nube): Es un servidor privado e idéntico al de los clientes, pero oculto. Aquí subes tu actualización primero. Haces pruebas de estrés, ves que la UI no se rompa y que el solver converja bien.Production (El servidor real): El que usan las mineras.B. Despliegues Zero-Downtime (Blue/Green Deployment)Cuando ya probaste tu actualización en Staging y quieres pasarla a Production, no apagas el servidor viejo. Usas una técnica llamada Blue/Green Deployment.Tienes tu código actual corriendo (Servidor Azul). Los clientes están usándolo.Enciendes un servidor nuevo al lado con tu actualización (Servidor Verde).Le haces pruebas automáticas al Verde para confirmar que encendió bien.Le dices al "Enrutador" (Load Balancer) de Google Cloud: "A partir de este segundo, manda a todos los usuarios nuevos al Servidor Verde".Los usuarios ni se enteran del cambio. Una vez que el Servidor Azul se queda sin usuarios activos, lo apagas y lo destruyes. Cero segundos de caída del sistema.C. Versionado de APIs (Para no romper proyectos viejos)¿Qué pasa si cambiaste cómo se calcula la matemática, pero GEODATO quiere volver a abrir un proyecto de hace 6 meses que usaba la matemática vieja para una auditoría?Para eso versionamos la API.Tu código viejo vivirá en la URL api.terraquantum.io/v1/inversion.Tu actualización nueva vivirá en api.terraquantum.io/v2/inversion.El frontend nuevo usará la v2, pero si un cliente abre un proyecto congelado (legacy), el sistema seguirá apuntando a la v1 para mantener la consistencia JORC de ese trabajo antiguo. Con el tiempo, les mandas un correo formal: "Estimados, la versión v1 quedará obsoleta en 6 meses, les recomendamos migrar sus proyectos".