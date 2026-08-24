# INFORME 07 — COMPUTACIÓN CIENTÍFICA
## Discretización, paralelismo, complejidad y reproducibilidad numérica

**Destinatario:** computación científica · HPC · métodos numéricos aplicados
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `exploration/gravimetry.py`, `exploration/potential_field_core.py`, `exploration/solver_preconditioned.py`, `exploration/storage.py`, `core/config.py`, `requirements.txt`.

> Autocontenido. Repite lo mínimo del planteamiento del problema para que las
> decisiones de cómputo tengan sentido.

---

## 1. El problema de cómputo, en una página

TerraQuantum resuelve un problema inverso lineal mal planteado: recuperar un campo de
contraste de densidad $m\in\mathbb{R}^n$ en una malla 3D a partir de $p$ mediciones de
gravedad, con $p \ll n$.

Las magnitudes reales, tomadas de los umbrales que el propio código usa para decidir:

| Cantidad | Orden típico |
|---|---|
| $p$ (estaciones) | decenas a miles |
| $n$ (celdas activas) | **30.000 – 100.000** (`core/config.py:220-221`) |
| Sistema aumentado | $(p+2n)\times n$ |
| Iteraciones del solver | 500 (tope duro) |

El objeto dominante es la matriz $G\in\mathbb{R}^{p\times n}$ del operador directo. Con
$p=1000$ y $n=10^5$, una matriz densa serían $8\times10^8$ bytes = 800 MB. **Toda la
estrategia de cómputo del sistema gira alrededor de no materializar eso.**

---

## 2. Discretización y estructuras de datos

### 2.1 La malla

Tres esquemas coexisten:

- **Regular uniforme**: vóxeles de lado constante.
- **Tensorial no uniforme**: espaciados `hx`, `hy`, `hz` variables, con el Laplaciano
  adaptado por pesos de arista $w_{ij}=2/(h_i+h_j)$ (`exploration/gravimetry.py:1358-1381`).
- **Octree / TreeMesh**: celdas de tamaño variable con ruta de kernel dedicada
  (`exploration/gravimetry.py:946`).

La ruta de octree está diseñada como **aditiva y opt-in**: con `cell_d* = None` el
resultado es byte-idéntico al uniforme, «incluida la caché de geometría»
(`exploration/gravimetry.py:790-793`). Es la forma correcta de introducir una variante
numérica sin arriesgar regresiones.

El aplanado usa **orden Fortran** de forma explícita y marcada como obligatoria
(`exploration/gravimetry.py:1330-1333`), con la advertencia de que los pesos deben
ravelarse en el mismo orden.

### 2.2 Reducción del dominio antes de calcular

Dos podas reducen $n$ antes de construir nada pesado:

- **Topografía**: sólo celdas bajo el terreno
  (`exploration/potential_field_core.py:167-169`).
- **Dominio observable**: se descartan las celdas cuya norma de columna en el kernel cae
  por debajo de $10^{-6}$ del máximo (`exploration/potential_field_core.py:180-189`). El
  argumento del código es numérico y correcto: esas columnas «sólo añaden plateau de mínima
  norma y saturación espuria en el bound».

Reducir el dominio antes de ensamblar es preferible a ensamblar y luego enmascarar: ahorra
memoria y mejora el condicionamiento.

### 2.3 Formato disperso

$G$ se materializa como `scipy.sparse.csr_matrix`, `float64`
(`exploration/gravimetry.py:911-915`), ensamblada por tripletas
(fila, columna, valor) concatenadas al final (`exploration/gravimetry.py:906-910`).

Es el patrón correcto: construir listas y coalescer una vez, en lugar de insertar en una
estructura dispersa (que en CSR es $O(\text{nnz})$ por inserción).

El Laplaciano se ensambla en COO y se convierte a CSR
(`exploration/gravimetry.py:1394-1401`), con $O(n)$ no ceros (hasta 7 por fila).

