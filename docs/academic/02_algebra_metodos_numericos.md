# INFORME 02 — ÁLGEBRA LINEAL Y MÉTODOS NUMÉRICOS
## Las matrices, los solvers y la estabilidad numérica de TerraQuantum

**Destinatario:** álgebra lineal numérica · métodos iterativos · computación matricial
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `exploration/potential_field_core.py` (completo), `exploration/solver_preconditioned.py` (completo), y las rutinas de ensamblado y despacho de `exploration/gravimetry.py`.

> Este informe se puede leer sin haber leído ningún otro. Repite lo mínimo necesario
> del planteamiento del problema para que las decisiones algebraicas tengan sentido.

---

## 1. El sistema lineal, en detalle completo

Todo el sistema gira alrededor de un único objeto: un sistema lineal sobredeterminado
que se resuelve en el sentido de mínimos cuadrados. Conviene desarmarlo pieza por
pieza, porque cada símbolo tiene un significado físico y unas unidades concretas.

### 1.1 La forma básica $Gm = d$

$$
G\,m \;=\; d
$$

| Objeto | Qué es | Forma | Unidad | Dónde se construye |
|---|---|---|---|---|
| $m$ | incógnita: contraste de densidad de cada celda respecto de la densidad de fondo | $(n,)$ | t/m³ | es la salida del solver |
| $d$ | dato: anomalía de gravedad medida en cada estación | $(p,)$ | m/s² | llega del preprocesamiento |
| $G$ | operador directo: cuánto responde la estación $i$ a una unidad de densidad en la celda $j$ | $(p,n)$ | (m/s²)/(t/m³) | `exploration/gravimetry.py:773` |

**Qué representa cada entrada de $G$.** El elemento $G_{ij}$ es el campo gravitacional
vertical que produciría en el sensor $i$ un prisma rectangular ubicado en la celda $j$
con contraste de densidad unitario. Es puramente geométrico: depende de la posición
relativa sensor–celda y del tamaño de la celda, y **no** depende del modelo. Por eso el
problema es lineal.

**Cómo se construye $G$.** No se calcula la misma fórmula para todos los pares. El
código usa un esquema híbrido en dos regímenes, decidido por un árbol k-dimensional
(`scipy.spatial.cKDTree`) construido sobre los centros de las celdas activas
(`exploration/gravimetry.py:836-837`):

- **Campo cercano** ($r \le 4\,a_{eq}$, con $a_{eq}=\sqrt{dx^2+dy^2+dz^2}$):
  fórmula cerrada de prisma de Nagy (1966), evaluada sobre los 8 vértices con signos
  alternados (`exploration/gravimetry.py:733-770`).
- **Campo lejano** ($4\,a_{eq} < r \le r_{cutoff}$): aproximación de masa puntual,
  $G_{ij} \propto \Delta y_{ij}/r_{ij}^3$ (`exploration/gravimetry.py:872`).
- **Más allá de $r_{cutoff}$** (por defecto 800 m, `exploration/gravimetry.py:716`):
  **contribución exactamente cero**, y la entrada ni siquiera se almacena.

Esa última decisión es la que convierte $G$ de densa a dispersa, y tiene consecuencias
algebraicas que se discuten en §2.2.

### 1.2 Dimensiones reales

Órdenes de magnitud del producto, tomados de los umbrales que el propio código usa
para decidir:

- $p$ (estaciones): decenas a algunos miles.
- $n$ (celdas activas): el código enruta a distintos solvers en 8.000 y en 50.000
  (`exploration/gravimetry.py:2529-2531`), y los comentarios de configuración hablan del
  «régimen normal del producto, 30k–100k vóxeles» (`core/config.py:220-221`).

Es decir: **$p \ll n$**, típicamente por dos o tres órdenes de magnitud.

### 1.3 La consecuencia inmediata: el sistema está subdeterminado

Con $p \ll n$, el rango de $G$ es a lo sumo $p$. El núcleo de $G$ tiene dimensión al
menos $n-p$, y en la práctica más, porque las columnas de $G$ están fuertemente
correlacionadas (celdas vecinas producen respuestas casi idénticas).

Esto significa, sin ambigüedad:

> Existen infinitas distribuciones de densidad que reproducen **exactamente** los mismos
> datos. Elegir una es una decisión del algoritmo, no un descubrimiento sobre la roca.

Todo lo que sigue —regularización, precondicionamiento, bounds— es la maquinaria para
hacer esa elección de forma controlada y, en la medida de lo posible, declarada.

**Nota terminológica.** En la literatura se dice a veces que el sistema es
"sobredeterminado" porque hay más ecuaciones que incógnitas tras apilar los bloques de
regularización. Eso es cierto del **sistema aumentado** (§3), no del problema físico. El
sistema aumentado es sobredeterminado **por construcción**, precisamente para curar la
subdeterminación del original.

---

## 2. Estructura matricial y dispersión

### 2.1 Formato de almacenamiento

$G$ se materializa como `scipy.sparse.csr_matrix` de `dtype=float64`
(`exploration/gravimetry.py:911-915`). El ensamblado se hace por tripletas
(fila, columna, valor) acumuladas por sensor y concatenadas al final
(`exploration/gravimetry.py:906-910`), lo cual evita indexado disperso repetido —el
patrón correcto para construir matrices CSR.

Detalle relevante para la reproducibilidad: el ensamblado es **paralelo pero
determinista**. Se lanzan tareas por sensor a un `ThreadPoolExecutor` y se recogen
**en orden de índice**, no por orden de finalización
(`exploration/gravimetry.py:897-904`). El comentario lo llama explícitamente
«tripletas deterministas». Esto importa: la suma en coma flotante no es asociativa, de
modo que un orden de acumulación variable produciría matrices distintas bit a bit entre
ejecuciones.

### 2.2 El *cutoff* como truncamiento del operador

El radio de corte convierte a $G$ en dispersa. Algebraicamente esto no es un detalle de
implementación: **es una perturbación del operador**. Se está resolviendo
$\tilde G m = d$ con $\tilde G = G - E$, donde $E$ contiene todas las contribuciones
lejanas descartadas.

