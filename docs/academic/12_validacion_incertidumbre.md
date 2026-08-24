# INFORME 12 — VALIDACIÓN CIENTÍFICA, TESTING E INCERTIDUMBRE
## Qué se ha demostrado realmente sobre TerraQuantum, y qué no

**Destinatario:** estadística · metodología científica · verificación y validación de software científico
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** `exploration/checkerboard_test.py`, `exploration/potential_field_core.py`, `exploration/gravimetry.py` (estimadores de incertidumbre), `services/geophysics_service.py` (marco de confianza), `scripts/validation/GATES.json` (71 scripts clasificados), `.github/workflows/ci.yml`, `pytest.ini`, y una **medición numérica propia** (§5.2).

> Autocontenido. Este informe es deliberadamente el más incómodo del expediente:
> su trabajo es separar lo que está demostrado de lo que sólo está probado en el
> sentido informático.

---

## 1. La distinción que ordena todo este informe

En software científico se confunden sistemáticamente dos cosas que no tienen nada que
ver:

| | Pregunta | Contra qué se compara | Qué demuestra |
|---|---|---|---|
| **Verificación** | ¿El software hace lo que el código dice? | contra la especificación / contra sí mismo | ausencia de errores de programación |
| **Validación** | ¿El resultado corresponde a la realidad física? | contra el mundo o contra una solución analítica independiente | que el modelo es adecuado |

Un sistema puede tener **verificación perfecta y validación nula**. Puede pasar mil
tests en verde mientras implementa la física equivocada, porque los tests sólo comparan
el código consigo mismo.

**Este informe documenta un caso exacto de eso dentro de TerraQuantum** (§5.2), y lo
documenta con una medición, no con una opinión.

Adelanto del veredicto general: **la verificación de TerraQuantum es notablemente buena
—mejor que la de la mayoría de software académico— y su validación es más estrecha de lo
que su volumen de tests sugiere.**

---

## 2. Lo que sí está verificado, y está bien hecho

Conviene empezar por aquí, porque es sustancial y honesto.

### 2.1 El inventario de validación se declara a sí mismo

`scripts/validation/GATES.json` clasifica **71 scripts** obligando a cada uno a declarar
si **decide** (una puerta: falla y detiene) o sólo **mide** (un instrumento):

| Tipo | Nº |
|---|---|
| diagnóstico (mide, no decide) | 37 |
| **puerta** (decide, `exit != 0`) | **24** |
| tests | 7 |
| biblioteca | 3 |

Un script de CI (`scripts/ci/validation_inventory.py`) verifica que la clasificación esté
al día. El razonamiento está escrito en el propio archivo: la distinción existe porque un
script que parece decidir y sólo mide es una red de seguridad falsa.

**Esto es infraestructura metodológica de calidad poco común.** La mayoría de proyectos
no sabe cuáles de sus scripts de validación realmente bloquean nada.

### 2.2 La CI tiene guardas que no dependen de correr física

Del workflow (`.github/workflows/ci.yml`):

- **Comprobación de compilación** con un script que contrasta los paquetes declarados
  contra los que existen en disco. El comentario explica por qué: antes se compilaban
  «`Camiones` y `workers`, que no existen», y como `compileall` avisa por stdout pero
  devuelve 0, «la CI pasaba en verde compilando seis paquetes de los ocho que decía
  compilar».
- **Presupuestos por AST** para que una refactorización previa no se deshaga sola.
- **Cierre de dependencias**: el código no puede importar nada que el job no instale. Se
  añadió tras medir que `psutil` había dejado de ser instalable y eso ponía 6 tests en
  rojo en un runner limpio.
- **Censo de superficie de configuración**: se recorren por AST las 42 variables de
  entorno del backend y falla si aparece una nueva sin declarar.
- **Duplicación estructural** entre los dos motores de física, con umbral (<40 ventanas;
  se bajó de 192 a 20).
- **Versión de Python leída del mismo archivo que usa el instalador**, tras detectar que
  la CI fijaba 3.11 y `zarr==3.2.1` exige ≥3.12, de modo que «la CI validaba un árbol de
  dependencias que nunca llega al cliente».

Cada guarda existe porque **se midió un fallo concreto**. Eso es lo que distingue una
suite de tests construida por experiencia de una construida por costumbre.

### 2.3 Identidad byte a byte en refactorizaciones numéricas