---

## 3. Qué hace que el kernel sea disperso — y una observación incómoda

La dispersión no es una propiedad del problema: es **una decisión**. El kernel
gravitacional decae como $1/r^2$ pero nunca se anula.

El código impone tres regímenes por distancia
(`exploration/gravimetry.py:824-825`, `864-874`):

| Régimen | Condición | Coste por par |
|---|---|---|
| Nagy exacto | $r\le4a_{eq}$ | 8 evaluaciones con `log` y `arctan2` |
| Masa puntual | $4a_{eq}<r\le r_{cut}$ | ~5 operaciones aritméticas |
| Descartado | $r>r_{cut}$ (800 m) | 0 |

**La observación incómoda.** Con $r_{cut}=800$ m y celdas de 10 m, el número medio de
celdas dentro del corte por sensor es

$$
\bar k \approx \frac{\tfrac{4}{3}\pi r_{cut}^3}{dx\,dy\,dz} \approx 2{,}1\times10^{6}
$$

es decir, **más celdas de las que suele tener el modelo entero**. En ese régimen el corte
no recorta nada y la matriz es efectivamente densa. El corte sólo produce dispersión
cuando el dominio es mayor que 1.600 m de lado o las celdas son grandes.

Esto explica por qué existe la salvaguarda de memoria de §4 y por qué vigila la
**densidad** y no el número de vóxeles.

---

## 4. La salvaguarda de memoria: bien diseñada

`_guard_sparse_kernel_memory` (`exploration/gravimetry.py:57`) estima el tamaño del kernel
**antes de materializarlo**:

```python
counts = tree.query_ball_point(sensor_coords, r=cutoff, return_length=True)
nnz = int(np.sum(counts))
bytes_est = nnz * 24
```

Tres decisiones acertadas:

1. **`return_length=True`** devuelve sólo el conteo de vecinos, $O(p)$ en memoria, sin
   materializar las listas de índices — «que para un kernel denso son justamente lo que
   dispara el OOM» (`exploration/gravimetry.py:60-63`).
2. **24 bytes por no cero** como cota superior, contando CSR más los arrays transitorios
   (`exploration/gravimetry.py:47-53`).
3. **Aborta si supera el 60 % de la RAM disponible**, con un error accionable
   (`SOLVER_KERNEL_TOO_DENSE`) que incluye el tamaño estimado, la memoria libre, el
   porcentaje de llenado y el cutoff (`exploration/gravimetry.py:88-100`).

Y el criterio está bien elegido: **no limita vóxeles, limita densidad del kernel**. «Un
kernel disperso de millones de celdas pasa; uno denso de pocas celdas se detiene»
(`exploration/gravimetry.py:50-52`).

**Degradación segura declarada:** si SciPy es antiguo y no soporta `return_length`, la
función devuelve `None` y no estima, en lugar de fallar
(`exploration/gravimetry.py:76-78`).

---

## 5. Paralelismo: qué es real y qué es nominal

### 5.1 El paralelismo que sí existe

El ensamblado del kernel usa `ThreadPoolExecutor` con
`max_workers = max(1, cpu_count - 1)` (`exploration/gravimetry.py:825`, `897-904`), una
tarea por sensor.

**¿Por qué funciona en Python, con el GIL?** Porque cada tarea es esencialmente NumPy
vectorizado sobre arrays de índices, y NumPy **libera el GIL** durante las operaciones
sobre arrays. Es el caso en que los hilos sí paralelizan en CPython. La elección es
correcta y evita el coste de serialización de `multiprocessing`.

Además el código evita estado mutable compartido: cada tarea devuelve sus propias
tripletas y el comentario lo marca — «no shared writes»
(`exploration/gravimetry.py:857`).

### 5.2 El paralelismo que no existe

