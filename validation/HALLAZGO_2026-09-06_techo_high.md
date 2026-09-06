# HALLAZGO — Fase 30: el techo a `HIGH` no era una entrada, eran tres

**Fecha:** 2026-09-06 · **Rama:** `fases-19-25-cierre` · **Ámbito:** backend puro.
**Pre-registro:** `validation/PREREGISTRO_2026-09-06_fase30.md` (escrito antes de medir).
**Gate reproducible:** `py -3.14 -m validation.exp_high_ceiling`.

---

## 0. Resumen en una frase

El plan pedía **quitar una sola entrada** del worst-of (`high_hold_pending_fase30`); medido
sobre las 75 corridas de la Fase 26, hacer exactamente eso **no habría cambiado ni uno de los
75 veredictos**, y el gate de la fase —«0 corridas SOBRECONFIADAS»— habría dado 0 con **0
corridas en `HIGH`**: un 0 que mide un techo, no honestidad. Es la **quinta** vez en este
proyecto que el trabajo que pedía la ficha era decorativo.

---

## 1. Lo que se midió ANTES de tocar código

Fuente: `exp_resolution_confirm.json` de la Fase 26 — 15 regímenes × 5 semillas frescas
(900011…900515), el conjunto sobre el que la Fase 26 cerró con ρ = +0,8081.

| pregunta | respuesta |
|---|---|
| corridas cuyo **único** limitante es `high_hold_pending_fase30` | **0 de 75** |
| corridas MEDIUM también capadas por `priority_class` | **44 de 44** |
| ⇒ **veredictos que cambia quitar sólo el hold** | **0 de 75** |
| corridas donde `priority_class` decide en solitario | **0 de 75** |

El techo declarado **no era el techo**. Detrás había otro, sin declarar, y con una propiedad
peor: `priority_class` capaba a MEDIUM **las 44 corridas MEDIUM sin distinguir entre ellas**,
incluidas las de PR-AUC 1,000 y 11 m de error horizontal.

### Y un tercero, medido en el payload

La corrida mejor calificada de todo el barrido (`depth_250m`: PR-AUC 1,000, error 11,3 m)
sale con **todas** las señales de calidad en HIGH — `survey_confidence: HIGH`,
`model_reliability: HIGH_RELIABILITY`, `survey_resolution: RESOLVES` a 250 m, sin smear de
piso, `r06_physical_severity = 0,0`, `technicalSummary.overall_level = GOOD`,
`uncertainty_score = 0,0` — y aun así queda en MEDIUM, porque
`priority_class = MEDIUM_RELATIVE_PRIORITY`. La razón, medida en el mismo payload:

```
favorability.score = 44,9      (hace falta >= 65 para HIGH_RELATIVE_PRIORITY)
  anomaly_intensity    0,000   <-- w=0,25   en la MEJOR corrida del barrido
  depth_accessibility  0,850   <-- w=0,20
  core_coherence       1,000   <-- w=0,25
  structural_gradient  0,000   <-- w=0,15
  msx_support          0,067   <-- w=0,10
  quality_gate x1,00 · uncertainty_gate x1,00   (los dos PERFECTOS)
```

Con los dos multiplicadores en su valor máximo el score sigue en 44,9, así que
`HIGH_RELATIVE_PRIORITY` no era inalcanzable *en esa corrida*: era inalcanzable **por la
aritmética de los factores**. Y `anomaly_intensity` está **invertido**: da **0,000** a la
mejor corrida y **1,000** a `worst_ldm_like` (PR-AUC 0,002, error 1.186 m).

---

## 2. La decisión, y por qué no es la que pedía la ficha

Cumplir la ficha al pie de la letra habría dado un gate verde sin haber movido nada. Lo que
hace la fase, en tres cambios de `build_reconciled_verdict`:

### 2.1 Se retira la retención declarada

`levels.append(("MEDIUM", "high_hold_pending_fase30"))` desaparece. Era honesta —decía que
era una retención, con condición de salida escrita— pero no era la que mandaba.

### 2.2 `priority_class` deja de topear (y se sigue publicando)

