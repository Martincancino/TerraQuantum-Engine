# Hallazgo — El bound de densidad por defecto del camino de usuario cae del lado que hunde el modelo

**Fecha:** 2026-08-06 · **Versión:** `adba2b8+dirty` · **Método:** 48 inversiones controladas por
la ruta de producción, datos anti-inverse-crime, más lectura de la cadena UI → API → esquema.

> ## ⚠️ CORRECCIÓN (misma fecha, tras el E2E multi-semilla) — leer antes que nada
>
> **El titular original de este documento era incorrecto por sobre-generalización.** Decía que
> el bound por defecto "hunde el modelo en el camino del usuario". Eso es cierto **sólo cuando
> la malla es grande respecto al survey**, que es la configuración en que yo lo medí (malla
> forzada 2250 m sobre un survey de 1500 m). En el **flujo real** —grilla derivada del CSV, que
> es lo que manda la UI— el efecto catastrófico **no ocurre**.
>
> **Y una SEGUNDA corrección, tras barrer regímenes (48 inversiones, §7.2): tampoco el costo de
> profundidad generaliza.** Lo medí en un solo régimen (esfera r=150 m a 400 m) y volví a hablar
> de más. Al mover profundidad y tamaño, el efecto **cambia de signo y de magnitud**:
>
> | régimen | PR-AUC def/est | **profundidad def/est** | factor |
> |---|---|---|---:|
> | y=250 m | **0,890 / 0,288** | 125,0 / 78,7 m | 1,6× |
> | y=400 m | 0,867 / 0,816 | **247,9 / 24,0 m** | **10,3×** |
> | y=600 m | 0,297 / 0,059 | 135,2 / 191,9 m | **0,7×** |
> | y=900 m | 0,066 / 0,067 | 37,8 / 39,3 m | 1,0× |
> | r=100 m | 0,056 / 0,141 | 323,0 / 289,7 m | 1,1× |
> | r=250 m | 0,814 / 0,977 | **197,6 / 11,9 m** | **16,6×** |
>
> **Ningún brazo domina.** A 250 m el permisivo es **claramente mejor** (PR-AUC 0,890 vs 0,288);
> a 400 m el estricto gana por 10-17× en profundidad; a 600-900 m y con cuerpo chico da lo mismo
> porque **ninguno recupera**.
>
> ### Conclusión que sí se sostiene
>
> **`density_min` es una VARIABLE dependiente del régimen, no un default correcto o incorrecto.**
> Que es exactamente lo que decía `solver_configs.py` desde el primer día —*"no hay un valor
> correcto que elegir: hay dos brazos que se miden"*— y de lo que me fui alejando cuando las
> mediciones de malla forzada dieron números dramáticos.
>
> **La recomendación de invertir el default queda RETIRADA.** No hay evidencia que la respalde.
>
> Lo que queda accionable son los hechos de código de §2 —que el contraste efectivo no se declara
> en ningún lado, que nada acopla `density_min` con `base_density`, y que ningún test cubre el
> caso desacoplado— y precisamente **porque el valor correcto depende del régimen**, el usuario
> necesita al menos poder VER cuál le tocó.
>
> Las secciones §1–§5 conservan su medición original, válida **para la configuración en que se
> hizo**, ahora declarada en cada una.

---

## 1. La medición

Mismo mundo, misma geometría de survey, misma configuración de solver. Lo único que cambia es el
límite inferior de densidad. 8 semillas por brazo.

| `density_min` (relativo al fondo) | caídas | PR-AUC mediana | horizontal mediana | celdas en el bound |
|---|---:|---:|---:|---:|
| **base + 0,00** (contraste ≥ 0) | **2/8** | **1,000** | **25,0 m** | **91,3 %** |
| base − 0,01 | 8/8 | 0,035 | 133,9 m | 4,6 % |
| base − 0,02 | 8/8 | 0,035 | 145,7 m | 0,5 % |
| base − 0,05 | 8/8 | 0,035 | 141,9 m | 0,1 % |
| **base − 2,60** ← equivalente al default | **8/8** | **0,035** | **146,5 m** | **0,0 %** |

**El acantilado está en −0,01**, no en algún valor grande: permitir un 1,7 % del contraste del
cuerpo como densidad negativa ya destruye la recuperación en todas las semillas. La saturación
explica por qué: al abrirse el bound, las celdas se despegan en masa (91 % → 4,6 % → 0 %) y el
solver deja de estar restringido.