Existen dos arneses (`fase7_byte_identity.py`, `fase8_byte_identity.py`, ambos **puertas**)
que comparan SHA-256 sobre los bits de los `float64` resultantes tras mover código. El
módulo compartido documenta el contrato: cada función reproduce la aritmética original
**en el mismo orden**, y «si se cambia el orden de una multiplicación, el hash cambia y el
arnés lo dice» (`exploration/potential_field_core.py:35-38`).

Es un reconocimiento explícito de que en coma flotante la reasociación no es una
transformación neutra. Muy pocos proyectos científicos lo tratan con este rigor.

### 2.4 Marcadores de test que separan coste

De `pytest.ini`:

```
slow        : tests que tardan más de 10s
integration : tests que escriben a disco
unit        : rápidos, sin I/O
benchmark   : benchmarks científicos con ground truth analítico
validation  : regresión física a demanda (minutos); SE SALTA salvo TQ_RUN_VALIDATION=1
```

La regresión física completa **no corre en cada PR**: va de noche (`cron: "30 4 * * *"`)
porque «cuesta entre 33 min y 6,9 h MEDIDOS en dos corridas del propio gate». La decisión
está tomada con datos y declarada.

---

## 3. Lo que está validado, y con qué alcance real

### 3.1 Los benchmarks externos

El proyecto ha corrido su motor contra cuatro conjuntos de datos reales publicados:

| Benchmark | Qué es | Resultado registrado |
|---|---|---|
| **DO-27 (Tli Kwi Cho)** | kimberlita, Territorios del Noroeste, Canadá | error horizontal 53,7 m (gravedad sola) |
| **Raglan** | Ni-Cu, Nunavut; dato de campo crudo | pico interior a 212 m |
| **San Nicolás** | sulfuro masivo, México | techo 125 m frente a 150–220 m publicado |
| **Laguna del Maule** | volcánico, Chile; flujo E2E completo | $\chi^2=0{,}92$, targeting ~2 km |

**Alcance honesto, y el propio proyecto lo tiene escrito en sus notas:** estos casos
validan **el motor**, no la competitividad del producto ni su fiabilidad operativa. "El
motor funciona" no equivale a "el producto es confiable".

### 3.2 Un detalle metodológico importante: los benchmarks no son puertas

En `GATES.json`, `do27_harness.py` y `raglan_harness.py` están clasificados como
`"tipo": "diagnostico"`, `"decide": false`.

Es decir: **las validaciones externas miden e imprimen, pero no bloquean nada.** Una
regresión que empeorase el resultado de DO-27 no pondría la CI en rojo.

Esto es defendible (los datos externos pueden no estar disponibles en un runner) pero
conviene que el revisor lo sepa: cuando el proyecto dice "validado contra DO-27", se
refiere a una corrida histórica registrada, no a una verificación continua.

### 3.3 Un sesgo de cobertura que importa

Los dos benchmarks **magnéticos** —DO-27 y Raglan— son de latitudes árticas. La
inclinación de DO-27 está verificada en `tests/test_do27_ingest.py:63`:
$I = 83{,}8°$. Raglan está en Nunavut, con inclinación comparable.

En ambos, $\cos I \approx 0{,}11$: la componente horizontal del campo geomagnético es
apenas un 11 % del total. El caso de uso declarado del producto es Chile, con
$I\approx-30°$ y $\cos I\approx0{,}87$.

**Consecuencia metodológica:** cualquier defecto que afecte a la **orientación horizontal**
del campo inductor sería casi indetectable en estos dos benchmarks y máximo en el caso de
uso real. El informe 03 (§7) documenta precisamente un defecto candidato de ese tipo. No
está confirmado; lo que sí está establecido es que **la validación existente no podría
detectarlo**.

Esto no es un fallo de los benchmarks: son los datos públicos disponibles. Es una
limitación de cobertura que debe declararse.

---

## 4. El "inverse crime" y dónde aparece

### 4.1 Qué es

Se llama *inverse crime* a generar los datos sintéticos con **el mismo modelo directo,
la misma malla y la misma discretización** que después se usa para invertir. El resultado
es sistemáticamente demasiado bueno: el error de discretización se cancela exactamente,
y la recuperación aparente sobreestima lo que se lograría con datos reales.

La medida estándar es generar los datos en una malla mucho más fina (típicamente 3× o
más) e invertir en la gruesa.

