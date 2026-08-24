# INFORME 04 — GEOFÍSICA
## El flujo completo de TerraQuantum, del dato de campo a la interpretación

**Destinatario:** geofísica aplicada · métodos potenciales · exploración
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de la cadena de reducción (`services/gravity_corrections_service.py`, `services/opentopo_service.py`, `services/gravity_import_service.py`), de los motores (`exploration/gravimetry.py`, `exploration/magnetometry.py`, `exploration/potential_field_core.py`) y una **medición numérica propia** de la corrección de terreno (§4.5).

> Autocontenido: no hace falta leer los otros informes.
>
> **Aviso al revisor:** este informe contiene dos problemas detectados que
> consideramos serios. Uno está **medido** (§4.5, corrección de terreno) y otro
> **indicado por lectura de código sin confirmar experimentalmente** (§8.3,
> orientación del campo magnético). Si sólo va a mirar una cosa, mire §4.5.

---

## 1. Qué problema geofísico se está resolviendo

TerraQuantum es un sistema de **inversión de campos potenciales para targeting de
exploración minera**. La pregunta que intenta responder no es "¿cuánto mineral hay?"
sino "¿dónde conviene perforar?".

Esa distinción está declarada en el propio proyecto y conviene tomarla en serio, porque
determina qué es un éxito. El sistema busca **estructura y contraste**, no leyes ni
tonelajes. Un informe posterior (06) documenta que el campo llamado `grade` está
marcado internamente como `"grade_source": "heuristic_gravity_proxy"`,
`"assay_supported": false` (`services/geophysics_service.py:614-618`).

**Los dos métodos implementados:**

| Método | Propiedad física | Unidad del modelo | Dato observado |
|---|---|---|---|
| Gravimetría | contraste de densidad | t/m³ | anomalía de gravedad (mGal) |
| Magnetometría | susceptibilidad magnética | SI, adimensional | TMI (nT) |

Y una ruta de **inversión conjunta** que acopla ambas (`services/joint_inversion.py`, no
auditada en esta pasada: **NO DETERMINADO**).

---

## 2. La adquisición: qué dato entra

### 2.1 El punto de partida realista

El sistema está diseñado para ingerir un CSV de campo "sucio": delimitador desconocido,
decimal con coma o punto, nombres de columna en español o inglés, coordenadas en
lat/lon o UTM, unidades mezcladas. El módulo de ingesta
(`services/gravity_import_service.py`, 2.379 líneas) se ocupa de eso.

Un elemento clave de diseño: el mapeo de columnas es **por rol**, no por nombre. El
sistema decide qué columna cumple el papel de "coordenada este", "coordenada norte",
"elevación", "valor de gravedad", "tiempo", "identificador de estación".

**La asignación de roles de coordenadas es explícita:**

```
# 2. Lat/lon: lon→x_m slot, lat→z_m slot
```
(`services/gravity_import_service.py:311`)

Es decir: **longitud → eje x, latitud → eje z**. Retenga este dato; reaparece en §8.3.

### 2.2 Tipos de dato de entrada aceptados

El sistema acepta datos en distintos grados de reducción, y **salta las correcciones ya
aplicadas** (`services/gravity_corrections_service.py:357-361`):

| `gravity_type_in` | Qué se asume ya hecho |
|---|---|
| `g_raw` | nada — lectura de instrumento |
| `free_air_anomaly` | latitud y aire libre |
| `bouguer_anomaly` | + Bouguer simple |
| `complete_bouguer_anomaly` | + terreno |

Esto es correcto y evita el error clásico de corregir dos veces. Las notas del proyecto
registran que un error de doble Bouguer existió y se corrigió.

---

## 3. Convención de coordenadas y malla

### 3.1 El sistema interno

```
                      superficie (y = 0)
        ──────────────────────────────────────►  x  = ESTE
       ╱ │
      ╱  │
     ╱   │
    z    │
  NORTE  ▼
         y = PROFUNDIDAD, positiva HACIA ABAJO
```

Declarado en `exploration/gravimetry.py:709-713` y `exploration/treemesh.py:11`. La
identificación de $x$ con Este y $z$ con Norte se deduce de dos rutas independientes:
la ingesta (`services/gravity_import_service.py:311`) y la exportación georreferenciada
(`services/omf_export_service.py:561`, que hace `x + easting₀`, `z + northing₀`).

La profundidad positiva hacia abajo es una convención habitual en geofísica; conviene
notar que **no** es la de un sistema cartesiano dextrógiro estándar con $z$ arriba, y
que el frontend tiene que deshacer el signo para dibujar (informe 10).

### 3.2 Discretización

El dominio se divide en vóxeles rectangulares. Hay tres caminos de malla:

1. **Malla regular uniforme** — el caso base.
2. **Malla tensorial no uniforme** (`hx`, `hy`, `hz` variables), soportada por el
   Laplaciano con pesos de arista $w_{ij}=2/(h_i+h_j)$
   (`exploration/gravimetry.py:1358-1381`).
