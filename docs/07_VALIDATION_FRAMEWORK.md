# TerraQuantum — VALIDATION FRAMEWORK (diseño)

| Campo | Valor |
|---|---|
| Fecha | 2026-08-05 |
| Estado | **PROPUESTA DE DISEÑO** — documento de ingeniería, sin código. No se ha modificado nada del repositorio. |
| Decisiones | Las 4 preguntas abiertas se **resolvieron por investigación** (§8), no por criterio. Dos de mis propuestas iniciales resultaron mal planteadas y están corregidas ahí. |
| Depende de | `docs/06_AUDITORIA_TECNICA_INTEGRAL.md` (hallazgos H-1, H-27, H-28, H-33, H-36, H-37, H-38) · `docs/05_RIGOR_FISICO_Y_RED_TEAM.md` (Parte A: presupuesto de error) |
| Pregunta única | *"¿TerraQuantum está recuperando correctamente la realidad que yo conozco — y lo dice cuando no?"* |

---

# 0. QUÉ ES Y QUÉ NO ES

## 0.1 La misión, en una frase

**No es un generador de datos sintéticos. Es un sistema que produce evidencia cuantitativa, reproducible y comparable entre versiones sobre cuándo TerraQuantum acierta y cuándo se equivoca.**

La diferencia no es retórica. Un generador de datos se mide por cuántos escenarios produce. Este sistema se mide por **cuántas afirmaciones sobre el motor puede sostener con un número**.

## 0.2 Lo que NO debe llegar a ser (anti-scope del framework)

Escrito ahora, porque este proyecto tiene una atracción gravitatoria natural hacia convertirse en otra cosa:

| No es | Por qué |
|---|---|
| Un simulador geológico tipo Leapfrog | Consumiría años y compite con el anti-scope declarado del producto (`docs/02` §6) |
| Un generador de "minas realistas" | El realismo **resta** capacidad de atribución: si el modelo falla en un mundo con fallas, alteración y anisotropía, no sabes cuál causó el fallo |
| Una segunda implementación de la física | Toda física nueva aquí es física sin validar. El framework **mide**, no calcula |
| Un reemplazo de los benchmarks externos | DO-27, Raglan, San Nicolás y LdM siguen siendo la prueba con dato real. El sintético complementa, no sustituye |

## 0.3 Lo que ya existe (punto de partida real)

**[MEDIDO en la auditoría]** Esto no es un proyecto nuevo: es la consolidación de ~2.400 líneas ya escritas y dispersas en ocho archivos.

| Archivo | LOC | Qué aporta hoy |
|---|---:|---|
| `tests/synthetic_recovery_benchmark.py` | 1.020 | El banco más completo; selección de λ, métricas de recuperación |
| `scripts/validation/synthetic_cases.py` | 379 | `CASES[]` (1 cuerpo / profundo / 2 cuerpos), `build_contrast_for_bodies`, ruido determinista, `center_of_mass`, `compute_pearson`, `compute_top_overlap` |
| `scripts/validation/f9_regression_lib.py` | 306 | Regresión congelada de los 4 datasets reales con tolerancias justificadas |
| `scripts/validation/error_budget.py` | 219 | Barrido de 15 regímenes sobre 5 ejes, verdad analítica (esfera), reporte HTML |
| `tests/f8_storm_lib.py` | — | Surveys sintéticos con verdad sobre 5 ejes; invariante "modelo válido o error catalogado" |
| `test_analytic_sphere_validation.py`, `test_sphere_forward.py` | — | Esfera de forma cerrada |
| `test_prism_recovery_benchmark.py` | — | Prisma contra Plouff (1976) |
| `test_benchmark_two_body.py`, `test_benchmark_dipping_dike.py`, `test_benchmark_checkerboard.py` | — | Escenarios ya escritos |
| `services/field_validation_service.py` | 434 | `estimate_location_error` y utilidades de comparación (prod=0: **ya es un servicio de validación**) |

**El trabajo es de consolidación y contrato, no de invención.** Lo genuinamente nuevo es: el objeto de mundo como artefacto de primera clase, la matriz de honestidad, la persistencia por versión, y las métricas volumétricas (IoU 3D, recall/precision de cuerpos).

---

# 1. PRINCIPIOS DE DISEÑO

Cada uno viene de un hallazgo medido, no de una preferencia estética.

### P1 — La verdad es una sola cosa
La geometría y las propiedades físicas **son** la verdad. Nunca se almacena un `ground_truth` derivado junto al mundo que lo genera: los productos derivados (centroide, volumen, máscara del cuerpo) se **calculan** desde el mundo, con una función pura y versionada. Dos representaciones del mismo hecho divergen; el día que lo hagan, el framework mentiría con autoridad de oráculo.

### P2 — El mundo no sabe cómo lo van a medir
El subsuelo existe igual lo midas con 64 estaciones o con 900. Survey, ruido y semilla pertenecen a la **campaña**, no al mundo. Esta separación es la que convierte *"el mismo cuerpo medido de cinco maneras"* en un experimento de primera clase — y es exactamente el eje de cobertura que `docs/05` ya midió (26 / 88 / 149 m).

> **[MEDIDO] Hoy esto está mezclado:** `error_budget.Case` contiene `depth_m`, `radius_m`, `delta_rho` (mundo) junto a `span_m`, `n_side`, `noise_mgal`, `seed` (campaña) en un único dataclass.

### P3 — Umbrales justificados, nunca valores esperados
Prohibido `expected_centroid = (100, 200, 300)`. Si el fixture declara el resultado, el test valida que TQ hace lo que hizo la última vez, no que acierta. Cada umbral lleva **la medición que lo justifica**, como ya se hace en el mejor sitio del repo:

```python
"san_nicolas_misfit_max_pct": 3.0,  # ajuste excelente; medido 1.51% (stride 4) → margen ~2x
```

> **[MEDIDO] Hoy esto está a medias:** los umbrales de `synthetic_cases.CASES` (`pass_center: 30.0`, `pass_corr: 0.35`, `pass_overlap: 0.30`) **no llevan justificación**. No se sabe si salieron de una medición o de ajustarlos hasta que pasaran.

### P4 — Anti-inverse-crime declarado por máquina, no por disciplina
El dato nunca se genera con el operador que usa la inversión. Pero además: **cada conjunto de observaciones declara cómo se generó**, en un campo legible por máquina, para que el framework pueda excluir o marcar automáticamente un resultado contaminado. La regla existente (`docs/05` A2) depende hoy de que quien escribe el test se acuerde.

### P5 — Se entra por la puerta del usuario
El framework invoca el flujo de producción (paquete → `run_geophysics_inversion` con configuración real), **no** la API interna del solver.

> **Justificación medida:** H-37. El modo `amplitude` está declarado en el esquema, ofrecido en la UI y con su solver implementado y testeado — y **ninguna rama lo despacha**. Un framework que llamara a `solve_amplitude_inversion_lsqr` directamente lo habría dado por bueno para siempre. Lo mismo con H-27 (topografía plana silenciosa) y H-38 (padding incondicional que anula `depth_beta`).

