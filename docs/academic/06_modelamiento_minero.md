# INFORME 06 — MODELAMIENTO MINERO
## Qué hace TerraQuantum del lado minero, y sobre todo qué no hace

**Destinatario:** ingeniería de minas · evaluación de yacimientos · cumplimiento JORC / NI 43-101
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `services/block_model_service.py`, `services/block_model_store.py`, `exploration/gravimetry.py` (`TargetingEngine`, `rank_drill_targets`), `reporting/report_generator.py`, `api/chat_api.py`, y búsqueda exhaustiva de términos económicos en todo el repositorio.

> Autocontenido. Este informe es deliberadamente conservador: su trabajo principal
> es impedir que un lector atribuya a TerraQuantum capacidades de evaluación de
> recursos que **no tiene**.

---

## 1. La conclusión, antes que nada

**TerraQuantum no es un sistema de evaluación de recursos ni de planificación minera.**

No estima recursos ni reservas. No optimiza pit. No hace *scheduling*. No estima leyes por
kriging ni por ningún otro método geoestadístico. No calcula VAN ni vida de mina.

Lo que sí hace es producir **un ranking de blancos de perforación** a partir de una
inversión geofísica, con una cuantificación estadística de la probabilidad de que cada
blanco supere un umbral de contraste de densidad.

Esta delimitación no es una interpretación de la auditoría: **está declarada en el código
en al menos cinco lugares distintos**, y el sistema toma medidas activas para impedir que
se cruce. Es, de hecho, el aspecto mejor resuelto de esta parte del sistema.

---

## 2. Qué se eliminó deliberadamente

La primera evidencia está en una sola línea:

```python
# Mode "economic" eliminado (2026-06-10): sin módulos de economía minera.
SUPPORTED_BLOCK_MODEL_MODES = {"exploration", "full", "anomaly", "doi_reliable", "profile"}
```
(`services/block_model_service.py:13-14`)

Y en el punto de entrada de la aplicación:

```python
# plataforma de exploración geofísica — solo modelo 3D, sin NPV/LOM.
```
(`main.py:67`)

Búsqueda exhaustiva en todo el repositorio de `lerchs`, `pseudoflow`, `floating_cone`,
`pit_optim`, `scheduling`: **cero coincidencias**. No hay optimización de pit de ningún
tipo, ni algoritmo de secuenciamiento.

---

## 3. El "block model" no es un block model minero

El nombre invita a confusión, así que conviene ser preciso.

En la industria, un *block model* es un modelo de bloques con leyes estimadas por celda
(típicamente por kriging o inverse distance), densidades, dominios geológicos, categorías
de recurso (medido / indicado / inferido) y atributos metalúrgicos. Es el insumo de la
evaluación económica.

En TerraQuantum, `block_model_service.py` es un **servicio de vista y exportación de
vóxeles**. Sus responsabilidades reales, leídas del código:

- normalizar el modo de vista (`exploration`, `full`, `anomaly`, `doi_reliable`, `profile`)
  (`services/block_model_service.py:49`);
- calcular estadísticas de distribución y percentiles
  (`services/block_model_service.py:239`) — p2, p5, p50, p85, p90, p95, p98;
- construir respuestas en Arrow con compresión (`services/block_model_service.py:1051`);
- generar niveles de detalle por octree y submuestreo
  (`services/block_model_service.py:962-1007`);
- exportar a Zarr (`services/block_model_service.py:803`);
- construir perfiles A–A' (`services/block_model_service.py:1250`).

Los atributos que transporta son **densidad, contraste de densidad, índice DOI y scores de
visualización**. No hay ley, no hay tonelaje de mena, no hay dominio geológico, no hay
categoría de recurso.

Hay incluso un umbral de advertencia de rendimiento a 200.000 vóxeles
(`services/block_model_service.py:15`), lo que confirma que el objeto es una malla de
visualización y no un modelo de bloques de evaluación.

---

## 4. La "ley": un proxy declarado como tal

Éste es el punto donde un sistema deshonesto haría daño, y donde TerraQuantum se comporta
correctamente.

### 4.1 El campo existe, pero viene marcado

```python
_GRADE_PROVENANCE = {
    "grade_source": "heuristic_gravity_proxy",
    "assay_supported": False,
    "economically_validated": False,
}
```
(`services/geophysics_service.py:614-618`)