Motivo **semántico**, no numérico: mide el **atractivo** relativo del blanco, no la
**confiabilidad** del modelo, que es lo que este veredicto responde. Y ya venía derivado de la
calidad — `compute_favorability_score` multiplica por `quality_gate`
(`technicalSummary.overall_level`) y por `uncertainty_gate`, y la Regla 1 le prohíbe HIGH si
`overall_level == LOW` —, así que dentro del worst-of **contaba la calidad dos veces** e
inyectaba una dimensión ajena a la pregunta.

Se degrada a señal publicada con su papel declarado
(`priority_class_role: targeting_attractiveness_not_quality_since_fase30`), exactamente el
patrón que la Fase 26 aplicó al tablero. **No se borra del reporte.**

Que retirarlo es seguro está medido, no argumentado: las **3** corridas que serían
SOBRECONFIADAS si `HIGH` se soltara sin criterio (978,4 · 636,8 · 542,1 m de error) las cazan
`survey_confidence` y `model_reliability` **por su cuenta**, ambas en MEDIUM. `priority_class`
no era quien protegía de la sobreconfianza: era **quien impedía medirla**.

### 2.3 `HIGH` deja de concederse por AUSENCIA de defectos — el sello

Éste es el cambio de fondo. Hasta la Fase 29 el worst-of sólo sabía **restar**: cada señal
podía topear, y quien no topeaba no aportaba nada. Con el techo puesto daba igual, porque
nadie llegaba arriba. Al retirarlo se midió que **no** da igual: soltar `HIGH` sin criterio
positivo declaraba HIGH a **3 corridas de 44**.

Así que el nivel superior exige ahora evidencia positiva — dos pruebas, `_high_seal`:

1. **Resolución mejor que el suelo del examen.**
   `shallowest_band_resolution_m < max_block_tested_m`. El perfil de la Fase 26 prueba una
   escalera de bloques laterales; aprobar **sólo el peldaño más grueso** es aprobar el suelo
   del examen, no demostrar resolución. Es una condición **estructural** («no el último
   peldaño»), no un número: no cambia si mañana cambian la escalera o el tamaño de celda.

2. **Sin exceso de masa en el piso de la malla.** `floor_mass_excess ≤ 0,5`.
   Es el número que la Fase 26 midió y el plan mandó traer, usado donde corresponde: como
   umbral para **degradar a LOW** dejaba sólo un 12 % de margen al peor caso sano y por eso se
   dejó en 1,0; como umbral para **negar el nivel superior** no acusa a nadie, sólo se niega a
   sellar, y el coste de equivocarse es un MEDIUM de más y no un LOW injusto.

**La ausencia no sella.** Si falta cualquiera de los dos datos, el sello capa a MEDIUM. Es la
propiedad de la Fase 21 —medir menos nunca mejora el veredicto— aplicada al nivel nuevo, y
ahora importa mucho más: sin ella, un reporte vacío saldría `HIGH`.

### 2.4 Dos efectos colaterales que había que arreglar

* **La rama `HIGH` del worst-of nunca se había ejecutado.** Con el techo puesto el mínimo era
  siempre MEDIUM o menos. Al abrirla se ve que la fórmula genérica lista como «limitantes» a
  **todas** las señales empatadas en el máximo: la corrida mejor calificada del sistema
  publicaría «limitado por: survey_confidence, model_reliability, …». Cuando el veredicto es
  HIGH, `limiting_factors` va **vacío**.
* **`ceiling` era una constante del producto.** Devolvía literalmente lo mismo —MEDIUM,
  `capped_by: [la retención]`, el mismo párrafo— para las 75 corridas del barrido, la mejor y
  la peor. Un campo constante no informa: era la patología del tablero un piso más arriba. Hoy
  se calcula de las señales que topearon **esta** corrida, dice qué prueba concreta falló con
  su número, y `how_to_lift` dice qué hacer en el mundo físico en vez de «esperar a una fase».

---

## 3. El gate

Tres criterios declarados antes de correr, sobre **150 corridas** con semillas frescas
(310007 + 1009·i, sin solape con ninguna tanda anterior):