El campo gravitacional decae como $1/r^2$, de modo que las entradas descartadas son
pequeñas individualmente. Pero son **muchas**: para una malla grande, el número de
celdas más allá del cutoff crece como $r^3$ mientras la contribución individual decae
como $r^{-2}$, de modo que la contribución agregada de una corona esférica crece con
$r$. El truncamiento no es obviamente inocuo, y **no se encontró en el código ninguna
cota del error introducido**: NO DETERMINADO.

El sistema sí registra la tasa de llenado resultante
(`exploration/gravimetry.py:917`) y aborta si el kernel quedó vacío
(`exploration/gravimetry.py:927-931`), pero eso son salvaguardas de ejecución, no
control de error.

### 2.3 Salvaguarda de memoria basada en dispersión, no en tamaño

Una decisión de ingeniería numérica que merece mención positiva. Antes de materializar
la matriz, el código **estima** su número de no-ceros consultando sólo el *conteo* de
vecinos por sensor (`query_ball_point(..., return_length=True)`), sin materializar las
listas de índices (`exploration/gravimetry.py:69-77`). Con ello estima

$$
\text{bytes} \approx \text{nnz} \times 24
$$

(`exploration/gravimetry.py:53`, cota superior por no-cero contando CSR más los arrays
transitorios) y aborta con un error accionable si supera el 60 % de la RAM disponible
(`exploration/gravimetry.py:54`, `exploration/gravimetry.py:88-100`).

Lo notable es el criterio: **no limita el número de vóxeles, limita la densidad del
kernel**. Un kernel disperso de millones de celdas pasa; uno denso de pocas celdas se
detiene (`exploration/gravimetry.py:47-52`). Es la magnitud correcta a vigilar.

Si SciPy es antiguo y no soporta `return_length`, la función devuelve `None` y **no
estima** — degradación segura documentada (`exploration/gravimetry.py:76-78`).

### 2.4 El Laplaciano como matriz

El operador de regularización espacial es un **Laplaciano de grafo** ensamblado en COO
y convertido a CSR (`exploration/gravimetry.py:1291-1401`):

$$
L = W - D,\qquad L_{ij}=w_{ij}\ (i\sim j),\qquad L_{ii}=-\!\!\sum_{j\sim i}w_{ij}
$$

Propiedades algebraicas que se cumplen por construcción:

- **Simétrica**: cada arista se añade en ambas direcciones con el mismo peso
  (`exploration/gravimetry.py:1349-1351`).
- **Filas suman cero** en la malla completa ⇒ $L\mathbf{1}=0$ ⇒ el vector constante está
  en el núcleo.
- **Semidefinida negativa** (con este signo); el código señala que la regularización
  $\|Lm\|^2$ es idéntica a la del Laplaciano estándar $(D-W)$ porque
  $L^2 = (-L_{std})^2 = L_{std}^2$ (`exploration/gravimetry.py:1315-1317`). Correcto.
- **Estructura de banda dependiente del orden F** de indexado
  (`exploration/gravimetry.py:1330-1333`).
- **nnz** $\approx 2\cdot(\text{nº aristas}) + n$, es decir $O(n)$: hasta 7 no-ceros por
  fila en el interior (6 vecinos más la diagonal).

**Un detalle algebraico que la restricción al dominio activo rompe.** El Laplaciano se
construye sobre la malla completa y **después** se recorta:

```python
L_active = L_full.tocsr()[active_cells, :][:, active_cells]
```
(`exploration/gravimetry.py:2233-2235`)

Como la diagonal se calculó antes del recorte contando todos los vecinos
(`exploration/gravimetry.py:1399-1401`), las filas de $L_a$ **ya no suman cero** en las
celdas frontera. En términos algebraicos: $L_a$ deja de ser singular por el modo
constante, y el sistema se comporta como si las celdas eliminadas tuvieran valor cero.
Es una condición de tipo Dirichlet introducida por la operación de indexado. Se
documenta aquí porque afecta al espectro de $L_a$ y, por tanto, al condicionamiento del
sistema aumentado; su discusión física está en el informe 01, §2.7.

---

## 3. El sistema aumentado

### 3.1 Qué se apila

El solver nunca ve $Gm=d$. Ve un sistema apilado verticalmente
(`exploration/gravimetry.py:2440-2441`, `exploration/gravimetry.py:2704-2712`):

$$
A =
\begin{pmatrix}
W_dGW_s\\
\lambda_{sp}L_aW_s\\
\operatorname{diag}(w_{sm})\\
\hline
\text{(bloques opcionales)}
\end{pmatrix}
\in\mathbb{R}^{(p+n+n+\cdots)\times n},
\qquad
b=\begin{pmatrix}W_dd\\ \lambda_{sp}L_am_{ref}\\ w_{sm}\odot t\\ \hline \cdot\end{pmatrix}
$$

y resuelve $\min_{\tilde m}\|A\tilde m-b\|_2^2$ (con cotas, §5).

**Ahora sí es sobredeterminado:** $A$ tiene al menos $p+2n$ filas y $n$ columnas. Más
importante: **$A$ tiene rango columna completo** siempre que $w_{sm,j}>0$ para todo $j$,
porque el bloque diagonal por sí solo ya lo garantiza. De ahí que el problema
regularizado tenga **solución única**, aunque el original no la tenga.

### 3.2 Cómo se apila (detalle de implementación relevante)

Los bloques se combinan con `scipy.sparse.vstack(...).tocsr()`. El orden de apilado es
fijo y el RHS se concatena en el mismo orden (`exploration/gravimetry.py:2704-2712`).

La inyección de bloques externos (acoplamiento de inversión conjunta) valida
explícitamente que el número de columnas coincida y produce un mensaje que dice **qué
hacer** si no coincide (recortar por la máscara del dominio observable), en lugar de
dejar que el `vstack` reviente más abajo
(`exploration/potential_field_core.py:748-755`). Es una buena práctica de programación
matricial: fallar en la frontera, no en el interior.

### 3.3 El precondicionamiento por la derecha

El cambio de variable $m=W_s\tilde m$ con
$W_s=\operatorname{diag}(1/\|\text{col}_j(W_dG)\|)$
(`exploration/potential_field_core.py:341-346`) **normaliza las columnas del bloque de
datos a norma unidad**. Es precondicionamiento por la derecha, o *column equilibration*.