Este diccionario se adjunta a **cada** objeto que reporta una ley
(`services/geophysics_service.py:671`, `830`, `1638`, `1710`), y cada blanco lleva además
`"is_demo_grade": True` (`services/geophysics_service.py:830`).

La función que construye la salida de vóxeles emite además una advertencia en el log:

```python
_log.warning("[WARNING] Grade heuristic used for exploration preview")
```
(`services/geophysics_service.py:622`)

### 4.2 Qué es realmente ese número

El campo primario se llama `density_proxy_index`, no `grade`
(`services/geophysics_service.py:632`), y el "score de anomalía de densidad" se calcula
como una simple normalización lineal por encima de un umbral:

$$
\text{DAS} = \min\!\left(1,\ \max\!\left(0,\ \frac{\rho - \rho_{cutoff}}{\rho_{cutoff}}\right)\right)
$$

(`services/geophysics_service.py:637`, con `cutoff_density = 2.75` por defecto).

Es decir: **una función monótona de la densidad invertida**. No contiene ninguna
información sobre concentración de metal, mineralogía, ni recuperación metalúrgica.
Llamarlo "ley" sería incorrecto, y el código no lo llama así en sus campos estructurados.

### 4.3 El contraste con la práctica habitual

Merece señalarse porque es infrecuente: la mayoría de las herramientas que presentan un
"índice de prospectividad" no marcan su procedencia en el dato estructurado. Aquí, un
consumidor programático **no puede** leer el número sin leer también
`assay_supported: false`. Ésa es la forma correcta de manejar un proxy.

---

## 5. El "tonelaje": masa de roca, no de mena

`TargetingEngine.extract_and_export` (`exploration/gravimetry.py:4158`) calcula:

```python
block_volume = min(block_size ** 3, MAX_BLOCK_VOLUME_M3)   # tope 1e6 m³
tonnage = block_volume * density
```
(`exploration/gravimetry.py:4211-4214`)

Es volumen × densidad: **la masa de roca de la celda**. No es tonelaje de mena, porque no
hay ley con la que discriminar mena de estéril.

El propio código lo reconoce y renombra las columnas al exportar
(`exploration/gravimetry.py:4232-4237`):

| Variable interna | Columna exportada | Motivo declarado |
|---|---|---|
| `tonnage` | `bulk_rock_mass_kg` | «nombres de columna no-mineros/compliance-safe» |
| `probability` | `relative_target_score` | ídem |
| `targeting_score` | `exploration_index` | ídem |

El renombrado es la decisión correcta: `tonnage` en un Parquet invita a leerlo como
tonelaje de recurso.

### 5.1 Dos problemas detectados en esa exportación

Ambos son de severidad moderada porque no se localizó ningún consumidor de estas columnas
—ni en el backend, ni en el frontend, ni en los scripts de validación— pero el archivo
**sí se escribe** en producción (`services/geophysics_service.py:4449`, con el comentario
«Se sigue ejecutando TargetingEngine por compatibilidad industrial»).

**(a) La unidad del nombre no coincide con la unidad del valor.**
`density` está en t/m³ y `block_volume` en m³, de modo que su producto está en **toneladas**.
La columna se llama `bulk_rock_mass_kg`. Hay un factor **1.000** entre el nombre y el
contenido. Quien abra ese Parquet confiando en el sufijo leerá masas mil veces menores de
lo que son.

**(b) El contraste se calcula contra una constante literal, no contra la densidad de
fondo real.**

```python
density_contrast = density - 2.6
```
(`exploration/gravimetry.py:4213`)

`2.6` está escrito a mano. Pero `base_density` es un parámetro configurable de la
inversión (`exploration/gravimetry.py:1270`), y la ruta principal sí lo usa correctamente:
`density_raw = self.base_density + density_contrast_active`
(`exploration/gravimetry.py:2912`). Si un usuario declara `base_density = 2.75`, esta
columna de exportación queda desfasada en 0,15 t/m³ — un sesgo del mismo orden que muchos
contrastes de interés.

*(Nota: la columna que sí consume el frontend se llama `density_contrast_t_m3` y proviene
de la ruta correcta, `exploration/gravimetry.py:2893`. Son dos columnas distintas con
nombres parecidos, lo cual es en sí mismo un riesgo.)*

---

#### Cierre — Fase 22 (2026-08-27), y en qué se quedó corta esta sección

