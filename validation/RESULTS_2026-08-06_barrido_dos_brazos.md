# Barrido de regímenes — 2 brazos de `density_min` · 2026-08-06

**Versión de TQ medida:** `adba2b8+dirty` · **150 inversiones** (15 regímenes × 5 semillas × 2 brazos)
· **149,5 min** (60 s/inversión) · **0 errores** · malla 18×14×18 @ 125 m · config de producción
(Morozov con σ declarado) · datos generados con `choclo` (anti-inverse-crime).

Datos crudos: `%LOCALAPPDATA%\TerraQuantum\validation_results\adba2b8+dirty\sweep_regimes.json`

---

## 1. Resultado principal: `s_strict_L2` domina en los 15 regímenes

| régimen | eje | PR-AUC **strict** | PR-AUC **permissive** | horiz. strict (m) | prof. strict (m) |
|---|---|---:|---:|---:|---:|
| depth_250m | profundidad | **0,946** ± 0,121 | 0,075 | 25,7 ± 31,0 | 28,5 ± 20,4 |
| coverage_14 | cobertura | **0,943** ± 0,127 | 0,036 | 42,5 ± 31,3 | 102,7 ± 35,9 |
| baseline / depth_400m | baseline | **0,858** ± 0,200 | 0,037 | 105,4 ± 132,0 | 160,9 ± 115,7 |
| coverage_9 | cobertura | **0,748** ± 0,262 | 0,033 | 142,7 ± 152,0 | 199,5 ± 124,7 |
| contrast_0.4 | contraste | **0,675** ± 0,340 | 0,035 | 255,5 ± 296,9 | 285,7 ± 266,6 |
| noise_0.05 | SNR | **0,463** ± 0,252 | 0,022 | 534,1 ± 502,7 | 465,9 ± 479,8 |
| contrast_0.2 | contraste | **0,378** ± 0,231 | 0,022 | 658,8 ± 503,6 | 501,8 ± 491,0 |
| coverage_6 | cobertura | **0,285** ± 0,141 | 0,027 | 767,7 ± 300,9 | 1022,8 ± 368,3 |
| depth_600m | profundidad | **0,097** ± 0,021 | 0,013 | 669,3 ± 326,6 | 1018,1 ± 109,6 |
| noise_0.15 | SNR | **0,057** ± 0,079 | 0,007 | 959,8 ± 126,3 | 834,1 ± 552,6 |
| span_1200m | extensión | **0,039** ± 0,002 | 0,007 | 903,7 ± 699,2 | 1287,0 ± 1,2 |
| span_800m | extensión | **0,027** ± 0,005 | 0,003 | 386,6 ± 368,9 | 1025,5 ± 22,5 |
| depth_900m | profundidad | 0,003 | 0,003 | 341,8 ± 161,5 | 710,9 ± 14,2 |
| worst_ldm_like | compuesto | 0,003 | 0,002 | 663,0 ± 180,7 | 510,3 ± 282,1 |

**Predicción refutada.** Antes del barrido escribí que esperaba un empate por régimen: el brazo
permisivo mejor donde la malla resuelve bien el cuerpo, el estricto donde no. **La medición dice
que no.** En esta malla el brazo permisivo hunde la masa al fondo del dominio en los 15 regímenes
(profundidad recuperada 1250 m ≈ base del dominio, PR-AUC entre 0,002 y 0,075) — no es peor,
es inservible.

**Alcance honesto del resultado.** Este barrido cubre **una sola malla** (125 m). La única medición
donde el brazo permisivo ganó (w001: 2,3 m, PR-AUC 0,96 contra 9,8 m / 0,48 del estricto) fue en
malla de **50 m**, que este barrido no toca. La resolución de malla queda como el eje no medido:
la afirmación defendible es *"en malla de 125 m, `density_min = fondo` domina"*, no
*"`density_min` permisivo es incorrecto"*.

---

## 2. El error de centroide habría elegido el brazo equivocado

En **4 de los 15 regímenes** el brazo permisivo tiene **mejor** error horizontal y a la vez
un PR-AUC 10× peor:

| régimen | horiz. permissive | horiz. strict | PR-AUC permissive | PR-AUC strict |
|---|---:|---:|---:|---:|
| coverage_6 | **97,1** | 767,7 | 0,027 | **0,285** |
| contrast_0.2 | **321,5** | 658,8 | 0,022 | **0,378** |
| noise_0.05 | **278,2** | 534,1 | 0,022 | **0,463** |
| noise_0.15 | **747,9** | 959,8 | 0,007 | **0,057** |

