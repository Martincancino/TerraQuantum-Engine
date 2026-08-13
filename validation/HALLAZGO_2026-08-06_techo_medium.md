# Hallazgo — El veredicto de TerraQuantum tiene un techo estructural en `MEDIUM`

**Fecha:** 2026-08-06 · **Versión medida:** `adba2b8+dirty` · **Método:** 99 inversiones por la
ruta de producción (75 del barrido + 24 del experimento bimodal), datos anti-inverse-crime.

> **Dos hallazgos, uno dentro del otro.** (1) En el régimen donde el producto declara su
> fortaleza, **una de cada tres realizaciones de ruido** produce un blanco desplazado ~170 m
> en vez de ~19 m. (2) TerraQuantum **no puede distinguir esos dos casos**, y además **no
> puede declarar confianza alta en ningún caso** — por un motivo concreto y localizado en el
> código.

---

## Resumen en tres frases

TerraQuantum **nunca declaró confianza `HIGH`** en ninguna de las corridas medidas. No es
prudencia del modelo ante casos difíciles: es que un QA de resolución que **no depende del dato
observado** devuelve `FAIL` siempre, y el veredicto reconciliado (B3) lo usa como tope duro.
El resultado es que el nivel más alto de la escala del producto **es inalcanzable por
construcción** para cualquier survey gravimétrico realista.

---

## 1. Los hechos, en orden

### [MEDIDO] La confianza nunca llega a HIGH

99 corridas por `run_geophysics_inversion`: **0 `HIGH`**. En el barrido de 75:
103 `MEDIUM` / 47 `LOW` contando ambos brazos; 60 `MEDIUM` / 15 `LOW` en el estricto.
`depth_confidence` fue `LOW` en **75 de 75**.

Esto vacía el criterio de honestidad que el propio framework se había puesto: el cuadrante
SOBRECONFIADO (error grande + confianza alta) salió **0 de 150**, pero *no se puede ser
sobreconfiado si nunca se declara confianza alta*. El "0" no medía honestidad; medía un techo.

### [MEDIDO] El diagnóstico de ajuste no predice el acierto

Spearman entre `chi2_red` y PR-AUC sobre las 75 corridas del brazo estricto: **+0,073**.
Controlando por régimen, la **mediana de ρ es exactamente 0,000**, con signos que van de
−0,707 a +0,500 sin patrón.

El caso más claro es `baseline` — mismo mundo, mismo survey, misma configuración, **mismo
λ = 0,31623**, y sólo cambia la realización de ruido:

| semilla | PR-AUC | horizontal | χ² | misfit % | confianza | conf. prof. | null-space |
|---|---:|---:|---:|---:|---|---|---|
| 11 | 1,000 | 5,6 m | 1,243 | 20,27 | MEDIUM | LOW | False |
| 202 | 1,000 | 18,2 m | 1,411 | 21,78 | MEDIUM | LOW | False |
| 40004 | 1,000 | 9,9 m | 1,197 | 20,24 | MEDIUM | LOW | False |
| 20260805 | 0,704 | **208,0 m** | 1,349 | 21,41 | MEDIUM | LOW | False |
| 3003 | 0,583 | **285,5 m** | 1,268 | 20,76 | MEDIUM | LOW | False |

**El error varía 51×. El χ² varía 16 %. Los tres campos de honestidad no varían nada.**

### [MEDIDO] Confirmado con 24 semillas frescas e independientes

El patrón anterior salía de 5 semillas que además resultaron estar correlacionadas entre
regímenes. `exp_bimodal.py` lo repite con **24 semillas nuevas**, sin solape con el barrido,
sobre `baseline` con la geometría de survey FIJA — lo único que cambia es la realización de
ruido de 0,02 mGal:

| | |
|---|---|
| **Tasa de caída** (PR-AUC < 0,90) | **8 de 24 = 33 %** · IC 95 % (Wilson) **18 % – 53 %** |
| horizontal, corridas buenas | mediana **18,5 m** |
| horizontal, corridas caídas | mediana **168,8 m** (rango global 6,8 – 327,1 m, factor 48×) |
| λ elegido por Morozov | **0,31623 en las 24** — un solo valor |
| (confianza, conf. profundidad, null-space) | **`('MEDIUM','LOW',False)` en las 24** — una sola combinación |