### P6 — Procedencia completa o el resultado no cuenta
Semilla, versión del generador, hash del mundo, versión de TQ, configuración efectiva. Sin esto, "reproducible" es una aspiración.
*(Es el mismo patrón que H-36 señaló ausente en el motor: dato derivado sin procedencia ni validez. Que reaparezca aquí confirma que es un principio, no una anécdota.)*

### P7 — Varianza antes que variedad
Cinco semillas sobre veinte escenarios valen más que una semilla sobre cien.

> **Justificación medida:** en `docs/05` §A′, el operating-point a 300 m dio **288 ± 550 m**. La varianza *era* el hallazgo — con una sola semilla se habría reportado un número tranquilizador y falso.

### P8 — La honestidad es una métrica, no un comentario
Se mide con el mismo rigor que el error de targeting. Ver §4.2.

---

# 2. EL CONTRATO

Cuatro entidades. Cada una responde una pregunta distinta: **qué hay** · **cómo lo medí** · **qué acepto como bueno** · **qué obtuve**.

```
World  ──1:N──▶  Campaign  ──1:1──▶  Observations
  │                  │                    │
  │                  │                    ▼
  └──────────▶  Acceptance          TerraQuantum (flujo de producción)
                     │                    │
                     └────────┬───────────┘
                              ▼
                           Result  ──▶  History (por versión de TQ)
```

## 2.1 `World` — la verdad

```python
@dataclass(frozen=True)
class World:
    """La realidad del subsuelo. Inmutable. No sabe que existe un survey."""
    schema_version: str              # "world/1" — versión del CONTRATO
    id: str                          # "w_two_bodies_shallow"
    instance_version: int            # versión de ESTE mundo; sube si cambia su contenido

    geometry: Geometry               # topografía + cuerpos + (futuro) fallas
    properties: Properties           # densidad y susceptibilidad por dominio
    metadata: WorldMetadata          # nombre, régimen, ejes que ejercita, notas
    provenance: Provenance           # semilla, versión del generador, hash del contenido

    # NO existe un campo `ground_truth` (P1): los derivados se calculan.
    # NO existen `survey`, `noise` ni `expected_outputs` (P2, P3).
```

```python
@dataclass(frozen=True)
class Geometry:
    bounds_m: tuple                          # (x0,y0,z0,x1,y1,z1); y positivo hacia abajo
    topography: Topography                   # "flat" | malla DEM | función analítica
    bodies: tuple[Body, ...]                 # cada uno con forma paramétrica

@dataclass(frozen=True)
class Body:
    id: str
    shape: Shape                             # Sphere | Prism | DippingDike | Ellipsoid
    domain: str                              # clave hacia Properties
    # La forma es PARAMÉTRICA, no una máscara de vóxeles: permite calcular la verdad
    # a cualquier resolución y evita atar el mundo a una malla concreta.

@dataclass(frozen=True)
class Properties:
    background: DomainProps                  # densidad y susceptibilidad de la roca caja
    domains: dict[str, DomainProps]          # por dominio geológico
```

**Derivados calculados (no almacenados), función pura y versionada:**

```python
def truth_products(world: World, mesh: Mesh) -> TruthProducts:
    """Rasteriza la verdad a UNA malla concreta y calcula los derivados.
    La malla es un ARGUMENTO: el mismo mundo se evalúa a distintas resoluciones."""
    # -> contrast_field, body_mask, centroid_per_body, volume_per_body, top_depth_per_body
```

## 2.2 `Campaign` — cómo se midió

```python
@dataclass(frozen=True)
class Campaign:
    schema_version: str              # "campaign/1"
    id: str                          # "c_dense_lownoise"
    world_id: str                    # a qué mundo se aplica
    world_instance_version: int      # contra qué versión del mundo (detecta desfase)

    survey: SurveyDesign             # extensión, nº de estaciones, altura, geometría
    noise: NoiseModel                # instrumental (mGal/nT), posicionamiento (m), deriva
    boreholes: BoreholeCampaign|None # sondajes sintéticos: trazas, tramos, qué se mide
    provenance: Provenance           # semilla PROPIA (independiente de la del mundo)

    generation_method: GenerationMethod   # ← P4, el campo más importante del contrato
```

```python
class GenerationMethod(str, Enum):
    THIRD_PARTY       = "third_party_forward" # ← PREFERENTE (D5): Harmonica u otra
                                              #   implementación externa e independiente
    ANALYTIC          = "analytic"            # forma cerrada (esfera, prisma, dipolo)
    FORWARD_ALT_MESH  = "forward_alt_mesh"    # motor propio, malla DISTINTA a la de inversión
    FORWARD_SAME_MESH = "INVERSE_CRIME"       # PROHIBIDO en gates; solo diagnóstico
```

**Regla dura del framework:** un `Result` cuya campaña use `INVERSE_CRIME` **no puede contribuir a ningún gate** y se marca en rojo en todo reporte. La disciplina pasa a ser un invariante (P4).

Para `FORWARD_ALT_MESH`, `provenance` registra la malla de generación — hoy la práctica es forward 5 m / inversión 15 m, y esa relación debe quedar **explícita y auditable**, no en un comentario.

## 2.3 `Acceptance` — qué se considera bueno

```python
@dataclass(frozen=True)
class Acceptance:
    schema_version: str
    applies_to: Selector             # por régimen, por eje, o por (world_id, campaign_id)
    thresholds: tuple[Threshold, ...]

@dataclass(frozen=True)
class Threshold:
    metric: str                      # "horizontal_error_m"
    op: str                          # "<=" | ">=" | "within"
    value: float
    justification: str               # OBLIGATORIO (P3)
    measured_on: str                 # qué corrida produjo la justificación
    measured_value: float            # el número medido que sustenta el umbral
```

**El campo `justification` es obligatorio a nivel de esquema.** Un umbral sin la medición que lo respalda no se puede construir. Esto convierte P3 en algo que el tipo impone, no la revisión humana.

Los umbrales se declaran **por régimen**, no por escenario: *"targeting horizontal ≤ 60 m en régimen somero con cobertura densa"*, con la medición que lo sustenta. Así, añadir un escenario nuevo dentro de un régimen conocido no exige inventar umbrales.

## 2.4 `Result` — qué se obtuvo

```python
@dataclass(frozen=True)
class Result:
    schema_version: str
    run_id: str
    campaign_id: str; world_id: str; world_instance_version: int

    tq_version: str                  # commit SHA + tag
    tq_config: dict                  # configuración EFECTIVA (no la pedida)
    entry_point: str                 # "package_flow" | "direct_solver"  ← P5

    metrics: Metrics                 # §4.1
    honesty: HonestyRecord           # §4.2
    verdict: str                     # PASS | FAIL | EXCLUDED(inverse_crime) | ERROR
    failed_thresholds: tuple[str, ...]

    provenance: Provenance
    runtime_s: float
    artifacts: dict                  # rutas a parquet/JSON del modelo recuperado
```