3. **Octree / TreeMesh** (`exploration/treemesh.py`), con celdas de tamaño variable y una
   ruta de kernel dedicada (`exploration/gravimetry.py:946`).

El tamaño de malla se propone automáticamente (*auto-grid*). El régimen normal del
producto, según los comentarios de configuración, es de **30.000 a 100.000 vóxeles**
(`core/config.py:220-221`).

### 3.3 Padding

Existe un mecanismo de *padding*: celdas periféricas que absorben efectos de borde. Se
distinguen del núcleo por una máscara y reciben un peso de *smallness* multiplicado por
$\kappa = 10^5$ (`services/geophysics_service.py:3060-3063`), es decir, se las empuja
fuertemente hacia contraste cero. El comentario indica que el valor subió de $10^4$ a
$10^5$ tras una auditoría porque con $10^4$ el padding retenía un 15,4 % de señal
espuria (`services/geophysics_service.py:3836`).

---

## 4. La cadena de reducción gravimétrica

Ésta es la parte del flujo donde la geofísica de gabinete se hace explícita. El orden
implementado es el estándar.

```
lectura cruda del gravímetro
   │
   ├─(1) marea terrestre (Longman 1959)          ── opcional, default OFF
   ├─(2) deriva instrumental (cierres de base)    ── opcional, default OFF
   │
   ├─(3) gravedad normal GRS80 (Somigliana)       ── default ON
   ├─(4) corrección de aire libre                 ── default ON si hay elevación
   ├─(5) Bouguer de placa infinita                ── default ON si hay elevación
   ├─(6) corrección de terreno                    ── default ON  ⚠ ver §4.5
   │
   └─(7) separación regional–residual (polinomio) ── en el preprocesamiento
          │
          ▼
   anomalía lista para inversión
```

### 4.1 Marea terrestre y deriva instrumental

`apply_field_prereductions` (`services/gravity_corrections_service.py:198`).

El orden es el correcto de gabinete y está justificado en el código: **marea primero**
(astronomía pura), **deriva después**, porque los cierres de base deben evaluarse sobre
lecturas ya libres de marea (`services/gravity_corrections_service.py:211-214`).

- **Marea:** modelo de Longman (1959), vía `services/earth_tide_service.py`.
- **Deriva:** ajuste sobre re-ocupaciones de una estación base, con métodos
  seleccionables (`drift_method`, por defecto `"linear"`), vía
  `services/drift_correction_service.py`.

**Una virtud de diseño que merece destacarse.** Este módulo **nunca adivina**. Si falta
la columna de tiempo, lanza un error que dice exactamente qué formatos acepta
(`services/gravity_corrections_service.py:238-243`). Si un solo *timestamp* es
ilegible, rechaza el lote entero con el argumento de que «una corrección de marea/deriva
a medias corrompería en silencio» (`services/gravity_corrections_service.py:246-250`).
Si falta la estación base, lanza un error que **pregunta** e incluye la candidata
detectada (el identificador que más se repite)
(`services/gravity_corrections_service.py:268-280`).

Esto es exactamente lo contrario del anti-patrón habitual —rellenar con un valor por
defecto y seguir— y es la decisión correcta en un sistema científico.

**Limitación:** ambas están **desactivadas por defecto**
(`apply_tide=False`, `apply_drift=False`,
`services/gravity_corrections_service.py:205-206`). En un levantamiento real ambas son
obligatorias; la deriva de un gravímetro puede ser de décimas de mGal por día, del mismo
orden que la señal buscada.

### 4.2 Gravedad normal (corrección de latitud)

$$
\gamma(\phi) \;=\; \gamma_e\,\frac{1+k\sin^2\phi}{\sqrt{1-e^2\sin^2\phi}}
$$

(`services/gravity_corrections_service.py:49-51`) con

| Constante | Valor | Significado |
|---|---|---|
| $\gamma_e$ | 9,7803267715 m/s² | gravedad normal en el ecuador |
| $k$ | 0,001931851353 | constante de Somigliana |
| $e^2$ | 0,0066943800229 | primera excentricidad al cuadrado |

Es la **fórmula cerrada de Somigliana para GRS80** (Moritz 1980, IUGG). Los tres valores
son los oficiales de GRS80. Correcto y bien citado.

### 4.3 Corrección de aire libre

$$
\text{FAC} \;=\; (0{,}3087691 - 0{,}0004398\sin^2\phi)\,h \;-\; 7{,}2125\times10^{-8}\,h^2
\quad[\text{mGal}]
$$

(`services/gravity_corrections_service.py:74-78`)

Referencia citada: Heiskanen & Moritz (1967), fórmula 3-57. **Correcta**, y notablemente
mejor que la práctica común:

- es **dependiente de la latitud** (el término $\sin^2\phi$), y
- incluye el **término de segundo orden** en $h^2$, que a 3.000 m de altitud aporta
  $\sim0{,}65$ mGal — nada despreciable en los Andes.

El código documenta que existía una versión de coeficiente fijo 0,3086 mGal/m y se
eliminó porque no tenía llamadores y «la única diferencia posible es un resultado peor»
(`services/gravity_corrections_service.py:86-90`). Decisión acertada.

