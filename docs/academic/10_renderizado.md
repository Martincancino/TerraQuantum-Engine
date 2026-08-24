# INFORME 10 — VISUALIZACIÓN Y RENDERIZADO
## Qué ve el usuario, y en qué se diferencia de lo que el solver calculó

**Destinatario:** visualización científica · gráficos por computador · percepción visual
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `terraquantum-web/lib/terraQuantumGeology.ts` (650 líneas), `componentes/Scene3D.tsx`, `lib/render/VolumeRaymarchLayer.tsx`, `lib/render/IsosurfaceMeshLayer.tsx`, `lib/render/gpuCapabilities.ts`.

> Autocontenido.
>
> La pregunta que organiza este informe no es «¿se ve bien?» sino **«¿lo que se ve
> corresponde a lo que se calculó?»**. En un sistema científico esa es la pregunta
> relevante, y la respuesta aquí es: **en parte sí, y en un aspecto importante,
> no de forma evidente para el usuario**.

---

## 1. La pila de renderizado

| Componente | Tecnología |
|---|---|
| Motor | Three.js vía React-Three-Fiber |
| Modo principal | `InstancedMesh` — una caja por vóxel, una sola llamada de dibujo |
| Modo alternativo | *ray-marching* volumétrico sobre textura 3D (`VolumeRaymarchLayer`) |
| Superficies | mallas de marching cubes calculadas en el backend (`IsosurfaceMeshLayer`) |
| Capas auxiliares | sondajes, velo DOI, sección pintada, vectores de magnetización, envolvente |
| Backend gráfico | WebGL2, con sonda de capacidad para WebGPU |

El renderizado por instancias es la elección correcta para decenas de miles de vóxeles: el
coste por celda es una matriz $4\times4$ y un color, no una llamada de dibujo.

Hay una **sonda de capacidades GPU** (`lib/render/gpuCapabilities.ts`) que es pura
detección de características, sin React ni Three.js, segura en SSR, y que responde
—en sus propias palabras— «UNA pregunta honestamente: qué puede hacer realmente el
navegador del usuario». Devuelve `webgpu`, `webgl2` o `none`, y en el último caso la
recomendación es **no intentar renderizar en 3D** en lugar de degradar a algo que engañe.

*(Discrepancia menor: el docstring de `VolumeRaymarchLayer` dice «when wired into Scene3D,
a later slice», pero la capa ya está montada en `componentes/Scene3D.tsx:1144`.)*

---

## 2. El mapa de color: una decisión bien tomada

### 2.1 Qué se usa

**Viridis** de matplotlib, definido por nueve paradas de interpolación
(`lib/terraQuantumGeology.ts:208-218`), muestreado por interpolación lineal por tramos
(`lib/terraQuantumGeology.ts:220-232`).

### 2.2 Por qué importa, y por qué el código acierta

El comentario que acompaña la definición es correcto y merece citarse
(`lib/terraQuantumGeology.ts:203-207`):

> «Mapa SECUENCIAL PERCEPTUALMENTE UNIFORME: luminancia monótona, legible para daltónicos
> y sin los saltos cromáticos del arcoíris (que **exageraban gradientes inexistentes**).
> […] Reemplaza al espectral Geosoft (azul→…→magenta/rosa), no perceptual.»

Esto es exactamente el argumento estándar contra el mapa arcoíris en visualización
científica: en un arcoíris, la luminancia no es monótona, de modo que aparecen **bordes
percibidos** donde el dato varía suavemente (típicamente en la transición al cian y al
amarillo), y el ojo interpreta esos bordes como estructura. Cambiar a Viridis elimina una
fuente real de artefactos interpretativos.

Que el proyecto haya migrado desde el espectral tipo Geosoft —el estándar *de facto* en
geofísica— **en contra de la costumbre de la industria y a favor de la percepción** es una
decisión defendible y bien razonada.

### 2.3 Consistencia entre capas