### 4.2 Dónde el proyecto lo evita

Sí existe conciencia del problema. Un comentario en el motor describe un experimento
hecho «sobre el dique inclinado con **anti-inverse-crime ×3** y semillas pareadas»
(`exploration/gravimetry.py:2382-2384`). Es decir: al menos un experimento de decisión
—el del prior geológico en la *smallness*— se hizo correctamente.

### 4.3 Dónde no lo evita: el test de checkerboard

`exploration/checkerboard_test.py` es el QA matemático del motor. Su propia metodología
declarada (`exploration/checkerboard_test.py:9-18`):

```
1. Genera un volumen 3D con densidad alternante (checkerboard).
2. Calcula la gravedad sintética con GravimetryForward.
3. Invierte con GravimetryInversion.
4. Compara input vs output.
```

El paso 2 y el paso 3 usan **el mismo objeto `GravimetryForward`, la misma malla y el
mismo tamaño de celda**. Es un *inverse crime* de discretización.

**Atenuante real:** sí se añade ruido gaussiano
(`exploration/checkerboard_test.py:299-301`), con
$\sigma = \text{noise\_floor} + \text{noise\_pct}\cdot|g|$ y semilla fija 42. De modo que
no es el caso degenerado de datos exactos. Pero el error de discretización sigue
cancelado, y ése es el que hace parecer que la malla resuelve mejor de lo que resuelve.

**Consecuencia:** las métricas del checkerboard (correlación de Pearson, porcentaje de
recuperación de signo) son **cotas superiores optimistas** de la resolución real.

### 4.4 Semilla única

`seed=42` en el checkerboard (`exploration/checkerboard_test.py:299`) y `seed=0` en el
estimador de Hutchinson (`exploration/gravimetry.py:258`).

La reproducibilidad es buena. El problema es distinto: **una sola realización de ruido no
es una muestra**. Las propias notas del proyecto registran una medición devastadora sobre
este punto: en configuración base, **1 de cada 3 realizaciones de ruido da un error de
169 m en vez de 19 m, con diagnósticos idénticos**. Es decir, el mismo modelo, el mismo
$\chi^2$, la misma apariencia de calidad, y un orden de magnitud de diferencia en el
resultado.

Si eso es correcto —y es una medición del propio proyecto—, entonces **cualquier métrica
reportada a partir de una sola semilla carece de sentido sin su dispersión**.

---

## 5. Problemas detectados en la propia validación

### 5.1 Tests que no pueden fallar por la razón correcta

Un test que comprueba una propiedad que se cumple tanto con la implementación correcta
como con la incorrecta no aporta información. Ejemplos encontrados en la corrección de
terreno (`tests/test_gravity_corrections.py`, `tests/test_fase0_terrain_correction.py`):

- `test_tc_non_negative_always`: comprueba TC ≥ 0. Se cumple con cualquier fórmula que
  use $|\Delta h|$.
- `test_tc_flat_terrain_is_zero`: comprueba TC = 0 en terreno plano. Se cumple con
  cualquier fórmula proporcional a $\Delta h$.

Ninguno de los dos puede distinguir una física correcta de una incorrecta.

### 5.2 ⚠ El test tautológico, y lo que ocultó

Éste es el hallazgo central del informe.

`test_tc_matches_pointmass_formula` (`tests/test_fase0_terrain_correction.py:57-73`)
comprueba la corrección de terreno así:

```python
expected_mgal = _G_NEWTON * rho * (cell ** 2) * 30.0 / r ** 2 * 1e5
np.testing.assert_allclose(tc[0], expected_mgal, rtol=1e-9)
```

**El test reimplementa la misma fórmula que el código y comprueba que coinciden a
$10^{-9}$.** Verifica que el código calcula lo que el código calcula. Su propio docstring
lo dice sin advertirlo: «confirmando que ES masa-puntual y no un prisma exacto» — confirma
la *identidad* de la implementación, nunca su *corrección*.

**Qué ocultó.** La fórmula implementada es

$$
\text{TC} = \frac{G\rho A|\Delta h|}{r^{2}}
$$

que es el **módulo** de la atracción de la columna de terreno, no su **componente
vertical**, que es lo único que mide un gravímetro. La formulación clásica de columna
vertical (la que subyace a las cartas de Hammer) es
$G\rho A\,(1/r - 1/\sqrt{r^2+\Delta h^2})$, que para $\Delta h\ll r$ tiende a
$G\rho A\,\Delta h^2/(2r^3)$.