Los dos problemas están corregidos. El código citado arriba se conserva tal como estaba
cuando se detectó: es la evidencia, no el estado actual. Lo que la fase midió y esta
sección no había visto:

**(a) El factor no era 1.000, sino 1.000 · dx³/1.000.** La sección leyó
`block_volume = min(block_size**3, MAX_BLOCK_VOLUME_M3)` y no comprobó **con qué
`block_size` se llama en producción**: la llamada de `geophysics_service.py` no pasa ese
argumento, así que la firma cae en su default de 10 m y el volumen queda clavado en
1.000 m³ *cualquiera sea la malla*. Medido sobre `data/projects`: **1.034 de 2.089**
corridas usan un dx distinto de 10, y el `MAX_BLOCK_VOLUME_M3` recortaba en silencio toda
celda de más de 100 m. Corregir sólo el sufijo `_kg` habría cerrado un factor 1.000 y
dejado vivo uno de hasta 10⁹. La Fase 22 pasa el dx real, los índices reales de la malla,
y retira el tope.

**(b) El literal `2.6` estaba en TRES escritores, no en uno.** Además del que esta
sección cita, el `Density_Contrast_gcm3` del `.vtr` (`export_service.VTK_BASE_DENSITY`) y
el `Density_Contrast` del ASEG-GDF2, cuyo `.dfn` **declaraba por escrito** «Density minus
2.6 g/cm3 base». Los dos últimos viajan al cliente dentro del ZIP industrial, y el
ASEG-GDF2 es formato de **entrega regulatoria** en Australia y Nueva Zelanda: declarar una
base que no es la usada hace el fichero incorrecto por contrato, no sólo por número.

**(c) La pregunta de la §Pregunta 8 quedó respondida por medición, no por opinión.** No
hay ningún consumidor de la columna —grep sobre backend, frontend, scripts de validación,
notebooks y docs— y el propio repositorio ya había resuelto este mismo defecto en la ruta
canónica **renombrando** (`d424c7c`: `modeled_rock_mass_kg` → `modeled_rock_mass_tonnes`).
Se siguió ese precedente: `bulk_rock_mass_tonnes`, con la misma palabra, para que las dos
columnas de masa del producto puedan compararse — y un test exige que den el mismo número.

---

## 6. Lo que sí es sólido: el ranking probabilístico de blancos

`rank_drill_targets` (`exploration/gravimetry.py:519`) es, a juicio de esta auditoría, la
contribución minera real del sistema, y está bien construida.

### 6.1 La formulación

Para cada vóxel $j$, asumiendo el posterior lineal-gaussiano $m_j\sim N(\hat m_j,\sigma_j^2)$,
con $\text{diff}=\pm(\hat m_j-\tau)$ según el sentido buscado y $d=\text{diff}/\sigma_j$:

| Métrica | Fórmula | Interpretación |
|---|---|---|
| `exceedance_prob` | $\Phi(d)$ | probabilidad de superar el umbral |
| `expected_exceedance` | $\sigma_j\phi(d)+\text{diff}\cdot\Phi(d)$ | $\mathbb E[\max(\pm(m-\tau),0)]$ |
| `lower_confidence_bound` | $\text{diff}-k\sigma_j$ | score pesimista |

(`exploration/gravimetry.py:534-548`)

`expected_exceedance` es la forma cerrada del **expected improvement** de la optimización
bayesiana: premia simultáneamente magnitud y potencial exploratorio. Es una elección
acertada para targeting, donde interesa tanto la anomalía fuerte y bien resuelta como la
anomalía moderada con incertidumbre alta que podría ser mayor.

`lower_confidence_bound` es su complemento conservador: **penaliza la incertidumbre**, de
modo que «un pico fuerte pero mal resuelto cae» (`exploration/gravimetry.py:546-547`).

### 6.2 Supresión de no-máximos en 3D

Los candidatos con $\Phi(d)\ge$ `min_exceedance_prob` se ordenan por el score elegido y se
seleccionan codiciosamente, excluyendo todo candidato a menos de `exclusion_radius` de un
blanco ya elegido (`exploration/gravimetry.py:552-557`).

El objetivo, declarado: obtener blancos **espacialmente distintos**, «no 50 celdas del
mismo cuerpo». Es exactamente el problema práctico que tiene un ranking ingenuo por valor
de celda.

