# Hallazgo — El examen de resolución era imposible por TRES motivos, y la longitud de onda era el menor

**Fecha:** 2026-09-03 · **Versión medida:** `768cfaa` (+ los cambios de esta fase) ·
**Método:** 74 inversiones capturadas por la ruta de producción (15 regímenes × 5 semillas,
brazo `s_strict_L2`, conjunto de SELECCIÓN) + **75 de CONFIRMACIÓN** con semillas frescas · **Cierra:** la mitad
«entre surveys» de [`HALLAZGO_2026-08-06_techo_medium.md`](HALLAZGO_2026-08-06_techo_medium.md)

> **Lo que el hallazgo anterior suponía y lo que resultó ser.** El hallazgo de agosto
> localizó la causa del techo en la **longitud de onda** del tablero: alterna signo celda
> a celda, y en malla de 125 m eso es un patrón de 250 m, por debajo del límite físico de
> un campo potencial. Es cierto. Pero al medirlo contra el código resultaron ser **tres
> causas independientes**, y la longitud de onda es **la menor de las tres**: corregirla
> sola habría subido `pearson_r` de 0,116 a 0,247 — todavía muy lejos del PASS de 0,60.
> **El trabajo que el plan pedía habría sido insuficiente, no decorativo, pero
> insuficiente.**

---

## 0. Reproducir

```bash
python -m validation.exp_resolution --set selection   # las 5 semillas del barrido
python -m validation.exp_resolution --set confirm     # 5 semillas frescas -> EL GATE
python -m pytest tests/test_f26_resolution_qa.py -q   # 22 tests, incl. 5 mutaciones
```

---

## 1. Las tres causas, medidas

### [MEDIDO] Causa 1 — la longitud de onda (la que el hallazgo ya conocía)

`build_checkerboard_model` alterna el signo celda a celda (`(ix+iy+iz) % 2`). Reproducido
sobre el kernel de producción de `baseline`: **`pearson_r` = 0,116**, idéntico al 0,1162
publicado en agosto. Agrandando el bloque:

| bloque | 1 celda (hoy) | 2 celdas | 3 celdas | 4 celdas |
|---|---:|---:|---:|---:|
| `pearson_r` | **0,116** | 0,212 | 0,192 | 0,247 |

**Cambiar sólo la longitud de onda no acerca el examen al PASS de 0,60.**

### [MEDIDO] Causa 2 — puntúa profundidades que ningún survey gravimétrico resuelve

El Pearson se calcula sobre la malla **entera**, incluidas las capas profundas donde la
recuperación es ~0 para cualquier survey. Un survey perfecto tampoco aprobaría.

Mismo kernel, misma λ, mismo tablero — cambiando sólo **dónde se puntúa** (r dentro de la
banda, bloques laterales de L metros, `baseline`):

| banda (m) | L=125 | L=250 | L=375 | L=500 | L=750 |
|---|---:|---:|---:|---:|---:|
| 0 – 250 | 0,318 | 0,567 | 0,498 | 0,605 | **0,704** |
| 250 – 500 | 0,001 | −0,009 | 0,188 | 0,467 | **0,765** |
| 500 – 750 | 0,002 | −0,026 | 0,013 | 0,050 | 0,241 |
| 750 – 1000 | 0,005 | −0,026 | 0,020 | −0,005 | −0,197 |

El mismo survey que «suspende con 0,116» **aprueba con 0,70–0,77** en cuanto se le
pregunta por una escala y una profundidad concretas. El examen viejo no medía este
survey: medía el promedio entre lo resoluble y lo que nunca lo será.

### [MEDIDO] Causa 3 — califica a un solver distinto del que produce el modelo

`_run_checkerboard_qa_fast` invierte con `lsqr(damp=λ)` sobre el kernel **Core**: sin
padding, sin bounds, sin depth-weighting, sin suavidad. Nada de lo que hace el modelo que
el usuario ve.

Medido sobre `baseline`, **17 semillas**, con el MISMO dato observado:

| | ruta de producción | el solver del QA |
|---|---:|---:|
| PR-AUC | 0,583 – 1,000 | **0,039 – 0,041** |
| centroide en profundidad | ~466 m | **~85 m** |
| error horizontal | 5,6 – 285,5 m | 0,8 – 27,4 m |

Aunque el examen aprobara, **no describiría al modelo que se está mostrando**. Y explica
un fracaso de esta sesión: la idea de usar ese solver barato como proxy para detectar la
bimodalidad **no funciona** — el desplome de 1 de cada 3 realizaciones **no se reproduce**
en él (17 de 17 semillas entre 0,8 y 27,4 m). El desplome lo produce el solver regularizado
y acotado de producción, no la mala condición del kernel.