`sampleDensityViridis` se **exporta** explícitamente para que las isosuperficies coloreen
con exactamente el mismo mapa que los vóxeles
(`lib/terraQuantumGeology.ts:234-243`), y la capa de superficies lo importa y lo usa
(`lib/render/IsosurfaceMeshLayer.tsx:21`, `129-135`). El comentario del contrato es
explícito: «El frontend NO calcula física: el color por vértice usa el contraste con signo
que envía el backend» (`lib/render/IsosurfaceMeshLayer.tsx:15-17`).

Ésa es la disciplina correcta: un solo mapa, definido una vez, compartido.

---

## 3. ⚠ El problema central: la escala de color es relativa a cada corrida

Aquí está la decisión con mayor impacto sobre la honestidad de la visualización.

### 3.1 Qué se calcula

El fondo y la escala del mapa divergente **no son constantes**: se derivan de la
distribución de densidades de la propia corrida
(`lib/terraQuantumGeology.ts:450-462`):

```js
densBackground = pick(0.50);                     // mediana de la corrida
const spreadHi  = pick(0.95) - densBackground;
const spreadLo  = densBackground - pick(0.05);
densScale = Math.max(spreadHi, spreadLo, 0.05);  // piso 0.05
```

y el contraste que se colorea es

$$
u = 0.5 + 0.5\cdot\frac{\rho - \text{mediana}}{\text{escala robusta}}
$$

### 3.2 Por qué está bien hecho como técnica

Como técnica de escalado robusto, es correcta:

- **la mediana** como ancla del blanco del mapa divergente es robusta a colas;
- **percentiles 5–95** en vez de mín–máx evita que un único vóxel de borde saturado fije
  la escala — y el comentario declara exactamente ese motivo: «ignorando los pocos vóxeles
  de borde saturados a 0»;
- el **piso de 0,05** evita la división por una escala degenerada en un modelo casi plano;
- el mapa es **divergente y simétrico**, de modo que un déficit de masa (anomalía negativa)
  es tan visible como un exceso. El comentario lo justifica bien: «Un déficit de masa […]
  es un objetivo tan real como un exceso; los scores positivos lo ocultaban → "no hay
  azul"» (`lib/terraQuantumGeology.ts:526-529`).

### 3.3 Por qué es un problema científico

El problema no es la técnica: es que **la escala se reajusta a cada corrida y el usuario
no lo sabe**.

Consecuencias concretas:

1. **El mismo color significa cosas distintas en dos modelos.** Un amarillo brillante en
   un modelo con una anomalía de 0,05 t/m³ y un amarillo brillante en uno con 0,8 t/m³ se
   ven idénticos. Ambos son "el máximo de esta corrida".

2. **Un modelo sin anomalía real se ve igual que uno con anomalía fuerte.** Si el subsuelo
   es homogéneo y sólo hay ruido de inversión, la mediana sigue siendo el fondo y el
   percentil 95 sigue estando por encima: el ruido se colorea con el rango completo. El
   piso de 0,05 t/m³ acota el efecto, pero 0,05 t/m³ es un contraste pequeño que aun así
   ocupará todo el rango cromático.

3. **No se puede comparar visualmente dos modelos.** Ni dos escenarios de la misma zona,
   ni el mismo dato con dos configuraciones — que es exactamente lo que un usuario hace
   para decidir.

No se encontró en el código ninguna leyenda que publique los valores numéricos
correspondientes a los extremos del mapa dentro del propio visor 3D: **NO DETERMINADO** si
existe en otro componente de la interfaz no auditado.

---

## 4. La cascada de visibilidad: qué se oculta y por qué

Ésta es la segunda decisión de peso. `updateInstancedBuffers` no dibuja todas las celdas:
las hace pasar por una secuencia de filtros, y cada celda que falla uno se colapsa a escala
cero (`lib/terraQuantumGeology.ts:476-636`).

En orden de aplicación:

| # | Filtro | Criterio | Línea |
|---|---|---|---|
| 1 | celda inactiva | `is_active === false` o densidad `null` | 490 |
| 2 | umbral DOI | `doi_index < doiThreshold` | 511-518 |
| 3 | corte de sección | posición en el eje > posición del corte | 518 |
| 4 | **piso de anomalía** | contraste < umbral **y** scores bajos | 533 |
| 5 | rango de densidad | fuera de `[minDensityRaw, maxDensityRaw]` | 534 |
| 6 | modo profesional | configuración por score visual | 536-565 |

El filtro 4 es el más consecuente.

### 4.1 El piso de visibilidad es relativo al pico

```js
const _effContrastFloor = weakAnomaly
  ? ANOMALY_CONTRAST_VISIBLE                                  // 0.18
  : Math.max(ANOMALY_CONTRAST_VISIBLE, ANOMALY_PEAK_FRACTION * _maxContrastMag);
```
(`lib/terraQuantumGeology.ts:470-474`, con `ANOMALY_CONTRAST_VISIBLE = 0.18`,
`ANOMALY_PEAK_FRACTION = 0.20`, `ANOMALY_WEAK_PEAK = 0.60`,
`lib/terraQuantumGeology.ts:148-158`)

Es decir: **se ocultan las celdas cuyo contraste normalizado esté por debajo del 20 % del
pico de esa corrida** (con un piso absoluto del 18 % de la escala robusta).

El propósito declarado es legítimo: «Piso de visibilidad relativo al PICO de anomalía
(muestra el núcleo)» (`lib/terraQuantumGeology.ts:466`). Sin él, el modelo se ve como una
caja sólida de fondo y no se distingue nada. El comentario acompañante en la sección de
color explica el mismo razonamiento desde el otro lado: recortar al percentil 98 «satura
toda la anomalía a un rojo plano» (`lib/terraQuantumGeology.ts:440-445`).

**Pero la consecuencia es la misma que en §3:** lo que el usuario ve es siempre «el núcleo
de la anomalía más fuerte de esta corrida», independientemente de si esa anomalía es
significativa. Un modelo esencialmente vacío mostrará igualmente un cuerpo compacto: el
20 % superior de su propio ruido.

Hay una mitigación parcial: la bandera `weakAnomaly` detecta cuando el pico de contraste es
menor que 0,60 y entonces **no** escala el piso con el pico, dejándolo en el valor absoluto
0,18 (`lib/terraQuantumGeology.ts:471-474`). Es decir, el sistema **sí** distingue el caso
de anomalía débil. Lo que no se encontró es que esa bandera se **comunique al usuario**:
**NO DETERMINADO** si algún componente de la interfaz la muestra.

### 4.2 Un caso donde el sistema acierta: el DOI atenúa, no oculta

El tratamiento de la sensibilidad merece elogio explícito.

```js
const DOI_THRESHOLD = 0.05;
// El gate DOI NO oculta el vóxel: el modelo de densidad se calcula
// (regularizado) en TODA la malla; baja sensibilidad = menor confianza, y eso
// se comunica atenuando el brillo, no borrando.
// Ocultar aquí eliminaba ~2/3 de un modelo regional válido (causa de "no se
// ve nada" en surveys dispersos como Laguna del Maule).
```
(`lib/terraQuantumGeology.ts:499-508`)

y el brillo se modula continuamente
(`lib/terraQuantumGeology.ts:633`):

$$
\text{brillo} = 0{,}55 + 0{,}45\cdot\min\!\left(1,\ \frac{\text{sens}-0{,}05}{0{,}3-0{,}05}\right)
$$

**Ésta es la decisión de visualización correcta**, y el razonamiento es el adecuado: la baja
sensibilidad significa *menor confianza*, no *ausencia de material*. Borrar la celda
comunicaría lo segundo. Atenuarla comunica lo primero.

Y hay una distinción fina que el código maneja bien: un valor de sensibilidad `null`
significa «el backend no proveyó el dato», no «sensibilidad cero», y por tanto se trata
como visible (1,0) (`lib/terraQuantumGeology.ts:494-498`). Tratar el dato ausente como cero
ocultaba el modelo entero.

