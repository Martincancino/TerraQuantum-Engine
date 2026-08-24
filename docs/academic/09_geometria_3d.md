# INFORME 09 — GEOMETRÍA COMPUTACIONAL Y 3D
## Sistemas de coordenadas, mallas, superficies y transformaciones

**Destinatario:** geometría computacional · gráficos por computador · métodos de malla
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `terraquantum-web/lib/terraQuantumGeology.ts`, `componentes/Scene3D.tsx`, `lib/render/IsosurfaceMeshLayer.tsx`, `lib/terraquantum/frontendApi.ts`, y en el backend `services/isosurface_service.py`, `services/omf_export_service.py`, `exploration/gravimetry.py`, `services/borehole_desurvey_service.py`.

> Autocontenido. Contiene un **problema geométrico detectado** (§4) que
> consideramos serio y que se puede verificar en treinta segundos abriendo la
> aplicación.

---

## 1. Cuántos sistemas de coordenadas hay realmente

Éste es el problema central de este informe. Un dato geofísico atraviesa **cinco**
sistemas de coordenadas distintos entre el instrumento y la pantalla, y cada frontera
entre dos de ellos es una oportunidad de equivocarse en un signo o en un eje.

```
(1) GEOGRÁFICO            lat / lon / elevación                 [grados, m AMSL]
       │  pyproj, zona UTM, eventual Helmert
       ▼
(2) PROYECTADO            easting / northing / elevación        [m, m, m AMSL]
       │  resta del origen local
       ▼
(3) MODELO (backend)      x=Este · y=PROFUNDIDAD↓ · z=Norte     [m]
       │  ¿centrado? ¿inversión de Y?
       ▼
(4) ESCENA (Three.js)     X derecha · Y ARRIBA · Z hacia cámara [unidades de escena]
       │  cámara, proyección
       ▼
(5) PANTALLA              píxeles
```

La frontera (3)→(4) es donde está el problema, porque los dos sistemas discrepan en el
**significado del eje vertical**: en (3) crecer significa bajar; en (4) crecer significa
subir.

---

## 2. El sistema del modelo, y cómo se establece

### 2.1 La convención

$$
x = \text{ESTE},\qquad y = \text{PROFUNDIDAD (positiva hacia abajo)},\qquad z = \text{NORTE}
$$

Está confirmada por **tres** rutas independientes del código:

| Fuente | Evidencia |
|---|---|
| Ingesta de CSV | `services/gravity_import_service.py:311` — «lon→x_m slot, lat→z_m slot» |
| Exportación georreferenciada | `services/omf_export_service.py:561` — `x_m + easting₀`, `z_m + northing₀`, `−y_m` |
| Módulo de sondajes | `services/borehole_desurvey_service.py:16-17` — «x=este, z=norte […] y=profundidad POSITIVA hacia abajo» |

Y está declarada en los motores de física (`exploration/gravimetry.py:709-713`,
`exploration/treemesh.py:11`).

**Observación sobre la quiralidad.** Con $x$ hacia el Este, $z$ hacia el Norte e $y$ hacia
abajo, el triedro $(x,y,z)$ es **levógiro**. La convención geofísica más común es
$(\text{Norte}, \text{Este}, \text{abajo})$, que es dextrógira. No es un error —una
convención levógira es perfectamente utilizable si se aplica consistentemente— pero
significa que **cualquier producto vectorial, normal o rotación importada de una fuente
externa necesita revisión de signo**.

*(Existe además una inconsistencia en el módulo magnético, que declara $x$=Norte y
$z$=Este. Se desarrolla en el informe 03 §7; aquí sólo se registra porque afecta a la
coherencia geométrica del sistema.)*

### 2.2 El orden de indexado

La malla $n_x\times n_y\times n_z$ se aplana en **orden Fortran**:

```python
idx_grid = np.arange(total_voxels).reshape((nx, ny, nz), order="F")
```
(`exploration/gravimetry.py:1330-1333`)

El código marca el orden F como **obligatorio** y advierte que los pesos deben ravelarse
en el mismo orden para que el peso $k$ corresponda a la arista $k$
(`exploration/gravimetry.py:1345-1348`).

Matemáticamente el orden es una permutación irrelevante; prácticamente determina la
estructura de banda del Laplaciano y —más importante— un desajuste entre módulos produce
un modelo transpuesto **sin ningún error visible**. El proyecto ya sufrió un caso: el
`model.msh` en disco declara dimensiones `20 20 10` y el del mismo modelo dentro del ZIP
declara `20 10 20` (informe 11).