**Por qué es necesario, con números.** El comentario del código lo cuantifica: sin
$W_s$, un $\lambda=3{,}0$ domina los datos unas **14.000×** por las magnitudes SI
involucradas, y se pierde la calibración del sistema
(`exploration/gravimetry.py:2280-2282`). Es un problema de escalado clásico: el kernel
gravitacional en unidades SI produce valores del orden de $G\cdot\rho\cdot V/r^2$, es
decir números minúsculos, mientras la regularización trabaja con números de orden 1.

**Propiedad clave (y su límite).** Un precondicionador por la derecha aplicado a
**todos** los bloques es un cambio de variable puro: no altera el minimizador exacto.
Sólo altera la **trayectoria** del método iterativo. Por tanto:

- si el solver **converge**, $W_s$ es algebraicamente inocuo sobre el resultado;
- si el solver **trunca**, $W_s$ determina dónde se detiene y **sí** cambia el resultado.

El código formaliza esto en `solver_converged` y `declare_functional`
(`exploration/potential_field_core.py:391-403` y `404`), y lo llama por su nombre:
**regularización implícita por parada temprana**. La medición reportada es contundente:
solución exacta invariante a $10^{-11}$, pero solve iterativo con `istop=7` en 500/500
casos y diferencias de 66 %–86 % en el resultado publicado
(`exploration/potential_field_core.py:430-441`).

Éste es, a juicio de esta auditoría, el hallazgo numérico más importante del sistema:
**el resultado que el producto entrega no es el minimizador del funcional que declara
minimizar, sino el punto donde el método de Krylov se detuvo.**

---

## 4. Los solvers: cuáles, cuándo y con qué parámetros

El despacho ocurre en `_lsqr_despachar_solver` (`exploration/gravimetry.py:2504`).

### 4.1 La tabla de decisión real

```
n ≤ 8.000  y  USE_BOUNDED_SOLVER   →  TRF (scipy.optimize.lsq_linear)
n > 50.000 y  USE_LSMR_LARGE       →  LSMR
en cualquier otro caso             →  LSQR + clip
                                       └─ luego, si USE_PROJECTED_SOLVER: GPCG
```
(`exploration/gravimetry.py:2529-2535`; umbrales en `core/config.py:243-244`)

Con los valores por defecto (`USE_BOUNDED_SOLVER=True`, `USE_LSMR_LARGE=True`,
`USE_PROJECTED_SOLVER=True`, `LSMR_THRESHOLD_N_ACTIVE=50000`).

**Discrepancia detectada.** Existe una función `select_solver`
(`exploration/solver_preconditioned.py:34`) que implementa exactamente esta tabla de
decisión y está cubierta por cinco tests
(`tests/test_fase10_solver.py:56-71`). **Producción no la llama.** El despacho real está
escrito en línea dentro de `gravimetry.py`. Verificado por búsqueda en todo el
repositorio: los únicos llamadores de `select_solver` son los tests.

Las dos implementaciones son lógicamente equivalentes hoy, de modo que no hay un error
de comportamiento. Pero **los tests validan una función que el producto no ejecuta**:
si alguien cambiara el despacho en línea, la suite seguiría en verde. Es confianza mal
dirigida.

### 4.2 LSQR — la ruta por defecto

```python
result = lsqr(_G_aug_sm, _d_aug_sm, damp=0.0, iter_lim=500, atol=1e-8, btol=1e-8)
m_tilde = np.clip(result[0], _lb_tilde, _ub_tilde)
```
(`exploration/gravimetry.py:2610-2614`)

**Qué es LSQR.** El algoritmo de Paige & Saunders (1982) para
$\min\|Ax-b\|_2$. Internamente construye una bidiagonalización de Golub–Kahan mediante
productos $Av$ y $A^\top u$, y resuelve el problema proyectado en el subespacio de
Krylov $\mathcal{K}_k(A^\top A, A^\top b)$. Es matemáticamente equivalente a aplicar
gradiente conjugado a las ecuaciones normales, pero **sin formarlas nunca**, lo que
evita elevar al cuadrado el número de condición.

**Por qué es la elección correcta aquí.** $A$ es grande, dispersa y muy mal
condicionada. Formar $A^\top A$ sería catastrófico: $\text{cond}(A^\top A)=\text{cond}(A)^2$,
y con $\text{cond}(A)\sim10^{5.5}$ eso da $10^{11}$, al borde de la precisión doble.
El código conoce esta lección y la documenta dos veces
(`exploration/gravimetry.py:2578-2582`, `core/config.py:236-239`), refiriéndose a un
intento previo de solver directo SuperLU sobre ecuaciones normales que además llamaba a
una función inexistente y abortaba con `NameError`. Se eliminó en lugar de repararse.
Decisión correcta.

**Parámetros, uno por uno:**

| Parámetro | Valor | Qué controla |
|---|---|---|
| `damp` | `0.0` | amortiguamiento de Tikhonov **interno** de LSQR. Es cero porque la regularización ya está apilada explícitamente en $A$. Correcto: duplicarla sería regularizar dos veces. |
| `atol`, `btol` | `1e-8` | tolerancias de parada relativas sobre $\|A^\top r\|$ y $\|r\|$. Valores exigentes. |
| `iter_lim` | `500` | tope duro de iteraciones. **Es el parámetro que en la práctica decide.** |
| `conlim` | (por defecto de SciPy, $10^8$) | tope de condición estimada. No se fija explícitamente. |

**El problema del `iter_lim=500`.** El proyecto midió que en la ruta magnética el solver
termina con `istop=7` (límite de iteraciones agotado) en **500 de 500** corridas
(`exploration/potential_field_core.py:434-436`). Es decir: **las tolerancias nunca se
alcanzan; siempre gana el tope**. En esas condiciones, el resultado es una solución
regularizada por parada temprana, cuyo grado de regularización efectivo depende del
precondicionador y del número de iteraciones, no de $\lambda$.

El código **publica** esto: extrae `istop` e `itn` del resultado de LSQR y los expone
(`exploration/gravimetry.py:2615-2621`), con un comentario que dice que publicarlo «es la
diferencia entre "el solver llegó" y "el solver se rindió"». Es honesto y correcto. Lo
que no está resuelto es la decisión de fondo: el valor 500 se documenta en las notas del
proyecto como «DECIDIDO: no se sube».