**Una de cada tres corridas devuelve un blanco desplazado ~170 m en vez de ~19 m, y el
producto declara exactamente lo mismo en los dos casos.** En targeting de perforación esa
diferencia es acertar o no acertar.

Sobre el poder discriminante de lo que sí se calcula, en estas 24:

- `chi2_red`: ρ = **−0,232** (no significativo con n=24), y los rangos se solapan por completo
  — buenas 1,129–1,499, caídas 1,167–1,522.
- `misfit_pct`: ρ = **−0,400**, débil y en la dirección intuitiva (peor ajuste → peor
  recuperación). Es la única señal con algo de información, y **no está expuesta como
  veredicto de calidad**.

Ninguna de las dos separa una corrida de 18 m de una de 169 m.

**Alcance:** la tasa del 33 % vale para *esta* configuración —esfera r=150 m a 400 m,
contraste +0,6, malla 125 m, 12×12 estaciones sobre 1500 m, ruido 0,02 mGal—. No es "TQ falla
un tercio de las veces" en general; es "en el régimen que el producto declara como su
fortaleza, un tercio de las realizaciones de ruido cambian materialmente el resultado".

### [MEDIDO] El detector de null-space nunca dispara

`is_null_space_artifact = False` en **75 de 75**, incluidos los 15 casos con PR-AUC ≤ 0,01
(`depth_900m`, `worst_ldm_like`, `span_*`), donde el modelo recuperado *es* smear de null-space.
Verificado que no es un fallo de lectura del harness: la clave existe en `best_target` del
backend (`reporting/report_generator.py:617`, `api/chat_api.py:312`) y el runner la lee bien —
en las mismas corridas sí extrae `confidence_level` y `depth_confidence` con valores reales.
Su condición de disparo, según sus propios tests (`test_b1_best_target_nullspace.py:93`), es
la saturación total en el piso: **mucho más estrecha de lo que el nombre sugiere al usuario**.

### [MEDIDO] El QA de checkerboard devuelve el mismo número siempre

`pearson_r = 0.1162`, **idéntico a cuatro decimales en las 9 corridas revisadas del
experimento**, y `status = FAIL` en todas. En el probe de honestidad de una sesión anterior
(`scripts/validation/honesty_test_report.json`) el valor es `0.1178` en **las 5 filas**, que
van de un cuerpo recuperado a 150 m a uno fallado a 900 m.

### [VERIFICADO EN CÓDIGO] Y es constante por diseño, no por avería

`_run_checkerboard_qa_fast` (`services/geophysics_service.py:1646`) recibe
`kernel_sparse_core`, `nx/ny/nz` y `lambda_mag`. **No recibe el dato observado.** Sintetiza un
checkerboard, lo propaga con el mismo kernel y lo invierte con LSQR. Para una geometría de
survey y una malla dadas, su salida es determinista.

Eso está bien como diagnóstico: pregunta *"¿puede este survey resolver estructura fina?"*, y
esa pregunta genuinamente no depende de qué haya enterrado. El problema es **qué estructura
usa como prueba**: `build_checkerboard_model` (`exploration/checkerboard_test.py:61`) alterna
el signo **celda a celda** (`(ix+iy+iz) % 2`). En una malla de 125 m eso es un patrón de 250 m
de longitud de onda que además alterna en profundidad — **por debajo del límite físico de
resolución de un campo potencial, a cualquier profundidad**.

Es un examen que ningún survey gravimétrico puede aprobar. `pearson_r ≈ 0,12` frente a un
umbral de PASS de 0,60 no es un diagnóstico de este survey: es el resultado esperado del
examen.

### [VERIFICADO EN CÓDIGO] Y ese FAIL es un tope duro sobre el veredicto

`geophysics_service.py:877-881`:

```python
cb_status = str(cb.get("status", "")).upper()
components["checkerboard_qa"] = cb_status or "NOT_RUN"
if cb_status == "FAIL":
    levels.append(("MEDIUM", "checkerboard_resolution"))
```

B3 toma el **worst-of** de todas las señales. Con `checkerboard_qa = FAIL` presente siempre,
`MEDIUM` entra siempre en la lista, y `HIGH` **no puede sobrevivir nunca**.