**Causa.** El centroide de una masa untada por todo el dominio cae cerca del centro del dominio.
Si el cuerpo verdadero también está cerca del centro, el error de centroide sale pequeño **por
accidente geométrico**, no por acierto. La métrica independiente de umbral no se deja engañar
porque mide la forma completa del ranking, no un punto resumen.

Es la justificación empírica de P4 del framework, y no es teórica: la validación previa del
proyecto usaba error de centroide como métrica principal.

---

## 3. Acantilado de profundidad entre 400 y 600 m

Brazo estricto, mismo cuerpo, sólo cambia la profundidad:

```
250 m  →  PR-AUC 0,946   prof. 28,5 m      recuperación limpia
400 m  →  PR-AUC 0,858   prof. 160,9 m     buena, pero sigma 115 m
600 m  →  PR-AUC 0,097   prof. 1018,1 m    COLAPSO
900 m  →  PR-AUC 0,003   prof. 710,9 m     muerto
```

Esto **reproduce de forma independiente** lo que `docs/05` midió con otro harness y otro
generador de datos: *"Morozov rescata moderado (150–300 m), no profundo (600 frágil, 900 falla)"*.
El framework no fue ajustado para reproducirlo — llegó al mismo sitio por su cuenta, con datos
generados por un forward de terceros.

Nótese además que a 900 m el error **horizontal** (341,8 m) es *mejor* que a 600 m (669,3 m)
mientras el PR-AUC cae de 0,097 a 0,003. Segundo caso del mismo espejismo de la §2.

---

## 4. La distribución no es ancha: es BIMODAL. Y eso cambia la lectura

La media ± σ del §1 dice "muy variable". La mediana dice otra cosa, y es más útil:

| régimen | media ± σ (horiz.) | **mediana** | PR-AUC medio | **PR-AUC mediano** |
|---|---:|---:|---:|---:|
| baseline / depth_400m | 105,4 ± 132,0 | **18,2 m** | 0,858 | **1,000** |
| depth_250m | 25,7 ± 31,0 | **11,3 m** | 0,946 | **1,000** |
| coverage_14 | 42,5 ± 31,3 | **53,4 m** | 0,943 | **1,000** |
| coverage_9 | 142,7 ± 152,0 | **95,2 m** | 0,748 | **0,716** |
| contrast_0.4 | 255,5 ± 296,9 | **111,6 m** | 0,675 | **0,716** |

Valores por semilla en `baseline`:

```
semilla   11    →   5,6 m   PR-AUC 1,000
semilla  202    →  18,2 m   PR-AUC 1,000
semilla 40004   →   9,9 m   PR-AUC 1,000
semilla 20260805→ 208,0 m   PR-AUC 0,704     <- se desploma
semilla 3003    → 285,5 m   PR-AUC 0,583     <- se desploma
```

**No es ruido alrededor de un valor central: son dos poblaciones.** Tres semillas recuperan el
cuerpo con ranking PERFECTO y error de una decena de metros; dos se caen. Reportar 105 ± 132 m
describe mal ese comportamiento — sugiere una nube ancha donde hay un interruptor.

### La semilla 3003 es la peor en 6 de 6 regímenes examinados

```
baseline 285,5 | depth_250m 80,5 | coverage_14 53,4 | contrast_0.4 718,2 | noise_0.05 1281,3 | coverage_9 95,2
```

Que la misma semilla sea la peor en todos los regímenes **no es coincidencia**: las campañas
comparten el arranque del flujo aleatorio, así que la realización de ruido adversa se repite.
Consecuencia metodológica incómoda: **5 semillas dan menos independencia de la que aparentan**.
El σ del §1 mide en parte una realización repetida, no cinco muestras independientes.

**Pendiente derivado:** descorrelacionar las semillas entre regímenes (derivar la semilla del par
régimen×semilla, no de la semilla sola) y volver a medir el σ. Hasta entonces, la mediana es el
estadístico defendible y el σ debe leerse como cota superior optimista.

### Verificado con 24 semillas frescas: la bimodalidad es real

`exp_bimodal.py` repitió `baseline` con **24 semillas nuevas** sin solape con este barrido,
geometría de survey fija, cambiando sólo la realización de ruido:

**Tasa de caída (PR-AUC < 0,90) = 8/24 = 33 %**, IC 95 % de Wilson **18 – 53 %**.
Horizontal: mediana **18,5 m** en las buenas, **168,8 m** en las caídas.
λ = 0,31623 en las 24. Y `(confianza, conf. profundidad, null-space)` = `('MEDIUM','LOW',False)`
en **las 24** — una sola combinación para los dos desenlaces.

