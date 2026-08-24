# INFORME 05 — GEOLOGÍA Y MODELAMIENTO DEL SUBSUELO
## Qué información geológica usa TerraQuantum y cómo la incorpora

**Destinatario:** geología estructural · modelamiento geológico implícito · petrofísica
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `exploration/implicit_modeling.py`, `services/borehole_desurvey_service.py`, `services/isosurface_service.py`, `exploration/potential_field_core.py` (mapeo de intervalos) y `services/geophysics_service.py` (construcción y diagnóstico del prior geológico).

> Autocontenido. No hace falta leer los otros informes.

---

## 1. El punto de partida: un sistema sin geología

Conviene empezar por la afirmación que el propio código hace sobre sí mismo:

> «TerraQuantum hoy NO tiene geología explícita: toda "estructura" es emergente de la
> inversión.»
> (`exploration/implicit_modeling.py:5-6`)

Es una descripción exacta del problema que este subsistema intenta resolver. Una
inversión gravimétrica sin restricciones produce manchas suaves de contraste de densidad.
Esas manchas **no son unidades geológicas**: no tienen contactos, no tienen orientación,
no tienen identidad litológica. Son el resultado de un operador de regularización actuando
sobre un problema subdeterminado.

TerraQuantum incorpora geología por **tres vías distintas**, con grados de madurez muy
diferentes:

| Vía | Qué aporta | Estado |
|---|---|---|
| **Sondajes como anclaje** | valores de densidad medidos en celdas concretas | maduro, con desurvey y QA/QC |
| **Bounds por litología** | rangos petrofísicos por unidad | implementado, tabla por defecto |
| **Geología implícita (HRBF)** | una superficie de contacto interpolada que sesga el modelo | implementado y cableado, **opt-in** |

---

## 2. Sondajes: de la traza al vóxel

### 2.1 El problema que resuelve el desurvey

Un sondaje no es una línea vertical. Se desvía. Si el sistema asume verticalidad, un pozo
inclinado queda mal posicionado y sus datos se anclan a las celdas equivocadas — y lo hace
**en silencio**, que es la peor forma de equivocarse.

El módulo lo declara como su razón de existir:

> «Hoy TQ asume sondajes VERTICALES (`borehole_service`): un pozo inclinado se posiciona
> MAL en silencio.»
> (`services/borehole_desurvey_service.py:3-4`)

### 2.2 El algoritmo: curvatura mínima

`desurvey_minimum_curvature` (`services/borehole_desurvey_service.py:78`) implementa el
método de **curvatura mínima**, que es el estándar de la industria (SRK, AusIMM). A partir
del collar y de estaciones de survey (profundidad medida MD, azimut, dip), reconstruye la
traza 3D verdadera.

El vector director unitario se construye así
(`services/borehole_desurvey_service.py:53-58`):

$$
\hat u = \big(\underbrace{\cos(\text{dip})\sin(\text{az})}_{\text{Este}},\;
\underbrace{\cos(\text{dip})\cos(\text{az})}_{\text{Norte}},\;
\underbrace{\sin(\text{dip})}_{\text{abajo}}\big)
$$

Ésta es la convención geodésica **correcta**: azimut medido desde el Norte hacia el Este,
de modo que $\sin(\text{az})$ da la componente este y $\cos(\text{az})$ la norte.

### 2.3 Las convenciones, declaradas explícitamente

El módulo es inusualmente cuidadoso en declarar sus convenciones
(`services/borehole_desurvey_service.py:15-21`):

- Ejes del backend: **x = Este, z = Norte** (planta); **y = profundidad positiva hacia
  abajo**.
- Azimut en grados desde el **Norte hacia el Este**.
- **Dip** en grados **bajo la horizontal**, positivo hacia abajo (90° = vertical).
- *Up-holes* (dip < 0, minería subterránea) se aceptan **con advertencia**.
- MD = profundidad medida a lo largo del pozo desde el collar.

> **Nota transversal para el revisor.** Esta declaración de ejes (x=Este, z=Norte) es la
> **tercera** confirmación independiente de la convención del sistema, junto con la
> ingesta de CSV (`services/gravity_import_service.py:311`) y la exportación
> georreferenciada (`services/omf_export_service.py:561`). Es relevante porque el módulo
> magnético declara la convención **contraria** (`exploration/magnetometry.py:82-84`), lo
> que el informe 03 desarrolla como problema detectado.