---

## 2. El examen nuevo

Un **perfil de resolución**: por cada banda de profundidad y cada tamaño de bloque lateral
de una escalera declarada, se sintetiza un tablero que alterna en (x, z) dentro de la
banda, se propaga con el MISMO kernel, se le suma ruido al **σ declarado**, y se puntúa la
correlación del **mapa en planta**. De ahí sale, por banda, la **longitud de resolución**:
el bloque más pequeño que se recupera con r ≥ 0,60. Un número en **metros** que el usuario
compara con el tamaño del cuerpo que busca.

Tres decisiones, cada una medida:

- **Mapa en planta, no celda a celda.** Aísla la resolución LATERAL —la que manda el
  targeting— de la ambigüedad de PROFUNDIDAD, que la gravedad-sola no resuelve.
- **Escalado a la amplitud de SEÑAL**, `sqrt(max(rms_obs² − σ², 0))`. Sin esto un survey
  ruidoso se auto-aprueba: `noise_0.15` sacaba r = 0,790 con PR-AUC real de 0,010; con la
  corrección baja a 0,661.
- **Se puntúa el DOMINIO completo, no la huella del survey.** Restringir la nota a las
  columnas con estaciones encima premia al que cubre menos: `span_800m` pasaba de 0,104
  (dominio) a 0,643 (huella) con PR-AUC real de 0,026.

### El perfil, por régimen (longitud de resolución en metros, banda a banda)

| régimen | PR-AUC mediano | índice | 0-250 | 250-500 | 500-750 | 750-1000 | 1000-1750 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `depth_250m` | 1,000 | 0,2553 | 250 | 250 | 500 | — | — |
| `coverage_14` | 1,000 | 0,2539 | 250 | 250 | 750 | — | — |
| `baseline` | 1,000 | 0,2476 | 250 | 250 | 500 | — | — |
| `contrast_0.4` | 0,716 | 0,2378 | 250 | 250 | 500 | — | — |
| `coverage_9` | 0,716 | 0,2136 | 500 | 500 | 750 | 750 | — |
| `noise_0.05` | 0,457 | 0,2162 | 250 | 375 | 750 | — | — |
| `depth_600m` | 0,100 | 0,2242 | 250 | 375 | 500 | — | — |
| `coverage_6` | 0,225 | 0,1966 | 500 | 500 | 750 | 750 | — |
| `span_1200m` | 0,039 | 0,1714 | — | — | — | — | — |
| `span_800m` | 0,026 | 0,1124 | — | — | — | — | — |
| `noise_0.15` | 0,010 | 0,1209 | — | — | — | — | — |
| `depth_900m` | 0,002 | 0,1583 | — | — | — | — | — |
| `worst_ldm_like` | 0,002 | 0,0108 | — | — | — | — | — |

«—» = ni el bloque más grande de la escalera se resuelve en esa banda.

---

## 3. El gate

**Criterio del plan:** Spearman entre el diagnóstico nuevo y PR-AUC sobre ≥75 corridas en
≥5 regímenes; si no sube claramente por encima del **0,073** actual, la fase no cierra.

**Y un segundo listón que el plan no tenía.** Ese 0,073 es ρ(`chi2_red`, PR-AUC). Al
re-medirlo salió que **el tablero de hoy ya da ρ = +0,275** sobre las mismas 75 corridas:
superar 0,073 es demasiado fácil. El diagnóstico nuevo se compara contra los dos.

### Conjunto de SELECCIÓN — 74 corridas, 15 regímenes (donde se eligió el diseño)

| diagnóstico | ρ (74 corridas) | ρ (15 medianas por régimen) |
|---|---:|---:|
| `chi2_red` — el control del plan | +0,0601 | +0,1479 |
| tablero de hoy (`pearson_r`) | +0,2747 | +0,3381 |
| `misfit_pct` (negado) | +0,3816 | +0,4495 |
| **`resolvability_index`** | **+0,8746** | **+0,9324** |
| `floor_mass_excess` (negado) | +0,6773 | +0,7394 |

### El escalar primario, y por qué NO es el mejor que se midió

`resolvability_index` = media de r sobre **todo** el examen (todas las bandas × todos los
peldaños). Variantes con una banda o un peldaño escogidos daban **más**: `L=500` en el
dominio llegaba a +0,9173. **Se descartan a propósito**: la ganancia es de tres centésimas
y el coste es un parámetro elegido mirando la respuesta. El índice no tiene ninguno.