**`tq_config` guarda la configuración *efectiva*, no la solicitada.** Es la lección directa de H-38: el padding se activa incondicionalmente aunque nadie lo pida, y eso cambia el funcional de regularización. Un `Result` que no registre lo que *realmente* corrió no permite comparar dos versiones.

## 2.5 Por qué cuatro entidades y no el árbol de ocho ramas

| Nodo propuesto originalmente | Destino | Motivo |
|---|---|---|
| `Geometry`, `PhysicalProperties` | `World.geometry`, `World.properties` | ✅ correctos |
| `GroundTruth` | **eliminado** | Error de categoría: geometría + propiedades **son** la verdad (P1) |
| `SurveyDesign`, `NoiseModel` | `Campaign` | No son propiedades del mundo (P2) |
| `ExpectedOutputs` | **eliminado** → `Acceptance` | Valores esperados = tautología (P3) |
| `Metadata` | `World.metadata` | ✅ |
| `Version` | **tres campos distintos** | `schema_version` · `instance_version` · `tq_version`. Con uno solo, no se puede distinguir "TQ mejoró" de "toqué el fixture" |
| — | `Provenance` (nuevo) | P6 |
| — | `generation_method` (nuevo) | P4 — el campo de mayor valor del contrato |

---

# 3. MAPA DE MIGRACIÓN

Nada se reescribe desde cero. Cada pieza existente encuentra su lugar.

| Archivo actual | Qué se extrae | Destino |
|---|---|---|
| `synthetic_cases.py` → `CASES[].bodies` | Geometría de 1 cuerpo / profundo / 2 cuerpos | **`World`** × 3 (los primeros del catálogo) |
| `synthetic_cases.py` → `pass_center/corr/overlap` | Umbrales | **`Acceptance`** — ⚠️ **requieren justificación retroactiva**: hoy no la tienen |
| `synthetic_cases.py` → `build_voxel_grid`, `build_contrast_for_bodies` | Rasterización de la verdad | **`truth_products()`** |
| `synthetic_cases.py` → `build_sensor_array`, `add_deterministic_noise` | Survey y ruido | **`Campaign`** |
| `synthetic_cases.py` → `center_of_mass`, `compute_pearson`, `compute_top_overlap` | Métricas | **`Metrics`** (§4.1) |
| `error_budget.py` → `Case.depth_m/radius_m/delta_rho` | Mundo | **`World`** (barrido de profundidad y contraste) |
| `error_budget.py` → `Case.span_m/n_side/noise_mgal/seed` | Campaña | **`Campaign`** (barrido de cobertura y SNR) |
| `error_budget.py` → `Case.axis`, `notes` | Qué eje ejercita | **`World.metadata.axis`** |
| `error_budget.py` → esfera analítica | Generación | **`GenerationMethod.ANALYTIC`** |
| `error_budget.py` → `LAMBDA_GRAV=1e-3`, `COMPACT_IRLS=2` | Configuración | ⚠️ **NO migrar como está** — ver §3.1 |
| `error_budget_html.py` | Reporte | **`report/`** del framework |
| `f9_regression_lib.py` | 4 datasets reales + tolerancias justificadas | **`Acceptance`** de referencia — *el modelo a imitar* (sus umbrales sí llevan justificación) |
| `f8_storm_lib.py` | Ejes de suciedad, invariante "modelo válido o error catalogado" | **`Campaign`** (ruido/formato) + una métrica de robustez |
| `synthetic_recovery_benchmark.py` (1.020 LOC) | El banco más completo | Se **descompone** en World/Campaign/Acceptance; es la migración más laboriosa y la de mayor retorno |
| `field_validation_service.estimate_location_error` | Comparador | **`Metrics`** — ya existe y está probado |
| `honesty_test.py` | Semilla de la matriz de honestidad | **`HonestyRecord`** (§4.2) |
| `test_analytic_sphere_validation.py`, `test_prism_recovery_benchmark.py` | Oráculos analíticos | Se conservan **tal cual** como tests unitarios del forward; el framework los referencia, no los absorbe |

## 3.1 Advertencia crítica sobre la configuración de `error_budget.py`

`error_budget.py` fija `LAMBDA_GRAV = 1e-3` con el comentario *"config IDÉNTICA al harness DO-27 validado"*. Pero `docs/05` §A′ **ya endureció esa conclusión**: ese λ fijo **sobreajusta en profundo** y produjo el artefacto que hizo creer que la profundidad no se recuperaba nunca.

**Por tanto:** el framework corre con **configuración de producción** (Morozov cuando hay σ declarado; operating-point cuando no), no con λ fijo. Si se quiere el brazo de λ fijo, es **una campaña más**, declarada como tal — no el default.

Esto es P5 aplicado a la configuración: entrar por la puerta del usuario incluye **usar los parámetros que el usuario tendría**.

---

# 4. MÉTRICAS

## 4.1 Exactitud

| Métrica | Definición | Estado hoy |
|---|---|---|
| `horizontal_error_m` | Distancia horizontal centroide recuperado ↔ verdadero | ✅ existe (35 usos) |
| `depth_error_centroid_m` / `depth_error_top_m` | Error de profundidad de centroide y techo | ✅ existe (51 usos) |
| `pearson_r` | Correlación del campo de contraste | ✅ existe (121 usos) |
| `chi2_red` | Ajuste al nivel de ruido declarado | ✅ existe (200 usos) |
| **`pr_auc`** | **Primaria (D2)**: precisión-exhaustividad sobre el barrido de umbrales. **Independiente del umbral** | ❌ **nuevo** |
| **`iou_auc`** | **Primaria (D2)**: área bajo la curva IoU(τ) | ❌ **nuevo** |
| `iou_3d @ τ` | **Secundaria (D2)**: solo para comunicar a un humano. **Nunca compara versiones** | ⚠️ marginal (7 usos) |
| **`volume_error_pct`** | Error volumétrico relativo | ❌ **nuevo** |
| **`body_recall` / `body_precision`** | Cuerpos detectados / falsos positivos, con criterio de emparejamiento explícito | ❌ **nuevo** |
| `density_recovery_pct` | Fracción del contraste recuperada | ✅ existe |

> **⚠️ CORREGIDO POR LA INVESTIGACIÓN (D2).** La primera versión de esta sección proponía fijar un umbral de segmentación y justificarlo. **Estaba mal planteado.** La literatura documenta que *el ranking de modelos cambia con el umbral de binarización* — y como el propósito de este framework es decir si 0.8 es mejor que 0.7, una métrica dependiente del umbral permite invertir la respuesta eligiendo otro. **Las métricas de comparación entre versiones son independientes del umbral**; las de umbral fijo se reportan siempre con su τ y solo para comunicar. Ver §8 D2.

## 4.2 Honestidad — la métrica que nadie más tiene