### 4.4 Corrección de Bouguer de placa infinita

$$
\text{BC} = 0{,}04193\;\rho\,h \quad [\text{mGal}], \qquad \rho\ \text{en g/cm}^3
$$

(`services/gravity_corrections_service.py:110-111`)

El coeficiente corresponde a $2\pi G$ con $G$ CODATA 2018, convertido a mGal. Verificado:
$2\pi\cdot6{,}6743\times10^{-11}\cdot1000\ \text{kg/m}^3\cdot 10^5 = 0{,}04193$ mGal/m
por g/cm³. Correcto. Referencia citada: Hinze et al. (2005), la estandarización de la
NAGD. Densidad de reducción por defecto 2,67 g/cm³, el valor estándar.

### 4.5 ⚠ PROBLEMA DETECTADO Y MEDIDO — la corrección de terreno

Ésta es la sección más importante del informe.

#### 4.5.1 Lo que el código calcula

```python
tc_contrib = _G_NEWTON * rho_kg_m3 * cell_area * np.abs(dh) / r_m ** 2
tc[i] = np.sum(tc_contrib) * 1e5
```
(`services/gravity_corrections_service.py:159-162`)

Es decir, por cada celda del DEM:

$$
\text{TC}_{\text{TQ}} \;=\; \frac{G\,\rho\,A\,|\Delta h|}{r^{2}}
$$

donde $r$ es la distancia **horizontal** estación–celda y $\Delta h$ la diferencia de
elevación.

#### 4.5.2 Por qué es físicamente incorrecto

La masa de la columna de terreno es $M=\rho A|\Delta h|$. La expresión implementada es
entonces

$$
\frac{G M}{r^{2}}
$$

que es el **módulo** de la atracción de una masa puntual a distancia $r$ — no su
**componente vertical**, que es lo único que mide un gravímetro.

La componente vertical de una masa puntual con desnivel $\Delta z$ es

$$
g_z=\frac{G M\,\Delta z}{(r^2+\Delta z^2)^{3/2}}\;\xrightarrow[\Delta z\ll r]{}\;\frac{GM\,\Delta z}{r^{3}}
$$

La formulación clásica para una columna vertical (la que subyace a las cartas de Hammer)
es

$$
\text{TC}_{\text{columna}} = G\rho A\left(\frac{1}{r}-\frac{1}{\sqrt{r^{2}+\Delta h^{2}}}\right)
\;\xrightarrow[\Delta h\ll r]{}\; \frac{G\rho A\,\Delta h^{2}}{2r^{3}}
$$

Comparando ambas en el régimen $\Delta h\ll r$:

$$
\boxed{\;\frac{\text{TC}_{\text{TQ}}}{\text{TC}_{\text{columna}}}\;\approx\;\frac{2r}{|\Delta h|}\;}
$$

El error **crece linealmente con la distancia**. Y el radio de integración por defecto es
de **22 km** (`services/gravity_corrections_service.py:125`).

#### 4.5.3 La medición

No basta con el álgebra. Se ejecutó una comparación numérica directa de ambas fórmulas
(script propio, Python puro, sin modificar el proyecto). Celda de DEM de 30 m,
$\rho=2{,}67$ g/cm³:

| $r$ [m] | $\Delta h$ [m] | TQ [mGal] | Columna [mGal] | Razón |
|---|---|---|---|---|
| 50 | 10 | 6,415e-02 | 6,229e-03 | **10,3×** |
| 100 | 10 | 1,604e-02 | 7,960e-04 | **20,1×** |
| 500 | 10 | 6,415e-04 | 6,413e-06 | **100,0×** |
| 1.000 | 10 | 1,604e-04 | 8,019e-07 | **200,0×** |
| 5.000 | 10 | 6,415e-06 | 6,415e-09 | **1000,0×** |
| 20.000 | 10 | 4,010e-07 | 1,002e-10 | **4000,0×** |
| 1.000 | 100 | 1,604e-03 | 7,960e-05 | 20,1× |

Las razones medidas coinciden **exactamente** con la predicción analítica $2r/|\Delta h|$
(a $r=1000$, $\Delta h=10$: $2\cdot1000/10=200$; medido 200,0×). Eso confirma que el
diagnóstico es correcto y no un artefacto del experimento.

**Caso realista.** Cono de 500 m de altura y 2 km de radio, estación al pie del cono,
integración a 22 km:

| Formulación | TC total |
|---|---|
| TerraQuantum | **17,01 mGal** |
| Columna vertical | **1,41 mGal** |
| Razón | **12,0×** |

Para referencia: las correcciones de terreno reales en terreno montañoso están
típicamente entre 0,1 y 10 mGal.

#### 4.5.4 Por qué importa tanto

La corrección de terreno se **suma** a la anomalía
(`services/gravity_corrections_service.py:398`), y en la ruta de importación está
**activada por defecto** (`apply_terrain: bool = True`,
`services/gravity_import_service.py:1810`), encadenada como
`_fetch_terrain_correction` → `compute_terrain_correction_prism` →
`compute_terrain_correction_pointmass`
(`services/gravity_import_service.py:1893-1897`, `services/opentopo_service.py:341`).