### 6.3 El alcance declarado

El docstring incluye una sección titulada «ALCANCE HONESTO»
(`exploration/gravimetry.py:559-565`):

> «las probabilidades son del posterior LINEAL alrededor de la solución regularizada […]
> NO capturan no-unicidad no-lineal ni error de modelo. Es un ranking DEFENDIBLE de
> TARGETING/ESTRUCTURA ("dónde perforar"), **NO una probabilidad de mena/ley**.»

Y una degradación declarada: si no se pasa la σ posterior real, se estima una σ
homoscedástica del MAD del modelo, marcada como «degradado; pasar la σ real es muy
preferible».

Esta distinción —probabilidad de **contraste de densidad** frente a probabilidad de
**mena**— es la más importante de todo el informe, y el código la sostiene.

### 6.4 El ranking pondera por resolubilidad

En la selección del mejor blanco, el score no es la anomalía sino
$\text{sens}\times\text{anomalía}$ (`services/geophysics_service.py:750`), donde `sens` es
el proxy de sensibilidad del kernel. El razonamiento está escrito
(`services/geophysics_service.py:745-749`): recomendar perforar donde el dato **muestra**
anomalía **y** la **constriñe**, de modo que el artefacto profundo de espacio nulo (masa
apilada en el piso de la malla, sensibilidad ≈ 0) queda por debajo del cuerpo somero
respaldado por el dato, aunque su anomalía absoluta sea mayor.

Y cuando un artefacto es descartado, **se publica** en un campo `demoted` con su razón
textual explícita: «no es un blanco de perforación»
(`services/geophysics_service.py:764-773`). El comentario lo llama «transparencia, no
silencio».

---

## 7. El reporte: etiquetas honestas sobre casillas vacías

`reporting/report_generator.py` genera un informe HTML imprimible.

### 7.1 El descargo es completo y correcto

El encabezado del módulo (`reporting/report_generator.py:28-58`) cita los marcos
regulatorios pertinentes —**NI 43-101** (Canadá), **JORC 2012** (Australasia), **SAMREC**
(Sudáfrica), **SEC S-K 1300** (EE. UU.)— y enumera las limitaciones:

- «"Ley estimada" (grade): PROXY HEURÍSTICO […] NO es ley medida por análisis geoquímico
  certificado.»
- «Tonelaje: ESTIMADO CALCULADO, no muestreado ni estimado por kriging/IK.»
- «NPV y LOM: CONCEPTUALES […] NO constituyen evaluación bancable.»
- «TerraQuantum es un sistema de EXPLORACIÓN EXPERIMENTAL/CONCEPTUAL.»

Y declara qué **no** reemplaza: PEA/PFS/FS, análisis geotécnico o hidrogeológico,
evaluación por Persona Competente, debida diligencia.

Esto es correcto y completo.

### 7.2 Pero las métricas económicas no existen

El reporte renderiza siete tarjetas económicas
(`reporting/report_generator.py:728-735`):

`npv` · `tonnage` · `avg_grade` · `strip_ratio` · `lom_years` · `cutoff_grade` ·
`ore_tonnage` · `waste_tonnage`

Búsqueda exhaustiva en **todo el repositorio** (backend y frontend) de un productor de
`npv`, `ore_tonnage`, `cutoff_grade` o `waste_tonnage`: **no existe ninguno**. Los únicos
lugares donde aparecen son el propio reporte (que los **lee**) y
`services/block_model_store.py:459-465` (que calcula un *delta* entre dos corridas, es
decir, también los lee).

**Consecuencia.** Como `_number` y `_money` devuelven la cadena `"No disponible"` ante
`None` (`reporting/report_generator.py:999-1014`), esas tarjetas se renderizan con
"No disponible". El comportamiento **degrada correctamente** y no inventa números — eso es
lo importante y está bien resuelto.

Pero queda una sección entera del informe cuya única función es mostrar siete casillas
vacías con títulos como «NPV Conceptual — no validado». Un lector podría interpretar la
existencia de la sección como indicio de que el sistema *podría* calcular esos valores.
No puede.

---

## 8. El escudo de cumplimiento del asistente de IA

`api/chat_api.py` implementa un copiloto conversacional anclado a la corrida concreta. Y
tiene una capa de cumplimiento que merece descripción, porque es una decisión de diseño
inusual.

