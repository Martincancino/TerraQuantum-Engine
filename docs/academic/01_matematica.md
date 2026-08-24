# INFORME 01 — MATEMÁTICA
## La matemática que TerraQuantum realmente implementa

**Destinatario:** matemática aplicada · análisis numérico · optimización · teoría de problemas inversos
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa e íntegra de `exploration/potential_field_core.py` (883 líneas) y de las secciones matemáticamente relevantes de `exploration/gravimetry.py` y `services/geophysics_service.py`.

> **Nota de cobertura.** Este informe describe la matemática del motor gravimétrico,
> que es el motor principal y el mejor documentado internamente. El motor
> magnético (`exploration/magnetometry.py`) comparte el mismo núcleo
> (`potential_field_core.py`) pero difiere en una elección clave que se señala en
> §6.4; su auditoría completa está pendiente y así se declara donde corresponde.

---

## 1. De qué tipo de problema matemático estamos hablando

Antes de cualquier fórmula conviene fijar la naturaleza del objeto.

TerraQuantum resuelve un **problema inverso lineal discreto y mal planteado**
(*discrete linear ill-posed problem*). Los tres adjetivos importan:

- **Lineal**: la relación entre la propiedad física buscada (contraste de densidad)
  y el dato medido (anomalía de gravedad) es exactamente lineal. Esto no es una
  aproximación conveniente: la ley de gravitación de Newton es lineal en la densidad,
  de modo que el operador directo es genuinamente un operador lineal. Es una ventaja
  enorme respecto de, por ejemplo, la inversión sísmica.

- **Discreto**: el subsuelo continuo se reemplaza por un número finito de celdas
  (vóxeles), cada una con densidad constante. El problema pasa de ser una ecuación
  integral de Fredholm de primera especie a un sistema matricial finito.

- **Mal planteado** (*ill-posed*, en el sentido de Hadamard): la solución **no es
  única** y **no depende de forma continua de los datos**. Ésta es la dificultad
  central, y no es un defecto de la implementación: es una propiedad del problema
  físico. El informe la trata como el objeto matemático principal, no como una nota
  al pie.

### 1.1 El origen continuo

El punto de partida teórico es la ecuación integral

$$
d(\mathbf{r}_s) \;=\; \int_{\Omega} K(\mathbf{r}_s, \mathbf{r})\, \rho(\mathbf{r})\, dV
$$

donde $d$ es el dato medido en la posición del sensor $\mathbf{r}_s$, $\rho$ es la
función de contraste de densidad definida sobre el dominio $\Omega \subset \mathbb{R}^3$,
y $K$ es un núcleo (*kernel*) que depende sólo de la geometría.

Ésta es una **ecuación de Fredholm de primera especie**. Su patología es clásica y
bien conocida: el operador integral es compacto, sus valores singulares decaen a
cero, y por tanto su inversa **no está acotada**. En términos prácticos: dos
distribuciones de densidad arbitrariamente distintas pueden producir datos
arbitrariamente parecidos. Ningún algoritmo puede deshacer eso; sólo puede elegir,
entre las infinitas soluciones compatibles, una según un criterio adicional.

**Todo lo demás en este informe es, en el fondo, la descripción de ese criterio
adicional.**

### 1.2 La discretización

El código sustituye la integral por una suma sobre celdas:

$$
d_i \;=\; \sum_{j=1}^{n} G_{ij}\, m_j , \qquad i = 1,\dots,p
$$

con:

| Símbolo | Significado | Dimensión | Unidad |
|---|---|---|---|
| $m \in \mathbb{R}^{n}$ | vector de contraste de densidad por celda | $n$ = nº de celdas activas | t/m³ |
| $d \in \mathbb{R}^{p}$ | vector de anomalías observadas | $p$ = nº de estaciones | m/s² (SI interno) |
| $G \in \mathbb{R}^{p \times n}$ | matriz del operador directo | $p \times n$ | (m/s²)·(m³/t) |

La construcción de $G$ es puramente geométrica y se describe en el informe 02 (como
objeto algebraico) y en el informe 03 (como objeto físico). Aquí sólo importa lo
matemáticamente esencial: **$G$ no depende de $m$**. Es una matriz fija una vez
elegida la malla y las posiciones de los sensores. Esto es lo que hace el problema
lineal.

Evidencia: la matriz se ensambla en
`exploration/gravimetry.py:773` (`_build_sparse_kernel`) y se devuelve como
`scipy.sparse.csr_matrix` de forma `(n_obs, n_active)` y `dtype=float64`
(`exploration/gravimetry.py:911-915`).

### 1.3 El orden de índices: una convención con consecuencias

El vector $m$ es una reordenación (*flattening*) de una malla tridimensional
$n_x \times n_y \times n_z$. El código usa **orden Fortran** de forma explícita y
sistemática:

```python
idx_grid = np.arange(self.total_voxels).reshape((self.nx, self.ny, self.nz), order="F")
```
(`exploration/gravimetry.py:1330-1333`)

El comentario del propio código advierte que el orden F es *obligatorio* y que los
pesos deben ravelarse en el mismo orden para que el peso $k$ corresponda a la arista
$k$ (`exploration/gravimetry.py:1345-1348`).

Matemáticamente el orden es irrelevante (es una permutación $P$, y $PGP^{-1}$
representa el mismo operador). Prácticamente **no lo es**, porque determina la
estructura de banda de la matriz del Laplaciano y, por tanto, el patrón de dispersión
y el coste de las operaciones. Y sobre todo: un desajuste de orden entre dos módulos
produce un modelo transpuesto sin ningún error visible. Este proyecto ya sufrió un
caso documentado de ejes permutados al exportar (informe 11).

---

## 2. El funcional que realmente se minimiza

Ésta es la sección central del informe. Se escribe el funcional **tal como lo
ensambla el código**, no como aparecería en un artículo.

### 2.1 Los pesos de dato: la matriz $W_d$

Antes del funcional hay una decisión estadística. Cada observación $d_i$ recibe una
desviación estándar estimada $\sigma_i$, y se define

$$
W_d = \operatorname{diag}\!\left(\frac{1}{\sigma_1},\dots,\frac{1}{\sigma_p}\right)
$$

(`exploration/gravimetry.py:2215`).

Hay **dos** modos de obtener $\sigma$, y cuál se usa depende de una comparación de
igualdad de flotantes contra un valor centinela:

**Modo paramétrico** (cuando el usuario declara su ruido):
$$
\sigma_i = \max(\text{noise\_floor},\; \text{noise\_pct}\cdot|d_i|)
$$

**Modo adaptativo** (cuando no lo declara — el centinela `(0.02, 0.02)`):
$$
\sigma_i = \max\big(0.02\,|d_i|,\; 0.01 \cdot \text{rango}(d)\big)
$$
(`exploration/potential_field_core.py:130`)

con detección opcional de atípicos por MAD:
$$
\text{atípico}_i \iff |d_i - \operatorname{med}(d)| > 3 \cdot 1.4826 \cdot \operatorname{MAD}(d)
$$
y, si los hay, el rango se calcula con percentiles $p_5$–$p_{95}$ en lugar de
mín–máx, y los atípicos se **des-pesan multiplicando su $\sigma$ por 10**
(`exploration/potential_field_core.py:113-134`).