La razón entre ambas es $\approx 2r/|\Delta h|$: **el error crece con la distancia**, y el
radio de integración por defecto es de 22 km.

**Medición propia** (script en Python puro, sin modificar el proyecto; celda de DEM de
30 m, $\rho=2{,}67$):

| $r$ [m] | $\Delta h$ [m] | TQ [mGal] | Columna [mGal] | Razón |
|---|---|---|---|---|
| 100 | 10 | 1,604e-02 | 7,960e-04 | 20,1× |
| 1.000 | 10 | 1,604e-04 | 8,019e-07 | **200,0×** |
| 20.000 | 10 | 4,010e-07 | 1,002e-10 | **4000,0×** |

Las razones medidas coinciden exactamente con la predicción analítica $2r/|\Delta h|$.
En un caso realista (cono de 500 m, estación al pie, integración a 22 km): **17,01 mGal
frente a 1,41 mGal, un factor 12**. Para referencia, las TC reales en terreno montañoso
están entre 0,1 y 10 mGal.

**Y la historia metodológica es la parte instructiva.** El proyecto **ya auditó esta
función**. El encabezado del test dice:

> «`compute_terrain_correction_prism` implementaba SOLO masa-puntual (G·ρ·área·|dh|/r²)
> pero el nombre/comentarios prometían "exact prism formula". Se renombró a
> `compute_terrain_correction_pointmass`.»
> (`tests/test_fase0_terrain_correction.py:1-6`)

Se detectó que **el nombre** mentía y se corrigió el nombre. Nadie preguntó si **la
fórmula** era correcta. Y después se escribió un test que congela la fórmula equivocada
con tolerancia $10^{-9}$, convirtiéndola en el comportamiento de referencia.

*(El desarrollo geofísico completo está en el informe 04, §4.5.)*

### 5.3 Una función testeada que producción no ejecuta

`select_solver` (`exploration/solver_preconditioned.py:34`) implementa la tabla de
despacho de solvers y tiene cinco tests (`tests/test_fase10_solver.py:56-71`). Búsqueda
exhaustiva en el repositorio: **los únicos llamadores son los tests**. El despacho real
está escrito en línea en `exploration/gravimetry.py:2529-2535`.

Hoy ambas implementaciones son lógicamente equivalentes, luego no hay error de
comportamiento. Pero si alguien cambiara el despacho real, la suite seguiría en verde.
Es cobertura que no protege lo que parece proteger.

---

## 6. La maquinaria de incertidumbre

Aquí el sistema es considerablemente mejor de lo habitual. Conviene describir cada pieza
y decir qué mide y qué no.

### 6.1 El modelo de ruido, $\sigma$

Dos regímenes (`exploration/potential_field_core.py:84-155`):

- **Declarado**: $\sigma_i=\max(\text{piso},\ \text{pct}\cdot|d_i|)$, con una tabla de
  pisos **por modelo de gravímetro** (`GRAVIMETER_NOISE_FLOOR`).
- **Adaptativo**: $\sigma_i=\max(0{,}02|d_i|,\ 0{,}01\cdot\text{rango})$, con detección de
  atípicos por MAD ($3\times1{,}4826\cdot\text{MAD}$) y des-peso $\times10$.

**Lo que el sistema hace bien y es el núcleo de su honestidad estadística:** distingue
explícitamente los dos casos y **cambia de método de regularización en consecuencia**. Con
$\sigma$ declarado, $\chi^2_{red}$ es físicamente interpretable y se usa el principio de
discrepancia de Morozov; con $\sigma$ adaptativo, $\chi^2$ **no** lo es y se recurre a un
punto de operación fijo (`services/geophysics_service.py:3196-3210`).

Que un sistema se niegue a usar $\chi^2$ cuando $\chi^2$ no significa nada es
exactamente la conducta correcta.

**Limitación declarada:** el des-peso $\times10$ de los atípicos es heurístico y el propio
código lo dice (`exploration/potential_field_core.py:96-98`). No corresponde a ningún
estimador M estándar (Huber, Tukey) y su efecto sobre la distribución del residuo no está
caracterizado.

### 6.2 Desviación posterior: el estimador de Hutchinson

`hutchinson_diag_inv` (`exploration/gravimetry.py:253`) estima
$\operatorname{diag}(A^{-1})$ con sondas de Rademacher:

$$
\operatorname{diag}(A^{-1})\approx\frac1N\sum_{k=1}^{N} z_k\odot(A^{-1}z_k),
\qquad z_k\sim\text{Rademacher}(\pm1)
$$

Cada $A^{-1}z_k$ se resuelve por CG con precondicionador de Jacobi. La referencia citada
—Bekas, Kokiopoulou & Saad (2007)— es la correcta, y la justificación de insesgadez
($\mathbb E[zz^\top]=I$) está bien escrita.

**Dos observaciones que el código no hace:**

1. **$N=32$ sondas por defecto.** El error del estimador decae como $O(1/\sqrt N)$, de
   modo que con 32 sondas la incertidumbre **del propio estimador de incertidumbre** es
   del orden del 18 %. No es despreciable si el número se muestra al usuario como si
   fuera exacto.

2. **El recorte a no negativos introduce sesgo.** La última línea es
   `np.clip(diag_est, a_min=0.0, a_max=None)` (`exploration/gravimetry.py:305`). El
   estimador es insesgado *antes* del recorte; después no lo es, porque
   $\mathbb E[\max(X,0)]\ge\mathbb E[X]$. En celdas de varianza pequeña y estimación
   ruidosa, **sobreestima sistemáticamente**. El recorte es necesario (una varianza
   negativa no tiene sentido), pero su consecuencia estadística no está declarada.

**Lo que este número mide y lo que no.** Mide la varianza posterior **bajo el supuesto de
que el modelo es correcto y el prior es el que impone la regularización elegida**. No mide
el error de modelo, ni el efecto de haber elegido otro $\lambda$, ni la no unicidad
estructural. Es incertidumbre *dentro* de la formulación, no *sobre* la formulación.

### 6.3 El test de checkerboard

`compute_checkerboard_metrics` (`exploration/checkerboard_test.py:138`) devuelve
correlación de Pearson sobre la malla activa, porcentaje de recuperación de signo, SNR y
una etiqueta cualitativa.

Mide **resolución de estructura fina**: si el levantamiento puede distinguir un patrón
alternante del tamaño de celda elegido. Es la herramienta clásica en tomografía sísmica.

**Limitaciones:** el *inverse crime* de discretización (§4.3) hace las métricas
optimistas; y el resultado depende de la longitud de onda del patrón elegido, que aquí es
fija (una celda de alternancia).

### 6.4 El *null-space shuttle*

`null_space_shuttle_directions` (`exploration/gravimetry.py:308`) y
`assemble_shuttle_ensemble` (`exploration/potential_field_core.py:609`) generan un abanico
de modelos alternativos que **explican los datos igual de bien**, moviéndose en
direcciones del espacio nulo.

Conceptualmente es la respuesta correcta a la no unicidad: en lugar de afirmar un modelo,
mostrar la familia de modelos compatibles. Y hay un detalle de diseño acertado: el recorte
al box petrofísico se aplica **al miembro del abanico, no a la dirección**, de modo que el
abanico mide no unicidad **dentro de lo físicamente admisible**
(`exploration/potential_field_core.py:616-618`).

### 6.5 Profundidad de investigación (DOI) y sensibilidad

Se calcula un proxy de sensibilidad como la norma de columna del kernel ponderado,
normalizada (`exploration/gravimetry.py:2220-2223`), y se publica por celda. El frontend
lo usa para atenuar el brillo de celdas mal constreñidas en lugar de ocultarlas — decisión
correcta y documentada (informe 10).

---

## 7. El marco de honestidad: qué afirma el sistema sobre sí mismo

Esta es, a juicio de esta auditoría, la parte mejor resuelta de TerraQuantum.

### 7.1 Veredicto por eslabón más débil

`build_reconciled_verdict` (`services/geophysics_service.py:886`) produce **un solo**
veredicto tomando el **mínimo** entre cinco señales de calidad: confianza del
levantamiento, fiabilidad del modelo, prioridad de targeting, puerta física de
padding/regional, y si el blanco recuperado es un artefacto de espacio nulo.

El docstring lo declara sin ambigüedad: «Nunca deja sobrevivir un 'HIGH' junto a un
REMEDIATION_REQUIRED / UNCLASSIFIED / blanco null-space»
(`services/geophysics_service.py:893-895`). El método se publica como
`"weakest_link_reconciliation"`.