Las métricas de §4.1 responden *"¿acertó?"*. Ésta responde ***"cuando se equivocó, ¿lo dijo?"*** — y es el diferenciador comercial declarado del producto.

```python
@dataclass(frozen=True)
class HonestyRecord:
    declared_confidence: str         # HIGH | MEDIUM | LOW (de B1/B3)
    declared_depth_confidence: str   # desacoplada (fix C2′ ya implementado)
    is_null_space_artifact: bool
    observable_depth_max_m: float
    actual_horizontal_error_m: float
    actual_depth_error_m: float
    quadrant: str                    # ver matriz
```

**La matriz, con el cuadrante letal marcado:**

| | Error pequeño | Error grande |
|---|---|---|
| **Confianza HIGH** | ✅ `CALIBRADO` | 🔴 **`SOBRECONFIADO`** ← el único fallo inaceptable |
| **Confianza LOW** | 🟡 `CONSERVADOR` | ✅ `CALIBRADO` |

**Métrica agregada del framework:** `overconfidence_rate` = fracción de escenarios en el cuadrante rojo.

**Criterio de aceptación propuesto: `overconfidence_rate == 0`.** No un umbral bajo: **cero**. Un solo caso de "HIGH donde el error es grande" es un bug de honestidad, y `docs/05` §C2′ ya estableció ese precedente al demostrar y tapar uno.

**[OPINIÓN]** Si dentro de dos años alguien pregunta por qué confiar en TerraQuantum, la respuesta fuerte no es *"mi IoU es 0,91"* — es ***"en 300 escenarios nunca dije HIGH donde me equivoqué"***. Eso es defendible ante una Persona Calificada que firma, y ningún competidor puede copiarlo sin rehacer su producto.

## 4.3 Robustez (heredada de F8)

`crash_rate` (debe ser 0), `catalogued_error_rate` (todo fallo con error en español), `silent_corruption_count` (**debe ser 0**: modelo con veredicto bueno y error grande sin aviso).

---

# 5. EJECUCIÓN: NIVELES Y PRESUPUESTO

Una inversión son minutos. 100 escenarios × 5 semillas son horas: eso no corre en cada commit.

| Nivel | Alcance | Presupuesto | Cuándo | Gate |
|---|---|---|---|---|
| **smoke** | 5 mundos × 1 campaña × 1 semilla | < 5 min | cada PR | bloquea el merge |
| **standard** | 20 mundos × 2 campañas × 3 semillas | < 45 min | nocturno | avisa; bloquea `main` |
| **full** | catálogo completo × 5 semillas | horas | semanal / pre-release | informe de release |

Cada nivel produce el **mismo esquema** de `Result`, para que las series temporales sean comparables. **Y ninguno declara cobertura que no tenga:** si el nivel recorta escenarios, el reporte lo dice explícitamente (la auditoría encontró que el silencio sobre lo truncado se lee como cobertura completa).

> **Conexión con la auditoría (H-4, H-22):** hoy la regresión física **no corre en CI** y el 66% de los scripts de validación no tienen criterio automático de aprobado. El framework no sirve de nada si repite ese patrón: **el nivel `smoke` en CI es requisito de la Fase 1**, no un extra.

---

# 6. SPRINTS

Regla: **cada sprint produce un resultado científicamente verificable**. Si no se puede enunciar como un número contra una verdad, no es un sprint.

## Sprint 0 — Investigación acotada · 2–3 días

**No** 1–2 semanas desde cero: ya implementas buena parte del estado del arte, y el corpus de informes tiene calidad desigual (el 06 llegó truncado, las conclusiones del 04 son ilegibles).

Preguntas nombradas, y solo éstas:
1. Métricas de recuperación 3D en la literatura de inversión de campos potenciales: ¿cómo se define IoU/recall cuando el modelo recuperado es difuso y no binario?
2. ¿Cómo reportan los papers la **calibración de incertidumbre** (no solo el error)?
3. Bibliotecas de escenarios existentes (SimPEG, Fatiando, GeoSci) — ¿qué se puede citar o reutilizar como oráculo sin añadir dependencia de producción?
4. Convenciones de nomenclatura de escenarios sintéticos, para que los nombres sean legibles por un revisor externo.

**Entregable:** 2 páginas con decisiones tomadas, no un informe.

## Sprint 1 — El contrato y una vuelta completa · S · ✅ **EJECUTADO 2026-08-05**

> **Resultado medido.** Código en `validation/` (10 módulos). Una vuelta completa del
> circuito, con configuración de producción:
>
> | | |
> |---|---|
> | oráculo choclo vs fórmula cerrada | **4,1e-16** (precisión de máquina) |
> | λ elegido | **0,31623** por `morozov_chi2_discrepancy` |
> | error horizontal | **2,3 m** |
> | error de profundidad | 33,2 m |
> | PR-AUC / IoU-AUC (primarias) | **0,9612** / 0,5248 |
> | χ² / misfit | 1,78 / 9,69 % |
> | honestidad | MEDIUM + profundidad LOW → **CALIBRADO** |
> | veredicto | **PASS** · reproducible: dos corridas, métricas idénticas |
>
> **Validación cruzada:** los 2,3 m coinciden con los 2 m que `error_budget.py` midió
> para el régimen somero-denso-limpio — dos harnesses independientes, con generadores
> distintos, dando el mismo número.
>
> **Los 8 invariantes se verifican en segundos** (`test_determinism.py`), incluidos
> los dos que el tipo impone: un `Threshold` sin justificación no se construye, y
> `INVERSE_CRIME` queda fuera del gate por contrato.
>
> **Desviaciones honestas del plan:**
> - **Presupuesto excedido:** el smoke tarda ~6 min, no <5. Una inversión con Morozov
>   son 6 solves. Recomendación revisada: `test_determinism` en cada PR (segundos),
>   `run_smoke` nocturno. Poner 6 min en cada PR es la vía rápida a que se desactive.
> - **`choclo` en vez de `harmonica`**: 3 paquetes en lugar de 9, y es exactamente el
>   alcance necesario (kernels de forward). Harmonica añade procesamiento que este
>   framework no usa.
> - Umbrales anclados a benchmarks externos, no a este framework — declarado en cada
>   `justification`; el Sprint 2 los re-ancla.
> - `depth_error_top_m` y `pearson_r` quedan en `NaN` explícito, nunca en 0.

### Plan original del sprint

**Objetivo:** una sola vuelta del circuito entero, con el escenario más simple que ya funciona.

Trabajo: definir las cuatro entidades; migrar `synthetic_cases.CASES[0]` (cuerpo único) a `World` + `Campaign` + `Acceptance`; runner que entre **por el flujo de paquete** (P5); comparador con las métricas que ya existen; persistir `Result`.

**Criterio verificable:** *la esfera se recupera con error horizontal ≤ el umbral justificado, el `Result` queda persistido con procedencia completa, y **la corrida es byte-reproducible con la misma semilla**.*

**Además (no negociable):** el nivel `smoke` corre en CI desde este sprint.

