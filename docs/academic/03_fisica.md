# INFORME 03 — FÍSICA
## Los fenómenos físicos que TerraQuantum modela, y cómo los aproxima

**Destinatario:** física · teoría de potencial · gravitación · magnetismo
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de los kernels de `exploration/gravimetry.py` y `exploration/magnetometry.py`, y de las rutas de ingesta y exportación que fijan el sistema de coordenadas.

> Este informe se puede leer sin haber leído los demás. Contiene una sección
> (§7) con un **problema físico detectado** que consideramos el hallazgo más
> importante de toda la auditoría hasta ahora, y que un físico puede evaluar
> sin conocer nada más del sistema.

---

## 1. Qué física hay realmente aquí

TerraQuantum modela **dos campos potenciales**, y sólo dos:

1. **El campo gravitacional** producido por variaciones laterales de densidad en el
   subsuelo.
2. **El campo magnético** producido por la magnetización de las rocas en presencia del
   campo geomagnético terrestre.

Ambos son campos potenciales clásicos, estáticos, en el vacío (o en un medio no
polarizable, que es la aproximación habitual en geofísica de exploración). No hay
electrodinámica, no hay propagación de ondas, no hay difusión, no hay dependencia
temporal. Esto simplifica enormemente el problema: los dos campos derivan de un
potencial escalar que satisface la ecuación de Laplace fuera de las fuentes.

La consecuencia física central, y conviene decirla antes que nada:

> Un campo que satisface la ecuación de Laplace fuera de sus fuentes **no determina
> unívocamente esas fuentes**. Es el teorema clásico de no unicidad de la teoría de
> potencial: existen distribuciones de masa no nulas cuyo campo externo es idénticamente
> cero (por ejemplo, una capa esférica con densidad total nula distribuida de cierto
> modo). Ninguna medición externa, por precisa que sea, puede distinguirlas.

Todo lo demás —la regularización, los diagnósticos de confianza, las restricciones
petrofísicas— es maquinaria para convivir con ese hecho físico.

---

## 2. Gravimetría: el fenómeno

### 2.1 De qué se trata físicamente

Un cuerpo mineralizado tiene, en general, una densidad distinta de la roca que lo
rodea. Un sulfuro masivo puede tener 4,0–4,5 t/m³ frente a 2,7 t/m³ de una roca de caja
silícea. Esa diferencia de densidad —el **contraste**, no la densidad absoluta— produce
una perturbación diminuta en el campo gravitacional terrestre, medible en superficie.

Los órdenes de magnitud importan para entender el problema:

| Cantidad | Valor típico |
|---|---|
| Gravedad terrestre $g$ | $9{,}8\ \text{m/s}^2$ |
| Anomalía de un depósito | $10^{-6}$ a $10^{-4}\ \text{m/s}^2$ (0,1–10 mGal) |
| Razón señal/campo total | $\sim10^{-7}$ a $10^{-5}$ |

Es decir: se busca una señal que es una parte en un millón del campo de fondo. Por eso
la cadena de correcciones (informe 04) es tan importante: hay que retirar efectos
—latitud, altitud, marea, deriva instrumental, terreno— que son órdenes de magnitud
mayores que lo que se busca.

### 2.2 La ley física