Que un sistema comercial elija deliberadamente **el peor** de sus indicadores en lugar del
promedio, y lo declare, es infrecuente y correcto.

### 7.2 La confianza en profundidad se desacopla de la horizontal

$$
\text{si no hay dato independiente} \Rightarrow \texttt{depth\_confidence = "LOW"}
$$
(`services/geophysics_service.py:801-810`)

con el mensaje: la profundidad mostrada «es INDICATIVA, no un dato resuelto; el targeting
confiable es el HORIZONTAL».

El razonamiento está medido y escrito: la gravedad sola no resuelve la profundidad
absoluta, y un cuerpo profundo se recupera indistinguible de uno somero
(`services/geophysics_service.py:790-793`). El caso que cierra: antes, una profundidad
equivocada (62,5 m para un cuerpo real a 900 m) se presentaba con la misma confianza
MEDIUM que una correcta.

Y hay un matiz fino: sólo un dato **independiente** (sondaje real) sube la confianza —
explícitamente **no** el prior automático derivado del espectro, «que SATURA ~350 m en
profundo».

### 7.3 La "ley" se declara como proxy

```python
_GRADE_PROVENANCE = {
    "grade_source": "heuristic_gravity_proxy",
    "assay_supported": False,
    "economically_validated": False,
}
```
(`services/geophysics_service.py:614-618`)

más `"is_demo_grade": True` en cada blanco (`services/geophysics_service.py:830`) y un
`logger.warning("[WARNING] Grade heuristic used for exploration preview")` en la propia
construcción (`services/geophysics_service.py:622`).

El sistema **no puede** presentar su índice de ley como una ley sin que el campo
estructurado lo desmienta. Es la forma correcta de manejar un proxy.

### 7.4 El artefacto degradado se publica, no se oculta

Cuando el máximo de anomalía cae en una celda que satura el bound y está en el piso de la
malla —firma de masa de espacio nulo no constreñida—, el sistema lo **degrada** pero lo
publica en un campo `demoted` con su razón textual
(`services/geophysics_service.py:764-773`): «no es un blanco de perforación». El
comentario lo llama «transparencia, no silencio».

Además el ranking de blancos se pondera por **resolubilidad** ($\text{score} = \text{sens}\times\text{anomalía}$),
de modo que un artefacto profundo con sensibilidad ~0 queda por debajo de un cuerpo somero
constreñido por el dato aunque su anomalía absoluta sea mayor
(`services/geophysics_service.py:745-752`).

### 7.5 El límite del marco: ¿es "HIGH" alcanzable?

Las notas internas del proyecto afirman que TerraQuantum **nunca puede emitir HIGH**,
porque el checkerboard falla siempre y el veredicto worst-of lo usa como tope duro.

**La lectura del código matiza esa afirmación.** El código dice:

```python
if cb_status == "FAIL":
    levels.append(("MEDIUM", "checkerboard_resolution"))
```
con el comentario: «Ausente / NOT_RUN → sin efecto»
(`services/geophysics_service.py:949-959`).

Es decir: el checkerboard sólo topa a MEDIUM **si se ejecutó y falló**. Si no se ejecuta,
no hay tope. Por tanto HIGH es alcanzable en corridas sin checkerboard.

Esto plantea una pregunta metodológica incómoda: **el veredicto puede ser mejor
precisamente cuando se ha medido menos**. No se determinó en esta auditoría con qué
frecuencia se ejecuta el checkerboard en producción: **NO DETERMINADO**.

---

## 8. Fuentes de incertidumbre, y cuáles cubre el sistema

| Fuente | ¿Cubierta? | Cómo / por qué no |
|---|---|---|
| Ruido de medición | **Sí** | $\sigma$ declarado o adaptativo; $W_d$; $\chi^2$ |
| Atípicos | Parcial | MAD + des-peso ×10 (heurístico, no caracterizado) |
| No unicidad estructural | **Sí** | *null-space shuttle*; desacople de profundidad |
| Resolución espacial | Parcial | checkerboard (con *inverse crime*) |
| Varianza posterior | Parcial | Hutchinson, 32 sondas (~18 % de error propio), recorte sesgado |
| Elección de $\lambda$ | **No** | no se propaga la incertidumbre por la elección del regularizador |
| **Error de modelo** | **No** | si la física está mal (p. ej. §5.2), nada lo detecta |
| Error de discretización | **No** | el *inverse crime* del checkerboard lo cancela |
| Truncamiento del kernel | **No** | sin cota (informe 03) |
| Parada temprana del solver | **Declarada, no cuantificada** | se publica `istop`, pero no su efecto en el resultado |
| Densidad de fondo mal elegida | **No** | desplaza todo el modelo sin diagnóstico |