**Comentario matemático.** El factor $1.4826$ es el conocido estimador consistente de
la desviación estándar a partir de la MAD bajo normalidad
($1/\Phi^{-1}(0.75) \approx 1.4826$). El uso de MAD es una elección robusta correcta.
Ahora bien, el des-peso $\times 10$ es **heurístico y el propio código lo declara así**
(`exploration/potential_field_core.py:96-98`). No corresponde a ningún estimador M
estándar (Huber, Tukey), y su efecto sobre la distribución del residuo no está
caracterizado.

**Problema detectado (menor pero real).** El despacho entre ambos modos es una
comparación de igualdad exacta entre números de punto flotante:

```python
if noise_floor == SIGMA_SENTINEL[0] and noise_pct == SIGMA_SENTINEL[1]:
```
(`exploration/potential_field_core.py:150`)

Un usuario que declare de buena fe un piso de ruido de exactamente `0.02` obtiene el
modo adaptativo sin ningún aviso. El código reconoce el riesgo y lo centraliza en un
único sitio precisamente por eso (`exploration/potential_field_core.py:144-149`), lo
cual mitiga la duplicación pero no elimina la ambigüedad semántica: **`0.02` significa
dos cosas distintas**.

### 2.2 El cambio de variable (precondicionamiento por la derecha)

El código **no resuelve en $m$**. Resuelve en una variable escalada $\tilde{m}$
definida por

$$
m = W_s\,\tilde{m}, \qquad
W_s = \operatorname{diag}\!\left(\frac{1}{\|\,\text{col}_j(W_d G)\,\|_2}\right)
$$

(`exploration/potential_field_core.py:341-346`, `exploration/gravimetry.py:2286-2289`).

Es decir: cada columna del kernel ponderado se normaliza a norma unidad. La cota
inferior `1e-12` evita división por cero (`exploration/potential_field_core.py:344`).

Esta es una de las decisiones más importantes de todo el sistema, y el proyecto la
identificó por medición y no por diseño. La razón se explica más abajo (§2.5), pero
la formulación conviene fijarla aquí porque **el funcional se escribe en $\tilde{m}$**.

### 2.3 El sistema aumentado, bloque a bloque

El solver resuelve un problema de mínimos cuadrados **sin restricciones de igualdad**
sobre un sistema apilado:

$$
\min_{\tilde m} \;\;
\left\|
\begin{pmatrix}
W_d G W_s \\[2pt]
\lambda_{sp} L_a W_s \\[2pt]
\operatorname{diag}(w_{sm}) \\[2pt]
\sqrt{\alpha}\,I \;\;(\text{opcional}) \\[2pt]
B_k W_s \;\;(\text{opcional})
\end{pmatrix}
\tilde m
-
\begin{pmatrix}
W_d d \\[2pt]
\lambda_{sp} L_a m_{ref} \\[2pt]
w_{sm} \odot t \\[2pt]
\sqrt{\alpha}\, m_{ref} \\[2pt]
b_k
\end{pmatrix}
\right\|_2^2
$$

Evidencia del apilado: `exploration/gravimetry.py:2440-2441` (bloques de datos y
suavidad), `exploration/gravimetry.py:2704-2712` (bloque de *smallness* con pesos
$w_{sm}$ y su lado derecho), `exploration/gravimetry.py:2392-2402` (bloque
$\sqrt{\alpha} I$ del prior geológico), `exploration/potential_field_core.py:735-756`
(inyección de bloques externos $B_k$).

Traducido a espacio físico $m = W_s\tilde m$, el funcional es:

$$
\boxed{
\Phi(m) \;=\;
\underbrace{\big\|W_d(Gm - d)\big\|_2^2}_{\text{misfit}}
\;+\;
\underbrace{\lambda_{sp}^2\big\|L_a(m - m_{ref})\big\|_2^2}_{\text{suavidad}}
\;+\;
\underbrace{\lambda_{ef}^2\sum_j \big(\|\text{col}_j(W_dG)\|\,m_j\big)^2}_{\text{\emph{smallness} ponderada por sensibilidad}}
}
$$

más los términos opcionales. Cada término merece su propia lectura.

### 2.4 Término 1 — el misfit

$$
\Phi_d(m) = \|W_d(Gm-d)\|_2^2 = \sum_{i=1}^{p}\left(\frac{(Gm)_i - d_i}{\sigma_i}\right)^2
$$

**Qué es matemáticamente.** La suma de residuos estandarizados al cuadrado. Bajo el
supuesto de ruido gaussiano independiente $\varepsilon_i \sim N(0,\sigma_i^2)$, esto
es exactamente $-2\log$ de la verosimilitud, salvo constante. Minimizarlo solo es
estimación de máxima verosimilitud.

**Qué significa su valor.** El código publica la versión reducida
$$
\chi^2_{red} = \frac{\Phi_d}{p}
$$
(`exploration/gravimetry.py:1846-1847`). Si el modelo de ruido es correcto y el
modelo físico también, $\chi^2_{red} \approx 1$. Valores $\gg 1$ indican subajuste
(o $\sigma$ subestimado); valores $\ll 1$ indican sobreajuste al ruido (o $\sigma$
sobreestimado).

**Advertencia importante y declarada por el propio código.** Cuando $\sigma$ viene del
modo adaptativo, $\chi^2$ **no es físicamente interpretable**, porque $\sigma$ se
calibró con la amplitud del propio dato y no con el error instrumental. El sistema lo
reconoce explícitamente y cambia de estrategia de regularización según este hecho
(`services/geophysics_service.py:3196-3199`). Esto está bien resuelto y es honesto.

### 2.5 Término 3 — la *smallness*, y por qué no es lo que su nombre sugiere

Éste es el punto matemáticamente más sutil del sistema, y merece desarrollo completo.

En el sistema aumentado, el bloque de *smallness* es **la identidad en $\tilde m$**:
el residuo de esa fila es $w_{sm,j}(\tilde m_j - t_j)$. Si uno sólo mira el sistema
escalado, parece una regularización de norma mínima ordinaria, $\|\tilde m\|^2$.

Pero $\tilde m$ no es el modelo físico. Deshaciendo el cambio de variable,
$\tilde m_j = m_j / (W_s)_{jj} = \|\text{col}_j(W_dG)\|\, m_j$, y por tanto

$$
\|\tilde m\|_2^2 = \sum_j \Big(\|\text{col}_j(W_dG)\|\; m_j\Big)^2
$$

Es decir: **no se penaliza la magnitud del modelo, se penaliza la magnitud del modelo
ponderada por su sensibilidad**. Una celda a la que los sensores son muy sensibles
(columna de norma grande) se penaliza mucho; una celda profunda o lejana, a la que
los datos apenas responden, se penaliza poco.

El código documenta esto explícitamente en un comentario extenso
(`exploration/gravimetry.py:2253-2278`) que además narra un error histórico
instructivo: existía un bloque titulado *"W_z formal (Li & Oldenburg 1998)"* que
pretendía implementar el *depth weighting* estándar con un parámetro `depth_beta`, y
la medición demostró que **no hacía nada**. La demostración algebraica es de tres
líneas y vale la pena reproducirla porque es correcta:

$$
W_z^{-1} = \operatorname{diag}\big((z+z_0)^{\beta/2}\big), \qquad
W_s = \operatorname{diag}\!\left(\frac{1}{\|\text{col}_j(G_w W_z^{-1})\|}\right)
= \operatorname{diag}\!\left(\frac{1}{w_j\|\text{col}_j(G_w)\|}\right)
$$
$$
\Longrightarrow\quad W_z^{-1}W_s = \operatorname{diag}\!\left(\frac{1}{\|\text{col}_j(G_w)\|}\right)
$$