La señal que se busca invertir es de 0,1 a 10 mGal. Un término sobrestimado en un factor
de 12 e inyectado con signo positivo **no es un sesgo pequeño: puede dominar el dato**.
Y como el error crece con la distancia, el término espurio es de **longitud de onda
larga**, correlacionado con la topografía regional. Parte podría ser absorbido por la
separación regional–residual (§4.6), pero no hay ninguna garantía de ello y no se ha
medido.

#### 4.5.5 La historia, que es instructiva

El proyecto **ya miró esta función y no vio el problema**. El encabezado del test dice:

> «`compute_terrain_correction_prism` implementaba SOLO masa-puntual
> (G·ρ·área·|dh|/r²) pero el nombre/comentarios prometían "exact prism formula".
> Se renombró a `compute_terrain_correction_pointmass` (alias viejo deprecado).»
> (`tests/test_fase0_terrain_correction.py:1-6`)

Es decir: se detectó que **el nombre** mentía y se corrigió el nombre. Nadie preguntó si
**la fórmula** era correcta.

Y el docstring resultante contiene una afirmación que la medición desmiente:

> «La masa puntual converge al prisma en campo lejano (r ≫ tamaño de celda) y
> sobrestima en el campo cercano (r ≲ celda).»
> (`services/gravity_corrections_service.py:139-141`)

Es exactamente al revés: la discrepancia **crece** con la distancia ($2r/|\Delta h|$).
La afirmación sería cierta de una masa puntual con su componente vertical bien tomada;
no lo es de la expresión implementada.

#### 4.5.6 Por qué los tests no lo detectaron

Tres tests cubren esta función y ninguno puede detectar el error:

- `test_tc_non_negative_always` — comprueba $\text{TC}\ge0$. Se cumple con la fórmula
  correcta **y** con la incorrecta.
- `test_tc_flat_terrain_is_zero` — comprueba TC = 0 en terreno plano. También se cumple
  con ambas ($\Delta h=0$).
- `test_tc_matches_pointmass_formula` — **reimplementa la misma fórmula en el test** y
  comprueba que coincide con `rtol=1e-9`
  (`tests/test_fase0_terrain_correction.py:70-73`).

El tercero es **tautológico**: verifica que el código calcula lo que el código calcula.
Su propio docstring lo dice sin darse cuenta: «confirmando que ES masa-puntual y no un
prisma exacto» — confirma la *identidad* de la implementación, no su *corrección*.

Es un ejemplo de manual de la distinción entre **verificación** y **validación** (informe
12): la suite verifica perfectamente y no valida nada. Ningún test compara contra una
referencia física independiente (carta de Hammer, cilindro analítico, o la fórmula de
columna vertical).

#### 4.5.7 Qué falta para cerrarlo

Lo medido es la discrepancia entre las dos fórmulas. Lo que **no** se ha hecho:

- comparar contra una referencia canónica externa (una carta de Hammer o el TC publicado
  de un levantamiento conocido);
- medir cuánta de la señal espuria absorbe la separación regional–residual;
- cuantificar el efecto sobre un modelo invertido de extremo a extremo.

**Estado honesto: la fórmula implementada difiere de la formulación clásica en un factor
medido de $2r/|\Delta h|$, lo que en un caso realista da 12×. Que eso arruine un
resultado concreto depende de la topografía y del regional, y no se ha medido.**

### 4.6 Separación regional–residual

`separate_regional_residual` (`services/regional_residual_service.py:61`), ajuste
**polinómico** de orden configurable, con **orden 2 por defecto**
(`services/gravity_preprocessing_service.py:13`). Se aplica en el preprocesamiento antes
de la inversión (`services/inversion_kernel_service.py:216`).

Físicamente: se supone que las fuentes profundas y regionales producen una tendencia
suave que un polinomio de bajo grado captura, y que lo que queda (el residual) es la
señal de interés. Es la práctica estándar, pero es una decisión con consecuencias: un
polinomio de orden 2 sobre un área pequeña puede absorber parte de la señal de un cuerpo
grande.

---

## 5. La malla y el dominio efectivo

Dos podas reducen el dominio antes de invertir:

**Topografía.** Se activan sólo las celdas bajo el terreno:
`voxel_top = y_c − dy/2 ≥ topo_depth` (`exploration/potential_field_core.py:167-169`).
Si no se aporta topografía, se asume **terreno plano a cota 0** sin advertencia
(`exploration/potential_field_core.py:161-163`).

**Dominio observable.** Se descartan las celdas cuya sensibilidad a todos los sensores es
despreciable (norma de columna por debajo de $10^{-6}$ del máximo)
(`exploration/potential_field_core.py:180-189`). El argumento del código es correcto:
esas columnas sólo añaden un plateau de mínima norma y saturación espuria en los bounds.

