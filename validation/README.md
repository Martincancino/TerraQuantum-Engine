# TerraQuantum — Validation Framework

Responde una sola pregunta: **¿TerraQuantum recupera correctamente la realidad que
conozco — y lo dice cuando no?**

Diseño completo y justificación de cada decisión: [`docs/07_VALIDATION_FRAMEWORK.md`](../docs/07_VALIDATION_FRAMEWORK.md).

---

## Uso

```bash
# desde la raíz del repositorio
pip install -r validation/requirements-validation.txt

python -m validation.test_determinism   # segundos — reproducibilidad e invariantes
python -m validation.run_smoke          # ~6 min por caso — una inversión real
```

`test_determinism` no invierte: verifica que el oráculo coincide con la fórmula
cerrada, que la misma semilla produce los mismos datos, y que los invariantes del
contrato se cumplen. Es barato y debe correr siempre.

---

## Las cuatro entidades

| Entidad | Pregunta | Dónde |
|---|---|---|
| `World` | ¿qué hay ahí abajo? (la verdad) | `contract.py` |
| `Campaign` | ¿cómo lo medí? | `contract.py` |
| `Acceptance` | ¿qué considero bueno? | `contract.py` |
| `Result` | ¿qué obtuve? | `contract.py` |

Un mundo puede tener N campañas: eso convierte *"el mismo cuerpo medido de cinco
maneras"* en un experimento, no en cinco fixtures sin relación.

## Invariantes que impone el TIPO, no la disciplina

- **`Threshold` sin `justification` no se puede construir.** Un umbral sin la
  medición que lo respalda es contabilidad, no ciencia.
- **`GenerationMethod.INVERSE_CRIME` está excluido de cualquier gate** por
  `admissible_in_gate`. El anti-inverse-crime deja de depender de que alguien se
  acuerde.
- **No existe un campo `ground_truth`.** La verdad es la geometría + las
  propiedades; los derivados se calculan con `truth_products()`, que es pura y
  recibe la malla como argumento.
- **Se entra por `run_geophysics_inversion`**, el flujo de producción — no por la
  API interna del solver. Ver abajo por qué.

## Por qué el oráculo es externo

Las observaciones las genera **`choclo`** (proyecto Fatiando a Terra), no el motor
de TerraQuantum. Que el dato lo produzca código de otros autores convierte el
anti-inverse-crime de *procedimiento* en *estructura*.

Convenciones verificadas antes de usarlo (`generate.py`):

| | choclo | TerraQuantum |
|---|---|---|
| ejes | (easting, northing, upward) | (x, y, z) |
| vertical | upward positivo **arriba** | y positivo **abajo** |
| signo | negativo para exceso de masa | positivo |
| unidades | m/s² | m/s² |

`selfcheck_against_analytic()` compara choclo contra la fórmula cerrada de masa
puntual en cada arranque del smoke: **error 4,1e-16**. Si choclo o las convenciones
cambian, se detecta antes de medir nada.

## Por qué se entra por el flujo de producción

La auditoría (`docs/06`) encontró que los fallos más peligrosos **no estaban en el
solver** sino en el camino hasta él:

- **H-37** — el modo `amplitude` está declarado en el esquema y ofrecido en la UI,
  pero ninguna rama lo despacha: corre TMI inducida y el reporte dice "amplitude".
  Un framework que llamara a `solve_amplitude_inversion_lsqr` directamente lo
  habría dado por bueno para siempre.
- **H-27** — la caída a topografía plana se registra en el log y no llega al usuario.
- **H-38** — el padding se activa incondicionalmente y **cambia el funcional de
  regularización**; por eso `Result.tq_config` guarda la configuración *efectiva*,
  no la solicitada.

## Dónde se guardan los resultados