**El recorte.** `np.clip` tras LSQR proyecta la solución libre sobre la caja. Como se
discute en §5, esa proyección no es el minimizador restringido.

### 4.3 LSMR — para $n>50.000$

`exploration/solver_preconditioned.py:55`, envuelto sobre `scipy.sparse.linalg.lsmr`:

```python
spla.lsmr(G_aug, d_aug, damp=0.0, atol=1e-8, btol=1e-8, conlim=1e10, maxiter=1000)
```
(`exploration/solver_preconditioned.py:86-95`)

**Qué es LSMR.** Fong & Saunders (2011). Usa la misma bidiagonalización de
Golub–Kahan que LSQR, pero aplica MINRES al sistema proyectado en lugar de CG. La
diferencia práctica: LSMR hace **monótonamente decreciente** la norma $\|A^\top r\|$,
mientras que LSQR sólo garantiza monotonía en $\|r\|$. Para un criterio de parada basado
en $\|A^\top r\|$ —que es el criterio natural en mínimos cuadrados— eso hace a LSMR más
predecible.

La justificación escrita en el código es correcta en lo esencial
(`exploration/solver_preconditioned.py:4-7`), aunque contiene un desliz: dice que LSQR
«puede oscilar» en el residuo; en realidad LSQR sí decrece monótonamente en $\|r\|$, y
lo que oscila es $\|A^\top r\|$. La conclusión práctica no cambia.

Nótese que aquí `maxiter=1000` (el doble que LSQR) y `conlim=1e10` sí se fija
explícitamente.

**Discrepancia doc-vs-código.** El docstring del módulo afirma:

> «El precondicionamiento está dado por el cambio de variable W_z formal
> (Li & Oldenburg 1998, H-A0) ya aplicado en G_aug antes de llamar aquí.»
> (`exploration/solver_preconditioned.py:14-15`)

y el de la función repite que el sistema «ya tiene el depth weighting formal W_z
aplicado» (`exploration/solver_preconditioned.py:69-71`). **Esto es falso desde la
Fase 4.** El precondicionador que realmente se aplica es
$\operatorname{diag}(1/\|\text{col}_j(W_dG)\|)$ —ponderación por sensibilidad— y el
propio proyecto demostró algebraicamente que el $W_z$ de Li & Oldenburg se cancelaba
exactamente (`exploration/gravimetry.py:2253-2270`). Los dos docstrings quedaron
desactualizados.

### 4.4 TRF — para $n\le8.000$

```python
lsq_linear(_G_aug_sm, _d_aug_sm, bounds=(_lb_tilde,_ub_tilde),
           method='trf', lsq_solver='lsmr', tol=1e-6, max_iter=300)
```
(`exploration/gravimetry.py:2572-2576`)

*Trust Region Reflective* de SciPy: resuelve genuinamente el problema con restricciones
de caja, con subproblemas resueltos por LSMR. Satisface KKT.

La razón del umbral está medida y escrita: TRF+LSMR tarda ~40 s con nnz≈213.000 y
$n\approx14.000$, frente a <0,1 s de LSQR (`exploration/gravimetry.py:2524-2528`). Es
decir, **el umbral 8.000 es una decisión de rendimiento con consecuencia matemática**:
por encima de él se abandona la garantía KKT del solver principal.

Obsérvese además que `tol=1e-6` aquí es dos órdenes más laxa que el `1e-8` de LSQR.

### 4.5 GPCG proyectado — el refinamiento para $n>8.000$

`solve_inversion_pgd_fista` (`exploration/solver_preconditioned.py:159`). El nombre dice
FISTA; la implementación es **GPCG (Moré & Toraldo 1991)**, y la elección está bien
razonada en el propio código: FISTA puro converge en $O(\sqrt{\kappa})$ iteraciones, lo
que es inviable con $\text{cond}(G^\top G)\sim10^{11}$
(`exploration/solver_preconditioned.py:205-208`).

Estructura, por ciclo externo (hasta `max_outer=6`):

1. **Fase de gradiente proyectado** (20–60 iteraciones) con aceleración de Nesterov y
   **reinicio adaptativo** de O'Donoghue & Candès (2015): si
   $\langle y_k-x_k,\ x_k-x_{k-1}\rangle>0$ se reinicia el momento
   (`exploration/solver_preconditioned.py:224-233`). Sirve para identificar el conjunto
   activo.
2. **Chequeo KKT** por gradiente proyectado en norma infinito, con criterio **relativo**
   al primer valor medido (`exploration/solver_preconditioned.py:255-261`). El código
   justifica correctamente por qué relativo y no absoluto: los bounds en $\tilde m$
   vienen escalados por las normas de columna ($\sim10^6$), de modo que un umbral
   absoluto no sería invariante de escala.
3. **Determinación del conjunto libre**: interior estricto, o en cota con gradiente
   apuntando hacia adentro (`exploration/solver_preconditioned.py:264-267`). Ésta es la
   definición correcta del conjunto libre en optimización con caja.
4. **Solve de Krylov en el subespacio libre**: `lsqr(G_free, r, iter_lim=200)` sobre las
   columnas libres, y actualización recortada (`exploration/solver_preconditioned.py:274-280`).

**El paso.** $\text{step}=1/L$ con $L$ estimada por iteración de potencia sobre
$G^\top G$ e inflada un 5 % «porque power-iter subestima $\sigma_{max}$»
(`exploration/solver_preconditioned.py:194`). Es la salvaguarda correcta: un paso mayor
que $1/L$ rompe la garantía de descenso del gradiente proyectado. El número de
iteraciones de potencia y su criterio de parada están en
`exploration/solver_preconditioned.py:143-156`.

**Garantía estructural.** Se conserva el mejor iterado y nunca se devuelve un punto peor
que el punto de partida caliente (`exploration/solver_preconditioned.py:296-298`). No
garantiza KKT, pero garantiza no empeorar.