---

## 5. Física en el frontend: dónde se cruza la regla de oro

Las reglas del proyecto establecen que el frontend **no calcula física** y **no duplica
lógica del backend**. La auditoría encontró tres lugares donde eso no se cumple del todo.

### 5.1 Dos densidades de referencia codificadas a mano

```js
const DENSITY_COUNTRY_ROCK_FALLBACK_T_M3 = 2.75;   // línea 143
```
usada para calcular un score de anomalía de densidad
(`lib/terraQuantumGeology.ts:280`, `293`):

$$
\text{DAS} = \frac{\max(0,\ \rho - 2{,}75)}{2{,}75}
$$

Y por separado, en el cálculo del color:

```js
let densBackground = 2.6;    // línea 450, valor por defecto
```

Ambas son **copias de parámetros del backend**: `base_density` (por defecto 2,6,
`exploration/gravimetry.py:1270`) y `cutoff_density` (por defecto 2,75,
`services/geophysics_service.py:637`). Si el usuario cambia `base_density` a 2,75 en la
inversión, el frontend **no se entera**: seguirá calculando el contraste contra sus propias
constantes.

Además, `getVoxelModeledDensity` usa `2.6` como valor de respaldo cuando falta la densidad
(`lib/terraQuantumGeology.ts:274`), lo que significa que una celda sin dato se dibuja como
si tuviera densidad de fondo, en lugar de como celda sin dato.

*(Mitigación: la ruta de color prefiere la mediana empírica de la corrida sobre el 2,6
codificado, que sólo actúa como respaldo cuando hay menos de dos muestras.)*

### 5.2 Un score compuesto con pesos inventados en TypeScript

```js
function getExplorationSupportScore(cell, densityRatio) {
  const probability = clamp01(getVoxelTargetScore(cell));
  const visualScore = clamp01(getCellNumber(cell, ["visual_score"], densityRatio));
  const densityAnomalyScore = clamp01(getVoxelDensityAnomalyScore(cell));
  return Math.max(probability * 0.45, visualScore * 0.45, densityAnomalyScore * 0.10);
}
```
(`lib/terraQuantumGeology.ts:302-307`)

Los coeficientes 0,45 / 0,45 / 0,10 no aparecen justificados en ninguna parte, ni tienen
contraparte en el backend. Es un score de prospectividad —una magnitud interpretativa—
**construido en la capa de presentación**.

Nótese además que es un `Math.max` de tres términos ponderados, no una suma ponderada: la
estructura no corresponde a ninguna combinación convexa estándar, y el término de densidad
con peso 0,10 sólo puede ganar si los otros dos son muy bajos.

### 5.3 Una cadena de respaldos que mezcla magnitudes distintas

`getCellVisualScore` (`lib/terraQuantumGeology.ts:285-294`) prueba en orden:
`visual_score` → `relative_target_score` → `density_anomaly_score` → `probability` → y
finalmente un score calculado desde la densidad y la constante 2,75.

Son magnitudes **con significados diferentes** (una probabilidad, un score relativo, un
contraste normalizado) usadas de forma intercambiable para decidir color y visibilidad. Si
el backend deja de enviar el primer campo, el visor cambia de criterio sin avisar y el
usuario ve un modelo distinto sin haber cambiado nada.

**Contexto justo:** la cadena de respaldos existe por una razón real y documentada. El
comentario de `getCellNumber` (`lib/terraQuantumGeology.ts:257-263`) explica que
`Number(null) === 0` en JavaScript, de modo que un campo opcional emitido como `null` por
el `response_model` estricto se leía como 0 — «`target_score=null` se leía como 0
(ocultando todo) y `modeled_density_index=null` hacía densidad=0 en TODA la malla». La
corrección —aceptar sólo números finitos y pasar a la siguiente clave— es correcta. El
problema no es el mecanismo, es la **heterogeneidad semántica** de las claves encadenadas.

---

## 6. Transparencia, orden de dibujado y modo fantasma

El manejo de transparencia está razonado con más cuidado de lo habitual:

- **Las isosuperficies se ordenan por fracción descendente**, «Núcleo (fracción alta)
  primero para escribir profundidad antes del manto»
  (`lib/render/IsosurfaceMeshLayer.tsx:113-114`). Es la solución correcta al problema de
  orden en transparencia sin *depth peeling*.
- **`depthWrite` condicional**: sólo las superficies suficientemente opacas
  (`opacity ≥ 0.85`) escriben en el buffer de profundidad
  (`lib/render/IsosurfaceMeshLayer.tsx:165`). Correcto: una superficie translúcida que
  escribiera profundidad ocultaría lo que hay detrás.
- **`side: DoubleSide`** porque «mallas abiertas en el borde muestran interior»
  (`lib/render/IsosurfaceMeshLayer.tsx:163`). Necesario cuando la isosuperficie se corta
  contra el borde del dominio.
- **Modo fantasma**: cuando las isosuperficies están activas, los vóxeles se dibujan tenues
  como «nube fantasma de contexto» detrás de la cáscara
  (`componentes/Scene3D.tsx:1960-1966`).

Ese último punto tiene una dependencia crítica: el modo fantasma sólo comunica lo que
pretende —«la superficie es el núcleo denso de la nube»— **si ambas capas se superponen
exactamente**. El informe 09 §4 documenta indicios de que no lo hacen.

---

## 7. La liberación de recursos y el rendimiento

Dos detalles que indican cuidado de ingeniería:

- **Singletons de módulo** para `THREE.Object3D` y `THREE.Color` reutilizados en cada
  actualización, «para evitar que el GC acumule decenas de miles de Color/Object3D por
  actualización», con la advertencia «NUNCA retener referencias externas a estos objetos
  entre llamadas» (`lib/terraQuantumGeology.ts:3-9`).
- **Liberación explícita de geometrías** al desmontar o cambiar datos, para no filtrar VRAM
  (`lib/render/IsosurfaceMeshLayer.tsx:145-150`), y separación de memos: la geometría
  (trabajo pesado) sólo se recalcula al cambiar los datos, mientras que los materiales
  (baratos) se rehacen al cambiar cortes u opacidad
  (`lib/render/IsosurfaceMeshLayer.tsx:109-111`, `155-157`).

---

## 8. Los tres niveles, aplicados a la visualización

**Lo que el código hace.** Normaliza la densidad de cada celda contra la mediana y la
dispersión robusta **de esa corrida**, la colorea con Viridis divergente, oculta las celdas
por debajo del 20 % del pico de contraste de esa corrida, atenúa el brillo según la
sensibilidad, y dibuja el resultado como cajas instanciadas.

**Lo que gráficamente significa.** Una representación de **contraste relativo dentro de la
corrida**, con un recorte del rango inferior. No es un mapa absoluto de densidad.

**Lo que el usuario percibe, y aquí está el riesgo.** Un cuerpo compacto, brillante, de
forma definida, sobre un fondo vacío. Esa imagen es **la misma** para una anomalía fuerte y
bien resuelta y para el 20 % superior del ruido de un modelo sin señal. La diferencia
existe en los diagnósticos numéricos del sistema —que son buenos y honestos (informe 12)—
pero **no en la imagen**.

Ésta es la brecha central: TerraQuantum tiene un marco de honestidad numérica cuidadoso, y
una capa de visualización que puede contradecirlo visualmente sin decir nada falso.

---

## 9. Resumen técnico

### Correctamente implementado

- Viridis perceptualmente uniforme, sustituyendo un arcoíris, con la justificación correcta.
- Mapa de color exportado y compartido entre vóxeles e isosuperficies.
- Escalado robusto por mediana y percentiles 5–95, con piso.
- Mapa divergente simétrico: los déficits de masa son tan visibles como los excesos.
- **El DOI atenúa el brillo en lugar de ocultar**, con la razón correcta y medida.
- Distinción entre dato ausente (`null`) y valor cero, tras un fallo documentado.
- Orden de dibujado por opacidad y `depthWrite` condicional.
- Sonda de capacidades GPU que recomienda **no renderizar** en lugar de degradar
  engañosamente.