---

## 3. Las mallas

Hay tres tipos de discretización espacial:

**Malla regular uniforme.** Vóxeles idénticos de lado `block_size`. El caso base.

**Malla tensorial no uniforme.** Espaciados variables `hx`, `hy`, `hz`. El Laplaciano se
adapta con pesos de arista $w_{ij}=2/(h_i+h_j)$ —el inverso de la distancia real entre
centros— (`exploration/gravimetry.py:1358-1381`). El código valida la convergencia al caso
uniforme: con `hx = [h₀]*N` se obtiene $L_{nu} = (1/h_0)L_u$ con error $<10^{-10}$
(`exploration/gravimetry.py:1300-1302`, `1321-1323`).

**Octree / TreeMesh** (`exploration/treemesh.py`), con celdas de tamaño variable y una ruta
de kernel dedicada que usa el tamaño y volumen **por celda** en lugar del escalar uniforme
(`exploration/gravimetry.py:946`). El código declara que esta ruta es aditiva y *opt-in*:
con `cell_d* = None` el comportamiento es byte-idéntico al uniforme
(`exploration/gravimetry.py:790-793`).

**Padding.** Celdas periféricas que absorben efectos de borde, distinguidas por máscara.

**Dominio activo.** Dos podas geométricas reducen la malla antes de resolver:
topografía (`voxel_top = y_c − dy/2 ≥ topo_depth`,
`exploration/potential_field_core.py:167-169`) y dominio observable (celdas cuya norma de
columna en el kernel cae por debajo de $10^{-6}$ del máximo,
`exploration/potential_field_core.py:180-189`).

---

## 4. ⚠ PROBLEMA DETECTADO — vóxeles e isosuperficies no comparten el eje vertical

Ésta es la sección principal del informe.

### 4.1 Lo que hace la capa de vóxeles

En `updateInstancedBuffers`, la posición de cada instancia se compone así
(`terraquantum-web/lib/terraQuantumGeology.ts:476-487`):

```js
const rawY = getCellNumber(cell, ["y", "cy"], 0);
ry_visual = rawY;                                   // sin negación
const rx_visual = getCellNumber(cell, ["x", "cx"], 0);
const rz_visual = getCellNumber(cell, ["z", "cz"], 0);
```

Y el docstring lo confirma explícitamente
(`terraquantum-web/lib/terraQuantumGeology.ts:352-361`):

> ```
> x_visual = voxel.x   (raw Easting)
> y_visual = voxel.y   (raw Y)
> z_visual = voxel.z   (raw Northing)
> ```

El valor `cell.y` llega **crudo** del backend: el cliente de API lo asigna sin transformar,
`y: ys[i]` (`terraquantum-web/lib/terraquantum/frontendApi.ts:2157`).

Estas instancias se montan bajo un grupo que aplica **sólo una traslación**:

```jsx
<group position={[-modelCenter[0], -modelCenter[1], -modelCenter[2]]}>
```
(`terraquantum-web/componentes/Scene3D.tsx:1954`)

sin escala negativa ni rotación. Y `modelCenter` es el centro de la caja envolvente
(`terraquantum-web/componentes/Scene3D.tsx:1694-1701`).

**Consecuencia geométrica:**

$$
Y_{\text{mundo}}^{\text{vóxel}} = y_m - c_y
$$

Como $y_m$ es profundidad positiva hacia abajo y en Three.js $+Y$ es **arriba**, las celdas
**más profundas se dibujan más arriba**. El modelo de vóxeles está invertido
verticalmente respecto de la realidad física.

### 4.2 Lo que hace la capa de isosuperficies

El backend entrega los vértices **ya transformados al espacio visual**, con inversión de Y
y centrado. La transformación está documentada donde el exportador OMF tiene que
deshacerla (`services/omf_export_service.py:552-556`):

> «`isosurface_service` entrega los vértices centrados y con flip-Y para Three.js:
> `vx = x_m − cx`, `vy = cy − y_m`, `vz = z_m − cz`.»

La capa del frontend **no aplica ninguna transformación posicional**: decodifica el base64
y lo pasa directamente a un `BufferAttribute`
(`terraquantum-web/lib/render/IsosurfaceMeshLayer.tsx:117-123`). Y se monta **bajo el mismo
grupo** (`terraquantum-web/componentes/Scene3D.tsx:1971`).

**Consecuencia geométrica:**

$$
Y_{\text{mundo}}^{\text{iso}} = (c_y^{iso} - y_m) - c_y
$$