El $w_j$ **se cancela exactamente**. Como $W_s$ se calculaba *después* de aplicar
$W_z$, deshacía justo lo que $W_z$ acababa de hacer. Medido a precisión de máquina:
$1.7\times10^{-16}$.

**Qué se hace ahora.** El sistema mide, para cada corrida y sobre su propia malla, a
qué exponente de Li & Oldenburg equivale de hecho la ponderación por sensibilidad,
ajustando una ley de potencia en escala log-log:

$$
u_j = \frac{1}{(W_s)_{jj}}, \qquad
\beta_{eq} = -2\cdot \text{pendiente}\big(\log u \;\text{vs}\; \log(z+z_0)\big)
$$
(`exploration/potential_field_core.py:283-315`)

y publica también la desviación relativa máxima respecto de esa ley de potencia
(`exploration/potential_field_core.py:308-311`). El valor medido de referencia es
$\beta_{eq}\approx 2{,}63$ con desviación máxima $5{,}3\%$
(`exploration/potential_field_core.py:290-296`).

**Lectura matemática honesta.** La ponderación por sensibilidad **es** un
*depth weighting* efectivo, de la misma familia que el estándar industrial $\beta=2$
y algo más agresiva. El problema que el proyecto identifica no es que la forma sea
mala: es que **no es ajustable y no es una decisión** — la fija el kernel. Esto tiene
una consecuencia que un revisor debería sopesar: no hay ninguna perilla para
controlar el compromiso entre resolución superficial y penetración en profundidad.

### 2.6 El teorema del "cambio de variable puro"

El código formaliza una observación algebraica que gobierna todo el comportamiento
del sistema, y que está enunciada en `exploration/potential_field_core.py:29-33` y
codificada en `declare_functional` (`exploration/potential_field_core.py:404`):

> Un peso de modelo $W$ que multiplica **todos** los bloques del sistema aumentado es
> un cambio de variable puro y **no cambia la solución física**; sólo actúa si algún
> bloque queda **sin** él.

La justificación es inmediata. Si todos los bloques son $A_kW$ y se minimiza
$\sum_k\|A_kW\tilde m - b_k\|^2$, entonces con $m = W\tilde m$ el problema es
$\sum_k\|A_km-b_k\|^2$, cuyo minimizador no depende de $W$ (si $W$ es invertible).

Éste es un resultado correcto y es, además, la explicación unificada de un
comportamiento que antes parecía caprichoso: el mismo parámetro `depth_beta` actuaba
o no según si el *padding* estaba activo, porque eso determinaba si algún bloque
quedaba sin $W$ (`exploration/potential_field_core.py:15-21`).

**Y aquí viene el matiz que hace bueno al análisis.** El código no se detiene en el
álgebra. Observa que $W$ es también un **precondicionador por la derecha**, y que un
precondicionador sólo es inocuo *si el solver converge*. Si el solver se detiene por
límite de iteraciones, $W$ cambia **dónde** se detiene, y por tanto sí afecta al
resultado:

> «la solución EXACTA (`lstsq` denso) es invariante en $\beta$ a $10^{-11}$ […] pero
> el solve iterativo termina con `istop=7` en 500/500 para todo $\beta$, y queda a
> 54 %–269 % de la exacta. Mover $\beta$ de 0,5 a 3,0 cambia la susceptibilidad
> recuperada un **66 %–86 %**.»
> (`exploration/potential_field_core.py:430-441`)

En consecuencia, la función declara `depth_beta_has_effect=True` con
`effect_mechanism="early_stopping"` en ese caso
(`exploration/potential_field_core.py:465-470`). Es **regularización implícita por
parada temprana**, un fenómeno bien conocido en métodos de Krylov, correctamente
identificado y —lo que es más raro— correctamente comunicado al usuario.

### 2.7 Término 2 — la suavidad, y el operador $L$

$$
\Phi_{sp}(m) = \lambda_{sp}^2\,\|L_a(m-m_{ref})\|_2^2
$$

El operador $L$ se construye en `exploration/gravimetry.py:1291` como un
**Laplaciano de grafo**:

$$
L = W - D, \qquad
L_{ij} = w_{ij}\;(i\sim j), \qquad
L_{ii} = -\sum_{j\sim i} w_{ij}
$$

con $w_{ij}=1$ en malla uniforme y $w_{ij} = 2/(h_i+h_j)$ en malla no uniforme —el
inverso de la distancia entre centros de celda— (`exploration/gravimetry.py:1358-1381`).
No hay *wrap-around*: las aristas sólo conectan vecinos reales de la malla.

Cuatro observaciones matemáticas, en orden de importancia:

**(a) La penalización es de cuarto orden, no de segundo.**
El término es $\|Lm\|^2 = m^{\top}L^{\top}Lm = m^{\top}L^2m$ (por simetría de $L$).
El operador que aparece en las ecuaciones normales es $L^2$, un operador **de tipo
bi-armónico**. Esto **no** es la regularización de suavidad estándar de Li &
Oldenburg, que usa operadores de **primera** diferencia $\partial_x,\partial_y,\partial_z$
y penaliza $\|\nabla m\|^2$. La diferencia es sustantiva: penalizar la curvatura al
cuadrado favorece soluciones más suaves (de clase superior) y tiene un núcleo mayor.
El código cita a Li & Oldenburg 1998 como referencia (`exploration/gravimetry.py:1319`)
pero **implementa un operador distinto del de esa referencia**. Ésta es una
discrepancia real entre la cita y la implementación, y es la primera pregunta del §9.

**(b) El núcleo de $L$ contiene las constantes.**
Como las filas de $L$ suman cero por construcción, $L\mathbf{1}=0$. Un desplazamiento
uniforme de densidad **no es penalizado en absoluto** por el término de suavidad. Sólo
la *smallness* lo controla. En un problema donde el nivel de referencia absoluto ya es
notoriamente mal determinado por la gravimetría, esto merece atención.

**(c) La restricción al dominio activo introduce una condición de contorno no
declarada.** Éste es un hallazgo de esta auditoría y no aparece documentado en el
código. La secuencia es:

```python
L_full   = self._build_laplacian(hx, hy, hz)          # sobre la malla COMPLETA
L_active = L_full.tocsr()[active_cells, :][:, active_cells]
```
(`exploration/gravimetry.py:2233-2235`)

La diagonal de `L_full` se calculó contando **todos** los vecinos de la malla
completa (`exploration/gravimetry.py:1399-1401`). Al recortar filas y columnas, se
eliminan las entradas fuera de la diagonal que apuntaban a celdas inactivas, **pero
la diagonal conserva su peso**. Consecuencia:

$$
L_a\mathbf{1} \;=\; -\!\!\sum_{j \notin \text{activas}} w_{ij} \;\neq\; 0
\quad\text{en las celdas frontera}
$$

Es decir: el operador restringido se comporta como si las celdas inactivas
(aire sobre la topografía, celdas podadas por falta de sensibilidad) tuvieran
**contraste cero**. Es una **condición de Dirichlet homogénea implícita** en el borde
del dominio activo.

