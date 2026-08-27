# TerraQuantum — CONVENCIÓN DE EJES DEL BACKEND

> **Decidido por la Fase 18** · 2026-08-25 · defecto **ACAD-1**
> Este documento existe porque dos módulos del backend documentaban convenciones
> **opuestas** y nada las comparaba. Aquí se elige una, se dice por qué, y se
> deja escrito qué tiene que cambiar para cumplirla.
>
> Toda afirmación numérica sale de
> `terraquantum-backend/scripts/validation/fase18_axis_convention_experiment.py`
> y su reporte `fase18_axis_convention_report.json`. Nada se apoya en
> documentación previa.

---

## 1. LA DECISIÓN

**El marco local del backend es, en todo el árbol y sin excepción:**

| slot | significado | signo |
|---|---|---|
| `x_m` / eje 0 | **ESTE** (easting) | + hacia el Este |
| `y_m` / eje 1 | **PROFUNDIDAD** | **+ hacia ABAJO** |
| `z_m` / eje 2 | **NORTE** (northing) | + hacia el Norte |

Es un marco **levógiro** respecto del ENU habitual, porque `y` apunta hacia
abajo. Eso ya era así y no se toca: cambiarlo movería la gravimetría, los
sondajes, la topografía y los exportadores.

Lo que sí cambia es **quién estaba equivocado**. El motor magnético declaraba
`x=Norte, z=Este` y construía su vector de campo con esa creencia. **Está
equivocado, y es el que se adapta.**

En consecuencia, el vector unitario del campo geomagnético inducido es

```
f̂ = (cos I · sin D,   sin I,   cos I · cos D)        [orden (x=Este, y=prof↓, z=Norte)]
```

y **no** `(cos I · cos D, sin I, cos I · sin D)`, que es la forma correcta sólo
si el eje 0 fuese el Norte.

---

## 2. POR QUÉ ÉSTA Y NO LA OTRA

Se podía cerrar la contradicción por cualquiera de los dos lados: permutar el
dato en el empalme, o corregir el campo en el motor. La decisión no es de
gusto — se tomó contando **cuántos sitios afirma cada convención y cuántos
dependen de ella para funcionar**.

**`x=Este, z=Norte` ya está implementada y en uso** en todo el camino del dato:

| dónde | evidencia |
|---|---|
| Ingesta, declaración canónica | `services/gravity_import_service.py:131` — *«Internal convention: x_m slot = east/lon, z_m slot = north/lat»* |
| Ingesta, rama UTM | `gravity_import_service.py:350` — *«UTM: easting→x_m slot, northing→z_m slot»* |
| Ingesta, rama lat/lon | `gravity_import_service.py:324` — *«lon→x_m slot, lat→z_m slot»* |
| Transformación de coordenadas | `services/coordinate_transform_service.py:129` — `_build_shifted_observations(observations, east_m, north_m)` → `x_m=east`, `z_m=north` |
| Mapeo manual de columnas | `services/column_mapping_service.py:29,32-33` |
| Exportador OMF | `services/omf_export_service.py:423` — *«x=Este, y=profundidad↓, z=Norte»*, y `:425,:561` suman `easting0` a la columna x |
| Escritor UBC de disco | `services/gravity_import_service.py:2166` — *«TQ: (x=Este, y=profundidad hacia abajo, z=Norte)»* |

**`x=Norte, z=Este` no está implementada en ninguna parte del camino del dato.**
La declaran **28 sitios**, y de ellos **sólo dos expresiones ejecutables**
dependen de ella para calcular algo:

- `exploration/magnetometry.py:93` — la componente 0 de `f̂`, con el comentario
  `# x = Norte`. **Ésta es la raíz.**
- `exploration/magnetometry.py:2458` — `dec_eff = atan2(Mz, Mx)` en la
  inversión vectorial MVI. **Segunda fuga independiente**: publica al usuario
  una declinación de magnetización calculada con la convención equivocada.
- Los **26** restantes son docstrings, comentarios, cadenas de metadatos y los
  harness de validación. No calculan nada.