Coherente con lo observado: en el reporte de honestidad previo, `overall_limiting` incluye
`checkerboard_resolution` en **las 5 filas**, tanto en los casos recuperados como en los fallidos.

---

## 2. Qué está bien y qué está mal aquí

**Bien — y conviene decirlo:** el diseño de B3 es correcto. Worst-of, downgrade-only, con los
componentes expuestos para auditoría. Es exactamente cómo debe reconciliarse un veredicto:
sin inventar métrica nueva y sin dejar que la señal optimista tape a la pesimista. El
mecanismo no es el problema.

**Mal:** una de sus entradas está pegada. Y por ser worst-of, **una sola entrada pegada en
`FAIL` determina la salida del sistema entero**. Ésa es la propiedad incómoda del worst-of:
es robusto frente a señales demasiado optimistas y **frágil frente a una señal
constantemente pesimista**.

**Consecuencia de producto.** El usuario nunca ve el nivel superior de la escala. Y como el
techo se aplica igual a la corrida de 5,6 m de error que a la de 285,5 m, **la escala de
confianza no distingue el caso bueno del malo en el régimen donde el producto declara su
fortaleza**. Lo que el reporte comunica no es "confianza media": es "no tengo forma de decirte".

---

## 3. Relación con el trabajo previo (C2)

Una sesión anterior ya había detectado el síntoma —`honesty_test.py` lo dice en su docstring:
*"el checkerboard_qa=FAIL NO propaga a la confianza"*— y el commit `adba2b8` desacopló
`depth_confidence` del horizontal en el reporte y la UI.

Esta medición **se hizo sobre `adba2b8`**, es decir, después de ese arreglo. Aporta tres cosas
que el probe anterior no tenía:

1. **Escala**: 99 corridas contra 5, en 15 regímenes, con métricas independientes del umbral.
2. **Cuantificación**: ρ(χ², PR-AUC) mediano = 0,000 — no "parece que no discrimina", sino
   *cuánto* no discrimina.
3. **La causa raíz en el código**: no es que el FAIL no propague — **sí propaga**, y por eso
   nadie puede llegar a HIGH. El problema está un nivel más abajo, en que el examen que
   produce ese FAIL es infalible por construcción.

El arreglo de C2 mejoró **qué se muestra**. No cambió **cuánta información lleva la señal**.
Es el tipo de mejora que un framework de validación existe para distinguir.

---

## 4. Direcciones de arreglo (no implementadas — requieren decisión)

Ninguna se toca sin medir antes; van en orden de coste.

1. **Recalibrar el umbral del checkerboard** contra lo que un buen survey gravimétrico
   *realmente* alcanza. Si el mejor caso posible da 0,3, un PASS en 0,6 no clasifica: rechaza.
2. **Cambiar la longitud de onda del examen**: en vez de alternar celda a celda, usar bloques
   del tamaño del objetivo declarado. Eso convierte la pregunta en *"¿resuelve este survey un
   cuerpo del tamaño que digo buscar?"*, que sí es accionable y sí varía entre surveys.
3. **Separar "resolución de estructura fina" de "confianza en el blanco"**: hoy una limita a la
   otra. El targeting horizontal puede ser bueno con resolución fina pobre — el propio
   comentario del código (`geophysics_service.py:874-876`) lo reconoce, y aun así aplica el cap.
4. **Hacer informativo el detector de null-space** para el caso frecuente (smear profundo
   data-consistente), no sólo para la saturación total.

**Advertencia sobre 1 y 2:** subir el techo a `HIGH` sin arreglar antes lo del §1 sería peor
que el estado actual. Hoy el sistema no distingue bien de mal pero tampoco afirma de más. Si
se libera el techo sin que la señal discrimine, aparecerían `HIGH` en corridas de 285 m de
error — el cuadrante SOBRECONFIADO, que es el único inaceptable. **El orden correcto es:
primero que la señal informe, después subir el techo.**

---

## 5. Reproducir

```bash
python -m validation.exp_bimodal --seeds 24     # baseline, solo cambia el ruido
```

Datos crudos en `%LOCALAPPDATA%\TerraQuantum\validation_results\adba2b8+dirty\`.
Scripts de análisis en el scratchpad de la sesión: `diag_bimodal.py`,
`diag_diagnostics_informative.py`.