Físicamente el valor 0 es defendible (contraste cero = densidad de fondo). Pero es un
supuesto que nadie eligió: emerge de la operación de *slicing*. Y tiene un efecto
real: la regularización tira activamente el modelo hacia la densidad de fondo justo
bajo la topografía y en el borde del dominio observable, que son precisamente las
zonas donde uno querría dejar que el dato hable.

**(d) El escalado de $\lambda_{sp}$ es dependiente de la malla.**
$$
\lambda_{sp} = \alpha_{sp}\cdot\frac{p}{n}
$$
(`exploration/gravimetry.py:2355`). El propio servicio advierte que para mallas
grandes con pocos sensores este cociente puede ser $\lll 1$, reduciendo la
regularización espacial casi a nada, y emite un aviso si $\lambda_{sp}<10^{-4}$
(`services/geophysics_service.py:3229-3239`). El aviso es correcto; la elección de
normalizar por $p/n$ no está justificada en ninguna referencia citada.

### 2.8 La calibración $\sqrt{n/256}$

El peso de la *smallness* no es $\lambda$ sino

$$
\lambda_{ef} = \lambda\cdot\sqrt{\frac{n}{256}}
$$
(`exploration/gravimetry.py:2432-2434`), con `_N_CALIB = 256` fijado como constante
literal.

**Interpretación matemática.** La *smallness* aporta $n$ filas al sistema mientras que
el misfit aporta $p$. Sin corrección, el peso relativo de la regularización crecería
con el tamaño de la malla simplemente por contar más filas. Escalar por $\sqrt{n}$
mantiene aproximadamente constante la **contribución total** del término al funcional
($n$ términos de tamaño $\lambda_{ef}^2 \propto \lambda^2 n$ ... nótese que esto de
hecho *aumenta* la contribución linealmente en $n$, no la mantiene constante).

**Problema detectado.** El valor 256 es un número de calibración empírico sin
derivación. El comentario lo atribuye a "H-A0 Bug 2" y dice "calibrado a N_CALIB=256"
(`exploration/gravimetry.py:2430-2431`), sin explicar contra qué. Un $\lambda$ que el
usuario elija tiene, por tanto, un significado que depende de una constante mágica.

---

## 3. La elección del parámetro de regularización $\lambda$

Matemáticamente, $\lambda$ es lo que selecciona un punto de la curva de compromiso
entre ajuste y estructura. TerraQuantum implementa **tres** métodos, y —esto es
importante— **el que usa en producción no es ninguno de los dos clásicos**.

### 3.1 Curva-L con curvatura de Menger

Implementado en `exploration/gravimetry.py:1416`. Se barre un conjunto logarítmico de
$\lambda$ y para cada uno se registra el par
$\big(\log\|d-Gm\|,\ \log\|\text{col}\odot m\|\big)$. La esquina se detecta con la
**curvatura de Menger** sobre tríos consecutivos:

$$
\kappa_i = \frac{4A_i}{|P_{i-1}P_i|\cdot|P_iP_{i+1}|\cdot|P_{i+1}P_{i-1}|}
$$

donde $A_i$ es el área del triángulo (`exploration/gravimetry.py:1586-1607`). Los ejes
se normalizan a $[0,1]$ antes —correcto, porque la curvatura no es invariante de
escala— y se descartan tríos con algún lado menor que $10^{-3}$ para evitar
denominadores degenerados. Si falla, hay un respaldo de máxima distancia
perpendicular a la recta que une los extremos (`exploration/gravimetry.py:1573`).

La referencia citada (Hansen 2010) es la correcta para este método.

**Dos observaciones críticas.**

1. **La seminorma del eje vertical es la correcta, y esto se corrigió tras un error.**
   El eje de "rugosidad" mide $\|\,\|\text{col}_j\|\odot m\,\|$ — es decir, la seminorma
   del término que $\lambda$ **realmente** penaliza (`exploration/gravimetry.py:1560`).
   El comentario adyacente documenta que antes se medía $\|Lm\|$, penalizada por un
   $\lambda_{sp}$ **fijo que el barrido no varía** (`exploration/gravimetry.py:1552-1559`).
   Una curva-L cuyo eje vertical corresponde a un parámetro que no se mueve no
   significa nada. La corrección es matemáticamente acertada.

2. **Los ensayos usan un solver más débil que la producción.** Cada ensayo corre
   `lsqr(..., iter_lim=150)` (`exploration/gravimetry.py:1541`) mientras que la
   inversión real usa `iter_lim=500` (`exploration/gravimetry.py:2611`). Dado que el
   propio proyecto midió que la parada temprana cambia el resultado hasta un 86 %
   (§2.6), **el $\lambda$ elegido por la curva-L se elige sobre un operador que no es
   el que se usará después**. Es una inconsistencia real.

### 3.2 Principio de discrepancia (Morozov) como diagnóstico

`select_lambda_chi2_target` (`exploration/gravimetry.py:1674`) escanea candidatos y
elige el que minimiza $\big|\log_{10}\chi^2 - \log_{10}\chi^2_{target}\big|$ sujeto a
$\text{cond}(A) < 10^{12}$.

Éste es el principio de discrepancia de Morozov: elegir el mayor $\lambda$ tal que el
residuo no supere el nivel de ruido. La implementación tiene una propiedad honesta
notable: el comentario documenta que este escáner estuvo **midiendo con el funcional
equivocado** durante un tiempo, y cuantifica el daño con una tabla medida
(`exploration/gravimetry.py:1805-1817`):

| Profundidad | $\chi^2$ prometido | $\chi^2$ real | Razón |
|---|---|---|---|
| 150 m | 2,084 | 48,53 | 23× |
| 350 m | 0,444 | 128,5 | 289× |
| 550 m | 0,0724 | 165,7 | 2.290× |
| 750 m | 0,0161 | 204,5 | 12.700× |

y que en 0 de 4 casos eligió el $\lambda$ que el solver real habría elegido. **El error
crece con la profundidad**, que es exactamente donde los dos funcionales más difieren.
Esto está ahora corregido, y el propio código declara que este selector es un
**instrumento de diagnóstico y no la ruta de producción**
(`exploration/gravimetry.py:1826-1829`).

### 3.3 Lo que producción hace de verdad

En `services/geophysics_service.py:3180-3225` la lógica es:

```
si (auto_lambda o lambda_mag == 0):
    si σ es EXPLÍCITO (piso de ruido declarado o gravímetro conocido):
        → Morozov sobre el SOLVER REAL, candidatos logspace(-2, 1, 5)
          = [0.01, 0.05623, 0.31623, 1.77828, 10.0], con refinamiento
            por media geométrica entre corchetes
    si no:
        → λ = PRECONDITIONED_OPERATING_LAMBDA (constante fija)
si no:
    → λ = el que dio el usuario
```

El razonamiento declarado es sólido: con $\sigma$ adaptativo, $\chi^2$ no es
interpretable, luego Morozov no tiene sentido y se recurre a un punto de operación
fijo (`services/geophysics_service.py:3196-3199`).

**Problema detectado — discrepancia entre la constante y su propia justificación.**
El valor es

```python
PRECONDITIONED_OPERATING_LAMBDA = 0.1
```
(`services/geophysics_service.py:72`)

pero la justificación que el mismo código adjunta dice:

> «Preconditioned optimum O(1-10), validated vs synthetic ground-truth
> (lambda~3 -> pearson~0.95)»
> (`services/geophysics_service.py:3213-3216`)