**Sesgo de selección, declarado.** Se probaron del orden de 15 resúmenes candidatos sobre
el conjunto de selección. Por eso el número del gate se mide en un conjunto de
**confirmación** con 5 semillas frescas sin solape (`900011 + 126·i`), con los dos
escalares **pre-registrados** en `validation/exp_resolution.py` antes de correrlo.

### Conjunto de CONFIRMACIÓN — 75 corridas, 15 regímenes (EL GATE)

Semillas `900011, 900137, 900263, 900389, 900515`. 62,4 min. Cero errores.

| diagnóstico | ρ (75 corridas) | ρ **DENTRO** de régimen (mediana) |
|---|---:|---:|
| `chi2_red` — el control del plan | **−0,0675** | −0,100 (14 regímenes) |
| tablero de hoy (`pearson_r`) | +0,1996 | — |
| `misfit_pct` (negado) | +0,3564 | — |
| **`resolvability_index`** | **+0,8081** | +0,200 (14 regímenes) |
| `floor_mass_excess` (negado) | +0,6523 | **+0,7071** (13 regímenes) |

**GATE PASADO.** El listón del plan era 0,073 y el listón real —el que el tablero de hoy ya
alcanzaba— era 0,275. El número encoge respecto al conjunto de selección (+0,8746 →
+0,8081), que es exactamente lo que tiene que pasar cuando el diseño se eligió en otro
sitio; y sigue estando un orden de magnitud por encima. En este conjunto `chi2_red` sale
**negativo**: no es que discrimine poco, es que no discrimina.

### Lo que el conjunto de confirmación enseñó de propina

Las medianas por régimen **se mueven mucho** entre los dos juegos de semillas —
`contrast_0.2` pasa de 0,273 a 0,985, `coverage_6` de 0,225 a 0,704, `noise_0.05` de 0,457
a 1,000. Es la misma bimodalidad del hallazgo de agosto vista desde otro ángulo, y es la
justificación empírica de la dirección 5: **cinco semillas siguen siendo pocas**, y una
sola no dice nada. El diagnóstico, en cambio, se mueve poco (`baseline` da 0,2476 y 0,2478
en los dos juegos): mide el survey, no la tirada — que es justo lo que se le pide.

### Efecto medido sobre el veredicto (las 75 de confirmación)

| | |
|---|---|
| veredicto final | **44 MEDIUM / 31 LOW** (antes: casi todo MEDIUM) |
| clase «no resuelve nada» | 22 corridas, PR-AUC **máximo 0,238**, mediana 0,017 |
| el resto | 53 corridas, PR-AUC mediana **1,000** |
| `is_floor_smear` dispara | 25 de 75 · PR-AUC **máximo 0,204** entre ellas · **0 falsos** |
| caza | 25 de las 45 corridas con PR-AUC < 0,90 |
| `is_null_space_artifact` (el detector viejo) | **0 de 75**, otra vez |
| coste del perfil | **0,89 s** medianos por corrida |

---

## 4. La otra mitad del hallazgo: dentro de un mismo régimen

El perfil **no puede** cerrar la segunda mitad: usa el σ declarado, no la realización de
ruido concreta, así que para un mismo survey devuelve lo mismo con cualquier semilla. La
pregunta que quedaba abierta era si algo podía distinguir, con el survey y la
configuración FIJOS, la corrida de 5,6 m de la de 285,5 m.

**Sí puede, y el producto ya tenía el dato en la mano.** Sobre las 74 corridas capturadas,
midiendo 13 candidatos derivados del modelo recuperado:

| candidato | ρ agrupado | ρ **DENTRO** de régimen (mediana) |
|---|---:|---:|
| `chi2_red` | +0,038 | **+0,000** |
| `misfit_pct` (negado) | +0,340 | +0,103 |
| foco de la anomalía | +0,544 | +0,564 (inestable: cambia de signo en 3 regímenes) |
| `doi_p95` (negado) | +0,064 | +0,779 |
| **masa en la banda de piso** (negado) | **+0,677** | **+0,741** |

**`floor_mass_excess`** = fracción de la anomalía recuperada que vive en la banda de piso
de la malla (1,5 celdas), dividida por la que pondría ahí un modelo **uniforme** (contada
en celdas). Un exceso > 1 significa que la inversión apiló masa en el fondo del dominio,
donde la gravedad no la constriñe.

El caso insignia del hallazgo, `baseline`, mismo mundo y misma λ:

| semilla | PR-AUC | horizontal | exceso de piso |
|---|---:|---:|---:|
| 11 | 1,000 | 5,6 m | 0,065 |
| 202 | 1,000 | 18,2 m | 0,125 |
| 40004 | 1,000 | 9,9 m | 0,329 |
| **3003** | **0,583** | **285,5 m** | **0,944** |

