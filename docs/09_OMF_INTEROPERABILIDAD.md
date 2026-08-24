# 09 — OMF: interoperabilidad con el software minero

**Fase 12 del plan** (`docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §10). Estado: **v0**.

TerraQuantum exporta e importa **Open Mining Format v1** (`.omf`), el contenedor
con el que un consultor entrega a una minera que trabaja con Leapfrog, Vulcan,
Micromine o Deswik. Sin él, el resultado de TerraQuantum muere en TerraQuantum.

---

## 1. Qué se entrega

`GET /export/omf/{project_id}/{run_id}?include_surfaces=true`
→ un `.omf` con hasta cuatro clases de elemento:

| Elemento OMF      | Contenido                                   | De dónde sale                       |
|-------------------|---------------------------------------------|-------------------------------------|
| `VolumeElement`   | Block model, malla regular                  | `block_model.parquet` + `inputs.json` |
| `PointSetElement` | Estaciones: observado, calculado, residual  | `obs_vs_calc.parquet`               |
| `LineSetElement`  | Sondajes: densidad y litología por tramo    | `boreholes.json`                    |
| `SurfaceElement`  | Una por isosuperficie (50 %, 70 %, 90 %)    | `isosurface_service` (al vuelo)     |

En la interfaz: botón **«OMF (Leapfrog / Vulcan)»** en el panel de exportación
del visor 3D.

### Atributos del block model

Se publican **curados por medición de la propia corrida**, no por una lista fija:
se descarta toda columna que sea NaN en todas las celdas o bit a bit idéntica a
otra ya publicada. Con eso quedan fuera, entre otras, `grade` (NaN siempre salvo
en modo demo), `rho`/`density` (copias de `density_t_m3`), `relative_target_score`
(copia de `probability`) y `doi_raw` (copia de `doi_index`).

Publicar un atributo vacío es peor que no publicarlo: en el visor del cliente
parece un dato que se calculó mal.

---

## 2. Las tres decisiones que hacen que el fichero abra bien

### 2.1 Permutación de ejes

El modelo interno **no** es (Este, Norte, Z). Es:

```
x_m = Este     y_m = PROFUNDIDAD (positiva hacia ABAJO)     z_m = Norte
aplanado en orden Fortran:  idx = ix + nx*iy + nx*ny*iz
```

El OMF se escribe en `(u=Este, v=Norte, w=ARRIBA)`:

```
cubo = plano.reshape((nx, ny, nz), order="F")   # (Este, profundidad, Norte)
cubo = transpose(cubo, (0, 2, 1))[:, :, ::-1]   # (Este, Norte, arriba)
salida = cubo.ravel(order="F")
```

Es la misma permutación que `gravity_import_service` aplica al exportar UBC-GIF
desde `load-package`.

### 2.2 Orden de las celdas

La especificación de GMG dice, para el modelo de bloques: **«Ordering increases U
first, then V, then W»** — orden Fortran. TerraQuantum sigue la especificación.

> ⚠️ **`omfvista` discrepa de la especificación.** `volume_to_vtk` hace
> `np.reshape(arr, (nu,nv,nw))` en orden **C** y luego `.flatten(order="F")`, lo
> que equivale a leer W como índice rápido: una transposición. Un fichero
> correcto **se ve transpuesto en ese lector**. No se corrige escribiendo mal a
> propósito. Queda pinchado en `tests/test_fase12_omf.py`
> (`test_defecto_h_f12_2_omfvista_lee_las_celdas_transpuestas`).

### 2.3 Dónde viven las coordenadas absolutas

Medido leyendo los conversores de `omfvista`: para `VolumeGridGeometry` **sí** se
aplica `geometry.origin`, pero para PointSet / LineSet / Surface triangulada
`geometry.origin` **se ignora** (sólo se suma el origen del *proyecto*). Por eso:

- el volumen lleva el desplazamiento absoluto en `geometry.origin`;
- puntos, líneas y superficies lo llevan **horneado en los vértices**;
- `Project.origin` se deja en `(0,0,0)`.

Así los cuatro elementos caen en el mismo sitio con cualquiera de los dos
criterios de lectura.

---

## 3. Lo que NO se inventa

| Situación | Qué hace TerraQuantum |
|---|---|
| El proyecto no declara CRS proyectado, o la corrida no guardó origen absoluto | Exporta en **metros locales**, origen `(0,0,0)`, y lo escribe en la descripción del propio fichero |
| No hay datum vertical (`vertical_datum: null` en todo el repo) | El eje Z es **profundidad bajo la superficie local** (Z=0 en superficie), **no** cota sobre el nivel del mar. Declarado en el fichero |
| El block model no trae `ix/iy/iz` (tabla dispersa de la inversión conjunta) | **422** con el motivo. No se infiere una malla |
| No hay `inputs.json` | **422**. La malla no es reconstruible y no se adivina |
| No hay `obs_vs_calc.parquet` (magnética y joint no lo escriben) | Se omite el elemento de estaciones. No se fabrica un punto |

Para georreferenciar hace falta que coincidan **dos** cosas:
`coordinate_transform.absolute_origin` (easting/northing) en la corrida **y** un
CRS proyectado en `project_meta.json`. Medido en disco: 25 de 105 proyectos
cumplen; el resto sale en local, declarándolo.

---

## 4. Importación

`POST /borehole/import-omf` (multipart) → **el mismo `BoreholeSurvey`** que
produce `/borehole/parse-csv`. El sondaje importado alimenta el anclaje de la
inversión por el camino que ya existía; no hay contrato nuevo para el motor.

En la interfaz: el panel de sondajes acepta `.omf` además de `.csv`.

**Se consume** el `LineSetElement`. Del resto (volúmenes, superficies, nubes de
puntos) se devuelve un **inventario** y se declara que TerraQuantum todavía no
los consume — se listan en la UI, no se fingen importados.

### Lo que el importador se niega a inventar

1. **Sondajes desviados.** El motor sólo representa pozos verticales
   (limitación declarada en `BoreholeInterval`). Un pozo desviado se **descarta y
   se nombra**; aplastarlo a la vertical del collar metería una mentira
   geométrica en un ancla de inversión. Tolerancia por defecto: 1 m.
2. **El origen horizontal.** O lo declara quien llama (`origin_easting`,
   `origin_northing`), o se toma del proyecto destino (`project_id` + `run_id`),
   o se pasan las coordenadas tal cual **con aviso**. Siempre se publica la caja
   envolvente en coordenadas originales, para que se vea si venía en UTM.
3. **El datum vertical.** Sin `surface_z`, la profundidad se mide desde el collar
   de cada pozo, y se avisa. Para un OMF escrito por TerraQuantum: `surface_z=0`.

Con `surface_z=0`, la ida y vuelta TerraQuantum → OMF → TerraQuantum devuelve el
intervalo original **exacto**, litología incluida.

---

## 5. Dependencia

`omf==1.0.1` (MIT), más sus transitivas `properties`, `vectormath`, `pypng`,
pineadas exactas por H-23 (reproducibilidad del instalador firmado): `omf` las
declara sin techo.

Se **descartó** el fork vivo `mira-omf` 3.4.0, mejor mantenido, porque arrastra
`geoh5py`, que es **LGPL-3.0-or-later**, y esto se distribuye como instalador
firmado de un producto que se vende.

**Riesgo asumido y medido:** `omf` 1.0.1 se publicó en 2019 y no tiene
mantenimiento. Funciona hoy en Python 3.14.4 con numpy 2.4.4 (verificado con
round-trip completo de los cuatro tipos de elemento), pero su cadena emite
avisos de deprecación (`datetime.utcnow()`, `__array_wrap__` de numpy 2.0) que
algún día serán errores. El día que rompa hay dos salidas ya exploradas: migrar a
`mira-omf` (aceptando LGPL) o escribir el contenedor a mano — es una cabecera de
60 bytes, arrays comprimidos con zlib y un índice JSON, y está documentado en
§6.

---

## 6. El contenedor, por si hay que reimplementarlo

OMF v1 (`OMF-v0.9.0`), cabecera de 60 bytes:

```
[0:4]    b'\x84\x83\x82\x81'      número mágico
[4:36]   '<32s'                   versión, rellenada con \x00: 'OMF-v0.9.0'
[36:52]  '<16s'                   UID del proyecto (little-endian)
[52:60]  '<Q'                     posición donde empieza el JSON
[60:...] blobs binarios           cada array: zlib(float64 '<f8' o int64 '<i8')
[json:]  UTF-8                    índice de objetos por UID; los arrays se
                                  referencian con {start, dtype, length}
```

`tests/test_fase12_omf.py::test_la_cabecera_cumple_el_formato_documentado`
parsea esto **a mano**, sin usar el lector de `omf`.

---

## 7. Qué está verificado y qué no

**Verificado, con test:**

- Geometría íntegra celda a celda contra el parquet, con un CONTROL que demuestra
  que la comparación sabe distinguir.
- El orden de celdas es el de la especificación, con dato de prueba asimétrico
  (una transposición cambiaría el resultado).
- La cabecera cumple el formato publicado, parseada sin el lector de `omf`.
- Nada se inventa: malla, georreferencia, atributos vacíos, sondajes desviados.
- Ida y vuelta exacta de sondajes.

**NO verificado, y hay que decirlo:** el criterio de aceptación de la fase es
*«abre correctamente en un visor OMF de terceros»*. **Ningún visor de terceros se
ha ejecutado.** No es automatizable en CI y Leapfrog/Vulcan no están disponibles
aquí. Lo que sí puede afirmarse es que el contenedor lo escribe la implementación
de referencia de GMG, así que leerlo con esa misma librería **no** es una
verificación independiente de la serialización; lo que las pruebas verifican de
forma independiente es el **mapeo** de TerraQuantum, que es donde está el riesgo
real de esta fase.

**Pendiente para v1:** abrir un `.omf` generado aquí en un visor real
(`omfvista` con PyVista, o Leapfrog Viewer) y dejar constancia con captura.