Es decir: **el texto justifica $\lambda\approx3$ y la constante vale $0{,}1$**, un
factor 30 de diferencia, y $0{,}1$ está fuera del rango $O(1\text{–}10)$ que el propio
texto declara óptimo. O la constante está desactualizada, o la justificación lo está.
No se pudo determinar cuál leyendo el código: **NO DETERMINADO**.

---

## 4. Regularización no cuadrática: IRLS y soporte mínimo

Cuando `regularization_norm != "l2"`, el sistema entra en un bucle de **mínimos
cuadrados reponderados iterativamente** (IRLS) para aproximar una penalización no
cuadrática.

### 4.1 El funcional objetivo implícito

Los pesos se calculan como

$$
f_i = \frac{1}{\sqrt{c_i^2+\varepsilon^2}}
$$
(`exploration/potential_field_core.py:571`), donde $c = W_s\tilde m$ es el contraste
**físico** de la iteración anterior (`exploration/gravimetry.py:2794`).

Éste es el esquema clásico de **soporte mínimo** (*minimum support*) de
Last & Kubik (1983) y Portniaguine & Zhdanov (1999), correctamente citados
(`exploration/potential_field_core.py:559-560`). Multiplicar la penalización por
$f_i$ y minimizar equivale, en el límite $\varepsilon\to0$, a penalizar

$$
\sum_i \frac{c_i^2}{c_i^2+\varepsilon^2} \;\xrightarrow[\varepsilon\to 0]{}\; \#\{i: c_i\neq 0\}
$$

es decir, una aproximación suave de la **norma $\ell_0$** — el número de celdas no
nulas. De ahí que produzca cuerpos compactos en lugar de manchas difusas.

### 4.2 Las dos modificaciones respecto del esquema clásico

**Normalización a media 1 sobre celdas libres:**
$$
\hat f = \frac{f}{\operatorname{mean}(f|_{\text{libres}})}, \qquad
\hat f \leftarrow \operatorname{clip}(\hat f, 0.05, 20)
$$
(`exploration/potential_field_core.py:572-574`)

El razonamiento del código —que la normalización conserva la magnitud global de la
regularización y por tanto redistribuye el foco sin degradar el misfit
(`exploration/potential_field_core.py:565-567`)— es correcto en promedio, aunque no es
una identidad exacta.

El **recorte a $[0.05,\,20]$** es una decisión que merece escrutinio: acota el rango
dinámico del foco a 400×. Sin él, una celda con $c_i\to0$ recibiría peso $1/\varepsilon$
y podría dominar el sistema. Con él, el esquema **no puede** alcanzar el límite $\ell_0$
verdadero. Es una elección de estabilidad a costa de fidelidad al funcional objetivo,
y no está declarada como tal.

**Enfriamiento de $\varepsilon$:**
$$
\varepsilon_0 = \max\big(\varepsilon_{floor},\; 0.5\cdot p_{90}(|c|_{\text{libres}})\big),
\qquad
\varepsilon_{k+1} = \max(0.7\,\varepsilon_k,\ \varepsilon_{floor})
$$
(`exploration/potential_field_core.py:576-582` y `exploration/gravimetry.py:2811`),
con $\varepsilon_{floor} = \max(\texttt{compact\_eps},\,10^{-3})$
(`exploration/gravimetry.py:2694`).

Esto es una **homotopía**: se empieza con un problema casi cuadrático y bien
condicionado y se endurece progresivamente hacia el no convexo. Es la estrategia
correcta, y evita el problema conocido de que IRLS con $\varepsilon$ pequeño desde el
inicio quede atrapado en mínimos locales pobres.

### 4.3 Criterio de parada

$$
\delta_k = \frac{\|\hat f_k - \hat f_{k-1}\|}{\|\hat f_k\|} < \texttt{compact\_tol}
$$
(`exploration/gravimetry.py:2799-2812`), con tope `compact_max_irls`.

**Observación matemática.** El criterio mide la convergencia de **los pesos**, no la
del **modelo** ni la del **funcional**. Son cosas distintas: los pesos pueden
estabilizarse mientras el modelo aún se mueve, o al revés. Además, como $\varepsilon$
se enfría en cada iteración, el funcional objetivo **cambia entre iteraciones**; la
sucesión no está minimizando un objetivo fijo, de modo que las garantías de
convergencia monótona de IRLS (que existen para $\varepsilon$ fijo, vía
mayorización-minimización) **no aplican directamente**.

### 4.4 Qué celdas participan

El foco se aplica **sólo** a las celdas "libres": se excluyen las de *padding* y las
ancladas por sondaje, que conservan su papel de restricción fuerte en $\ell_2$
(`exploration/gravimetry.py:2675-2680`). Es una decisión razonable y explícitamente
documentada.

---

## 5. Restricciones de caja y optimización con restricciones

El problema real no es de mínimos cuadrados libres, sino **restringido**:

$$
\min_{\tilde m} \Phi(\tilde m)
\quad\text{sujeto a}\quad
\ell \le \tilde m \le u
$$

Las cotas se derivan del box petrofísico físico $[\rho_{min}, \rho_{max}]$ mediante la
**misma biyección** que recupera la densidad:

$$
\ell_j = (\rho_{min}-\rho_{base})\cdot\|\text{col}_j(W_dG)\|, \qquad
u_j = (\rho_{max}-\rho_{base})\cdot\|\text{col}_j(W_dG)\|
$$
(`exploration/gravimetry.py:2292-2294`). El comentario afirma que la transformación es
exacta, y lo es: la aplicación es diagonal con entradas positivas, luego preserva el
orden componente a componente.

Existe además un **override por unidad litológica**: en celdas con litología conocida,
el box escalar global se sustituye por el box de su unidad
(`exploration/gravimetry.py:2298-2310`), impuesto por un solver que satisface KKT por
celda.

**Comentario matemático.** El conjunto factible es una caja: convexo, cerrado y
acotado. El funcional es convexo cuadrático (en el caso $\ell_2$). Por tanto el
problema **tiene solución y es única** si el sistema aumentado tiene rango columna
completo — lo cual está garantizado por el término de *smallness* siempre que
$\lambda_{ef}>0$. Esto es una propiedad valiosa: la unicidad **del problema
regularizado** se recupera aunque el problema original no la tenga.

Las condiciones KKT para este problema son las de complementariedad estándar:
$$
\nabla\Phi(\tilde m^*)_j
\begin{cases}
= 0 & \text{si } \ell_j<\tilde m^*_j<u_j\\
\ge 0 & \text{si } \tilde m^*_j=\ell_j\\
\le 0 & \text{si } \tilde m^*_j=u_j
\end{cases}
$$

**Problema detectado — no todas las rutas satisfacen KKT.** El despacho de solver
(`exploration/gravimetry.py:2529-2535`) elige según el tamaño:

- $n \le 8000$: `scipy.optimize.lsq_linear` con `method='trf'` → **sí resuelve el
  problema restringido** y satisface KKT.
- $n > 8000$: LSQR **sin restricciones** seguido de `np.clip` → **el recorte posterior
  no satisface KKT**. Es una proyección del minimizador libre sobre la caja, que en
  general **no es** el minimizador restringido.

El propio código lo reconoce: «El clip post-hoc descarta masa fuera del box sin
redistribuir (misfit degradado ~35 % en cuerpos compactos)»
(`exploration/gravimetry.py:2617-2620`), y por eso añade una etapa de **gradiente
proyectado acelerado** con el recorte como punto inicial caliente, que sí converge al
óptimo restringido para problemas convexos.