## Sprint 2 — Régimen y varianza · M · ✅ **CERRADO 2026-08-06**

**Barrido definitivo: 150 corridas** (15 regímenes × 5 semillas × **2 brazos declarados de
`density_min`**), 149,5 min, 0 errores, versión de TQ `adba2b8+dirty`.
Reporte completo: `validation/RESULTS_2026-08-06_barrido_dos_brazos.md`.
Umbrales derivados: `validation/acceptance_measured.py` (**generado**, no escrito a mano).

| Lo que quedó medido | |
|---|---|
| Brazo ganador | `s_strict_L2` **en los 15 regímenes**. El permisivo hunde la masa al fondo siempre — en esta malla |
| Alcance de esa afirmación | **una sola malla** (125 m). La resolución queda como eje no medido |
| Regímenes que recuperan de verdad | **7 de 15** (PR-AUC mediano ≥ 0,30). Los otros 8: umbral de regresión, cero pretensión de calidad |
| Frontera de profundidad | **acantilado entre 400 y 600 m** (PR-AUC 0,86 → 0,10) — reproduce `docs/05` con otro harness y otro generador |
| Forma de la distribución | **bimodal**, no ancha: en `baseline` 3 semillas dan PR-AUC 1,000 y 2 se desploman |
| Independencia de las semillas | **menor de la que aparenta**: la semilla 3003 es la peor en 6 de 6 regímenes examinados |
| Confianza declarada por TQ | **nunca `HIGH`** en 150 corridas (103 MEDIUM, 47 LOW) |

**Tres resultados que valen más que la tabla:**

1. **Predicción propia refutada.** Antes de correr escribí que esperaba un empate por
   régimen. La medición dijo que no, en las 15 celdas. Queda registrado porque un
   framework cuyo autor sólo publica lo que acertó no sirve para nada.
2. **En 4 de 15 regímenes el error de centroide habría elegido el brazo equivocado**
   (mejor horizontal, PR-AUC 10× peor). Es la justificación empírica de D2 — y la
   validación previa del proyecto usaba centroide como métrica principal.
3. **El "0 sobreconfiados" es casi vacío.** No se puede ser sobreconfiado sin declarar
   confianza alta, y TQ nunca la declara. La señal separa en promedio (PR-AUC medio 0,51
   en `MEDIUM` contra 0,07 en `LOW`) pero es inútil caso a caso: un `MEDIUM` va de 0,003
   a 1,000. **Consecuencia de producto:** hoy el sistema no sabe decir *"esta corrida sí
   es fiable"*; sólo *"regular"* o *"mala"*.

**Brecha con `error_budget.py` — resuelta, y no como esperaba.** La mediana del baseline es
**18,2 m** frente a los 14 m del harness antiguo. Los 208 m que había reportado eran una
media arrastrada por dos semillas caídas. No había sesgo de la ruta de producción: había una
distribución bimodal descrita con la estadística equivocada. H-38 no queda refutado, pero
deja de ser necesario para explicar los números. Lo que sigue abierto —y es mejor pregunta—
es **por qué se desploman esas dos semillas**.

**Limitación que hereda el Sprint 3:** `Acceptance` se evalúa por corrida, así que el umbral
debe dar cabida a la peor semilla; con distribución bimodal eso lo deja flojo (`baseline`
≤ 360 m cuando la mediana es 18 m). Hace falta **aceptación de nivel agregado** sobre la
mediana de N semillas. Las medianas ya se publican en `acceptance_measured.MEDIANS`.

---

### Historia: el primer barrido fue RETIRADO

> **El primer barrido corrió (15 regímenes × 5 semillas, 75 inversiones, 127 min) y sus
> números NO eran utilizables.** Se retiraron por decisión propia. El sprint **cumplió
> su función**: el framework detectó un defecto en sí mismo antes de que ningún
> número saliera del laboratorio.
>
> ### Qué mostró el barrido
> El centroide recuperado caía a ~1.650 m —el fondo del dominio— **sea cual fuera la
> profundidad verdadera** (250/400/600/900 m). El "error de profundidad" que la tabla
> reportaba no medía el régimen: medía la distancia de la verdad al suelo.
>
> ### El control que lo retiró
> `control_lambda.py` — mismo mundo, misma campaña, cambiando **solo λ**. Con λ=1e-3,
> la configuración con la que el harness antiguo reporta 14 m, mi framework seguía
> dando 289 m y el mismo hundimiento. **La causa no era la configuración de λ.**
>
> ### La atribución
> `control_matrix.py` aisló dos divergencias estructurales, **ambas elecciones
> arbitrarias mías**, ni de producción ni del harness antiguo:
>
> | config | horizontal | centroide y | PR-AUC |
> |---|---:|---:|---:|
> | L2 + contraste negativo | 100,3 m | **1.653 m** | 0,038 |
> | L2 + solo positivo | 208,0 m | **655 m** | **0,704** |
> | compact + contraste negativo | 45,8 m | **1.662 m** | 0,065 |
> | compact + solo positivo | 243,1 m | **661 m** | **0,634** |
>
> **La causa es `density_min`.** Permitir contraste negativo (`base − 0.5`) dejaba al
> solver construir un dipolo —positivo somero, negativo profundo— que ajusta el dato
> y hunde la masa.
>
> ### ⚠️ Y una corrección de esa corrección
> Al re-verificar el Sprint 1 con el default cambiado, **el efecto se invierte**:
>
> | w001 (malla 50 m, esfera somera 300 m) | contraste negativo | solo positivo |
> |---|---:|---:|
> | horizontal | **2,3 m** | 9,8 m |
> | PR-AUC | **0,961** | 0,479 |
> | χ² | 1,78 | 0,494 (sobreajusta) |
> | λ de Morozov | 0,316 | **0,024** |
>
> En malla fina y somera, permitir contraste negativo es **mejor**; en malla gruesa
> es catastrófico. Y el parámetro **cambia el λ que Morozov elige en un orden de
> magnitud**, de modo que no es una restricción aislada: reconfigura la selección de
> regularización.
>
> **Conclusión corregida:** `density_min` no era un defecto que arreglar sino **una
> variable experimental que yo estaba fijando en silencio**. Ambos valores que usé
> son elecciones mías, no de producción.
>
> **Cambio de diseño que esto impone (Sprint 3):** los parámetros del solver que
> cambian materialmente el resultado no pueden ser defaults del runner. Necesitan una
> entidad declarada —**`SolverConfig`**— al mismo nivel que `World` y `Campaign`, con
> procedencia registrada. Es P3/P6 aplicado a la configuración: **lo que cambia el
> resultado se declara, no se asume.** Hasta entonces, ningún número del framework es
> comparable con otro que no declare `density_min` y `regularization_norm`.
>
> ### La lección, que vale más que el bug
> En las configuraciones patológicas el error **horizontal era MEJOR** (46–100 m) que
> en las sanas (208–243 m), porque el cuerpo hundido queda centrado bajo el survey.
> **La métrica de centroide premiaba la patología.** Lo que la delató fue el PR-AUC
> (0,04 frente a 0,70).
>
> Esto valida en la práctica la decisión **D2**: las métricas de campo independientes
> del umbral no son un refinamiento estadístico — son lo que impide que una métrica de
> localización esconda un modelo roto. La corrección que la investigación introdujo en
> el diseño se pagó sola en el primer barrido.
>
> ### Residual honesto, no resuelto
> Corregido el default, el baseline da ~208 m frente a los **14 m** de
> `error_budget.py`. La diferencia restante: aquel llama a `solve_inversion_lsqr`
> **directamente**, mientras el framework entra por producción, que **añade padding
> incondicionalmente** (H-38) y aplica post-proceso. **Hipótesis nombrada, no
> verificada.** Hasta medirla, ni 208 ni 14 deben citarse como "el error del motor".
>
> ### Cambio de proceso que este sprint impone al diseño
> **Todo barrido nuevo requiere un experimento de control que reproduzca un resultado
> conocido antes de que sus números cuenten.** Sin él, un harness produce tablas con
> apariencia de rigor —media ± σ sobre 5 semillas— que son artefactos de sus propios
> parámetros. Se añade como requisito a §7 (Riesgos del propio framework).