**Capa A — términos prohibidos** (`api/chat_api.py:44-46`):
`reserve`, `resource`, `grade`, `npv`, `irr`, `tonnage`, `economic value`. Si la respuesta
generada contiene cualquiera de estas subcadenas, se **redacta la respuesta completa**
(`api/chat_api.py:65-70`).

**Capa B — patrones de estimación** (`api/chat_api.py:49-55`): expresiones regulares que
detectan número + unidad de recurso en español o inglés:

- `\d[\d.,]*\s*(?:toneladas?|tonnes?|Mt|kt)` — tonelaje
- `(?:ley|grade)\s*(?:de\s*)?[:=]?\s*\d[\d.,]*\s*%?` — ley
- `(?:npv|van|tir|irr)\s*[:=]?\s*\d` — económicos
- `[$€]\s*\d…` — dinero

El diseño distingue correctamente entre **educar** y **estimar**: las menciones educativas
de JORC («qué exige la norma») **no** se redactan; sólo se redacta cuando aparece una cifra
con unidad de recurso (`api/chat_api.py:37-43`).

El mensaje de redacción es explícito y explica por qué
(`api/chat_api.py:57-62`).

**Observación menor.** La capa A hace coincidencia de **subcadena**, no de palabra
completa. Términos legítimos que contengan `grade` (`upgrade`, `degrade`) o `resource`
(`resourceful`) dispararían la redacción total. En un asistente que responde en español el
riesgo es bajo, pero la capa B —basada en regex con contexto— es claramente la mejor
construida de las dos.

---

## 9. Lo que un ingeniero de minas NO puede hacer con esto

Explícitamente, y para evitar malentendidos:

| Tarea | ¿Posible? | Por qué no |
|---|---|---|
| Estimar recursos (medidos/indicados/inferidos) | **No** | no hay leyes ni categorización |
| Estimar leyes entre sondajes | **No** | eso es kriging; no está implementado, y las notas del proyecto registran un *leave-one-out* con resultado NO_GO |
| Calcular tonelaje de mena | **No** | sin ley no hay discriminación mena/estéril |
| Optimizar un pit | **No** | no hay algoritmo de pit de ningún tipo |
| Secuenciar la explotación | **No** | no hay *scheduling* |
| Calcular VAN / TIR / vida de mina | **No** | ningún módulo los computa |
| Reportar bajo JORC / NI 43-101 | **No** | y el sistema lo declara y lo bloquea activamente |
| **Priorizar dónde perforar** | **Sí** | es exactamente para lo que está construido |
| **Cuantificar la probabilidad de que un blanco supere un contraste de densidad** | **Sí, con caveats** | posterior lineal; no captura error de modelo |

---

## 10. Los tres niveles, aplicados

**Lo que el código hace.** Ordena celdas de una malla por una métrica estadística
construida sobre el modelo de densidad invertido y su desviación posterior, suprime
vecinos próximos y devuelve una lista de coordenadas con probabilidades asociadas.

**Lo que matemáticamente significa.** Bajo el supuesto de que el posterior es gaussiano
alrededor de la solución regularizada, y de que la σ estimada es correcta, esas
probabilidades son la probabilidad de que el contraste de densidad en esa celda supere el
umbral. El supuesto es fuerte: ignora la no unicidad no lineal y el error de modelo, cosa
que el propio código declara.

**Lo que mineramente se puede afirmar.** Que esas ubicaciones son las que mejor combinan
anomalía de densidad y respaldo del dato. **No** se puede afirmar que haya mineralización,
ni ley, ni continuidad, ni volumen económico. Una anomalía de densidad positiva puede ser
un sulfuro masivo, una intrusión máfica estéril, un cambio litológico o un artefacto.

Y una limitación que atraviesa todo: **la profundidad no está resuelta** sin dato
independiente, y el sistema fija `depth_confidence = "LOW"` por defecto
(`services/geophysics_service.py:801-810`). Para diseñar una perforación eso importa
mucho: el sistema orienta dónde emplazar el collar, no a qué profundidad esperar el
intercepto.

---

## 11. Resumen técnico

### Correctamente implementado

- Ranking probabilístico de blancos con *expected improvement* y cota inferior de
  confianza, con alcance honesto declarado.