Geofísicamente esto es sano: se está admitiendo que hay partes del modelo sobre las que
el dato no dice nada, y se las excluye en lugar de rellenarlas con regularización pura.

---

## 6. El modelo directo

### 6.1 Gravimetría

Tres regímenes según la distancia sensor–celda
(`exploration/gravimetry.py:773-931`):

| Régimen | Condición | Fórmula |
|---|---|---|
| Campo cercano | $r\le4a_{eq}$ | prisma exacto de **Nagy (1966)** |
| Campo lejano | $4a_{eq}<r\le r_{cut}$ | masa puntual, $G\rho V\Delta y/r^3$ |
| Fuera | $r>r_{cut}$ (800 m) | **cero exacto** |

con $a_{eq}=\sqrt{dx^2+dy^2+dz^2}$. La matriz resultante es dispersa (CSR, float64).

El truncamiento a 800 m **no tiene cota de error en el repositorio**: NO DETERMINADO.

### 6.2 Magnetometría

Modelo invertido: susceptibilidad $\kappa$ (SI), referencia $\kappa=0$
(`exploration/magnetometry.py:121-123`). Se calcula la anomalía TMI proyectada sobre el
campo ambiente, $\Delta T\approx\Delta\mathbf B\cdot\hat f$.

| Modo | Fórmula |
|---|---|
| `"dipole"` (**por defecto**) | $C(3\cos^2\theta-1)/r^3$, con $C=B_0V/4\pi$ |
| `"prism"` (opcional) | $D\,\hat f^\top\mathsf T\hat f$ (Bhattacharyya 1964; Sharma 1966) |

El código verifica la consistencia física del prisma comprobando que **converge
exactamente al dipolo en campo lejano**, y lo llama «la prueba de consistencia que valida
los signos del tensor» (`exploration/magnetometry.py:204-208`). Es una verificación
física genuina y poco común.

Nótese que el modo por defecto es el dipolo a toda distancia, pese a que el propio código
advierte que sesga la amplitud en cuerpos someros
(`exploration/magnetometry.py:165-170`).

**Remanencia:** $G_{tot}=G_{ind}+Q\,G_{rem}$ con $Q$ la razón de Koenigsberger y
dirección de remanencia independiente (`exploration/magnetometry.py:504`).

---

## 7. El problema inverso

### 7.1 El funcional

$$
\Phi(m)=\underbrace{\|W_d(Gm-d)\|^2}_{\text{misfit}}
+\underbrace{\lambda_{sp}^2\|L_a(m-m_{ref})\|^2}_{\text{suavidad}}
+\underbrace{\lambda_{ef}^2\sum_j(\|\text{col}_j(W_dG)\|\,m_j)^2}_{\text{ponderación por sensibilidad}}
$$

con $W_d=\operatorname{diag}(1/\sigma_i)$.

**Lo que un geofísico debe saber de este funcional, y que no es obvio:**

1. **No hay un *depth weighting* ajustable.** El proyecto intentó implementar el
   $W_z=(z+z_0)^{-\beta/2}$ de Li & Oldenburg (1998) y midió que **se cancelaba
   algebraicamente** contra el escalado de columnas que se aplicaba después
   (`exploration/gravimetry.py:2253-2270`). La ponderación efectiva es la norma de
   columna del kernel, que resulta equivalente a una ley de potencia con
   $\beta_{eq}\approx2{,}63$ (desviación máxima 5,3 %)
   (`exploration/potential_field_core.py:283-315`). Está en la misma familia que el
   $\beta=2$ estándar, algo más agresiva, pero **la fija el kernel, no el usuario**.

2. **El operador de suavidad es un Laplaciano, no una primera diferencia.** Se penaliza
   $\|Lm\|^2=m^\top L^2m$, un operador bi-armónico, mientras la referencia citada usa
   $\|\nabla m\|^2$ (informe 01, §2.7).

3. **Hay una condición de contorno implícita.** Restringir el Laplaciano al dominio
   activo por indexado deja filas que no suman cero, imponiendo de hecho contraste nulo
   en el aire y en el borde podado (`exploration/gravimetry.py:2233-2235`).

### 7.2 El ruido y $\chi^2$

$$
\sigma_i=\max(\text{piso},\ \text{pct}\cdot|d_i|)
\quad\text{o, si no se declara,}\quad
\sigma_i=\max(0{,}02|d_i|,\ 0{,}01\cdot\text{rango})
$$
(`exploration/potential_field_core.py:130`)

con detección de atípicos por MAD ($3\times1{,}4826\cdot\text{MAD}$) y des-peso $\times10$
(`exploration/potential_field_core.py:113-134`).

Existe una tabla de pisos de ruido **por modelo de gravímetro**
(`GRAVIMETER_NOISE_FLOOR`, `services/geophysics_service.py:3255-3258`), lo que permite un
$\chi^2$ físicamente interpretable cuando el usuario declara su instrumento.