**Degradación documentada.** Si $A$ es un `LinearOperator` en lugar de una matriz
dispersa, el paso 4 no es posible (requiere recortar columnas) y el método degrada a
gradiente proyectado puro (`exploration/solver_preconditioned.py:212-213`). Está
declarado.

### 4.6 Gradiente conjugado con precondicionador de Jacobi

Para los sistemas SPD pequeños de las actualizaciones locales
(`exploration/potential_field_core.py:774-788`) y para el operador de suavizado
(`exploration/potential_field_core.py:584-607`) se usa CG con precondicionador diagonal:

$$
M^{-1} = \operatorname{diag}(A)^{-1}, \qquad \text{con piso } 10^{-30}
$$

Es la elección estándar y barata. La matriz es SPD por construcción gracias al término
$\lambda^2I$ (`exploration/potential_field_core.py:789-802`), y los llamadores **exigen**
$\lambda>0$ en lugar de dejar que CG falle a mitad de camino
(`exploration/potential_field_core.py:794-796`). Es la disciplina correcta.

---

## 5. Restricciones de caja: qué garantía da cada ruta

| Ruta | Método | ¿Satisface KKT? |
|---|---|---|
| $n\le8000$ | TRF con bounds | **Sí** |
| $n>8000$, GPCG activo (por defecto) | LSQR/LSMR + clip + GPCG | **Probablemente**, sin verificación publicada |
| $n>8000$, GPCG desactivado | LSQR/LSMR + `np.clip` | **No** |

La proyección $\Pi_{[\ell,u]}(x^*_{libre})$ **no** es en general el minimizador
restringido: el argumento es elemental (el gradiente en el punto recortado no tiene por
qué satisfacer la complementariedad).

El impacto medido de apagar GPCG es grande y está escrito: el $\chi^2$ final pasa de
$0{,}244$ a $22{,}7$, un factor 93 (`core/config.py:229-232`). El propio comentario
concluye: «no es una preferencia de solver, es la diferencia entre ajustar el dato y no
ajustarlo». Se deja la perilla como vía de escape pero se documenta lo que cuesta usarla.
Ésta es exactamente la forma correcta de tratar una bandera peligrosa.

**Lo que falta.** El diccionario `info` de GPCG incluye `converged_by`, `pg_norm`,
`frac_lb_active`, `frac_ub_active`
(`exploration/solver_preconditioned.py:185-187`), es decir, toda la información
necesaria para saber si se alcanzó KKT o se agotaron los ciclos. **No se encontró
ningún análisis agregado de esa estadística sobre corridas reales.** Es una medición
barata y pendiente.

---

## 6. Número de condición: qué se mide realmente

Éste es un punto donde conviene ser preciso, porque el sistema reporta un campo llamado
`cond_A` y ese nombre invita a una lectura que no corresponde.

### 6.1 El estimador barato

```python
def estimate_cond_from_columns(A):
    col_sq = np.array(A.power(2).sum(axis=0)).ravel()
    ...
    return float(np.sqrt(mx / mn))
```
(`exploration/potential_field_core.py:541-557`)

Es decir:
$$
\widehat{\kappa} = \sqrt{\frac{\max_j\|a_j\|^2}{\min_j\|a_j\|^2}}
= \frac{\max_j\|a_j\|}{\min_j\|a_j\|}
$$

**Esto no es el número de condición.** Es la razón entre la mayor y la menor norma de
columna. Su relación con $\kappa_2(A)=\sigma_{max}/\sigma_{min}$ es indirecta:

- $\sigma_{max}\ge\max_j\|a_j\|$, siempre.
- $\sigma_{min}\le\min_j\|a_j\|$, siempre.
- Por tanto $\kappa_2(A)\ \ge\ \widehat{\kappa}$: **el estimador es una cota inferior**.

Y puede ser una cota inferior arbitrariamente mala. El caso patológico es evidente: dos
columnas de norma idéntica pero casi colineales dan $\widehat{\kappa}=1$ mientras
$\kappa_2$ es enorme. Y **columnas casi colineales es exactamente lo que ocurre en este
problema**, porque celdas vecinas producen respuestas casi idénticas.