Un detalle de forma: `position_at` devuelve las columnas en el orden
`(este, norte, profundidad)` (`services/borehole_desurvey_service.py:74`), que **no** es el
orden de ejes del backend `(x, y, z) = (este, profundidad, norte)`. El consumidor debe
remapear. No es un error —la función documenta su salida— pero es un punto donde un
descuido produciría un intercambio de ejes silencioso.

### 2.4 QA/QC de intervalos

El módulo valida cada intervalo con severidad graduada
(`services/borehole_desurvey_service.py:7-11`): `FROM ≥ TO`, solapes, huecos, duplicados,
profundidades negativas, y **densidades fuera de rango físico**, con los límites

$$
1{,}0 \le \rho \le 6{,}0\ \text{t/m}^3
$$

(`services/borehole_desurvey_service.py:38-40`, citando a Telford et al.). Cada hallazgo
lleva número de fila y severidad (**bloqueante** o **advertencia**).

### 2.5 Compositación

Se compositan intervalos a longitud regular
(`services/borehole_desurvey_service.py:12-14`):

- **densidad**: media ponderada por largo;
- **litología**: moda ponderada por largo;
- composites con **cobertura < 50 % se descartan con aviso**.

Las tres decisiones son estándar y están documentadas. Descartar con aviso en lugar de
rellenar es la elección correcta.

### 2.6 Del intervalo a la celda de la malla

`map_intervals_to_cells` (`exploration/potential_field_core.py:191`) es **geometría pura,
sin física** — lo dice el propio docstring, y es la razón por la que ambos motores
(gravimétrico y magnético) podían compartirla.

El algoritmo: selecciona la columna de vóxeles dentro de una tolerancia `tol_xz` en X/Z,
recorta al tramo $[y_{from}, y_{to}]$, y —el detalle que importa— si el intervalo es más
corto que la altura de celda `dy` y no toca ningún centro, cae al **vóxel más cercano al
punto medio** (`exploration/potential_field_core.py:236-243`).

Sin esa rama, un tramo de sondaje más corto que una celda **se perdería en silencio**. Es
exactamente el tipo de caso borde que decide si un sistema es utilizable con datos reales.

### 2.7 Cómo entra el sondaje a la inversión

Dos modos (`exploration/gravimetry.py:2700-2706`):

- **`hard`**: la celda anclada se elimina como grado de libertad (columna nula) y su
  *smallness* se pone a 0 — «no penalizar un DOF inexistente».
- **`soft`**: restricción fuerte vía *smallness* multiplicada por `anchor_kappa`.

Además se **relaja localmente el Laplaciano** en las celdas ancladas escalando sus filas
por `laplacian_relax_alpha < 1` (`exploration/gravimetry.py:2244-2250`). El argumento es
correcto y está escrito: reduce el acoplamiento de suavidad que la celda anclada impone
sobre sus vecinas, mitigando halos y *bullseyes*; el valor lo debe fijar la restricción,
no el suavizado.

---

## 3. Geología implícita: el campo escalar φ

### 3.1 Qué es y de dónde viene

`exploration/implicit_modeling.py` construye un **campo escalar implícito continuo**
$\varphi(\mathbf x)$ a partir de datos geológicos duros, cuyo **nivel cero es la superficie
geológica** y cuyo **signo etiqueta unidades**.

Método declarado: **HRBF** (*Hermite Radial Basis Function implicits*), citando a
Macedo, Gois & Velho (2011). El código lo sitúa correctamente en la literatura: es «la
formulación de "potential field"/dual-cokriging que usan GemPy/LoopStructural, pero
implementada con numpy puro» (`exploration/implicit_modeling.py:16-18`) — las dependencias
están prohibidas por las reglas del proyecto.

### 3.2 El kernel y por qué ese kernel

$$
\psi(r) = r^3
$$

con deriva polinómica de grado 1 (`exploration/implicit_modeling.py:49-52`).

La elección está **justificada, y la justificación es correcta**:

> «Elegido (vs biarmónico $r$) porque su gradiente $3r(x-c)$ y su Hessiana son continuos
> en $r=0$, condición necesaria para imponer *constraints* de gradiente (HRBF).»
> (`exploration/implicit_modeling.py:44-47`)