`compute_jacobian_dask` (`exploration/gravimetry.py:3815`) construye el Jacobiano por lotes
de sensores con `dask.delayed` y lo escribe a Zarr para que «la matriz densa completa nunca
viva en RAM simultáneamente».

Dos matices que conviene registrar:

1. Llama a `dask.compute(..., scheduler="synchronous")`, es decir, **sin paralelismo**.
   Dask aquí aporta *out-of-core*, no concurrencia. El propio `requirements.txt` lo
   documenta al justificar la eliminación de `distributed`
   (`requirements.txt:71-76`).
2. **No se localizó ningún llamador en producción.** Las únicas referencias son tests
   (`tests/test_jacobian_dask.py`, `tests/test_fase10_solver.py`) y un docstring en
   `exploration/solver_preconditioned.py:349`.

Es decir: la capacidad *out-of-core* existe, está probada, y **no está cableada al flujo
del producto**.

### 5.3 Higiene de dependencias

Merece mención positiva que el proyecto haya **eliminado** dependencias cuya utilidad no
se materializaba: `distributed` (porque el scheduler es síncrono), y las perillas de
compresión wavelet junto con su función, porque «NINGÚN código las leía»
(`core/config.py:246-251`). También se eliminó un camino de solver directo SuperLU que
llamaba a una función inexistente y abortaba con `NameError`
(`core/config.py:235-239`).

Eliminar en lugar de reparar código especulativo es la decisión correcta.

---

## 6. Caché de geometría

El kernel depende **sólo** de la geometría —coordenadas activas, sensores, tamaños de
celda, cutoff—, **no** de $\lambda$, del modelo de referencia ni del ruido. El código
explota esto con una caché de **una sola entrada**
(`exploration/gravimetry.py:722-728`, `806-820`):

```
clave = (dx, dy, dz, cutoff, shape_coords, shape_sensores) + arrays de coordenadas
validación = np.array_equal (no hash)
```

Dos aciertos:

- **Validación por `np.array_equal` en lugar de hash**: sin riesgo de colisión, a costa de
  una comparación $O(n)$ que es despreciable frente a reconstruir el KDTree.
- **Justificación medida del beneficio**: dentro de una corrida, «solve/L-curve/DOI/UQ
  reusan la misma geometría → se evita reconstruir el KDTree»
  (`exploration/gravimetry.py:724-727`).

Y hay un contador `kernel_build_count` expuesto para diagnóstico y tests
(`exploration/gravimetry.py:729`), es decir: **la eficacia de la caché es observable**, no
una suposición.

---

## 7. Complejidad, derivada del código

### 7.1 Construcción del kernel

| Etapa | Coste |
|---|---|
| KDTree sobre $n$ centros | $O(n\log n)$ |
| Dos consultas de bola en lote | $O(p\log n + \text{nnz})$ |
| Evaluación | $O(\text{nnz})$, constante mayor en campo cercano |
| Coalescencia CSR | $O(\text{nnz}\log\text{nnz})$ |

con $\text{nnz}\approx p\cdot\bar k$.

### 7.2 Solve iterativo

LSQR y LSMR hacen **dos productos matriz-vector por iteración**, cada uno
$O(\text{nnz}(A))$, con

$$
\text{nnz}(A) = \text{nnz}(G) + O(7n) + n
$$

Coste total: $O(\text{it}\cdot\text{nnz}(A))$ con `it` = 500. Memoria: $O(\text{nnz}(A)+n)$
— los métodos de Krylov de tipo LSQR guardan un puñado de vectores, no una base completa.

### 7.3 Multiplicadores que se acumulan

Éste es el punto que más importa para el coste real, y no está declarado al usuario:

| Mecanismo | Multiplicador |
|---|---|
| IRLS (norma no $\ell_2$) | × `compact_max_irls` |
| GPCG proyectado | + hasta 6 ciclos con solves de Krylov internos |
| Selección de $\lambda$ por curva-L | × 20 solves (`iter_lim=150`) |
| Selección de $\lambda$ por Morozov | × 5 candidatos + bisección, **con el solver real** |