La fila más importante es **error de modelo**. Todo el aparato de incertidumbre asume que
el modelo directo es correcto. La corrección de terreno de §5.2 es un ejemplo de un error
que ningún estimador de este sistema podría detectar, porque no es ruido: es sesgo
sistemático en la física.

---

## 9. Resumen técnico

### Verificación — bien resuelta

- Inventario de 71 scripts que declaran si deciden o sólo miden.
- Guardas de CI construidas cada una a partir de un fallo medido.
- Identidad byte a byte en refactorizaciones numéricas.
- Marcadores de coste y regresión física nocturna con tiempos medidos.

### Marco de honestidad — muy bien resuelto

- Veredicto por eslabón más débil, declarado como tal.
- Confianza en profundidad desacoplada y por defecto LOW.
- Procedencia de la "ley" marcada como proxy heurístico en el campo estructurado.
- Artefactos de espacio nulo degradados y publicados con su razón.
- Rechazo a usar $\chi^2$ cuando $\chi^2$ no es interpretable.

### Validación — más estrecha de lo que parece

- Cuatro benchmarks externos, pero **clasificados como diagnósticos, no como puertas**.
- Los dos benchmarks magnéticos son árticos: ciegos a errores de orientación horizontal.
- El checkerboard comete *inverse crime* de discretización.
- Semilla única, cuando el propio proyecto midió que 1 de cada 3 realizaciones cambia el
  resultado en un orden de magnitud.

### Problemas detectados

1. **Test tautológico que congeló una física incorrecta** (§5.2). **Medido.**
2. Tests que comprueban propiedades que se cumplen con cualquier fórmula.
3. `select_solver` testeada pero no ejecutada.
4. El veredicto puede mejorar cuando se mide menos (§7.5).
5. Hutchinson: recorte que sesga, y 32 sondas sin declarar su propio error.

---

## 10. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Cómo se escribe un test que pueda detectar física equivocada

**Pregunta.** El test de la corrección de terreno reimplementa la fórmula del código y la
compara consigo misma con `rtol=1e-9`. Pasó siempre, y congeló una expresión que difiere
de la formulación clásica en un factor medido de $2r/|\Delta h|$. ¿Qué estructura de test
recomendaría usted para que este tipo de error sea detectable? Nuestras candidatas son:
(a) comparar contra una **solución analítica independiente** (el TC de un cono o un
cilindro tienen forma cerrada); (b) comprobar el **orden de convergencia** al refinar el
DEM; (c) verificar **leyes de escala** ($\text{TC}\propto\Delta h^2$ en campo lejano, no
$\propto\Delta h$). ¿Alguna otra?

**Por qué surge.** Es el caso más claro de verificación perfecta con validación nula que
encontramos.

**Evidencia.** `tests/test_fase0_terrain_correction.py:57-73` (el test);
`services/gravity_corrections_service.py:159-162` (la fórmula).

**Qué sabemos.** Que la opción (c) habría detectado el error inmediatamente: la razón
$2r/|\Delta h|$ implica que la dependencia en $\Delta h$ es lineal en vez de cuadrática.

**Qué opinión sería útil.** Un criterio general para decidir cuándo un test necesita una
referencia externa y cuándo basta con una propiedad interna.

---

### Pregunta 2 — El *inverse crime* del checkerboard

**Pregunta.** El test de resolución genera los datos sintéticos con el mismo modelo
directo y la misma malla con que después invierte (aunque añade ruido). ¿Qué factor de
refinamiento recomendaría para la malla de generación —3×, 5×— y qué métrica usaría para
saber si el refinamiento es suficiente? ¿Y considera que un checkerboard con *inverse
crime* aporta algo, o debería descartarse su resultado por completo?

**Evidencia.** `exploration/checkerboard_test.py:9-18` (la metodología);
`exploration/checkerboard_test.py:299-301` (el ruido);
`exploration/gravimetry.py:2382-2384` (donde el proyecto sí usó anti-inverse-crime ×3).

---