**El sistema distingue correctamente los dos regímenes.** Cuando $\sigma$ es explícito,
$\chi^2_{red}$ es interpretable y se usa el **principio de discrepancia de Morozov**
($\chi^2\to1$) sobre el solver real. Cuando $\sigma$ es adaptativo, $\chi^2$ **no** es
interpretable y se recurre a un punto de operación fijo
(`services/geophysics_service.py:3196-3210`). Éste es un razonamiento geofísico correcto
y bien implementado.

*(Nota: la constante de ese punto de operación vale 0,1 mientras el comentario que la
justifica valida $\lambda\approx3$ — informe 01, §3.3.)*

### 7.3 Restricciones petrofísicas

Caja $[\rho_{min},\rho_{max}]$ transformada exactamente al espacio escalado
(`exploration/gravimetry.py:2292-2294`), con posibilidad de **bounds por unidad
litológica** en celdas de litología conocida (`exploration/gravimetry.py:2298-2310`).

**Un dato medido que el proyecto registra y que un geofísico debería conocer:** el bound
inferior de densidad **no es un default correcto o incorrecto, sino una variable de
régimen**. Según las mediciones internas del proyecto (48 inversiones E2E), a 250 m de
profundidad un bound permisivo recupera mucho mejor (PR-AUC 0,890 frente a 0,288), a
400 m gana el estricto por un factor 10–17 en profundidad, y a 600–900 m da igual porque
ninguno recupera.

### 7.4 Anclaje por sondajes

Los intervalos de sondaje se mapean a celdas por geometría pura
(`exploration/potential_field_core.py:191-247`), con dos modos: *hard* (la celda se elimina
como grado de libertad) y *soft* (restricción fuerte vía *smallness* con $\kappa$). Además
se **relaja localmente el Laplaciano** en las celdas ancladas
(`exploration/gravimetry.py:2244-2250`) para evitar halos, con el argumento correcto de
que el valor lo debe fijar la restricción y no el suavizado.

### 7.5 Inversión compacta (soporte mínimo)

Opcionalmente, un bucle IRLS con pesos $f_i=1/\sqrt{c_i^2+\varepsilon^2}$
(`exploration/potential_field_core.py:571`) aproxima una penalización de tipo $\ell_0$,
produciendo cuerpos compactos en lugar de manchas difusas. Referencias correctas:
Last & Kubik (1983), Portniaguine & Zhdanov (1999). $\varepsilon$ se enfría por homotopía
($\varepsilon\leftarrow0{,}7\varepsilon$), lo que es la estrategia adecuada.

---

## 8. Los límites de resolución: lo que la gravimetría no puede decir

### 8.1 La no unicidad en profundidad

Éste es el límite físico central, y el proyecto lo tiene **medido y declarado**:

> «LEY del null-space (MEDIDA en config de producción, 5 semillas): la gravedad-sola NO
> resuelve la profundidad absoluta. Un cuerpo PROFUNDO se recupera indistinguible de una
> PILA SOMERA.»
> (`services/geophysics_service.py:790-793`)

En consecuencia, el sistema **desacopla la confianza horizontal de la vertical**:

```python
if depth_independently_constrained:
    depth_confidence = confidence_level
else:
    depth_confidence = "LOW"
```
(`services/geophysics_service.py:801-810`)

y el mensaje al usuario dice que la profundidad mostrada «es INDICATIVA, no un dato
resuelto; el targeting confiable es el HORIZONTAL»
(`services/geophysics_service.py:806-810`).

Sólo un dato **independiente** (un sondaje real, explícitamente no el prior automático
derivado del espectro, que satura hacia los 350 m) eleva la confianza en profundidad.

Ésta es, a juicio de esta auditoría, la pieza de honestidad científica mejor resuelta de
todo el sistema. Es también la razón por la que el producto se posiciona como
**targeting** y no como estimación de recursos.

### 8.2 Qué sí resuelve

La posición **horizontal** de un contraste de densidad, que es lo que determina dónde
emplazar una perforación. Las validaciones externas del proyecto (DO-27, Raglan, San
Nicolás) apuntan a errores horizontales de decenas de metros, aunque su alcance real se
discute en el informe 12.

### 8.3 ⚠ PROBLEMA DETECTADO (no confirmado) — orientación del campo magnético

Resumen; el desarrollo completo está en el informe 03, §7.

| Fuente | Convención que fija | Evidencia |
|---|---|---|
| Ingesta de CSV | lon (Este) → $x$; lat (Norte) → $z$ | `services/gravity_import_service.py:311` |
| Exportación OMF | $x\to$ easting; $z\to$ northing | `services/omf_export_service.py:561` |
| Módulo magnético | $x$ = Norte; $z$ = Este | `exploration/magnetometry.py:82-84` |

El vector unitario implementado es
$\hat f=(\cos I\cos D,\ \sin I,\ \cos I\sin D)$
(`exploration/magnetometry.py:91-95`). Si $x$ es realmente Este, la componente **norte**
del campo está asignada al eje **este** y viceversa: la proyección horizontal del campo
inductor quedaría rotada 90°, equivalente a usar $D_{ef}=90°-D$. No se encontró
permutación compensatoria en el kernel (`exploration/magnetometry.py:313`, `330-335`).