**Esta etapa está activa por defecto**: `USE_PROJECTED_SOLVER` vale `True`
(`core/config.py:233`). Apagarla se midió y no es inocuo: el $\chi^2$ final pasó de
$0{,}244$ a $22{,}7$ — un factor 93 (`core/config.py:229-232`). Es decir, en la
configuración por defecto **el problema restringido sí se aborda con un método
proyectado**, y la preocupación se traslada de "¿se resuelve?" a "¿converge lo
suficiente?" (§5.1).

Conviene registrar un matiz sobre la otra perilla: `USE_BOUNDED_SOLVER` sólo decide
por debajo de 8.000 celdas activas. Por encima —el régimen normal del producto,
30k–100k vóxeles— el despacho es LSQR+clip **esté la perilla como esté**, y el propio
código lo deja escrito para que no se lea de más (`core/config.py:219-221`).

### 5.1 Qué método es realmente, y su garantía

El código llama al método «FISTA proyectado», pero leer la implementación revela algo
distinto y más elaborado (`exploration/solver_preconditioned.py:159`): es el esquema
**GPCG de Moré & Toraldo (1991)**, que alterna

1. fases de gradiente proyectado —con reinicio adaptativo de O'Donoghue & Candès
   (2015)— para **identificar el conjunto activo**, y
2. un solve de Krylov (`lsqr`, `iter_lim=200`) **restringido al subespacio libre**,

durante `max_outer = 6` ciclos externos. El razonamiento que lo motiva es correcto y
está escrito: FISTA puro converge en $O(\sqrt{\kappa})$ iteraciones, lo que es
inviable con $\text{cond}(G^\top G)\sim10^{11}$ del sistema aumentado real
(`exploration/solver_preconditioned.py:205-211`).

El paso se fija con $1/L$, donde $L$ se estima por iteración de potencia sobre
$G^\top G$ y se infla un 5 % porque la iteración de potencia subestima $\sigma_{max}$
(`exploration/solver_preconditioned.py:194`). Es la salvaguarda correcta: un paso
mayor que $1/L$ rompe la garantía de descenso.

El criterio de parada KKT es el **gradiente proyectado relativo**: se para cuando
$\|x-\Pi_{[\ell,u]}(x-\text{step}\cdot\nabla\Phi)\|_\infty$ cae a `tol_pg` veces su
valor en el primer chequeo (`exploration/solver_preconditioned.py:180-183`). El
comentario justifica la elección de un criterio relativo y no absoluto: los bounds en
$\tilde m$ vienen escalados por las normas de columna ($\sim10^6$), de modo que un
umbral absoluto no sería invariante de escala. Es un argumento correcto.

Finalmente, hay una **garantía estructural**: se conserva el mejor iterado y nunca se
devuelve un punto peor que el punto de partida caliente
(`exploration/solver_preconditioned.py:296-298`). Esto asegura que la etapa proyectada
no puede empeorar el resultado del recorte, aunque no garantiza que lo lleve al óptimo.

---

## 6. Otras piezas matemáticas presentes

### 6.1 Estimador de traza de Hutchinson

`hutchinson_diag_inv` (`exploration/gravimetry.py:253`) estima la diagonal de la
inversa de la matriz de información sin invertirla. El estimador de Hutchinson usa
vectores aleatorios de Rademacher $z$ con $\mathbb{E}[zz^\top]=I$:

$$
\operatorname{diag}(A^{-1})_j \approx \frac{1}{K}\sum_{k=1}^{K} z^{(k)}_j\,(A^{-1}z^{(k)})_j
$$

Es un estimador **insesgado** pero de varianza $O(1/K)$. Se usa para la desviación
posterior (informe 12).

### 6.2 Fórmula de Woodbury para actualizaciones de rango $k$

`woodbury_low_rank_update` (`exploration/gravimetry.py:425`) y
`woodbury_update_from_new_rows` (`exploration/potential_field_core.py:709`)
incorporan $k$ observaciones nuevas sin re-invertir. La identidad de
Sherman–Morrison–Woodbury:

$$
(A+U V^\top)^{-1} = A^{-1} - A^{-1}U(I+V^\top A^{-1}U)^{-1}V^\top A^{-1}
$$

reduce el coste a resolver $k$ sistemas contra $A$ (congelada) en lugar de re-factorizar.
Es la aplicación correcta y estándar.

### 6.3 Matriz de información y garantía de definición positiva

$$
A = \tilde G^\top\tilde G + \lambda_{sp}^2\,\tilde L^\top\tilde L + \lambda^2 I
$$
(`exploration/potential_field_core.py:789-802`)

El comentario señala con precisión que $A$ es SPD **gracias** al término $\lambda^2I$,
y que por eso los llamadores exigen $\lambda>0$ en lugar de dejar que el gradiente
conjugado falle a mitad de camino (`exploration/potential_field_core.py:794-796`).
Correcto: sin ese término, $A$ sería sólo semidefinida positiva si $\tilde G$ y
$\tilde L$ tienen núcleo común.

### 6.4 Pesos de fila frente a cambio de variable — la distinción que costó cara

`depth_row_weights` (`exploration/potential_field_core.py:368`) calcula

$$
w_{reg} = \frac{1}{(z+z_0)^{\beta}}, \quad\text{normalizado a media 1}
$$

y el código insiste en que **no debe confundirse** con `build_model_weights`: éste
multiplica las **filas** de un bloque de regularización y **no se deshace** al
destransformar, porque no es un cambio de variable
(`exploration/potential_field_core.py:377-384`).

Matemáticamente son objetos distintos: $BW$ (columnas, cambio de variable, cancelable)
frente a $\operatorname{diag}(w)B$ (filas, no cancelable). El proyecto documenta que
llamar a ambos "*depth weighting*" fue la raíz de un hallazgo de auditoría entero.
Es una distinción correcta y bien explicada.

### 6.5 Estadística robusta: amplitud del modelo

`robust_amplitude` (`exploration/potential_field_core.py:849`) usa de nuevo
$1.4826\cdot\operatorname{MAD}$ como estimador robusto de escala, con un piso.
Consistente con §2.1.

---

## 7. Qué matemática NO está presente

Por honestidad, y porque un revisor podría esperarla:

- **No hay optimización no lineal general.** No hay Gauss-Newton, ni región de
  confianza sobre un problema no lineal, ni continuación en un parámetro físico. El
  problema es lineal y se trata como tal. (El IRLS es no lineal, pero por
  reponderación, no por linealización.)
- **No hay inferencia bayesiana completa.** No hay MCMC, ni muestreo posterior, ni
  evidencia marginal. Lo que hay es un estimador puntual regularizado más
  diagnósticos de incertidumbre construidos alrededor (informe 12). Interpretar
  $\lambda$ como precisión de un prior gaussiano es legítimo, pero el sistema no
  explota esa interpretación.
- **No hay descomposición en valores singulares del operador.** No se calcula la SVD
  ni se examina el espectro de $G$ directamente. El "número de condición" que se
  reporta es un sustituto barato (informe 02, §6).
- **No hay análisis de resolución formal.** No se construye la matriz de resolución
  del modelo $R=G^{\dagger}G$ ni se examinan sus filas, que es la herramienta clásica
  para cuantificar qué promedia realmente cada celda del modelo. El sistema usa en su
  lugar pruebas empíricas tipo *checkerboard* (informe 12).