Consistente con el barrido de 150 corridas, donde el brazo de −0,5 dio PR-AUC 0,037 ± 0,003 en
**los 15 regímenes** — consistentemente malo, sin una sola excepción.

---

## 2. La cadena hasta el usuario, eslabón por eslabón

Todo lo de abajo es **[VERIFICADO EN CÓDIGO]**, con ruta y línea.

1. **UI** — `densityMin` arranca en `"0.0"` y el preset en `"custom"`
   (`terraquantum-web/componentes/PrepPanel.tsx:440-442`); se envía tal cual como
   `density_min` en la configuración del paquete (`:944`).
   Los presets (granito 2,6 · magnetita 4,5 · cobre 4,3) están en `:459-461`, pero **hay que
   elegirlos**: el estado inicial no es ninguno de ellos.
2. **API** — el paquete pasa el valor **verbatim** a la inversión, con el mismo default:
   `density_min=float(cfg.get("density_min", 0.0))`
   (`terraquantum-backend/api/gravity_import_api.py:1819`). **`base_density` no se pasa**
   en esa llamada.
3. **Semántica declarada por el propio backend**
   (`terraquantum-backend/api/gravity_import_api.py:1998-2002`):

   ```python
   # Bounds petrofísicos (t/m³ absolutos; base=2.6). density_min < 2.6 permite
   # contrastes NEGATIVOS (magma, sal, cavidades). Default 0.0 = bound físico
   # mínimo (recomendación industrial v2; el clip de no-negatividad estricta
   # degrada el misfit ~35% en cuerpos compactos).
   density_min: float = Form(0.0),
   ```

4. **`base_density`** cae en su default de esquema, **2,6**
   (`terraquantum-backend/schemas/geophysics_schema.py:757-758`).
5. ⇒ **contraste permitido ≥ 0,0 − 2,6 = −2,6 t/m³.**

Y nada acopla los dos campos: `_validate_box` y `_v2_cross_validate` sólo comprueban
`min < max`. La única cosa que sugiere que deben moverse juntos es un **comentario**
(`geophysics_schema.py:754-756`). Las pruebas propias del proyecto
(`tests/test_bounds_variability.py:82,92,102`) sólo ejercitan pares acoplados
(2,6/2,6 · 4,5/4,5 · 3,0/3,0): **el caso desacoplado no está cubierto por ningún test**.

---

## 3. La afirmación que sostiene el default, contrastada

El comentario declara el motivo: *"el clip de no-negatividad estricta degrada el misfit ~35 % en
cuerpos compactos"*. Es la única justificación escrita del default, así que merecía medirse en
vez de descartarse. Los datos del barrido (15 regímenes × 5 semillas × 2 brazos) la contrastan
directamente, porque miden misfit **y** calidad al mismo tiempo.

### Veredicto: la afirmación es real en su dirección, y menor y menos general de lo que dice

**En los regímenes compactos y bien sensados que la afirmación invoca** (medianas sobre 5 semillas):

| régimen | misfit estricto → permisivo | | PR-AUC estricto → permisivo | |
|---|---|---:|---|---:|
| `baseline` | 20,76 % → 17,16 % | **+21,0 %** | 1,000 → 0,038 | **−96 %** |
| `depth_400m` | 20,76 % → 17,16 % | **+21,0 %** | 1,000 → 0,038 | **−96 %** |
| `coverage_14` | 20,42 % → 17,61 % | **+16,0 %** | 1,000 → 0,035 | **−97 %** |
| `depth_250m` | 9,17 % → 9,41 % | **−2,6 %** | 1,000 → 0,074 | **−93 %** |

*(«+» = el clip estricto ajusta peor, que es lo que la afirmación sostiene.)*

- La degradación real en cuerpos compactos es de **16–21 %**, no 35 %. Y en uno de los cuatro el
  clip estricto ajusta **mejor**.
- **Sobre los 15 regímenes la ventaja se disuelve**: el permisivo ajusta mejor en **8 de 15**
  —apenas mejor que una moneda— con una **mediana de +0,6 %** y un rango de −38,6 % a +37,9 %.