**Por qué nadie lo vio.** La gravimetría es invariante a esa permutación: su kernel usa
sólo la componente vertical. Y los dos benchmarks magnéticos del proyecto son árticos
—DO-27 con $I=83{,}8°$ (`tests/test_do27_ingest.py:63`) y Raglan en Nunavut—, donde
$\cos I\approx0{,}11$ y el efecto es mínimo. El caso de uso declarado es Chile,
$I\approx-30°$, $\cos I\approx0{,}87$: el máximo posible.

**Estado: indicado por lectura de código en tres puntos, sin experimento que lo
confirme.** La prueba propuesta es directa: generar la respuesta TMI de un cuerpo
compacto con $I=-30°$, $D=2°$ y observar hacia dónde se desplaza el mínimo asociado. Con
la física correcta debe desplazarse hacia el **Norte**; si va hacia el **Este**, el
defecto está confirmado.

---

## 9. De modelo a interpretación: los tres niveles

**Lo que el código produce.** Un vector de contraste de densidad por celda, compatible
con los datos dentro del ruido declarado, más diagnósticos de sensibilidad, DOI y
confianza.

**Lo que matemáticamente significa.** Una de las infinitas soluciones compatibles,
seleccionada por la regularización y —en la práctica— también por el punto donde el
solver iterativo se detuvo (informe 02, §4.2).

**Lo que geofísicamente se puede afirmar.** Que existe un contraste de densidad en esa
posición horizontal capaz de explicar la anomalía. **No** se puede afirmar la profundidad
absoluta sin dato independiente (§8.1). **No** se puede afirmar que el contraste sea
mineralización: podría ser un cambio litológico, una intrusión estéril, una zona de
alteración o un artefacto de la regularización.

El sistema respeta esta última frontera en sus campos estructurados
(`"is_demo_grade": true`, `"assay_supported": false`), lo cual es correcto y poco común.

---

## 10. Resumen técnico

### Correctamente implementado

- Gravedad normal GRS80 (Somigliana) con las constantes oficiales.
- Aire libre dependiente de latitud **y con término de segundo orden**.
- Bouguer de placa infinita con coeficiente correcto y referencia adecuada.
- Orden de reducción correcto (marea → deriva → latitud → FAC → BC → TC → regional).
- Manejo "nunca adivina" en marea y deriva, con errores que preguntan.
- Salto de correcciones ya aplicadas según el tipo de dato de entrada.
- Prisma exacto de Nagy en campo cercano gravimétrico.
- Kernel magnético de prisma con verificación de consistencia por convergencia al dipolo.
- Desacople de la confianza en profundidad respecto de la horizontal, medido y declarado.
- Poda del dominio no observable en lugar de rellenarlo con regularización.

### Parcialmente implementado

- Marea y deriva existen y están bien hechas, pero **desactivadas por defecto**.
- El prisma magnético existe pero **no es el modo por defecto**.
- Separación regional–residual sólo polinómica (orden 2 por defecto).
- Topografía como máscara binaria; el fallback a terreno plano es silencioso.

### Problemas detectados

1. **Corrección de terreno físicamente incorrecta y activa por defecto** (§4.5).
   Usa el módulo de la atracción en vez de su componente vertical. Error medido
   $\approx2r/|\Delta h|$; 12× en un caso realista. **Medido.**
2. **Orientación horizontal del campo geomagnético posiblemente rotada 90°** (§8.3).
   **No confirmado experimentalmente.**
3. Truncamiento del kernel gravitacional a 800 m sin cota de error.
4. La suite de tests de la corrección de terreno es **tautológica** y no puede detectar
   (1).

---

## 11. Preguntas abiertas para revisión académica

---

### Pregunta 1 — La corrección de terreno (prioritaria)

**Pregunta.** El código calcula $\text{TC}=G\rho A|\Delta h|/r^2$, que es el **módulo** de
la atracción de la columna de terreno, no su componente vertical. Medimos que difiere de
la formulación clásica de columna vertical
$G\rho A(1/r-1/\sqrt{r^2+\Delta h^2})$ en un factor $\approx2r/|\Delta h|$: 200× a 1 km
con 10 m de desnivel, y 12× en el total de un cono de 500 m integrado a 22 km.
¿Confirma usted que la formulación implementada es incorrecta? ¿Y cuál recomendaría:
la columna vertical clásica (base de Hammer), el prisma exacto de Nagy —que el proyecto
ya tiene implementado para el kernel de inversión y podría reutilizar—, o un esquema
mixto por zonas?

**Por qué surge.** Se detectó leyendo la fórmula y se **midió** antes de afirmarlo.

**Evidencia.** `services/gravity_corrections_service.py:159-162` (la fórmula);
`services/gravity_import_service.py:1810` (`apply_terrain=True` por defecto);
`services/opentopo_service.py:341` (la cadena de llamada);
`services/gravity_corrections_service.py:125` (radio 22 km);
`tests/test_fase0_terrain_correction.py:70-73` (el test tautológico).