* **G1 — honestidad.** Cuadrante SOBRECONFIADO (error horizontal > 200 m **y** veredicto
  `HIGH`) = **0**.
* **G2 — alcanzabilidad.** ≥ 20 % de las corridas en `HIGH`. Es lo que convierte el 0 de G1 en
  una medición y no en un techo. **Sin G2 el gate se cumple sin que el cambio haga nada**, que
  es literalmente lo que habría pasado ejecutando la ficha al pie de la letra.
* **G3 — no regresión.** Ninguna corrida con `resolves_anywhere = False` por encima de LOW, ni
  ninguna con `is_floor_smear = True`. Es lo que cerró la Fase 26.

### El resultado, medido

Corrida completa: **150 corridas**, 49 min, versión `d6701e1+dirty`.
Datos crudos en `exp_high_ceiling.json` bajo `TQ_VALIDATION_HOME`.

| nivel | n | PR-AUC mediana | PR-AUC mín. | error horiz. mediana | p90 | máx. | con error > 200 m |
|---|---:|---:|---:|---:|---:|---:|---:|
| **HIGH** | 36 | 1.000 | 0.683 | 18,5 m | 82,2 m | 164,9 m | **0** |
| MEDIUM | 36 | 0.481 | 0.210 | 306,4 m | 1 278,2 m | 1 337,6 m | 18 |
| LOW | 78 | 0.035 | 0.002 | 599,5 m | 1 274,6 m | 1 414,2 m | 62 |

* **G1 — PASA.** Corridas SOBRECONFIADAS: **0**.
* **G2 — PASA.** `HIGH` en **36 de 150** = **24.0%** (mínimo 20 %).
  Llegan a HIGH 6 regímenes: `baseline`, `contrast_0.4`, `coverage_14`, `coverage_9`, `depth_250m`, `depth_400m`.
  No llega ninguno de: `contrast_0.2`, `coverage_6`, `depth_600m`, `depth_900m`, `noise_0.05`, `noise_0.15`, `span_1200m`, `span_800m`, `worst_ldm_like`.
* **G3 — PASA.** Ninguna corrida con `resolves_anywhere = False`
  ni con `is_floor_smear = True` supera LOW.

**=> GATE PASADO**

### La escala, recalibrada

Los tres niveles ya no son un adorno: separan. `HIGH` tiene PR-AUC mediana
1.000 y error máximo 164,9 m; `LOW` tiene PR-AUC mediana
0.035 y mediana de error 599,5 m. Entre el peor `HIGH` y la
línea de los 200 m queda un margen de **35 m**.

### Cuánto trabajo hizo el sello

**21 corridas** habrían salido `HIGH` sin él —eran su ÚNICO limitante— y de esas
**9 tienen error > 200 m**: son sobreconfianzas que el sello evitó, una a una.

* `noise_0.05` s314043: **1 337,6 m** de error, PR-AUC 0.435 — resolución 750.0/750.0 m, exceso de piso 0.938
* `contrast_0.2` s315052: **1 325,6 m** de error, PR-AUC 0.392 — resolución 750.0/750.0 m, exceso de piso 0.998
* `noise_0.05` s315052: **1 127,0 m** de error, PR-AUC 0.452 — resolución 750.0/750.0 m, exceso de piso 0.924
* `contrast_0.4` s314043: **753,6 m** de error, PR-AUC 0.558 — resolución 500.0/750.0 m, exceso de piso 0.755
* `contrast_0.2` s319088: **654,0 m** de error, PR-AUC 0.289 — resolución 750.0/750.0 m, exceso de piso 0.305
* `noise_0.05` s319088: **611,6 m** de error, PR-AUC 0.324 — resolución 750.0/750.0 m, exceso de piso 0.369
* `coverage_6` s313034: **556,9 m** de error, PR-AUC 0.371 — resolución 750.0/750.0 m, exceso de piso 0.948
* `baseline` s317070: **549,4 m** de error, PR-AUC 0.448 — resolución 250.0/750.0 m, exceso de piso 0.731

### Los dos límites que el plan mandó traer