Es decir: **activar la selección automática de $\lambda$ multiplica el coste total por un
factor de entre 5 y 20**, y combinarla con IRLS lo multiplica otra vez. No se encontró
ninguna advertencia al usuario sobre esto.

### 7.4 Un umbral de rendimiento con consecuencia numérica

El despacho de solver decide por tamaño (`exploration/gravimetry.py:2529-2535`), y el
umbral de 8.000 celdas viene de un *benchmark* medido: TRF+LSMR ~40 s con nnz≈213.000 y
$n\approx14.000$, frente a <0,1 s de LSQR (`exploration/gravimetry.py:2524-2528`).

Conviene nombrarlo por lo que es: **una decisión de rendimiento que cambia la garantía
matemática**. Por debajo del umbral se resuelve el problema con restricciones de caja; por
encima se resuelve sin ellas y se corrige después (informe 02, §5).

---

## 8. Aritmética de punto flotante

### 8.1 Precisión

`float64` en todo el pipeline, explícito y sistemático (`dtype=np.float64` aparece en cada
conversión). No se encontró ningún cálculo en precisión simple en el backend.

*(Nota: el transporte al frontend sí usa `float32` en los buffers Arrow, lo cual es
adecuado para visualización.)*

### 8.2 Tratamiento de singularidades

La fórmula de Nagy tiene singularidades logarítmicas reales. El tratamiento
(`exploration/gravimetry.py:748-763`):

| Riesgo | Salvaguarda |
|---|---|
| $r\to0$ | $r=\sqrt{x^2+y^2+z^2+\varepsilon}$ |
| $\log(0)$ | $\log(\max(\cdot,\varepsilon))$ en vez de $\log(|\cdot|+\varepsilon)$ |
| $\arctan(xz/yr)$ con $y\to0$ | `arctan2(xz, yr+ε)` obligatorio |
| escala inadecuada | $\varepsilon=10^{-10}\cdot\min(dx,dy,dz)$ |

La última es la más fina y la menos habitual: hacer $\varepsilon$ **proporcional a la escala
del vóxel** en lugar de una constante absoluta. Con $d\sim10$ m el sesgo introducido es
$\sim10^{-9}$ m² bajo la raíz, despreciable frente a distancias métricas.

### 8.3 Pisos numéricos sistemáticos

| Salvaguarda | Valor | Ubicación |
|---|---|---|
| piso de $\sigma$ | $10^{-30}$ | `potential_field_core.py:136` |
| piso de normas de columna | $10^{-12}$ | `potential_field_core.py:344` |
| piso al deshacer el cambio de variable | $10^{-12}$ | `potential_field_core.py:281-283` |
| piso de diagonal en Jacobi | $10^{-30}$ | `potential_field_core.py:598`, `781` |
| denominador de misfit relativo | $10^{-30}$ | `potential_field_core.py:820` |

Y un rechazo explícito de NaN en el modelo de referencia, con el argumento correcto: «un
modelo de referencia con NaN envenena el RHS de la suavidad **en silencio**»
(`exploration/potential_field_core.py:895-896`). Los NaN se propagan por álgebra matricial
sin lanzar error hasta que alguien mira el resultado.

### 8.4 Un estimador que no es lo que su nombre sugiere

`estimate_cond_from_columns` (`exploration/potential_field_core.py:541`) calcula

$$
\widehat\kappa = \frac{\max_j\|a_j\|}{\min_j\|a_j\|}
$$

Es $O(\text{nnz})$ y sin SVD, lo cual es la virtud buscada. Pero **es una cota inferior de
$\kappa_2(A)$**, y puede ser arbitrariamente mala cuando las columnas son casi colineales
—que es la situación normal en este problema, porque celdas vecinas producen respuestas
casi idénticas. Se usa como disparador de una salvaguarda con umbral $10^{12}$
(`exploration/gravimetry.py:2757-2760`), de modo que **puede no dispararse en sistemas
genuinamente mal condicionados**.