Es decir: como el método interpola **también derivadas** (las normales a la
estratificación), el kernel debe ser $C^2$. El biarmónico $r$ no lo es en el origen; el
triarmónico $r^3$ sí. Las derivadas están implementadas explícitamente:

$$
\nabla\psi = 3r(\mathbf x-\mathbf c), \qquad
H\psi = 3\Big[r\,I + \frac{(\mathbf x-\mathbf c)(\mathbf x-\mathbf c)^\top}{r}\Big]
$$

(`exploration/implicit_modeling.py:54-70`), con el límite $H\psi\to0$ cuando $r\to0$
tratado explícitamente.

### 3.3 Qué interpola

Simultáneamente dos tipos de restricción (`exploration/implicit_modeling.py:13-15`):

1. **Valores de $\varphi$**: puntos dentro, fuera o sobre la superficie, derivados de los
   contactos litológicos de los sondajes.
2. **Gradientes de $\varphi$**: las normales, obtenidas de medidas estructurales de
   orientación (dip y azimut) vía `OrientationDatum.from_dip_azimuth`
   (`exploration/implicit_modeling.py:87`).

Ésta es la propiedad valiosa del método: **un dato de orientación en un afloramiento
restringe la superficie sin necesidad de un sondaje ahí**. Es lo que distingue HRBF de una
interpolación RBF ordinaria.

### 3.4 Del campo φ al prior petrofísico

`build_spatial_prior_from_implicit` (`exploration/implicit_modeling.py:435`) convierte
$\varphi$ en un prior por celda mediante una **sigmoide**:

$$
w(\mathbf x) = \sigma\!\left(\frac{\varphi(\mathbf x)}{\text{softness}}\right),
\qquad
\mu(\mathbf x) = w\cdot\mu_{objetivo} + (1-w)\cdot\mu_{huésped}
$$

El parámetro `softness` controla cuán abrupta es la transición entre unidades. Con
`softness → 0` el contacto es un escalón; con valores grandes, una transición gradual.

El resultado se lleva a espacio de **contraste** restando la densidad de fondo
(`services/geophysics_service.py:1851`), que es donde vive el solver.

### 3.5 Cómo entra al funcional — y una medición que cambió la decisión

Ésta es la parte más interesante, porque el proyecto **midió** y el resultado invirtió la
elección inicial.

El modelo de referencia $m_{ref}$ puede entrar de dos formas:

- **por la suavidad**: $\|L(m-m_{ref})\|^2$ — que es donde estaba en la Fase 7.2;
- **por la *smallness***: un bloque aditivo $\alpha\|m-m_{ref}\|^2$ — donde lo pone
  Li & Oldenburg (1999).

El comentario del código explica por qué la primera opción no funciona
(`exploration/gravimetry.py:2371-2384`):

> «el `m_ref` de arriba entra SÓLO en la suavidad, ‖L·(m − m_ref)‖², y `L` es un
> Laplaciano de grafo, así que sólo actúa en la CURVATURA del contacto mientras el
> smallness sigue tirando de cada celda hacia `base_density` — es decir, **contra el
> prior**.»

Y la medición, sobre un dique inclinado con **anti-inverse-crime ×3** y semillas pareadas:

| Vía | Resultado |
|---|---|
| por la **suavidad** | el prior **EMPEORA** la recuperación (PR-AUC 0 de 25 semillas) |
| por la ***smallness*** | **MEJORA** en las cuatro métricas y en todas las semillas |
| control con geología **FALSA** por smallness | pasa a ser **el peor brazo de todos** |

Ese último control es el que hace convincente el resultado. El comentario lo nombra bien:
«es la firma de una restricción que de verdad transporta información geológica». Un prior
que mejora con geología verdadera **y empeora con geología falsa** está transportando
información; uno que mejora con ambas sólo está regularizando.

El *binding* por defecto es `"smallness"`, y `"smoothness"` queda disponible para
reproducir exactamente el comportamiento histórico
(`services/geophysics_service.py:1863-1867`). Con `geo_prior_alpha = 0` no se apila nada y
la inversión es byte-idéntica (`exploration/gravimetry.py:2398-2401`).

### 3.6 Los diagnósticos de honestidad del prior