Todo procede de la ley de gravitación universal. Para una distribución continua de
densidad $\rho(\mathbf{r}')$, la componente vertical del campo en el punto de
observación $\mathbf{r}$ es

$$
g_z(\mathbf{r}) \;=\; G\int_{\Omega}\rho(\mathbf{r}')\,\frac{(z'-z)}{|\mathbf{r}'-\mathbf{r}|^{3}}\;dV'
$$

con $G$ la constante de gravitación universal. En el código:

```python
self.G = 6.67430e-11
```
(`exploration/gravimetry.py:721`)

Es el valor CODATA 2018 en unidades SI ($\text{m}^3\,\text{kg}^{-1}\,\text{s}^{-2}$). Correcto.

**La propiedad crucial:** la relación entre $\rho$ y $g_z$ es **lineal**. Duplicar la
densidad duplica la anomalía; la anomalía de dos cuerpos es la suma de sus anomalías.
Esto no es una aproximación: es exacto. Es lo que permite escribir el problema como un
sistema matricial y no como una optimización no lineal.

### 2.3 Qué se calcula exactamente: contraste, no densidad

El sistema **no** invierte la densidad absoluta. Invierte el **contraste** respecto de
una densidad de fondo `base_density` (`exploration/gravimetry.py:1270`). Los límites de
la caja petrofísica se transforman restando esa referencia:

```python
_lb_tilde = (float(density_min) - self.base_density) * _col_norms_wz
```
(`exploration/gravimetry.py:2292`)

**Por qué es físicamente correcto.** Una capa horizontal infinita y homogénea produce un
campo vertical constante en todo el semiespacio superior, y una anomalía **nula**: no
hay gradiente lateral. La gravimetría es intrínsecamente ciega al nivel absoluto de
densidad; sólo ve variaciones laterales. Invertir el contraste es la formulación
honesta.

**Consecuencia interpretativa que conviene no perder de vista.** Un resultado de
"+0,5 t/m³" no dice que la roca tenga 3,2 t/m³. Dice que tiene 0,5 t/m³ más que lo que
el operador declaró como fondo. Si `base_density` está mal elegida, todo el modelo se
desplaza.

---

## 3. El modelo directo gravimétrico: cómo se aproxima

Ésta es la pieza donde la física continua se convierte en aritmética. El código usa
**tres regímenes** según la distancia sensor–celda.

### 3.1 Campo cercano: la solución exacta del prisma (Nagy, 1966)

Para $r \le 4\,a_{eq}$, con $a_{eq}=\sqrt{dx^2+dy^2+dz^2}$ la diagonal del vóxel
(`exploration/gravimetry.py:824-825`), se usa la solución analítica cerrada de la
integral sobre un prisma rectangular de densidad constante.

Implementación en `exploration/gravimetry.py:733-770`. La estructura es la clásica suma
alternada sobre los ocho vértices del prisma:

$$
g \;=\; G\rho \sum_{i=1}^{2}\sum_{j=1}^{2}\sum_{k=1}^{2}(-1)^{i+j+k}
\Big[\,x\ln(z+r)\;+\;z\ln(x+r)\;-\;y\arctan\frac{xz}{y\,r}\,\Big]
$$

con $r=\sqrt{x^2+y^2+z^2}$ y $(x,y,z)$ las coordenadas del vértice relativas al sensor.
El código implementa exactamente esta expresión
(`exploration/gravimetry.py:764-765`).

**Qué representa físicamente.** Es la integral triple de $1/r^2$ sobre el volumen del
prisma, evaluada en forma cerrada. La suma alternada sobre vértices es la aplicación del
teorema fundamental del cálculo en tres dimensiones: la primitiva se evalúa en los
límites de integración, con signo según cuántas veces se toma el límite superior.

Es **exacta** para un prisma de densidad uniforme. No es una aproximación numérica: es
la antiderivada.

**La referencia.** Nagy (1966), *"The gravitational attraction of a right rectangular
prism"*, Geophysics 31(2). Es la referencia canónica y está correctamente citada
(`exploration/gravimetry.py:735`). Existen formulaciones posteriores más estables
numéricamente (Nagy, Papp & Benedek 2000; Heck & Seitz 2007) que el código no usa.

**Las singularidades y su tratamiento.** La expresión tiene singularidades reales:
$\ln(z+r)\to-\infty$ cuando el sensor está sobre una arista, y $\arctan(xz/yr)$ degenera
cuando $y\to0$ (sensor en el plano del prisma). El tratamiento
(`exploration/gravimetry.py:748-763`):

- $r=\sqrt{x^2+y^2+z^2+\varepsilon}$ con $\varepsilon=10^{-10}\cdot\min(dx,dy,dz)$;
- $\ln(\max(\cdot,\varepsilon))$ en lugar de $\ln(|\cdot|+\varepsilon)$;
- `arctan2(xz, yr+ε)` en lugar de `arctan(xz/(yr))`.

Físicamente, estas singularidades son integrables: el campo de un prisma es finito en
todas partes, incluso sobre sus aristas. Las divergencias son de la *primitiva*, no del
campo. El tratamiento con $\varepsilon$ es pragmático y numéricamente razonable, aunque
introduce un sesgo sistemático (siempre aumenta $r$, siempre reduce el campo). Con
$\varepsilon\sim10^{-9}$ m² frente a distancias métricas, el sesgo es despreciable.

**Nota positiva:** que $\varepsilon$ escale con el tamaño del vóxel en lugar de ser una
constante absoluta es la elección correcta y no es habitual verla.

### 3.2 Campo lejano: aproximación de masa puntual

Para $4a_{eq} < r \le r_{cutoff}$:

$$
g \;\approx\; \frac{G\,\rho\,V\,\Delta y}{r^{3}}
$$

(`exploration/gravimetry.py:872`, donde `_vol` es el volumen del vóxel y `dyv` la
componente vertical de la separación).

**Qué aproxima.** Toda la masa del prisma concentrada en su centroide. Es el primer
término del desarrollo multipolar del potencial del prisma.

**Cuándo es válida.** El error relativo del monopolo respecto del prisma exacto es del
orden de $(a/r)^2$, donde $a$ es la dimensión característica del cuerpo. A $r=4a_{eq}$
eso da un error de orden $(1/4)^2 \approx 6\%$... pero el término cuadrupolar de un
prisma casi cúbico es pequeño por simetría, de modo que el error real es bastante menor.

El umbral $4a_{eq}$ es una elección estándar y defendible. El código **no documenta**
una medición del error en la transición: NO DETERMINADO.

### 3.3 Más allá del corte: cero exacto

Para $r > r_{cutoff}$ (por defecto **800 m**, `exploration/gravimetry.py:716`), la
contribución se descarta y ni siquiera se almacena.

**Esto sí es una aproximación física fuerte, y merece atención.** El campo gravitacional
no tiene alcance finito. Truncarlo es afirmar que la masa lejana no contribuye, lo cual
es falso. El argumento habitual es que las contribuciones lejanas son suaves y quedan
absorbidas por la corrección regional (informe 04), pero eso es un argumento
cualitativo, no una cota.

**Contra-argumento cuantitativo que un físico debería sopesar:** el número de celdas en
una cáscara de radio $r$ y espesor $dr$ crece como $r^2$, mientras la contribución
individual decae como $r^{-2}$. El producto es **constante**: cada cáscara aporta
aproximadamente lo mismo. La contribución total diverge logarítmicamente con el radio del
dominio si la densidad no se anula. Truncar a 800 m es una decisión con consecuencias
que **no están acotadas en ninguna parte del código**.

*(Matiz: en la práctica el dominio del modelo es finito y suele ser menor que 1.600 m de
lado, de modo que el cutoff puede no activarse nunca. Pero entonces no está ahorrando
nada y no es una salvaguarda, es sólo un parámetro inerte.)*

### 3.4 Cómo entra la topografía

Las celdas se marcan activas o inactivas según estén bajo el terreno:

```python
voxel_top = y_c - dy/2.0
active_cells = voxel_top >= topo_depth
```
(`exploration/potential_field_core.py:167-169`)

**Fallback silencioso declarado.** Si no se proporciona topografía,
`topography_elevations=None` equivale a **terreno plano a cota 0**
(`exploration/potential_field_core.py:161-163`). El código lo identifica como un hallazgo
de auditoría previo (H-27) y conserva el comportamiento sin cambiarlo, pero al menos ya
está escrito en un solo sitio. Físicamente: se está asumiendo un semiespacio plano. Para
terrenos de relieve fuerte —y Chile los tiene— esto es una aproximación significativa.

---

## 4. Unidades: auditoría completa de la cadena gravimétrica

Éste es un punto donde los errores son fáciles y caros. La cadena real es:

| Etapa | Unidad | Evidencia |
|---|---|---|
| Dato del gravímetro / CSV | mGal | convención de campo |
| Conversión en la ingesta | mGal → m/s² (×$10^{-5}$) | `services/gravity_import_service.py:1284` (`convert_to_ms2`) |
| **Unidad interna del solver** | **m/s²** | `services/geophysics_service.py:3244` |
| Piso de ruido declarado | mGal → m/s² (×$10^{-5}$) | `services/geophysics_service.py:3252` |
| Modelo (incógnita) | **t/m³** | `exploration/gravimetry.py:713` |
| Conversión en el kernel | t/m³ → kg/m³ (×1000) | `exploration/gravimetry.py:770` |

La relación $1\ \text{mGal} = 10^{-5}\ \text{m/s}^2$ es correcta
($1\ \text{Gal}=1\ \text{cm/s}^2$, luego $1\ \text{mGal}=10^{-3}\ \text{cm/s}^2=10^{-5}\ \text{m/s}^2$).

El factor 1000 dentro del kernel convierte la densidad de t/m³ a kg/m³ para que sea
compatible con $G$ en SI (`exploration/gravimetry.py:768-770`). Correcto.

**Un detalle que confirma que las unidades importan.** El código documenta que el valor
por defecto del piso de ruido, `noise_floor = 0.02`, interpretado en SI significa
$0{,}02\ \text{m/s}^2 \approx 2000$ mGal, es decir, **cuatro órdenes de magnitud mayor
que cualquier señal real** (0,001–0,1 mGal) (`exploration/gravimetry.py:2205-2206`). Por
eso ese valor se reinterpretó como centinela de "no me declararon el ruido" en lugar de
como un piso literal. Es un caso instructivo: una unidad mal entendida convertida en
bandera semántica.

---

## 5. El sistema de coordenadas

### 5.1 La convención interna

El backend usa un sistema con la **profundidad como segundo eje y positiva hacia abajo**:

```
                    (superficie, y = 0)
        ────────────────────────────────────────►  x
       ╱│
      ╱ │
     ╱  │
    z   │
        ▼
        y  (profundidad, positiva HACIA ABAJO)
```

Declarado en `exploration/gravimetry.py:709-713`, `exploration/magnetometry.py:126-129`
y `exploration/treemesh.py:11`.

Es un sistema **levógiro** si se interpreta $y$ como "hacia abajo" con $x$ y $z$
horizontales en el orden dado — un punto que conviene tener presente al comparar con
convenciones geofísicas estándar, que suelen usar $(x=\text{Norte},\ y=\text{Este},\ z=\text{abajo})$
o $(x,y,z)$ dextrógiro con $z$ hacia arriba.

### 5.2 Qué eje horizontal es cuál — y aquí empieza el problema

Dos rutas independientes del código fijan el significado de $x$ y $z$, y coinciden:

**Ruta de entrada (ingesta de CSV):**
```
# 2. Lat/lon: lon→x_m slot, lat→z_m slot
```
(`services/gravity_import_service.py:311`)

Longitud (Este) → $x$. Latitud (Norte) → $z$.

**Ruta de salida (exportación OMF):**
```python
return np.column_stack([x_m + georef.easting0, z_m + georef.northing0, -y_m])
```
(`services/omf_export_service.py:561`)

$x$ + easting de origen, $z$ + northing de origen. Es decir: $x$ es **Este**, $z$ es
**Norte**.

**Conclusión, con dos evidencias independientes:**

$$
x = \text{ESTE}, \qquad y = \text{PROFUNDIDAD (abajo)}, \qquad z = \text{NORTE}
$$

**Por qué la gravimetría nunca lo notó.** El kernel gravimétrico usa
$\Delta y/r^3$ y la fórmula de Nagy con $y$ como eje vertical. La componente vertical del
campo de un prisma es **invariante bajo rotación en el plano horizontal**. Intercambiar
las etiquetas de $x$ y $z$ no cambia absolutamente nada en gravimetría. Por eso el
docstring de `gravimetry.py` se limita a decir "x: eje horizontal, z: eje horizontal"
(`exploration/gravimetry.py:710-712`) sin comprometerse — y hace bien, porque para
gravedad da igual.

Para magnetismo **no da igual en absoluto**.

---

## 6. Magnetometría: el fenómeno

### 6.1 Qué se mide y qué se modela

Un magnetómetro mide la **intensidad total** del campo magnético, $|\mathbf{B}|$. La
anomalía de intensidad magnética total (TMI) es la diferencia entre esa medición y el
campo geomagnético de referencia (IGRF).

El modelo invertido es la **susceptibilidad magnética** $\kappa$ (SI, adimensional), con
referencia $\kappa=0$ para roca no magnética, de modo que el contraste coincide con
$\kappa$ (`exploration/magnetometry.py:121-123`).

### 6.2 La física de la magnetización inducida

En presencia del campo geomagnético $\mathbf{B}_0$, una roca de susceptibilidad $\kappa$
adquiere una magnetización inducida

$$
\mathbf{M} \;=\; \kappa\,\mathbf{H}_0 \;=\; \kappa\,\frac{\mathbf{B}_0}{\mu_0}
$$

Esta magnetización produce a su vez un campo, que es el que se mide como anomalía. El
código documenta exactamente esta cadena (`exploration/magnetometry.py:186-190`).

**La cancelación de $\mu_0$.** El campo de un dipolo de momento $\mathbf{m}$ lleva un
factor $\mu_0/4\pi$; el momento lleva $1/\mu_0$ vía la magnetización. Los dos se
cancelan, dejando un prefactor puramente en nT:

```python
self.C = self.field_intensity_nt * self.voxel_volume / (4.0 * np.pi)   # nT·m³
self.D = self.field_intensity_nt / (4.0 * np.pi)                        # nT
```
(`exploration/magnetometry.py:158-162`)

La contabilidad dimensional es correcta y está bien explicada.

### 6.3 La aproximación TMI

El código calcula la **proyección de la anomalía sobre la dirección del campo ambiente**:

$$
\Delta T \;\approx\; \Delta\mathbf{B}\cdot\hat{f}
$$

Ésta es la aproximación estándar de anomalía de campo total, válida cuando
$|\Delta\mathbf{B}| \ll |\mathbf{B}_0|$. Es una linealización: la diferencia de módulos
$|\mathbf{B}_0+\Delta\mathbf{B}|-|\mathbf{B}_0|$ se aproxima por la proyección. El error
es de segundo orden en $|\Delta\mathbf{B}|/|\mathbf{B}_0|$.

Para anomalías de miles de nT sobre un campo de 23.500 nT
(`exploration/magnetometry.py:139`) la razón puede llegar a $\sim10\%$, y el error de
segundo orden a $\sim0{,}5\%$. Aceptable, pero no despreciable para cuerpos muy
magnéticos. **El código no declara esta aproximación como limitación** en ningún sitio
que se haya encontrado.

### 6.4 Los dos regímenes del kernel magnético

**Dipolo (por defecto, `near_field_mode="dipole"`):**

$$
\frac{\Delta T}{\kappa} \;=\; C\,\frac{3(\hat f\cdot\mathbf{d})^2-r^2}{r^5}
\;=\; C\,\frac{3\cos^2\theta-1}{r^3}
$$

(`exploration/magnetometry.py:333-335`), donde $\mathbf{d}$ es el vector
celda − sensor y $\theta$ el ángulo entre $\hat f$ y $\mathbf{d}$.

Nótese que ésta es la forma del campo dipolar **proyectado sobre la misma dirección de
la magnetización**, que es lo correcto para TMI cuando la magnetización es paralela al
campo ambiente (caso inducido puro).

**Prisma (opcional, `near_field_mode="prism"`):**

$$
\frac{\Delta T}{\kappa} \;=\; D\;\hat f^\top\, \mathsf{T}\, \hat f
$$

con $\mathsf{T}$ el tensor simétrico de segundas derivadas del potencial newtoniano del
prisma, evaluado por suma con signo sobre las 8 esquinas
(`exploration/magnetometry.py:192-202`). Las referencias citadas —Bhattacharyya (1964),
Sharma (1966), Blakely (1995 cap. 9)— son las correctas.

**Una prueba de consistencia que merece elogio.** El código documenta que en campo lejano
$\mathsf{T}_{ij}\to V(3d_id_j-r^2\delta_{ij})/r^5$, de modo que
$D\,\hat f^\top \mathsf{T}\hat f \to C(3\cos^2\theta-1)/r^3$: **recupera exactamente el
dipolo, con el mismo signo y la misma escala**, y llama a esa convergencia "la prueba de
consistencia que valida los signos del tensor"
(`exploration/magnetometry.py:204-208`). Es exactamente el tipo de verificación física
que uno querría ver, y no es frecuente encontrarla escrita.

**Importante:** el modo por defecto es `"dipole"` a toda distancia
(`exploration/magnetometry.py:140`), con el prisma como opción. El propio comentario
advierte que el dipolo «sobre/sub-estima la amplitud en cuerpos someros»
(`exploration/magnetometry.py:167-169`). Es decir: **por defecto, el sistema usa la
aproximación menos precisa justo donde más importa**, y el modo exacto existe pero no es
el predeterminado.

### 6.5 Remanencia

`build_kernel_with_remanence` (`exploration/magnetometry.py:444`) construye

$$
G_{total} = G_{ind} + Q\,G_{rem}
$$

donde $Q$ es la **razón de Koenigsberger** (cociente entre magnetización remanente e
inducida) y $G_{rem}$ se construye con una dirección de remanencia independiente
(`exploration/magnetometry.py:504`). Con $Q=0$ devuelve el kernel inducido sin coste
adicional (`exploration/magnetometry.py:465`).

Esto es físicamente correcto y relevante: en depósitos IOCG y de magnetita —comunes en
Chile— la remanencia puede dominar. **NO DETERMINADO:** si esta ruta está cableada al
flujo de producción o si sólo es accesible programáticamente. No se auditó la capa de
API magnética.

---

## 7. PROBLEMA DETECTADO — la dirección del campo geomagnético

Ésta es la sección más importante del informe.

### 7.1 Qué dice el código

```python
def field_unit_vector(inclination_deg, declination_deg):
    """
    Vector unitario f̂ del campo geomagnético inducido en coordenadas del backend
    (x=Norte, z=Este, y=profundidad + hacia abajo).

        f̂ = (cos I · cos D,  sin I,  cos I · sin D)
    """
    f = np.array([
        np.cos(I) * np.cos(D),   # x = Norte
        np.sin(I),               # y = profundidad (+ abajo)
        np.cos(I) * np.sin(D),   # z = Este
    ])
```
(`exploration/magnetometry.py:80-98`)

Con la convención que el docstring declara —$x$ = Norte, $z$ = Este— **la fórmula es
correcta**. Es la descomposición estándar del campo geomagnético en función de
inclinación $I$ y declinación $D$: componente norte $\cos I\cos D$, componente este
$\cos I\sin D$, componente vertical hacia abajo $\sin I$.

### 7.2 Qué dice el resto del sistema

Pero la convención declarada en ese docstring **contradice** a las otras dos rutas del
sistema, verificadas de forma independiente:

| Fuente | Qué afirma | Evidencia |
|---|---|---|
| Ingesta de CSV | lon (Este) → $x$; lat (Norte) → $z$ | `services/gravity_import_service.py:311` |
| Exportación OMF | $x$ + easting₀; $z$ + northing₀ | `services/omf_export_service.py:561` |
| Docstring magnético | $x$ = Norte; $z$ = Este | `exploration/magnetometry.py:82-84` |

**Dos contra uno**, y las dos que coinciden son las que tocan datos reales del usuario
(entrada y salida georreferenciada).

### 7.3 La consecuencia física

Si $x$ es realmente **Este** y $z$ es **Norte**, entonces el vector implementado

$$
\hat f = (\underbrace{\cos I\cos D}_{\text{va al eje ESTE}},\ \sin I,\ \underbrace{\cos I\sin D}_{\text{va al eje NORTE}})
$$

coloca la componente **norte** del campo sobre el eje **este**, y viceversa. Es decir:
**la proyección horizontal del campo inductor está rotada 90° respecto de la realidad.**

Equivalentemente: el sistema estaría usando una declinación efectiva
$D_{ef} = 90° - D$.

Verificado que no hay compensación posterior: el kernel toma las componentes en el mismo
orden y las multiplica por las separaciones en el mismo orden
(`exploration/magnetometry.py:313`, `exploration/magnetometry.py:330-335`).

### 7.4 Por qué esto importa mucho, y dónde importa poco

La forma de una anomalía magnética depende **fuertemente** de la dirección del campo
inductor. Un cuerpo compacto en un campo inclinado produce una anomalía **asimétrica**,
con un máximo desplazado y un mínimo asociado en el lado opuesto a lo largo de la
proyección horizontal del campo. Rotar esa dirección 90° rota el patrón de la anomalía.

La magnitud del efecto escala con $\cos I$, es decir, con cuánta componente horizontal
tiene el campo:

| Lugar | Inclinación $I$ | $\cos I$ | Severidad esperada |
|---|---|---|---|
| Chile (valor por defecto del código) | $-30°$ | **0,87** | **máxima** |
| DO-27, Territorios del Noroeste | $+83{,}8°$ | 0,11 | mínima |
| Raglan, Nunavut | ártico, $I\to90°$ | $\approx0{,}1$ | mínima |

El valor de DO-27 está verificado en `tests/test_do27_ingest.py:63`
(`inclination_deg == 83.8`).

**Y aquí está lo incómodo:** los dos únicos benchmarks magnéticos externos del proyecto
—DO-27 y Raglan— son de latitudes árticas, donde el campo es casi vertical y la
componente horizontal es apenas el 10 % del total. **Son precisamente los casos donde
este defecto sería casi invisible.** El caso de uso declarado del producto —Chile,
$I\approx-30°$— es precisamente donde sería máximo.

Esto no prueba que el defecto exista: prueba que **la validación existente no puede
detectarlo**. Es una limitación de cobertura, no una confirmación.

### 7.5 Qué falta para cerrarlo

Lo honesto es decir qué se hizo y qué no.

**Hecho:** se verificaron tres puntos del código independientes y se comprobó que el
kernel no aplica ninguna permutación compensatoria.

**No hecho:** no se ejecutó ningún experimento numérico. La prueba decisiva es barata y
se propone explícitamente:

> Construir un cuerpo sintético compacto, generar su respuesta TMI con
> $I=-30°$, $D=2°$, e inspeccionar hacia dónde se desplaza el mínimo asociado respecto
> del máximo. Con la física correcta debe desplazarse aproximadamente hacia el **Norte**
> (hemisferio sur, campo apuntando hacia arriba y al norte). Si se desplaza hacia el
> **Este**, el defecto está confirmado.

Mientras ese experimento no se haga, el estado correcto de esta afirmación es:
**fuertemente indicado por lectura de código, no confirmado experimentalmente.**

---

## 8. Qué física NO se modela

Por honestidad, y porque un físico lo preguntará:

**Auto-desmagnetización.** Para susceptibilidades altas ($\kappa \gtrsim 0{,}1$ SI), el
campo inducido dentro del cuerpo se opone al campo aplicado y reduce la magnetización
efectiva. La relación $\mathbf{M}=\kappa\mathbf{H}_0$ deja de ser válida y hay que
resolver $\mathbf{M}=\kappa(\mathbf{H}_0-N\mathbf{M})$ con $N$ el factor
desmagnetizante. Las notas del proyecto mencionan que existe trabajo sobre esto, pero
**NO DETERMINADO** si está en la ruta de producción; no se auditó.

**Anisotropía magnética.** $\kappa$ se trata como escalar. En rocas foliadas o con fábrica
mineral marcada es un tensor. No se modela.

**Efecto de terreno en magnetometría.** La topografía entra sólo por la máscara de celdas
activas.

**Corrección de terreno gravimétrica completa.** NO DETERMINADO — pertenece a la cadena de
correcciones (informe 04), no auditada en esta pasada.

**Curvatura terrestre y efecto de la esfericidad.** El modelo es cartesiano y plano. Para
dominios de pocos kilómetros es despreciable; para escala regional no.

**Gradiente vertical del campo geomagnético** dentro del dominio del modelo: se asume
$\mathbf{B}_0$ uniforme (un solo `field_intensity_nt`).

---

## 9. La distinción de tres niveles, aplicada

Es útil aplicar explícitamente la distinción que rige todo este expediente.

**Lo que el código hace.** Resuelve un sistema lineal cuya matriz codifica la respuesta
gravitacional (Nagy exacto / masa puntual / cero) o magnética (dipolo o prisma proyectado
sobre $\hat f$) de cada celda en cada sensor, y devuelve un vector de contrastes.

**Lo que matemáticamente significa.** Una de las infinitas distribuciones compatibles con
los datos, seleccionada por un criterio de regularización explícito, y en la práctica
también por el punto donde el solver iterativo se detuvo.

**Lo que físicamente se puede afirmar.** Que existe una distribución de contraste de
densidad (o susceptibilidad) que reproduce las observaciones dentro del ruido declarado.
**No** se puede afirmar que sea la distribución real. **No** se puede afirmar que un
volumen de alta densidad sea mineralización: podría ser un cambio litológico, una
intrusión estéril, una zona de alteración densa, o un artefacto de la regularización. La
gravimetría mide densidad; la densidad no es mena.

---

## 10. Resumen técnico

### Correctamente implementado

- Constante $G$ correcta (CODATA 2018) y contabilidad dimensional consistente.
- Solución exacta de Nagy (1966) para el prisma, con tratamiento cuidadoso y
  escala-consciente de las singularidades.
- Inversión del **contraste** y no de la densidad absoluta — la formulación físicamente
  honesta.
- Cadena de unidades mGal ↔ m/s² correcta y consistente.
- Cancelación de $\mu_0$ en el kernel magnético, correctamente razonada.
- Kernel de prisma magnético (Bhattacharyya/Sharma) con **verificación de consistencia
  física** por convergencia al dipolo en campo lejano.
- Remanencia como $G_{ind}+Q\,G_{rem}$ con dirección independiente.

### Parcialmente implementado

- **Prisma magnético en campo cercano**: existe pero no es el modo por defecto, pese a
  que el propio código dice que el dipolo sesga la amplitud en cuerpos someros.
- **Topografía**: entra sólo como máscara binaria de celdas activas (existe una opción
  de *cut-cell* que no se auditó).

### No implementado / no modelado

- Auto-desmagnetización (NO DETERMINADO en producción), anisotropía de $\kappa$,
  esfericidad, gradiente de $\mathbf{B}_0$.
- Cota del error por truncamiento del kernel a 800 m.

### Riesgos físicos, ordenados por gravedad

1. **La dirección horizontal del campo geomagnético parece estar rotada 90°** (§7).
   Máximo impacto justo en el caso de uso declarado (Chile). Los benchmarks disponibles
   no pueden detectarlo.
2. **El dipolo es el modo por defecto** en campo cercano, siendo el prisma la opción
   exacta y disponible.
3. **Terreno plano como fallback silencioso** cuando no se aporta topografía.
4. **Truncamiento del kernel sin cota de error.**
5. **La aproximación TMI no se declara** como limitación en ninguna parte.

---

## 11. Preguntas abiertas para revisión académica

---

### Pregunta 1 — La orientación del campo geomagnético (prioritaria)

**Pregunta.** Tres puntos del código fijan el significado de los ejes horizontales. Dos
—la ingesta de CSV y la exportación georreferenciada— establecen $x$ = Este, $z$ = Norte.
El tercero —el constructor del vector unitario del campo— documenta y usa $x$ = Norte,
$z$ = Este. ¿Confirma usted que, bajo la convención $x$ = Este, la componente norte del
campo ($\cos I\cos D$) está asignada al eje equivocado, y que el efecto es una rotación
de 90° de la proyección horizontal del campo inductor?

**Por qué surge.** Se detectó al cruzar la ruta de datos de entrada con la de salida,
no leyendo el módulo magnético aisladamente.

**Evidencia.** `services/gravity_import_service.py:311` · `services/omf_export_service.py:561`
· `exploration/magnetometry.py:80-98` · sin permutación compensatoria en
`exploration/magnetometry.py:313` y `330-335`.

**Qué sabemos.** Que la gravimetría es invariante a esta permutación (usa sólo la
componente vertical), lo que explica que el defecto sobreviviera. Que los dos benchmarks
magnéticos externos son árticos ($I\approx84°$, $\cos I\approx0{,}11$), donde el efecto
sería mínimo. Que el caso de uso declarado es Chile ($I\approx-30°$, $\cos I\approx0{,}87$),
donde sería máximo.

**Qué NO sabemos.** El impacto numérico real. **No se ha ejecutado ningún experimento.**

**Qué opinión sería útil.** (a) Confirmación de que el razonamiento físico es correcto.
(b) Cuál sería el diagnóstico más limpio y rápido para confirmarlo —proponemos observar
hacia dónde se desplaza el mínimo asociado de la anomalía de un cuerpo compacto, pero un
especialista quizá conozca uno mejor. (c) Si conoce casos publicados de este error, qué
sintomatología produjo.

---

### Pregunta 2 — El dipolo como modo por defecto en campo cercano

**Pregunta.** El kernel magnético usa por defecto la aproximación dipolar a toda
distancia, pese a que el propio código advierte que sobre o subestima la amplitud en
cuerpos someros, y pese a que el prisma exacto está implementado y verificado por
convergencia al dipolo. ¿Qué error de amplitud esperaría usted para un cuerpo cuyo techo
está a 2–4 anchos de celda del sensor? ¿Es suficiente para afectar a la profundidad
recuperada, o principalmente a la susceptibilidad?

**Evidencia.** `exploration/magnetometry.py:140` (modo por defecto);
`exploration/magnetometry.py:165-170` (la advertencia del propio código);
`exploration/magnetometry.py:175-208` (el prisma disponible).

**Qué sabemos.** Que el prisma converge exactamente al dipolo en campo lejano, luego
activarlo no introduce discontinuidad.

**Qué NO sabemos.** Si hay una razón de coste que justifique el defecto. El prisma
requiere 8 evaluaciones con logaritmos y arcotangentes frente a una operación aritmética.

---

### Pregunta 3 — Truncamiento del kernel gravitacional

**Pregunta.** Las contribuciones de celdas a más de 800 m se descartan exactamente. Dado
que el número de celdas en una cáscara crece como $r^2$ mientras la contribución decae
como $r^{-2}$, cada cáscara aporta aproximadamente lo mismo y el truncamiento no es
obviamente pequeño. ¿Considera aceptable el corte duro? ¿Existe una regla estándar para
elegirlo, o recomendaría un desarrollo multipolar para el campo lejano en su lugar?

**Evidencia.** `exploration/gravimetry.py:716` (el valor); `exploration/gravimetry.py:864-874`
(los tres regímenes).

**Qué NO sabemos.** La magnitud del error. NO DETERMINADO: no hay cota ni medición.

---

### Pregunta 4 — La aproximación TMI y su rango de validez

**Pregunta.** El sistema calcula $\Delta T\approx\Delta\mathbf{B}\cdot\hat f$, válida para
$|\Delta\mathbf{B}|\ll|\mathbf{B}_0|$. Con $B_0=23.500$ nT y anomalías que en depósitos de
magnetita pueden alcanzar varios miles de nT, la razón llega al 10 %. ¿A partir de qué
razón recomendaría usted abandonar la aproximación y calcular el módulo completo? ¿Y
convendría que el sistema **avisara** cuando la anomalía observada supere ese umbral?

**Evidencia.** `exploration/magnetometry.py:186-190`; $B_0$ por defecto en
`exploration/magnetometry.py:139`.

---

### Pregunta 5 — Terreno plano como supuesto silencioso

**Pregunta.** Si no se aporta topografía, el sistema asume un semiespacio plano a cota 0
sin emitir advertencia. En terreno andino con cientos de metros de relieve dentro del
dominio del modelo, ¿qué magnitud de artefacto esperaría? ¿Debería el sistema
**rechazar** la inversión sin topografía en lugar de asumir plano?

**Evidencia.** `exploration/potential_field_core.py:161-163`.

**Qué sabemos.** Que el proyecto identificó este fallback como hallazgo de auditoría
(H-27) y decidió conservarlo, documentándolo en un único sitio.

---

### Pregunta 6 — Densidad de fondo y su efecto sobre la interpretación

**Pregunta.** El modelo invierte el contraste respecto de `base_density`, un parámetro
del operador. Un error en esa referencia desplaza todo el modelo. ¿Qué práctica
recomienda para fijarla —promedio de densidades de sondaje, valor litológico tabulado,
estimación a partir del método de Nettleton— y debería el sistema exigirla en lugar de
tener un valor por defecto?

**Evidencia.** `exploration/gravimetry.py:1270` (parámetro con defecto 2,6);
`exploration/gravimetry.py:2292-2294` (cómo entra en los bounds).

**Nota relacionada.** Las notas internas del proyecto registran una medición según la
cual el bound inferior de densidad se comporta como **variable de régimen** y no como un
defecto correcto: a 250 m de profundidad un bound permisivo recupera mucho mejor, a 400 m
gana el estricto, y a 600–900 m da igual porque no se recupera nada. Eso sugiere que la
elección del par (`base_density`, `density_min`) no es un detalle de configuración sino
una decisión física con consecuencias medibles.

---

*Fin del informe 03. El informe 04 (geofísica) trata el flujo completo desde la
adquisición hasta la interpretación, incluidas las correcciones que no se cubren aquí;
el informe 01 trata la formulación matemática; el informe 12 trata la incertidumbre.*