El código sí es honesto en el caso indeterminado: devuelve `None` cuando todas las columnas
son nulas, «que es "no se puede estimar", no "está sano"»
(`exploration/potential_field_core.py:548-549`).

---

## 9. Determinismo y reproducibilidad

Éste es un apartado donde el proyecto está claramente por encima de la media.

**Orden de acumulación fijo.** El ensamblado paralelo lanza tareas por sensor y las recoge
**en orden de índice**, no por orden de finalización
(`exploration/gravimetry.py:897-904`), con el comentario «deterministic triplets». Es
imprescindible: la suma en coma flotante no es asociativa, y un orden variable produciría
matrices distintas bit a bit entre ejecuciones.

**Contrato de identidad byte a byte.** Existen dos arneses
(`scripts/validation/fase7_byte_identity.py`, 31 casos;
`scripts/validation/fase8_byte_identity.py`) que comparan **SHA-256 sobre los bits de los
`float64`** tras mover código. El módulo compartido declara el contrato: cada función
reproduce la aritmética original «en el mismo orden», no una versión "equivalente", y «si
se cambia el orden de una multiplicación, el hash cambia y el arnés lo dice»
(`exploration/potential_field_core.py:35-38`).

Reconocer explícitamente que la reasociación en coma flotante **no** es una
transformación neutra, y construir una red que lo verifique, es una disciplina poco común.

**Semillas fijas** en los componentes estocásticos: `seed=0` en Hutchinson
(`exploration/gravimetry.py:258`), `seed=42` en el checkerboard
(`exploration/checkerboard_test.py:299`). Buena para reproducibilidad; problemática como
metodología estadística (informe 12, §4.4).

---

## 10. La superficie de configuración

El backend expone **42 variables de entorno**, censadas por AST en un test de CI que falla
si aparece una nueva sin declarar (`.github/workflows/ci.yml`, paso de guardas). Es un
mecanismo inusual y valioso: convierte la configuración en algo **inventariado** en lugar
de disperso.

Las relevantes para el cómputo (`core/config.py:216-244`):

| Variable | Por defecto | Efecto |
|---|---|---|
| `USE_BOUNDED_SOLVER` | `True` | TRF con bounds — **sólo actúa por debajo de 8.000 celdas** |
| `USE_PROJECTED_SOLVER` | `True` | GPCG proyectado tras LSQR/LSMR |
| `USE_LSMR_LARGE` | `True` | LSMR por encima del umbral |
| `LSMR_THRESHOLD_N_ACTIVE` | `50000` | el umbral |

Dos notas de honestidad que el código incorpora tras medir:

- El comentario de `USE_BOUNDED_SOLVER` declara el **límite** de la perilla: «sólo decide
  por debajo de 8.000 celdas activas. Por encima —el régimen normal del producto— el solver
  usa LSQR+clip esté como esté» (`core/config.py:219-221`).
- El de `USE_PROJECTED_SOLVER` declara **el coste de usar el rollback**: apagarlo llevó el
  $\chi^2$ de 0,244 a 22,7, un factor 93. «No es una preferencia de solver, es la diferencia
  entre ajustar el dato y no ajustarlo» (`core/config.py:229-232`).

Y hay una lección de parseo que merece registro: se midió que `USE_BOUNDED_SOLVER=0` **no**
hacía rollback porque el parser sólo reconocía la cadena exacta `"false"`, y que
`TQ_AUTH_ENABLED=` (vacío) **activaba** la autenticación (`core/config.py:58-80`). La regla
nueva —vocabulario conocido, o el arranque falla nombrando la variable— es la correcta:
«Un flag de seguridad no se adivina.»

---

## 11. Resumen técnico

### Correctamente implementado