### Plan original del sprint

Migrar los 15 regímenes de `error_budget.py` separando mundo de campaña (§3). Ejecutar con **5 semillas** (P7). Publicar la tabla `error × régimen` con **media ± σ**, no solo la media.

**Criterio verificable:** *se reproduce la tabla de `docs/05` Parte A —ahora con configuración de producción en vez de λ=1e-3— y se documenta explícitamente en qué celdas el número cambia respecto al harness antiguo y por qué.*

**[INFERENCIA] Es plausible que varias celdas cambien**, porque `docs/05` §A′ ya midió que Morozov rescata el régimen moderado que el λ fijo daba por perdido. Ése sería, por sí solo, un resultado que justifica el sprint.

## Sprint 3 — `SolverConfig` y la matriz de honestidad · M · 🔶 **PARCIAL**

> **`SolverConfig` ✅ HECHO (2026-08-06).** Es entidad de primera clase en
> `contract.py`, con `rationale` obligatorio —construir una configuración sin declarar
> por qué lanza excepción, igual que `Threshold.justification`— y cada `Result` lleva
> `solver_config_id`. Los dos brazos declarados viven en `solver_configs.py` y el
> barrido de 150 corridas los midió a ambos. **Ningún número del framework puede ya
> compararse con otro sin declarar bajo qué configuración se obtuvo.**
>
> **Matriz de honestidad: PENDIENTE**, y el Sprint 2 le dejó dos requisitos nuevos:
> 1. El criterio `overconfidence_rate == 0` **no basta**: se cumplió trivialmente en 150
>    corridas porque **TQ nunca declara confianza `HIGH`**. Hay que medir la
>    *informatividad* de la señal, no sólo su ausencia de mentira. Reliability diagram,
>    ECE y MCE — con el bin `HIGH` posiblemente vacío, que es en sí el hallazgo.
> 2. Añadir **aceptación de nivel agregado**: hoy `Acceptance` se evalúa por corrida y
>    debe tolerar la peor semilla, lo que con distribución bimodal deja los umbrales
>    flojos. Las medianas ya están publicadas en `acceptance_measured.MEDIANS`.

> **Ampliado tras el Sprint 2.** Antes de la matriz de honestidad hay que cerrar un
> agujero que el Sprint 2 destapó: **la configuración del solver se está eligiendo en
> silencio**. `density_min` y `regularization_norm` cambian el resultado de forma
> material —y hasta cambian el λ que Morozov selecciona— pero viven como defaults del
> runner.
>
> **Entregable previo:** una entidad `SolverConfig` al mismo nivel que `World` y
> `Campaign`, con `provenance`, referenciada por cada `Result`. Un resultado sin
> `SolverConfig` declarado no es comparable con ningún otro. Es la misma disciplina
> que `Threshold.justification` impone a los umbrales, aplicada a la configuración.

### La matriz de honestidad (plan original)

Instrumentar `HonestyRecord` en cada `Result`, clasificar por cuadrante, calcular `overconfidence_rate`.

**Criterio verificable:** *`overconfidence_rate == 0` sobre el catálogo, o la lista explícita de escenarios que caen en el cuadrante rojo — que pasan a ser bugs de honestidad con nombre propio.*

## Sprint 4 — Historial y comparación entre versiones · M

Persistencia indexada por `tq_version`; reporte de diferencias entre dos versiones; detección de las tres transiciones: **mejora**, **empeora** y **cambia de comportamiento sin cambiar el promedio** (la más sutil y la que atrapa regresiones silenciosas).

**Criterio verificable:** *se puede responder con un comando "¿qué cambió entre el commit A y el B?", y la respuesta distingue los tres casos.*

## Sprint 5 — Catálogo · L

Escenarios nuevos, **de a uno y con propósito declarado**. Cada mundo nuevo debe responder a la pregunta *"¿qué eje aísla este mundo que ningún otro aísla?"*. Si no hay respuesta, no entra.

## Sprint 6 — La pregunta abierta del motor · M

> **Nota de 2026-08-06: el framework ya se pagó, antes de llegar aquí.** El Sprint 2 produjo
> dos defectos que ninguna suite existente detectaba, ambos medidos y con la cadena de causa
> verificada en el código:
>
> 1. **El bound de densidad por defecto del camino de usuario cae del lado que hunde el modelo**
>    (`validation/HALLAZGO_2026-08-06_bound_por_defecto.md`). Contraste ≥ 0 → PR-AUC 1,000;
>    contraste ≥ −0,01 → 8/8 caídas con PR-AUC 0,035; el default deja pasar ≥ −2,6. La
>    justificación escrita de ese default se apoyaba en el **misfit**, que es exactamente la
>    métrica ciega al fallo — algo que sólo se ve midiendo ajuste y calidad a la vez.
> 2. **El veredicto tiene un techo estructural en `MEDIUM`**
>    (`validation/HALLAZGO_2026-08-06_techo_medium.md`).
>
> Los dos comparten forma: **una decisión razonable tomada con una métrica que no podía ver su
> propio precio.** Es la clase de fallo que ninguna cantidad de tests unitarios encuentra,
> porque cada pieza hace exactamente lo que promete.

**Aquí el framework se paga solo.** Con el banco en pie, ejecutar el experimento de la **Fase A de la auditoría**: ¿reparar el depth-weighting (H-1/H-33/H-38, inerte hoy en los tres solvers) cambia la recuperación de profundidad?

**Criterio verificable:** *tabla antes/después por régimen con 5 semillas y configuración de producción, dejando que Morozov re-elija λ en ambos brazos.* El resultado, sea cual sea, cierra una pregunta que lleva meses abierta: si mejora, es producto nuevo; si no, la ley del null-space queda confirmada con autoridad definitiva.