---

## 8. Resumen técnico

### Lo que está correctamente implementado

- La formulación del problema como mínimos cuadrados regularizados con pesos de dato
  derivados de $\sigma$ es estándar y correcta.
- El teorema del cambio de variable puro (§2.6) es correcto, está bien enunciado y —
  lo que es infrecuente— sus consecuencias se **declaran al usuario** en la salida de
  cada corrida.
- La detección de la esquina de la curva-L por curvatura de Menger, con normalización
  de ejes y descarte de tríos degenerados, es la implementación correcta del método.
- El IRLS de soporte mínimo con homotopía en $\varepsilon$ está bien planteado y bien
  citado.
- El uso de MAD, Woodbury y Hutchinson es correcto en cada caso.
- La transformación de las cotas de caja al espacio escalado es exacta.

### Lo que está parcialmente implementado

- **Restricciones de caja**: resueltas exactamente para $n\le8000$; para mallas
  grandes se abordan con GPCG proyectado (activo por defecto) pero con un presupuesto
  fijo de 6 ciclos, sin garantía verificada de haber alcanzado KKT (§5.1).
- **Selección de $\lambda$**: los dos métodos clásicos existen, pero producción usa un
  tercero, y la constante de ese tercero contradice su propia justificación (§3.3).
- **Convergencia del IRLS**: hay criterio de parada, pero mide los pesos y el objetivo
  cambia entre iteraciones (§4.3).

### Lo que no está implementado

- SVD, análisis espectral y matriz de resolución formal.
- Inferencia posterior completa.
- Regularización de primera diferencia (la que citan las referencias).

### Supuestos matemáticos que el sistema hace sin declararlos

1. Ruido gaussiano, independiente y de media cero en las observaciones.
2. Contraste cero en el borde del dominio activo (condición de Dirichlet implícita, §2.7c).
3. Que la penalización de curvatura al cuadrado es el prior de suavidad adecuado.
4. Que 256 es la escala de referencia correcta para calibrar $\lambda$ (§2.8).
5. Que recortar el foco IRLS a $[0.05, 20]$ no altera materialmente el óptimo (§4.2).

---

## 9. Preguntas abiertas para revisión académica

---

### Pregunta 1 — El operador de suavidad es de cuarto orden, no de segundo

**Pregunta.** El término de suavidad penaliza $\|Lm\|^2 = m^\top L^2 m$ con $L$ un
Laplaciano de grafo, lo que en las ecuaciones normales da un operador bi-armónico.
La literatura que el código cita (Li & Oldenburg 1998) usa operadores de **primera**
diferencia y penaliza $\|\nabla m\|^2$. ¿Considera usted que penalizar la curvatura al
cuadrado es apropiado para este problema, o recomendaría la formulación de primer
orden? En particular: ¿qué efecto espera sobre la nitidez de los contactos
geológicos?

**Por qué surge.** Fue una discrepancia entre la cita y la implementación detectada al
leer el código, no algo que el proyecto hubiera notado.

**Evidencia en el código.** `exploration/gravimetry.py:1291` (construcción de $L$),
`exploration/gravimetry.py:1319` (cita a Li & Oldenburg), `exploration/gravimetry.py:2440`
(el bloque entra al sistema como $\lambda_{sp}L$, luego al cuadrado en el funcional).

**Qué sabemos.** Que $L$ es simétrico, con pesos $2/(h_i+h_j)$ en malla no uniforme,
sin *wrap-around*, y que el código validó propiedades de M-matriz y convergencia al
caso uniforme (`exploration/gravimetry.py:1321-1327`).

**Qué NO sabemos.** No se ha medido nunca la diferencia de resultado entre penalizar
$\|Lm\|^2$ y $\|\nabla m\|^2$ sobre el mismo dato. No existe ese experimento.

**Qué opinión sería útil.** Si el revisor considera que la penalización de cuarto orden
sobre-suaviza de forma perjudicial para localizar cuerpos compactos, sería un cambio
prioritario. Si considera que, combinada con el IRLS de soporte mínimo, el efecto es
menor, también es información valiosa: nos diría que no hay que gastar esfuerzo ahí.

---

### Pregunta 2 — Una condición de contorno de Dirichlet que nadie eligió

**Pregunta.** Al restringir el Laplaciano al dominio activo mediante *slicing*
(`L_full[activas][:,activas]`), la diagonal conserva el peso de las aristas hacia
celdas inactivas mientras las entradas fuera de la diagonal se eliminan. El resultado
es que $L_a\mathbf{1}\ne0$ en la frontera, lo que equivale a imponer contraste **cero**
en las celdas de aire y en las celdas podadas. ¿Le parece a usted una condición de
contorno razonable para este problema, o introduce un sesgo indeseable justo bajo la
topografía, que es donde la resolución debería ser máxima?

**Por qué surge.** Es un efecto colateral de una operación de indexado, no una
decisión de modelado. No está documentado en ningún sitio del código.

**Evidencia.** `exploration/gravimetry.py:1399-1401` (la diagonal se calcula sobre la
malla completa) y `exploration/gravimetry.py:2233-2235` (el recorte posterior).

**Qué sabemos.** Que el valor implícito es cero, que en unidades físicas significa
"densidad de fondo", y que afecta a dos fronteras distintas: la topográfica y la del
dominio observable podado por sensibilidad.

**Qué NO sabemos.** La magnitud del sesgo. No se ha comparado nunca contra una
alternativa (por ejemplo, recalcular la diagonal después del recorte, lo que daría una
condición de tipo Neumann).

**Qué opinión sería útil.** Saber cuál de las dos condiciones (Dirichlet homogénea o
Neumann natural) es la estándar defendible en inversión de campos potenciales, y si
la elección debería depender de qué frontera se trate.

---

### Pregunta 3 — El *depth weighting* no es una decisión, lo fija el kernel

**Pregunta.** El sistema no tiene un *depth weighting* ajustable: la ponderación
efectiva es $\|\text{col}_j(W_dG)\|$, que resulta equivalente a una ley de potencia con
$\beta_{eq}\approx2{,}63$ (desviación máxima 5,3 % sobre la malla de producción). El
estándar industrial es $\beta=2$. ¿Considera aceptable que el exponente lo determine
la geometría del kernel en lugar de ser un parámetro del usuario? ¿Y le parece
$\beta\approx2{,}63$ una elección razonable, o excesivamente agresiva?

**Por qué surge.** El proyecto intentó implementar Li & Oldenburg explícitamente,
midió que el peso se cancelaba algebraicamente, y decidió **no** cablear la
alternativa tras 576 inversiones de prueba.

**Evidencia.** `exploration/gravimetry.py:2253-2278` (la demostración de la
cancelación), `exploration/potential_field_core.py:283-315` (la medición de
$\beta_{eq}$), `exploration/gravimetry.py:2280-2284` (la decisión de no cablear).

**Qué sabemos.** Que la cancelación es exacta ($1{,}7\times10^{-16}$), que
$\beta_{eq}\approx2{,}63$ está medido, y que en 3.450 inversiones ningún $\beta$ fijo
mejoró la recuperación de profundidad en todos los regímenes a la vez.

**Qué NO sabemos.** Si un $\beta$ dependiente del régimen (profundidad esperada del
objetivo, densidad de estaciones) sería mejor. Sólo se probaron valores fijos.