> **Corolario que decide el asunto:** adoptar `x=Este, z=Norte` no obliga a
> permutar un solo array. La alternativa —permutar el dato en el empalme—
> obligaría a permutar de vuelta la malla, los vóxeles, el parquet, los cortes,
> los anclajes de sondaje y los dos exportadores, para acabar en el mismo sitio.

**Errata heredada.** `magnetometry.py:31` afirma que su convención es *«idéntica
a gravimetry»*. `exploration/gravimetry.py` **no declara ninguna convención de
ejes** en sus 4365 líneas, así que la afirmación no es verificable contra su
fuente. Y no podía detectarse por sus resultados: la gravimetría usa sólo la
componente vertical del prisma de Nagy, que es **simétrica bajo x↔z** — medido,
`4,8·10⁻¹⁴` de diferencia relativa al permutar (mutación M4).

---

## 3. LA EVIDENCIA

### 3.1 El defecto no es una rotación de 90°: es una **reflexión**

Producción calcula la respuesta magnética con una **declinación efectiva**

```
D_efectiva = 90° − D          (I queda intacta)
```

Es decir, refleja el azimut del campo sobre la diagonal de 45°. Ajustando qué
par (I', D') reproduce la salida de producción, el residuo baja a **~10⁻¹³ nT**:
no es una aproximación, es una identidad.

| sitio | I | D | D efectiva medida | predicha | rotación | Pearson r | error/señal |
|---|---|---|---|---|---|---|---|
| **Chile** (defaults) | −30,0° | 2,0° | **88,000°** | 88,00° | **86,000°** | **−0,053** | **1,45** |
| DO-27 (IGRF real) | 83,8° | 25,4° | 64,600° | 64,60° | 39,200° | 0,9945 | 0,103 |
| Raglan (IGRF real) | 83,0° | −32,0° | 122,000° | 122,00° | 154,000° | 0,9407 | 0,336 |
| **Declinación 45°** | −30,0° | 45,0° | **45,000°** | 45,00° | **0,000°** | **1,0000** | **0,000** |

La última fila es la que **distingue reflexión de rotación**, y ninguna lectura
de código podía darla: con `D = 45°` el defecto es **exactamente invisible**
(diferencia `1,9·10⁻¹³` nT). Si fuera una rotación rígida de 90°, ahí habría un
error del **78 %** de la señal. Se midió: lo hay para la hipótesis rival, no
para producción (mutación M2).

En Chile el `r = −0,05` es el titular: la anomalía que produce el motor **no
está correlacionada con la verdadera**. No es un sesgo, es otro dato.

### 3.2 Por qué DO-27 y Raglan no lo vieron — y son dos razones

**(a) La ceguera es cuantificable y tiene forma cerrada.** Lo que se desplaza es
`f̂` en el marco geográfico, y su módulo vale exactamente

```
índice de ceguera = √2 · cos I · |sin D − cos D|
```

verificado contra el cálculo numérico a `1·10⁻¹⁶`:

| sitio | índice | relativo a Chile |
|---|---|---|
| Chile | **1,1813** | 1× |
| Raglan | 0,2375 | **5,0× menor** |
| DO-27 | 0,0725 | **16,3× menor** |
| D = 45° | 0,0000 | ∞ |

`cos I ≈ 0,11` en el Ártico aplasta la componente horizontal del campo, que es
justo la que se refleja. El caso de uso declarado —Chile, `cos I ≈ 0,87`— es el
**peor** del rango.

**(b) Los harness no pasan por el importador.** `ingest_do27.py:100` y
`raglan_harness.py:104` arman el frame local a mano *con* la convención del
motor (`x=Norte`), así que son internamente consistentes pase lo que pase en
producción. Por eso la Fase 18 tuvo que construir un CSV y meterlo por la puerta
del usuario.

### 3.3 El camino de producción completo lo confirma

CSV con cabeceras en español → `import_gravity_csv_v1(data_kind="magnetic")` →
empalme literal de `geophysics_service.py:2107` → motor.

**El contrato de la ingesta, medido** (malla de estaciones deliberadamente
asimétrica, 21 × 13, spans 1200 m × 720 m — con malla cuadrada el defecto sería
invisible):