Esta subsección merece existir por separado, porque es —a juicio de esta auditoría— **el
mejor trabajo del repositorio**. El sistema no se limita a aplicar el prior: **mide en qué
condiciones el prior es una afirmación vacía o peligrosa, y lo declara**.

Los cuatro diagnósticos (`services/geophysics_service.py:1867-1958`):

**(1) `inert_no_contrast` — el prior que no dice nada.**
Si el prior clasifica el 0 % o el 100 % de las celdas como unidad objetivo, es
espacialmente constante. Y como $L\cdot\text{constante}=0$ exactamente (medido:
$\max|L\mathbf 1| = 0{,}0$ en malla uniforme, $4\times10^{-17}$ en no uniforme), el término
de suavidad **lo anula exactamente**. El código concluye: «La inversión sale igual que sin
prior. Eso no se puede reportar como `enabled: true` a secas.»

**(2) `degenerate_planar_field` — el HRBF que degeneró a un plano.**
Cuando los contactos no bastan para fijar curvatura (por ejemplo, todos los sondajes
cortan el contacto a la misma profundidad), los pesos RBF salen ~0 y $\varphi$ queda en la
rampa lineal de la deriva polinómica. Entonces «la superficie geológica» es un **plano
extrapolado a toda la malla**, no una superficie interpolada.

La medición que acompaña es contundente: **con 1 sondaje vertical y contacto a 90 m,
$\varphi\ge0$ en el 85 % de la malla, a 403 m del único pozo.**

**(3) `extrapolation_max_m` — la afirmación más lejana sin dato.**
Se calcula la distancia horizontal de cada celda clasificada como objetivo al collar más
cercano, y se publica el máximo (`services/geophysics_service.py:1883-1890`). El código lo
describe como «la afirmación geológica más lejana que el prior está haciendo sin dato».

**(4) `declared_std_is_inert` — un parámetro que el usuario cree que hace algo.**
`build_spatial_prior_from_implicit` calcula una desviación estándar por celda, pero el
solver **sólo consume `prior.mean`**. En lugar de disimularlo, el sistema publica el campo
`"declared_std_is_inert": True` (`services/geophysics_service.py:1918-1920`).

**Y una quinta cosa: una colisión medida entre dos priors.**
Un sondaje **sólo litológico** —justo el input que el prior geológico exige— no entra al
array de anclaje. Entonces `enable_depth_prior` encuentra `boreholes_arr is None`, fuerza
`anchor_mode="hard"`, y eso fija las celdas ancladas a `base_density` **eliminándolas del
sistema**. El prior geológico queda pisado sin que nada avise. El sistema emite la
advertencia: «Desactive uno de los dos» (`services/geophysics_service.py:1948-1958`).

### 3.7 Se niega a inventar geología

Si `implicit_geology` está activado pero ningún sondaje declara litología, el sistema
responde **HTTP 422** con el mensaje: «El prior geológico implícito requiere contactos
litológicos de sondaje; **no se infiere geología sin dato**»
(`services/geophysics_service.py:1798-1806`).

Es la conducta correcta. Un prior geológico inventado no es un prior: es una alucinación
con formato de restricción.

---

## 4. Bounds petrofísicos por litología

En celdas con litología conocida, el box escalar global $[\rho_{min},\rho_{max}]$ se
sustituye por el box de su unidad, transformado al espacio del solver con la misma
biyección (`exploration/gravimetry.py:2298-2310`). El solver con restricciones lo impone
satisfaciendo KKT por celda.

La tabla por defecto es `LITHOLOGY_BOUNDS_DEFAULTS`, extensible o sobrescribible por
`params.lithology_bounds` (`services/geophysics_service.py:1979-1981`), con emparejamiento
insensible a mayúsculas.

**Un detalle de gobernanza que merece mención.** Un comentario en `core/config.py:207-214`
registra que esa tabla petrofísica **se sacó de la configuración de infraestructura** con
el argumento de que «una tabla petrofísica por litología es dominio geofísico, no
infraestructura», y que si vuelve a hacer falta «va junto al motor magnético que la
consuma, y entra el mismo día que su consumidor — no antes». Es una regla sana contra el
código especulativo.

---

## 5. Superficies e isosuperficies

`services/isosurface_service.py` extrae superficies de nivel del modelo invertido:

- **Marching cubes** de `skimage.measure` (`services/isosurface_service.py:338-349`), con
  la guarda correcta: exige $v_{min} < \text{nivel} < v_{max}$, y si no, no hay superficie.
- **Suavizado de Taubin** (`services/isosurface_service.py:269`), que es la elección
  correcta frente al laplaciano simple porque **no encoge** la malla.
- **Corrección de orientación**: se calcula el volumen con signo y se invierte el
  *winding* de las caras si hace falta (`services/isosurface_service.py:239-253`).
- **Normales** recalculadas por vértice y una dirección "hacia afuera" tomada como
  $-\nabla|\text{contraste}|$ (`services/isosurface_service.py:375-379`).
- **Niveles de detalle (LOD)** por submuestreo (`services/isosurface_service.py:317`).

Nótese que la superficie se entrega ya en **espacio visual** (centrada y con inversión del
eje Y para Three.js), y que la exportación a OMF tiene que **deshacer** exactamente esa
transformación (`services/omf_export_service.py:550-561`). Es un acoplamiento incómodo
—un servicio de dominio que produce coordenadas de presentación— pero está documentado.

**Advertencia interpretativa importante.** Una isosuperficie de un modelo regularizado
**parece** un cuerpo geológico: tiene forma cerrada, superficie suave, volumen calculable.
No lo es. Es un contorno de nivel de un campo continuo elegido por un operador de
regularización, y su suavidad viene del suavizado de Taubin además de la del Laplaciano.
El informe 10 desarrolla este punto desde la visualización.

---

## 6. Qué geología NO está modelada

El propio módulo declara sus límites, y conviene reproducirlos porque son exactos
(`exploration/implicit_modeling.py:24-32`):

- **No hay fallas.** Ninguna discontinuidad estructural. Un HRBF produce un campo continuo;
  una falla es precisamente una superficie de discontinuidad.
- **No hay estratigrafía multi-serie.** El modelo es **categórico binario** (unidad
  objetivo frente al resto); multi-unidad sólo secuencialmente.
- **No hay cokriging bayesiano** (GemPy) ni el marco de relaciones estructurales de
  LoopStructural — dependencias prohibidas por las reglas del proyecto.
- **No hay inversión *level-set***. Las funciones `evolve_level_set`,
  `level_set_step`, `reinitialize_sdf` y `speed_from_property` existen
  (`exploration/implicit_modeling.py:480-560`), pero el docstring declara que la geofísica
  que deforma $\varphi$ (Giraud, GJI 2024) «NO se cablea al solver». **NO DETERMINADO** si
  alguna ruta las invoca hoy; no se localizó consumidor en producción.

Y un límite que no es del método sino del dato, y que el código enuncia bien:

> «Un sondaje vertical muestrea una sola línea: con pocos sondajes la superficie 3D queda
> poco restringida (límite de DATO, no del método).»
> (`exploration/implicit_modeling.py:30-32`)

---

## 7. Los tres niveles, aplicados a la geología

**Lo que el código hace.** Interpola un campo escalar $\varphi$ desde contactos de sondaje
y orientaciones, lo convierte en un campo de densidad de referencia por celda vía una
sigmoide, y lo inyecta como modelo de referencia en el término de *smallness* de la
inversión.

**Lo que matemáticamente significa.** Se está desplazando el punto hacia el que la
regularización tira cada celda. No se está imponiendo la geología: se está **sesgando** la
solución hacia ella con un peso $\alpha$ ajustable. Con $\alpha$ grande, el modelo se
parecerá al prior aunque el dato no lo respalde.

**Lo que geológicamente se puede afirmar.** Que existe un modelo de densidad compatible
con los datos gravimétricos **y** con los contactos observados en los sondajes. Nada más.
En particular:

- La superficie entre sondajes es **interpolación**, no observación. El diagnóstico
  `extrapolation_max_m` cuantifica exactamente hasta dónde llega esa interpolación.
- Si `degenerate_planar_field` es verdadero, la "superficie geológica" es un **plano
  extrapolado**, y presentarla como un contacto modelado sería engañoso.
- El signo de $\varphi$ etiqueta unidades **según la clasificación que el usuario declaró**
  en `target_lithologies`. No es un descubrimiento litológico.