### Pregunta 3 — Una semilla no es una muestra

**Pregunta.** El proyecto midió que 1 de cada 3 realizaciones de ruido produce 169 m de
error en lugar de 19 m, con diagnósticos idénticos. Sin embargo los tests y benchmarks
usan semilla fija. ¿Cuántas realizaciones recomendaría como mínimo, y qué estadístico
debería reportarse — mediana y rango intercuartílico, peor caso, probabilidad de superar
un umbral? Y sobre todo: si los diagnósticos no distinguen el caso bueno del malo,
**¿qué diagnóstico adicional propondría** para detectar cuándo una corrida cayó en el
modo malo?

**Por qué surge.** Es la observación más inquietante del expediente: la métrica de
calidad que el sistema publica no discrimina entre un resultado bueno y uno diez veces
peor.

---

### Pregunta 4 — El estimador de incertidumbre y su propia incertidumbre

**Pregunta.** La desviación posterior se estima con Hutchinson y 32 sondas de Rademacher,
lo que da $\sim18\%$ de error propio, y después se recorta a no negativos, lo que
introduce sesgo hacia arriba. ¿Cuántas sondas recomendaría para que el número sea
presentable al usuario? ¿Y hay una forma estándar de manejar el recorte sin sesgar — por
ejemplo, reportar el intervalo del estimador en lugar del valor puntual?

**Evidencia.** `exploration/gravimetry.py:253-305`.

---

### Pregunta 5 — Cuando medir menos mejora el veredicto

**Pregunta.** El veredicto worst-of topa a MEDIUM si el checkerboard **falla**, pero no
tiene efecto si **no se ejecutó**. Un revisor puede leer eso como un incentivo perverso:
no medir la resolución permite un veredicto mejor. ¿Recomendaría tratar `NOT_RUN` como
una limitación explícita (por ejemplo, impidiendo HIGH sin evidencia de resolución), o
considera correcto el diseño actual?

**Evidencia.** `services/geophysics_service.py:949-959`.

**Qué NO sabemos.** Con qué frecuencia se ejecuta el checkerboard en producción.
NO DETERMINADO.

---

### Pregunta 6 — Benchmarks que no bloquean

**Pregunta.** Los arneses de DO-27 y Raglan están clasificados como diagnósticos
(`"decide": false`), de modo que una regresión que empeorase su resultado no pondría la
CI en rojo. ¿Le parece defendible, dado que los datos externos pueden no estar en un
runner? ¿O recomendaría congelar métricas de referencia y convertirlos en puertas con
tolerancia?

**Evidencia.** `scripts/validation/GATES.json` (clasificación de los 71 scripts).

---

### Pregunta 7 — Cobertura de validación sesgada por latitud

**Pregunta.** Los dos benchmarks magnéticos son árticos ($I\approx84°$, $\cos I\approx0{,}11$)
y el caso de uso declarado es Chile ($I\approx-30°$, $\cos I\approx0{,}87$). Cualquier
defecto en la orientación horizontal del campo sería casi invisible en la validación
existente. ¿Conoce conjuntos de datos magnéticos públicos de latitudes medias o del
hemisferio sur que sirvieran de benchmark? Y en su defecto: ¿qué prueba **sintética**
sería aceptable como sustituto?

**Evidencia.** `tests/test_do27_ingest.py:63` ($I=83{,}8°$);
`exploration/magnetometry.py:139` (el defecto de Chile, $I=-30°$).

---

### Pregunta 8 — Qué falta para poder decir "validado"

**Pregunta.** Con lo descrito en este informe, ¿qué diría usted que TerraQuantum tiene
derecho a afirmar hoy? Nuestra formulación tentativa es: *"el motor reproduce la posición
horizontal de cuerpos conocidos en cuatro casos publicados, con error de decenas de
metros; la profundidad no está resuelta sin dato independiente; y la validación magnética
sólo cubre campo casi vertical."* ¿Le parece una afirmación defendible, insuficiente o
excesiva? ¿Qué añadiría o quitaría?

**Por qué surge.** El proyecto quiere venderse a consultores geofísicos. La frase que
ponga en su material tiene consecuencias, y preferimos que la revise un especialista
antes de escribirla.

---

*Fin del informe 12. El informe 04 desarrolla la geofísica de la corrección de terreno;
el informe 03, la física de los kernels; el informe 02, los diagnósticos numéricos del
solver.*