### 4.3 Las dos capas discrepan

Comparando:

| Capa | $Y$ en el mundo | Comportamiento con la profundidad |
|---|---|---|
| Vóxeles | $y_m - c_y$ | más profundo → **más arriba** |
| Isosuperficies | $c_y^{iso} - y_m - c_y$ | más profundo → **más abajo** |

Son **imágenes especulares** una de otra respecto del eje vertical. Además, como la
isosuperficie ya viene centrada por el backend y el grupo vuelve a restar el centro, queda
**doblemente centrada**: desplazada $c_y^{iso}$ en $Y$, y análogamente $c_x^{iso}$ y
$c_z^{iso}$ en horizontal.

Y sin embargo, el comentario junto al montaje afirma lo contrario
(`terraquantum-web/componentes/Scene3D.tsx:1968-1970`):

> «Mismo grupo centrado que los vóxeles → **superposición exacta**.»

Lo mismo el encabezado de la capa
(`terraquantum-web/lib/render/IsosurfaceMeshLayer.tsx:13-15`):

> «se superponen **pixel-a-pixel** con los vóxeles al montarse bajo el MISMO grupo padre.»

Y el propósito declarado del modo combinado es que los vóxeles se muestren tenues «detrás
de la cáscara suave, para que se vea que la superficie es el núcleo denso de la nube»
(`terraquantum-web/componentes/Scene3D.tsx:1960-1962`) — es decir, el diseño **depende** de
la superposición exacta.

### 4.4 Qué falta para cerrarlo, y cómo comprobarlo en treinta segundos

**Lo que se hizo:** se leyeron las cuatro piezas —construcción del vóxel, cliente de API,
capa de isosuperficies y grupo padre— y se comprobó que ninguna aplica una negación o un
centrado compensatorio.

**Lo que no se hizo:** no se ejecutó la aplicación ni se inspeccionaron valores reales de
`center_m`. Es posible que en la práctica $c^{iso}=(0,0,0)$ si la malla del backend ya vive
en coordenadas locales centradas, lo que anularía el desfase horizontal — **pero no la
inversión de Y**, que no depende del centro.

**La comprobación decisiva** no necesita herramientas:

> Cargar un modelo con un cuerpo denso somero, **activar las isosuperficies** y mirar. Si
> la superficie aparece **dentro** de la nube de vóxeles densos, no hay problema. Si
> aparece **espejada** respecto del plano medio (arriba cuando la nube está abajo), el
> defecto está confirmado.
>
> Complemento: mirar si la profundidad crece hacia arriba en la escena de vóxeles.

**Estado honesto: inconsistencia derivada de la lectura de cuatro archivos, contradicha
por dos comentarios del propio código, sin verificación visual.** Que dos comentarios
independientes afirmen la superposición sugiere que en algún momento funcionó; el
candidato más probable es que la transformación del backend o la del frontend cambiara
sin actualizar la otra.

### 4.5 Por qué importa geométricamente

Más allá del aspecto: si la profundidad crece hacia arriba en la escena, entonces

- las **secciones** y los **planos de corte** operan sobre un eje invertido;
- el **picking** devuelve la celda correcta sólo si usa índices y no posición;
- las **anotaciones de profundidad** en los tooltips pueden ser coherentes con el dato
  pero incoherentes con lo que el usuario ve;
- y cualquier juicio visual del tipo «el cuerpo está bajo el sondaje» se invierte.

---

## 5. Extracción de superficies

`services/isosurface_service.py` implementa la cadena completa:

**Marching cubes** de `skimage.measure` (`services/isosurface_service.py:338-349`), con la
guarda correcta: exige $v_{min}<\text{nivel}<v_{max}$, y si no se cumple no hay superficie
en lugar de devolver una malla degenerada.

**Orientación de las caras.** Se calcula el volumen con signo y se invierte el *winding* si
resulta negativo (`services/isosurface_service.py:239-253`). Es la comprobación correcta:
el signo del volumen encerrado por una malla cerrada depende de la orientación de sus
triángulos, de modo que sirve como test global de consistencia.

**Suavizado de Taubin** (`services/isosurface_service.py:269`). La elección importa: el
suavizado laplaciano simple **encoge** la malla monótonamente (un cuerpo suavizado 20 veces
tiende a un punto). Taubin alterna un paso de contracción $\lambda$ con uno de expansión
$\mu<0$, de modo que el volumen se preserva aproximadamente. Es la elección correcta para
una superficie cuyo volumen encerrado se reporta.