---

## 8. Resumen técnico

### Correctamente implementado

- Desurvey por curvatura mínima con la convención geodésica correcta y todas las
  convenciones declaradas explícitamente.
- QA/QC de intervalos con severidad graduada y rango petrofísico físico.
- Compositación con reglas documentadas y descarte con aviso.
- Mapeo intervalo→celda con la rama que evita perder tramos cortos.
- HRBF con kernel triarmónico correctamente justificado por continuidad $C^2$.
- Interpolación conjunta de valores y gradientes (orientaciones).
- Elección del término de acople **medida**, con control de geología falsa.
- Cinco diagnósticos de honestidad del prior, todos medidos.
- Rechazo explícito a inferir geología sin dato (HTTP 422).
- Bounds por unidad litológica impuestos por KKT.
- Marching cubes con guarda de nivel y suavizado de Taubin (no encoge).

### Parcialmente implementado

- Modelo categórico **binario**; multi-unidad sólo secuencial.
- La σ del prior se calcula pero el solver no la consume (declarado como inerte).
- Las rutinas de *level-set* existen sin consumidor localizado (**NO DETERMINADO**).

### No implementado

- Fallas y discontinuidades estructurales.
- Estratigrafía multi-serie con relaciones de corte.
- Cokriging bayesiano / cuantificación de incertidumbre de la superficie.
- Inversión geofísica que deforme $\varphi$ (*level-set inversion*).

### Riesgos geológicos

1. **Extrapolación silenciosa con pocos sondajes.** Mitigado —no eliminado— por los
   diagnósticos. Con un solo pozo, el 85 % de la malla puede quedar clasificada.
2. **Una isosuperficie suave parece un cuerpo geológico y no lo es.**
3. **Colisión entre el prior de profundidad y el prior geológico**, detectada y advertida
   pero no impedida.
4. **El peso $\alpha$ del prior no tiene criterio de elección documentado**; con $\alpha$
   grande el modelo puede reproducir el prior en lugar de contrastarlo.

---

## 9. Preguntas abiertas para revisión académica

---

### Pregunta 1 — ¿Cuántos sondajes hacen falta para que un HRBF signifique algo?

**Pregunta.** El sistema mide que con **1 sondaje vertical** y contacto a 90 m, el campo
implícito clasifica el 85 % de la malla como unidad objetivo, hasta 403 m del único pozo, y
lo declara como campo degenerado a plano. ¿Existe un criterio geológico defendible —número
mínimo de contactos, distribución espacial mínima, relación entre separación de sondajes y
profundidad del contacto— por debajo del cual el sistema debería **negarse** a construir el
prior en lugar de construirlo con una advertencia?

**Por qué surge.** Hoy el sistema advierte pero procede. Un usuario apurado puede ignorar
la advertencia.

**Evidencia.** `exploration/implicit_modeling.py:240` (`degenerado_a_plano`);
`services/geophysics_service.py:1875-1882` (la medición); `1936-1944` (las advertencias).

**Qué sabemos.** Que la degeneración se detecta correctamente (los pesos RBF se anulan y
queda la deriva polinómica).

**Qué NO sabemos.** Cuál es el umbral geológicamente razonable. NO DETERMINADO.

**Qué opinión sería útil.** Una regla práctica del tipo «con menos de N contactos no
coplanares no se debería hablar de superficie interpolada», aunque sea aproximada.

---

### Pregunta 2 — El kernel triarmónico y la deriva de grado 1

**Pregunta.** Se usa $\psi(r)=r^3$ con deriva polinómica de grado 1, justificado por
continuidad $C^2$ para poder imponer restricciones de gradiente. ¿Le parece la elección
adecuada para contactos geológicos? En particular: ¿una deriva de grado 1 (plano) es
suficiente, o para geología plegada convendría grado 2? ¿Y qué efecto tiene $r^3$ sobre la
extrapolación lejos de los datos, dado que crece sin límite?

**Evidencia.** `exploration/implicit_modeling.py:44-52` (kernel y justificación);
`exploration/implicit_modeling.py:12-14` (deriva de grado 1).

**Qué sabemos.** Que la justificación de $C^2$ es correcta y necesaria para HRBF.