- **El precio es el modelo**: PR-AUC cae entre −93 % y −97 % en los mismos casos.

Traducido a la decisión: **se compra un 16–21 % de misfit al precio de ~95 % de la capacidad de
localizar el cuerpo.** Y fuera de los cuatro casos compactos, ni siquiera se compra eso.

### Qué tan malo es un PR-AUC de 0,035 — medido, no adjetivado

Con 8 celdas de cuerpo en 4.536, un ranking **aleatorio** da PR-AUC ≈ **0,0018**
(mediana empírica sobre 200 rankings aleatorios: 0,0018; p95 0,0036).

Así que **0,035 no es azar: es ~20× el azar.** Conserva señal real, sólo que muy pobre. El brazo
estricto está en ~567× el azar. La diferencia entre los dos brazos es un factor **29**.
Lo digo así porque «el modelo es basura» sería más contundente y menos cierto.

### Por qué el criterio no podía ver el coste

**El misfit es precisamente la métrica ciega a esta falla.** Medido en este mismo trabajo:

- ρ(χ², PR-AUC) sobre 75 corridas = **+0,073**; mediana intra-régimen = **0,000**.
- En `baseline`, cinco semillas con **el mismo λ** y χ² entre 1,197 y 1,411 dan errores de
  5,6 m a 285,5 m.

El modelo hundido **ajusta el dato igual de bien**: es una solución data-consistente del
null-space, positivo somero y negativo profundo. Por construcción, cualquier criterio basado en
residuales la va a preferir. Que el misfit mejore un 35 % al abrir el bound no es evidencia de
que el modelo sea mejor — es lo que se esperaría si el bound estuviera haciendo el trabajo de
regularización que el misfit no puede evaluar.

Esto conecta con el otro hallazgo del día
([`HALLAZGO_2026-08-06_techo_medium.md`](HALLAZGO_2026-08-06_techo_medium.md)): las tres señales
que el usuario ve —χ² sano, confianza `MEDIUM`, error de centroide de 146 m que no parece
alarmante— son **las tres tranquilizadoras** en el caso hundido.

---

## 4. Lo que este hallazgo NO dice

- **No dice que el contraste negativo sea incorrecto.** Existen objetivos genuinamente menos
  densos que la roca caja — el propio comentario nombra magma, sal y cavidades. Para ésos el
  bound negativo es necesario. La conclusión no es "forzar ≥ 0 siempre".
- **No está medido en todos los regímenes.** El barrido de bound usa una malla (125 m), un
  cuerpo (r=150 m a 400 m) y un contraste (+0,6). El respaldo más amplio es el brazo de −0,5 del
  barrido de 150 corridas, malo en los 15 regímenes.
- ~~**No se ejecutó el endpoint HTTP.**~~ **Cerrado — ver §7.**
- **El cuerpo ocupa 8 celdas de 4.536.** Con tan pocos positivos, el PR-AUC salta en escalones
  gruesos (1,000 · 0,716 · 0,583 …), así que **no distingue finamente** dentro del brazo bueno.
  La bimodalidad no descansa en eso: la confirma el error de centroide, que es independiente y
  se mueve de ~10 m a ~285 m. Pero conviene saber que la resolución de la métrica es limitada
  en este mundo, y que un mundo con el cuerpo mejor muestreado mediría mejor.
- **La afirmación del 35 % no se pudo reproducir en su forma original**: no consta con qué
  mundos, mallas ni métricas se midió. Lo medido aquí es un contraste equivalente sobre el
  catálogo del framework, no una réplica del experimento original.

---

## 7.2 Barrido de regímenes — el efecto no generaliza

`validation/e2e_bound_regimes.py`: grilla automática, cutoff 2250, **6 regímenes × 2 brazos ×
4 semillas = 48 inversiones por HTTP**, 120 min, 0 errores. Mediana y rango por celda.