- Ensamblado disperso por tripletas con coalescencia única.
- Salvaguarda de memoria basada en dispersión **estimada sin materializar**, con criterio
  correcto (densidad, no tamaño) y degradación segura.
- Paralelismo por hilos donde NumPy libera el GIL, sin estado mutable compartido.
- Caché de geometría con validación exacta y eficacia **observable**.
- Poda del dominio antes de ensamblar.
- Métodos de Krylov que no forman las ecuaciones normales.
- `float64` uniforme, pisos numéricos sistemáticos, rechazo explícito de NaN.
- $\varepsilon$ de anti-singularidad proporcional a la escala del vóxel.
- Determinismo por orden de acumulación fijo y contrato de identidad byte a byte.
- Superficie de configuración inventariada por AST con guarda de CI.
- Eliminación de dependencias y código especulativo tras medir que no aportaban.

### Parcialmente implementado

- **Out-of-core**: existe, está probado, usa scheduler síncrono y **no tiene llamador en
  producción**.
- **Restricciones de caja**: exactas sólo por debajo de 8.000 celdas.

### Problemas detectados

1. **El cutoff de 800 m no produce dispersión** en el régimen de malla fina: $\bar k$ es
   mayor que el modelo entero. La matriz es efectivamente densa y sólo la salvaguarda de
   memoria lo contiene.
2. **`estimate_cond_from_columns` es una cota inferior** presentada como estimación de
   condición, y gobierna un disparador.
3. **El coste de la selección automática de $\lambda$ (×5 a ×20) no se comunica.**
4. **`iter_lim=500` nunca se alcanza por tolerancia** (medido: `istop=7` en 500/500), de
   modo que el resultado depende del punto de parada (informe 02).

---

## 12. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Un cutoff que no recorta

**Pregunta.** Con `cutoff_radius = 800` m y celdas de 10 m, el número medio de celdas dentro
del corte por sensor es $\sim2\times10^6$, mayor que el modelo completo: el kernel es
efectivamente denso y el corte no aporta dispersión. ¿Recomendaría escalar el cutoff con el
tamaño de celda o con la profundidad de investigación —por ejemplo, un múltiplo de la
profundidad máxima del modelo— en lugar de una constante absoluta? ¿Y existe una regla
estándar en inversión de campos potenciales?

**Evidencia.** `exploration/gravimetry.py:716` (el valor);
`exploration/gravimetry.py:864-874` (los tres regímenes);
`exploration/gravimetry.py:47-52` (la salvaguarda que existe precisamente por esto).

**Qué NO sabemos.** El error introducido por el truncamiento cuando **sí** actúa. No hay
cota en el repositorio (informe 03).

---

### Pregunta 2 — Estimar la condición sin SVD

**Pregunta.** Se usa $\max_j\|a_j\|/\min_j\|a_j\|$ como estimador de $\kappa$, que es una
cota inferior y puede fallar precisamente con columnas casi colineales. Gobierna una
salvaguarda con umbral $10^{12}$. ¿Qué estimador barato recomendaría en su lugar? Nuestras
candidatas: (a) unos pasos de iteración de potencia sobre $A^\top A$ y sobre su inversa
aproximada; (b) reutilizar los valores de Ritz que LSQR ya produce internamente;
(c) `scipy.sparse.linalg.onenormest` sobre $A$ y $A^{-1}$ aplicado implícitamente.

**Evidencia.** `exploration/potential_field_core.py:541-557`;
`exploration/gravimetry.py:2757-2760`.

**Qué NO sabemos.** Cuánto subestima en la práctica. **Nunca se ha comparado contra una
SVD, ni siquiera en un caso pequeño.** Es un experimento barato y pendiente.

---

### Pregunta 3 — Paralelismo por hilos frente a procesos