**Qué opinión sería útil.** Si hay literatura que recomiende adaptar $\beta$ a la
geometría de adquisición, sería directamente accionable.

---

### Pregunta 4 — ¿Seis ciclos de GPCG bastan para satisfacer KKT?

**Pregunta.** Para $n\le8000$ celdas se usa `lsq_linear` con región de confianza, que
resuelve el problema restringido. Para $n>8000$ —el tamaño habitual del producto— se
resuelve sin restricciones, se recorta, y se refina con un esquema GPCG
(Moré & Toraldo 1991) limitado a **6 ciclos externos** con fases de 20–60 iteraciones
de gradiente proyectado y solves de Krylov de 200 iteraciones en el subespacio libre.
¿Considera usted que ese presupuesto es suficiente para identificar correctamente el
conjunto activo en un problema con $\text{cond}(G^\top G)\sim10^{11}$? ¿O esperaría
que el conjunto activo siga cambiando al agotarse los ciclos?

**Por qué surge.** El método está bien elegido —GPCG es exactamente la respuesta
correcta al mal condicionamiento que hace inviable FISTA puro—, pero el presupuesto de
iteraciones es una constante fija que no se adapta al problema.

**Evidencia.** `exploration/gravimetry.py:2529-2535` (umbral 8000);
`exploration/solver_preconditioned.py:205-211` (justificación de GPCG);
`exploration/solver_preconditioned.py:243-244` (`max_outer = 6`,
`pg_iters_per_phase = max(20, min(60, max_iter//max_outer))`);
`core/config.py:233` (activo por defecto).

**Qué sabemos.** Que el método está activo por defecto y que apagarlo empeora el
$\chi^2$ 93× (`core/config.py:229-232`), luego está haciendo un trabajo real. Que
existe una garantía estructural de no empeorar el punto de partida
(`exploration/solver_preconditioned.py:296-298`). Que el criterio de parada KKT es
relativo y hay una razón correcta para ello.

**Qué NO sabemos.** Con qué frecuencia se sale por `max_outer` en lugar de por el
criterio KKT en corridas reales. El código publica `converged_by` en su diccionario de
información, pero **no se ha analizado esa estadística**. Es una medición barata y
pendiente.

**Qué opinión sería útil.** Si el revisor conoce heurísticas para dimensionar
`max_outer` en función de $n$ o del número de celdas en los bounds, sería directamente
accionable. También: si la fracción de celdas saturadas en los bounds (que el código
ya calcula como `frac_lb_active`/`frac_ub_active`) es un buen diagnóstico de que el
box está mal elegido.

---

### Pregunta 5 — Una constante que contradice su propia justificación

**Pregunta.** `PRECONDITIONED_OPERATING_LAMBDA = 0.1`, pero el comentario que la
justifica afirma que el óptimo preacondicionado es $O(1\text{–}10)$ y que $\lambda\approx3$
fue validado contra verdad sintética con correlación de Pearson $\approx0{,}95$.
¿Cómo interpretaría esta discrepancia de factor 30? ¿Hay alguna razón por la que el
punto de operación debiera ser mucho menor que el óptimo medido?

**Por qué surge.** Discrepancia directa entre una constante y el texto que la explica,
ambos en el mismo repositorio.

**Evidencia.** `services/geophysics_service.py:72` frente a
`services/geophysics_service.py:3213-3216`.

**Qué sabemos.** Que este valor se usa siempre que el usuario no declara su ruido, es
decir, en el caso más común.

**Qué NO sabemos.** Cuál de los dos (constante o justificación) está desactualizado.
**NO DETERMINADO** por lectura de código.

**Qué opinión sería útil.** Sobre todo metodológica: cómo se debería fijar y documentar
un punto de operación de $\lambda$ cuando los selectores automáticos no son aplicables.

---

### Pregunta 6 — El recorte del foco IRLS limita el funcional que se aproxima

**Pregunta.** Los pesos de soporte mínimo se recortan a $[0{,}05,\,20]$ tras
normalizarlos a media 1. Eso acota el rango dinámico del foco a 400× e impide alcanzar
el límite $\ell_0$. ¿Considera este recorte una salvaguarda numérica necesaria, o una
limitación que degrada materialmente la compacidad alcanzable? ¿Existe una elección
mejor fundamentada para esos límites?

**Evidencia.** `exploration/potential_field_core.py:559-574`.

**Qué sabemos.** Que sin recorte una celda con $c_i\to0$ recibiría peso $1/\varepsilon$,
y que $\varepsilon$ tiene piso $10^{-3}$, luego el peso máximo sin recorte sería $\sim10^3$
antes de normalizar.

**Qué NO sabemos.** Si $[0{,}05,20]$ se eligió por medición o por intuición. El código
no lo dice.

---

### Pregunta 7 — El criterio de parada del IRLS y la ausencia de garantías

**Pregunta.** El bucle IRLS enfría $\varepsilon$ en cada iteración, de modo que el
funcional objetivo cambia entre iteraciones; y el criterio de parada mide el cambio
relativo de **los pesos**, no del modelo ni del objetivo. ¿Le parece adecuado? ¿Debería
medirse convergencia sobre el modelo, o fijarse $\varepsilon$ y demostrar decrecimiento
monótono por mayorización-minimización antes de enfriar?

**Evidencia.** `exploration/gravimetry.py:2794-2812`.

**Qué sabemos.** Que la homotopía en $\varepsilon$ es una estrategia reconocida para
evitar mínimos locales en problemas no convexos.

**Qué NO sabemos.** Si la sucesión converge en algún sentido demostrable con este
esquema combinado.

---

### Pregunta 8 — La curva-L se calcula con un solver distinto del de producción

**Pregunta.** Los ensayos del barrido de la curva-L usan `iter_lim=150` mientras que la
inversión final usa `iter_lim=500`. Dado que el mismo proyecto midió que la parada
temprana puede cambiar el resultado hasta un 86 %, ¿tiene sentido el $\lambda$ así
elegido? ¿O la curva-L debe construirse necesariamente con el operador exacto que se
usará después?

**Evidencia.** `exploration/gravimetry.py:1541` frente a `exploration/gravimetry.py:2611`;
la medición de la parada temprana en `exploration/potential_field_core.py:430-441`.

---

### Pregunta 9 — Ausencia de análisis de resolución formal

**Pregunta.** El sistema no calcula la matriz de resolución del modelo
$R = (G^\top W_d^\top W_d G + \lambda^2 R_m)^{-1}G^\top W_d^\top W_d G$ ni examina sus
filas. Usa en su lugar pruebas empíricas de tablero de ajedrez. Para un problema de
este tamaño ($n$ del orden de $10^4$–$10^5$), ¿considera factible y recomendable
calcular al menos las filas de $R$ en celdas seleccionadas (por ejemplo, en el blanco
propuesto), y sería más informativo que el tablero?

**Por qué surge.** El sistema propone puntos de perforación. Saber qué volumen promedia
realmente cada celda del blanco es exactamente la pregunta que un cliente haría.

**Qué sabemos.** Que existe un estimador de traza (Hutchinson) que podría reutilizarse
para estimar filas de $R$ sin invertir.

**Qué NO sabemos.** El coste real. NO DETERMINADO.

---

*Fin del informe 01. Los informes 02 (álgebra lineal y solvers), 04 (geofísica) y 12
(incertidumbre) tratan aspectos complementarios de la misma maquinaria desde sus
respectivas disciplinas.*