Un factor **14×** entre la mejor y la peor, donde `chi2_red` variaba un 16 % sin orden y
los tres campos de honestidad no variaban nada.

**Y cierra la dirección 4 del plan.** `is_null_space_artifact` exige saturación **total**
al bound: salió `False` en 75 de 75 corridas del barrido, incluidas las 15 con PR-AUC ≤
0,01 donde el modelo recuperado *es* smear. El smear de piso es el caso que sí ocurre.

**Umbral: geométrico, no ajustado.** Dispara con exceso > 1 («más masa de la que le toca
por número de celdas»). Sobre 67 corridas: dispara en 27, y en **ninguna** con PR-AUC ≥
0,90 — el exceso más alto entre las buenas es 0,444, así que el margen es amplio. Caza 27
de las 49 que se desploman.

**Límite conocido, y se declara:** `baseline`/3003 da 0,944 y **no dispara por poco**,
aunque el número la separa igual de las tres que aciertan. Con umbral 0,5 se cazarían 37
de 49 y los falsos positivos seguirían en 0 **en esta muestra**, pero el margen al peor
caso sano bajaría a un 12 %. Se deja como opción **medida** para la Fase 30, no se toma
ahora. El número se publica siempre, dispare o no.

---

## 5. Qué cambia en el veredicto — y qué NO

**Cambia:**

1. El tablero **ya no topea**. Se sigue publicando como control histórico (`role:
   historical_control_since_fase26`): su constancia es la evidencia del techo.
2. Entra `survey_resolution`. Si el examen **no resuelve nada** en ninguna banda, cap a
   **LOW**. Medido: esa clase son 20 corridas con PR-AUC **máximo 0,186** (mediana 0,025)
   frente a 0,644 del resto — y **10 de esas 20 salían hoy declaradas MEDIUM**.
3. Entra `best_target_floor_smear`. Cap a LOW cuando el exceso de piso supera lo uniforme.
4. El techo a `HIGH` se declara como lo que es: `high_hold_pending_fase30`, con
   `structural: false` y una condición de salida escrita.

**NO cambia: `HIGH` sigue sin ser alcanzable.** Es deliberado y es lo que el plan ordena.
El propio hallazgo de agosto lo advierte por escrito: *«primero que la señal informe,
después subir el techo»*. Y la mitad que sigue abierta es justo la que lo haría peligroso:
`floor_mass_excess` caza 27 de 49 desplomes, no los 49.

**El error que queda, declarado:** 13 de las 55 corridas cuyo examen «resuelve algo»
también tienen PR-AUC ≤ 0,186 y **no** se topan a LOW — casi todas de los regímenes
profundos, donde el examen ve resolución somera que un cuerpo a 600–900 m no aprovecha.
El error es del lado conservador (no se declara más de lo que se tiene), pero está ahí.

---

## 6. Un callejón sin salida que vale la pena registrar

**Anclar el diagnóstico a la profundidad del blanco recuperado sería SOBRECONFIANZA
fabricada.** La primera versión leía el perfil en la banda del `best_target`. Medido sobre
las 74 corridas capturadas: `best_target.depth_m` sale **62,5 m o 187,5 m en todas** —con
el cuerpo verdadero a 250, 400, 600 o 900 m— y además cae **más somero cuanto más profundo
está el cuerpo** (900 m → 62,5 m en 5 de 5). Anclar ahí le da a las corridas **peores** la
banda **más fácil**. El diagnóstico final no usa la profundidad del blanco: el resumen es
agnóstico de profundidad a propósito.

---

## 7. Lo que este hallazgo NO cierra

- **La bimodalidad, del todo.** `floor_mass_excess` caza 27 de 49; el caso insignia queda
  a 0,944 de un umbral de 1,0.
- **La profundidad.** Sigue sin resolverse y el producto sigue diciéndolo (`depth_confidence`
  = LOW por defecto). Nada aquí lo cambia.
- **`HIGH`.** Fase 30, con su propio gate sobre ≥150 corridas.
- **El frontend.** `resolution_qa`, `floor_mass_excess` y el bloque `ceiling` entero **no
  los lee ningún `.tsx`**: `HonestReportWidgets.tsx:50` consume `overall_verdict` pero sólo
  `level` y `limiting_factors`, y `RecoveryCoverageWidgets.tsx:135` sigue leyendo
  `checkerboard_qa`. La consecuencia visible es que la UI mostrará el literal
  `high_hold_pending_fase30` sin explicación. Es la misma familia que NUEVO-7/H-36 de la
  Fase 25 y queda **abierta**: la regla del proyecto prohíbe tocar backend y frontend en la
  misma fase.