**Normales** recalculadas por vértice a partir de las caras
(`services/isosurface_service.py:254`), y una dirección "hacia afuera" definida como
$-\nabla|\text{contraste}|$ muestreada por interpolación trilineal
(`services/isosurface_service.py:375-379`).

Ese último punto tiene un detalle geométrico que conviene señalar:

```python
outward = np.column_stack([-gi, gj, -gk])  # x:−g, y:+g (flip), z:−g
```
(`services/isosurface_service.py:379`)

El signo de la componente $Y$ es **opuesto** al de $X$ y $Z$ precisamente porque el espacio
visual invierte $Y$. Es decir: **este módulo sí sabe que hay un flip y lo compensa**. Eso
refuerza la lectura de §4: el backend está produciendo espacio visual con flip, y la capa
de vóxeles del frontend no lo aplica.

**Niveles de detalle** por submuestreo con paso dependiente del número de celdas
(`services/isosurface_service.py:317`).

---

## 6. Cortes, planos de recorte y secciones

`computeClippingPlanes` (invocado en `terraquantum-web/componentes/Scene3D.tsx:1703-1709`)
construye planos de `THREE.Plane` a partir del eje y la posición del corte. Se combinan con
planos opcionales de caja de recorte (`Scene3D.tsx:1713-1715`) y se pasan a los materiales
de todas las capas —vóxeles, isosuperficies, sondajes— de modo que el corte es coherente
entre capas.

El recorte de Three.js opera en **espacio de mundo**, lo que significa que hereda cualquier
problema del §4: si dos capas están en espacios verticales distintos, un plano de corte
horizontal las corta a profundidades distintas.

Existe además un modo de **sección pintada**: el backend calcula un raster de contraste
sobre el plano de corte y el frontend lo dibuja sobre la capa correspondiente
(`terraquantum-web/componentes/Scene3D.tsx:1986-1989`), con la nota explícita de que «el
dato del backend manda; esto solo lo dibuja».

En el selector de eje de sección, el mapeo de ejes a coordenadas de textura está
explícito (`terraquantum-web/componentes/Scene3D.tsx:1412-1422`): para un corte según un
eje se eligen las dos coordenadas restantes como $(u,v)$, incluyendo `["y","cy"]` como
coordenada vertical de la imagen.

---

## 7. Picking y selección

La selección de vóxeles opera sobre `InstancedMesh`, que en Three.js expone el
`instanceId` del rayo intersectado. El grupo de anotación se posiciona con
`position={selectedVoxel.position}` (`terraquantum-web/componentes/Scene3D.tsx:1339`), es
decir, con la posición **visual** de la instancia.

El tooltip muestra `depth_below_surface_m` leído del dato
(`terraquantum-web/componentes/Scene3D.tsx:1288`, `1323`), no derivado de la geometría de la
escena. Ésa es la decisión correcta: la profundidad que se informa proviene del backend y
no de la posición en pantalla, de modo que es robusta frente a cualquier transformación
visual.

---

## 8. Geometría de los sondajes

Los sondajes se dibujan como cilindros bajo el mismo grupo centrado, «→ caen donde el pozo
cruza el cuerpo» (`terraquantum-web/componentes/Scene3D.tsx:1977-1979`).

La traza proviene del desurvey por curvatura mínima
(`services/borehole_desurvey_service.py:78`), que devuelve las columnas en el orden
`(este, norte, profundidad)` (`services/borehole_desurvey_service.py:74`) — **distinto** del
orden de ejes del modelo, que es $(x,y,z)=(\text{este},\text{profundidad},\text{norte})$.
El consumidor debe remapear. La función documenta su salida, de modo que no es un error,
pero es exactamente el tipo de frontera donde un descuido produce un intercambio de ejes
silencioso.

---

## 9. Elevación real frente a profundidad

Existe un modo alternativo en el que el eje vertical representa **elevación absoluta** en
lugar de profundidad (`terraquantum-web/lib/terraQuantumGeology.ts:479-485`):

```js
if (elevationEnabled) {
  const elev = Number(cell.voxel_elevation_masl);
  ry_visual = Number.isFinite(elev) ? elev - refElev : rawY;
}
```

Nótese que $\text{elev}-\text{refElev}$ **sí** crece hacia arriba, de modo que en este modo
la orientación vertical es la correcta. Es decir: **los dos modos del visor usan
convenciones verticales opuestas**, y el respaldo cuando falta el dato de elevación es
`rawY`, que es la profundidad — mezclando ambas.