---

# 7. RIESGOS DEL PROPIO FRAMEWORK

Un sistema de validación que falla en silencio es peor que no tenerlo, porque produce confianza injustificada.

| Riesgo | Mitigación de diseño |
|---|---|
| **Inverse crime accidental** | `generation_method` obligatorio; `INVERSE_CRIME` excluido de gates por construcción (P4) |
| **Umbrales ajustados hasta pasar** | `justification` + `measured_value` obligatorios en el tipo (P3); revisión de cualquier cambio de umbral como cambio de contrato |
| **Fixture drift** (cambia el mundo y parece que TQ mejoró) | `world.instance_version` + hash; el `Result` guarda contra qué versión corrió |
| **Validar una puerta que nadie usa** | `entry_point` registrado; los gates exigen `package_flow` (P5) |
| **Falsa cobertura** | Cada nivel declara qué recortó; sin silencio sobre lo truncado |
| **El framework se vuelve el producto** | Anti-scope §0.2, revisado en cada sprint |
| **El propio harness produce el resultado** (añadido tras el Sprint 2) | **Todo barrido nuevo exige un experimento de control que reproduzca un resultado conocido antes de que sus números cuenten.** Un harness sin control genera tablas con apariencia de rigor —media ± σ sobre N semillas— que son artefactos de sus propios parámetros. Medido: `density_min` mal elegido invalidó 75 inversiones |
| **Una métrica esconde el fallo que otra revela** (añadido tras el Sprint 2) | Medido: con el modelo hundido, el error horizontal MEJORABA (46 m) mientras el PR-AUC se desplomaba (0,04). Ningún veredicto puede apoyarse en una sola familia de métricas: localización **y** campo, siempre juntas |
| **Las N semillas no son N muestras independientes** (añadido tras el barrido de 2026-08-06) | **[MEDIDO]** La semilla 3003 es la peor en 6 de 6 regímenes examinados: las campañas comparten el arranque del flujo aleatorio, así que la realización adversa se repite entre regímenes. El σ reportado mide en parte una realización repetida. **Mitigación pendiente:** derivar la semilla del par régimen×semilla, no de la semilla sola, y volver a medir σ |
| **La media describe mal una distribución bimodal** (añadido tras el barrido de 2026-08-06) | **[MEDIDO]** `baseline` reportaba 105 ± 132 m; la mediana es 18,2 m porque 3 de 5 semillas dan PR-AUC 1,000 y 2 se desploman. La media sugiere una nube ancha donde hay un interruptor. **P7 sigue vigente —la varianza es el hallazgo— pero se reporta mediana + valores por semilla, no sólo media ± σ** |

---

# 8. DECISIONES RESUELTAS POR INVESTIGACIÓN

*Las cuatro preguntas abiertas de la primera versión de este documento se resolvieron consultando la práctica establecida, no por preferencia. **Una de mis propuestas resultó estar mal planteada** y se corrige aquí.*

## D1 — Dónde vive: directorio de nivel superior, y los resultados aparte

**Decisión: `validation/` como directorio de primer nivel, hermano de `tests/`. Y el historial de resultados en un archivo separado del repositorio de código.**

**Evidencia.** La convención establecida en el ecosistema científico de Python (guía de empaquetado de pyOpenSci; práctica de ASV, la herramienta de benchmarking de NumPy/SciPy/pandas) es un **directorio de benchmarks de nivel superior con su propia configuración**, separado tanto del paquete como de los tests. Y explícitamente: *"un repositorio de archivo de benchmarks separado evita saturar el repositorio principal con resultados"*.

**Lo que esto corrige de mi propuesta original:** yo había propuesto `terraquantum-backend/validation/` **dentro** del paquete backend. Está mejor fuera: el framework no es parte del producto que se distribuye —no debe entrar en el sidecar de PyInstaller de 199 MB— y ponerlo dentro invita a que alguien lo importe desde producción.

**Y añade algo que no había considerado:** la separación del **archivo de resultados**. Es directamente relevante aquí, porque el repositorio ya arrastra 113 MB de DO-27 y la auditoría midió un instalador de 321 MB. Un historial que crece con cada corrida de cada versión no puede vivir en el árbol de código.

*Nota relacionada de la misma fuente:* la práctica recomendada es **no incluir datos de test en el repositorio**, sino alojarlos externamente (Zenodo, Figshare) y descargarlos con `pooch`. Aplicable a los datasets grandes actuales — lo dejo anotado, no es parte de este framework.

## D2 — Umbral de segmentación: la pregunta estaba mal planteada

**Decisión: las métricas primarias deben ser INDEPENDIENTES DEL UMBRAL. IoU a un τ fijo pasa a secundaria y solo se reporta con su τ declarado.**

**Evidencia.** La literatura de evaluación por segmentación documenta que *"el ranking de modelos puede cambiar con distintos ajustes de binarización, lo que subraya el valor de las métricas independientes del umbral"*.

**Por qué esto importa muchísimo aquí:** el propósito declarado del framework es decir si la versión 0.8 es mejor que la 0.7. **Si la métrica principal depende de un umbral, la respuesta a esa pregunta puede invertirse eligiendo otro umbral** — y el framework entero pierde su razón de ser. Mi propuesta de "reutilizar el criterio relativo al pico del visor" habría metido esa fragilidad en el núcleo.

**Diseño corregido:**
- **Primaria:** métrica independiente del umbral sobre el campo continuo — **PR-AUC** (precisión-exhaustividad sobre el barrido de umbrales) y/o la **curva IoU(τ)** completa, reportando el área bajo ella.
- **Secundaria:** `iou_3d` a un τ declarado en `Acceptance`, útil para comunicar a un humano ("el cuerpo recuperado solapa un 0,72 con el verdadero al 50% del pico") pero **nunca como criterio de comparación entre versiones**.
- El campo `τ` sigue viviendo en `Acceptance` para que sea auditable.

*El vocabulario ya existe en tu repo:* el agente revisor de benchmarks geofísicos del proyecto menciona "PR-AUC/Top-K/IoU/F1". La decisión es promover PR-AUC de métrica ocasional a métrica primaria.

## D3 — Honestidad: mi `overconfidence_rate == 0` era ingenuo

**Decisión: adoptar la tríada estándar de calibración — diagrama de fiabilidad + ECE + MCE — y poner el gate duro sobre el bin de confianza alta, no sobre un conteo suelto.**

**Evidencia.** La práctica establecida para medir si un sistema "sabe lo que no sabe" no es contar fallos: es el **diagrama de fiabilidad** (confianza declarada contra exactitud empírica; un sistema perfectamente calibrado cae en la diagonal de 45°), resumido en dos números: **Expected Calibration Error (ECE)** — la desviación media entre confianza y exactitud, ponderada por bin — y **Maximum Calibration Error (MCE)** — el peor bin.