Fuera del repositorio, en `%LOCALAPPDATA%\TerraQuantum\validation_results\<versión>\`
(o `TQ_VALIDATION_HOME`). Convención de ASV: un historial que crece con cada corrida
de cada versión no debe vivir en el árbol de código.

---

## Sprint 2 — CERRADO (2026-08-06)

**150 corridas** (15 regímenes × 5 semillas × 2 brazos de `density_min`), 149,5 min,
0 errores. Resultados completos y salvedades:
[`RESULTS_2026-08-06_barrido_dos_brazos.md`](RESULTS_2026-08-06_barrido_dos_brazos.md).

Titulares, con lo que cada uno certifica y lo que no:

- **`s_strict_L2` domina en los 15 regímenes.** El brazo permisivo hunde la masa al fondo
  del dominio *siempre* en esta malla (PR-AUC 0,002–0,075). Alcance: **una sola malla**
  (125 m); la única medición donde el permisivo ganó fue en malla de 50 m, fuera de este
  barrido. La resolución de malla queda como eje no medido.
- **7 de 15 regímenes recuperan de verdad** (PR-AUC mediano ≥ 0,30). Los otros 8 tienen
  umbral de regresión pero **ninguna pretensión de calidad**.
- **En 4 regímenes el error de centroide habría elegido el brazo equivocado**: mejor
  horizontal con PR-AUC 10× peor. Ver §2 del reporte.
- **Acantilado de profundidad entre 400 y 600 m** (PR-AUC 0,86 → 0,10), reproduciendo de
  forma independiente lo que `docs/05` midió con otro harness y otro generador.
- **La distribución es bimodal, no ancha.** En `baseline`, tres semillas dan PR-AUC 1,000
  con 6–18 m de error y dos se desploman a 208–285 m. Y la semilla 3003 es la peor en
  6 de 6 regímenes examinados: **las semillas están correlacionadas entre regímenes**, así
  que 5 semillas dan menos independencia de la que aparentan.
- **TerraQuantum nunca declaró confianza `HIGH`** en las 150 corridas (103 `MEDIUM`,
  47 `LOW`). El "0 sobreconfiados" es por tanto mucho más débil de lo que suena.

**⚠️ Y de ahí salieron los dos hallazgos principales de la sesión.**

### (a) El bound de densidad por defecto cae del lado que hunde el modelo

[`HALLAZGO_2026-08-06_bound_por_defecto.md`](HALLAZGO_2026-08-06_bound_por_defecto.md) — 48
inversiones controladas. Contraste permitido ≥ 0 → PR-AUC mediano **1,000** y 25 m de error;
contraste ≥ **−0,01** (un 1,7 % del contraste del cuerpo) → **8/8 caídas**, PR-AUC 0,035.
El camino por defecto del usuario deja pasar **≥ −2,6**: UI `densityMin="0.0"` →
`gravity_import_api.py:1819` verbatim, **sin pasar `base_density`** → default de esquema 2,6.
Nada acopla los dos campos y ningún test cubre el caso desacoplado.

La justificación escrita del default (*"el clip estricto degrada el misfit ~35 %"*) se midió:
es **16–21 %** en los regímenes compactos que invoca, **+0,6 % de mediana** sobre los 15, y
cuesta **93–97 % del PR-AUC**. El misfit es la métrica ciega a ese precio.

Candado: [`test_bound_regression.py`](test_bound_regression.py) (`TQ_RUN_VALIDATION=1`).

### (b) El veredicto tiene un techo estructural en `MEDIUM`


[`HALLAZGO_2026-08-06_techo_medium.md`](HALLAZGO_2026-08-06_techo_medium.md). En `baseline`,
**una de cada tres realizaciones de ruido** (8/24, IC 95 % 18–53 %) da un blanco a ~169 m en
vez de ~19 m — y el producto declara `('MEDIUM','LOW',False)` en **las 24**, idéntico para
los dos desenlaces. La causa está localizada: el QA de checkerboard **no depende del dato
observado**, usa un patrón que alterna celda a celda —por debajo del límite físico de un
campo potencial— y devuelve `FAIL` siempre; B3 lo toma como tope duro (worst-of), así que
`HIGH` es inalcanzable por construcción. El diseño de B3 es correcto; una de sus entradas
está pegada.

Umbrales medidos: `acceptance_measured.py`, **generado desde los datos crudos**, no escrito
a mano.

---

## Cómo se llegó ahí: el barrido anterior fue RETIRADO

El primer barrido (127 min, 75 inversiones) **se retiró por decisión propia**, no porque
alguien lo cuestionara. Vale la pena conservar el registro: es lo que justifica el diseño.

**Lo que mostró el barrido:** el centroide recuperado cae a ~1.650 m —el fondo del
dominio— **sea cual sea la profundidad verdadera** (250, 400, 600 o 900 m). El
"error de profundidad" que reportaba la tabla no medía el régimen: medía la
distancia de la verdad al suelo del dominio.

**El control que lo retiró** (`control_lambda.py`): mismo mundo, misma campaña,
cambiando SOLO λ. Con λ=1e-3 —la configuración del harness antiguo, que reporta
14 m en baseline— mi framework seguía dando 289 m y el mismo hundimiento.
**Conclusión: la diferencia no es la configuración de λ, es mi harness.**

**Divergencias estructurales identificadas** (ambas eran elecciones arbitrarias mías,
no de producción ni del harness antiguo):

| parámetro | `error_budget.py` | mi runner v1 |
|---|---|---|
| `density_min` | `BASE_DENSITY` — **prohíbe contraste negativo** | `base − 0.5` — lo permite |
| `regularization_norm` | `"compact"` (IRLS minimum-support) | `"L2"` (suave) |

**Resultado de la matriz de atribución** (`control_matrix.py`, mismo mundo, misma
campaña, misma semilla; verdad a 400 m, fondo del dominio 1.687 m):

| config | horizontal | centroide y | PR-AUC | IoU@τ |
|---|---:|---:|---:|---:|
| A · L2 + contraste negativo | 100,3 m | **1.653 m** | 0,038 | 0,000 |
| B · L2 + solo positivo | 208,0 m | **655 m** | **0,704** | 0,104 |
| C · compact + contraste negativo | 45,8 m | **1.662 m** | 0,065 | 0,000 |
| D · compact + solo positivo | 243,1 m | **661 m** | **0,634** | 0,242 |

**La causa es `density_min`, no la norma de regularización.** Con contraste negativo
permitido (A, C) la masa se hunde al fondo en ambas normas; prohibiéndolo (B, D) el
centroide sube a ~658 m y el PR-AUC salta de 0,04 a 0,70. El solver estaba
construyendo un dipolo —positivo somero, negativo profundo— que ajusta el dato y
desplaza la masa.

**Y hay una lección que vale más que el bug:** en las configuraciones patológicas el
error **horizontal era MEJOR** (46–100 m) que en las sanas (208–243 m), porque el
cuerpo hundido queda centrado bajo el survey. La métrica de centroide **premiaba la
patología**. Lo que la delató fue el PR-AUC (0,04 vs 0,70).

Esto valida en la práctica la decisión D2 del diseño: **las métricas de campo
independientes del umbral no son un refinamiento estadístico, son lo que impide que
una métrica de localización te esconda un modelo roto.**

### ⚠️ Corrección de la corrección: `density_min` no es un bug, es una VARIABLE

Al re-verificar el Sprint 1 con el default cambiado, el efecto **se invierte**:

| w001 (malla 50 m, esfera somera 300 m, 16×16) | contraste negativo | solo positivo |
|---|---:|---:|
| horizontal | **2,3 m** | 9,8 m |
| profundidad | **33,2 m** | 86,1 m |
| PR-AUC | **0,961** | 0,479 |
| χ² | 1,78 | 0,494 (sobreajusta) |
| λ elegido por Morozov | 0,316 | 0,024 |

En la malla fina y somera, **permitir contraste negativo da un resultado claramente
mejor**; en la malla gruesa (`w_base`, 125 m) causa el hundimiento catastrófico. El
mismo parámetro mejora un régimen y destruye otro — y además **cambia el λ que
Morozov elige** en más de un orden de magnitud (0,316 → 0,024).

**Conclusión corregida:** `density_min` **no era un defecto que arreglar, sino una
variable experimental que yo estaba fijando en silencio.** Mi primer valor
(`base − 0,5`) y el segundo (`base`) son ambos elecciones mías, no de producción.

**Implicación de diseño (pendiente, va al Sprint 3):** los parámetros del solver que
cambian materialmente el resultado no pueden vivir como defaults del runner. Necesitan
ser una entidad declarada —`SolverConfig`— igual que `World` y `Campaign`, con su
procedencia registrada. Es el mismo principio P3/P6 aplicado a la configuración: **lo
que cambia el resultado se declara, no se asume.**

Hoy `density_min_override` y `regularization_norm` son parámetros explícitos del
runner y se registran en `Result.tq_config`, pero **su valor por defecto sigue siendo
una elección tácita**. Hasta cerrar eso, ningún número de este framework debe
compararse con otro que no declare esos dos valores.

**Residual honesto — y su desenlace.** Durante semanas quedó abierto que el baseline daba
~208 m de error horizontal frente a los **14 m** de `error_budget.py`, con la hipótesis
nombrada del padding incondicional de producción (H-38).

**El barrido de 150 corridas lo resolvió en buena parte, y no como yo esperaba:** la
**mediana** del baseline es **18,2 m**, comparable a los 14 m del harness antiguo. Los
208 m eran una media arrastrada por dos semillas que se desploman. No había sesgo
sistemático de la ruta de producción; había una distribución bimodal reportada con la
estadística equivocada.

Lo que sigue abierto es más interesante que la brecha original: **por qué se desploman esas
dos semillas.** Un modo de fallo que aparece en el 40 % de las realizaciones de ruido, en
el régimen donde el producto declara su fortaleza, importa más que 4 m de diferencia en la
mediana. H-38 no queda refutado, pero deja de ser necesario para explicar los números.

**Por qué esto importa más que los números perdidos:** el framework hizo exactamente
su trabajo. Un harness sin experimento de control habría publicado una tabla con
apariencia de rigor —media ± σ sobre 5 semillas— que era un artefacto de dos
parámetros mal elegidos. La lección va al diseño: **todo barrido nuevo necesita un
control que reproduzca un resultado conocido antes de que sus números cuenten.**

---

## Estado actual (Sprint 1)

Primera vuelta completa del circuito, medida:

| | |
|---|---|
| mundo | `w001_single_sphere` — esfera r=150 m a 300 m, contraste +0,6 t/m³ |
| campaña | 16×16 estaciones sobre 1.600 m, ruido 0,01 mGal |
| λ elegido | **0,31623** por `morozov_chi2_discrepancy` (config de producción) |
| error horizontal | **2,3 m** |
| error de profundidad | 33,2 m |
| PR-AUC (primaria) | **0,9612** |
| IoU-AUC (primaria) | 0,5248 |
| χ² | 1,78 · misfit 9,69 % |
| honestidad | confianza MEDIUM, profundidad LOW → **CALIBRADO** |
| veredicto | **PASS** |

El error horizontal de 2,3 m es coherente con lo que `docs/05` midió para el régimen
somero-denso-limpio (2 m), lo que da confianza cruzada entre dos harnesses
independientes.

### Limitaciones honestas de este estado

- ~~**Un solo mundo y una sola semilla.**~~ Cerrado en el Sprint 2: 15 regímenes × 5
  semillas × 2 brazos.
- **Los umbrales de `catalog.py` siguen anclados a benchmarks externos**, y es
  deliberado: el barrido midió los mundos de `regimes.py` sobre malla de 125 m, y `w001`
  es otro mundo con otra malla. Copiarle esas medianas sería anclar a una medición que no
  lo midió. Los umbrales medidos viven en `acceptance_measured.py`.
- **La aceptación se evalúa por corrida, no por agregado.** Con distribución bimodal eso
  deja los umbrales flojos (`baseline` ≤ 360 m cuando la mediana es 18 m): sólo cazan
  regresiones catastróficas. El gate afilado —la mediana sobre N semillas— se publica en
  `acceptance_measured.MEDIANS`, pero el contrato aún no sabe evaluarlo.
- **Presupuesto de tiempo excedido:** el diseño fija <5 min para el smoke; una
  inversión real con Morozov (6 solves) tarda **~6 min**. Ver abajo.
- `depth_error_top_m` y `pearson_r` aún no se calculan (quedan en `NaN` explícito,
  nunca en 0).

### Recomendación de CI, dado el tiempo medido

| Nivel | Qué | Cuándo |
|---|---|---|
| `test_determinism` | segundos, sin invertir | **cada PR** |
| `run_smoke` | ~6 min por caso | nocturno |

Poner el smoke en cada PR con el tiempo actual sería la vía rápida a que alguien
lo desactive. La regresión física completa (`pytest -m validation`) sigue siendo
un hueco abierto de la auditoría (H-4).