Varias capas se desactivan en modo elevación —isosuperficies, sección pintada, velo DOI—
con el argumento de que «usan la grilla regular, no el retículo deformado por vóxel»
(`terraquantum-web/componentes/Scene3D.tsx:1969-1970`, `1988`, `1993`). Eso sugiere que la
incompatibilidad entre ambos espacios ya era conocida, y que la solución adoptada fue
apagar las capas en conflicto en lugar de unificar el espacio.

---

## 10. Resumen técnico

### Correctamente implementado

- Convención de ejes del modelo declarada y consistente en tres rutas independientes.
- Orden Fortran explícito y marcado como obligatorio, con advertencia sobre los pesos.
- Laplaciano no uniforme con pesos de arista correctos y convergencia validada al caso
  uniforme.
- Ruta de octree aditiva y byte-idéntica cuando no se activa.
- Marching cubes con guarda de nivel válido.
- Corrección de orientación de caras por volumen con signo.
- Suavizado de Taubin (no encoge), correcto para reportar volumen encerrado.
- Compensación explícita del flip de $Y$ en el cálculo de la dirección exterior de la
  superficie.
- La profundidad del tooltip proviene del dato, no de la geometría de la escena.
- Planos de corte compartidos entre todas las capas.

### Problemas detectados

1. **Vóxeles e isosuperficies parecen no compartir el eje vertical** (§4), y además la
   isosuperficie quedaría doblemente centrada. Dos comentarios del código afirman lo
   contrario. **Sin verificación visual.**
2. **La capa de vóxeles dibuja la profundidad hacia arriba** al no negar $y$ antes de
   entregarla a Three.js.
3. **Los dos modos del visor (profundidad y elevación) usan orientaciones verticales
   opuestas**, con respaldo cruzado cuando falta el dato.
4. El docstring de `VolumeRaymarchLayer` dice «when wired into Scene3D, a later slice»
   pero la capa **ya está montada** (`Scene3D.tsx:1144`): documentación desactualizada.

### Riesgos geométricos

- Un triedro levógiro exige revisar el signo de toda normal o rotación importada.
- La frontera desurvey→modelo cambia el orden de las componentes.
- El doble centrado y el flip son invisibles en un modelo simétrico y evidentes en uno
  asimétrico: el tipo de defecto que pasa las pruebas y falla con el dato real.

---

## 11. Preguntas abiertas para revisión académica

---

### Pregunta 1 — La inconsistencia vertical entre capas (prioritaria)

**Pregunta.** La capa de vóxeles coloca la profundidad cruda en el eje $Y$ de Three.js
(donde $+Y$ es arriba), mientras que las isosuperficies llegan del backend ya con
$v_y = c_y - y_m$ y se montan bajo el mismo grupo, que vuelve a restar el centro. La
lectura da $Y^{vox} = y_m - c_y$ frente a $Y^{iso} = c_y^{iso} - y_m - c_y$: especulares y
con un desfase adicional. ¿Confirma usted que esas dos expresiones no pueden coincidir
salvo en un plano? ¿Y cuál de las dos convenciones recomendaría fijar como canónica para
toda la escena?

**Por qué surge.** Dos comentarios del código afirman superposición exacta, y el diseño del
modo combinado (vóxeles tenues + cáscara suave) depende de ella.

**Evidencia.** `lib/terraQuantumGeology.ts:352-361` y `476-487` (vóxeles crudos);
`lib/terraquantum/frontendApi.ts:2157` (`y: ys[i]`);
`services/omf_export_service.py:552-556` (la transformación del backend);
`lib/render/IsosurfaceMeshLayer.tsx:117-123` (sin transformación);
`componentes/Scene3D.tsx:1954` y `1971` (el grupo y el montaje);
`componentes/Scene3D.tsx:1968-1970` (el comentario que afirma lo contrario).

**Qué sabemos.** Que `isosurface_service` **sí** compensa el flip al calcular la dirección
exterior (`services/isosurface_service.py:379`), lo que confirma que el backend produce
espacio visual con $Y$ invertida.

**Qué NO sabemos.** El valor real de `center_m` en una corrida, y por tanto si el desfase
horizontal existe además del vertical. **No se ejecutó la aplicación.**

**Qué opinión sería útil.** Sobre todo metodológica: ¿dónde debería vivir la conversión
modelo→escena? Nuestra intuición es que el backend **no** debería emitir coordenadas de
presentación y que el flip debería ser responsabilidad exclusiva de una única función del
frontend; pero quizá haya razones de rendimiento para lo contrario.