- Gestión explícita de memoria de GPU y de objetos temporales.

### Problemas detectados

1. **La escala de color es relativa a cada corrida** y no se comunica: el mismo color
   significa cosas distintas en modelos distintos, y dos modelos no son comparables
   visualmente (§3.3).
2. **El piso de visibilidad es relativo al pico de la corrida** (20 %): siempre se ve «un
   cuerpo», haya o no anomalía significativa (§4.1). Existe la bandera `weakAnomaly` pero
   no se localizó que se comunique (**NO DETERMINADO**).
3. **Física e interpretación en el frontend**: dos densidades de referencia codificadas a
   mano que duplican parámetros del backend, y un score compuesto con pesos 0,45/0,45/0,10
   sin justificación (§5).
4. **Cadena de respaldos semánticamente heterogénea** para decidir color y visibilidad
   (§5.3).
5. **El modo fantasma depende de una superposición** que el informe 09 §4 pone en duda.

---

## 10. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Escala relativa frente a escala absoluta (prioritaria)

**Pregunta.** El visor normaliza el color contra la mediana y la dispersión robusta de cada
corrida. Es un escalado robusto correcto, pero implica que el mismo color codifica
contrastes distintos en modelos distintos y que dos resultados no son comparables a simple
vista. ¿Qué recomendaría usted: (a) escala absoluta fija en t/m³, (b) mantener la
adaptativa pero con una **leyenda numérica obligatoria** en el visor, (c) ofrecer ambas con
la absoluta por defecto, o (d) una escala "anclada" que se fije en la primera corrida de
una sesión y no cambie al comparar?

**Por qué surge.** Es la decisión con mayor impacto sobre lo que el usuario concluye.

**Evidencia.** `lib/terraQuantumGeology.ts:450-462` (el cálculo);
`lib/terraQuantumGeology.ts:440-445` (la justificación de no recortar a P98).

**Qué sabemos.** Que la técnica de escalado robusto es correcta y que el recorte a P98
tenía un problema real (saturaba la anomalía a un color plano).

**Qué NO sabemos.** Si existe una leyenda numérica en algún componente de la interfaz que
no auditamos. **NO DETERMINADO.**

---

### Pregunta 2 — Un piso de visibilidad relativo al pico

**Pregunta.** Se ocultan las celdas por debajo del 20 % del contraste máximo de la corrida
(con piso absoluto 0,18 de la escala robusta). El efecto es que **siempre** se ve un cuerpo
compacto: en un modelo sin señal, el 20 % superior del ruido. ¿Considera aceptable este
compromiso —sin él la escena es una caja sólida— o recomendaría un umbral con significado
físico, por ejemplo ligado a la σ posterior del vóxel (mostrar sólo lo que supera $k\sigma$)?

**Evidencia.** `lib/terraQuantumGeology.ts:466-474`;
constantes en `lib/terraQuantumGeology.ts:148-158`.

**Qué sabemos.** Que el sistema **ya calcula** una σ posterior por vóxel (estimador de
Hutchinson) y la transporta al frontend, de modo que un umbral estadístico sería viable sin
cómputo adicional.

**Qué opinión sería útil.** Si un umbral del tipo «mostrar sólo celdas con
$|\rho-\rho_{fondo}| > 2\sigma_{posterior}$» es defendible en visualización geofísica, sería
un cambio de alto valor y bajo coste.

---

### Pregunta 3 — La bandera de anomalía débil, calculada y no comunicada

**Pregunta.** El código detecta `weakAnomaly` cuando el contraste máximo de la corrida es
inferior a 0,60 y ajusta su comportamiento, pero no encontramos que ese hecho se muestre al
usuario. ¿Debería el visor **declarar en pantalla** «esta corrida no tiene una anomalía
destacada; lo que ve es el rango superior del fondo»? ¿Y con qué criterio numérico fijaría
ese aviso?