| régimen | y (m) | r (m) | PR-AUC def/est | horiz def/est | profundidad def/est | factor |
|---|---:|---:|---|---|---|---:|
| `prof_250` | 250 | 150 | **0,890 / 0,288** | 4,4 / 18,8 | 125,0 [123-128] / 78,7 [26-83] | 1,6× |
| `prof_400` | 400 | 150 | 0,867 / 0,816 | 4,5 / 8,7 | **247,9** [244-253] / **24,0** [20-30] | **10,3×** |
| `prof_600` | 600 | 150 | 0,297 / 0,059 | 17,5 / 31,8 | 135,2 [120-142] / 191,9 [121-194] | **0,7×** |
| `prof_900` | 900 | 150 | 0,066 / 0,067 | 49,5 / 54,2 | 37,8 [27-50] / 39,3 [28-52] | 1,0× |
| `radio_100` | 400 | 100 | 0,056 / 0,141 | 24,9 / 31,8 | 323,0 [247-334] / 289,7 [157-301] | 1,1× |
| `radio_250` | 400 | 250 | 0,814 / 0,977 | 2,0 / 2,9 | **197,6** [196-199] / **11,9** [10-134] | **16,6×** |

**Lectura, por partes:**

1. **El costo de profundidad es real pero sólo en 2 de 6 regímenes** (`prof_400` 10,3× y
   `radio_250` 16,6×), y en ambos con rangos que no se solapan. No es azar; es específico.
2. **A 250 m el brazo permisivo GANA, y por mucho**: PR-AUC 0,890 contra 0,288 y horizontal 4,4
   contra 18,8 m. Reproduce lo que ya se había medido en `w001` (somero, malla fina) al comienzo
   de todo esto: permisiva 2,3 m / PR-AUC 0,96 contra estricta 9,8 m / 0,48.
3. **A 600 m el permisivo es mejor en profundidad** (135,2 vs 191,9 m) aunque ambos ya están
   rotos en PR-AUC (0,297 y 0,059).
4. **A 900 m y con cuerpo chico (r=100) no hay diferencia** porque no hay recuperación:
   PR-AUC 0,056–0,141.

**El espejismo del centroide, ahora en vertical — confirmado.** En `prof_900` el error de
profundidad es de apenas 37,8 m con **PR-AUC 0,066**. Un centroide casi exacto sobre un modelo
sin información: la masa untada por el dominio tiene su centro cerca del medio, y a 900 m el
cuerpo verdadero está cerca del medio. **Ese 37,8 m no es un acierto, es un empate por
geometría.** Es la tercera vez en esta sesión que el centroide miente, ahora en el eje que el
producto declara como su punto débil. Ninguna cifra de profundidad de este sistema debería
leerse sin su PR-AUC al lado.

**Mejora de la medición:** con grilla automática la malla tiene 9.216 celdas y el cuerpo ocupa
52–54 (contra 8 en la malla forzada). Eso levanta la limitación declarada antes: con 8 positivos
el PR-AUC saltaba en escalones gruesos; con 54 discrimina de verdad.

---

## 5-bis. ~~Recomendación~~ RETIRADA — ver la corrección al inicio

> **Esta sección se conserva como registro de un razonamiento que la medición posterior refutó.**
> El barrido de regímenes (§7.2) mostró que ningún brazo domina: a 250 m el permisivo gana
> claramente, a 400 m gana el estricto, a 600-900 m da igual. **No hay base para invertir el
> default.** Lo que sigue quedó escrito antes de tener esos datos.

<details>
<summary>Texto original (refutado)</summary>

## 5-bis. Recomendación, ahora que la afirmación está medida

Cuando escribí la primera versión de este documento dije que el default no debía tocarse hasta
re-medir el 35 %. Ya está medido, así que corresponde pronunciarse.

**El argumento que sostiene el default no sobrevive a su propia medición.** Compra 16–21 % de
misfit en cuatro regímenes compactos —a cambio de 93–97 % de la calidad de recuperación— y fuera
de ellos no compra nada (8/15, mediana +0,6 %). No es que la afirmación fuera falsa: es que se
midió con la única métrica que no podía ver el precio.

**Recomiendo invertir el default** a contraste ≥ 0, con el negativo disponible como opción
explícita y motivada. Pero **la decisión es del dueño del producto**, por tres razones que no son
técnicas y que quiero dejar escritas:

1. Cambia lo que ve un usuario que ya tenga corridas hechas: modelos previos y nuevos dejarán de
   ser comparables. Hace falta decidir qué se le dice.
2. Los objetivos de contraste negativo (sal, cavidades, magma) dejan de funcionar por defecto.
   Si algún usuario real los busca, para él es una regresión.
3. Mi medición cubre un mundo, una malla y un contraste positivo. Es suficiente para justificar
   el cambio, **no** para prometer que no rompe nada.