No era artefacto de las 5 semillas correlacionadas: el fenómeno es del sistema, no del harness.
Análisis completo de la causa en
[`HALLAZGO_2026-08-06_techo_medium.md`](HALLAZGO_2026-08-06_techo_medium.md).

---

## 5. Matriz de honestidad — resultado real y su límite

| cuadrante | n | lectura |
|---|---:|---|
| SOBRECONFIADO (error grande + confianza alta) | **0** / 150 | ningún caso |
| CONSERVADOR | 8 | |
| CALIBRADO | 142 | **bolsa residual, no evidencia de calibración** |

**El "0 sobreconfiado" es más débil de lo que parece, y hay que decirlo.**
[MEDIDO] En las 150 corridas **TerraQuantum nunca declaró confianza `HIGH`**: 103 `MEDIUM`,
47 `LOW`. Es imposible caer en el cuadrante sobreconfiado si nunca se afirma confianza alta.

Lo que **sí** carga información, medido en el brazo estricto:

| confianza declarada | n | PR-AUC medio | rango |
|---|---:|---:|---|
| MEDIUM | 60 | 0,514 | 0,003 – 1,000 |
| LOW | 15 | 0,069 | 0,002 – 0,729 |

Separa **en promedio** (0,514 vs 0,069) pero es **inútil caso a caso**: un `MEDIUM` puede ser una
recuperación perfecta o una muerta. Y el tope de su propia escala no se usa nunca.

**Consecuencia de producto, no del framework:** hoy el sistema no tiene forma de decirle al usuario
*"esta corrida sí es fiable"*. Sólo sabe decir *"regular"* o *"mala"*.

---

## 6. Umbrales re-anclados a medición

`validation/acceptance_measured.py` — **generado, no escrito a mano** — sustituye los umbrales
anclados a benchmarks externos por umbrales derivados de estas 75 corridas del brazo estricto.

Regla declarada: error → peor semilla × 1,25 · PR-AUC → mínimo × 0,75. El margen de 25 % absorbe
ruido de semilla; con n=5 el extremo observado no es el extremo poblacional.

**7 de 15 regímenes recuperan de verdad** (PR-AUC mediano ≥ 0,30): `baseline`, `depth_250m`,
`depth_400m`, `coverage_14`, `coverage_9`, `contrast_0.4`, `noise_0.05`. Los otros 8 llevan
`RECUPERA = False` y su umbral **detecta cambios pero no certifica calidad** — usarlos como
prueba de que el sistema funciona sería deshonesto, y el módulo lo dice en su propio docstring.

`for_regime()` lanza `KeyError` explícito para un régimen no medido, en vez de devolver un
umbral por defecto. No se gatea contra un número inventado (P3).

**Limitación declarada.** `Acceptance` se evalúa sobre **una** corrida, así que el umbral debe dar
cabida a la peor semilla — y con distribución bimodal eso lo deja flojo (`baseline` ≤ 360 m cuando
la mediana es 18 m). Sólo caza regresiones catastróficas. El gate afilado es la mediana sobre N
semillas: se publica en `MEDIANS`, pero **el contrato todavía no sabe evaluar aceptación de nivel
agregado**. Es el siguiente trabajo, no un descuido.

---

## 7. Corrección: la "brecha sin explicar" era en buena parte la media

En el reporte preliminar escribí que el framework medía ~105–208 m en baseline donde
`error_budget.py` medía 14 m, y lo dejé como brecha abierta atribuible al padding de producción.

**Con la mediana, la brecha se encoge de 105 m a 18,2 m** — comparable a los 14 m del harness
antiguo. Lo que había era una media arrastrada por dos semillas que se desploman, no un sesgo
sistemático de la ruta de producción.

Lo que **sigue abierto** y es más interesante que la brecha original: por qué esas dos semillas
se desploman. Un modo de fallo que aparece en el 40 % de las realizaciones de ruido, en el
régimen donde el producto declara su fortaleza, importa más que un desplazamiento de 4 m en la
mediana. La hipótesis del padding (H-38) no queda refutada, pero deja de ser necesaria para
explicar los números.

---

## 8. Pendientes

1. **Descorrelacionar las semillas** entre regímenes y volver a medir σ (§4).
2. **Diagnosticar el modo de fallo bimodal**: qué distingue a las semillas 3003 y 20260805.
3. **Aceptación de nivel agregado** en el contrato, para poder gatear sobre la mediana (§6).
4. **Eje no medido:** resolución de malla. Único candidato vivo para que el brazo permisivo
   tenga sentido en algún régimen.