- Supresión de no-máximos 3D para blancos espacialmente distintos.
- Ponderación del score por resolubilidad del dato.
- Publicación de artefactos degradados con su razón, en lugar de ocultarlos.
- Procedencia de la "ley" marcada en el dato estructurado, no sólo en la prosa.
- Renombrado de columnas exportadas a nombres no mineros.
- Descargo regulatorio completo y correcto en el reporte.
- Escudo de cumplimiento en el asistente de IA, con la distinción educar/estimar bien
  resuelta.
- Degradación correcta a "No disponible" para métricas ausentes.

### No implementado (y declarado como tal)

- Economía minera completa: VAN, TIR, LOM, *cutoff* económico.
- Optimización de pit y *scheduling*.
- Estimación de leyes (kriging, IDW, IK).
- Categorización de recursos.

### Problemas detectados

1. **`bulk_rock_mass_kg` está en toneladas** — factor 1.000 entre el nombre y el valor
   (`exploration/gravimetry.py:4214`, `4248`). **CERRADO por la Fase 22 (2026-08-27):**
   renombrado a `bulk_rock_mass_tonnes`. La auditoría se quedó corta en el diagnóstico —
   ver la nota al final de §5.1.
2. **`density_contrast` se calcula contra un literal `2.6`** en lugar de `base_density`
   (`exploration/gravimetry.py:4213`), en una columna homónima pero distinta de la que
   consume el frontend. **CERRADO por la Fase 22 (2026-08-27):** eran tres escritores,
   no uno — ver §5.1.
3. **Sección económica del reporte sin productores**: siete tarjetas que siempre dicen
   "No disponible".
4. **Coincidencia por subcadena** en la lista de términos prohibidos del asistente.

---

## 12. Preguntas abiertas para revisión académica

---

### Pregunta 1 — ¿Es defensable el posicionamiento "targeting, no recursos"?

**Pregunta.** TerraQuantum se posiciona explícitamente como herramienta de **targeting**
(dónde perforar) y se niega a producir estimaciones de recurso. Desde la práctica de la
ingeniería de minas: ¿es ése un producto útil por sí solo para una empresa junior o una
consultora, o el mercado exige inevitablemente el paso a estimación de recursos? Y si es
útil: ¿qué información mínima adicional esperaría un cliente antes de comprometer una
campaña de perforación basada en este *output*?

**Por qué surge.** Es la decisión estratégica sobre la que descansa todo el diseño
técnico. Si la respuesta es que el targeting solo no se vende, hay que saberlo antes de
seguir construyendo sobre esa premisa.

**Evidencia.** `services/block_model_service.py:13` (eliminación del modo económico);
`exploration/gravimetry.py:559-565` (alcance declarado del ranking);
`api/chat_api.py:37-62` (el bloqueo activo).

---

### Pregunta 2 — El umbral de contraste y su elección

**Pregunta.** El ranking requiere un umbral $\tau$ de contraste de densidad por encima del
cual una celda es "anómala", y el `cutoff_density` por defecto es 2,75 t/m³. ¿Cómo
recomendaría fijar ese umbral en la práctica — a partir de la densidad medida de la roca
de caja en sondajes, de tablas petrofísicas por tipo de depósito, o de la distribución
estadística del propio modelo invertido? ¿Y debería el sistema exigirlo en lugar de
ofrecer un valor por defecto?

**Evidencia.** `services/geophysics_service.py:637` (el cálculo);
`exploration/gravimetry.py:519-533` (el parámetro `threshold`).

**Qué sabemos.** Que el resultado del ranking depende fuertemente de $\tau$: cambia tanto
qué celdas son candidatas como el valor de `expected_exceedance`.

---

### Pregunta 3 — Expected improvement como criterio de targeting

**Pregunta.** El score por defecto es
$\mathbb E[\max(m-\tau,0)] = \sigma\phi(d)+\text{diff}\cdot\Phi(d)$, tomado de la
optimización bayesiana. Premia tanto la anomalía fuerte y bien resuelta como la moderada
con incertidumbre alta. ¿Le parece el criterio adecuado para priorizar perforación, donde
cada sondaje cuesta decenas de miles de dólares? ¿O preferiría el criterio pesimista
(`lower_confidence_bound`), que penaliza la incertidumbre, dado que un sondaje fallido
tiene un coste real y no sólo un coste de oportunidad?

**Por qué surge.** En optimización bayesiana el *expected improvement* es adecuado porque
explorar es barato y se itera muchas veces. En perforación, ninguna de las dos cosas es
cierta.