```
|x_m − Este|  = 0,00e+00 m          |x_m − Norte| = 1200,0 m
span(x_m, z_m) = (1200, 720)        span CSV (E, N) = (1200, 720)
```

El slot `x_m` **es** el easting. No es una lectura de comentario: es el número.

**La consecuencia en el modelo recuperado** (inversión magnética de producción;
brazo de control = `field_unit_vector` parcheado a la convención del dato, un
instrumento de medida que no se escribe en producción):

| geometría | sitio | brazo | err. horizontal | misfit |
|---|---|---|---|---|
| cuadrada 17×17 | **Chile** | **producción** | **150,0 m** | **51,61 %** |
| cuadrada 17×17 | **Chile** | control | **30,0 m** | **1,04 %** |
| cuadrada 17×17 | DO-27 | producción | 30,0 m | 21,67 % |
| cuadrada 17×17 | DO-27 | control | 30,0 m | 21,05 % |
| alargada 21×13 | Chile | producción | 150,0 m | 60,76 % |
| alargada 21×13 | Chile | control | 30,0 m | 22,06 % |
| alargada 21×13 | DO-27 | producción | 30,0 m | 26,41 % |
| alargada 21×13 | DO-27 | control | 30,0 m | 25,72 % |

En Chile el defecto **quintuplica el error horizontal y multiplica el misfit por
50**. En el Ártico **los dos brazos son indistinguibles** (0,6 puntos de misfit,
mismo error horizontal). Eso es exactamente lo que predice el índice de ceguera.

> El misfit del 51,6 % es lo que el usuario ve: la inversión **no puede ajustar
> su propio dato**, y el producto le entrega igualmente un modelo.

---

## 4. QUÉ CAMBIÓ (ejecutado por la Fase 19, 2026-08-26)

> **Estado: HECHO.** Todo lo que esta sección enumeraba está aplicado. La
> guardia que exige la §6 vive en `tests/test_fase19_convencion_de_ejes.py` y
> `tests/test_fase19_zip_ubc_ejes.py`. Se conserva el texto en futuro porque es
> el registro de la decisión, no una lista de tareas viva.
>
> **Dos erratas de esta sección, medidas al ejecutarla:** los «26 sitios
> declarativos» incluían **dos que sí calculan** —
> `scripts/prepare_test_csv.py:87-89` (`fx`/`fz` del campo regional) y
> `scripts/diagnostics/generar_3csv_multifisica.py:36-38` (el `rvec` con el que
> genera el CSV multi-física)—: los dos generan datos sintéticos que entran al
> motor por los slots 0 y 2, así que había que voltearlos. Y faltaba un tercer
> sitio declarativo, `magnetometry.py:125-128`, en el docstring de
> `MagnetometryForward`.

### 4.1 Lo que decía el plan

**Lo ejecutable — dos líneas, y las dos hay que cambiar juntas:**

| ruta:línea | hoy | debe ser |
|---|---|---|
| `exploration/magnetometry.py:92-96` | `f = [cos I·cos D, sin I, cos I·sin D]` | `f = [cos I·sin D, sin I, cos I·cos D]` |
| `exploration/magnetometry.py:2458` | `dec_eff = degrees(arctan2(Mz, Mx))` | `dec_eff = degrees(arctan2(Mx, Mz))` |

> **Arreglar sólo la primera es peor que no arreglar nada** en el modo MVI: el
> kernel quedaría correcto y la declinación publicada seguiría reflejada. El
> repositorio ya tiene la trampa puesta —
> `tests/test_fase20c_mvi.py:159` exige `|dec_eff − DEC| ≤ 25°` con
> `DEC = 2,0°`; un arreglo a medias devuelve 88° y el test se pone rojo con
> **86°** de margen excedido. Es la guardia que ya existe: **no la borres, es la
> que caza el arreglo incompleto.**

**Herencia gratuita:** la remanencia (`magnetometry.py:468`,
`f_rem = field_unit_vector(inc_rem, dec_rem)`) y la amplitud usan la MISMA
función, así que se corrigen solas. No hay que tocarlas.