**Evidencia.** `lib/terraQuantumGeology.ts:471-474` (`ANOMALY_WEAK_PEAK = 0.60`).

---

### Pregunta 4 — Constantes físicas duplicadas en la capa de presentación

**Pregunta.** El frontend codifica 2,75 t/m³ como densidad de roca de caja y 2,6 t/m³ como
respaldo de fondo, duplicando `cutoff_density` y `base_density` del backend. Si el usuario
cambia `base_density` en la inversión, el visor no se entera. Desde la arquitectura de
software científico: ¿basta con que el backend envíe esos valores en el contrato de
respuesta y el frontend los consuma, o hay un argumento para tener respaldos locales?

**Evidencia.** `lib/terraQuantumGeology.ts:143`, `274`, `280`, `293`, `450`;
`exploration/gravimetry.py:1270`; `services/geophysics_service.py:637`.

**Nota.** El sistema **ya** genera automáticamente los tipos TypeScript desde los esquemas
Pydantic, de modo que la infraestructura para transportar estos valores existe.

---

### Pregunta 5 — Un score compuesto en la capa de presentación

**Pregunta.** `getExplorationSupportScore` combina probabilidad, score visual y score de
anomalía de densidad como `max(0.45·p, 0.45·v, 0.10·d)`. Los pesos no están justificados y
el score es una magnitud interpretativa calculada en el cliente. ¿Recomendaría moverlo al
backend —donde puede documentarse, versionarse y validarse— aunque sea sólo aritmética?
¿Y le parece defendible un `max` de términos ponderados frente a una suma ponderada?

**Evidencia.** `lib/terraQuantumGeology.ts:302-307`.

---

### Pregunta 6 — Respaldos entre magnitudes de significado distinto

**Pregunta.** Para decidir color y visibilidad, el visor prueba `visual_score` →
`relative_target_score` → `density_anomaly_score` → `probability` → un score derivado de la
densidad. Son magnitudes con semánticas diferentes usadas de forma intercambiable, de modo
que la ausencia de un campo cambia el criterio sin aviso. ¿Recomendaría eliminar la cadena
y **fallar visiblemente** cuando falta el campo esperado?

**Evidencia.** `lib/terraQuantumGeology.ts:285-294`;
`lib/terraQuantumGeology.ts:257-263` (la razón por la que la cadena existe).

---

### Pregunta 7 — Viridis frente al espectral de la industria

**Pregunta.** El proyecto migró del espectral tipo Geosoft a Viridis por uniformidad
perceptual, en contra de la convención de la industria geofísica. ¿Le parece la decisión
correcta, o el coste de que un geofísico no reconozca su paleta habitual supera el
beneficio perceptual? ¿Ofrecería el espectral como opción explícitamente marcada como «no
perceptual»?

**Evidencia.** `lib/terraQuantumGeology.ts:203-207`.

---

### Pregunta 8 — Lo que la imagen no distingue

**Pregunta.** Ésta es la pregunta de fondo del informe. El sistema tiene un marco de
honestidad numérica cuidadoso: veredicto por eslabón más débil, confianza en profundidad en
LOW por defecto, artefactos de espacio nulo degradados y publicados. Pero la **imagen** de
una anomalía fuerte y la de un modelo sin señal son visualmente muy parecidas, porque tanto
la escala de color como el umbral de visibilidad son relativos a la propia corrida.
¿Qué recursos visuales recomendaría para que la imagen comunique la confianza —opacidad
global ligada al veredicto, un marco o velo de color, una marca de agua, mostrar el modelo
en escala de grises cuando el veredicto es LOW?

**Por qué surge.** Es la brecha entre la honestidad de los números y la persuasión de la
imagen. Un usuario mira la imagen.

---

*Fin del informe 10. El informe 09 trata las transformaciones geométricas y una
inconsistencia detectada entre capas; el 12, los diagnósticos numéricos de confianza que
esta capa debería comunicar; el 05, qué significa geológicamente una isosuperficie.*