---

### Pregunta 2 — ¿Dónde debe ocurrir la conversión de espacio?

**Pregunta.** Hoy la responsabilidad está repartida: el servicio de isosuperficies emite
coordenadas ya centradas y con flip para Three.js, mientras que los vóxeles viajan crudos y
el frontend los centra. Como principio de diseño en visualización científica, ¿recomienda
que el backend emita **siempre** coordenadas físicas y que toda conversión a espacio de
presentación viva en el cliente? El coste sería recorrer los vértices en el cliente; el
beneficio, un único punto donde el signo puede equivocarse.

**Evidencia.** `services/isosurface_service.py:380-395` (el backend produce espacio visual);
`services/omf_export_service.py:550-561` (el exportador tiene que **deshacerlo** para
georreferenciar).

**Nota.** El hecho de que el exportador OMF tenga que invertir la transformación del visor
para producir coordenadas geográficas es, en sí mismo, un indicio de acoplamiento indebido.

---

### Pregunta 3 — Un triedro levógiro

**Pregunta.** El sistema del modelo $(x=\text{E}, y=\downarrow, z=\text{N})$ es levógiro,
mientras que la convención geofísica habitual $(\text{N},\text{E},\downarrow)$ es
dextrógira. ¿Considera que merece la pena migrar a la convención estándar, dado el coste de
tocar todos los kernels, o basta con documentarla y revisar caso por caso los productos
vectoriales? ¿Qué operaciones concretas vigilaría?

**Evidencia.** `exploration/gravimetry.py:709-713`;
`services/borehole_desurvey_service.py:16-21`.

**Qué sabemos.** Que el módulo magnético ya declara una convención distinta de la del resto
del sistema (informe 03 §7), lo que sugiere que la convención no estándar ya causó al menos
una confusión.

---

### Pregunta 4 — Dos modos verticales opuestos en el mismo visor

**Pregunta.** El modo "profundidad" dibuja $y$ crudo (crece hacia arriba en escena) y el
modo "elevación" dibuja $\text{elev}-\text{refElev}$ (crece hacia arriba correctamente).
Además, cuando falta el dato de elevación, el modo elevación cae a `rawY`. Varias capas se
apagan en modo elevación por incompatibilidad declarada. ¿Recomendaría unificar ambos modos
a un único espacio vertical con signo consistente, aunque eso obligue a recalcular la
posición de todas las capas?

**Evidencia.** `lib/terraQuantumGeology.ts:479-485`;
`componentes/Scene3D.tsx:1969-1970`, `1988`, `1993`.

---

### Pregunta 5 — El suavizado de Taubin y el volumen reportado

**Pregunta.** Las isosuperficies se suavizan con Taubin y se reporta el volumen encerrado
(`enclosed_volume_m3`). Taubin preserva el volumen **aproximadamente**, no exactamente.
¿Qué error de volumen esperaría para el número de iteraciones habitual, y debería el
sistema reportar el volumen **antes** del suavizado —que es el que corresponde al campo
invertido— en lugar del posterior?

**Evidencia.** `services/isosurface_service.py:269-308` (Taubin);
`lib/render/IsosurfaceMeshLayer.tsx:29` (`enclosed_volume_m3` en el contrato).

**Por qué importa.** El volumen de una isosuperficie es una de las cifras que un usuario
copiará a un informe.

---

### Pregunta 6 — Marching cubes sobre un campo regularizado

**Pregunta.** Se extrae una isosuperficie de un campo que ya es suave por construcción (el
operador de regularización es un Laplaciano) y después se suaviza otra vez con Taubin. El
resultado tiene aspecto de contacto geológico nítido. Desde la geometría computacional:
¿qué representación alternativa comunicaría mejor que el nivel elegido es arbitrario —por
ejemplo, varias isosuperficies anidadas semitransparentes, o una banda de nivel en lugar de
una superficie?

**Evidencia.** `services/isosurface_service.py:329-395` (varios niveles ya soportados);
`lib/render/IsosurfaceMeshLayer.tsx:113-114` (se ordenan por fracción y se dibuja el núcleo
primero).

**Qué sabemos.** Que la infraestructura de múltiples niveles ya existe y se usa: la opacidad
depende de la fracción (`opacityForFraction`).

---

*Fin del informe 09. El informe 10 trata las decisiones de color, visibilidad y
transparencia que afectan a lo que el usuario percibe; el 05, el significado geológico de
las superficies; el 11, los formatos y el orden de ejes en la persistencia.*