**Los 26 sitios declarativos** (docstrings, comentarios y cadenas de metadatos)
en `magnetometry.py:31,83,93,95,202-203,461,523,2455`,
`schemas/geophysics_schema.py:576`, `services/geophysics_service.py:2125`
(un comentario `# (x=Norte, z=Este)` sobre datos correctos) y
`scripts/prepare_test_csv.py:87`.

**Dos mentiras publicadas al cliente**, que hoy salen en la respuesta HTTP:

- `services/geophysics_service.py:2433` → `"axis_convention": "x=Norte, z=Este, y=profundidad(+abajo)"`
- `services/joint_inversion.py:972` → idéntica

Son **falsas respecto del contenido de los arrays** que acompañan. La rama joint
es especialmente clara: declara `x=Norte` en `:972` y su propio empalme de
`:491` mete el easting en el slot 0.

**Los harness de validación, en el MISMO commit:** `ingest_do27.py:18,26,100,116`,
`do27_harness.py:118`, `do27_depth_experiment.py:105`, `ingest_raglan.py:10-11,206`,
`raglan_harness.py:15,104,174`, `synthetic_depth_ambiguity.py:66`,
`depth_source_comparison.py:41`.

> **Sus números NO cambian, y está medido.** Voltear `f̂` *y* voltear el
> ensamblado del harness es un re-etiquetado consistente de la misma
> configuración física: el dato predicho sale **idéntico a 3·10⁻¹⁶ nT** sobre una
> señal de ~1 nT, en los cuatro sitios (Parte C). Lo medido es el **forward**; la
> inversión lo hereda por ser el mismo sistema re-etiquetado, pero eso es un
> argumento, no una corrida — **la Fase 19 debe cerrarlo corriendo DO-27 y Raglan
> de punta a punta antes y después.**

---

## 5. QUÉ **NO** HAY QUE CAMBIAR

- **La ingesta.** Ya cumple la convención canónica en las cinco ramas
  (`x_m/z_m` legacy, lat/lon, UTM, alias locales, mapeo manual). No se toca.
- **`coordinate_transform_service.py`.** Idem.
- **La malla, los vóxeles, el parquet, los cortes, los anclajes de sondaje.** Son
  geometría por slots: invariantes bajo re-etiquetado.
- **Gravimetría.** Medido invariante a `4,8·10⁻¹⁴`. Cualquier cambio ahí es
  riesgo sin beneficio.
- **El signo de `y`.** Profundidad positiva hacia abajo se queda.

---

## 6. LA GUARDIA QUE FALTA

Nada en el árbol compara hoy la convención de la ingesta con la del motor. Ese
es el defecto real — la permutación ausente es sólo su síntoma. Después de la
Fase 19 debe existir un test que **falle si alguien vuelve a separarlas**, y el
criterio no puede ser leer un comentario: tiene que meter un CSV con easting y
northing distinguibles y comprobar en qué slot caen, y luego comprobar contra
qué componente de `f̂` se multiplica ese slot.

`part_b` (tramo B1) y la Parte D de
`scripts/validation/fase18_axis_convention_experiment.py` ya son ese test en
forma de experimento; convertirlo en `tests/` es trabajo de la Fase 19.

---

## 7. LO QUE ESTE DOCUMENTO **NO** DECIDE

- **La convención de los ejes visuales del frontend.** `section_service.py:13`
  habla de ejes Three.js; esta decisión es del backend. La Fase 18 no miró
  frontend (regla de oro del repositorio).
- **El orden de celdas UBC-GIF y la georreferencia del ZIP** (ACAD-1c). Es el
  mismo error en el otro extremo del pipeline, y la Fase 19 lo agrupa, pero su
  criterio es el estándar UBC, no este documento.
- **Si `omfvista` lee las celdas transpuestas** respecto de la especificación
  (hallazgo de la Fase 12). Sigue abierto.

---

*Fase 18 · mutación 8/8 · reporte
`terraquantum-backend/scripts/validation/fase18_axis_convention_report.json`*