**Lo mínimo defendible si no se quiere tocar el default todavía:** que la corrida **declare** el
contraste permitido efectivo (`density_min − base_density`) en su salida y en el reporte, y que
avise cuando sea negativo. Hoy ese número —el único que importa físicamente— no aparece en
ningún lado; se deduce restando dos campos que viajan por caminos distintos. Eso es barato, no
cambia ningún resultado, y convierte un fallo silencioso en uno visible.

</details>

**Lo único de esta sección que sobrevive al barrido de regímenes** es el último párrafo, y ahora
con más fuerza que antes: **precisamente porque el valor correcto depende del régimen**, el
contraste permitido efectivo tiene que ser visible. No se le puede pedir al usuario que elija
bien un parámetro cuyo valor efectivo el sistema no le muestra.

---

## 5. Direcciones (ninguna implementada — requieren decisión)

1. **Acoplar `density_min` a `base_density` por construcción**: expresar el bound en espacio de
   **contraste** en la superficie de usuario, o validar que se declaren juntos. Hoy son dos
   números independientes cuya relación —que es lo único que importa físicamente— no la comprueba
   nadie.
2. **Cambiar el default a contraste ≥ 0** y exigir opt-in explícito para negativo, con el motivo
   declarado (*"busco un cuerpo menos denso que la caja: sal / cavidad / magma"*). El default
   debería ser el caso mayoritario, no el más permisivo.
3. **Re-medir la afirmación del 35 %** con métricas independientes del umbral. Si al abrir el
   bound el misfit mejora y el PR-AUC se desploma, la afirmación sigue siendo cierta y **deja de
   ser un argumento**.
4. **Un test del caso desacoplado**: `density_min` absoluto ≠ `base_density`, verificando que el
   contraste permitido resultante es el que se pretende.

**Orden sugerido:** 1 y 4 primero (son estructurales y baratos), 3 antes de tocar el default,
2 al final, cuando el número respalde el cambio.

---

## 7. E2E por HTTP — confirmado, y con un segundo default de regalo

`validation/e2e_package_bound.py` sube un paquete `.tqpkg` real a
`POST /v2/gravity-import/load-package?sync=true` con el backend levantado. Nada de llamar a la
función por dentro: el camino completo del usuario.

| caso | `density_min` | `cutoff_radius` | PR-AUC | horizontal |
|---|---|---|---:|---:|
| **estricto** | 2,6 (= `base_density`) | 2250 | **1,000** | **1,1 m** |
| **default del paquete** | *(ausente → 0,0)* | 2250 | **0,018** | 1168,9 m |
| estricto | 2,6 | *(0 → 500)* | 0,213 | 724,4 m |
| default del paquete | *(ausente → 0,0)* | *(0 → 500)* | 0,226 | 712,3 m |

**El hallazgo del bound queda confirmado de punta a punta**: a igual todo lo demás, el bound
acoplado a `base_density` da PR-AUC 1,000 y **1,1 m** de error; el default del paquete da 0,018
y 1,2 km, con **50,4 % de las celdas en contraste negativo**. Factor 55.

Y el E2E destapó **un segundo default en el mismo camino**: `cutoff_radius: 0.0` del paquete se
convierte en **500 m** (verificado en el `inputs.json` de la corrida). Con ese valor **no
recupera ninguna de las dos configuraciones** (0,213 y 0,226): el bound deja de importar porque
ya no hay nada que salvar.

### 7.1 La grilla automática lo cambia todo — 5 semillas, flujo real

Lo anterior usa la malla FORZADA. El flujo real manda `nx/ny/nz/block/depth` en 0 y el backend
deriva la grilla del CSV (9.216 celdas en vez de 4.536). Repetido así, **2 bounds × 2 cutoffs ×
5 semillas = 20 inversiones por HTTP**, medianas:

| bound | cutoff | PR-AUC | horizontal | **profundidad** | rango prof. | celdas < 0 |
|---|---|---:|---:|---:|---|---:|
| default | *(0 → 500)* | 0,464 | 25,5 m | 58,9 m | 51,1 – 65,3 | 6,7 % |
| estricto | *(0 → 500)* | 0,452 | 31,1 m | 60,6 m | 56,3 – 67,6 | 0,0 % |
| default | 2250 | 0,837 | 13,1 m | **247,6 m** | 236,1 – 258,2 | 44,3 % |
| **estricto** | **2250** | **0,835** | **13,1 m** | **18,8 m** | **7,4 – 35,5** | 0,0 % |