**Pregunta.** El ensamblado del kernel usa `ThreadPoolExecutor` con `cpu_count−1` hilos,
apoyándose en que NumPy libera el GIL. ¿Es esa la elección correcta para este patrón —una
tarea por sensor, cada una con arrays de tamaño muy variable— o esperaría mejor escalado
con `multiprocessing` y memoria compartida, dado que las tripletas resultantes hay que
serializar de vuelta? ¿Y le preocuparía el desbalanceo de carga, dado que el número de
vecinos por sensor varía mucho en un levantamiento irregular?

**Evidencia.** `exploration/gravimetry.py:825`, `897-904`.

---

### Pregunta 4 — Out-of-core probado pero no cableado

**Pregunta.** `compute_jacobian_dask` transmite el Jacobiano por lotes a Zarr para no
tenerlo en RAM, está cubierto por tests, usa `scheduler="synchronous"` (sin paralelismo) y
**no tiene llamador en producción**. ¿Recomendaría cablearlo como ruta automática por
encima de cierto tamaño, o eliminarlo por ser capacidad no usada? El proyecto ya eliminó
otras funciones especulativas con ese criterio.

**Evidencia.** `exploration/gravimetry.py:3815`; `requirements.txt:71-76`; ausencia de
llamadores fuera de tests.

---

### Pregunta 5 — El coste oculto de la selección automática de λ

**Pregunta.** Activar `auto_lambda` cuesta entre 5 y 20 solves completos, y combinado con
IRLS se multiplica otra vez, sin que nada lo advierta al usuario. Desde el cálculo
numérico: ¿es aplicable aquí la técnica de resolver la familia completa de problemas de
Tikhonov desde **una única bidiagonalización de Golub–Kahan**, dado que la regularización
está apilada explícitamente en $A$ en lugar de entrar por el parámetro `damp` de LSQR?
¿O habría que reformular el sistema para aprovecharla?

**Evidencia.** `services/geophysics_service.py:3596-3625` (Morozov con el solver real);
`exploration/gravimetry.py:1533-1541` (20 ensayos de la curva-L).

---

### Pregunta 6 — Identidad byte a byte como criterio de refactorización

**Pregunta.** El proyecto verifica sus refactorizaciones numéricas comparando SHA-256 sobre
los bits de los `float64`, exigiendo que el orden de operaciones se preserve exactamente.
Es estricto y ha funcionado. ¿Le parece el criterio adecuado, o demasiado rígido —impide
optimizaciones legítimas como reasociar una suma para vectorizar? ¿Qué criterio intermedio
usaría: tolerancia en ULPs, o identidad exacta sólo en las rutas que deciden?

**Evidencia.** `exploration/potential_field_core.py:35-38`;
`scripts/validation/fase7_byte_identity.py` y `fase8_byte_identity.py` (ambos clasificados
como puertas en `GATES.json`).

---

### Pregunta 7 — Un umbral de rendimiento que cambia la garantía matemática

**Pregunta.** El umbral de 8.000 celdas se eligió por tiempo medido (40 s frente a <0,1 s),
pero determina si el problema con restricciones se resuelve exactamente o se aproxima.
Como práctica en computación científica, ¿le parece aceptable que un parámetro de
rendimiento gobierne una propiedad matemática, siempre que esté documentado? ¿O debería el
sistema **declarar en la salida** qué garantía tuvo esa corrida concreta?

**Evidencia.** `exploration/gravimetry.py:2524-2535`; `core/config.py:219-221`.

**Qué sabemos.** Que el sistema **ya publica** el camino de solver realmente usado
(`_solver_path_usado`, `bounded_usado`, `bounded_pedido`), precisamente tras detectar que
antes reportaba lo que se **pidió** y no lo que **pasó**
(`exploration/gravimetry.py:2536-2551`).

---

*Fin del informe 07. El informe 02 trata los solvers y el condicionamiento en detalle; el
11, la persistencia y el rendimiento de E/S; el 12, la reproducibilidad desde el punto de
vista metodológico.*