El código es honesto sobre el coste ($O(\text{nnz})$, sin SVD) y sobre el caso
indeterminado (devuelve `None` cuando todas las columnas son nulas, «que es "no se puede
estimar", no "está sano"», `exploration/potential_field_core.py:548-549`). Pero **no
declara que sea sólo una cota inferior**, y ese matiz importa porque el valor se usa
para tomar decisiones.

### 6.2 Dónde se usa, y por qué importa el matiz

**(a) Adaptación dinámica de $\kappa$.** Si $\widehat\kappa>10^{12}$ y `auto_kappa` está
activo, los pesos fuertes de *padding* y anclaje se reescalan por $10^{12}/\widehat\kappa$
(`exploration/gravimetry.py:2757-2760`). Como $\widehat\kappa$ subestima, **el disparador
puede no activarse en sistemas genuinamente mal condicionados**.

**(b) Restricción de factibilidad en la selección de $\lambda$.** El escáner de $\chi^2$
descarta candidatos con $\text{cond}(A)>10^{12}$ (`exploration/gravimetry.py:1849`). Aquí,
sin embargo, se usa el valor devuelto por **LSQR** (`res[6]`), no el estimador de
columnas. Son dos estimaciones distintas con el mismo nombre en el reporte.

La estimación de LSQR (`acond`) es la condición del sistema **bidiagonal proyectado**
acumulada hasta la iteración de parada. Es más informativa que la razón de normas de
columna, pero tampoco es $\kappa_2(A)$: es una cota inferior que mejora con las
iteraciones, y si el solver se detiene pronto, subestima.

**Conclusión.** El sistema publica un campo llamado "cond" que, según la ruta, es una de
dos cotas inferiores distintas. Ninguna es el número de condición. Un revisor que lea
`cond_A ~ 1e5` podría concluir que el sistema está bien condicionado cuando podría no
estarlo.

---

## 7. Aritmética de punto flotante y salvaguardas numéricas

El código está sembrado de protecciones explícitas. Merecen inventario porque cada una
declara un modo de fallo que alguien encontró.

### 7.1 En el kernel directo

La fórmula de Nagy tiene singularidades logarítmicas y una arcotangente que degenera.
El tratamiento (`exploration/gravimetry.py:733-770`):

| Riesgo | Salvaguarda | Línea |
|---|---|---|
| $r\to0$ cuando el sensor coincide con el centroide | $r=\sqrt{x^2+y^2+z^2+\varepsilon}$ | 758 |
| $\log(0)$ | $\log(\max(\cdot,\varepsilon))$ en vez de $\log(|\cdot|+\varepsilon)$ | 760-761 |
| división por cero en $\arctan(xz/yr)$ con $y\to0$ | `arctan2(xz, yr+ε)` obligatorio | 763 |
| $\varepsilon$ fijo inadecuado a la escala | $\varepsilon = 10^{-10}\cdot\min(dx,dy,dz)$ | 748 |

La última es la más fina: hacer $\varepsilon$ proporcional a la escala del vóxel en lugar
de una constante absoluta. El comentario señala además que `np.minimum` funciona tanto
con escalares (malla uniforme) como con arrays por celda (malla octree), preservando
resultado idéntico en el primer caso (`exploration/gravimetry.py:745-747`).

**Observación.** Inyectar $\varepsilon$ **dentro** del radio ($r=\sqrt{\cdots+\varepsilon}$)
sesga sistemáticamente $r$ hacia arriba. Con $\varepsilon=10^{-10}\cdot\min(d)$ y
$d\sim10$ m, el sesgo es $\sim10^{-9}$ m² bajo la raíz: despreciable frente a
distancias métricas. La elección es segura, pero conviene notar que **no es una
regularización neutra**, es un desplazamiento.

### 7.2 En el resto del sistema

| Salvaguarda | Valor | Dónde |
|---|---|---|
| piso de $\sigma$ | $10^{-30}$ | `potential_field_core.py:136` |
| piso de rango de datos | $10^{-30}$ | `potential_field_core.py:124` |
| piso de normas de columna | $10^{-12}$ | `potential_field_core.py:344` |
| piso al deshacer el cambio de variable | $10^{-12}$ | `potential_field_core.py:281-283` |
| piso de diagonal en Jacobi | $10^{-30}$ | `potential_field_core.py:598`, `781` |
| denominador de misfit relativo | $10^{-30}$ | `potential_field_core.py:820` |
| umbral de dominio observable | $10^{-6}$ relativo | `potential_field_core.py:180-189` |
| `nan_to_num` en curvatura de Menger | 0.0 | `gravimetry.py:1609` |

**Rechazo explícito de NaN.** `resolve_reference_model` valida
`np.isfinite(out).all()` y lanza excepción, con el argumento de que «un modelo de
referencia con NaN envenena el RHS de la suavidad en silencio»
(`exploration/potential_field_core.py:895-896`). Correcto: los NaN se propagan a través
de operaciones matriciales sin error hasta que alguien mira el resultado.

`float64` es obligatorio y explícito en todo el pipeline (`dtype=np.float64` aparece
sistemáticamente). No se encontró ningún cálculo en precisión simple.

### 7.3 Determinismo y reproducibilidad numérica

Dos mecanismos:

- **Orden de acumulación fijo** en el ensamblado paralelo del kernel
  (`exploration/gravimetry.py:897-904`), como se discutió en §2.1.
- **Contrato de identidad byte a byte**: existe un arnés
  (`scripts/validation/fase7_byte_identity.py`, 31 casos) que compara SHA-256 sobre los
  bits de los `float64` resultantes, y el módulo compartido documenta que cada función
  reproduce la aritmética original **en el mismo orden**, no una versión "equivalente"
  (`exploration/potential_field_core.py:35-38`). El comentario advierte: «Si se cambia
  el orden de una multiplicación, el hash cambia y el arnés lo dice».

Esto es una disciplina de refactorización numérica poco común y muy valiosa: reconoce
explícitamente que en coma flotante la reasociación **no** es una transformación neutra.

---

## 8. Complejidad computacional (derivada del código, no supuesta)

### 8.1 Construcción del kernel

- Construcción del cKDTree sobre $n$ centros: $O(n\log n)$
  (`exploration/gravimetry.py:837`).
- Dos consultas de bola por sensor, en lote: $O(p\log n + \text{nnz})$
  (`exploration/gravimetry.py:846-847`).
- Evaluación: por cada par (sensor, celda) dentro del cutoff, o bien 8 evaluaciones de
  la fórmula de Nagy (campo cercano) o una operación aritmética (campo lejano).
  Coste $O(\text{nnz})$ con constante mayor en el cercano.
- **Total: $O(n\log n + \text{nnz})$**, donde
  $\text{nnz}\approx p\cdot\bar{k}$ y $\bar{k}$ es el número medio de celdas dentro del
  radio de corte, $\bar{k}\approx \frac{4}{3}\pi r_{cutoff}^3/(dx\,dy\,dz)$.

Con $r_{cutoff}=800$ m y celdas de 10 m: $\bar{k}\approx 2{,}1\times10^6$ celdas por
sensor — es decir, **el cutoff por defecto no produce dispersión apreciable en mallas
finas**; sólo la produce cuando el dominio es menor que el radio de corte. Esto explica
por qué la salvaguarda de memoria de §2.3 existe y vigila la densidad y no el tamaño.

### 8.2 Coste por iteración de Krylov

LSQR y LSMR hacen **dos productos matriz-vector por iteración** ($Av$ y $A^\top u$), cada
uno $O(\text{nnz}(A))$ donde

$$
\text{nnz}(A) = \underbrace{\text{nnz}(G)}_{\text{datos}} + \underbrace{O(7n)}_{\text{Laplaciano}} + \underbrace{n}_{\text{smallness}}
$$

Con `iter_lim=500`, el coste total del solve es $O(500\cdot\text{nnz}(A))$. Memoria:
$O(\text{nnz}(A) + n)$ — LSQR guarda un puñado de vectores de trabajo, no una base
completa de Krylov.

### 8.3 GPCG

Por ciclo externo: $2\times$(20–60) matvecs en la fase de gradiente proyectado, más un
`lsqr` de hasta 200 iteraciones sobre el subespacio libre (con $\le2\times200$ matvecs
sobre una submatriz), más el recorte de columnas
$G[:,\text{libres}]$, que en CSR **no es barato**: requiere reconstruir la estructura.
Con `max_outer=6`, el coste total puede acercarse al del solve principal.

La estimación de Lipschitz añade unas pocas iteraciones de potencia, cada una con
2 matvecs (`exploration/solver_preconditioned.py:143-156`).

### 8.4 IRLS

Multiplica todo lo anterior por el número de reponderaciones (`compact_max_irls`), ya
que cada iteración reensambla el sistema y vuelve a resolver
(`exploration/gravimetry.py:2762`).

### 8.5 Selección de $\lambda$

- Curva-L: `n_trials` (por defecto 20) solves con `iter_lim=150`
  (`exploration/gravimetry.py:1533-1541`).
- Morozov en producción: 5 candidatos más refinamiento por bisección geométrica, cada
  uno un solve **completo** con el solver real (`services/geophysics_service.py:3596-3625`).

Es decir: **activar la selección automática de $\lambda$ multiplica el coste total por
un factor de entre 5 y 20.** Esto no está declarado al usuario en ninguna parte que se
haya encontrado.

---

## 9. Resumen técnico

### Correctamente implementado

- Elección de métodos de Krylov (LSQR/LSMR) que **no** forman las ecuaciones normales,
  con la razón correcta documentada.
- Precondicionamiento por equilibrado de columnas, con la magnitud del problema que
  resuelve cuantificada (14.000×).
- Reconocimiento explícito y **publicación** de la regularización implícita por parada
  temprana — algebraicamente correcto y comunicativamente honesto.
- GPCG con reinicio adaptativo, paso $1/L$ con margen, criterio KKT relativo invariante
  de escala y garantía de no empeorar.
- Salvaguarda de memoria basada en dispersión estimada sin materializar.
- Ensamblado paralelo determinista y contrato de identidad byte a byte.
- Uso uniforme de `float64` y pisos numéricos sistemáticos.

### Parcialmente implementado

- **Garantía KKT** para $n>8000$: el método es el correcto, pero el presupuesto de
  iteraciones es fijo y su suficiencia no se ha verificado.
- **Estimación de condición**: existe, es barata, es una cota inferior, y no se declara
  como tal.

### No implementado

- SVD o análisis espectral del operador.
- Cota del error introducido por el truncamiento del kernel.
- Análisis agregado de `istop` y `converged_by` sobre corridas reales.

### Riesgos numéricos, ordenados por gravedad

1. **`iter_lim=500` nunca se alcanza por tolerancia** — el resultado publicado depende
   del punto de parada, no del funcional declarado.
2. **`cond_A` no es el número de condición** y se usa para tomar decisiones.
3. **El truncamiento del kernel no tiene cota de error.**
4. **`select_solver` está testeada pero no ejecutada** — confianza mal dirigida.
5. **Dos docstrings de `solver_preconditioned.py` describen un precondicionador que ya
   no existe.**

---

## 10. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Un solver que siempre agota iteraciones

**Pregunta.** LSQR se llama con `atol=btol=1e-8` e `iter_lim=500`, y el proyecto midió
que termina por `istop=7` (tope de iteraciones) en 500 de 500 corridas. Es decir, las
tolerancias no gobiernan nunca: gobierna el tope. En esas condiciones el resultado es
una solución regularizada por parada temprana. ¿Cómo abordaría usted esto? ¿Subir
`iter_lim` hasta converger de verdad, relajar las tolerancias a un valor alcanzable, o
aceptar la parada temprana como regularización deliberada y **documentarla como tal**
(por ejemplo, fijando iteraciones en lugar de $\lambda$)?

**Por qué surge.** Es el hallazgo numérico más consecuente de la auditoría: el sistema
declara minimizar un funcional y entrega otra cosa.

**Evidencia.** `exploration/gravimetry.py:2610-2614` (los parámetros);
`exploration/potential_field_core.py:430-441` (la medición 500/500 y el efecto de
66 %–86 %); `exploration/potential_field_core.py:391-403` (la detección de no
convergencia).

**Qué sabemos.** Que el efecto está medido, que se publica al usuario, y que la
diferencia respecto de la solución exacta densa fue de 54 %–269 % en la prueba
magnética.

**Qué NO sabemos.** Cuántas iteraciones harían falta para converger de verdad con
$\text{cond}(A)\sim10^{5{,}5}$. No se ha corrido nunca sin tope.

**Qué opinión sería útil.** Si la parada temprana es aceptable como regularización en
este contexto (hay literatura que la trata así), saberlo cambiaría la forma de
presentar el resultado. Si no lo es, es la corrección número uno de la lista.

---

### Pregunta 2 — Un estimador de condición que es sólo una cota inferior

**Pregunta.** El sistema reporta `cond_A`, calculado como
$\max_j\|a_j\|/\min_j\|a_j\|$. Esto es una cota **inferior** de $\kappa_2(A)$ y puede ser
arbitrariamente mala precisamente cuando las columnas son casi colineales, que es la
situación normal en este problema. Además se usa como disparador de la adaptación de
$\kappa$ con umbral $10^{12}$. ¿Recomendaría usted sustituirlo por una estimación real
—por ejemplo, unos pocos pasos de iteración de potencia sobre $A^\top A$ y sobre su
inversa, o los valores de Ritz que LSQR ya produce— o considera aceptable la cota
inferior para el propósito de disparar una salvaguarda?

**Evidencia.** `exploration/potential_field_core.py:541-557` (el estimador);
`exploration/gravimetry.py:2757-2760` (su uso como disparador);
`exploration/gravimetry.py:1849` (el uso del `acond` de LSQR en el otro camino).

**Qué sabemos.** Que es $O(\text{nnz})$ y sin SVD, y que el código declara `None` cuando
no puede estimar en lugar de fingir un valor sano.

**Qué NO sabemos.** Cuánto subestima en la práctica. Nunca se ha comparado contra una
SVD, ni siquiera sobre un caso pequeño. **Es un experimento barato y no se ha hecho.**

---

### Pregunta 3 — Truncar el kernel a 800 m sin cota de error

**Pregunta.** Las contribuciones de celdas a más de `cutoff_radius` (por defecto 800 m)
se descartan exactamente. Eso es una perturbación $E$ del operador cuya norma no se
acota en ninguna parte. Dado que el número de celdas en una corona crece como $r^3$
mientras la contribución individual decae como $r^{-2}$, ¿es defendible el truncamiento
duro? ¿Existe una regla estándar para elegir el radio en función del tamaño del dominio
y de la profundidad de investigación, o convendría reemplazarlo por un desarrollo
multipolar del campo lejano?

**Evidencia.** `exploration/gravimetry.py:716` (el valor por defecto);
`exploration/gravimetry.py:864-874` (masa puntual hasta el cutoff, cero después);
`exploration/gravimetry.py:917` (la tasa de llenado que sí se registra).

**Qué sabemos.** Que existe un régimen intermedio de masa puntual, de modo que el salto
no es de Nagy a cero sino de Nagy a masa puntual a cero.

**Qué NO sabemos.** La magnitud del error. NO DETERMINADO — no hay ninguna cota ni
medición en el repositorio.

---

### Pregunta 4 — ¿Basta el presupuesto de GPCG?

**Pregunta.** Para $n>8000$ el problema con restricciones de caja se aborda con GPCG
limitado a 6 ciclos externos, fases de 20–60 iteraciones de gradiente proyectado, y
solves de Krylov de 200 iteraciones en el subespacio libre. Con
$\text{cond}(G^\top G)\sim10^{11}$, ¿esperaría usted que el conjunto activo se estabilice
en 6 ciclos? ¿Y qué diagnóstico usaría para saberlo?

**Evidencia.** `exploration/solver_preconditioned.py:243-244` (los topes);
`exploration/solver_preconditioned.py:205-211` (por qué GPCG y no FISTA);
`exploration/solver_preconditioned.py:185-187` (los campos de diagnóstico disponibles).

**Qué sabemos.** Que el método está activo por defecto, que apagarlo empeora el $\chi^2$
93× (`core/config.py:229-232`), y que existe garantía de no empeorar el punto inicial.

**Qué NO sabemos.** Con qué frecuencia se sale por `max_outer` frente al criterio KKT.
El dato existe (`converged_by`) pero nunca se ha agregado.

---

### Pregunta 5 — Precondicionar por columnas frente a precondicionar por la geometría

**Pregunta.** El precondicionador es el equilibrado de columnas
$\operatorname{diag}(1/\|\text{col}_j\|)$. Es eficaz para el escalado (resuelve un
desbalance de 14.000×) pero **no está diseñado para reducir $\kappa$**: no ataca la casi
colinealidad entre columnas vecinas, que es la fuente real del mal condicionamiento.
¿Recomendaría usted un precondicionador que sí la ataque —por ejemplo, uno basado en el
operador de suavidad, del tipo $(\lambda_{sp}^2L^\top L+\lambda^2I)^{-1/2}$— aunque cueste
más por iteración?

**Por qué surge.** El sistema hace 500 iteraciones sin converger. Un precondicionador
mejor podría cambiar eso, y con ello disolver la Pregunta 1.

**Evidencia.** `exploration/potential_field_core.py:341-346` (el precondicionador
actual); `exploration/gravimetry.py:2280-2282` (los 14.000× que resuelve).

**Qué NO sabemos.** Si el coste de aplicar un precondicionador de suavidad (que
requeriría resolver un sistema por iteración) compensa la reducción de iteraciones. No
se ha estimado.

---

### Pregunta 6 — Una función testeada que producción no ejecuta

**Pregunta.** `select_solver` implementa la tabla de despacho y tiene cinco tests. El
despacho real está escrito en línea en otro archivo y nunca la llama. Hoy son
equivalentes, de modo que no hay error de comportamiento. Como práctica de ingeniería
de software científico, ¿qué peso le daría a este tipo de "test que no toca el camino de
ejecución"?

**Evidencia.** `exploration/solver_preconditioned.py:34` (la función);
`tests/test_fase10_solver.py:56-71` (los tests);
`exploration/gravimetry.py:2529-2535` (el despacho real).

*(Esta pregunta pertenece también al informe 08 y al 12; se incluye aquí porque el
objeto en cuestión es el despacho de solvers.)*

---

### Pregunta 7 — Dos docstrings que describen un precondicionador inexistente

**Pregunta.** El módulo del solver afirma dos veces que el sistema llega con el
*depth weighting* formal de Li & Oldenburg aplicado. La Fase 4 del proyecto demostró
algebraicamente que ese peso se cancela y que el precondicionador real es la ponderación
por sensibilidad. ¿Cómo recomendaría gestionar este tipo de deriva entre documentación y
código en un proyecto científico, donde un docstring equivocado puede llevar a un
revisor a validar algo que no existe?

**Evidencia.** `exploration/solver_preconditioned.py:14-15` y `69-71` (las afirmaciones)
frente a `exploration/gravimetry.py:2253-2270` (la demostración de la cancelación).

---

### Pregunta 8 — El coste oculto de la selección automática de $\lambda$

**Pregunta.** Activar `auto_lambda` multiplica el coste por 5–20 solves completos, y eso
no se comunica al usuario. Desde el punto de vista del cálculo numérico, ¿existe una
alternativa que aproveche el trabajo ya hecho —por ejemplo, reutilizar la
bidiagonalización de Golub–Kahan para evaluar varios $\lambda$ a la vez, que es una
propiedad conocida de los métodos de Krylov con regularización de Tikhonov— en lugar de
re-resolver desde cero para cada candidato?

**Evidencia.** `services/geophysics_service.py:3596-3625` (5 candidatos más bisección,
cada uno un solve completo); `exploration/gravimetry.py:1533-1541` (20 ensayos en la
curva-L).

**Qué sabemos.** Que existe literatura sobre resolver la familia completa de problemas
de Tikhonov desde una única bidiagonalización.

**Qué NO sabemos.** Si es aplicable aquí, dado que los bloques de regularización están
apilados explícitamente en $A$ en lugar de entrar por el parámetro `damp`.

---

*Fin del informe 02. El informe 01 trata la formulación matemática del funcional; el
informe 07 trata la discretización, el paralelismo y el rendimiento; el informe 12 trata
qué significan los diagnósticos numéricos en términos de confianza en el resultado.*