**Qué NO sabemos.** Si el crecimiento $r^3$ contribuye a la extrapolación agresiva medida
en el diagnóstico (3). No se ha separado el efecto del kernel del efecto de la falta de
dato.

---

### Pregunta 3 — El peso del prior, y el riesgo de circularidad

**Pregunta.** El prior geológico entra como $\alpha\|m-m_{ref}\|^2$ con
$\alpha=$ `prior_weight` (por defecto 1,0). No encontramos ningún criterio documentado
para elegir $\alpha$. Con $\alpha$ suficientemente grande, la inversión reproduce el prior
y el resultado deja de ser evidencia independiente. ¿Cómo recomendaría fijar $\alpha$?
¿Y qué diagnóstico usaría para detectar que el modelo está reproduciendo el prior en lugar
de contrastarlo — por ejemplo, comparar el misfit con y sin prior?

**Por qué surge.** Es el riesgo clásico de los priors informativos: confirmar lo que se
supuso.

**Evidencia.** `services/geophysics_service.py:1866` (el default);
`exploration/gravimetry.py:2398-2410` (cómo se apila).

**Qué sabemos.** Que la medición con **geología falsa** empeoró el resultado, lo que
sugiere que con $\alpha=1$ el dato aún manda. Es evidencia real contra la circularidad,
pero para un solo valor de $\alpha$.

**Qué NO sabemos.** A partir de qué $\alpha$ el prior domina. No se barrió.

---

### Pregunta 4 — Fallas ausentes

**Pregunta.** El HRBF produce un campo continuo, de modo que no puede representar fallas.
En un contexto de exploración chilena —donde el control estructural es a menudo el factor
determinante del emplazamiento— ¿qué tan limitante considera esta ausencia? ¿Y hay alguna
aproximación de bajo costo (por ejemplo, dominios separados a ambos lados de una falla
declarada por el usuario, cada uno con su propio HRBF) que valga la pena antes de
implementar el marco completo?

**Evidencia.** `exploration/implicit_modeling.py:28-29` (declarado como no implementado).

---

### Pregunta 5 — La colisión entre priors

**Pregunta.** Un sondaje que sólo declara litología (sin densidad medida) es exactamente
el input que el prior geológico exige, pero hace que `enable_depth_prior` fuerce
`anchor_mode="hard"`, lo que fija esas celdas a `base_density` y las elimina del sistema,
pisando el prior geológico. El sistema lo detecta y advierte «desactive uno de los dos».
¿Le parece suficiente advertir, o debería ser un error bloqueante? ¿Y cuál de los dos
priors debería tener precedencia geológicamente?

**Evidencia.** `services/geophysics_service.py:1948-1958`.

---

### Pregunta 6 — La σ del prior, calculada e inerte

**Pregunta.** El prior produce una media y una desviación por celda, pero el solver sólo
consume la media; la σ se declara explícitamente como inerte. Incorporarla significaría
un peso de *smallness* **por celda** (más confianza donde el prior es firme, menos donde
extrapola), lo que parece geológicamente deseable. ¿Recomendaría cablearla? ¿Y cómo
debería mapearse σ a un peso — $1/\sigma$, $1/\sigma^2$?

**Evidencia.** `services/geophysics_service.py:1918-1920` (la declaración de inercia);
`exploration/implicit_modeling.py:416-430` (`SpatialPetrophysicalPrior`).

**Qué sabemos.** Que hoy el prior aplica la misma fuerza a 5 m de un sondaje que a 400 m.

---

### Pregunta 7 — Interpretar una isosuperficie

**Pregunta.** El sistema extrae isosuperficies del modelo invertido con marching cubes y
las suaviza con Taubin. El resultado tiene aspecto de cuerpo geológico: cerrado, suave,
con volumen. Pero es un contorno de nivel de un campo regularizado, y su suavidad tiene
dos orígenes artificiales (el operador de suavidad de la inversión y el suavizado de la
malla). ¿Qué advertencia o qué representación alternativa recomendaría para que un
geólogo no lo lea como un contacto? ¿Mostrar varias isosuperficies a distintos niveles
sería más honesto que una sola?

**Evidencia.** `services/isosurface_service.py:338-395`.

---

*Fin del informe 05. El informe 06 trata el uso minero de estos resultados; el 03, la
física; el 12, la validación e incertidumbre; el 10, la visualización.*