**(a) `floor_mass_excess`: los dos umbrales, medidos sobre las 150.** El de la Fase 26 (1,0,
que DEGRADA a LOW) dispara en **67 de 150** y sigue con **0 falsos positivos por su propia
definición** —ninguna corrida con PR-AUC ≥ 0,90 lo dispara; el PR-AUC máximo entre las
disparadas es **0,716**—. La afirmación de la Fase 26 **se sostiene al doblar la muestra**; no
hay corrección que hacer.

El del sello (0,5, que NIEGA `HIGH`) supera el umbral en 94 corridas, y **su coste exacto es
una**: `coverage_14` s318079, PR-AUC 1,000 y 67,5 m de error, exceso 0,555 ⇒ sale MEDIUM en vez
de HIGH. Una corrida excelente degradada de 150. Ése es el precio del margen doble, y es del
lado correcto: pierde un HIGH merecido antes que conceder uno que no lo es.

**(b) las «resuelve algo» con PR-AUC bajo — CERRADO en esta muestra.** La Fase 26 declaró que
13 de 55 corridas cuyo examen resuelve algo tenían PR-AUC ≤ 0,186 y **no** se topaban a LOW.
Sobre estas 150 son **19**, y las **19 salen LOW**. Ninguna llega a MEDIUM, ninguna a `HIGH`.
Vienen de `depth_600m` (10), `depth_900m` (4), `contrast_0.2` (3) y `coverage_6` (2) — los
regímenes profundos que el hallazgo señalaba.

---

## 3b. ¿Y el dato de CAMPO? Las dos corridas reales del repositorio

El gate es sintético por diseño (necesita verdad conocida para medir el error). Pero la
pregunta que importa al producto es qué saca un survey real, así que se re-invirtieron por el
motor de producción las dos corridas canónicas de dato real que viven en el repositorio
(`project_id=None`, no pisan nada):

| | Laguna del Maule (Miller 2017) | San Nicolás (VMS, México) |
|---|---|---|
| estaciones | 191 | 256 (stride 4) |
| χ² reducido | 0,987 | 0,357 |
| `survey_confidence` / `model_reliability` | **HIGH** / **HIGH** | **HIGH** / **HIGH** |
| `survey_resolution` | **RESOLVES_NOTHING** | RESOLVES (300 m) |
| `is_floor_smear` | **sí** (exceso 1,075) | **sí** (exceso 1,609) |
| sello de HIGH | `NOT_MEASURABLE` | `NOT_SEALED` (300 m = el peldaño más grueso, **y** piso 1,609) |
| **veredicto** | **LOW** | **LOW** |

**Las dos salen LOW, y la Fase 30 no cambió eso: ya salían LOW.** Lo que las capa es
`best_target_floor_smear` (Fase 26), que esta fase no tocó. El dato interesante es **quién NO
las cazó**: `survey_confidence` y `model_reliability` —las señales que existían antes de la
Fase 26— dicen **HIGH** en las dos. Sin el trabajo de la 26, y con el techo levantado, ambas
habrían salido `HIGH`. Es la mejor evidencia disponible de que el orden que el hallazgo exigía
por escrito («primero que la señal informe, después subir el techo») no era retórica.

**Y el sello se estrena bien en dato real:** en San Nicolás falla las DOS pruebas y lo dice con
sus números — la banda más somera resuelve 300 m, que es exactamente el peldaño más grueso que
el examen probó (el suelo del examen), y el exceso de masa de piso es 1,609.

⚠️ **Observación abierta, que NO es de esta fase.** San Nicolás es un benchmark **aprobado**
contra campo real (techo del cuerpo a 125 m frente a 150–220 m publicados) y sale `LOW`. El
veredicto es más conservador que la validación externa. La causa es el umbral de
`is_floor_smear` (1,0) sobre una malla cuyo dominio es poco profundo, no nada que la Fase 30
haya introducido — pero merece dueño: un producto que llama «no confiable» a su propio
benchmark aprobado tiene algo que explicar.

---

## 4. Verificación por mutación

**12 de 12 cazadas**, y el fichero restaurado con hash idéntico (`ce8dff8420b0af00`).
Cada mutación es la versión defectuosa de una decisión de esta fase:

| # | mutación | ¿la caza la suite? |
|---|---|---|
| M1 | el sello acepta el peldaño **más grueso** (`<` → `<=`) | ✅ |
| M2 | el límite de masa de piso se afloja a 5,0 (inerte) | ✅ |
| M3 | la **ausencia** de datos concede HIGH (rompe la monotonía de la Fase 21) | ✅ |
| M4 | no sellar **degrada a LOW** en vez de topar a MEDIUM (acusa de más) | ✅ |
| M5 | `priority_class` vuelve a topear | ✅ |
| M6 | el techo vuelve a ser una **constante del producto** | ✅ |
| M7 | un `HIGH` publica limitantes (la rama nueva del worst-of, sin guarda) | ✅ |
| M8 | el sello ignora la masa de piso (media prueba) | ✅ |
| M9 | el sello ignora la resolución (la otra media prueba) | ✅ |
| M10 | el nivel degradado de `priority_class` se publica en blanco (degradar = silenciar) | ✅ |
| M11 | el techo AFIRMA que el sello se cumplió sin comprobarlo (la rama LOW) | ✅ |
| M12 | el techo no nombra `high_seal` primero en `capped_by` | ✅ |

**M11 no es hipotética: era un defecto real de esta fase, escrito y corregido.** La primera
versión de `_verdict_ceiling` decidía el texto por «¿está `high_seal` en `capped_by`?». Cuando
algo baja el veredicto por debajo de MEDIUM, `capped_by` sólo trae las señales de ESE nivel,
así que el sello podía haber fallado y no aparecer — y la rama `else` afirmaba «el sello de
resolución y de masa de piso ya está superado». Mentía justo en la corrida peor. Hoy la rama
pregunta por `sealed is True` y hay una tercera rama para el caso mixto.

---

## 4b. Efecto colateral declarado: el presupuesto AST se actualizó

`scripts/ci/ast_budgets.py` falló con `services.loc 31168 > 31114` (techo = +5 % sobre la
línea base). El procedimiento que el propio script indica es `--update` + explicar. Se hizo,
y hay que decir **exactamente qué absorbió**, porque no es sólo esta fase:

| paquete | línea base (Fase 16) | hoy | delta |
|---|---:|---:|---:|
| `services` | 29.632 | 31.168 | **+1.536** (de los cuales la Fase 30 aporta **+171**) |
| `exploration` | 11.693 | 11.754 | +61 |
| `reporting` | 1.771 | 1.848 | +77 |
| `api` | 6.854 | 6.862 | +8 |

La línea base no se tocaba desde el commit `84521e4` (**Fase 16**). La Fase 30 no es la que
engordó `services`: es la que **agotó la pista**, y al actualizar absorbe trece fases de
crecimiento ajeno. Lo que **no** se oculta: `cc_max` de `services` sigue en **181**
(`gravity_import_service.py:942`) y `args_max` en **36**, ambos sin cambio. `func_loc_max`
pasa de 777 a 812 y cambia de dueño — el máximo es ahora `joint_inversion.py:548
run_joint_inversion`, que ya lo era antes de esta fase y pasaba por estar dentro del +5 %.

---

## 5. Erratas y defectos NUEVOS que esta fase destapó y NO arregla

1. **NUEVO-15 — `favorability.anomaly_intensity` está invertido.** Da **0,000** a la mejor
   corrida del barrido (`depth_250m`, PR-AUC 1,000, error 11,3 m) y **1,000** a la peor
   (`worst_ldm_like`, PR-AUC 0,002, error 1.186 m). Pesa 0,25 de 0,95.
   `structural_gradient` (0,000–0,066) y `msx_support` (0,067–0,083) son casi **constantes** y
   pesan otro 0,25 juntos: tres de los cinco factores evaluados no discriminan. No se toca
   aquí porque cambiar el veredicto y la favorabilidad a la vez impediría atribuir el
   resultado del gate. **Sin dueño.**