**Lo que esto corrige:** mi `overconfidence_rate` era, sin saberlo, **una versión pobre del MCE**. La formulación estándar es mejor por tres razones: (a) distingue el sesgo medio del peor caso, y en un producto de seguridad el peor caso manda; (b) es comparable entre versiones como número continuo, mientras que un contador entero salta de 0 a 1 sin gradación; (c) tiene nombre reconocible, lo que importa cuando alguien externo audita tu método.

**Diseño corregido:**

```python
@dataclass(frozen=True)
class CalibrationReport:
    reliability_bins: tuple[Bin, ...]   # (confianza_declarada, exactitud_empírica, n)
    ece: float                          # miscalibración media
    mce: float                          # peor bin  ← el criterio de seguridad
    high_bin_accuracy: float            # exactitud dentro del bin HIGH
    overconfident_cases: tuple[str, ...] # trazabilidad: qué escenarios
```

**Gate propuesto, ahora con forma defendible:** el bin de confianza **HIGH** debe tener exactitud ≥ el umbral que declara (con su justificación medida, P3), y **MCE se reporta y se vigila**. El "cero casos sobreconfiados" sigue siendo el objetivo, pero expresado como *"exactitud del bin HIGH ≥ X"* en vez de como un contador.

*Matiz de diseño, honesto:* la confianza de TQ es **ordinal** (HIGH/MEDIUM/LOW), no una probabilidad. Un diagrama de fiabilidad canónico asume probabilidades. La adaptación es tratar cada nivel como un bin y declarar la exactitud esperada de cada uno — es lo que hace la literatura con predicciones categóricas, y hay que **documentar la adaptación** en vez de fingir que se aplica la fórmula estándar sin más.

## D4 — Migrar `synthetic_recovery_benchmark.py`, no congelarlo

**Decisión: migrar, pero por partes y con paridad demostrada antes de retirar el original.**

**Evidencia.** La misma convención de D1 resuelve esto: los benchmarks **no viven en `tests/`**. Ese archivo (1.020 LOC) está hoy en `tests/`, y ahí no le corresponde estar: produce artefactos y mide recuperación, no verifica invariantes. Congelarlo perpetuaría la mezcla que el framework existe para deshacer.

**Procedimiento:** migrar sus escenarios a `World`/`Campaign` de uno en uno, y mantener el original ejecutándose hasta que el framework reproduzca sus números **dentro de tolerancia declarada**. Solo entonces se retira. Es el mismo criterio de byte-identidad que la auditoría recomienda para los refactores del motor (Fase B).

## D5 — Hallazgo no buscado: el oráculo independiente ya existe

Investigando surgió algo que **refuerza P4 de forma estructural**, y no estaba en el plan.

**Harmonica** (proyecto Fatiando a Terra) implementa modelado directo de gravedad y magnetismo —prismas, fuentes puntuales, teseroides— optimizado con numba y **diseñado explícitamente para ser reutilizado por otras librerías**, incluida SimPEG.

Es decir: existe una **implementación independiente y madura del problema directo**. Usarla como generadora de las observaciones sintéticas convierte el anti-inverse-crime de *procedimiento* (usar otra malla y acordarse) en *estructura* (el dato lo produce otro código, de otros autores).

**Y tu proyecto ya tuvo esta idea:** `docs/01` registra en F2B *"Fatiando a Terra/harmonica como oráculo de comparación en tests, sin agregarla como dependencia de producción"*. La decisión es **extender ese patrón de los operadores FFT al forward gravimétrico y magnético** del framework.

⚠️ **Requiere tu autorización explícita**: es una dependencia nueva, aunque sea solo de validación y no de producción. Las reglas del repositorio lo exigen.

Esto añade un cuarto valor a `GenerationMethod`:

```python
THIRD_PARTY = "third_party_forward"   # Harmonica u otra implementación externa
```

que es el **más fuerte** de todos, por encima de `FORWARD_ALT_MESH`.

## D6 — Contexto competitivo: no hay suite comunitaria que reutilizar

**[Hallazgo de la investigación]** No encontré una suite de benchmarks sintéticos formal y consensuada para inversión gravimétrica/magnética. Existen las piezas (los forwards de Harmonica, los tutoriales de SimPEG) pero **no un catálogo de escenarios con verdad conocida y métricas acordadas**.

Dos lecturas, y las dos importan:

1. **No hay rueda que reinventar**: no se está duplicando algo que ya exista mejor hecho.
2. **Es una oportunidad de posicionamiento.** Un catálogo público de escenarios con verdad conocida, métricas reproducibles y resultados versionados es **material de credibilidad** — exactamente el activo que `docs/00_INVESTIGACION_MERCADO.md` identifica como el camino hacia el consultor. Vale más que una funcionalidad nueva.

---

# 9. CAMBIOS QUE ESTAS DECISIONES INTRODUCEN EN EL DISEÑO

| Sección | Qué cambia |
|---|---|
| §2.2 `GenerationMethod` | Se añade `THIRD_PARTY` como método preferente (D5) |
| §4.1 Métricas | **PR-AUC / IoU(τ) integrada pasan a primarias**; `iou_3d` a τ fijo queda secundaria y nunca compara versiones (D2) |
| §4.2 Honestidad | `overconfidence_rate` se sustituye por `CalibrationReport` con ECE + MCE + exactitud del bin HIGH (D3) |
| §5 Ejecución | El historial de resultados vive en un archivo separado del repositorio de código (D1) |
| §6 Sprint 0 | La pregunta 3 (bibliotecas existentes) queda **respondida**: Harmonica como oráculo; no hay suite comunitaria (D5, D6) |
| §6 Sprint 3 | El criterio pasa a ser *"exactitud del bin HIGH ≥ umbral justificado, con ECE y MCE reportados"* |
| Ubicación | `validation/` de primer nivel, fuera del paquete backend (D1) |

---

*Documento de diseño. Ninguna línea de código del repositorio fue modificada al escribirlo. La única decisión que sigue requiriendo tu autorización es **D5**: añadir Harmonica como dependencia de validación (no de producción). El siguiente paso natural es el Sprint 1 — pequeño, y produce la primera vuelta completa del circuito.*

**Fuentes de la investigación:** [pyOpenSci — Python Package Structure](https://www.pyopensci.org/python-package-guide/package-structure-code/python-package-structure.html) · [Benchmarking Scientific Python Packages with ASV](https://speakerdeck.com/anissa111/benchmarking-your-scientific-python-packages-using-asv-and-github-actions) · [Expected Calibration Error](https://www.emergentmind.com/topics/expected-calibration-error-ece) · [Calibrated Uncertainty Quantification](https://www.emergentmind.com/topics/calibrated-uncertainty-quantification) · [netcal — calibration framework](https://github.com/EFS-OpenSource/calibration-framework) · [Harmonica — Fatiando a Terra](https://github.com/fatiando/harmonica) · [SimPEG](https://docs.simpeg.xyz/) · [Deep learning EM inversion (uso de IoU)](https://academic.oup.com/gji/article/218/2/817/5484841)