**Qué sabemos.** El factor de error analítico y su verificación numérica; que está activa
por defecto; que el término espurio es de longitud de onda larga y correlacionado con la
topografía.

**Qué NO sabemos.** Cuánto de ese término absorbe la separación regional–residual de
orden 2. Cuánto cambia un modelo invertido de extremo a extremo. Ninguna de las dos cosas
se ha medido.

**Qué opinión sería útil.** (a) Confirmación del diagnóstico. (b) Cuál es hoy la práctica
estándar recomendada para TC a partir de DEM (Hammer clásico, prismas, FFT de Parker).
(c) Si conviene además **limitar el radio de integración**: 22 km con una fórmula
$r^{-2}$ hace que zonas lejanas dominen, algo que no ocurriría con $r^{-3}$.

---

### Pregunta 2 — Marea y deriva desactivadas por defecto

**Pregunta.** Ambas correcciones están bien implementadas (Longman 1959; cierres de base)
pero con `apply_tide=False` y `apply_drift=False`. En un levantamiento real ambas son
obligatorias y la deriva puede ser de décimas de mGal por día, del mismo orden que la
señal. ¿Debería el sistema **rechazar** un `g_raw` que traiga columna de tiempo sin
aplicar marea, en lugar de permitir que se omitan silenciosamente?

**Evidencia.** `services/gravity_corrections_service.py:205-206`.

---

### Pregunta 3 — Regional–residual polinómico de orden 2

**Pregunta.** La separación regional–residual usa un polinomio de orden 2 por defecto.
Para un depósito grande dentro de un área pequeña, ¿cuánto riesgo hay de que el polinomio
absorba parte de la señal de interés? ¿Recomendaría un criterio para elegir el orden
(por ejemplo en función de la razón entre el tamaño del área y el tamaño esperado del
cuerpo), o directamente otro método (continuación ascendente, filtrado en número de onda)?

**Evidencia.** `services/gravity_preprocessing_service.py:13` (orden 2);
`services/regional_residual_service.py:95` (método polinómico).

**Relación con la Pregunta 1.** Si la TC introduce un término espurio de longitud de onda
larga, el regional podría estar absorbiéndolo — y en ese caso el regional estaría
haciendo un trabajo que no le corresponde, y el residual quedaría sesgado de forma
difícil de rastrear.

---

### Pregunta 4 — El *depth weighting* que fija el kernel

**Pregunta.** No hay un $\beta$ ajustable: la ponderación efectiva es la norma de columna
del kernel, medida como equivalente a $\beta_{eq}\approx2{,}63$ frente al $\beta=2$
estándar de Li & Oldenburg. ¿Le parece aceptable que el exponente lo determine la
geometría de adquisición en lugar de ser una decisión del intérprete? ¿Y $2{,}63$ es
razonable o excesivamente agresivo para exploración somera?

**Evidencia.** `exploration/gravimetry.py:2253-2278`;
`exploration/potential_field_core.py:283-315`.

**Qué sabemos.** Que en 3.450 inversiones ningún $\beta$ fijo mejoró la recuperación de
profundidad en todos los regímenes simultáneamente.

---

### Pregunta 5 — Terreno plano como supuesto silencioso

**Pregunta.** Sin topografía, el sistema asume semiespacio plano a cota 0 sin advertir.
En los Andes, con cientos de metros de relieve dentro del dominio, ¿qué magnitud de
artefacto esperaría? ¿Debería rechazarse la inversión en lugar de asumir plano?

**Evidencia.** `exploration/potential_field_core.py:161-163`.

---

### Pregunta 6 — Truncamiento del kernel a 800 m

**Pregunta.** Las contribuciones más allá de 800 m se descartan exactamente. Como el
número de celdas en una cáscara crece como $r^2$ mientras la contribución decae como
$r^{-2}$, cada cáscara aporta lo mismo y el truncamiento no es obviamente pequeño.
¿Existe una regla estándar para elegir ese radio en función del dominio y de la
profundidad de investigación?

**Evidencia.** `exploration/gravimetry.py:716`, `exploration/gravimetry.py:864-874`.

---

### Pregunta 7 — El bound de densidad como variable de régimen

**Pregunta.** El proyecto midió que el bound inferior de densidad no tiene un valor
correcto universal: a 250 m gana el permisivo (PR-AUC 0,890 vs 0,288), a 400 m gana el
estricto (10–17× en profundidad), a 600–900 m da igual. ¿Cómo recomendaría exponer esto
al usuario? ¿Debería el sistema **declarar el contraste efectivo**
($\rho_{min}-\rho_{base}$), que hoy es invisible, y pedir al intérprete que lo fije
según la profundidad esperada del objetivo?

---

### Pregunta 8 — La orientación del campo magnético

*(Desarrollada en el informe 03, §7 y Pregunta 1 de ese informe. Se referencia aquí
porque afecta directamente a la validez de toda inversión magnética y conjunta en
latitudes medias.)*

---

*Fin del informe 04. El informe 03 desarrolla la física de los kernels; el informe 01,
la formulación matemática; el informe 12, la validación y la incertidumbre.*