2. **NUEVO-16 — la Regla 3 de `compute_priority_class_from_report` es código muerto.**
   Lee `fav.get("quality_label")`, y `compute_favorability_score` **no devuelve** esa clave
   (devuelve `version, score, level, not_mineral_confirmation, disclaimer, factors, gates,
   scoring_detail, warnings, computed_at`; la etiqueta vive en `gates.quality_gate.label`).
   La regla «calidad BAJA/INSUFICIENTE ⇒ máximo LOW_RELATIVE_PRIORITY» **nunca se ha
   ejecutado**. Se declara, no se arregla: activarla cambiaría `priority_class` en el mismo
   commit en que se le retira el poder de topear.

3. **NUEVO-17 — el veredicto llama `LOW` a un benchmark APROBADO.** San Nicolás, validado
   contra campo real (techo del cuerpo a 125 m frente a 150–220 m publicados), sale `LOW`
   por `is_floor_smear` (exceso 1,609). Laguna del Maule igual (1,075). No es un defecto que
   introduzca esta fase —el umbral 1,0 y su cap a LOW son de la Fase 26, y ambas salían LOW
   antes— pero queda **medido y sin dueño**: un producto cuyo argumento es la honestidad no
   puede llamar «no confiable como base única» a su propio benchmark aprobado sin explicar
   la discrepancia. Ver §3b.

4. **ERRATA del barrido — son 14 casos distintos, no 15.** `baseline` y `depth_400m` son el
   **mismo mundo con distinto id** (misma esfera de 150 m a 400 m, mismo contraste 0,6, misma
   campaña por defecto) y devuelven resultados idénticos bit a bit con la misma semilla —
   comprobado en las filas 1-10 y 21-30 del gate. Afecta también al conteo de la Fase 26: sus
   «75 corridas / 15 regímenes» son **75 filas sobre 14 casos**, con uno duplicado. No
   invalida ρ = +0,8081 (las filas duplicadas son idénticas, no contradictorias), pero el
   régimen `baseline`/`depth_400m` pesa el doble que los demás y hay que decirlo.

---

## 6. Lo que esta fase NO hace

* **No toca el frontend** (NUEVO-10, abierto desde la Fase 26). Medido, para que la deuda
  quede con coordenada y no como una generalidad:
  - `HonestReportWidgets.tsx:34` tiene un mapa `LIMITING_LABELS` con cinco entradas y
    **ninguna es `high_seal`**, ni `survey_resolution`, ni `best_target_floor_smear`; el
    componente cae al `code` crudo (`limitingLabel`, línea 42), así que la UI mostrará el
    literal **`high_seal`** sin explicación — la misma familia de defecto que antes mostraba
    `high_hold_pending_fase30`.
  - `HonestReportWidgets.tsx:93` sigue pintando `priority_class` dentro del panel del
    veredicto **sin decir que ya no topea**. Es la lectura más peligrosa que deja esta fase:
    un campo que parece limitar y no limita.
  - Lo bueno que llega solo: en una corrida `HIGH` el widget mostrará «Factor limitante: —»,
    porque `limiting_factors` va vacío. Eso ya es correcto sin tocar nada.
  La regla del proyecto prohíbe tocar backend y frontend en la misma fase.
* **No arregla `favorability`** (NUEVO-15/16 arriba).
* **No cambia nada para magnetometría ni para la conjunta.** `run_resolution_profile_qa` se
  invoca dentro de la ruta gravimétrica (`geophysics_service.py:5050`, sobre `kernel_sparse`
  y `datos.g_observed`), así que en una corrida magnética o conjunta no hay `resolution_qa` y
  el sello sale `NOT_MEASURABLE` ⇒ cap a MEDIUM. Es **el mismo techo que ya tenían** (se lo
  ponía la retención), y por una razón defendible: no se puede sellar la resolución de una
  modalidad que no se examinó. Extender el perfil a magnetometría es trabajo con dueño
  propio, no un efecto colateral de esta fase.
* **No resuelve la bimodalidad.** Sigue siendo cierto que dentro de un mismo régimen unas
  realizaciones de ruido se desvían cientos de metros. Lo que cambia es que ahora hay un
  criterio POSITIVO que se les niega, en vez de un techo que se le niega a todos.
* **No toca la profundidad.** `depth_confidence` sigue en LOW por defecto y con razón.