**Evidencia.** `exploration/gravimetry.py:534-548` (las tres métricas);
`exploration/gravimetry.py:529` (`rank_by="expected_exceedance"` por defecto).

**Qué opinión sería útil.** Si en su experiencia la práctica es conservadora, cambiar el
default sería una mejora directa y de una línea.

---

### Pregunta 4 — El radio de exclusión

**Pregunta.** La supresión de no-máximos excluye candidatos a menos de `exclusion_radius`
de un blanco ya elegido, para obtener blancos espacialmente distintos. ¿Con qué criterio
fijaría ese radio — en función del tamaño esperado del cuerpo, de la resolución de la
malla, del espaciamiento de la grilla de perforación planificada? Hoy es un parámetro sin
valor por defecto documentado.

**Evidencia.** `exploration/gravimetry.py:527`, `552-557`.

---

### Pregunta 5 — Un proxy de densidad presentado junto a un campo llamado `grade`

**Pregunta.** El sistema calcula un `density_proxy_index` y lo expone también en un campo
llamado `grade`, acompañado de `is_demo_grade: true` y
`grade_source: "heuristic_gravity_proxy"`. ¿Considera suficiente esa señalización, o
recomendaría **eliminar** el campo `grade` por completo y dejar sólo
`density_proxy_index`? El argumento a favor de eliminarlo es que un campo llamado `grade`
acabará copiado a una presentación sin sus metadatos.

**Evidencia.** `services/geophysics_service.py:614-618`, `829-833`.

---

### Pregunta 6 — La sección económica vacía del reporte

**Pregunta.** El informe muestra siete tarjetas económicas (NPV, LOM, *cutoff*, ore/waste
tonnage…) que ningún módulo calcula, y que por tanto siempre dicen "No disponible".
¿Recomendaría eliminarlas del reporte, o mantenerlas con una explicación de por qué el
sistema deliberadamente no las calcula? Hay un argumento para lo segundo —documenta el
límite del alcance— y otro para lo primero: una sección vacía sugiere una capacidad que no
existe.

**Evidencia.** `reporting/report_generator.py:728-735` (las tarjetas);
búsqueda exhaustiva sin productores.

---

### Pregunta 7 — Qué haría falta para dar el paso a estimación de recursos

**Pregunta.** Suponiendo que en el futuro se quisiera cruzar la línea hacia estimación de
recursos: ¿cuál es el conjunto mínimo de piezas? Nuestra lista tentativa: (a) ensayos
químicos de sondaje; (b) un estimador geoestadístico con variografía; (c) dominios
geológicos definidos; (d) densidad medida por unidad, no invertida; (e) validación por
Persona Competente. ¿Falta algo esencial? ¿Y en qué orden lo abordaría?

**Por qué surge.** Para evitar construir en la dirección equivocada. Es más útil saber
ahora que el camino es largo que descubrirlo a mitad.

---

### Pregunta 8 — El error de unidades en la exportación

**Pregunta.** La columna `bulk_rock_mass_kg` contiene toneladas (volumen en m³ × densidad
en t/m³). Ningún consumidor identificado la lee, pero el Parquet se escribe en cada
corrida. Como práctica de ingeniería de datos en contexto minero —donde un error de
unidades de 1.000× en una masa es exactamente el tipo de error que llega a un informe—
¿qué recomendaría: corregir el nombre, corregir el valor, o eliminar la columna por no
tener consumidor?

**Evidencia.** `exploration/gravimetry.py:4214` (el cálculo), `4248` (el nombre exportado).

*(Respondida por el proyecto en la Fase 22, 2026-08-27: **corregir el nombre**, porque la
búsqueda exhaustiva no encontró consumidor alguno y porque el repositorio ya había
resuelto el mismo defecto así en su ruta canónica. Sigue siendo buena pregunta de examen:
la opción «eliminar la columna» es defendible y se descartó por una razón que conviene
discutir —el plan pedía conservarla— y el diagnóstico original subestimaba el error, que
no es 1.000× sino 1.000·dx³/1.000. Ver el cierre de §5.1.)*

---

*Fin del informe 06. El informe 05 trata la geología del subsuelo; el 04, la geofísica; el
12, la validación y la incertidumbre — incluida la discusión de por qué la profundidad no
está resuelta.*