**Tres conclusiones, todas con los rangos a la vista:**

1. **El desastre del bound NO se reproduce en el flujo real.** Aquí todo recupera: horizontal
   entre 13 y 31 m para un cuerpo de radio 150 m. El factor 55 del §7 era propio de la malla
   sobredimensionada.
2. **Pero el bound sí cuesta PROFUNDIDAD, y de forma limpia:** 247,6 m contra 18,8 m, con
   **rangos que no se solapan** (236–258 vs 7–36) sobre 5 semillas. Y **no cuesta nada en
   horizontal**: 13,1 m en ambos. El contraste negativo deja hundir la masa sin mover el blanco
   en planta — exactamente el modo de fallo que el proyecto ya conocía por otras vías.
3. **El `cutoff_radius` por defecto (0 → 500 m) también cuesta**, y en el otro eje: PR-AUC 0,464
   contra 0,837 y horizontal 25,5 contra 13,1 m. En profundidad, en cambio, 500 m es *mejor* que
   2250 con bound permisivo (58,9 vs 247,6): al recortar el kernel, la masa no alcanza a hundirse.

**Los defaults de fábrica contra la mejor configuración medida:**

| | PR-AUC | horizontal | profundidad |
|---|---:|---:|---:|
| default de fábrica (bound 0,0 · cutoff 0→500) | 0,464 | 25,5 m | 58,9 m |
| mejor medida (bound = base · cutoff 2250) | **0,835** | **13,1 m** | **18,8 m** |

Factor **1,8× en PR-AUC, 2× en horizontal, 3× en profundidad** — sin tocar el motor, sólo dos
números de configuración. No es la catástrofe que reporté al principio; es una mejora libre y
medible que hoy nadie se está llevando.

**Límite:** un mundo, un tamaño de cuerpo, una profundidad, 5 semillas. Suficiente para decir
"aquí hay algo que revisar", insuficiente para cambiar defaults sin barrer regímenes.

`depth` quedó descartado como sospechoso: 1 vs 1750 da resultados byte-idénticos.

### El bug que casi me hace publicar lo contrario

**La primera pasada del E2E dijo que el bound NO tenía efecto** (0,023 vs 0,024) y que nada
recuperaba. Era un fallo mío: **el import re-origina las estaciones al mínimo** —las envié en
x,z ∈ [375, 1875] y quedaron persistidas en [0, 1500], un corrimiento de −375 m— mientras la
malla se construye 0..2250. Mi máscara de verdad seguía en el marco de entrada, así que medía
contra el sitio equivocado.

Lo que lo delató fue comparar las observaciones enviadas contra las persistidas: la gravedad
coincidía a 8 dígitos y las **coordenadas no**. Corregido, `estricto` pasó de 0,003 a **1,000**
y coincidió al decimal con la corrida directa (1,1 m en ambas).

El script ahora **deriva el desplazamiento de los datos persistidos** en vez de asumirlo, e
imprime cuánto fue. Dos lecciones que valen más que el arreglo:

1. **Un E2E que confirma lo que esperabas es sospechoso; uno que lo refuta hay que auditarlo
   antes de creerle.** Si la primera pasada hubiera coincidido con mi hipótesis, no habría
   mirado las coordenadas y el bug seguiría ahí, esta vez a favor.
2. **Efecto colateral observado:** con una malla mayor que el survey, éste **no queda centrado**
   —se ancla en la esquina del dominio— porque el import re-origina al mínimo y la malla parte
   de 0. Sólo muerde cuando la malla se fuerza más grande que el survey, pero conviene saberlo.

---

## 6. Reproducir

```bash
python -m validation.exp_bound_saturation --seeds 8                 # 0,00 / -0,01 / -0,02 / -0,05
python -m validation.exp_bound_saturation --seeds 8 --arms "0,-2.6" # estricto vs default
```

48 inversiones, ~45 min. Datos crudos en
`%LOCALAPPDATA%\TerraQuantum\validation_results\adba2b8+dirty\exp_bound_saturation.json`.
